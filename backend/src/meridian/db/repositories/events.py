"""Repository for the append-only progress event log (SSE backing store)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from meridian.db.models import ResearchEventModel
from meridian.schemas.events import EventType, ProgressEvent


def _event_from_row(row: ResearchEventModel) -> ProgressEvent:
    return ProgressEvent(
        seq=row.seq,
        session_id=row.session_id,
        type=EventType(row.type),
        agent=row.agent,
        message=row.message,
        data=row.data,
        at=row.at,
    )


class EventRepository:
    """Persists `ProgressEvent`s and assigns a monotonic `seq` per session.

    Takes an `AsyncSession` owned by the caller; never commits or opens its own transaction. `seq`
    assignment reads the current max within the caller's transaction and flushes immediately so
    back-to-back appends for the same session (the normal single-writer-per-run pattern) see a
    consistent sequence.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: ProgressEvent) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(ResearchEventModel.seq), 0)).where(
                ResearchEventModel.session_id == event.session_id
            )
        )
        next_seq = int(result.scalar_one()) + 1
        row = ResearchEventModel(
            session_id=event.session_id,
            seq=next_seq,
            type=event.type.value,
            agent=event.agent.value if event.agent else None,
            message=event.message,
            data=event.data,
            at=event.at,
        )
        self._session.add(row)
        await self._session.flush()
        return next_seq

    async def list_since(self, session_id: str, after_seq: int) -> list[ProgressEvent]:
        stmt = (
            select(ResearchEventModel)
            .where(ResearchEventModel.session_id == session_id, ResearchEventModel.seq > after_seq)
            .order_by(ResearchEventModel.seq.asc())
        )
        result = await self._session.execute(stmt)
        return [_event_from_row(row) for row in result.scalars().all()]
