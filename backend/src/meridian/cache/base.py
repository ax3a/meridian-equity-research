from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from meridian.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class CachePolicy:
    """Freshness policy per data class. ttl_seconds=None means immutable (cache long-term)."""

    name: str
    ttl_seconds: int | None


MINUTE, HOUR, DAY = 60, 3600, 86400


class Policies:
    TICKERS = CachePolicy("tickers", 7 * DAY)
    SUBMISSIONS = CachePolicy("submissions", 6 * HOUR)
    COMPANY_FACTS = CachePolicy("company_facts", DAY)
    FRAMES = CachePolicy("frames", 7 * DAY)
    FILING_DOCUMENT = CachePolicy("filing_document", None)  # filed documents never change
    PRICES = CachePolicy("prices", 15 * MINUTE)
    NEWS = CachePolicy("news", HOUR)
    MACRO = CachePolicy("macro", 6 * HOUR)
    PROFILE = CachePolicy("profile", DAY)
    EMBEDDINGS = CachePolicy("embeddings", 30 * DAY)
    NONE = CachePolicy("none", 0)


IMMUTABLE_TTL = 30 * DAY


@runtime_checkable
class Cache(Protocol):
    name: str

    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None: ...

    async def delete(self, key: str) -> None: ...


class MemoryCache:
    name = "memory"

    def __init__(self, max_items: int = 2048) -> None:
        self._data: dict[str, tuple[float | None, bytes]] = {}
        self._max = max_items

    async def get(self, key: str) -> bytes | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires is not None and expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        if ttl_seconds == 0:
            return
        if len(self._data) >= self._max:
            self._data.pop(next(iter(self._data)))
        ttl = ttl_seconds if ttl_seconds is not None else IMMUTABLE_TTL
        self._data[key] = (time.monotonic() + ttl, value)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class RedisCache:
    """Redis cache that degrades to an in-process cache if Redis is unreachable."""

    name = "redis"

    def __init__(self, url: str, prefix: str = "meridian:") -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, socket_connect_timeout=1.5, socket_timeout=3)
        self._prefix = prefix
        self._fallback = MemoryCache()
        self._healthy = True

    async def _call(self, op: str, *args: object) -> object:
        if not self._healthy:
            return None
        try:
            return await getattr(self._redis, op)(*args)
        except Exception as exc:  # network boundary: degrade gracefully
            log.warning("redis_unavailable_falling_back", error=str(exc))
            self._healthy = False
            return None

    async def get(self, key: str) -> bytes | None:
        value = await self._call("get", self._prefix + key)
        if isinstance(value, bytes):
            return value
        return await self._fallback.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        if ttl_seconds == 0:
            return
        ttl = ttl_seconds if ttl_seconds is not None else IMMUTABLE_TTL
        if self._healthy:
            await self._call("set", self._prefix + key, value, ttl)
        if not self._healthy:
            await self._fallback.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        await self._call("delete", self._prefix + key)
        await self._fallback.delete(key)

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self._redis.aclose()


def build_cache(redis_url: str | None) -> Cache:
    return RedisCache(redis_url) if redis_url else MemoryCache()
