from __future__ import annotations

from meridian.agents.report_writer import ReportWriter
from meridian.providers.llm.scripted import ScriptedLLMProvider
from meridian.schemas.enums import AgentName, FindingKind, FindingStatus, ReportSection

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


def _build_state(settings, **kw):
    company = make_company()
    metrics = make_metrics()
    source = make_source("10k")
    evidence = make_evidence(source, "Revenue was $245,122 million in FY2024, up 15.7% year over year.")

    fact = make_finding(
        AgentName.COMPANY,
        ReportSection.COMPANY_OVERVIEW,
        "Acme Corp sells enterprise software.",
        kind=FindingKind.FACT,
        evidence_ids=[evidence.id],
        status=FindingStatus.APPROVED,
    )
    calculated = make_finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "FY2024 revenue was $245,122 million.",
        kind=FindingKind.CALCULATED,
        metric_refs=["FY2024.revenue"],
        status=FindingStatus.APPROVED,
    )
    unverified = make_finding(
        AgentName.NEWS,
        ReportSection.RECENT_DEVELOPMENTS,
        "The company may be exploring an acquisition.",
        kind=FindingKind.INTERPRETATION,
        status=FindingStatus.UNVERIFIED,
    )

    state = make_state(
        company=company,
        metrics=metrics,
        sources=[source],
        evidence=[evidence],
        outputs=[
            make_output(AgentName.COMPANY, [fact]),
            make_output(AgentName.FINANCIALS, [calculated]),
            make_output(AgentName.NEWS, [unverified]),
        ],
        **kw,
    )
    return state, evidence


async def test_offline_report_renders_with_real_citations(settings) -> None:
    state, evidence = _build_state(settings)
    writer = ReportWriter(make_deps(settings))

    result = await writer.write(state)
    report = result.report

    assert report.company.ticker == state.company.ticker
    assert report.llm_mode == "offline"
    assert evidence.id in report.citations
    assert report.citations[evidence.id].source_title.startswith("Source")

    overview = next(s for s in report.sections if s.section == ReportSection.COMPANY_OVERVIEW)
    assert f"[{evidence.id}]" in overview.paragraphs[0].text

    open_questions = next(s for s in report.sections if s.section == ReportSection.OPEN_QUESTIONS)
    assert open_questions.paragraphs[0].unverified is True
    assert report.unverified_claims == 1

    # every cited evidence id in the report must resolve to a real Citation
    for section in report.sections:
        for para in section.paragraphs:
            for eid in para.evidence_ids:
                assert eid in report.citations


async def test_writer_refuses_unresolvable_citation_marker_and_falls_back(settings) -> None:
    state, _evidence = _build_state(settings)
    provider = ScriptedLLMProvider()
    # Every attempt for every section returns a marker shaped like a real evidence id (ev_ + hex) that
    # nonetheless doesn't exist in this run's evidence store -- exactly what a hallucinated citation looks like.
    fake_marker = "ev_deadbeef00000000"
    bad_response = {
        "structured": {
            "title": "Section",
            "paragraphs": [
                {"text": f"Acme Corp does great things. [{fake_marker}]", "kind": "fact"},
            ],
        }
    }
    provider.script(
        AgentName.REPORT_WRITER,
        bad_response,
        bad_response,
        bad_response,
        bad_response,
        bad_response,
        bad_response,
        bad_response,
        bad_response,
        bad_response,
    )
    writer = ReportWriter(make_deps(settings, llm=provider))

    result = await writer.write(state)
    report = result.report

    rendered_text = " ".join(p.text for s in report.sections for p in s.paragraphs)
    assert fake_marker not in rendered_text
    for section in report.sections:
        for para in section.paragraphs:
            for eid in para.evidence_ids:
                assert eid in state.evidence
