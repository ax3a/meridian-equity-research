"""Contracts between the graph and the orchestration agents (supervisor, critic, report writer)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol

from meridian.schemas.analysis import CriticReview
from meridian.schemas.citations import Evidence, Source
from meridian.schemas.enums import AgentName
from meridian.schemas.findings import AgentOutput
from meridian.schemas.report import ResearchReport
from meridian.schemas.research import CompanyIdentity, HumanFeedback, ResearchPlan, ResearchTask
from meridian.schemas.state import ResearchState
from meridian.schemas.telemetry import LLMUsage, ToolCallRecord

if TYPE_CHECKING:
    from meridian.agents.base import AgentResult


@dataclass
class ResolveResult:
    company: CompanyIdentity
    sources: dict[str, Source] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: list[LLMUsage] = field(default_factory=list)


@dataclass
class PlanResult:
    plan: ResearchPlan
    usage: list[LLMUsage] = field(default_factory=list)


@dataclass
class ReviewDecision:
    """Supervisor's post-research review: extra work to dispatch (possibly none) and conflicts noted."""

    follow_up: list[ResearchTask] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    summary: str = ""
    usage: list[LLMUsage] = field(default_factory=list)


@dataclass
class CriticResult:
    review: CriticReview
    # Outputs whose findings had their status updated (APPROVED / REJECTED / UNVERIFIED), keyed by agent value.
    updated_outputs: dict[str, AgentOutput] = field(default_factory=dict)
    rework_notes: dict[str, str] = field(default_factory=dict)  # agent value -> instructions for revision
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: list[LLMUsage] = field(default_factory=list)


@dataclass
class WriterResult:
    report: ResearchReport
    usage: list[LLMUsage] = field(default_factory=list)


class Specialist(Protocol):
    # ClassVar, because every agent sets its name on the class and none of them can be renamed per
    # instance. Declared as a plain attribute this protocol promised something settable, so no real
    # agent satisfied it -- visible only for Bull and Bear, since the rest are loaded dynamically and
    # arrive as `Any`.
    name: ClassVar[AgentName]

    async def execute(self, task: ResearchTask, state: ResearchState) -> AgentResult: ...


class Supervisor(Protocol):
    async def resolve(self, state: ResearchState) -> ResolveResult: ...

    async def plan(self, state: ResearchState) -> PlanResult: ...

    async def review(self, state: ResearchState) -> ReviewDecision: ...

    def tasks_for_feedback(self, state: ResearchState, feedback: list[HumanFeedback]) -> list[ResearchTask]: ...

    def tasks_for_rework(
        self, state: ResearchState, agents: list[AgentName], notes: dict[str, str]
    ) -> list[ResearchTask]:
        """Revision tasks (revision+1) for critic-rejected agents."""
        ...


class Critic(Protocol):
    async def review(self, state: ResearchState) -> CriticResult: ...


class ReportWriter(Protocol):
    async def write(self, state: ResearchState) -> WriterResult: ...


@dataclass
class AgentSet:
    supervisor: Supervisor
    critic: Critic
    writer: ReportWriter
    specialists: dict[AgentName, Specialist]
