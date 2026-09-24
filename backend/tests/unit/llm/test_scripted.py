from __future__ import annotations

import pytest

from meridian.providers.llm.base import ChatMessage, LLMProvider, LLMRequest, LLMResponse, LLMToolCall
from meridian.providers.llm.scripted import ScriptedLLMProvider, ScriptExhaustedError
from meridian.schemas.enums import AgentName
from meridian.schemas.telemetry import LLMUsage


def _req(agent: AgentName = AgentName.COMPANY) -> LLMRequest:
    return LLMRequest(agent=agent, tier="worker", system="sys", messages=[ChatMessage(role="user", content="hi")])


def test_scripted_provider_shape() -> None:
    provider = ScriptedLLMProvider()
    assert provider.name == "scripted"
    assert provider.generative is True
    assert isinstance(provider, LLMProvider)


async def test_scripted_provider_returns_queued_response_and_records_request() -> None:
    provider = ScriptedLLMProvider()
    usage = LLMUsage(agent=AgentName.COMPANY, model="test-model", provider="scripted")
    response = LLMResponse(text="hello there", usage=usage)
    provider.script(AgentName.COMPANY, response)

    req = _req()
    result = await provider.complete(req)

    assert result is response
    assert provider.requests == [req]


async def test_scripted_provider_dict_shorthand_fills_defaults() -> None:
    provider = ScriptedLLMProvider()
    provider.script(AgentName.COMPANY, {"text": "hi", "structured": {"a": 1}})

    result = await provider.complete(_req())

    assert result.text == "hi"
    assert result.structured == {"a": 1}
    assert result.usage.agent == AgentName.COMPANY


async def test_scripted_provider_callable_entry_receives_request() -> None:
    provider = ScriptedLLMProvider()

    def make_response(request: LLMRequest) -> dict:
        return {"text": f"echo:{request.agent}"}

    provider.script(AgentName.COMPANY, make_response)

    result = await provider.complete(_req())

    assert result.text == "echo:company"


async def test_scripted_provider_sequences_multiple_responses() -> None:
    provider = ScriptedLLMProvider()
    provider.script(AgentName.COMPANY, {"text": "first"}, {"text": "second"})

    r1 = await provider.complete(_req())
    r2 = await provider.complete(_req())

    assert r1.text == "first"
    assert r2.text == "second"


async def test_scripted_provider_keeps_separate_queues_per_agent() -> None:
    provider = ScriptedLLMProvider()
    provider.script(AgentName.COMPANY, {"text": "company-answer"})
    provider.script(AgentName.FINANCIALS, {"text": "financials-answer"})

    r_fin = await provider.complete(_req(AgentName.FINANCIALS))
    r_co = await provider.complete(_req(AgentName.COMPANY))

    assert r_fin.text == "financials-answer"
    assert r_co.text == "company-answer"


async def test_scripted_provider_exhaustion_raises_clear_error() -> None:
    provider = ScriptedLLMProvider()
    provider.script(AgentName.COMPANY, {"text": "only one"})
    await provider.complete(_req())

    with pytest.raises(ScriptExhaustedError, match="company"):
        await provider.complete(_req())


async def test_scripted_provider_supports_tool_calls_in_dict_shorthand() -> None:
    provider = ScriptedLLMProvider()
    provider.script(
        AgentName.COMPANY,
        {"tool_calls": [LLMToolCall(id="call_1", name="get_company_profile", arguments={"ticker": "MSFT"})]},
    )

    result = await provider.complete(_req())

    assert result.tool_calls[0].name == "get_company_profile"
