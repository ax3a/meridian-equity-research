from __future__ import annotations

from meridian.agents.competitors import CompetitorsAgent, CompetitorsAnswer, ProposedPeer
from meridian.schemas.enums import AgentName, FindingStatus, ReportSection
from tests.unit.agents.conftest import build_tool_registry, make_deps, make_state, make_task


async def test_competitors_offline_builds_peer_comparison_with_real_evidence(fake_data, events, offline_llm, settings):
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, offline_llm, events)
    agent = CompetitorsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    assert result.output.status.value == "completed"
    peers = result.state_updates["peers"]
    assert peers.target_ticker == fake_data.ticker
    assert 1 <= len(peers.peers) - 1 <= 5  # target row plus up to 5 peers
    assert any(p.is_target for p in peers.peers)

    assert result.output.findings, "expected comparison findings"
    for f in result.output.findings:
        assert f.status != FindingStatus.UNVERIFIED
        assert f.section == ReportSection.INDUSTRY_COMPETITION
        for eid in f.evidence_ids:
            assert eid in result.evidence


async def test_competitors_generative_validates_proposed_peer_by_resolution(fake_data, events, scripted_llm, settings):
    fake_data.add_peer_snapshot(
        "QCOM", "Qualcomm Inc", revenue=30e9, growth=0.12, gm=0.55, om=0.25, nm=0.20, pe=18.0, ev_sales=5.0
    )
    scripted_llm.script(
        AgentName.COMPETITORS,
        {
            "structured": CompetitorsAnswer(
                summary="Compared against a mobile-chip peer as well as the SIC universe.",
                findings=[],
                proposed_peers=[
                    ProposedPeer(ticker="QCOM", reason="Overlapping AI accelerator ambitions."),
                    ProposedPeer(ticker="NOTREAL", reason="Should be dropped: cannot be resolved."),
                ],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = CompetitorsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    peers = result.state_updates["peers"]
    peer_tickers = {p.company.ticker for p in peers.peers if not p.is_target}
    assert "QCOM" in peer_tickers
    assert "NOTREAL" not in peer_tickers
    assert len(peer_tickers) <= 5


async def test_competitors_generative_caps_peers_at_five(fake_data, events, scripted_llm, settings):
    # 5 proposed peers already fill the cap; the 2 default find_peer_candidates (AMD, INTC) must be dropped.
    for i in range(5):
        fake_data.add_peer_snapshot(
            f"EX{i}", f"Extra Peer {i}", revenue=1e9, growth=0.1, gm=0.4, om=0.15, nm=0.1, pe=15.0, ev_sales=2.0
        )
    scripted_llm.script(
        AgentName.COMPETITORS,
        {
            "structured": CompetitorsAnswer(
                summary="Proposed many peers.",
                findings=[],
                proposed_peers=[ProposedPeer(ticker=f"EX{i}", reason="candidate") for i in range(5)],
            ).model_dump()
        },
    )
    tools = build_tool_registry(fake_data)
    deps = make_deps(settings, tools, scripted_llm, events)
    agent = CompetitorsAgent(deps)
    state = make_state(fake_data.ticker)
    task = make_task(agent.name)

    result = await agent.execute(task, state)

    peers = result.state_updates["peers"]
    non_target = [p for p in peers.peers if not p.is_target]
    assert len(non_target) == 5
    assert {p.company.ticker for p in non_target} == {f"EX{i}" for i in range(5)}
