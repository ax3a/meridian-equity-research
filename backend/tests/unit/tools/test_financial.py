from __future__ import annotations

from meridian.tools.financial import (
    ComputeFinancialMetricsInput,
    ComputeFinancialMetricsTool,
    GetFinancialStatementsInput,
    GetFinancialStatementsTool,
)
from tests.unit.tools.conftest import (
    BIGBANK,
    FakeDirectory,
    FakeFundamentals,
    FakeMarket,
    make_registry,
    msft_statements,
)


async def test_get_financial_statements_returns_evidence_ids(make_ctx):
    ctx = make_ctx()
    output = await GetFinancialStatementsTool().run(GetFinancialStatementsInput(ticker="MSFT", years=5), ctx)
    assert output.statements.ticker == "MSFT"
    assert len(output.statements.annual) == 2
    assert output.evidence_ids  # non-empty
    # Every evidence id promised in the output must actually resolve in the ledger.
    for eid in output.evidence_ids:
        assert ctx.ledger.evidence[eid] is not None
    summary = GetFinancialStatementsTool().summarize(output)
    assert "revenue FY2024" in summary
    assert "245,122,000,000" in summary


async def test_compute_financial_metrics_summary_shows_evidence_ids_inline(make_ctx):
    ctx = make_ctx()
    output = await ComputeFinancialMetricsTool().run(
        ComputeFinancialMetricsInput(ticker="MSFT", years=5, include_market=True), ctx
    )
    assert output.metrics.ticker == "MSFT"
    revenue_fy2024 = output.metrics.get("FY2024", "revenue")
    assert revenue_fy2024 is not None
    assert revenue_fy2024.value == 245_122_000_000.0

    gross_margin = output.metrics.get("FY2024", "gross_margin")
    assert gross_margin is not None
    assert round(gross_margin.value, 4) == round(171_008_000_000.0 / 245_122_000_000.0, 4)

    summary = ComputeFinancialMetricsTool().summarize(output)
    # This is the exact property the WHY-THIS-MATTERS brief cares about: a value with its evidence id
    # rendered right next to it, so an LLM can only cite ids it has actually seen.
    assert "revenue FY2024 = 245,122,000,000 USD [" in summary
    revenue_evidence_id = output.statements.annual[-1].evidence_ids["revenue"]
    assert revenue_evidence_id in summary
    assert revenue_evidence_id in output.evidence_ids


async def test_compute_financial_metrics_skips_gross_margin_for_banks(make_ctx):
    bank_statements = msft_statements().model_copy(update={"ticker": "BBNK"})
    registry = make_registry(
        directory=FakeDirectory(identities={"BBNK": BIGBANK}),
        fundamentals=FakeFundamentals(bank_statements),
    )
    ctx = make_ctx(providers=registry)
    output = await ComputeFinancialMetricsTool().run(ComputeFinancialMetricsInput(ticker="BBNK"), ctx)
    gross_margin = output.metrics.get("FY2024", "gross_margin")
    assert gross_margin is not None
    assert gross_margin.value is None
    assert gross_margin.note == "not meaningful for financial institutions"


async def test_compute_financial_metrics_tolerates_market_failure(make_ctx):
    registry = make_registry(market=FakeMarket(fails=True))
    ctx = make_ctx(providers=registry)
    output = await ComputeFinancialMetricsTool().run(ComputeFinancialMetricsInput(ticker="MSFT"), ctx)
    assert output.quote is None
    assert "current" not in output.metrics.periods
