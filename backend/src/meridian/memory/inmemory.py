"""In-memory implementations of `ResearchMemoryStore` and `PreferenceStore` (frozen protocols).

Used by tests, the CLI and any run that isn't wired to the database-backed repositories (Task 12).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from meridian.memory.freshness import is_expired
from meridian.memory.types import MemoryItem
from meridian.schemas.api import UserPreferences


class InMemoryResearchMemoryStore:
    """Keeps every item ever stored (for `history`) but only ever returns non-expired ones from `get`."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], list[MemoryItem]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def get(self, ticker: str, kind: str) -> MemoryItem | None:
        async with self._lock:
            items = self._items.get((ticker, kind), [])
            fresh = [i for i in items if not is_expired(i.expires_at)]
            return fresh[-1] if fresh else None

    async def put(self, item: MemoryItem) -> None:
        async with self._lock:
            self._items[(item.ticker, item.kind)].append(item)

    async def history(self, ticker: str, limit: int = 5) -> list[MemoryItem]:
        async with self._lock:
            all_for_ticker = [i for (t, _kind), items in self._items.items() if t == ticker for i in items]
        all_for_ticker.sort(key=lambda i: i.created_at, reverse=True)
        return all_for_ticker[:limit]


class InMemoryPreferenceStore:
    def __init__(self) -> None:
        self._prefs: dict[str, UserPreferences] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: str) -> UserPreferences:
        async with self._lock:
            return self._prefs.get(user_id, UserPreferences())

    async def put(self, user_id: str, prefs: UserPreferences) -> None:
        async with self._lock:
            self._prefs[user_id] = prefs


__all__ = ["InMemoryPreferenceStore", "InMemoryResearchMemoryStore"]
