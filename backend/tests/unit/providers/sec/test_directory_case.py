"""Name resolution must be case-insensitive: SEC titles are upper case ("MICROSOFT CORP")."""

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
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "2": {"cik_str": 1616318, "ticker": "APLE", "title": "APPLE HOSPITALITY REIT, INC."},
    "3": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
}


@pytest.fixture
def directory(http_client):
    return SecCompanyDirectory(http_client)


def _mock() -> None:
    respx.get(COMPANY_TICKERS_URL).mock(return_value=httpx.Response(200, json=json.loads(json.dumps(ROWS))))


@respx.mock
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Microsoft", "MSFT"),
        ("microsoft", "MSFT"),
        ("MICROSOFT CORP", "MSFT"),
        ("msft", "MSFT"),
        ("nvidia", "NVDA"),
        ("Apple", "AAPL"),  # shortest title wins over Apple Hospitality REIT
    ],
)
async def test_resolve_is_case_insensitive(directory, query, expected):
    _mock()
    assert (await directory.resolve(query)).ticker == expected


@respx.mock
async def test_resolve_unknown_company_raises(directory):
    _mock()
    with pytest.raises(CompanyNotFoundError):
        await directory.resolve("Definitely Not A Listed Company Ltd")
