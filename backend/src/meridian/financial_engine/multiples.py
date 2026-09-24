"""Market-value metrics and valuation multiples."""

from __future__ import annotations

from meridian.financial_engine.safe import Calc, safe_add, safe_div, safe_mul, safe_sub

NOT_MEANINGFUL_NOTE = "not meaningful (negative or zero denominator)"


def market_cap(price: float | None, shares_outstanding: float | None) -> Calc:
    inputs = {"price": price, "shares_outstanding": shares_outstanding}
    formula = "price * shares_outstanding"
    value = safe_mul(price, shares_outstanding)
    note = None if value is not None else "insufficient data: missing price or shares outstanding"
    return Calc(value, formula, inputs, note)


def enterprise_value(
    market_cap_value: float | None,
    total_debt_value: float | None,
    cash: float | None,
    short_term_investments: float | None,
) -> Calc:
    inputs = {
        "market_cap": market_cap_value,
        "total_debt": total_debt_value,
        "cash_and_equivalents": cash,
        "short_term_investments": short_term_investments,
    }
    formula = "market_cap + total_debt - cash_and_equivalents - short_term_investments"
    gross = safe_add(market_cap_value, total_debt_value)
    value = safe_sub(gross, cash, short_term_investments)
    note = None if value is not None else "insufficient data: missing market cap, total debt, cash, or investments"
    return Calc(value, formula, inputs, note)


def _multiple(
    numerator: float | None,
    denominator: float | None,
    numerator_key: str,
    denominator_key: str,
    formula: str,
) -> Calc:
    inputs = {numerator_key: numerator, denominator_key: denominator}
    if numerator is None or denominator is None:
        return Calc(None, formula, inputs, note=f"insufficient data: missing {numerator_key} or {denominator_key}")
    if denominator <= 0:
        return Calc(None, formula, inputs, note=NOT_MEANINGFUL_NOTE)
    return Calc(numerator / denominator, formula, inputs)


def pe(price: float | None, eps_diluted: float | None) -> Calc:
    return _multiple(price, eps_diluted, "price", "eps_diluted", "price / eps_diluted")


def price_sales(market_cap_value: float | None, revenue: float | None) -> Calc:
    return _multiple(market_cap_value, revenue, "market_cap", "revenue", "market_cap / revenue")


def price_fcf(market_cap_value: float | None, free_cash_flow_value: float | None) -> Calc:
    return _multiple(
        market_cap_value, free_cash_flow_value, "market_cap", "free_cash_flow", "market_cap / free_cash_flow"
    )


def ev_sales(enterprise_value_value: float | None, revenue: float | None) -> Calc:
    return _multiple(enterprise_value_value, revenue, "enterprise_value", "revenue", "enterprise_value / revenue")


def ev_ebitda(enterprise_value_value: float | None, ebitda_value: float | None) -> Calc:
    return _multiple(enterprise_value_value, ebitda_value, "enterprise_value", "ebitda", "enterprise_value / ebitda")


def fcf_yield(free_cash_flow_value: float | None, market_cap_value: float | None) -> Calc:
    inputs = {"free_cash_flow": free_cash_flow_value, "market_cap": market_cap_value}
    formula = "free_cash_flow / market_cap"
    value = safe_div(free_cash_flow_value, market_cap_value)
    note = None if value is not None else "insufficient data: missing free cash flow or market cap"
    return Calc(value, formula, inputs, note)


def earnings_yield(net_income: float | None, market_cap_value: float | None) -> Calc:
    inputs = {"net_income": net_income, "market_cap": market_cap_value}
    formula = "net_income / market_cap"
    value = safe_div(net_income, market_cap_value)
    note = None if value is not None else "insufficient data: missing net income or market cap"
    return Calc(value, formula, inputs, note)
