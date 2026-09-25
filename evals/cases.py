"""Benchmark research requests, each with what a correct run should look like.

Cases deliberately cover awkward shapes as well as easy ones: different fiscal calendars, a bank whose
margins and EV multiples are not meaningful, a request phrased as a sentence with a focus clause, an
acronym that collides with a real ticker, and a company that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from meridian.schemas.enums import AgentName, ReportSection
from meridian.schemas.research import Depth

CORE_AGENTS = {AgentName.COMPANY, AgentName.FINANCIALS, AgentName.FILINGS}


@dataclass(frozen=True)
class EvalCase:
    key: str
    query: str
    why: str
    ticker: str | None = None
    depth: Depth = "standard"
    expected_ticker: str | None = None
    expected_agents: set[AgentName] = field(default_factory=lambda: set(CORE_AGENTS))
    forbidden_agents: set[AgentName] = field(default_factory=set)
    expect_failure: bool = False
    # Metrics that must be absent rather than wrong (banks have no meaningful gross margin).
    expect_absent_metrics: tuple[str, ...] = ()
    # Sections expected at this depth; None means the standard set. Quick depth drops the bull/bear cases
    # by design, so scoring it against the standard list would measure the metric, not the system.
    required_sections: tuple[ReportSection, ...] | None = None


CASES: tuple[EvalCase, ...] = (
    EvalCase(
        key="msft",
        query="Analyse Microsoft",
        why="Baseline large cap with a June fiscal year end and a long filing history.",
        expected_ticker="MSFT",
        expected_agents=CORE_AGENTS | {AgentName.VALUATION, AgentName.RISK, AgentName.BULL, AgentName.BEAR},
    ),
    EvalCase(
        key="nvda_focus",
        query="Analyse NVIDIA with particular attention to AI infrastructure growth, margins and valuation",
        why=(
            "Natural-language request with a focus clause, and an acronym (AI) that is also a real ticker: "
            "a regression guard for the run that researched C3.ai instead of NVIDIA."
        ),
        expected_ticker="NVDA",
        expected_agents=CORE_AGENTS | {AgentName.VALUATION, AgentName.COMPETITORS},
    ),
    EvalCase(
        key="aapl",
        query="Analyse Apple",
        why="September fiscal year end; checks fiscal-period labelling on a different calendar.",
        expected_ticker="AAPL",
    ),
    EvalCase(
        key="jpm_bank",
        query="Analyse JPMorgan Chase",
        why=(
            "A bank: gross margin and EV multiples are not meaningful and must be absent with a stated "
            "reason rather than computed as a misleading number."
        ),
        expected_ticker="JPM",
        expect_absent_metrics=("gross_margin", "ev_ebitda", "ev_sales"),
    ),
    EvalCase(
        key="quick_depth",
        query="Analyse Microsoft",
        ticker="MSFT",
        depth="quick",
        why="Quick depth must prune the plan rather than run everything.",
        expected_ticker="MSFT",
        expected_agents=set(CORE_AGENTS),
        forbidden_agents={AgentName.MACRO},
        required_sections=(
            ReportSection.EXECUTIVE_SUMMARY,
            ReportSection.COMPANY_OVERVIEW,
            ReportSection.FINANCIAL_PERFORMANCE,
            ReportSection.KEY_RISKS,
        ),
    ),
    EvalCase(
        key="unknown_company",
        query="Analyse Nonexistent Fabricated Holdings Ltd",
        why="Must fail cleanly with a resolution error naming what it tried, not crash or invent a company.",
        expect_failure=True,
    ),
)

BY_KEY = {case.key: case for case in CASES}
