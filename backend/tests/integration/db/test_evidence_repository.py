"""Integration tests for `EvidenceRepository` against a real Postgres instance."""

from __future__ import annotations

import pytest

from meridian.db.repositories.evidence import EvidenceRepository
from meridian.db.repositories.research import ResearchRepository
from tests.integration.db.helpers import (
    make_evidence,
    make_finding,
    make_request,
    make_source,
    unique_session_id,
)

pytestmark = pytest.mark.integration


async def _new_session(db_session) -> str:
    session_id = unique_session_id()
    await ResearchRepository(db_session).create(session_id, make_request(), llm_mode="offline", data_mode="live")
    return session_id


async def test_save_and_list_sources(db_session) -> None:
    session_id = await _new_session(db_session)
    repo = EvidenceRepository(db_session)
    source = make_source()

    await repo.save_sources(session_id, [source])
    sources = await repo.list_sources(session_id)

    assert [s.id for s in sources] == [source.id]
    assert sources[0].title == source.title
    assert sources[0].publisher == source.publisher


async def test_save_evidence_requires_existing_source_and_round_trips_locator(db_session) -> None:
    session_id = await _new_session(db_session)
    repo = EvidenceRepository(db_session)
    source = make_source()
    evidence = make_evidence(source)

    await repo.save_sources(session_id, [source])
    await repo.save_evidence(session_id, [evidence])

    listed = await repo.list_evidence(session_id)
    assert len(listed) == 1
    assert listed[0].id == evidence.id
    assert listed[0].locator.xbrl_concept == "us-gaap:Revenues"
    assert listed[0].text == evidence.text


async def test_save_findings_is_idempotent_on_upsert(db_session) -> None:
    session_id = await _new_session(db_session)
    evidence_repo = EvidenceRepository(db_session)
    source = make_source()
    evidence = make_evidence(source)
    finding = make_finding(evidence)

    await evidence_repo.save_sources(session_id, [source])
    await evidence_repo.save_evidence(session_id, [evidence])
    await evidence_repo.save_findings(session_id, [finding])
    # Save again (e.g. a revision loop re-persisting the same finding id): must not duplicate.
    await evidence_repo.save_findings(session_id, [finding])

    findings = await evidence_repo.list_findings(session_id)
    assert len(findings) == 1
    assert findings[0].id == finding.id
    assert findings[0].claim == finding.claim


async def test_evidence_cascades_when_source_deleted(db_session) -> None:
    from sqlalchemy import select

    from meridian.db.models import EvidenceModel, SourceModel

    session_id = await _new_session(db_session)
    repo = EvidenceRepository(db_session)
    source = make_source()
    evidence = make_evidence(source)
    await repo.save_sources(session_id, [source])
    await repo.save_evidence(session_id, [evidence])

    row = await db_session.get(SourceModel, {"session_id": session_id, "id": source.id})
    await db_session.delete(row)
    await db_session.flush()

    remaining = (
        (await db_session.execute(select(EvidenceModel).where(EvidenceModel.session_id == session_id))).scalars().all()
    )
    assert remaining == []
