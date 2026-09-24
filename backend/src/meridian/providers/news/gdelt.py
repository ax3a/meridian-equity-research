"""GDELT DOC 2.0 keyless news provider.

Verified reachable with a live check on 2026-09-24. GDELT enforces an informal rate limit (their own error
text asks for "one every 5 seconds") and answers over-quota or malformed requests with a plain-text 200
response instead of JSON; ``HttpClient`` already turns a non-JSON body into a ``ProviderError`` (JSON
decode failure), so a ``NewsChain`` can fall back to another provider without crashing.
"""

from __future__ import annotations

from datetime import date, datetime

from meridian.cache.base import Policies
from meridian.core.http import HttpClient
from meridian.providers.base import NewsArticle, ProviderResult
from meridian.providers.news import reliability
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.research import CompanyIdentity

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


class GdeltNewsProvider:
    """Keyless news search over the GDELT DOC 2.0 API."""

    name = "gdelt"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def search_news(
        self, company: CompanyIdentity, days: int = 90, limit: int = 25
    ) -> ProviderResult[list[NewsArticle]]:
        params = {
            "query": f'"{company.name}" sourcelang:english',
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(min(max(limit, 1), 250)),
            "timespan": f"{max(days, 1)}d",
            "sort": "DateDesc",
        }
        result = await self._http.get_json(GDELT_URL, provider=self.name, policy=Policies.NEWS, params=params)
        raw_articles = (result.body or {}).get("articles") or []

        triples: list[tuple[NewsArticle, Source, Evidence]] = []
        for raw in raw_articles[:limit]:
            title = (raw.get("title") or "").strip()
            url = raw.get("url")
            domain = (raw.get("domain") or _domain_from_url(url) or "").strip()
            if not title or not url or not domain or reliability.is_spam(domain):
                continue

            published = _parse_seendate(raw.get("seendate"))
            tier = reliability.classify(domain)
            article = NewsArticle(
                title=title,
                url=url,
                published_at=published,
                publisher=domain,
                language=raw.get("language"),
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
        ordered_articles = [t[0] for t in triples]
        sources = [t[1] for t in triples]
        evidence = [t[2] for t in triples]

        return ProviderResult(
            data=ordered_articles,
            provider=self.name,
            sources=sources,
            evidence=evidence,
            is_snapshot=result.from_snapshot,
        )


def _parse_seendate(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").date()
    except ValueError:
        return None


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    host = urlparse(url).hostname
    return host.lower() if host else None
