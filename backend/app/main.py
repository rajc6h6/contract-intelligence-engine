"""
FastAPI entry point — Contract Intelligence Engine backend.

Endpoints:
  POST /contracts          Upload contract (PDF or JSON text) → start LangGraph run
  GET  /contracts/{id}     Get final RiskReport for a completed analysis
  GET  /contracts/{id}/stream  SSE stream of live node-by-node progress
  POST /contracts/{id}/resume  Resume an escalated (interrupted) graph
  GET  /health             Liveness check

SSE streaming uses an asyncio.Queue per contract_id. The LangGraph graph
streams state updates as each node completes, and the queue fan-outs to
all connected SSE clients (typically just the dashboard browser tab).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import logfire
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from pypdf import PdfReader

from app.db.postgres import get_pool, get_checkpointer, init_db, close_db
from app.graph.graph import build_graph
from app.observability import configure_observability

# ── Observability first ──────────────────────────────────────────────────────
configure_observability()

# ── In-memory SSE queue registry ─────────────────────────────────────────────
# Maps contract_id → list[asyncio.Queue]
# Each connected SSE client gets its own queue.
_sse_queues: dict[str, list[asyncio.Queue]] = {}

# ── Compiled LangGraph (initialised at startup) ───────────────────────────────
_graph = None


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: init DB, build graph. Shutdown: close connections."""
    global _graph

    await init_db()
    checkpointer = await get_checkpointer()
    _graph = build_graph(checkpointer)

    logfire.info("contract_intelligence_engine_started")
    yield

    await close_db()
    logfire.info("contract_intelligence_engine_stopped")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Contract Intelligence Engine",
    description="Autonomous legal-risk analyst for early-stage SaaS contracts",
    version="0.1.0",
    lifespan=lifespan,
)

# Instrument FastAPI — every request gets a Logfire span automatically
logfire.instrument_fastapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ───────────────────────────────────────────────────

class ContractTextRequest(BaseModel):
    contract_text: str
    filename: str | None = None


class AnalysisResponse(BaseModel):
    contract_id: str
    status: str
    message: str


class ResumeRequest(BaseModel):
    reviewer_notes: str | None = None
    approved: bool = True


# ── Helper: extract text from PDF or plain text ────────────────────────────────

async def _extract_text(file: UploadFile | None, contract_text: str | None) -> str:
    if contract_text:
        return contract_text

    if file is None:
        raise HTTPException(status_code=400, detail="Provide either 'file' (PDF) or 'contract_text'")

    content = await file.read()
    if file.filename and file.filename.lower().endswith(".pdf"):
        try:
            import io
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"PDF parsing failed: {exc}") from exc
    else:
        # Assume UTF-8 text
        return content.decode("utf-8", errors="replace")


# ── Helper: push SSE update ───────────────────────────────────────────────────

def _push_update(contract_id: str, data: dict) -> None:
    """Push a state update to all SSE clients watching this contract."""
    queues = _sse_queues.get(contract_id, [])
    for q in queues:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass  # Drop if client is slow


# ── Background task: run the LangGraph graph ─────────────────────────────────

async def _run_analysis(contract_id: str, raw_text: str) -> None:
    """Run the full LangGraph analysis pipeline in the background."""
    pool = await get_pool()

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE contracts SET status = 'running' WHERE id = $1",
                contract_id,
            )

        initial_state = {
            "contract_id": contract_id,
            "raw_text": raw_text,
            "analysis": None,
            "precedents": None,
            "risk_report": None,
            "current_node": "starting",
            "auto_approved": False,
            "requires_escalation": False,
            "error_log": [],
            "retry_count": 0,
        }

        config = {
            "configurable": {"thread_id": contract_id},
            "recursion_limit": 25,
        }

        # Stream node-by-node progress for SSE
        async for event in _graph.astream(initial_state, config=config, stream_mode="updates"):
            print(f"DEBUG EVENT: {event!r}")
            for node_name, node_output in event.items():
                if not isinstance(node_output, dict):
                    continue
                _push_update(contract_id, {
                    "type": "node_complete",
                    "node": node_name,
                    "current_node": node_output.get("current_node", node_name),
                    "risk_score": (node_output.get("risk_report") or {}).get("risk_score"),
                    "requires_escalation": node_output.get("requires_escalation", False),
                })

        # Get final state
        final_state = await _graph.aget_state(config)
        risk_report = final_state.values.get("risk_report")
        requires_escalation = final_state.values.get("requires_escalation", False)
        status = "escalated" if requires_escalation else "completed"

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE contracts SET status = $2, completed_at = NOW()
                WHERE id = $1
                """,
                contract_id,
                status,
            )
            if risk_report:
                await conn.execute(
                    """
                    INSERT INTO analysis_runs (contract_id, current_node, risk_score, risk_report, requires_escalation, thread_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (contract_id) DO UPDATE
                    SET current_node = EXCLUDED.current_node,
                        risk_score = EXCLUDED.risk_score,
                        risk_report = EXCLUDED.risk_report,
                        requires_escalation = EXCLUDED.requires_escalation
                    """,
                    contract_id,
                    final_state.values.get("current_node", "completed"),
                    risk_report.get("risk_score"),
                    json.dumps(risk_report),
                    requires_escalation,
                    contract_id,
                )

        _push_update(contract_id, {
            "type": "complete",
            "status": status,
            "risk_score": (risk_report or {}).get("risk_score"),
            "requires_escalation": requires_escalation,
            "risk_report": risk_report,
        })

    except Exception as exc:
        import traceback
        traceback.print_exc()
        logfire.error("analysis_run_failed", contract_id=contract_id, error=str(exc))
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE contracts SET status = 'failed', error_message = $2 WHERE id = $1",
                contract_id,
                str(exc),
            )
        _push_update(contract_id, {"type": "error", "message": str(exc)})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Liveness check."""
    return {"status": "ok", "service": "contract-intelligence-engine"}


@app.post("/contracts", response_model=AnalysisResponse, status_code=202)
async def submit_contract(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    contract_text: str | None = Form(default=None),
    filename: str | None = Form(default=None),
):
    """
    Submit a contract for analysis.

    Accepts:
      - Multipart PDF upload (file=)
      - Plain text via form field (contract_text=)
      - JSON body via /contracts/text endpoint

    Returns immediately with contract_id. Analysis runs in background.
    Stream progress via GET /contracts/{id}/stream
    """
    with logfire.span("submit_contract"):
        raw_text = await _extract_text(file, contract_text)
        raw_text = raw_text.replace("\x00", "")

        if len(raw_text.strip()) < 100:
            raise HTTPException(
                status_code=422,
                detail="Contract text is too short (< 100 characters). Please upload a valid contract."
            )

        contract_id = str(uuid.uuid4())
        pool = await get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO contracts (id, filename, raw_text, status) VALUES ($1, $2, $3, 'pending')",
                contract_id,
                filename or (file.filename if file else "text_upload"),
                raw_text,
            )

        logfire.info("contract_submitted", contract_id=contract_id, text_length=len(raw_text))
        background_tasks.add_task(_run_analysis, contract_id, raw_text)

        return AnalysisResponse(
            contract_id=contract_id,
            status="pending",
            message=f"Analysis started. Stream progress at /contracts/{contract_id}/stream",
        )


@app.post("/contracts/text", response_model=AnalysisResponse, status_code=202)
async def submit_contract_text(
    request: ContractTextRequest,
    background_tasks: BackgroundTasks,
):
    """Submit contract as JSON body with plain text."""
    with logfire.span("submit_contract_text"):
        request.contract_text = request.contract_text.replace("\x00", "")
        if len(request.contract_text.strip()) < 100:
            raise HTTPException(status_code=422, detail="Contract text too short")

        contract_id = str(uuid.uuid4())
        pool = await get_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO contracts (id, filename, raw_text, status) VALUES ($1, $2, $3, 'pending')",
                contract_id,
                request.filename or "text_upload",
                request.contract_text,
            )

        background_tasks.add_task(_run_analysis, contract_id, request.contract_text)
        return AnalysisResponse(
            contract_id=contract_id,
            status="pending",
            message=f"Analysis started. Stream at /contracts/{contract_id}/stream",
        )


@app.get("/contracts/{contract_id}/stream")
async def stream_contract_progress(contract_id: str):
    """
    Server-Sent Events stream for live analysis progress.

    The Next.js dashboard connects here immediately after upload.
    Events emitted:
      - node_complete: {node, current_node, risk_score}
      - complete: {status, risk_score, risk_report}
      - error: {message}
      - heartbeat: {} (every 15s to keep connection alive)
    """
    # Verify contract exists
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM contracts WHERE id = $1", contract_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")

    # Register SSE queue for this client
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_queues.setdefault(contract_id, []).append(queue)

    async def event_generator():
        try:
            # If already completed, send final state immediately
            if row["status"] in ("completed", "escalated", "failed"):
                async with pool.acquire() as conn:
                    run = await conn.fetchrow(
                        "SELECT risk_score, risk_report, requires_escalation FROM analysis_runs WHERE contract_id = $1",
                        contract_id,
                    )
                if run:
                    payload = {
                        "type": "complete",
                        "status": row["status"],
                        "risk_score": run["risk_score"],
                        "requires_escalation": run["requires_escalation"],
                        "risk_report": json.loads(run["risk_report"]) if run["risk_report"] else None,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    return

            # Stream live updates
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                    if data.get("type") in ("complete", "error"):
                        break
                except asyncio.TimeoutError:
                    yield "data: {\"type\": \"heartbeat\"}\n\n"
        finally:
            queues = _sse_queues.get(contract_id, [])
            if queue in queues:
                queues.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.get("/contracts/{contract_id}")
async def get_contract_result(contract_id: str):
    """Get the final risk report for a completed analysis."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        contract = await conn.fetchrow(
            "SELECT id, filename, status, created_at, completed_at, error_message FROM contracts WHERE id = $1",
            contract_id,
        )
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")

        run = await conn.fetchrow(
            "SELECT risk_score, risk_report, requires_escalation, current_node FROM analysis_runs WHERE contract_id = $1",
            contract_id,
        )

    return {
        "contract_id": contract_id,
        "filename": contract["filename"],
        "status": contract["status"],
        "created_at": contract["created_at"].isoformat() if contract["created_at"] else None,
        "completed_at": contract["completed_at"].isoformat() if contract["completed_at"] else None,
        "error_message": contract["error_message"],
        "risk_score": run["risk_score"] if run else None,
        "requires_escalation": run["requires_escalation"] if run else False,
        "current_node": run["current_node"] if run else None,
        "risk_report": json.loads(run["risk_report"]) if run and run["risk_report"] else None,
    }


@app.post("/contracts/{contract_id}/resume")
async def resume_escalated_contract(
    contract_id: str,
    request: ResumeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Resume a paused (escalated) LangGraph graph after human review.

    This endpoint is called when the reviewer clicks 'Approve' or 'Reject'
    in the EscalationBanner on the dashboard. It resumes the LangGraph
    execution from the interrupt_before=["escalate"] checkpoint.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        contract = await conn.fetchrow(
            "SELECT status FROM contracts WHERE id = $1", contract_id
        )

    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract["status"] != "escalated":
        raise HTTPException(
            status_code=409,
            detail=f"Contract is not awaiting escalation review (status: {contract['status']})"
        )

    config = {"configurable": {"thread_id": contract_id}}

    # Resume from checkpoint — graph continues from the escalate node
    async def _resume():
        try:
            async for event in _graph.astream(None, config=config, stream_mode="updates"):
                for node_name, output in event.items():
                    _push_update(contract_id, {
                        "type": "node_complete",
                        "node": node_name,
                        "reviewer_approved": request.approved,
                    })

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE contracts SET status = 'completed', completed_at = NOW() WHERE id = $1",
                    contract_id,
                )
            _push_update(contract_id, {"type": "complete", "status": "completed", "reviewer_approved": request.approved})
        except Exception as exc:
            logfire.error("resume_failed", contract_id=contract_id, error=str(exc))

    background_tasks.add_task(_resume)
    logfire.info("escalation_resumed", contract_id=contract_id, approved=request.approved)

    return {"contract_id": contract_id, "status": "resuming", "approved": request.approved}


@app.get("/contracts")
async def list_contracts(limit: int = 20, offset: int = 0):
    """List all submitted contracts with their current status."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.filename, c.status, c.created_at, a.risk_score, a.requires_escalation
            FROM contracts c
            LEFT JOIN analysis_runs a ON c.id = a.contract_id
            ORDER BY c.created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    return {
        "contracts": [
            {
                "contract_id": row["id"],
                "filename": row["filename"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "risk_score": row["risk_score"],
                "requires_escalation": row["requires_escalation"],
            }
            for row in rows
        ],
        "total": len(rows),
    }
