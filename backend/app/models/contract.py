"""
Pydantic v2 models for contract clause extraction.

These are the strictly-typed output schemas that PydanticAI agents must produce.
ValidationError on these models triggers the retry-on-validation loop in the
clause_extractor node — a key reliability signal in the LangGraph pipeline.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class ClauseSpan(BaseModel):
    """Character-level offsets into the raw contract text for citation."""
    start: int = Field(ge=0, description="Start character offset in raw contract text")
    end: int = Field(ge=0, description="End character offset in raw contract text")
    excerpt: str = Field(description="The extracted clause text at this span")

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v: int, info: object) -> int:
        start = getattr(info, "data", {}).get("start", 0)
        if v <= start:
            raise ValueError(f"end ({v}) must be greater than start ({start})")
        return v


class LiabilityCap(BaseModel):
    """Liability cap analysis — the single most financially dangerous clause type."""
    capped: bool = Field(description="True if liability is contractually capped to a finite amount")
    cap_amount: str | None = Field(
        default=None,
        description="Cap amount as written (e.g. '2x annual fees', '$500,000'). None if uncapped."
    )
    cap_type: Literal["fixed", "fee_multiple", "insurance_limit", "uncapped", "unclear"] = Field(
        description="Classification of the cap structure"
    )
    span: ClauseSpan | None = Field(default=None, description="Location in original text")


class IPAssignment(BaseModel):
    """Intellectual property assignment and ownership clause."""
    ip_assigned_to_client: bool = Field(
        description="True if the contract assigns IP created under it to the client/counterparty"
    )
    carve_outs: list[str] = Field(
        default_factory=list,
        description="List of IP carve-outs explicitly retained (e.g. 'pre-existing IP', 'open source')"
    )
    span: ClauseSpan | None = Field(default=None)


class AutoRenewal(BaseModel):
    """Automatic renewal terms — a common trap for SaaS contracts."""
    auto_renews: bool = Field(description="True if the contract auto-renews without explicit opt-out")
    renewal_period: str | None = Field(default=None, description="e.g. '1 year', '30 days'")
    notice_period_days: int | None = Field(
        default=None,
        ge=0,
        description="Days of advance notice required to cancel before auto-renewal"
    )
    span: ClauseSpan | None = Field(default=None)


class IndemnificationClause(BaseModel):
    """Indemnification obligations — scope determines catastrophic risk."""
    mutual: bool = Field(description="True if indemnification obligations are mutual")
    indemnifying_party: str | None = Field(
        default=None,
        description="Which party bears primary indemnification burden"
    )
    scope: Literal["ip_infringement_only", "broad", "unlimited", "narrow", "unclear"] = Field(
        description="Breadth of indemnification obligations"
    )
    span: ClauseSpan | None = Field(default=None)


class TerminationClause(BaseModel):
    """Termination for convenience and cause provisions."""
    termination_for_convenience: bool = Field(
        description="Either party can terminate without cause"
    )
    notice_period_days: int | None = Field(default=None, ge=0)
    termination_fee: str | None = Field(
        default=None,
        description="Early termination fee if applicable"
    )
    span: ClauseSpan | None = Field(default=None)


class Clause(BaseModel):
    """Generic named clause extracted from the contract."""
    name: str = Field(description="Clause name as it appears or its standard legal name")
    clause_type: str = Field(description="Category: e.g. 'payment', 'confidentiality', 'dispute_resolution'")
    text: str = Field(description="Full text of the clause")
    span: ClauseSpan | None = Field(default=None)
    risk_flag: bool = Field(
        default=False,
        description="True if this clause appears non-standard or potentially risky"
    )


class ContractAnalysis(BaseModel):
    """
    Strictly-typed output of the PydanticAI clause extraction agent.

    Every field must be populated from the contract text. If a field is genuinely
    absent from the contract, it should be None. Do NOT hallucinate missing clauses.
    """
    contract_id: str = Field(description="Pass through the contract_id from input")
    jurisdiction: str = Field(
        description="Governing law jurisdiction (e.g. 'Delaware, USA', 'England and Wales'). "
                    "Set to 'Not specified' if absent."
    )
    governing_law: str | None = Field(
        default=None,
        description="Specific governing law clause text"
    )
    contract_type: Literal[
        "saas_subscription", "vendor_agreement", "partnership", "employment",
        "nda", "services_agreement", "license", "other"
    ] = Field(description="Classification of contract type")

    # Structured high-risk clause analyses
    liability_cap: LiabilityCap = Field(description="Liability cap analysis — required")
    ip_assignment: IPAssignment = Field(description="IP assignment analysis — required")
    auto_renewal: AutoRenewal = Field(description="Auto-renewal analysis — required")
    indemnification: IndemnificationClause = Field(description="Indemnification analysis — required")
    termination: TerminationClause = Field(description="Termination analysis — required")

    # All extracted clauses for comprehensive coverage
    clause_list: list[Clause] = Field(
        min_length=1,
        description="Complete list of all named clauses found in the contract"
    )

    # Metadata
    raw_text_length: int = Field(ge=0, description="Character length of the raw input text")
    extraction_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Agent's self-assessed confidence in the extraction (0-1)"
    )
    missing_standard_clauses: list[str] = Field(
        default_factory=list,
        description="Standard clause types expected but not found in this contract"
    )
