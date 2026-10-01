import asyncio
import json
import time
from typing import Any, Literal, TypeVar, cast

import httpx
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from .config import settings
from .models import ClaimVerification, EvidenceItem, ResearchPlan, SearchQuery, SourceRecord

T = TypeVar("T", bound=BaseModel)


class _GroqTokenBucket:
    """Conservative per-process request gate shared by all Groq model calls."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tokens = float(settings.groq_tpm_budget)
        self._updated_at = time.monotonic()
        self._semaphore = asyncio.Semaphore(settings.groq_max_concurrency)

    async def reserve(self, amount: int) -> None:
        capacity = float(settings.groq_tpm_budget)
        if amount > capacity:
            raise PromptBudgetExceeded("Estimated request exceeds the configured Groq token budget")
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(capacity, self._tokens + (now - self._updated_at) * capacity / 60)
                self._updated_at = now
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                wait_seconds = (amount - self._tokens) * 60 / capacity
            await asyncio.sleep(wait_seconds)

    async def refund(self, amount: int) -> None:
        async with self._lock:
            capacity = float(settings.groq_tpm_budget)
            now = time.monotonic()
            self._tokens = min(capacity, self._tokens + amount + (now - self._updated_at) * capacity / 60)
            self._updated_at = now

    async def reconcile(self, reserved: int, actual: int | None) -> None:
        if actual is not None and actual < reserved:
            await self.refund(reserved - actual)
        elif actual is not None and actual > reserved:
            async with self._lock:
                self._tokens -= actual - reserved


_groq_bucket = _GroqTokenBucket()


class PlanOutput(ResearchPlan):
    queries: list[SearchQuery]


class QueryExpansionOutput(BaseModel):
    queries: list[SearchQuery]


class EvidenceDraft(BaseModel):
    source_id: str
    subquestion: str
    # `text` must be copied verbatim from the indicated record section.
    text: str
    evidence_type: Literal["experimental", "observational", "computational", "review", "inference", "background", "unknown"]
    evidence_level: Literal["direct", "indirect", "contextual", "inference"]
    source_part: Literal["title", "abstract", "methods", "results"]
    limitations: list[str] = Field(default_factory=list)


class ClaimDraft(BaseModel):
    text: str
    subquestion: str
    evidence_indexes: list[int]


class ExtractionOutput(BaseModel):
    evidence: list[EvidenceDraft]
    claims: list[ClaimDraft]
    research_gaps: list[str]


class PaperDigestDraft(BaseModel):
    source_id: str
    what_study_did: str = Field(max_length=1200)
    key_findings: list[str] = Field(default_factory=list, max_length=5)
    why_it_matches: str = Field(max_length=500)
    study_type: Literal["experimental", "clinical_observational", "computational", "review", "systematic_review_meta_analysis", "case_report", "other", "unclear"]


class PaperDigestOutput(BaseModel):
    papers: list[PaperDigestDraft]


def _coerce_paper_digest_output(content: str) -> PaperDigestOutput:
    """Normalize common OpenRouter/free-model JSON variations before validation."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        raw = json.loads(text[start : end + 1])

    raw_papers: Any
    if isinstance(raw, list):
        raw_papers = raw
    elif isinstance(raw, dict):
        raw_papers = raw.get("papers", raw.get("results", raw.get("items", [])))
        if isinstance(raw_papers, dict):
            raw_papers = [raw_papers]
    else:
        raw_papers = []

    allowed_types = {"experimental", "clinical_observational", "computational", "review", "systematic_review_meta_analysis", "case_report", "other", "unclear"}
    normalized: list[dict[str, Any]] = []
    for item in raw_papers if isinstance(raw_papers, list) else []:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id", item.get("paper_id", item.get("id")))
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        summary = item.get("what_study_did", item.get("study_summary", item.get("summary", item.get("what_the_study_did", ""))))
        relevance = item.get("why_it_matches", item.get("relevance_note", item.get("why_relevant", "")))
        findings = item.get("key_findings", item.get("findings", item.get("quotes", [])))
        if isinstance(findings, str):
            findings = [findings]
        quote_texts: list[str] = []
        if isinstance(findings, list):
            for finding in findings:
                quote = finding if isinstance(finding, str) else finding.get("text", finding.get("quote")) if isinstance(finding, dict) else None
                if isinstance(quote, str) and quote.strip():
                    quote_texts.append(quote.strip()[:1200])
        kind = str(item.get("study_type", item.get("study_design", "unclear"))).strip().casefold().replace("-", "_").replace(" ", "_")
        if kind not in allowed_types:
            if any(term in kind for term in ("review", "meta_analysis", "systematic")):
                kind = "systematic_review_meta_analysis" if any(term in kind for term in ("meta_analysis", "systematic")) else "review"
            elif any(term in kind for term in ("clinical", "cohort", "case_control", "cross_sectional")):
                kind = "clinical_observational"
            elif any(term in kind for term in ("computational", "bioinformatic", "in_silico", "genomic")):
                kind = "computational"
            elif "case" in kind:
                kind = "case_report"
            elif any(term in kind for term in ("in_vitro", "in_vivo", "experimental", "laboratory", "knockout", "assay")):
                kind = "experimental"
            elif kind in {"", "none", "null"}:
                kind = "unclear"
            else:
                kind = "other"
        normalized.append({
            "source_id": source_id.strip(),
            "what_study_did": (summary.strip() if isinstance(summary, str) and summary.strip() else "The model did not provide a study summary.")[:1200],
            "key_findings": quote_texts[:5],
            "why_it_matches": (relevance.strip() if isinstance(relevance, str) and relevance.strip() else "Selected by local relevance ranking.")[:500],
            "study_type": kind,
        })
    return PaperDigestOutput(papers=normalized)


class ScreenDecision(BaseModel):
    source_id: str
    relevant: bool
    rationale: str = Field(max_length=500)


class ScreeningOutput(BaseModel):
    decisions: list[ScreenDecision]


class VerificationOutput(BaseModel):
    assessments: list[ClaimVerification]
    contradictions: list[str]
    research_gaps: list[str]


class ReportOutput(BaseModel):
    executive_summary: str
    section_texts: list[str]


class PromptBudgetExceeded(RuntimeError):
    """The provider says this individual request exceeds the configured token budget."""


class GroqRateLimited(RuntimeError):
    """Groq asked the caller to wait longer than the workflow's retry budget."""

    def __init__(self, model_name: str, retry_after_seconds: float | None) -> None:
        self.model_name = model_name
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Groq rate limit cooldown exceeds the configured wait budget")


def _structured_model(
    schema: type[BaseModel], model_name: str | None = None, max_completion_tokens: int | None = None
) -> Any:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required to run the research workflow")
    model = ChatGroq(  # type: ignore[call-arg]
        api_key=settings.groq_api_key,
        model=model_name or settings.groq_model,
        temperature=0,
        max_tokens=max_completion_tokens or settings.groq_max_completion_tokens,
        reasoning_effort=settings.groq_reasoning_effort,
    )
    return model.with_structured_output(schema, include_raw=True)


def _rate_limit_error(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    message = str(error).casefold()
    return status == 429 or "rate_limit_exceeded" in message or "too many requests" in message


def _request_too_large(error: Exception) -> bool:
    message = str(error).casefold()
    return "tokens per minute" in message and any(word in message for word in ("requested", "limit", "reduce"))


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0.0, min(float(raw), 86400.0)) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def invoke_structured(
    schema: type[T],
    messages: list[tuple[str, str]],
    model_name: str | None = None,
    *,
    max_retry_wait_seconds: float | None = None,
    max_retries: int | None = None,
    max_completion_tokens: int | None = None,
) -> tuple[T, dict]:
    model_name = model_name or settings.groq_model
    model = _structured_model(schema, model_name, max_completion_tokens) if max_completion_tokens else _structured_model(schema, model_name)
    response = None
    retry_limit = settings.groq_max_retries if max_retries is None else max_retries
    wait_limit = settings.groq_max_retry_wait_seconds if max_retry_wait_seconds is None else max_retry_wait_seconds
    request_text = json.dumps(messages, ensure_ascii=False)
    completion_cap = max_completion_tokens or settings.groq_max_completion_tokens
    reserved_tokens = max(1, (len(request_text) + 2) // 3) + completion_cap
    for attempt in range(retry_limit + 1):
        try:
            async with _groq_bucket._semaphore:
                await _groq_bucket.reserve(reserved_tokens)
                try:
                    response = await model.ainvoke(messages)
                except Exception:
                    await _groq_bucket.refund(reserved_tokens)
                    raise
            break
        except Exception as error:
            if _request_too_large(error):
                raise PromptBudgetExceeded("The provider request exceeded the per-request token budget") from None
            if not _rate_limit_error(error):
                raise
            delay = _retry_after(error)
            if delay is not None and delay > wait_limit:
                raise GroqRateLimited(model_name, delay) from None
            if attempt >= retry_limit:
                raise GroqRateLimited(model_name, delay) from None
            if delay is None:
                delay = min(settings.groq_retry_base_seconds * (2**attempt), wait_limit)
            await asyncio.sleep(delay)
    if response is None:
        raise RuntimeError("Groq request failed after retry handling")
    parsed = response.get("parsed")
    if parsed is None:
        parse_error = response.get("parsing_error")
        raise RuntimeError(f"Groq structured response could not be parsed: {type(parse_error).__name__ if parse_error else 'missing parsed value'}")
    raw = response.get("raw")
    usage = getattr(raw, "usage_metadata", None) or getattr(raw, "response_metadata", {}).get("token_usage", {})
    usage = usage or {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    actual_total = usage.get("total_tokens")
    if actual_total is None and input_tokens is not None and output_tokens is not None:
        actual_total = input_tokens + output_tokens
    await _groq_bucket.reconcile(reserved_tokens, actual_total)
    return parsed, {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": actual_total, "model": model_name}


async def invoke_openrouter_structured(
    schema: type[T], messages: list[tuple[str, str]], model_name: str | None = None
) -> tuple[T, dict]:
    """One bounded OpenRouter call used only as an independent digest fallback."""
    if not settings.openrouter_api_key:
        raise RuntimeError("OpenRouter fallback is not configured")
    payload = {
        "model": model_name or settings.openrouter_fallback_model,
        "messages": [{"role": role, "content": content} for role, content in messages],
        "response_format": {"type": "json_object"},
        "max_tokens": settings.paper_digest_max_completion_tokens,
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if schema is PaperDigestOutput:
        parsed: T = cast(T, _coerce_paper_digest_output(content))
    else:
        parsed = schema.model_validate_json(content)
    usage = body.get("usage", {})
    return parsed, {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "model": body.get("model", model_name or settings.openrouter_fallback_model),
        "provider": "openrouter",
    }


def compact_sources(sources: list[SourceRecord]) -> list[dict]:
    """Keep LLM context bounded; raw provider payloads stay in the audit record only."""
    max_abstract_chars = settings.max_source_text_chars
    return [
        {
            "source_id": source.source_id,
            "provider": source.provider,
            "title": source.title[:500],
            "authors": source.authors[:8],
            "publication_year": source.publication_year,
            "url": source.url,
            "abstract": source.abstract[:max_abstract_chars],
            "full_text_sections": [
                {"source_part": section.source_part, "title": section.title, "text": section.text[:700]}
                for part in ("methods", "results")
                for section in [next((item for item in source.full_text_sections if item.source_part == part), None)]
                if section is not None
            ],
        }
        for source in sources
    ]


def compact_evidence(evidence: list[EvidenceItem]) -> list[dict]:
    return [e.model_dump(mode="json") for e in evidence]
