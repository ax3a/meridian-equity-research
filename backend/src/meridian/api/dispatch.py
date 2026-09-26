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
from contextvars import ContextVar
from typing import Protocol
from uuid import uuid4

from meridian.api.concurrency import RunAdmission, run_and_release
from meridian.core.logging import get_logger
from meridian.graph.jobs import JobKind, RunJob, RunQueue
from meridian.graph.runner import ResearchRunner, RunStore
from meridian.schemas.research import HumanFeedback, ResearchRequest

log = get_logger(__name__)

# The admission token reserved for the request currently being handled. A ContextVar rather than an
# attribute because several requests share one dispatcher instance and must not share this.
_reservation: ContextVar[str | None] = ContextVar("meridian_admission_token", default=None)


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

    def __init__(
        self,
        runner: ResearchRunner,
        queue: RunQueue,
        store: RunStore,
        *,
        limit: int,
        slot_stale_seconds: float,
    ) -> None:
        self._runner = runner
        self._queue = queue
        self._store = store
        self._limit = limit
        self._slot_stale_seconds = slot_stale_seconds

    @property
    def limit(self) -> int:
        return self._limit

    async def try_admit(self) -> bool:
        """Reserve one of the shared admission slots, atomically.

        A counter in this process would let every API replica admit the full limit on its own, and
        comparing a store count against the limit is a read rather than a reservation -- two requests
        arriving together both saw the same count and were both admitted. The reservation is a single
        Lua script in Redis, so the count and the insert cannot interleave.

        Slots are released when the run reaches a terminal state, and any left behind by a replica that
        died are aged out after `slot_stale_seconds`.
        """
        try:
            token = f"pending:{uuid4().hex}"
            if not await self._queue.reserve_slot(token, self._limit, self._slot_stale_seconds):
                return False
            _reservation.set(token)
            return True
        except Exception as exc:
            # Refusing every run because Redis hiccuped is a worse failure than briefly exceeding the cap.
            log.warning("admission_reservation_failed_allowing_run", error=str(exc))
            return True

    async def start(self, request: ResearchRequest) -> str:
        session_id = await self._runner.create(request)
        # Re-key the reservation from the pre-admission token to the real session id, so the slot can
        # be released when the run finishes rather than waiting to age out.
        token = _reservation.get()
        if token is not None:
            await self._queue.release_slot(token)
            await self._queue.reserve_slot(session_id, self._limit + 1, self._slot_stale_seconds)
            _reservation.set(None)
        await self._queue.enqueue(RunJob(kind=JobKind.START, session_id=session_id))
        return session_id

    async def release(self, session_id: str) -> None:
        """Give the admission slot back once the run is no longer active."""
        await self._queue.release_slot(session_id)

    async def resume(self, session_id: str, feedback: list[HumanFeedback]) -> None:
        await self._queue.enqueue(RunJob(kind=JobKind.RESUME, session_id=session_id, feedback=feedback))

    async def cancel(self, session_id: str) -> None:
        # Queued so the worker holding the run stops it; also applied locally so the stored state turns
        # `cancelled` immediately, which is what the caller sees on the next read.
        await self._runner.cancel(session_id)
        await self._queue.enqueue(RunJob(kind=JobKind.CANCEL, session_id=session_id))
