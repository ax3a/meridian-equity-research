"""Declarative base and shared metadata conventions for the Meridian ORM models."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# A stable naming convention keeps constraint names deterministic across
# `alembic` autogeneration and manual migrations alike.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base for every Meridian ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
