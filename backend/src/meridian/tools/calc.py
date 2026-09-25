"""Pure-calculation tools: calculate_metric, run_dcf. Thin wrappers over `financial_engine`.

Neither tool talks to a provider or absorbs evidence -- the caller (an agent) supplies the raw inputs,
typically themselves sourced from a prior `get_financial_statements`/`compute_financial_metrics` call
whose evidence ids the agent already holds. These tools exist so an agent can compute a metric the engine
did not already produce (e.g. a custom period) or run a DCF, without ever doing arithmetic itself.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.financial_engine import calculate, run_dcf
from meridian.schemas.analysis import DCFAssumptions, DCFResult
from meridian.schemas.financials import MetricValue
from meridian.tools._util import render_metric_value
from meridian.tools.base import Tool, ToolContext


class CalculateMetricInput(BaseModel):
    metric: str
    inputs: dict[str, float | None] = Field(default_factory=dict)
    period: str = "custom"


class CalculateMetricTool(Tool[CalculateMetricInput, MetricValue]):
    """Single-metric deterministic calculation (e.g. gross_margin, pe, roe) from named inputs."""

    name = "calculate_metric"
    description = (
        "Deterministically calculate one financial metric (e.g. 'gross_margin', 'pe', 'roe', "
        "'free_cash_flow') from named numeric inputs. Never invent a formula yourself -- use this tool "
        "for every ratio or derived figure not already produced by compute_financial_metrics."
    )
    input_model = CalculateMetricInput

    async def run(self, args: CalculateMetricInput, ctx: ToolContext) -> MetricValue:
        return calculate(args.metric, args.inputs, period=args.period)

    def summarize(self, output: MetricValue) -> str:
        note_str = f" ({output.note})" if output.note else ""
        return f"{output.key} {output.period} = {render_metric_value(output)}{note_str} [formula: {output.formula}]"


class RunDcfInput(BaseModel):
    assumptions: DCFAssumptions
    current_price: float | None = None


class RunDcfTool(Tool[RunDcfInput, DCFResult]):
    """Discounted cash flow valuation from explicit, agent-supplied assumptions."""

    name = "run_dcf"
    description = (
        "Run a discounted cash flow valuation from explicit assumptions (revenue growth path, FCF "
        "margin, discount rate, terminal growth, net cash, shares outstanding). Returns projected "
        "FCF, enterprise/equity value, value per share and a discount-rate x terminal-growth "
        "sensitivity grid. Every assumption must be justified in `assumptions.rationale` by the caller."
    )
    input_model = RunDcfInput

    async def run(self, args: RunDcfInput, ctx: ToolContext) -> DCFResult:
        return run_dcf(args.assumptions, args.current_price)

    def summarize(self, output: DCFResult) -> str:
        lines = [
            f"DCF value/share = {output.value_per_share:,.2f} USD "
            f"(EV={output.enterprise_value:,.0f}, equity value={output.equity_value:,.0f})"
        ]
        if output.current_price is not None:
            upside = f"{output.upside_pct * 100:.1f}%" if output.upside_pct is not None else "n/a"
            lines.append(f"current price = {output.current_price:,.2f} USD, implied upside = {upside}")
        if output.assumptions.rationale:
            lines.append("assumptions: " + "; ".join(output.assumptions.rationale))
        return "\n".join(lines)[:6000]
