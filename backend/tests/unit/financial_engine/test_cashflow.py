from __future__ import annotations

import pytest
from tests.unit.financial_engine.conftest import CAPEX_FY2024, FCF_FY2024, OCF_FY2024

from meridian.financial_engine.cashflow import ebitda, free_cash_flow


class TestFreeCashFlow:
    def test_msft_fy2024(self):
        calc = free_cash_flow(OCF_FY2024, CAPEX_FY2024)
        assert calc.value == pytest.approx(FCF_FY2024, rel=1e-9)
        assert calc.note is None
        assert calc.inputs["operating_cash_flow"] == OCF_FY2024
        assert calc.inputs["capex"] == CAPEX_FY2024

    def test_missing_ocf(self):
        calc = free_cash_flow(None, CAPEX_FY2024)
        assert calc.value is None
        assert calc.note is not None

    def test_missing_capex(self):
        calc = free_cash_flow(OCF_FY2024, None)
        assert calc.value is None


class TestEbitda:
    def test_basic(self):
        calc = ebitda(100.0, 20.0)
        assert calc.value == pytest.approx(120.0)
        assert calc.note is None

    def test_missing(self):
        assert ebitda(None, 20.0).value is None
        assert ebitda(100.0, None).value is None
