"""Integration tests for `ResearchRepository` against a real Postgres instance."""

from __future__ import annotations

import pytest
from tests.integration.db.helpers import (
    make_agent_output,
    make_company,
    make_critic_review,
    make_evidence,
    make_finding,
    make_request,
    make_source,
    make_task,
    unique_session_id,
)

from meridian.db.repositories.research import ResearchRepository
from meridian.schemas.enums import RunStatus
from meridian.schemas.state import ResearchState

pytestmark = pytest.mark.integration


async def test_create_get_and_list_recent(db_session) -> None:
    repo = ResearchRepository(db_session)
    session_id = unique_session_id()
    request = make_request("MSFT")

    await repo.create(session_id, request, llm_mode="offline", data_mode="live")

    record = await repo.get(session_id)
    assert record is not None
    assert record.id == session_id
    assert record.query == request.query
    assert record.status == RunStatus.QUEUED
    assert record.request.ticker == "MSFT"

    recent = await repo.list_recent(limit=10)
    assert any(r.id == session_id for r in recent)


async def test_get_missing_session_returns_none(db_session) -> None:
    repo = ResearchRepository(db_session)
    assert await repo.get("sess_does_not_exist") is None


async def test_update_status_sets_completed_at_on_terminal_status(db_session) -> None:
    repo = ResearchRepository(db_session)
    session_id = unique_session_id()
    await repo.create(session_id, make_request(), llm_mode="offline", data_mode="live")

    await repo.update_status(session_id, RunStatus.RESEARCHING)
    mid = await repo.get(session_id)
    assert mid is not None
    assert mid.status == RunStatus.RESEARCHING
    assert mid.completed_at is None

    await repo.update_status(session_id, RunStatus.COMPLETED)
    done = await repo.get(session_id)
    assert done is not None
    assert done.status == RunStatus.COMPLETED
    assert done.completed_at is not None


async def test_save_state_round_trips_full_research_state(db_session) -> None:
    repo = ResearchRepository(db_session)
    session_id = unique_session_id()
    request = make_request("MSFT")
    await repo.create(session_id, request, llm_mode="offline", data_mode="live")

    company = make_company("MSFT")
    source = make_source()
    evidence = make_evidence(source)
    finding = make_finding(evidence)
    task = make_task()
    output = make_agent_output(task, finding)
    review = make_critic_review()

    state = ResearchState(
        session_id=session_id,
        request=request,
        status=RunStatus.REVIEWING,
        company=company,
        sources={source.id: source},
        evidence={evidence.id: evidence},
        outputs={output.agent.value: output},
        critic_reviews=[review],
    )

    await repo.save_state(session_id, state)

    record = await repo.get(session_id)
    assert record is not None
    assert record.ticker == "MSFT"
    assert record.company is not None
    assert record.company.name == company.name
    assert record.state is not None

    round_tripped = record.state
    assert round_tripped.session_id == session_id
    assert round_tripped.status == RunStatus.REVIEWING
    assert set(round_tripped.sources) == {source.id}
    assert set(round_tripped.evidence) == {evidence.id}
    assert round_tripped.evidence[evidence.id].text == evidence.text
    assert round_tripped.outputs[output.agent.value].findings[0].claim == finding.claim
    assert round_tripped.critic_reviews[0].summary == review.summary


async def test_upsert_tasks_and_agent_runs_round_trip(db_session) -> None:
    repo = ResearchRepository(db_session)
    session_id = unique_session_id()
    await repo.create(session_id, make_request(), llm_mode="offline", data_mode="live")

    task = make_task()
    await repo.upsert_tasks(session_id, [task])
    # Re-upserting the same task id must update in place, not duplicate.
    await repo.upsert_tasks(session_id, [task])

    source = make_source()
    evidence = make_evidence(source)
    finding = make_finding(evidence)
    output = make_agent_output(task, finding)
    await repo.upsert_agent_run(session_id, output, wave=task.wave)
    await repo.upsert_agent_run(session_id, output, wave=task.wave)

    runs = await repo.list_agent_runs(session_id)
    assert len(runs) == 1
    assert runs[0].output.task_id == task.id
    assert runs[0].wave == task.wave
    assert runs[0].output.findings[0].claim == finding.claim


async def test_save_critic_review_upserts_by_round(db_session) -> None:
    from sqlalchemy import select

    from meridian.db.models import CriticReviewModel

    repo = ResearchRepository(db_session)
    session_id = unique_session_id()
    await repo.create(session_id, make_request(), llm_mode="offline", data_mode="live")

    review = make_critic_review(round_=1)
    await repo.save_critic_review(session_id, review)
    updated = make_critic_review(round_=1)
    updated.summary = "Revised summary."
    await repo.save_critic_review(session_id, updated)

    rows = (
        (await db_session.execute(select(CriticReviewModel).where(CriticReviewModel.session_id == session_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "upserting the same round must update in place, not duplicate"
    assert rows[0].summary == "Revised summary."


async def test_add_feedback_does_not_raise(db_session) -> None:
    from meridian.schemas.enums import FeedbackAction
    from meridian.schemas.research import HumanFeedback

    repo = ResearchRepository(db_session)
    session_id = unique_session_id()
    await repo.create(session_id, make_request(), llm_mode="offline", data_mode="live")

    await repo.add_feedback(session_id, HumanFeedback(action=FeedbackAction.APPROVE))


async def test_count_active_excludes_terminal_statuses(db_session) -> None:
    repo = ResearchRepository(db_session)
    running_id = unique_session_id()
    done_id = unique_session_id()
    await repo.create(running_id, make_request(), llm_mode="offline", data_mode="live")
    await repo.create(done_id, make_request(), llm_mode="offline", data_mode="live")
    await repo.update_status(running_id, RunStatus.RESEARCHING)
    await repo.update_status(done_id, RunStatus.COMPLETED)

    active = await repo.count_active()
    # At least our one still-running session must be counted; the completed one must not add to it
    # beyond what was already active before this test (hence >=1, and re-checking after completing
    # the running one too keeps this robust to other rows in a shared session-scoped schema).
    assert active >= 1
    await repo.update_status(running_id, RunStatus.COMPLETED)
    active_after = await repo.count_active()
    assert active_after == active - 1
