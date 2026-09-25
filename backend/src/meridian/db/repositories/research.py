"""Repository for research sessions, tasks, agent runs, critic reviews and feedback."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meridian.core.ids import utcnow
from meridian.db.models import (
    AgentRunModel,
    CriticReviewModel,
    FeedbackModel,
    ResearchSessionModel,
    ResearchTaskModel,
)
from meridian.schemas.analysis import CriticReview
from meridian.schemas.enums import TERMINAL_RUN_STATUSES, RunStatus
from meridian.schemas.findings import AgentOutput
from meridian.schemas.research import CompanyIdentity, HumanFeedback, ResearchRequest, ResearchTask
from meridian.schemas.state import ApprovalState, ResearchState


class ResearchRecord(BaseModel):
    """Read model for a persisted research session."""

    id: str
    user_id: str | None
    query: str
    request: ResearchRequest
    status: RunStatus
    approval: ApprovalState
    ticker: str | None
    company: CompanyIdentity | None
    llm_mode: str
    data_mode: str
    state: ResearchState | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AgentRunRecord(BaseModel):
    """One persisted agent execution: the `AgentOutput` plus its scheduling metadata."""

    output: AgentOutput
    wave: int


def _record_from_row(row: ResearchSessionModel) -> ResearchRecord:
    return ResearchRecord(
        id=row.id,
        user_id=row.user_id,
        query=row.query,
        request=ResearchRequest.model_validate(row.request),
        status=RunStatus(row.status),
        approval=row.approval,
        ticker=row.ticker,
        company=CompanyIdentity.model_validate(row.company) if row.company else None,
        llm_mode=row.llm_mode,
        data_mode=row.data_mode,
        state=ResearchState.model_validate(row.state) if row.state else None,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


class ResearchRepository:
    """Persists research sessions and everything scoped to one run's lifecycle.

    Takes an `AsyncSession` owned by the caller; never commits or opens its own transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, session_id: str, request: ResearchRequest, llm_mode: str, data_mode: str) -> None:
        now = utcnow()
        self._session.add(
            ResearchSessionModel(
                id=session_id,
                user_id=request.user_id,
                query=request.query,
                request=request.model_dump(mode="json"),
                status=RunStatus.QUEUED.value,
                approval="not_required",
                ticker=request.ticker.upper() if request.ticker else None,
                company=None,
                llm_mode=llm_mode,
                data_mode=data_mode,
                state=None,
                error=None,
                created_at=now,
                updated_at=now,
            )
        )
        # Flush (not commit) so the row exists for the rest of this transaction. Everything written
        # during a run -- tool calls, usage, evidence, findings -- carries a foreign key to this session,
        # and the unit of work does not otherwise guarantee the parent insert is ordered first.
        await self._session.flush()

    async def get(self, session_id: str) -> ResearchRecord | None:
        row = await self._session.get(ResearchSessionModel, session_id)
        return _record_from_row(row) if row else None

    async def list_recent(self, limit: int, user_id: str | None = None) -> list[ResearchRecord]:
        stmt = select(ResearchSessionModel).order_by(ResearchSessionModel.created_at.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.where(ResearchSessionModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [_record_from_row(row) for row in result.scalars().all()]

    async def update_status(
        self,
        session_id: str,
        status: RunStatus,
        approval: ApprovalState | None = None,
        error: str | None = None,
    ) -> None:
        row = await self._session.get(ResearchSessionModel, session_id)
        if row is None:
            return
        row.status = status.value
        if approval is not None:
            row.approval = approval
        if error is not None:
            row.error = error
        row.updated_at = utcnow()
        if status in TERMINAL_RUN_STATUSES:
            row.completed_at = utcnow()

    async def save_state(self, session_id: str, state: ResearchState) -> None:
        """Round-trip the full `ResearchState` as JSON, denormalising ticker/company for list queries."""
        row = await self._session.get(ResearchSessionModel, session_id)
        if row is None:
            return
        # A finished run holds thousands of evidence records, so this dump is megabytes of JSON and
        # takes seconds. Done inline it blocks the event loop and stalls every other request, including
        # the progress stream the UI depends on.
        row.state = await asyncio.to_thread(state.model_dump, mode="json")
        row.status = state.status.value
        row.approval = state.approval
        if state.company is not None:
            row.ticker = state.company.ticker
            row.company = state.company.model_dump(mode="json")
        if state.errors:
            row.error = state.errors[-1].message
        row.updated_at = utcnow()

    async def upsert_tasks(self, session_id: str, tasks: list[ResearchTask]) -> None:
        if not tasks:
            return
        values = [
            {
                "session_id": session_id,
                "task_id": t.id,
                "agent": t.agent.value,
                "objective": t.objective,
                "wave": t.wave,
                "depends_on": [a.value for a in t.depends_on],
                "reason": t.reason,
                "instructions": t.instructions,
                "status": t.status.value,
                "attempts": t.attempts,
                "revision": t.revision,
                "fingerprint": t.fingerprint,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
                "error": t.error,
            }
            for t in tasks
        ]
        stmt = pg_insert(ResearchTaskModel).values(values)
        update_cols = {
            c: stmt.excluded[c]
            for c in (
                "agent",
                "objective",
                "wave",
                "depends_on",
                "reason",
                "instructions",
                "status",
                "attempts",
                "revision",
                "fingerprint",
                "started_at",
                "finished_at",
                "error",
            )
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[ResearchTaskModel.session_id, ResearchTaskModel.task_id],
            set_=update_cols,
        )
        await self._session.execute(stmt)

    async def upsert_agent_run(self, session_id: str, output: AgentOutput, wave: int) -> None:
        values: dict[str, Any] = {
            "session_id": session_id,
            "task_id": output.task_id,
            "agent": output.agent.value,
            "wave": wave,
            "status": output.status.value,
            "summary": output.summary,
            "findings": [f.model_dump(mode="json") for f in output.findings],
            "data": output.data,
            "source_ids": output.source_ids,
            "evidence_ids": output.evidence_ids,
            "tools_used": output.tools_used,
            "error": output.error,
            "revision": output.revision,
            "started_at": output.started_at,
            "finished_at": output.finished_at,
        }
        stmt = pg_insert(AgentRunModel).values(**values)
        update_cols = {c: stmt.excluded[c] for c in values if c not in ("session_id", "task_id")}
        stmt = stmt.on_conflict_do_update(
            index_elements=[AgentRunModel.session_id, AgentRunModel.task_id],
            set_=update_cols,
        )
        await self._session.execute(stmt)

    async def list_agent_runs(self, session_id: str) -> list[AgentRunRecord]:
        stmt = (
            select(AgentRunModel)
            .where(AgentRunModel.session_id == session_id)
            .order_by(AgentRunModel.wave, AgentRunModel.agent)
        )
        result = await self._session.execute(stmt)
        records: list[AgentRunRecord] = []
        for row in result.scalars().all():
            output = AgentOutput(
                agent=row.agent,
                task_id=row.task_id,
                status=row.status,
                summary=row.summary,
                findings=row.findings,
                data=row.data,
                source_ids=row.source_ids,
                evidence_ids=row.evidence_ids,
                tools_used=row.tools_used,
                error=row.error,
                revision=row.revision,
                started_at=row.started_at,
                finished_at=row.finished_at,
            )
            records.append(AgentRunRecord(output=output, wave=row.wave))
        return records

    async def save_critic_review(self, session_id: str, review: CriticReview) -> None:
        values = {
            "session_id": session_id,
            "round": review.round,
            "overall_verdict": review.overall_verdict.value,
            "summary": review.summary,
            "reviews": [r.model_dump(mode="json") for r in review.reviews],
            "checks_run": review.checks_run,
        }
        stmt = pg_insert(CriticReviewModel).values(**values)
        update_cols = {c: stmt.excluded[c] for c in ("overall_verdict", "summary", "reviews", "checks_run")}
        stmt = stmt.on_conflict_do_update(
            index_elements=[CriticReviewModel.session_id, CriticReviewModel.round],
            set_=update_cols,
        )
        await self._session.execute(stmt)

    async def add_feedback(self, session_id: str, fb: HumanFeedback) -> None:
        self._session.add(
            FeedbackModel(
                session_id=session_id,
                action=fb.action.value,
                agent=fb.agent.value if fb.agent else None,
                ticker=fb.ticker,
                comment=fb.comment,
                submitted_at=fb.submitted_at or utcnow(),
            )
        )

    async def count_active(self) -> int:
        terminal = {s.value for s in TERMINAL_RUN_STATUSES}
        stmt = (
            select(func.count()).select_from(ResearchSessionModel).where(ResearchSessionModel.status.notin_(terminal))
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())
