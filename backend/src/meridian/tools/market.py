"""Market data tool: get_market_quote."""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.schemas.financials import Quote
from meridian.tools.base import Tool, ToolContext


class GetMarketQuoteInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    history_days: int = Field(default=365, ge=1, le=3650)


class GetMarketQuoteOutput(BaseModel):
    quote: Quote
    evidence_ids: list[str]


class GetMarketQuoteTool(Tool[GetMarketQuoteInput, GetMarketQuoteOutput]):
    """Current price and price history for a ticker."""

    name = "get_market_quote"
    description = "Fetch a ticker's current price and daily price history."
    input_model = GetMarketQuoteInput

    async def run(self, args: GetMarketQuoteInput, ctx: ToolContext) -> GetMarketQuoteOutput:
        result = await ctx.providers.market.get_quote(args.ticker.upper(), args.history_days)
        ctx.ledger.absorb(result)
        return GetMarketQuoteOutput(quote=result.data, evidence_ids=[e.id for e in result.evidence])

    def summarize(self, output: GetMarketQuoteOutput) -> str:
        q = output.quote
        eid_str = f" [{output.evidence_ids[0]}]" if output.evidence_ids else ""
        return (
            f"{q.ticker} price = {q.price:,.2f} {q.currency} as of {q.as_of} ({len(q.history)} history points){eid_str}"
        )
