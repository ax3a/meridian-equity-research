"""An `LLMProvider` for any OpenAI-compatible `/chat/completions` endpoint.

Written so the generative path is not tied to one vendor. Groq, Cerebras, Mistral, OpenRouter, GitHub
Models, Together and Google's Gemini compatibility layer all speak this protocol, and so does a local
Ollama or vLLM server -- so pointing `LLM_BASE_URL` somewhere else is the whole of "switch model".
That matters beyond convenience: a reviewer with no paid account can run the generative path against a
free endpoint or their own machine, instead of reading that it is untested.

Two translations do the real work, because this system's `LLMRequest` is shaped after Anthropic's API:

* **Messages.** `ChatMessage.content` is either a string or Anthropic-style blocks (`tool_use` on the
  assistant side, `tool_result` on the user side). OpenAI splits those: tool calls live in
  `message.tool_calls` on an assistant message, and each result is its own `role="tool"` message keyed
  by `tool_call_id`. One assistant turn with two tool calls therefore becomes one assistant message
  plus two tool messages, in order.
* **Structured output.** `output_schema` is exposed the same way the Anthropic provider does it -- as a
  `submit_answer` function the model is forced to call -- rather than via `response_format`. Support
  for `json_schema` response formats varies across these endpoints, while forced function calling is
  the one thing they all implement, and it keeps the two providers behaving identically.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from meridian.core.config import Settings
from meridian.core.errors import ProviderUnavailableError
from meridian.core.logging import get_logger
from meridian.providers.llm.base import LLMRequest, LLMResponse, LLMToolCall
from meridian.providers.llm.pricing import estimate_cost
from meridian.providers.llm.schema_tools import inline_json_schema, inline_schema_dict, portable_schema
from meridian.schemas.telemetry import LLMUsage

log = get_logger(__name__)

OUTPUT_TOOL_NAME = "submit_answer"
_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """The endpoint's own instruction on how long to wait, when it gives one."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _is_retryable(exc: BaseException) -> bool:
    """Rate limits, server faults and transport errors are worth another attempt; a 400 is not."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, httpx.TransportError)


class OpenAICompatLLMProvider:
    name = "openai_compat"
    generative = True

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        base_url = (settings.llm_base_url or "").rstrip("/")
        if not base_url:
            raise ProviderUnavailableError("openai_compat", "LLM_BASE_URL is not configured")
        self._url = f"{base_url}/chat/completions"
        key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
        headers = {"Content-Type": "application/json"}
        if key:
            # A local Ollama or vLLM needs no key, so an absent one is normal rather than an error.
            headers["Authorization"] = f"Bearer {key}"
        self._client = client or httpx.AsyncClient(
            headers=headers, timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0)
        )
        self._slots = asyncio.Semaphore(settings.llm_max_concurrency)
        self._min_interval = 60.0 / settings.llm_requests_per_minute if settings.llm_requests_per_minute else 0.0
        self._pace_lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.settings.model_for(request.tier)
        payload = self._build_payload(request, model)
        started = time.perf_counter()
        async with self._slots:
            await self._pace()
            data = await self._post_with_retry(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._to_llm_response(request, model, data, latency_ms)

    async def _pace(self) -> None:
        """Space request starts so a burst cannot outrun a per-minute quota."""
        if self._min_interval <= 0:
            return
        async with self._pace_lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval

    # ---- request building --------------------------------------------------------------------

    def _build_payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system}]
        for message in request.messages:
            messages.extend(_translate_message(message))

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }

        tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": portable_schema(inline_schema_dict(spec.input_schema)),
                },
            }
            for spec in request.tools
        ]

        if request.output_schema is not None:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": OUTPUT_TOOL_NAME,
                        "description": "Return the final answer in the required structure.",
                        "parameters": portable_schema(inline_json_schema(request.output_schema)),
                    },
                }
            )

        if tools:
            payload["tools"] = tools
            force = request.force_output or not request.tools
            only_answer = force and len(tools) == 1
            if only_answer:
                # "required" rather than naming the function: the object form
                # `{"type": "function", "function": {...}}` is valid OpenAI and rejected by Gemini, and
                # with a single tool on offer the two mean the same thing.
                payload["tool_choice"] = "required"
            else:
                # With several tools available there is no portable way to force one, so the model is
                # asked rather than made to -- the caller loops and validates, so a prose reply costs a
                # turn rather than the run.
                payload["tool_choice"] = "auto"
        return payload

    async def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        last: dict[str, Any] = {}
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(1, self.settings.llm_max_retries)),
            wait=wait_exponential_jitter(initial=0.25, max=4, jitter=0.25),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                response = await self._client.post(self._url, json=payload)
                if response.status_code == 429:
                    # A per-minute quota needs a wait measured in tens of seconds; the exponential
                    # backoff below tops out around four, which never clears one. Honour Retry-After
                    # when the endpoint sends it, and otherwise wait out the rest of the window.
                    delay = _retry_after_seconds(response) or self.settings.llm_rate_limit_backoff_seconds
                    log.warning("llm_rate_limited", url=self._url, sleeping_seconds=delay)
                    await asyncio.sleep(delay)
                if response.status_code >= 400:
                    # Endpoints differ in how they report a bad request, and the body is where the
                    # useful part is -- surface it rather than a bare status code.
                    body = response.text[:600]
                    log.warning("llm_http_error", status=response.status_code, url=self._url, body=body)
                    response.raise_for_status()
                last = response.json()
        return last

    # ---- response translation ----------------------------------------------------------------

    def _to_llm_response(self, request: LLMRequest, model: str, data: dict[str, Any], latency_ms: int) -> LLMResponse:
        choices = data.get("choices") or [{}]
        message = choices[0].get("message") or {}
        finish_reason = choices[0].get("finish_reason")

        tool_calls: list[LLMToolCall] = []
        structured: dict[str, Any] | None = None
        raw_blocks: list[dict[str, Any]] = []

        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            name = function.get("name", "")
            arguments = _parse_arguments(function.get("arguments"))
            if name == OUTPUT_TOOL_NAME:
                structured = arguments
                continue
            call_id = raw.get("id") or f"call_{len(tool_calls)}"
            tool_calls.append(LLMToolCall(id=call_id, name=name, arguments=arguments))
            block: dict[str, Any] = {"type": "tool_use", "id": call_id, "name": name, "input": arguments}
            # Carried back verbatim on the next turn, never interpreted. Gemini returns a
            # `thought_signature` here and *rejects* the follow-up request if it does not come back:
            # "Function call is missing a thought_signature in functionCall parts". Dropping it meant
            # every tool-using agent failed on its second turn, which is every tool-using agent.
            if raw.get("extra_content"):
                block["extra_content"] = raw["extra_content"]
            raw_blocks.append(block)

        text = message.get("content") or None
        if text:
            raw_blocks.insert(0, {"type": "text", "text": text})

        usage_raw = data.get("usage") or {}
        input_tokens = int(usage_raw.get("prompt_tokens", 0))
        output_tokens = int(usage_raw.get("completion_tokens", 0))
        usage = LLMUsage(
            agent=request.agent,
            provider=self.name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(model, input_tokens, output_tokens, warn_unknown=False),
            latency_ms=latency_ms,
        )
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            structured=structured,
            stop_reason=finish_reason,
            usage=usage,
            raw_content=raw_blocks,
        )


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON *string*, and not always a valid one."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # A truncated response (hit max_tokens mid-JSON) must not crash the run: the caller validates
        # against the schema and will treat empty arguments as a failed step.
        log.warning("llm_tool_arguments_unparsable", preview=str(raw)[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _translate_message(message: Any) -> list[dict[str, Any]]:
    """Turn one Anthropic-shaped message into the one or more OpenAI messages it corresponds to."""
    if isinstance(message.content, str):
        return [{"role": message.role, "content": message.content}]

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for block in message.content:
        kind = block.get("type")
        if kind == "text":
            text_parts.append(block.get("text", ""))
        elif kind == "tool_use":
            call: dict[str, Any] = {
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input") or {}),
                },
            }
            if block.get("extra_content"):
                call["extra_content"] = block["extra_content"]
            tool_calls.append(call)
        elif kind == "tool_result":
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": _stringify_result(block.get("content")),
                }
            )

    messages: list[dict[str, Any]] = []
    if message.role == "assistant" and (tool_calls or text_parts):
        assistant: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
        if tool_calls:
            assistant["tool_calls"] = tool_calls
        messages.append(assistant)
    elif text_parts and message.role != "assistant":
        messages.append({"role": message.role, "content": "\n".join(text_parts)})

    # Results follow the assistant turn that requested them, which is the order the protocol requires.
    messages.extend(tool_results)
    return messages


def _stringify_result(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return json.dumps(content) if content is not None else ""
