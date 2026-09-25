from __future__ import annotations

from meridian.agents.base import AgentAnswer, DraftFinding
from meridian.agents.financials import FinancialsAgent
from meridian.schemas.enums import AgentName, Confidence, FindingKind, FindingStatus, ReportSection
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


async def test_financials_offline_numbers_come_from_metric_refs(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = FinancialsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    assert result.state_updates["metrics"] is fake_data.metrics
    assert result.state_updates["financials"] is fake_data.statements

    calculated = [f for f in result.output.findings if f.kind == FindingKind.CALCULATED]
    assert calculated, "expected CALCULATED financial findings"
    for f in calculated:
        assert f.status != FindingStatus.UNVERIFIED
        assert f.metric_refs, "every CALCULATED finding must carry a metric ref"
        for ref in f.metric_refs:
            mv = fake_data.metrics.values[ref]
            # the number actually appears in the claim (formatted), never a value the engine didn't produce
            assert mv.ref == ref

    sections = {f.section for f in result.output.findings}
    assert ReportSection.FINANCIAL_PERFORMANCE in sections
    assert ReportSection.KEY_RATIOS in sections


async def test_financials_offline_degrades_when_compute_metrics_fails(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data, fail=frozenset({"compute_financial_metrics"}))
    deps = make_deps(settings, tools, offline_llm, events)
    agent = FinancialsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    assert result.output.findings == []
    assert "Could not compute" in result.output.summary


async def test_financials_generative_rejects_fabricated_metric_ref(fake_data, events, scripted_llm, settings):
    scripted_llm.script(
        AgentName.FINANCIALS,
        {
            "structured": AgentAnswer(
                summary="Revenue grew strongly.",
                findings=[
                    DraftFinding(
                        claim="Revenue was $999B, far higher than reported.",
                        kind=FindingKind.CALCULATED,
                        section=ReportSection.FINANCIAL_PERFORMANCE,
                        metric_refs=["FY2099.revenue"],
                        confidence=Confidence.HIGH,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = FinancialsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    f = result.output.findings[0]
    assert f.metric_refs == []
    assert f.status == FindingStatus.UNVERIFIED


async def test_financials_generative_accepts_real_metric_ref(fake_data, events, scripted_llm, settings):
    real_ref = "FY2025.revenue"
    assert real_ref in fake_data.metrics.values
    scripted_llm.script(
        AgentName.FINANCIALS,
        {
            "structured": AgentAnswer(
                summary="Revenue grew strongly.",
                findings=[
                    DraftFinding(
                        claim=f"Revenue for FY2025 was {fake_data.metrics.values[real_ref].value:,.0f}.",
                        kind=FindingKind.CALCULATED,
                        section=ReportSection.FINANCIAL_PERFORMANCE,
                        metric_refs=[real_ref],
                        confidence=Confidence.HIGH,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = FinancialsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    f = result.output.findings[0]
    assert f.metric_refs == [real_ref]
    assert f.status != FindingStatus.UNVERIFIED
    # the generative call must have been a single-shot structured synthesis, not a free tool loop
    assert scripted_llm.requests[-1].tools == []
