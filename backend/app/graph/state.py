"""
LangGraph TypedDict state for the contract analysis pipeline.

Every field is preserved across node transitions and persisted to
PostgreSQL via AsyncPostgresSaver after each node completes.
If the server crashes, the graph resumes from the last persisted state.
"""

from __future__ import annotations

from typing import TypedDict, Any


class ContractState(TypedDict, total=False):
    """
    Shared state flowing through all LangGraph nodes.

    Fields are populated progressively:
      START  → clause_extractor sets: analysis
      clause_extractor → precedent_retriever sets: precedents
      precedent_retriever → risk_scorer sets: risk_report
      risk_scorer → router → [auto_approve | escalate]
    """
    # Input (set at graph invocation)
    contract_id: str
    raw_text: str

    # Node 1 output: PydanticAI clause extraction
    analysis: dict[str, Any] | None          # ContractAnalysis.model_dump()

    # Node 2 output: MCP precedent retrieval
    precedents: list[dict[str, Any]] | None  # List of precedent records

    # Node 3 output: PydanticAI risk scoring
    risk_report: dict[str, Any] | None       # RiskReport.model_dump()

    # Routing / status
    current_node: str                         # For SSE progress streaming
    auto_approved: bool
    requires_escalation: bool

    # Error tracking for retry-on-ValidationError loop
    error_log: list[str]
    retry_count: int
