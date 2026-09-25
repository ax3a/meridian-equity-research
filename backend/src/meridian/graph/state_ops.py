"""Pure mapping from an agent's execution result into a `ResearchState` partial update.

Kept separate from `nodes.py` so node functions stay thin: gather inputs, call the agent/protocol,
hand the result to `updates_from_result`, return whatever it produces.
"""

from __future__ import annotations

from typing import Any

from meridian.agents.base import AgentResult
from meridian.schemas.enums import TaskStatus
from meridian.schemas.research import ResearchTask
from meridian.schemas.telemetry import RunError


def updates_from_result(result: AgentResult, task: ResearchTask) -> dict[str, Any]:
    """Map one agent's `AgentResult` for `task` into a `ResearchState` update dict.

    Every key here matches a `ResearchState` field name; reducer-annotated fields (outputs, sources,
    evidence, tool_calls, usage, completed_fingerprints, tasks, timings, errors, output_history) merge
    correctly even when several worker nodes return updates in the same super-step.
    """
    output = result.output
    updated_task = task.model_copy(
        update={
            "status": output.status,
            "attempts": task.attempts + 1,
            "error": output.error,
            "started_at": output.started_at or task.started_at,
            "finished_at": output.finished_at,
        }
    )

    update: dict[str, Any] = {
        "outputs": {task.agent.value: output},
        "output_history": [output],
        "tasks": {task.id: updated_task},
        "sources": dict(result.sources),
        "evidence": dict(result.evidence),
        "tool_calls": list(result.tool_calls),
        "usage": list(result.usage),
    }

    # Once a fingerprint has been attempted (success or failure) it must never be dispatched again.
    if task.fingerprint:
        update["completed_fingerprints"] = [task.fingerprint]

    duration = output.duration_ms
    if duration is not None:
        update["timings"] = {f"{task.agent.value}:{task.id}": duration}

    if output.status == TaskStatus.FAILED:
        update["errors"] = [
            RunError(agent=task.agent, stage="agent", message=output.error or "agent failed", retryable=False)
        ]

    # Structured payloads the agent produced for shared state (e.g. {"metrics": FinancialMetrics(...)}).
    for key, value in result.state_updates.items():
        update[key] = value

    return update
