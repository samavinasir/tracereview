import html
import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


def now_utc() -> datetime:
    return datetime.now(UTC)


def clean_source_text(value: str) -> str:
    """Decode and remove HTML/JATS markup while preserving its readable text."""
    text = value or ""
    for _ in range(2):
        text = html.unescape(text)
    text = re.sub(r"(?i)</?(?:jats:)?(?:p|div|br|li|sec|title|h[1-6])\b[^>]*>", " ", text)
    text = re.sub(r"<[^>]*>", "", text)
    return " ".join(text.split())


class ResearchPlan(BaseModel):
    objective: str
    subquestions: list[str]
    source_types: list[str]
    search_strategy: str


class SearchQuery(BaseModel):
    query_id: str = Field(max_length=80)
    subquestion: str = Field(max_length=1000)
    query: str = Field(min_length=1, max_length=500)
    source_names: list[str] = Field(min_length=1, max_length=5)
    must_contain_any: list[str] = Field(default_factory=list, max_length=12)


class SourceSection(BaseModel):
    source_part: Literal["methods", "results"]
    title: str = Field(default="", max_length=300)
    text: str = Field(max_length=20000)

    @field_validator("title", "text", mode="before")
    @classmethod
    def clean_passage_markup(cls, value: str) -> str:
        return clean_source_text(value) if isinstance(value, str) else value


class SourceRecord(BaseModel):
    source_id: str = Field(max_length=500)
    provider: str = Field(max_length=80)
    title: str = Field(max_length=2000)
    authors: list[str] = Field(default_factory=list, max_length=50)
    publication_year: int | None = None
    url: str = Field(max_length=2000)
    abstract: str = Field(default="", max_length=12000)
    full_text_sections: list[SourceSection] = Field(default_factory=list, max_length=40)
    raw_metadata: dict = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=now_utc)

    @field_validator("title", "abstract", mode="before")
    @classmethod
    def clean_bibliographic_markup(cls, value: str) -> str:
        return clean_source_text(value) if isinstance(value, str) else value

    @field_validator("url")
    @classmethod
    def allow_only_https_source_urls(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "https" or not parsed.hostname:
            return ""
        return value.strip()


class PaperQuote(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    source_part: Literal["abstract", "methods", "results"]


class PaperDigest(BaseModel):
    source_id: str
    rank: int = Field(ge=1, le=10)
    what_study_did: str = Field(max_length=1200)
    key_findings: list[PaperQuote] = Field(default_factory=list, max_length=5)
    authors_conclusion: str = Field(default="", max_length=2000)
    conclusion_source: Literal["abstract_last_sentence", "not_available"] = "not_available"
    why_it_matches: str = Field(max_length=500)
    study_type: Literal["experimental", "clinical_observational", "computational", "review", "systematic_review_meta_analysis", "case_report", "other", "unclear"]


class EvidenceItem(BaseModel):
    evidence_id: str
    source_id: str
    subquestion: str
    text: str = Field(max_length=4000)
    relevance: float = Field(ge=0, le=1)
    evidence_type: Literal["experimental", "observational", "computational", "review", "inference", "background", "unknown"]
    evidence_level: Literal["direct", "indirect", "contextual", "inference"]
    source_part: Literal["title", "abstract", "methods", "results"]
    supports: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CandidateClaim(BaseModel):
    claim_id: str
    text: str = Field(max_length=2000)
    subquestion: str
    evidence_ids: list[str]


class ClaimVerification(BaseModel):
    claim_id: str
    verification_status: Literal["verified", "partially_supported", "rejected", "insufficient_evidence", "unverified"]
    evidence_assessment: str
    evidence_types: list[str] = Field(default_factory=list)
    evidence_levels: list[Literal["direct", "indirect", "contextual", "inference"]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    additional_source_required: bool = False
    verifier: str = "evidence_verifier"


class VerifiedClaim(CandidateClaim):
    verification_status: Literal["verified", "partially_supported", "rejected", "insufficient_evidence", "unverified"]
    limitations: list[str] = Field(default_factory=list)
    verification: ClaimVerification


class AuditEvent(BaseModel):
    event_id: str
    run_id: str
    timestamp: datetime = Field(default_factory=now_utc)
    node: str
    action: str
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class ReportSection(BaseModel):
    subquestion: str
    text: str
    claim_ids: list[str]


class ResearchCoverage(BaseModel):
    retrieved: int = Field(ge=0)
    assessable: int = Field(ge=0)
    screened: int = Field(ge=0)
    assessed: int = Field(ge=0)
    unassessed: int = Field(ge=0)
    screen_excluded: int = Field(ge=0)
    retrieved_coverage_percent: float = Field(default=0.0, ge=0, le=100)
    assessable_coverage_percent: float = Field(default=0.0, ge=0, le=100)
    extraction_candidates: int = Field(default=0, ge=0)
    extraction_coverage_percent: float = Field(default=0.0, ge=0, le=100)


class ResearchReport(BaseModel):
    research_question: str
    outcome: Literal["supported", "partially_supported", "no_evidence_in_assessed", "inconclusive_low_coverage", "verification_incomplete"]
    coverage: ResearchCoverage
    executive_summary: str
    research_method: dict
    findings: list[ReportSection]
    evidence_assessment: list[dict]
    conflicting_evidence: list[str]
    research_gaps: list[str]
    references: list[SourceRecord]
    generated_at: datetime = Field(default_factory=now_utc)
