"""Peer discovery and comparison tools: find_peer_candidates, get_peer_snapshot."""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.core.errors import MeridianError
from meridian.financial_engine import compute_metrics
from meridian.providers.base import PeerCandidate
from meridian.schemas.analysis import PeerSnapshot
from meridian.schemas.financials import FinancialMetrics
from meridian.tools._util import fmt_num, fmt_pct, metric_evidence_ids, resolve_identity_with_profile
from meridian.tools.base import Tool, ToolContext


class FindPeerCandidatesInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    limit: int = Field(default=8, ge=1, le=30)


class FindPeerCandidatesOutput(BaseModel):
    candidates: list[PeerCandidate]


class FindPeerCandidatesTool(Tool[FindPeerCandidatesInput, FindPeerCandidatesOutput]):
    """Candidate peer companies in the same industry (SIC code), ranked by revenue."""

    name = "find_peer_candidates"
    description = "Find candidate peer companies in the same industry (same SIC code), ranked by revenue."
    input_model = FindPeerCandidatesInput

    async def run(self, args: FindPeerCandidatesInput, ctx: ToolContext) -> FindPeerCandidatesOutput:
        identity = await resolve_identity_with_profile(ctx, args.ticker)
        result = await ctx.providers.peers.candidate_peers(identity, args.limit)
        return FindPeerCandidatesOutput(candidates=result.data)

    def summarize(self, output: FindPeerCandidatesOutput) -> str:
        lines = [
            f"{c.company.ticker} ({c.company.name}): revenue={fmt_num(c.revenue)} {c.fiscal_period or ''} - {c.reason}"
            for c in output.candidates
        ]
        return "\n".join(lines)[:6000]


def _metric_value(metrics: FinancialMetrics, period: str, key: str) -> float | None:
    mv = metrics.get(period, key)
    return mv.value if mv is not None else None


class GetPeerSnapshotInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    is_target: bool = False


class GetPeerSnapshotTool(Tool[GetPeerSnapshotInput, PeerSnapshot]):
    """One company's key comparison metrics (revenue, margins, valuation multiples), for peer tables."""

    name = "get_peer_snapshot"
    description = (
        "Fetch one company's key peer-comparison metrics: latest-year revenue, revenue growth, gross/"
        "operating/net margin, market cap, P/E and EV/Sales. Call once per peer (and once with "
        "is_target=true for the target company itself) to build a comparison table."
    )
    input_model = GetPeerSnapshotInput

    async def run(self, args: GetPeerSnapshotInput, ctx: ToolContext) -> PeerSnapshot:
        identity = await resolve_identity_with_profile(ctx, args.ticker)
        stmt_result = await ctx.providers.fundamentals.get_statements(identity, years=2)
        ctx.ledger.absorb(stmt_result)
        statements = stmt_result.data

        try:
            quote_result = await ctx.providers.market.get_quote(identity.ticker)
        except MeridianError:
            quote = None
        else:
            ctx.ledger.absorb(quote_result)
            quote = quote_result.data

        metrics = compute_metrics(statements, quote, is_financial_institution=identity.is_financial_institution)
        latest = statements.latest_annual()
        label = latest.period.label if latest else None

        evidence_ids: set[str] = set()
        if latest is not None and label:
            for key in ("revenue", "gross_profit", "operating_income", "net_income"):
                eid = latest.evidence_ids.get(key)
                if eid:
                    evidence_ids.add(eid)
            for key in ("revenue_growth", "gross_margin", "operating_margin", "net_margin"):
                mv = metrics.get(label, key)
                if mv is not None:
                    evidence_ids.update(metric_evidence_ids(mv, statements))
        for key in ("market_cap", "pe", "ev_sales"):
            mv = metrics.get("current", key)
            if mv is not None:
                evidence_ids.update(metric_evidence_ids(mv, statements))

        return PeerSnapshot(
            company=identity,
            is_target=args.is_target,
            selection_reason="target company" if args.is_target else "candidate peer",
            fiscal_period=label,
            revenue=latest.value("revenue") if latest else None,
            revenue_growth=_metric_value(metrics, label, "revenue_growth") if label else None,
            gross_margin=_metric_value(metrics, label, "gross_margin") if label else None,
            operating_margin=_metric_value(metrics, label, "operating_margin") if label else None,
            net_margin=_metric_value(metrics, label, "net_margin") if label else None,
            market_cap=_metric_value(metrics, "current", "market_cap"),
            pe=_metric_value(metrics, "current", "pe"),
            ev_sales=_metric_value(metrics, "current", "ev_sales"),
            evidence_ids=sorted(evidence_ids),
        )

    def summarize(self, output: PeerSnapshot) -> str:
        tag = " (target)" if output.is_target else ""
        return (
            f"{output.company.ticker}{tag}: revenue={fmt_num(output.revenue)} ({output.fiscal_period}), "
            f"revenue_growth={fmt_pct(output.revenue_growth)}, gross_margin={fmt_pct(output.gross_margin)}, "
            f"net_margin={fmt_pct(output.net_margin)}, market_cap={fmt_num(output.market_cap)}, "
            f"pe={fmt_num(output.pe, decimals=2)}x [{', '.join(output.evidence_ids)}]"
        )
