"""Financials specialist: performance, trends and ratios computed entirely by the deterministic engine.

Every numeric claim this agent emits -- in both the offline and generative paths -- carries the exact
`MetricValue.ref` that produced it, and never a figure the financial engine did not itself compute.
"""

from __future__ import annotations

from typing import Any

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.financials import FinancialMetrics, MetricValue
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

_PERFORMANCE_KEYS: tuple[str, ...] = (
    "revenue",
    "revenue_growth",
    "gross_profit",
    "operating_income",
    "net_income",
    "net_margin",
    "free_cash_flow",
    "fcf_margin",
)
_MARGIN_TREND_KEYS: tuple[str, ...] = ("gross_margin", "operating_margin", "net_margin")
_GROWTH_TREND_KEYS: tuple[str, ...] = ("revenue_cagr_3y", "revenue_cagr_5y")
_RATIO_KEYS: tuple[str, ...] = ("current_ratio", "debt_to_equity", "roa", "roe")
_MARKET_RATIO_KEYS: tuple[str, ...] = ("pe", "ev_ebitda", "ev_sales", "price_sales", "price_fcf", "fcf_yield")

_LABELS: dict[str, str] = {
    "revenue": "Revenue",
    "revenue_growth": "Revenue growth",
    "gross_profit": "Gross profit",
    "operating_income": "Operating income",
    "net_income": "Net income",
    "net_margin": "Net margin",
    "free_cash_flow": "Free cash flow",
    "fcf_margin": "FCF margin",
    "gross_margin": "Gross margin",
    "operating_margin": "Operating margin",
    "revenue_cagr_3y": "3-year revenue CAGR",
    "revenue_cagr_5y": "5-year revenue CAGR",
    "current_ratio": "Current ratio",
    "debt_to_equity": "Debt-to-equity",
    "roa": "Return on assets",
    "roe": "Return on equity",
    "pe": "P/E",
    "ev_ebitda": "EV/EBITDA",
    "ev_sales": "EV/Sales",
    "price_sales": "Price/Sales",
    "price_fcf": "Price/FCF",
    "fcf_yield": "FCF yield",
}


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


def _label(key: str) -> str:
    return _LABELS.get(key, key.replace("_", " "))


def _fmt(mv: MetricValue) -> str:
    v = mv.value
    if v is None:
        return "unavailable"
    if mv.unit == "USD":
        if abs(v) >= 1e9:
            return f"${v / 1e9:.2f}B"
        if abs(v) >= 1e6:
            return f"${v / 1e6:.1f}M"
        return f"${v:,.0f}"
    if mv.unit == "USD/share":
        return f"${v:.2f}"
    if mv.unit == "ratio":
        return f"{v:.1%}"
    if mv.unit == "x":
        return f"{v:.1f}x"
    if mv.unit == "percent":
        return f"{v:.1f}%"
    if mv.unit == "shares":
        return f"{v:,.0f}"
    return f"{v:.2f}"


def _select_periods(statements, metrics: FinancialMetrics) -> tuple[str | None, str | None, str | None, str | None]:
    annual = statements.annual
    latest = annual[-1].period.label if annual else None
    prior = annual[-2].period.label if len(annual) > 1 else None
    ttm = "TTM" if "TTM" in metrics.periods else None
    current = "current" if "current" in metrics.periods else None
    return latest, prior, ttm, current


def _offline_findings(
    agent: FinancialsAgent, metrics: FinancialMetrics, periods: tuple[str | None, str | None, str | None, str | None]
) -> list[Finding]:
    latest, prior, ttm, current = periods
    findings: list[Finding] = []

    perf_period = ttm or latest
    if perf_period:
        for key in _PERFORMANCE_KEYS:
            mv = metrics.get(perf_period, key)
            if mv is None or mv.value is None:
                continue
            findings.append(
                agent.finding(
                    f"{_label(key)} for {perf_period} is {_fmt(mv)}.",
                    FindingKind.CALCULATED,
                    ReportSection.FINANCIAL_PERFORMANCE,
                    metric_refs=[mv.ref],
                    confidence=Confidence.HIGH,
                )
            )

    if latest and prior:
        for key in _MARGIN_TREND_KEYS:
            mv_latest, mv_prior = metrics.get(latest, key), metrics.get(prior, key)
            if mv_latest and mv_latest.value is not None and mv_prior and mv_prior.value is not None:
                findings.append(
                    agent.finding(
                        f"{_label(key)} moved from {_fmt(mv_prior)} in {prior} to {_fmt(mv_latest)} in {latest}.",
                        FindingKind.CALCULATED,
                        ReportSection.FINANCIAL_TRENDS,
                        metric_refs=[mv_prior.ref, mv_latest.ref],
                        confidence=Confidence.MEDIUM,
                    )
                )
    if latest:
        for key in _GROWTH_TREND_KEYS:
            mv = metrics.get(latest, key)
            if mv is not None and mv.value is not None:
                findings.append(
                    agent.finding(
                        f"{_label(key)} is {_fmt(mv)}.",
                        FindingKind.CALCULATED,
                        ReportSection.FINANCIAL_TRENDS,
                        metric_refs=[mv.ref],
                        confidence=Confidence.MEDIUM,
                    )
                )

    if latest:
        for key in _RATIO_KEYS:
            mv = metrics.get(latest, key)
            if mv is not None and mv.value is not None:
                findings.append(
                    agent.finding(
                        f"{_label(key)} for {latest} is {_fmt(mv)}.",
                        FindingKind.CALCULATED,
                        ReportSection.KEY_RATIOS,
                        metric_refs=[mv.ref],
                        confidence=Confidence.MEDIUM,
                    )
                )
    if current:
        for key in _MARKET_RATIO_KEYS:
            mv = metrics.get(current, key)
            if mv is not None and mv.value is not None:
                findings.append(
                    agent.finding(
                        f"{_label(key)} is {_fmt(mv)}.",
                        FindingKind.CALCULATED,
                        ReportSection.KEY_RATIOS,
                        metric_refs=[mv.ref],
                        confidence=Confidence.MEDIUM,
                    )
                )
    return findings


class FinancialsAgent(BaseAgent):
    name = AgentName.FINANCIALS
    role = "Financial Analyst"
    mission = (
        "Report the company's financial performance, trends and key ratios using only figures computed by "
        "the deterministic financial engine, each cited by its exact metric reference."
    )
    allowed_tools = frozenset({"get_financial_statements", "compute_financial_metrics", "calculate_metric"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        if ticker is None:
            return AgentDraft(summary="No resolved ticker; cannot compute financial metrics.")

        inv = await self.tool(ctx, "compute_financial_metrics", ticker=ticker, years=5, include_market=True)
        if not inv.ok or inv.output is None:
            return AgentDraft(summary=f"Could not compute financial metrics for {ticker}: {inv.error}")

        metrics: FinancialMetrics = inv.output.metrics
        statements = inv.output.statements
        state_updates: dict[str, Any] = {"financials": statements, "metrics": metrics}
        periods = _select_periods(statements, metrics)

        if self.generative:
            answer = await self._run_generative(task, ctx, ticker, metrics, periods)
            findings = self.to_findings(answer)
            summary = answer.summary
        else:
            findings = _offline_findings(self, metrics, periods)
            summary = (
                f"Computed {len(metrics.values)} financial metrics for {ticker} across {len(metrics.periods)} periods."
            )

        return AgentDraft(
            summary=summary, findings=findings, data={"metric_count": len(metrics.values)}, state_updates=state_updates
        )

    async def _run_generative(
        self,
        task: ResearchTask,
        ctx: ToolContext,
        ticker: str,
        metrics: FinancialMetrics,
        periods: tuple[str | None, str | None, str | None, str | None],
    ) -> AgentAnswer:
        latest, prior, ttm, current = periods
        wanted = {p for p in (latest, prior, ttm, current) if p}
        metric_context = {
            ref: {"value": mv.value, "unit": mv.unit, "period": mv.period, "formula": mv.formula}
            for ref, mv in metrics.values.items()
            if mv.period in wanted
        }
        context = {"ticker": ticker, "objective": task.objective, "computed_metrics": metric_context}
        return await self.llm_structured(
            ctx,
            task=(
                f"Using ONLY the values in computed_metrics (trusted_context) for {ticker}, write "
                "FINANCIAL_PERFORMANCE, FINANCIAL_TRENDS and KEY_RATIOS findings. Every numeric figure you "
                "state must be one of the given metric values and must carry its exact key (the dict key, "
                "e.g. 'FY2024.gross_margin') in metric_refs. Never compute, restate with a different number, "
                "or invent any figure that is not present in computed_metrics."
            ),
            schema=AgentAnswer,
            evidence=[],
            sources={},
            context=context,
        )
