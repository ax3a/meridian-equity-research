"""`OpenAICompatLLMProvider` against a real HTTP endpoint speaking the OpenAI protocol.

These assert on the bytes that actually went over the wire, which a scripted provider cannot do: it
replaces the provider, so it can only show the callers behave. Everything here -- request shape, the
Anthropic-to-OpenAI message translation, tool-argument decoding -- is precisely what a fake at the
provider boundary would have assumed correct.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from meridian.core.config import Settings
from meridian.providers.llm.base import ChatMessage, LLMRequest, ToolSpec
from meridian.providers.llm.openai_compat import OpenAICompatLLMProvider
from meridian.schemas.enums import AgentName
from tests.integration.llm.fake_openai_server import _completion, running_server, tool_call


class _Answer(BaseModel):
    summary: str
    findings: list[str] = []


def _settings(base_url: str) -> Settings:
    # `llm_provider="auto"` explicitly: the test suite pins LLM_PROVIDER=offline globally so nothing can
    # reach a real API by accident, and these tests need the selection logic itself.
    return Settings(
        sec_user_agent="Meridian Test test@example.com",
        redis_url=None,
        llm_provider="auto",
        llm_base_url=base_url,
        model_worker="fake-model",
    )


def _request(**overrides) -> LLMRequest:
    payload = {
        "agent": AgentName.COMPANY,
        "tier": "worker",
        "system": "You are a test agent.",
        "messages": [ChatMessage(role="user", content="Analyse TST")],
    }
    payload.update(overrides)
    return LLMRequest(**payload)


async def test_the_provider_is_selected_by_base_url_alone() -> None:
    settings = _settings("http://127.0.0.1:1/v1")

    assert settings.llm_mode == "openai_compat"
    assert settings.anthropic_api_key is None, "no paid key should be needed to reach the generative path"


async def test_without_a_base_url_the_system_stays_offline() -> None:
    """The default has to remain deterministic offline mode, key or no key."""
    settings = Settings(sec_user_agent="Meridian Test test@example.com", redis_url=None, llm_provider="auto")

    assert settings.llm_base_url is None
    assert settings.llm_mode == "offline"


async def test_a_plain_completion_round_trips() -> None:
    async with running_server(lambda p: _completion(content="hello from the model")) as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            response = await provider.complete(_request())
        finally:
            await provider.aclose()

    assert response.text == "hello from the model"
    assert response.usage.input_tokens == 120
    assert response.usage.output_tokens == 40
    sent = fake.last_request()
    assert sent["model"] == "fake-model"
    assert sent["messages"][0] == {"role": "system", "content": "You are a test agent."}
    assert sent["messages"][1] == {"role": "user", "content": "Analyse TST"}


async def test_structured_output_is_requested_as_a_forced_tool() -> None:
    """`response_format` support varies across these endpoints; forced function calling does not.

    The force is `tool_choice: "required"`, not the object form naming the function. Both are valid
    OpenAI, but Gemini rejects the object form with a bare "Request contains an invalid argument" --
    and with a single tool on offer the two say the same thing.
    """
    async with running_server() as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            response = await provider.complete(_request(output_schema=_Answer, force_output=True))
        finally:
            await provider.aclose()

    sent = fake.last_request()
    assert sent["tool_choice"] == "required"
    schema = next(t for t in sent["tools"] if t["function"]["name"] == "submit_answer")["function"]["parameters"]
    assert "$ref" not in json.dumps(schema), "refs must be inlined; several endpoints reject them"
    assert response.structured == {"summary": "ok", "findings": []}
    assert response.tool_calls == [], "the answer tool is not a tool call for the caller to execute"


async def test_tool_calls_are_returned_and_arguments_decoded() -> None:
    async with running_server() as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            response = await provider.complete(
                _request(tools=[ToolSpec(name="get_profile", description="d", input_schema={"type": "object"})])
            )
        finally:
            await provider.aclose()

    assert [c.name for c in response.tool_calls] == ["get_profile"]
    assert response.tool_calls[0].arguments == {"ticker": "TST"}, "arguments arrive as a JSON string"
    assert fake.last_request()["tool_choice"] == "auto"


async def test_a_tool_result_turn_becomes_assistant_plus_tool_messages() -> None:
    """The translation the system's Anthropic-shaped state depends on.

    One assistant turn carrying two tool calls must become one assistant message plus two `role="tool"`
    messages, each keyed to the call it answers, in order.
    """
    conversation = [
        ChatMessage(role="user", content="Analyse TST"),
        ChatMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "calling tools"},
                {"type": "tool_use", "id": "call_a", "name": "get_profile", "input": {"ticker": "TST"}},
                {"type": "tool_use", "id": "call_b", "name": "get_filings", "input": {"ticker": "TST"}},
            ],
        ),
        ChatMessage(
            role="user",
            content=[
                {"type": "tool_result", "tool_use_id": "call_a", "content": "profile data"},
                {"type": "tool_result", "tool_use_id": "call_b", "content": [{"type": "text", "text": "filing data"}]},
            ],
        ),
    ]

    async with running_server(lambda p: _completion(content="done")) as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            await provider.complete(_request(messages=conversation))
        finally:
            await provider.aclose()

    messages = fake.last_request()["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "tool"]
    assistant = messages[2]
    assert [c["function"]["name"] for c in assistant["tool_calls"]] == ["get_profile", "get_filings"]
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"ticker": "TST"}
    assert messages[3] == {"role": "tool", "tool_call_id": "call_a", "content": "profile data"}
    assert messages[4] == {"role": "tool", "tool_call_id": "call_b", "content": "filing data"}


async def test_unparsable_tool_arguments_do_not_crash_the_run() -> None:
    """A response truncated at max_tokens leaves invalid JSON; the caller validates and moves on."""
    truncated = {"id": "c1", "type": "function", "function": {"name": "get_profile", "arguments": '{"ticker": "TS'}}

    async with running_server(lambda p: _completion(tool_calls=[truncated], finish_reason="length")) as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            response = await provider.complete(
                _request(tools=[ToolSpec(name="get_profile", description="d", input_schema={"type": "object"})])
            )
        finally:
            await provider.aclose()

    assert response.tool_calls[0].arguments == {}
    assert response.stop_reason == "length"


async def test_a_server_error_is_retried_and_then_succeeds() -> None:
    state = {"calls": 0}

    def flaky(payload):
        state["calls"] += 1
        if state["calls"] == 1:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="try again")
        return _completion(content="second time lucky")

    async with running_server(flaky) as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            response = await provider.complete(_request())
        finally:
            await provider.aclose()

    assert response.text == "second time lucky"
    assert state["calls"] == 2


async def test_a_bad_request_is_not_retried() -> None:
    """A 400 means the body is wrong; retrying it just multiplies the same failure."""
    state = {"calls": 0}

    def rejecting(payload):
        state["calls"] += 1
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="unsupported parameter")

    async with running_server(rejecting) as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            with pytest.raises(Exception):
                await provider.complete(_request())
        finally:
            await provider.aclose()

    assert state["calls"] == 1


async def test_no_authorization_header_when_no_key_is_set() -> None:
    """A local Ollama or vLLM needs no key; sending an empty bearer token upsets some of them."""
    settings = _settings("http://127.0.0.1:1/v1")
    provider = OpenAICompatLLMProvider(settings)
    try:
        assert "Authorization" not in provider._client.headers
    finally:
        await provider.aclose()


async def test_a_key_is_sent_as_a_bearer_token() -> None:
    settings = _settings("http://127.0.0.1:1/v1")
    settings.llm_api_key = pytest.importorskip("pydantic").SecretStr("secret-key")
    provider = OpenAICompatLLMProvider(settings)
    try:
        assert provider._client.headers["Authorization"] == "Bearer secret-key"
    finally:
        await provider.aclose()


async def test_several_tools_are_offered_rather_than_forced() -> None:
    """There is no portable way to force one specific tool, so the model is asked.

    The caller loops and validates, so a prose reply costs a turn instead of the run.
    """
    async with running_server() as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            await provider.complete(
                _request(
                    tools=[ToolSpec(name="get_profile", description="d", input_schema={"type": "object"})],
                    output_schema=_Answer,
                    force_output=True,
                )
            )
        finally:
            await provider.aclose()

    assert fake.last_request()["tool_choice"] == "auto"


async def test_schemas_are_reduced_to_the_portable_subset() -> None:
    """Keywords outside the subset are rejected outright by some endpoints, naming nothing.

    `maxItems` on one array was half of what made a real agent schema fail against Gemini.
    """
    async with running_server() as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        try:
            await provider.complete(_request(output_schema=_Answer, force_output=True))
        finally:
            await provider.aclose()

    schema = json.dumps(fake.last_request()["tools"][0]["function"]["parameters"])
    for keyword in ("additionalProperties", "maxItems", "minItems", "title", "default", "$ref", "anyOf"):
        assert keyword not in schema, f"{keyword} must not reach a restricted endpoint"


async def test_vendor_extras_on_a_tool_call_are_carried_back_verbatim() -> None:
    """Some endpoints attach opaque state to a tool call and reject the next turn without it.

    Gemini returns a `thought_signature` under `extra_content` and answers the follow-up with
    "Function call is missing a thought_signature in functionCall parts". Dropping it meant every
    tool-using agent failed on its second turn -- which is every tool-using agent.
    """
    signature = {"google": {"thought_signature": "opaque-blob"}}

    def with_signature(payload):
        call = tool_call("call_sig", "get_profile", {"ticker": "TST"})
        call["extra_content"] = signature
        return _completion(tool_calls=[call], finish_reason="tool_calls")

    async with running_server(with_signature) as fake:
        provider = OpenAICompatLLMProvider(_settings(fake.base_url))
        spec = ToolSpec(name="get_profile", description="d", input_schema={"type": "object"})
        try:
            first = await provider.complete(_request(tools=[spec]))
            # Exactly what an agent does next: replay the assistant turn, then the tool's result.
            await provider.complete(
                _request(
                    tools=[spec],
                    messages=[
                        ChatMessage(role="user", content="Analyse TST"),
                        ChatMessage(role="assistant", content=first.raw_content),
                        ChatMessage(
                            role="user",
                            content=[{"type": "tool_result", "tool_use_id": "call_sig", "content": "data"}],
                        ),
                    ],
                )
            )
        finally:
            await provider.aclose()

    assert first.raw_content[0]["extra_content"] == signature, "the extra must survive into the state"
    replayed = fake.last_request()["messages"][2]
    assert replayed["tool_calls"][0]["extra_content"] == signature, "and must be sent back unchanged"
