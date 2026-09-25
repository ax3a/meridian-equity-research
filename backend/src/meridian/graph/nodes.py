"""Graph node functions.

Nodes are built by `builder.build_graph` as closures over an `AgentSet`, `Settings` and `EventSink`, so
they stay free functions here and get their dependencies bound once at graph-construction time. Every
node function is thin: gather inputs from `state`, call the relevant agent/protocol method, hand the
result to `state_ops`/small local helpers, and return the partial state update dict.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from meridian.agents.base import AgentResult
from meridian.agents.contracts import AgentSet, Specialist
from meridian.agents.validation import ValidationReport
from meridian.core.config import Settings
from meridian.core.ids import utcnow
from meridian.core.logging import get_logger
from meridian.graph import state_ops
from meridian.observability.events import EventSink
from meridian.schemas.enums import AgentName, FeedbackAction, RunStatus, TaskStatus, Verdict
from meridian.schemas.events import EventType, ProgressEvent
from meridian.schemas.findings import AgentOutput
from meridian.schemas.research import HumanFeedback, ResearchTask
from meridian.schemas.state import ResearchState

log = get_logger(__name__)


class WorkerInput(BaseModel):
    """Input schema for specialist worker nodes, dispatched via `Send`."""

    task: ResearchTask
    snapshot: ResearchState


def _pending_tasks(state: ResearchState) -> list[ResearchTask]:
    return [t for t in state.tasks.values() if t.status == TaskStatus.PENDING]


async def _emit(
    events: EventSink,
    state: ResearchState,
    event_type: EventType,
    message: str,
    *,
    agent: AgentName | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    await events.emit(
        ProgressEvent(session_id=state.session_id, type=event_type, agent=agent, message=message, data=data or {})
    )


# ---------------------------------------------------------------------------
# intake / plan
# ---------------------------------------------------------------------------


def make_intake_node(agents: AgentSet, events: EventSink):
    async def intake(state: ResearchState) -> dict[str, Any]:
        await _emit(events, state, EventType.RUN_STARTED, f"starting research: {state.request.query}")
        result = await agents.supervisor.resolve(state)
        await _emit(
            events,
            state,
            EventType.COMPANY_RESOLVED,
            f"resolved company: {result.company.name} ({result.company.ticker})",
        )
        return {
            "company": result.company,
            "sources": dict(result.sources),
            "evidence": dict(result.evidence),
            "usage": list(result.usage),
            "status": RunStatus.PLANNING,
        }

    return intake


def make_plan_node(agents: AgentSet, events: EventSink):
    async def plan(state: ResearchState) -> dict[str, Any]:
        result = await agents.supervisor.plan(state)
        tasks = {t.id: t for t in result.plan.tasks}
        waves = sorted({t.wave for t in result.plan.tasks})
        await _emit(
            events,
            state,
            EventType.PLAN_CREATED,
            f"plan created: {len(result.plan.tasks)} task(s) across {len(waves)} wave(s)",
            data={"skipped_agents": result.plan.skipped_agents, "waves": waves},
        )
        return {"plan": result.plan, "tasks": tasks, "status": RunStatus.RESEARCHING, "usage": list(result.usage)}

    return plan


# ---------------------------------------------------------------------------
# dispatch / workers / advance_wave
# ---------------------------------------------------------------------------


def make_dispatch_node(events: EventSink):
    """Marks the next runnable batch (lowest wave among pending, dedupe-by-fingerprint) as RUNNING.

    Guardrails enforced here:
    - a task whose fingerprint is already in `state.completed_fingerprints` is never dispatched; it is
      marked SKIPPED instead.
    - two pending tasks that share a fingerprint (e.g. a stale duplicate) are collapsed to one dispatch;
      the rest are marked SKIPPED.
    """

    async def dispatch(state: ResearchState) -> dict[str, Any]:
        pending = _pending_tasks(state)
        if not pending:
            return {}

        seen_fingerprints = set(state.completed_fingerprints)
        updates: dict[str, ResearchTask] = {}
        runnable: list[ResearchTask] = []
        for task in sorted(pending, key=lambda t: (t.wave, t.id)):
            fp = task.fingerprint
            if fp and fp in seen_fingerprints:
                updates[task.id] = task.model_copy(
                    update={"status": TaskStatus.SKIPPED, "error": "duplicate fingerprint: already dispatched"}
                )
                continue
            if fp:
                seen_fingerprints.add(fp)
            runnable.append(task)

        if not runnable:
            return {"tasks": updates} if updates else {}

        wave = min(t.wave for t in runnable)
        batch = [t for t in runnable if t.wave == wave]
        now = utcnow()
        for task in batch:
            updates[task.id] = task.model_copy(update={"status": TaskStatus.RUNNING, "started_at": now})

        await _emit(
            events,
            state,
            EventType.WAVE_STARTED,
            f"wave {wave}: dispatching {len(batch)} agent(s)",
            data={"wave": wave, "agents": [t.agent.value for t in batch]},
        )
        return {"tasks": updates, "current_wave": wave}

    return dispatch


def _failed_result(agent: AgentName, task: ResearchTask, exc: Exception) -> AgentResult:
    now = utcnow()
    output = AgentOutput(
        agent=agent,
        task_id=task.id,
        status=TaskStatus.FAILED,
        summary="",
        error=f"{type(exc).__name__}: {exc}",
        started_at=now,
        finished_at=now,
    )
    return AgentResult(
        output=output, sources={}, evidence={}, tool_calls=[], usage=[], state_updates={}, validation=ValidationReport()
    )


def make_worker_node(name: AgentName, specialist: Specialist, events: EventSink):
    """One node per specialist. A specialist that raises is caught here: the run is never aborted."""

    async def worker(input: WorkerInput) -> dict[str, Any]:
        task, snapshot = input.task, input.snapshot
        await _emit(
            events, snapshot, EventType.AGENT_STARTED, f"{name.value} agent running: {task.objective}", agent=name
        )
        try:
            result = await specialist.execute(task, snapshot)
        except Exception as exc:  # graph boundary: a broken specialist must not crash the run
            log.exception("specialist_crashed", agent=name, task_id=task.id)
            result = _failed_result(name, task, exc)

        if result.output.status == TaskStatus.FAILED:
            await _emit(
                events, snapshot, EventType.AGENT_FAILED, f"{name.value} failed: {result.output.error}", agent=name
            )
        else:
            await _emit(
                events,
                snapshot,
                EventType.AGENT_COMPLETED,
                f"{name.value} completed ({len(result.output.findings)} finding(s))",
                agent=name,
            )

        return state_ops.updates_from_result(result, task)

    return worker


async def advance_wave(state: ResearchState) -> dict[str, Any]:
    """Fan-in point after a Send-dispatched batch. Pure pass-through; `route_after_wave` decides next."""
    return {}


# ---------------------------------------------------------------------------
# supervisor_review / critic / revise / human_review
# ---------------------------------------------------------------------------


def make_supervisor_review_node(agents: AgentSet, settings: Settings, events: EventSink):
    async def supervisor_review(state: ResearchState) -> dict[str, Any]:
        decision = await agents.supervisor.review(state)
        updates: dict[str, Any] = {"usage": list(decision.usage)}
        if decision.follow_up and state.supervisor_loops < settings.max_supervisor_loops:
            updates["tasks"] = {t.id: t for t in decision.follow_up}
            updates["supervisor_loops"] = state.supervisor_loops + 1
        await _emit(
            events,
            state,
            EventType.SUPERVISOR_REVIEW,
            decision.summary or "supervisor review complete",
            data={"conflicts": decision.conflicts, "follow_up": len(decision.follow_up)},
        )
        return updates

    return supervisor_review


def make_critic_node(agents: AgentSet, settings: Settings, events: EventSink):
    async def critic(state: ResearchState) -> dict[str, Any]:
        await _emit(events, state, EventType.CRITIC_STARTED, "critic reviewing findings")
        result = await agents.critic.review(state)
        review = result.review
        needs_revision = (
            review.overall_verdict == Verdict.NEEDS_REVISION and state.revision_round < settings.max_revision_rounds
        )
        updates: dict[str, Any] = {
            "critic_reviews": [review],
            "usage": list(result.usage),
            "tool_calls": list(result.tool_calls),
            "rework_notes": result.rework_notes,
            "rework_agents": review.agents_needing_revision() if needs_revision else [],
        }
        if result.updated_outputs:
            updates["outputs"] = result.updated_outputs

        if needs_revision:
            updates["status"] = RunStatus.REVISING
        elif state.require_approval and state.approval != "approved":
            updates["approval"] = "pending"
            updates["status"] = RunStatus.AWAITING_APPROVAL
        else:
            updates["status"] = RunStatus.WRITING

        issue_count = sum(len(r.issues) for r in review.reviews)
        await _emit(
            events,
            state,
            EventType.CRITIC_VERDICT,
            f"critic verdict: {review.overall_verdict.value}",
            data={"round": review.round, "issues": issue_count},
        )
        if updates.get("approval") == "pending":
            await _emit(events, state, EventType.AWAITING_APPROVAL, "awaiting human approval")
        return updates

    return critic


def make_revise_node(agents: AgentSet, events: EventSink):
    async def revise(state: ResearchState) -> dict[str, Any]:
        tasks = agents.supervisor.tasks_for_rework(state, list(state.rework_agents), dict(state.rework_notes))
        await _emit(
            events,
            state,
            EventType.REVISION_STARTED,
            f"revising: {', '.join(a.value for a in state.rework_agents)}",
            data={"round": state.revision_round + 1, "agents": [a.value for a in state.rework_agents]},
        )
        updates: dict[str, Any] = {"revision_round": state.revision_round + 1, "status": RunStatus.RESEARCHING}
        if tasks:
            updates["tasks"] = {t.id: t for t in tasks}
        return updates

    return revise


def _coerce_feedback(raw: Any) -> list[HumanFeedback]:
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [item if isinstance(item, HumanFeedback) else HumanFeedback.model_validate(item) for item in items]


def make_human_review_node(agents: AgentSet, events: EventSink):
    async def human_review(state: ResearchState) -> dict[str, Any]:
        if not (state.require_approval and state.approval == "pending"):
            return {}

        from langgraph.types import interrupt  # imported lazily: keeps this module importable without langgraph

        payload = {
            "session_id": state.session_id,
            "plan_rationale": state.plan.rationale if state.plan else "",
            "sections_with_findings": sorted({f.section.value for f in state.findings()}),
        }
        raw = interrupt(payload)
        feedback = _coerce_feedback(raw)

        if not feedback or all(f.action == FeedbackAction.APPROVE for f in feedback):
            await _emit(events, state, EventType.FEEDBACK_RECEIVED, "run approved")
            return {"approval": "approved", "status": RunStatus.WRITING, "human_feedback": feedback}

        extra_tasks = agents.supervisor.tasks_for_feedback(state, feedback)
        await _emit(
            events,
            state,
            EventType.FEEDBACK_RECEIVED,
            f"feedback received: {len(feedback)} item(s)",
            data={"actions": [f.action.value for f in feedback]},
        )
        updates: dict[str, Any] = {
            "approval": "changes_requested",
            "human_feedback": feedback,
            "status": RunStatus.RESEARCHING,
        }
        if extra_tasks:
            updates["tasks"] = {t.id: t for t in extra_tasks}
        return updates

    return human_review


# ---------------------------------------------------------------------------
# write_report / finalize
# ---------------------------------------------------------------------------


def make_write_report_node(agents: AgentSet, events: EventSink):
    async def write_report(state: ResearchState) -> dict[str, Any]:
        await _emit(events, state, EventType.REPORT_STARTED, "writing report")
        result = await agents.writer.write(state)
        await _emit(
            events,
            state,
            EventType.REPORT_COMPLETED,
            "report complete",
            data={"sections": len(result.report.sections)},
        )
        return {"report": result.report, "usage": list(result.usage)}

    return write_report


def make_finalize_node(events: EventSink):
    async def finalize(state: ResearchState) -> dict[str, Any]:
        await _emit(events, state, EventType.RUN_COMPLETED, "research run complete")
        return {"status": RunStatus.COMPLETED}

    return finalize
