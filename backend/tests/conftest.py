"""Shared fixtures. Workstreams add their own directory-level conftest.py rather than editing this file."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

os.environ.setdefault("ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LLM_PROVIDER", "offline")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("EMBEDDING_PROVIDER", "hashing")


@pytest.fixture
def settings(tmp_path: Path):
    from meridian.core.config import Settings

    return Settings(
        env="test",
        redis_url=None,
        llm_provider="offline",
        data_mode="live",
        snapshot_dir=tmp_path / "snapshots",
        model_cache_dir=tmp_path / "models",
        embedding_provider="hashing",
        sec_user_agent="Meridian Test test@example.com",
    )


@pytest.fixture
def memory_cache():
    from meridian.cache.base import MemoryCache

    return MemoryCache()


@pytest.fixture
def snapshot_store(tmp_path: Path):
    from meridian.providers.snapshots import SnapshotStore

    return SnapshotStore(tmp_path / "snapshots")


@pytest.fixture
def events():
    from meridian.observability.events import ListEventSink

    return ListEventSink()


@pytest.fixture
async def http_client(settings, memory_cache, snapshot_store) -> AsyncIterator:
    """HttpClient wired to an in-memory cache and a temp snapshot dir. Mock transport with respx."""
    from meridian.core.http import HttpClient

    client = HttpClient(settings, memory_cache, snapshot_store)
    yield client
    await client.aclose()


def load_fixture(directory: Path, name: str) -> str:
    return (directory / "fixtures" / name).read_text(encoding="utf-8")
