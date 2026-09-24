from __future__ import annotations

from datetime import date

import pytest
from tests.unit.financial_engine.conftest import (
    FCF_FY2024,
    GROSS_PROFIT_FY2024,
    NET_INCOME_FY2024,
    REVENUE_FY2023,
    REVENUE_FY2024,
)

from meridian.core.errors import ValidationFailedError
from meridian.financial_engine.metrics import calculate, compute_metrics
from meridian.schemas.financials import FinancialPeriod, FinancialStatements, PeriodFinancials, Quote


class TestComputeMetricsAnnual:
    def test_revenue_passthrough(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "revenue")
        assert mv is not None
        assert mv.value == pytest.approx(REVENUE_FY2024)
        assert mv.unit == "USD"

    def test_revenue_growth_fy2024(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "revenue_growth")
        assert mv.value == pytest.approx((REVENUE_FY2024 - REVENUE_FY2023) / REVENUE_FY2023, rel=1e-9)
        assert mv.value == pytest.approx(0.15675, rel=1e-3)
        assert mv.unit == "ratio"

    def test_revenue_growth_first_period_is_none(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2022", "revenue_growth")
        assert mv.value is None
        assert mv.note is not None

    def test_gross_margin_fy2024(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "gross_margin")
        assert mv.value == pytest.approx(GROSS_PROFIT_FY2024 / REVENUE_FY2024, rel=1e-6)
        assert mv.value == pytest.approx(0.69764, rel=1e-4)

    def test_free_cash_flow_fy2024(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "free_cash_flow")
        assert mv.value == pytest.approx(FCF_FY2024, rel=1e-9)
        assert mv.unit == "USD"

    def test_fcf_margin_fy2024(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "fcf_margin")
        assert mv.value == pytest.approx(FCF_FY2024 / REVENUE_FY2024, rel=1e-9)

    def test_ebitda_fy2024(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "ebitda")
        # fy2024 fixture: operating_income + depreciation_amortization
        assert mv.value == pytest.approx(109_433_000_000.0 + 22_000_000_000.0)

    def test_roa_uses_average_when_two_periods_exist(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "roa")
        expected = 88_136_000_000.0 / ((500_000_000_000.0 + 400_000_000_000.0) / 2)
        assert mv.value == pytest.approx(expected)
        assert "average" in mv.formula.lower()

    def test_roa_uses_ending_basis_when_prior_period_has_no_assets(self, msft_statements):
        # FY2023's prior period (FY2022) only has revenue set, so the average basis is
        # unavailable and roa must fall back to the ending-balance basis.
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2023", "roa")
        expected = 70_000_000_000.0 / 400_000_000_000.0
        assert mv.value == pytest.approx(expected)
        assert "ending" in mv.formula.lower()

    def test_roa_none_when_period_has_no_data_at_all(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2022", "roa")
        # FY2022 fixture only has revenue -> total_assets missing entirely -> None value.
        assert mv.value is None

    def test_roe_first_period_uses_ending_basis(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2023", "roe")
        expected = 70_000_000_000.0 / 200_000_000_000.0
        assert mv.value == pytest.approx(expected)
        assert "ending" in mv.formula.lower()

    def test_current_ratio(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "current_ratio")
        assert mv.value == pytest.approx(125_000_000_000.0 / 100_000_000_000.0)

    def test_debt_to_equity(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("FY2024", "debt_to_equity")
        assert mv.value == pytest.approx(50_000_000_000.0 / 300_000_000_000.0)

    def test_total_debt_and_net_cash(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        td = metrics.get("FY2024", "total_debt")
        assert td.value == pytest.approx(50_000_000_000.0)
        nc = metrics.get("FY2024", "net_cash")
        assert nc.value == pytest.approx(75_000_000_000.0 - 50_000_000_000.0)

    def test_periods_list_populated(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        assert "FY2022" in metrics.periods
        assert "FY2023" in metrics.periods
        assert "FY2024" in metrics.periods


class TestComputeMetricsCagr:
    def test_insufficient_history_for_3y_and_5y(self, msft_statements):
        # fixture only has 3 annual periods -- neither CAGR is computable.
        metrics = compute_metrics(msft_statements)
        cagr3 = metrics.get("FY2024", "revenue_cagr_3y")
        cagr5 = metrics.get("FY2024", "revenue_cagr_5y")
        assert cagr3.value is None
        assert cagr3.note is not None
        assert cagr5.value is None
        assert cagr5.note is not None

    def test_3y_cagr_computed_with_enough_history(self):
        periods = []
        base_revenue = 100.0
        for i, year in enumerate(range(2021, 2025)):
            periods.append(
                PeriodFinancials(
                    period=FinancialPeriod(
                        label=f"FY{year}",
                        fiscal_year=year,
                        fiscal_period="FY",
                        period_end=date(year, 6, 30),
                    ),
                    revenue=base_revenue * (1.10**i),
                )
            )
        statements = FinancialStatements(ticker="TEST", annual=periods)
        metrics = compute_metrics(statements)
        mv = metrics.get("FY2024", "revenue_cagr_3y")
        expected = (periods[-1].revenue / periods[0].revenue) ** (1 / 3) - 1
        assert mv.value == pytest.approx(expected, rel=1e-9)
        assert mv.value == pytest.approx(0.10, rel=1e-6)

    def test_single_period_cagr_is_none(self):
        statements = FinancialStatements(
            ticker="TEST",
            annual=[
                PeriodFinancials(
                    period=FinancialPeriod(
                        label="FY2024", fiscal_year=2024, fiscal_period="FY", period_end=date(2024, 6, 30)
                    ),
                    revenue=100.0,
                )
            ],
        )
        metrics = compute_metrics(statements)
        assert metrics.get("FY2024", "revenue_cagr_3y").value is None
        assert metrics.get("FY2024", "revenue_cagr_5y").value is None


class TestComputeMetricsAllNonePeriod:
    def test_all_none_period_never_raises(self):
        statements = FinancialStatements(
            ticker="TEST",
            annual=[
                PeriodFinancials(
                    period=FinancialPeriod(
                        label="FY2024", fiscal_year=2024, fiscal_period="FY", period_end=date(2024, 6, 30)
                    )
                )
            ],
        )
        metrics = compute_metrics(statements)
        mv = metrics.get("FY2024", "revenue")
        assert mv.value is None
        assert mv.note is not None
        mv_margin = metrics.get("FY2024", "gross_margin")
        assert mv_margin.value is None

    def test_empty_statements_never_raises(self):
        statements = FinancialStatements(ticker="TEST")
        metrics = compute_metrics(statements)
        assert metrics.values == {}


class TestFinancialInstitutionFlag:
    def test_skips_gross_margin(self, msft_statements):
        metrics = compute_metrics(msft_statements, is_financial_institution=True)
        mv = metrics.get("FY2024", "gross_margin")
        assert mv.value is None
        assert mv.note == "not meaningful for financial institutions"

    def test_skips_ev_multiples(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote, is_financial_institution=True)
        ev_sales = metrics.get("current", "ev_sales")
        ev_ebitda = metrics.get("current", "ev_ebitda")
        assert ev_sales.value is None
        assert ev_sales.note == "not meaningful for financial institutions"
        assert ev_ebitda.value is None
        assert ev_ebitda.note == "not meaningful for financial institutions"

    def test_non_bank_gross_margin_still_computed(self, msft_statements):
        metrics = compute_metrics(msft_statements, is_financial_institution=False)
        mv = metrics.get("FY2024", "gross_margin")
        assert mv.value is not None


class TestComputeMetricsMarket:
    def test_no_quote_means_no_market_metrics(self, msft_statements):
        metrics = compute_metrics(msft_statements)
        assert metrics.get("current", "market_cap") is None
        assert metrics.get("current", "pe") is None

    def test_market_cap(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote)
        mv = metrics.get("current", "market_cap")
        assert mv.value == pytest.approx(400.0 * 7_400_000_000.0)
        assert mv.unit == "USD"

    def test_enterprise_value(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote)
        mv = metrics.get("current", "enterprise_value")
        expected = (400.0 * 7_400_000_000.0) + 50_000_000_000.0 - 20_000_000_000.0 - 55_000_000_000.0
        assert mv.value == pytest.approx(expected)

    def test_pe_uses_latest_annual_when_no_ttm(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote)
        mv = metrics.get("current", "pe")
        assert mv.value == pytest.approx(400.0 / 11.80)
        assert mv.unit == "x"

    def test_pe_negative_eps_not_meaningful(self, msft_statements, msft_quote):
        msft_statements.annual[-1].eps_diluted = -1.0
        metrics = compute_metrics(msft_statements, msft_quote)
        mv = metrics.get("current", "pe")
        assert mv.value is None
        assert mv.note == "not meaningful (negative or zero denominator)"

    def test_price_sales(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote)
        mc = 400.0 * 7_400_000_000.0
        mv = metrics.get("current", "price_sales")
        assert mv.value == pytest.approx(mc / REVENUE_FY2024)

    def test_fcf_yield(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote)
        mc = 400.0 * 7_400_000_000.0
        mv = metrics.get("current", "fcf_yield")
        assert mv.value == pytest.approx(FCF_FY2024 / mc)

    def test_earnings_yield(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote)
        mc = 400.0 * 7_400_000_000.0
        mv = metrics.get("current", "earnings_yield")
        assert mv.value == pytest.approx(NET_INCOME_FY2024 / mc)

    def test_ev_sales_and_ev_ebitda(self, msft_statements, msft_quote):
        metrics = compute_metrics(msft_statements, msft_quote)
        ev = metrics.get("current", "enterprise_value").value
        ev_sales = metrics.get("current", "ev_sales")
        assert ev_sales.value == pytest.approx(ev / REVENUE_FY2024)
        ebitda_val = 109_433_000_000.0 + 22_000_000_000.0
        ev_ebitda = metrics.get("current", "ev_ebitda")
        assert ev_ebitda.value == pytest.approx(ev / ebitda_val)


class TestComputeMetricsTTM:
    def test_ttm_revenue_is_sum_of_last_four_quarters(self, msft_statements, msft_quarterly):
        msft_statements.quarterly = msft_quarterly
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("TTM", "revenue")
        expected = 60e9 + 62e9 + 64e9 + 66e9
        assert mv.value == pytest.approx(expected)

    def test_ttm_growth_uses_prior_four_quarters(self, msft_statements, msft_quarterly):
        msft_statements.quarterly = msft_quarterly
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("TTM", "revenue_growth")
        current = 60e9 + 62e9 + 64e9 + 66e9
        prior = 50e9 + 52e9 + 54e9 + 56e9
        assert mv.value == pytest.approx((current - prior) / prior)

    def test_ttm_not_produced_with_fewer_than_four_quarters(self, msft_statements, msft_quarterly):
        msft_statements.quarterly = msft_quarterly[-3:]
        metrics = compute_metrics(msft_statements)
        assert metrics.get("TTM", "revenue") is None

    def test_ttm_not_produced_when_quarters_not_consecutive(self, msft_statements, msft_quarterly):
        gappy = msft_quarterly[-4:]
        # push the last quarter's period_end far into the future so the gap check fails.
        gappy[-1] = gappy[-1].model_copy(
            update={"period": gappy[-1].period.model_copy(update={"period_end": date(2025, 6, 30)})}
        )
        msft_statements.quarterly = gappy
        metrics = compute_metrics(msft_statements)
        assert metrics.get("TTM", "revenue") is None

    def test_ttm_growth_none_without_eight_quarters(self, msft_statements, msft_quarterly):
        msft_statements.quarterly = msft_quarterly[-4:]
        metrics = compute_metrics(msft_statements)
        mv = metrics.get("TTM", "revenue_growth")
        assert mv.value is None

    def test_market_metrics_prefer_ttm_when_available(self, msft_statements, msft_quarterly, msft_quote):
        msft_statements.quarterly = msft_quarterly
        metrics = compute_metrics(msft_statements, msft_quote)
        mv = metrics.get("current", "pe")
        ttm_eps = 2.90 + 2.80 + 2.94 + 3.00
        assert mv.value == pytest.approx(400.0 / ttm_eps)


class TestCalculate:
    def test_unknown_metric_raises(self):
        with pytest.raises(ValidationFailedError):
            calculate("not_a_real_metric", {})

    def test_gross_margin(self):
        mv = calculate("gross_margin", {"gross_profit": 171.0, "revenue": 245.0}, period="FY2024")
        assert mv.value == pytest.approx(171.0 / 245.0)
        assert mv.period == "FY2024"
        assert mv.key == "gross_margin"
        assert mv.unit == "ratio"

    def test_default_period_is_custom(self):
        mv = calculate("revenue", {"revenue": 100.0})
        assert mv.period == "custom"

    def test_free_cash_flow(self):
        mv = calculate("free_cash_flow", {"operating_cash_flow": 118.5, "capex": 44.5})
        assert mv.value == pytest.approx(74.0)
        assert mv.unit == "USD"

    def test_pe_not_meaningful(self):
        mv = calculate("pe", {"price": 400.0, "eps_diluted": -1.0})
        assert mv.value is None
        assert mv.note == "not meaningful (negative or zero denominator)"

    def test_missing_data_returns_none_value_not_raise(self):
        mv = calculate("gross_margin", {})
        assert mv.value is None
        assert mv.note is not None

    def test_market_cap(self):
        mv = calculate("market_cap", {"price": 400.0, "shares_outstanding": 1_000_000.0})
        assert mv.value == pytest.approx(400_000_000.0)
        assert mv.unit == "USD"

    def test_enterprise_value(self):
        mv = calculate(
            "enterprise_value",
            {
                "price": 10.0,
                "shares_outstanding": 100.0,
                "long_term_debt": 50.0,
                "current_debt": 10.0,
                "cash_and_equivalents": 20.0,
                "short_term_investments": 5.0,
            },
        )
        assert mv.value == pytest.approx(1000.0 + 60.0 - 20.0 - 5.0)

    def test_revenue_cagr_3y(self):
        mv = calculate("revenue_cagr_3y", {"end_revenue": 133.1, "start_revenue": 100.0, "years": 3})
        assert mv.value == pytest.approx(0.10, rel=1e-6)

    def test_roa_ending_basis(self):
        mv = calculate("roa", {"net_income": 88.0, "total_assets": 500.0})
        assert mv.value == pytest.approx(88.0 / 500.0)

    def test_all_metric_keys_are_dispatchable(self):
        # Every metric named in the plan must be in the registry, even if inputs are empty
        # (must return value=None with a note, never raise).
        keys = [
            "revenue",
            "revenue_growth",
            "gross_profit",
            "gross_margin",
            "operating_income",
            "operating_margin",
            "net_income",
            "net_margin",
            "eps_diluted",
            "eps_growth",
            "operating_cash_flow",
            "capex",
            "free_cash_flow",
            "fcf_margin",
            "rd_intensity",
            "ebitda",
            "ebitda_margin",
            "cash_and_investments",
            "total_debt",
            "net_cash",
            "total_assets",
            "total_liabilities",
            "shareholders_equity",
            "current_ratio",
            "debt_to_equity",
            "roa",
            "roe",
            "revenue_cagr_3y",
            "revenue_cagr_5y",
            "market_cap",
            "enterprise_value",
            "pe",
            "price_sales",
            "price_fcf",
            "ev_sales",
            "ev_ebitda",
            "fcf_yield",
            "earnings_yield",
        ]
        for key in keys:
            mv = calculate(key, {})
            assert mv.value is None
            assert mv.key == key


class TestComputeMetricsEdgeCases:
    def test_quote_with_no_statements_never_raises(self):
        statements = FinancialStatements(ticker="TEST")
        quote = Quote(ticker="TEST", price=100.0, as_of=date(2024, 1, 1), source_id="src_1")
        metrics = compute_metrics(statements, quote)
        mv = metrics.get("current", "market_cap")
        assert mv.value is None
        mv_pe = metrics.get("current", "pe")
        assert mv_pe.value is None

    def test_ttm_field_with_one_missing_quarter_is_none(self, msft_statements, msft_quarterly):
        # Blank out gross_profit on one of the four TTM quarters -- that one field must come
        # back None, while fields present in all four quarters (like revenue) still sum fine.
        msft_quarterly[-1] = msft_quarterly[-1].model_copy(update={"gross_profit": None})
        msft_statements.quarterly = msft_quarterly
        metrics = compute_metrics(msft_statements)
        assert metrics.get("TTM", "gross_profit").value is None
        assert metrics.get("TTM", "revenue").value is not None
