from __future__ import annotations

from typing import Protocol, runtime_checkable

from meridian.schemas.events import ProgressEvent


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, event: ProgressEvent) -> None: ...


class NullEventSink:
    async def emit(self, event: ProgressEvent) -> None:
        return None


class ListEventSink:
    """Collects events in memory (tests, CLI)."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def emit(self, event: ProgressEvent) -> None:
        event.seq = len(self.events) + 1
        self.events.append(event)
