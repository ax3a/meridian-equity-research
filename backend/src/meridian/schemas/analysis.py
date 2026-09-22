"""Structured payloads produced by specialist agents and the critic."""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.schemas.enums import AgentName, CriticIssueType, Severity, Verdict
from meridian.schemas.research import CompanyIdentity


class ValuationMultiple(BaseModel):
    name: str  # "pe", "ev_ebitda", "ev_sales", "price_sales", "price_fcf"
    label: str  # "P/E (TTM)"
    value: float | None
    peer_median: float | None = None
    historical_median: float | None = None
    basis: str  # which period/inputs
    note: str | None = None


class DCFAssumptions(BaseModel):
    base_revenue: float
    revenue_growth: list[float]  # per projection year, decimal
    fcf_margin: float
    discount_rate: float
    terminal_growth: float
    net_cash: float  # cash + ST investments - debt
    shares_outstanding: float
    rationale: list[str] = Field(default_factory=list)


class DCFResult(BaseModel):
    assumptions: DCFAssumptions
    projected_fcf: list[float]
    present_value_fcf: float
    terminal_value: float
    present_value_terminal: float
    enterprise_value: float
    equity_value: float
    value_per_share: float
    current_price: float | None = None
    upside_pct: float | None = None
    sensitivity: list[dict[str, float]] = Field(default_factory=list)  # {discount_rate, terminal_growth, value}


class ValuationResult(BaseModel):
    ticker: str
    price: float | None
    price_as_of: str | None
    market_cap: float | None
    enterprise_value: float | None
    multiples: list[ValuationMultiple] = Field(default_factory=list)
    dcf: DCFResult | None = None
    methodology_notes: list[str] = Field(default_factory=list)


class PeerSnapshot(BaseModel):
    company: CompanyIdentity
    is_target: bool = False
    selection_reason: str = ""
    fiscal_period: str | None = None
    revenue: float | None = None
    revenue_growth: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    market_cap: float | None = None
    pe: float | None = None
    ev_sales: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class PeerComparison(BaseModel):
    target_ticker: str
    selection_method: str
    peers: list[PeerSnapshot] = Field(default_factory=list)  # includes the target row (is_target=True)


class CriticIssue(BaseModel):
    agent: AgentName
    finding_id: str | None = None
    issue_type: CriticIssueType
    severity: Severity
    description: str
    suggested_fix: str | None = None


class SectionReview(BaseModel):
    agent: AgentName
    verdict: Verdict
    issues: list[CriticIssue] = Field(default_factory=list)


class CriticReview(BaseModel):
    round: int
    overall_verdict: Verdict
    summary: str
    reviews: list[SectionReview] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)

    def agents_needing_revision(self) -> list[AgentName]:
        return [r.agent for r in self.reviews if r.verdict != Verdict.APPROVED]
