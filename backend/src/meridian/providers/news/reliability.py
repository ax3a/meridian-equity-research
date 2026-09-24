"""Domain reliability tiering and spam filtering for news articles.

A headline is evidence that something was *reported*, not evidence the underlying claim is true. This
module lets news providers rank articles by how much editorial trust their outlet carries, and drop
obvious low-quality aggregator/content-mill domains before they ever become evidence.
"""

from __future__ import annotations

from meridian.providers.base import NewsArticle

# Company/regulator primary sources.
PRIMARY_DOMAINS: frozenset[str] = frozenset({"sec.gov"})

# Major wire services and financial dailies with independent editorial standards.
TIER1_DOMAINS: frozenset[str] = frozenset(
    {
        "reuters.com",
        "apnews.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "cnbc.com",
        "barrons.com",
        "economist.com",
    }
)

# Reputable but more opinion/aggregation-oriented outlets.
TIER2_DOMAINS: frozenset[str] = frozenset(
    {
        "techcrunch.com",
        "theverge.com",
        "seekingalpha.com",
        "benzinga.com",
        "fool.com",
        "yahoo.com",
    }
)

# Low-quality content mills / SEO aggregators that republish or auto-generate market "news". Deliberately
# small and explicit: a domain is only added here when it is *known* junk, not merely unrated.
SPAM_DOMAINS: frozenset[str] = frozenset(
    {
        "marketbeat.com",
        "insidermonkey.com",
        "khodrobank.com",
        "financialbuzz.com",
        "newsfilecorp.com",
    }
)

_RANK = {"primary": 0, "tier1": 1, "tier2": 2, "unrated": 3}


def normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    return d[4:] if d.startswith("www.") else d


def _matches(domain: str, bucket: frozenset[str]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in bucket)


def classify(domain: str) -> str:
    """Map a domain to 'primary' | 'tier1' | 'tier2' | 'unrated'."""
    d = normalize_domain(domain)
    if _matches(d, PRIMARY_DOMAINS):
        return "primary"
    if _matches(d, TIER1_DOMAINS):
        return "tier1"
    if _matches(d, TIER2_DOMAINS):
        return "tier2"
    return "unrated"


def is_spam(domain: str) -> bool:
    d = normalize_domain(domain)
    return _matches(d, SPAM_DOMAINS)


def sort_key(article: NewsArticle) -> tuple[int, float]:
    """(reliability_rank, recency) sort key: primary before tier1 before ... ; newest first within a tier."""
    rank = _RANK.get(article.reliability, 3)
    recency = -article.published_at.toordinal() if article.published_at else float("inf")
    return (rank, recency)


def sort_articles(articles: list[NewsArticle]) -> list[NewsArticle]:
    """Sort by reliability tier first, then by recency (most recent first) within a tier."""
    return sorted(articles, key=sort_key)
