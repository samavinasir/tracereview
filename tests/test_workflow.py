import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest

from auditable_research import api as api_module
from auditable_research import graph
from auditable_research.agents import (
    ClaimDraft,
    EvidenceDraft,
    ExtractionOutput,
    GroqRateLimited,
    PaperDigestDraft,
    PaperDigestOutput,
    PlanOutput,
    ScreeningOutput,
    VerificationOutput,
    _coerce_paper_digest_output,
)
from auditable_research.models import (
    CandidateClaim,
    ClaimVerification,
    EvidenceItem,
    ResearchCoverage,
    SearchQuery,
    SourceRecord,
    SourceSection,
)
from auditable_research.storage import _report_generated_at, _report_markdown


class FakeTool:
    name = "pubmed"

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        return [SourceRecord(source_id="pubmed:123", provider="pubmed", title="Resistance study", url="https://example.org/study", abstract="The strain showed resistance in a controlled assay. The researchers measured susceptibility outcomes in multiple isolate groups to assess treatment response across several treatment conditions and independent laboratory repeats. These observations were recorded for later comparison.", publication_year=2024)]


class FailingTool:
    name = "openalex"

    async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
        raise RuntimeError("mock provider unavailable")


def test_source_markup_is_cleaned_before_quote_matching() -> None:
    source = SourceRecord(source_id="crossref:doi", provider="crossref", title="&lt;i&gt;Klebsiella pneumoniae&lt;/i&gt; study", url="https://example.org", abstract="&lt;jats:p&gt;Loss of &lt;i&gt;OmpK36&lt;/i&gt; altered susceptibility.&lt;/jats:p&gt; The final &lt;i&gt;bla&lt;/i&gt;&lt;sub&gt;KPC-2&lt;/sub&gt; sentence.&lt;/jats:p&gt;")
    assert source.title == "Klebsiella pneumoniae study"
    assert "<" not in source.abstract and "jats" not in source.abstract
    assert "blaKPC-2" in source.abstract
    assert graph._abstract_last_sentence(source.abstract) == "The final blaKPC-2 sentence."


def test_sources_deduplicate_on_pmid_keep_best_abstract_and_both_links() -> None:
    shorter = SourceRecord(source_id="pubmed:41798751", provider="pubmed", title="Same study", url="https://pubmed.ncbi.nlm.nih.gov/41798751/", abstract="A short abstract. Study result.", raw_metadata={"uid": "41798751"})
    richer = SourceRecord(source_id="europe_pmc:41798751", provider="europe_pmc", title="Same study record", url="https://europepmc.org/article/MED/41798751", abstract="This is the more complete abstract for the exact same biomedical study, identified through its PMID and describing methods and findings in enough detail.", raw_metadata={"pmid": "41798751"})
    deduped, aliases = graph._dedupe_sources([shorter, richer])
    assert len(deduped) == 1
    assert deduped[0].source_id == richer.source_id
    assert aliases[shorter.source_id] == richer.source_id
    assert any(link["url"] == shorter.url for link in deduped[0].raw_metadata["alternate_sources"])


def test_paper_candidates_drop_short_abstracts_and_theses() -> None:
    short = SourceRecord(source_id="pubmed:short", provider="pubmed", title="Short abstract", url="https://example.org", abstract="Relevant but short.")
    thesis = SourceRecord(source_id="openalex:thesis", provider="openalex", title="A thesis on porin loss", url="https://example.org", abstract="Relevant findings are described here. " * 8)
    typed_thesis = SourceRecord(source_id="pubmed:typed-thesis", provider="pubmed", title="Porin loss in infection", url="https://example.org", abstract="Relevant findings are described here. " * 8, raw_metadata={"pubtype": "Thesis"})
    assert not graph._eligible_paper_record(short)
    assert not graph._eligible_paper_record(thesis)
    assert not graph._eligible_paper_record(typed_thesis)


def test_relevance_note_is_neutralized_when_it_claims_a_result() -> None:
    source = SourceRecord(source_id="pmid:1", provider="pubmed", title="OmpK36 deficiency and carbapenem susceptibility", url="https://example.org", abstract="The study examines OmpK36 and carbapenem susceptibility in multiple isolates.")
    note = graph._safe_relevance_note("Demonstrates that independent loss causes resistance", source, "OmpK36 independent carbapenem resistance")
    assert note.startswith("Related to: ")
    assert "demonstrates" not in note.casefold()


def test_sentence_fallback_selects_question_relevant_verbatim_sentences() -> None:
    abstract = "The cohort included multiple clinical isolates. OmpK36 loss was measured alongside carbapenem susceptibility. The study reports annual surveillance results."
    quotes = graph._fallback_abstract_quotes(abstract, "OmpK36 carbapenem susceptibility")
    assert len(quotes) == 2
    assert quotes[1].text == "OmpK36 loss was measured alongside carbapenem susceptibility."


@pytest.mark.asyncio
async def test_partial_review_with_cards_is_completed_not_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = graph.PaperDigest(source_id="pubmed:1", rank=1, what_study_did="Study summary", key_findings=[], authors_conclusion="Authors' words.", conclusion_source="abstract_last_sentence", why_it_matches="Examines the topic.", study_type="experimental")

    class PartialGraph:
        async def astream(self, initial: dict[str, Any], **_: Any):
            yield {**initial, "selected_paper_ids": ["pubmed:1", "pubmed:2"], "paper_digests": [digest], "assessed_source_ids": ["pubmed:1"], "failed_source_ids": ["pubmed:2"]}

    saved: list[tuple[str, str | None, list[str]]] = []

    async def fake_save(_id: Any, _question: str, state: dict[str, Any], status: str, **kwargs: Any) -> None:
        saved.append((status, kwargs.get("error"), list(state.get("warnings", []))))

    monkeypatch.setattr(api_module, "research_graph", PartialGraph())
    monkeypatch.setattr(api_module, "save_run", fake_save)
    await api_module._run_workflow(uuid4(), "A focused research question")
    assert saved[-1][0] == "completed"
    assert saved[-1][1] is None
    assert sum("Review incomplete" in warning for warning in saved[-1][2]) == 1


@pytest.mark.asyncio
async def test_end_to_end_graph_with_mocked_llm_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "min_papers_per_review", 1)
    async def no_cache_read(keys: list[str]) -> dict[str, dict]:
        return {}

    async def no_cache_write(entries: list[dict[str, Any]]) -> None:
        return None

    monkeypatch.setattr(graph, "get_cached_paper_digests", no_cache_read)
    monkeypatch.setattr(graph, "store_cached_paper_digests", no_cache_write)
    async def fake_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None, **kwargs: Any) -> tuple[Any, dict[str, int]]:
        if schema is PlanOutput:
            return PlanOutput(objective="Assess experimental evidence", subquestions=["Which experiments support resistance?"], source_types=["primary research"], search_strategy="Search public databases", queries=[SearchQuery(query_id="Q1", subquestion="Which experiments support resistance?", query="controlled assay resistance", source_names=["openalex", "pubmed"])]), {"input_tokens": 10, "output_tokens": 10}
        if schema is PaperDigestOutput:
            payload = json.loads(messages[1][1])
            record = payload["untrusted_papers"][0]
            return PaperDigestOutput(papers=[PaperDigestDraft(source_id=record["source_id"], what_study_did="The study assessed resistance in a controlled assay.", key_findings=["The strain showed resistance in a controlled assay."], why_it_matches="It examines experimental resistance.", study_type="experimental")]), {"input_tokens": 20, "output_tokens": 20}
        raise AssertionError(f"Unexpected structured output schema: {schema}")

    monkeypatch.setattr(graph, "invoke_structured", fake_invoke)
    monkeypatch.setattr(graph, "TOOLS", {"openalex": FailingTool(), "pubmed": FakeTool()})
    workflow = graph.build_graph()
    final = await workflow.ainvoke({"run_id": "test-run", "research_question": "What experimental evidence supports resistance?", "audit_log": [], "errors": [], "warnings": [], "metadata": {}})

    assert [event.action for event in final["audit_log"]][-3:] == ["created_paper_digests", "created_executive_summary", "generated_paper_digest_report"]
    assert any("OpenAlex was unavailable" in warning and "responding sources" in warning for warning in final["warnings"])
    assert len(final["paper_digests"]) == 1
    digest = final["paper_digests"][0]
    assert digest.key_findings[0].text == "The strain showed resistance in a controlled assay."
    assert digest.authors_conclusion == "These observations were recorded for later comparison."
    assert digest.conclusion_source == "abstract_last_sentence"
    assert "Authors et al." not in final["final_report"]["executive_summary"]
    assert "These observations were recorded for later comparison." in final["final_report"]["executive_summary"]
    assert final["final_report"]["coverage"]["reviewed_records"] == 1
    markdown = _report_markdown(final["final_report"])
    assert "Paper cards" in markdown
    assert "abstract's final sentence" in markdown.lower()
    assert "https://example.org/study" in markdown


@pytest.mark.asyncio
async def test_extraction_rejects_nonverbatim_model_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    source = SourceRecord(source_id="pubmed:123", provider="pubmed", title="Study", url="https://example.org", abstract="Exact source wording.")

    async def fake_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None) -> tuple[Any, dict[str, int]]:
        return ExtractionOutput(evidence=[EvidenceDraft(source_id="pubmed:123", subquestion="Q", text="A fabricated paraphrase.", source_part="abstract", evidence_level="direct", evidence_type="experimental")], claims=[ClaimDraft(text="Claim based on fabricated excerpt", subquestion="Q", evidence_indexes=[0])], research_gaps=[]), {}

    monkeypatch.setattr(graph, "invoke_structured", fake_invoke)
    state = {"run_id": "test", "retrieved_sources": [source], "subquestions": ["Q"], "search_queries": [], "audit_log": [], "errors": [], "metadata": {}}

    state.update({"source_contexts": [{"source_id": source.source_id, "query": "Q", "subquestion": "Q"}], "ranked_source_ids": [source.source_id], "assessed_source_ids": [], "screened_source_ids": [source.source_id], "active_batch_size": 1})
    result = await graph.extract_evidence_batch(state)  # type: ignore[arg-type]

    assert result["evidence_items"] == []
    assert result["candidate_claims"] == []


@pytest.mark.asyncio
async def test_extraction_falls_back_to_configured_model_after_primary_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    source = SourceRecord(source_id="pubmed:123", provider="pubmed", title="Study", url="https://example.org", abstract="Exact source wording supports resistance.")
    fallback_model = "test-fallback-model"
    monkeypatch.setattr(graph.settings, "groq_fallback_model", fallback_model)

    async def fake_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None, **kwargs: Any) -> tuple[Any, dict[str, str]]:
        assert model_name == fallback_model
        return ExtractionOutput(evidence=[EvidenceDraft(source_id=source.source_id, subquestion="Q", text=source.abstract, source_part="abstract", evidence_level="indirect", evidence_type="observational")], claims=[], research_gaps=[]), {"model": fallback_model}

    monkeypatch.setattr(graph, "invoke_structured", fake_invoke)
    state = {"run_id": "fallback-test", "research_question": "Q", "retrieved_sources": [source], "subquestions": ["Q"], "source_contexts": {}, "ranked_source_ids": [source.source_id], "assessed_source_ids": [], "failed_source_ids": [], "rate_limited_models": [graph.settings.groq_model], "audit_log": [], "warnings": []}

    result = await graph.extract_evidence_batch(state)  # type: ignore[arg-type]

    assert len(result["evidence_items"]) == 1
    assert result["assessed_source_ids"] == [source.source_id]
    assert graph.settings.groq_model in result["rate_limited_models"]
    assert "fallback model" in result["warnings"][-1]
    assert result["audit_log"][0].details["model"] == fallback_model
    assert result["audit_log"][0].details["fallback_used"] is True


@pytest.mark.asyncio
async def test_paper_digest_discards_quotes_not_found_in_supplied_source(monkeypatch: pytest.MonkeyPatch) -> None:
    source = SourceRecord(source_id="pubmed:456", provider="pubmed", title="Study", url="https://example.org", abstract="The authors measured susceptibility in three isolates.")

    async def fake_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None, **kwargs: Any) -> tuple[Any, dict[str, int]]:
        return PaperDigestOutput(papers=[PaperDigestDraft(source_id=source.source_id, what_study_did="The study measured susceptibility.", key_findings=["The treatment cured every patient."], why_it_matches="It discusses susceptibility.", study_type="clinical_observational")]), {}

    monkeypatch.setattr(graph, "invoke_structured", fake_invoke)
    monkeypatch.setattr(graph, "get_cached_paper_digests", lambda keys: asyncio.sleep(0, result={}))
    monkeypatch.setattr(graph, "store_cached_paper_digests", lambda entries: asyncio.sleep(0))
    monkeypatch.setattr(graph.settings, "max_papers_per_review", 8)
    state = {"run_id": "quote-check", "research_question": "susceptibility in isolates", "retrieved_sources": [source], "selected_paper_ids": [source.source_id], "assessed_source_ids": [], "failed_source_ids": [], "paper_digests": [], "rate_limited_models": [], "warnings": [], "audit_log": []}
    result = await graph.digest_papers_batch(state)  # type: ignore[arg-type]

    assert [quote.text for quote in result["paper_digests"][0].key_findings] == [source.abstract]
    quote_audit = result["audit_log"][0].details["quote_validation"][source.source_id]
    assert quote_audit["quotes_rejected"] == 1
    assert quote_audit["fallback_quotes"] == 1


def test_paper_route_has_one_bounded_retrieval_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "min_papers_per_review", 5)
    monkeypatch.setattr(graph.settings, "max_search_rounds", 2)
    base = {"selected_paper_ids": ["SRC-1"], "assessed_source_ids": ["SRC-1"], "failed_source_ids": [], "paper_digests": [object(), object()]}

    assert graph._paper_route({**base, "search_round": 1}) == "broaden"  # type: ignore[arg-type]
    assert graph._paper_route({**base, "search_round": 2}) == "report"  # type: ignore[arg-type]
    assert graph._paper_route({**base, "search_round": 1, "paper_digests": [object()] * 5}) == "report"  # type: ignore[arg-type]
    assert graph._paper_route({**base, "search_round": 1, "assessed_source_ids": []}) == "digest"  # type: ignore[arg-type]


def test_paper_route_processes_all_selected_before_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "min_papers_per_review", 3)
    monkeypatch.setattr(graph.settings, "max_search_rounds", 2)
    state = {
        "selected_paper_ids": [f"SRC-{i}" for i in range(10)],
        "assessed_source_ids": [f"SRC-{i}" for i in range(9)],
        "failed_source_ids": [],
        "paper_digests": [object()] * 9,
        "search_round": 1,
    }
    assert graph._paper_route(state) == "digest"  # type: ignore[arg-type]
    state["assessed_source_ids"].append("SRC-9")
    state["paper_digests"].append(object())
    assert graph._paper_route(state) == "report"  # type: ignore[arg-type]


def test_digest_failure_does_not_trigger_search_once_retrieval_cap_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "min_papers_per_review", 3)
    monkeypatch.setattr(graph.settings, "max_records_per_research_run", 10)
    state = {"selected_paper_ids": [f"SRC-{i}" for i in range(10)], "assessed_source_ids": [], "failed_source_ids": [f"SRC-{i}" for i in range(10)], "paper_digests": [], "search_round": 1, "retrieved_sources": [object()] * 10}
    assert graph._paper_route(state) == "report"  # type: ignore[arg-type]
    state["retrieved_sources"] = [object()]
    monkeypatch.setattr(graph.settings, "max_records_per_research_run", 25)
    assert graph._paper_route(state) == "report"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_paper_digest_cache_hit_skips_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    source = SourceRecord(source_id="pubmed:cache1", provider="pubmed", title="Study", url="https://example.org", abstract="Exact quote from this abstract.")
    cached_digest = graph.PaperDigest(source_id=source.source_id, rank=1, what_study_did="Cached paper summary.", key_findings=[graph.PaperQuote(text="Exact quote from this abstract.", source_part="abstract")], authors_conclusion="Exact quote from this abstract.", conclusion_source="abstract_last_sentence", why_it_matches="It matches the topic.", study_type="experimental")
    entry = graph._paper_digest_cache_entry(source, "question about the study", cached_digest)

    async def read_cache(keys: list[str]) -> dict[str, dict]:
        return {entry["cache_key"]: entry["digest_json"]}

    async def unexpected_model(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("A cache hit must avoid an LLM call")

    monkeypatch.setattr(graph, "get_cached_paper_digests", read_cache)
    monkeypatch.setattr(graph, "invoke_structured", unexpected_model)
    state = {"run_id": "cached", "research_question": "question about the study", "retrieved_sources": [source], "selected_paper_ids": [source.source_id], "assessed_source_ids": [], "failed_source_ids": [], "paper_digests": [], "rate_limited_models": [], "warnings": [], "audit_log": []}
    result = await graph.digest_papers_batch(state)  # type: ignore[arg-type]

    assert result["audit_log"][0].action == "loaded_cached_paper_digests"
    assert result["assessed_source_ids"] == [source.source_id]
    assert result["paper_digests"][0].what_study_did == "Cached paper summary."


@pytest.mark.asyncio
async def test_openrouter_schema_failure_opens_digest_fallback_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [SourceRecord(source_id=f"pubmed:{index}", provider="pubmed", title=f"Study {index}", url="https://example.org", abstract="Abstract text.") for index in range(4)]
    calls = {"fallback": 0}

    async def groq_limited(*args: Any, **kwargs: Any) -> Any:
        raise GroqRateLimited("groq-test", 440)

    async def invalid_fallback(*args: Any, **kwargs: Any) -> Any:
        calls["fallback"] += 1
        raise json.JSONDecodeError("invalid JSON", "", 0)

    monkeypatch.setattr(graph, "invoke_structured", groq_limited)
    monkeypatch.setattr(graph, "invoke_openrouter_structured", invalid_fallback)
    monkeypatch.setattr(graph, "get_cached_paper_digests", lambda keys: asyncio.sleep(0, result={}))
    monkeypatch.setattr(graph.settings, "paper_digest_batch_size", 2)
    state = {"run_id": "circuit", "research_question": "Q", "retrieved_sources": sources, "selected_paper_ids": [source.source_id for source in sources], "assessed_source_ids": [], "failed_source_ids": [], "paper_digests": [], "rate_limited_models": [], "warnings": [], "audit_log": []}

    first = await graph.digest_papers_batch(state)  # type: ignore[arg-type]
    second = await graph.digest_papers_batch({**state, **first})  # type: ignore[arg-type]

    assert calls["fallback"] == 1
    assert second["digest_fallback_unavailable"] is True
    assert len(second["failed_source_ids"]) == 4


def test_paper_review_is_not_complete_with_undigested_sources_or_too_few_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "min_papers_per_review", 3)
    assert graph.paper_review_completion_issue({"selected_paper_ids": ["SRC-1"], "paper_digests": []})  # type: ignore[arg-type]
    digests = [graph.PaperDigest(source_id=f"SRC-{i}", rank=i, what_study_did="summary", key_findings=[], authors_conclusion="", conclusion_source="not_available", why_it_matches="match", study_type="other") for i in (1, 2)]
    assert "at least 3" in (graph.paper_review_completion_issue({"selected_paper_ids": ["SRC-1", "SRC-2"], "paper_digests": digests}) or "")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_planner_provider_failure_uses_multiple_focused_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(graph, "invoke_structured", unavailable)
    monkeypatch.setattr(graph, "invoke_openrouter_structured", unavailable)
    result = await graph.plan_research({"run_id": "fallback-plan", "research_question": "Does OmpK35 and OmpK36 loss affect carbapenem resistance in Klebsiella pneumoniae?", "warnings": [], "rate_limited_models": [], "audit_log": []})  # type: ignore[arg-type]

    assert len(result["search_queries"]) == 6
    assert {"ompk35", "ompk36"}.issubset({query.query.split()[2].casefold() for query in result["search_queries"]})


@pytest.mark.asyncio
async def test_planner_does_not_route_queries_to_crossref_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    async def planned(*args: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        return PlanOutput(objective="Study", subquestions=["Study"], source_types=["primary"], search_strategy="Search", queries=[SearchQuery(query_id="Q1", subquestion="Study", query="study query", source_names=["crossref", "pubmed", "europe_pmc"]) ]), {}

    monkeypatch.setattr(graph, "invoke_structured", planned)
    result = await graph.plan_research({"run_id": "no-crossref", "research_question": "Study question", "warnings": [], "rate_limited_models": [], "audit_log": []})  # type: ignore[arg-type]
    assert "crossref" not in result["search_queries"][0].source_names


def test_quote_locator_checks_other_parts_and_normalizes_punctuation() -> None:
    source = SourceRecord(
        source_id="europe_pmc:123",
        provider="europe_pmc",
        title="Porin experiment",
        url="https://example.org/study",
        abstract="A study was performed.",
        full_text_sections=[SourceSection(source_part="results", text="OmpK36 disruption - raised MIC.")],
    )

    part, match = graph._locate_quote(source, "OmpK36 disruption—raised MIC.", "abstract")

    assert (part, match) == ("results", "normalized")


def test_openrouter_digest_output_normalizes_common_schema_variations() -> None:
    raw = {"papers": [{"paper_id": "pubmed:1", "summary": "Study summary " * 100, "findings": [{"quote": "Exact quote."}], "relevance_note": "Relevant.", "study_type": "in vitro experiment"}]}
    result = _coerce_paper_digest_output("```json\n" + json.dumps(raw) + "\n```")
    assert result.papers[0].source_id == "pubmed:1"
    assert len(result.papers[0].what_study_did) <= 1200
    assert result.papers[0].key_findings == ["Exact quote."]
    assert result.papers[0].study_type == "experimental"


def test_report_timestamp_supports_paper_digest_report_dict() -> None:
    report = {"report_type": "paper_digest_review", "generated_at": "2026-10-01T10:00:00Z"}
    assert _report_generated_at(report, report).isoformat() == "2026-10-01T10:00:00+00:00"


@pytest.mark.asyncio
async def test_verifier_provider_failure_is_unverified_not_a_scientific_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise GroqRateLimited("test-model", 60)

    monkeypatch.setattr(graph, "invoke_structured", unavailable)
    claim = CandidateClaim(claim_id="CLM-001", text="Porin disruption is associated with increased MIC.", subquestion="Does porin disruption raise MIC?", evidence_ids=["EV-001"])
    evidence = EvidenceItem(evidence_id="EV-001", source_id="pubmed:123", subquestion=claim.subquestion, text="OmpK36 disruption raised MIC.", relevance=0.9, evidence_type="experimental", evidence_level="direct", source_part="results", supports=[claim.claim_id])

    result = await graph.verify_claims({
        "run_id": "verifier-failure-test",
        "candidate_claims": [claim],
        "evidence_items": [evidence],
        "retrieved_sources": [],
        "warnings": [],
        "rate_limited_models": [],
        "research_gaps": [],
        "audit_log": [],
    })  # type: ignore[arg-type]

    assert result["verified_claims"][0].verification_status == "unverified"
    assert "not a scientific verdict" in result["verified_claims"][0].verification.evidence_assessment
    assert result["audit_log"][0].details["error_type"] == "GroqRateLimited"
    assert result["audit_log"][0].details["retry_after_seconds"] == 60
    coverage = ResearchCoverage(retrieved=1, assessable=1, screened=1, assessed=1, unassessed=0, extraction_candidates=1, extraction_coverage_percent=100, screen_excluded=0)
    assert graph._outcome(result, coverage, []) == "verification_incomplete"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_verifier_uses_fallback_when_primary_is_already_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_model = "test-verifier-fallback"
    monkeypatch.setattr(graph.settings, "groq_fallback_model", fallback_model)

    async def fake_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None, **kwargs: Any) -> tuple[Any, dict[str, str]]:
        assert model_name == fallback_model
        return VerificationOutput(assessments=[ClaimVerification(claim_id="CLM-001", verification_status="verified", evidence_assessment="The passage directly supports the claim.", evidence_types=["experimental"])], contradictions=[], research_gaps=[]), {"model": fallback_model}

    monkeypatch.setattr(graph, "invoke_structured", fake_invoke)
    claim = CandidateClaim(claim_id="CLM-001", text="Porin disruption raised MIC.", subquestion="Does porin disruption raise MIC?", evidence_ids=["EV-001"])
    evidence = EvidenceItem(evidence_id="EV-001", source_id="pubmed:123", subquestion=claim.subquestion, text="OmpK36 disruption raised MIC.", relevance=0.9, evidence_type="experimental", evidence_level="direct", source_part="results", supports=[claim.claim_id])
    result = await graph.verify_claims({
        "run_id": "verifier-fallback-test", "candidate_claims": [claim], "evidence_items": [evidence],
        "retrieved_sources": [], "warnings": [], "rate_limited_models": [graph.settings.groq_model],
        "research_gaps": [], "audit_log": [],
    })  # type: ignore[arg-type]

    assert result["verified_claims"][0].verification_status == "verified"
    assert result["audit_log"][0].details["model"] == fallback_model
    assert result["audit_log"][0].details["fallback_used"] is True
    assert any("fallback model" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_screening_is_checkpointed_one_batch_per_graph_step(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [
        SourceRecord(source_id=f"pubmed:{index}", provider="pubmed", title=f"Resistance study {index}", url=f"https://example.org/{index}", abstract=f"Evidence about porin resistance {index}.")
        for index in range(5)
    ]

    async def fake_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None) -> tuple[Any, dict[str, int]]:
        payload = json.loads(messages[1][1])
        decisions = [{"source_id": item["source_id"], "relevant": True, "rationale": "Related topic."} for item in payload["untrusted_records"]]
        return ScreeningOutput(decisions=decisions), {"input_tokens": 2}

    monkeypatch.setattr(graph, "invoke_structured", fake_invoke)
    monkeypatch.setattr(graph.settings, "screening_batch_size", 2)
    state: dict[str, Any] = {
        "run_id": "screen-test",
        "research_question": "porin resistance",
        "subquestions": ["porin resistance"],
        "new_source_ids": [source.source_id for source in sources],
        "retrieved_sources": sources,
        "source_contexts": {source.source_id: [{"query": "porin resistance", "subquestion": "porin resistance"}] for source in sources},
        "screened_source_ids": [],
        "ranked_source_ids": [],
        "screen_decisions": {},
        "audit_log": [],
    }

    first = await graph.screen_sources(state)  # type: ignore[arg-type]
    state.update(first)
    assert len(state["screened_source_ids"]) == 2
    assert graph._screening_route(state) == "screen"  # type: ignore[arg-type]

    second = await graph.screen_sources(state)  # type: ignore[arg-type]
    state.update(second)
    assert len(state["screened_source_ids"]) == 4

    third = await graph.screen_sources(state)  # type: ignore[arg-type]
    state.update(third)
    assert len(state["screened_source_ids"]) == 5
    assert len(state["ranked_source_ids"]) == 5
    assert graph._screening_route(state) == "extract"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_recoverable_screening_retries_are_audit_events_not_user_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [
        SourceRecord(source_id=f"pubmed:{index}", provider="pubmed", title=f"Study {index}", url=f"https://example.org/{index}", abstract=f"Resistance finding {index}.")
        for index in range(3)
    ]

    async def failing_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None) -> tuple[Any, dict[str, int]]:
        raise graph.PromptBudgetExceeded("provider request too large")

    monkeypatch.setattr(graph, "invoke_structured", failing_invoke)
    monkeypatch.setattr(graph.settings, "screening_batch_size", 3)
    state: dict[str, Any] = {
        "run_id": "retry-test",
        "research_question": "resistance",
        "subquestions": ["resistance"],
        "new_source_ids": [source.source_id for source in sources],
        "retrieved_sources": sources,
        "source_contexts": {source.source_id: [] for source in sources},
        "screened_source_ids": [],
        "ranked_source_ids": [],
        "screen_decisions": {},
        "screen_queue_relevant_ids": [],
        "audit_log": [],
        "errors": [],
        "warnings": [],
    }

    result = await graph.screen_sources(state)  # type: ignore[arg-type]

    assert result["active_screening_batch_size"] == 1
    assert "errors" not in result
    assert "warnings" not in result
    assert result["audit_log"][0].action == "retrying_smaller_screening_batch"


@pytest.mark.asyncio
async def test_non_budget_screening_error_does_not_resubmit_smaller_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [SourceRecord(source_id=f"pubmed:{index}", provider="pubmed", title=f"Study {index}", url=f"https://example.org/{index}", abstract="Relevant resistance finding.") for index in range(3)]
    calls = 0

    async def failing_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None) -> tuple[Any, dict[str, int]]:
        nonlocal calls
        calls += 1
        raise ValueError("mock deterministic bad request")

    monkeypatch.setattr(graph, "invoke_structured", failing_invoke)
    monkeypatch.setattr(graph.settings, "screening_batch_size", 3)
    state: dict[str, Any] = {
        "run_id": "screen-error-test", "research_question": "resistance", "subquestions": ["resistance"],
        "new_source_ids": [source.source_id for source in sources], "retrieved_sources": sources,
        "source_contexts": {source.source_id: [] for source in sources}, "screened_source_ids": [],
        "ranked_source_ids": [], "screen_decisions": {}, "audit_log": [], "warnings": [],
    }

    result = await graph.screen_sources(state)  # type: ignore[arg-type]

    assert calls == 1
    assert len(result["screened_source_ids"]) == 3
    assert len(result["ranked_source_ids"]) == 3
    assert "active_screening_batch_size" not in result
    assert any(event.action == "screening_unavailable_retained_batch" for event in result["audit_log"])


@pytest.mark.asyncio
async def test_retrieval_enforces_one_total_run_cap_and_skips_broadening_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    class QueryRecordsTool:
        name = "pubmed"

        async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
                return [SourceRecord(source_id=f"pubmed:{query.query_id}-{index}", provider="pubmed", title=f"{query.query_id} resistance study {index}", url=f"https://example.org/{query.query_id}/{index}", abstract=("Porin resistance susceptibility findings in the studied isolates. " * 5)) for index in range(5)]

    monkeypatch.setattr(graph, "TOOLS", {"pubmed": QueryRecordsTool()})
    monkeypatch.setattr(graph.settings, "max_records_per_search_round", 25)
    monkeypatch.setattr(graph.settings, "max_records_per_research_run", 2)
    first_state: dict[str, Any] = {
        "run_id": "total-cap-test", "research_question": "porin resistance", "search_round": 0,
        "current_search_queries": [SearchQuery(query_id="Q1", subquestion="porin resistance", query="porin resistance", source_names=["pubmed"])],
        "retrieved_sources": [], "source_contexts": {}, "audit_log": [],
    }

    first = await graph.retrieve(first_state)  # type: ignore[arg-type]
    second_state = {**first_state, **first, "search_round": 1, "current_search_queries": [SearchQuery(query_id="Q2", subquestion="porin resistance", query="outer membrane porin", source_names=["pubmed"])]}
    second = await graph.retrieve(second_state)  # type: ignore[arg-type]
    route_state = {**second_state, **second, "evidence_items": [], "assessed_source_ids": [], "failed_source_ids": []}

    assert len(first["retrieved_sources"]) == 2
    assert len(second["retrieved_sources"]) == 2
    assert second["new_source_ids"] == []
    assert graph._extraction_route(route_state) == "verify"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_non_budget_extraction_error_fails_batch_without_splitting(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [SourceRecord(source_id=f"pubmed:{index}", provider="pubmed", title=f"Study {index}", url=f"https://example.org/{index}", abstract="Relevant resistance finding.") for index in range(3)]
    calls = 0

    async def failing_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None) -> tuple[Any, dict[str, int]]:
        nonlocal calls
        calls += 1
        raise ValueError("mock deterministic bad request")

    monkeypatch.setattr(graph, "invoke_structured", failing_invoke)
    monkeypatch.setattr(graph.settings, "extraction_batch_size", 3)
    state: dict[str, Any] = {
        "run_id": "extract-error-test", "research_question": "resistance", "subquestions": ["resistance"],
        "retrieved_sources": sources, "ranked_source_ids": [source.source_id for source in sources],
        "assessed_source_ids": [], "failed_source_ids": [], "evidence_items": [], "candidate_claims": [],
        "source_contexts": {}, "audit_log": [], "warnings": [],
    }

    result = await graph.extract_evidence_batch(state)  # type: ignore[arg-type]

    assert calls == 1
    assert set(result["failed_source_ids"]) == {source.source_id for source in sources}
    assert "active_batch_size" not in result
    assert result["audit_log"][0].action == "batch_skipped_after_provider_error"


@pytest.mark.asyncio
async def test_rate_limited_extraction_model_opens_run_wide_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [SourceRecord(source_id=f"pubmed:{index}", provider="pubmed", title=f"Study {index}", url=f"https://example.org/{index}", abstract="Relevant resistance finding.") for index in range(5)]

    async def should_not_invoke(schema: type[Any], messages: list[tuple[str, str]], model_name: str | None = None) -> tuple[Any, dict[str, int]]:
        raise AssertionError("A run-throttled model must not receive another request")

    monkeypatch.setattr(graph, "invoke_structured", should_not_invoke)
    monkeypatch.setattr(graph.settings, "extraction_batch_size", 2)
    state: dict[str, Any] = {
        "run_id": "rate-limit-circuit-test", "research_question": "resistance", "subquestions": ["resistance"],
        "retrieved_sources": sources, "ranked_source_ids": [source.source_id for source in sources],
        "assessed_source_ids": [], "failed_source_ids": [], "evidence_items": [], "candidate_claims": [],
        "source_contexts": {}, "audit_log": [], "warnings": [], "rate_limited_models": [graph.settings.groq_model],
    }

    result = await graph.extract_evidence_batch(state)  # type: ignore[arg-type]

    assert set(result["failed_source_ids"]) == {source.source_id for source in sources}
    assert result["audit_log"][0].action == "batch_skipped_model_rate_limited"
    assert result["audit_log"][0].details["remaining_source_count_skipped_without_provider_calls"] == 3


@pytest.mark.asyncio
async def test_retrieval_drops_empty_records_and_caps_ranked_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class ManyRecordsTool:
        name = "pubmed"

        async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
            return [
                    SourceRecord(source_id=f"pubmed:{index}", provider="pubmed", title=f"Study {index}", url=f"https://example.org/{index}", abstract=(f"Porin resistance findings {index} were measured across the studied population. " * 4))
                for index in range(4)
            ] + [SourceRecord(source_id="pubmed:empty", provider="pubmed", title="No abstract", url="https://example.org/empty")]

    monkeypatch.setattr(graph, "TOOLS", {"pubmed": ManyRecordsTool()})
    monkeypatch.setattr(graph.settings, "max_records_per_search_round", 3)
    state: dict[str, Any] = {
        "run_id": "retrieval-test",
        "research_question": "porin resistance",
        "search_round": 0,
        "current_search_queries": [SearchQuery(query_id="Q1", subquestion="porin", query="porin resistance", source_names=["pubmed"])],
        "retrieved_sources": [],
        "source_contexts": {},
        "audit_log": [],
        "errors": [],
    }

    result = await graph.retrieve(state)  # type: ignore[arg-type]

    assert len(result["retrieved_sources"]) == 3
    assert all(source.abstract for source in result["retrieved_sources"])
    details = result["audit_log"][0].details
    assert details["ranked_out_by_run_cap"] == 1
    assert details["records_without_abstract_or_full_text"] == 1


@pytest.mark.asyncio
async def test_retrieval_runs_provider_requests_concurrently_with_a_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    active = 0
    peak_active = 0

    class DelayedTool:
        def __init__(self, name: str) -> None:
            self.name = name

        async def search(self, query: SearchQuery, limit: int) -> list[SourceRecord]:
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return [SourceRecord(source_id=f"{self.name}:1", provider=self.name, title=f"{self.name} study", url=f"https://example.org/{self.name}", abstract=("Relevant evidence was reported for the observed groups in this research study. " * 4))]

    provider_names = [f"provider_{index}" for index in range(5)]
    monkeypatch.setattr(graph, "TOOLS", {name: DelayedTool(name) for name in provider_names})
    monkeypatch.setattr(graph.settings, "retrieval_concurrency", 2)
    state: dict[str, Any] = {
        "run_id": "parallel-retrieval-test",
        "research_question": "relevant evidence",
        "search_round": 0,
        "current_search_queries": [SearchQuery(query_id="Q1", subquestion="evidence", query="relevant evidence", source_names=provider_names)],
        "retrieved_sources": [],
        "source_contexts": {},
        "audit_log": [],
        "errors": [],
    }

    result = await graph.retrieve(state)  # type: ignore[arg-type]

    assert peak_active == 2
    assert len(result["retrieved_sources"]) == 3
    call_order = [call["tool"] for call in result["audit_log"][0].details["tool_calls"]]
    assert call_order == provider_names[:3]
    assert result["audit_log"][0].details["max_concurrent_requests"] == 2


def test_low_coverage_verdict_is_inconclusive() -> None:
    coverage = ResearchCoverage(retrieved=27, assessable=27, screened=27, assessed=6, unassessed=6, extraction_candidates=12, extraction_coverage_percent=50, screen_excluded=15, retrieved_coverage_percent=22.2, assessable_coverage_percent=22.2)
    assert graph._outcome({} , coverage, []) == "inconclusive_low_coverage"  # type: ignore[arg-type]
    summary = graph._summary("inconclusive_low_coverage", coverage, [])
    assert "27 records were retrieved" in summary
    assert "6 of 12 relevant records assessed" in summary
    assert "6 records remain unassessed" in summary
    assert "inconclusive because coverage was low" in summary


def test_no_evidence_outcome_requires_eighty_percent_coverage() -> None:
    full = ResearchCoverage(retrieved=10, assessable=10, screened=10, assessed=8, unassessed=2, extraction_candidates=10, extraction_coverage_percent=80, screen_excluded=0, retrieved_coverage_percent=80, assessable_coverage_percent=80)
    low = full.model_copy(update={"assessed": 6, "unassessed": 4, "extraction_coverage_percent": 60, "retrieved_coverage_percent": 60, "assessable_coverage_percent": 60})
    assert graph._outcome({}, full, []) == "no_evidence_in_assessed"  # type: ignore[arg-type]
    assert graph._outcome({}, low, []) == "inconclusive_low_coverage"  # type: ignore[arg-type]


def test_extraction_continues_in_batches_without_total_record_cap() -> None:
    state = {
        "ranked_source_ids": [f"pubmed:{index}" for index in range(101)],
        "assessed_source_ids": [f"pubmed:{index}" for index in range(100)],
        "failed_source_ids": [],
        "evidence_items": [],
        "search_round": 2,
    }
    assert graph._extraction_route(state) == "extract"  # type: ignore[arg-type]
