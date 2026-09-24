from __future__ import annotations

import pytest

from meridian.core.errors import ValidationFailedError
from meridian.financial_engine.dcf import run_dcf
from meridian.schemas.analysis import DCFAssumptions


def make_assumptions(**overrides) -> DCFAssumptions:
    defaults = dict(
        base_revenue=100.0,
        revenue_growth=[0.10, 0.08, 0.06, 0.05, 0.04],
        fcf_margin=0.30,
        discount_rate=0.09,
        terminal_growth=0.03,
        net_cash=50.0,
        shares_outstanding=100.0,
    )
    defaults.update(overrides)
    return DCFAssumptions(**defaults)


class TestRunDcf:
    def test_projects_revenue_and_fcf(self):
        assumptions = make_assumptions()
        result = run_dcf(assumptions)

        revenue = 100.0
        expected_fcf = []
        for g in assumptions.revenue_growth:
            revenue *= 1 + g
            expected_fcf.append(revenue * assumptions.fcf_margin)

        assert result.projected_fcf == pytest.approx(expected_fcf, rel=1e-9)

    def test_present_value_and_terminal_value(self):
        assumptions = make_assumptions()
        result = run_dcf(assumptions)

        discounted = [cf / (1 + assumptions.discount_rate) ** (i + 1) for i, cf in enumerate(result.projected_fcf)]
        expected_pv_fcf = sum(discounted)
        assert result.present_value_fcf == pytest.approx(expected_pv_fcf, rel=1e-9)

        last_fcf = result.projected_fcf[-1]
        expected_terminal = (
            last_fcf * (1 + assumptions.terminal_growth) / (assumptions.discount_rate - assumptions.terminal_growth)
        )
        assert result.terminal_value == pytest.approx(expected_terminal, rel=1e-9)

        n = len(result.projected_fcf)
        expected_pv_terminal = expected_terminal / (1 + assumptions.discount_rate) ** n
        assert result.present_value_terminal == pytest.approx(expected_pv_terminal, rel=1e-9)

    def test_equity_value_and_per_share(self):
        assumptions = make_assumptions()
        result = run_dcf(assumptions)

        expected_ev = result.present_value_fcf + result.present_value_terminal
        assert result.enterprise_value == pytest.approx(expected_ev, rel=1e-9)

        expected_equity = expected_ev + assumptions.net_cash
        assert result.equity_value == pytest.approx(expected_equity, rel=1e-9)

        expected_per_share = expected_equity / assumptions.shares_outstanding
        assert result.value_per_share == pytest.approx(expected_per_share, rel=1e-9)

    def test_upside_pct_computed_when_price_given(self):
        assumptions = make_assumptions()
        result = run_dcf(assumptions, current_price=50.0)
        expected = (result.value_per_share - 50.0) / 50.0
        assert result.upside_pct == pytest.approx(expected, rel=1e-9)
        assert result.current_price == 50.0

    def test_upside_pct_none_without_price(self):
        assumptions = make_assumptions()
        result = run_dcf(assumptions)
        assert result.upside_pct is None
        assert result.current_price is None

    def test_rejects_discount_rate_too_close_to_terminal_growth(self):
        assumptions = make_assumptions(discount_rate=0.035, terminal_growth=0.03)
        with pytest.raises(ValidationFailedError):
            run_dcf(assumptions)

    def test_rejects_discount_rate_below_terminal_growth(self):
        assumptions = make_assumptions(discount_rate=0.02, terminal_growth=0.03)
        with pytest.raises(ValidationFailedError):
            run_dcf(assumptions)

    def test_accepts_exactly_at_boundary_plus_epsilon(self):
        # discount_rate must exceed terminal_growth + 0.005; 0.0351 clears the 0.035 boundary.
        assumptions = make_assumptions(discount_rate=0.0351, terminal_growth=0.03)
        result = run_dcf(assumptions)
        assert result.value_per_share is not None

    def test_sensitivity_grid_shape(self):
        assumptions = make_assumptions()
        result = run_dcf(assumptions)
        assert len(result.sensitivity) > 0
        for entry in result.sensitivity:
            assert set(entry.keys()) == {"discount_rate", "terminal_growth", "value"}
            assert entry["discount_rate"] > entry["terminal_growth"] + 0.005 - 1e-9

        deltas_dr = {round(e["discount_rate"] - assumptions.discount_rate, 6) for e in result.sensitivity}
        deltas_tg = {round(e["terminal_growth"] - assumptions.terminal_growth, 6) for e in result.sensitivity}
        assert deltas_dr <= {-0.02, -0.01, 0.0, 0.01, 0.02}
        assert deltas_tg <= {-0.01, -0.005, 0.0, 0.005, 0.01}
        # base case (no delta) must always be present and safe
        assert any(d == 0.0 for d in deltas_dr)
        assert any(d == 0.0 for d in deltas_tg)

    def test_sensitivity_skips_invalid_combinations_without_raising(self):
        # discount_rate - 0.02 with terminal_growth + 0.01 would violate r > g + 0.005 for a
        # tight base case; must be silently omitted, never raised.
        assumptions = make_assumptions(discount_rate=0.045, terminal_growth=0.03)
        result = run_dcf(assumptions)
        for entry in result.sensitivity:
            assert entry["discount_rate"] > entry["terminal_growth"] + 0.005 - 1e-9

    def test_zero_shares_outstanding_does_not_raise(self):
        assumptions = make_assumptions(shares_outstanding=0.0)
        result = run_dcf(assumptions)
        assert result.value_per_share == 0.0
