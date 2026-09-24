"""Repository for versioned report snapshots."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from meridian.db.models import ReportVersionModel
from meridian.schemas.report import ResearchReport


class ReportRepository:
    """Persists immutable `ResearchReport` versions per session.

    Takes an `AsyncSession` owned by the caller; never commits or opens its own transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_version(self, session_id: str, report: ResearchReport) -> int:
        """Assign the next version number for the session and persist the report. Returns that version."""
        stmt = select(func.coalesce(func.max(ReportVersionModel.version), 0)).where(
            ReportVersionModel.session_id == session_id
        )
        result = await self._session.execute(stmt)
        next_version = int(result.scalar_one()) + 1
        versioned = report.model_copy(update={"version": next_version})
        self._session.add(
            ReportVersionModel(
                session_id=session_id,
                version=next_version,
                report=versioned.model_dump(mode="json"),
            )
        )
        return next_version

    async def latest(self, session_id: str) -> ResearchReport | None:
        stmt = (
            select(ReportVersionModel)
            .where(ReportVersionModel.session_id == session_id)
            .order_by(ReportVersionModel.version.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        return ResearchReport.model_validate(row.report) if row else None

    async def list_versions(self, session_id: str) -> list[ResearchReport]:
        stmt = (
            select(ReportVersionModel)
            .where(ReportVersionModel.session_id == session_id)
            .order_by(ReportVersionModel.version.asc())
        )
        result = await self._session.execute(stmt)
        return [ResearchReport.model_validate(row.report) for row in result.scalars().all()]
