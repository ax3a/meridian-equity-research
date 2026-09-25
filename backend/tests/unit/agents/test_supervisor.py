from __future__ import annotations

import pytest

from meridian.agents.supervisor import Supervisor
from meridian.core.errors import CompanyNotFoundError
from meridian.providers.llm.scripted import ScriptedLLMProvider
from meridian.schemas.enums import AgentName, FeedbackAction, TaskStatus
from meridian.schemas.research import HumanFeedback

from .conftest_orchestration import (
    make_company,
    make_deps,
    make_evidence,
    make_output,
    make_source,
    make_state,
    make_tool_registry_with_resolve,
)


async def test_resolve_uses_resolve_company_tool(settings) -> None:
    company = make_company(ticker="MSFT", name="Microsoft")
    source = make_source("directory")
    evidence = make_evidence(source, "Microsoft Corporation, ticker MSFT.")
    tools = make_tool_registry_with_resolve(company, source=source, evidence=evidence)
    supervisor = Supervisor(make_deps(settings, tools=tools))
    state = make_state(query="Research Microsoft", ticker="MSFT")

    result = await supervisor.resolve(state)

    assert result.company.ticker == "MSFT"
    assert evidence.id in result.evidence
    assert source.id in result.sources


async def test_resolve_raises_when_company_not_found(settings) -> None:
    tools = make_tool_registry_with_resolve(None, fail=True)
    supervisor = Supervisor(make_deps(settings, tools=tools))
    state = make_state(query="Research Nonexistent Co", ticker="NOPE")

    with pytest.raises(CompanyNotFoundError):
        await supervisor.resolve(state)


async def test_plan_skips_macro_when_not_relevant(settings) -> None:
    company = make_company(ticker="ACME", sic="7372")  # software, not a financial institution
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company, query="Give me a research report on Acme Corp's cloud business")

    result = await supervisor.plan(state)

    assert AgentName.MACRO not in result.plan.agents()
    assert "macro" in result.plan.skipped_agents


async def test_plan_includes_macro_when_request_asks_about_interest_rates(settings) -> None:
    company = make_company(ticker="ACME", sic="7372")
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company, query="How exposed is Acme Corp to rising interest rates and Fed policy?")

    result = await supervisor.plan(state)

    assert AgentName.MACRO in result.plan.agents()
    assert "macro" not in result.plan.skipped_agents


async def test_plan_quick_depth_drops_macro_and_bull_bear(settings) -> None:
    company = make_company()
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company, depth="quick", query="Quick look at Acme Corp, focus on interest rates")

    result = await supervisor.plan(state)

    agents = result.plan.agents()
    assert AgentName.MACRO not in agents
    assert AgentName.BULL not in agents
    assert AgentName.BEAR not in agents
    assert {"macro", "bull", "bear"} <= set(result.plan.skipped_agents)


async def test_plan_deep_depth_requests_dcf_and_more_peers(settings) -> None:
    company = make_company()
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company, depth="deep", query="Deep dive on Acme Corp")

    result = await supervisor.plan(state)

    valuation_task = next(t for t in result.plan.tasks if t.agent == AgentName.VALUATION)
    competitors_task = next(t for t in result.plan.tasks if t.agent == AgentName.COMPETITORS)
    assert valuation_task.instructions.get("include_dcf") is True
    assert competitors_task.instructions.get("peer_limit", 0) > 4


async def test_invalid_llm_plan_refinement_is_rejected(settings) -> None:
    """An LLM refinement that moves a known agent to the wrong wave is invalid and must be discarded."""
    company = make_company()
    provider = ScriptedLLMProvider()
    provider.script(
        AgentName.SUPERVISOR,
        {
            "structured": {
                "rationale": "moving company research later",
                "tasks": [
                    {
                        "agent": "company",
                        "objective": "Research the company later.",
                        "wave": 3,
                        "reason": "reprioritized",
                    }
                ],
                "drop_agents": {},
            }
        },
    )
    supervisor = Supervisor(make_deps(settings, llm=provider))
    state = make_state(company=company, query="Research Acme Corp")

    deterministic = supervisor._deterministic_plan(state)
    result = await supervisor.plan(state)

    assert result.plan.agents() == deterministic.agents()
    company_task = next(t for t in result.plan.tasks if t.agent == AgentName.COMPANY)
    assert company_task.wave == 1  # the invalid wave-3 proposal was discarded


async def test_valid_llm_plan_refinement_is_applied(settings) -> None:
    company = make_company()
    provider = ScriptedLLMProvider()
    provider.script(
        AgentName.SUPERVISOR,
        {
            "structured": {
                "rationale": "sharpen the company objective",
                "tasks": [
                    {
                        "agent": "company",
                        "objective": "Research Acme Corp with emphasis on its cloud segment.",
                        "wave": 1,
                        "reason": "user asked about cloud",
                    }
                ],
                "drop_agents": {},
            }
        },
    )
    supervisor = Supervisor(make_deps(settings, llm=provider))
    state = make_state(company=company, query="Research Acme Corp")

    result = await supervisor.plan(state)

    company_task = next(t for t in result.plan.tasks if t.agent == AgentName.COMPANY)
    assert "cloud segment" in company_task.objective


async def test_review_requests_rework_for_failed_agent(settings) -> None:
    company = make_company()
    failed_output = make_output(AgentName.NEWS, [], status=TaskStatus.FAILED, error="provider timeout")
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company, outputs=[failed_output])

    decision = await supervisor.review(state)

    assert any(t.agent == AgentName.NEWS for t in decision.follow_up)
    assert any("news" in c for c in decision.conflicts)


async def test_review_respects_supervisor_loop_cap(settings) -> None:
    company = make_company()
    failed_output = make_output(AgentName.NEWS, [], status=TaskStatus.FAILED, error="provider timeout")
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company, outputs=[failed_output], supervisor_loops=settings.max_supervisor_loops)

    decision = await supervisor.review(state)

    assert decision.follow_up == []


def test_tasks_for_rework_are_fingerprint_distinct_from_original(settings) -> None:
    company = make_company()
    supervisor = Supervisor(make_deps(settings))
    original_output = make_output(AgentName.NEWS, [], revision=0)
    state = make_state(company=company, outputs=[original_output])

    rework = supervisor.tasks_for_rework(state, [AgentName.NEWS], {"news": "add more recent sources"})

    assert len(rework) == 1
    assert rework[0].revision == 1
    assert rework[0].fingerprint  # non-empty, and distinct because revision+instructions changed
    baseline = supervisor.tasks_for_rework(state, [AgentName.NEWS], {})
    assert rework[0].fingerprint != baseline[0].fingerprint


def test_tasks_for_feedback_add_competitor_on_fresh_agent_starts_at_revision_zero(settings) -> None:
    company = make_company()
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company)  # competitors never ran yet
    feedback = [HumanFeedback(action=FeedbackAction.ADD_COMPETITOR, ticker="AMD")]

    tasks = supervisor.tasks_for_feedback(state, feedback)

    assert len(tasks) == 1
    assert tasks[0].agent == AgentName.COMPETITORS
    assert tasks[0].instructions["add_ticker"] == "AMD"
    assert tasks[0].revision == 0


def test_tasks_for_feedback_add_competitor_after_a_run_bumps_revision(settings) -> None:
    company = make_company()
    supervisor = Supervisor(make_deps(settings))
    prior_output = make_output(AgentName.COMPETITORS, [], revision=0)
    state = make_state(company=company, outputs=[prior_output])
    feedback = [HumanFeedback(action=FeedbackAction.ADD_COMPETITOR, ticker="AMD")]

    tasks = supervisor.tasks_for_feedback(state, feedback)

    assert len(tasks) == 1
    assert tasks[0].revision == 1


def test_tasks_for_feedback_ignores_approve_and_comment(settings) -> None:
    company = make_company()
    supervisor = Supervisor(make_deps(settings))
    state = make_state(company=company)
    feedback = [
        HumanFeedback(action=FeedbackAction.APPROVE),
        HumanFeedback(action=FeedbackAction.COMMENT, comment="lgtm"),
    ]

    tasks = supervisor.tasks_for_feedback(state, feedback)

    assert tasks == []
