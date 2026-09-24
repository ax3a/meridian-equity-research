from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from meridian.schemas.api import UserPreferences


class MemoryItem(BaseModel):
    """Reusable research knowledge about a company, valid until `expires_at`."""

    ticker: str
    kind: str  # "profile" | "financial_metrics" | "peer_set" | "research_summary"
    payload: dict[str, Any]
    source_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime
    session_id: str | None = None


@runtime_checkable
class ResearchMemoryStore(Protocol):
    async def get(self, ticker: str, kind: str) -> MemoryItem | None:
        """Return the item only if not expired."""
        ...

    async def put(self, item: MemoryItem) -> None: ...

    async def history(self, ticker: str, limit: int = 5) -> list[MemoryItem]: ...


@runtime_checkable
class PreferenceStore(Protocol):
    async def get(self, user_id: str) -> UserPreferences: ...

    async def put(self, user_id: str, prefs: UserPreferences) -> None: ...
