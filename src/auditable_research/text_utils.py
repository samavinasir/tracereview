"""Small text helpers shared by the workflow.

The sentence splitter is deliberately conservative: when it is unsure whether a
period ends a sentence it keeps the text together. A slightly long sentence is
a safe failure for TraceReview (we only ever display it verbatim); a fragment
such as "5 fold." is not.
"""

import re

# A terminator run ("." / "?!" / ".)" ...) followed by whitespace.
_BOUNDARY = re.compile(r"""[.!?]+["'’”)\]]*\s+""")
_OPENERS = "\"'“‘([{"

# Lower-case, periods removed. "et al." is "al", "e.g." is "eg", and so on.
_ABBREVIATIONS = frozenset(
    {
        "al", "approx", "ca", "cf", "dr", "eg", "eq", "eqs", "fig", "figs", "ie",
        "inc", "ltd", "mr", "mrs", "ms", "pp", "prof", "ref", "refs", "resp",
        "sp", "spp", "ssp", "subsp", "suppl", "viz", "vol", "vs",
    }
)  # fmt: skip


def _ends_with_abbreviation(before: str) -> bool:
    """True if the word directly before a period is an abbreviation or initial."""
    match = re.search(r"(\S+)$", before)
    if match is None:
        return False
    token = match.group(1).lstrip(_OPENERS)
    if not token:
        return False
    segments = token.split(".")
    # "K" (K. pneumoniae), "J" (J. Smith), "U.S", "e.g" -> all single letters.
    if all(len(part) == 1 and part.isalpha() for part in segments):
        return True
    return "".join(segments).casefold() in _ABBREVIATIONS


def _is_sentence_end(text: str, match: re.Match[str]) -> bool:
    following = text[match.end() : match.end() + 1]
    if not following:
        return True
    # Real sentences start with a capital, a digit, or an opening quote/bracket.
    # Lower-case continuations ("et al. in vivo", "Fig. 2 shows") are not breaks.
    if not (following.isupper() or following.isdigit() or following in _OPENERS):
        return False
    if match.group(0).lstrip().startswith(("?", "!")):
        return True
    return not _ends_with_abbreviation(text[: match.start()])


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving the original wording exactly.

    Decimals (``2.5``), ``et al.``, ``Fig. 2``, ``vs.``, initials and species
    abbreviations (``E. coli``) do not end a sentence.
    """
    text = (text or "").strip()
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        if not _is_sentence_end(text, match):
            continue
        sentence = text[start : match.end()].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences
