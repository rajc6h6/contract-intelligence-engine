"""
LLM-as-Judge Evaluator using Gemini 2.0 Flash (free tier).

For each contract in the eval set, passes (contract_text, risk_report) to
Gemini with a structured grading rubric measuring:

  1. clause_coverage (0.0-1.0)
     Fraction of genuinely risky clauses in the contract that were
     identified in the RiskReport. Measures completeness.

  2. hallucination_rate (0.0-1.0)
     Fraction of clause citations in risk_factors that do NOT appear
     in the actual contract text. 0.0 = perfect, 1.0 = complete fabrication.
     CI blocks merge if hallucination_rate > 5% (0.05).

  3. severity_calibration (0.0-1.0)
     Whether the severity labels match expected levels (e.g., uncapped
     liability should be 'critical', not 'low').

The judge returns structured JSON — parsed with Pydantic for type safety.

Run: python evals/eval_llm_judge.py <risk_reports.json>
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import google.generativeai as genai
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent.parent


class JudgeScore(BaseModel):
    """Structured output from the Gemini judge for one contract."""
    contract_id: str
    clause_coverage: float = Field(ge=0.0, le=1.0)
    hallucination_rate: float = Field(ge=0.0, le=1.0)
    severity_calibration: float = Field(ge=0.0, le=1.0)
    reasoning: str
    hallucinated_clauses: list[str] = Field(
        default_factory=list,
        description="List of clause references that do not appear in the contract"
    )
    missed_risks: list[str] = Field(
        default_factory=list,
        description="List of actual risks in the contract not captured in the report"
    )


@dataclass
class LLMJudgeResults:
    scores: list[JudgeScore] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def avg_clause_coverage(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.clause_coverage for s in self.scores) / len(self.scores)

    @property
    def avg_hallucination_rate(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.hallucination_rate for s in self.scores) / len(self.scores)

    @property
    def avg_severity_calibration(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.severity_calibration for s in self.scores) / len(self.scores)

    @property
    def passes_ci_gate(self) -> bool:
        """Returns True if hallucination rate is under the 5% CI threshold."""
        return self.avg_hallucination_rate < 0.05

    def summary(self) -> dict:
        return {
            "contracts_evaluated": len(self.scores),
            "errors": len(self.errors),
            "avg_clause_coverage": round(self.avg_clause_coverage, 4),
            "hallucination_rate": round(self.avg_hallucination_rate, 4),
            "avg_severity_calibration": round(self.avg_severity_calibration, 4),
            "passes_ci_gate": self.passes_ci_gate,
            "ci_threshold": 0.05,
            "worst_hallucinations": [
                {"id": s.contract_id, "rate": s.hallucination_rate, "clauses": s.hallucinated_clauses}
                for s in sorted(self.scores, key=lambda x: x.hallucination_rate, reverse=True)[:5]
                if s.hallucination_rate > 0
            ],
        }


_JUDGE_PROMPT_TEMPLATE = """
You are a senior legal AI evaluation expert. Your job is to evaluate whether an AI-generated risk report accurately and completely analyses a contract.

CONTRACT TEXT:
---
{contract_text}
---

AI-GENERATED RISK REPORT:
---
{risk_report_json}
---

GROUND TRUTH KEY RISKS (from human expert annotation):
{ground_truth_risks}

EVALUATION TASK:
Score the risk report on three dimensions. Be strict and precise.

1. CLAUSE COVERAGE (0.0 to 1.0):
   What fraction of the genuinely risky clauses present in the contract text were identified in the risk report?
   - 1.0 = all risky clauses found
   - 0.0 = no risky clauses found
   Count from the ground truth key risks list above.

2. HALLUCINATION RATE (0.0 to 1.0):
   What fraction of the clause_excerpt citations in risk_factors do NOT match actual text in the contract?
   - 0.0 = all citations are real (no hallucinations)
   - 1.0 = all citations are fabricated
   Check EACH risk_factor.clause_excerpt against the contract text above. If a clause_excerpt cannot be found verbatim or near-verbatim in the contract, it is hallucinated.

3. SEVERITY CALIBRATION (0.0 to 1.0):
   How well do the severity labels (critical/high/medium/low) match the actual danger level?
   - Uncapped liability must be 'critical'
   - Broad indemnification must be 'high' or 'critical'
   - Auto-renewal <30 days notice must be at least 'medium'
   - 1.0 = all severities correctly calibrated
   - 0.0 = all severities wrong

Respond ONLY with a valid JSON object in this exact format:
{{
  "contract_id": "{contract_id}",
  "clause_coverage": <float 0.0-1.0>,
  "hallucination_rate": <float 0.0-1.0>,
  "severity_calibration": <float 0.0-1.0>,
  "reasoning": "<2-3 sentence explanation of your scores>",
  "hallucinated_clauses": ["<clause excerpt that was fabricated>", ...],
  "missed_risks": ["<risk that was present but not identified>", ...]
}}
"""


def _call_gemini_judge(
    contract: dict,
    report: dict,
    model: genai.GenerativeModel,
) -> JudgeScore | None:
    """Call Gemini to judge one contract/report pair."""
    prompt = _JUDGE_PROMPT_TEMPLATE.format(
        contract_text=contract["contract_text"][:6000],
        risk_report_json=json.dumps(report, indent=2)[:4000],
        ground_truth_risks=json.dumps(contract.get("key_risks", []), indent=2),
        contract_id=contract["id"],
    )

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,  # Low temp for consistent grading
                response_mime_type="application/json",
            ),
        )
        raw = response.text.strip()
        data = json.loads(raw)
        return JudgeScore(**data)
    except Exception as exc:
        print(f"  ⚠ Judge failed for {contract['id']}: {exc}")
        return None


def run_llm_judge(
    ground_truth_path: Path,
    risk_reports: dict[str, dict],
    sample_size: int | None = None,
) -> LLMJudgeResults:
    """
    Run LLM-as-judge evaluation for all contracts with reports.

    Args:
        ground_truth_path: Path to ground_truth.json
        risk_reports: Dict mapping contract_id → RiskReport dict
        sample_size: If set, only evaluate this many contracts (for speed)

    Returns:
        LLMJudgeResults with per-contract scores and aggregate metrics
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    with open(ground_truth_path) as f:
        ground_truth = json.load(f)

    contracts = ground_truth["contracts"]
    if sample_size:
        contracts = contracts[:sample_size]

    results = LLMJudgeResults()
    evaluated = 0

    print(f"\n🤖 LLM Judge: evaluating {len(contracts)} contracts with Gemini 2.0 Flash...")

    for i, contract in enumerate(contracts):
        cid = contract["id"]
        report = risk_reports.get(cid)

        if report is None:
            results.errors.append(f"No report for {cid}")
            continue

        print(f"  [{i+1}/{len(contracts)}] Judging {cid}: {contract['name']}...", end=" ", flush=True)
        score = _call_gemini_judge(contract, report, model)

        if score:
            results.scores.append(score)
            print(
                f"coverage={score.clause_coverage:.2f} | "
                f"hallucination={score.hallucination_rate:.2f} | "
                f"calibration={score.severity_calibration:.2f}"
            )
            evaluated += 1
        else:
            results.errors.append(f"Judge call failed for {cid}")
            print("FAILED")

        # Rate limit: free tier ~15 RPM for Gemini
        if i < len(contracts) - 1:
            time.sleep(4)

    return results


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")

    if len(sys.argv) < 2:
        print("Usage: python eval_llm_judge.py <risk_reports.json> [--sample N]")
        sys.exit(1)

    reports_path = Path(sys.argv[1])
    sample_size = None
    if "--sample" in sys.argv:
        idx = sys.argv.index("--sample")
        sample_size = int(sys.argv[idx + 1])

    with open(reports_path) as f:
        risk_reports = json.load(f)

    results = run_llm_judge(
        ROOT / "evals" / "ground_truth.json",
        risk_reports,
        sample_size=sample_size,
    )

    summary = results.summary()

    print(f"\n{'='*60}")
    print("LLM JUDGE RESULTS")
    print(f"{'='*60}")
    print(f"  Contracts evaluated : {summary['contracts_evaluated']}")
    print(f"  Avg clause coverage : {summary['avg_clause_coverage']:.1%}")
    print(f"  Hallucination rate  : {summary['hallucination_rate']:.1%} (threshold: 5%)")
    print(f"  Severity calibration: {summary['avg_severity_calibration']:.1%}")
    print(f"  CI gate             : {'✅ PASS' if summary['passes_ci_gate'] else '❌ FAIL'}")

    if not summary["passes_ci_gate"]:
        print(f"\n❌ BLOCKING: Hallucination rate {summary['hallucination_rate']:.1%} exceeds 5% threshold")
        sys.exit(1)
    else:
        print("\n✅ Hallucination rate within acceptable threshold")
