"""The live read path must never let a stale graph checkpoint outrank a finished run.

Regression: a run that failed inside the intake node reported "queued" from every read endpoint
indefinitely. LangGraph checkpoints the state that went *into* a step, so when the node raised, the
checkpoint still held the pre-intake state while the runner wrote FAILED to the store -- and `live_state`
preferred the checkpoint. The UI polled a run that would never move.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from meridian.api import live
from meridian.api.memory_store import RunRecord
from meridian.schemas.enums import RunStatus
from meridian.schemas.research import ResearchRequest
from meridian.schemas.state import ResearchState


def _state(status: RunStatus, query: str = "Analyse Lowe's") -> ResearchState:
    return ResearchState(session_id="run_1", request=ResearchRequest(query=query), status=status)


@dataclass
class _Snapshot:
    values: Any


class _App:
    def __init__(self, values: Any) -> None:
        self._values = values
        self.calls = 0

    async def aget_state(self, config: dict[str, Any]) -> _Snapshot:
        self.calls += 1
        return _Snapshot(self._values)


class _Runner:
    def __init__(self, checkpoint: Any, stored: ResearchState | None) -> None:
        self.app = _App(checkpoint)
        self._stored = stored

    async def status(self, session_id: str) -> ResearchState | None:
        return self._stored


class _Store:
    def __init__(self, state: ResearchState | None) -> None:
        self._state = state

    async def get_meta(self, session_id: str) -> RunRecord | None:
        if self._state is None:
            return None
        now = datetime.now(UTC)
        return RunRecord(session_id="run_1", state=self._state, created_at=now, updated_at=now)


class _Runtime:
    def __init__(self, checkpoint: Any, stored: ResearchState | None) -> None:
        self.runner = _Runner(checkpoint, stored)
        self.store = _Store(stored)


async def test_failed_run_is_not_reported_as_queued_by_a_stale_checkpoint() -> None:
    stored = _state(RunStatus.FAILED)
    runtime = _Runtime(checkpoint=_state(RunStatus.QUEUED), stored=stored)

    state = await live.live_state(runtime, "run_1")

    assert state is not None
    assert state.status is RunStatus.FAILED
    assert runtime.runner.app.calls == 0, "a terminal run should not need the checkpoint at all"


async def test_terminal_store_record_wins_for_every_terminal_status() -> None:
    for status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        runtime = _Runtime(checkpoint=_state(RunStatus.RESEARCHING), stored=_state(status))
        state = await live.live_state(runtime, "run_1")
        assert state is not None and state.status is status


async def test_in_flight_run_still_reads_through_the_checkpoint() -> None:
    """The whole point of the fast path: the store is only written at ainvoke boundaries."""
    runtime = _Runtime(checkpoint=_state(RunStatus.RESEARCHING), stored=_state(RunStatus.QUEUED))

    state = await live.live_state(runtime, "run_1")

    assert state is not None
    assert state.status is RunStatus.RESEARCHING
    assert runtime.runner.app.calls == 1


async def test_store_is_used_when_the_checkpoint_is_empty() -> None:
    """A run started by a previous process: the in-memory checkpointer did not survive the restart."""
    runtime = _Runtime(checkpoint=None, stored=_state(RunStatus.RESEARCHING))

    state = await live.live_state(runtime, "run_1")

    assert state is not None
    assert state.status is RunStatus.RESEARCHING


async def test_live_record_reports_the_terminal_status() -> None:
    runtime = _Runtime(checkpoint=_state(RunStatus.QUEUED), stored=_state(RunStatus.FAILED))

    rec = await live.live_record(runtime, "run_1")

    assert rec is not None
    assert rec.state.status is RunStatus.FAILED


async def test_live_record_is_none_for_a_run_that_never_existed() -> None:
    runtime = _Runtime(checkpoint=None, stored=None)

    assert await live.live_record(runtime, "run_1") is None
