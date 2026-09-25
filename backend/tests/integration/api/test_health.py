"""`/health` must respond 200 and report `database: false` when Postgres is unreachable -- never fail."""

from __future__ import annotations

import pytest

from tests.integration.api.conftest import ClientFactory

pytestmark = pytest.mark.asyncio


async def test_health_ok_without_database_or_redis(client_factory: ClientFactory) -> None:
    harness = await client_factory()  # api_settings points at the default (unreachable in this sandbox) DB/Redis
    resp = await harness.client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is False
    assert body["redis"] is False
    assert body["auth_required"] is False


async def test_system_status_reports_offline_llm_and_no_database(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    resp = await harness.client.get("/api/v1/system/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_mode"] == "offline"
    assert body["database"] is False
    assert body["redis"] is False
    assert isinstance(body["providers"], list) and body["providers"]
    assert body["active_runs"] == 0
