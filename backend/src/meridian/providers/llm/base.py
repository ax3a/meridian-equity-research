from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from meridian.core.config import LLMTier
from meridian.schemas.enums import AgentName
from meridian.schemas.telemetry import LLMUsage


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    # str, or Anthropic-style content blocks (tool_use / tool_result) for multi-turn tool loops.
    content: str | list[dict[str, Any]]


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class LLMToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMRequest(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    agent: AgentName
    tier: LLMTier
    system: str
    messages: list[ChatMessage]
    tools: list[ToolSpec] = Field(default_factory=list)
    # When set, the provider exposes a final "submit_answer" tool with this schema and returns its arguments
    # in `structured`. With force_output=True (or no other tools) the provider must force that tool.
    output_schema: type[BaseModel] | None = None
    force_output: bool = False
    max_tokens: int = 4096
    temperature: float = 0.2


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    structured: dict[str, Any] | None = None
    stop_reason: str | None = None
    usage: LLMUsage
    raw_content: list[dict[str, Any]] = Field(default_factory=list)  # assistant blocks, for tool loops


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    # False for the deterministic offline mode: agents then use their evidence-driven synthesis path.
    generative: bool

    async def complete(self, request: LLMRequest) -> LLMResponse: ...
