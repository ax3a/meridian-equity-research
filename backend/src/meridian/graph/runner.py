"""The run manager: owns the compiled graph, drives runs as background asyncio tasks, and fans events out
to any number of live subscribers (SSE clients) plus a replayable event store.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from meridian.agents.contracts import AgentSet
from meridian.core.config import Settings
from meridian.core.ids import new_id
from meridian.core.logging import get_logger
from meridian.graph.builder import build_graph
from meridian.observability.bus import EventBus, NullEventBus
from meridian.schemas.enums import TERMINAL_RUN_STATUSES, RunStatus
from meridian.schemas.events import EventType, ProgressEvent
from meridian.schemas.research import HumanFeedback, ResearchRequest
from meridian.schemas.state import ResearchState
from meridian.schemas.telemetry import RunError

log = get_logger(__name__)


@runtime_checkable
class RunStore(Protocol):
    async def save_state(self, session_id: str, state: ResearchState) -> None: ...

    async def get_state(self, session_id: str) -> ResearchState | None: ...

    async def save_event(self, session_id: str, event: ProgressEvent) -> int:
        """Persist `event`, assign it a monotonic per-session `seq`, and return that seq."""
        ...

    async def list_events_since(self, session_id: str, after_seq: int) -> list[ProgressEvent]: ...

    async def count_active(self) -> int:
        """Runs not in a terminal state. Every implementation had this; the protocol did not say so,
        so a caller working through the protocol could not use it."""
        ...


class InMemoryRunStore:
    """Default `RunStore`. A database-backed implementation is wired in later (Task 12)."""

    def __init__(self) -> None:
        self._states: dict[str, ResearchState] = {}
        self._events: dict[str, list[ProgressEvent]] = defaultdict(list)

    async def save_state(self, session_id: str, state: ResearchState) -> None:
        self._states[session_id] = state

    async def get_state(self, session_id: str) -> ResearchState | None:
        return self._states.get(session_id)

    async def save_event(self, session_id: str, event: ProgressEvent) -> int:
        events = self._events[session_id]
        seq = len(events) + 1
        event.seq = seq
        events.append(event)
        return seq

    async def list_events_since(self, session_id: str, after_seq: int) -> list[ProgressEvent]:
        return [e for e in self._events.get(session_id, []) if e.seq > after_seq]

    async def count_active(self) -> int:
        return sum(1 for state in self._states.values() if state.status not in TERMINAL_RUN_STATUSES)


# Events after which no more will arrive for a session, so a cross-process subscriber can stop.
# AWAITING_APPROVAL is included: the run is idle until a human acts, and the resume opens a new stream.
_TERMINAL_EVENT_TYPES = frozenset({EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.AWAITING_APPROVAL})


class _RouterEventSink:
    """The single `EventSink` bound into the (once-built) graph; routes each event by `session_id`."""

    def __init__(self, store: RunStore, subscribers: dict[str, list[Any]], bus: EventBus | None = None) -> None:
        self._store = store
        self._subscribers = subscribers
        self._bus = bus or NullEventBus()

    async def emit(self, event: ProgressEvent) -> None:
        """Record progress, then fan out to live subscribers.

        Reporting progress must never be able to fail a research run: a storage error here once
        propagated out of an agent node and silently stalled the whole run. The event is dropped from
        the durable log if it cannot be written, logged, and still delivered to anyone watching.
        """
        try:
            event.seq = await self._store.save_event(event.session_id, event)
        except Exception as exc:
            log.warning(
                "progress_event_not_persisted",
                session_id=event.session_id,
                event_type=event.type.value,
                error=str(exc),
            )
        for queue in list(self._subscribers.get(event.session_id, [])):
            queue.put_nowait(event)
        # Reaches subscribers in *other* processes -- the API holding an SSE connection for a run this
        # worker is executing. A no-op on the null bus, so single-process behaviour is unchanged.
        await self._bus.publish(event)


def _coerce_state(raw: Any) -> ResearchState:
    return raw if isinstance(raw, ResearchState) else ResearchState.model_validate(raw)


class ResearchRunner:
    """Starts, resumes, cancels and streams progress for research runs.

    One `ResearchRunner` builds the LangGraph app exactly once; each run is a distinct LangGraph "thread"
    (`thread_id = session_id`) sharing that one compiled graph and checkpointer.
    """

    def __init__(
        self,
        agents: AgentSet,
        settings: Settings,
        *,
        store: RunStore | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.agents = agents
        self.settings = settings
        self.store: RunStore = store or InMemoryRunStore()
        self.bus: EventBus = bus or NullEventBus()
        self._subscribers: dict[str, list[Any]] = defaultdict(list)
        self._sink = _RouterEventSink(self.store, self._subscribers, self.bus)
        self.app = build_graph(agents, settings, self._sink, checkpointer=checkpointer)
        # Entries are removed as each run settles. Left to accumulate, every finished run's Task -- and
        # the coroutine frame it holds -- stayed here for the life of the process.
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Concurrency is bounded by `api.concurrency.RunAdmission`, which rejects an over-limit request
        # with 429 before this class is ever called. Deliberately not duplicated here: a second limiter
        # that silently queues would contradict the first one that visibly refuses.

    def _config(self, session_id: str) -> RunnableConfig:
        """The per-run graph config.

        Typed as `RunnableConfig` -- a TypedDict whose keys are exactly the two set here -- rather than
        `dict[str, Any]`, which matches neither `ainvoke`'s overloads nor `aget_state`'s signature.
        """
        return {"configurable": {"thread_id": session_id}, "recursion_limit": self.settings.graph_recursion_limit}

    async def create(self, request: ResearchRequest) -> str:
        """Register a run and persist its initial state, without executing it.

        Split out of `start` so the API can accept a request and hand execution to a worker: the run is
        durably `queued` the moment this returns, so a read of it never 404s while it waits for a slot.
        """
        session_id = new_id("run")
        require_approval = (
            request.require_approval if request.require_approval is not None else self.settings.require_approval_default
        )
        initial = ResearchState(session_id=session_id, request=request, require_approval=require_approval)
        await self.store.save_state(session_id, initial)
        return session_id

    async def start(self, request: ResearchRequest) -> str:
        """Create a run and execute it in this process."""
        session_id = await self.create(request)
        state = await self.store.get_state(session_id)
        self._tasks[session_id] = asyncio.create_task(self._drive(session_id, state))
        return session_id

    async def execute_pending(self, session_id: str) -> None:
        """Drive a run this process did not create, and wait for it to settle.

        The worker's entry point. The state comes from the store rather than from a request object,
        which is the whole point: the API created it, possibly in another process.

        A run interrupted by a worker dying already has checkpoints, and LangGraph continues such a
        thread when invoked with `None` rather than a fresh state. Passing the stored state instead
        would re-run every agent that had already finished: wasted work, duplicated evidence, and a
        second round of tool calls against SEC.
        """
        state = await self.store.get_state(session_id)
        if state is None:
            log.warning("run_not_found_for_execution", session_id=session_id)
            return
        graph_input: Any = state
        if await self.has_resumable_checkpoint(session_id):
            log.info("resuming_from_checkpoint", session_id=session_id, status=state.status.value)
            graph_input = None
        task = asyncio.create_task(self._drive(session_id, graph_input))
        self._tasks[session_id] = task
        await task

    async def has_resumable_checkpoint(self, session_id: str) -> bool:
        """Whether the graph holds partial progress for this thread that it could continue from."""
        try:
            snapshot = await self.app.aget_state(self._config(session_id))
        except Exception as exc:
            log.warning("checkpoint_probe_failed", session_id=session_id, error=str(exc))
            return False
        return bool(snapshot.values) and bool(snapshot.next)

    def resume(self, session_id: str, feedback: list[HumanFeedback] | list[dict[str, Any]] | None) -> None:
        """Continue a paused run with human feedback (an empty/approve-only list just approves).

        Launches a background task, same as `start`; callers that need to know when it settles (paused
        again or finished) can await `wait_idle(session_id)`.
        """
        self._tasks[session_id] = asyncio.create_task(self._drive(session_id, Command(resume=feedback)))

    async def wait_idle(self, session_id: str) -> None:
        """Block until the current background task for `session_id` finishes (paused or terminal)."""
        task = self._tasks.get(session_id)
        if task is not None:
            await task

    async def _drive(self, session_id: str, graph_input: Any) -> None:
        try:
            await self._drive_inner(session_id, graph_input)
        finally:
            # Only if this task is still the registered one: an approval resume replaces the entry
            # while the run it superseded is settling, and that newer task must not be dropped.
            if self._tasks.get(session_id) is asyncio.current_task():
                self._tasks.pop(session_id, None)

    async def _drive_inner(self, session_id: str, graph_input: Any) -> None:
        config = self._config(session_id)
        try:
            await self.app.ainvoke(graph_input, config=config)
            snapshot = await self.app.aget_state(config)
            state = _coerce_state(snapshot.values)
            paused = bool(snapshot.next)
            if not paused and state.status not in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
                state.status = RunStatus.COMPLETED
            await self.store.save_state(session_id, state)
            if not paused:
                self._close_subscribers(session_id)
        except Exception as exc:  # the run manager must survive a broken graph run
            log.exception("run_failed", session_id=session_id)
            # A distinct name from the `state` bound in the try block, which is non-optional: reusing it
            # made the variable `ResearchState | None` for the whole function.
            stored = await self.store.get_state(session_id)
            failed = stored or ResearchState(session_id=session_id, request=ResearchRequest(query="unknown"))
            failed.status = RunStatus.FAILED
            failed.errors = [*failed.errors, RunError(stage="runner", message=str(exc))]
            await self.store.save_state(session_id, failed)
            await self._sink.emit(ProgressEvent(session_id=session_id, type=EventType.RUN_FAILED, message=str(exc)))
            self._close_subscribers(session_id)

    def _close_subscribers(self, session_id: str) -> None:
        for queue in list(self._subscribers.get(session_id, [])):
            queue.put_nowait(None)

    async def cancel(self, session_id: str) -> None:
        task = self._tasks.get(session_id)
        if task is not None and not task.done():
            task.cancel()
        state = await self.store.get_state(session_id)
        if state is not None:
            state.status = RunStatus.CANCELLED
            await self.store.save_state(session_id, state)
        await self._sink.emit(
            ProgressEvent(
                session_id=session_id, type=EventType.RUN_FAILED, message="run cancelled", data={"reason": "cancelled"}
            )
        )
        self._close_subscribers(session_id)

    async def status(self, session_id: str) -> ResearchState | None:
        return await self.store.get_state(session_id)

    async def _forward_bus(self, session_id: str, queue: asyncio.Queue[ProgressEvent | None]) -> None:
        """Feed events published by another process into this subscriber's queue.

        The run may be executing in a worker, in which case nothing local ever emits for it. Terminal
        events close the queue so the SSE response ends instead of hanging on a finished run.
        """
        try:
            async for event in self.bus.listen(session_id):
                queue.put_nowait(event)
                if event.type in _TERMINAL_EVENT_TYPES:
                    queue.put_nowait(None)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("event_bus_listen_failed", session_id=session_id, error=str(exc))

    async def subscribe(self, session_id: str, after_seq: int = 0) -> AsyncIterator[ProgressEvent]:
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        self._subscribers[session_id].append(queue)
        forwarder: asyncio.Task[None] | None = None
        if not isinstance(self.bus, NullEventBus):
            forwarder = asyncio.create_task(self._forward_bus(session_id, queue))
        last_seq = after_seq
        try:
            for event in await self.store.list_events_since(session_id, after_seq):
                last_seq = max(last_seq, event.seq)
                yield event
            while True:
                item = await queue.get()
                if item is None:
                    break
                if item.seq > last_seq:
                    last_seq = item.seq
                    yield item
        finally:
            if forwarder is not None:
                forwarder.cancel()
            subs = self._subscribers.get(session_id)
            if subs and queue in subs:
                subs.remove(queue)
