from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from meridian.core.ids import stable_id
from meridian.schemas.enums import AgentName, FeedbackAction, TaskStatus

Depth = Literal["quick", "standard", "deep"]


# Tickers are interpolated into provider URL paths, so they are constrained at the boundary rather than
# trusted: letters, digits, dot and dash only. This blocks path traversal and CRLF before a request is
# ever built (the SSRF host allowlist in core.http remains the primary control).
TICKER_PATTERN = r"^[A-Za-z0-9.\-]{1,12}$"


class CompanyIdentity(BaseModel):
    name: str
    ticker: str = Field(pattern=TICKER_PATTERN)
    cik: str  # zero-padded 10 digits
    exchange: str | None = None
    sic: str | None = None
    sic_description: str | None = None
    fiscal_year_end: str | None = None  # "MMDD"
    state_of_incorporation: str | None = None
    website: str | None = None

    @field_validator("ticker")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("cik")
    @classmethod
    def _pad(cls, v: str) -> str:
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return digits.zfill(10)

    @property
    def is_financial_institution(self) -> bool:
        """Banks/insurers/REITs (SIC 6000-6799): gross margin and EV multiples are not meaningful."""
        return bool(self.sic and self.sic.isdigit() and 6000 <= int(self.sic) <= 6799)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    ticker: str | None = Field(default=None, pattern=TICKER_PATTERN)
    focus_areas: list[str] = Field(default_factory=list, max_length=10)
    depth: Depth = "standard"
    require_approval: bool | None = None
    user_id: str | None = None


class ResearchTask(BaseModel):
    id: str
    agent: AgentName
    objective: str
    wave: int = Field(ge=1, le=4)
    depends_on: list[AgentName] = Field(default_factory=list)
    reason: str = ""
    instructions: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    revision: int = 0
    fingerprint: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    @classmethod
    def make(cls, agent: AgentName, objective: str, wave: int, *, revision: int = 0, **kw: Any) -> ResearchTask:
        instructions = kw.get("instructions") or {}
        fp = stable_id("fp", agent, " ".join(objective.lower().split()), sorted(instructions.items()), revision)
        return cls(
            id=stable_id("task", fp),
            agent=agent,
            objective=objective,
            wave=wave,
            revision=revision,
            fingerprint=fp,
            **kw,
        )


class ResearchPlan(BaseModel):
    objectives: list[str]
    tasks: list[ResearchTask]
    skipped_agents: dict[str, str] = Field(default_factory=dict)  # agent -> reason
    rationale: str
    focus_areas: list[str] = Field(default_factory=list)

    def agents(self) -> list[AgentName]:
        return [t.agent for t in self.tasks]


class HumanFeedback(BaseModel):
    action: FeedbackAction
    agent: AgentName | None = None
    ticker: str | None = Field(default=None, pattern=TICKER_PATTERN)
    comment: str | None = Field(default=None, max_length=2000)
    submitted_at: datetime | None = None
