from __future__ import annotations

from datetime import UTC

from meridian.agents import report_assembly
from meridian.schemas.enums import FindingKind, ReportSection
from meridian.schemas.report import ChartSeries, MetricRow, ReportParagraph, ReportSectionContent, ResearchReport

from .conftest_orchestration import make_evidence, make_metrics, make_source, make_state


def test_build_chart_series_excludes_point_in_time_periods() -> None:
    metrics = make_metrics()

    charts = report_assembly.build_chart_series(metrics)

    revenue_chart = next(c for c in charts if c.key == "revenue")
    assert isinstance(revenue_chart, ChartSeries)
    periods = [p.period for p in revenue_chart.points]
    assert "current" not in periods
    assert "FY2023" in periods and "FY2024" in periods
    # pe is not in the chart key set at all (it's a current-only valuation multiple)
    assert not any(c.key == "pe" for c in charts)


def test_build_chart_series_handles_missing_metrics() -> None:
    assert report_assembly.build_chart_series(None) == []


def test_build_key_metrics_includes_formula_for_traceability() -> None:
    metrics = make_metrics()

    rows = report_assembly.build_key_metrics(metrics)

    revenue_row = next(r for r in rows if r.key == "revenue")
    assert isinstance(revenue_row, MetricRow)
    assert revenue_row.values["FY2024"] == 245_122_000_000.0
    assert revenue_row.formula
    pe_row = next(r for r in rows if r.key == "pe")
    assert pe_row.values["current"] == 33.9


def test_resolve_citations_maps_evidence_to_citation_and_skips_unknown() -> None:
    source = make_source("10k")
    evidence = make_evidence(source, "Revenue was $245,122 million.")
    state = make_state(sources=[source], evidence=[evidence])

    citations = report_assembly.resolve_citations([evidence.id, "ev_unknown"], state)

    assert set(citations) == {evidence.id}
    citation = citations[evidence.id]
    assert citation.source_id == source.id
    assert citation.publisher == source.publisher


def test_render_markdown_marks_unverified_paragraphs() -> None:
    from datetime import datetime

    from meridian.schemas.research import CompanyIdentity

    company = CompanyIdentity(name="Acme Corp", ticker="ACME", cik="1")
    report = ResearchReport(
        id="report_1",
        session_id="sess_1",
        company=company,
        title="Acme Corp Equity Research",
        generated_at=datetime.now(UTC),
        llm_mode="offline",
        data_mode="snapshot",
        sections=[
            ReportSectionContent(
                section=ReportSection.COMPANY_OVERVIEW,
                title="Company Overview",
                paragraphs=[
                    ReportParagraph(text="Acme sells widgets. [ev_1]", kind=FindingKind.FACT, evidence_ids=["ev_1"]),
                ],
            ),
            ReportSectionContent(
                section=ReportSection.OPEN_QUESTIONS,
                title="Open Questions",
                paragraphs=[
                    ReportParagraph(text="Margin trend is unclear.", kind=FindingKind.INTERPRETATION, unverified=True),
                ],
            ),
        ],
    )

    markdown = report_assembly.render_markdown(report)

    assert "Acme sells widgets" in markdown
    assert "(unverified" in markdown
    assert report.disclaimer in markdown
