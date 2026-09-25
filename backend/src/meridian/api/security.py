"""API-key authentication and per-key/IP rate limiting for every `/api/v1` route.

When `settings.api_key` is unset the API is open (local-dev only, documented on `/health`); when it is
set, every `/api/v1` request needs a matching `X-API-Key`, compared in constant time. Rate limiting uses
Redis (a fixed one-minute window per identity) when reachable, and degrades to an in-process counter
--  permanently, for the life of the process -- the first time Redis stops answering.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from typing import TYPE_CHECKING

from fastapi import Header, Request

from meridian.core.config import Settings, get_settings
from meridian.core.errors import AuthenticationError, RateLimitedError
from meridian.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = get_logger(__name__)


class RateLimiter:
    """Fixed one-minute-window limiter. Redis-backed when available, in-process otherwise."""

    def __init__(self, limit_per_minute: int, redis_url: str | None) -> None:
        self._limit = max(1, limit_per_minute)
        self._redis_url = redis_url
        self._redis: Redis | None = None
        self._redis_healthy = False
        self._counters: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return "redis" if self._redis_healthy else "memory"

    async def start(self) -> None:
        if not self._redis_url:
            return
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(self._redis_url, socket_connect_timeout=1.5, socket_timeout=2.0)
            await client.ping()
            self._redis = client
            self._redis_healthy = True
        except Exception as exc:  # pragma: no cover - exercised only when redis is actually down
            log.warning("rate_limiter_redis_unavailable", error=str(exc))
            self._redis = None
            self._redis_healthy = False

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def hit(self, key: str) -> tuple[bool, int]:
        """Returns `(allowed, retry_after_seconds)`."""
        if self._redis_healthy and self._redis is not None:
            try:
                return await self._hit_redis(key)
            except Exception as exc:  # network boundary: degrade permanently for this process
                log.warning("rate_limiter_redis_failed_falling_back", error=str(exc))
                self._redis_healthy = False
        return await self._hit_local(key)

    async def _hit_redis(self, key: str) -> tuple[bool, int]:
        assert self._redis is not None
        bucket = int(time.time() // 60)
        rkey = f"meridian:rl:{key}:{bucket}"
        count = await self._redis.incr(rkey)
        if count == 1:
            await self._redis.expire(rkey, 60)
        return count <= self._limit, 60 - int(time.time() % 60)

    async def _hit_local(self, key: str) -> tuple[bool, int]:
        async with self._lock:
            bucket = int(time.time() // 60)
            window, count = self._counters.get(key, (bucket, 0))
            if window != bucket:
                window, count = bucket, 0
            count += 1
            self._counters[key] = (window, count)
            return count <= self._limit, 60 - int(time.time() % 60)


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _settings_for(request: Request) -> Settings:
    """The settings this *instance* is running with, not the process-wide cached singleton -- tests (and
    anything else that builds a `Runtime` directly rather than through `build_runtime`) pass their own
    `Settings` into `create_app`, and `request.app.state.runtime.settings` is the one that's authoritative.
    """
    runtime = getattr(request.app.state, "runtime", None)
    settings = getattr(runtime, "settings", None)
    return settings if settings is not None else get_settings()


async def require_api_key(
    request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")
) -> str | None:
    settings = _settings_for(request)
    configured = settings.api_key.get_secret_value() if settings.api_key else None
    if configured is None:
        return None  # open API: local-dev only, see /health
    if x_api_key is None or not _constant_time_eq(x_api_key, configured):
        raise AuthenticationError("missing or invalid X-API-Key")
    return x_api_key


async def enforce_rate_limit(request: Request, api_key: str | None = None) -> None:
    runtime = getattr(request.app.state, "runtime", None)
    limiter: RateLimiter | None = getattr(runtime, "rate_limiter", None)
    if limiter is None:
        return
    identity = api_key or (request.client.host if request.client else "unknown")
    allowed, retry_after = await limiter.hit(identity)
    if not allowed:
        raise RateLimitedError("rate limit exceeded", details={"retry_after_seconds": retry_after})


async def authenticate_and_throttle(
    request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")
) -> str | None:
    """Combined dependency: checks the API key, then rate-limits by key (or client IP if the API is open)."""
    api_key = await require_api_key(request, x_api_key)
    await enforce_rate_limit(request, api_key)
    return api_key
