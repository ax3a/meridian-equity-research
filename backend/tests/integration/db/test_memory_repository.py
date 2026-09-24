"""Integration tests for `MemoryRepository` and `PreferenceRepository`."""

from __future__ import annotations

from datetime import timedelta

import pytest

from meridian.core.ids import new_id, utcnow
from meridian.db.repositories.memory import MemoryRepository, PreferenceRepository
from meridian.memory.types import MemoryItem
from meridian.schemas.api import UserPreferences

pytestmark = pytest.mark.integration


def _ticker() -> str:
    # Reuse new_id's randomness to keep tickers unique per test without exceeding the 12-char column.
    return "T" + new_id("")[-8:].upper()


async def test_get_returns_none_when_nothing_stored(db_session) -> None:
    repo = MemoryRepository(db_session)
    assert await repo.get(_ticker(), "profile") is None


async def test_put_then_get_returns_the_item(db_session) -> None:
    repo = MemoryRepository(db_session)
    ticker = _ticker()
    item = MemoryItem(
        ticker=ticker,
        kind="profile",
        payload={"sic": "7372"},
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(days=1),
    )
    await repo.put(item)

    fetched = await repo.get(ticker, "profile")
    assert fetched is not None
    assert fetched.payload == {"sic": "7372"}


async def test_expired_item_returns_none(db_session) -> None:
    repo = MemoryRepository(db_session)
    ticker = _ticker()
    expired = MemoryItem(
        ticker=ticker,
        kind="profile",
        payload={"sic": "7372"},
        created_at=utcnow() - timedelta(days=2),
        expires_at=utcnow() - timedelta(days=1),
    )
    await repo.put(expired)

    assert await repo.get(ticker, "profile") is None


async def test_get_returns_most_recent_non_expired_item(db_session) -> None:
    repo = MemoryRepository(db_session)
    ticker = _ticker()
    older = MemoryItem(
        ticker=ticker,
        kind="profile",
        payload={"version": 1},
        created_at=utcnow() - timedelta(hours=2),
        expires_at=utcnow() + timedelta(days=1),
    )
    newer = MemoryItem(
        ticker=ticker,
        kind="profile",
        payload={"version": 2},
        created_at=utcnow() - timedelta(hours=1),
        expires_at=utcnow() + timedelta(days=1),
    )
    await repo.put(older)
    await repo.put(newer)

    fetched = await repo.get(ticker, "profile")
    assert fetched is not None
    assert fetched.payload == {"version": 2}


async def test_history_returns_items_across_kinds_newest_first(db_session) -> None:
    repo = MemoryRepository(db_session)
    ticker = _ticker()
    for i, kind in enumerate(["profile", "financial_metrics", "peer_set"]):
        await repo.put(
            MemoryItem(
                ticker=ticker,
                kind=kind,
                payload={"i": i},
                created_at=utcnow() - timedelta(minutes=3 - i),
                expires_at=utcnow() + timedelta(days=1),
            )
        )

    history = await repo.history(ticker, limit=5)
    assert [h.kind for h in history] == ["peer_set", "financial_metrics", "profile"]


async def test_preferences_default_then_save(db_session) -> None:
    repo = PreferenceRepository(db_session)
    user_id = "user_" + new_id("")[-8:]

    defaults = await repo.get(user_id)
    assert defaults == UserPreferences()

    custom = UserPreferences(report_length="detailed", preferred_sectors=["Technology"])
    await repo.put(user_id, custom)

    saved = await repo.get(user_id)
    assert saved.report_length == "detailed"
    assert saved.preferred_sectors == ["Technology"]

    # Saving again must update in place, not duplicate.
    again = UserPreferences(report_length="brief")
    await repo.put(user_id, again)
    final = await repo.get(user_id)
    assert final.report_length == "brief"
