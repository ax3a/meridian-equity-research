"""News specialist: recent developments from public news and SEC 8-K events.

8-K items and the existence of a headline are FACT; any read-through about what coverage implies is
INTERPRETATION and is only ever produced with real supporting evidence ids.
"""

from __future__ import annotations

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


class NewsAgent(BaseAgent):
    name = AgentName.NEWS
    role = "News Analyst"
    mission = (
        "Surface the company's recent developments from public news and SEC 8-K filings, keeping factual "
        "reporting separate from any interpretation of what the coverage means."
    )
    allowed_tools = frozenset({"search_news", "get_recent_8k_events"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        if ticker is None:
            return AgentDraft(summary="No resolved ticker; cannot search news.")

        if self.generative:
            return await self._run_generative(task, ctx, ticker)
        return await self._run_offline(ctx, ticker)

    async def _run_offline(self, ctx: ToolContext, ticker: str) -> AgentDraft:
        findings: list[Finding] = []

        events_inv = await self.tool(ctx, "get_recent_8k_events", ticker=ticker, limit=10)
        if events_inv.ok and events_inv.output is not None:
            for event in list(events_inv.output.events)[:10]:
                evidence_id = getattr(event, "evidence_id", "")
                if not evidence_id:
                    continue
                items = ", ".join(getattr(event, "items", []) or [])
                description = getattr(event, "description", "") or "Material event disclosed."
                filed = getattr(event, "filed", None) or getattr(event, "filing_date", None)
                findings.append(
                    self.finding(
                        f"Filed 8-K (item(s) {items or 'n/a'}) on {filed}: {description[:400]}",
                        FindingKind.FACT,
                        ReportSection.RECENT_DEVELOPMENTS,
                        evidence_ids=[evidence_id],
                        confidence=Confidence.HIGH,
                    )
                )

        news_evidence_ids: list[str] = []
        article_count = 0
        news_inv = await self.tool(ctx, "search_news", ticker=ticker, days=90, limit=20)
        if news_inv.ok and news_inv.output is not None:
            articles = list(news_inv.output.articles)
            news_evidence_ids = list(news_inv.output.evidence_ids)
            article_count = len(articles)
            same_length = len(articles) == len(news_evidence_ids)
            paired = list(zip(articles, news_evidence_ids, strict=True)) if same_length else []
            for article, evidence_id in paired:
                findings.append(
                    self.finding(
                        f'{article.publisher} reported: "{article.title}"'
                        f"{f' ({article.published_at})' if article.published_at else ''}.",
                        FindingKind.FACT,
                        ReportSection.RECENT_DEVELOPMENTS,
                        evidence_ids=[evidence_id],
                        confidence=Confidence.MEDIUM,
                    )
                )
            if article_count and not paired:
                # Tool didn't align 1:1 with per-article ids -- still cite the batch of ids that back the count.
                findings.append(
                    self.finding(
                        f"{article_count} news articles about {ticker} were published in the last 90 days.",
                        FindingKind.FACT,
                        ReportSection.RECENT_DEVELOPMENTS,
                        evidence_ids=news_evidence_ids[:10],
                        confidence=Confidence.MEDIUM,
                    )
                )
            if article_count:
                findings.append(
                    self.finding(
                        f"Media coverage volume ({article_count} articles in 90 days) suggests "
                        f"{'elevated' if article_count >= 10 else 'routine'} investor and press attention to {ticker}.",
                        FindingKind.INTERPRETATION,
                        ReportSection.RECENT_DEVELOPMENTS,
                        evidence_ids=news_evidence_ids[:10],
                        confidence=Confidence.LOW,
                    )
                )

        summary = f"Reviewed 8-K events and {article_count} recent news articles for {ticker}."
        return AgentDraft(summary=summary, findings=findings)

    async def _run_generative(self, task: ResearchTask, ctx: ToolContext, ticker: str) -> AgentDraft:
        context = {"ticker": ticker, "objective": task.objective}
        answer = await self.llm_research(
            ctx,
            task=(
                f"Report {ticker}'s recent developments (RECENT_DEVELOPMENTS section) from search_news and "
                "get_recent_8k_events. Label 8-K items and the existence of a headline as kind=fact; label any "
                "read-through about what the coverage implies as kind=interpretation with lower confidence. "
                "Cite only evidence ids a tool actually returned; never invent one."
            ),
            schema=AgentAnswer,
            context=context,
        )
        findings = self.to_findings(answer)
        return AgentDraft(summary=answer.summary, findings=findings)
