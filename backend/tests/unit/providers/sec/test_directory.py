from __future__ import annotations

import pytest

from meridian.core.errors import CompanyNotFoundError
from meridian.providers.sec.directory import SecCompanyDirectory
from meridian.providers.sec.endpoints import COMPANY_TICKERS_URL, submissions_url
from meridian.schemas.enums import SourceKind


@pytest.fixture
def directory(http_client):
    return SecCompanyDirectory(http_client)


async def test_resolve_exact_ticker_match(respx_mock, directory, company_tickers):
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)

    identity = await directory.resolve("msft")

    assert identity.ticker == "MSFT"
    assert identity.cik == "0000789019"
    assert identity.name == "MICROSOFT CORP"


async def test_resolve_exact_name_match(respx_mock, directory, company_tickers):
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)

    identity = await directory.resolve("apple inc.")

    assert identity.ticker == "AAPL"


async def test_resolve_falls_back_to_fuzzy_name_match(respx_mock, directory, company_tickers):
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)

    # Fixture title is "Berkshire Hathaway Inc" (no trailing period) -- neither ticker nor exact
    # name matches, so this must land in the difflib cutoff=0.75 fuzzy path.
    identity = await directory.resolve("Berkshire Hathaway Inc.")

    assert identity.ticker == "BRK-A"


async def test_resolve_raises_company_not_found(respx_mock, directory, company_tickers):
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)

    with pytest.raises(CompanyNotFoundError):
        await directory.resolve("totally unknown company zzz not real")


async def test_search_ranks_ticker_prefix_before_name_substring(respx_mock, directory, company_tickers):
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)

    results = await directory.search("a", limit=10)
    tickers = [r.ticker for r in results]

    assert tickers[0] == "AAPL"  # ticker-prefix match ranked first
    assert "MSFT" not in tickers  # "microsoft corp" contains no letter "a"
    assert "NVDA" in tickers  # matched via name substring ("nvidia")


async def test_search_empty_query_returns_nothing(respx_mock, directory, company_tickers):
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)

    assert await directory.search("   ") == []


async def test_profile_fills_fields_and_emits_source_and_evidence(
    respx_mock, directory, submissions_msft, msft_identity
):
    url = submissions_url(msft_identity.cik)
    respx_mock.get(url).respond(json=submissions_msft)

    result = await directory.profile(msft_identity)
    profile = result.data

    assert profile.identity.sic == "7372"
    assert profile.identity.sic_description == "Services-Prepackaged Software"
    assert profile.identity.exchange == "Nasdaq"
    assert profile.identity.fiscal_year_end == "0630"
    assert profile.identity.state_of_incorporation == "WA"
    assert profile.category == "Large accelerated filer"
    assert profile.former_names == ["MICROSOFT CORP OLD NAME"]

    assert len(result.sources) == 1
    assert result.sources[0].kind == SourceKind.COMPANY_PROFILE
    assert result.sources[0].publisher == "U.S. SEC EDGAR"
    assert len(result.evidence) == 1
    assert "7372" in result.evidence[0].text
    assert "Nasdaq" in result.evidence[0].text
    assert not result.is_snapshot
