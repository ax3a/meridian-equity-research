"""Research memory recall tool: recall_research_memory.

Lets an agent check for reusable prior research (a company profile, financial metrics, peer set or
research summary) before repeating provider calls the platform has already made, subject to the TTLs in
`meridian.memory.freshness`. When no memory store is configured for this run, always reports not-found
rather than failing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.memory.types import MemoryItem
from meridian.tools.base import Tool, ToolContext


class RecallResearchMemoryInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    kind: str


class RecallResearchMemoryOutput(BaseModel):
    found: bool
    item: MemoryItem | None = None


class RecallResearchMemoryTool(Tool[RecallResearchMemoryInput, RecallResearchMemoryOutput]):
    """Recall previously stored, still-fresh research memory for a ticker."""

    name = "recall_research_memory"
    description = (
        "Check for previously stored, still-fresh research about a company (kind: 'profile', "
        "'financial_metrics', 'peer_set', or 'research_summary') before re-deriving it from scratch."
    )
    input_model = RecallResearchMemoryInput

    async def run(self, args: RecallResearchMemoryInput, ctx: ToolContext) -> RecallResearchMemoryOutput:
        if ctx.memory is None:
            return RecallResearchMemoryOutput(found=False, item=None)
        item = await ctx.memory.get(args.ticker.upper(), args.kind)
        return RecallResearchMemoryOutput(found=item is not None, item=item)

    def summarize(self, output: RecallResearchMemoryOutput) -> str:
        if not output.found or output.item is None:
            return "no cached memory found"
        item = output.item
        return (
            f"cached {item.kind} for {item.ticker}, created {item.created_at.date()}, expires {item.expires_at.date()}"
        )
