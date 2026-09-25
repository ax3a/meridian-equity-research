"""News tool: search_news.

A headline is evidence that something was *reported*, not evidence the underlying claim is true --
`NewsArticle.reliability` and `Source.metadata["evidence_type"] = "headline"` (set by the news providers)
carry that distinction through to the report writer/critic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.providers.base import NewsArticle
from meridian.tools.base import Tool, ToolContext


class SearchNewsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    days: int = Field(default=90, ge=1, le=730)
    limit: int = Field(default=20, ge=1, le=100)


class SearchNewsOutput(BaseModel):
    articles: list[NewsArticle]
    evidence_ids: list[str]


class SearchNewsTool(Tool[SearchNewsInput, SearchNewsOutput]):
    """Recent news coverage for a company, ranked by outlet reliability then recency."""

    name = "search_news"
    description = (
        "Search recent news coverage for a company, ranked by source reliability (primary/tier1/tier2) "
        "then recency. Headlines are evidence of reporting, not of the underlying fact."
    )
    input_model = SearchNewsInput

    async def run(self, args: SearchNewsInput, ctx: ToolContext) -> SearchNewsOutput:
        identity = await ctx.providers.directory.resolve(args.ticker)
        result = await ctx.providers.news.search_news(identity, args.days, args.limit)
        ctx.ledger.absorb(result)
        return SearchNewsOutput(articles=result.data, evidence_ids=[e.id for e in result.evidence])

    def summarize(self, output: SearchNewsOutput) -> str:
        lines = []
        for article, eid in zip(output.articles, output.evidence_ids, strict=False):
            lines.append(
                f"{article.publisher} ({article.published_at}) [{article.reliability}]: {article.title} [{eid}]"
            )
        return "\n".join(lines)[:6000]
