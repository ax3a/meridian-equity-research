from __future__ import annotations

from meridian.agents.base import AgentAnswer, DraftFinding
from meridian.agents.company import CompanyAgent
from meridian.providers.llm.base import LLMToolCall
from meridian.schemas.enums import AgentName, Confidence, FindingKind, FindingStatus, ReportSection
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


async def test_company_offline_cites_real_evidence(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = CompanyAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    fact_findings = [f for f in result.output.findings if f.kind == FindingKind.FACT]
    assert fact_findings, "expected at least one FACT finding"
    for f in fact_findings:
        assert f.status != FindingStatus.UNVERIFIED
        assert f.evidence_ids
        for eid in f.evidence_ids:
            assert eid in result.evidence

    sections = {f.section for f in result.output.findings}
    assert ReportSection.COMPANY_OVERVIEW in sections
    assert ReportSection.BUSINESS_MODEL in sections


async def test_company_offline_degrades_when_profile_tool_fails(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data, fail=frozenset({"get_company_profile"}))
    deps = make_deps(settings, tools, offline_llm, events)
    agent = CompanyAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"  # a failed tool degrades, it never crashes the agent
    assert result.output.error is None
    assert any(f.section == ReportSection.BUSINESS_MODEL for f in result.output.findings)


async def test_company_generative_path_uses_real_tool_evidence(fake_data, events, scripted_llm, settings):
    cited_evidence_id = fake_data.filing_passages[0].evidence_id
    scripted_llm.script(
        AgentName.COMPANY,
        {
            "tool_calls": [
                LLMToolCall(
                    id="call1",
                    name="search_filings",
                    arguments={"ticker": fake_data.ticker, "query": "business overview", "k": 2},
                )
            ],
            "raw_content": [{"type": "tool_use", "id": "call1", "name": "search_filings", "input": {}}],
        },
        {
            "structured": AgentAnswer(
                summary="NVIDIA sells GPUs for gaming and data center workloads.",
                findings=[
                    DraftFinding(
                        claim="NVIDIA's data center segment is its largest revenue source.",
                        kind=FindingKind.FACT,
                        section=ReportSection.BUSINESS_MODEL,
                        evidence_ids=[cited_evidence_id],
                        confidence=Confidence.HIGH,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = CompanyAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert scripted_llm.requests, "expected the agent to call the scripted LLM"
    assert len(result.output.findings) == 1
    f = result.output.findings[0]
    assert f.status != FindingStatus.UNVERIFIED
    assert f.evidence_ids == [cited_evidence_id]
    assert cited_evidence_id in result.evidence


async def test_company_generative_strips_fabricated_evidence_id(fake_data, events, scripted_llm, settings):
    scripted_llm.script(
        AgentName.COMPANY,
        {
            "structured": AgentAnswer(
                summary="NVIDIA overview.",
                findings=[
                    DraftFinding(
                        claim="NVIDIA invented a brand new product line no filing mentions.",
                        kind=FindingKind.FACT,
                        section=ReportSection.BUSINESS_MODEL,
                        evidence_ids=["ev_totally_made_up"],
                        confidence=Confidence.HIGH,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = CompanyAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert len(result.output.findings) == 1
    f = result.output.findings[0]
    assert f.evidence_ids == []
    assert f.status == FindingStatus.UNVERIFIED
    assert result.validation.problems > 0
