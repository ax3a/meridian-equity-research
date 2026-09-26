from __future__ import annotations

from meridian.agents.base import AgentAnswer, DraftFinding
from meridian.agents.filings import FilingsAgent
from meridian.schemas.enums import AgentName, Confidence, FindingKind, FindingStatus, ReportSection
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


async def test_filings_offline_covers_multiple_sections_with_real_evidence(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = FilingsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    assert result.output.findings, "expected filing-derived findings"
    for f in result.output.findings:
        assert f.status != FindingStatus.UNVERIFIED
        for eid in f.evidence_ids:
            assert eid in result.evidence

    sections = {f.section for f in result.output.findings}
    assert ReportSection.FINANCIAL_PERFORMANCE in sections
    assert ReportSection.KEY_RISKS in sections
    assert ReportSection.RECENT_DEVELOPMENTS in sections


async def test_filings_offline_no_evidence_yields_no_findings_for_that_topic(fake_data, events, offline_llm, settings):
    fake_data.search_filings_fn = lambda query: []  # nothing indexed / retrieved
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = FilingsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    # only the 8-K-derived RECENT_DEVELOPMENTS findings remain; no fabricated filing-text findings
    assert all(f.section == ReportSection.RECENT_DEVELOPMENTS for f in result.output.findings)


async def test_filings_generative_path(fake_data, events, scripted_llm, settings):
    cited = fake_data.filing_passages[0].evidence_id
    scripted_llm.script(
        AgentName.FILINGS,
        {
            "structured": AgentAnswer(
                summary="Reviewed MD&A and risk factors.",
                findings=[
                    DraftFinding(
                        claim="Management discussed strong data center demand in MD&A.",
                        kind=FindingKind.FACT,
                        section=ReportSection.FINANCIAL_PERFORMANCE,
                        evidence_ids=[cited],
                        confidence=Confidence.MEDIUM,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = FilingsAgent(deps)
    state = make_state(
        fake_data.ticker, evidence={cited: next(ev for _, ev in fake_data.passage_evidence.values() if ev.id == cited)}
    )
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    f = result.output.findings[0]
    assert f.status != FindingStatus.UNVERIFIED
    assert f.evidence_ids == [cited]


async def test_filings_risk_label_only_applied_to_risk_factor_text(fake_data, events, offline_llm, settings):
    """ "Risk factor: ..." must mean Item 1A, not whatever best matched a search for risk factors.

    A real run labelled a reputation passage a "Segment disclosure" for exactly this reason.
    """
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    result = await FilingsAgent(deps).execute(make_task(AgentName.FILINGS), make_state(fake_data.ticker))

    by_evidence = {p.evidence_id: p for p in fake_data.filing_passages}
    for finding in result.output.findings:
        if not finding.claim.startswith("Risk factor:"):
            continue
        sections = {by_evidence[eid].section for eid in finding.evidence_ids if eid in by_evidence}
        assert sections <= {"Item 1A. Risk Factors"}, f"risk label on {sections}"


async def test_filings_falls_back_when_no_section_matches(fake_data, events, offline_llm, settings):
    """Section detection fails on some filings; coverage must survive, without an unearned label."""
    only_business = [p for p in fake_data.filing_passages if p.section == "Item 1. Business"]
    fake_data.filing_passages = only_business
    fake_data.section_passages = only_business

    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    result = await FilingsAgent(deps).execute(make_task(AgentName.FILINGS), make_state(fake_data.ticker))

    claims = [f.claim for f in result.output.findings]
    assert claims, "the agent should still produce findings from the unscoped fallback"
    assert not any(c.startswith("Risk factor:") for c in claims)
    assert any(c.startswith("Filing excerpt matching") for c in claims)
