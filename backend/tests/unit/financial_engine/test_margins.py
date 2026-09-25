from __future__ import annotations

import pytest

from meridian.financial_engine.margins import (
    ebitda_margin,
    gross_margin,
    net_margin,
    operating_margin,
    rd_intensity,
)
from tests.unit.financial_engine.conftest import GROSS_PROFIT_FY2024, NET_INCOME_FY2024, REVENUE_FY2024


class TestGrossMargin:
    def test_msft_fy2024(self):
        calc = gross_margin(GROSS_PROFIT_FY2024, REVENUE_FY2024)
        assert calc.value == pytest.approx(GROSS_PROFIT_FY2024 / REVENUE_FY2024, rel=1e-6)
        assert calc.value == pytest.approx(0.69764, rel=1e-4)
        assert calc.note is None

    def test_missing_inputs(self):
        calc = gross_margin(None, REVENUE_FY2024)
        assert calc.value is None
        assert calc.note is not None

    def test_zero_revenue(self):
        calc = gross_margin(100.0, 0.0)
        assert calc.value is None
        assert calc.note is not None


class TestOperatingMargin:
    def test_basic(self):
        calc = operating_margin(50.0, 200.0)
        assert calc.value == pytest.approx(0.25)


class TestNetMargin:
    def test_msft_fy2024(self):
        calc = net_margin(NET_INCOME_FY2024, REVENUE_FY2024)
        assert calc.value == pytest.approx(NET_INCOME_FY2024 / REVENUE_FY2024, rel=1e-6)


class TestRdIntensity:
    def test_basic(self):
        calc = rd_intensity(20.0, 100.0)
        assert calc.value == pytest.approx(0.20)

    def test_missing(self):
        assert rd_intensity(None, 100.0).value is None


class TestEbitdaMargin:
    def test_basic(self):
        calc = ebitda_margin(60.0, 200.0)
        assert calc.value == pytest.approx(0.30)
