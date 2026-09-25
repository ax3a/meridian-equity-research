"""Fixtures for the API integration suite.

Every test drives the real FastAPI app (`meridian.api.app.create_app`) over `httpx.ASGITransport`, with a
`Runtime` built from the fakes in `fakes.py` instead of `api.wiring.build_runtime` -- so requests exercise
real routing, auth, rate limiting, error mapping and SSE, but never touch the network, a real LLM, or a
database. `LocalRunStore` (the same fallback the app uses when Postgres is unreachable) backs every run.

`create_app()`'s lifespan (which builds a *real* `Runtime`) is intentionally bypassed here: plain
`httpx.ASGITransport` never sends ASGI lifespan events, so `app.state.runtime` is set directly instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from meridian.api.app import create_app
from meridian.api.concurrency import RunAdmission
from meridian.api.memory_store import LocalRunStore
from meridian.api.security import RateLimiter
from meridian.api.wiring import Runtime
from meridian.core.config import Settings
from meridian.graph.runner import ResearchRunner
from meridian.memory.inmemory import InMemoryPreferenceStore, InMemoryResearchMemoryStore
from meridian.schemas.research import CompanyIdentity
from tests.integration.api.fakes import TEST_COMPANY, build_fake_agent_set


@dataclass
class FakeDirectory:
    """Just enough of `CompanyDirectory` for `/companies/search` -- no network involved."""

    results: list[CompanyIdentity]

    async def search(self, query: str, limit: int = 10) -> list[CompanyIdentity]:
        return self.results[:limit]

    async def resolve(self, query: str) -> CompanyIdentity:
        return self.results[0]


@dataclass
class FakeProviders:
    directory: FakeDirectory


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        redis_url=None,
        llm_provider="offline",
        data_mode="live",
        snapshot_dir=tmp_path / "snapshots",
        model_cache_dir=tmp_path / "models",
        embedding_provider="hashing",
        sec_user_agent="Meridian Test test@example.com",
        api_key=None,
        rate_limit_per_minute=1000,
        require_approval_default=True,
        agent_timeout_seconds=5.0,
        graph_recursion_limit=100,
    )


@dataclass
class ApiHarness:
    client: AsyncClient
    runtime: Runtime
    handles: dict[str, Any]


ClientFactory = Callable[..., Awaitable[ApiHarness]]


@pytest.fixture
async def client_factory(api_settings: Settings) -> AsyncIterator[ClientFactory]:
    created: list[AsyncClient] = []

    async def _factory(*, settings: Settings | None = None, **fake_kwargs: Any) -> ApiHarness:
        resolved_settings = settings or api_settings
        agent_set, handles = build_fake_agent_set(**fake_kwargs)
        store = LocalRunStore()
        runner = ResearchRunner(agent_set, resolved_settings, store=store)
        rate_limiter = RateLimiter(resolved_settings.rate_limit_per_minute, None)
        await rate_limiter.start()
        runtime = Runtime(
            settings=resolved_settings,
            runner=runner,
            store=store,
            admission=RunAdmission(limit=10),
            providers=FakeProviders(directory=FakeDirectory(results=[TEST_COMPANY])),
            preferences=InMemoryPreferenceStore(),
            memory=InMemoryResearchMemoryStore(),
            rate_limiter=rate_limiter,
            db_available=False,
            redis_available=False,
        )
        app = create_app(settings=resolved_settings, runtime=runtime)
        app.state.runtime = runtime  # bypass lifespan: ASGITransport never sends lifespan events
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        created.append(client)
        return ApiHarness(client=client, runtime=runtime, handles=handles)

    try:
        yield _factory
    finally:
        for client in created:
            await client.aclose()


@pytest.fixture
async def harness(client_factory: ClientFactory) -> ApiHarness:
    """The common case: one FINANCIALS task, default (approval-required) settings."""
    return await client_factory()
