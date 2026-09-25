"""ResearchRunner: the approval interrupt pauses a run and `resume` carries it to a finished report;
feedback that requests extra work produces new tasks that actually run before the report is written.
"""

from __future__ import annotations

from meridian.graph.runner import ResearchRunner
from meridian.schemas.enums import AgentName, FeedbackAction, RunStatus
from meridian.schemas.events import EventType
from meridian.schemas.research import HumanFeedback, ResearchRequest

from .graph_fakes import FakeCritic, FakeSpecialist, FakeSupervisor, FakeWriter, build_agent_set, make_task


def request(*, require_approval: bool) -> ResearchRequest:
    return ResearchRequest(
        query="Analyse Test Company", ticker="TST", depth="standard", require_approval=require_approval
    )


async def test_approval_interrupt_pauses_and_resume_completes_report(graph_settings, graph_events) -> None:
    plan_tasks = [make_task(AgentName.COMPANY, "company overview", 1)]
    agent_set = build_agent_set(
        {AgentName.COMPANY: FakeSpecialist(AgentName.COMPANY)},
        FakeSupervisor(plan_tasks=plan_tasks),
        FakeCritic(),
        FakeWriter(),
    )
    runner = ResearchRunner(agent_set, graph_settings)

    session_id = await runner.start(request(require_approval=True))
    await runner.wait_idle(session_id)

    paused = await runner.status(session_id)
    assert paused is not None
    assert paused.status == RunStatus.AWAITING_APPROVAL
    assert paused.report is None

    runner.resume(session_id, [HumanFeedback(action=FeedbackAction.APPROVE)])
    await runner.wait_idle(session_id)

    done = await runner.status(session_id)
    assert done is not None
    assert done.status == RunStatus.COMPLETED
    assert done.report is not None

    history = await runner.store.list_events_since(session_id, 0)
    types = [e.type for e in history]
    assert EventType.AWAITING_APPROVAL in types
    assert types.index(EventType.AWAITING_APPROVAL) < types.index(EventType.FEEDBACK_RECEIVED)
    assert types.index(EventType.FEEDBACK_RECEIVED) < types.index(EventType.REPORT_COMPLETED)
    assert types[-1] == EventType.RUN_COMPLETED


async def test_feedback_add_competitor_produces_new_tasks_that_run(graph_settings, graph_events) -> None:
    plan_tasks = [make_task(AgentName.COMPANY, "company overview", 1)]

    def feedback_tasks(state, feedback):
        return [
            make_task(AgentName.COMPETITORS, f"add competitor {fb.ticker}", 1)
            for fb in feedback
            if fb.action == FeedbackAction.ADD_COMPETITOR
        ]

    supervisor = FakeSupervisor(plan_tasks=plan_tasks, feedback_tasks_factory=feedback_tasks)
    competitors = FakeSpecialist(AgentName.COMPETITORS)
    agent_set = build_agent_set(
        {AgentName.COMPANY: FakeSpecialist(AgentName.COMPANY), AgentName.COMPETITORS: competitors},
        supervisor,
        FakeCritic(),
        FakeWriter(),
    )
    runner = ResearchRunner(agent_set, graph_settings)

    session_id = await runner.start(request(require_approval=True))
    await runner.wait_idle(session_id)
    assert (await runner.status(session_id)).status == RunStatus.AWAITING_APPROVAL

    feedback = [HumanFeedback(action=FeedbackAction.ADD_COMPETITOR, ticker="AMD", comment="add competitor AMD")]
    runner.resume(session_id, feedback)
    await runner.wait_idle(session_id)

    state = await runner.status(session_id)
    assert state is not None
    assert state.status == RunStatus.COMPLETED
    assert state.report is not None
    assert len(competitors.calls) == 1
    assert "AMD" in competitors.calls[0].objective
    assert state.approval == "changes_requested"
    assert len(state.human_feedback) == 1
    assert state.human_feedback[0].action == FeedbackAction.ADD_COMPETITOR
