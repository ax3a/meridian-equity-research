from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from meridian.core.ids import utcnow
from meridian.schemas.enums import AgentName


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    COMPANY_RESOLVED = "company_resolved"
    PLAN_CREATED = "plan_created"
    WAVE_STARTED = "wave_started"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    TOOL_CALLED = "tool_called"
    SUPERVISOR_REVIEW = "supervisor_review"
    CRITIC_STARTED = "critic_started"
    CRITIC_VERDICT = "critic_verdict"
    REVISION_STARTED = "revision_started"
    AWAITING_APPROVAL = "awaiting_approval"
    FEEDBACK_RECEIVED = "feedback_received"
    REPORT_STARTED = "report_started"
    REPORT_COMPLETED = "report_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class ProgressEvent(BaseModel):
    """User-facing progress event. Contains action summaries only — never model reasoning."""

    seq: int = 0
    session_id: str
    type: EventType
    agent: AgentName | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)
