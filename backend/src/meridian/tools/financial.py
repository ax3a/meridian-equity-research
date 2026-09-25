"""Financial statement and metrics tools: get_financial_statements, compute_financial_metrics.

`compute_financial_metrics` is the tool the WHY-THIS-MATTERS note in the task brief is about: its
`summarize()` renders every reported metric with its evidence id inline (e.g.
``revenue FY2024 = 245,122,000,000 USD [ev_ab12]``) so a generative agent can only cite evidence it has
actually seen in a tool result.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.core.errors import MeridianError
from meridian.financial_engine import compute_metrics
from meridian.schemas.financials import FinancialMetrics, FinancialStatements, Quote
from meridian.tools._util import fmt_num, metric_evidence_ids, render_metric_value, resolve_identity_with_profile
from meridian.tools.base import Tool, ToolContext


class GetFinancialStatementsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    years: int = Field(default=5, ge=1, le=15)


class GetFinancialStatementsOutput(BaseModel):
    statements: FinancialStatements
    evidence_ids: list[str]
    is_snapshot: bool


class GetFinancialStatementsTool(Tool[GetFinancialStatementsInput, GetFinancialStatementsOutput]):
    """Multi-year annual + quarterly financial statements, with per-line-item evidence."""

    name = "get_financial_statements"
    description = (
        "Fetch multi-year annual and quarterly financial statements (revenue, margins, cash flow, "
        "balance sheet) for a company, with per-line-item source evidence. Never computes ratios -- "
        "use compute_financial_metrics for that."
    )
    input_model = GetFinancialStatementsInput

    async def run(self, args: GetFinancialStatementsInput, ctx: ToolContext) -> GetFinancialStatementsOutput:
        identity = await ctx.providers.directory.resolve(args.ticker)
        result = await ctx.providers.fundamentals.get_statements(identity, args.years)
        ctx.ledger.absorb(result)
        evidence_ids = sorted(
            {eid for pf in (*result.data.annual, *result.data.quarterly) for eid in pf.evidence_ids.values()}
        )
        return GetFinancialStatementsOutput(
            statements=result.data, evidence_ids=evidence_ids, is_snapshot=result.is_snapshot
        )

    def summarize(self, output: GetFinancialStatementsOutput) -> str:
        st = output.statements
        snap = " [snapshot data]" if output.is_snapshot else ""
        lines = [f"{st.ticker}: {len(st.annual)} annual period(s), {len(st.quarterly)} quarterly period(s){snap}"]
        latest = st.latest_annual()
        if latest is not None:
            for field in ("revenue", "gross_profit", "operating_income", "net_income", "operating_cash_flow", "capex"):
                value = latest.value(field)
                eid = latest.evidence_ids.get(field)
                eid_str = f" [{eid}]" if eid else ""
                lines.append(f"{field} {latest.period.label} = {fmt_num(value)} USD{eid_str}")
        return "\n".join(lines)[:6000]


class ComputeFinancialMetricsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    years: int = Field(default=5, ge=1, le=15)
    include_market: bool = True


class ComputeFinancialMetricsOutput(BaseModel):
    metrics: FinancialMetrics
    statements: FinancialStatements
    quote: Quote | None = None
    evidence_ids: list[str]


class ComputeFinancialMetricsTool(Tool[ComputeFinancialMetricsInput, ComputeFinancialMetricsOutput]):
    """Every deterministic financial-engine metric (margins, growth, leverage, valuation multiples)."""

    name = "compute_financial_metrics"
    description = (
        "Compute every deterministic financial metric (margins, growth rates, leverage ratios, "
        "valuation multiples, DCF-ready inputs) for a company from its financial statements and "
        "(optionally) current market quote. Skips gross margin and EV multiples for banks/insurers. "
        "This is the only source of truth for calculated ratios -- never restate a number it did not produce."
    )
    input_model = ComputeFinancialMetricsInput

    async def run(self, args: ComputeFinancialMetricsInput, ctx: ToolContext) -> ComputeFinancialMetricsOutput:
        identity = await resolve_identity_with_profile(ctx, args.ticker)
        stmt_result = await ctx.providers.fundamentals.get_statements(identity, args.years)
        ctx.ledger.absorb(stmt_result)
        statements = stmt_result.data

        evidence_ids = {eid for pf in (*statements.annual, *statements.quarterly) for eid in pf.evidence_ids.values()}

        quote: Quote | None = None
        if args.include_market:
            try:
                quote_result = await ctx.providers.market.get_quote(identity.ticker)
            except MeridianError:
                quote = None
            else:
                ctx.ledger.absorb(quote_result)
                quote = quote_result.data
                evidence_ids.update(e.id for e in quote_result.evidence)

        metrics = compute_metrics(statements, quote, is_financial_institution=identity.is_financial_institution)
        return ComputeFinancialMetricsOutput(
            metrics=metrics, statements=statements, quote=quote, evidence_ids=sorted(evidence_ids)
        )

    def summarize(self, output: ComputeFinancialMetricsOutput) -> str:
        lines: list[str] = []
        if output.quote is not None:
            lines.append(
                f"quote: {output.quote.ticker} = {fmt_num(output.quote.price, decimals=2)} "
                f"{output.quote.currency} as of {output.quote.as_of}"
            )

        periods: list[str] = []
        latest = output.statements.latest_annual()
        if latest is not None:
            periods.append(latest.period.label)
        if "TTM" in output.metrics.periods:
            periods.append("TTM")
        if "current" in output.metrics.periods:
            periods.append("current")

        for period in periods:
            period_metrics = sorted(
                (mv for mv in output.metrics.values.values() if mv.period == period), key=lambda mv: mv.key
            )
            for mv in period_metrics:
                eids = metric_evidence_ids(mv, output.statements)
                eid_str = f" [{', '.join(eids)}]" if eids else ""
                note_str = f" ({mv.note})" if mv.note else ""
                lines.append(f"{mv.key} {period} = {render_metric_value(mv)}{eid_str}{note_str}")
        return "\n".join(lines)[:6000]
