"""Discounted cash flow valuation.

Pure function over :class:`~meridian.schemas.analysis.DCFAssumptions`. The only case that raises
is an economically nonsensical discount/terminal-growth pair (Gordon growth requires
``discount_rate > terminal_growth``, and the plan requires a 0.5 percentage-point safety margin);
everything else degrades gracefully.
"""

from __future__ import annotations

from meridian.core.errors import ValidationFailedError
from meridian.schemas.analysis import DCFAssumptions, DCFResult

_MIN_SPREAD = 0.005

# Sensitivity grid deltas, per the plan: discount_rate +/-1pp and +/-2pp, terminal_growth
# +/-0.5pp and +/-1pp (0.0 included so the base case itself appears in the grid).
_DISCOUNT_RATE_DELTAS: tuple[float, ...] = (-0.02, -0.01, 0.0, 0.01, 0.02)
_TERMINAL_GROWTH_DELTAS: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01)


def _check_spread(discount_rate: float, terminal_growth: float) -> bool:
    # Round away binary floating-point noise (e.g. 0.035 - 0.03 != 0.005 exactly) so an
    # assumption pair that is mathematically exactly at the 0.5pp boundary is treated as
    # invalid rather than accepted or rejected depending on representation error.
    spread = round(discount_rate - terminal_growth, 9)
    return spread > _MIN_SPREAD


def _project_fcf(base_revenue: float, revenue_growth: list[float], fcf_margin: float) -> list[float]:
    fcfs: list[float] = []
    revenue = base_revenue
    for g in revenue_growth:
        revenue = revenue * (1 + g)
        fcfs.append(revenue * fcf_margin)
    return fcfs


def _discount(cash_flows: list[float], discount_rate: float) -> list[float]:
    return [cf / (1 + discount_rate) ** (i + 1) for i, cf in enumerate(cash_flows)]


def _terminal_value(last_fcf: float, discount_rate: float, terminal_growth: float) -> float:
    return last_fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)


def _value_per_share(
    base_revenue: float,
    revenue_growth: list[float],
    fcf_margin: float,
    discount_rate: float,
    terminal_growth: float,
    net_cash: float,
    shares_outstanding: float,
) -> tuple[list[float], float, float, float, float, float, float]:
    projected_fcf = _project_fcf(base_revenue, revenue_growth, fcf_margin)
    discounted = _discount(projected_fcf, discount_rate)
    present_value_fcf = sum(discounted)

    terminal_value = _terminal_value(projected_fcf[-1], discount_rate, terminal_growth)
    n = len(projected_fcf)
    present_value_terminal = terminal_value / (1 + discount_rate) ** n

    enterprise_value = present_value_fcf + present_value_terminal
    equity_value = enterprise_value + net_cash
    value_per_share = equity_value / shares_outstanding if shares_outstanding else 0.0

    return (
        projected_fcf,
        present_value_fcf,
        terminal_value,
        present_value_terminal,
        enterprise_value,
        equity_value,
        value_per_share,
    )


def _build_sensitivity(assumptions: DCFAssumptions) -> list[dict[str, float]]:
    grid: list[dict[str, float]] = []
    for dr_delta in _DISCOUNT_RATE_DELTAS:
        discount_rate = assumptions.discount_rate + dr_delta
        for tg_delta in _TERMINAL_GROWTH_DELTAS:
            terminal_growth = assumptions.terminal_growth + tg_delta
            if not _check_spread(discount_rate, terminal_growth):
                continue
            *_, value_per_share = _value_per_share(
                assumptions.base_revenue,
                assumptions.revenue_growth,
                assumptions.fcf_margin,
                discount_rate,
                terminal_growth,
                assumptions.net_cash,
                assumptions.shares_outstanding,
            )
            grid.append(
                {
                    "discount_rate": discount_rate,
                    "terminal_growth": terminal_growth,
                    "value": value_per_share,
                }
            )
    return grid


def run_dcf(assumptions: DCFAssumptions, current_price: float | None = None) -> DCFResult:
    """Project FCF, discount it plus a Gordon-growth terminal value, and derive per-share value.

    Raises :class:`ValidationFailedError` when ``discount_rate`` does not exceed
    ``terminal_growth`` by at least 0.5 percentage points -- the only case in this module that
    raises, since the calculation is otherwise economically undefined.
    """
    if not _check_spread(assumptions.discount_rate, assumptions.terminal_growth):
        raise ValidationFailedError(
            "discount_rate must exceed terminal_growth by at least 0.5 percentage points",
            details={
                "discount_rate": assumptions.discount_rate,
                "terminal_growth": assumptions.terminal_growth,
            },
        )

    (
        projected_fcf,
        present_value_fcf,
        terminal_value,
        present_value_terminal,
        enterprise_value,
        equity_value,
        value_per_share,
    ) = _value_per_share(
        assumptions.base_revenue,
        assumptions.revenue_growth,
        assumptions.fcf_margin,
        assumptions.discount_rate,
        assumptions.terminal_growth,
        assumptions.net_cash,
        assumptions.shares_outstanding,
    )

    upside_pct = None
    if current_price is not None and current_price > 0:
        upside_pct = (value_per_share - current_price) / current_price

    return DCFResult(
        assumptions=assumptions,
        projected_fcf=projected_fcf,
        present_value_fcf=present_value_fcf,
        terminal_value=terminal_value,
        present_value_terminal=present_value_terminal,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        value_per_share=value_per_share,
        current_price=current_price,
        upside_pct=upside_pct,
        sensitivity=_build_sensitivity(assumptions),
    )
