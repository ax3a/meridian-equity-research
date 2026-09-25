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

# A DEDICATED database, never the development one. These fixtures drop every table at teardown, so
# pointing them at `meridian` wipes the developer's data -- which is exactly what happened once: a test
# run deleted the schema that `alembic upgrade head` had just created, and the API then 500'd on every
# request. The guard below refuses to run against a database whose name does not end in `_test`.
DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian_test"
TEST_DATABASE_URL = os.environ.get("MERIDIAN_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
TEST_DB_NAME = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?", 1)[0]


async def _ensure_test_database_exists() -> bool:
    """Create the test database if it is missing. Returns False when Postgres is unreachable."""
    import asyncpg

    admin_dsn = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").rsplit("/", 1)[0] + "/postgres"
    try:
        conn = await asyncpg.connect(admin_dsn, timeout=3)
    except Exception:
        return False
    try:
        exists = await conn.fetchval("select 1 from pg_database where datname = $1", TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
        return True
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def db_settings() -> Settings:
    return Settings(database_url=TEST_DATABASE_URL, llm_provider="offline", redis_url=None)


@pytest.fixture
async def engine(db_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Function-scoped: `pyproject.toml` pins `asyncio_default_fixture_loop_scope = "function"`,
    so a session-scoped async fixture would outlive its event loop. Recreating the (empty) schema
    per test is cheap and keeps every test fully isolated regardless."""
    if not TEST_DB_NAME.endswith("_test"):
        pytest.skip(
            f"refusing to run destructive schema tests against {TEST_DB_NAME!r}: these fixtures drop every "
            "table at teardown. Point MERIDIAN_TEST_DATABASE_URL at a database whose name ends in '_test'."
        )
    if not await _ensure_test_database_exists():
        pytest.skip(f"Postgres is unreachable at {TEST_DATABASE_URL!r}")

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
