"""
Node 1 — Clause Extractor

PydanticAI agent that receives raw contract text and must produce a strictly-typed
ContractAnalysis. If the LLM output fails Pydantic validation, we retry up to
MAX_EXTRACTION_RETRIES times with increasing specificity in the prompt.

Each attempt creates a Logfire span with:
  - attempt number
  - token input/output counts (instrumented by logfire.instrument_pydantic_ai())
  - ValidationError details if any

This retry-on-validation loop is a key signal: it shows that the system
treats LLM outputs as untrusted inputs that must conform to a typed schema.
"""

from __future__ import annotations

import asyncio
import os
import re
import logfire
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from app.graph.state import ContractState
from app.models.contract import ContractAnalysis

MAX_RETRIES = int(os.getenv("MAX_EXTRACTION_RETRIES", "3"))
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

_SYSTEM_PROMPT = """
You are a senior legal analyst specialising in B2B SaaS contracts.
Your task is to perform a comprehensive structured extraction of all clauses
from the provided contract text.

CRITICAL RULES:
1. Extract ONLY what is actually present in the text. Do NOT invent clauses.
2. Preserve exact character offsets for every ClauseSpan you populate — these
   are used to highlight text in the frontend. Count from the start of the
   raw_text input.
3. If a required high-risk clause (liability_cap, ip_assignment, auto_renewal,
   indemnification, termination) is genuinely absent, mark it accordingly
   (e.g., capped=False, auto_renews=False) and add the clause type to
   missing_standard_clauses.
4. extraction_confidence should honestly reflect your certainty (0.0-1.0).
5. clause_list must contain AT LEAST the 5 structured clauses above, plus any
   other named clauses you find (payment, dispute resolution, SLA, etc.).
6. For contract_id, use the value from the [CONTRACT_ID: ...] marker in the input.
"""

_RETRY_HINTS = [
    "",  # attempt 0: no extra hint
    "\n\nIMPORTANT: Ensure every ClauseSpan has start < end and both are valid character offsets.",
    "\n\nIMPORTANT: extraction_confidence must be between 0.0 and 1.0. "
    "clause_list must have at least 1 item. All required fields must be present.",
]

clause_agent = Agent(
    GroqModel(GROQ_MODEL, provider=GroqProvider(api_key=GROQ_API_KEY)),
    output_type=ContractAnalysis,
    system_prompt=_SYSTEM_PROMPT,
)


def _extract_retry_delay(exc: Exception) -> float | None:
    """Parse the retryDelay seconds from a Gemini 429 error message."""
    msg = str(exc)
    # Matches patterns like "Please retry in 45.5s" or "retryDelay: 45s"
    m = re.search(r'retry[^\d]*(\d+\.?\d*)', msg, re.IGNORECASE)
    if m:
        return min(float(m.group(1)) + 2, 120)  # cap at 2 min
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True if the exception is a 429 quota/rate-limit error."""
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


async def clause_extractor_node(state: ContractState) -> dict:
    """
    LangGraph node: extract structured clauses from raw contract text.

    Retries up to MAX_RETRIES times on ValidationError, logging each failure
    to Logfire. After MAX_RETRIES failures, raises and the graph transitions
    to a failed state.
    """
    contract_id = state["contract_id"]
    raw_text = state["raw_text"]
    error_log: list[str] = list(state.get("error_log", []))
    retry_count: int = state.get("retry_count", 0)

    with logfire.span(
        "clause_extractor",
        contract_id=contract_id,
        retry_count=retry_count,
        text_length=len(raw_text),
    ):
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            hint = _RETRY_HINTS[min(attempt, len(_RETRY_HINTS) - 1)]
            prompt = (
                f"[CONTRACT_ID: {contract_id}]\n\n"
                f"{raw_text[:15000]}"  # Gemini free-tier context limit buffer
                f"{hint}"
            )

            with logfire.span("clause_extraction_attempt", attempt=attempt):
                try:
                    result = await clause_agent.run(prompt)
                    analysis = result.output

                    logfire.info(
                        "clause_extraction_success",
                        contract_id=contract_id,
                        attempt=attempt,
                        clause_count=len(analysis.clause_list),
                        confidence=analysis.extraction_confidence,
                        missing_clauses=analysis.missing_standard_clauses,
                    )

                    return {
                        "analysis": analysis.model_dump(mode="json"),
                        "current_node": "clause_extractor",
                        "retry_count": attempt,
                    }

                except ValidationError as exc:
                    last_error = exc
                    error_msg = f"Attempt {attempt + 1}/{MAX_RETRIES}: ValidationError — {exc.error_count()} errors"
                    error_log.append(error_msg)

                    logfire.warning(
                        "clause_extraction_validation_error",
                        contract_id=contract_id,
                        attempt=attempt,
                        error_count=exc.error_count(),
                        errors=exc.errors(include_url=False),
                    )

                except Exception as exc:
                    last_error = exc
                    error_msg = f"Attempt {attempt + 1}/{MAX_RETRIES}: Unexpected error — {exc!s}"
                    error_log.append(error_msg)

                    if _is_rate_limit_error(exc):
                        wait = _extract_retry_delay(exc) or (30 * (attempt + 1))
                        logfire.warning(
                            "clause_extraction_rate_limited",
                            contract_id=contract_id,
                            attempt=attempt,
                            wait_seconds=wait,
                            error=str(exc),
                        )
                        await asyncio.sleep(wait)
                    else:
                        logfire.error(
                            "clause_extraction_unexpected_error",
                            contract_id=contract_id,
                            attempt=attempt,
                            error=str(exc),
                        )

        logfire.error(
            "clause_extraction_all_retries_exhausted",
            contract_id=contract_id,
            total_attempts=MAX_RETRIES,
        )
        raise RuntimeError(
            f"Clause extraction failed after {MAX_RETRIES} attempts for {contract_id}: {last_error}"
        ) from last_error
