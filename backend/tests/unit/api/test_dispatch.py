"""Dispatch decides where a run executes, and admits against the right source of truth.

In-process, a local counter is exact. With workers, several API processes admit against a pool of
workers none of them owns, so capacity has to come from the shared run store -- a per-process counter
would let every replica admit the full limit by itself.
"""

from __future__ import annotations

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
    def __init__(self) -> None:
        self.jobs: list[RunJob] = []

    async def enqueue(self, job: RunJob) -> None:
        self.jobs.append(job)


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
    dispatcher = WorkerDispatcher(runner, queue, _FakeStore(), limit=4)  # type: ignore[arg-type]

    session_id = await dispatcher.start(_request())

    assert session_id == "run_created"
    assert runner.created and not runner.started, "the API must not execute the run itself"
    assert [j.kind for j in queue.jobs] == [JobKind.START]
    assert queue.jobs[0].session_id == "run_created"


async def test_worker_dispatcher_queues_feedback_with_the_resume() -> None:
    runner, queue = _FakeRunner(), _FakeQueue()
    dispatcher = WorkerDispatcher(runner, queue, _FakeStore(), limit=4)  # type: ignore[arg-type]
    feedback = [HumanFeedback(action=FeedbackAction.ADD_COMPETITOR, ticker="AMD")]

    await dispatcher.resume("run_abc", feedback)

    assert not runner.resumed, "the worker holds the run; the API must not resume it locally"
    assert queue.jobs[0].kind is JobKind.RESUME
    assert queue.jobs[0].feedback is not None
    assert queue.jobs[0].feedback[0].ticker == "AMD"


async def test_worker_cancel_is_both_recorded_and_queued() -> None:
    """The stored state must read `cancelled` immediately, and the worker must be told to stop."""
    runner, queue = _FakeRunner(), _FakeQueue()
    dispatcher = WorkerDispatcher(runner, queue, _FakeStore(), limit=4)  # type: ignore[arg-type]

    await dispatcher.cancel("run_abc")

    assert runner.cancelled == ["run_abc"]
    assert queue.jobs[0].kind is JobKind.CANCEL


async def test_worker_admission_reads_the_shared_store() -> None:
    store = _FakeStore(active=3)
    dispatcher = WorkerDispatcher(_FakeRunner(), _FakeQueue(), store, limit=4)  # type: ignore[arg-type]

    assert await dispatcher.try_admit() is True
    store.active = 4
    assert await dispatcher.try_admit() is False
    assert store.calls == 2, "capacity must be read per request, not cached in this process"


async def test_worker_admission_allows_the_run_when_the_store_is_unreachable() -> None:
    """A database hiccup should not make the API refuse every run; that is a worse failure."""

    class _BrokenStore:
        async def count_active(self) -> int:
            raise RuntimeError("database down")

    dispatcher = WorkerDispatcher(_FakeRunner(), _FakeQueue(), _BrokenStore(), limit=1)  # type: ignore[arg-type]

    assert await dispatcher.try_admit() is True
