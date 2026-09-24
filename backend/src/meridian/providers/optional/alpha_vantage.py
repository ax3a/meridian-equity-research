"""Alpha Vantage market data provider. Optional: requires an API key.

Alpha Vantage answers most failure modes (bad symbol, rate limit) with an HTTP 200 body containing an
"Error Message" or "Note"/"Information" key rather than a non-2xx status, so those have to be detected in
the parsed body instead of relying on ``HttpClient``'s status-code mapping.
"""

from __future__ import annotations

from datetime import datetime

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.core.http import HttpClient
from meridian.providers.base import ProviderResult
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import PricePoint, Quote

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
TIME_SERIES_KEY = "Time Series (Daily)"


class AlphaVantageProvider:
    """Daily price history from Alpha Vantage. Requires ``ALPHA_VANTAGE_API_KEY``."""

    name = "alpha_vantage"

    def __init__(self, http: HttpClient, api_key: str | None) -> None:
        self._http = http
        self._api_key = api_key

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        if not self._api_key:
            raise ProviderUnavailableError(self.name, "no API key configured")

        symbol = ticker.strip().upper()
        outputsize = "compact" if history_days <= 100 else "full"
        result = await self._http.get_json(
            ALPHA_VANTAGE_URL,
            provider=self.name,
            policy=Policies.PRICES,
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": self._api_key,
                "outputsize": outputsize,
            },
        )
        body = result.body or {}
        if "Error Message" in body:
            raise ProviderError(
                self.name, f"alpha vantage error for {symbol}: {body['Error Message']}", retryable=False
            )
        if "Note" in body or "Information" in body:
            raise ProviderError(self.name, "alpha vantage rate limit or plan restriction", retryable=True)
        series = body.get(TIME_SERIES_KEY)
        if not series:
            raise ProviderError(self.name, f"unexpected alpha vantage response shape for {symbol}", retryable=False)

        points: list[PricePoint] = []
        for day_str, values in series.items():
            try:
                day = datetime.strptime(day_str, "%Y-%m-%d").date()
                close = float(values["4. close"])
            except (KeyError, ValueError):
                continue
            raw_volume = values.get("5. volume")
            volume = float(raw_volume) if raw_volume not in (None, "") else None
            points.append(PricePoint(day=day, close=close, volume=volume))
        if not points:
            raise ProviderError(self.name, f"no usable price points for {symbol}", retryable=False)
        points.sort(key=lambda p: p.day)
        trimmed = points[-history_days:] if history_days > 0 else points
        last = trimmed[-1]

        source = Source.make(
            kind=SourceKind.MARKET_DATA,
            title=f"Alpha Vantage daily prices: {symbol}",
            provider=self.name,
            publisher="Alpha Vantage",
            url=f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}",
        )
        evidence = Evidence.make(
            source_id=source.id,
            text=f"Alpha Vantage ({last.day.isoformat()}): {symbol} closed at {last.close:.2f}.",
            locator=EvidenceLocator(period=last.day.isoformat()),
        )
        quote = Quote(ticker=symbol, price=last.close, as_of=last.day, source_id=source.id, history=trimmed)
        return ProviderResult(data=quote, provider=self.name, sources=[source], evidence=[evidence])
