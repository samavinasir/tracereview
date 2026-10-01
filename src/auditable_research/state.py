from typing import Any, TypedDict

from .models import (
    AuditEvent,
    CandidateClaim,
    EvidenceItem,
    PaperDigest,
    ResearchPlan,
    ResearchReport,
    SearchQuery,
    SourceRecord,
    VerifiedClaim,
)


class ResearchState(TypedDict, total=False):
    run_id: str
    research_question: str
    research_plan: ResearchPlan
    subquestions: list[str]
    search_queries: list[SearchQuery]
    current_search_queries: list[SearchQuery]
    retrieved_sources: list[SourceRecord]
    new_source_ids: list[str]
    source_contexts: dict[str, list[dict[str, Any]]]
    ranked_source_ids: list[str]
    screen_queue_ids: list[str]
    screen_queue_relevant_ids: list[str]
    screen_queue_initialized: bool
    active_screening_batch_size: int
    screened_source_ids: list[str]
    screen_decisions: dict[str, dict[str, Any]]
    assessed_source_ids: list[str]
    failed_source_ids: list[str]
    active_batch_size: int
    search_round: int
    rate_limited_models: list[str]
    digest_fallback_unavailable: bool
    evidence_items: list[EvidenceItem]
    paper_digests: list[PaperDigest]
    executive_summary: str
    selected_paper_ids: list[str]
    candidate_claims: list[CandidateClaim]
    verified_claims: list[VerifiedClaim]
    contradictions: list[str]
    research_gaps: list[str]
    final_report: ResearchReport | dict[str, Any]
    research_outcome: str
    audit_log: list[AuditEvent]
    errors: list[str]
    warnings: list[str]
    metadata: dict[str, Any]
