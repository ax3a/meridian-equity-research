"""Stooq keyless daily-CSV market data provider.

Stooq is documented as a keyless price source (``https://stooq.com/q/d/l/?s={ticker}.us&i=d``), but as
verified with a live reachability check on 2026-09-24, it now answers programmatic clients with an
anti-bot JavaScript "prove you're a browser" challenge page instead of CSV -- with an HTTP 200 status, so
the failure is only detectable by inspecting the body. This provider validates that the response actually
looks like the documented CSV before parsing it and raises ``ProviderError`` otherwise, so a
``MarketChain`` can fall back to ``providers.market.yahoo.YahooMarketProvider`` (or a keyed provider)
without crashing.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError
from meridian.core.http import HttpClient
from meridian.providers.base import ProviderResult
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import PricePoint, Quote

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}.us&i=d"


class StooqMarketProvider:
    """Keyless daily price history from Stooq's CSV export."""

    name = "stooq"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        symbol = ticker.strip().lower()
        url = STOOQ_URL.format(symbol=symbol)
        result = await self._http.get_text(url, provider=self.name, policy=Policies.PRICES)
        rows = _parse_csv(result.body, provider=self.name, ticker=ticker)
        rows.sort(key=lambda r: r[0])
        history = rows[-history_days:] if history_days > 0 else rows
        last_day, last_close, _ = history[-1]

        source = Source.make(
            kind=SourceKind.MARKET_DATA,
            title=f"Stooq daily prices: {ticker.upper()}",
            provider=self.name,
            publisher="Stooq",
            url=f"https://stooq.com/q/?s={symbol}.us",
        )
        evidence = Evidence.make(
            source_id=source.id,
            text=f"Stooq ({last_day.isoformat()}): {ticker.upper()} closed at {last_close:.2f}.",
            locator=EvidenceLocator(period=last_day.isoformat()),
        )
        quote = Quote(
            ticker=ticker.upper(),
            price=last_close,
            as_of=last_day,
            source_id=source.id,
            history=[PricePoint(day=d, close=c, volume=v) for d, c, v in history],
        )
        return ProviderResult(
            data=quote,
            provider=self.name,
            sources=[source],
            evidence=[evidence],
            is_snapshot=result.from_snapshot,
        )


def _parse_csv(text: str, *, provider: str, ticker: str) -> list[tuple[date, float, float | None]]:
    stripped = text.strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    if not first_line.startswith("Date,"):
        raise ProviderError(
            provider, f"unexpected response body for {ticker} (not CSV -- likely blocked)", retryable=False
        )
    reader = csv.DictReader(io.StringIO(stripped))
    rows: list[tuple[date, float, float | None]] = []
    for row in reader:
        try:
            day = datetime.strptime(row["Date"], "%Y-%m-%d").date()
            close = float(row["Close"])
        except (KeyError, ValueError, TypeError):
            continue
        volume: float | None = None
        raw_volume = row.get("Volume")
        if raw_volume not in (None, ""):
            try:
                volume = float(raw_volume)
            except ValueError:
                volume = None
        rows.append((day, close, volume))
    if not rows:
        raise ProviderError(provider, f"no usable price rows for {ticker}", retryable=False)
    return rows
