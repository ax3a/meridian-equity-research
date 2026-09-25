"""The human-in-the-loop checkpoint: a run pauses, `/review` shows the package, `/approve` resumes it to
a completed report; `/feedback` records the feedback and resumes without approving.
"""

from __future__ import annotations

import asyncio

import pytest

from meridian.schemas.enums import AgentName
from tests.integration.api.conftest import ClientFactory
from tests.integration.api.helpers import wait_for_status_value, wait_for_terminal

pytestmark = pytest.mark.asyncio


async def test_approval_flow_pauses_reviews_and_resumes_to_report(client_factory: ClientFactory) -> None:
    harness = await client_factory(specialist_agents=[AgentName.FINANCIALS, AgentName.RISK])
    client = harness.client

    create = await client.post("/api/v1/research", json={"query": "Analyse Test Co"})
    session_id = create.json()["id"]

    status = await wait_for_status_value(client, session_id, "awaiting_approval")
    assert status["approval"] == "pending"

    review_resp = await client.get(f"/api/v1/research/{session_id}/review")
    assert review_resp.status_code == 200
    review = review_resp.json()
    assert review["session_id"] == session_id
    assert review["company"]["ticker"] == "TST"
    assert review["plan"]["tasks"]
    assert review["sources"]
    assert {p["agent"] for p in review["preliminary"]} == {"financials", "risk"}
    assert "approve" in review["available_actions"]

    approve_resp = await client.post(f"/api/v1/research/{session_id}/approve")
    assert approve_resp.status_code == 204

    final = await wait_for_terminal(client, session_id)
    assert final["status"] == "completed"
    assert final["approval"] == "approved"

    report = (await client.get(f"/api/v1/research/{session_id}/report")).json()
    assert report["company"]["ticker"] == "TST"
    assert report["session_id"] == session_id


async def test_feedback_flow_records_feedback_and_resumes(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    client = harness.client

    create = await client.post("/api/v1/research", json={"query": "Analyse Test Co"})
    session_id = create.json()["id"]
    await wait_for_status_value(client, session_id, "awaiting_approval")

    fb_resp = await client.post(
        f"/api/v1/research/{session_id}/feedback",
        json={"actions": [{"action": "comment", "comment": "please double-check margins"}]},
    )
    assert fb_resp.status_code == 204

    loop = asyncio.get_event_loop()
    deadline = loop.time() + 5.0
    detail: dict | None = None
    while loop.time() < deadline:
        detail = (await client.get(f"/api/v1/research/{session_id}")).json()
        if detail["human_feedback"]:
            break
        await asyncio.sleep(0.02)
    assert detail is not None and detail["human_feedback"], "feedback was never recorded onto the run"
    assert detail["human_feedback"][0]["comment"] == "please double-check margins"
    assert detail["human_feedback"][0]["action"] == "comment"
