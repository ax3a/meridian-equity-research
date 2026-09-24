"""Repositories implementing the frozen `ResearchMemoryStore` and `PreferenceStore` protocols."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meridian.core.ids import utcnow
from meridian.db.models import ResearchMemoryModel, UserModel, UserPreferenceModel
from meridian.memory.types import MemoryItem
from meridian.schemas.api import UserPreferences


class MemoryRepository:
    """Implements `ResearchMemoryStore`: append-only history of cached research knowledge.

    `put` always inserts a new row so `history` can show prior values; `get` returns only the
    latest non-expired item for a given `(ticker, kind)`. Takes an `AsyncSession` owned by the
    caller; never commits or opens its own transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, ticker: str, kind: str) -> MemoryItem | None:
        now = utcnow()
        stmt = (
            select(ResearchMemoryModel)
            .where(
                ResearchMemoryModel.ticker == ticker,
                ResearchMemoryModel.kind == kind,
                ResearchMemoryModel.expires_at > now,
            )
            .order_by(ResearchMemoryModel.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        if row is None:
            return None
        return MemoryItem(
            ticker=row.ticker,
            kind=row.kind,
            payload=row.payload,
            source_ids=row.source_ids,
            created_at=row.created_at,
            expires_at=row.expires_at,
            session_id=row.session_id,
        )

    async def put(self, item: MemoryItem) -> None:
        self._session.add(
            ResearchMemoryModel(
                ticker=item.ticker,
                kind=item.kind,
                payload=item.payload,
                source_ids=item.source_ids,
                session_id=item.session_id,
                created_at=item.created_at,
                expires_at=item.expires_at,
            )
        )

    async def history(self, ticker: str, limit: int = 5) -> list[MemoryItem]:
        stmt = (
            select(ResearchMemoryModel)
            .where(ResearchMemoryModel.ticker == ticker)
            .order_by(ResearchMemoryModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            MemoryItem(
                ticker=row.ticker,
                kind=row.kind,
                payload=row.payload,
                source_ids=row.source_ids,
                created_at=row.created_at,
                expires_at=row.expires_at,
                session_id=row.session_id,
            )
            for row in result.scalars().all()
        ]


class PreferenceRepository:
    """Implements `PreferenceStore`; returns `UserPreferences()` defaults when nothing is saved.

    Takes an `AsyncSession` owned by the caller; never commits or opens its own transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: str) -> UserPreferences:
        row = await self._session.get(UserPreferenceModel, user_id)
        if row is None:
            return UserPreferences()
        return UserPreferences.model_validate(row.payload)

    async def put(self, user_id: str, prefs: UserPreferences) -> None:
        await self._session.execute(
            pg_insert(UserModel).values(id=user_id).on_conflict_do_nothing(index_elements=[UserModel.id])
        )
        stmt = pg_insert(UserPreferenceModel).values(user_id=user_id, payload=prefs.model_dump(mode="json"))
        stmt = stmt.on_conflict_do_update(
            index_elements=[UserPreferenceModel.user_id],
            set_={"payload": stmt.excluded.payload, "updated_at": utcnow()},
        )
        await self._session.execute(stmt)
