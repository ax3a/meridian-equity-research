"""Resolution must refuse a company it cannot actually identify.

Found by the eval suite: "Analyse Nonexistent Fabricated Holdings Ltd" produced a complete, fully-cited
research report on Star Holdings, because the generic word "Holdings" matched it. A confidently wrong
company is the worst possible output, so ambiguity has to fail instead.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from meridian.core.errors import CompanyNotFoundError
from meridian.providers.sec.directory import SecCompanyDirectory
from meridian.providers.sec.endpoints import COMPANY_TICKERS_URL

ROWS = {
    "0": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "2": {"cik_str": 1953984, "ticker": "STHO", "title": "Star Holdings"},
    "3": {"cik_str": 1090727, "ticker": "UPS", "title": "UNITED PARCEL SERVICE INC"},
    "4": {"cik_str": 2000001, "ticker": "GRPX", "title": "GENERIC GROUP HOLDINGS LTD"},
    "5": {"cik_str": 21344, "ticker": "KO", "title": "COCA COLA CO"},
    "6": {"cik_str": 317540, "ticker": "COKE", "title": "Coca-Cola Consolidated, Inc."},
    "7": {"cik_str": 200406, "ticker": "JNJ", "title": "JOHNSON & JOHNSON"},
    # EDGAR drops the apostrophe in some titles and keeps it in others.
    "8": {"cik_str": 60667, "ticker": "LOW", "title": "LOWES COMPANIES INC"},
    "9": {"cik_str": 63908, "ticker": "MCD", "title": "MCDONALDS CORP"},
    "10": {"cik_str": 1089063, "ticker": "DKS", "title": "DICK'S SPORTING GOODS, INC."},
}


@pytest.fixture
def directory(http_client):
    return SecCompanyDirectory(http_client)


def _mock() -> None:
    respx.get(COMPANY_TICKERS_URL).mock(return_value=httpx.Response(200, json=json.loads(json.dumps(ROWS))))


@respx.mock
@pytest.mark.parametrize("query", ["Holdings", "Group", "Ltd", "Inc", "Corp", "Services", "Parcel", "Chase"])
async def test_generic_words_never_resolve_a_company(directory, query):
    _mock()
    with pytest.raises(CompanyNotFoundError):
        await directory.resolve(query)


@respx.mock
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Microsoft", "MSFT"),
        ("microsoft", "MSFT"),
        ("MICROSOFT CORP", "MSFT"),
        ("Nvidia Corporation", "NVDA"),  # fuzzy, but the leading word agrees
        ("Star Holdings", "STHO"),  # the full name still resolves
        ("United Parcel Service", "UPS"),
        ("NVDA", "NVDA"),
    ],
)
async def test_identifying_names_still_resolve(directory, query, expected):
    _mock()
    assert (await directory.resolve(query)).ticker == expected


@respx.mock
async def test_a_fabricated_company_is_not_resolved(directory):
    _mock()
    with pytest.raises(CompanyNotFoundError):
        await directory.resolve("Nonexistent Fabricated Holdings Ltd")


@respx.mock
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Coca-Cola", "KO"),  # hyphen in the query, none in the SEC title
        ("Coca Cola", "KO"),
        ("coca-cola co", "KO"),
        ("Coca-Cola Consolidated", "COKE"),  # the longer name still reaches the bottler
        ("Johnson & Johnson", "JNJ"),
        ("Johnson and Johnson", "JNJ"),  # "and" written out instead of an ampersand
    ],
)
async def test_punctuation_differences_do_not_change_the_company(directory, query, expected):
    """Regression: "Coca-Cola" resolved to Coca-Cola Consolidated, a bottler, because the hyphen stopped
    it prefix-matching "COCA COLA CO". Names are now compared with punctuation normalised."""
    _mock()
    assert (await directory.resolve(query)).ticker == expected


@respx.mock
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Lowe's", "LOW"),  # apostrophe in the query, none in the SEC title
        ("Lowes", "LOW"),
        # The curly apostrophe that browsers and word processors insert is the point of this case.
        ("Lowe’s", "LOW"),  # noqa: RUF001
        ("McDonald's", "MCD"),
        ("Dick's Sporting Goods", "DKS"),  # apostrophe on both sides
    ],
)
async def test_an_apostrophe_joins_rather_than_separates(directory, query, expected):
    """Regression: "Analyse Lowe's..." failed to resolve at all.

    Normalising every non-alphanumeric character to a space turned "Lowe's" into "lowe s", whose leading
    word "lowe" matched nothing in "lowes companies inc", so the whole run failed at intake.
    """
    _mock()
    assert (await directory.resolve(query)).ticker == expected
