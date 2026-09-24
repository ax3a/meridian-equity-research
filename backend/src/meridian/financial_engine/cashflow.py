"""Cash-flow derived line items: free cash flow and EBITDA."""

from __future__ import annotations

from meridian.financial_engine.safe import Calc, safe_add, safe_sub


def free_cash_flow(operating_cash_flow: float | None, capex: float | None) -> Calc:
    """operating_cash_flow - capex (capex is stored as a positive outflow)."""
    inputs = {"operating_cash_flow": operating_cash_flow, "capex": capex}
    formula = "operating_cash_flow - capex"
    value = safe_sub(operating_cash_flow, capex)
    note = None if value is not None else "insufficient data: missing operating cash flow or capex"
    return Calc(value, formula, inputs, note)


def ebitda(operating_income: float | None, depreciation_amortization: float | None) -> Calc:
    """operating_income + depreciation_amortization."""
    inputs = {
        "operating_income": operating_income,
        "depreciation_amortization": depreciation_amortization,
    }
    formula = "operating_income + depreciation_amortization"
    value = safe_add(operating_income, depreciation_amortization)
    note = None if value is not None else "insufficient data: missing operating income or D&A"
    return Calc(value, formula, inputs, note)
