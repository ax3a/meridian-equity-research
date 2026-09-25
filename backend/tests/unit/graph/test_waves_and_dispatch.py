"""Core graph mechanics: wave sequencing, cross-wave visibility, failure containment, fingerprint dedup."""

from __future__ import annotations

from typing import Any

from meridian.core.ids import new_id
from meridian.graph.builder import build_graph
from meridian.schemas.enums import AgentName, RunStatus, TaskStatus
from meridian.schemas.events import EventType
from meridian.schemas.research import ResearchRequest
from meridian.schemas.state import ResearchState

from .graph_fakes import (
    FakeCritic,
    FakeSpecialist,
    FakeSupervisor,
    FakeWriter,
    build_agent_set,
    default_result,
    make_task,
)


def initial_state(*, require_approval: bool = False, session_id: str | None = None) -> ResearchState:
    request = ResearchRequest(query="Analyse Test Company", ticker="TST", depth="standard")
    return ResearchState(session_id=session_id or new_id("run"), request=request, require_approval=require_approval)


async def run_graph(agent_set, settings, events, state: ResearchState) -> ResearchState:
    app = build_graph(agent_set, settings, events)
    config = {"configurable": {"thread_id": state.session_id}, "recursion_limit": settings.graph_recursion_limit}
    result = await app.ainvoke(state, config=config)
    return ResearchState.model_validate(result)


async def test_plan_produces_waves_and_wave2_sees_wave1_output(graph_settings, graph_events) -> None:
    seen_wave1_company_marker: list[Any] = []

    def valuation_behavior(task, state):
        company_output = state.outputs.get("company")
        seen_wave1_company_marker.append(company_output.data.get("marker") if company_output else None)
        return default_result(AgentName.VALUATION, task)

    plan_tasks = [
        make_task(AgentName.COMPANY, "company overview", 1),
        make_task(AgentName.VALUATION, "value the company", 2),
    ]
    specialists = {
        AgentName.COMPANY: FakeSpecialist(
            AgentName.COMPANY,
            behavior=lambda task, state: default_result(AgentName.COMPANY, task, data={"marker": "wave1-company"}),
        ),
        AgentName.VALUATION: FakeSpecialist(AgentName.VALUATION, behavior=valuation_behavior),
    }
    agent_set = build_agent_set(specialists, FakeSupervisor(plan_tasks=plan_tasks), FakeCritic(), FakeWriter())

    state = await run_graph(agent_set, graph_settings, graph_events, initial_state())

    assert state.status == RunStatus.COMPLETED
    assert state.report is not None
    assert seen_wave1_company_marker == ["wave1-company"]
    assert specialists[AgentName.COMPANY].calls and specialists[AgentName.VALUATION].calls
    wave_started = [e for e in graph_events.events if e.type == EventType.WAVE_STARTED]
    assert [e.data["wave"] for e in wave_started] == [1, 2]


async def test_failed_specialist_does_not_abort_run(graph_settings, graph_events) -> None:
    def boom(task, state):
        raise RuntimeError("specialist blew up")

    plan_tasks = [
        make_task(AgentName.COMPANY, "company overview", 1),
        make_task(AgentName.NEWS, "recent news", 1),
    ]
    specialists = {
        AgentName.COMPANY: FakeSpecialist(AgentName.COMPANY, behavior=boom),
        AgentName.NEWS: FakeSpecialist(AgentName.NEWS),
    }
    agent_set = build_agent_set(specialists, FakeSupervisor(plan_tasks=plan_tasks), FakeCritic(), FakeWriter())

    state = await run_graph(agent_set, graph_settings, graph_events, initial_state())

    assert state.status == RunStatus.COMPLETED
    assert state.report is not None
    company_output = state.outputs["company"]
    assert company_output.status == TaskStatus.FAILED
    assert "specialist blew up" in (company_output.error or "")
    assert any(err.agent == AgentName.COMPANY for err in state.errors)
    # the other wave-1 agent still completed normally
    assert state.outputs["news"].status == TaskStatus.COMPLETED
    failed_events = [e for e in graph_events.events if e.type == EventType.AGENT_FAILED]
    assert len(failed_events) == 1


async def test_duplicate_fingerprint_never_dispatched_twice(graph_settings, graph_events) -> None:
    original = make_task(AgentName.NEWS, "check the news", 1)
    duplicate = original.model_copy(update={"id": "task_manual_duplicate"})
    assert duplicate.fingerprint == original.fingerprint
    assert duplicate.id != original.id

    plan_tasks = [original, duplicate]
    specialists = {AgentName.NEWS: FakeSpecialist(AgentName.NEWS)}
    agent_set = build_agent_set(specialists, FakeSupervisor(plan_tasks=plan_tasks), FakeCritic(), FakeWriter())

    state = await run_graph(agent_set, graph_settings, graph_events, initial_state())

    assert len(specialists[AgentName.NEWS].calls) == 1
    statuses = {state.tasks[original.id].status, state.tasks[duplicate.id].status}
    assert TaskStatus.SKIPPED in statuses
    assert TaskStatus.COMPLETED in statuses
    assert state.status == RunStatus.COMPLETED


async def test_events_emitted_in_sensible_order(graph_settings, graph_events) -> None:
    plan_tasks = [make_task(AgentName.COMPANY, "company overview", 1)]
    specialists = {AgentName.COMPANY: FakeSpecialist(AgentName.COMPANY)}
    agent_set = build_agent_set(specialists, FakeSupervisor(plan_tasks=plan_tasks), FakeCritic(), FakeWriter())

    await run_graph(agent_set, graph_settings, graph_events, initial_state())

    order = [e.type for e in graph_events.events]

    def index_of(event_type: EventType) -> int:
        return order.index(event_type)

    assert index_of(EventType.RUN_STARTED) < index_of(EventType.COMPANY_RESOLVED)
    assert index_of(EventType.COMPANY_RESOLVED) < index_of(EventType.PLAN_CREATED)
    assert index_of(EventType.PLAN_CREATED) < index_of(EventType.WAVE_STARTED)
    assert index_of(EventType.WAVE_STARTED) < index_of(EventType.AGENT_STARTED)
    assert index_of(EventType.AGENT_STARTED) < index_of(EventType.AGENT_COMPLETED)
    assert index_of(EventType.AGENT_COMPLETED) < index_of(EventType.SUPERVISOR_REVIEW)
    assert index_of(EventType.SUPERVISOR_REVIEW) < index_of(EventType.CRITIC_STARTED)
    assert index_of(EventType.CRITIC_STARTED) < index_of(EventType.CRITIC_VERDICT)
    assert index_of(EventType.CRITIC_VERDICT) < index_of(EventType.REPORT_STARTED)
    assert index_of(EventType.REPORT_STARTED) < index_of(EventType.REPORT_COMPLETED)
    assert index_of(EventType.REPORT_COMPLETED) < index_of(EventType.RUN_COMPLETED)
    # every emitted event carries an increasing seq assigned by the sink
    seqs = [e.seq for e in graph_events.events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
