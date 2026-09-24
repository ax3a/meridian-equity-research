"""Fixtures for the DB integration suite.

Every test in this package needs a real Postgres (pgvector) instance. When one isn't reachable
(e.g. `docker compose up -d db` hasn't been run, or Docker itself is unavailable) the `engine`
fixture calls `pytest.skip`, so the whole suite skips cleanly instead of failing.

Each test gets its own `AsyncSession` that is rolled back at teardown (never committed), so tests
never need to worry about leaking rows between runs.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from meridian.core.config import Settings

# Import models so Base.metadata is fully populated before create_all/drop_all.
from meridian.db import models as _models  # noqa: F401
from meridian.db.base import Base
from meridian.db.session import check_database, create_db_engine, session_factory

TEST_DATABASE_URL = os.environ.get(
    "MERIDIAN_TEST_DATABASE_URL",
    "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian",
)


@pytest.fixture(scope="session")
def db_settings() -> Settings:
    return Settings(database_url=TEST_DATABASE_URL, llm_provider="offline", redis_url=None)


@pytest.fixture
async def engine(db_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Function-scoped: `pyproject.toml` pins `asyncio_default_fixture_loop_scope = "function"`,
    so a session-scoped async fixture would outlive its event loop. Recreating the (empty) schema
    per test is cheap and keeps every test fully isolated regardless."""
    eng = create_db_engine(db_settings)
    if not await check_database(eng):
        await eng.dispose()
        pytest.skip(f"Postgres is unreachable at {TEST_DATABASE_URL!r}")
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = session_factory(engine)
    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
