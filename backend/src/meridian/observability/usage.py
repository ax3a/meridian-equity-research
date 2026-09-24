"""Summarise raw per-call `LLMUsage` records into the per-agent/model rows shown in the UI."""

from __future__ import annotations

from meridian.schemas.api import UsageBreakdown
from meridian.schemas.telemetry import LLMUsage


def summarize_usage(usage: list[LLMUsage]) -> tuple[list[UsageBreakdown], int, float]:
    """Group usage records by (agent, model) and total tokens/cost across all of them.

    Returns `(breakdown_rows, total_tokens, total_cost_usd)`. Row order follows first appearance.
    """
    grouped: dict[tuple[str, str], UsageBreakdown] = {}
    total_tokens = 0
    total_cost = 0.0
    for record in usage:
        key = (str(record.agent), record.model)
        row = grouped.get(key)
        if row is None:
            row = UsageBreakdown(
                agent=str(record.agent), model=record.model, calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0
            )
            grouped[key] = row
        row.calls += 1
        row.input_tokens += record.input_tokens
        row.output_tokens += record.output_tokens
        row.cost_usd += record.cost_usd
        total_tokens += record.input_tokens + record.output_tokens
        total_cost += record.cost_usd
    return list(grouped.values()), total_tokens, total_cost
