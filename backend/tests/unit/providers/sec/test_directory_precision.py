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
