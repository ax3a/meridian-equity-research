from __future__ import annotations

import pytest

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


class TestMarketCap:
    def test_basic(self):
        calc = market_cap(400.0, 7_400_000_000.0)
        assert calc.value == pytest.approx(400.0 * 7_400_000_000.0)

    def test_missing(self):
        assert market_cap(None, 100.0).value is None


class TestEnterpriseValue:
    def test_basic(self):
        calc = enterprise_value(1000.0, 50.0, 20.0, 55.0)
        assert calc.value == pytest.approx(1000.0 + 50.0 - 20.0 - 55.0)

    def test_missing(self):
        assert enterprise_value(None, 50.0, 20.0, 55.0).value is None


class TestPe:
    def test_basic(self):
        calc = pe(400.0, 11.80)
        assert calc.value == pytest.approx(400.0 / 11.80)
        assert calc.note is None

    def test_negative_eps_not_meaningful(self):
        calc = pe(400.0, -2.0)
        assert calc.value is None
        assert calc.note == "not meaningful (negative or zero denominator)"

    def test_zero_eps_not_meaningful(self):
        calc = pe(400.0, 0.0)
        assert calc.value is None
        assert calc.note == "not meaningful (negative or zero denominator)"

    def test_missing_inputs(self):
        calc = pe(None, 11.80)
        assert calc.value is None
        assert calc.note != "not meaningful (negative or zero denominator)"


class TestPriceSales:
    def test_basic(self):
        calc = price_sales(1000.0, 200.0)
        assert calc.value == pytest.approx(5.0)

    def test_negative_revenue_not_meaningful(self):
        calc = price_sales(1000.0, -200.0)
        assert calc.value is None
        assert calc.note == "not meaningful (negative or zero denominator)"


class TestPriceFcf:
    def test_basic(self):
        calc = price_fcf(1000.0, 100.0)
        assert calc.value == pytest.approx(10.0)

    def test_negative_fcf_not_meaningful(self):
        calc = price_fcf(1000.0, -50.0)
        assert calc.value is None
        assert calc.note == "not meaningful (negative or zero denominator)"


class TestEvSales:
    def test_basic(self):
        calc = ev_sales(2000.0, 400.0)
        assert calc.value == pytest.approx(5.0)

    def test_zero_revenue(self):
        calc = ev_sales(2000.0, 0.0)
        assert calc.value is None
        assert calc.note == "not meaningful (negative or zero denominator)"


class TestEvEbitda:
    def test_basic(self):
        calc = ev_ebitda(2000.0, 500.0)
        assert calc.value == pytest.approx(4.0)

    def test_negative_ebitda(self):
        calc = ev_ebitda(2000.0, -500.0)
        assert calc.value is None
        assert calc.note == "not meaningful (negative or zero denominator)"


class TestFcfYield:
    def test_basic(self):
        calc = fcf_yield(100.0, 1000.0)
        assert calc.value == pytest.approx(0.10)

    def test_negative_fcf_still_meaningful(self):
        # fcf_yield is not in the "not meaningful" list -- a negative FCF yields a negative,
        # still-informative ratio rather than None.
        calc = fcf_yield(-50.0, 1000.0)
        assert calc.value == pytest.approx(-0.05)

    def test_zero_market_cap(self):
        assert fcf_yield(100.0, 0.0).value is None


class TestEarningsYield:
    def test_basic(self):
        calc = earnings_yield(88.0, 1000.0)
        assert calc.value == pytest.approx(0.088)

    def test_negative_net_income(self):
        calc = earnings_yield(-10.0, 1000.0)
        assert calc.value == pytest.approx(-0.01)
