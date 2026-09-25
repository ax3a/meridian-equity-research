"""Scoring functions over a finished `ResearchState`.

Every metric is computed from the run itself, never asserted by hand, so a bad score shows up as a bad
score. Each returns a `Metric` carrying the value, the counts behind it and a one-line explanation, so a
scorecard can be read without re-deriving anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from meridian.financial_engine import compute_metrics
from meridian.schemas.enums import (
    AgentName,
    FindingKind,
    FindingStatus,
    ReportSection,
    TaskStatus,
)
from meridian.schemas.state import ResearchState

# Sections a standard-depth report should always contain.
REQUIRED_SECTIONS: tuple[ReportSection, ...] = (
    ReportSection.EXECUTIVE_SUMMARY,
    ReportSection.COMPANY_OVERVIEW,
    ReportSection.FINANCIAL_PERFORMANCE,
    ReportSection.KEY_RISKS,
    ReportSection.BULL_CASE,
    ReportSection.BEAR_CASE,
)

# Relative tolerance when re-deriving a metric from the statements.
CALC_TOLERANCE = 1e-6


@dataclass
class Metric:
    name: str
    value: float | None
    detail: str
    counts: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "detail": self.detail,
            "counts": self.counts,
        }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def task_completion(state: ResearchState) -> Metric:
    tasks = list(state.tasks.values())
    done = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
    return Metric(
        "task_completion",
        _ratio(done, len(tasks)),
        f"{done}/{len(tasks)} dispatched tasks completed ({failed} failed)",
        {"completed": done, "failed": failed, "total": len(tasks)},
    )


def routing_accuracy(
    state: ResearchState, *, expected: set[AgentName], forbidden: set[AgentName]
) -> Metric:
    """Did the supervisor select the agents this request needs, and skip the ones it should not run?"""
    planned = {t.agent for t in (state.plan.tasks if state.plan else [])}
    missing = sorted(a.value for a in expected - planned)
    wrongly_included = sorted(a.value for a in forbidden & planned)
    checks = len(expected) + len(forbidden)
    correct = checks - len(missing) - len(wrongly_included)
    return Metric(
        "routing_accuracy",
        _ratio(correct, checks),
        f"missing={missing or 'none'}; wrongly included={wrongly_included or 'none'}",
        {
            "planned": sorted(a.value for a in planned),
            "missing": missing,
            "wrongly_included": wrongly_included,
        },
    )


def citation_coverage(state: ResearchState) -> Metric:
    """Share of factual/calculated findings that carry support which actually resolves."""
    checkable = [
        f
        for f in state.findings()
        if f.kind in (FindingKind.FACT, FindingKind.CALCULATED)
    ]
    known_metrics = set(state.metrics.values) if state.metrics else set()
    supported = [
        f
        for f in checkable
        if any(e in state.evidence for e in f.evidence_ids)
        or any(m in known_metrics for m in f.metric_refs)
    ]
    return Metric(
        "citation_coverage",
        _ratio(len(supported), len(checkable)),
        f"{len(supported)}/{len(checkable)} fact/calculated findings carry resolvable support",
        {"supported": len(supported), "checkable": len(checkable)},
    )


def source_correctness(state: ResearchState) -> Metric:
    """Every cited evidence id must exist and point at a source that also exists."""
    cited = [e for f in state.findings() for e in f.evidence_ids]
    valid = 0
    dangling_evidence, dangling_source = 0, 0
    for evidence_id in cited:
        evidence = state.evidence.get(evidence_id)
        if evidence is None:
            dangling_evidence += 1
        elif evidence.source_id not in state.sources:
            dangling_source += 1
        else:
            valid += 1
    return Metric(
        "source_correctness",
        _ratio(valid, len(cited)),
        f"{valid}/{len(cited)} citations resolve to a real source "
        f"({dangling_evidence} unknown evidence, {dangling_source} orphaned source)",
        {
            "valid": valid,
            "cited": len(cited),
            "unknown_evidence": dangling_evidence,
            "orphan_source": dangling_source,
        },
    )


def calculation_accuracy(state: ResearchState) -> Metric:
    """Recompute the metrics table from the statements and compare, catching drift between the two."""
    if state.financials is None or state.metrics is None:
        return Metric(
            "calculation_accuracy", None, "no statements or metrics on the run", {}
        )
    recomputed = compute_metrics(
        state.financials,
        state.quote,
        is_financial_institution=bool(
            state.company and state.company.is_financial_institution
        ),
    )
    compared, matched, mismatches = 0, 0, []
    for ref, original in state.metrics.values.items():
        check = recomputed.values.get(ref)
        if check is None or original.value is None or check.value is None:
            continue
        compared += 1
        denominator = max(abs(original.value), 1e-9)
        if abs(original.value - check.value) / denominator <= CALC_TOLERANCE:
            matched += 1
        elif len(mismatches) < 5:
            mismatches.append(
                f"{ref}: run={original.value!r} recomputed={check.value!r}"
            )
    return Metric(
        "calculation_accuracy",
        _ratio(matched, compared),
        f"{matched}/{compared} metrics reproduce exactly"
        + (f"; e.g. {mismatches[0]}" if mismatches else ""),
        {"matched": matched, "compared": compared, "mismatches": mismatches},
    )


def critic_rejection_rate(state: ResearchState) -> Metric:
    """Share of findings the critic refused to approve. High is not automatically bad -- it means the
    gate is doing something -- but a run where nothing is approved produces an empty report."""
    findings = state.findings()
    rejected = sum(1 for f in findings if f.status == FindingStatus.REJECTED)
    unverified = sum(1 for f in findings if f.status == FindingStatus.UNVERIFIED)
    approved = sum(1 for f in findings if f.status == FindingStatus.APPROVED)
    issues = sum(
        len(r.issues) for review in state.critic_reviews for r in review.reviews
    )
    return Metric(
        "critic_rejection_rate",
        _ratio(rejected + unverified, len(findings)),
        f"{approved} approved, {unverified} unverified, {rejected} rejected; "
        f"{issues} issues raised over {len(state.critic_reviews)} round(s)",
        {
            "approved": approved,
            "unverified": unverified,
            "rejected": rejected,
            "issues": issues,
        },
    )


def unsupported_claims_in_report(state: ResearchState) -> Metric:
    """The report is the product: count paragraphs asserting fact without resolvable support."""
    if state.report is None:
        return Metric("unsupported_report_claims", None, "no report produced", {})
    paragraphs = [p for section in state.report.sections for p in section.paragraphs]
    factual = [
        p for p in paragraphs if p.kind in (FindingKind.FACT, FindingKind.CALCULATED)
    ]
    unsupported = [
        p
        for p in factual
        if not any(e in state.report.citations for e in p.evidence_ids)
        and not p.metric_refs
    ]
    return Metric(
        "unsupported_report_claims",
        float(len(unsupported)),
        f"{len(unsupported)}/{len(factual)} factual paragraphs lack a resolvable citation or metric ref",
        {
            "unsupported": len(unsupported),
            "factual": len(factual),
            "paragraphs": len(paragraphs),
        },
    )


def report_completeness(
    state: ResearchState, *, required: tuple[ReportSection, ...] | None = None
) -> Metric:
    """Sections expected for the depth that was requested.

    A quick-depth run deliberately drops the bull and bear cases, so scoring it against the standard
    section list would measure the metric's assumptions rather than the system's behaviour.
    """
    expected = required if required is not None else REQUIRED_SECTIONS
    if state.report is None:
        return Metric(
            "report_completeness",
            0.0,
            "no report produced",
            {"present": [], "missing": []},
        )
    present = {s.section for s in state.report.sections if s.paragraphs}
    missing = sorted(s.value for s in expected if s not in present)
    return Metric(
        "report_completeness",
        _ratio(len(expected) - len(missing), len(expected)),
        f"missing sections: {missing or 'none'} (expected {len(expected)} for this depth)",
        {"sections": len(state.report.sections), "missing": missing},
    )


def cost_and_tokens(state: ResearchState) -> Metric:
    tokens = sum(u.input_tokens + u.output_tokens for u in state.usage)
    cost = sum(u.cost_usd for u in state.usage)
    return Metric(
        "estimated_cost_usd",
        round(cost, 4),
        f"{tokens} tokens across {len(state.usage)} LLM call(s); "
        f"{len(state.tool_calls)} tool calls (0 tokens means offline mode)",
        {
            "tokens": tokens,
            "llm_calls": len(state.usage),
            "tool_calls": len(state.tool_calls),
        },
    )


def tool_success_rate(state: ResearchState) -> Metric:
    ok = sum(1 for c in state.tool_calls if c.status == "ok")
    return Metric(
        "tool_success_rate",
        _ratio(ok, len(state.tool_calls)),
        f"{ok}/{len(state.tool_calls)} tool calls succeeded",
        {"ok": ok, "total": len(state.tool_calls)},
    )


def score_run(
    state: ResearchState,
    *,
    expected: set[AgentName],
    forbidden: set[AgentName],
    latency_s: float,
    required_sections: tuple[ReportSection, ...] | None = None,
) -> list[Metric]:
    return [
        task_completion(state),
        routing_accuracy(state, expected=expected, forbidden=forbidden),
        citation_coverage(state),
        source_correctness(state),
        calculation_accuracy(state),
        critic_rejection_rate(state),
        unsupported_claims_in_report(state),
        report_completeness(state, required=required_sections),
        tool_success_rate(state),
        cost_and_tokens(state),
        Metric(
            "latency_seconds",
            round(latency_s, 1),
            "wall-clock time for the whole run",
            {},
        ),
    ]
