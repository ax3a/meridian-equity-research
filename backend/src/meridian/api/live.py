"""Reads the *live* graph state for a run, not just whatever was last checkpointed to the `RunStore`.

`ResearchRunner._drive` only calls `store.save_state` at the boundaries of one `ainvoke` (i.e. when a run
pauses for approval or reaches a terminal state) -- a run midway through a wave of specialist agents can
go the full 1-3 minutes of a real research session without a single store write, even though
`ProgressEvent`s are flowing continuously over SSE the whole time. Every `/research/{id}*` read endpoint
that used the store directly would show a stale "queued"/empty view for that entire window.

`ResearchRunner.app` (the compiled LangGraph) is checkpointed after *every* internal step regardless, so
reading through `app.aget_state` gives an always-current snapshot for any run this process has driven.
Only a run started by a *previous* process needs the `RunStore` fallback, since the graph's checkpointer
(`graph.builder.default_checkpointer`, an in-memory `InMemorySaver`) does not survive a restart the way a
`DbRunStore` does.

The checkpoint is a fast path for runs still *in flight*, never an override for a finished one. When a
node raises, LangGraph keeps the checkpoint at the state that went *into* that step -- still "queued" for
a failure during intake -- while the runner records the failure in the store. Preferring the checkpoint
there left a failed run reporting "queued" forever, with the UI polling something that would never move,
so a terminal store record wins over any checkpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from meridian.core.logging import get_logger
from meridian.schemas.enums import TERMINAL_RUN_STATUSES
from meridian.schemas.state import ResearchState

if TYPE_CHECKING:
    from meridian.api.wiring import Runtime

log = get_logger(__name__)


def _coerce_state(raw: Any) -> ResearchState:
    return raw if isinstance(raw, ResearchState) else ResearchState.model_validate(raw)


async def live_state(runtime: Runtime, session_id: str, *, stored: ResearchState | None = None) -> ResearchState | None:
    """The most current `ResearchState` for `session_id`, or `None` if it has never existed.

    `stored` is the store's copy when the caller already holds it, which saves a second read.
    """
    if stored is None:
        stored = await runtime.runner.status(session_id)
    if stored is not None and stored.status in TERMINAL_RUN_STATUSES:
        return stored
    try:
        snapshot = await runtime.runner.app.aget_state({"configurable": {"thread_id": session_id}})
        if snapshot.values:
            return _coerce_state(snapshot.values)
    except Exception:  # the graph's checkpointer is a best-effort fast path; the store is authoritative
        log.warning("live_state_checkpoint_read_failed", session_id=session_id)
    return stored


async def live_record(runtime: Runtime, session_id: str) -> Any:
    """A `RunRecord` (from `api.memory_store` or `db.run_store`) with its `.state` refreshed to the live
    value when one is available. Returns `None` only if the run has never existed at all.
    """
    rec = await runtime.store.get_meta(session_id)
    if rec is None:
        return None
    state = await live_state(runtime, session_id, stored=rec.state)
    if state is not None:
        rec.state = state
    return rec
