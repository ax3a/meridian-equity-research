from __future__ import annotations

from datetime import UTC, datetime, timedelta

from meridian.memory.types import MemoryItem
from meridian.tools.memory import RecallResearchMemoryInput, RecallResearchMemoryTool


class FakeMemoryStore:
    def __init__(self, items: dict[tuple[str, str], MemoryItem] | None = None) -> None:
        self.items = items or {}

    async def get(self, ticker: str, kind: str) -> MemoryItem | None:
        return self.items.get((ticker, kind))

    async def put(self, item: MemoryItem) -> None:
        self.items[(item.ticker, item.kind)] = item

    async def history(self, ticker: str, limit: int = 5) -> list[MemoryItem]:
        return [v for (t, _), v in self.items.items() if t == ticker][:limit]


async def test_recall_research_memory_no_store_returns_not_found(make_ctx):
    ctx = make_ctx(memory=None)
    output = await RecallResearchMemoryTool().run(RecallResearchMemoryInput(ticker="MSFT", kind="profile"), ctx)
    assert output.found is False
    assert output.item is None
    assert RecallResearchMemoryTool().summarize(output) == "no cached memory found"


async def test_recall_research_memory_hit(make_ctx):
    now = datetime.now(UTC)
    item = MemoryItem(
        ticker="MSFT", kind="profile", payload={"sic": "7372"}, created_at=now, expires_at=now + timedelta(days=30)
    )
    store = FakeMemoryStore({("MSFT", "profile"): item})
    ctx = make_ctx(memory=store)
    output = await RecallResearchMemoryTool().run(RecallResearchMemoryInput(ticker="msft", kind="profile"), ctx)
    assert output.found is True
    assert output.item is not None
    assert output.item.payload == {"sic": "7372"}


async def test_recall_research_memory_miss(make_ctx):
    store = FakeMemoryStore()
    ctx = make_ctx(memory=store)
    output = await RecallResearchMemoryTool().run(RecallResearchMemoryInput(ticker="MSFT", kind="peer_set"), ctx)
    assert output.found is False
