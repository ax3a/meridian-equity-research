"""The real Anthropic-backed `LLMProvider`.

Everything that touches the Anthropic SDK's request/response shapes lives here so the rest of the
codebase (agents, graph, API) never sees SDK types — it only ever sees `LLMRequest`/`LLMResponse`.

Two request shapes, chosen per `LLMRequest`:

- **Structured output** (`request.force_output` is True, or `request.tools` is empty): the model is
  asked for JSON directly via `output_config.format = {"type": "json_schema", "schema": ...}`. No
  `tools` are sent at all. The response's single text block is parsed as JSON into `structured`.
- **Tool loop** (otherwise): `request.tools` are sent as strict Anthropic tools (schemas inlined,
  `strict: true`), plus a synthesized `submit_answer` tool built from `request.output_schema`, with
  `tool_choice={"type": "auto"}`. Every `tool_use` block becomes an `LLMToolCall`; if one of them is
  `submit_answer`, its input also becomes `structured`.

Neither path ever sends `temperature`, `top_p`, `top_k`, or `thinking` — these models reject all of
them with a 400. Reasoning depth is controlled solely via `output_config.effort`.

On Opus-tier tiers (planner/critic/writer) with `settings.llm_refusal_fallbacks` enabled, requests go
through `client.beta.messages.create` with server-side refusal fallbacks (`fallbacks="default"`, beta
header `server-side-fallback-2026-07-01`). Any response whose final `stop_reason` is `"refusal"` (the
whole fallback chain declined) raises `LLMOutputError` carrying `stop_details.category`.

Retries (`RateLimitError`, `APIConnectionError`, `APITimeoutError`, `InternalServerError`, and any
`APIStatusError` with `status_code >= 500`) are driven by tenacity with exponential backoff and jitter,
`settings.llm_max_retries` attempts; the SDK client itself is built with `max_retries=0` so tenacity is
the single source of retry behaviour. A final exhausted retry (or any other Anthropic SDK error) is
wrapped in `ProviderError` so the rest of the app only ever has to handle `MeridianError` subclasses.
"""

from __future__ import annotations

import json
import time
from typing import Any

import anthropic
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from meridian.core.config import Settings
from meridian.core.errors import LLMOutputError, ProviderError
from meridian.core.logging import get_logger
from meridian.providers.llm.base import ChatMessage, LLMRequest, LLMResponse, LLMToolCall, ToolSpec
from meridian.providers.llm.pricing import estimate_cost
from meridian.providers.llm.schema_tools import inline_json_schema, inline_schema_dict
from meridian.schemas.telemetry import LLMUsage

log = get_logger(__name__)

_REFUSAL_FALLBACK_TIERS = frozenset({"planner", "critic", "writer"})
_REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_RETRYABLE_EXCEPTIONS = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE_EXCEPTIONS):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False


class AnthropicLLMProvider:
    name = "anthropic"
    generative = True

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client if client is not None else self._build_client(settings)

    @staticmethod
    def _build_client(settings: Settings) -> anthropic.AsyncAnthropic:
        api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        return anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.settings.model_for(request.tier)
        kwargs = self._build_kwargs(request, model)
        use_fallbacks = self.settings.llm_refusal_fallbacks and request.tier in _REFUSAL_FALLBACK_TIERS
        create_fn = self._client.beta.messages.create if use_fallbacks else self._client.messages.create
        if use_fallbacks:
            kwargs = {**kwargs, "betas": [_REFUSAL_FALLBACK_BETA], "fallbacks": "default"}

        t0 = time.perf_counter()
        try:
            response = await self._call_with_retry(create_fn, kwargs)
        except Exception as exc:
            log.warning("anthropic_call_failed", agent=str(request.agent), model=model, error=str(exc))
            raise ProviderError("anthropic", str(exc)) from exc
        latency_ms = (time.perf_counter() - t0) * 1000

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            explanation = getattr(response.stop_details, "explanation", None) if response.stop_details else None
            raise LLMOutputError(
                f"{request.agent}: Anthropic refused to answer (category={category})",
                details={"category": category, "explanation": explanation},
            )

        return self._to_llm_response(request, model, response, latency_ms)

    async def _call_with_retry(self, create_fn: Any, kwargs: dict[str, Any]) -> Any:
        last_response: Any = None

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(1, self.settings.llm_max_retries)),
            wait=wait_exponential_jitter(initial=0.25, max=4, jitter=0.25),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                last_response = await create_fn(**kwargs)
        return last_response

    # ---- request building --------------------------------------------------------------------

    def _build_kwargs(self, request: LLMRequest, model: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [self._message_dict(m) for m in request.messages],
            "output_config": {"effort": self.settings.effort_for(request.tier)},
        }
        # No temperature/top_p/top_k/thinking: these models reject all of them (400). Thinking stays
        # at its adaptive default by simply never being mentioned.
        structured_only = request.force_output or not request.tools
        if structured_only:
            if request.output_schema is not None:
                kwargs["output_config"]["format"] = {
                    "type": "json_schema",
                    "schema": inline_json_schema(request.output_schema),
                }
            return kwargs

        tools = [self._tool_dict(spec) for spec in request.tools]
        if request.output_schema is not None:
            tools.append(self._submit_answer_tool(request.output_schema))
        kwargs["tools"] = tools
        kwargs["tool_choice"] = {"type": "auto"}
        return kwargs

    @staticmethod
    def _message_dict(message: ChatMessage) -> dict[str, Any]:
        return {"role": message.role, "content": message.content}

    @staticmethod
    def _tool_dict(spec: ToolSpec) -> dict[str, Any]:
        return {
            "name": spec.name,
            "description": spec.description,
            "strict": True,
            "input_schema": inline_schema_dict(spec.input_schema),
        }

    @staticmethod
    def _submit_answer_tool(output_schema: type[Any]) -> dict[str, Any]:
        return {
            "name": "submit_answer",
            "description": "Submit your final structured answer for this task.",
            "strict": True,
            "input_schema": inline_json_schema(output_schema),
        }

    # ---- response parsing ---------------------------------------------------------------------

    def _to_llm_response(self, request: LLMRequest, model: str, response: Any, latency_ms: float) -> LLMResponse:
        raw_content = [self._block_to_dict(block) for block in response.content]
        text = next((block.text for block in response.content if getattr(block, "type", None) == "text"), None)

        tool_calls = [
            LLMToolCall(id=block.id, name=block.name, arguments=dict(block.input))
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
        ]

        structured: dict[str, Any] | None = None
        structured_only = request.force_output or not request.tools
        if structured_only:
            if text is not None:
                try:
                    structured = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise LLMOutputError(
                        f"{request.agent}: Anthropic structured-output response was not valid JSON"
                    ) from exc
        else:
            submit_call = next((c for c in tool_calls if c.name == "submit_answer"), None)
            if submit_call is not None:
                structured = submit_call.arguments

        usage = LLMUsage(
            agent=request.agent,
            model=model,
            provider=self.name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=estimate_cost(model, response.usage.input_tokens, response.usage.output_tokens),
            latency_ms=latency_ms,
        )

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            structured=structured,
            stop_reason=response.stop_reason,
            usage=usage,
            raw_content=raw_content,
        )

    @staticmethod
    def _block_to_dict(block: Any) -> dict[str, Any]:
        # Null fields are dropped: replayed assistant blocks must not carry nulls the API would reject.
        if hasattr(block, "model_dump"):
            raw = dict(block.model_dump())
        elif isinstance(block, dict):
            raw = dict(block)
        else:
            raw = dict(vars(block))
        return {k: v for k, v in raw.items() if v is not None}
