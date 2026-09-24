from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError
from meridian.providers.macro.treasury import TreasuryMacroProvider

CSV_BODY = (
    'Date,"1 Mo","2 Mo","3 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "09/24/2026,4.01,4.18,4.24,4.34,4.51,4.87,4.99,5.03,5.10,5.18,5.53,5.47\n"
    "09/23/2026,3.99,4.10,4.19,4.31,4.49,4.85,4.97,4.99,5.05,5.11,5.45,5.40\n"
    "09/22/2026,3.97,4.09,4.16,4.26,4.43,4.71,4.81,4.83,4.89,4.96,5.33,5.29\n"
)


def _year_route(year: int):
    return respx.get(
        url__regex=rf"https://home\.treasury\.gov/resource-center/data-chart-center/interest-rates/"
        rf"daily-treasury-rates\.csv/{year}/all.*"
    )


@pytest.fixture
def provider(http_client) -> TreasuryMacroProvider:
    return TreasuryMacroProvider(http_client)


@respx.mock
async def test_get_indicators_parses_tenors(provider: TreasuryMacroProvider) -> None:
    _year_route(2026).mock(return_value=httpx.Response(200, text=CSV_BODY))

    result = await provider.get_indicators()

    assert provider.name == "us_treasury"
    assert result.provider == "us_treasury"
    keys = {ind.key for ind in result.data}
    assert keys == {"ust_3m", "ust_2y", "ust_10y"}
    by_key = {ind.key: ind for ind in result.data}
    assert by_key["ust_3m"].latest == pytest.approx(4.24)
    assert by_key["ust_2y"].latest == pytest.approx(4.87)
    assert by_key["ust_10y"].latest == pytest.approx(5.18)
    assert by_key["ust_10y"].as_of.isoformat() == "2026-09-24"
    assert len(by_key["ust_10y"].history) == 3
    assert by_key["ust_10y"].unit == "percent"
    assert len(result.sources) == 1
    assert len(result.evidence) == 3


@respx.mock
async def test_get_indicators_maps_http_error(provider: TreasuryMacroProvider) -> None:
    _year_route(2026).mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.get_indicators()


@respx.mock
async def test_get_indicators_raises_on_unexpected_body(provider: TreasuryMacroProvider) -> None:
    _year_route(2026).mock(return_value=httpx.Response(200, text="<html>not csv</html>"))

    with pytest.raises(ProviderError):
        await provider.get_indicators()


@respx.mock
async def test_get_indicators_raises_on_empty_csv(provider: TreasuryMacroProvider) -> None:
    _year_route(2026).mock(return_value=httpx.Response(200, text='Date,"1 Mo","2 Mo","3 Mo","2 Yr","10 Yr"\n'))

    with pytest.raises(ProviderError):
        await provider.get_indicators()
