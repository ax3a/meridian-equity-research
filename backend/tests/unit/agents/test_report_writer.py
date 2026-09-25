from __future__ import annotations

from meridian.agents.critic import parse_figures, within_tolerance
from meridian.agents.report_writer import ReportWriter
from meridian.providers.llm.scripted import ScriptedLLMProvider
from meridian.schemas.enums import AgentName, FindingKind, FindingStatus, ReportSection
from meridian.schemas.report import ReportSectionContent

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


def _executive_summary(report) -> ReportSectionContent:
    return next(s for s in report.sections if s.section == ReportSection.EXECUTIVE_SUMMARY)


async def test_offline_executive_summary_includes_company_metric_and_evidence(settings) -> None:
    state, evidence = _build_state(settings)
    writer = ReportWriter(make_deps(settings))

    result = await writer.write(state)
    report = result.report

    exec_summary = _executive_summary(report)
    assert exec_summary.paragraphs
    full_text = " ".join(p.text for p in exec_summary.paragraphs)
    assert state.company.name in full_text

    metric_refs = [ref for p in exec_summary.paragraphs for ref in p.metric_refs]
    assert metric_refs
    assert all(ref in state.metrics.values for ref in metric_refs)

    evidence_ids = [eid for p in exec_summary.paragraphs for eid in p.evidence_ids]
    assert evidence.id in evidence_ids
    for eid in evidence_ids:
        assert eid in report.citations


async def test_offline_executive_summary_without_valuation_or_peers(settings) -> None:
    state, _evidence = _build_state(settings)
    assert state.valuation is None
    assert state.peers is None
    writer = ReportWriter(make_deps(settings))

    result = await writer.write(state)
    report = result.report

    exec_summary = _executive_summary(report)
    assert exec_summary.paragraphs
    assert not any(p.text.startswith("Valuation:") for p in exec_summary.paragraphs)
    # nothing false: every citation used still resolves, and there is no "n/a"-riddled or empty prose
    for p in exec_summary.paragraphs:
        assert p.text.strip()
        for eid in p.evidence_ids:
            assert eid in state.evidence


async def test_executive_summary_generative_rejects_bogus_marker_and_falls_back(settings) -> None:
    state, evidence = _build_state(settings)
    provider = ScriptedLLMProvider()
    fake_marker = "ev_baadf00d00000000"
    bad_response = {
        "structured": {
            "title": "Executive Summary",
            "paragraphs": [
                {"text": f"Acme Corp does amazing things. [{fake_marker}]", "kind": "fact"},
            ],
        }
    }
    provider.script(AgentName.REPORT_WRITER, *([bad_response] * 9))
    writer = ReportWriter(make_deps(settings, llm=provider))

    result = await writer.write(state)
    report = result.report

    exec_summary = _executive_summary(report)
    exec_text = " ".join(p.text for p in exec_summary.paragraphs)
    assert fake_marker not in exec_text
    # falls back to the deterministic offline summary, which cites only real evidence
    assert evidence.id in " ".join(p.text for p in exec_summary.paragraphs)
    for p in exec_summary.paragraphs:
        for eid in p.evidence_ids:
            assert eid in state.evidence


async def test_executive_summary_with_no_approved_findings_says_so_explicitly(settings) -> None:
    company = make_company()
    state = make_state(company=company)  # no outputs at all -> nothing approved
    writer = ReportWriter(make_deps(settings))

    result = await writer.write(state)
    report = result.report

    exec_summary = _executive_summary(report)
    assert len(exec_summary.paragraphs) == 1
    assert "no approved findings" in exec_summary.paragraphs[0].text


async def test_offline_executive_summary_numbers_are_grounded_in_metrics(settings) -> None:
    state, _evidence = _build_state(settings)
    writer = ReportWriter(make_deps(settings))

    result = await writer.write(state)
    report = result.report

    exec_summary = _executive_summary(report)
    text = " ".join(p.text for p in exec_summary.paragraphs)
    known_values = [mv.value for mv in state.metrics.values.values() if mv.value is not None]

    figures = parse_figures(text)
    assert figures, "expected the headline financials sentence to carry at least one number"
    for number in figures:
        assert any(within_tolerance(number, v) for v in known_values), f"{number} is not in the metrics table"
