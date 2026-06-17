"""
Pydantic v2 models for risk scoring output.

RiskReport is the final deliverable — structured, cited, and actionable.
Every RiskFactor must cite back to a specific clause span so the frontend
can highlight the exact text. Precedent citations link to historical outcomes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class PrecedentCitation(BaseModel):
    """Reference to a historical clause precedent from the pgvector database."""
    clause_type: str
    outcome: str = Field(description="Real-world outcome of this clause pattern")
    similarity_score: float = Field(ge=0.0, le=1.0)
    jurisdiction: str | None = None


class RiskFactor(BaseModel):
    """
    A single identified risk with full citation chain.

    Hiring managers should see: clause_ref → span → precedent_citation
    This traceability chain is what separates production analysis from a chatbot.
    """
    factor: str = Field(description="Human-readable risk description")
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description="Risk severity level"
    )
    clause_name: str = Field(description="Name of the clause this risk originates from")
    clause_span_start: int | None = Field(
        default=None,
        description="Start character offset in original text for frontend highlighting"
    )
    clause_span_end: int | None = Field(
        default=None,
        description="End character offset in original text for frontend highlighting"
    )
    clause_excerpt: str = Field(description="The specific clause text triggering this risk")
    precedent_citation: PrecedentCitation | None = Field(
        default=None,
        description="Historical precedent from pgvector similarity search"
    )
    financial_exposure: str | None = Field(
        default=None,
        description="Estimated financial exposure if risk materialises (e.g. 'uncapped', '$2M+')"
    )


class RecommendedAction(BaseModel):
    """Structured remediation recommendation."""
    action: str = Field(description="Specific action to take (imperative, e.g. 'Negotiate a liability cap')")
    priority: Literal["immediate", "before_signing", "nice_to_have"] = Field(
        description="Timeline priority"
    )
    target_clause: str = Field(description="Which clause this action applies to")
    suggested_language: str | None = Field(
        default=None,
        description="Suggested contract language to propose"
    )


class RiskReport(BaseModel):
    """
    Final risk analysis output for a contract.

    risk_score < 40:  Auto-approved by LangGraph router
    risk_score >= 40: Graph pauses at interrupt_before=["escalate"] for human review
    """
    contract_id: str
    risk_score: int = Field(
        ge=0,
        le=100,
        description="Composite risk score. 0=no risk, 100=catastrophic. "
                    "Calibrated so uncapped liability alone pushes above 70."
    )
    risk_level: Literal["low", "moderate", "high", "critical"] = Field(
        description="Human-readable tier derived from risk_score"
    )
    risk_factors: list[RiskFactor] = Field(
        description="All identified risk factors with citations"
    )
    recommended_actions: list[RecommendedAction] = Field(
        description="Prioritised remediation actions"
    )

    # Routing decisions
    auto_approved: bool = Field(
        default=False,
        description="True if risk_score < ESCALATION_THRESHOLD and auto-approved"
    )
    requires_escalation: bool = Field(
        default=False,
        description="True if risk_score >= ESCALATION_THRESHOLD — triggers graph interrupt"
    )
    escalation_reason: str | None = Field(
        default=None,
        description="Human-readable escalation reason shown in dashboard banner"
    )

    # Coverage metrics (used by eval hallucination checker)
    clause_coverage_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of clauses in clause_list that were evaluated for risk"
    )
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = Field(description="Gemini model version that produced this report")

    @property
    def critical_factors(self) -> list[RiskFactor]:
        return [f for f in self.risk_factors if f.severity == "critical"]

    @property
    def high_factors(self) -> list[RiskFactor]:
        return [f for f in self.risk_factors if f.severity == "high"]
