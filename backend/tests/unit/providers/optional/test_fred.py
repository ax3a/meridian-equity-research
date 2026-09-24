from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.providers.optional.fred import FredMacroProvider

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def _obs(series_id: str, points: list[tuple[str, str]]) -> dict:
    return {"observations": [{"date": d, "value": v} for d, v in points]}


@pytest.fixture
def provider(http_client) -> FredMacroProvider:
    return FredMacroProvider(http_client, api_key="test-key")


async def test_missing_key_raises_unavailable(http_client) -> None:
    unconfigured = FredMacroProvider(http_client, api_key=None)

    with pytest.raises(ProviderUnavailableError):
        await unconfigured.get_indicators()


@respx.mock
async def test_get_indicators_computes_yoy_and_passthrough_rates(provider: FredMacroProvider) -> None:
    cpi_points = [(f"2025-{m:02d}-01", str(300 + m)) for m in range(1, 13)]
    cpi_points += [("2026-01-01", "315.0")]
    respx.get(FRED_URL, params={"series_id": "CPIAUCSL"}).mock(
        return_value=httpx.Response(200, json=_obs("CPIAUCSL", cpi_points))
    )
    respx.get(FRED_URL, params={"series_id": "FEDFUNDS"}).mock(
        return_value=httpx.Response(200, json=_obs("FEDFUNDS", [("2026-08-01", "4.33")]))
    )
    respx.get(FRED_URL, params={"series_id": "UNRATE"}).mock(
        return_value=httpx.Response(200, json=_obs("UNRATE", [("2026-08-01", "4.1")]))
    )
    gdp_points = [(f"202{y}-01-01", str(21000 + y * 100)) for y in range(0, 6)]
    respx.get(FRED_URL, params={"series_id": "GDPC1"}).mock(
        return_value=httpx.Response(200, json=_obs("GDPC1", gdp_points))
    )

    result = await provider.get_indicators()

    assert provider.name == "fred"
    by_key = {ind.key: ind for ind in result.data}
    assert set(by_key) == {"cpi_yoy", "fed_funds", "unemployment", "real_gdp_growth"}
    assert by_key["fed_funds"].latest == pytest.approx(4.33)
    assert by_key["unemployment"].latest == pytest.approx(4.1)
    assert by_key["cpi_yoy"].latest == pytest.approx((315.0 / 301.0 - 1) * 100)
    assert len(result.sources) == 4
    assert len(result.evidence) == 4


@respx.mock
async def test_get_indicators_maps_http_error(provider: FredMacroProvider) -> None:
    respx.get(FRED_URL).mock(return_value=httpx.Response(401))

    with pytest.raises(ProviderError):
        await provider.get_indicators()


@respx.mock
async def test_api_key_not_logged_or_in_cache_key(provider: FredMacroProvider, memory_cache) -> None:
    respx.get(FRED_URL, params={"series_id": "FEDFUNDS"}).mock(
        return_value=httpx.Response(200, json=_obs("FEDFUNDS", [("2026-08-01", "4.33")]))
    )
    respx.get(FRED_URL).mock(return_value=httpx.Response(200, json={"observations": []}))

    await provider.get_indicators()

    for key in memory_cache._data:
        assert "test-key" not in key
