from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.providers.optional.alpha_vantage import AlphaVantageProvider

URL = "https://www.alphavantage.co/query"

BODY = {
    "Meta Data": {"2. Symbol": "AAPL"},
    "Time Series (Daily)": {
        "2026-09-03": {"1. open": "222.80", "4. close": "223.40", "5. volume": "39000000"},
        "2026-09-02": {"1. open": "221.00", "4. close": "222.75", "5. volume": "41000000"},
        "2026-09-01": {"1. open": "220.10", "4. close": "220.90", "5. volume": "45000000"},
    },
}


@pytest.fixture
def provider(http_client) -> AlphaVantageProvider:
    return AlphaVantageProvider(http_client, api_key="demo-key")


async def test_missing_key_raises_unavailable(http_client) -> None:
    unconfigured = AlphaVantageProvider(http_client, api_key=None)

    with pytest.raises(ProviderUnavailableError):
        await unconfigured.get_quote("AAPL")


@respx.mock
async def test_get_quote_parses_time_series(provider: AlphaVantageProvider) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=BODY))

    result = await provider.get_quote("aapl", history_days=365)

    assert provider.name == "alpha_vantage"
    assert result.data.ticker == "AAPL"
    assert result.data.price == pytest.approx(223.40)
    assert result.data.as_of.isoformat() == "2026-09-03"
    assert len(result.data.history) == 3
    assert result.sources[0].publisher == "Alpha Vantage"
    assert len(result.evidence) == 1


@respx.mock
async def test_get_quote_raises_on_error_message(provider: AlphaVantageProvider) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"Error Message": "Invalid API call"}))

    with pytest.raises(ProviderError):
        await provider.get_quote("BADTICKER")


@respx.mock
async def test_get_quote_raises_on_rate_limit_note(provider: AlphaVantageProvider) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"Note": "Thank you for using Alpha Vantage"}))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_get_quote_maps_http_error(provider: AlphaVantageProvider) -> None:
    respx.get(URL).mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")
