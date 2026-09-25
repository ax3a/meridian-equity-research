"""Valuation specialist: trading multiples plus an optional deterministic DCF.

Every DCF assumption is derived by this module's own code from engine-computed metrics, following the
plan's fixed rules -- never by a language model in either the generative or offline path:

- revenue growth starts at ``min(3y revenue CAGR, 0.25)`` and decays linearly to ``0.04`` by year 5
- ``fcf_margin`` is the 3-year average annual FCF margin
- ``discount_rate`` is fixed at 0.09 and ``terminal_growth`` at 0.025
- ``net_cash`` comes from the latest balance-sheet metric

The DCF only runs when the latest annual revenue and free cash flow are positive and shares outstanding
are known; otherwise it is skipped with a documented reason. In generative mode the model only narrates
figures already computed by this agent (`llm_structured`, no tool access), so it cannot invent an
assumption or a number the engine did not produce.
"""

from __future__ import annotations

import statistics
from typing import Any

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.schemas.analysis import DCFAssumptions, DCFResult, ValuationMultiple, ValuationResult
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.financials import FinancialMetrics
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

_DCF_YEARS = 5
_DISCOUNT_RATE = 0.09
_TERMINAL_GROWTH = 0.025
_GROWTH_CAP = 0.25
_TERMINAL_YEAR_GROWTH = 0.04

_MULTIPLE_SPECS: tuple[tuple[str, str], ...] = (
    ("pe", "P/E"),
    ("ev_ebitda", "EV/EBITDA"),
    ("ev_sales", "EV/Sales"),
    ("price_sales", "Price/Sales"),
    ("price_fcf", "Price/FCF"),
)


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


def _project_growth(start: float, end: float, years: int) -> list[float]:
    if years <= 1:
        return [end]
    step = (end - start) / (years - 1)
    return [start + step * i for i in range(years)]


def _three_year_avg_fcf_margin(metrics: FinancialMetrics, statements) -> tuple[float | None, list[str]]:
    labels = [p.period.label for p in statements.annual[-3:]]
    values, refs = [], []
    for label in labels:
        mv = metrics.get(label, "fcf_margin")
        if mv is not None and mv.value is not None:
            values.append(mv.value)
            refs.append(mv.ref)
    if not values:
        return None, []
    return sum(values) / len(values), refs


def _derive_dcf_assumptions(metrics: FinancialMetrics, statements) -> tuple[DCFAssumptions | None, str, list[str]]:
    """Returns (assumptions_or_None, skip_reason, metric_refs_that_fed_the_model)."""
    if not statements.annual:
        return None, "no annual statements available", []
    latest = statements.annual[-1]
    label = latest.period.label

    base_revenue = latest.revenue
    if base_revenue is None or base_revenue <= 0:
        return None, "latest annual revenue is missing or non-positive", []

    shares = latest.shares_outstanding
    if not shares:
        for q in reversed(statements.quarterly):
            if q.shares_outstanding:
                shares = q.shares_outstanding
                break
    if not shares:
        return None, "shares outstanding is unknown", []

    fcf_mv = metrics.get(label, "free_cash_flow")
    if fcf_mv is None or fcf_mv.value is None or fcf_mv.value <= 0:
        return None, "latest annual free cash flow is not positive", []

    cagr_mv = metrics.get(label, "revenue_cagr_3y")
    if cagr_mv is None or cagr_mv.value is None:
        return None, "3-year revenue CAGR is unavailable", []

    fcf_margin_avg, fcf_refs = _three_year_avg_fcf_margin(metrics, statements)
    if fcf_margin_avg is None or fcf_margin_avg <= 0:
        return None, "3-year average FCF margin is unavailable or non-positive", []

    net_cash_mv = metrics.get(label, "net_cash")
    net_cash = net_cash_mv.value if net_cash_mv and net_cash_mv.value is not None else 0.0

    start_growth = min(cagr_mv.value, _GROWTH_CAP)
    growth_path = _project_growth(start_growth, _TERMINAL_YEAR_GROWTH, _DCF_YEARS)

    metric_refs_used = [cagr_mv.ref, *fcf_refs, fcf_mv.ref]
    if net_cash_mv is not None:
        metric_refs_used.append(net_cash_mv.ref)

    rationale = [
        f"Revenue growth starts at {start_growth:.1%} = min(3y revenue CAGR {cagr_mv.value:.1%} [{cagr_mv.ref}], "
        f"{_GROWTH_CAP:.0%} cap), decaying linearly to {_TERMINAL_YEAR_GROWTH:.1%} by year {_DCF_YEARS} "
        f"[{cagr_mv.ref}].",
        f"FCF margin held flat at {fcf_margin_avg:.1%}, the average of the last {len(fcf_refs)} annual FCF "
        f"margins [{', '.join(fcf_refs)}].",
        f"Discount rate fixed at {_DISCOUNT_RATE:.1%} (policy assumption, not derived from market data).",
        f"Terminal growth fixed at {_TERMINAL_GROWTH:.1%} (long-run nominal GDP proxy).",
        f"Net cash of {net_cash:,.0f} taken from {net_cash_mv.ref if net_cash_mv else 'unavailable (assumed zero)'}.",
        f"Base revenue of {base_revenue:,.0f} [{label}.revenue] and {shares:,.0f} diluted shares taken from "
        f"the {label} statements.",
    ]
    assumptions = DCFAssumptions(
        base_revenue=base_revenue,
        revenue_growth=growth_path,
        fcf_margin=fcf_margin_avg,
        discount_rate=_DISCOUNT_RATE,
        terminal_growth=_TERMINAL_GROWTH,
        net_cash=net_cash,
        shares_outstanding=shares,
        rationale=rationale,
    )
    return assumptions, "", metric_refs_used


def _build_multiples(metrics: FinancialMetrics, peers) -> list[ValuationMultiple]:
    out: list[ValuationMultiple] = []
    peer_rows = [p for p in (peers.peers if peers else []) if not p.is_target]
    for key, label in _MULTIPLE_SPECS:
        mv = metrics.get("current", key)
        if mv is None:
            continue
        peer_median = None
        if key == "pe":
            values = [p.pe for p in peer_rows if p.pe is not None]
            peer_median = statistics.median(values) if values else None
        elif key == "ev_sales":
            values = [p.ev_sales for p in peer_rows if p.ev_sales is not None]
            peer_median = statistics.median(values) if values else None
        out.append(
            ValuationMultiple(
                name=key, label=label, value=mv.value, peer_median=peer_median, basis=mv.formula, note=mv.note
            )
        )
    return out


def _offline_findings(
    agent: ValuationAgent,
    ticker: str,
    multiples: list[ValuationMultiple],
    dcf_result: DCFResult | None,
    dcf_metric_refs: list[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for m in multiples:
        if m.value is None:
            continue
        claim = f"{ticker} trades at {m.value:.1f}x {m.label}."
        if m.peer_median is not None:
            claim += f" Peer median is {m.peer_median:.1f}x."
        findings.append(
            agent.finding(
                claim,
                FindingKind.CALCULATED,
                ReportSection.VALUATION,
                metric_refs=[f"current.{m.name}"],
                confidence=Confidence.MEDIUM,
            )
        )

    if dcf_result is not None:
        upside = dcf_result.upside_pct
        upside_txt = ""
        if upside is not None:
            direction = "upside" if upside >= 0 else "downside"
            upside_txt = f" ({abs(upside):.1%} {direction} vs. the current price)"
        findings.append(
            agent.finding(
                f"A base-case discounted cash flow model implies a fair value of ${dcf_result.value_per_share:,.2f} "
                f"per share{upside_txt}; every assumption and its rationale is recorded in the methodology notes.",
                FindingKind.INTERPRETATION,
                ReportSection.VALUATION,
                metric_refs=dcf_metric_refs,
                confidence=Confidence.MEDIUM,
            )
        )
    return findings


class ValuationAgent(BaseAgent):
    name = AgentName.VALUATION
    role = "Valuation Analyst"
    mission = (
        "Value the company using trading multiples against its peers and, when the data supports it, a "
        "discounted cash flow model whose assumptions are always derived deterministically from computed "
        "financial metrics -- never invented by a language model."
    )
    allowed_tools = frozenset(
        {"get_market_quote", "compute_financial_metrics", "calculate_metric", "run_dcf", "get_peer_snapshot"}
    )

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        if ticker is None:
            return AgentDraft(summary="No resolved ticker; cannot value the company.")

        metrics_inv = await self.tool(ctx, "compute_financial_metrics", ticker=ticker, years=5, include_market=True)
        if not metrics_inv.ok or metrics_inv.output is None:
            return AgentDraft(summary=f"Could not compute metrics for {ticker}: {metrics_inv.error}")
        metrics: FinancialMetrics = metrics_inv.output.metrics
        statements = metrics_inv.output.statements
        quote = metrics_inv.output.quote

        if quote is None:
            quote_inv = await self.tool(ctx, "get_market_quote", ticker=ticker, history_days=365)
            quote = quote_inv.output.quote if quote_inv.ok and quote_inv.output else None

        multiples = _build_multiples(metrics, state.peers)

        dcf_result: DCFResult | None = None
        assumptions, skip_reason, dcf_metric_refs = _derive_dcf_assumptions(metrics, statements)
        methodology_notes: list[str] = []
        if assumptions is not None:
            dcf_inv = await self.tool(
                ctx, "run_dcf", assumptions=assumptions, current_price=quote.price if quote else None
            )
            if dcf_inv.ok and dcf_inv.output is not None:
                dcf_result = dcf_inv.output
                methodology_notes.extend(assumptions.rationale)
            else:
                methodology_notes.append(f"DCF skipped: run_dcf failed ({dcf_inv.error}).")
                dcf_metric_refs = []
        else:
            methodology_notes.append(f"DCF skipped: {skip_reason}.")

        market_cap_mv = metrics.get("current", "market_cap")
        ev_mv = metrics.get("current", "enterprise_value")
        valuation = ValuationResult(
            ticker=ticker,
            price=quote.price if quote else None,
            price_as_of=quote.as_of.isoformat() if quote else None,
            market_cap=market_cap_mv.value if market_cap_mv else None,
            enterprise_value=ev_mv.value if ev_mv else None,
            multiples=multiples,
            dcf=dcf_result,
            methodology_notes=methodology_notes,
        )
        # Also publish metrics defensively: valuation must validate its own CALCULATED findings against
        # known metric refs even if it runs before/without the financials agent in this session.
        state_updates: dict[str, Any] = {"valuation": valuation, "metrics": metrics, "financials": statements}

        if self.generative:
            answer = await self._run_generative(task, ctx, ticker, multiples, dcf_result, methodology_notes)
            findings = self.to_findings(answer)
            summary = answer.summary
        else:
            findings = _offline_findings(self, ticker, multiples, dcf_result, dcf_metric_refs)
            summary = f"Valued {ticker} using {len(multiples)} multiples" + (
                " and a DCF model." if dcf_result else "; DCF skipped (see methodology notes)."
            )

        return AgentDraft(
            summary=summary,
            findings=findings,
            data={"multiples": len(multiples), "dcf_ran": dcf_result is not None},
            state_updates=state_updates,
        )

    async def _run_generative(
        self,
        task: ResearchTask,
        ctx: ToolContext,
        ticker: str,
        multiples: list[ValuationMultiple],
        dcf_result: DCFResult | None,
        methodology_notes: list[str],
    ) -> AgentAnswer:
        context = {
            "ticker": ticker,
            "multiples": [m.model_dump() for m in multiples],
            "dcf": dcf_result.model_dump() if dcf_result else None,
            "methodology_notes": methodology_notes,
            "note": (
                "All figures above were computed deterministically by the platform, not by you. Cite a "
                "multiple via metric_refs=['current.<name>'] (e.g. 'current.pe'). The DCF value itself has no "
                "metric ref -- if you mention it, treat it as interpretation grounded in the metric refs named "
                "inside methodology_notes."
            ),
        }
        return await self.llm_structured(
            ctx,
            task=(
                f"Write VALUATION section findings for {ticker} using ONLY the multiples and DCF result given "
                "in trusted_context. Do not compute, restate with a different number, or invent any multiple, "
                "discount rate, growth assumption or per-share value."
            ),
            schema=AgentAnswer,
            evidence=[],
            sources={},
            context=context,
        )
