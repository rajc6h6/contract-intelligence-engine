"""
LangGraph StateGraph assembly — the heart of the Contract Intelligence Engine.

Graph topology:
  START
    ↓
  clause_extractor   ← PydanticAI agent (retry on ValidationError)
    ↓
  precedent_retriever ← MCP client → FastMCP server → pgvector
    ↓
  risk_scorer        ← PydanticAI agent
    ↓
  [conditional router: route_by_score]
    ├─ score < 40 → auto_approve → END
    └─ score ≥ 40 → escalate     ← interrupt_before pauses here
                       ↓
                    [human resumes via POST /contracts/{id}/resume]
                       ↓
                     END

interrupt_before=["escalate"] is the human-in-the-loop mechanism:
  - Graph persists full state to PostgreSQL checkpointer
  - Dashboard shows "Pending Review" status
  - POST /contracts/{id}/resume calls graph.ainvoke() with existing thread_id
  - Graph resumes from the escalate node with human-provided notes

The compile() call with interrupt_before is only available in LangGraph >= 0.2.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.graph.state import ContractState
from app.graph.router import route_by_score
from app.graph.nodes.clause_extractor import clause_extractor_node
from app.graph.nodes.precedent_retriever import precedent_retriever_node
from app.graph.nodes.risk_scorer import (
    risk_scorer_node,
    auto_approve_node,
    escalate_node,
)


def build_graph(checkpointer: AsyncPostgresSaver):
    """
    Construct and compile the LangGraph StateGraph.

    Called once at FastAPI startup. The compiled graph is reused across
    all requests — each analysis gets its own thread_id for state isolation.

    Args:
        checkpointer: AsyncPostgresSaver backed by PostgreSQL. Provides
                      durable mid-execution checkpointing: if the server
                      crashes, the analysis resumes from the last node.

    Returns:
        Compiled LangGraph CompiledStateGraph ready for ainvoke() / astream()
    """
    builder = StateGraph(ContractState)

    # ── Register nodes ─────────────────────────────────────────────────────
    builder.add_node("clause_extractor", clause_extractor_node)
    builder.add_node("precedent_retriever", precedent_retriever_node)
    builder.add_node("risk_scorer", risk_scorer_node)
    builder.add_node("auto_approve", auto_approve_node)
    builder.add_node("escalate", escalate_node)

    # ── Define edges ───────────────────────────────────────────────────────
    builder.add_edge(START, "clause_extractor")
    builder.add_edge("clause_extractor", "precedent_retriever")
    builder.add_edge("precedent_retriever", "risk_scorer")

    # Conditional routing after risk_scorer
    builder.add_conditional_edges(
        "risk_scorer",
        route_by_score,
        {
            "auto_approve": "auto_approve",
            "escalate": "escalate",
        },
    )

    builder.add_edge("auto_approve", END)
    builder.add_edge("escalate", END)

    # ── Compile with human-in-the-loop interrupt ───────────────────────────
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["escalate"],
        # interrupt_before pauses the graph BEFORE executing 'escalate',
        # giving the human reviewer a fully materialised RiskReport to evaluate.
    )
