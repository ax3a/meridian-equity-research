"""Conditional-edge routing functions.

Kept separate from the node bodies: a node *does* something (and returns a state update); a routing
function only *decides* where to go next by reading state that a node already wrote. None of these
mutate state.
"""

from __future__ import annotations

from langgraph.types import Send

from meridian.graph.nodes import WorkerInput
from meridian.schemas.enums import TaskStatus
from meridian.schemas.state import ResearchState


def route_dispatch(state: ResearchState) -> list[Send] | str:
    """Fan out the batch `dispatch` just marked RUNNING to the matching specialist worker nodes."""
    batch = [t for t in state.tasks.values() if t.status == TaskStatus.RUNNING and t.wave == state.current_wave]
    if not batch:
        # Nothing runnable (e.g. every pending task in the batch turned out to be a duplicate fingerprint):
        # let the collector re-evaluate what to do next from the current state.
        return "advance_wave"
    return [Send(task.agent.value, WorkerInput(task=task, snapshot=state)) for task in batch]


def _has_pending(state: ResearchState) -> bool:
    return any(t.status == TaskStatus.PENDING for t in state.tasks.values())


def route_after_wave(state: ResearchState) -> str:
    """Runs after every worker batch (initial waves, supervisor follow-up, revision, feedback extra-work).

    Order matters: more pending tasks always win (keeps multi-wave plans and supervisor follow-up waves
    progressing one wave at a time); otherwise `rework_agents`/`approval` tell us which loop we were just
    running so we can return to the right place without threading extra state through task.wave.
    """
    if _has_pending(state):
        return "dispatch"
    if state.rework_agents:
        return "critic"
    if state.approval == "changes_requested":
        return "write_report"
    return "supervisor_review"


def route_after_supervisor(state: ResearchState) -> str:
    """`supervisor_review` seeds follow-up tasks (bounded by `max_supervisor_loops`) or hands off to critic."""
    return "dispatch" if _has_pending(state) else "critic"


def route_after_critic(state: ResearchState) -> str:
    if state.rework_agents:
        return "revise"
    if state.require_approval and state.approval != "approved":
        return "human_review"
    return "write_report"


def route_after_human(state: ResearchState) -> str:
    return "dispatch" if _has_pending(state) else "write_report"
