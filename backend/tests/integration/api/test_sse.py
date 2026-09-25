"""The SSE progress stream: replay-then-live for an in-flight run, and immediate termination (no hang)
for a run that has already finished before the client ever connects.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from tests.integration.api.conftest import ClientFactory
from tests.integration.api.helpers import wait_for_status_value, wait_for_terminal

pytestmark = pytest.mark.asyncio


async def _collect_sse(client: AsyncClient, url: str) -> list[dict]:
    events: list[dict] = []
    async with client.stream("GET", url) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


async def test_sse_replays_past_events_then_streams_live_ones(client_factory: ClientFactory) -> None:
    harness = await client_factory()  # require_approval defaults True -> the run will pause
    client = harness.client

    create = await client.post("/api/v1/research", json={"query": "Analyse Test Co"})
    session_id = create.json()["id"]
    await wait_for_status_value(client, session_id, "awaiting_approval")

    collected: list[dict] = []

    async def consume() -> None:
        collected.extend(await _collect_sse(client, f"/api/v1/research/{session_id}/events"))

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)  # let the replay (of events emitted before we connected) land

    approve = await client.post(f"/api/v1/research/{session_id}/approve")
    assert approve.status_code == 204
    await wait_for_terminal(client, session_id)
    await asyncio.wait_for(task, timeout=5.0)

    types = [e["type"] for e in collected]
    assert "awaiting_approval" in types  # replayed: emitted before we ever connected
    assert "feedback_received" in types  # live: emitted only after our POST /approve
    assert types[-1] == "run_completed"
    seqs = [e["seq"] for e in collected]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


async def test_sse_for_a_finished_run_replays_and_terminates_immediately(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    client = harness.client

    create = await client.post("/api/v1/research", json={"query": "Analyse Test Co", "require_approval": False})
    session_id = create.json()["id"]
    await wait_for_terminal(client, session_id)

    # The regression this guards against: a client connecting *after* the run is over would otherwise
    # hang forever, because `ResearchRunner` only wakes subscribers registered before it closed them out.
    events = await asyncio.wait_for(_collect_sse(client, f"/api/v1/research/{session_id}/events"), timeout=2.0)
    assert events
    assert events[-1]["type"] == "run_completed"


async def test_sse_after_seq_skips_already_seen_events(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    client = harness.client

    create = await client.post("/api/v1/research", json={"query": "Analyse Test Co", "require_approval": False})
    session_id = create.json()["id"]
    await wait_for_terminal(client, session_id)

    full = await asyncio.wait_for(_collect_sse(client, f"/api/v1/research/{session_id}/events"), timeout=2.0)
    assert len(full) >= 2
    cutoff = full[0]["seq"]

    partial = await asyncio.wait_for(
        _collect_sse(client, f"/api/v1/research/{session_id}/events?after_seq={cutoff}"), timeout=2.0
    )
    assert all(e["seq"] > cutoff for e in partial)
    assert len(partial) == len(full) - 1
