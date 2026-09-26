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
from meridian.core.logging import get_logger
from meridian.db.repositories.events import EventRepository
from meridian.db.repositories.evidence import EvidenceRepository
from meridian.db.repositories.reports import ReportRepository
from meridian.db.repositories.research import ResearchRepository
from meridian.db.repositories.telemetry import TelemetryRepository
from meridian.schemas.enums import TERMINAL_RUN_STATUSES
from meridian.schemas.events import ProgressEvent
from meridian.schemas.state import ResearchState

log = get_logger(__name__)


@dataclass
class RunRecord:
    """A `ResearchState` plus the created/updated timestamps the state itself doesn't carry."""

    session_id: str
    state: ResearchState
    created_at: datetime
    updated_at: datetime


class DbRunStore:
    """`RunStore` implementation backed by `research_sessions`/`research_events`.

    During a run, `ResearchState` is round-tripped as a single JSONB blob (see
    `ResearchRepository.save_state`), which is enough to reconstruct every read-side view the API
    exposes without keeping the normalised tables in sync on every step.

    When a run reaches a terminal state the artefacts are written out once into the normalised tables
    (`agent_runs`, `tool_calls`, `llm_usage`, `sources`, `evidence`, `findings`, `report_versions`), so
    finished research is queryable with ordinary SQL rather than only by unpacking JSON. Doing it once
    at the end keeps the hot path cheap; failing to do it never fails the run.
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
            if state.status in TERMINAL_RUN_STATUSES:
                await self._persist_artifacts(session, session_id, state)
            await session.commit()

    async def _persist_artifacts(self, session: AsyncSession, session_id: str, state: ResearchState) -> None:
        """Write the finished run into the normalised tables. Best effort: a reporting problem here must
        not lose the run itself, which is already safe in the JSONB snapshot."""
        try:
            research = ResearchRepository(session)
            await research.upsert_tasks(session_id, list(state.tasks.values()))
            waves = {t.agent.value: t.wave for t in state.tasks.values()}
            for agent_key, output in state.outputs.items():
                await research.upsert_agent_run(session_id, output, waves.get(agent_key, 1))
            for review in state.critic_reviews:
                await research.save_critic_review(session_id, review)

            evidence_repo = EvidenceRepository(session)
            await evidence_repo.save_sources(session_id, list(state.sources.values()))
            await evidence_repo.save_evidence(session_id, list(state.evidence.values()))
            await evidence_repo.save_findings(session_id, state.findings())

            telemetry = TelemetryRepository(session)
            await telemetry.save_tool_calls(session_id, state.tool_calls)
            await telemetry.save_usage(session_id, state.usage)

            if state.report is not None:
                await ReportRepository(session).add_version(session_id, state.report)
        except Exception as exc:
            log.warning("run_artifacts_not_persisted", session_id=session_id, error=str(exc))

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

    async def list_recoverable(self) -> list[str]:
        async with self._sessions() as session:
            return await ResearchRepository(session).list_recoverable()
