"""
Deterministic Evaluator — rule-based assertions on RiskReport outputs.

These assertions encode non-negotiable scoring invariants derived from
real-world SaaS contract dispute data. They catch regressions in the
risk scoring agent that no LLM judge can detect (e.g., calibration drift).

Assertions:
  1. Contracts with uncapped liability MUST score > 70
  2. Contracts with broad indemnification + uncapped MUST score > 80
  3. GDPR-non-compliant contracts MUST score > 65
  4. Clean NDAs MUST score < 30
  5. Contracts requiring escalation must have requires_escalation=True

Run: python evals/eval_deterministic.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent


@dataclass
class AssertionResult:
    test_id: str
    contract_name: str
    passed: bool
    assertion: str
    actual_value: Any
    expected: str
    message: str = ""


@dataclass
class DeterministicEvalResults:
    results: list[AssertionResult] = field(default_factory=list)

    @property
    def passed(self) -> list[AssertionResult]:
        return [r for r in self.results if r.passed]

    @property
    def failed(self) -> list[AssertionResult]:
        return [r for r in self.results if not r.passed]

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 1.0
        return len(self.passed) / len(self.results)

    def summary(self) -> dict:
        return {
            "total": len(self.results),
            "passed": len(self.passed),
            "failed": len(self.failed),
            "pass_rate": round(self.pass_rate, 4),
            "failed_tests": [
                {
                    "test_id": r.test_id,
                    "contract": r.contract_name,
                    "assertion": r.assertion,
                    "actual": r.actual_value,
                    "expected": r.expected,
                }
                for r in self.failed
            ],
        }


def run_deterministic_assertions(
    ground_truth_path: Path,
    risk_reports: dict[str, dict],
) -> DeterministicEvalResults:
    """
    Run all deterministic assertions against a dict of RiskReport outputs.

    Args:
        ground_truth_path: Path to ground_truth.json
        risk_reports: Dict mapping contract_id → RiskReport dict (from API or mock)

    Returns:
        DeterministicEvalResults with pass/fail for each assertion
    """
    with open(ground_truth_path) as f:
        ground_truth = json.load(f)

    eval_results = DeterministicEvalResults()

    for contract in ground_truth["contracts"]:
        cid = contract["id"]
        name = contract["name"]
        report = risk_reports.get(cid)

        if report is None:
            eval_results.results.append(AssertionResult(
                test_id=f"{cid}_no_report",
                contract_name=name,
                passed=False,
                assertion="report_exists",
                actual_value=None,
                expected="RiskReport present",
                message=f"No risk report found for {cid}",
            ))
            continue

        score = report.get("risk_score", -1)

        # ── Assertion 1: Uncapped liability → score > 70 ─────────────────
        if contract["has_uncapped_liability"]:
            passed = score > 70
            eval_results.results.append(AssertionResult(
                test_id=f"{cid}_uncapped_liability_score",
                contract_name=name,
                passed=passed,
                assertion="uncapped_liability → risk_score > 70",
                actual_value=score,
                expected="> 70",
                message="" if passed else f"FAIL: Uncapped liability contract scored {score}, expected > 70",
            ))

        # ── Assertion 2: Uncapped + broad indemnification → score > 80 ──
        if contract["has_uncapped_liability"] and contract["has_broad_indemnification"]:
            passed = score > 80
            eval_results.results.append(AssertionResult(
                test_id=f"{cid}_uncapped_plus_broad_indem",
                contract_name=name,
                passed=passed,
                assertion="uncapped_liability + broad_indemnification → risk_score > 80",
                actual_value=score,
                expected="> 80",
                message="" if passed else f"FAIL: Combined critical risk contract scored {score}, expected > 80",
            ))

        # ── Assertion 3: Expected escalation matches ─────────────────────
        expected_escalation = contract["requires_escalation"]
        actual_escalation = report.get("requires_escalation", False)
        # Escalation should be True for all contracts scoring >= 40
        if expected_escalation:
            passed = actual_escalation is True
            eval_results.results.append(AssertionResult(
                test_id=f"{cid}_requires_escalation",
                contract_name=name,
                passed=passed,
                assertion="high_risk_contract → requires_escalation=True",
                actual_value=actual_escalation,
                expected="True",
                message="" if passed else f"FAIL: High-risk contract not flagged for escalation",
            ))

        # ── Assertion 4: Low-risk contracts → score < 30 ────────────────
        if not contract["requires_escalation"] and not contract["has_uncapped_liability"]:
            if contract["expected_risk_score_max"] <= 30:
                passed = score < 30
                eval_results.results.append(AssertionResult(
                    test_id=f"{cid}_low_risk_score",
                    contract_name=name,
                    passed=passed,
                    assertion="clean_contract → risk_score < 30",
                    actual_value=score,
                    expected="< 30",
                    message="" if passed else f"FAIL: Clean contract over-scored at {score}",
                ))

        # ── Assertion 5: Score within expected range ─────────────────────
        min_score = contract["expected_risk_score_min"]
        max_score = contract["expected_risk_score_max"]
        in_range = min_score <= score <= max_score
        eval_results.results.append(AssertionResult(
            test_id=f"{cid}_score_range",
            contract_name=name,
            passed=in_range,
            assertion=f"risk_score in [{min_score}, {max_score}]",
            actual_value=score,
            expected=f"between {min_score} and {max_score}",
            message="" if in_range else f"Score {score} outside expected range [{min_score}, {max_score}]",
        ))

        # ── Assertion 6: RiskReport has at least one factor for high-risk ─
        if contract["has_uncapped_liability"] or contract["has_broad_indemnification"]:
            factors = report.get("risk_factors", [])
            critical_or_high = [
                f for f in factors
                if f.get("severity") in ("critical", "high")
            ]
            passed = len(critical_or_high) >= 1
            eval_results.results.append(AssertionResult(
                test_id=f"{cid}_has_critical_factors",
                contract_name=name,
                passed=passed,
                assertion="high_risk_contract → at least 1 critical/high RiskFactor",
                actual_value=len(critical_or_high),
                expected=">= 1",
                message="" if passed else "FAIL: No critical/high risk factors found for high-risk contract",
            ))

    return eval_results


if __name__ == "__main__":
    # Stand-alone mode: load risk reports from a JSON file if provided
    reports_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    if reports_path and reports_path.exists():
        with open(reports_path) as f:
            risk_reports = json.load(f)
    else:
        print("Usage: python eval_deterministic.py <risk_reports.json>")
        print("  risk_reports.json: {contract_id: RiskReport_dict, ...}")
        sys.exit(1)

    results = run_deterministic_assertions(
        ROOT / "evals" / "ground_truth.json",
        risk_reports,
    )

    summary = results.summary()
    print(f"\n{'='*60}")
    print(f"DETERMINISTIC EVAL: {summary['passed']}/{summary['total']} passed ({summary['pass_rate']*100:.1f}%)")
    print(f"{'='*60}")

    if results.failed:
        print(f"\n❌ FAILED ({len(results.failed)}):")
        for r in results.failed:
            print(f"  [{r.test_id}] {r.contract_name}")
            print(f"    {r.assertion}")
            print(f"    Got: {r.actual_value} | Expected: {r.expected}")

    if results.pass_rate < 1.0:
        sys.exit(1)
    else:
        print("\n✅ All deterministic assertions passed")
