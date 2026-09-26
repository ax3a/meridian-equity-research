"""Company specialist: business description, products, revenue sources, geography, competitive position.

Grounded entirely in `get_company_profile` and 10-K Item 1 text retrieved via `search_filings`. Both the
generative and offline paths only ever cite evidence ids that a tool actually returned.
"""

from __future__ import annotations

from typing import Any

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.agents.claims import describe_claim, is_quotable
from meridian.agents.retrieval import search_sections, unscoped_label
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

# (retrieval query, short label, 10-K section keys to search). The query is phrased for retrieval
# quality; the label is what a reader sees in front of the quoted passage, so it has to read like a
# report heading rather than a search box. The section keys keep the label honest: searching the whole
# filing for "products and services" once returned Walmart's litigation matters, which were then quoted
# under that heading as a fact. Item 1 is the business description; Item 7 (MD&A) is where revenue by
# market and competitive position are discussed.
_BUSINESS_QUERIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("business overview, products and services", "Products and services", ("1",)),
    ("revenue sources and geographic markets", "Revenue and markets", ("1", "7")),
    ("customers and competitive position", "Customers and competition", ("1", "7")),
)


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


def _clip(text: str, limit: int = 500) -> str:
    return " ".join(text.split())[:limit]


class CompanyAgent(BaseAgent):
    name = AgentName.COMPANY
    role = "Company Analyst"
    mission = (
        "Describe the company's business model: what it sells, who it sells to, where it operates, and how "
        "it is positioned against competitors, grounded in its own SEC filings and profile data."
    )
    allowed_tools = frozenset(
        {"resolve_company", "get_company_profile", "search_filings", "get_filing_section", "recall_research_memory"}
    )

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        state_updates: dict[str, Any] = {}

        if ticker is None:
            inv = await self.tool(ctx, "resolve_company", query=state.request.query)
            if inv.ok and inv.output is not None:
                ticker = inv.output.company.ticker
                state_updates["company"] = inv.output.company

        if ticker is None:
            return AgentDraft(summary="Could not resolve a company to research; no ticker or query available.")

        if self.generative:
            return await self._run_generative(task, ctx, ticker, state_updates)
        return await self._run_offline(ctx, ticker, state_updates)

    async def _run_offline(self, ctx: ToolContext, ticker: str, state_updates: dict[str, Any]) -> AgentDraft:
        findings = []
        summary_bits: list[str] = []

        profile_inv = await self.tool(ctx, "get_company_profile", ticker=ticker)
        if profile_inv.ok and profile_inv.output is not None:
            profile = profile_inv.output.profile
            evidence_ids = list(profile_inv.output.evidence_ids)
            identity = profile.identity
            overview = (
                f"{identity.name} ({identity.ticker}) is listed on {identity.exchange or 'an unspecified exchange'} "
                f"and classified under SIC {identity.sic or 'unknown'} ({identity.sic_description or 'unclassified'})."
            )
            findings.append(
                self.finding(
                    overview,
                    FindingKind.FACT,
                    ReportSection.COMPANY_OVERVIEW,
                    evidence_ids=evidence_ids,
                    confidence=Confidence.HIGH,
                )
            )
            if profile.description:
                findings.append(
                    self.finding(
                        _clip(profile.description, 1500),
                        FindingKind.FACT,
                        ReportSection.COMPANY_OVERVIEW,
                        evidence_ids=evidence_ids,
                    )
                )
            summary_bits.append(f"Profile retrieved for {identity.name}.")
        else:
            summary_bits.append(f"Company profile unavailable: {profile_inv.error}")

        topics_covered = 0
        seen_evidence: set[str] = set()
        for query, label, section_keys in _BUSINESS_QUERIES:
            passages, scoped = await search_sections(
                self, ctx, ticker=ticker, query=query, k=2, section_keys=section_keys
            )
            if not passages:
                continue
            topics_covered += 1
            # Outside the business sections the topical label would assert something the passage does
            # not support, so an unscoped result is quoted neutrally instead.
            claim_label = label if scoped else unscoped_label(label)
            for hit in passages[:2]:
                text = _clip(getattr(hit, "text", ""))
                evidence_id = getattr(hit, "evidence_id", "")
                # Retrieval queries overlap, so the same passage can answer several topics. Quoting it
                # once per topic pads the report with duplicates that say nothing new.
                if not text or not is_quotable(text) or evidence_id in seen_evidence:
                    continue
                seen_evidence.add(evidence_id)
                findings.append(
                    self.finding(
                        describe_claim(claim_label, text),
                        FindingKind.FACT,
                        ReportSection.BUSINESS_MODEL,
                        evidence_ids=[evidence_id],
                        confidence=Confidence.MEDIUM,
                    )
                )
        summary_bits.append(f"Reviewed Item 1 filing text across {topics_covered}/{len(_BUSINESS_QUERIES)} topics.")
        return AgentDraft(summary=" ".join(summary_bits), findings=findings, state_updates=state_updates)

    async def _run_generative(
        self, task: ResearchTask, ctx: ToolContext, ticker: str, state_updates: dict[str, Any]
    ) -> AgentDraft:
        context = {"ticker": ticker, "objective": task.objective, "instructions": task.instructions}
        answer = await self.llm_research(
            ctx,
            task=(
                f"Research {ticker}'s business model for the COMPANY_OVERVIEW and BUSINESS_MODEL sections: "
                "products/services, revenue sources, geography, customers and competitive position. Use the "
                "company profile and 10-K Item 1 text via the available tools. Cite every claim with real "
                "evidence ids returned by the tools you call; never invent an id."
            ),
            schema=AgentAnswer,
            context=context,
        )
        findings = self.to_findings(answer)
        return AgentDraft(summary=answer.summary, findings=findings, state_updates=state_updates)
