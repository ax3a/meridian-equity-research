"""In-memory ResearchMemoryStore / PreferenceStore behaviour, including TTL expiry."""

from __future__ import annotations

from datetime import timedelta

from meridian.core.ids import utcnow
from meridian.memory.freshness import compute_expiry, ttl_for
from meridian.memory.inmemory import InMemoryPreferenceStore, InMemoryResearchMemoryStore
from meridian.memory.types import MemoryItem
from meridian.schemas.api import UserPreferences


def make_item(ticker: str, kind: str, *, expires_in: timedelta | None = None) -> MemoryItem:
    now = utcnow()
    expires_at = now + expires_in if expires_in is not None else compute_expiry(kind, now=now)
    return MemoryItem(ticker=ticker, kind=kind, payload={"x": 1}, created_at=now, expires_at=expires_at)


def test_ttl_for_known_kinds() -> None:
    assert ttl_for("profile") == timedelta(days=30)
    assert ttl_for("financial_metrics") == timedelta(days=7)
    assert ttl_for("peer_set") == timedelta(days=30)
    assert ttl_for("research_summary") == timedelta(days=90)
    assert ttl_for("unknown_kind") == timedelta(days=7)


async def test_put_then_get_returns_fresh_item() -> None:
    store = InMemoryResearchMemoryStore()
    item = make_item("MSFT", "profile")
    await store.put(item)
    got = await store.get("MSFT", "profile")
    assert got is not None
    assert got.ticker == "MSFT"
    assert got.payload == {"x": 1}


async def test_expired_item_returns_none() -> None:
    store = InMemoryResearchMemoryStore()
    expired = make_item("MSFT", "financial_metrics", expires_in=timedelta(seconds=-1))
    await store.put(expired)
    assert await store.get("MSFT", "financial_metrics") is None


async def test_get_is_scoped_by_ticker_and_kind() -> None:
    store = InMemoryResearchMemoryStore()
    await store.put(make_item("MSFT", "profile"))
    assert await store.get("NVDA", "profile") is None
    assert await store.get("MSFT", "peer_set") is None


async def test_history_returns_most_recent_first_limited() -> None:
    store = InMemoryResearchMemoryStore()
    now = utcnow()
    for i in range(3):
        item = MemoryItem(
            ticker="MSFT",
            kind="research_summary",
            payload={"i": i},
            created_at=now + timedelta(seconds=i),
            expires_at=now + timedelta(days=90),
        )
        await store.put(item)
    history = await store.history("MSFT", limit=2)
    assert len(history) == 2
    assert history[0].payload == {"i": 2}
    assert history[1].payload == {"i": 1}


async def test_preference_store_default_then_round_trip() -> None:
    store = InMemoryPreferenceStore()
    defaults = await store.get("user-1")
    assert defaults == UserPreferences()

    custom = UserPreferences(report_length="brief", require_approval=False)
    await store.put("user-1", custom)
    got = await store.get("user-1")
    assert got.report_length == "brief"
    assert got.require_approval is False
    # a different user is unaffected
    assert await store.get("user-2") == UserPreferences()
