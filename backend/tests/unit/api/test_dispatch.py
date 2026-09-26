"""Dispatch decides where a run executes, and admits against the right source of truth.

In-process, a local counter is exact. With workers, several API processes admit against a pool of
workers none of them owns, so capacity has to come from the shared run store -- a per-process counter
would let every replica admit the full limit by itself.
"""

from __future__ import annotations

import asyncio
from typing import Any

from meridian.api.concurrency import RunAdmission
from meridian.api.dispatch import InProcessDispatcher, WorkerDispatcher
from meridian.graph.jobs import JobKind, RunJob
from meridian.schemas.enums import FeedbackAction
from meridian.schemas.research import HumanFeedback, ResearchRequest


class _FakeRunner:
    def __init__(self) -> None:
        self.created: list[ResearchRequest] = []
        self.started: list[ResearchRequest] = []
        self.resumed: list[tuple[str, Any]] = []
        self.cancelled: list[str] = []

    async def create(self, request: ResearchRequest) -> str:
        self.created.append(request)
        return "run_created"

    async def start(self, request: ResearchRequest) -> str:
        self.started.append(request)
        return "run_started"

    def resume(self, session_id: str, feedback: Any) -> None:
        self.resumed.append((session_id, feedback))

    async def wait_idle(self, session_id: str) -> None:
        return None

    async def cancel(self, session_id: str) -> None:
        self.cancelled.append(session_id)


class _FakeQueue:
    """Models the Lua reservation: prune, then admit only while under the limit."""

    def __init__(self, *, fail_reserve: bool = False) -> None:
        self.jobs: list[RunJob] = []
        self.admitted: set[str] = set()
        self._fail_reserve = fail_reserve

    async def enqueue(self, job: RunJob) -> None:
        self.jobs.append(job)

    async def reserve_slot(self, member: str, limit: int, stale_after_seconds: float) -> bool:
        if self._fail_reserve:
            raise RuntimeError("redis down")
        if member in self.admitted:
            return True
        if len(self.admitted) >= limit:
            return False
        self.admitted.add(member)
        return True

    async def release_slot(self, member: str) -> None:
        self.admitted.discard(member)


class _FakeStore:
    def __init__(self, active: int = 0) -> None:
        self.active = active
        self.calls = 0

    async def count_active(self) -> int:
        self.calls += 1
        return self.active


def _request() -> ResearchRequest:
    return ResearchRequest(query="Analyse Test Company", ticker="TST")


async def test_in_process_dispatcher_executes_locally() -> None:
    runner = _FakeRunner()
    dispatcher = InProcessDispatcher(runner, RunAdmission(limit=2))  # type: ignore[arg-type]

    session_id = await dispatcher.start(_request())

    assert session_id == "run_started"
    assert runner.started and not runner.created, "in-process mode runs it here, it does not queue it"


async def test_worker_dispatcher_persists_then_queues_without_executing() -> None:
    runner, queue = _FakeRunner(), _FakeQueue()
    dispatcher = WorkerDispatcher(runner, queue, _FakeStore(), limit=4, slot_stale_seconds=1800)  # type: ignore[arg-type]

    session_id = await dispatcher.start(_request())

    assert session_id == "run_created"
    assert runner.created and not runner.started, "the API must not execute the run itself"
    assert [j.kind for j in queue.jobs] == [JobKind.START]
    assert queue.jobs[0].session_id == "run_created"


async def test_worker_dispatcher_queues_feedback_with_the_resume() -> None:
    runner, queue = _FakeRunner(), _FakeQueue()
    dispatcher = WorkerDispatcher(runner, queue, _FakeStore(), limit=4, slot_stale_seconds=1800)  # type: ignore[arg-type]
    feedback = [HumanFeedback(action=FeedbackAction.ADD_COMPETITOR, ticker="AMD")]

    await dispatcher.resume("run_abc", feedback)

    assert not runner.resumed, "the worker holds the run; the API must not resume it locally"
    assert queue.jobs[0].kind is JobKind.RESUME
    assert queue.jobs[0].feedback is not None
    assert queue.jobs[0].feedback[0].ticker == "AMD"


async def test_worker_cancel_is_both_recorded_and_queued() -> None:
    """The stored state must read `cancelled` immediately, and the worker must be told to stop."""
    runner, queue = _FakeRunner(), _FakeQueue()
    dispatcher = WorkerDispatcher(runner, queue, _FakeStore(), limit=4, slot_stale_seconds=1800)  # type: ignore[arg-type]

    await dispatcher.cancel("run_abc")

    assert runner.cancelled == ["run_abc"]
    assert queue.jobs[0].kind is JobKind.CANCEL


async def test_admission_is_reserved_atomically_not_merely_counted() -> None:
    """Counting active runs and comparing to the limit is a read, not a reservation.

    Two requests arriving together both saw the same count and were both admitted, and with several API
    replicas each could admit the whole limit on its own. The reservation is one Lua script, so the
    count and the insert cannot interleave.
    """
    queue = _FakeQueue()
    dispatcher = WorkerDispatcher(_FakeRunner(), queue, _FakeStore(), limit=2, slot_stale_seconds=1800)  # type: ignore[arg-type]

    granted = await asyncio.gather(*(dispatcher.try_admit() for _ in range(10)))

    assert sum(granted) == 2, f"{sum(granted)} admitted against a limit of 2"
    assert len(queue.admitted) == 2


async def test_a_finished_run_gives_its_slot_back() -> None:
    queue = _FakeQueue()
    dispatcher = WorkerDispatcher(_FakeRunner(), queue, _FakeStore(), limit=1, slot_stale_seconds=1800)  # type: ignore[arg-type]

    assert await dispatcher.try_admit() is True
    session_id = await dispatcher.start(_request())
    assert await dispatcher.try_admit() is False, "the cap must still hold while the run is active"

    await dispatcher.release(session_id)

    assert await dispatcher.try_admit() is True


async def test_a_redis_failure_admits_rather_than_refusing_everything() -> None:
    """Refusing every run because Redis hiccuped is a worse failure than briefly exceeding the cap."""
    dispatcher = WorkerDispatcher(
        _FakeRunner(),
        _FakeQueue(fail_reserve=True),
        _FakeStore(),
        limit=1,
        slot_stale_seconds=1800,
    )  # type: ignore[arg-type]

    assert await dispatcher.try_admit() is True
