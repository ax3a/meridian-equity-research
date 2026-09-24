from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from meridian.core.config import Settings
from meridian.core.errors import LLMOutputError, ProviderError
from meridian.providers.llm.anthropic_provider import AnthropicLLMProvider
from meridian.providers.llm.base import ChatMessage, LLMRequest, ToolSpec
from meridian.providers.llm.schema_tools import inline_json_schema
from meridian.schemas.enums import AgentName


class Answer(BaseModel):
    summary: str
    score: int = 0


def _settings(**overrides: Any) -> Settings:
    base = dict(
        env="test",
        redis_url=None,
        llm_provider="anthropic",
        anthropic_api_key="sk-ant-test-key",
        llm_max_retries=3,
        llm_timeout_seconds=30.0,
    )
    base.update(overrides)
    return Settings(**base)


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Please analyse this company.")]


# ---- fakes: no network, record kwargs, replay queued responses/exceptions ----------------------


class FakeBlock:
    def __init__(self, type_: str, **kw: Any) -> None:
        self.type = type_
        self._kw = kw
        for k, v in kw.items():
            setattr(self, k, v)

    def model_dump(self) -> dict[str, Any]:
        return {"type": self.type, **self._kw}


class FakeUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeStopDetails:
    def __init__(self, category: str | None) -> None:
        self.category = category
        self.explanation = "simulated refusal"


class FakeMessage:
    def __init__(
        self,
        content: list[FakeBlock],
        *,
        stop_reason: str = "end_turn",
        stop_details: FakeStopDetails | None = None,
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.usage = FakeUsage(input_tokens, output_tokens)
        self.model = "claude-sonnet-5"


class RecordingEndpoint:
    """Records every kwargs dict it is called with and replays a queue of responses/exceptions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._queue: list[Any] = []

    def queue(self, *items: Any) -> None:
        self._queue.extend(items)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._queue:
            raise AssertionError("RecordingEndpoint queue exhausted")
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _Namespace:
    def __init__(self, endpoint: RecordingEndpoint) -> None:
        self.create = endpoint.create


class _BetaNamespace:
    def __init__(self, endpoint: RecordingEndpoint) -> None:
        self.messages = _Namespace(endpoint)


class FakeAsyncAnthropic:
    def __init__(self) -> None:
        self.messages_endpoint = RecordingEndpoint()
        self.beta_endpoint = RecordingEndpoint()
        self.messages = _Namespace(self.messages_endpoint)
        self.beta = _BetaNamespace(self.beta_endpoint)


def _rate_limit_error() -> anthropic.RateLimitError:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(429, request=req)
    return anthropic.RateLimitError("rate limited", response=resp, body=None)


def _server_error() -> anthropic.InternalServerError:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(500, request=req)
    return anthropic.InternalServerError("server error", response=resp, body=None)


BANNED_KEYS = ("temperature", "top_p", "top_k", "thinking")


def _assert_no_banned_params(kwargs: dict[str, Any]) -> None:
    for key in BANNED_KEYS:
        assert key not in kwargs, f"banned sampling parameter {key!r} was sent: {kwargs}"


# ---- structured-output path ----------------------------------------------------------------


async def test_structured_output_path_sends_json_schema_and_no_tools() -> None:
    client = FakeAsyncAnthropic()
    text_block = FakeBlock("text", text=json.dumps({"summary": "all good", "score": 7}))
    client.messages_endpoint.queue(FakeMessage([text_block]))

    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False), client=client)
    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys prompt",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    resp = await provider.complete(req)

    assert resp.structured == {"summary": "all good", "score": 7}
    assert len(client.messages_endpoint.calls) == 1
    kwargs = client.messages_endpoint.calls[0]
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["output_config"]["format"] == {"type": "json_schema", "schema": inline_json_schema(Answer)}
    assert kwargs["output_config"]["effort"] == "medium"  # settings.effort_for("worker") default
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
    _assert_no_banned_params(kwargs)
    assert client.beta_endpoint.calls == []  # worker tier / fallbacks disabled -> plain client used


async def test_structured_output_path_used_when_force_output_false_but_no_tools() -> None:
    client = FakeAsyncAnthropic()
    text_block = FakeBlock("text", text=json.dumps({"summary": "no tools needed"}))
    client.messages_endpoint.queue(FakeMessage([text_block]))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False), client=client)

    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=False,
        tools=[],
    )
    resp = await provider.complete(req)

    assert resp.structured == {"summary": "no tools needed"}
    kwargs = client.messages_endpoint.calls[0]
    assert "tools" not in kwargs


# ---- tool-loop path -------------------------------------------------------------------------


def _profile_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="get_company_profile",
        description="Fetch a company profile.",
        input_schema={
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    )


async def test_tool_loop_sends_strict_tools_plus_submit_answer_and_maps_tool_use() -> None:
    client = FakeAsyncAnthropic()
    call_block = FakeBlock("tool_use", id="call_1", name="get_company_profile", input={"ticker": "MSFT"})
    submit_block = FakeBlock("tool_use", id="call_2", name="submit_answer", input={"summary": "ok", "score": 9})
    client.messages_endpoint.queue(FakeMessage([call_block, submit_block], stop_reason="tool_use"))

    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False), client=client)
    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys",
        messages=_messages(),
        tools=[_profile_tool_spec()],
        output_schema=Answer,
        force_output=False,
    )
    resp = await provider.complete(req)

    kwargs = client.messages_endpoint.calls[0]
    _assert_no_banned_params(kwargs)
    assert "output_config" in kwargs
    assert "format" not in kwargs["output_config"]
    tool_names = {t["name"] for t in kwargs["tools"]}
    assert tool_names == {"get_company_profile", "submit_answer"}
    for t in kwargs["tools"]:
        assert t["strict"] is True
        assert "$ref" not in json.dumps(t["input_schema"])
        assert t["input_schema"]["additionalProperties"] is False
    assert kwargs["tool_choice"] == {"type": "auto"}

    assert resp.stop_reason == "tool_use"
    assert len(resp.tool_calls) == 2
    profile_call = next(c for c in resp.tool_calls if c.name == "get_company_profile")
    assert profile_call.arguments == {"ticker": "MSFT"}
    submit_call = next(c for c in resp.tool_calls if c.name == "submit_answer")
    assert submit_call.id == "call_2"
    assert resp.structured == {"summary": "ok", "score": 9}
    assert resp.raw_content and resp.raw_content[0]["type"] == "tool_use"


async def test_tool_loop_without_submit_answer_leaves_structured_none() -> None:
    client = FakeAsyncAnthropic()
    call_block = FakeBlock("tool_use", id="call_1", name="get_company_profile", input={"ticker": "MSFT"})
    client.messages_endpoint.queue(FakeMessage([call_block], stop_reason="tool_use"))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False), client=client)

    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys",
        messages=_messages(),
        tools=[_profile_tool_spec()],
        output_schema=Answer,
        force_output=False,
    )
    resp = await provider.complete(req)

    assert resp.structured is None
    assert resp.tool_calls[0].name == "get_company_profile"


# ---- refusal ---------------------------------------------------------------------------------


async def test_refusal_raises_llm_output_error_with_category() -> None:
    client = FakeAsyncAnthropic()
    client.messages_endpoint.queue(FakeMessage([], stop_reason="refusal", stop_details=FakeStopDetails("cyber")))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False), client=client)

    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    with pytest.raises(LLMOutputError) as exc_info:
        await provider.complete(req)
    assert exc_info.value.details.get("category") == "cyber"


# ---- retries -----------------------------------------------------------------------------------


async def test_retries_on_rate_limit_then_succeeds() -> None:
    client = FakeAsyncAnthropic()
    text_block = FakeBlock("text", text=json.dumps({"summary": "ok"}))
    client.messages_endpoint.queue(_rate_limit_error(), FakeMessage([text_block]))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False, llm_max_retries=3), client=client)

    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    resp = await provider.complete(req)

    assert resp.structured == {"summary": "ok"}
    assert len(client.messages_endpoint.calls) == 2


async def test_exhausted_retries_raise_provider_error() -> None:
    client = FakeAsyncAnthropic()
    client.messages_endpoint.queue(_server_error(), _server_error(), _server_error())
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False, llm_max_retries=3), client=client)

    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    with pytest.raises(ProviderError):
        await provider.complete(req)
    assert len(client.messages_endpoint.calls) == 3


# ---- usage / cost --------------------------------------------------------------------------


async def test_usage_and_cost_are_populated() -> None:
    client = FakeAsyncAnthropic()
    text_block = FakeBlock("text", text=json.dumps({"summary": "ok"}))
    client.messages_endpoint.queue(FakeMessage([text_block], input_tokens=1000, output_tokens=200))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False), client=client)

    req = LLMRequest(
        agent=AgentName.FINANCIALS,
        tier="worker",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    resp = await provider.complete(req)

    assert resp.usage.agent == AgentName.FINANCIALS
    assert resp.usage.provider == "anthropic"
    assert resp.usage.model == "claude-sonnet-5"
    assert resp.usage.input_tokens == 1000
    assert resp.usage.output_tokens == 200
    # claude-sonnet-5: $2/1M in, $10/1M out
    assert resp.usage.cost_usd == pytest.approx(1000 / 1_000_000 * 2.0 + 200 / 1_000_000 * 10.0)
    assert resp.usage.latency_ms >= 0


# ---- refusal fallbacks (Opus-tier only) -------------------------------------------------------


async def test_refusal_fallbacks_used_on_opus_tier_when_enabled() -> None:
    client = FakeAsyncAnthropic()
    text_block = FakeBlock("text", text=json.dumps({"summary": "ok"}))
    client.beta_endpoint.queue(FakeMessage([text_block]))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=True), client=client)

    req = LLMRequest(
        agent=AgentName.CRITIC,
        tier="critic",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    resp = await provider.complete(req)

    assert resp.structured == {"summary": "ok"}
    assert client.messages_endpoint.calls == []
    kwargs = client.beta_endpoint.calls[0]
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["fallbacks"] == "default"
    _assert_no_banned_params(kwargs)


async def test_refusal_fallbacks_not_used_on_worker_tier() -> None:
    client = FakeAsyncAnthropic()
    text_block = FakeBlock("text", text=json.dumps({"summary": "ok"}))
    client.messages_endpoint.queue(FakeMessage([text_block]))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=True), client=client)

    req = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    await provider.complete(req)

    assert client.beta_endpoint.calls == []
    assert "betas" not in client.messages_endpoint.calls[0]


async def test_refusal_fallbacks_not_used_when_disabled_even_on_opus_tier() -> None:
    client = FakeAsyncAnthropic()
    text_block = FakeBlock("text", text=json.dumps({"summary": "ok"}))
    client.messages_endpoint.queue(FakeMessage([text_block]))
    provider = AnthropicLLMProvider(_settings(llm_refusal_fallbacks=False), client=client)

    req = LLMRequest(
        agent=AgentName.CRITIC,
        tier="critic",
        system="sys",
        messages=_messages(),
        output_schema=Answer,
        force_output=True,
    )
    await provider.complete(req)

    assert client.beta_endpoint.calls == []
    assert len(client.messages_endpoint.calls) == 1
