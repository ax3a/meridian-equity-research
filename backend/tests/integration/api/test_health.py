"""`/health` must answer 200 whether or not Postgres and Redis are reachable, and report the truth.

These tests previously asserted `database is False`, which passed only because the sandbox had no
Postgres. Once a real database was running they failed, having been assertions about the environment
rather than about behaviour. They now pin the dependency explicitly instead of inheriting it.
"""

from __future__ import annotations

import pytest

from meridian.core.config import Settings
from tests.integration.api.conftest import ClientFactory

pytestmark = pytest.mark.asyncio

UNREACHABLE_DB = "postgresql+asyncpg://meridian:meridian@127.0.0.1:59999/meridian"


async def test_health_is_ok_and_honest_when_storage_is_unreachable(
    client_factory: ClientFactory, api_settings: Settings
) -> None:
    offline = api_settings.model_copy(update={"database_url": UNREACHABLE_DB, "redis_url": None})
    harness = await client_factory(settings=offline)

    resp = await harness.client.get("/health")

    assert resp.status_code == 200, "health must never fail because storage is down"
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is False
    assert body["redis"] is False
    assert body["auth_required"] is False


async def test_system_status_reports_offline_llm_and_unreachable_storage(
    client_factory: ClientFactory, api_settings: Settings
) -> None:
    offline = api_settings.model_copy(update={"database_url": UNREACHABLE_DB, "redis_url": None})
    harness = await client_factory(settings=offline)

    resp = await harness.client.get("/api/v1/system/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_mode"] == "offline"
    assert body["database"] is False
    assert body["redis"] is False
    assert isinstance(body["providers"], list) and body["providers"]
    assert body["active_runs"] == 0


async def test_health_reports_storage_state_as_booleans_whatever_the_environment(
    client_factory: ClientFactory,
) -> None:
    """With ambient settings the values depend on what is running locally; the contract is the shape."""
    harness = await client_factory()

    body = (await harness.client.get("/health")).json()

    assert body["status"] == "ok"
    assert isinstance(body["database"], bool)
    assert isinstance(body["redis"], bool)
