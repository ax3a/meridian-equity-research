"""In-process `RunStore` used whenever Postgres is unavailable (or not configured).

Implements the same four methods as `graph.runner.RunStore`/`InMemoryRunStore` (structural, not a
subclass -- `graph/runner.py` is frozen) plus the read-side extras (`get_meta`/`list_recent`/
`count_active`) the API needs for listing runs and building the dashboard, which the graph's own
`RunStore` protocol has no reason to define.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from meridian.core.ids import utcnow
from meridian.schemas.enums import RECOVERABLE_RUN_STATUSES, TERMINAL_RUN_STATUSES
from meridian.schemas.events import ProgressEvent
from meridian.schemas.state import ResearchState


@dataclass
class RunRecord:
    """A `ResearchState` plus the created/updated timestamps the state itself doesn't carry."""

    session_id: str
    state: ResearchState
    created_at: datetime
    updated_at: datetime


class LocalRunStore:
    """Thread-safe (asyncio-safe) in-memory `RunStore` with listing support.

    Used as the fallback whenever the database is unreachable, and always used by the CLI (a one-shot
    process has no need for cross-run persistence).
    """

    def __init__(self) -> None:
        self._states: dict[str, ResearchState] = {}
        self._meta: dict[str, tuple[datetime, datetime]] = {}
        self._events: dict[str, list[ProgressEvent]] = defaultdict(list)
        self._order: list[str] = []
        self._lock = asyncio.Lock()

    # ---- RunStore protocol (structural match with graph.runner.RunStore) ----
    async def save_state(self, session_id: str, state: ResearchState) -> None:
        async with self._lock:
            now = utcnow()
            if session_id not in self._states:
                self._meta[session_id] = (now, now)
                self._order.append(session_id)
            else:
                created, _ = self._meta[session_id]
                self._meta[session_id] = (created, now)
            self._states[session_id] = state

    async def get_state(self, session_id: str) -> ResearchState | None:
        return self._states.get(session_id)

    async def save_event(self, session_id: str, event: ProgressEvent) -> int:
        async with self._lock:
            events = self._events[session_id]
            seq = len(events) + 1
            event.seq = seq
            events.append(event)
            return seq

    async def list_events_since(self, session_id: str, after_seq: int) -> list[ProgressEvent]:
        return [e for e in self._events.get(session_id, []) if e.seq > after_seq]

    # ---- read extras used by the API layer ----
    async def get_meta(self, session_id: str) -> RunRecord | None:
        state = self._states.get(session_id)
        if state is None:
            return None
        created, updated = self._meta[session_id]
        return RunRecord(session_id=session_id, state=state, created_at=created, updated_at=updated)

    async def list_recent(self, limit: int) -> list[RunRecord]:
        tail = self._order[-limit:] if limit > 0 else []
        ids: Iterable[str] = reversed(tail)
        records = []
        for session_id in ids:
            rec = await self.get_meta(session_id)
            if rec is not None:
                records.append(rec)
        return records

    async def count_active(self) -> int:
        return sum(1 for s in self._states.values() if s.status not in TERMINAL_RUN_STATUSES)

    async def list_recoverable(self) -> list[str]:
        return [sid for sid, s in self._states.items() if s.status in RECOVERABLE_RUN_STATUSES]
