from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from meridian.core.ids import utcnow
from meridian.schemas.enums import AgentName


class LLMUsage(BaseModel):
    agent: AgentName
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    at: datetime = Field(default_factory=utcnow)


class ToolCallRecord(BaseModel):
    id: str
    agent: AgentName
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)  # sanitised summary, never secrets
    status: str  # "ok" | "error" | "cached"
    duration_ms: float
    result_summary: str = ""
    error: str | None = None
    attempts: int = 1
    at: datetime = Field(default_factory=utcnow)


class RunError(BaseModel):
    agent: AgentName | None = None
    stage: str
    message: str
    retryable: bool = False
    at: datetime = Field(default_factory=utcnow)
