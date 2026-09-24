"""Integration tests for `EventRepository` against a real Postgres instance."""

from __future__ import annotations

import pytest
from tests.integration.db.helpers import make_request, unique_session_id

from meridian.db.repositories.events import EventRepository
from meridian.db.repositories.research import ResearchRepository
from meridian.schemas.events import EventType, ProgressEvent

pytestmark = pytest.mark.integration


async def test_append_assigns_monotonic_seq_per_session(db_session) -> None:
    session_id = unique_session_id()
    await ResearchRepository(db_session).create(session_id, make_request(), llm_mode="offline", data_mode="live")
    repo = EventRepository(db_session)

    seq1 = await repo.append(ProgressEvent(session_id=session_id, type=EventType.RUN_STARTED, message="started"))
    seq2 = await repo.append(ProgressEvent(session_id=session_id, type=EventType.PLAN_CREATED, message="planned"))
    seq3 = await repo.append(ProgressEvent(session_id=session_id, type=EventType.WAVE_STARTED, message="wave 1"))

    assert (seq1, seq2, seq3) == (1, 2, 3)


async def test_seq_is_independent_per_session(db_session) -> None:
    session_a = unique_session_id()
    session_b = unique_session_id()
    repo_sessions = ResearchRepository(db_session)
    await repo_sessions.create(session_a, make_request(), llm_mode="offline", data_mode="live")
    await repo_sessions.create(session_b, make_request(), llm_mode="offline", data_mode="live")
    repo = EventRepository(db_session)

    seq_a1 = await repo.append(ProgressEvent(session_id=session_a, type=EventType.RUN_STARTED, message="a1"))
    seq_b1 = await repo.append(ProgressEvent(session_id=session_b, type=EventType.RUN_STARTED, message="b1"))
    seq_a2 = await repo.append(ProgressEvent(session_id=session_a, type=EventType.PLAN_CREATED, message="a2"))

    assert seq_a1 == 1
    assert seq_b1 == 1
    assert seq_a2 == 2


async def test_list_since_returns_only_newer_events_in_order(db_session) -> None:
    session_id = unique_session_id()
    await ResearchRepository(db_session).create(session_id, make_request(), llm_mode="offline", data_mode="live")
    repo = EventRepository(db_session)
    for i, event_type in enumerate(
        [EventType.RUN_STARTED, EventType.PLAN_CREATED, EventType.WAVE_STARTED, EventType.RUN_COMPLETED]
    ):
        await repo.append(ProgressEvent(session_id=session_id, type=event_type, message=f"m{i}"))

    since_2 = await repo.list_since(session_id, after_seq=2)
    assert [e.seq for e in since_2] == [3, 4]
    assert [e.type for e in since_2] == [EventType.WAVE_STARTED, EventType.RUN_COMPLETED]

    since_all = await repo.list_since(session_id, after_seq=0)
    assert len(since_all) == 4
