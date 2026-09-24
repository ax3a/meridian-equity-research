"""Fixtures for the financial_engine test suite.

FY2024 figures for Microsoft (revenue, gross_profit, operating_income, net_income, eps_diluted,
operating_cash_flow, capex) are the real reported 10-K numbers named in the implementation plan.
FY2022/FY2023 revenue (used only for growth-rate baselines) are also real reported figures.
All other supplementary line items (balance-sheet detail, R&D, D&A, shares outstanding, quarterly
splits) are clean, deliberately round synthetic numbers -- the plan does not mandate real values for
them, and round numbers make the expected results easy to hand-verify in the tests.
"""

from __future__ import annotations

from datetime import date

import pytest

from meridian.schemas.financials import FinancialPeriod, FinancialStatements, PeriodFinancials, Quote

REVENUE_FY2022 = 198_270_000_000.0
REVENUE_FY2023 = 211_915_000_000.0
REVENUE_FY2024 = 245_122_000_000.0
GROSS_PROFIT_FY2024 = 171_008_000_000.0
OPERATING_INCOME_FY2024 = 109_433_000_000.0
NET_INCOME_FY2024 = 88_136_000_000.0
EPS_DILUTED_FY2024 = 11.80
OCF_FY2024 = 118_548_000_000.0
CAPEX_FY2024 = 44_477_000_000.0
FCF_FY2024 = 74_071_000_000.0  # OCF - capex, named explicitly in the plan


def _period(label: str, fiscal_year: int, month: int, day: int) -> FinancialPeriod:
    return FinancialPeriod(
        label=label,
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        period_end=date(fiscal_year, month, day),
        form="10-K",
    )


@pytest.fixture
def fy2022() -> PeriodFinancials:
    return PeriodFinancials(period=_period("FY2022", 2022, 6, 30), revenue=REVENUE_FY2022)


@pytest.fixture
def fy2023() -> PeriodFinancials:
    return PeriodFinancials(
        period=_period("FY2023", 2023, 6, 30),
        revenue=REVENUE_FY2023,
        gross_profit=140_000_000_000.0,
        operating_income=90_000_000_000.0,
        net_income=70_000_000_000.0,
        eps_diluted=9.50,
        research_and_development=27_000_000_000.0,
        depreciation_amortization=14_000_000_000.0,
        operating_cash_flow=90_000_000_000.0,
        capex=30_000_000_000.0,
        cash_and_equivalents=30_000_000_000.0,
        short_term_investments=70_000_000_000.0,
        current_assets=180_000_000_000.0,
        total_assets=400_000_000_000.0,
        current_liabilities=100_000_000_000.0,
        total_liabilities=200_000_000_000.0,
        long_term_debt=40_000_000_000.0,
        current_debt=8_000_000_000.0,
        shareholders_equity=200_000_000_000.0,
        shares_outstanding=7_450_000_000.0,
    )


@pytest.fixture
def fy2024() -> PeriodFinancials:
    return PeriodFinancials(
        period=_period("FY2024", 2024, 6, 30),
        revenue=REVENUE_FY2024,
        gross_profit=GROSS_PROFIT_FY2024,
        operating_income=OPERATING_INCOME_FY2024,
        net_income=NET_INCOME_FY2024,
        eps_diluted=EPS_DILUTED_FY2024,
        research_and_development=29_500_000_000.0,
        depreciation_amortization=22_000_000_000.0,
        operating_cash_flow=OCF_FY2024,
        capex=CAPEX_FY2024,
        cash_and_equivalents=20_000_000_000.0,
        short_term_investments=55_000_000_000.0,
        current_assets=125_000_000_000.0,
        total_assets=500_000_000_000.0,
        current_liabilities=100_000_000_000.0,
        total_liabilities=200_000_000_000.0,
        long_term_debt=42_000_000_000.0,
        current_debt=8_000_000_000.0,
        shareholders_equity=300_000_000_000.0,
        shares_outstanding=7_400_000_000.0,
    )


@pytest.fixture
def msft_statements(fy2022, fy2023, fy2024) -> FinancialStatements:
    return FinancialStatements(ticker="MSFT", annual=[fy2022, fy2023, fy2024])


@pytest.fixture
def msft_quote() -> Quote:
    return Quote(ticker="MSFT", price=400.0, as_of=date(2024, 7, 1), source_id="src_quote_1")


def _quarter(label: str, fiscal_year: int, fiscal_period, period_end: date, **kwargs) -> PeriodFinancials:
    return PeriodFinancials(
        period=FinancialPeriod(
            label=label,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            period_end=period_end,
            form="10-Q",
        ),
        **kwargs,
    )


@pytest.fixture
def msft_quarterly() -> list[PeriodFinancials]:
    """8 consecutive quarters (MSFT-style fiscal year ending June 30): FY2023 Q1-Q4 (prior TTM)
    then FY2024 Q1-Q4 (current TTM)."""
    prior = [
        _quarter("FY2023Q1", 2023, "Q1", date(2022, 9, 30), revenue=50_000_000_000.0, eps_diluted=2.35),
        _quarter("FY2023Q2", 2023, "Q2", date(2022, 12, 31), revenue=52_000_000_000.0, eps_diluted=2.40),
        _quarter("FY2023Q3", 2023, "Q3", date(2023, 3, 31), revenue=54_000_000_000.0, eps_diluted=2.45),
        _quarter("FY2023Q4", 2023, "Q4", date(2023, 6, 30), revenue=56_000_000_000.0, eps_diluted=2.30),
    ]
    current = [
        _quarter(
            "FY2024Q1",
            2024,
            "Q1",
            date(2023, 9, 30),
            revenue=60_000_000_000.0,
            gross_profit=42_000_000_000.0,
            operating_income=26_000_000_000.0,
            net_income=22_000_000_000.0,
            eps_diluted=2.90,
            operating_cash_flow=30_000_000_000.0,
            capex=10_000_000_000.0,
            research_and_development=7_000_000_000.0,
            depreciation_amortization=5_000_000_000.0,
        ),
        _quarter(
            "FY2024Q2",
            2024,
            "Q2",
            date(2023, 12, 31),
            revenue=62_000_000_000.0,
            gross_profit=43_000_000_000.0,
            operating_income=27_000_000_000.0,
            net_income=21_000_000_000.0,
            eps_diluted=2.80,
            operating_cash_flow=28_000_000_000.0,
            capex=11_000_000_000.0,
            research_and_development=7_200_000_000.0,
            depreciation_amortization=5_200_000_000.0,
        ),
        _quarter(
            "FY2024Q3",
            2024,
            "Q3",
            date(2024, 3, 31),
            revenue=64_000_000_000.0,
            gross_profit=44_000_000_000.0,
            operating_income=27_500_000_000.0,
            net_income=21_900_000_000.0,
            eps_diluted=2.94,
            operating_cash_flow=31_000_000_000.0,
            capex=11_500_000_000.0,
            research_and_development=7_300_000_000.0,
            depreciation_amortization=5_500_000_000.0,
        ),
        _quarter(
            "FY2024Q4",
            2024,
            "Q4",
            date(2024, 6, 30),
            revenue=66_000_000_000.0,
            gross_profit=45_000_000_000.0,
            operating_income=28_000_000_000.0,
            net_income=22_500_000_000.0,
            eps_diluted=3.00,
            operating_cash_flow=32_000_000_000.0,
            capex=12_000_000_000.0,
            research_and_development=7_400_000_000.0,
            depreciation_amortization=5_600_000_000.0,
        ),
    ]
    return prior + current
