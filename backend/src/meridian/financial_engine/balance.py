"""Balance-sheet derived metrics: liquidity, leverage and return ratios."""

from __future__ import annotations

from meridian.financial_engine.safe import Calc, safe_add, safe_div, safe_sub


def cash_and_investments(cash: float | None, short_term_investments: float | None) -> Calc:
    inputs = {"cash_and_equivalents": cash, "short_term_investments": short_term_investments}
    formula = "cash_and_equivalents + short_term_investments"
    value = safe_add(cash, short_term_investments)
    note = None if value is not None else "insufficient data: missing cash or short-term investments"
    return Calc(value, formula, inputs, note)


def total_debt(long_term_debt: float | None, current_debt: float | None) -> Calc:
    inputs = {"long_term_debt": long_term_debt, "current_debt": current_debt}
    formula = "long_term_debt + current_debt"
    value = safe_add(long_term_debt, current_debt)
    note = None if value is not None else "insufficient data: missing long-term or current debt"
    return Calc(value, formula, inputs, note)


def net_cash(cash: float | None, short_term_investments: float | None, total_debt_value: float | None) -> Calc:
    inputs = {
        "cash_and_equivalents": cash,
        "short_term_investments": short_term_investments,
        "total_debt": total_debt_value,
    }
    formula = "cash_and_equivalents + short_term_investments - total_debt"
    value = safe_sub(safe_add(cash, short_term_investments), total_debt_value)
    note = None if value is not None else "insufficient data: missing cash, short-term investments, or total debt"
    return Calc(value, formula, inputs, note)


def current_ratio(current_assets: float | None, current_liabilities: float | None) -> Calc:
    inputs = {"current_assets": current_assets, "current_liabilities": current_liabilities}
    formula = "current_assets / current_liabilities"
    value = safe_div(current_assets, current_liabilities)
    note = None
    if value is None:
        if current_assets is None or current_liabilities is None:
            note = "insufficient data: missing current assets or current liabilities"
        else:
            note = "insufficient data: current liabilities is zero"
    return Calc(value, formula, inputs, note)


def debt_to_equity(total_debt_value: float | None, shareholders_equity: float | None) -> Calc:
    inputs = {"total_debt": total_debt_value, "shareholders_equity": shareholders_equity}
    formula = "total_debt / shareholders_equity"
    value = safe_div(total_debt_value, shareholders_equity)
    note = None
    if value is None:
        if total_debt_value is None or shareholders_equity is None:
            note = "insufficient data: missing total debt or shareholders' equity"
        else:
            note = "insufficient data: shareholders' equity is zero"
    return Calc(value, formula, inputs, note)


def _return_ratio(
    label: str,
    numerator_key: str,
    numerator: float | None,
    ending: float | None,
    beginning: float | None,
) -> Calc:
    use_average = beginning is not None and ending is not None
    if use_average:
        denominator = (ending + beginning) / 2  # type: ignore[operator]
        formula = f"{numerator_key} / average({label}_beginning, {label}_ending)"
        basis = "average of beginning and ending balances"
    else:
        denominator = ending
        formula = f"{numerator_key} / {label}_ending"
        basis = "ending balance only (no prior period available)"
    inputs = {numerator_key: numerator, f"{label}_ending": ending, f"{label}_beginning": beginning}
    value = safe_div(numerator, denominator)
    note = None
    if value is None:
        if numerator is None or denominator is None:
            note = f"insufficient data: missing inputs for {label} ratio ({basis})"
        else:
            note = f"insufficient data: {label} denominator is zero ({basis})"
    return Calc(value, f"{formula} [{basis}]", inputs, note)


def roa(net_income: float | None, ending_assets: float | None, beginning_assets: float | None = None) -> Calc:
    return _return_ratio("total_assets", "net_income", net_income, ending_assets, beginning_assets)


def roe(
    net_income: float | None,
    ending_equity: float | None,
    beginning_equity: float | None = None,
) -> Calc:
    return _return_ratio("shareholders_equity", "net_income", net_income, ending_equity, beginning_equity)
