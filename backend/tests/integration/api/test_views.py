"""`/agents`, `/sources` and `/trace` shapes, checked against the frozen response models."""

from __future__ import annotations

import pytest

from meridian.schemas.api import AgentRunView, SourceView, TraceView
from meridian.schemas.enums import AgentName
from tests.integration.api.conftest import ClientFactory
from tests.integration.api.helpers import wait_for_terminal

pytestmark = pytest.mark.asyncio


async def test_agents_sources_trace_shapes(client_factory: ClientFactory) -> None:
    harness = await client_factory(specialist_agents=[AgentName.FINANCIALS])
    client = harness.client

    create = await client.post("/api/v1/research", json={"query": "Analyse Test Co", "require_approval": False})
    session_id = create.json()["id"]
    await wait_for_terminal(client, session_id)

    agents_resp = await client.get(f"/api/v1/research/{session_id}/agents")
    assert agents_resp.status_code == 200
    agents = [AgentRunView.model_validate(a) for a in agents_resp.json()]
    assert len(agents) == 1
    assert agents[0].agent == AgentName.FINANCIALS
    assert agents[0].status.value == "completed"
    assert agents[0].wave == 1
    assert agents[0].findings
    assert agents[0].duration_ms is not None

    sources_resp = await client.get(f"/api/v1/research/{session_id}/sources")
    assert sources_resp.status_code == 200
    sources = [SourceView.model_validate(s) for s in sources_resp.json()]
    assert len(sources) == 1
    assert sources[0].evidence
    assert sources[0].cited_by_findings, "the fake finding cites evidence belonging to this source"

    trace_resp = await client.get(f"/api/v1/research/{session_id}/trace")
    assert trace_resp.status_code == 200
    trace = TraceView.model_validate(trace_resp.json())
    assert trace.session_id == session_id
    assert trace.total_tokens >= 0
    assert isinstance(trace.timings_ms, dict)


async def test_report_404_before_completion(client_factory: ClientFactory) -> None:
    harness = await client_factory()
    client = harness.client
    create = await client.post("/api/v1/research", json={"query": "Analyse Test Co"})  # pauses for approval
    session_id = create.json()["id"]

    resp = await client.get(f"/api/v1/research/{session_id}/report")
    assert resp.status_code == 404
