"""
Node 3 — Risk Scorer

PydanticAI agent that synthesises:
  - ContractAnalysis (structured clause extraction from Node 1)
  - Precedents (pgvector similarity results from Node 2)

into a RiskReport with:
  - risk_score: int 0-100
  - risk_factors: cited to specific clause spans
  - recommended_actions: prioritised remediation steps
  - auto_approved / requires_escalation: routing flags

The Logfire span captures: risk_score, factor count, token usage.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import logfire
from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from app.graph.state import ContractState
from app.models.contract import ContractAnalysis
from app.models.risk import RiskReport

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ESCALATION_THRESHOLD = int(os.getenv("ESCALATION_THRESHOLD", "40"))

_SYSTEM_PROMPT = """
You are a legal risk quantification specialist for early-stage B2B SaaS startups.

You will receive:
1. A structured ContractAnalysis (JSON) — the extracted clauses
2. Historical precedent data from a legal database — similar clauses with real outcomes
3. Jurisdiction-specific regulatory flags

Your task is to produce a RiskReport with a calibrated risk_score (0-100).

SCORING CALIBRATION (non-negotiable):
- Uncapped liability clause → minimum score of 70
- Broad indemnification (unlimited scope) → adds 20+ points
- No IP assignment clause in a services contract → adds 15+ points
- Auto-renewal with < 30 days notice period → adds 10+ points
- No governing law specified → adds 10+ points
- GDPR/CCPA non-compliance flags → adds 15+ points

CITATION REQUIREMENT:
Every RiskFactor MUST include clause_excerpt from the actual extracted text.
Every precedent citation MUST reference a real precedent from the provided data.
Do NOT cite clauses or precedents that are not in your input — that is hallucination.

OUTPUT:
- risk_level: low (0-25), moderate (26-50), high (51-75), critical (76-100)
- clause_coverage_score: fraction of clause_list items you evaluated
- model_used: always "{model}"
""".format(model=GROQ_MODEL)

risk_agent = Agent(
    GroqModel(GROQ_MODEL, provider=GroqProvider(api_key=GROQ_API_KEY)),
    output_type=RiskReport,
    system_prompt=_SYSTEM_PROMPT,
)


async def risk_scorer_node(state: ContractState) -> dict:
    """LangGraph node: synthesise analysis + precedents into a structured RiskReport."""
    contract_id = state["contract_id"]
    analysis_dict = state.get("analysis") or {}
    precedents = state.get("precedents") or []

    with logfire.span(
        "risk_scorer",
        contract_id=contract_id,
        precedent_count=len(precedents),
    ):
        # Build a concise context for the LLM
        analysis_summary = _build_analysis_summary(analysis_dict)
        precedent_summary = _build_precedent_summary(precedents)

        prompt = f"""
CONTRACT ANALYSIS (structured extraction):
{analysis_summary}

HISTORICAL PRECEDENTS (from pgvector similarity search):
{precedent_summary}

CONTRACT ID: {contract_id}

Produce a comprehensive RiskReport. Remember:
- Every RiskFactor must cite a real clause from the analysis above
- Every precedent_citation must reference a real precedent from the list above
- risk_score calibration rules apply (uncapped liability → 70+, etc.)
"""

        result = await risk_agent.run(prompt)
        report = result.output

        # Enrich with routing decisions
        score = report.risk_score
        report.auto_approved = score < ESCALATION_THRESHOLD
        report.requires_escalation = score >= ESCALATION_THRESHOLD
        report.analysis_timestamp = datetime.utcnow()

        if report.requires_escalation:
            critical_factors = [f.factor for f in report.risk_factors if f.severity in ("critical", "high")]
            report.escalation_reason = (
                f"Risk score {score}/100 exceeds threshold {ESCALATION_THRESHOLD}. "
                f"Key concerns: {'; '.join(critical_factors[:3])}"
            )

        logfire.info(
            "risk_scoring_complete",
            contract_id=contract_id,
            risk_score=score,
            risk_level=report.risk_level,
            factor_count=len(report.risk_factors),
            requires_escalation=report.requires_escalation,
            clause_coverage=report.clause_coverage_score,
        )

        return {
            "risk_report": report.model_dump(mode="json"),
            "current_node": "risk_scorer",
            "auto_approved": report.auto_approved,
            "requires_escalation": report.requires_escalation,
        }


def _build_analysis_summary(analysis_dict: dict) -> str:
    """Format the ContractAnalysis as concise JSON for the LLM prompt."""
    # Include full analysis but cap precedent-irrelevant fields
    summary = {
        "contract_type": analysis_dict.get("contract_type"),
        "jurisdiction": analysis_dict.get("jurisdiction"),
        "liability_cap": analysis_dict.get("liability_cap"),
        "ip_assignment": analysis_dict.get("ip_assignment"),
        "auto_renewal": analysis_dict.get("auto_renewal"),
        "indemnification": analysis_dict.get("indemnification"),
        "termination": analysis_dict.get("termination"),
        "missing_standard_clauses": analysis_dict.get("missing_standard_clauses", []),
        "clause_list": analysis_dict.get("clause_list", [])[:20],  # Cap to avoid token overflow
        "extraction_confidence": analysis_dict.get("extraction_confidence"),
    }
    return json.dumps(summary, indent=2)


def _build_precedent_summary(precedents: list[dict]) -> str:
    """Format precedents as a numbered list for easy LLM citation."""
    if not precedents:
        return "No historical precedents found in database."

    lines = []
    for i, p in enumerate(precedents[:15], 1):  # Cap at 15 precedents
        clause_type = p.get("clause_type", "unknown")
        outcome = p.get("outcome", "outcome unknown")
        risk_label = p.get("risk_label", "unknown")
        similarity = p.get("similarity_score", 0.0)
        source_clause = p.get("source_clause_name", "")
        lines.append(
            f"[P{i}] Clause Type: {clause_type} | Risk: {risk_label} | "
            f"Similarity: {similarity:.2f} | Outcome: {outcome} | "
            f"Related to: {source_clause}"
        )

    return "\n".join(lines)


async def auto_approve_node(state: ContractState) -> dict:
    """Terminal node for low-risk contracts. Updates status and logs."""
    contract_id = state["contract_id"]
    score = (state.get("risk_report") or {}).get("risk_score", 0)

    logfire.info(
        "contract_auto_approved",
        contract_id=contract_id,
        risk_score=score,
    )
    return {"current_node": "auto_approve", "auto_approved": True}


async def escalate_node(state: ContractState) -> dict:
    """
    Terminal node for high-risk contracts.

    This node is declared in interrupt_before=["escalate"] in graph.py.
    The graph PAUSES before executing this node and waits for human input
    via POST /contracts/{id}/resume. Once resumed, this node runs and
    records the escalation decision.
    """
    contract_id = state["contract_id"]
    score = (state.get("risk_report") or {}).get("risk_score", 0)

    logfire.info(
        "contract_escalated_for_human_review",
        contract_id=contract_id,
        risk_score=score,
        escalation_reason=state.get("risk_report", {}).get("escalation_reason"),
    )
    return {"current_node": "escalate", "requires_escalation": True}
