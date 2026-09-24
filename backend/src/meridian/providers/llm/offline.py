"""The deterministic offline LLM "provider": always unavailable for generation.

Used when no Anthropic API key is configured (`settings.llm_mode == "offline"`). Agents check
`llm.generative` before attempting a generative path and fall back to their deterministic,
evidence-driven synthesis instead of calling `complete()` at all — this class exists mainly so the
provider registry always has a uniform `LLMProvider` to hand out, and so a stray generative call
fails loudly rather than silently.
"""

from __future__ import annotations

from meridian.core.errors import ProviderUnavailableError
from meridian.providers.llm.base import LLMRequest, LLMResponse


class OfflineLLMProvider:
    name = "offline"
    generative = False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise ProviderUnavailableError(
            "offline",
            "The offline LLM provider cannot generate completions (no Anthropic API key configured). "
            "Agents must check `generative` and use their deterministic synthesis path instead.",
        )
