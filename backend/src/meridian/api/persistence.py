"""Database-backed `ResearchMemoryStore`/`PreferenceStore` adapters.

Each method opens and commits its own short-lived `AsyncSession` around the corresponding repository
(`db/repositories/memory.py`), so these adapters can be handed to `AgentDeps.memory` / used by the
`/preferences` routes exactly like the frozen in-memory implementations in `memory/inmemory.py`, just
durable across process restarts.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meridian.db.repositories.memory import MemoryRepository, PreferenceRepository
from meridian.memory.types import MemoryItem
from meridian.schemas.api import UserPreferences


class DbResearchMemoryStore:
    """`ResearchMemoryStore` backed by the `research_memory` table."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, ticker: str, kind: str) -> MemoryItem | None:
        async with self._sessions() as session:
            return await MemoryRepository(session).get(ticker, kind)

    async def put(self, item: MemoryItem) -> None:
        async with self._sessions() as session:
            await MemoryRepository(session).put(item)
            await session.commit()

    async def history(self, ticker: str, limit: int = 5) -> list[MemoryItem]:
        async with self._sessions() as session:
            return await MemoryRepository(session).history(ticker, limit)


class DbPreferenceStore:
    """`PreferenceStore` backed by `user_preferences`."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, user_id: str) -> UserPreferences:
        async with self._sessions() as session:
            return await PreferenceRepository(session).get(user_id)

    async def put(self, user_id: str, prefs: UserPreferences) -> None:
        async with self._sessions() as session:
            await PreferenceRepository(session).put(user_id, prefs)
            await session.commit()
