from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    """Deterministic id from content, used so identical sources/evidence dedupe across agents."""
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]}"


def utcnow() -> datetime:
    return datetime.now(UTC)
