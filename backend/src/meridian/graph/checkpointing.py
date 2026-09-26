"""Checkpointer selection: Postgres when a database is reachable, memory otherwise.

LangGraph checkpoints after every internal step, and that checkpoint is the only complete record of a
run while it is mid-flight -- `RunStore.save_state` only writes at `ainvoke` boundaries. With the
`InMemorySaver` this build shipped with, a restart therefore lost every run in progress, and a run
could only ever be read by the process that started it.

`AsyncPostgresSaver` fixes both. State survives a restart, and because the checkpoint lives in a shared
database rather than one process's memory, an API process can read the live state of a run that a
worker process is executing -- which is what makes `api.live.live_state` keep working once runs move
off the API process.

The in-memory saver remains the fallback for the CLI, for unit tests and for any deployment without a
database, so nothing here is required to run the system.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from meridian.core.config import Settings
from meridian.core.logging import get_logger
from meridian.graph.serde import meridian_msgpack_allowlist

log = get_logger(__name__)


def psycopg_dsn(database_url: str) -> str:
    """Convert a SQLAlchemy URL to the plain DSN psycopg expects.

    The app talks to Postgres through SQLAlchemy + asyncpg, but the LangGraph saver is psycopg-based,
    so the `+asyncpg` (or other) driver suffix has to come off.
    """
    scheme, _, rest = database_url.partition("://")
    base = scheme.split("+", 1)[0]
    return f"{base}://{rest}"


def _incompatible_event_loop() -> str | None:
    """Why psycopg cannot run async on the current loop, or None if it can.

    psycopg refuses Windows' default `ProactorEventLoop`. SQLAlchemy's asyncpg driver has no such
    limitation, so the rest of the database layer keeps working and only checkpointing degrades.
    """
    if sys.platform != "win32":
        return None
    loop = asyncio.get_running_loop()
    if type(loop).__name__ == "ProactorEventLoop":
        return "psycopg cannot run in async mode on Windows' ProactorEventLoop"
    return None


def memory_checkpointer() -> InMemorySaver:
    """An `InMemorySaver` whose serializer knows about every meridian type, warning-free."""
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=meridian_msgpack_allowlist()))


class CheckpointerHandle:
    """A checkpointer plus whatever it needs closing.

    Returned instead of a bare saver so the caller can shut the connection pool down; the in-memory
    case has nothing to close and reports `durable=False`.
    """

    def __init__(
        self, saver: BaseCheckpointSaver[Any], pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None
    ) -> None:
        self.saver = saver
        self._pool = pool

    @property
    def durable(self) -> bool:
        return self._pool is not None

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()


async def build_checkpointer(settings: Settings, *, use_database: bool = True) -> CheckpointerHandle:
    """A Postgres-backed checkpointer, or the in-memory one if Postgres cannot be reached.

    Falling back rather than failing matches how the rest of the runtime treats an absent database: the
    system still runs, it just loses durability, and says so in the log.
    """
    if not use_database or not settings.database_url:
        return CheckpointerHandle(memory_checkpointer(), None)

    if (reason := _incompatible_event_loop()) is not None:
        # Checked up front because the alternative is a ten-second pool timeout on every start, logged
        # as "pool initialization incomplete", which says nothing about the actual cause.
        log.warning(
            "checkpointer_postgres_unsupported_on_this_event_loop",
            detail=reason,
            remedy="runs are durable under Docker (Linux); on native Windows they stay in memory",
        )
        return CheckpointerHandle(memory_checkpointer(), None)

    serde = JsonPlusSerializer(allowed_msgpack_modules=meridian_msgpack_allowlist())
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
    try:
        pool = AsyncConnectionPool[AsyncConnection[DictRow]](
            conninfo=psycopg_dsn(settings.database_url),
            min_size=1,
            max_size=settings.checkpointer_pool_size,
            # `dict_row` is required, not a preference: the saver reads its rows by column name.
            # Autocommit because it manages its own transactions, and no prepared statements because
            # the pool hands the same connection to different queries.
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=False,
        )
        await pool.open(wait=True, timeout=10)
        saver = AsyncPostgresSaver(pool, serde=serde)
        # Idempotent, and deliberately not an Alembic migration: these tables belong to LangGraph, and
        # their schema is versioned by the library rather than by this project.
        await saver.setup()
    except Exception as exc:
        if pool is not None:
            await pool.close()
        log.warning(
            "checkpointer_postgres_unavailable_falling_back_to_memory",
            error=str(exc),
            detail="runs will not survive a restart of this process",
        )
        return CheckpointerHandle(memory_checkpointer(), None)

    log.info("checkpointer_postgres_ready", pool_size=settings.checkpointer_pool_size)
    return CheckpointerHandle(saver, pool)
