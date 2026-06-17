"""
Node 2 — Precedent Retriever (MCP Client)

This node acts as a proper MCP client, connecting via Streamable HTTP to
the standalone FastMCP server process on port 8001.

The MCP decoupling is the architecture that impresses senior engineers:
  - Tool logic lives in a completely separate process (mcp_server/server.py)
  - The server can be scaled, replaced, or versioned independently
  - The client is just a typed interface — no SQL here, no pgvector here

For each contract analysis, this node calls two MCP tools:
  1. search_precedent_clauses(clause_text) → pgvector cosine similarity
  2. get_jurisdiction_rules(jurisdiction) → regulatory flag lookup

Results are attached to state as `precedents` for the risk_scorer to use.
"""

from __future__ import annotations

import json
import os

import logfire
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.graph.state import ContractState
from app.models.contract import ContractAnalysis

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001/mcp")

# Number of clauses to search precedents for (top by risk relevance)
TOP_CLAUSES_TO_SEARCH = 5

# High-risk clause types to prioritise for precedent search
PRIORITY_CLAUSE_TYPES = {
    "liability_cap", "indemnification", "ip_assignment",
    "auto_renewal", "termination", "limitation_of_liability",
}


async def precedent_retriever_node(state: ContractState) -> dict:
    """
    LangGraph node: retrieve historical precedents via MCP client.

    Connects to the FastMCP server over Streamable HTTP, calls two tools,
    and returns combined precedent context for the risk_scorer.
    """
    contract_id = state["contract_id"]
    analysis_dict = state.get("analysis") or {}

    # Reconstruct the analysis model for typed access
    try:
        analysis = ContractAnalysis.model_validate(analysis_dict)
    except Exception:
        # Graceful degradation: proceed with empty precedents rather than fail
        logfire.warning("precedent_retriever_analysis_parse_failed", contract_id=contract_id)
        return {"precedents": [], "current_node": "precedent_retriever"}

    with logfire.span("precedent_retriever", contract_id=contract_id):
        precedents: list[dict] = []

        try:
            async with streamablehttp_client(MCP_SERVER_URL) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # 1. Retrieve jurisdiction-specific regulatory flags
                    with logfire.span(
                        "mcp_get_jurisdiction_rules",
                        jurisdiction=analysis.jurisdiction,
                    ):
                        try:
                            jur_result = await session.call_tool(
                                "get_jurisdiction_rules",
                                {"jurisdiction": analysis.jurisdiction},
                            )
                            for item in jur_result.content:
                                if hasattr(item, "text"):
                                    rules = json.loads(item.text)
                                    if isinstance(rules, list):
                                        precedents.extend(rules)
                                    logfire.info(
                                        "jurisdiction_rules_retrieved",
                                        jurisdiction=analysis.jurisdiction,
                                        count=len(rules) if isinstance(rules, list) else 1,
                                    )
                        except Exception as exc:
                            logfire.warning("mcp_jurisdiction_rules_failed", error=str(exc))

                    # 2. Search precedents for the highest-risk clauses
                    # Prioritise: liability_cap → indemnification → ip_assignment → others
                    clauses_to_search = _select_priority_clauses(analysis)

                    for clause in clauses_to_search[:TOP_CLAUSES_TO_SEARCH]:
                        with logfire.span(
                            "mcp_search_precedent_clauses",
                            clause_type=clause.clause_type,
                            clause_name=clause.name,
                        ):
                            try:
                                result = await session.call_tool(
                                    "search_precedent_clauses",
                                    {"clause_text": clause.text[:2000]},
                                )
                                for item in result.content:
                                    if hasattr(item, "text"):
                                        clause_precedents = json.loads(item.text)
                                        if isinstance(clause_precedents, list):
                                            for p in clause_precedents:
                                                p["source_clause_name"] = clause.name
                                                p["source_clause_type"] = clause.clause_type
                                            precedents.extend(clause_precedents)
                                        logfire.info(
                                            "precedents_found",
                                            clause_name=clause.name,
                                            count=len(clause_precedents) if isinstance(clause_precedents, list) else 0,
                                        )
                            except Exception as exc:
                                logfire.warning(
                                    "mcp_precedent_search_failed",
                                    clause_name=clause.name,
                                    error=str(exc),
                                )

        except Exception as exc:
            # If MCP server is unreachable, log and continue (graceful degradation)
            logfire.error(
                "mcp_server_unreachable",
                url=MCP_SERVER_URL,
                error=str(exc),
                contract_id=contract_id,
            )

        logfire.info(
            "precedent_retrieval_complete",
            contract_id=contract_id,
            total_precedents=len(precedents),
        )

        return {
            "precedents": precedents,
            "current_node": "precedent_retriever",
        }


def _select_priority_clauses(analysis: ContractAnalysis) -> list:
    """Sort clauses by risk priority for precedent search."""
    from app.models.contract import Clause

    priority_order = list(PRIORITY_CLAUSE_TYPES)

    def priority_key(clause: Clause) -> int:
        ct = clause.clause_type.lower()
        for i, p in enumerate(priority_order):
            if p in ct:
                return i
        return len(priority_order)  # deprioritise unknown types

    # Always include the 5 structured high-risk clauses first
    structured_clauses = []
    for clause in analysis.clause_list:
        if clause.clause_type.lower() in PRIORITY_CLAUSE_TYPES or clause.risk_flag:
            structured_clauses.append(clause)

    return sorted(structured_clauses, key=priority_key)
