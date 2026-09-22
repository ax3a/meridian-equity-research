"""Public API contract (v1). The frontend's `lib/types.ts` mirrors these models exactly."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from meridian.schemas.analysis import CriticReview
from meridian.schemas.citations import Evidence, Source
from meridian.schemas.enums import AgentName, RunStatus, TaskStatus
from meridian.schemas.findings import Finding
from meridian.schemas.research import CompanyIdentity, HumanFeedback, ResearchPlan, ResearchRequest
from meridian.schemas.state import ApprovalState
from meridian.schemas.telemetry import RunError, ToolCallRecord


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ResearchCreated(BaseModel):
    id: str
    status: RunStatus
    events_url: str
    status_url: str


class ResearchSummary(BaseModel):
    id: str
    query: str
    company: CompanyIdentity | None
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    has_report: bool
    llm_mode: str
    data_mode: str


class AgentProgress(BaseModel):
    agent: AgentName
    status: TaskStatus
    wave: int
    revision: int = 0
    objective: str = ""


class StatusView(BaseModel):
    id: str
    status: RunStatus
    progress: float = Field(ge=0, le=1)
    current_wave: int
    revision_round: int
    approval: ApprovalState
    agents: list[AgentProgress]
    message: str | None = None


class ResearchDetail(BaseModel):
    id: str
    request: ResearchRequest
    status: RunStatus
    company: CompanyIdentity | None
    plan: ResearchPlan | None
    approval: ApprovalState
    current_wave: int
    revision_round: int
    critic_reviews: list[CriticReview]
    human_feedback: list[HumanFeedback]
    errors: list[RunError]
    has_report: bool
    llm_mode: str
    data_mode: str
    uses_snapshot_data: bool
    created_at: datetime
    updated_at: datetime


class AgentRunView(BaseModel):
    agent: AgentName
    task_id: str
    objective: str
    status: TaskStatus
    wave: int
    revision: int
    summary: str
    findings: list[Finding]
    tools_used: list[str]
    duration_ms: float | None
    error: str | None


class SourceView(BaseModel):
    source: Source
    evidence: list[Evidence]
    cited_by_findings: list[str]


class UsageBreakdown(BaseModel):
    agent: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class TraceView(BaseModel):
    session_id: str
    agent_runs: list[AgentRunView]
    tool_calls: list[ToolCallRecord]
    usage: list[UsageBreakdown]
    total_tokens: int
    total_cost_usd: float
    timings_ms: dict[str, float]
    errors: list[RunError]


class ReviewSectionPreview(BaseModel):
    agent: AgentName
    summary: str
    findings: list[Finding]


class ReviewPackage(BaseModel):
    """What a human sees at the approval checkpoint."""

    session_id: str
    company: CompanyIdentity
    plan: ResearchPlan
    sources: list[Source]
    preliminary: list[ReviewSectionPreview]
    critic: CriticReview | None
    available_actions: list[str]


class FeedbackRequest(BaseModel):
    actions: list[HumanFeedback] = Field(min_length=1, max_length=10)


class CompanySearchResult(BaseModel):
    results: list[CompanyIdentity]


class ProviderStatus(BaseModel):
    name: str
    role: str
    configured: bool
    detail: str | None = None


class SystemStatus(BaseModel):
    version: str
    llm_mode: Literal["anthropic", "offline"]
    data_mode: str
    database: bool
    redis: bool
    providers: list[ProviderStatus]
    active_runs: int


class SavedCompany(BaseModel):
    company: CompanyIdentity
    saved_at: datetime
    last_research_id: str | None = None


class DashboardView(BaseModel):
    recent_runs: list[ResearchSummary]
    saved_companies: list[SavedCompany]
    system: SystemStatus
    stats: dict[str, float]


class UserPreferences(BaseModel):
    report_length: Literal["brief", "standard", "detailed"] = "standard"
    preferred_sectors: list[str] = Field(default_factory=list, max_length=20)
    preferred_metrics: list[str] = Field(default_factory=list, max_length=30)
    valuation_methods: list[Literal["pe", "ev_ebitda", "ev_sales", "price_sales", "price_fcf", "dcf"]] = Field(
        default_factory=lambda: ["pe", "ev_ebitda", "ev_sales", "price_fcf", "dcf"])
    require_approval: bool = True
