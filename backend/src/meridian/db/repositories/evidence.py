"""Repository for sources, evidence and findings gathered during a research run."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meridian.db.models import EvidenceModel, FindingModel, SourceModel
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.findings import Finding


def _source_from_row(row: SourceModel) -> Source:
    return Source(
        id=row.id,
        kind=row.kind,
        title=row.title,
        url=row.url,
        publisher=row.publisher,
        provider=row.provider,
        published_at=row.published_at,
        retrieved_at=row.retrieved_at,
        is_snapshot=row.is_snapshot,
        snapshot_date=row.snapshot_date,
        metadata=row.source_metadata,
    )


def _evidence_from_row(row: EvidenceModel) -> Evidence:
    return Evidence(
        id=row.id,
        source_id=row.source_id,
        locator=EvidenceLocator.model_validate(row.locator),
        text=row.text,
        injection_flags=row.injection_flags,
    )


def _finding_from_row(row: FindingModel) -> Finding:
    return Finding(
        id=row.id,
        agent=row.agent,
        section=row.section,
        claim=row.claim,
        kind=row.kind,
        evidence_ids=row.evidence_ids,
        metric_refs=row.metric_refs,
        confidence=row.confidence,
        category=row.category,
        status=row.status,
        revision=row.revision,
    )


class EvidenceRepository:
    """Persists `Source`/`Evidence`/`Finding` rows, keyed `(session_id, id)`.

    Takes an `AsyncSession` owned by the caller; never commits or opens its own transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_sources(self, session_id: str, sources: list[Source]) -> None:
        if not sources:
            return
        values = [
            {
                "session_id": session_id,
                "id": s.id,
                "kind": s.kind.value,
                "title": s.title,
                "url": s.url,
                "publisher": s.publisher,
                "provider": s.provider,
                "published_at": s.published_at,
                "retrieved_at": s.retrieved_at,
                "is_snapshot": s.is_snapshot,
                "snapshot_date": s.snapshot_date,
                "metadata": s.metadata,
            }
            for s in sources
        ]
        stmt = pg_insert(SourceModel).values(values)
        update_cols = {
            c: stmt.excluded[c]
            for c in (
                "kind",
                "title",
                "url",
                "publisher",
                "provider",
                "published_at",
                "retrieved_at",
                "is_snapshot",
                "snapshot_date",
                "metadata",
            )
        }
        stmt = stmt.on_conflict_do_update(index_elements=[SourceModel.session_id, SourceModel.id], set_=update_cols)
        await self._session.execute(stmt)

    async def save_evidence(self, session_id: str, evidence: list[Evidence]) -> None:
        if not evidence:
            return
        values = [
            {
                "session_id": session_id,
                "id": e.id,
                "source_id": e.source_id,
                "locator": e.locator.model_dump(mode="json"),
                "text": e.text,
                "injection_flags": e.injection_flags,
            }
            for e in evidence
        ]
        stmt = pg_insert(EvidenceModel).values(values)
        update_cols = {c: stmt.excluded[c] for c in ("source_id", "locator", "text", "injection_flags")}
        stmt = stmt.on_conflict_do_update(index_elements=[EvidenceModel.session_id, EvidenceModel.id], set_=update_cols)
        await self._session.execute(stmt)

    async def save_findings(self, session_id: str, findings: list[Finding]) -> None:
        if not findings:
            return
        values = [
            {
                "session_id": session_id,
                "id": f.id,
                "agent": f.agent.value,
                "section": f.section.value,
                "claim": f.claim,
                "kind": f.kind.value,
                "evidence_ids": f.evidence_ids,
                "metric_refs": f.metric_refs,
                "confidence": f.confidence.value,
                "category": f.category,
                "status": f.status.value,
                "revision": f.revision,
            }
            for f in findings
        ]
        stmt = pg_insert(FindingModel).values(values)
        update_cols = {
            c: stmt.excluded[c]
            for c in (
                "agent",
                "section",
                "claim",
                "kind",
                "evidence_ids",
                "metric_refs",
                "confidence",
                "category",
                "status",
                "revision",
            )
        }
        stmt = stmt.on_conflict_do_update(index_elements=[FindingModel.session_id, FindingModel.id], set_=update_cols)
        await self._session.execute(stmt)

    async def list_sources(self, session_id: str) -> list[Source]:
        stmt = select(SourceModel).where(SourceModel.session_id == session_id)
        result = await self._session.execute(stmt)
        return [_source_from_row(row) for row in result.scalars().all()]

    async def list_evidence(self, session_id: str) -> list[Evidence]:
        stmt = select(EvidenceModel).where(EvidenceModel.session_id == session_id)
        result = await self._session.execute(stmt)
        return [_evidence_from_row(row) for row in result.scalars().all()]

    async def list_findings(self, session_id: str) -> list[Finding]:
        stmt = select(FindingModel).where(FindingModel.session_id == session_id)
        result = await self._session.execute(stmt)
        return [_finding_from_row(row) for row in result.scalars().all()]
