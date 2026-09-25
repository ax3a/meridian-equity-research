from __future__ import annotations

import pytest

from meridian.core.errors import ValidationFailedError
from meridian.schemas.analysis import DCFAssumptions
from meridian.tools.calc import CalculateMetricInput, CalculateMetricTool, RunDcfInput, RunDcfTool


async def test_calculate_metric_gross_margin(make_ctx):
    ctx = make_ctx()
    output = await CalculateMetricTool().run(
        CalculateMetricInput(metric="gross_margin", inputs={"gross_profit": 50.0, "revenue": 200.0}), ctx
    )
    assert output.value == pytest.approx(0.25)
    summary = CalculateMetricTool().summarize(output)
    assert "gross_margin" in summary and "25.00%" in summary


async def test_calculate_metric_unknown_metric_raises(make_ctx):
    ctx = make_ctx()
    with pytest.raises(ValidationFailedError):
        await CalculateMetricTool().run(CalculateMetricInput(metric="not_a_real_metric", inputs={}), ctx)


async def test_run_dcf_produces_value_per_share(make_ctx):
    ctx = make_ctx()
    assumptions = DCFAssumptions(
        base_revenue=245_122_000_000.0,
        revenue_growth=[0.12, 0.10, 0.08, 0.06, 0.04],
        fcf_margin=0.30,
        discount_rate=0.09,
        terminal_growth=0.025,
        net_cash=15_000_000_000.0,
        shares_outstanding=7_434_000_000.0,
        rationale=["revenue growth decays from 3y CAGR toward 4% by year 5"],
    )
    output = await RunDcfTool().run(RunDcfInput(assumptions=assumptions, current_price=430.50), ctx)
    assert output.value_per_share > 0
    assert output.upside_pct is not None
    assert len(output.sensitivity) > 0
    summary = RunDcfTool().summarize(output)
    assert "DCF value/share" in summary
    assert "revenue growth decays" in summary


async def test_run_dcf_invalid_spread_raises(make_ctx):
    ctx = make_ctx()
    assumptions = DCFAssumptions(
        base_revenue=100.0,
        revenue_growth=[0.05],
        fcf_margin=0.2,
        discount_rate=0.03,
        terminal_growth=0.03,
        net_cash=0.0,
        shares_outstanding=10.0,
    )
    with pytest.raises(ValidationFailedError):
        await RunDcfTool().run(RunDcfInput(assumptions=assumptions), ctx)
