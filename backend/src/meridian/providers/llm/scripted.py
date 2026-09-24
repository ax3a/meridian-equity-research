"""A scripted `LLMProvider` for tests: queue canned responses per agent, assert on recorded requests.

This is the backbone other workstreams' agent/graph tests are built on. Usage:

    provider = ScriptedLLMProvider()

    # Queue one or more responses for a given agent. Each call to `complete()` for that agent pops
    # the next entry off its queue. Entries can be:
    #   - an `LLMResponse` (used as-is)
    #   - a `dict` of `LLMResponse` field overrides (e.g. {"text": "..."}, {"structured": {...}},
    #     {"tool_calls": [...]}) — missing fields (notably `usage`) get sensible defaults
    #   - a callable `(LLMRequest) -> LLMResponse | dict`, for responses that depend on the request
    #     (e.g. echoing back an argument, or asserting something about `request.messages` first)
    provider.script(AgentName.FINANCIALS, {"structured": {"summary": "...", "findings": []}})
    provider.script(AgentName.FILINGS, response_one, response_two)  # sequential, popped in order

    result = await provider.complete(request)   # returns response_one-equivalent, in order
    provider.requests                            # every LLMRequest ever passed to complete(), in order

    # Wire it into a ProviderRegistry / AgentDeps in place of the real Anthropic provider so agent
    # tests run with no network and no API key:
    registry = ProviderRegistry(..., llm=provider)

Each agent (`AgentName`) has its own independent queue, so scripting one agent's responses never
interferes with another's. Calling `complete()` for an agent whose queue is empty (never scripted, or
already exhausted) raises `ScriptExhaustedError` with a message naming the agent, so a missing script
fails fast and points straight at the fix instead of surfacing as a confusing downstream failure.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from meridian.providers.llm.base import LLMRequest, LLMResponse
from meridian.schemas.enums import AgentName
from meridian.schemas.telemetry import LLMUsage

ScriptEntry = LLMResponse | dict[str, Any] | Callable[[LLMRequest], "LLMResponse | dict[str, Any]"]


class ScriptExhaustedError(RuntimeError):
    """Raised when `ScriptedLLMProvider.complete()` is called with no scripted response left."""


class ScriptedLLMProvider:
    name = "scripted"
    generative = True

    def __init__(self) -> None:
        self._scripts: dict[AgentName, deque[ScriptEntry]] = defaultdict(deque)
        self.requests: list[LLMRequest] = []

    def script(self, agent: AgentName, *responses: ScriptEntry) -> None:
        """Queue one or more responses to be returned, in order, for `agent`'s next `complete()` calls."""
        self._scripts[agent].extend(responses)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        queue = self._scripts.get(request.agent)
        if not queue:
            raise ScriptExhaustedError(
                f"ScriptedLLMProvider: no scripted response left for agent {request.agent!r}. "
                f"Call provider.script(AgentName.{request.agent.name}, ...) with at least one response "
                "before running this agent, or queue more responses if it calls the LLM more than once."
            )
        entry = queue.popleft()
        return self._materialize(request, entry)

    def _materialize(self, request: LLMRequest, entry: ScriptEntry) -> LLMResponse:
        if callable(entry) and not isinstance(entry, LLMResponse):
            entry = entry(request)
        if isinstance(entry, LLMResponse):
            return entry
        payload: dict[str, Any] = dict(entry)
        payload.setdefault("usage", LLMUsage(agent=request.agent, model="scripted", provider="scripted"))
        return LLMResponse(**payload)
