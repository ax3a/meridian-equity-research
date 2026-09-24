"""Polygon.io market data provider. Optional: requires an API key."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.core.http import HttpClient
from meridian.core.ids import utcnow
from meridian.providers.base import ProviderResult
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import PricePoint, Quote

POLYGON_URL = "https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"


class PolygonProvider:
    """Daily price history from Polygon.io aggregates. Requires ``POLYGON_API_KEY``."""

    name = "polygon"

    def __init__(self, http: HttpClient, api_key: str | None) -> None:
        self._http = http
        self._api_key = api_key

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        if not self._api_key:
            raise ProviderUnavailableError(self.name, "no API key configured")

        symbol = ticker.strip().upper()
        end = utcnow().date()
        # buffer past weekends/holidays so we still end up with `history_days` trading days
        start = end - timedelta(days=int(history_days * 1.6) + 10)
        url = POLYGON_URL.format(symbol=symbol, start=start.isoformat(), end=end.isoformat())
        result = await self._http.get_json(
            url,
            provider=self.name,
            policy=Policies.PRICES,
            params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": self._api_key},
        )
        body = result.body or {}
        status = body.get("status")
        if status not in ("OK", "DELAYED"):
            reason = body.get("error") or body.get("message") or status
            raise ProviderError(self.name, f"polygon returned status={status}: {reason}", retryable=False)

        raw = body.get("results") or []
        points: list[PricePoint] = []
        for bar in raw:
            try:
                day = datetime.fromtimestamp(bar["t"] / 1000, tz=UTC).date()
                close = float(bar["c"])
            except (KeyError, TypeError, ValueError):
                continue
            volume = float(bar["v"]) if bar.get("v") is not None else None
            points.append(PricePoint(day=day, close=close, volume=volume))
        if not points:
            raise ProviderError(self.name, f"no usable price bars for {symbol}", retryable=False)
        points.sort(key=lambda p: p.day)
        trimmed = points[-history_days:] if history_days > 0 else points
        last = trimmed[-1]

        source = Source.make(
            kind=SourceKind.MARKET_DATA,
            title=f"Polygon.io daily aggregates: {symbol}",
            provider=self.name,
            publisher="Polygon.io",
            url=f"https://polygon.io/quote/{symbol}",
        )
        evidence = Evidence.make(
            source_id=source.id,
            text=f"Polygon.io ({last.day.isoformat()}): {symbol} closed at {last.close:.2f}.",
            locator=EvidenceLocator(period=last.day.isoformat()),
        )
        quote = Quote(ticker=symbol, price=last.close, as_of=last.day, source_id=source.id, history=trimmed)
        return ProviderResult(data=quote, provider=self.name, sources=[source], evidence=[evidence])
