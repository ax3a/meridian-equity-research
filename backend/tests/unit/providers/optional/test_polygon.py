from __future__ import annotations

import re

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.providers.optional.polygon import PolygonProvider

URL_REGEX = re.compile(r"https://api\.polygon\.io/v2/aggs/ticker/AAPL/range/1/day/.*")

BODY = {
    "status": "OK",
    "results": [
        {"t": 1798761600000, "c": 220.9, "v": 45000000},
        {"t": 1798848000000, "c": 222.75, "v": 41000000},
        {"t": 1798934400000, "c": 223.4, "v": 39000000},
    ],
}


@pytest.fixture
def provider(http_client) -> PolygonProvider:
    return PolygonProvider(http_client, api_key="demo-key")


async def test_missing_key_raises_unavailable(http_client) -> None:
    unconfigured = PolygonProvider(http_client, api_key=None)

    with pytest.raises(ProviderUnavailableError):
        await unconfigured.get_quote("AAPL")


@respx.mock
async def test_get_quote_parses_aggregates(provider: PolygonProvider) -> None:
    respx.get(url__regex=URL_REGEX).mock(return_value=httpx.Response(200, json=BODY))

    result = await provider.get_quote("aapl", history_days=365)

    assert provider.name == "polygon"
    assert result.data.ticker == "AAPL"
    assert result.data.price == pytest.approx(223.4)
    assert len(result.data.history) == 3
    assert result.sources[0].publisher == "Polygon.io"
    assert len(result.evidence) == 1


@respx.mock
async def test_get_quote_raises_on_error_status(provider: PolygonProvider) -> None:
    respx.get(url__regex=URL_REGEX).mock(
        return_value=httpx.Response(200, json={"status": "ERROR", "error": "Unknown API Key"})
    )

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_get_quote_raises_on_no_results(provider: PolygonProvider) -> None:
    respx.get(url__regex=URL_REGEX).mock(return_value=httpx.Response(200, json={"status": "OK", "results": []}))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_get_quote_maps_http_error(provider: PolygonProvider) -> None:
    respx.get(url__regex=URL_REGEX).mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")
