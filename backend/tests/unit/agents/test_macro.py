from __future__ import annotations

from meridian.agents.base import AgentAnswer
from meridian.agents.macro import MacroAgent
from meridian.schemas.enums import AgentName, FindingStatus, ReportSection
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


async def test_macro_offline_zero_findings_when_nothing_material(fake_data, events, offline_llm, settings):
    fake_data.search_filings_fn = lambda query: []  # no filing language links the company to macro exposure
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = MacroAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"  # absence of exposure is a valid result, not a failure
    assert result.output.findings == []
    assert "no material macro exposure" in result.output.summary.lower()


async def test_macro_offline_links_exposure_to_filing_evidence(fake_data, events, offline_llm, settings):
    hit = fake_data.add_passage(
        "Our results are subject to fluctuations in interest rates and foreign currency exchange rates, "
        "which increase our borrowing costs.",
        "Item 7A. Quantitative Disclosures",
    )
    fake_data.search_filings_fn = lambda query: [hit]
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = MacroAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.findings, "expected a macro finding tied to real filing evidence"
    for f in result.output.findings:
        assert f.section == ReportSection.MACRO
        assert f.status != FindingStatus.UNVERIFIED
        assert hit.evidence_id in f.evidence_ids
        for eid in f.evidence_ids:
            assert eid in result.evidence


async def test_macro_generative_reports_no_material_link(fake_data, events, scripted_llm, settings):
    fake_data.search_filings_fn = lambda query: []
    scripted_llm.script(
        AgentName.MACRO,
        {
            "structured": AgentAnswer(
                summary="No material macro exposure was found in the filings reviewed.",
                findings=[],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = MacroAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    assert result.output.findings == []
    assert "no material" in result.output.summary.lower()
