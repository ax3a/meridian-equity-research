from __future__ import annotations

import asyncio
from typing import Any

from httpx import AsyncClient

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


async def wait_for_status(
    client: AsyncClient, session_id: str, *, predicate, timeout_s: float = 5.0, interval: float = 0.02
) -> dict[str, Any]:
    """Poll `GET /research/{id}/status` until `predicate(status_json)` is true, or raise on timeout."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    last: dict[str, Any] | None = None
    while loop.time() < deadline:
        resp = await client.get(f"/api/v1/research/{session_id}/status")
        resp.raise_for_status()
        last = resp.json()
        if predicate(last):
            return last
        await asyncio.sleep(interval)
    raise AssertionError(f"timed out waiting for status predicate; last status was {last!r}")


async def wait_for_terminal(client: AsyncClient, session_id: str, *, timeout_s: float = 5.0) -> dict[str, Any]:
    return await wait_for_status(
        client, session_id, predicate=lambda s: s["status"] in TERMINAL_STATUSES, timeout_s=timeout_s
    )


async def wait_for_status_value(
    client: AsyncClient, session_id: str, value: str, *, timeout_s: float = 5.0
) -> dict[str, Any]:
    return await wait_for_status(client, session_id, predicate=lambda s: s["status"] == value, timeout_s=timeout_s)
