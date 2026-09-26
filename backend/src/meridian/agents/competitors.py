"""Competitors specialist: peer selection and industry comparison.

In generative mode the model may propose additional peers by ticker with a reason; every proposal is
validated by actually resolving a snapshot for it (`get_peer_snapshot`) before it counts, and the peer set
is capped at 5. Always sets `state_updates["peers"]`.
"""

from __future__ import annotations

import contextlib
import statistics
from typing import Any

from pydantic import BaseModel, Field

from meridian.agents.base import AgentAnswer, AgentDraft, BaseAgent
from meridian.schemas.analysis import PeerComparison
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection
from meridian.schemas.findings import Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

_MAX_PEERS = 5
_COMPARISON_FIELDS: tuple[tuple[str, str], ...] = (
    ("revenue_growth", "revenue growth"),
    ("gross_margin", "gross margin"),
    ("operating_margin", "operating margin"),
    ("net_margin", "net margin"),
)


def _resolved_ticker(state: ResearchState) -> str | None:
    if state.company:
        return state.company.ticker
    ticker = (state.request.ticker or "").strip().upper()
    return ticker or None


class ProposedPeer(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    reason: str = Field(min_length=3, max_length=300)


class CompetitorsAnswer(AgentAnswer):
    proposed_peers: list[ProposedPeer] = Field(default_factory=list, max_length=5)


def _peer_medians(peers: list) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for field_name, _ in _COMPARISON_FIELDS:
        values = [getattr(p, field_name) for p in peers if getattr(p, field_name) is not None]
        out[field_name] = statistics.median(values) if values else None
    return out


# A peer snapshot carries an evidence id for every line item it fetched. Attaching all of them to one
# sentence produced claims trailing twenty markers, which drowns the text and helps nobody verify
# anything. Cite a few representative ids; the Sources tab lists the rest.
_MAX_CITATIONS_PER_CLAIM = 3


def _cite(*groups: list[str], limit: int = _MAX_CITATIONS_PER_CLAIM) -> list[str]:
    seen: list[str] = []
    for group in groups:
        for eid in group:
            if eid and eid not in seen:
                seen.append(eid)
    return seen[:limit]


def _offline_findings(agent: CompetitorsAgent, target, peers: list) -> list[Finding]:
    findings: list[Finding] = []
    if not peers:
        return findings

    for peer in peers:
        if peer.revenue is not None:
            findings.append(
                agent.finding(
                    f"{peer.company.name} ({peer.company.ticker}) reported revenue of ${peer.revenue:,.0f} for "
                    f"{peer.fiscal_period or 'its most recent period'}.",
                    FindingKind.FACT,
                    ReportSection.INDUSTRY_COMPETITION,
                    evidence_ids=_cite(list(peer.evidence_ids)),
                    confidence=Confidence.MEDIUM,
                )
            )

    if target is None:
        return findings

    medians = _peer_medians(peers)
    for field_name, label in _COMPARISON_FIELDS:
        median = medians.get(field_name)
        target_value = getattr(target, field_name)
        if median is None or target_value is None:
            continue
        evidence_ids = _cite(list(target.evidence_ids), [e for p in peers for e in p.evidence_ids], limit=4)
        findings.append(
            agent.finding(
                f"{target.company.ticker}'s {label} of {target_value:.1%} compares to a peer median of {median:.1%} "
                f"across {len(peers)} peers.",
                FindingKind.INTERPRETATION,
                ReportSection.INDUSTRY_COMPETITION,
                evidence_ids=evidence_ids,
                confidence=Confidence.MEDIUM,
            )
        )
    return findings


class CompetitorsAgent(BaseAgent):
    name = AgentName.COMPETITORS
    role = "Competitive Analyst"
    mission = (
        "Identify the company's closest peers and compare it against them on growth and margins, using only "
        "peer data actually returned by the peer-snapshot tool."
    )
    allowed_tools = frozenset({"find_peer_candidates", "get_peer_snapshot", "search_filings"})

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:
        ticker = _resolved_ticker(state)
        if ticker is None:
            return AgentDraft(summary="No resolved ticker; cannot select peers.")

        candidates_inv = await self.tool(ctx, "find_peer_candidates", ticker=ticker, limit=8)
        candidates = list(candidates_inv.output.candidates) if candidates_inv.ok and candidates_inv.output else []

        answer: CompetitorsAnswer | None = None
        if self.generative:
            answer = await self._propose_peers(task, ctx, ticker, candidates)

        selected_tickers: list[str] = []
        peer_snapshots: list[Any] = []

        async def add_peer(pt: str, reason: str) -> None:
            pt = pt.strip().upper()
            if len(selected_tickers) >= _MAX_PEERS or pt == ticker or pt in selected_tickers:
                return
            snap_inv = await self.tool(ctx, "get_peer_snapshot", ticker=pt, is_target=False)
            if not snap_inv.ok or snap_inv.output is None:
                return  # invalid/unresolvable ticker -- silently dropped, never fabricated
            snap = snap_inv.output
            if reason:
                with contextlib.suppress(AttributeError):
                    snap = snap.model_copy(update={"selection_reason": reason})
            selected_tickers.append(pt)
            peer_snapshots.append(snap)

        if answer is not None:
            for p in answer.proposed_peers:
                await add_peer(p.ticker, p.reason)
        for cand in candidates:
            await add_peer(cand.company.ticker, cand.reason)

        target_inv = await self.tool(ctx, "get_peer_snapshot", ticker=ticker, is_target=True)
        target_snapshot = target_inv.output if target_inv.ok else None

        comparison = PeerComparison(
            target_ticker=ticker,
            selection_method="SIC peer universe reviewed by the LLM" if self.generative else "SIC peer universe",
            peers=([target_snapshot] if target_snapshot else []) + peer_snapshots,
        )
        state_updates: dict[str, Any] = {"peers": comparison}

        if answer is not None:
            findings = self.to_findings(answer)
            summary = answer.summary
        else:
            findings = _offline_findings(self, target_snapshot, peer_snapshots)
            summary = f"Compared {ticker} against {len(peer_snapshots)} peers ({comparison.selection_method})."

        return AgentDraft(
            summary=summary, findings=findings, data={"peer_count": len(peer_snapshots)}, state_updates=state_updates
        )

    async def _propose_peers(
        self, task: ResearchTask, ctx: ToolContext, ticker: str, candidates: list
    ) -> CompetitorsAnswer:
        context = {
            "ticker": ticker,
            "candidate_peers": [
                {"ticker": c.company.ticker, "reason": c.reason, "revenue": c.revenue} for c in candidates
            ],
        }
        return await self.llm_research(
            ctx,
            task=(
                f"Select up to {_MAX_PEERS} peers for {ticker}, preferring candidate_peers but you may propose "
                "a different ticker with a reason in proposed_peers if you believe it is a materially better "
                "comparator -- every proposal is independently validated before use, so an unresolvable ticker "
                "is simply dropped. Use search_filings/get_peer_snapshot to support INDUSTRY_COMPETITION "
                "findings. Cite every finding with real evidence ids the tools actually returned; never invent "
                "an id."
            ),
            schema=CompetitorsAnswer,
            context=context,
        )
