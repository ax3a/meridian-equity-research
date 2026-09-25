"""Requests are written in natural language; company lookup needs a name or ticker.

The first real end-to-end run died here: "Analyse Microsoft" was passed verbatim to the SEC directory,
which correctly found no company of that name, so no request phrased normally could ever run.
"""

from __future__ import annotations

import pytest

from meridian.agents.company_extraction import candidate_names


def _first_matching(query: str, known: set[str]) -> str | None:
    """Mimics the supervisor loop against a directory with SEC-like matching.

    `SecCompanyDirectory.resolve` accepts an exact ticker, an exact name, or a case-insensitive
    prefix/substring of a title ("Microsoft" resolves "MICROSOFT CORP"), so the fake must too.
    """
    for candidate in candidate_names(query):
        c = candidate.upper()
        for entry in known:
            e = entry.upper()
            if c == e or e.startswith(c) or c in e:
                return c
    return None


KNOWN = {"MSFT", "MICROSOFT CORP", "NVDA", "NVIDIA", "AMD", "Advanced Micro Devices", "AAPL", "Apple", "JPM"}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Analyse Microsoft", "MICROSOFT"),
        ("analyse microsoft", "MICROSOFT"),
        ("Analyse NVIDIA with particular attention to AI infrastructure growth, margins and valuation", "NVIDIA"),
        ("Do a deep dive on Advanced Micro Devices", "ADVANCED MICRO DEVICES"),
        ("research $AAPL", "AAPL"),
        ("Tell me about Apple (AAPL)", "AAPL"),
        ("Write a report on NVDA focusing on data centre demand", "NVDA"),
        ("What about JPM?", "JPM"),
    ],
)
def test_company_is_extracted_from_natural_language(query, expected):
    assert _first_matching(query, KNOWN) == expected


def test_leading_capitalised_verb_is_not_mistaken_for_a_ticker():
    # "ANALYSE" is uppercase and ticker-shaped; the real company must be tried first.
    candidates = [c.upper() for c in candidate_names("ANALYSE MICROSOFT")]

    assert _first_matching("ANALYSE MICROSOFT", KNOWN) == "MICROSOFT"
    assert "ANALYSE" not in candidates or candidates.index("MICROSOFT") < candidates.index("ANALYSE")


def test_an_acronym_in_the_focus_clause_does_not_beat_the_company_name():
    """Regression: "Analyse NVIDIA with attention to AI infrastructure" researched C3.ai (ticker AI).

    Bare uppercase tokens used to outrank company names, so a request about NVIDIA produced a full
    report on an unrelated company — the worst kind of failure, because the output looks entirely valid.
    """
    candidates = candidate_names("Analyse NVIDIA with attention to AI infrastructure growth and margins")

    assert candidates[0] == "NVIDIA"
    assert _first_matching(
        "Analyse NVIDIA with attention to AI infrastructure growth and margins", KNOWN | {"AI"}
    ) == "NVIDIA"


@pytest.mark.parametrize("vocabulary", ["AI", "ETF", "GDP", "CEO", "IPO", "ESG", "SAAS", "TTM"])
def test_common_research_vocabulary_is_never_offered_as_a_bare_ticker(vocabulary):
    assert vocabulary not in candidate_names(f"Analyse Microsoft with attention to {vocabulary} exposure")


def test_an_explicitly_marked_ticker_is_still_honoured_even_if_it_looks_like_vocabulary():
    # "$AI" is a deliberate ticker reference, unlike the word "AI" in prose.
    assert "AI" in candidate_names("research $AI")


def test_unknown_company_yields_candidates_but_no_match():
    query = "Analyse Nonexistent Fake Corp Ltd"

    candidates = candidate_names(query)

    assert candidates, "must still produce candidates so the error can report what was tried"
    assert _first_matching(query, KNOWN) is None


def test_focus_clause_is_not_treated_as_part_of_the_company_name():
    candidates = candidate_names("Analyse Microsoft with particular attention to margins")

    # The best candidate is the company alone; the raw query may survive only as a last resort.
    assert candidates[0] == "Microsoft"
    assert "attention" not in candidates[0].lower()
