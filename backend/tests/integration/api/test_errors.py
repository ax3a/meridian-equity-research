"""Every error path must come back through the frozen `ErrorResponse` shape: `{"error": {code, message,
details, request_id}}`.
"""

from __future__ import annotations

import pytest

from tests.integration.api.conftest import ClientFactory

pytestmark = pytest.mark.asyncio


def _assert_error_shape(payload: dict, *, code: str | None = None) -> None:
    assert "error" in payload
    error = payload["error"]
    assert set(error) >= {"code", "message", "details", "request_id"}
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], dict)
    if code is not None:
        assert error["code"] == code


async def test_404_shape_for_unknown_run(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    resp = await harness.client.get("/api/v1/research/run_nope/status")
    assert resp.status_code == 404
    _assert_error_shape(resp.json(), code="not_found")
    assert resp.headers.get("x-request-id")
    assert resp.json()["error"]["request_id"] == resp.headers["x-request-id"]


async def test_409_shape_when_not_awaiting_approval(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    create = await harness.client.post("/api/v1/research", json={"query": "Analyse Test Co", "require_approval": False})
    session_id = create.json()["id"]

    resp = await harness.client.post(f"/api/v1/research/{session_id}/approve")
    assert resp.status_code == 409
    _assert_error_shape(resp.json(), code="conflict")


async def test_422_shape_for_invalid_body(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    resp = await harness.client.post("/api/v1/research", json={"query": "a"})  # min_length=2
    assert resp.status_code == 422
    body = resp.json()
    _assert_error_shape(body, code="validation_failed")
    assert "errors" in body["error"]["details"]


async def test_review_404_before_plan_exists_is_not_a_500(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    resp = await harness.client.get("/api/v1/research/run_nope/review")
    assert resp.status_code == 404
    _assert_error_shape(resp.json())
