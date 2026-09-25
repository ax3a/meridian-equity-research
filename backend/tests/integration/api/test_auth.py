"""`X-API-Key` enforcement: open when unset, required and constant-time-compared when set."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from tests.integration.api.conftest import ClientFactory

pytestmark = pytest.mark.asyncio


async def test_open_api_when_no_key_configured(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    resp = await harness.client.get("/api/v1/system/status")
    assert resp.status_code == 200


async def test_rejects_missing_or_bad_key(client_factory: ClientFactory, api_settings) -> None:
    settings = api_settings.model_copy(update={"api_key": SecretStr("secret-123")})
    harness = await client_factory(settings=settings)

    missing = await harness.client.get("/api/v1/system/status")
    assert missing.status_code == 401
    body = missing.json()
    assert body["error"]["code"] == "unauthenticated"

    wrong = await harness.client.get("/api/v1/system/status", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401


async def test_accepts_good_key(client_factory: ClientFactory, api_settings) -> None:
    settings = api_settings.model_copy(update={"api_key": SecretStr("secret-123")})
    harness = await client_factory(settings=settings)

    resp = await harness.client.get("/api/v1/system/status", headers={"X-API-Key": "secret-123"})
    assert resp.status_code == 200


async def test_health_is_unauthenticated(client_factory: ClientFactory, api_settings) -> None:
    settings = api_settings.model_copy(update={"api_key": SecretStr("secret-123")})
    harness = await client_factory(settings=settings)

    resp = await harness.client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["auth_required"] is True
