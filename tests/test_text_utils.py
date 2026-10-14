import pytest

from auditable_research import graph
from auditable_research.models import SourceRecord
from auditable_research.text_utils import split_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Decimals must not end a sentence (this used to return "5 fold.").
        (
            "OmpK36 loss was measured. It raised the meropenem MIC by 2.5 fold.",
            ["OmpK36 loss was measured.", "It raised the meropenem MIC by 2.5 fold."],
        ),
        # "et al." used to return "in vivo."
        (
            "Earlier work was limited. These results differ from Smith et al. in vivo.",
            ["Earlier work was limited.", "These results differ from Smith et al. in vivo."],
        ),
        # Figure references and p-values used to return "2)."
        (
            "Isolates were tested. We tested n=40 isolates (p<0.05, Fig. 2).",
            ["Isolates were tested.", "We tested n=40 isolates (p<0.05, Fig. 2)."],
        ),
        # Species abbreviations / initials.
        (
            "We studied E. coli and K. pneumoniae isolates. Resistance rose.",
            ["We studied E. coli and K. pneumoniae isolates.", "Resistance rose."],
        ),
        ("Strain J. Smith-1 was used. It grew well.", ["Strain J. Smith-1 was used.", "It grew well."]),
        # vs. / e.g. / i.e.
        (
            "Mutants grew slower vs. wild type. This held in all assays.",
            ["Mutants grew slower vs. wild type.", "This held in all assays."],
        ),
        (
            "Several drugs (e.g. meropenem) were tested. None worked.",
            ["Several drugs (e.g. meropenem) were tested.", "None worked."],
        ),
        # A reference in brackets followed by a real new sentence.
        (
            "Loss was confirmed (see Fig. 2). Susceptibility fell.",
            ["Loss was confirmed (see Fig. 2).", "Susceptibility fell."],
        ),
        # ? and ! still split; closing quote stays with its sentence.
        ("Does it matter? Yes! It does.", ["Does it matter?", "Yes!", "It does."]),
        ('The authors called it "novel." They then stopped.', ['The authors called it "novel."', "They then stopped."]),
        # No terminal punctuation on the final sentence.
        ("First sentence. Last one without a period", ["First sentence.", "Last one without a period"]),
        # A sentence that starts with a digit.
        ("Samples were pooled. 120 patients were enrolled.", ["Samples were pooled.", "120 patients were enrolled."]),
        ("", []),
        ("   ", []),
    ],
)
def test_split_sentences(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


def test_split_sentences_never_alters_wording() -> None:
    text = "A 2.5 fold change (Fig. 2) was seen. Smith et al. disagree. Why?"
    assert " ".join(split_sentences(text)) == text


@pytest.mark.parametrize(
    ("abstract", "expected"),
    [
        ("Loss of OmpK36 raised the meropenem MIC by 2.5 fold.", "Loss of OmpK36 raised the meropenem MIC by 2.5 fold."),
        ("Background text. These results differ from Smith et al. in vivo.", "These results differ from Smith et al. in vivo."),
        ("Methods. We tested n=40 isolates (p<0.05, Fig. 2).", "We tested n=40 isolates (p<0.05, Fig. 2)."),
        ("", ""),
    ],
)
def test_abstract_last_sentence_is_a_whole_sentence(abstract: str, expected: str) -> None:
    assert graph._abstract_last_sentence(abstract) == expected


def test_fallback_quotes_do_not_split_inside_abbreviations_or_decimals() -> None:
    abstract = (
        "The cohort was described. OmpK36 loss raised the carbapenem MIC by 2.5 fold in E. coli (Fig. 2). "
        "Annual surveillance was also reported."
    )
    quotes = graph._fallback_abstract_quotes(abstract, "OmpK36 carbapenem MIC")
    texts = [quote.text for quote in quotes]
    assert "OmpK36 loss raised the carbapenem MIC by 2.5 fold in E. coli (Fig. 2)." in texts
    assert all(text in abstract for text in texts)


def _source() -> SourceRecord:
    return SourceRecord(
        source_id="pubmed:1",
        provider="pubmed",
        title="Porin loss and carbapenem susceptibility",
        url="https://example.org",
        abstract="The study examines porin loss and carbapenem susceptibility in isolates.",
    )


@pytest.mark.parametrize(
    "note",
    [
        "Examines improved susceptibility testing of porin mutants.",
        "Describes approved dosing regimens for carbapenems.",
        "Reports results because isolates were collected over time.",
        "Describes a conference dataset of porin mutants.",
        "Tests whether the provided isolates differ.",
    ],
)
def test_benign_relevance_notes_are_kept(note: str) -> None:
    assert graph._safe_relevance_note(note, _source(), "porin carbapenem") == note


@pytest.mark.parametrize(
    "note",
    [
        "Demonstrates that porin loss confers resistance.",
        "Shows that loss causes resistance.",
        "This proves the mechanism.",
        "Confirms the earlier result.",
        "An independent effect of porin loss.",
        "Examines what is shown to cause resistance.",
    ],
)
def test_result_claiming_relevance_notes_are_neutralized(note: str) -> None:
    cleaned = graph._safe_relevance_note(note, _source(), "porin carbapenem")
    assert cleaned.startswith("Related to: ")
    assert "porin" in cleaned
