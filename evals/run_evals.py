"""
Eval runner — orchestrates both deterministic and LLM-judge evaluations.

Steps:
  1. For each contract in ground_truth.json, call the live API to get a RiskReport
  2. Run deterministic assertions (zero API calls, instant)
  3. Run LLM-as-judge scoring (Gemini, rate-limited)
  4. Write combined results to evals/results.json
  5. Exit non-zero if any gate fails (used by GitHub Actions)

Usage:
  python evals/run_evals.py                        # Full eval, live API
  python evals/run_evals.py --mock                 # Use precomputed reports (no API)
  python evals/run_evals.py --sample 10            # Evaluate 10 contracts (faster)
  python evals/run_evals.py --output results.json  # Custom output path

Environment:
  BACKEND_URL=http://localhost:8000  (default)
  GEMINI_API_KEY=...                 (required for LLM judge)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
EVALS_DIR = ROOT / "evals"

load_dotenv(ROOT / "backend" / ".env")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


async def _get_report_from_api(
    client: httpx.AsyncClient,
    contract: dict,
    timeout: float = 180.0,
) -> dict | None:
    """
    Submit a contract to the live API and poll until analysis is complete.
    Returns the RiskReport dict or None if failed/timed out.
    """
    cid = contract["id"]
    try:
        # Submit the contract
        resp = await client.post(
            f"{BACKEND_URL}/contracts/text",
            json={
                "contract_text": contract["contract_text"],
                "filename": f"eval_{cid}.txt",
            },
            timeout=30,
        )
        resp.raise_for_status()
        api_cid = resp.json()["contract_id"]

        # Poll for completion
        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(5)
            status_resp = await client.get(f"{BACKEND_URL}/contracts/{api_cid}", timeout=15)
            status_resp.raise_for_status()
            data = status_resp.json()

            if data["status"] in ("completed", "escalated"):
                report = data.get("risk_report")
                if report:
                    report["contract_id"] = cid  # Map back to eval ID
                return report
            elif data["status"] == "failed":
                print(f"    API returned failed status for {cid}: {data.get('error_message')}")
                return None

        print(f"    Timeout waiting for {cid}")
        return None

    except Exception as exc:
        print(f"    API error for {cid}: {exc}")
        return None


async def collect_reports_from_api(
    contracts: list[dict],
    sample_size: int | None = None,
) -> dict[str, dict]:
    """Run all contracts through the live API and collect reports."""
    if sample_size:
        contracts = contracts[:sample_size]

    reports: dict[str, dict] = {}
    async with httpx.AsyncClient(base_url=BACKEND_URL) as client:
        # Verify backend is alive
        try:
            health = await client.get("/health", timeout=10)
            health.raise_for_status()
            print(f"✓ Backend at {BACKEND_URL} is healthy")
        except Exception:
            print(f"❌ Cannot reach backend at {BACKEND_URL}")
            print("   Start it with: docker-compose up backend")
            sys.exit(1)

        for i, contract in enumerate(contracts):
            cid = contract["id"]
            print(f"  [{i+1}/{len(contracts)}] Submitting {cid}: {contract['name']}...", end=" ", flush=True)
            report = await _get_report_from_api(client, contract)
            if report:
                reports[cid] = report
                score = report.get("risk_score", "?")
                print(f"score={score}")
            else:
                print("FAILED")

    return reports


def load_mock_reports(mock_path: Path) -> dict[str, dict]:
    """Load pre-computed reports from a JSON file."""
    if not mock_path.exists():
        print(f"❌ Mock reports file not found: {mock_path}")
        sys.exit(1)
    with open(mock_path) as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Contract Intelligence Engine Eval Runner")
    parser.add_argument("--mock", metavar="PATH", help="Use pre-computed reports from JSON file")
    parser.add_argument("--sample", type=int, help="Evaluate only N contracts")
    parser.add_argument("--output", default=str(EVALS_DIR / "results.json"), help="Output path for results")
    parser.add_argument("--skip-llm-judge", action="store_true", help="Skip LLM-as-judge (faster)")
    args = parser.parse_args()

    with open(EVALS_DIR / "ground_truth.json") as f:
        ground_truth = json.load(f)
    contracts = ground_truth["contracts"]

    print("=" * 60)
    print("Contract Intelligence Engine — Eval Runner")
    print("=" * 60)
    print(f"Contracts in dataset: {len(contracts)}")
    if args.sample:
        print(f"Sample size: {args.sample}")

    # ── Step 1: Collect risk reports ────────────────────────────────────────
    if args.mock:
        print("\n📋 Loading pre-computed reports from mock file...")
        risk_reports = load_mock_reports(Path(args.mock))
    else:
        print("\n🚀 Submitting contracts to live API...")
        risk_reports = asyncio.run(collect_reports_from_api(contracts, args.sample))

    print(f"\n✓ Collected {len(risk_reports)}/{len(contracts)} reports")

    # Save reports for re-use
    reports_path = EVALS_DIR / "collected_reports.json"
    with open(reports_path, "w") as f:
        json.dump(risk_reports, f, indent=2, default=str)
    print(f"✓ Reports saved to {reports_path}")

    # ── Step 2: Deterministic assertions ────────────────────────────────────
    print("\n🔢 Running deterministic assertions...")
    from evals.eval_deterministic import run_deterministic_assertions
    det_results = run_deterministic_assertions(
        EVALS_DIR / "ground_truth.json",
        risk_reports,
    )
    det_summary = det_results.summary()
    print(f"   {det_summary['passed']}/{det_summary['total']} passed ({det_summary['pass_rate']*100:.1f}%)")

    # ── Step 3: LLM-as-judge ────────────────────────────────────────────────
    llm_summary: dict = {}
    if not args.skip_llm_judge:
        print("\n🤖 Running LLM-as-judge (Gemini 2.0 Flash)...")
        from evals.eval_llm_judge import run_llm_judge
        llm_results = run_llm_judge(
            EVALS_DIR / "ground_truth.json",
            risk_reports,
            sample_size=args.sample,
        )
        llm_summary = llm_results.summary()
    else:
        print("\n⏭  LLM judge skipped (--skip-llm-judge)")

    # ── Step 4: Write combined results ───────────────────────────────────────
    combined = {
        "deterministic": det_summary,
        "llm_judge": llm_summary,
        # Top-level fields that CI gate checks
        "hallucination_rate": llm_summary.get("hallucination_rate", 0.0),
        "deterministic_pass_rate": det_summary["pass_rate"],
        "passes_ci_gate": (
            det_summary["pass_rate"] >= 1.0
            and llm_summary.get("passes_ci_gate", True)
        ),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\n✓ Results written to {output_path}")

    # ── Step 5: Final verdict ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("FINAL VERDICT")
    print(f"{'='*60}")
    print(f"  Deterministic pass rate : {det_summary['pass_rate']*100:.1f}%")
    if llm_summary:
        print(f"  Clause coverage         : {llm_summary.get('avg_clause_coverage', 0)*100:.1f}%")
        print(f"  Hallucination rate      : {llm_summary.get('hallucination_rate', 0)*100:.1f}% (limit: 5%)")
        print(f"  CI gate                 : {'✅ PASS' if combined['passes_ci_gate'] else '❌ FAIL'}")

    if not combined["passes_ci_gate"]:
        print("\n❌ EVAL FAILED — merge blocked")
        sys.exit(1)
    else:
        print("\n✅ All eval gates passed")


if __name__ == "__main__":
    main()
