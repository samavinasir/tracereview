"""The search fallbacks and ranking must be topic-neutral.

They used to contain hardcoded antimicrobial-resistance terms (OmpK35, Klebsiella,
carbapenem...), which silently altered searches for every other subject.
"""

import re
from typing import Any

import pytest

from auditable_research import graph
from auditable_research.models import SourceRecord

_GENERIC_PHRASES = {
    "research", "methods", "reported", "findings", "review",
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Does metformin lower colorectal cancer risk in diabetic patients?",
        "What is the evidence for statins preventing dementia?",
        # The former hardcoded special case: it must now behave like any other question.
        "Does OmpK35 and OmpK36 loss affect carbapenem resistance in Klebsiella pneumoniae?",
        "How does PostgreSQL handle concurrent database transactions?",
        "What factors influence voter turnout in local elections?",
        "How do bridge materials affect structural fatigue under repeated loads?",
        "How did modernist poetry change narrative voice?",
    ],
)
async def test_fallback_plan_only_uses_the_users_own_words(monkeypatch: pytest.MonkeyPatch, question: str) -> None:
    async def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(graph, "invoke_structured", unavailable)
    monkeypatch.setattr(graph, "invoke_openrouter_structured", unavailable)

    result = await graph.plan_research({"run_id": "r", "research_question": question, "warnings": [], "rate_limited_models": [], "audit_log": []})  # type: ignore[arg-type]

    assert result["subquestions"] == [question]
    assert len(result["search_queries"]) == 4
    allowed = _words(question) | _GENERIC_PHRASES
    for query in result["search_queries"]:
        assert _words(query.query) <= allowed, f"unexpected terms injected: {_words(query.query) - allowed}"


def test_source_rank_scores_only_literal_question_terms() -> None:
    synonym_only = SourceRecord(
        source_id="pubmed:1", provider="pubmed", title="Membrane permeability",
        url="https://example.org", abstract="An outer membrane protein changed permeability in the isolates.",
    )
    literal = SourceRecord(
        source_id="pubmed:2", provider="pubmed", title="Porin loss",
        url="https://example.org", abstract="Porin loss was measured in the isolates.",
    )
    # No hidden synonym table: "porin" does not secretly match "outer membrane protein".
    assert graph._source_rank(synonym_only, [], "porin loss")[0] == 0
    assert graph._source_rank(literal, [], "porin loss")[0] == 2


def test_source_rank_unchanged_for_an_unrelated_subject() -> None:
    source = SourceRecord(
        source_id="pubmed:3", provider="pubmed", title="Metformin and cancer",
        url="https://example.org", abstract="Metformin use was associated with lower cancer incidence.",
    )
    assert graph._source_rank(source, [], "metformin cancer incidence")[0] == 3


def test_postgresql_question_does_not_select_unrelated_records() -> None:
    question = "What is PostgreSQL?"
    relevant = SourceRecord(
        source_id="openalex:postgres", provider="openalex", title="PostgreSQL Database Systems",
        url="https://example.org/postgres", abstract="PostgreSQL is a relational database system. " * 20,
    )
    unrelated = SourceRecord(
        source_id="openalex:biology", provider="openalex", title="Membrane Protein Transport",
        url="https://example.org/biology", abstract="This study investigates membrane protein transport in bacteria. " * 20,
    )

    result = graph.select_papers({
        "run_id": "postgres-question", "research_question": question,
        "retrieved_sources": [relevant, unrelated], "selected_paper_ids": [],
        "paper_digests": [], "source_contexts": {}, "warnings": [], "audit_log": [],
    })

    assert result["selected_paper_ids"] == ["openalex:postgres"]
    assert unrelated.raw_metadata["_tracereview_relevance"] == "Unmatched"


@pytest.mark.parametrize(
    ("round_number", "suffix"),
    [(1, "review"), (2, "research methods"), (3, "reported findings"), (4, "review")],
)
def test_broadening_queries_use_a_generic_suffix_that_changes_each_round(round_number: int, suffix: str) -> None:
    state: Any = {"subquestions": ["Is metformin alone sufficient to lower cancer risk?"]}

    (query,) = graph._fallback_queries(state, round_number)

    assert query.query == f"Is metformin to lower cancer risk? {suffix}"
    assert query.query_id == f"QB{round_number}-1"
    assert query.subquestion == "Is metformin alone sufficient to lower cancer risk?"


@pytest.mark.asyncio
async def test_broaden_search_adds_new_queries_without_topic_terms() -> None:
    subquestion = "Does intermittent fasting improve insulin sensitivity?"
    state: Any = {
        "run_id": "r", "research_question": subquestion, "subquestions": [subquestion],
        "search_queries": [], "search_round": 0, "audit_log": [], "selected_paper_ids": [],
    }

    result = await graph.broaden_paper_search(state)

    (added,) = result["current_search_queries"]
    assert _words(added.query) <= _words(subquestion) | _GENERIC_PHRASES
    assert added.query.casefold() != subquestion.casefold()
    assert result["search_queries"] == [added]
