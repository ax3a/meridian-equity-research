from __future__ import annotations

from meridian.providers.llm.pricing import MODEL_PRICING, estimate_cost


def test_pricing_table_matches_spec() -> None:
    assert MODEL_PRICING["claude-opus-5"] == (5.0, 25.0)
    assert MODEL_PRICING["claude-opus-4-8"] == (5.0, 25.0)
    assert MODEL_PRICING["claude-sonnet-5"] == (2.0, 10.0)
    assert MODEL_PRICING["claude-sonnet-4-6"] == (3.0, 15.0)
    assert MODEL_PRICING["claude-haiku-4-5"] == (1.0, 5.0)
    assert MODEL_PRICING["claude-fable-5-1"] == (10.0, 50.0)


def test_estimate_cost_known_model() -> None:
    # claude-sonnet-5: $2/1M input, $10/1M output
    cost = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=500_000)
    assert cost == 2.0 + 5.0


def test_estimate_cost_zero_tokens() -> None:
    assert estimate_cost("claude-opus-5", input_tokens=0, output_tokens=0) == 0.0


def test_estimate_cost_unknown_model_returns_zero(capsys) -> None:
    # Unknown models must not raise and must return 0.0; a warning is logged (structlog, best-effort check).
    cost = estimate_cost("some-made-up-model", input_tokens=1000, output_tokens=1000)
    assert cost == 0.0
    out = capsys.readouterr()
    assert "some-made-up-model" in (out.out + out.err)
