"""TTL policy for reusable research memory, keyed by `MemoryItem.kind`."""

from __future__ import annotations

from datetime import datetime, timedelta

from meridian.core.ids import utcnow

# Kinds documented on `MemoryItem.kind`: "profile" | "financial_metrics" | "peer_set" | "research_summary".
TTL_BY_KIND: dict[str, timedelta] = {
    "profile": timedelta(days=30),
    "financial_metrics": timedelta(days=7),
    "peer_set": timedelta(days=30),
    "research_summary": timedelta(days=90),
}

DEFAULT_TTL = timedelta(days=7)


def ttl_for(kind: str) -> timedelta:
    """TTL for a memory kind; unknown kinds fall back to a conservative 7-day default."""
    return TTL_BY_KIND.get(kind, DEFAULT_TTL)


def compute_expiry(kind: str, *, now: datetime | None = None) -> datetime:
    return (now or utcnow()) + ttl_for(kind)


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    return (now or utcnow()) >= expires_at
