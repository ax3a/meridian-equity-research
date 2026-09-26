"""Static per-model pricing and cost estimation for Anthropic models.

Prices are USD per 1M tokens as (input_price, output_price). Unknown models cost 0.0 (with a
logged warning) rather than raising, so a new/renamed model never crashes usage accounting.
"""

from __future__ import annotations

from meridian.core.logging import get_logger

log = get_logger(__name__)

MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int, *, warn_unknown: bool = True) -> float:
    """Estimate the USD cost of a completion. Returns 0.0 for a model not in `MODEL_PRICING`.

    `warn_unknown=False` for OpenAI-compatible endpoints: their models are not in this table by
    design -- pricing varies per vendor and several are free -- so a warning on every call would be
    noise rather than news, and 0.0 is the honest figure for a free tier.
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        if warn_unknown:
            log.warning("unknown_model_pricing", model=model)
        return 0.0
    input_price, output_price = pricing
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
