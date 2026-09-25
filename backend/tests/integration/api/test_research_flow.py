"""Create a run, poll it to completion, and fetch its report -- the happy path with no approval pause."""

from __future__ import annotations

import pytest

from tests.integration.api.conftest import ApiHarness, ClientFactory
from tests.integration.api.helpers import wait_for_terminal

pytestmark = pytest.mark.asyncio


async def test_create_and_poll_to_completion(client_factory: ClientFactory) -> None:
    harness: ApiHarness = await client_factory()
    client = harness.client

    resp = await client.post("/api/v1/research", json={"query": "Analyse Test Company", "require_approval": False})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    assert body["events_url"] == f"/api/v1/research/{body['id']}/events"
    assert body["status_url"] == f"/api/v1/research/{body['id']}/status"
    session_id = body["id"]

    final = await wait_for_terminal(client, session_id)
    assert final["status"] == "completed"
    assert final["progress"] == 1.0
    assert final["approval"] in ("not_required", "approved")

    report_resp = await client.get(f"/api/v1/research/{session_id}/report")
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert report["session_id"] == session_id
    assert report["company"]["ticker"] == "TST"
    assert report["sections"], "fake writer should have produced at least one section"

    detail_resp = await client.get(f"/api/v1/research/{session_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["has_report"] is True
    assert detail["status"] == "completed"

    listing_resp = await client.get("/api/v1/research")
    assert listing_resp.status_code == 200
    listing = listing_resp.json()
    assert any(r["id"] == session_id for r in listing)


async def test_status_404_for_unknown_run(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    resp = await harness.client.get("/api/v1/research/run_does_not_exist/status")
    assert resp.status_code == 404
