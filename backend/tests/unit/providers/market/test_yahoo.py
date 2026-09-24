from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError
from meridian.providers.market.yahoo import YahooMarketProvider

YAHOO_BODY = {
    "chart": {
        "result": [
            {
                "meta": {"symbol": "AAPL", "currency": "USD"},
                "timestamp": [1798761600, 1798848000, 1798934400],
                "indicators": {
                    "quote": [
                        {
                            "close": [220.9, 222.75, 223.4],
                            "volume": [45000000, 41000000, 39000000],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}


@pytest.fixture
def provider(http_client) -> YahooMarketProvider:
    return YahooMarketProvider(http_client)


@respx.mock
async def test_get_quote_parses_chart_json(provider: YahooMarketProvider) -> None:
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/AAPL").mock(
        return_value=httpx.Response(200, json=YAHOO_BODY)
    )

    result = await provider.get_quote("aapl", history_days=365)

    assert provider.name == "yahoo"
    assert result.provider == "yahoo"
    assert result.data.ticker == "AAPL"
    assert result.data.price == pytest.approx(223.4)
    assert len(result.data.history) == 3
    assert result.sources[0].metadata.get("unofficial_endpoint") is True
    assert len(result.evidence) == 1


@respx.mock
async def test_get_quote_skips_null_closes(provider: YahooMarketProvider) -> None:
    body = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "AAPL"},
                    "timestamp": [1798761600, 1798848000],
                    "indicators": {"quote": [{"close": [None, 222.75], "volume": [None, 41000000]}]},
                }
            ],
            "error": None,
        }
    }
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/AAPL").mock(
        return_value=httpx.Response(200, json=body)
    )

    result = await provider.get_quote("AAPL")

    assert len(result.data.history) == 1
    assert result.data.price == pytest.approx(222.75)


@respx.mock
async def test_get_quote_raises_on_chart_error(provider: YahooMarketProvider) -> None:
    body = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/BADTICKER").mock(
        return_value=httpx.Response(200, json=body)
    )

    with pytest.raises(ProviderError):
        await provider.get_quote("BADTICKER")


@respx.mock
async def test_get_quote_raises_on_unexpected_shape(provider: YahooMarketProvider) -> None:
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/AAPL").mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_get_quote_maps_http_error(provider: YahooMarketProvider) -> None:
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/AAPL").mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")
