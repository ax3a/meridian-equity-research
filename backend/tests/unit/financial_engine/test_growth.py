from __future__ import annotations

import pytest

from meridian.financial_engine.growth import cagr, yoy_growth
from tests.unit.financial_engine.conftest import REVENUE_FY2023, REVENUE_FY2024


class TestYoyGrowth:
    def test_msft_revenue_growth_fy2024(self):
        calc = yoy_growth(REVENUE_FY2024, REVENUE_FY2023, label="revenue")
        expected = (REVENUE_FY2024 - REVENUE_FY2023) / REVENUE_FY2023
        assert calc.value == pytest.approx(expected, rel=1e-9)
        # The plan quotes this growth rate as ~0.15675; the precise figure from the exact
        # reported revenue values is 0.15670, so we check it to 3 significant figures.
        assert calc.value == pytest.approx(0.15675, rel=1e-3)
        assert calc.note is None
        assert "revenue" in calc.formula

    def test_none_current(self):
        calc = yoy_growth(None, 100.0)
        assert calc.value is None
        assert calc.note is not None

    def test_none_prior(self):
        calc = yoy_growth(100.0, None)
        assert calc.value is None
        assert calc.note is not None

    def test_zero_prior(self):
        calc = yoy_growth(100.0, 0.0)
        assert calc.value is None
        assert "zero" in calc.note

    def test_negative_to_positive(self):
        calc = yoy_growth(50.0, -100.0)
        assert calc.value == pytest.approx((50.0 - (-100.0)) / -100.0)


class TestCagr:
    def test_basic_three_year(self):
        calc = cagr(133.1, 100.0, 3)
        assert calc.value == pytest.approx(0.10, rel=1e-6)
        assert calc.note is None

    def test_none_start_le_zero(self):
        calc = cagr(100.0, 0.0, 3)
        assert calc.value is None
        assert calc.note is not None

    def test_negative_start(self):
        calc = cagr(100.0, -10.0, 3)
        assert calc.value is None

    def test_years_less_than_one(self):
        calc = cagr(110.0, 100.0, 0)
        assert calc.value is None

    def test_missing_inputs(self):
        assert cagr(None, 100.0, 3).value is None
        assert cagr(100.0, None, 3).value is None
        assert cagr(100.0, 50.0, None).value is None

    def test_records_inputs(self):
        calc = cagr(133.1, 100.0, 3, label="revenue")
        assert calc.inputs["end_revenue"] == 133.1
        assert calc.inputs["start_revenue"] == 100.0
        assert calc.inputs["years"] == 3
