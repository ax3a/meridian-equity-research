from __future__ import annotations

from meridian.agents.base import AgentAnswer
from meridian.agents.macro import MacroAgent
from meridian.providers.base import MacroIndicator
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


async def test_macro_quotes_the_indicator_value_and_its_date(fake_data, events, offline_llm, settings):
    """The default fixture carries a 10-Year Treasury Yield of 4.2% as of 2025-09-20."""
    hit = fake_data.add_passage(
        "Our borrowing costs are sensitive to changes in interest rates across our debt portfolio.",
        "Item 7A. Quantitative Disclosures",
    )
    fake_data.search_filings_fn = lambda query: [hit]
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)

    result = await MacroAgent(deps).execute(make_task(AgentName.MACRO), make_state(fake_data.ticker))

    claims = " ".join(f.claim for f in result.output.findings)
    assert "10-Year Treasury Yield" in claims
    assert "4.2%" in claims
    assert "2025-09-20" in claims


async def test_macro_indicator_without_a_date_reads_sensibly(fake_data, events, offline_llm, settings):
    """`as_of` is optional on the model, and a getattr default never fires for an attribute that
    exists-but-is-None -- which rendered the claim as "as of None"."""
    fake_data.indicators = [
        MacroIndicator(key="ust_10y", label="10-Year Treasury Yield", unit="%", latest=4.2, as_of=None, history=[])
    ]
    hit = fake_data.add_passage(
        "Our borrowing costs are sensitive to changes in interest rates across our debt portfolio.",
        "Item 7A. Quantitative Disclosures",
    )
    fake_data.search_filings_fn = lambda query: [hit]
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)

    result = await MacroAgent(deps).execute(make_task(AgentName.MACRO), make_state(fake_data.ticker))

    claims = " ".join(f.claim for f in result.output.findings)
    assert "as of None" not in claims
    assert "an unknown date" in claims
