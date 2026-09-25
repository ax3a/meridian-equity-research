"""Integration tests for `TelemetryRepository` against a real Postgres instance."""

from __future__ import annotations

import pytest

from meridian.core.ids import new_id
from meridian.db.repositories.research import ResearchRepository
from meridian.db.repositories.telemetry import TelemetryRepository
from meridian.schemas.enums import AgentName
from meridian.schemas.telemetry import LLMUsage, ToolCallRecord
from tests.integration.db.helpers import make_request, unique_session_id

pytestmark = pytest.mark.integration


async def _new_session(db_session) -> str:
    session_id = unique_session_id()
    await ResearchRepository(db_session).create(session_id, make_request(), llm_mode="offline", data_mode="live")
    return session_id


async def test_save_tool_calls_upserts_by_id(db_session) -> None:
    session_id = await _new_session(db_session)
    repo = TelemetryRepository(db_session)
    record = ToolCallRecord(
        id=new_id("tc"),
        agent=AgentName.FINANCIALS,
        tool="get_financial_statements",
        status="ok",
        duration_ms=42.0,
    )
    await repo.save_tool_calls(session_id, [record])
    updated = record.model_copy(update={"status": "cached", "duration_ms": 1.0})
    await repo.save_tool_calls(session_id, [updated])

    from sqlalchemy import select

    from meridian.db.models import ToolCallModel

    rows = (
        (await db_session.execute(select(ToolCallModel).where(ToolCallModel.session_id == session_id))).scalars().all()
    )
    assert len(rows) == 1
    assert rows[0].status == "cached"


async def test_usage_breakdown_aggregates_by_agent_and_model(db_session) -> None:
    session_id = await _new_session(db_session)
    repo = TelemetryRepository(db_session)
    usage = [
        LLMUsage(
            agent=AgentName.FINANCIALS,
            model="claude-sonnet-5",
            provider="anthropic",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.01,
        ),
        LLMUsage(
            agent=AgentName.FINANCIALS,
            model="claude-sonnet-5",
            provider="anthropic",
            input_tokens=200,
            output_tokens=75,
            cost_usd=0.02,
        ),
        LLMUsage(
            agent=AgentName.CRITIC,
            model="claude-opus-5",
            provider="anthropic",
            input_tokens=300,
            output_tokens=100,
            cost_usd=0.05,
        ),
    ]
    await repo.save_usage(session_id, usage)

    breakdown = await repo.usage_breakdown(session_id)
    by_key = {(b.agent, b.model): b for b in breakdown}

    financials = by_key[("financials", "claude-sonnet-5")]
    assert financials.calls == 2
    assert financials.input_tokens == 300
    assert financials.output_tokens == 125
    assert financials.cost_usd == pytest.approx(0.03)

    critic = by_key[("critic", "claude-opus-5")]
    assert critic.calls == 1
    assert critic.cost_usd == pytest.approx(0.05)
