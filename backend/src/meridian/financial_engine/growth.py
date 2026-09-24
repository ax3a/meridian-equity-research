"""Growth-rate calculations: year-over-year growth and multi-year CAGR."""

from __future__ import annotations

from meridian.financial_engine.safe import Calc


def yoy_growth(current: float | None, prior: float | None, *, label: str = "value") -> Calc:
    """(current - prior) / prior. ``None`` if either operand is missing or ``prior`` is zero."""
    inputs = {f"current_{label}": current, f"prior_{label}": prior}
    formula = f"(current_{label} - prior_{label}) / prior_{label}"
    if current is None or prior is None:
        return Calc(None, formula, inputs, note=f"insufficient data: missing {label} for growth calculation")
    if prior == 0:
        return Calc(None, formula, inputs, note=f"insufficient data: prior {label} is zero")
    return Calc((current - prior) / prior, formula, inputs)


def cagr(end: float | None, start: float | None, years: float | None, *, label: str = "revenue") -> Calc:
    """Compound annual growth rate. ``None`` if data is missing, ``start`` <= 0, or ``years`` < 1."""
    inputs = {f"end_{label}": end, f"start_{label}": start, "years": years}
    formula = f"(end_{label} / start_{label}) ** (1 / years) - 1"
    if end is None or start is None or years is None:
        return Calc(None, formula, inputs, note=f"insufficient data: missing {label} history for CAGR")
    if start <= 0 or years < 1:
        return Calc(
            None,
            formula,
            inputs,
            note="insufficient data: start value <= 0 or fewer than 1 year of history",
        )
    return Calc((end / start) ** (1 / years) - 1, formula, inputs)
