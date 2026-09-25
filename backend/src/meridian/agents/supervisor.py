"""The supervisor: resolves the company, builds/refines the research plan, and reviews results for gaps.

`plan()` always builds a deterministic base plan first (which agents run in which wave, adjusted for
`depth` and `focus_areas`) and only then, when a generative LLM is configured, asks it to refine that plan.
The refinement is treated as untrusted advice: it is validated (known specialist agents only, canonical
waves preserved, at most 10 tasks, every dropped agent recorded with a reason) and discarded in favour of
the deterministic plan if it fails validation or the LLM call itself fails.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from meridian.agents.base import AgentDraft, BaseAgent
from meridian.agents.company_extraction import candidate_names
from meridian.agents.contracts import PlanResult, ResolveResult, ReviewDecision
from meridian.agents.critic import parse_figures, within_tolerance
from meridian.core.config import LLMTier
from meridian.core.errors import CompanyNotFoundError
from meridian.core.logging import get_logger
from meridian.schemas.enums import SPECIALIST_AGENTS as _SPECIALIST_AGENTS
from meridian.schemas.enums import AgentName, FeedbackAction, FindingKind, TaskStatus
from meridian.schemas.research import HumanFeedback, ResearchPlan, ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

log = get_logger(__name__)

# Canonical wave for every specialist agent. The LLM refinement may not move an agent to a different wave.
_AGENT_WAVE: dict[AgentName, int] = {
    AgentName.COMPANY: 1,
    AgentName.FINANCIALS: 1,
    AgentName.FILINGS: 1,
    AgentName.NEWS: 1,
    AgentName.MACRO: 1,
    AgentName.COMPETITORS: 2,
    AgentName.VALUATION: 2,
    AgentName.RISK: 2,
    AgentName.BULL: 3,
    AgentName.BEAR: 3,
}

_MACRO_KEYWORDS = (
    "interest rate",
    "interest-rate",
    "rate hike",
    "rate cut",
    "fed ",
    "federal reserve",
    "the fed",
    "inflation",
    "monetary policy",
    "yield curve",
    "treasury yield",
    "recession",
    "macro",
    "central bank",
)

_MAX_PLAN_TASKS = 10


class PlanRefinementTask(BaseModel):
    agent: AgentName
    objective: str = Field(min_length=3, max_length=500)
    wave: int = Field(ge=1, le=4)
    reason: str = ""
    instructions: dict[str, Any] = Field(default_factory=dict)


class PlanRefinement(BaseModel):
    rationale: str = ""
    tasks: list[PlanRefinementTask] = Field(default_factory=list, max_length=_MAX_PLAN_TASKS)
    drop_agents: dict[AgentName, str] = Field(default_factory=dict)


class Supervisor(BaseAgent):
    name: ClassVar[AgentName] = AgentName.SUPERVISOR
    role: ClassVar[str] = "Supervisor"
    mission: ClassVar[str] = (
        "Decides what research is actually needed for this request and routes it: resolves the company, "
        "plans which specialist agents run in which wave, and reviews their output for gaps and conflicts."
    )
    tier: ClassVar[LLMTier] = "planner"
    allowed_tools: ClassVar[frozenset[str]] = frozenset({"resolve_company"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:  # pragma: no cover
        raise NotImplementedError("Supervisor is invoked via resolve()/plan()/review(), not run()/execute()")

    # ---- resolve ----------------------------------------------------------------------------------------
    async def resolve(self, state: ResearchState) -> ResolveResult:
        ctx = self.new_context(state)
        # An explicit ticker wins; otherwise work through candidates extracted from the request text.
        candidates = [state.request.ticker.strip()] if state.request.ticker else candidate_names(state.request.query)
        company = None
        for candidate in candidates:
            inv = await self.tool(ctx, "resolve_company", query=candidate)
            if inv.ok and inv.output is not None:
                company = getattr(inv.output, "company", None)
                if company is not None:
                    break
        if company is None:
            attempted = ", ".join(repr(c) for c in candidates[:6]) or repr(state.request.query)
            raise CompanyNotFoundError(f"could not resolve a company from {state.request.query!r}; tried {attempted}")
        return ResolveResult(
            company=company,
            sources=ctx.ledger.sources,
            evidence=ctx.ledger.evidence,
            tool_calls=ctx.calls,
            usage=self.drain_usage(),
        )

    # ---- plan ---------------------------------------------------------------------------------------------
    async def plan(self, state: ResearchState) -> PlanResult:
        base = self._deterministic_plan(state)
        if not self.generative:
            return PlanResult(plan=base, usage=[])
        refinement: PlanRefinement | None = None
        try:
            refinement = await self._request_refinement(state, base)
        except Exception:  # LLM refinement is best-effort: never let it crash planning.
            log.warning("plan_refinement_failed", session_id=state.session_id, exc_info=True)
        usage = self.drain_usage()
        if refinement is not None and self._validate_refinement(refinement):
            base = self._merge_refinement(base, refinement)
        elif refinement is not None:
            log.info("plan_refinement_rejected", session_id=state.session_id)
        return PlanResult(plan=base, usage=usage)

    def _macro_relevant(self, state: ResearchState) -> bool:
        if state.company is not None and state.company.is_financial_institution:
            return True
        haystack = " ".join([state.request.query, *state.request.focus_areas]).lower()
        return any(kw in haystack for kw in _MACRO_KEYWORDS)

    def _deterministic_plan(self, state: ResearchState) -> ResearchPlan:
        request = state.request
        depth = request.depth
        ticker = state.company.ticker if state.company else (request.ticker or "the company")
        focus = list(request.focus_areas)
        skipped: dict[str, str] = {}
        tasks: list[ResearchTask] = []

        def add(agent: AgentName, wave: int, objective: str, instructions: dict[str, Any] | None = None) -> None:
            instr = dict(instructions or {})
            obj = objective
            if focus:
                instr.setdefault("focus_areas", focus)
                obj = f"{objective} Focus on: {', '.join(focus)}."
            tasks.append(ResearchTask.make(agent, obj, wave, instructions=instr))

        add(AgentName.COMPANY, 1, f"Research {ticker}'s business model, products and competitive position.")
        add(AgentName.FINANCIALS, 1, f"Compute financial statements and key metrics for {ticker}.")
        add(AgentName.FILINGS, 1, f"Extract MD&A, risk factors, segments and material events from {ticker}'s filings.")
        add(AgentName.NEWS, 1, f"Survey recent news and 8-K events for {ticker}.")

        if depth == "quick":
            skipped["macro"] = "depth=quick omits macro analysis"
        elif self._macro_relevant(state):
            add(AgentName.MACRO, 1, f"Assess macro and interest-rate exposure for {ticker}.")
        else:
            skipped["macro"] = "no interest-rate/macro sensitivity indicated by the request or sector"

        competitor_instr = {"peer_limit": 6} if depth == "deep" else {}
        add(AgentName.COMPETITORS, 2, f"Identify peers and compare {ticker} against them.", competitor_instr)
        valuation_instr = {"include_dcf": True} if depth == "deep" else {}
        valuation_obj = (
            f"Build a valuation for {ticker} using multiples" + (" and a DCF" if depth == "deep" else "") + "."
        )
        add(AgentName.VALUATION, 2, valuation_obj, valuation_instr)
        add(AgentName.RISK, 2, f"Categorize key risks for {ticker} across risk categories, tied to evidence.")

        if depth == "quick":
            skipped["bull"] = "depth=quick omits the qualitative bull/bear cases"
            skipped["bear"] = "depth=quick omits the qualitative bull/bear cases"
        else:
            add(AgentName.BULL, 3, f"Build the strongest evidence-based bull case for {ticker}.")
            add(AgentName.BEAR, 3, f"Build the strongest evidence-based bear case for {ticker}.")

        rationale = f"Deterministic plan for depth={depth}"
        if focus:
            rationale += f"; focus_areas={focus}"
        if skipped:
            rationale += f"; skipped={sorted(skipped)}"
        objectives = [t.objective for t in tasks]
        return ResearchPlan(
            objectives=objectives, tasks=tasks, skipped_agents=skipped, rationale=rationale, focus_areas=focus
        )

    async def _request_refinement(self, state: ResearchState, base: ResearchPlan) -> PlanRefinement:
        ctx = self.new_context(state)
        context = {
            "request": state.request.model_dump(mode="json"),
            "deterministic_plan": {
                "tasks": [{"agent": t.agent.value, "wave": t.wave, "objective": t.objective} for t in base.tasks],
                "skipped_agents": base.skipped_agents,
            },
        }
        task = (
            "Review the deterministic research plan below. Propose refinements only if they add real value: "
            "sharper objectives, an agent to add back with a reason, or an agent to drop with a reason. Use "
            "only known specialist agent names and keep each agent in its existing wave. Return an empty "
            "tasks/drop_agents list if the plan is already fine."
        )
        return await self.llm_structured(
            ctx, task=task, schema=PlanRefinement, evidence=[], sources={}, context=context
        )

    def _validate_refinement(self, refinement: PlanRefinement) -> bool:
        if len(refinement.tasks) > _MAX_PLAN_TASKS:
            return False
        for t in refinement.tasks:
            if t.agent not in _SPECIALIST_AGENTS:
                return False
            canonical_wave = _AGENT_WAVE.get(t.agent)
            if canonical_wave is not None and t.wave != canonical_wave:
                return False
        for agent, reason in refinement.drop_agents.items():
            if agent not in _SPECIALIST_AGENTS or not reason.strip():
                return False
        return True

    def _merge_refinement(self, base: ResearchPlan, refinement: PlanRefinement) -> ResearchPlan:
        by_agent: dict[AgentName, ResearchTask] = {t.agent: t for t in base.tasks}
        skipped = dict(base.skipped_agents)
        for agent, reason in refinement.drop_agents.items():
            by_agent.pop(agent, None)
            skipped[agent.value] = reason
        for rt in refinement.tasks:
            by_agent[rt.agent] = ResearchTask.make(rt.agent, rt.objective, rt.wave, instructions=dict(rt.instructions))
            skipped.pop(rt.agent.value, None)
        tasks = sorted(by_agent.values(), key=lambda t: (t.wave, t.agent.value))[:_MAX_PLAN_TASKS]
        suffix = f"; refined via LLM: {refinement.rationale}" if refinement.rationale else "; refined via LLM"
        rationale = base.rationale + suffix
        objectives = [t.objective for t in tasks]
        return ResearchPlan(
            objectives=objectives,
            tasks=tasks,
            skipped_agents=skipped,
            rationale=rationale,
            focus_areas=base.focus_areas,
        )

    # ---- review ---------------------------------------------------------------------------------------------
    async def review(self, state: ResearchState) -> ReviewDecision:
        if state.supervisor_loops >= self.deps.settings.max_supervisor_loops:
            return ReviewDecision(
                follow_up=[], conflicts=[], summary="max_supervisor_loops reached; no further review rounds", usage=[]
            )

        conflicts: list[str] = []
        follow_up: list[ResearchTask] = []

        failed_agents = [AgentName(k) for k, out in state.outputs.items() if out.status == TaskStatus.FAILED]
        for agent in failed_agents:
            out = state.outputs[agent.value]
            conflicts.append(f"{agent.value} task failed: {out.error}")
            note = {agent.value: f"previous attempt failed: {out.error}"}
            follow_up.extend(self.tasks_for_rework(state, [agent], note))

        for agent_str, out in state.outputs.items():
            agent = AgentName(agent_str)
            if out.status == TaskStatus.COMPLETED and not out.findings and agent != AgentName.MACRO:
                conflicts.append(f"{agent.value} completed with no findings")

        conflicts.extend(self._metric_conflicts(state))
        conflicts.extend(self._peer_revenue_conflicts(state))

        summary = "; ".join(conflicts) if conflicts else "no gaps or conflicts detected"
        return ReviewDecision(follow_up=follow_up, conflicts=conflicts, summary=summary, usage=[])

    def _metric_conflicts(self, state: ResearchState) -> list[str]:
        if not state.metrics:
            return []
        notes: list[str] = []
        for f in state.findings():
            if f.kind != FindingKind.CALCULATED or not f.metric_refs:
                continue
            parsed = parse_figures(f.claim)
            if not parsed:
                continue
            for ref in f.metric_refs:
                mv = state.metrics.values.get(ref)
                if mv is None or mv.value is None:
                    continue
                if not any(within_tolerance(p, mv.value) for p in parsed):
                    notes.append(f"{f.agent.value} claim for {ref} disagrees with the computed metric ({mv.value:g})")
        return notes

    def _peer_revenue_conflicts(self, state: ResearchState, rel_tolerance: float = 0.05) -> list[str]:
        if not state.peers or not state.financials or not state.financials.annual:
            return []
        target = next((p for p in state.peers.peers if p.is_target), None)
        if target is None or target.revenue is None:
            return []
        statement_revenue = state.financials.annual[-1].revenue
        if statement_revenue is None:
            return []
        if not within_tolerance(target.revenue, statement_revenue, rel=rel_tolerance):
            return [
                f"peer comparison revenue ({target.revenue:g}) is inconsistent with "
                f"reported statements ({statement_revenue:g})"
            ]
        return []

    # ---- deterministic revision/feedback task builders -------------------------------------------------------
    def _existing_revision(self, state: ResearchState, agent: AgentName) -> int:
        out = state.output(agent)
        if out is not None:
            return out.revision
        for t in state.tasks.values():
            if t.agent == agent:
                return max(t.revision, 0)
        return -1

    def _wave_for(self, state: ResearchState, agent: AgentName) -> int:
        if state.plan is not None:
            for t in state.plan.tasks:
                if t.agent == agent:
                    return t.wave
        return _AGENT_WAVE.get(agent, 1)

    def _objective_for(self, state: ResearchState, agent: AgentName) -> str:
        if state.plan is not None:
            for t in state.plan.tasks:
                if t.agent == agent:
                    return t.objective
        ticker = state.company.ticker if state.company else (state.request.ticker or "the company")
        return f"Research {agent.value} for {ticker}."

    def tasks_for_rework(
        self, state: ResearchState, agents: list[AgentName], notes: dict[str, str]
    ) -> list[ResearchTask]:
        tasks: list[ResearchTask] = []
        for agent in agents:
            revision = self._existing_revision(state, agent) + 1
            note = notes.get(agent.value, "")
            wave = self._wave_for(state, agent)
            base_objective = self._objective_for(state, agent)
            objective = f"{base_objective} REVISION {revision}: address critic feedback"
            if note:
                objective += f" — {note}"
            tasks.append(
                ResearchTask.make(agent, objective, wave, revision=revision, instructions={"rework_notes": note})
            )
        return tasks

    def tasks_for_feedback(self, state: ResearchState, feedback: list[HumanFeedback]) -> list[ResearchTask]:
        tasks: list[ResearchTask] = []
        for fb in feedback:
            agent, instructions, suffix = self._feedback_target(fb)
            if agent is None:
                continue
            revision = self._existing_revision(state, agent) + 1
            wave = self._wave_for(state, agent)
            base_objective = self._objective_for(state, agent)
            objective = f"{base_objective} {suffix} (revision {revision})".strip()
            tasks.append(ResearchTask.make(agent, objective, wave, revision=revision, instructions=instructions))
        return tasks

    def _feedback_target(self, fb: HumanFeedback) -> tuple[AgentName | None, dict[str, Any], str]:
        if fb.action == FeedbackAction.DEEPEN_VALUATION:
            return (AgentName.VALUATION, {"include_dcf": True, "deepen": True}, "Deepen the valuation with a full DCF.")
        if fb.action == FeedbackAction.ADD_COMPETITOR:
            return AgentName.COMPETITORS, {"add_ticker": fb.ticker}, f"Add {fb.ticker} as an explicit peer."
        if fb.action == FeedbackAction.ADD_RISK_ANALYSIS:
            return AgentName.RISK, {"deepen": True}, "Expand the risk analysis."
        if fb.action == FeedbackAction.RERUN_AGENT and fb.agent is not None:
            comment = fb.comment or ""
            return fb.agent, {"comment": comment}, f"Rerun requested by the user: {comment}".rstrip(": ")
        return None, {}, ""
