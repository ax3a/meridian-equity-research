"""Fakes satisfying the frozen `agents/contracts.py` protocols, for driving the API through a real
`ResearchRunner`/graph without any network call or LLM.

Deliberately self-contained (rather than importing `tests/unit/graph/graph_fakes.py`) since Task 12 may
only add files under `tests/integration/api/**`.
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
from meridian.schemas.analysis import CriticReview
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection, SourceKind, TaskStatus, Verdict
from meridian.schemas.findings import AgentOutput, Finding
from meridian.schemas.report import ReportParagraph, ReportSectionContent, ResearchReport
from meridian.schemas.research import CompanyIdentity, HumanFeedback, ResearchPlan, ResearchTask
from meridian.schemas.state import ResearchState

TEST_COMPANY = CompanyIdentity(name="Test Company", ticker="TST", cik="0000000001")

TEST_SOURCE = Source.make(
    kind=SourceKind.XBRL_FACTS, title="Test 10-K", provider="test", publisher="SEC EDGAR", url="https://example.com/10k"
)
TEST_EVIDENCE = Evidence(
    id=stable_id("ev", "test"),
    source_id=TEST_SOURCE.id,
    locator=EvidenceLocator(section="Item 7"),
    text="Revenue grew 15% year over year.",
)


def make_task(agent: AgentName, objective: str, wave: int = 1, *, revision: int = 0, **kw: Any) -> ResearchTask:
    return ResearchTask.make(agent, objective, wave, revision=revision, **kw)


def make_finding(
    agent: AgentName, claim: str, *, section: ReportSection = ReportSection.FINANCIAL_PERFORMANCE
) -> Finding:
    return Finding(
        agent=agent,
        section=section,
        claim=claim,
        kind=FindingKind.FACT,
        evidence_ids=[TEST_EVIDENCE.id],
        confidence=Confidence.HIGH,
    )


def default_output(agent: AgentName, task: ResearchTask, *, findings: list[Finding] | None = None) -> AgentOutput:
    now = utcnow()
    return AgentOutput(
        agent=agent,
        task_id=task.id,
        status=TaskStatus.COMPLETED,
        summary=f"{agent.value} finished: {task.objective}",
        findings=findings or [],
        source_ids=[TEST_SOURCE.id],
        evidence_ids=[TEST_EVIDENCE.id],
        started_at=now,
        finished_at=now,
    )


def default_result(agent: AgentName, task: ResearchTask, *, findings: list[Finding] | None = None) -> AgentResult:
    resolved_findings = findings if findings is not None else [make_finding(agent, f"{agent.value} claim")]
    return AgentResult(
        output=default_output(agent, task, findings=resolved_findings),
        sources={TEST_SOURCE.id: TEST_SOURCE},
        evidence={TEST_EVIDENCE.id: TEST_EVIDENCE},
        tool_calls=[],
        usage=[],
        state_updates={},
        validation=ValidationReport(),
    )


@dataclass
class FakeSpecialist:
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

    async def resolve(self, state: ResearchState) -> ResolveResult:
        return ResolveResult(company=TEST_COMPANY, sources={TEST_SOURCE.id: TEST_SOURCE})

    async def plan(self, state: ResearchState) -> PlanResult:
        return PlanResult(
            plan=ResearchPlan(objectives=["test objective"], tasks=list(self.plan_tasks), rationale="fake plan")
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
        return [make_task(a, f"revise {a.value}", 1, revision=state.revision_round + 1) for a in agents]


@dataclass
class FakeCritic:
    verdict_sequence: list[Verdict] = field(default_factory=lambda: [Verdict.APPROVED])
    calls: int = 0

    async def review(self, state: ResearchState) -> CriticResult:
        idx = min(self.calls, len(self.verdict_sequence) - 1)
        verdict = self.verdict_sequence[idx]
        self.calls += 1
        review = CriticReview(round=self.calls, overall_verdict=verdict, summary=f"critic round {self.calls}")
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
            title=f"{(state.company or TEST_COMPANY).name} Research Report",
            generated_at=utcnow(),
            llm_mode="offline",
            data_mode="live",
            sections=[
                ReportSectionContent(
                    section=ReportSection.EXECUTIVE_SUMMARY,
                    title="Executive Summary",
                    paragraphs=[
                        ReportParagraph(
                            text="Test company looks fine.", kind=FindingKind.FACT, evidence_ids=[TEST_EVIDENCE.id]
                        )
                    ],
                )
            ],
        )
        return WriterResult(report=report)


def build_fake_agent_set(
    *,
    specialist_agents: list[AgentName] | None = None,
    specialist_behavior: dict[AgentName, Callable[[ResearchTask, ResearchState], Any]] | None = None,
    critic_verdicts: list[Verdict] | None = None,
    review_follow_up: list[ResearchTask] | None = None,
) -> tuple[AgentSet, dict[str, Any]]:
    """Returns `(agent_set, handles)`; `handles` exposes the fakes for assertions in tests."""
    agents = specialist_agents or [AgentName.FINANCIALS]
    behavior = specialist_behavior or {}
    specialists = {a: FakeSpecialist(name=a, behavior=behavior.get(a)) for a in agents}
    supervisor = FakeSupervisor(
        plan_tasks=[make_task(a, f"research {a.value}", 1) for a in agents],
        review_follow_up=review_follow_up or [],
    )
    critic = FakeCritic(verdict_sequence=critic_verdicts or [Verdict.APPROVED])
    writer = FakeWriter()
    agent_set = AgentSet(supervisor=supervisor, critic=critic, writer=writer, specialists=specialists)
    return agent_set, {"specialists": specialists, "supervisor": supervisor, "critic": critic, "writer": writer}
