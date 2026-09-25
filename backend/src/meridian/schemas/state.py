"""Typed shared research state for the LangGraph workflow.

Fields annotated with a reducer can be written by parallel agent nodes in the same super-step.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, Field

from meridian.schemas.analysis import CriticReview, PeerComparison, ValuationResult
from meridian.schemas.citations import Evidence, Source
from meridian.schemas.enums import AgentName, FindingStatus, RunStatus
from meridian.schemas.financials import FinancialMetrics, FinancialStatements, Quote
from meridian.schemas.findings import AgentOutput, Finding
from meridian.schemas.report import ResearchReport
from meridian.schemas.research import CompanyIdentity, HumanFeedback, ResearchPlan, ResearchRequest, ResearchTask
from meridian.schemas.telemetry import LLMUsage, RunError, ToolCallRecord

T = TypeVar("T")

ApprovalState = Literal["not_required", "pending", "approved", "changes_requested"]


def merge_dict(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


def append_list(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    return [*(left or []), *(right or [])]


def union_list(left: list[str] | None, right: list[str] | None) -> list[str]:
    seen = dict.fromkeys(left or [])
    seen.update(dict.fromkeys(right or []))
    return list(seen)


def keep_latest(left: T | None, right: T | None) -> T | None:
    return right if right is not None else left


class ResearchState(BaseModel):
    session_id: str
    request: ResearchRequest
    status: RunStatus = RunStatus.QUEUED
    require_approval: bool = True
    user_preferences: dict[str, Any] = Field(default_factory=dict)

    company: CompanyIdentity | None = None
    plan: ResearchPlan | None = None
    current_wave: int = 0

    tasks: Annotated[dict[str, ResearchTask], merge_dict] = Field(default_factory=dict)
    outputs: Annotated[dict[str, AgentOutput], merge_dict] = Field(default_factory=dict)  # agent -> latest
    output_history: Annotated[list[AgentOutput], append_list] = Field(default_factory=list)
    completed_fingerprints: Annotated[list[str], union_list] = Field(default_factory=list)

    sources: Annotated[dict[str, Source], merge_dict] = Field(default_factory=dict)
    evidence: Annotated[dict[str, Evidence], merge_dict] = Field(default_factory=dict)

    financials: Annotated[FinancialStatements | None, keep_latest] = None
    metrics: Annotated[FinancialMetrics | None, keep_latest] = None
    quote: Annotated[Quote | None, keep_latest] = None
    peers: Annotated[PeerComparison | None, keep_latest] = None
    valuation: Annotated[ValuationResult | None, keep_latest] = None

    critic_reviews: Annotated[list[CriticReview], append_list] = Field(default_factory=list)
    revision_round: int = 0
    supervisor_loops: int = 0
    rework_agents: list[AgentName] = Field(default_factory=list)
    rework_notes: dict[str, str] = Field(default_factory=dict)  # agent -> what to fix

    human_feedback: Annotated[list[HumanFeedback], append_list] = Field(default_factory=list)
    approval: ApprovalState = "not_required"

    report: ResearchReport | None = None

    errors: Annotated[list[RunError], append_list] = Field(default_factory=list)
    tool_calls: Annotated[list[ToolCallRecord], append_list] = Field(default_factory=list)
    usage: Annotated[list[LLMUsage], append_list] = Field(default_factory=list)
    timings: Annotated[dict[str, float], merge_dict] = Field(default_factory=dict)  # node/agent -> ms

    # ---- read helpers -------------------------------------------------
    def output(self, agent: AgentName) -> AgentOutput | None:
        return self.outputs.get(agent.value)

    def findings(self, agents: list[AgentName] | None = None) -> list[Finding]:
        wanted = {a.value for a in agents} if agents else None
        return [f for key, out in self.outputs.items() if wanted is None or key in wanted for f in out.findings]

    def approved_findings(self) -> list[Finding]:
        return [f for f in self.findings() if f.status in (FindingStatus.APPROVED, FindingStatus.UNVERIFIED)]

    def uses_snapshot_data(self) -> bool:
        return any(s.is_snapshot for s in self.sources.values())
