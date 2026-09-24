from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from meridian.core.config import get_settings

# Import models so they are registered on Base.metadata (needed for --autogenerate).
from meridian.db import models as _models  # noqa: F401
from meridian.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_database_url() -> str:
    """The app runs on asyncpg; migrations run synchronously via psycopg so `env.py` needs no event loop.

    `MERIDIAN_MIGRATIONS_URL` overrides everything (used by tests against a throwaway database).
    """
    override = os.environ.get("MERIDIAN_MIGRATIONS_URL")
    if override:
        return override
    url = get_settings().database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    """Render SQL without a live DB connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=_sync_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _sync_database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
