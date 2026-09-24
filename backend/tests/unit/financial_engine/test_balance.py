from __future__ import annotations

import pytest

from meridian.financial_engine.balance import (
    cash_and_investments,
    current_ratio,
    debt_to_equity,
    net_cash,
    roa,
    roe,
    total_debt,
)


class TestCashAndInvestments:
    def test_basic(self):
        calc = cash_and_investments(20.0, 55.0)
        assert calc.value == pytest.approx(75.0)

    def test_missing(self):
        assert cash_and_investments(None, 55.0).value is None


class TestTotalDebt:
    def test_basic(self):
        calc = total_debt(42.0, 8.0)
        assert calc.value == pytest.approx(50.0)

    def test_missing(self):
        assert total_debt(None, 8.0).value is None


class TestNetCash:
    def test_basic(self):
        calc = net_cash(20.0, 55.0, 50.0)
        assert calc.value == pytest.approx(25.0)

    def test_missing_total_debt(self):
        assert net_cash(20.0, 55.0, None).value is None

    def test_missing_cash(self):
        assert net_cash(None, 55.0, 50.0).value is None


class TestCurrentRatio:
    def test_basic(self):
        calc = current_ratio(125.0, 100.0)
        assert calc.value == pytest.approx(1.25)

    def test_zero_liabilities(self):
        calc = current_ratio(125.0, 0.0)
        assert calc.value is None
        assert calc.note is not None


class TestDebtToEquity:
    def test_basic(self):
        calc = debt_to_equity(50.0, 300.0)
        assert calc.value == pytest.approx(50.0 / 300.0)

    def test_zero_equity(self):
        assert debt_to_equity(50.0, 0.0).value is None


class TestRoa:
    def test_ending_only(self):
        calc = roa(88.0, 500.0)
        assert calc.value == pytest.approx(88.0 / 500.0)
        assert "ending" in calc.formula.lower()

    def test_average_basis(self):
        calc = roa(88.0, 500.0, 400.0)
        expected = 88.0 / ((500.0 + 400.0) / 2)
        assert calc.value == pytest.approx(expected)
        assert "average" in calc.formula.lower()

    def test_missing_net_income(self):
        assert roa(None, 500.0).value is None

    def test_zero_ending_assets(self):
        assert roa(88.0, 0.0).value is None


class TestRoe:
    def test_ending_only(self):
        calc = roe(88.0, 300.0)
        assert calc.value == pytest.approx(88.0 / 300.0)
        assert "ending" in calc.formula.lower()

    def test_average_basis(self):
        calc = roe(88.0, 300.0, 200.0)
        expected = 88.0 / ((300.0 + 200.0) / 2)
        assert calc.value == pytest.approx(expected)
        assert "average" in calc.formula.lower()
