"""Consumes the run queue and drives the graph, in a process of its own.

Why a separate process at all: a research run parses megabyte filings and embeds hundreds of chunks, so
it competes with the API for one event loop and one GIL. Moving it out means request latency no longer
depends on what a run happens to be doing, and the two can be scaled and restarted independently.

What makes this work rather than merely move the problem:

* The checkpointer is Postgres, so the state a worker writes is readable by the API. `api.live` reads
  the live graph state of a run it is not executing, and every existing read endpoint keeps working.
* Progress events go to `research_events` *and* to the Redis bus, so an SSE connection held by the API
  still streams a run the worker owns.
* Admission is unchanged: the API still refuses over-limit requests with 429 before anything is queued.
  `worker_concurrency` then bounds what one worker executes at once.

A worker is stateless and idempotent to start; run as many as the database and rate limits allow.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import tempfile
import time
from pathlib import Path

from meridian.api.wiring import Runtime, build_runtime
from meridian.core.config import Settings, get_settings
from meridian.core.logging import configure_logging, get_logger
from meridian.graph.jobs import JobKind, RunJob, RunQueue
from meridian.schemas.enums import TERMINAL_RUN_STATUSES, RunStatus

log = get_logger(__name__)

# How long a worker's claim survives without a refresh, and how often the holder refreshes it.
#
# The claim answers "is a worker alive?", which is a different question from "is this run progressing?"
# -- the idle window below answers that one. Separating them lets the claim be short: refreshing every
# 5s means a dead worker is detectable in 20s, while a *live* worker that is simply busy keeps its
# claim, because the refresh is a tiny timer rather than anything that waits on the run.
CLAIM_TTL_SECONDS = 20
CLAIM_REFRESH_SECONDS = 5.0
# A silent run must also be this old before a sweep treats it as abandoned. A backstop, not the main
# test: the claim above answers "is a worker alive?", and it does so reliably now that no single step
# can starve the event loop for minutes (embedding is batched, so the 5s refresh always gets to run).
#
# It used to have to exceed `agent_timeout_seconds`, because a starved loop let a live worker's claim
# lapse and a sweep then stole a run mid-tool-call. With that cause fixed the window is about
# tolerating a brief clock or scheduling skew, which three claim periods covers.
ORPHAN_IDLE_SECONDS = CLAIM_TTL_SECONDS * 3

# Touched while the worker is alive and consuming. The container healthcheck reads its mtime, because
# the worker serves no HTTP and would otherwise inherit the API image's curl check and always fail.
HEARTBEAT_PATH = Path(os.environ.get("WORKER_HEARTBEAT_PATH") or Path(tempfile.gettempdir()) / "meridian-worker-alive")
HEARTBEAT_INTERVAL_SECONDS = 10.0


class RunWorker:
    """Pops jobs and executes them, up to `worker_concurrency` at a time."""

    def __init__(self, runtime: Runtime, queue: RunQueue, *, concurrency: int, sweep_seconds: float = 20.0) -> None:
        self._runtime = runtime
        self._queue = queue
        self._slots = asyncio.Semaphore(concurrency)
        self._concurrency = concurrency
        self._sweep_seconds = sweep_seconds
        self._orphan_idle_seconds = float(ORPHAN_IDLE_SECONDS)
        self._inflight: set[asyncio.Task[None]] = set()
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run_forever(self) -> None:
        log.info(
            "worker_started",
            concurrency=self._concurrency,
            durable_runs=self._runtime.durable_runs,
            db=self._runtime.db_available,
            orphan_idle_seconds=self._orphan_idle_seconds,
        )
        self._beat()
        beater = asyncio.create_task(self._heartbeat())
        sweeper: asyncio.Task[None] | None = None
        if self._runtime.durable_runs:
            await self.recover_orphans()
            sweeper = asyncio.create_task(self._sweep_periodically())
        while not self._stopping.is_set():
            # Hold a slot *before* popping, so a job is never taken off the queue while the worker is
            # already saturated -- a taken job that cannot start is a job at risk of being lost.
            await self._slots.acquire()
            if self._stopping.is_set():
                self._slots.release()
                break
            job = None
            try:
                job = await self._queue.dequeue(block_seconds=2.0)
            except Exception as exc:
                log.warning("run_queue_dequeue_failed", error=str(exc))
                await asyncio.sleep(1.0)
            if job is None:
                self._slots.release()
                continue
            task = asyncio.create_task(self._execute(job))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

        beater.cancel()
        if sweeper is not None:
            sweeper.cancel()
        await self._drain()

    async def _release_if_settled(self, session_id: str) -> None:
        """Hand the admission slot back once the run is finished, or paused for a human.

        Not on every job: a run that merely paused for approval is still occupying capacity in the
        sense that matters, but a *terminal* one is not, and a run awaiting a person could sit there
        for hours. Both release; only a run still executing keeps its slot.
        """
        try:
            state = await self._runtime.store.get_state(session_id)
            if state is None or state.status in TERMINAL_RUN_STATUSES or state.status is RunStatus.AWAITING_APPROVAL:
                await self._queue.release_slot(session_id)
        except Exception as exc:
            # The slot ages out on its own, so this is a latency problem rather than a leak.
            log.warning("admission_slot_not_released", session_id=session_id, error=str(exc))

    def _beat(self) -> None:
        """Record liveness. Best effort: a read-only filesystem must not stop the worker working."""
        try:
            HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
            HEARTBEAT_PATH.write_text(str(time.time()), encoding="utf-8")
        except Exception as exc:
            log.debug("heartbeat_write_failed", path=str(HEARTBEAT_PATH), error=str(exc))

    async def _heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                self._beat()
        except asyncio.CancelledError:
            raise

    async def _sweep_periodically(self) -> None:
        """Re-check for orphans on a timer, not just at startup.

        A worker killed outright leaves its claim behind until the TTL lapses, so the run it was
        executing is *not* recoverable at the moment the next worker boots -- a startup-only sweep
        re-queued it, the claim was still held, and the job was dropped. Sweeping on an interval means
        the run is picked up on the first pass after the claim expires.
        """
        try:
            while True:
                await asyncio.sleep(self._sweep_seconds)
                await self.recover_orphans()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("orphan_sweep_failed", error=str(exc))

    async def _hold_claim(self, session_id: str) -> None:
        """Keep this worker's claim alive while the run executes; stop, and it lapses for recovery."""
        try:
            while True:
                await asyncio.sleep(CLAIM_REFRESH_SECONDS)
                await self._queue.refresh_claim(session_id, CLAIM_TTL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("claim_refresh_failed", session_id=session_id, error=str(exc))

    async def recover_orphans(self) -> int:
        """Re-queue runs left mid-flight by a worker that died.

        Their state survives in the checkpointer, so they can continue rather than restart -- but only
        if something notices them. A run is an orphan when it is non-terminal and no live worker holds
        its claim; claims lapse on their TTL, so a run being executed right now is never taken.
        """
        try:
            orphans = await self._runtime.store.list_recoverable(idle_for_seconds=self._orphan_idle_seconds)
        except Exception as exc:
            log.warning("orphan_scan_failed", error=str(exc))
            return 0

        requeued = 0
        for session_id in orphans:
            if not await self._queue.claim(session_id, CLAIM_TTL_SECONDS):
                continue  # a live worker holds it
            await self._queue.release_claim(session_id)
            await self._queue.enqueue(RunJob(kind=JobKind.START, session_id=session_id))
            requeued += 1
            log.info("orphaned_run_requeued", session_id=session_id)
        if requeued:
            log.info("orphan_recovery_complete", requeued=requeued)
        return requeued

    async def _drain(self) -> None:
        """Let running jobs finish before the process exits, so their checkpoints are consistent."""
        if not self._inflight:
            return
        log.info("worker_draining", inflight=len(self._inflight))
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    async def _execute(self, job: RunJob) -> None:
        runner = self._runtime.runner
        # One worker per session. Without this, a recovery sweep could hand a run to a second worker
        # while the first is still driving it, and both would write checkpoints for the same thread.
        if not await self._queue.claim(job.session_id, CLAIM_TTL_SECONDS):
            log.info("run_job_skipped_already_claimed", session_id=job.session_id, kind=job.kind.value)
            self._slots.release()
            return
        heartbeat = asyncio.create_task(self._hold_claim(job.session_id))
        try:
            log.info("run_job_started", session_id=job.session_id, kind=job.kind.value)
            if job.kind is JobKind.START:
                await runner.execute_pending(job.session_id)
            elif job.kind is JobKind.RESUME:
                runner.resume(job.session_id, job.feedback or [])  # launches the task
                await runner.wait_idle(job.session_id)
            elif job.kind is JobKind.CANCEL:
                await runner.cancel(job.session_id)
            log.info("run_job_finished", session_id=job.session_id, kind=job.kind.value)
        except Exception as exc:
            # `_drive` already records the failure on the run itself; this is the worker's own log.
            log.exception("run_job_failed", session_id=job.session_id, kind=job.kind.value, error=str(exc))
        finally:
            heartbeat.cancel()
            await self._queue.release_claim(job.session_id)
            await self._release_if_settled(job.session_id)
            self._slots.release()


async def run_worker(settings: Settings | None = None) -> None:
    """Build a runtime, connect the queue and consume until told to stop."""
    settings = settings or get_settings()
    if not settings.redis_url:
        raise RuntimeError("the worker needs REDIS_URL: the run queue and the event bus are both Redis")

    queue = RunQueue(settings.redis_url)
    await queue.start()
    runtime = await build_runtime(settings)
    if not runtime.durable_runs:
        # Worth saying plainly: without a shared checkpointer the API cannot read this worker's runs.
        log.warning(
            "worker_without_durable_checkpointer",
            detail="runs execute but their live state is not visible to the API and is lost on restart",
        )

    worker = RunWorker(runtime, queue, concurrency=settings.worker_concurrency)
    _install_signal_handlers(worker)
    try:
        await worker.run_forever()
    finally:
        await queue.aclose()
        await runtime.aclose()
        log.info("worker_stopped")


def _install_signal_handlers(worker: RunWorker) -> None:
    """Stop on SIGTERM/SIGINT so `docker stop` drains rather than kills mid-run."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(sig, worker.stop)


def main() -> None:
    configure_logging()
    settings = get_settings()
    asyncio.run(run_worker(settings))
