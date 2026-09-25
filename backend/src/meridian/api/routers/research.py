"""`/api/v1/research*` -- create/inspect/steer research runs, including the SSE progress stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request, Response
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from meridian.api import live, views
from meridian.api.concurrency import run_and_release
from meridian.api.errors import TooManyActiveRunsError
from meridian.api.security import authenticate_and_throttle
from meridian.api.wiring import Runtime
from meridian.core.errors import ConflictError, NotFoundError
from meridian.core.logging import get_logger
from meridian.schemas.api import (
    AgentRunView,
    FeedbackRequest,
    ResearchCreated,
    ResearchDetail,
    ResearchSummary,
    ReviewPackage,
    SourceView,
    StatusView,
    TraceView,
)
from meridian.schemas.enums import RunStatus
from meridian.schemas.events import ProgressEvent
from meridian.schemas.report import ResearchReport
from meridian.schemas.research import HumanFeedback, ResearchRequest
from meridian.schemas.state import ResearchState

log = get_logger(__name__)

router = APIRouter(tags=["research"], dependencies=[Depends(authenticate_and_throttle)])


def _runtime(request: Request) -> Runtime:
    return request.app.state.runtime  # type: ignore[no-any-return]


async def _get_state_or_404(runtime: Runtime, session_id: str) -> ResearchState:
    state = await live.live_state(runtime, session_id)
    if state is None:
        raise NotFoundError(f"research run '{session_id}' not found")
    return state


async def _try_admit(runtime: Runtime) -> None:
    if not await runtime.admission.try_acquire():
        raise TooManyActiveRunsError(
            f"at most {runtime.admission.limit} research runs may execute concurrently; try again shortly",
            details={"limit": runtime.admission.limit},
        )


def _release_when_idle(runtime: Runtime, session_id: str) -> None:
    task = asyncio.create_task(run_and_release(runtime.admission, lambda: runtime.runner.wait_idle(session_id)))
    runtime.track(task)


@router.post("/research", response_model=ResearchCreated, status_code=201)
async def create_research(payload: ResearchRequest, request: Request) -> ResearchCreated:
    runtime = _runtime(request)
    await _try_admit(runtime)
    session_id = await runtime.runner.start(payload)
    _release_when_idle(runtime, session_id)
    state = await live.live_state(runtime, session_id)
    assert state is not None  # start() always saves the initial state before returning
    return ResearchCreated(
        id=session_id,
        status=state.status,
        events_url=f"/api/v1/research/{session_id}/events",
        status_url=f"/api/v1/research/{session_id}/status",
    )


@router.get("/research", response_model=list[ResearchSummary])
async def list_research(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[ResearchSummary]:
    runtime = _runtime(request)
    records = await runtime.store.list_recent(limit)
    # `list_recent` reads the store directly (cheap, one query) -- freshen each row's state from the
    # live graph checkpoint so an in-flight run doesn't show up stuck at "queued" (see api/live.py).
    live_records = [await live.live_record(runtime, r.session_id) or r for r in records]
    return [views.to_summary(runtime.settings, r) for r in live_records]


@router.get("/research/{session_id}", response_model=ResearchDetail)
async def get_research(session_id: str, request: Request) -> ResearchDetail:
    runtime = _runtime(request)
    rec = await live.live_record(runtime, session_id)
    if rec is None:
        raise NotFoundError(f"research run '{session_id}' not found")
    return views.to_detail(runtime.settings, rec)


@router.get("/research/{session_id}/status", response_model=StatusView)
async def get_status(session_id: str, request: Request) -> StatusView:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    return views.to_status_view(session_id, state)


@router.get("/research/{session_id}/report", response_model=ResearchReport)
async def get_report(session_id: str, request: Request) -> ResearchReport:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    if state.report is None:
        raise NotFoundError(f"research run '{session_id}' has no report yet")
    return state.report


@router.get("/research/{session_id}/agents", response_model=list[AgentRunView])
async def get_agents(session_id: str, request: Request) -> list[AgentRunView]:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    return views.to_agent_run_views(state)


@router.get("/research/{session_id}/sources", response_model=list[SourceView])
async def get_sources(session_id: str, request: Request) -> list[SourceView]:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    return views.to_source_views(state)


@router.get("/research/{session_id}/trace", response_model=TraceView)
async def get_trace(session_id: str, request: Request) -> TraceView:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    return views.to_trace_view(state)


@router.get("/research/{session_id}/review", response_model=ReviewPackage)
async def get_review(session_id: str, request: Request) -> ReviewPackage:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    return views.to_review_package(state)


@router.post("/research/{session_id}/feedback", status_code=204)
async def submit_feedback(session_id: str, payload: FeedbackRequest, request: Request) -> Response:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    _require_awaiting_approval(state)
    await _try_admit(runtime)
    runtime.runner.resume(session_id, list(payload.actions))
    _release_when_idle(runtime, session_id)
    return Response(status_code=204)


@router.post("/research/{session_id}/approve", status_code=204)
async def approve_research(session_id: str, request: Request) -> Response:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    _require_awaiting_approval(state)
    await _try_admit(runtime)
    runtime.runner.resume(session_id, [HumanFeedback(action="approve")])
    _release_when_idle(runtime, session_id)
    return Response(status_code=204)


@router.post("/research/{session_id}/cancel", status_code=204)
async def cancel_research(session_id: str, request: Request) -> Response:
    runtime = _runtime(request)
    state = await _get_state_or_404(runtime, session_id)
    if state.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        raise ConflictError(f"research run '{session_id}' has already finished (status={state.status.value})")
    await runtime.runner.cancel(session_id)
    return Response(status_code=204)


def _require_awaiting_approval(state: ResearchState) -> None:
    if not (state.approval == "pending" and state.status == RunStatus.AWAITING_APPROVAL):
        raise ConflictError(f"research run '{state.session_id}' is not awaiting approval (status={state.status.value})")


_EVENT_POLL_TIMEOUT_SECONDS = 15.0


def _sse(event: ProgressEvent) -> ServerSentEvent:
    """Emit as the DEFAULT event type rather than naming it after `event.type`.

    A named SSE event only reaches a browser listener registered for that exact name; the standard
    `EventSource.onmessage` handler never fires for one. Naming these after the event type meant the
    live view silently received nothing and sat on "Queued" while the run finished behind it. The type
    is already in the payload, so clients filter on that and any new event type works without a
    matching client change.
    """
    return ServerSentEvent(id=str(event.seq), data=event.model_dump_json())

async def _stream_events(runtime: Runtime, session_id: str, after_seq: int) -> AsyncIterator[ServerSentEvent]:
    # A client reconnecting after the run already finished would otherwise hang forever: the runner only
    # wakes subscribers that were registered *before* it closed them out. Replay-then-return here avoids
    # ever calling `subscribe()` for a run that is already done.
    state = await live.live_state(runtime, session_id)
    if state is None:
        return
    if state.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        for event in await runtime.store.list_events_since(session_id, after_seq):
            yield _sse(event)
        return

    subscription = runtime.runner.subscribe(session_id, after_seq=after_seq).__aiter__()
    while True:
        try:
            event = await asyncio.wait_for(subscription.__anext__(), timeout=_EVENT_POLL_TIMEOUT_SECONDS)
        except TimeoutError:
            # No event in a while: check whether the run ended without us (race with the fast path above,
            # or a late-registered subscriber the runner will never wake) so the stream still terminates.
            current = await live.live_state(runtime, session_id)
            if current is None or current.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
                return
            continue
        except StopAsyncIteration:
            return
        yield _sse(event)


@router.get("/research/{session_id}/events")
async def stream_events(
    session_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
) -> EventSourceResponse:
    runtime = _runtime(request)
    await _get_state_or_404(runtime, session_id)  # 404 up front rather than an empty/silent stream
    last_event_id = request.headers.get("last-event-id")
    start_after = after_seq if after_seq else int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return EventSourceResponse(_stream_events(runtime, session_id, start_after), ping=10)
