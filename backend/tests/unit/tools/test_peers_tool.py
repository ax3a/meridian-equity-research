from __future__ import annotations

from meridian.tools.peers import (
    FindPeerCandidatesInput,
    FindPeerCandidatesTool,
    GetPeerSnapshotInput,
    GetPeerSnapshotTool,
)


async def test_find_peer_candidates_returns_candidates(make_ctx):
    ctx = make_ctx()
    output = await FindPeerCandidatesTool().run(FindPeerCandidatesInput(ticker="MSFT"), ctx)
    assert len(output.candidates) == 1
    assert output.candidates[0].company.ticker == "ORCL"
    summary = FindPeerCandidatesTool().summarize(output)
    assert "ORCL" in summary


async def test_get_peer_snapshot_for_target_carries_evidence(make_ctx):
    ctx = make_ctx()
    snapshot = await GetPeerSnapshotTool().run(GetPeerSnapshotInput(ticker="MSFT", is_target=True), ctx)
    assert snapshot.is_target is True
    assert snapshot.fiscal_period == "FY2024"
    assert snapshot.revenue == 245_122_000_000.0
    assert snapshot.gross_margin is not None
    assert snapshot.market_cap is not None  # quote succeeded in the fixture
    assert len(snapshot.evidence_ids) > 0
    for eid in snapshot.evidence_ids:
        assert ctx.ledger.evidence[eid] is not None
    summary = GetPeerSnapshotTool().summarize(snapshot)
    assert "(target)" in summary
