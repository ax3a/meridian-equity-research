from __future__ import annotations

from meridian.agents.bull import Bull
from meridian.providers.llm.scripted import ScriptedLLMProvider
from meridian.schemas.enums import AgentName, FindingKind, FindingStatus, ReportSection
from meridian.schemas.research import ResearchTask

from .conftest_orchestration import (
    make_company,
    make_deps,
    make_evidence,
    make_finding,
    make_output,
    make_source,
    make_state,
)


def _task() -> ResearchTask:
    return ResearchTask.make(AgentName.BULL, "Build the bull case.", 3)


async def test_bull_offline_only_cites_existing_evidence(settings) -> None:
    company = make_company()
    source = make_source("10k")
    evidence = make_evidence(source, "Revenue grew 15% and margins expanded.")
    candidate = make_finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "Revenue grew 15% year over year with margin expansion.",
        kind=FindingKind.CALCULATED,
        evidence_ids=[evidence.id],
        status=FindingStatus.APPROVED,
    )

    state = make_state(
        company=company, sources=[source], evidence=[evidence], outputs=[make_output(AgentName.FINANCIALS, [candidate])]
    )
    ctx = Bull(make_deps(settings)).new_context(state)

    bull = Bull(make_deps(settings))
    draft = await bull.run(_task(), state, ctx)

    assert draft.findings, "expected at least one bull case point"
    for f in draft.findings:
        assert f.section == ReportSection.BULL_CASE
        assert all(eid == evidence.id for eid in f.evidence_ids)


async def test_bull_generative_produces_cited_findings(settings) -> None:
    company = make_company()
    source = make_source("10k")
    evidence = make_evidence(source, "Revenue grew 15% and margins expanded.")
    candidate = make_finding(
        AgentName.FINANCIALS,
        ReportSection.FINANCIAL_PERFORMANCE,
        "Revenue grew 15% year over year.",
        kind=FindingKind.CALCULATED,
        evidence_ids=[evidence.id],
        status=FindingStatus.APPROVED,
    )
    state = make_state(
        company=company, sources=[source], evidence=[evidence], outputs=[make_output(AgentName.FINANCIALS, [candidate])]
    )

    provider = ScriptedLLMProvider()
    provider.script(
        AgentName.BULL,
        {
            "structured": {
                "summary": "Strong growth supports the bull case.",
                "findings": [
                    {
                        "claim": "Revenue growth of 15% signals durable demand.",
                        "kind": "interpretation",
                        "section": "bull_case",
                        "evidence_ids": [evidence.id],
                        "metric_refs": [],
                        "confidence": "medium",
                    }
                ],
            }
        },
    )
    bull = Bull(make_deps(settings, llm=provider))
    ctx = bull.new_context(state)

    draft = await bull.run(_task(), state, ctx)

    assert len(draft.findings) == 1
    assert draft.findings[0].evidence_ids == [evidence.id]
