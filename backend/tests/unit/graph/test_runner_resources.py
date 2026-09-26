"""The runner's bookkeeping: a settled run must not be retained.

Every completed run's `Task` -- and the coroutine frame it references -- stayed in `_tasks` for the life
of the process. Concurrency itself is bounded a layer up by `api.concurrency.RunAdmission`; see
`tests/unit/api/test_concurrency.py`.
"""

from __future__ import annotations

from meridian.graph.runner import ResearchRunner
from meridian.schemas.enums import AgentName, RunStatus
from meridian.schemas.research import ResearchRequest

from .graph_fakes import FakeCritic, FakeSpecialist, FakeSupervisor, FakeWriter, build_agent_set, make_task


def _runner(graph_settings, specialist: FakeSpecialist | None = None) -> ResearchRunner:
    agent = specialist or FakeSpecialist(AgentName.COMPANY)
    agent_set = build_agent_set(
        {AgentName.COMPANY: agent},
        FakeSupervisor(plan_tasks=[make_task(AgentName.COMPANY, "company overview", 1)]),
        FakeCritic(),
        FakeWriter(),
    )
    return ResearchRunner(agent_set, graph_settings)


def _request() -> ResearchRequest:
    return ResearchRequest(query="Analyse Test Company", ticker="TST", depth="standard", require_approval=False)


async def test_a_finished_run_is_not_retained(graph_settings) -> None:
    runner = _runner(graph_settings)

    session_id = await runner.start(_request())
    await runner.wait_idle(session_id)

    state = await runner.status(session_id)
    assert state is not None and state.status is RunStatus.COMPLETED
    assert session_id not in runner._tasks, "a settled run must be dropped, not held for the process's life"


async def test_many_sequential_runs_do_not_accumulate(graph_settings) -> None:
    runner = _runner(graph_settings)

    for _ in range(5):
        await runner.wait_idle(await runner.start(_request()))

    assert runner._tasks == {}
