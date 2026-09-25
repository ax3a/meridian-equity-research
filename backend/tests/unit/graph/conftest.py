"""Pytest fixtures for the graph tests.

Reusable fakes live in `graph_fakes.py`: a module named `conftest` is importable at top level, so two
sibling test packages that both ship one collide on import. Importing helpers from a uniquely named
module avoids that.
"""

from __future__ import annotations

import pytest

from meridian.core.config import Settings
from meridian.observability.events import ListEventSink


@pytest.fixture
def graph_settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        redis_url=None,
        llm_provider="offline",
        data_mode="live",
        snapshot_dir=tmp_path / "snapshots",
        model_cache_dir=tmp_path / "models",
        embedding_provider="hashing",
        sec_user_agent="Meridian Test test@example.com",
        max_revision_rounds=2,
        max_supervisor_loops=2,
        agent_timeout_seconds=5.0,
        graph_recursion_limit=100,
    )


@pytest.fixture
def graph_events() -> ListEventSink:
    return ListEventSink()
