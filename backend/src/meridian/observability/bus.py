"""Cross-process delivery of `ProgressEvent`s.

`ResearchRunner` fans events out to in-process subscriber queues, which is all the API needs while it
executes runs itself. Once a worker process owns execution, the API holds the SSE connection but never
sees the events, so live progress would stop at whatever the durable log happened to contain.

The bus closes that gap over Redis pub/sub: the worker publishes each event on a per-session channel
and the API forwards it into the same subscriber queue the in-process path uses, so `subscribe()` is
unchanged from the caller's point of view.

Delivery is best-effort by design. Pub/sub drops messages for anyone not currently listening, but every
event is also written to `research_events` first, and `subscribe()` replays that log before it starts
listening -- so a dropped message costs latency, never a lost event.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol, runtime_checkable

from meridian.core.logging import get_logger
from meridian.schemas.events import ProgressEvent

log = get_logger(__name__)

CHANNEL_PREFIX = "meridian:events:"


def channel_for(session_id: str) -> str:
    return f"{CHANNEL_PREFIX}{session_id}"


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: ProgressEvent) -> None: ...

    def listen(self, session_id: str) -> AsyncIterator[ProgressEvent]: ...

    async def aclose(self) -> None: ...


class NullEventBus:
    """No-op bus for single-process runs, where in-process fan-out already delivers everything."""

    async def publish(self, event: ProgressEvent) -> None:
        return None

    async def listen(self, session_id: str) -> AsyncIterator[ProgressEvent]:
        # A generator that ends immediately, so callers need no special case.
        return
        yield  # pragma: no cover - unreachable, present to make this an async generator

    async def aclose(self) -> None:
        return None


class RedisEventBus:
    """Redis pub/sub bus, one channel per session."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Any | None = None

    async def start(self) -> None:
        from redis.asyncio import Redis

        client = Redis.from_url(self._redis_url, socket_connect_timeout=1.5, socket_timeout=2.0)
        await client.ping()
        self._client = client

    async def publish(self, event: ProgressEvent) -> None:
        if self._client is None:
            return
        try:
            await self._client.publish(channel_for(event.session_id), event.model_dump_json())
        except Exception as exc:  # never let progress reporting fail a run
            log.warning("event_publish_failed", session_id=event.session_id, error=str(exc))

    async def listen(self, session_id: str) -> AsyncIterator[ProgressEvent]:
        if self._client is None:
            return
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel_for(session_id))
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    await asyncio.sleep(0)  # yield so a cancelled consumer stops promptly
                    continue
                try:
                    yield ProgressEvent.model_validate_json(message["data"])
                except Exception as exc:
                    log.warning("event_decode_failed", session_id=session_id, error=str(exc))
        finally:
            try:
                await pubsub.unsubscribe(channel_for(session_id))
                await pubsub.aclose()
            except Exception as exc:
                log.debug("event_pubsub_cleanup_failed", session_id=session_id, error=str(exc))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


@asynccontextmanager
async def build_event_bus(redis_url: str | None) -> AsyncIterator[EventBus]:
    """A Redis bus when Redis is reachable, otherwise the null bus.

    Falling back keeps a worker-less, Redis-less deployment working exactly as before rather than
    failing to start.
    """
    if not redis_url:
        bus: EventBus = NullEventBus()
        yield bus
        return
    redis_bus = RedisEventBus(redis_url)
    try:
        await redis_bus.start()
    except Exception as exc:
        log.warning("event_bus_unavailable_falling_back", error=str(exc), detail="live progress stays in-process")
        yield NullEventBus()
        return
    try:
        yield redis_bus
    finally:
        await redis_bus.aclose()
