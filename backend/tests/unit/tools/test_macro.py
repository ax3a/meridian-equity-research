from __future__ import annotations

from meridian.tools.macro import GetMacroIndicatorsInput, GetMacroIndicatorsTool


async def test_get_macro_indicators_returns_all_by_default(make_ctx):
    ctx = make_ctx()
    output = await GetMacroIndicatorsTool().run(GetMacroIndicatorsInput(), ctx)
    assert {i.key for i in output.indicators} == {"ust_3m", "ust_2y", "ust_10y"}
    assert len(output.evidence_ids) == 3


async def test_get_macro_indicators_filters_by_key_keeping_evidence_aligned(make_ctx):
    ctx = make_ctx()
    output = await GetMacroIndicatorsTool().run(GetMacroIndicatorsInput(keys=["ust_10y"]), ctx)
    assert [i.key for i in output.indicators] == ["ust_10y"]
    assert len(output.evidence_ids) == 1
    assert ctx.ledger.evidence[output.evidence_ids[0]].text.startswith("Treasury: ust_10y")
    summary = GetMacroIndicatorsTool().summarize(output)
    assert "ust_10y" in summary and output.evidence_ids[0] in summary
