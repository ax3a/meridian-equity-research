from __future__ import annotations

from meridian.agents.base import AgentAnswer, DraftFinding
from meridian.agents.risk import RiskAgent
from meridian.schemas.enums import AgentName, Confidence, FindingKind, FindingStatus, ReportSection, RiskCategory
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


async def test_risk_offline_ties_debt_and_liquidity_to_metrics(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = RiskAgent(deps)
    state = make_state(fake_data.ticker, metrics=fake_data.metrics)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    debt_findings = [f for f in result.output.findings if f.category == RiskCategory.DEBT.value]
    liquidity_findings = [f for f in result.output.findings if f.category == RiskCategory.LIQUIDITY.value]
    assert debt_findings and debt_findings[0].metric_refs
    assert liquidity_findings and liquidity_findings[0].metric_refs
    for f in debt_findings + liquidity_findings:
        assert f.kind == FindingKind.CALCULATED
        assert f.status != FindingStatus.UNVERIFIED
        for ref in f.metric_refs:
            assert ref in fake_data.metrics.values


async def test_risk_offline_one_finding_per_category_with_evidence(fake_data, events, offline_llm, settings):
    competitive_hit = fake_data.add_passage(
        "We face intense competition from larger, well-funded rivals.", "Item 1A. Risk Factors"
    )
    regulatory_hit = fake_data.add_passage(
        "We are subject to extensive export control and antitrust regulation.", "Item 1A. Risk Factors"
    )

    def fn(query: str):
        if "competitive" in query:
            return [competitive_hit]
        if "regulatory" in query:
            return [regulatory_hit]
        return []

    fake_data.search_filings_fn = fn
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = RiskAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    categories = [f.category for f in result.output.findings if f.category]
    assert categories.count(RiskCategory.COMPETITIVE.value) == 1
    assert categories.count(RiskCategory.REGULATORY.value) == 1
    assert RiskCategory.OPERATIONAL.value not in categories  # no evidence -> no fabricated finding
    for f in result.output.findings:
        if f.category in (RiskCategory.COMPETITIVE.value, RiskCategory.REGULATORY.value):
            assert f.kind == FindingKind.FACT
            assert f.evidence_ids
            for eid in f.evidence_ids:
                assert eid in result.evidence


async def test_risk_generative_path_sets_category(fake_data, events, scripted_llm, settings):
    hit = fake_data.filing_passages[0]
    scripted_llm.script(
        AgentName.RISK,
        {
            "structured": AgentAnswer(
                summary="Identified competitive risk.",
                findings=[
                    DraftFinding(
                        claim="Faces intense competitive pressure in GPUs.",
                        kind=FindingKind.FACT,
                        section=ReportSection.KEY_RISKS,
                        evidence_ids=[hit.evidence_id],
                        category=RiskCategory.COMPETITIVE.value,
                        confidence=Confidence.MEDIUM,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = RiskAgent(deps)
    state = make_state(
        fake_data.ticker,
        evidence={
            hit.evidence_id: fake_data.passage_evidence[hit.evidence_id][1],
        },
    )
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    f = result.output.findings[0]
    assert f.category == RiskCategory.COMPETITIVE.value
    assert f.status != FindingStatus.UNVERIFIED
