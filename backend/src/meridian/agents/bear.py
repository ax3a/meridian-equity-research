"""The bear case agent: argues the strongest skeptical thesis from evidence already in state.

Mirrors `bull.py`: only cites findings/evidence other agents already gathered, or anything it retrieves via
its two allowed tools. It never introduces an uncited claim.
"""

from __future__ import annotations

from typing import Any, ClassVar

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.core.config import LLMTier
from meridian.schemas.enums import AgentName, FindingKind, ReportSection
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

_NEGATIVE_HINTS = (
    "decline",
    "decrease",
    "risk",
    "debt",
    "weak",
    "miss",
    "pressure",
    "competition",
    "regulatory",
    "litigation",
    "exposure",
    "loss",
    "contract",
    "slow",
    "headwind",
)


def _rank(findings: list[Finding], hints: tuple[str, ...]) -> list[Finding]:
    def score(f: Finding) -> int:
        text = f.claim.lower()
        return sum(text.count(h) for h in hints)

    return sorted(findings, key=score, reverse=True)


def _candidate_dict(f: Finding) -> dict[str, Any]:
    return {
        "finding_id": f.id,
        "claim": f.claim,
        "kind": f.kind.value,
        "evidence_ids": f.evidence_ids,
        "metric_refs": f.metric_refs,
    }


class Bear(BaseAgent):
    name: ClassVar[AgentName] = AgentName.BEAR
    role: ClassVar[str] = "Bear Case Agent"
    mission: ClassVar[str] = (
        "Builds the strongest evidence-based bear case for the company. Argues only from findings and "
        "evidence already gathered by other agents, or from evidence retrieved with lookup_evidence / "
        "search_filings. Never states a point it cannot cite."
    )
    tier: ClassVar[LLMTier] = "worker"
    allowed_tools: ClassVar[frozenset[str]] = frozenset({"lookup_evidence", "search_filings"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        candidates = [
            f
            for f in state.findings()
            if f.agent not in (AgentName.BULL, AgentName.BEAR) and (f.evidence_ids or f.metric_refs)
        ]
        if self.generative:
            context = {"candidate_findings": [_candidate_dict(f) for f in candidates[:30]]}
            answer = await self.llm_research(
                ctx,
                task=(
                    "Build the bear case: the strongest reasons to be skeptical about this company. Every "
                    "point must cite a real evidence id or metric ref, either from the candidate findings "
                    "below or from evidence you retrieve with your tools. Do not state anything you cannot cite."
                ),
                schema=AgentAnswer,
                context=context,
            )
            return AgentDraft(summary=answer.summary, findings=self.to_findings(answer))
        return self._offline_draft(candidates)

    def _offline_draft(self, candidates: list[Finding]) -> AgentDraft:
        picked = _rank(candidates, _NEGATIVE_HINTS)[:6]
        findings = [
            self.finding(
                f"Bear case: {f.claim}",
                FindingKind.INTERPRETATION,
                ReportSection.BEAR_CASE,
                evidence_ids=f.evidence_ids,
                metric_refs=f.metric_refs,
                confidence=f.confidence,
                category="bear_point",
            )
            for f in picked
        ]
        summary = (
            f"Identified {len(findings)} bear case point(s) from existing research."
            if findings
            else "No supporting evidence was available to build a bear case."
        )
        return AgentDraft(summary=summary, findings=findings)
