"""Shared builders for constructing sample schema objects in the DB integration tests."""

from __future__ import annotations

from datetime import timedelta

from meridian.core.ids import new_id, utcnow
from meridian.schemas.analysis import CriticIssue, CriticReview, SectionReview
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import (
    AgentName,
    Confidence,
    CriticIssueType,
    FindingKind,
    ReportSection,
    RunStatus,
    Severity,
    SourceKind,
    TaskStatus,
    Verdict,
)
from meridian.schemas.findings import AgentOutput, Finding
from meridian.schemas.report import ResearchReport
from meridian.schemas.research import CompanyIdentity, ResearchRequest, ResearchTask


def make_request(ticker: str = "MSFT") -> ResearchRequest:
    return ResearchRequest(query=f"Analyse {ticker}", ticker=ticker, depth="quick")


def make_company(ticker: str = "MSFT") -> CompanyIdentity:
    return CompanyIdentity(
        name="Microsoft Corp",
        ticker=ticker,
        cik="0000789019",
        exchange="NASDAQ",
        sic="7372",
        sic_description="Prepackaged Software",
        fiscal_year_end="0630",
        state_of_incorporation="WA",
        website="https://microsoft.com",
    )


def make_source(session_suffix: str = "") -> Source:
    return Source.make(
        kind=SourceKind.SEC_FILING,
        title="10-K filing" + session_suffix,
        provider="sec_edgar",
        publisher="U.S. SEC EDGAR",
        url="https://www.sec.gov/Archives/edgar/data/789019/000078901924000001-index.htm",
    )


def make_evidence(source: Source) -> Evidence:
    return Evidence.make(
        source_id=source.id,
        text="Revenue was 245,122,000,000 USD for FY2024.",
        locator=EvidenceLocator(xbrl_concept="us-gaap:Revenues", period="FY2024"),
    )


def make_finding(evidence: Evidence) -> Finding:
    return Finding(
        agent=AgentName.FINANCIALS,
        section=ReportSection.FINANCIAL_PERFORMANCE,
        claim="FY2024 revenue grew 15.7% year over year.",
        kind=FindingKind.CALCULATED,
        evidence_ids=[evidence.id],
        confidence=Confidence.HIGH,
    )


def make_task(agent: AgentName = AgentName.FINANCIALS, wave: int = 1) -> ResearchTask:
    return ResearchTask.make(agent=agent, objective="Gather FY2024 financials", wave=wave)


def make_agent_output(task: ResearchTask, finding: Finding) -> AgentOutput:
    return AgentOutput(
        agent=task.agent,
        task_id=task.id,
        status=TaskStatus.COMPLETED,
        summary="Computed FY2024 metrics.",
        findings=[finding],
        source_ids=[],
        evidence_ids=finding.evidence_ids,
        tools_used=["get_financial_statements"],
        started_at=utcnow() - timedelta(seconds=5),
        finished_at=utcnow(),
    )


def make_critic_review(round_: int = 1, verdict: Verdict = Verdict.APPROVED) -> CriticReview:
    return CriticReview(
        round=round_,
        overall_verdict=verdict,
        summary="Looks solid.",
        reviews=[
            SectionReview(
                agent=AgentName.FINANCIALS,
                verdict=verdict,
                issues=[]
                if verdict == Verdict.APPROVED
                else [
                    CriticIssue(
                        agent=AgentName.FINANCIALS,
                        issue_type=CriticIssueType.MISSING_CITATION,
                        severity=Severity.MEDIUM,
                        description="Needs a citation.",
                    )
                ],
            )
        ],
        checks_run=["citation_check"],
    )


def make_report(session_id: str, company: CompanyIdentity) -> ResearchReport:
    return ResearchReport(
        id=new_id("rpt"),
        session_id=session_id,
        company=company,
        title=f"{company.name} Equity Research",
        generated_at=utcnow(),
        llm_mode="offline",
        data_mode="live",
        sections=[],
    )


def unique_session_id() -> str:
    return new_id("sess_test")


__all__ = [
    "RunStatus",
    "make_agent_output",
    "make_company",
    "make_critic_review",
    "make_evidence",
    "make_finding",
    "make_report",
    "make_request",
    "make_source",
    "make_task",
    "unique_session_id",
]
