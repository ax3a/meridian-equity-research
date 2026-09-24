from __future__ import annotations

from datetime import date

from meridian.providers.base import NewsArticle
from meridian.providers.news import reliability


def test_classify_primary() -> None:
    assert reliability.classify("sec.gov") == "primary"
    assert reliability.classify("www.sec.gov") == "primary"


def test_classify_tier1() -> None:
    assert reliability.classify("reuters.com") == "tier1"
    assert reliability.classify("www.bloomberg.com") == "tier1"
    assert reliability.classify("wsj.com") == "tier1"


def test_classify_tier2() -> None:
    assert reliability.classify("techcrunch.com") == "tier2"
    assert reliability.classify("fool.com") == "tier2"


def test_classify_unrated_for_unknown_domain() -> None:
    assert reliability.classify("some-random-blog.example") == "unrated"


def test_classify_matches_subdomains() -> None:
    assert reliability.classify("markets.businessinsider.com") == "unrated"
    assert reliability.classify("investor.reuters.com") == "tier1"


def test_is_spam_flags_known_aggregators() -> None:
    assert reliability.is_spam("marketbeat.com") is True
    assert reliability.is_spam("reuters.com") is False


def test_sort_articles_orders_by_reliability_then_recency() -> None:
    articles = [
        NewsArticle(
            title="unrated old",
            url="https://u/1",
            published_at=date(2026, 1, 1),
            publisher="blog.example",
            reliability="unrated",
        ),
        NewsArticle(
            title="tier1 new",
            url="https://u/2",
            published_at=date(2026, 9, 1),
            publisher="reuters.com",
            reliability="tier1",
        ),
        NewsArticle(
            title="tier1 old",
            url="https://u/3",
            published_at=date(2026, 1, 1),
            publisher="reuters.com",
            reliability="tier1",
        ),
        NewsArticle(
            title="primary",
            url="https://u/4",
            published_at=date(2026, 5, 1),
            publisher="sec.gov",
            reliability="primary",
        ),
        NewsArticle(
            title="tier1 undated", url="https://u/5", published_at=None, publisher="reuters.com", reliability="tier1"
        ),
    ]

    ordered = reliability.sort_articles(articles)

    assert [a.title for a in ordered] == ["primary", "tier1 new", "tier1 old", "tier1 undated", "unrated old"]
