import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings
from .graph import paper_review_completion_issue, research_graph
from .models import AuditEvent
from .state import ResearchState
from .storage import (
    create_research,
    engine,
    get_audit,
    get_claims,
    get_evidence,
    get_plan,
    get_report,
    get_research,
    get_sources,
    get_status,
    initialize_storage,
    save_run,
)

logger = logging.getLogger(__name__)
_request_times: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = asyncio.Lock()
_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bBearer\s+[^\s,;]+"), "Bearer [REDACTED]"),
    (re.compile(r"\b(?:gsk_|sk-)[A-Za-z0-9_-]{10,}\b"), "[REDACTED_SECRET]"),
    (re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[:=]\s*)[^\s,;]+"), r"\1\2[REDACTED]"),
)


def _sanitize_error(error: Exception) -> str:
    detail = f"{type(error).__name__}: {error}"
    for pattern, replacement in _SECRET_PATTERNS:
        detail = pattern.sub(replacement, detail)
    return detail[:500]


async def _limit_research_requests(request: Request) -> None:
    # This per-process limiter is suitable for the single-container starter stack.
    # Use a shared store such as Redis when deploying multiple API workers/replicas.
    client_id = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = settings.research_rate_limit_window_seconds
    async with _rate_limit_lock:
        attempts = _request_times[client_id]
        while attempts and now - attempts[0] >= window:
            attempts.popleft()
        if len(attempts) >= settings.research_rate_limit_requests:
            retry_after = max(1, int(window - (now - attempts[0])))
            raise HTTPException(
                status_code=429,
                detail="Research request limit reached. Please try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        attempts.append(now)


class ResearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=10, max_length=4000)

    @field_validator("question")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ValueError("Question contains unsupported control characters")
        return value


@asynccontextmanager
async def lifespan(_: FastAPI):
    await initialize_storage()
    yield
    await engine.dispose()


app = FastAPI(title="TraceReview", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _run_workflow(research_id: UUID, question: str) -> None:
    run_id = str(research_id)
    started = AuditEvent(
        event_id=f"AUD-{uuid4().hex[:12]}",
        run_id=run_id,
        node="workflow",
        action="workflow_started",
        input_refs=["research_question"],
        output_refs=[],
        details={"status": "initializing"},
    )
    initial: ResearchState = {"run_id": run_id, "research_question": question, "audit_log": [started], "errors": [], "warnings": [], "metadata": {}}
    result = initial
    last_tick = time.perf_counter()
    try:
        # Persist before the first model call so a slow planner/retry never
        # leaves the UI showing "queued" with no indication of activity.
        await save_run(research_id, question, initial, "running")
        async for snapshot in research_graph.astream(initial, config={"recursion_limit": 500}, stream_mode="values"):
            node_latency_ms = (time.perf_counter() - last_tick) * 1000
            result = snapshot
            await save_run(research_id, question, result, "running", latency_ms=node_latency_ms)
            last_tick = time.perf_counter()
        completion_issue = paper_review_completion_issue(result)
        if completion_issue:
            cards = result.get("paper_digests", [])
            event = AuditEvent(
                event_id=f"AUD-{uuid4().hex[:12]}",
                run_id=run_id,
                node="workflow",
                action="workflow_partial_completion" if cards else "workflow_incomplete",
                input_refs=["selected_paper_ids", "paper_digests"],
                output_refs=[digest.source_id for digest in cards],
                details={"reason": completion_issue},
            )
            result["audit_log"] = [*result.get("audit_log", []), event]
            if cards:
                result["warnings"] = list(dict.fromkeys([*result.get("warnings", []), completion_issue]))
            else:
                result["errors"] = list(dict.fromkeys([*result.get("errors", []), completion_issue]))
            status = "completed" if cards else "failed"
            await save_run(research_id, question, result, status, error=None if cards else completion_issue)
            return
        await save_run(research_id, question, result, "completed")
    except Exception as exc:
        # Avoid logging upstream exception bodies, which can contain user content
        # or provider diagnostics. Keep a safe, structured failure record instead.
        logger.error("Research workflow failed run_id=%s error_type=%s", run_id, type(exc).__name__)
        event = AuditEvent(event_id=f"AUD-{uuid4().hex[:12]}", run_id=run_id, node="workflow", action="workflow_failed", details={"error_type": type(exc).__name__})
        result["audit_log"] = [*result.get("audit_log", []), event]
        detail = _sanitize_error(exc)
        result["errors"] = [*result.get("errors", []), f"Workflow failed: {type(exc).__name__}: {detail}"]
        await save_run(research_id, question, result, "failed", latency_ms=(time.perf_counter() - last_tick) * 1000, error=result["errors"][-1])


@app.post("/research", status_code=202, dependencies=[Depends(_limit_research_requests)])
async def start_research(request: ResearchRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    try:
        research_id = await create_research(request.question)
    except Exception as exc:
        logger.error("Research run creation failed error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Could not queue research run. Check API and database health.") from None
    background_tasks.add_task(_run_workflow, research_id, request.question)
    return {"research_id": str(research_id), "run_id": str(research_id), "status": "queued", "result_url": f"/research/{research_id}"}


async def _required(value: dict | list | None, research_id: UUID):
    if value is None:
        raise HTTPException(status_code=404, detail=f"Research {research_id} not found")
    return value


@app.get("/research/{research_id}")
async def read_research(research_id: UUID) -> dict:
    return await _required(await get_research(research_id), research_id)


@app.get("/research/{research_id}/status")
async def read_status(research_id: UUID) -> dict:
    return await _required(await get_status(research_id), research_id)


@app.get("/research/{research_id}/plan")
async def read_plan(research_id: UUID) -> dict:
    return await _required(await get_plan(research_id), research_id)


@app.get("/research/{research_id}/sources")
async def read_sources(research_id: UUID) -> list[dict]:
    return await _required(await get_sources(research_id), research_id)


@app.get("/research/{research_id}/evidence")
async def read_evidence(research_id: UUID) -> list[dict]:
    return await _required(await get_evidence(research_id), research_id)


@app.get("/research/{research_id}/claims")
async def read_claims(research_id: UUID) -> list[dict]:
    return await _required(await get_claims(research_id), research_id)


@app.get("/research/{research_id}/audit")
async def read_audit(research_id: UUID) -> list[dict]:
    return await _required(await get_audit(research_id), research_id)


@app.get("/research/{research_id}/report")
async def read_report(research_id: UUID, format: str = Query("json", pattern="^(json|markdown)$")):
    result = await _required(await get_report(research_id), research_id)
    if format == "markdown":
        return PlainTextResponse(result["markdown"], headers={"Content-Disposition": f'attachment; filename="research-{research_id}.md"'})
    return result
