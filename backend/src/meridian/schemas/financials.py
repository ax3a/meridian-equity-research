from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

MetricUnit = Literal["USD", "USD/share", "shares", "ratio", "percent", "x", "years"]

# Canonical line items. Values are raw USD (not thousands/millions) except EPS (USD/share) and shares.
LINE_ITEMS: tuple[str, ...] = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "research_and_development",
    "operating_income",
    "interest_expense",
    "income_tax_expense",
    "net_income",
    "eps_basic",
    "eps_diluted",
    "shares_diluted",
    "depreciation_amortization",
    "operating_cash_flow",
    "capex",
    "cash_and_equivalents",
    "short_term_investments",
    "current_assets",
    "total_assets",
    "current_liabilities",
    "total_liabilities",
    "long_term_debt",
    "current_debt",
    "shareholders_equity",
    "shares_outstanding",
)


class FinancialPeriod(BaseModel):
    label: str  # "FY2024" or "FY2025Q2"
    fiscal_year: int
    fiscal_period: Literal["FY", "Q1", "Q2", "Q3", "Q4"]
    period_end: date
    form: str | None = None
    accession_number: str | None = None
    filed: date | None = None


class PeriodFinancials(BaseModel):
    period: FinancialPeriod
    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    research_and_development: float | None = None
    operating_income: float | None = None
    interest_expense: float | None = None
    income_tax_expense: float | None = None
    net_income: float | None = None
    eps_basic: float | None = None
    eps_diluted: float | None = None
    shares_diluted: float | None = None
    depreciation_amortization: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None  # stored as a positive outflow
    cash_and_equivalents: float | None = None
    short_term_investments: float | None = None
    current_assets: float | None = None
    total_assets: float | None = None
    current_liabilities: float | None = None
    total_liabilities: float | None = None
    long_term_debt: float | None = None
    current_debt: float | None = None
    shareholders_equity: float | None = None
    shares_outstanding: float | None = None
    # line item -> evidence id that supports the value
    evidence_ids: dict[str, str] = Field(default_factory=dict)

    def value(self, item: str) -> float | None:
        v = getattr(self, item, None)
        return v if isinstance(v, int | float) else None


class FinancialStatements(BaseModel):
    ticker: str
    currency: str = "USD"
    annual: list[PeriodFinancials] = Field(default_factory=list)  # ascending by period_end
    quarterly: list[PeriodFinancials] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)

    def latest_annual(self) -> PeriodFinancials | None:
        return self.annual[-1] if self.annual else None


class MetricValue(BaseModel):
    """A deterministic, traceable calculation result."""

    key: str  # e.g. "gross_margin"
    period: str  # e.g. "FY2024", "TTM", "current"
    value: float | None
    unit: MetricUnit
    formula: str
    inputs: dict[str, float | None] = Field(default_factory=dict)
    note: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.period}.{self.key}"


class FinancialMetrics(BaseModel):
    ticker: str
    periods: list[str] = Field(default_factory=list)
    values: dict[str, MetricValue] = Field(default_factory=dict)  # keyed by MetricValue.ref

    def add(self, metric: MetricValue) -> None:
        self.values[metric.ref] = metric
        if metric.period not in self.periods:
            self.periods.append(metric.period)

    def get(self, period: str, key: str) -> MetricValue | None:
        return self.values.get(f"{period}.{key}")

    def series(self, key: str) -> list[MetricValue]:
        return [m for m in self.values.values() if m.key == key]


class PricePoint(BaseModel):
    day: date
    close: float
    volume: float | None = None


class Quote(BaseModel):
    ticker: str
    price: float
    as_of: date
    currency: str = "USD"
    source_id: str
    history: list[PricePoint] = Field(default_factory=list)
