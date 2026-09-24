from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError
from meridian.providers.market.stooq import StooqMarketProvider

STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-09-01,220.10,221.50,219.80,220.90,45000000\n"
    "2026-09-02,221.00,223.00,220.50,222.75,41000000\n"
    "2026-09-03,222.80,224.10,222.00,223.40,39000000\n"
)


@pytest.fixture
def provider(http_client) -> StooqMarketProvider:
    return StooqMarketProvider(http_client)


@respx.mock
async def test_get_quote_parses_csv(provider: StooqMarketProvider) -> None:
    respx.get("https://stooq.com/q/d/l/?s=aapl.us&i=d").mock(return_value=httpx.Response(200, text=STOOQ_CSV))

    result = await provider.get_quote("AAPL", history_days=365)

    assert provider.name == "stooq"
    assert result.provider == "stooq"
    assert result.data.ticker == "AAPL"
    assert result.data.price == pytest.approx(223.40)
    assert result.data.as_of.isoformat() == "2026-09-03"
    assert len(result.data.history) == 3
    assert result.data.history[0].close == pytest.approx(220.90)
    assert len(result.sources) == 1
    assert result.sources[0].publisher == "Stooq"
    assert len(result.evidence) == 1
    assert "223.40" in result.evidence[0].text
    assert result.evidence[0].source_id == result.sources[0].id


@respx.mock
async def test_get_quote_trims_history_days(provider: StooqMarketProvider) -> None:
    respx.get("https://stooq.com/q/d/l/?s=aapl.us&i=d").mock(return_value=httpx.Response(200, text=STOOQ_CSV))

    result = await provider.get_quote("AAPL", history_days=2)

    assert len(result.data.history) == 2
    assert result.data.history[-1].close == pytest.approx(223.40)


@respx.mock
async def test_get_quote_raises_on_anti_bot_html(provider: StooqMarketProvider) -> None:
    """Stooq sometimes answers programmatic clients with a 200 OK JS-challenge page instead of CSV."""
    respx.get("https://stooq.com/q/d/l/?s=aapl.us&i=d").mock(
        return_value=httpx.Response(200, text="<!DOCTYPE html><html><body>Please enable JavaScript</body></html>")
    )

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_get_quote_raises_on_empty_csv(provider: StooqMarketProvider) -> None:
    respx.get("https://stooq.com/q/d/l/?s=aapl.us&i=d").mock(
        return_value=httpx.Response(200, text="Date,Open,High,Low,Close,Volume\n")
    )

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_get_quote_maps_http_error(provider: StooqMarketProvider) -> None:
    respx.get("https://stooq.com/q/d/l/?s=aapl.us&i=d").mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")
