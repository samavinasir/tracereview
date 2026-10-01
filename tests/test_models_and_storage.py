from uuid import UUID

import pytest
from pydantic import ValidationError

from auditable_research import storage
from auditable_research.db_models import ResearchQuestion, ResearchRun, ResearchSession
from auditable_research.models import CandidateClaim, ClaimVerification, EvidenceItem, SourceRecord


def test_claim_verification_schema_has_no_confidence_score() -> None:
    schema = ClaimVerification.model_json_schema()
    assert "confidence" not in schema["properties"]
    with pytest.raises(ValidationError):
        ClaimVerification.model_validate({"claim_id": "CLM-1", "verification_status": "certain", "evidence_assessment": "unsupported"})


def test_evidence_requires_bounded_relevance_and_claim_text() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(evidence_id="EV-1", source_id="SRC-1", subquestion="Q", text="Excerpt", relevance=1.2, evidence_type="experimental")
    with pytest.raises(ValidationError):
        CandidateClaim(claim_id="CLM-1", text="x" * 2001, subquestion="Q", evidence_ids=[])


def test_source_urls_only_allow_https() -> None:
    source = SourceRecord(source_id="SRC-1", provider="pubmed", title="Study", url="javascript:alert(1)")
    assert source.url == ""


@pytest.mark.asyncio
async def test_create_research_flushes_parent_rows_before_children(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTransaction:
        def __init__(self, session: "FakeSession") -> None:
            self.session = session

        async def __aenter__(self) -> "FakeSession":
            return self.session

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.pending: list[object] = []
            self.inserted: list[type[object]] = []

        def begin(self) -> FakeTransaction:
            return FakeTransaction(self)

        def add(self, value: object) -> None:
            self.pending.append(value)

        async def flush(self) -> None:
            self.inserted.extend(type(item) for item in self.pending)
            self.pending.clear()

    session = FakeSession()

    class FakeSessionFactory:
        def begin(self) -> FakeTransaction:
            return session.begin()

    monkeypatch.setattr(storage, "Session", FakeSessionFactory())

    research_id = await storage.create_research("A sufficiently long research question")

    assert isinstance(research_id, UUID)
    assert session.inserted == [ResearchSession, ResearchQuestion, ResearchRun]
