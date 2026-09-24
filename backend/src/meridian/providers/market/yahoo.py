"""Yahoo Finance chart endpoint as the keyless market-data fallback.

This is an **unofficial, undocumented endpoint** (no published API contract, no key). It is used because
a live reachability check on 2026-09-24 found that Stooq's CSV export (the primary documented keyless
source; see ``providers.market.stooq``) blocks programmatic clients with an anti-bot challenge page, while
this endpoint returned normal OHLC chart JSON. Since it is unofficial it may change or disappear without
notice -- callers should still list a keyed provider (FMP/Alpha Vantage/Polygon) after this one in a
``MarketChain`` for production resilience.
"""

from __future__ import annotations

from datetime import UTC, datetime

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError
from meridian.core.http import HttpClient
from meridian.providers.base import ProviderResult
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import PricePoint, Quote

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _range_for(history_days: int) -> str:
    if history_days <= 5:
        return "5d"
    if history_days <= 30:
        return "1mo"
    if history_days <= 90:
        return "3mo"
    if history_days <= 180:
        return "6mo"
    if history_days <= 365:
        return "1y"
    if history_days <= 730:
        return "2y"
    if history_days <= 1825:
        return "5y"
    return "10y"


class YahooMarketProvider:
    """Keyless daily price history from Yahoo Finance's chart endpoint (unofficial)."""

    name = "yahoo"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        symbol = ticker.strip().upper()
        url = YAHOO_URL.format(symbol=symbol)
        result = await self._http.get_json(
            url,
            provider=self.name,
            policy=Policies.PRICES,
            params={"interval": "1d", "range": _range_for(history_days)},
        )
        history = _parse_chart(result.body, provider=self.name, ticker=ticker)
        history = history[-history_days:] if history_days > 0 else history
        last = history[-1]

        source = Source.make(
            kind=SourceKind.MARKET_DATA,
            title=f"Yahoo Finance chart: {symbol}",
            provider=self.name,
            publisher="Yahoo Finance",
            url=f"https://finance.yahoo.com/quote/{symbol}",
            metadata={"unofficial_endpoint": True},
        )
        evidence = Evidence.make(
            source_id=source.id,
            text=f"Yahoo Finance ({last.day.isoformat()}): {symbol} closed at {last.close:.2f}.",
            locator=EvidenceLocator(period=last.day.isoformat()),
        )
        quote = Quote(ticker=symbol, price=last.close, as_of=last.day, source_id=source.id, history=history)
        return ProviderResult(
            data=quote,
            provider=self.name,
            sources=[source],
            evidence=[evidence],
            is_snapshot=result.from_snapshot,
        )


def _parse_chart(body: object, *, provider: str, ticker: str) -> list[PricePoint]:
    try:
        chart = body["chart"]  # type: ignore[index]
        if chart.get("error"):
            raise ProviderError(provider, f"yahoo reported an error for {ticker}: {chart['error']}", retryable=False)
        results = chart["result"]
        if not results:
            raise ProviderError(provider, f"no chart result for {ticker}", retryable=False)
        payload = results[0]
        timestamps = payload["timestamp"]
        quote0 = payload["indicators"]["quote"][0]
        closes = quote0["close"]
        volumes = quote0.get("volume") or [None] * len(timestamps)
    except ProviderError:
        raise
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(provider, f"unexpected yahoo chart response shape for {ticker}", retryable=False) from exc

    points: list[PricePoint] = []
    for ts, close, volume in zip(timestamps, closes, volumes, strict=False):
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=UTC).date()
        points.append(PricePoint(day=day, close=float(close), volume=float(volume) if volume is not None else None))
    if not points:
        raise ProviderError(provider, f"no usable price points for {ticker}", retryable=False)
    points.sort(key=lambda p: p.day)
    return points
