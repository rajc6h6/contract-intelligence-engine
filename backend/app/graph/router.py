"""
Conditional router for the LangGraph contract analysis pipeline.

Routes from risk_scorer output to either:
  - 'auto_approve' → risk_score < ESCALATION_THRESHOLD (default: 40)
  - 'escalate'     → risk_score >= ESCALATION_THRESHOLD
                     → graph pauses at interrupt_before=["escalate"]
                     → human reviews via POST /contracts/{id}/resume

The 'escalate' node being in interrupt_before is the human-in-the-loop
pattern. The graph state is durably checkpointed in PostgreSQL before
the interrupt, so the human reviewer gets a fully materialised RiskReport.
"""

from __future__ import annotations

import os
from app.graph.state import ContractState

ESCALATION_THRESHOLD = int(os.getenv("ESCALATION_THRESHOLD", "40"))


def route_by_score(state: ContractState) -> str:
    """
    Determine routing after risk_scorer node completes.

    Returns the name of the next node to execute.
    LangGraph uses this return value to resolve the conditional edge.
    """
    risk_report = state.get("risk_report")
    if not risk_report:
        # Should not happen; fail loudly so Logfire captures it
        raise ValueError(
            f"route_by_score called but risk_report is missing for contract {state.get('contract_id')}"
        )

    score = risk_report.get("risk_score", 100)

    if score < ESCALATION_THRESHOLD:
        return "auto_approve"
    return "escalate"
