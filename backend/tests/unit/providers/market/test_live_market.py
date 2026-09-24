"""Live reachability checks. Excluded by default; run explicitly with `-m live`.

Findings (recorded 2026-09-24, see task report for detail): Stooq's documented CSV endpoint answers
programmatic clients with an HTTP 200 anti-bot JS-challenge page instead of CSV, so `StooqMarketProvider`
is expected to raise here. Yahoo's unofficial chart endpoint is reachable and returns real OHLC data.
"""

from __future__ import annotations

import pytest

from meridian.providers.market.stooq import StooqMarketProvider
from meridian.providers.market.yahoo import YahooMarketProvider

pytestmark = pytest.mark.live


async def test_stooq_is_blocked_for_programmatic_clients(http_client) -> None:
    """Documents current real-world behaviour rather than asserting success: see module docstring."""
    provider = StooqMarketProvider(http_client)
    with pytest.raises(Exception):
        await provider.get_quote("AAPL", history_days=30)


async def test_yahoo_chart_endpoint_is_reachable(http_client) -> None:
    provider = YahooMarketProvider(http_client)

    result = await provider.get_quote("AAPL", history_days=30)

    assert result.data.price > 0
    assert len(result.data.history) > 0
