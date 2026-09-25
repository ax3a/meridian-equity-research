"""Postgres-backed `RunStore` (Task 12).

Satisfies the same structural protocol as `graph.runner.RunStore` (`save_state`/`get_state`/
`save_event`/`list_events_since`) so a `ResearchRunner` can use it directly, plus the read-side extras
(`get_meta`/`list_recent`/`count_active`) the API needs for listing runs. Each method opens and commits
its own short-lived `AsyncSession` -- the store owns no long-lived transaction, which keeps it safe to
share across concurrently running research sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from meridian.core.config import Settings
from meridian.db.repositories.events import EventRepository
from meridian.db.repositories.research import ResearchRepository
from meridian.schemas.events import ProgressEvent
from meridian.schemas.state import ResearchState


@dataclass
class RunRecord:
    """A `ResearchState` plus the created/updated timestamps the state itself doesn't carry."""

    session_id: str
    state: ResearchState
    created_at: datetime
    updated_at: datetime


class DbRunStore:
    """`RunStore` implementation backed by `research_sessions`/`research_events`.

    `ResearchState` is round-tripped as a single JSONB blob (see `ResearchRepository.save_state`), which
    is enough to reconstruct every read-side view the API exposes (status, detail, agents, sources,
    trace, review) without also having to keep the normalised tables (`agent_runs`, `sources`, ...)
    perfectly in sync on every step. Those tables exist for other consumers (e.g. evals) to query
    directly; this store does not populate them.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessions = sessions
        self._settings = settings

    async def save_state(self, session_id: str, state: ResearchState) -> None:
        async with self._sessions() as session:
            repo = ResearchRepository(session)
            existing = await repo.get(session_id)
            if existing is None:
                await repo.create(session_id, state.request, self._settings.llm_mode, self._settings.data_mode)
            await repo.save_state(session_id, state)
            await session.commit()

    async def get_state(self, session_id: str) -> ResearchState | None:
        async with self._sessions() as session:
            rec = await ResearchRepository(session).get(session_id)
            return rec.state if rec else None

    async def save_event(self, session_id: str, event: ProgressEvent) -> int:
        async with self._sessions() as session:
            seq = await EventRepository(session).append(event)
            await session.commit()
            return seq

    async def list_events_since(self, session_id: str, after_seq: int) -> list[ProgressEvent]:
        async with self._sessions() as session:
            return await EventRepository(session).list_since(session_id, after_seq)

    # ---- read extras used by the API layer ----
    async def get_meta(self, session_id: str) -> RunRecord | None:
        async with self._sessions() as session:
            rec = await ResearchRepository(session).get(session_id)
        if rec is None or rec.state is None:
            return None
        return RunRecord(session_id=session_id, state=rec.state, created_at=rec.created_at, updated_at=rec.updated_at)

    async def list_recent(self, limit: int) -> list[RunRecord]:
        async with self._sessions() as session:
            records = await ResearchRepository(session).list_recent(limit)
        return [
            RunRecord(session_id=r.id, state=r.state, created_at=r.created_at, updated_at=r.updated_at)
            for r in records
            if r.state is not None
        ]

    async def count_active(self) -> int:
        async with self._sessions() as session:
            return await ResearchRepository(session).count_active()
