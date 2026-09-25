"""End-to-end: one request in, one citation-backed report out, through the real graph.

Uses the real agents, tools, providers and RAG with the deterministic offline LLM, so it exercises the
whole pipeline without an API key. It needs network access to SEC EDGAR (or recorded snapshots), so it
is marked `integration` and skips when neither is available.
"""

from __future__ import annotations

import pytest

from meridian.agents.base import AgentDeps
from meridian.agents.registry import build_agent_set
from meridian.core.config import Settings
from meridian.graph.runner import ResearchRunner
from meridian.memory.inmemory import InMemoryResearchMemoryStore
from meridian.observability.events import ListEventSink
from meridian.providers.factory import build_providers, build_retriever
from meridian.schemas.enums import AgentName, FindingKind, ReportSection, RunStatus
from meridian.schemas.events import EventType
from meridian.schemas.research import ResearchRequest
from meridian.tools.factory import build_tool_registry

pytestmark = pytest.mark.integration

REQUIRED_SECTIONS = {
    ReportSection.EXECUTIVE_SUMMARY,
    ReportSection.COMPANY_OVERVIEW,
    ReportSection.FINANCIAL_PERFORMANCE,
    ReportSection.KEY_RISKS,
}


@pytest.fixture
def e2e_settings(tmp_path) -> Settings:
    return Settings(
        redis_url=None,
        data_mode="auto",
        llm_provider="offline",
        embedding_provider="hashing",
        require_approval_default=False,
        model_cache_dir=tmp_path / "models",
        sec_user_agent="Meridian E2E Test e2e@example.com",
    )


@pytest.fixture
def events() -> ListEventSink:
    return ListEventSink()


async def _run(settings: Settings, events: ListEventSink, query: str):
    providers = build_providers(settings)
    deps = AgentDeps(
        settings=settings,
        providers=providers,
        tools=build_tool_registry(),
        retriever=build_retriever(settings, providers),
        events=events,
        memory=InMemoryResearchMemoryStore(),
    )
    runner = ResearchRunner(build_agent_set(deps), settings)
    session_id = await runner.start(ResearchRequest(query=query, require_approval=False))
    await runner.wait_idle(session_id)
    state = await runner.status(session_id)
    # Lifecycle events are emitted through the runner''s own sink into its store; the sink injected into
    # AgentDeps only ever sees tool calls, so progress must be read back from the store.
    progress = await runner.store.list_events_since(session_id, 0)
    return state, progress


async def test_analyse_microsoft_produces_a_cited_report(e2e_settings, events):
    state, progress = await _run(e2e_settings, events, "Analyse Microsoft")
    if state is None or (state.status == RunStatus.FAILED and not state.sources):
        pytest.skip("SEC EDGAR unreachable and no snapshot available")

    # The company was identified from natural language, with no ticker supplied.
    assert state.company is not None and state.company.ticker == "MSFT"

    # A plan was made and several specialists ran in dependency waves.
    assert state.plan is not None and len(state.plan.tasks) >= 5
    completed = {name for name, out in state.outputs.items() if out.findings}
    assert {AgentName.COMPANY.value, AgentName.FINANCIALS.value} <= completed

    # Figures come from the deterministic engine, not from prose.
    assert state.metrics is not None and state.metrics.values
    assert state.financials is not None and state.financials.annual

    # Every citation resolves: no invented evidence ids survive validation.
    for finding in state.findings():
        for evidence_id in finding.evidence_ids:
            assert evidence_id in state.evidence, f"dangling citation {evidence_id}"
            assert state.evidence[evidence_id].source_id in state.sources

    # The critic reviewed the work before anything was written.
    assert state.critic_reviews, "critic did not run"

    report = state.report
    assert report is not None, "no report produced"
    assert {s.section for s in report.sections if s.paragraphs} >= REQUIRED_SECTIONS
    assert report.citations, "report has no resolved citations"
    for paragraph in (p for s in report.sections for p in s.paragraphs):
        if paragraph.kind is FindingKind.FACT:
            assert paragraph.evidence_ids or paragraph.metric_refs or paragraph.unverified

    # Progress was streamed in a sensible order for the live view.
    types = [e.type for e in progress]
    assert EventType.RUN_STARTED in types
    assert types[-1] in (EventType.RUN_COMPLETED, EventType.REPORT_COMPLETED)


async def test_an_unresolvable_company_fails_without_inventing_one(e2e_settings, events):
    state, _progress = await _run(e2e_settings, events, "Analyse Nonexistent Fabricated Holdings Ltd")
    if state is None:
        pytest.skip("runner returned no state")

    assert state.status == RunStatus.FAILED
    assert state.company is None, f"resolved an unrelated company: {state.company}"
    assert state.report is None
    assert state.errors and "could not resolve" in state.errors[0].message.lower()
