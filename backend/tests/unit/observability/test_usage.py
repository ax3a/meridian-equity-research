from __future__ import annotations

from meridian.observability.usage import summarize_usage
from meridian.schemas.api import UsageBreakdown
from meridian.schemas.enums import AgentName
from meridian.schemas.telemetry import LLMUsage


def _usage(agent: AgentName, model: str, input_tokens: int, output_tokens: int, cost: float) -> LLMUsage:
    return LLMUsage(
        agent=agent,
        model=model,
        provider="anthropic",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )


def test_summarize_usage_groups_by_agent_and_model() -> None:
    usage = [
        _usage(AgentName.COMPANY, "claude-sonnet-5", 100, 50, 0.001),
        _usage(AgentName.COMPANY, "claude-sonnet-5", 200, 100, 0.002),
        _usage(AgentName.CRITIC, "claude-opus-5", 300, 150, 0.01),
    ]

    breakdown, total_tokens, total_cost = summarize_usage(usage)

    assert len(breakdown) == 2
    company_row = next(b for b in breakdown if b.agent == AgentName.COMPANY)
    assert isinstance(company_row, UsageBreakdown)
    assert company_row.model == "claude-sonnet-5"
    assert company_row.calls == 2
    assert company_row.input_tokens == 300
    assert company_row.output_tokens == 150
    assert company_row.cost_usd == 0.001 + 0.002

    critic_row = next(b for b in breakdown if b.agent == AgentName.CRITIC)
    assert critic_row.calls == 1

    assert total_tokens == 100 + 50 + 200 + 100 + 300 + 150
    assert total_cost == 0.001 + 0.002 + 0.01


def test_summarize_usage_empty() -> None:
    breakdown, total_tokens, total_cost = summarize_usage([])
    assert breakdown == []
    assert total_tokens == 0
    assert total_cost == 0.0


def test_summarize_usage_same_agent_different_models_are_separate_rows() -> None:
    usage = [
        _usage(AgentName.VALUATION, "claude-sonnet-5", 10, 10, 0.001),
        _usage(AgentName.VALUATION, "claude-opus-5", 20, 20, 0.002),
    ]
    breakdown, _, _ = summarize_usage(usage)
    assert len(breakdown) == 2
    models = {b.model for b in breakdown}
    assert models == {"claude-sonnet-5", "claude-opus-5"}
