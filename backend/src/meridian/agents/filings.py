"""Filings specialist: MD&A, segments, guidance, accounting changes, risk factors and material events.

Reads 10-K/10-Q/8-K content through the RAG-backed filing tools; every finding cites the passage or event
evidence id a tool actually returned.
"""

from __future__ import annotations

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.agents.claims import describe_claim, is_quotable
from meridian.agents.retrieval import search_sections, unscoped_label
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

# (retrieval query, report section, short label used when quoting the passage as a claim, 10-K section
# keys to search). The query is written for retrieval quality; the label is written to read well in a
# report sentence. The section keys stop the label from asserting more than the evidence shows -- an
# unscoped search for segment disclosure once returned a reputation risk factor, which was then quoted
# under that heading. Outlook lives in MD&A; subsequent events live in the financial statement notes
# (8-K material events are collected separately by `get_recent_8k_events`).
_QUERIES: tuple[tuple[str, ReportSection, str, tuple[str, ...]], ...] = (
    (
        "management discussion and analysis of results of operations",
        ReportSection.FINANCIAL_PERFORMANCE,
        "MD&A",
        ("7",),
    ),
    (
        "business segments and revenue disaggregation",
        ReportSection.FINANCIAL_PERFORMANCE,
        "Segment disclosure",
        ("7", "8"),
    ),
    ("risk factors", ReportSection.KEY_RISKS, "Risk factor", ("1A",)),
    ("forward-looking guidance and outlook", ReportSection.RECENT_DEVELOPMENTS, "Guidance", ("7",)),
    (
        "changes in accounting policies or critical estimates",
        ReportSection.RECENT_DEVELOPMENTS,
        "Accounting policy",
        ("7", "8"),
    ),
    ("material events and subsequent events", ReportSection.RECENT_DEVELOPMENTS, "Material event", ("8",)),
)


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


def _clip(text: str, limit: int = 500) -> str:
    return " ".join(text.split())[:limit]


class FilingsAgent(BaseAgent):
    name = AgentName.FILINGS
    role = "Filings Analyst"
    mission = (
        "Extract what the company's own SEC filings say about its results, risks, segments, guidance, "
        "accounting changes and material events, citing the exact passage or event behind every claim."
    )
    allowed_tools = frozenset(
        {"list_filings", "index_filings", "search_filings", "get_filing_section", "get_recent_8k_events"}
    )

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        if ticker is None:
            return AgentDraft(summary="No resolved ticker; cannot read filings.")

        if self.generative:
            return await self._run_generative(task, ctx, ticker)
        return await self._run_offline(ctx, ticker)

    async def _run_offline(self, ctx: ToolContext, ticker: str) -> AgentDraft:
        findings: list[Finding] = []
        queries_hit = 0

        await self.tool(ctx, "list_filings", ticker=ticker, forms=["10-K", "10-Q", "8-K"], limit=12)
        await self.tool(ctx, "index_filings", ticker=ticker, forms=["10-K", "10-Q"], limit=3)

        # Scoped per section: one passage may legitimately answer queries feeding different sections,
        # but quoting it twice under one section says nothing new.
        seen_by_section: dict[ReportSection, set[str]] = {}
        for query, section, label, section_keys in _QUERIES:
            seen_evidence = seen_by_section.setdefault(section, set())
            passages, scoped = await search_sections(
                self, ctx, ticker=ticker, query=query, k=2, section_keys=section_keys
            )
            if not passages:
                continue
            queries_hit += 1
            # An unscoped hit cannot be claimed to come from the section the query targeted.
            claim_label = label if scoped else unscoped_label(label)
            for hit in passages[:2]:
                text = _clip(getattr(hit, "text", ""))
                evidence_id = getattr(hit, "evidence_id", "")
                # Queries overlap; quoting one passage under several headings pads the report.
                if not text or not is_quotable(text) or evidence_id in seen_evidence:
                    continue
                seen_evidence.add(evidence_id)
                # Prefix with the topic so the same passage surfaced for two different queries never
                # collides as a "duplicate claim" during citation validation (which dedups on claim text).
                findings.append(
                    self.finding(
                        describe_claim(claim_label, text),
                        FindingKind.FACT,
                        section,
                        evidence_ids=[evidence_id],
                        confidence=Confidence.MEDIUM,
                    )
                )

        events_inv = await self.tool(ctx, "get_recent_8k_events", ticker=ticker, limit=10)
        if events_inv.ok and events_inv.output is not None:
            for event in list(events_inv.output.events)[:10]:
                items = ", ".join(getattr(event, "items", []) or [])
                description = getattr(event, "description", "") or "Material event disclosed."
                filed = getattr(event, "filed", None) or getattr(event, "filing_date", None)
                claim = describe_claim(f"Filed 8-K (item(s) {items or 'n/a'}) on {filed}", description)
                evidence_id = getattr(event, "evidence_id", "")
                if not evidence_id:
                    continue
                findings.append(
                    self.finding(
                        claim,
                        FindingKind.FACT,
                        ReportSection.RECENT_DEVELOPMENTS,
                        evidence_ids=[evidence_id],
                        confidence=Confidence.HIGH,
                    )
                )

        summary = f"Reviewed filings for {ticker}: {queries_hit}/{len(_QUERIES)} topic queries returned evidence."
        return AgentDraft(summary=summary, findings=findings)

    async def _run_generative(self, task: ResearchTask, ctx: ToolContext, ticker: str) -> AgentDraft:
        context = {"ticker": ticker, "objective": task.objective, "instructions": task.instructions}
        answer = await self.llm_research(
            ctx,
            task=(
                f"Review {ticker}'s recent 10-K/10-Q/8-K filings. Cover MD&A results, business segments, "
                "risk factors, forward guidance, accounting changes and material events, placing findings in "
                "FINANCIAL_PERFORMANCE, KEY_RISKS or RECENT_DEVELOPMENTS as appropriate. Use list_filings and "
                "index_filings first if nothing is indexed yet, then search_filings/get_filing_section for "
                "text and get_recent_8k_events for events. Cite only evidence ids a tool actually returned."
            ),
            schema=AgentAnswer,
            context=context,
        )
        findings = self.to_findings(answer)
        return AgentDraft(summary=answer.summary, findings=findings)
