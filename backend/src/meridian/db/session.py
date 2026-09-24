"""Engine/session factory helpers. Callers own the unit of work (commit/rollback)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from meridian.core.config import Settings


def create_db_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine used by the application (asyncpg driver)."""
    return create_async_engine(settings.database_url, pool_pre_ping=True, future=True)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build a session factory. Sessions never auto-commit; the caller commits."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=True)


async def check_database(engine: AsyncEngine) -> bool:
    """Return True if the database is reachable, False otherwise (never raises)."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
