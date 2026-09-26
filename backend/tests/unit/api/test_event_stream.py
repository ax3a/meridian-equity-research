"""The SSE stream must survive a quiet stretch, and must not end before the durable log does.

Both rules come from a real failure. `_stream_events` used to await `subscription.__anext__()` under
`asyncio.wait_for`; a timeout there cancels the *generator*, running its `finally` -- which deregisters
the subscriber and stops the cross-process forwarder -- so every later `__anext__()` raised
StopAsyncIteration. One agent running longer than the poll timeout killed live updates for the rest of
the run: the first worker-backed test delivered 28 of 70 events to the browser and stopped at
`agent_completed`, never sending `run_completed`.

It went unnoticed because in-process runs rarely paused that long and the frontend's polling fallback
papered over the gap.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from meridian.api.routers import research as research_router
from meridian.schemas.enums import RunStatus
from meridian.schemas.events import EventType, ProgressEvent
from meridian.schemas.research import ResearchRequest
from meridian.schemas.state import ResearchState

SESSION = "run_stream"


def _event(seq: int, kind: EventType = EventType.AGENT_COMPLETED) -> ProgressEvent:
    event = ProgressEvent(session_id=SESSION, type=kind, message=f"event {seq}")
    event.seq = seq
    return event


class _FakeRunner:
    """Emits a couple of events, goes quiet past the poll timeout, then emits the rest."""

    def __init__(self, quiet_for: float) -> None:
        self._quiet_for = quiet_for
        self.subscriptions = 0

    async def subscribe(self, session_id: str, after_seq: int = 0) -> AsyncIterator[ProgressEvent]:
        self.subscriptions += 1
        yield _event(1)
        yield _event(2)
        await asyncio.sleep(self._quiet_for)
        yield _event(3)
        yield _event(4, EventType.RUN_COMPLETED)


class _FakeStore:
    def __init__(self, log: list[ProgressEvent]) -> None:
        self.log = log

    async def list_events_since(self, session_id: str, after_seq: int) -> list[ProgressEvent]:
        return [e for e in self.log if e.seq > after_seq]


class _FakeRuntime:
    def __init__(self, runner: Any, store: Any, status: RunStatus) -> None:
        self.runner = runner
        self.store = store
        self.settings = None
        self._status = status

    def state(self) -> ResearchState:
        return ResearchState(
            session_id=SESSION, request=ResearchRequest(query="Analyse Test Company"), status=self._status
        )


@pytest.fixture
def patched(monkeypatch):
    """Shrink the poll timeout so a "quiet stretch" is milliseconds, not fifteen seconds."""
    monkeypatch.setattr(research_router, "_EVENT_POLL_TIMEOUT_SECONDS", 0.05)

    def _install(runtime: _FakeRuntime) -> None:
        async def fake_live_state(rt: Any, session_id: str) -> ResearchState:
            return runtime.state()

        monkeypatch.setattr(research_router.live, "live_state", fake_live_state)

    return _install


async def _collect(runtime: Any) -> list[str]:
    return [
        e.data
        async for e in research_router._stream_events(runtime, SESSION, 0)  # type: ignore[attr-defined]
    ]


async def test_a_quiet_stretch_does_not_kill_the_stream(patched) -> None:
    runner = _FakeRunner(quiet_for=0.2)  # four times the poll timeout
    runtime = _FakeRuntime(runner, _FakeStore([]), RunStatus.RESEARCHING)
    patched(runtime)

    payloads = await _collect(runtime)

    assert len(payloads) == 4, f"expected all four events, got {len(payloads)}"
    assert "event 4" in payloads[-1]
    assert runner.subscriptions == 1, "the subscription must be established once, not re-established"


async def test_events_written_after_the_last_delivery_are_replayed(patched) -> None:
    """Live delivery is best-effort -- Redis pub/sub keeps no backlog -- so the log has the last word."""
    log = [_event(5), _event(6, EventType.RUN_COMPLETED)]
    runner = _FakeRunner(quiet_for=0.2)
    runtime = _FakeRuntime(runner, _FakeStore(log), RunStatus.RESEARCHING)
    patched(runtime)

    payloads = await _collect(runtime)

    assert "event 5" in " ".join(payloads)
    assert "event 6" in payloads[-1], "the terminal event must reach the client"


async def test_a_finished_run_replays_its_log_and_stops(patched) -> None:
    log = [_event(1), _event(2), _event(3, EventType.RUN_COMPLETED)]
    runner = _FakeRunner(quiet_for=0.0)
    runtime = _FakeRuntime(runner, _FakeStore(log), RunStatus.COMPLETED)
    patched(runtime)

    payloads = await _collect(runtime)

    assert len(payloads) == 3
    assert runner.subscriptions == 0, "a finished run must not open a subscription that nothing will wake"
