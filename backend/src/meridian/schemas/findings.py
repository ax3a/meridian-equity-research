from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from meridian.core.ids import stable_id
from meridian.schemas.enums import (
    AgentName,
    Confidence,
    FindingKind,
    FindingStatus,
    ReportSection,
    TaskStatus,
)


class Finding(BaseModel):
    """One atomic claim produced by an agent, tied to evidence and/or calculated metrics."""

    id: str = ""
    agent: AgentName
    section: ReportSection
    claim: str = Field(min_length=3, max_length=1500)
    kind: FindingKind
    evidence_ids: list[str] = Field(default_factory=list)
    metric_refs: list[str] = Field(default_factory=list)  # FinancialMetrics refs, e.g. "FY2024.gross_margin"
    confidence: Confidence = Confidence.MEDIUM
    category: str | None = None  # e.g. RiskCategory value, "catalyst", "open_question"
    status: FindingStatus = FindingStatus.DRAFT
    revision: int = 0

    @model_validator(mode="after")
    def _assign_id(self) -> Finding:
        if not self.id:
            self.id = stable_id("fnd", self.agent, self.section, self.claim, self.revision)
        return self


class AgentOutput(BaseModel):
    """Everything an agent produced for one task execution."""

    agent: AgentName
    task_id: str
    status: TaskStatus
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)  # structured payload (valuation, peers, ...)
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    error: str | None = None
    revision: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds() * 1000
        return None
