from __future__ import annotations

from meridian.agents.bear import Bear
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
    return ResearchTask.make(AgentName.BEAR, "Build the bear case.", 3)


async def test_bear_offline_only_cites_existing_evidence(settings) -> None:
    company = make_company()
    source = make_source("10k")
    evidence = make_evidence(source, "Rising competition pressures margins.")
    candidate = make_finding(
        AgentName.RISK,
        ReportSection.KEY_RISKS,
        "Rising competition and regulatory pressure could weaken margins.",
        kind=FindingKind.INTERPRETATION,
        evidence_ids=[evidence.id],
        status=FindingStatus.APPROVED,
    )
    state = make_state(
        company=company, sources=[source], evidence=[evidence], outputs=[make_output(AgentName.RISK, [candidate])]
    )
    bear = Bear(make_deps(settings))
    ctx = bear.new_context(state)

    draft = await bear.run(_task(), state, ctx)

    assert draft.findings, "expected at least one bear case point"
    for f in draft.findings:
        assert f.section == ReportSection.BEAR_CASE
        assert all(eid == evidence.id for eid in f.evidence_ids)


async def test_bear_generative_produces_cited_findings(settings) -> None:
    company = make_company()
    source = make_source("10k")
    evidence = make_evidence(source, "Debt levels rose sharply.")
    candidate = make_finding(
        AgentName.RISK,
        ReportSection.KEY_RISKS,
        "Debt levels rose sharply in FY2024.",
        kind=FindingKind.FACT,
        evidence_ids=[evidence.id],
        status=FindingStatus.APPROVED,
    )
    state = make_state(
        company=company, sources=[source], evidence=[evidence], outputs=[make_output(AgentName.RISK, [candidate])]
    )

    provider = ScriptedLLMProvider()
    provider.script(
        AgentName.BEAR,
        {
            "structured": {
                "summary": "Rising leverage is a key risk.",
                "findings": [
                    {
                        "claim": "Rising debt levels increase financial risk.",
                        "kind": "interpretation",
                        "section": "bear_case",
                        "evidence_ids": [evidence.id],
                        "metric_refs": [],
                        "confidence": "medium",
                    }
                ],
            }
        },
    )
    bear = Bear(make_deps(settings, llm=provider))
    ctx = bear.new_context(state)

    draft = await bear.run(_task(), state, ctx)

    assert len(draft.findings) == 1
    assert draft.findings[0].evidence_ids == [evidence.id]
