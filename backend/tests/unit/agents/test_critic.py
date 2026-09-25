from __future__ import annotations

from datetime import date, timedelta

from meridian.agents.critic import Critic, parse_figures, within_tolerance
from meridian.providers.llm.scripted import ScriptedLLMProvider
from meridian.schemas.enums import (
    AgentName,
    CriticIssueType,
    FindingKind,
    FindingStatus,
    ReportSection,
    Severity,
    Verdict,
)
from meridian.schemas.financials import MetricValue

from .conftest_orchestration import (
    make_company,
    make_deps,
    make_evidence,
    make_finding,
    make_metrics,
    make_output,
    make_source,
    make_state,
)


def test_parse_figures_handles_common_formats() -> None:
    assert parse_figures("$245.1B") == [245.1e9]
    assert parse_figures("245,122 million") == [245122e6]
    assert parse_figures("grew 15.7%") == [0.157]


def test_within_tolerance() -> None:
    assert within_tolerance(245.0e9, 245.1e9, rel=0.01)
    assert not within_tolerance(200.0e9, 245.1e9, rel=0.01)


async def test_critic_catches_planted_hallucination(settings) -> None:
    """A finding citing an evidence id that does not exist in the run's evidence store must be rejected."""
    company = make_company()
    finding = make_finding(
        AgentName.NEWS,
        ReportSection.RECENT_DEVELOPMENTS,
        "The company announced a new product line.",
        kind=FindingKind.FACT,
        evidence_ids=["ev_does_not_exist"],
        status=FindingStatus.APPROVED,
    )
    state = make_state(company=company, outputs=[make_output(AgentName.NEWS, [finding])])

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    hallucinations = [i for i in result.review.reviews[0].issues if i.issue_type == CriticIssueType.HALLUCINATION]
    assert hallucinations, "expected a HALLUCINATION issue for the fabricated evidence id"
    assert hallucinations[0].severity == Severity.HIGH

    updated = result.updated_outputs["news"]
    assert updated.findings[0].status == FindingStatus.REJECTED
    assert result.review.overall_verdict in (Verdict.NEEDS_REVISION, Verdict.REJECTED)
    assert "news" in result.rework_notes


async def test_critic_catches_number_disagreeing_with_metrics(settings) -> None:
    """A CALCULATED finding whose stated figure disagrees with the metrics table beyond 1% is rejected."""
    company = make_company()
    metrics = make_metrics()
    finding = make_finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "Revenue for FY2024 was $300.0B, a new record.",
        kind=FindingKind.CALCULATED,
        metric_refs=["FY2024.revenue"],
        status=FindingStatus.APPROVED,
    )
    state = make_state(company=company, metrics=metrics, outputs=[make_output(AgentName.FINANCIALS, [finding])])

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    issues = result.review.reviews[0].issues
    mismatches = [i for i in issues if i.issue_type == CriticIssueType.INCONSISTENT_FIGURE]
    assert mismatches
    assert mismatches[0].severity == Severity.HIGH
    assert result.updated_outputs["financials"].findings[0].status == FindingStatus.REJECTED


async def test_critic_approves_clean_findings(settings) -> None:
    """Findings with real evidence and metrics that agree with the table should sail through untouched."""
    company = make_company()
    metrics = make_metrics()
    source = make_source("10k", published_at=date.today())
    evidence = make_evidence(source, "Revenue was $245,122 million in FY2024.")
    fact = make_finding(
        AgentName.FILINGS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "The 10-K reports FY2024 revenue of $245,122 million.",
        kind=FindingKind.FACT,
        evidence_ids=[evidence.id],
        status=FindingStatus.APPROVED,
    )
    calculated = make_finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "FY2024 revenue grew to $245,122 million.",
        kind=FindingKind.CALCULATED,
        metric_refs=["FY2024.revenue"],
        status=FindingStatus.APPROVED,
    )
    state = make_state(
        company=company,
        metrics=metrics,
        sources=[source],
        evidence=[evidence],
        outputs=[make_output(AgentName.FILINGS, [fact]), make_output(AgentName.FINANCIALS, [calculated])],
    )

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    assert result.review.overall_verdict == Verdict.APPROVED
    assert not result.updated_outputs
    assert all(sr.verdict == Verdict.APPROVED for sr in result.review.reviews)
    assert "hallucinated_evidence" in result.review.checks_run
    assert "calculated_numbers" in result.review.checks_run


async def test_critic_explicitly_approves_draft_findings_that_pass_every_check(settings) -> None:
    """A finding that survives every check must move from DRAFT to APPROVED -- DRAFT must never leak
    into the report as if it had been reviewed (this is what BaseAgent.execute actually produces)."""
    company = make_company()
    metrics = make_metrics()
    source = make_source("10k", published_at=date.today())
    evidence = make_evidence(source, "Revenue was $245,122 million in FY2024.")
    fact = make_finding(
        AgentName.FILINGS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "The 10-K reports FY2024 revenue of $245,122 million.",
        kind=FindingKind.FACT,
        evidence_ids=[evidence.id],
        status=FindingStatus.DRAFT,
    )
    state = make_state(
        company=company,
        metrics=metrics,
        sources=[source],
        evidence=[evidence],
        outputs=[make_output(AgentName.FILINGS, [fact])],
    )

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    assert result.review.overall_verdict == Verdict.APPROVED
    assert "filings" in result.updated_outputs
    assert result.updated_outputs["filings"].findings[0].status == FindingStatus.APPROVED


async def test_critic_accepts_a_rounded_figure_but_still_catches_a_genuine_mismatch(settings) -> None:
    """A claim stating a metric rounded to the precision it was written at is not a mismatch, but a claim
    stating a genuinely different number still is (this is the false-positive the real MSFT run hit)."""
    company = make_company()
    metrics = make_metrics()
    metrics.add(
        MetricValue(key="debt_to_equity", period="FY2026", value=0.0910831, unit="ratio", formula="total_debt / equity")
    )
    rounded = make_finding(
        AgentName.RISK,
        ReportSection.KEY_RISKS,
        "Debt-to-equity is 0.09x as of FY2026, a key leverage ratio.",
        kind=FindingKind.CALCULATED,
        metric_refs=["FY2026.debt_to_equity"],
        status=FindingStatus.DRAFT,
    )
    wrong = make_finding(
        AgentName.FINANCIALS,
        ReportSection.KEY_RATIOS,
        "Debt-to-equity is 0.5x as of FY2026, a very high leverage ratio.",
        kind=FindingKind.CALCULATED,
        metric_refs=["FY2026.debt_to_equity"],
        status=FindingStatus.DRAFT,
    )
    state = make_state(
        company=company,
        metrics=metrics,
        outputs=[make_output(AgentName.RISK, [rounded]), make_output(AgentName.FINANCIALS, [wrong])],
    )

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    # Assert per finding id: issues are attributed to the finding's own agent, so filtering by agent alone
    # would not distinguish the two claims if they were ever authored by the same agent.
    figure_issues = {
        i.finding_id
        for r in result.review.reviews
        for i in r.issues
        if i.issue_type == CriticIssueType.INCONSISTENT_FIGURE
    }
    assert rounded.id not in figure_issues
    assert wrong.id in figure_issues
    assert result.updated_outputs["risk"].findings[0].status == FindingStatus.APPROVED
    assert result.updated_outputs["financials"].findings[0].status == FindingStatus.REJECTED


async def test_critic_downgrades_bull_bear_reuse_of_source_findings_to_low_severity(settings) -> None:
    """Bull/bear restating a point from the agent they're arguing from is expected, not a defect, and must
    not block approval; genuine duplication between two research agents still counts as MEDIUM."""
    company = make_company()
    source_finding = make_finding(
        AgentName.RISK,
        ReportSection.KEY_RISKS,
        "Rising competition pressures gross margins over time.",
        kind=FindingKind.INTERPRETATION,
        status=FindingStatus.DRAFT,
    )
    bear_finding = make_finding(
        AgentName.BEAR,
        ReportSection.BEAR_CASE,
        "Rising competition pressures gross margins over time.",
        kind=FindingKind.INTERPRETATION,
        status=FindingStatus.DRAFT,
    )
    independent_duplicate = make_finding(
        AgentName.NEWS,
        ReportSection.RECENT_DEVELOPMENTS,
        "Rising competition pressures gross margins over time.",
        kind=FindingKind.INTERPRETATION,
        status=FindingStatus.DRAFT,
    )
    state = make_state(
        company=company,
        outputs=[
            make_output(AgentName.RISK, [source_finding]),
            make_output(AgentName.BEAR, [bear_finding]),
            make_output(AgentName.NEWS, [independent_duplicate]),
        ],
    )

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    bear_issues = next(i for i in result.review.reviews if i.agent == AgentName.BEAR).issues
    bear_dupes = [i for i in bear_issues if i.issue_type == CriticIssueType.DUPLICATION]
    assert bear_dupes and all(i.severity == Severity.LOW for i in bear_dupes)
    # low severity must never block approval
    assert result.updated_outputs["bear"].findings[0].status == FindingStatus.APPROVED

    news_issues = next(i for i in result.review.reviews if i.agent == AgentName.NEWS).issues
    news_dupes = [i for i in news_issues if i.issue_type == CriticIssueType.DUPLICATION]
    assert news_dupes and any(i.severity == Severity.MEDIUM for i in news_dupes)


async def test_critic_flags_fact_without_evidence_as_unverified(settings) -> None:
    company = make_company()
    finding = make_finding(
        AgentName.NEWS,
        ReportSection.RECENT_DEVELOPMENTS,
        "The company hired a new CFO.",
        kind=FindingKind.FACT,
        evidence_ids=[],
        status=FindingStatus.DRAFT,
    )
    state = make_state(company=company, outputs=[make_output(AgentName.NEWS, [finding])])

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    assert result.updated_outputs["news"].findings[0].status == FindingStatus.UNVERIFIED
    assert result.review.overall_verdict == Verdict.APPROVED  # medium severity alone doesn't force revision


async def test_critic_flags_stale_recent_developments(settings) -> None:
    company = make_company()
    old_source = make_source("old-8k", published_at=date.today() - timedelta(days=500))
    evidence = make_evidence(old_source, "The company announced a restructuring plan.")
    finding = make_finding(
        AgentName.NEWS,
        ReportSection.RECENT_DEVELOPMENTS,
        "The company announced a restructuring plan.",
        kind=FindingKind.FACT,
        evidence_ids=[evidence.id],
        status=FindingStatus.APPROVED,
    )
    state = make_state(
        company=company, sources=[old_source], evidence=[evidence], outputs=[make_output(AgentName.NEWS, [finding])]
    )

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    stale = [i for i in result.review.reviews[0].issues if i.issue_type == CriticIssueType.STALE_INFORMATION]
    assert stale
    assert result.updated_outputs["news"].findings[0].status == FindingStatus.UNVERIFIED


async def test_critic_flags_contradictory_directional_claims(settings) -> None:
    company = make_company()
    metrics = make_metrics()
    up = make_finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "Revenue grew strongly in FY2024.",
        kind=FindingKind.CALCULATED,
        metric_refs=["FY2024.revenue_growth"],
        status=FindingStatus.APPROVED,
    )
    down = make_finding(
        AgentName.FILINGS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "Revenue declined in FY2024 according to the filing.",
        kind=FindingKind.CALCULATED,
        metric_refs=["FY2024.revenue_growth"],
        status=FindingStatus.APPROVED,
    )
    state = make_state(
        company=company,
        metrics=metrics,
        outputs=[make_output(AgentName.FINANCIALS, [up]), make_output(AgentName.FILINGS, [down])],
    )

    critic = Critic(make_deps(settings))
    result = await critic.review(state)

    all_issues = [i for r in result.review.reviews for i in r.issues]
    contradictions = [i for i in all_issues if i.issue_type == CriticIssueType.CONTRADICTION]
    assert len(contradictions) >= 2


async def test_critic_llm_pass_adds_judgement_issues(settings) -> None:
    company = make_company()
    finding = make_finding(
        AgentName.COMPANY,
        ReportSection.COMPANY_OVERVIEW,
        "The company will dominate its market.",
        kind=FindingKind.INTERPRETATION,
        status=FindingStatus.APPROVED,
    )
    state = make_state(company=company, outputs=[make_output(AgentName.COMPANY, [finding])])

    provider = ScriptedLLMProvider()
    provider.script(
        AgentName.CRITIC,
        {
            "structured": {
                "summary": "one weak assumption",
                "issues": [
                    {
                        "agent": "company",
                        "finding_id": finding.id,
                        "issue_type": "weak_assumption",
                        "severity": "medium",
                        "description": "unsupported superlative claim",
                        "suggested_fix": "soften the claim",
                    },
                ],
            }
        },
    )

    critic = Critic(make_deps(settings, llm=provider))
    result = await critic.review(state)

    weak = [i for i in result.review.reviews[0].issues if i.issue_type == CriticIssueType.WEAK_ASSUMPTION]
    assert weak
    assert "llm_pass" in result.review.checks_run
    assert result.updated_outputs["company"].findings[0].status == FindingStatus.UNVERIFIED
