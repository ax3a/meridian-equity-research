"""Finnhub provider: market data, company news and a peer ticker list. Optional: requires an API key.

Finnhub's free-tier peers endpoint (``/stock/peers``) returns bare ticker symbols only -- no CIK, no
company name, no financials. Since ``PeerCandidate.company`` requires a full ``CompanyIdentity`` (name +
ticker + CIK), and resolving a ticker to a CIK is SEC EDGAR's job (a different provider's territory), each
candidate here carries the ticker as a placeholder name and a zero-padded placeholder CIK, and the
``ProviderResult`` carries a warning explaining the gap. Callers that need a fully-identified peer should
still resolve it through a ``CompanyDirectory`` before citing it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.core.http import HttpClient
from meridian.core.ids import utcnow
from meridian.providers.base import NewsArticle, PeerCandidate, ProviderResult
from meridian.providers.news import reliability
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import PricePoint, Quote
from meridian.schemas.research import CompanyIdentity

QUOTE_URL = "https://finnhub.io/api/v1/quote"
CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"
NEWS_URL = "https://finnhub.io/api/v1/company-news"
PEERS_URL = "https://finnhub.io/api/v1/stock/peers"


class FinnhubProvider:
    """Market data, company news and peer tickers from Finnhub. Requires ``FINNHUB_API_KEY``."""

    name = "finnhub"

    def __init__(self, http: HttpClient, api_key: str | None) -> None:
        self._http = http
        self._api_key = api_key

    def _require_key(self) -> str:
        if not self._api_key:
            raise ProviderUnavailableError(self.name, "no API key configured")
        return self._api_key

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        token = self._require_key()
        symbol = ticker.strip().upper()
        end = utcnow()
        start = end - timedelta(days=int(history_days * 1.6) + 10)
        result = await self._http.get_json(
            CANDLE_URL,
            provider=self.name,
            policy=Policies.PRICES,
            params={
                "symbol": symbol,
                "resolution": "D",
                "from": int(start.timestamp()),
                "to": int(end.timestamp()),
                "token": token,
            },
        )
        body = result.body or {}
        if body.get("s") != "ok":
            raise ProviderError(self.name, f"finnhub candle status={body.get('s')!r} for {symbol}", retryable=False)

        closes, timestamps, volumes = body.get("c") or [], body.get("t") or [], body.get("v") or []
        points: list[PricePoint] = []
        for ts, close, volume in zip(timestamps, closes, volumes, strict=False):
            if close is None:
                continue
            day = datetime.fromtimestamp(ts, tz=UTC).date()
            points.append(PricePoint(day=day, close=float(close), volume=float(volume) if volume is not None else None))
        if not points:
            raise ProviderError(self.name, f"no usable price bars for {symbol}", retryable=False)
        points.sort(key=lambda p: p.day)
        trimmed = points[-history_days:] if history_days > 0 else points
        last = trimmed[-1]

        source = Source.make(
            kind=SourceKind.MARKET_DATA,
            title=f"Finnhub daily candles: {symbol}",
            provider=self.name,
            publisher="Finnhub",
            url=f"https://finnhub.io/quote/{symbol}",
        )
        evidence = Evidence.make(
            source_id=source.id,
            text=f"Finnhub ({last.day.isoformat()}): {symbol} closed at {last.close:.2f}.",
            locator=EvidenceLocator(period=last.day.isoformat()),
        )
        quote = Quote(ticker=symbol, price=last.close, as_of=last.day, source_id=source.id, history=trimmed)
        return ProviderResult(data=quote, provider=self.name, sources=[source], evidence=[evidence])

    async def search_news(
        self, company: CompanyIdentity, days: int = 90, limit: int = 25
    ) -> ProviderResult[list[NewsArticle]]:
        token = self._require_key()
        end = utcnow().date()
        start = end - timedelta(days=days)
        result = await self._http.get_json(
            NEWS_URL,
            provider=self.name,
            policy=Policies.NEWS,
            params={"symbol": company.ticker, "from": start.isoformat(), "to": end.isoformat(), "token": token},
        )
        raw_articles = result.body if isinstance(result.body, list) else []

        triples: list[tuple[NewsArticle, Source, Evidence]] = []
        for raw in raw_articles[:limit]:
            title = (raw.get("headline") or "").strip()
            url = raw.get("url")
            domain = raw.get("source") or ""
            if not title or not url or reliability.is_spam(domain):
                continue
            published = _epoch_to_date(raw.get("datetime"))
            tier = reliability.classify(domain)
            article = NewsArticle(
                title=title,
                url=url,
                published_at=published,
                publisher=domain,
                snippet=raw.get("summary"),
                reliability=tier,
            )
            source = Source.make(
                kind=SourceKind.NEWS,
                title=title,
                provider=self.name,
                publisher=domain,
                url=url,
                published_at=published,
                metadata={"evidence_type": "headline", "reliability": tier},
            )
            date_label = published.isoformat() if published else "date unknown"
            ev = Evidence.make(
                source_id=source.id,
                text=f"{domain} ({date_label}): {title}",
                locator=EvidenceLocator(section="headline"),
            )
            triples.append((article, source, ev))

        triples.sort(key=lambda t: reliability.sort_key(t[0]))
        return ProviderResult(
            data=[t[0] for t in triples],
            provider=self.name,
            sources=[t[1] for t in triples],
            evidence=[t[2] for t in triples],
        )

    async def candidate_peers(self, company: CompanyIdentity, limit: int = 12) -> ProviderResult[list[PeerCandidate]]:
        token = self._require_key()
        result = await self._http.get_json(
            PEERS_URL,
            provider=self.name,
            policy=Policies.PROFILE,
            params={"symbol": company.ticker, "token": token},
        )
        tickers = [t for t in (result.body or []) if isinstance(t, str) and t.upper() != company.ticker.upper()]
        tickers = tickers[:limit]

        source = Source.make(
            kind=SourceKind.PEER_DATA,
            title=f"Finnhub peers: {company.ticker}",
            provider=self.name,
            publisher="Finnhub",
            url=f"https://finnhub.io/quote/{company.ticker}/peers",
        )
        candidates = [
            PeerCandidate(
                company=CompanyIdentity(name=ticker, ticker=ticker, cik="0"),
                reason="Listed as a Finnhub sector/industry peer",
            )
            for ticker in tickers
        ]
        evidence = [
            Evidence.make(
                source_id=source.id,
                text=f"Finnhub lists {ticker} as a peer of {company.ticker}.",
                locator=EvidenceLocator(),
            )
            for ticker in tickers
        ]
        limitation = "finnhub peers are ticker-only: name and CIK are placeholders pending directory lookup"
        warnings = [limitation] if tickers else []
        return ProviderResult(
            data=candidates,
            provider=self.name,
            sources=[source] if tickers else [],
            evidence=evidence,
            warnings=warnings,
        )


def _epoch_to_date(value: object) -> date | None:
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, tz=UTC).date()
