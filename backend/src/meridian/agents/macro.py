"""Macro specialist: only asserts a macro link when filing evidence actually shows exposure.

When nothing material is found, that absence is the valid result: a clear summary and zero findings,
not a failure. Never invents an exposure that the filings don't support.
"""

from __future__ import annotations

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.providers.base import MacroIndicator
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

_MACRO_QUERY = "macroeconomic conditions: interest rates, inflation, tariffs, foreign currency exposure"

_KEYWORD_INDICATORS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("interest rate", "treasury", "borrowing cost"), ("ust_10y", "ust_3m", "fed_funds")),
    (("inflation", "cpi", "consumer price"), ("cpi_yoy",)),
    (("tariff", "trade", "import", "export"), ()),
    (("currency", "foreign exchange", "fx "), ()),
)


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


def _clip(text: str, limit: int = 500) -> str:
    return " ".join(text.split())[:limit]


def _match_indicator(text: str, indicators: list[MacroIndicator]) -> MacroIndicator | None:
    lowered = text.lower()
    for keywords, indicator_keys in _KEYWORD_INDICATORS:
        if any(kw in lowered for kw in keywords):
            for ind in indicators:
                if ind.key in indicator_keys:
                    return ind
    return indicators[0] if indicators else None


class MacroAgent(BaseAgent):
    name = AgentName.MACRO
    role = "Macro Analyst"
    mission = (
        "Determine whether macroeconomic conditions -- rates, inflation, trade, currency -- are material to "
        "this company, using its own filing language as the only basis for asserting a link. Absence of a "
        "material link is a valid, valuable conclusion."
    )
    allowed_tools = frozenset({"get_macro_indicators", "search_filings"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        if ticker is None:
            return AgentDraft(summary="No resolved ticker; cannot assess macro exposure.")

        if self.generative:
            return await self._run_generative(task, ctx, ticker)
        return await self._run_offline(ctx, ticker)

    async def _run_offline(self, ctx: ToolContext, ticker: str) -> AgentDraft:
        indicators_inv = await self.tool(ctx, "get_macro_indicators", keys=None)
        indicators_ok = indicators_inv.ok and indicators_inv.output is not None
        indicators = list(indicators_inv.output.indicators) if indicators_ok else []
        macro_evidence_ids = list(indicators_inv.output.evidence_ids) if indicators_ok else []

        passages_inv = await self.tool(ctx, "search_filings", ticker=ticker, query=_MACRO_QUERY, k=5)
        passages = list(passages_inv.output.passages) if passages_inv.ok and passages_inv.output else []

        if not passages:
            return AgentDraft(
                summary=(
                    f"No material macro exposure found in {ticker}'s filings: a targeted search for interest "
                    "rate, inflation, tariff and currency language returned no supporting passages. Macro "
                    "indicators were reviewed but not linked to any filing-evidenced exposure."
                ),
                findings=[],
            )

        findings = []
        for hit in passages[:3]:
            text = _clip(getattr(hit, "text", ""))
            if not text:
                continue
            passage_evidence_id = getattr(hit, "evidence_id", "")
            indicator = _match_indicator(text, indicators)
            evidence_ids = [passage_evidence_id] if passage_evidence_id else []
            claim = f"Filing language indicates macro exposure: {text}"
            if indicator is not None and indicator.latest is not None:
                # `as_of` is optional on the model, so the fallback has to survive a real None rather
                # than rely on a getattr default that only fires when the attribute is absent.
                as_of = indicator.as_of.isoformat() if indicator.as_of else "an unknown date"
                claim += f" (latest {indicator.label}: {indicator.latest}{indicator.unit} as of {as_of})."
                evidence_ids += macro_evidence_ids[:2]
            findings.append(
                self.finding(
                    claim,
                    FindingKind.INTERPRETATION,
                    ReportSection.MACRO,
                    evidence_ids=evidence_ids,
                    confidence=Confidence.MEDIUM,
                )
            )

        summary = f"Identified {len(findings)} filing-evidenced macro exposure point(s) for {ticker}."
        return AgentDraft(summary=summary, findings=findings)

    async def _run_generative(self, task: ResearchTask, ctx: ToolContext, ticker: str) -> AgentDraft:
        context = {"ticker": ticker, "objective": task.objective}
        answer = await self.llm_research(
            ctx,
            task=(
                f"Assess whether macro conditions (rates, inflation, tariffs, FX) are material to {ticker}. "
                "Only assert a macro link when 10-K/10-Q filing text via search_filings actually discusses "
                "that exposure, and cite that passage's evidence id plus, where relevant, a macro indicator's "
                "evidence id from get_macro_indicators. If you find no material exposure, say so explicitly in "
                "your summary and return zero findings -- that is a valid and expected result, not a failure."
            ),
            schema=AgentAnswer,
            context=context,
        )
        findings = self.to_findings(answer)
        return AgentDraft(summary=answer.summary, findings=findings)
