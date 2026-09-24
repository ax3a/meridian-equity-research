"""Repository for tool-call records and LLM usage/cost telemetry."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meridian.db.models import LLMUsageModel, ToolCallModel
from meridian.schemas.api import UsageBreakdown
from meridian.schemas.telemetry import LLMUsage, ToolCallRecord


class TelemetryRepository:
    """Persists tool-call and LLM-usage telemetry for a research session.

    Takes an `AsyncSession` owned by the caller; never commits or opens its own transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_tool_calls(self, session_id: str, records: list[ToolCallRecord]) -> None:
        if not records:
            return
        values = [
            {
                "session_id": session_id,
                "id": r.id,
                "agent": r.agent.value,
                "tool": r.tool,
                "arguments": r.arguments,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "result_summary": r.result_summary,
                "error": r.error,
                "attempts": r.attempts,
                "at": r.at,
            }
            for r in records
        ]
        stmt = pg_insert(ToolCallModel).values(values)
        update_cols = {
            c: stmt.excluded[c]
            for c in (
                "agent",
                "tool",
                "arguments",
                "status",
                "duration_ms",
                "result_summary",
                "error",
                "attempts",
                "at",
            )
        }
        stmt = stmt.on_conflict_do_update(index_elements=[ToolCallModel.session_id, ToolCallModel.id], set_=update_cols)
        await self._session.execute(stmt)

    async def save_usage(self, session_id: str, usage: list[LLMUsage]) -> None:
        if not usage:
            return
        self._session.add_all(
            [
                LLMUsageModel(
                    session_id=session_id,
                    agent=u.agent.value,
                    model=u.model,
                    provider=u.provider,
                    input_tokens=u.input_tokens,
                    output_tokens=u.output_tokens,
                    cost_usd=u.cost_usd,
                    latency_ms=u.latency_ms,
                    at=u.at,
                )
                for u in usage
            ]
        )

    async def usage_breakdown(self, session_id: str) -> list[UsageBreakdown]:
        stmt = (
            select(
                LLMUsageModel.agent,
                LLMUsageModel.model,
                func.count().label("calls"),
                func.coalesce(func.sum(LLMUsageModel.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(LLMUsageModel.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(LLMUsageModel.cost_usd), 0.0).label("cost_usd"),
            )
            .where(LLMUsageModel.session_id == session_id)
            .group_by(LLMUsageModel.agent, LLMUsageModel.model)
            .order_by(LLMUsageModel.agent, LLMUsageModel.model)
        )
        result = await self._session.execute(stmt)
        return [
            UsageBreakdown(
                agent=row.agent,
                model=row.model,
                calls=int(row.calls),
                input_tokens=int(row.input_tokens),
                output_tokens=int(row.output_tokens),
                cost_usd=float(row.cost_usd),
            )
            for row in result.all()
        ]
