import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import settings
from .db_models import (
    AgentEvent,
    Base,
    Claim,
    ClaimEvidence,
    Document,
    Evidence,
    PaperDigestCache,
    Report,
    ResearchPlan,
    ResearchQuestion,
    ResearchRun,
    ResearchSession,
    Source,
    Subquestion,
    VerificationResult,
)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _report_generated_at(report: Any, report_data: dict) -> datetime:
    """Support both Pydantic reports and the paper-digest report dictionaries."""
    value = _value(report, "generated_at") or report_data.get("generated_at")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = None
    return value if isinstance(value, datetime) else datetime.now(UTC)


def _json(value: Any) -> Any:
    def serialize(item: Any) -> Any:
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if hasattr(item, "isoformat"):
            return item.isoformat()
        return str(item)

    return json.loads(json.dumps(value, default=serialize))


def _without_confidence(value: Any) -> Any:
    """Hide legacy uncalibrated verifier confidence values in old run artifacts."""
    if isinstance(value, dict):
        return {key: _without_confidence(item) for key, item in value.items() if key != "confidence"}
    if isinstance(value, list):
        return [_without_confidence(item) for item in value]
    return value


async def initialize_storage() -> None:
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        columns = await connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'research_runs' AND table_schema = current_schema()"))
        existing = {row[0] for row in columns}
        if "run_id" in existing and "id" not in existing:
            legacy = await connection.execute(text("SELECT to_regclass(current_schema() || '.research_runs_legacy')"))
            if legacy.scalar() is None:
                await connection.execute(text("ALTER TABLE research_runs RENAME TO research_runs_legacy"))
                old_pk = await connection.execute(text("SELECT 1 FROM pg_constraint WHERE conrelid = 'research_runs_legacy'::regclass AND conname = 'research_runs_pkey'"))
                if old_pk.scalar() is not None:
                    await connection.execute(text("ALTER TABLE research_runs_legacy RENAME CONSTRAINT research_runs_pkey TO research_runs_legacy_pkey"))
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS full_text_sections JSONB NOT NULL DEFAULT '[]'::jsonb"))
        await connection.execute(text("ALTER TABLE evidence ADD COLUMN IF NOT EXISTS evidence_level VARCHAR(24) NOT NULL DEFAULT 'contextual'"))
        await connection.execute(text("ALTER TABLE evidence ADD COLUMN IF NOT EXISTS source_part VARCHAR(24) NOT NULL DEFAULT 'abstract'"))
        await connection.execute(text("ALTER TABLE verification_results ADD COLUMN IF NOT EXISTS evidence_levels JSONB NOT NULL DEFAULT '[]'::jsonb"))
        # Existing databases may have confidence scores emitted by the old LLM
        # schema. Keep the compatibility columns but clear misleading values.
        await connection.execute(text("ALTER TABLE verification_results ALTER COLUMN confidence DROP NOT NULL"))
        await connection.execute(text("UPDATE claims SET confidence = NULL WHERE confidence IS NOT NULL"))
        await connection.execute(text("UPDATE verification_results SET confidence = NULL WHERE confidence IS NOT NULL"))


async def get_cached_paper_digests(cache_keys: list[str]) -> dict[str, dict]:
    if not cache_keys:
        return {}
    async with Session() as session:
        rows = (await session.scalars(select(PaperDigestCache).where(PaperDigestCache.cache_key.in_(cache_keys)))).all()
        return {row.cache_key: row.digest_json for row in rows}


async def store_cached_paper_digests(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    async with Session.begin() as session:
        keys = [entry["cache_key"] for entry in entries]
        rows = (await session.scalars(select(PaperDigestCache).where(PaperDigestCache.cache_key.in_(keys)))).all()
        by_key = {row.cache_key: row for row in rows}
        for entry in entries:
            row = by_key.get(entry["cache_key"])
            if row is None:
                session.add(PaperDigestCache(**entry))
            else:
                row.source_identity = entry["source_identity"]
                row.content_hash = entry["content_hash"]
                row.question_hash = entry["question_hash"]
                row.prompt_version = entry["prompt_version"]
                row.digest_json = entry["digest_json"]


async def create_research(question: str) -> UUID:
    async with Session.begin() as session:
        session_id, question_id, research_id = uuid4(), uuid4(), uuid4()
        research_session = ResearchSession(id=session_id)
        research_question = ResearchQuestion(id=question_id, session_id=session_id, question=question)
        run = ResearchRun(id=research_id, session_id=session_id, question_id=question_id, status="queued", progress={"current_node": "queued"})
        # These rows form a strict FK chain. Explicit flushes guarantee each
        # parent is persisted before the dependent row is inserted.
        session.add(research_session)
        await session.flush()
        session.add(research_question)
        await session.flush()
        session.add(run)
        await session.flush()
        return run.id


async def save_run(research_id: UUID, question: str, state: Mapping[str, Any], status: str, latency_ms: float | None = None, error: str | None = None) -> None:
    async with Session.begin() as session:
        run = await session.get(ResearchRun, research_id)
        if run is None:
            return
        run.status = status
        run.error = error
        if latency_ms is not None:
            run.latency_ms = (run.latency_ms or 0) + latency_ms

        question_row = await session.get(ResearchQuestion, run.question_id)
        if question_row and question_row.question != question:
            question_row.question = question

        audit_log = state.get("audit_log", [])
        latest_event = audit_log[-1] if audit_log else None
        sources = state.get("retrieved_sources", [])
        evidence_items = state.get("evidence_items", [])
        claims = state.get("verified_claims", []) or state.get("candidate_claims", [])
        run.progress = {
            "current_node": _value(latest_event, "node", "queued"),
            "last_action": _value(latest_event, "action"),
            "source_count": len(sources),
            "paper_count": len(state.get("paper_digests", [])),
            "evidence_count": len(evidence_items),
            "claim_count": len(claims),
            "event_count": len(audit_log),
            "errors": state.get("errors", []),
            "warnings": state.get("warnings", []),
            "coverage": {
                "retrieved": len(sources),
                "assessable": sum(1 for source in sources if source.abstract.strip() or source.full_text_sections),
                "screened": len(set(state.get("screened_source_ids", []))),
                "assessed": len(set(state.get("assessed_source_ids", []))),
                "extraction_candidates": len(set(state.get("screen_queue_relevant_ids", []))),
                "unassessed": max(0, len(set(state.get("screen_queue_relevant_ids", [])) - set(state.get("assessed_source_ids", [])))),
                "screen_excluded": sum(1 for item in state.get("screen_decisions", {}).values() if item.get("relevant") is False),
                "retrieved_coverage_percent": round(100 * len(set(state.get("assessed_source_ids", []))) / len(sources), 1) if sources else 0.0,
                "extraction_coverage_percent": round(100 * len(set(state.get("assessed_source_ids", []))) / len(set(state.get("screen_queue_relevant_ids", []))), 1) if state.get("screen_queue_relevant_ids") else 0.0,
            },
            "search_round": state.get("search_round", 0),
            "research_outcome": state.get("research_outcome"),
        }

        subquestion_ids: dict[str, UUID] = {}
        plan = state.get("research_plan")
        if plan:
            plan_row = await session.scalar(select(ResearchPlan).where(ResearchPlan.research_id == research_id))
            if plan_row is None:
                plan_row = ResearchPlan(research_id=research_id, objective=plan.objective, source_types=plan.source_types, search_strategy=plan.search_strategy, search_queries=_json(state.get("search_queries", [])))
                session.add(plan_row)
                await session.flush()
            else:
                plan_row.objective = plan.objective
                plan_row.source_types = plan.source_types
                plan_row.search_strategy = plan.search_strategy
                plan_row.search_queries = _json(state.get("search_queries", []))
            existing_subquestions = list((await session.scalars(select(Subquestion).where(Subquestion.plan_id == plan_row.id))).all())
            for item in existing_subquestions:
                subquestion_ids[item.text] = item.id
            for position, value in enumerate(state.get("subquestions", [])):
                if value not in subquestion_ids:
                    subquestion = Subquestion(plan_id=plan_row.id, text=value, position=position)
                    session.add(subquestion)
                    await session.flush()
                    subquestion_ids[value] = subquestion.id

        source_rows = list((await session.scalars(select(Source).where(Source.research_id == research_id))).all())
        digests = {item.source_id: _json(item) for item in state.get("paper_digests", [])}
        selected_paper_ids = set(state.get("selected_paper_ids", []))
        source_by_external_id = {row.provider_source_id: row for row in source_rows}
        source_ids: dict[str, UUID] = {row.provider_source_id: row.id for row in source_rows}
        document_rows = list((await session.scalars(select(Document).where(Document.source_id.in_([row.id for row in source_rows])))).all()) if source_rows else []
        document_by_source = {row.source_id: row for row in document_rows}
        document_ids: dict[UUID, UUID] = {row.source_id: row.id for row in document_rows}
        for source_data in sources:
            external_id = source_data.source_id
            provider, _, _ = external_id.partition(":")
            provider = source_data.provider or provider
            source_row = source_by_external_id.get(external_id)
            if source_row is None:
                source_row = Source(research_id=research_id, provider=provider, provider_source_id=external_id, title=source_data.title, authors=source_data.authors, publication_year=source_data.publication_year, url=source_data.url, metadata_json={**source_data.raw_metadata, **({"_tracereview_digest": digests[external_id]} if external_id in digests else {})}, retrieved_at=source_data.retrieved_at)
                session.add(source_row)
                await session.flush()
                source_rows.append(source_row)
                source_by_external_id[external_id] = source_row
                source_ids[external_id] = source_row.id
            else:
                source_row.title = source_data.title
                source_row.authors = source_data.authors
                source_row.publication_year = source_data.publication_year
                source_row.url = source_data.url
                source_row.metadata_json = {**source_data.raw_metadata, **({"_tracereview_digest": digests[external_id]} if external_id in digests else {}), **({"_tracereview_selected": True} if external_id in selected_paper_ids else {})}
            document = document_by_source.get(source_row.id)
            if document is None:
                document = Document(source_id=source_row.id, abstract=source_data.abstract, full_text_sections=_json(source_data.full_text_sections), content_hash=hashlib.sha256((source_data.abstract + json.dumps(_json(source_data.full_text_sections), sort_keys=True)).encode()).hexdigest() if source_data.abstract or source_data.full_text_sections else None)
                session.add(document)
                await session.flush()
            else:
                document.abstract = source_data.abstract
                document.full_text_sections = _json(source_data.full_text_sections)
                document.content_hash = hashlib.sha256((source_data.abstract + json.dumps(_json(source_data.full_text_sections), sort_keys=True)).encode()).hexdigest() if source_data.abstract or source_data.full_text_sections else None
            document_ids[source_row.id] = document.id
            document_by_source[source_row.id] = document

        evidence_rows = list((await session.scalars(select(Evidence).where(Evidence.research_id == research_id))).all())
        evidence_by_external_id = {row.external_evidence_id: row for row in evidence_rows}
        evidence_ids: dict[str, UUID] = {row.external_evidence_id: row.id for row in evidence_rows}
        for item in evidence_items:
            source_id = source_ids.get(item.source_id)
            document_id = document_ids.get(source_id) if source_id else None
            if document_id is None:
                continue
            evidence_row = evidence_by_external_id.get(item.evidence_id)
            if evidence_row is None:
                evidence_row = Evidence(research_id=research_id, document_id=document_id, subquestion_id=subquestion_ids.get(item.subquestion), external_evidence_id=item.evidence_id, text=item.text, relevance=item.relevance, evidence_type=item.evidence_type, evidence_level=item.evidence_level, source_part=item.source_part, limitations=item.limitations)
                session.add(evidence_row)
                await session.flush()
                evidence_rows.append(evidence_row)
                evidence_by_external_id[item.evidence_id] = evidence_row
                evidence_ids[item.evidence_id] = evidence_row.id
            else:
                evidence_row.document_id = document_id
                evidence_row.subquestion_id = subquestion_ids.get(item.subquestion)
                evidence_row.text = item.text
                evidence_row.relevance = item.relevance
                evidence_row.evidence_type = item.evidence_type
                evidence_row.evidence_level = item.evidence_level
                evidence_row.source_part = item.source_part
                evidence_row.limitations = item.limitations

        claim_rows = list((await session.scalars(select(Claim).where(Claim.research_id == research_id))).all())
        claim_by_external_id = {row.external_claim_id: row for row in claim_rows}
        for item in claims:
            claim_row = claim_by_external_id.get(item.claim_id)
            if claim_row is None:
                claim_row = Claim(research_id=research_id, subquestion_id=subquestion_ids.get(item.subquestion), external_claim_id=item.claim_id, text=item.text, verification_status=getattr(item, "verification_status", "candidate"), confidence=None, limitations=getattr(item, "limitations", []))
                session.add(claim_row)
                await session.flush()
                claim_rows.append(claim_row)
                claim_by_external_id[item.claim_id] = claim_row
            else:
                claim_row.subquestion_id = subquestion_ids.get(item.subquestion)
                claim_row.text = item.text
                claim_row.verification_status = getattr(item, "verification_status", "candidate")
                claim_row.confidence = None
                claim_row.limitations = getattr(item, "limitations", [])
            existing_links = set((await session.scalars(select(ClaimEvidence.evidence_id).where(ClaimEvidence.claim_id == claim_row.id))).all())
            for external_evidence_id in item.evidence_ids:
                linked_evidence_id = evidence_ids.get(external_evidence_id)
                if linked_evidence_id and linked_evidence_id not in existing_links:
                    session.add(ClaimEvidence(claim_id=claim_row.id, evidence_id=linked_evidence_id))
                    existing_links.add(linked_evidence_id)
            verification = getattr(item, "verification", None)
            if verification:
                verification_result = await session.scalar(select(VerificationResult).where(VerificationResult.claim_id == claim_row.id, VerificationResult.verifier == verification.verifier).order_by(VerificationResult.created_at.desc()))
                if verification_result is None:
                    verification_result = VerificationResult(claim_id=claim_row.id, verifier=verification.verifier, verification_status=verification.verification_status, confidence=None, evidence_assessment=verification.evidence_assessment, evidence_types=verification.evidence_types, evidence_levels=verification.evidence_levels, limitations=verification.limitations, contradictions=verification.contradictions, additional_source_required=verification.additional_source_required)
                    session.add(verification_result)
                else:
                    verification_result.verification_status = verification.verification_status
                    verification_result.confidence = None
                    verification_result.evidence_assessment = verification.evidence_assessment
                    verification_result.evidence_types = verification.evidence_types
                    verification_result.evidence_levels = verification.evidence_levels
                    verification_result.limitations = verification.limitations
                    verification_result.contradictions = verification.contradictions
                    verification_result.additional_source_required = verification.additional_source_required

        existing_event_ids = set((await session.scalars(select(AgentEvent.external_event_id).where(AgentEvent.research_id == research_id))).all())
        for event in audit_log:
            event_id = _value(event, "event_id")
            if not event_id or event_id in existing_event_ids:
                continue
            details = _json(_value(event, "details", {}))
            usage = details.get("token_usage") or {}
            session.add(
                AgentEvent(
                    research_id=research_id,
                    external_event_id=event_id,
                    node=_value(event, "node", "workflow"),
                    action=_value(event, "action", "event"),
                    input_refs=_json(_value(event, "input_refs", [])),
                    output_refs=_json(_value(event, "output_refs", [])),
                    details=details,
                    latency_ms=details.get("latency_ms") or (latency_ms if event is latest_event else None),
                    prompt_tokens=usage.get("input_tokens") or usage.get("prompt_tokens"),
                    completion_tokens=usage.get("output_tokens") or usage.get("completion_tokens"),
                    estimated_cost_usd=None,
                    created_at=_value(event, "timestamp", datetime.now(UTC)),
                )
            )
            existing_event_ids.add(event_id)

        total_usage = {"input_tokens": 0, "output_tokens": 0}
        for event in audit_log:
            usage = _value(event, "details", {}).get("token_usage") or {}
            total_usage["input_tokens"] += usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
            total_usage["output_tokens"] += usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        run.prompt_tokens = total_usage["input_tokens"] or None
        run.completion_tokens = total_usage["output_tokens"] or None
        run.total_tokens = sum(total_usage.values()) or None

        report = state.get("final_report")
        if report:
            report_data = _json(report)
            markdown = _report_markdown(report_data)
            generated_at = _report_generated_at(report, report_data)
            report_row = await session.scalar(select(Report).where(Report.research_id == research_id))
            if report_row is None:
                session.add(Report(research_id=research_id, report_json=report_data, markdown=markdown, generated_at=generated_at))
            else:
                report_row.report_json = report_data
                report_row.markdown = markdown
                report_row.generated_at = generated_at


def _report_markdown(report: dict) -> str:
    if report.get("report_type") == "paper_digest_review":
        lines = [f"# TraceReview Paper Digest\n\n**Research question:** {report.get('research_question', '')}", "", report.get("executive_summary", ""), "", "## Research method"]
        method = report.get("research_method", {})
        lines.extend([f"- **Sources searched:** {', '.join(method.get('sources_searched', []))}", f"- **Search strategy:** {method.get('search_strategy', '')}", f"- **Retrieval:** {method.get('retrieval_process', '')}", f"- **Digest method:** {method.get('digest_process', '')}", "", "## Paper cards"])
        for paper in report.get("papers", []):
            source, digest = paper.get("source", {}), paper.get("digest", {})
            authors = ", ".join(source.get("authors", []))
            lines.extend([f"### [{paper.get('reference_number')}] {source.get('title', '')}", f"{authors} ({source.get('publication_year') or 'Year unavailable'}). [{source.get('provider', '')}]({source.get('url', '')})", "", f"**What this study did — AI summary of the abstract:** {digest.get('what_study_did', '')}", f"**Study type:** {digest.get('study_type', 'unclear')}", f"**Why it matches — retrieval note:** {digest.get('why_it_matches', '')}", "", "**Key finding excerpts (verbatim, checked against source text):**"])
            lines.extend([f"> {quote.get('text', '')} ({quote.get('source_part', '')})" for quote in digest.get("key_findings", [])] or ["No verbatim finding quote was validated."])
            if digest.get("authors_conclusion"):
                lines.extend(["", "**Abstract's final sentence (verbatim; read in context):**", f"> {digest['authors_conclusion']}"])
            lines.append("")
        lines.extend(["## Notes", *[f"- {note}" for note in report.get("notes", [])]])
        return "\n".join(lines) + "\n"
    coverage = report.get("coverage", {})
    lines = [
        f"# TraceReview Research Report\n\n**Research question:** {report.get('research_question', '')}",
        "",
        f"**Outcome:** `{report.get('outcome', 'inconclusive_low_coverage')}`",
        f"**Coverage:** {coverage.get('retrieved', 0)} retrieved; {coverage.get('screen_excluded', 0)} screened out; {coverage.get('assessed', 0)} of {coverage.get('extraction_candidates', 0)} relevant records assessed ({coverage.get('extraction_coverage_percent', 0)}%); {coverage.get('unassessed', 0)} relevant records unassessed.",
        "",
        "## Executive Summary",
        report.get("executive_summary", ""),
        "",
        "## Research Method",
    ]
    method = report.get("research_method", {})
    lines.extend([f"- **Sources searched:** {', '.join(method.get('sources_searched', []))}", f"- **Search strategy:** {method.get('search_strategy', '')}", f"- **Retrieval:** {method.get('retrieval_process', '')}", f"- **Verification:** {method.get('verification_methodology', '')}", "", "## Findings"])
    for section in report.get("findings", []):
        lines.extend([f"### {section.get('subquestion', '')}", section.get("text", ""), ""])
    lines.extend(["## Evidence Assessment"])
    for item in report.get("evidence_assessment", []):
        lines.extend([f"- **{item.get('claim_id')} — {item.get('verification')}:** {item.get('claim')}", f"  - Evidence: {', '.join(item.get('evidence_ids', []))}; sources: {', '.join(item.get('source_ids', []))}; level: {', '.join(item.get('evidence_level', []))}; source part: {', '.join(item.get('source_parts', []))}"])
    conflicts = [f"- {item}" for item in report.get("conflicting_evidence", [])] or ["- None identified."]
    gaps = [f"- {item}" for item in report.get("research_gaps", [])] or ["- None identified."]
    lines.extend(["", "## Conflicting Evidence", *conflicts, "", "## Research Gaps", *gaps, "", "## References"])
    for index, source in enumerate(report.get("references", []), 1):
        authors = ", ".join(source.get("authors", []))
        year = source.get("publication_year") or "n.d."
        lines.append(f"{index}. {authors} ({year}). {source.get('title', '')}. [{source.get('provider', '')}]({source.get('url', '')})")
    return "\n".join(lines) + "\n"


async def _run_row(session: Any, research_id: UUID) -> ResearchRun | None:
    return await session.get(ResearchRun, research_id)


async def get_research(research_id: UUID) -> dict | None:
    async with Session() as session:
        run = await _run_row(session, research_id)
        if run is None:
            return None
        question = await session.get(ResearchQuestion, run.question_id)
        return {"research_id": str(run.id), "session_id": str(run.session_id), "question": question.question if question else "", "status": run.status, "progress": run.progress, "error": run.error, "latency_ms": run.latency_ms, "token_usage": {"prompt_tokens": run.prompt_tokens, "completion_tokens": run.completion_tokens, "total_tokens": run.total_tokens}, "estimated_cost_usd": str(run.estimated_cost_usd) if run.estimated_cost_usd is not None else None, "created_at": run.created_at, "updated_at": run.updated_at}


async def get_status(research_id: UUID) -> dict | None:
    research = await get_research(research_id)
    if research is None:
        return None
    return {key: research[key] for key in ("research_id", "status", "progress", "error", "latency_ms", "token_usage", "estimated_cost_usd", "updated_at")}


async def get_plan(research_id: UUID) -> dict | None:
    async with Session() as session:
        plan = await session.scalar(select(ResearchPlan).where(ResearchPlan.research_id == research_id))
        if plan is None:
            return None
        questions = list((await session.scalars(select(Subquestion).where(Subquestion.plan_id == plan.id).order_by(Subquestion.position))).all())
        return {"objective": plan.objective, "source_types": plan.source_types, "search_strategy": plan.search_strategy, "search_queries": plan.search_queries, "subquestions": [{"id": str(item.id), "text": item.text, "position": item.position} for item in questions]}


async def get_sources(research_id: UUID) -> list[dict] | None:
    async with Session() as session:
        run = await _run_row(session, research_id)
        if run is None:
            return None
        rows = list((await session.scalars(select(Source).where(Source.research_id == research_id).order_by(Source.provider, Source.title))).all())
        ids = [row.id for row in rows]
        docs = list((await session.scalars(select(Document).where(Document.source_id.in_(ids)))).all()) if ids else []
        doc_by_source = {doc.source_id: doc for doc in docs}
        counts = dict((await session.execute(select(Evidence.document_id, func.count(Evidence.id)).where(Evidence.research_id == research_id).group_by(Evidence.document_id))).all())
        return [{"id": str(row.id), "source_id": row.provider_source_id, "alternate_source_ids": row.metadata_json.get("alternate_source_ids", []), "alternate_sources": row.metadata_json.get("alternate_sources", []), "relevance_level": row.metadata_json.get("_tracereview_relevance"), "provider": row.provider, "title": row.title, "authors": row.authors, "publication_year": row.publication_year, "url": row.url, "retrieved_at": row.retrieved_at, "abstract": doc_by_source[row.id].abstract if row.id in doc_by_source else "", "available_full_text_parts": list(dict.fromkeys(section.get("source_part") for section in (doc_by_source[row.id].full_text_sections if row.id in doc_by_source else []) if section.get("source_part"))), "evidence_count": counts.get(doc_by_source[row.id].id, 0) if row.id in doc_by_source else 0, "paper_digest": row.metadata_json.get("_tracereview_digest"), "selected_for_review": bool(row.metadata_json.get("_tracereview_selected") or row.metadata_json.get("_tracereview_digest"))} for row in rows]


async def get_evidence(research_id: UUID) -> list[dict] | None:
    async with Session() as session:
        run = await _run_row(session, research_id)
        if run is None:
            return None
        rows = list((await session.scalars(select(Evidence).where(Evidence.research_id == research_id).order_by(Evidence.external_evidence_id))).all())
        docs = {row.id: row for row in (await session.scalars(select(Document).where(Document.id.in_([item.document_id for item in rows])))).all()} if rows else {}
        source_rows = {row.id: row for row in (await session.scalars(select(Source).where(Source.id.in_([doc.source_id for doc in docs.values()])))).all()} if docs else {}
        subquestions = {row.id: row.text for row in (await session.scalars(select(Subquestion).where(Subquestion.id.in_([item.subquestion_id for item in rows if item.subquestion_id])))).all()} if rows else {}
        links = list((await session.scalars(select(ClaimEvidence).where(ClaimEvidence.evidence_id.in_([row.id for row in rows])))).all()) if rows else []
        claims = {row.id: row.external_claim_id for row in (await session.scalars(select(Claim).where(Claim.id.in_([link.claim_id for link in links])))).all()} if links else {}
        support_by_evidence: dict[UUID, list[str]] = {}
        for link in links:
            support_by_evidence.setdefault(link.evidence_id, []).append(claims.get(link.claim_id, ""))
        return [{"evidence_id": row.external_evidence_id, "source": _source_json(source_rows.get(docs[row.document_id].source_id)), "subquestion": subquestions.get(row.subquestion_id) if row.subquestion_id else None, "text": row.text, "source_part": row.source_part, "evidence_level": row.evidence_level, "relevance": row.relevance, "evidence_type": row.evidence_type, "supports": support_by_evidence.get(row.id, []), "limitations": row.limitations} for row in rows]


def _source_json(source: Source | None) -> dict | None:
    if source is None:
        return None
    return {"source_id": source.provider_source_id, "provider": source.provider, "title": source.title, "authors": source.authors, "publication_year": source.publication_year, "url": source.url}


async def get_claims(research_id: UUID) -> list[dict] | None:
    async with Session() as session:
        run = await _run_row(session, research_id)
        if run is None:
            return None
        rows = list((await session.scalars(select(Claim).where(Claim.research_id == research_id).order_by(Claim.external_claim_id))).all())
        links = list((await session.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id.in_([row.id for row in rows])))).all()) if rows else []
        evidence_by_id = {row.id: row for row in (await session.scalars(select(Evidence).where(Evidence.id.in_([link.evidence_id for link in links])))).all()} if links else {}
        doc_ids = [row.document_id for row in evidence_by_id.values()]
        docs = {row.id: row for row in (await session.scalars(select(Document).where(Document.id.in_(doc_ids)))).all()} if doc_ids else {}
        sources = {row.id: row for row in (await session.scalars(select(Source).where(Source.id.in_([doc.source_id for doc in docs.values()])))).all()} if docs else {}
        results = list((await session.scalars(select(VerificationResult).where(VerificationResult.claim_id.in_([row.id for row in rows])).order_by(VerificationResult.created_at.desc()))).all()) if rows else []
        verification_by_claim: dict[UUID, VerificationResult] = {}
        for item in results:
            verification_by_claim.setdefault(item.claim_id, item)
        evidence_links: dict[UUID, list[dict]] = {}
        for link in links:
            evidence = evidence_by_id.get(link.evidence_id)
            if evidence:
                source = sources.get(docs[evidence.document_id].source_id) if evidence.document_id in docs else None
                evidence_links.setdefault(link.claim_id, []).append({"evidence_id": evidence.external_evidence_id, "text": evidence.text, "source_part": evidence.source_part, "evidence_level": evidence.evidence_level, "evidence_type": evidence.evidence_type, "source": _source_json(source), "relationship": link.relationship_type})
        output = []
        for row in rows:
            verification = verification_by_claim.get(row.id)
            output.append({"claim_id": row.external_claim_id, "text": row.text, "verification_status": row.verification_status, "limitations": row.limitations, "evidence": evidence_links.get(row.id, []), "verification": {"verifier": verification.verifier, "status": verification.verification_status, "assessment": verification.evidence_assessment, "evidence_types": verification.evidence_types, "evidence_levels": verification.evidence_levels, "limitations": verification.limitations, "contradictions": verification.contradictions, "additional_source_required": verification.additional_source_required} if verification else None})
        return output


async def get_audit(research_id: UUID) -> list[dict] | None:
    async with Session() as session:
        run = await _run_row(session, research_id)
        if run is None:
            return None
        rows = list((await session.scalars(select(AgentEvent).where(AgentEvent.research_id == research_id).order_by(AgentEvent.created_at, AgentEvent.id))).all())
        return [{"event_id": row.external_event_id, "node": row.node, "action": row.action, "input_refs": row.input_refs, "output_refs": row.output_refs, "details": _without_confidence(row.details), "latency_ms": row.latency_ms, "prompt_tokens": row.prompt_tokens, "completion_tokens": row.completion_tokens, "estimated_cost_usd": str(row.estimated_cost_usd) if row.estimated_cost_usd is not None else None, "timestamp": row.created_at} for row in rows]


async def get_report(research_id: UUID) -> dict | None:
    async with Session() as session:
        run = await _run_row(session, research_id)
        if run is None:
            return None
        report = await session.scalar(select(Report).where(Report.research_id == research_id))
        return {"report": _without_confidence(report.report_json), "markdown": report.markdown, "generated_at": report.generated_at} if report else None
