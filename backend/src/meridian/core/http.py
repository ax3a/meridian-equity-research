"""Outbound HTTP for all providers: SSRF allowlist, caching, retries, per-host throttling, snapshot fallback."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from meridian.cache.base import Cache, CachePolicy
from meridian.core.config import Settings
from meridian.core.errors import BlockedURLError, ProviderError, ProviderUnavailableError
from meridian.core.logging import get_logger
from meridian.providers.snapshots import SnapshotStore, request_key

log = get_logger(__name__)

ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "www.sec.gov",
        "data.sec.gov",
        "efts.sec.gov",
        "stooq.com",
        "stooq.pl",
        "api.gdeltproject.org",
        "api.fiscaldata.treasury.gov",
        "financialmodelingprep.com",
        "www.alphavantage.co",
        "finnhub.io",
        "api.polygon.io",
        "api.stlouisfed.org",
        "query1.finance.yahoo.com",
        "home.treasury.gov",
    }
)

# Requests per second per host. SEC fair-access policy caps at 10 req/s.
HOST_RATE: dict[str, float] = {
    "www.sec.gov": 8.0,
    "data.sec.gov": 8.0,
    "efts.sec.gov": 5.0,
    "api.gdeltproject.org": 0.2,
}
DEFAULT_RATE = 4.0
MAX_BODY_BYTES = 60 * 1024 * 1024

ContentType = Literal["json", "text"]


def validate_url(url: str, allowed_hosts: frozenset[str] = ALLOWED_HOSTS) -> str:
    """SSRF guard: https only, allowlisted hostname, never an IP literal or credentials."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise BlockedURLError(f"only https URLs are allowed: {url[:120]}")
    host = (parsed.hostname or "").lower()
    if not host or parsed.username or parsed.password:
        raise BlockedURLError("malformed URL")
    try:
        ipaddress.ip_address(host)
        raise BlockedURLError("IP-literal hosts are not allowed")
    except ValueError:
        pass
    if parsed.port not in (None, 443):
        raise BlockedURLError("non-standard ports are not allowed")
    if host not in allowed_hosts:
        raise BlockedURLError(f"host not allowlisted: {host}")
    return host


@dataclass
class FetchResult:
    body: Any
    url: str
    from_cache: bool = False
    from_snapshot: bool = False
    snapshot_date: date | None = None


class _Throttle:
    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 425, 429, 500, 502, 503, 504)
    return isinstance(exc, httpx.TransportError)


class HttpClient:
    def __init__(
        self,
        settings: Settings,
        cache: Cache,
        snapshots: SnapshotStore,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        record_snapshots: bool = False,
        allowed_hosts: frozenset[str] = ALLOWED_HOSTS,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.snapshots = snapshots
        self.record_snapshots = record_snapshots
        self.allowed_hosts = allowed_hosts
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        self._throttles: dict[str, _Throttle] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers_for(self, host: str) -> dict[str, str]:
        if host.endswith("sec.gov"):
            return {"User-Agent": self.settings.sec_user_agent}
        return {"User-Agent": "Meridian-Research/0.1"}

    async def get_json(
        self,
        url: str,
        *,
        provider: str,
        policy: CachePolicy,
        params: dict[str, Any] | None = None,
        snapshot_transform: Callable[[Any], Any] | None = None,
    ) -> FetchResult:
        return await self._get(
            url,
            provider=provider,
            policy=policy,
            params=params,
            content_type="json",
            snapshot_transform=snapshot_transform,
        )

    async def get_text(
        self,
        url: str,
        *,
        provider: str,
        policy: CachePolicy,
        params: dict[str, Any] | None = None,
        snapshot_transform: Callable[[Any], Any] | None = None,
    ) -> FetchResult:
        return await self._get(
            url,
            provider=provider,
            policy=policy,
            params=params,
            content_type="text",
            snapshot_transform=snapshot_transform,
        )

    async def _get(
        self,
        url: str,
        *,
        provider: str,
        policy: CachePolicy,
        params: dict[str, Any] | None,
        content_type: ContentType,
        snapshot_transform: Callable[[Any], Any] | None,
    ) -> FetchResult:
        host = validate_url(url, self.allowed_hosts)
        cache_key = f"http:{provider}:{request_key(url, params)}"
        mode = self.settings.data_mode

        if mode != "snapshot":
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return FetchResult(body=_decode(cached, content_type), url=url, from_cache=True)

        if mode == "snapshot":
            return self._from_snapshot(provider, url, params)

        try:
            body = await self._fetch_live(host, url, params, content_type)
        except ProviderError as exc:
            if mode == "auto" and self.snapshots.exists(provider, url, params):
                log.warning("live_fetch_failed_using_snapshot", provider=provider, error=exc.message)
                return self._from_snapshot(provider, url, params)
            raise

        await self.cache.set(cache_key, _encode(body, content_type), policy.ttl_seconds)
        if self.record_snapshots:
            stored = snapshot_transform(body) if snapshot_transform else body
            self.snapshots.save(provider, url, params, stored, content_type)
        return FetchResult(body=body, url=url)

    def _from_snapshot(self, provider: str, url: str, params: dict[str, Any] | None) -> FetchResult:
        snap = self.snapshots.load(provider, url, params)
        if snap is None:
            raise ProviderUnavailableError(provider, f"no recorded snapshot for {url[:160]}")
        return FetchResult(body=snap.body, url=url, from_snapshot=True, snapshot_date=snap.snapshot_date)

    async def _fetch_live(self, host: str, url: str, params: dict[str, Any] | None, content_type: ContentType) -> Any:
        throttle = self._throttles.setdefault(host, _Throttle(HOST_RATE.get(host, DEFAULT_RATE)))
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential_jitter(initial=0.5, max=8),
                retry=retry_if_exception(_retryable),
                reraise=True,
            ):
                with attempt:
                    await throttle.wait()
                    resp = await self._client.get(url, params=params, headers=self._headers_for(host))
                    resp.raise_for_status()
                    if len(resp.content) > MAX_BODY_BYTES:
                        raise ProviderError(host, "response too large", retryable=False)
                    return resp.json() if content_type == "json" else resp.text
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise ProviderError(host, f"HTTP {code} for {url[:160]}", retryable=_retryable(exc), status=code) from exc
        except httpx.TransportError as exc:
            raise ProviderError(host, f"network error: {type(exc).__name__}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(host, "invalid JSON response", retryable=False) from exc
        raise ProviderError(host, "unreachable")  # pragma: no cover


def _encode(body: Any, content_type: ContentType) -> bytes:
    return json.dumps(body).encode() if content_type == "json" else str(body).encode()


def _decode(raw: bytes, content_type: ContentType) -> Any:
    return json.loads(raw) if content_type == "json" else raw.decode()
