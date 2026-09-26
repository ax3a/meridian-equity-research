"""Orchestrates the per-metric calculations into the two public entry points:

``compute_metrics`` walks a full :class:`FinancialStatements` (all annual periods, a synthesised
TTM period when 4+ consecutive quarters exist, and market/valuation metrics for the current
period when a :class:`Quote` is supplied) and returns a populated :class:`FinancialMetrics`.

``calculate`` is the single-metric dispatcher used by the ``calculate_metric`` tool: given a
metric key and a flat dict of named inputs, it looks up the same underlying calculation used by
``compute_metrics`` and wraps it into one :class:`MetricValue`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import pairwise

from meridian.core.errors import ValidationFailedError
from meridian.financial_engine.balance import (
    cash_and_investments,
    current_ratio,
    debt_to_equity,
    net_cash,
    roa,
    roe,
    total_debt,
)
from meridian.financial_engine.cashflow import ebitda, free_cash_flow
from meridian.financial_engine.growth import cagr, yoy_growth
from meridian.financial_engine.margins import (
    ebitda_margin,
    fcf_margin,
    gross_margin,
    net_margin,
    operating_margin,
    rd_intensity,
)
from meridian.financial_engine.multiples import (
    earnings_yield,
    enterprise_value,
    ev_ebitda,
    ev_sales,
    fcf_yield,
    market_cap,
    pe,
    price_fcf,
    price_sales,
)
from meridian.financial_engine.safe import Calc, safe_add
from meridian.schemas.financials import (
    FinancialMetrics,
    FinancialStatements,
    MetricUnit,
    MetricValue,
    PeriodFinancials,
    Quote,
)

_NOT_MEANINGFUL_BANK_NOTE = "not meaningful for financial institutions"

# Consecutive-quarter gap window, matching the ~80-100 day 10-Q duration convention used by the
# SEC EDGAR provider (Task 2) to identify quarterly facts.
_MIN_QUARTER_GAP_DAYS = 60
_MAX_QUARTER_GAP_DAYS = 100

_FLOW_FIELDS: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capex",
    "research_and_development",
    "depreciation_amortization",
)


def _mv(key: str, period: str, unit: MetricUnit, calc: Calc) -> MetricValue:
    return MetricValue(
        key=key, period=period, value=calc.value, unit=unit, formula=calc.formula, inputs=calc.inputs, note=calc.note
    )


def _mv_with_basis(key: str, period: str, unit: MetricUnit, calc: Calc, basis_label: str) -> MetricValue:
    formula = f"{calc.formula} [basis: {basis_label}]"
    return MetricValue(
        key=key, period=period, value=calc.value, unit=unit, formula=formula, inputs=calc.inputs, note=calc.note
    )


def _not_meaningful_for_bank(
    key: str, period: str, unit: MetricUnit, inputs: dict[str, float | None], formula: str
) -> MetricValue:
    return MetricValue(
        key=key, period=period, value=None, unit=unit, formula=formula, inputs=inputs, note=_NOT_MEANINGFUL_BANK_NOTE
    )


def _passthrough(key: str, period: str, unit: MetricUnit, value: float | None, field_name: str) -> MetricValue:
    note = None if value is not None else f"insufficient data: {field_name} not reported for {period}"
    return MetricValue(
        key=key,
        period=period,
        value=value,
        unit=unit,
        formula=f"reported {field_name}",
        inputs={field_name: value},
        note=note,
    )


def _flow_metrics(
    period_label: str,
    *,
    revenue: float | None,
    prior_revenue: float | None,
    gross_profit: float | None,
    operating_income: float | None,
    net_income: float | None,
    eps_diluted: float | None,
    prior_eps_diluted: float | None,
    operating_cash_flow: float | None,
    capex: float | None,
    research_and_development: float | None,
    depreciation_amortization: float | None,
    is_financial_institution: bool,
) -> list[MetricValue]:
    out: list[MetricValue] = []

    out.append(_passthrough("revenue", period_label, "USD", revenue, "revenue"))
    out.append(_mv("revenue_growth", period_label, "ratio", yoy_growth(revenue, prior_revenue, label="revenue")))

    out.append(_passthrough("gross_profit", period_label, "USD", gross_profit, "gross_profit"))
    if is_financial_institution:
        gm_inputs = {"gross_profit": gross_profit, "revenue": revenue}
        out.append(_not_meaningful_for_bank("gross_margin", period_label, "ratio", gm_inputs, "gross_profit / revenue"))
    else:
        out.append(_mv("gross_margin", period_label, "ratio", gross_margin(gross_profit, revenue)))

    out.append(_passthrough("operating_income", period_label, "USD", operating_income, "operating_income"))
    out.append(_mv("operating_margin", period_label, "ratio", operating_margin(operating_income, revenue)))

    out.append(_passthrough("net_income", period_label, "USD", net_income, "net_income"))
    out.append(_mv("net_margin", period_label, "ratio", net_margin(net_income, revenue)))

    out.append(_passthrough("eps_diluted", period_label, "USD/share", eps_diluted, "eps_diluted"))
    eps_growth_calc = yoy_growth(eps_diluted, prior_eps_diluted, label="eps_diluted")
    out.append(_mv("eps_growth", period_label, "ratio", eps_growth_calc))

    out.append(_passthrough("operating_cash_flow", period_label, "USD", operating_cash_flow, "operating_cash_flow"))
    out.append(_passthrough("capex", period_label, "USD", capex, "capex"))

    fcf_calc = free_cash_flow(operating_cash_flow, capex)
    out.append(_mv("free_cash_flow", period_label, "USD", fcf_calc))
    out.append(_mv("fcf_margin", period_label, "ratio", fcf_margin(fcf_calc.value, revenue)))
    out.append(_mv("rd_intensity", period_label, "ratio", rd_intensity(research_and_development, revenue)))

    ebitda_calc = ebitda(operating_income, depreciation_amortization)
    out.append(_mv("ebitda", period_label, "USD", ebitda_calc))
    out.append(_mv("ebitda_margin", period_label, "ratio", ebitda_margin(ebitda_calc.value, revenue)))

    return out


def _balance_metrics(period_label: str, pf: PeriodFinancials, prior: PeriodFinancials | None) -> list[MetricValue]:
    out: list[MetricValue] = []
    out.append(_passthrough("total_assets", period_label, "USD", pf.total_assets, "total_assets"))
    out.append(_passthrough("total_liabilities", period_label, "USD", pf.total_liabilities, "total_liabilities"))
    out.append(_passthrough("shareholders_equity", period_label, "USD", pf.shareholders_equity, "shareholders_equity"))

    cai = cash_and_investments(pf.cash_and_equivalents, pf.short_term_investments)
    out.append(_mv("cash_and_investments", period_label, "USD", cai))

    td = total_debt(pf.long_term_debt, pf.current_debt)
    out.append(_mv("total_debt", period_label, "USD", td))

    nc = net_cash(pf.cash_and_equivalents, pf.short_term_investments, td.value)
    out.append(_mv("net_cash", period_label, "USD", nc))

    out.append(_mv("current_ratio", period_label, "ratio", current_ratio(pf.current_assets, pf.current_liabilities)))
    out.append(_mv("debt_to_equity", period_label, "ratio", debt_to_equity(td.value, pf.shareholders_equity)))

    prior_assets = prior.value("total_assets") if prior else None
    prior_equity = prior.value("shareholders_equity") if prior else None
    out.append(_mv("roa", period_label, "ratio", roa(pf.net_income, pf.total_assets, prior_assets)))
    out.append(_mv("roe", period_label, "ratio", roe(pf.net_income, pf.shareholders_equity, prior_equity)))

    return out


def _emit_revenue_cagr(metrics: FinancialMetrics, annual: list[PeriodFinancials], years: int) -> None:
    latest = annual[-1]
    start = annual[-1 - years] if len(annual) > years else None
    if start is not None:
        actual_years = latest.period.fiscal_year - start.period.fiscal_year
        calc = cagr(latest.value("revenue"), start.value("revenue"), actual_years, label="revenue")
    else:
        calc = Calc(
            None,
            "(end_revenue / start_revenue) ** (1 / years) - 1",
            {"end_revenue": latest.value("revenue"), "start_revenue": None, "years": None},
            note=f"insufficient data: fewer than {years} years of annual history",
        )
    metrics.add(_mv(f"revenue_cagr_{years}y", latest.period.label, "ratio", calc))


def _sum_field(periods: list[PeriodFinancials], field_name: str) -> float | None:
    """Total `field_name` across `periods`, or None when any period is missing it.

    A partial sum would silently understate the figure, so one missing period voids the total --
    which is exactly `safe_add`'s contract.
    """
    return safe_add(*(p.value(field_name) for p in periods))


def _consecutive_quarters(periods: list[PeriodFinancials]) -> bool:
    ends = [p.period.period_end for p in periods]
    for a, b in pairwise(ends):
        gap = (b - a).days
        if not (_MIN_QUARTER_GAP_DAYS <= gap <= _MAX_QUARTER_GAP_DAYS):
            return False
    return True


def _assemble_ttm(quarterly: list[PeriodFinancials]) -> dict[str, float | None] | None:
    """Sum the last 4 consecutive quarters into a synthetic TTM period, plus the prior TTM
    (the 4 quarters before that) for growth comparisons when available."""
    if len(quarterly) < 4:
        return None
    last4 = quarterly[-4:]
    if not _consecutive_quarters(last4):
        return None

    summed = {field: _sum_field(last4, field) for field in _FLOW_FIELDS}

    prior_revenue: float | None = None
    prior_eps_diluted: float | None = None
    if len(quarterly) >= 8:
        prev4 = quarterly[-8:-4]
        if _consecutive_quarters(prev4):
            prior_revenue = _sum_field(prev4, "revenue")
            prior_eps_diluted = _sum_field(prev4, "eps_diluted")

    return {
        "revenue": summed["revenue"],
        "prior_revenue": prior_revenue,
        "gross_profit": summed["gross_profit"],
        "operating_income": summed["operating_income"],
        "net_income": summed["net_income"],
        "eps_diluted": summed["eps_diluted"],
        "prior_eps_diluted": prior_eps_diluted,
        "operating_cash_flow": summed["operating_cash_flow"],
        "capex": summed["capex"],
        "research_and_development": summed["research_and_development"],
        "depreciation_amortization": summed["depreciation_amortization"],
    }


def _latest_balance_period(
    annual: list[PeriodFinancials], quarterly: list[PeriodFinancials]
) -> PeriodFinancials | None:
    candidates = [*annual, *quarterly]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.period.period_end)


def _emit_market_metrics(
    metrics: FinancialMetrics,
    annual: list[PeriodFinancials],
    quarterly: list[PeriodFinancials],
    quote: Quote,
    ttm: dict[str, float | None] | None,
    latest_annual_fcf: Calc | None,
    latest_annual_ebitda: Calc | None,
    is_financial_institution: bool,
) -> None:
    latest_annual = annual[-1] if annual else None
    balance_period = _latest_balance_period(annual, quarterly)

    shares = balance_period.shares_outstanding if balance_period else None
    mc = market_cap(quote.price, shares)
    metrics.add(_mv("market_cap", "current", "USD", mc))

    td = total_debt(
        balance_period.long_term_debt if balance_period else None,
        balance_period.current_debt if balance_period else None,
    )
    ev = enterprise_value(
        mc.value,
        td.value,
        balance_period.cash_and_equivalents if balance_period else None,
        balance_period.short_term_investments if balance_period else None,
    )
    metrics.add(_mv("enterprise_value", "current", "USD", ev))

    if ttm is not None:
        basis_label = "TTM"
        basis_revenue = ttm["revenue"]
        basis_net_income = ttm["net_income"]
        basis_eps = ttm["eps_diluted"]
        basis_fcf = free_cash_flow(ttm["operating_cash_flow"], ttm["capex"]).value
        basis_ebitda = ebitda(ttm["operating_income"], ttm["depreciation_amortization"]).value
    elif latest_annual is not None:
        basis_label = latest_annual.period.label
        basis_revenue = latest_annual.revenue
        basis_net_income = latest_annual.net_income
        basis_eps = latest_annual.eps_diluted
        basis_fcf = latest_annual_fcf.value if latest_annual_fcf else None
        basis_ebitda = latest_annual_ebitda.value if latest_annual_ebitda else None
    else:
        basis_label = "unknown"
        basis_revenue = basis_net_income = basis_eps = basis_fcf = basis_ebitda = None

    metrics.add(_mv_with_basis("pe", "current", "x", pe(quote.price, basis_eps), basis_label))
    metrics.add(_mv_with_basis("price_sales", "current", "x", price_sales(mc.value, basis_revenue), basis_label))
    metrics.add(_mv_with_basis("price_fcf", "current", "x", price_fcf(mc.value, basis_fcf), basis_label))

    if is_financial_institution:
        ev_sales_inputs = {"enterprise_value": ev.value, "revenue": basis_revenue}
        ev_ebitda_inputs = {"enterprise_value": ev.value, "ebitda": basis_ebitda}
        metrics.add(_not_meaningful_for_bank("ev_sales", "current", "x", ev_sales_inputs, "enterprise_value / revenue"))
        metrics.add(
            _not_meaningful_for_bank("ev_ebitda", "current", "x", ev_ebitda_inputs, "enterprise_value / ebitda")
        )
    else:
        metrics.add(_mv_with_basis("ev_sales", "current", "x", ev_sales(ev.value, basis_revenue), basis_label))
        metrics.add(_mv_with_basis("ev_ebitda", "current", "x", ev_ebitda(ev.value, basis_ebitda), basis_label))

    fcf_yield_calc = fcf_yield(basis_fcf, mc.value)
    earnings_yield_calc = earnings_yield(basis_net_income, mc.value)
    metrics.add(_mv_with_basis("fcf_yield", "current", "ratio", fcf_yield_calc, basis_label))
    metrics.add(_mv_with_basis("earnings_yield", "current", "ratio", earnings_yield_calc, basis_label))


def compute_metrics(
    statements: FinancialStatements,
    quote: Quote | None = None,
    *,
    is_financial_institution: bool = False,
) -> FinancialMetrics:
    """Compute every metric key the engine supports for one company's statements.

    Flow/income-statement metrics are produced for every annual period, and again with
    ``period="TTM"`` when the statements carry 4+ consecutive quarters. Balance-sheet metrics
    are produced per annual period. ``revenue_cagr_3y``/``revenue_cagr_5y`` are keyed to the
    latest annual period. Market/valuation metrics (``period="current"``) are only produced when
    a ``quote`` is supplied, and prefer TTM figures over the latest annual figures when a TTM is
    available.
    """
    metrics = FinancialMetrics(ticker=statements.ticker)
    annual = statements.annual

    latest_annual_fcf: Calc | None = None
    latest_annual_ebitda: Calc | None = None

    for i, pf in enumerate(annual):
        prior = annual[i - 1] if i > 0 else None
        label = pf.period.label

        for mv in _flow_metrics(
            label,
            revenue=pf.revenue,
            prior_revenue=prior.revenue if prior else None,
            gross_profit=pf.gross_profit,
            operating_income=pf.operating_income,
            net_income=pf.net_income,
            eps_diluted=pf.eps_diluted,
            prior_eps_diluted=prior.eps_diluted if prior else None,
            operating_cash_flow=pf.operating_cash_flow,
            capex=pf.capex,
            research_and_development=pf.research_and_development,
            depreciation_amortization=pf.depreciation_amortization,
            is_financial_institution=is_financial_institution,
        ):
            metrics.add(mv)

        for mv in _balance_metrics(label, pf, prior):
            metrics.add(mv)

        if i == len(annual) - 1:
            latest_annual_fcf = free_cash_flow(pf.operating_cash_flow, pf.capex)
            latest_annual_ebitda = ebitda(pf.operating_income, pf.depreciation_amortization)

    if annual:
        _emit_revenue_cagr(metrics, annual, 3)
        _emit_revenue_cagr(metrics, annual, 5)

    ttm = _assemble_ttm(statements.quarterly)
    if ttm is not None:
        for mv in _flow_metrics("TTM", is_financial_institution=is_financial_institution, **ttm):
            metrics.add(mv)

    if quote is not None:
        _emit_market_metrics(
            metrics,
            annual,
            statements.quarterly,
            quote,
            ttm,
            latest_annual_fcf,
            latest_annual_ebitda,
            is_financial_institution,
        )

    return metrics


# ---------------------------------------------------------------------------
# calculate(): single-metric dispatch for the `calculate_metric` tool.
# ---------------------------------------------------------------------------

CalcFn = Callable[[Mapping[str, float | None]], Calc]


def _passthrough_calc(field_name: str) -> CalcFn:
    def _fn(inputs: Mapping[str, float | None]) -> Calc:
        value = inputs.get(field_name)
        note = None if value is not None else f"insufficient data: {field_name} not provided"
        return Calc(value, f"reported {field_name}", {field_name: value}, note)

    return _fn


def _calc_total_debt(inputs: Mapping[str, float | None]) -> Calc:
    return total_debt(inputs.get("long_term_debt"), inputs.get("current_debt"))


def _calc_market_cap(inputs: Mapping[str, float | None]) -> Calc:
    return market_cap(inputs.get("price"), inputs.get("shares_outstanding"))


def _calc_enterprise_value(inputs: Mapping[str, float | None]) -> Calc:
    return enterprise_value(
        _calc_market_cap(inputs).value,
        _calc_total_debt(inputs).value,
        inputs.get("cash_and_equivalents"),
        inputs.get("short_term_investments"),
    )


def _calc_free_cash_flow(inputs: Mapping[str, float | None]) -> Calc:
    return free_cash_flow(inputs.get("operating_cash_flow"), inputs.get("capex"))


def _calc_ebitda(inputs: Mapping[str, float | None]) -> Calc:
    return ebitda(inputs.get("operating_income"), inputs.get("depreciation_amortization"))


_REGISTRY: dict[str, CalcFn] = {
    "revenue": _passthrough_calc("revenue"),
    "revenue_growth": lambda inp: yoy_growth(inp.get("revenue"), inp.get("prior_revenue"), label="revenue"),
    "gross_profit": _passthrough_calc("gross_profit"),
    "gross_margin": lambda inp: gross_margin(inp.get("gross_profit"), inp.get("revenue")),
    "operating_income": _passthrough_calc("operating_income"),
    "operating_margin": lambda inp: operating_margin(inp.get("operating_income"), inp.get("revenue")),
    "net_income": _passthrough_calc("net_income"),
    "net_margin": lambda inp: net_margin(inp.get("net_income"), inp.get("revenue")),
    "eps_diluted": _passthrough_calc("eps_diluted"),
    "eps_growth": lambda inp: yoy_growth(inp.get("eps_diluted"), inp.get("prior_eps_diluted"), label="eps_diluted"),
    "operating_cash_flow": _passthrough_calc("operating_cash_flow"),
    "capex": _passthrough_calc("capex"),
    "free_cash_flow": _calc_free_cash_flow,
    "fcf_margin": lambda inp: fcf_margin(_calc_free_cash_flow(inp).value, inp.get("revenue")),
    "rd_intensity": lambda inp: rd_intensity(inp.get("research_and_development"), inp.get("revenue")),
    "ebitda": _calc_ebitda,
    "ebitda_margin": lambda inp: ebitda_margin(_calc_ebitda(inp).value, inp.get("revenue")),
    "cash_and_investments": lambda inp: cash_and_investments(
        inp.get("cash_and_equivalents"), inp.get("short_term_investments")
    ),
    "total_debt": _calc_total_debt,
    "net_cash": lambda inp: net_cash(
        inp.get("cash_and_equivalents"), inp.get("short_term_investments"), _calc_total_debt(inp).value
    ),
    "total_assets": _passthrough_calc("total_assets"),
    "total_liabilities": _passthrough_calc("total_liabilities"),
    "shareholders_equity": _passthrough_calc("shareholders_equity"),
    "current_ratio": lambda inp: current_ratio(inp.get("current_assets"), inp.get("current_liabilities")),
    "debt_to_equity": lambda inp: debt_to_equity(_calc_total_debt(inp).value, inp.get("shareholders_equity")),
    "roa": lambda inp: roa(inp.get("net_income"), inp.get("total_assets"), inp.get("prior_total_assets")),
    "roe": lambda inp: roe(inp.get("net_income"), inp.get("shareholders_equity"), inp.get("prior_shareholders_equity")),
    "revenue_cagr_3y": lambda inp: cagr(
        inp.get("end_revenue"), inp.get("start_revenue"), inp.get("years"), label="revenue"
    ),
    "revenue_cagr_5y": lambda inp: cagr(
        inp.get("end_revenue"), inp.get("start_revenue"), inp.get("years"), label="revenue"
    ),
    "market_cap": _calc_market_cap,
    "enterprise_value": _calc_enterprise_value,
    "pe": lambda inp: pe(inp.get("price"), inp.get("eps_diluted")),
    "price_sales": lambda inp: price_sales(_calc_market_cap(inp).value, inp.get("revenue")),
    "price_fcf": lambda inp: price_fcf(_calc_market_cap(inp).value, _calc_free_cash_flow(inp).value),
    "ev_sales": lambda inp: ev_sales(_calc_enterprise_value(inp).value, inp.get("revenue")),
    "ev_ebitda": lambda inp: ev_ebitda(_calc_enterprise_value(inp).value, _calc_ebitda(inp).value),
    "fcf_yield": lambda inp: fcf_yield(_calc_free_cash_flow(inp).value, _calc_market_cap(inp).value),
    "earnings_yield": lambda inp: earnings_yield(inp.get("net_income"), _calc_market_cap(inp).value),
}

_UNITS: dict[str, MetricUnit] = {
    "revenue": "USD",
    "revenue_growth": "ratio",
    "gross_profit": "USD",
    "gross_margin": "ratio",
    "operating_income": "USD",
    "operating_margin": "ratio",
    "net_income": "USD",
    "net_margin": "ratio",
    "eps_diluted": "USD/share",
    "eps_growth": "ratio",
    "operating_cash_flow": "USD",
    "capex": "USD",
    "free_cash_flow": "USD",
    "fcf_margin": "ratio",
    "rd_intensity": "ratio",
    "ebitda": "USD",
    "ebitda_margin": "ratio",
    "cash_and_investments": "USD",
    "total_debt": "USD",
    "net_cash": "USD",
    "total_assets": "USD",
    "total_liabilities": "USD",
    "shareholders_equity": "USD",
    "current_ratio": "ratio",
    "debt_to_equity": "ratio",
    "roa": "ratio",
    "roe": "ratio",
    "revenue_cagr_3y": "ratio",
    "revenue_cagr_5y": "ratio",
    "market_cap": "USD",
    "enterprise_value": "USD",
    "pe": "x",
    "price_sales": "x",
    "price_fcf": "x",
    "ev_sales": "x",
    "ev_ebitda": "x",
    "fcf_yield": "ratio",
    "earnings_yield": "ratio",
}


def calculate(metric: str, inputs: dict[str, float | None], *, period: str = "custom") -> MetricValue:
    """Single-metric dispatch used by the ``calculate_metric`` tool.

    ``inputs`` supplies whatever named values the metric needs (e.g. ``gross_margin`` needs
    ``gross_profit`` and ``revenue``); missing keys are treated the same as missing data
    everywhere else in this package -- the result carries ``value=None`` and a note, it never
    raises for that reason. The only case that raises is an unrecognised ``metric`` key.
    """
    fn = _REGISTRY.get(metric)
    if fn is None:
        raise ValidationFailedError(f"unknown metric: {metric}", details={"metric": metric})
    calc = fn(inputs)
    return MetricValue(
        key=metric,
        period=period,
        value=calc.value,
        unit=_UNITS[metric],
        formula=calc.formula,
        inputs=calc.inputs,
        note=calc.note,
    )
