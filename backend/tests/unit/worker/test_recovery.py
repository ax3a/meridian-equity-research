"""Recovery of runs left behind by a worker that died.

Before the persistent checkpointer this could not exist: the state died with the process. Now it
survives, so a worker can pick a run back up -- but only if something notices it, and only if it is
safe to do so. These tests pin the three rules that a real crash test exposed:

* a run waiting for a *person* is never resumed by a worker;
* a run another worker is still executing is never stolen;
* a claim left behind by a dead worker must not strand its run forever.
"""

from __future__ import annotations

from typing import Any

from meridian.graph.jobs import JobKind, RunJob
from meridian.schemas.enums import RECOVERABLE_RUN_STATUSES, TERMINAL_RUN_STATUSES, RunStatus
from meridian.worker.service import CLAIM_TTL_SECONDS, RunWorker


class _FakeQueue:
    """Claims behave like Redis SET NX: the first caller wins until the key is released."""

    def __init__(self, held: set[str] | None = None) -> None:
        self.held: set[str] = set(held or ())
        self.enqueued: list[RunJob] = []

    async def claim(self, session_id: str, ttl_seconds: int) -> bool:
        if session_id in self.held:
            return False
        self.held.add(session_id)
        return True

    async def release_claim(self, session_id: str) -> None:
        self.held.discard(session_id)

    async def refresh_claim(self, session_id: str, ttl_seconds: int) -> None:
        return None

    async def enqueue(self, job: RunJob) -> None:
        self.enqueued.append(job)


class _FakeStore:
    def __init__(self, recoverable: list[str], *, fail: bool = False) -> None:
        self._recoverable = recoverable
        self._fail = fail
        self.idle_window: float | None = None

    async def list_recoverable(self, *, idle_for_seconds: float) -> list[str]:
        self.idle_window = idle_for_seconds
        if self._fail:
            raise RuntimeError("database down")
        return list(self._recoverable)


class _FakeSettings:
    agent_timeout_seconds = 300.0


class _FakeRuntime:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.runner = object()
        self.durable_runs = True
        self.db_available = True
        self.settings = _FakeSettings()


def _worker(queue: _FakeQueue, store: Any) -> RunWorker:
    return RunWorker(_FakeRuntime(store), queue, concurrency=2)  # type: ignore[arg-type]


async def test_orphans_are_requeued_and_their_claim_released() -> None:
    queue = _FakeQueue()
    worker = _worker(queue, _FakeStore(["run_a", "run_b"]))

    requeued = await worker.recover_orphans()

    assert requeued == 2
    assert [j.kind for j in queue.enqueued] == [JobKind.START, JobKind.START]
    assert {j.session_id for j in queue.enqueued} == {"run_a", "run_b"}
    assert queue.held == set(), "the sweep must not keep the claim it probed with"


async def test_a_run_another_worker_holds_is_left_alone() -> None:
    queue = _FakeQueue(held={"run_busy"})
    worker = _worker(queue, _FakeStore(["run_busy", "run_free"]))

    requeued = await worker.recover_orphans()

    assert requeued == 1
    assert [j.session_id for j in queue.enqueued] == ["run_free"]
    assert "run_busy" in queue.held, "an in-flight run's claim must survive the sweep"


async def test_a_lapsed_claim_lets_the_next_sweep_recover_the_run() -> None:
    """A worker killed outright cannot release its claim, so the first sweep finds it still held.

    Dropping the run there stranded it permanently; the claim expires and a later sweep must take it.
    """
    queue = _FakeQueue(held={"run_crashed"})
    worker = _worker(queue, _FakeStore(["run_crashed"]))

    assert await worker.recover_orphans() == 0

    queue.held.discard("run_crashed")  # the TTL lapses
    assert await worker.recover_orphans() == 1
    assert queue.enqueued[0].session_id == "run_crashed"


async def test_a_store_failure_does_not_take_the_worker_down() -> None:
    queue = _FakeQueue()
    worker = _worker(queue, _FakeStore([], fail=True))

    assert await worker.recover_orphans() == 0
    assert queue.enqueued == []


def test_awaiting_approval_is_not_recoverable() -> None:
    """It is waiting for a person. Resuming it automatically would walk through the approval gate."""
    assert RunStatus.AWAITING_APPROVAL not in RECOVERABLE_RUN_STATUSES
    assert {RunStatus.QUEUED, RunStatus.RESEARCHING} == RECOVERABLE_RUN_STATUSES
    assert not (RECOVERABLE_RUN_STATUSES & TERMINAL_RUN_STATUSES)


async def test_silence_alone_never_makes_a_run_recoverable() -> None:
    """A claim is refreshed by a timer, so it only lapses when the worker is genuinely gone.

    That was not always true: an unbatched embedding call starved the event loop for minutes, the
    refresh never ran, and a sweep stole a run that a live worker was still driving. The idle window
    remains as a backstop against scheduling skew.
    """
    store = _FakeStore(["run_a"])
    worker = _worker(_FakeQueue(), store)

    await worker.recover_orphans()

    assert store.idle_window is not None
    assert store.idle_window >= CLAIM_TTL_SECONDS * 3, (
        "silence must outlast several claim periods before a run counts as abandoned"
    )
