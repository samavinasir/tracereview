import logging
import re
import time
from contextlib import nullcontext
from uuid import UUID, uuid4

from .graph import paper_review_completion_issue, research_graph
from .models import AuditEvent
from .provider_credentials import use_provider_keys
from .state import ResearchState
from .storage import save_run

logger = logging.getLogger(__name__)
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


async def run_workflow(research_id: UUID, question: str, research_options: dict | None = None, provider_keys: dict[str, str] | None = None) -> None:
    """Run the existing research graph for either the Django or legacy API entry point."""
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
    initial: ResearchState = {"run_id": run_id, "research_question": question, "research_options": research_options or {}, "audit_log": [started], "errors": [], "warnings": [], "metadata": {}}
    result = initial
    last_tick = time.perf_counter()
    try:
        await save_run(research_id, question, initial, "running")
        key_context = use_provider_keys(provider_keys) if provider_keys is not None else nullcontext()
        with key_context:
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
            await save_run(research_id, question, result, "completed" if cards else "failed", error=None if cards else completion_issue)
            return
        await save_run(research_id, question, result, "completed")
    except Exception as exc:
        logger.error("Research workflow failed run_id=%s error_type=%s", run_id, type(exc).__name__)
        event = AuditEvent(event_id=f"AUD-{uuid4().hex[:12]}", run_id=run_id, node="workflow", action="workflow_failed", details={"error_type": type(exc).__name__})
        result["audit_log"] = [*result.get("audit_log", []), event]
        result["errors"] = [*result.get("errors", []), f"Workflow failed: {type(exc).__name__}: {_sanitize_error(exc)}"]
        await save_run(research_id, question, result, "failed", latency_ms=(time.perf_counter() - last_tick) * 1000, error=result["errors"][-1])
