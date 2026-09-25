"""Selecting which existing findings support a bull or a bear thesis.

Keyword scoring alone is not enough: a risk-factor passage mentions "cash", "growth" and "expand" often
enough to outrank a genuine growth metric, which is how a bull case ends up arguing from Item 1A. Selection
therefore combines three signals — the report section a finding came from, the direction of the metric it
cites, and sentiment keywords — and requires a net-positive (or net-negative) score to qualify at all.
"""

from __future__ import annotations

from meridian.schemas.enums import AgentName, FindingKind, ReportSection
from meridian.schemas.findings import Finding
from meridian.schemas.state import ResearchState

Stance = str  # "bull" | "bear"

# Sections that inherently argue one way. A risk factor is never a bull point.
_BEARISH_SECTIONS = frozenset({ReportSection.KEY_RISKS})
_NEUTRAL_SECTIONS = frozenset(
    {
        ReportSection.COMPANY_OVERVIEW,
        ReportSection.BUSINESS_MODEL,
        ReportSection.FINANCIAL_PERFORMANCE,
        ReportSection.FINANCIAL_TRENDS,
        ReportSection.KEY_RATIOS,
        ReportSection.RECENT_DEVELOPMENTS,
        ReportSection.INDUSTRY_COMPETITION,
        ReportSection.VALUATION,
        ReportSection.MACRO,
    }
)

_POSITIVE_WORDS = (
    "growth",
    "grew",
    "increase",
    "increased",
    "expansion",
    "expanded",
    "strong",
    "record",
    "beat",
    "upside",
    "opportunity",
    "leadership",
    "leading",
    "moat",
    "advantage",
    "accelerat",
    "improv",
    "outperform",
    "margin expansion",
    "free cash flow generation",
)
_NEGATIVE_WORDS = (
    "risk",
    "decline",
    "declined",
    "decrease",
    "weak",
    "loss",
    "litigation",
    "lawsuit",
    "investigation",
    "regulat",
    "competition",
    "competitive pressure",
    "headwind",
    "uncertain",
    "adverse",
    "impair",
    "downside",
    "shortfall",
    "disrupt",
    "tariff",
    "sanction",
    "breach",
    "outage",
    "concentration",
    "dependence",
    "exposed to",
    "may be unable",
    "could harm",
)

# Metrics whose direction carries a thesis: (metric key, "higher is bullish")
_DIRECTIONAL_METRICS: dict[str, bool] = {
    "revenue_growth": True,
    "revenue_cagr_3y": True,
    "revenue_cagr_5y": True,
    "eps_growth": True,
    "gross_margin": True,
    "operating_margin": True,
    "net_margin": True,
    "fcf_margin": True,
    "free_cash_flow": True,
    "roe": True,
    "roa": True,
    "net_cash": True,
    "current_ratio": True,
    "debt_to_equity": False,
    "pe": False,
    "ev_ebitda": False,
    "price_fcf": False,
    "ev_sales": False,
    "price_sales": False,
}


def _keyword_score(text: str) -> int:
    lowered = text.lower()
    return sum(lowered.count(w) for w in _POSITIVE_WORDS) - sum(lowered.count(w) for w in _NEGATIVE_WORDS)


def _metric_score(finding: Finding, state: ResearchState) -> int:
    """+1 when the cited metric points the bullish way, -1 when it points the bearish way."""
    if not finding.metric_refs or state.metrics is None:
        return 0
    score = 0
    for ref in finding.metric_refs:
        metric = state.metrics.values.get(ref)
        if metric is None or metric.value is None or metric.key not in _DIRECTIONAL_METRICS:
            continue
        higher_is_better = _DIRECTIONAL_METRICS[metric.key]
        if metric.key in ("revenue_growth", "eps_growth", "revenue_cagr_3y", "revenue_cagr_5y", "net_cash"):
            positive = metric.value > 0
        elif metric.key == "debt_to_equity":
            positive = metric.value < 1.0
        elif metric.key == "current_ratio":
            positive = metric.value > 1.0
        else:
            positive = higher_is_better
        score += 1 if positive == higher_is_better or positive else -1
    return score


def stance_score(finding: Finding, state: ResearchState, *, stance: Stance) -> int:
    """How strongly a finding argues the given stance. Section membership dominates keyword noise."""
    score = _keyword_score(finding.claim) + 2 * _metric_score(finding, state)
    if finding.section in _BEARISH_SECTIONS:
        score -= 6
    if finding.kind == FindingKind.CALCULATED:
        score += 1  # a computed figure is stronger evidence than narrative text
    return score if stance == "bull" else -score


def _base_candidates(state: ResearchState) -> list[Finding]:
    return [
        f
        for f in state.findings()
        if f.agent not in (AgentName.BULL, AgentName.BEAR) and (f.evidence_ids or f.metric_refs)
    ]


def bull_candidates(state: ResearchState) -> list[Finding]:
    """Findings eligible for a bull case: never risk factors, and never a valuation point implying downside."""
    return [
        f for f in _base_candidates(state) if f.section not in _BEARISH_SECTIONS and not _implies_downside(f, state)
    ]


def bear_candidates(state: ResearchState) -> list[Finding]:
    return [f for f in _base_candidates(state) if f.section in _BEARISH_SECTIONS or f.section in _NEUTRAL_SECTIONS]


def _implies_downside(finding: Finding, state: ResearchState) -> bool:
    """A DCF or valuation claim stating downside is a bear point however positively it is worded."""
    lowered = finding.claim.lower()
    if "downside" in lowered:
        return True
    if state.valuation and state.valuation.dcf and finding.section == ReportSection.VALUATION:
        upside = state.valuation.dcf.upside_pct
        return upside is not None and upside < 0
    return False


def rank_by_stance(candidates: list[Finding], *, stance: Stance, state: ResearchState | None = None) -> list[Finding]:
    """Highest-scoring findings first, keeping only those that actually argue the stance."""
    if state is None:  # scoring without state still works, just without metric direction
        scored = [(_keyword_score(f.claim) * (1 if stance == "bull" else -1), f) for f in candidates]
    else:
        scored = [(stance_score(f, state, stance=stance), f) for f in candidates]
    qualifying = [(score, f) for score, f in scored if score > 0]
    qualifying.sort(key=lambda pair: pair[0], reverse=True)
    return [f for _, f in qualifying]
