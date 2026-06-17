"""
Logfire observability setup.

Instruments FastAPI, PydanticAI, and asyncpg to produce a single distributed
trace per contract analysis showing:
  FastAPI request → LangGraph orchestration → PydanticAI agent spans
  (with token counts) → pgvector query span (with similarity score)

If LOGFIRE_TOKEN is not set, traces are emitted to console via OTEL stdout.
"""

from __future__ import annotations

import os
import logfire


def configure_observability() -> None:
    """
    Call once at application startup before any other instrumentation.

    The resulting traces appear in the Logfire dashboard at:
    https://logfire.pydantic.dev/<your-project>
    """
    token = os.getenv("LOGFIRE_TOKEN")

    logfire.configure(
        service_name="contract-intelligence-engine",
        service_version="0.1.0",
        # If no token → console exporter only (development mode)
        send_to_logfire=bool(token),
        token=token or None,
    )

    # Instrument asyncpg — captures pgvector query latency + similarity scores
    logfire.instrument_asyncpg()

    # PydanticAI instrumentation — captures token input/output counts + latency
    # per agent run; pairs with each LangGraph node span automatically
    logfire.instrument_pydantic_ai()


def get_logfire():
    """Return the configured logfire module for use in span context managers."""
    return logfire
