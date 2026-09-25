"""Critic loop: NEEDS_REVISION sends work back to `revise`, bounded by `settings.max_revision_rounds`."""

from __future__ import annotations

from meridian.graph.builder import build_graph
from meridian.schemas.enums import AgentName, RunStatus, Verdict
from meridian.schemas.events import EventType
from meridian.schemas.state import ResearchState

from .graph_fakes import FakeCritic, FakeSpecialist, FakeSupervisor, FakeWriter, build_agent_set, make_task
from .test_waves_and_dispatch import initial_state


async def test_critic_loop_revises_then_terminates_at_cap(graph_settings, graph_events) -> None:
    assert graph_settings.max_revision_rounds == 2

    plan_tasks = [make_task(AgentName.COMPANY, "company overview", 1)]
    company = FakeSpecialist(AgentName.COMPANY)
    critic = FakeCritic(
        verdict_sequence=[Verdict.NEEDS_REVISION, Verdict.NEEDS_REVISION, Verdict.NEEDS_REVISION],
        agents_needing_revision=[AgentName.COMPANY],
    )
    agent_set = build_agent_set(
        {AgentName.COMPANY: company}, FakeSupervisor(plan_tasks=plan_tasks), critic, FakeWriter()
    )

    app = build_graph(agent_set, graph_settings, graph_events)
    state_in = initial_state()
    config = {
        "configurable": {"thread_id": state_in.session_id},
        "recursion_limit": graph_settings.graph_recursion_limit,
    }
    result = await app.ainvoke(state_in, config=config)
    state = ResearchState.model_validate(result)

    # critic ran 3 times (initial + 2 revisions) but only revised twice, hitting max_revision_rounds
    assert critic.calls == 3
    assert state.revision_round == 2
    assert len(state.critic_reviews) == 3
    assert state.rework_agents == []
    # company specialist executed once per initial dispatch plus once per revision round
    assert len(company.calls) == 3
    assert state.status == RunStatus.COMPLETED
    assert state.report is not None

    revisions_started = [e for e in graph_events.events if e.type == EventType.REVISION_STARTED]
    assert len(revisions_started) == 2
    verdicts = [e for e in graph_events.events if e.type == EventType.CRITIC_VERDICT]
    assert len(verdicts) == 3
