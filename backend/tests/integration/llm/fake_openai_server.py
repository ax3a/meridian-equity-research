"""A real HTTP server that speaks the OpenAI chat-completions protocol.

Deliberately not another scripted `LLMProvider`. A scripted fake replaces the provider, so it proves
the *callers* behave -- it cannot catch a provider that builds a malformed request body, mistranslates
Anthropic-style tool blocks, or misreads a response. Those are exactly the failures that only appear
against a real endpoint, and this project has been bitten twice by mocks that agreed with the code
while reality did not.

So this serves the wire protocol over HTTP and records every request body it receives, which lets a
test assert on what actually went over the network: message roles and ordering, `tools`/`tool_choice`,
and that each `tool_result` came back as a `role="tool"` message carrying the right `tool_call_id`.

It behaves like a small model: if the request offers tools it calls one, then answers on the next turn
once it sees the results.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request


class FakeOpenAIServer:
    """Runs on a real port; `requests` holds every payload it was sent."""

    def __init__(self, responder: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responder = responder or default_responder
        self.app = FastAPI()
        self._server: uvicorn.Server | None = None
        self.port = 0

        @self.app.post("/v1/chat/completions")
        async def chat_completions(request: Request) -> dict[str, Any]:
            payload = await request.json()
            self.requests.append(payload)
            return self._responder(payload)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def last_request(self) -> dict[str, Any]:
        return self.requests[-1]


def _completion(
    *,
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 120,
    completion_tokens: int = 40,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Note `arguments` is a JSON *string*, as the protocol specifies -- not an object."""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def default_responder(payload: dict[str, Any]) -> dict[str, Any]:
    """Call a tool on the first turn, then submit an answer once results come back."""
    tools = payload.get("tools") or []
    names = [t["function"]["name"] for t in tools]
    already_called = any(m.get("role") == "tool" for m in payload.get("messages", []))
    callable_tools = [n for n in names if n != "submit_answer"]

    if callable_tools and not already_called:
        return _completion(
            tool_calls=[tool_call("call_1", callable_tools[0], {"ticker": "TST"})], finish_reason="tool_calls"
        )
    if "submit_answer" in names:
        return _completion(
            tool_calls=[tool_call("call_2", "submit_answer", {"summary": "ok", "findings": []})],
            finish_reason="tool_calls",
        )
    return _completion(content="plain text answer")


@asynccontextmanager
async def running_server(
    responder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> AsyncIterator[FakeOpenAIServer]:
    """Start the server on an ephemeral port and shut it down afterwards."""
    import asyncio
    import socket

    fake = FakeOpenAIServer(responder)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        fake.port = probe.getsockname()[1]

    config = uvicorn.Config(fake.app, host="127.0.0.1", port=fake.port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.02)
        yield fake
    finally:
        server.should_exit = True
        await task


def minimal_instance(schema: dict[str, Any]) -> Any:
    """Build the smallest value satisfying a JSON schema.

    Lets the fake answer *any* agent, rather than one canned shape per agent: it reads the schema the
    provider actually sent and returns something that validates against it. That is what makes a whole
    13-agent generative run possible without a real model, and it exercises `inline_json_schema` too --
    an unresolved `$ref` here would surface immediately as an unsatisfiable schema.
    """
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for combinator in ("anyOf", "oneOf", "allOf"):
        if schema.get(combinator):
            # Prefer a non-null branch so required fields get a usable value.
            options = [o for o in schema[combinator] if o.get("type") != "null"] or schema[combinator]
            return minimal_instance(options[0])

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")

    if kind == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        return {name: minimal_instance(properties[name]) for name in schema.get("required", []) if name in properties}
    if kind == "array":
        return []
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return "generated by the fake model"


def schema_aware_responder(payload: dict[str, Any]) -> dict[str, Any]:
    """Answer immediately with a schema-valid `submit_answer`, calling no tools.

    Skipping the tool loop keeps a full-run test to one call per agent: the tool layer already has its
    own coverage, and what is untested here is that every agent's *generative* branch runs end to end.
    """
    tools = {t["function"]["name"]: t["function"] for t in payload.get("tools") or []}
    answer = tools.get("submit_answer")
    if answer is None:
        return _completion(content="No structured output was requested.")
    return _completion(
        tool_calls=[tool_call("call_answer", "submit_answer", minimal_instance(answer["parameters"]))],
        finish_reason="tool_calls",
    )
