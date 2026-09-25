"""Fakes satisfying the frozen `agents/contracts.py` protocols, used across the graph test suite.

None of these subclass `BaseAgent` (Task 9 is being implemented in parallel) - they implement the
`Specialist` / `Supervisor` / `Critic` / `ReportWriter` protocols directly, exactly as a caller of the
graph is expected to.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from meridian.agents.base import AgentResult
from meridian.agents.contracts import AgentSet, CriticResult, PlanResult, ResolveResult, ReviewDecision, WriterResult
from meridian.agents.validation import ValidationReport
from meridian.core.ids import stable_id, utcnow
from meridian.schemas.analysis import CriticReview, SectionReview
from meridian.schemas.enums import AgentName, TaskStatus, Verdict
from meridian.schemas.findings import AgentOutput
from meridian.schemas.report import ResearchReport
from meridian.schemas.research import CompanyIdentity, HumanFeedback, ResearchPlan, ResearchTask
from meridian.schemas.state import ResearchState

TEST_COMPANY = CompanyIdentity(name="Test Company", ticker="TST", cik="0000000001")


def make_task(agent: AgentName, objective: str, wave: int, *, revision: int = 0, **kw: Any) -> ResearchTask:
    return ResearchTask.make(agent, objective, wave, revision=revision, **kw)


def default_output(agent: AgentName, task: ResearchTask, *, data: dict[str, Any] | None = None) -> AgentOutput:
    now = utcnow()
    return AgentOutput(
        agent=agent,
        task_id=task.id,
        status=TaskStatus.COMPLETED,
        summary=f"{agent.value} done",
        data=data or {},
        started_at=now,
        finished_at=now,
    )


def default_result(agent: AgentName, task: ResearchTask, *, data: dict[str, Any] | None = None) -> AgentResult:
    return AgentResult(
        output=default_output(agent, task, data=data),
        sources={},
        evidence={},
        tool_calls=[],
        usage=[],
        state_updates={},
        validation=ValidationReport(),
    )


@dataclass
class FakeSpecialist:
    """A specialist whose behaviour is fully controlled by the test.

    `behavior`, if set, is called as `behavior(task, state)`; it may return an `AgentResult`, raise, or be
    a coroutine function. If unset, `execute` returns a bland completed `AgentResult`.
    """

    name: AgentName
    behavior: Callable[[ResearchTask, ResearchState], Any] | None = None
    calls: list[ResearchTask] = field(default_factory=list)

    async def execute(self, task: ResearchTask, state: ResearchState) -> AgentResult:
        self.calls.append(task)
        if self.behavior is None:
            return default_result(self.name, task)
        result = self.behavior(task, state)
        if inspect.isawaitable(result):
            result = await result
        return result


@dataclass
class FakeSupervisor:
    plan_tasks: list[ResearchTask]
    review_follow_up: list[ResearchTask] = field(default_factory=list)
    review_calls: int = 0
    feedback_tasks_factory: Callable[[ResearchState, list[HumanFeedback]], list[ResearchTask]] | None = None
    rework_tasks_factory: Callable[[ResearchState, list[AgentName], dict[str, str]], list[ResearchTask]] | None = None

    async def resolve(self, state: ResearchState) -> ResolveResult:
        return ResolveResult(company=TEST_COMPANY)

    async def plan(self, state: ResearchState) -> PlanResult:
        return PlanResult(
            plan=ResearchPlan(
                objectives=["test objective"], tasks=list(self.plan_tasks), rationale="fake deterministic plan"
            )
        )

    async def review(self, state: ResearchState) -> ReviewDecision:
        self.review_calls += 1
        follow_up = list(self.review_follow_up) if self.review_calls == 1 else []
        return ReviewDecision(follow_up=follow_up, summary=f"supervisor review #{self.review_calls}")

    def tasks_for_feedback(self, state: ResearchState, feedback: list[HumanFeedback]) -> list[ResearchTask]:
        if self.feedback_tasks_factory is not None:
            return self.feedback_tasks_factory(state, feedback)
        return []

    def tasks_for_rework(
        self, state: ResearchState, agents: list[AgentName], notes: dict[str, str]
    ) -> list[ResearchTask]:
        if self.rework_tasks_factory is not None:
            return self.rework_tasks_factory(state, agents, notes)
        return [make_task(a, f"revise {a.value}", 1, revision=state.revision_round + 1) for a in agents]


@dataclass
class FakeCritic:
    """Verdicts are consumed one per call; the last one repeats once the sequence is exhausted."""

    verdict_sequence: list[Verdict] = field(default_factory=lambda: [Verdict.APPROVED])
    agents_needing_revision: list[AgentName] = field(default_factory=list)
    calls: int = 0

    async def review(self, state: ResearchState) -> CriticResult:
        idx = min(self.calls, len(self.verdict_sequence) - 1)
        verdict = self.verdict_sequence[idx]
        self.calls += 1
        reviews = (
            [SectionReview(agent=a, verdict=Verdict.NEEDS_REVISION) for a in self.agents_needing_revision]
            if verdict == Verdict.NEEDS_REVISION
            else []
        )
        review = CriticReview(
            round=self.calls, overall_verdict=verdict, summary=f"critic round {self.calls}", reviews=reviews
        )
        return CriticResult(review=review)


@dataclass
class FakeWriter:
    calls: int = 0

    async def write(self, state: ResearchState) -> WriterResult:
        self.calls += 1
        report = ResearchReport(
            id=stable_id("rep", state.session_id, self.calls),
            session_id=state.session_id,
            company=state.company or TEST_COMPANY,
            title="Test Report",
            generated_at=utcnow(),
            llm_mode="offline",
            data_mode="live",
            sections=[],
        )
        return WriterResult(report=report)


def build_agent_set(
    specialists: dict[AgentName, FakeSpecialist], supervisor: FakeSupervisor, critic: FakeCritic, writer: FakeWriter
) -> AgentSet:
    return AgentSet(supervisor=supervisor, critic=critic, writer=writer, specialists=dict(specialists))
