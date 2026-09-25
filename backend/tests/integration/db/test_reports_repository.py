"""Integration tests for `ReportRepository` against a real Postgres instance."""

from __future__ import annotations

import pytest

from meridian.db.repositories.reports import ReportRepository
from meridian.db.repositories.research import ResearchRepository
from tests.integration.db.helpers import make_company, make_report, make_request, unique_session_id

pytestmark = pytest.mark.integration


async def test_add_version_assigns_sequential_versions_and_latest_wins(db_session) -> None:
    session_id = unique_session_id()
    await ResearchRepository(db_session).create(session_id, make_request(), llm_mode="offline", data_mode="live")
    repo = ReportRepository(db_session)
    company = make_company()

    v1 = await repo.add_version(session_id, make_report(session_id, company))
    v2 = await repo.add_version(session_id, make_report(session_id, company))

    assert v1 == 1
    assert v2 == 2

    latest = await repo.latest(session_id)
    assert latest is not None
    assert latest.version == 2

    versions = await repo.list_versions(session_id)
    assert [r.version for r in versions] == [1, 2]


async def test_latest_returns_none_when_no_reports_exist(db_session) -> None:
    session_id = unique_session_id()
    await ResearchRepository(db_session).create(session_id, make_request(), llm_mode="offline", data_mode="live")
    repo = ReportRepository(db_session)
    assert await repo.latest(session_id) is None
    assert await repo.list_versions(session_id) == []
