"""Income-statement margin ratios, all expressed as decimals of revenue."""

from __future__ import annotations

from meridian.financial_engine.safe import Calc, safe_div


def _margin(numerator_key: str, numerator: float | None, revenue: float | None) -> Calc:
    inputs = {numerator_key: numerator, "revenue": revenue}
    formula = f"{numerator_key} / revenue"
    value = safe_div(numerator, revenue)
    note = None
    if value is None:
        if numerator is None or revenue is None:
            note = f"insufficient data: missing {numerator_key} or revenue"
        else:
            note = "insufficient data: revenue is zero"
    return Calc(value, formula, inputs, note)


def gross_margin(gross_profit: float | None, revenue: float | None) -> Calc:
    return _margin("gross_profit", gross_profit, revenue)


def operating_margin(operating_income: float | None, revenue: float | None) -> Calc:
    return _margin("operating_income", operating_income, revenue)


def net_margin(net_income: float | None, revenue: float | None) -> Calc:
    return _margin("net_income", net_income, revenue)


def fcf_margin(free_cash_flow: float | None, revenue: float | None) -> Calc:
    return _margin("free_cash_flow", free_cash_flow, revenue)


def ebitda_margin(ebitda: float | None, revenue: float | None) -> Calc:
    return _margin("ebitda", ebitda, revenue)


def rd_intensity(research_and_development: float | None, revenue: float | None) -> Calc:
    return _margin("research_and_development", research_and_development, revenue)
