from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.providers.optional.finnhub import FinnhubProvider
from meridian.schemas.research import CompanyIdentity

QUOTE_URL = "https://finnhub.io/api/v1/quote"
CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"
NEWS_URL = "https://finnhub.io/api/v1/company-news"
PEERS_URL = "https://finnhub.io/api/v1/stock/peers"


@pytest.fixture
def provider(http_client) -> FinnhubProvider:
    return FinnhubProvider(http_client, api_key="demo-key")


@pytest.fixture
def company() -> CompanyIdentity:
    return CompanyIdentity(name="Apple Inc.", ticker="AAPL", cik="320193")


async def test_missing_key_raises_unavailable_for_every_method(http_client, company: CompanyIdentity) -> None:
    unconfigured = FinnhubProvider(http_client, api_key=None)

    with pytest.raises(ProviderUnavailableError):
        await unconfigured.get_quote("AAPL")
    with pytest.raises(ProviderUnavailableError):
        await unconfigured.search_news(company)
    with pytest.raises(ProviderUnavailableError):
        await unconfigured.candidate_peers(company)


@respx.mock
async def test_get_quote_parses_candles(provider: FinnhubProvider) -> None:
    respx.get(CANDLE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "s": "ok",
                "c": [220.9, 222.75, 223.4],
                "t": [1798761600, 1798848000, 1798934400],
                "v": [45000000, 41000000, 39000000],
            },
        )
    )

    result = await provider.get_quote("aapl", history_days=365)

    assert provider.name == "finnhub"
    assert result.data.price == pytest.approx(223.4)
    assert len(result.data.history) == 3


@respx.mock
async def test_get_quote_raises_on_no_data_status(provider: FinnhubProvider) -> None:
    respx.get(CANDLE_URL).mock(return_value=httpx.Response(200, json={"s": "no_data"}))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_search_news_filters_and_ranks(provider: FinnhubProvider, company: CompanyIdentity) -> None:
    respx.get(NEWS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "headline": "Apple beats estimates",
                    "url": "https://reuters.com/a",
                    "source": "reuters.com",
                    "datetime": 1790280000,
                    "summary": "...",
                },
                {
                    "headline": "Random blog take",
                    "url": "https://blog.example/a",
                    "source": "blog.example",
                    "datetime": 1790280000,
                },
            ],
        )
    )

    result = await provider.search_news(company, days=30)

    assert [a.publisher for a in result.data] == ["reuters.com", "blog.example"]
    assert result.data[0].reliability == "tier1"


@respx.mock
async def test_search_news_empty_body(provider: FinnhubProvider, company: CompanyIdentity) -> None:
    respx.get(NEWS_URL).mock(return_value=httpx.Response(200, json=[]))

    result = await provider.search_news(company)

    assert result.data == []


@respx.mock
async def test_candidate_peers_returns_placeholder_identities_with_warning(
    provider: FinnhubProvider, company: CompanyIdentity
) -> None:
    respx.get(PEERS_URL).mock(return_value=httpx.Response(200, json=["AAPL", "MSFT", "GOOGL"]))

    result = await provider.candidate_peers(company, limit=12)

    tickers = [c.company.ticker for c in result.data]
    assert "AAPL" not in tickers  # self excluded
    assert tickers == ["MSFT", "GOOGL"]
    assert any("ticker-only" in w for w in result.warnings)


@respx.mock
async def test_get_quote_maps_http_error(provider: FinnhubProvider) -> None:
    respx.get(CANDLE_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")
