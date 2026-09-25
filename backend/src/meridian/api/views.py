"""Pure functions turning a `ResearchState` (however it was persisted) into the frozen API response
models from `schemas/api.py`.

Keeping all of this state-driven (rather than re-querying normalised DB tables) means every response
shape behaves identically whether the run is backed by `LocalRunStore` (no database) or `DbRunStore`
(Postgres) -- both ultimately hand this module a `ResearchState`.
"""

from __future__ import annotations

from typing import Any

from meridian.core.config import Settings
from meridian.core.errors import ConflictError, NotFoundError
from meridian.observability.usage import summarize_usage
from meridian.schemas.api import (
    AgentProgress,
    AgentRunView,
    ResearchDetail,
    ResearchSummary,
    ReviewPackage,
    ReviewSectionPreview,
    SourceView,
    StatusView,
    TraceView,
)
from meridian.schemas.enums import AgentName, FeedbackAction, RunStatus, TaskStatus
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState

_STAGE_PROGRESS: dict[RunStatus, float] = {
    RunStatus.QUEUED: 0.0,
    RunStatus.PLANNING: 0.08,
    RunStatus.RESEARCHING: 0.2,
    RunStatus.REVIEWING: 0.65,
    RunStatus.REVISING: 0.7,
    RunStatus.AWAITING_APPROVAL: 0.8,
    RunStatus.WRITING: 0.9,
    RunStatus.COMPLETED: 1.0,
    RunStatus.FAILED: 1.0,
    RunStatus.CANCELLED: 1.0,
}


def compute_progress(state: ResearchState) -> float:
    """A rough 0..1 progress estimate. Exact within `RESEARCHING` (fraction of tasks settled)."""
    if state.status == RunStatus.RESEARCHING and state.tasks:
        tasks = list(state.tasks.values())
        settled = sum(1 for t in tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED))
        frac = settled / len(tasks) if tasks else 0.0
        return round(min(0.6, 0.15 + 0.45 * frac), 3)
    return _STAGE_PROGRESS.get(state.status, 0.0)


def _latest_task_per_agent(state: ResearchState) -> list[ResearchTask]:
    latest: dict[AgentName, ResearchTask] = {}
    order: list[AgentName] = []
    for task in state.tasks.values():
        prev = latest.get(task.agent)
        if prev is None:
            order.append(task.agent)
        if prev is None or (task.revision, task.wave) >= (prev.revision, prev.wave):
            latest[task.agent] = task
    return [latest[a] for a in order]


def agent_progress(state: ResearchState) -> list[AgentProgress]:
    return [
        AgentProgress(agent=t.agent, status=t.status, wave=t.wave, revision=t.revision, objective=t.objective)
        for t in _latest_task_per_agent(state)
    ]


def status_message(state: ResearchState) -> str | None:
    if state.status == RunStatus.FAILED and state.errors:
        return state.errors[-1].message
    if state.status == RunStatus.AWAITING_APPROVAL:
        return "awaiting human approval"
    if state.status == RunStatus.CANCELLED:
        return "run cancelled"
    return None


def to_summary(settings: Settings, rec: Any) -> ResearchSummary:
    """`rec` is a `RunRecord` from either `api.memory_store` or `db.run_store` (same shape, no shared base)."""
    state: ResearchState = rec.state
    return ResearchSummary(
        id=rec.session_id,
        query=state.request.query,
        company=state.company,
        status=state.status,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        has_report=state.report is not None,
        llm_mode=settings.llm_mode,
        data_mode=settings.data_mode,
    )


def to_detail(settings: Settings, rec: Any) -> ResearchDetail:
    state: ResearchState = rec.state
    return ResearchDetail(
        id=rec.session_id,
        request=state.request,
        status=state.status,
        company=state.company,
        plan=state.plan,
        approval=state.approval,
        current_wave=state.current_wave,
        revision_round=state.revision_round,
        critic_reviews=state.critic_reviews,
        human_feedback=state.human_feedback,
        errors=state.errors,
        has_report=state.report is not None,
        llm_mode=settings.llm_mode,
        data_mode=settings.data_mode,
        uses_snapshot_data=state.uses_snapshot_data(),
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


def to_status_view(session_id: str, state: ResearchState) -> StatusView:
    return StatusView(
        id=session_id,
        status=state.status,
        progress=compute_progress(state),
        current_wave=state.current_wave,
        revision_round=state.revision_round,
        approval=state.approval,
        agents=agent_progress(state),
        message=status_message(state),
    )


def to_agent_run_views(state: ResearchState) -> list[AgentRunView]:
    history = state.output_history or list(state.outputs.values())
    views = []
    for output in history:
        task = state.tasks.get(output.task_id)
        views.append(
            AgentRunView(
                agent=output.agent,
                task_id=output.task_id,
                objective=task.objective if task else "",
                status=output.status,
                wave=task.wave if task else 0,
                revision=output.revision,
                summary=output.summary,
                findings=output.findings,
                tools_used=output.tools_used,
                duration_ms=output.duration_ms,
                error=output.error,
            )
        )
    return views


def to_source_views(state: ResearchState) -> list[SourceView]:
    evidence_by_source: dict[str, list[str]] = {}
    for evidence in state.evidence.values():
        evidence_by_source.setdefault(evidence.source_id, []).append(evidence.id)
    findings = state.findings()
    views = []
    for source in state.sources.values():
        ev_ids = set(evidence_by_source.get(source.id, []))
        cited_by = [f.id for f in findings if ev_ids.intersection(f.evidence_ids)]
        views.append(
            SourceView(
                source=source,
                evidence=[state.evidence[eid] for eid in evidence_by_source.get(source.id, [])],
                cited_by_findings=cited_by,
            )
        )
    return views


def to_trace_view(state: ResearchState) -> TraceView:
    breakdown, total_tokens, total_cost = summarize_usage(state.usage)
    return TraceView(
        session_id=state.session_id,
        agent_runs=to_agent_run_views(state),
        tool_calls=state.tool_calls,
        usage=breakdown,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        timings_ms=state.timings,
        errors=state.errors,
    )


def to_review_package(state: ResearchState) -> ReviewPackage:
    if not (state.approval == "pending" and state.status == RunStatus.AWAITING_APPROVAL):
        raise ConflictError(f"run {state.session_id} is not awaiting approval (status={state.status.value})")
    if state.company is None or state.plan is None:
        raise NotFoundError(f"run {state.session_id} has no plan/company to review yet")
    preliminary = [
        ReviewSectionPreview(agent=agent, summary=output.summary, findings=output.findings)
        for agent, output in state.outputs.items()
        if agent != AgentName.REPORT_WRITER.value
    ]
    return ReviewPackage(
        session_id=state.session_id,
        company=state.company,
        plan=state.plan,
        sources=list(state.sources.values()),
        preliminary=preliminary,
        critic=state.critic_reviews[-1] if state.critic_reviews else None,
        available_actions=[a.value for a in FeedbackAction],
    )
