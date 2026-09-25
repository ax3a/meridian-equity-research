from __future__ import annotations

import pytest

from meridian.tools.market import GetMarketQuoteInput, GetMarketQuoteTool
from tests.unit.tools.conftest import FakeMarket, make_registry


async def test_get_market_quote_carries_evidence(make_ctx):
    ctx = make_ctx()
    output = await GetMarketQuoteTool().run(GetMarketQuoteInput(ticker="msft"), ctx)
    assert output.quote.ticker == "MSFT"
    assert output.quote.price == 430.50
    assert len(output.evidence_ids) == 1
    assert ctx.ledger.evidence[output.evidence_ids[0]] is not None
    summary = GetMarketQuoteTool().summarize(output)
    assert "430.50" in summary
    assert output.evidence_ids[0] in summary


async def test_get_market_quote_provider_failure_propagates(make_ctx):
    registry = make_registry(market=FakeMarket(fails=True))
    ctx = make_ctx(providers=registry)
    with pytest.raises(Exception):
        await GetMarketQuoteTool().run(GetMarketQuoteInput(ticker="MSFT"), ctx)
