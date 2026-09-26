"""How the API gets a run executed: here, or on a worker.

The routers call one interface and never branch on deployment shape. `InProcessDispatcher` is exactly
what this build always did -- drive the graph on the API's own event loop -- and remains the default,
what the CLI uses and what the tests exercise. `WorkerDispatcher` persists the run and puts a job on the
queue instead, so nothing heavy shares the request loop.

Admission differs between the two because the truth lives in a different place. In-process, a counter
in this process is exact. With workers, several API processes admit against a pool of workers none of
them owns, so capacity is read from the run store -- which every process shares -- instead of from a
local counter that would let each one admit the full limit on its own.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from meridian.api.concurrency import RunAdmission, run_and_release
from meridian.core.logging import get_logger
from meridian.graph.jobs import JobKind, RunJob, RunQueue
from meridian.graph.runner import ResearchRunner, RunStore
from meridian.schemas.research import HumanFeedback, ResearchRequest

log = get_logger(__name__)


class RunDispatcher(Protocol):
    @property
    def mode(self) -> str: ...

    async def try_admit(self) -> bool: ...

    @property
    def limit(self) -> int: ...

    async def start(self, request: ResearchRequest) -> str: ...

    async def resume(self, session_id: str, feedback: list[HumanFeedback]) -> None: ...

    async def cancel(self, session_id: str) -> None: ...


class InProcessDispatcher:
    """Executes runs on the API's event loop, releasing the admission slot when each goes idle."""

    mode = "inprocess"

    def __init__(self, runner: ResearchRunner, admission: RunAdmission) -> None:
        self._runner = runner
        self._admission = admission
        # A strong reference per in-flight releaser: a bare `create_task` result can be garbage
        # collected mid-await, and a lost releaser leaks its admission slot permanently.
        self._releasers: set[asyncio.Task[None]] = set()

    @property
    def limit(self) -> int:
        return self._admission.limit

    async def try_admit(self) -> bool:
        return await self._admission.try_acquire()

    def _release_when_idle(self, session_id: str) -> None:
        task = asyncio.create_task(run_and_release(self._admission, lambda: self._runner.wait_idle(session_id)))
        self._releasers.add(task)
        task.add_done_callback(self._releasers.discard)

    async def start(self, request: ResearchRequest) -> str:
        session_id = await self._runner.start(request)
        self._release_when_idle(session_id)
        return session_id

    async def resume(self, session_id: str, feedback: list[HumanFeedback]) -> None:
        self._runner.resume(session_id, feedback)
        self._release_when_idle(session_id)

    async def cancel(self, session_id: str) -> None:
        await self._runner.cancel(session_id)


class WorkerDispatcher:
    """Persists the run and queues it; a worker process executes it."""

    mode = "worker"

    def __init__(self, runner: ResearchRunner, queue: RunQueue, store: RunStore, *, limit: int) -> None:
        self._runner = runner
        self._queue = queue
        self._store = store
        self._limit = limit

    @property
    def limit(self) -> int:
        return self._limit

    async def try_admit(self) -> bool:
        """Admit against the shared run store, since no single process sees all the active runs.

        This is a check, not a reservation: two requests arriving together can both read the same
        count and both be admitted. The consequence is at most a few runs over the limit, which the
        worker's own concurrency then queues -- far better than a per-process counter that lets every
        API replica admit the full limit independently.
        """
        try:
            return await self._store.count_active() < self._limit
        except Exception as exc:
            log.warning("admission_count_failed_allowing_run", error=str(exc))
            return True

    async def start(self, request: ResearchRequest) -> str:
        session_id = await self._runner.create(request)
        await self._queue.enqueue(RunJob(kind=JobKind.START, session_id=session_id))
        return session_id

    async def resume(self, session_id: str, feedback: list[HumanFeedback]) -> None:
        await self._queue.enqueue(RunJob(kind=JobKind.RESUME, session_id=session_id, feedback=feedback))

    async def cancel(self, session_id: str) -> None:
        # Queued so the worker holding the run stops it; also applied locally so the stored state turns
        # `cancelled` immediately, which is what the caller sees on the next read.
        await self._runner.cancel(session_id)
        await self._queue.enqueue(RunJob(kind=JobKind.CANCEL, session_id=session_id))
