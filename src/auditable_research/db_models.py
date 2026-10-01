from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ResearchSession(Base):
    __tablename__ = "research_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ResearchQuestion(Base):
    __tablename__ = "research_questions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("research_questions.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ResearchPlan(Base):
    __tablename__ = "research_plans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), unique=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    source_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    search_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    search_queries: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Subquestion(Base):
    __tablename__ = "subquestions"
    __table_args__ = (UniqueConstraint("plan_id", "position", name="uq_subquestion_plan_position"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("research_plans.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("research_id", "provider", "provider_source_id", name="uq_source_provider_identity"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_source_id: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), unique=True)
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    full_text_sections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PaperDigestCache(Base):
    __tablename__ = "paper_digest_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_identity: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    digest_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


Index("ix_documents_embedding_hnsw", Document.embedding, postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("research_id", "external_evidence_id", name="uq_evidence_run_external_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    subquestion_id: Mapped[UUID | None] = mapped_column(ForeignKey("subquestions.id", ondelete="SET NULL"), index=True)
    external_evidence_id: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    relevance: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(24), nullable=False, default="contextual")
    source_part: Mapped[str] = mapped_column(String(24), nullable=False, default="abstract")
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("research_id", "external_claim_id", name="uq_claim_run_external_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    subquestion_id: Mapped[UUID | None] = mapped_column(ForeignKey("subquestions.id", ondelete="SET NULL"), index=True)
    external_claim_id: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False, default="candidate")
    confidence: Mapped[float | None] = mapped_column(Float)
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False, default="supports")


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    verifier: Mapped[str] = mapped_column(String(120), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False)
    # Retained as a nullable compatibility column; current verification never
    # generates or presents an uncalibrated numeric confidence value.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence_levels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    contradictions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    additional_source_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("research_id", "external_event_id", name="uq_event_run_external_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), index=True)
    external_event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    node: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    input_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    research_id: Mapped[UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"), unique=True)
    report_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
