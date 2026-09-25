"""`updates_from_result` maps an AgentResult into the ResearchState update dict."""

from __future__ import annotations

from meridian.agents.base import AgentResult
from meridian.agents.validation import ValidationReport
from meridian.core.ids import utcnow
from meridian.graph.state_ops import updates_from_result
from meridian.schemas.citations import Source
from meridian.schemas.enums import AgentName, SourceKind, TaskStatus
from meridian.schemas.findings import AgentOutput
from meridian.schemas.research import ResearchTask


def make_task(agent: AgentName = AgentName.COMPANY, wave: int = 1) -> ResearchTask:
    return ResearchTask.make(agent, "look at the company", wave)


def test_success_maps_outputs_tasks_sources_and_fingerprint() -> None:
    task = make_task()
    now = utcnow()
    source = Source.make(kind=SourceKind.COMPANY_PROFILE, title="10-K", provider="sec_edgar", publisher="SEC")
    output = AgentOutput(
        agent=task.agent,
        task_id=task.id,
        status=TaskStatus.COMPLETED,
        summary="done",
        source_ids=[source.id],
        started_at=now,
        finished_at=now,
    )
    result = AgentResult(
        output=output,
        sources={source.id: source},
        evidence={},
        tool_calls=[],
        usage=[],
        state_updates={},
        validation=ValidationReport(),
    )

    update = updates_from_result(result, task)

    assert update["outputs"] == {"company": output}
    assert update["output_history"] == [output]
    assert update["sources"] == {source.id: source}
    assert update["evidence"] == {}
    assert update["completed_fingerprints"] == [task.fingerprint]
    updated_task = update["tasks"][task.id]
    assert updated_task.status == TaskStatus.COMPLETED
    assert updated_task.attempts == task.attempts + 1
    assert "errors" not in update
    assert f"company:{task.id}" in update["timings"]


def test_failure_records_a_run_error() -> None:
    task = make_task(AgentName.NEWS)
    now = utcnow()
    output = AgentOutput(
        agent=task.agent,
        task_id=task.id,
        status=TaskStatus.FAILED,
        summary="",
        error="boom",
        started_at=now,
        finished_at=now,
    )
    result = AgentResult(
        output=output,
        sources={},
        evidence={},
        tool_calls=[],
        usage=[],
        state_updates={},
        validation=ValidationReport(),
    )

    update = updates_from_result(result, task)

    assert update["tasks"][task.id].status == TaskStatus.FAILED
    assert update["tasks"][task.id].error == "boom"
    assert len(update["errors"]) == 1
    assert update["errors"][0].agent == AgentName.NEWS
    assert update["errors"][0].message == "boom"
    # a failed task's fingerprint is still marked completed so it is never retried automatically
    assert update["completed_fingerprints"] == [task.fingerprint]


def test_state_updates_are_merged_as_top_level_keys() -> None:
    task = make_task(AgentName.FINANCIALS)
    now = utcnow()
    output = AgentOutput(
        agent=task.agent, task_id=task.id, status=TaskStatus.COMPLETED, started_at=now, finished_at=now
    )
    marker = object()
    result = AgentResult(
        output=output,
        sources={},
        evidence={},
        tool_calls=[],
        usage=[],
        state_updates={"metrics": marker},
        validation=ValidationReport(),
    )

    update = updates_from_result(result, task)

    assert update["metrics"] is marker
