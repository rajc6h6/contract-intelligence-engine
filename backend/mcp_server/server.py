"""
FastMCP Server — Standalone MCP tool server for legal precedent retrieval.

Runs as a SEPARATE PROCESS on port 8001 (independent from FastAPI on 8000).
The LangGraph precedent_retriever node connects to this via Streamable HTTP.

Why this architecture matters:
  - Tool logic is completely decoupled from the agent orchestrator
  - This server can be scaled, versioned, or swapped independently
  - Senior engineers recognise this as proper MCP server design, not a monolith

Tools exposed:
  1. search_precedent_clauses(clause_text) — pgvector cosine similarity search
     against 500+ CUAD-sourced historical contract clauses
  2. get_jurisdiction_rules(jurisdiction) — regulatory flag lookup
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

import asyncpg
import logfire
from fastmcp import FastMCP

# ── Configuration ───────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://cie_user:cie_password@localhost:5432/contract_intelligence",
)
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TOP_K_PRECEDENTS = 5

# ── Connection pool (module-level, initialised at startup) ──────────────────

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
    return _pool


# ── Embedding helper (for query-time vectorisation) ─────────────────────────

def _embed_query(text: str) -> list[float]:
    """Embed a clause text for similarity search using text-embedding-004."""
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text[:4000],
        task_type="retrieval_query",  # Query-optimised embedding
    )
    return result["embedding"]


# ── FastMCP Server ──────────────────────────────────────────────────────────

mcp = FastMCP(
    name="contract-precedent-server",
    instructions="""
    Legal contract precedent database with pgvector-powered semantic search.
    Use search_precedent_clauses to find historically similar clauses and their
    real-world outcomes. Use get_jurisdiction_rules to retrieve regulatory flags.
    """,
)


@mcp.tool()
async def search_precedent_clauses(clause_text: str) -> str:
    """
    Search for historically similar contract clauses using pgvector cosine similarity.

    Runs against a database of 500+ real clauses extracted from the CUAD dataset
    (Contract Understanding Atticus Dataset), each embedded with text-embedding-004.

    Args:
        clause_text: The clause text to find similar precedents for.
                     Should be the full clause text, not just the header.

    Returns:
        JSON array of top-5 most similar precedents with outcome labels,
        risk classifications, and cosine similarity scores.
    """
    with logfire.span("mcp_search_precedent_clauses", text_length=len(clause_text)):
        try:
            # Get embedding for the query clause
            embedding = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _embed_query(clause_text)
            )

            pool = await get_pool()
            async with pool.acquire() as conn:
                # pgvector cosine similarity: <=> operator
                # Lower distance = higher similarity; ORDER BY ASC for closest matches
                rows = await conn.fetch(
                    """
                    SELECT
                        clause_type,
                        clause_text,
                        outcome,
                        jurisdiction,
                        risk_label,
                        1 - (embedding <=> $1::vector) AS similarity_score
                    FROM clause_precedents
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                    """,
                    f"[{','.join(str(x) for x in embedding)}]",
                    TOP_K_PRECEDENTS,
                )

            results = [
                {
                    "clause_type": row["clause_type"],
                    "clause_text_preview": row["clause_text"][:300],
                    "outcome": row["outcome"],
                    "jurisdiction": row["jurisdiction"],
                    "risk_label": row["risk_label"],
                    "similarity_score": round(float(row["similarity_score"]), 4),
                }
                for row in rows
            ]

            logfire.info(
                "precedent_search_complete",
                results_count=len(results),
                top_similarity=results[0]["similarity_score"] if results else 0,
            )

            return json.dumps(results)

        except Exception as exc:
            logfire.error("precedent_search_failed", error=str(exc))
            return json.dumps([])


@mcp.tool()
async def get_jurisdiction_rules(jurisdiction: str) -> str:
    """
    Retrieve regulatory flags and compliance rules for a specific jurisdiction.

    Args:
        jurisdiction: Jurisdiction string as extracted from the contract
                      (e.g. 'California, USA', 'England and Wales', 'Not specified')

    Returns:
        JSON array of regulatory rules with severity levels.
    """
    with logfire.span("mcp_get_jurisdiction_rules", jurisdiction=jurisdiction):
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Try exact match first, then fuzzy on jurisdiction prefix
            rows = await conn.fetch(
                """
                SELECT rule_type, description, severity, source
                FROM jurisdiction_rules
                WHERE
                    LOWER(jurisdiction) = LOWER($1)
                    OR LOWER($1) LIKE LOWER(jurisdiction) || '%'
                    OR jurisdiction = 'Not specified'
                ORDER BY
                    CASE WHEN LOWER(jurisdiction) = LOWER($1) THEN 0 ELSE 1 END,
                    severity DESC
                LIMIT 10
                """,
                jurisdiction,
            )

        rules = [
            {
                "rule_type": row["rule_type"],
                "description": row["description"],
                "severity": row["severity"],
                "source": row["source"],
                "jurisdiction": jurisdiction,
            }
            for row in rows
        ]

        logfire.info(
            "jurisdiction_rules_fetched",
            jurisdiction=jurisdiction,
            rules_count=len(rules),
        )

        return json.dumps(rules)


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    # Configure Logfire for the MCP server process
    logfire.configure(
        service_name="contract-mcp-server",
        send_to_logfire=bool(os.getenv("LOGFIRE_TOKEN")),
        token=os.getenv("LOGFIRE_TOKEN"),
    )

    print(f"🔌 FastMCP server starting on http://0.0.0.0:{MCP_PORT}/mcp")
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=MCP_PORT,
        path="/mcp",
        stateless_http=True,  # No session affinity needed — each request is independent
    )
