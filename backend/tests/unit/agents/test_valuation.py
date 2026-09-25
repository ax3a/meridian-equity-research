from __future__ import annotations

import pytest

from meridian.agents.base import AgentAnswer, DraftFinding
from meridian.agents.valuation import ValuationAgent, _derive_dcf_assumptions
from meridian.schemas.enums import AgentName, Confidence, FindingKind, FindingStatus, ReportSection
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


def test_derive_dcf_assumptions_follows_the_deterministic_rules(fake_data):
    assumptions, skip_reason, refs = _derive_dcf_assumptions(fake_data.metrics, fake_data.statements)

    assert skip_reason == ""
    assert assumptions is not None
    # 3y CAGR from FY2022 (55B) to FY2025 (120B) is ~29.7%, above the 25% cap -> capped
    assert assumptions.revenue_growth[0] == pytest.approx(0.25, abs=1e-6)
    assert assumptions.revenue_growth[-1] == pytest.approx(0.04, abs=1e-6)
    assert len(assumptions.revenue_growth) == 5
    # linear decay
    step = (0.04 - 0.25) / 4
    for i, g in enumerate(assumptions.revenue_growth):
        assert g == pytest.approx(0.25 + step * i, abs=1e-9)
    assert assumptions.fcf_margin == pytest.approx(0.2475, abs=1e-6)
    assert assumptions.discount_rate == 0.09
    assert assumptions.terminal_growth == 0.025
    assert assumptions.net_cash == pytest.approx(16e9, abs=1e-3)
    assert assumptions.shares_outstanding == pytest.approx(2.5e9)
    assert len(assumptions.rationale) >= 5
    assert any("25%" in r or "0.25" in r for r in assumptions.rationale)
    assert refs  # the DCF is grounded in real metric refs, never asserted bare


def test_derive_dcf_assumptions_skips_when_revenue_non_positive(fake_data):
    bad_statements = fake_data.statements.model_copy(deep=True)
    bad_statements.annual[-1] = bad_statements.annual[-1].model_copy(update={"revenue": -1.0})

    assumptions, skip_reason, refs = _derive_dcf_assumptions(fake_data.metrics, bad_statements)

    assert assumptions is None
    assert "revenue" in skip_reason
    assert refs == []


async def test_valuation_offline_runs_dcf_and_records_methodology(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = ValuationAgent(deps)
    # In a real run, financials (wave 1) already populated state.metrics before valuation (wave 2) starts.
    state = make_state(fake_data.ticker, peers=None, metrics=fake_data.metrics)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    valuation = result.state_updates["valuation"]
    assert valuation.dcf is not None
    assert len(valuation.methodology_notes) >= 5
    assert valuation.multiples

    for f in result.output.findings:
        assert f.status != FindingStatus.UNVERIFIED
        if f.kind == FindingKind.CALCULATED:
            assert f.metric_refs
            for ref in f.metric_refs:
                assert ref in fake_data.metrics.values
        elif f.kind == FindingKind.INTERPRETATION:
            assert f.metric_refs or f.evidence_ids


async def test_valuation_offline_skips_dcf_gracefully_when_data_insufficient(fake_data, events, offline_llm, settings):
    fake_data.statements.annual[-1] = fake_data.statements.annual[-1].model_copy(update={"revenue": 0.0})
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = ValuationAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    valuation = result.state_updates["valuation"]
    assert valuation.dcf is None
    assert any("DCF skipped" in n for n in valuation.methodology_notes)
    assert all(f.claim.find("discounted cash flow") == -1 for f in result.output.findings)


async def test_valuation_generative_cannot_alter_dcf_assumptions(fake_data, events, scripted_llm, settings):
    _, _, refs = _derive_dcf_assumptions(fake_data.metrics, fake_data.statements)
    scripted_llm.script(
        AgentName.VALUATION,
        {
            "structured": AgentAnswer(
                summary="Valuation looks reasonable versus peers.",
                findings=[
                    DraftFinding(
                        claim="The DCF model implies solid upside based on the platform's computed assumptions.",
                        kind=FindingKind.INTERPRETATION,
                        section=ReportSection.VALUATION,
                        metric_refs=refs,
                        confidence=Confidence.MEDIUM,
                    )
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = ValuationAgent(deps)
    state = make_state(fake_data.ticker, metrics=fake_data.metrics)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    valuation = result.state_updates["valuation"]
    # the DCF result was computed by the agent's own deterministic code, not by the LLM
    assert valuation.dcf is not None
    assert valuation.dcf.assumptions.discount_rate == 0.09
    assert valuation.dcf.assumptions.terminal_growth == 0.025
    # the LLM call itself had no tool access, so it could not have invented or recomputed the DCF
    assert scripted_llm.requests[-1].tools == []
    f = result.output.findings[0]
    assert f.status != FindingStatus.UNVERIFIED
