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
