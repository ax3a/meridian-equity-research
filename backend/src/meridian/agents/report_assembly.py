"""Pure functions that assemble report artifacts (charts, key metrics, citations, markdown) from state.

No LLM calls here: every function is a deterministic transform over already-computed data, which keeps
report assembly trivially testable independent of the writer's prose generation.
"""

from __future__ import annotations

from collections.abc import Iterable

from meridian.schemas.citations import Citation, resolve_citation
from meridian.schemas.enums import Confidence, FindingKind
from meridian.schemas.financials import FinancialMetrics
from meridian.schemas.findings import Finding
from meridian.schemas.report import ChartSeries, ChartSeriesPoint, MetricRow, ResearchReport
from meridian.schemas.state import ResearchState

# Point-in-time periods (a single snapshot, e.g. "current price-based multiples") don't make a trend chart.
_TREND_PERIOD_EXCLUDE = {"current", "custom"}

_CHART_KEYS: tuple[tuple[str, str], ...] = (
    ("revenue", "Revenue"),
    ("gross_margin", "Gross Margin"),
    ("operating_margin", "Operating Margin"),
    ("net_margin", "Net Margin"),
    ("free_cash_flow", "Free Cash Flow"),
    ("ebitda_margin", "EBITDA Margin"),
)

_KEY_METRIC_KEYS: tuple[str, ...] = (
    "revenue",
    "revenue_growth",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "free_cash_flow",
    "fcf_margin",
    "ebitda_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "pe",
    "ev_ebitda",
    "price_sales",
    "fcf_yield",
)

_LABELS: dict[str, str] = {
    "revenue": "Revenue",
    "revenue_growth": "Revenue Growth",
    "gross_margin": "Gross Margin",
    "operating_margin": "Operating Margin",
    "net_margin": "Net Margin",
    "free_cash_flow": "Free Cash Flow",
    "fcf_margin": "FCF Margin",
    "ebitda_margin": "EBITDA Margin",
    "roe": "Return on Equity",
    "roa": "Return on Assets",
    "debt_to_equity": "Debt / Equity",
    "pe": "P/E",
    "ev_ebitda": "EV / EBITDA",
    "price_sales": "Price / Sales",
    "fcf_yield": "FCF Yield",
}


def build_chart_series(metrics: FinancialMetrics | None) -> list[ChartSeries]:
    """Chart-ready trend series (annual + TTM periods only) for the standard set of headline metrics."""
    if metrics is None:
        return []
    charts: list[ChartSeries] = []
    for key, label in _CHART_KEYS:
        points = sorted(
            (m for m in metrics.series(key) if m.period not in _TREND_PERIOD_EXCLUDE and m.value is not None),
            key=lambda m: m.period,
        )
        if not points:
            continue
        charts.append(
            ChartSeries(
                key=key,
                label=label,
                unit=points[0].unit,
                points=[ChartSeriesPoint(period=p.period, value=p.value) for p in points],
            )
        )
    return charts


def build_key_metrics(metrics: FinancialMetrics | None) -> list[MetricRow]:
    """Period -> value rows for the standard set of key metrics, each carrying its formula for traceability."""
    if metrics is None:
        return []
    rows: list[MetricRow] = []
    for key in _KEY_METRIC_KEYS:
        series = metrics.series(key)
        if not series:
            continue
        rows.append(
            MetricRow(
                key=key,
                label=_LABELS.get(key, key),
                unit=series[0].unit,
                values={m.period: m.value for m in series},
                formula=series[0].formula,
            )
        )
    return rows


_CONFIDENCE_RANK: dict[Confidence, int] = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


def rank_findings(findings: list[Finding]) -> list[Finding]:
    """Findings ordered best-first: higher confidence wins, ties broken by how well-cited they are."""

    def key(f: Finding) -> tuple[int, int]:
        return (_CONFIDENCE_RANK.get(f.confidence, 0), len(f.evidence_ids) + len(f.metric_refs))

    return sorted(findings, key=key, reverse=True)


def pick_best_finding(
    findings: list[Finding], *, prefer_kinds: tuple[FindingKind, ...] | None = None
) -> Finding | None:
    """The single best finding for a one-line summary, optionally preferring certain `FindingKind`s."""
    if not findings:
        return None
    ranked = rank_findings(findings)
    if prefer_kinds:
        preferred = [f for f in ranked if f.kind in prefer_kinds]
        if preferred:
            return preferred[0]
    return ranked[0]


def pick_top_findings(findings: list[Finding], limit: int) -> list[Finding]:
    """The `limit` best findings (see `rank_findings`), e.g. the top risks to headline."""
    return rank_findings(findings)[:limit]


def latest_metrics_period(metrics: FinancialMetrics | None) -> str | None:
    """The most recent real period to headline: TTM when available, else the latest annual period."""
    if metrics is None or not metrics.periods:
        return None
    if "TTM" in metrics.periods:
        return "TTM"
    candidates = [p for p in metrics.periods if p not in _TREND_PERIOD_EXCLUDE]
    return candidates[-1] if candidates else None


def _format_usd(value: float) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e12:
        return f"{sign}${v / 1e12:.1f}T"
    if v >= 1e9:
        return f"{sign}${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{sign}${v / 1e3:.1f}K"
    return f"{sign}${v:.2f}"


def format_metric_value(value: float | None, unit: str) -> str:
    """A short, human-readable rendering of a `MetricValue`, used to state engine-computed figures in prose."""
    if value is None:
        return "n/a"
    if unit == "USD":
        return _format_usd(value)
    if unit == "USD/share":
        return f"${value:,.2f}"
    if unit in ("ratio", "percent"):
        return f"{value * 100:.1f}%" if unit == "ratio" else f"{value:.1f}%"
    if unit == "x":
        return f"{value:.1f}x"
    return f"{value:g}"


def resolve_citations(evidence_ids: Iterable[str], state: ResearchState) -> dict[str, Citation]:
    """Resolve every cited evidence id to a rendered `Citation`, silently skipping any that can't be resolved."""
    out: dict[str, Citation] = {}
    for eid in evidence_ids:
        ev = state.evidence.get(eid)
        if ev is None:
            continue
        src = state.sources.get(ev.source_id)
        if src is None:
            continue
        out[eid] = resolve_citation(ev, src)
    return out


def render_markdown(report: ResearchReport) -> str:
    """A readable markdown rendering of the report, unverified content clearly marked."""
    lines = [
        f"# {report.title}",
        "",
        f"_Generated {report.generated_at.isoformat()} ({report.llm_mode} mode, {report.data_mode} data)_",
        "",
        report.disclaimer,
        "",
    ]
    for section in report.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        for para in section.paragraphs:
            suffix = " *(unverified — see Open Questions)*" if para.unverified else ""
            lines.append(para.text + suffix)
            lines.append("")
    if report.key_metrics:
        lines.append("## Key Metrics")
        lines.append("")
        for row in report.key_metrics:
            values = ", ".join(f"{period}: {value}" for period, value in row.values.items())
            lines.append(f"- **{row.label}** ({row.unit}): {values}")
        lines.append("")
    if report.citations:
        lines.append("## Sources")
        lines.append("")
        for eid, citation in report.citations.items():
            lines.append(f"- [{eid}] {citation.source_title} — {citation.publisher} ({citation.location})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
