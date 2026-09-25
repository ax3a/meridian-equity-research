from __future__ import annotations

from meridian.agents.base import AgentAnswer, DraftFinding
from meridian.agents.news import NewsAgent
from meridian.schemas.enums import AgentName, Confidence, FindingKind, FindingStatus, ReportSection
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


async def test_news_offline_separates_fact_from_interpretation(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = NewsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    assert result.output.findings, "expected news/8-K findings"
    for f in result.output.findings:
        assert f.status != FindingStatus.UNVERIFIED
        for eid in f.evidence_ids:
            assert eid in result.evidence
        assert f.section == ReportSection.RECENT_DEVELOPMENTS

    kinds = {f.kind for f in result.output.findings}
    assert FindingKind.FACT in kinds
    # 8-K items are always FACT
    eight_k_findings = [f for f in result.output.findings if "8-K" in f.claim]
    assert eight_k_findings and all(f.kind == FindingKind.FACT for f in eight_k_findings)


async def test_news_offline_no_events_or_articles_yields_no_findings(fake_data, events, offline_llm, settings):
    fake_data.events = []
    fake_data.articles = []
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = NewsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    assert result.output.findings == []


async def test_news_generative_path(fake_data, events, scripted_llm, settings):
    event = fake_data.events[0]
    scripted_llm.script(
        AgentName.NEWS,
        {
            "structured": AgentAnswer(
                summary="Reviewed recent developments.",
                findings=[
                    DraftFinding(
                        claim=f"Filed 8-K on {event.filed} covering items {', '.join(event.items)}.",
                        kind=FindingKind.FACT,
                        section=ReportSection.RECENT_DEVELOPMENTS,
                        evidence_ids=[event.evidence_id],
                        confidence=Confidence.HIGH,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = NewsAgent(deps)
    state = make_state(
        fake_data.ticker,
        evidence={
            event.evidence_id: fake_data.event_evidence[event.evidence_id][1],
        },
    )
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    f = result.output.findings[0]
    assert f.status != FindingStatus.UNVERIFIED
    assert f.evidence_ids == [event.evidence_id]
