from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError
from meridian.providers.news.gdelt import GdeltNewsProvider
from meridian.schemas.research import CompanyIdentity

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


@pytest.fixture
def provider(http_client) -> GdeltNewsProvider:
    return GdeltNewsProvider(http_client)


@pytest.fixture
def company() -> CompanyIdentity:
    return CompanyIdentity(name="Apple Inc.", ticker="AAPL", cik="320193")


GDELT_BODY = {
    "articles": [
        {
            "url": "https://www.reuters.com/tech/apple-story",
            "title": "Apple posts strong quarter",
            "seendate": "20260924T210000Z",
            "domain": "reuters.com",
            "language": "English",
        },
        {
            "url": "https://marketbeat.com/spam-story",
            "title": "Apple aggregator spam",
            "seendate": "20260924T200000Z",
            "domain": "marketbeat.com",
            "language": "English",
        },
        {
            "url": "https://fool.com/apple-analysis",
            "title": "Should you buy Apple now?",
            "seendate": "20260923T120000Z",
            "domain": "fool.com",
            "language": "English",
        },
    ]
}


@respx.mock
async def test_search_news_parses_and_ranks_articles(provider: GdeltNewsProvider, company: CompanyIdentity) -> None:
    respx.get(GDELT_URL).mock(return_value=httpx.Response(200, json=GDELT_BODY))

    result = await provider.search_news(company, days=30, limit=25)

    assert provider.name == "gdelt"
    assert result.provider == "gdelt"
    titles = [a.title for a in result.data]
    assert "Apple aggregator spam" not in titles  # spam domain dropped
    assert titles == ["Apple posts strong quarter", "Should you buy Apple now?"]  # tier1 before tier2
    assert result.data[0].reliability == "tier1"
    assert result.data[0].publisher == "reuters.com"
    assert result.data[0].published_at.isoformat() == "2026-09-24"


@respx.mock
async def test_search_news_evidence_reflects_headline_not_fact(
    provider: GdeltNewsProvider, company: CompanyIdentity
) -> None:
    respx.get(GDELT_URL).mock(return_value=httpx.Response(200, json=GDELT_BODY))

    result = await provider.search_news(company, days=30, limit=25)

    assert len(result.evidence) == len(result.sources) == 2
    ev = result.evidence[0]
    assert ev.text.startswith("reuters.com (2026-09-24):")
    assert "Apple posts strong quarter" in ev.text
    src = next(s for s in result.sources if s.id == ev.source_id)
    assert src.metadata["evidence_type"] == "headline"


@respx.mock
async def test_search_news_empty_results(provider: GdeltNewsProvider, company: CompanyIdentity) -> None:
    respx.get(GDELT_URL).mock(return_value=httpx.Response(200, json={"articles": []}))

    result = await provider.search_news(company)

    assert result.data == []
    assert result.evidence == []
    assert result.sources == []


@respx.mock
async def test_search_news_maps_http_error(provider: GdeltNewsProvider, company: CompanyIdentity) -> None:
    respx.get(GDELT_URL).mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.search_news(company)


@respx.mock
async def test_search_news_maps_rate_limit_plaintext_body(
    provider: GdeltNewsProvider, company: CompanyIdentity
) -> None:
    """GDELT sometimes answers a 200 with a plain-text rate-limit notice instead of JSON."""
    respx.get(GDELT_URL).mock(return_value=httpx.Response(200, text="Please limit requests to one every 5 seconds"))

    with pytest.raises(ProviderError):
        await provider.search_news(company)
