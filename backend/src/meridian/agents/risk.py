"""Risk specialist: one finding per risk category, each tied to real filing evidence or a computed metric.

Debt and liquidity risk prefer a leverage/liquidity metric already in `state.metrics` (computed by the
financials agent); every other category needs a real filing passage. A category with no support is simply
skipped -- never fabricated.
"""

from __future__ import annotations

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.agents.claims import describe_claim
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection, RiskCategory
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

_FILING_RISK_QUERIES: dict[RiskCategory, str] = {
    RiskCategory.FINANCIAL: "financial condition and earnings volatility risk",
    RiskCategory.COMPETITIVE: "competitive pressures and market share risk",
    RiskCategory.REGULATORY: "regulatory, legal and compliance risk",
    RiskCategory.OPERATIONAL: "operational disruption and supply chain risk",
    RiskCategory.CONCENTRATION: "customer or supplier concentration risk",
    RiskCategory.GEOPOLITICAL: "geopolitical and international trade risk",
    RiskCategory.TECHNOLOGY: "technology change, cybersecurity and IP risk",
    RiskCategory.VALUATION: "stock price volatility and valuation risk",
}


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


def _clip(text: str, limit: int = 500) -> str:
    return " ".join(text.split())[:limit]


class RiskAgent(BaseAgent):
    name = AgentName.RISK
    role = "Risk Analyst"
    mission = (
        "Identify the company's most material risks by category, tying every risk to real filing evidence "
        "or, for leverage and liquidity, to a metric the financial engine already computed."
    )
    allowed_tools = frozenset({"search_filings", "get_filing_section", "calculate_metric"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        if ticker is None:
            return AgentDraft(summary="No resolved ticker; cannot assess risk.")

        if self.generative:
            return await self._run_generative(task, ctx, ticker)
        return await self._run_offline(ctx, ticker, state)

    async def _run_offline(self, ctx: ToolContext, ticker: str, state: ResearchState) -> AgentDraft:
        findings: list[Finding] = []
        metrics = state.metrics

        if metrics is not None and metrics.periods:
            for period in reversed(metrics.periods):
                dte = metrics.get(period, "debt_to_equity")
                if dte is not None and dte.value is not None:
                    findings.append(
                        self.finding(
                            f"Debt-to-equity is {dte.value:.2f}x as of {period}, a key leverage risk indicator.",
                            FindingKind.CALCULATED,
                            ReportSection.KEY_RISKS,
                            metric_refs=[dte.ref],
                            category=RiskCategory.DEBT.value,
                            confidence=Confidence.MEDIUM,
                        )
                    )
                    break
            for period in reversed(metrics.periods):
                cr = metrics.get(period, "current_ratio")
                if cr is not None and cr.value is not None:
                    findings.append(
                        self.finding(
                            f"Current ratio is {cr.value:.2f} as of {period}, a key liquidity risk indicator.",
                            FindingKind.CALCULATED,
                            ReportSection.KEY_RISKS,
                            metric_refs=[cr.ref],
                            category=RiskCategory.LIQUIDITY.value,
                            confidence=Confidence.MEDIUM,
                        )
                    )
                    break

        for category, query in _FILING_RISK_QUERIES.items():
            inv = await self.tool(ctx, "search_filings", ticker=ticker, query=query, k=2)
            if not inv.ok or inv.output is None or not inv.output.passages:
                continue
            hit = inv.output.passages[0]
            text = _clip(getattr(hit, "text", ""))
            evidence_id = getattr(hit, "evidence_id", "")
            if not text or not evidence_id:
                continue
            # Prefix with the category so the same passage matching two category queries never collides
            # as a "duplicate claim" during citation validation (which dedups on claim text alone).
            findings.append(
                self.finding(
                    describe_claim(category.value, text),
                    FindingKind.FACT,
                    ReportSection.KEY_RISKS,
                    evidence_ids=[evidence_id],
                    category=category.value,
                    confidence=Confidence.MEDIUM,
                )
            )

        categories_covered = len({f.category for f in findings if f.category})
        summary = f"Identified {len(findings)} evidenced risk(s) across {categories_covered} categories for {ticker}."
        return AgentDraft(summary=summary, findings=findings)

    async def _run_generative(self, task: ResearchTask, ctx: ToolContext, ticker: str) -> AgentDraft:
        categories = ", ".join(c.value for c in RiskCategory)
        answer = await self.llm_research(
            ctx,
            task=(
                f"Identify {ticker}'s material risks (KEY_RISKS section). Produce at most one finding per "
                f"risk category ({categories}) and only when you have real support: filing text via "
                "search_filings/get_filing_section for most categories, or a computed leverage/liquidity "
                "metric via calculate_metric for debt and liquidity risk. Set each finding's category field "
                "to the matching value. Skip a category rather than inventing a risk you cannot support."
            ),
            schema=AgentAnswer,
            context={"ticker": ticker, "objective": task.objective},
        )
        findings = self.to_findings(answer)
        return AgentDraft(summary=answer.summary, findings=findings)
