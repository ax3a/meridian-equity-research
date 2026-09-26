"""The work queue between the API and the worker process.

A Redis list used as a FIFO: the API pushes a job when a run is created, approved, given feedback or
cancelled, and a worker pops it and drives the graph. Redis is already required for rate limiting and
caching, so this adds a dependency on nothing new -- and a broker like Celery would bring a second
serialization format, a second config surface and a second supervision story for one queue.

A job sits in Redis until a worker takes it, so restarting the API loses nothing. A worker that dies
*after* popping one would strand its run, so execution is guarded by a claim key with a TTL: whoever is
running a session refreshes it, and when a worker dies the claim lapses. `RunWorker`'s recovery sweep
then finds non-terminal runs that nothing holds and re-queues them, resuming from the last checkpoint
rather than starting over.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from meridian.core.logging import get_logger
from meridian.schemas.research import HumanFeedback

log = get_logger(__name__)

QUEUE_KEY = "meridian:runs:pending"
CLAIM_PREFIX = "meridian:runs:claim:"


def _claim_key(session_id: str) -> str:
    return f"{CLAIM_PREFIX}{session_id}"


class JobKind(StrEnum):
    START = "start"
    RESUME = "resume"
    CANCEL = "cancel"


@dataclass(frozen=True)
class RunJob:
    kind: JobKind
    session_id: str
    feedback: list[HumanFeedback] | None = None

    def to_json(self) -> str:
        payload: dict[str, Any] = {"kind": self.kind.value, "session_id": self.session_id}
        if self.feedback is not None:
            payload["feedback"] = [f.model_dump(mode="json") for f in self.feedback]
        return json.dumps(payload)

    @classmethod
    def from_json(cls, raw: str | bytes) -> RunJob:
        data = json.loads(raw)
        feedback = data.get("feedback")
        return cls(
            kind=JobKind(data["kind"]),
            session_id=data["session_id"],
            feedback=[HumanFeedback.model_validate(f) for f in feedback] if feedback is not None else None,
        )


class RunQueue:
    """Redis-backed job queue. `enqueue` is used by the API, `dequeue` by the worker."""

    def __init__(self, redis_url: str, *, key: str = QUEUE_KEY) -> None:
        self._redis_url = redis_url
        self._key = key
        self._client: Any | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def start(self) -> None:
        from redis.asyncio import Redis

        # No socket_timeout: `dequeue` blocks on BRPOP for longer than any sensible read timeout.
        client = Redis.from_url(self._redis_url, socket_connect_timeout=1.5)
        await client.ping()
        self._client = client

    async def enqueue(self, job: RunJob) -> None:
        if self._client is None:
            raise RuntimeError("run queue is not connected")
        await self._client.lpush(self._key, job.to_json())

    async def dequeue(self, block_seconds: float = 5.0) -> RunJob | None:
        """Block for up to `block_seconds`. None means nothing arrived, not an error."""
        if self._client is None:
            raise RuntimeError("run queue is not connected")
        item = await self._client.brpop([self._key], timeout=block_seconds)
        if item is None:
            return None
        _, raw = item
        try:
            return RunJob.from_json(raw)
        except Exception as exc:
            # A malformed job must not wedge the worker; drop it loudly and take the next one.
            log.warning("run_job_discarded", error=str(exc), raw=str(raw)[:200])
            return None

    async def claim(self, session_id: str, ttl_seconds: int) -> bool:
        """Take exclusive ownership of a session, or return False if a live worker already holds it.

        The claim expires rather than being held forever, so a worker that dies does not lock its run
        out of recovery. Whoever is executing refreshes it; once refreshes stop, it lapses.
        """
        if self._client is None:
            return True
        acquired: bool = await self._client.set(_claim_key(session_id), "1", nx=True, ex=ttl_seconds)
        return bool(acquired)

    async def refresh_claim(self, session_id: str, ttl_seconds: int) -> None:
        if self._client is not None:
            await self._client.expire(_claim_key(session_id), ttl_seconds)

    async def release_claim(self, session_id: str) -> None:
        if self._client is not None:
            await self._client.delete(_claim_key(session_id))

    async def depth(self) -> int:
        if self._client is None:
            return 0
        count: int = await self._client.llen(self._key)
        return count

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
