"""The bull case agent: argues the strongest optimistic thesis from evidence already in state.

Only cites findings/evidence other agents already gathered, or anything it retrieves itself via its two
allowed tools (`lookup_evidence`, `search_filings`). It never introduces an uncited claim: whatever it
emits still passes through `BaseAgent.execute`'s citation validation like every other agent.
"""

from __future__ import annotations

from typing import Any, ClassVar

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.agents.claims import describe_claim
from meridian.agents.stance import bull_candidates, rank_by_stance
from meridian.core.config import LLMTier
from meridian.schemas.enums import AgentName, FindingKind, ReportSection
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext


def _candidate_dict(f: Finding) -> dict[str, Any]:
    return {
        "finding_id": f.id,
        "claim": f.claim,
        "kind": f.kind.value,
        "evidence_ids": f.evidence_ids,
        "metric_refs": f.metric_refs,
    }


class Bull(BaseAgent):
    name: ClassVar[AgentName] = AgentName.BULL
    role: ClassVar[str] = "Bull Case Agent"
    mission: ClassVar[str] = (
        "Builds the strongest evidence-based bull case for the company. Argues only from findings and "
        "evidence already gathered by other agents, or from evidence retrieved with lookup_evidence / "
        "search_filings. Never states a point it cannot cite."
    )
    tier: ClassVar[LLMTier] = "worker"
    allowed_tools: ClassVar[frozenset[str]] = frozenset({"lookup_evidence", "search_filings"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        candidates = bull_candidates(state)
        if self.generative:
            context = {"candidate_findings": [_candidate_dict(f) for f in candidates[:30]]}
            answer = await self.llm_research(
                ctx,
                task=(
                    "Build the bull case: the strongest reasons to be optimistic about this company. Every "
                    "point must cite a real evidence id or metric ref, either from the candidate findings "
                    "below or from evidence you retrieve with your tools. Do not state anything you cannot cite."
                ),
                schema=AgentAnswer,
                context=context,
            )
            return AgentDraft(summary=answer.summary, findings=self.to_findings(answer))
        return self._offline_draft(candidates, state)

    def _offline_draft(self, candidates: list[Finding], state: ResearchState) -> AgentDraft:
        picked = rank_by_stance(candidates, stance="bull", state=state)[:6]
        findings = [
            self.finding(
                describe_claim("Bull case", f.claim),
                FindingKind.INTERPRETATION,
                ReportSection.BULL_CASE,
                evidence_ids=f.evidence_ids,
                metric_refs=f.metric_refs,
                confidence=f.confidence,
                category="bull_point",
            )
            for f in picked
        ]
        summary = (
            f"Identified {len(findings)} bull case point(s) from existing research."
            if findings
            else "No supporting evidence was available to build a bull case."
        )
        return AgentDraft(summary=summary, findings=findings)
