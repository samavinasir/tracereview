import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from uuid import UUID

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from auditable_research.config import settings
from auditable_research.provider_credentials import (
    PROVIDER_KEY_FIELDS,
    decrypt_provider_keys,
    encrypt_provider_keys,
    encryption_is_configured,
)
from auditable_research.storage import (
    create_queued_research,
    get_audit,
    get_claims,
    get_evidence,
    get_plan,
    get_report,
    get_research,
    get_sources,
    get_status,
    initialize_storage,
    update_source_review,
)

from .models import ResearchRunOwner, UserProviderCredentials

logger = logging.getLogger(__name__)
_storage_lock = asyncio.Lock()
_storage_ready = False
_rate_lock = asyncio.Lock()
_request_times: dict[str, deque[float]] = defaultdict(deque)
_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bBearer\s+[^\s,;]+"), "Bearer [REDACTED]"),
    (re.compile(r"\b(?:gsk_|sk-)[A-Za-z0-9_-]{10,}\b"), "[REDACTED_SECRET]"),
    (re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[:=]\s*)[^\s,;]+"), r"\1\2[REDACTED]"),
)


async def _ensure_storage() -> None:
    global _storage_ready
    if _storage_ready:
        return
    async with _storage_lock:
        if not _storage_ready:
            await initialize_storage()
            _storage_ready = True


def _safe_error(error: Exception) -> str:
    result = f"{type(error).__name__}: {error}"
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result[:500]


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    return render(request, "research/home.html")


def signup(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("home")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def api_keys(request: HttpRequest) -> HttpResponse:
    row, _ = UserProviderCredentials.objects.get_or_create(user=request.user)
    keys: dict[str, str] = {}
    encryption_ready = encryption_is_configured()
    if encryption_ready:
        try:
            keys = decrypt_provider_keys(row.encrypted_keys)
        except RuntimeError:
            messages.error(request, "Saved keys could not be decrypted. Check the server's USER_KEYS_ENCRYPTION_KEY.")
    elif request.method == "POST":
        messages.error(request, "Key storage is not enabled yet. The server must configure USER_KEYS_ENCRYPTION_KEY first.")

    if request.method == "POST" and encryption_ready:
        for field in PROVIDER_KEY_FIELDS:
            new_value = request.POST.get(field, "").strip()
            if request.POST.get(f"clear_{field}") == "on":
                keys.pop(field, None)
            elif new_value:
                keys[field] = new_value
        row.encrypted_keys = encrypt_provider_keys(keys)
        row.save(update_fields=["encrypted_keys", "updated_at"])
        messages.success(request, "Your provider keys were saved securely.")
        return redirect("api_keys")

    return render(request, "research/api_keys.html", {
        "key_fields": PROVIDER_KEY_FIELDS,
        "configured_keys": set(row.encrypted_keys or {}),
        "encryption_ready": encryption_ready,
        "has_groq_key": bool(keys.get("groq_api_key")) or "groq_api_key" in (row.encrypted_keys or {}),
    })


@require_GET
def research_workspace(request: HttpRequest, research_id: UUID, page: str) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect(f"/accounts/login/?next={request.path}")
    if not ResearchRunOwner.objects.filter(research_id=research_id, user=request.user).exists():
        return HttpResponse(status=404)
    if page not in {"results", "run"}:
        return HttpResponse(status=404)
    view = request.GET.get("view", "results" if page == "results" else "overview")
    allowed = {"results", "papers", "evidence", "synthesis", "export"} if page == "results" else {"overview", "plan", "audit"}
    if view not in allowed:
        view = "results" if page == "results" else "overview"
    return render(request, "research/workspace.html", {"research_id": research_id, "page": page, "view": view})


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@require_POST
async def start_research(request: HttpRequest) -> JsonResponse:
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({"detail": "Create an account or sign in to start research."}, status=401)
    if not encryption_is_configured():
        return JsonResponse({"detail": "Secure key storage is not configured on the server."}, status=503)
    credential_row = await UserProviderCredentials.objects.filter(user=user).afirst()
    try:
        user_keys = decrypt_provider_keys(credential_row.encrypted_keys if credential_row else None)
    except RuntimeError:
        logger.error("User provider keys could not be decrypted user_id=%s", user.pk)
        return JsonResponse({"detail": "Your saved provider keys could not be decrypted. Contact the site administrator."}, status=503)
    if not user_keys.get("groq_api_key"):
        return JsonResponse({"detail": "Add your Groq API key in API key settings before starting research."}, status=400)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict) or set(payload) - {"question", "options"}:
        return JsonResponse({"detail": "Request body may contain question and options fields."}, status=422)
    question = payload.get("question")
    if not isinstance(question, str):
        return JsonResponse({"detail": "Question must be text."}, status=422)
    question = question.strip()
    if len(question) < 10 or len(question) > 4000:
        return JsonResponse({"detail": "Question must be between 10 and 4000 characters."}, status=422)
    if any(ord(char) < 32 and char not in "\n\r\t" for char in question):
        return JsonResponse({"detail": "Question contains unsupported control characters."}, status=422)

    options = payload.get("options", {})
    fields = {"auto", "biology", "medicine", "computer_science", "engineering", "social_sciences", "humanities", "other"}
    goals = {"explore", "compare", "methods", "evidence"}
    providers = {"pubmed", "europe_pmc", "openalex", "semantic_scholar", "uniprot"}
    if not isinstance(options, dict):
        return JsonResponse({"detail": "Options must be an object."}, status=422)
    field = options.get("field", "auto")
    goal = options.get("review_goal", "explore")
    filters = options.get("filters", {})
    if not isinstance(field, str) or field not in fields or not isinstance(goal, str) or goal not in goals or not isinstance(filters, dict):
        return JsonResponse({"detail": "Invalid field, review goal, or filters."}, status=422)
    sources = filters.get("sources", [])
    if not isinstance(sources, list) or any(not isinstance(source, str) or source not in providers for source in sources):
        return JsonResponse({"detail": "One or more selected sources are not supported."}, status=422)
    year_from, year_to = filters.get("year_from"), filters.get("year_to")
    if any(value is not None and (not isinstance(value, int) or value < 1800 or value > 2100) for value in (year_from, year_to)):
        return JsonResponse({"detail": "Publication years must be between 1800 and 2100."}, status=422)
    if year_from and year_to and year_from > year_to:
        return JsonResponse({"detail": "Start year must not be later than end year."}, status=422)
    options = {"field": field, "review_goal": goal, "filters": {
        "year_from": year_from, "year_to": year_to,
        "full_text_only": bool(filters.get("full_text_only", False)),
        "sources": list(dict.fromkeys(sources)),
    }}

    now = time.monotonic()
    client = request.META.get("REMOTE_ADDR", "unknown")
    async with _rate_lock:
        attempts = _request_times[client]
        window = settings.research_rate_limit_window_seconds
        while attempts and now - attempts[0] >= window:
            attempts.popleft()
        if len(attempts) >= settings.research_rate_limit_requests:
            retry_after = max(1, int(window - (now - attempts[0])))
            return JsonResponse(
                {"detail": "Research request limit reached. Please try again shortly."},
                status=429,
                headers={"Retry-After": str(retry_after)},
            )
        attempts.append(now)
    try:
        await _ensure_storage()
        research_id = await create_queued_research(question, options, user_id=user.pk)
        await ResearchRunOwner.objects.acreate(research_id=research_id, user=user)
    except Exception as exc:
        logger.error("Research run creation failed user_id=%s error_type=%s", user.pk, type(exc).__name__)
        return JsonResponse({"detail": "Could not queue research run. Check API and database health."}, status=503)
    return JsonResponse({
        "research_id": str(research_id),
        "run_id": str(research_id),
        "status": "queued",
        "result_url": f"/research/{research_id}",
    }, status=202)


async def _read(request: HttpRequest, research_id: UUID, getter) -> JsonResponse:
    user = await request.auser()
    if not user.is_authenticated or not await ResearchRunOwner.objects.filter(research_id=research_id, user=user).aexists():
        return JsonResponse({"detail": "Research not found."}, status=404)
    try:
        await _ensure_storage()
        result = await getter(research_id)
    except Exception as exc:
        logger.error("Research read failed id=%s error_type=%s", research_id, type(exc).__name__)
        return JsonResponse({"detail": "Could not read research data. Check database health."}, status=503)
    if result is None:
        return JsonResponse({"detail": f"Research {research_id} not found"}, status=404)
    return JsonResponse(result, safe=not isinstance(result, list))


async def read_research(request: HttpRequest, research_id: UUID) -> JsonResponse:
    return await _read(request, research_id, get_research)


async def read_status(request: HttpRequest, research_id: UUID) -> JsonResponse:
    return await _read(request, research_id, get_status)


async def read_plan(request: HttpRequest, research_id: UUID) -> JsonResponse:
    return await _read(request, research_id, get_plan)


async def read_sources(request: HttpRequest, research_id: UUID) -> JsonResponse:
    return await _read(request, research_id, get_sources)


@require_POST
async def review_source(request: HttpRequest, research_id: UUID) -> JsonResponse:
    user = await request.auser()
    if not user.is_authenticated or not await ResearchRunOwner.objects.filter(research_id=research_id, user=user).aexists():
        return JsonResponse({"detail": "Research not found."}, status=404)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Request body must be valid JSON."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "Request body must be an object."}, status=422)
    source_id, decision, note = payload.get("source_id"), payload.get("decision"), payload.get("note", "")
    if not isinstance(source_id, str) or len(source_id) > 500 or decision not in {"include", "exclude", "unreviewed"} or not isinstance(note, str):
        return JsonResponse({"detail": "Provide a valid source_id, decision, and note."}, status=422)
    try:
        await _ensure_storage()
        updated = await update_source_review(research_id, source_id, decision, note)
    except Exception as exc:
        logger.error("Source decision save failed id=%s error_type=%s", research_id, type(exc).__name__)
        return JsonResponse({"detail": "Could not save the review decision."}, status=503)
    if not updated:
        return JsonResponse({"detail": "Source not found for this research run."}, status=404)
    return JsonResponse({"source_id": source_id, "decision": decision, "note": note[:1000]})


async def read_evidence(request: HttpRequest, research_id: UUID) -> JsonResponse:
    return await _read(request, research_id, get_evidence)


async def read_claims(request: HttpRequest, research_id: UUID) -> JsonResponse:
    return await _read(request, research_id, get_claims)


async def read_audit(request: HttpRequest, research_id: UUID) -> JsonResponse:
    return await _read(request, research_id, get_audit)


async def read_report(request: HttpRequest, research_id: UUID) -> HttpResponse:
    result = await _read(request, research_id, get_report)
    if result.status_code != 200 or request.GET.get("format") != "markdown":
        return result
    import json

    payload = json.loads(result.content)
    response = HttpResponse(payload["markdown"], content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="research-{research_id}.md"'
    return response
