"""A bull case must never be argued from risk factors, and claims must read as sentences.

Both defects came from the first real Microsoft run: the bull case quoted Item 1A risk passages (they
mention "cash", "growth" and "expand" often enough to win a keyword-only ranking) and every narrative
claim was a raw retrieved chunk ending mid-word.
"""

from __future__ import annotations

from meridian.agents.claims import clean_passage, describe_claim, summarize_passage
from meridian.agents.stance import bear_candidates, bull_candidates, rank_by_stance
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.financials import FinancialMetrics, MetricValue
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchRequest
from meridian.schemas.state import ResearchState

RISK_PASSAGE = (
    "[risk factors] RISK RISKS We are exposed to economic risk from foreign exchange rates, interest rates, "
    "credit risk, and equity prices. We use derivative instruments to manage these risks, however, they may "
    "still impact our consolidated financial statements. Our cash and investments could grow or expand in "
    "ways that are adverse. Pr"
)


def _finding(agent: AgentName, section: ReportSection, claim: str, **kw) -> Finding:
    kw.setdefault("kind", FindingKind.FACT)
    kw.setdefault("evidence_ids", ["ev_1"])
    return Finding(agent=agent, section=section, claim=claim, confidence=Confidence.MEDIUM, **kw)


def _state(findings: list[Finding], metrics: FinancialMetrics | None = None) -> ResearchState:
    from meridian.schemas.enums import TaskStatus
    from meridian.schemas.findings import AgentOutput

    outputs: dict[str, AgentOutput] = {}
    for f in findings:
        out = outputs.setdefault(
            f.agent.value, AgentOutput(agent=f.agent, task_id=f"task_{f.agent.value}", status=TaskStatus.COMPLETED)
        )
        out.findings.append(f)
    return ResearchState(
        session_id="s1", request=ResearchRequest(query="Analyse Test"), outputs=outputs, metrics=metrics
    )


def test_risk_factors_are_never_bull_candidates():
    risk = _finding(AgentName.RISK, ReportSection.KEY_RISKS, RISK_PASSAGE)
    growth = _finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_TRENDS,
        "Revenue growth for FY2026 is 17.8%.",
        kind=FindingKind.CALCULATED,
        evidence_ids=[],
        metric_refs=["FY2026.revenue_growth"],
    )
    state = _state([risk, growth])

    candidates = bull_candidates(state)

    assert risk not in candidates
    assert growth in candidates
    assert risk in bear_candidates(state)


def test_growth_metric_outranks_keyword_heavy_risk_text_for_the_bull_case():
    metrics = FinancialMetrics(ticker="TST")
    metrics.add(
        MetricValue(
            key="revenue_growth", period="FY2026", value=0.178, unit="ratio", formula="(current - prior) / prior"
        )
    )
    risky_but_wordy = _finding(AgentName.FILINGS, ReportSection.RECENT_DEVELOPMENTS, RISK_PASSAGE)
    growth = _finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_TRENDS,
        "Revenue growth for FY2026 is 17.8%, an acceleration on the prior year.",
        kind=FindingKind.CALCULATED,
        evidence_ids=[],
        metric_refs=["FY2026.revenue_growth"],
    )
    state = _state([risky_but_wordy, growth], metrics)

    ranked = rank_by_stance(bull_candidates(state), stance="bull", state=state)

    assert ranked and ranked[0] is growth
    assert risky_but_wordy not in ranked  # net-negative sentiment never qualifies as a bull point


def test_a_valuation_claim_implying_downside_is_not_a_bull_point():
    downside = _finding(
        AgentName.VALUATION,
        ReportSection.VALUATION,
        "A base-case discounted cash flow model implies a fair value of $252.49 per share "
        "(49.3% downside vs. the current price).",
        kind=FindingKind.INTERPRETATION,
    )
    state = _state([downside])

    assert downside not in bull_candidates(state)


def test_summarize_passage_keeps_whole_sentences_and_never_cuts_mid_word():
    result = summarize_passage(RISK_PASSAGE, max_chars=200)

    assert result.endswith(".")
    assert "indu" not in result.split()[-1]
    assert not result.startswith("[risk factors]")
    assert len(result) <= 200


def test_clean_passage_strips_section_tag_and_leading_filing_headings():
    assert clean_passage("[risk factors] RISK RISKS We are exposed") == "We are exposed"
    # An all-caps run that is the sentence itself must survive rather than being stripped to nothing.
    assert clean_passage("NVIDIA CORPORATION") == "NVIDIA CORPORATION"


def test_describe_claim_does_not_double_the_label():
    assert describe_claim("Bull case", "Bull case: revenue grew 17.8%.") == "Bull case: revenue grew 17.8%."
    assert describe_claim("Bull case", "Revenue grew 17.8%.") == "Bull case: Revenue grew 17.8%."


def test_a_passage_starting_mid_sentence_drops_the_broken_opening():
    """Chunks are cut at token boundaries, so they often start mid-thought.

    Quoting from there produced report sentences like "successful, and we may fail to sell any
    meaningful standalone software or services."
    """
    passage = (
        "successful, and we may fail to sell any meaningful standalone software. "
        "We design and manufacture accelerated computing platforms for data centres worldwide, "
        "serving hyperscale customers across several regions."
    )

    result = summarize_passage(passage, max_chars=200)

    assert result.startswith("We design and manufacture")


def test_a_mid_sentence_start_is_kept_when_nothing_substantial_follows():
    # Dropping the fragment would leave almost nothing, so the original text is better than a stub.
    passage = "attributable to the Compute & Networking segment. Yes."

    assert summarize_passage(passage).startswith("attributable to")


def test_summarize_passage_falls_back_to_a_word_boundary_for_one_long_sentence():
    long_sentence = "The company " + "expands into new markets and " * 20 + "continues to invest"

    result = summarize_passage(long_sentence, max_chars=120)

    assert result.endswith("...")
    assert len(result) <= 123
    assert not result[:-3].endswith(" ")
