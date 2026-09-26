"""`validate_findings`: the gate every agent's findings pass before they enter state.

It had no direct tests — it was only ever exercised through agent tests, which supply well-formed
findings and so never probed the rule itself. The gap showed when a live model produced nine findings
that cited a real computed metric but were labelled FACT: the rule demanded *evidence* for a FACT and
discarded all nine over the label rather than the substance.
"""

from __future__ import annotations

from meridian.agents.validation import validate_findings
from meridian.schemas.enums import AgentName, FindingKind, FindingStatus, ReportSection
from meridian.schemas.findings import Finding


def _finding(
    *,
    kind: FindingKind,
    evidence_ids: list[str],
    metric_refs: list[str],
    claim: str = "A claim that needs support.",
) -> Finding:
    return Finding(
        agent=AgentName.FINANCIALS,
        claim=claim,
        kind=kind,
        section=ReportSection.FINANCIAL_PERFORMANCE,
        evidence_ids=evidence_ids,
        metric_refs=metric_refs,
    )


def test_a_fact_supported_only_by_a_metric_is_relabelled_not_discarded() -> None:
    """A live model produced nine of these in one run, every one citing a real metric.

    All nine were thrown away because FACT demands evidence — the label was wrong, not the research.
    A claim backed by a computed metric *is* a calculation, so saying so keeps it and keeps the
    report's Fact/Calculated badge truthful at the same time.
    """
    finding = _finding(kind=FindingKind.FACT, evidence_ids=[], metric_refs=["m1"])

    out, report = validate_findings([finding], evidence_ids=set(), metric_refs={"m1"})

    assert out[0].kind is FindingKind.CALCULATED
    assert out[0].status is not FindingStatus.UNVERIFIED
    assert out[0].metric_refs == ["m1"]
    assert report.relabelled_finding_ids == [finding.id]
    assert report.unverified_finding_ids == []


def test_a_fact_with_real_evidence_keeps_its_kind() -> None:
    finding = _finding(kind=FindingKind.FACT, evidence_ids=["e1"], metric_refs=["m1"])

    out, report = validate_findings([finding], evidence_ids={"e1"}, metric_refs={"m1"})

    assert out[0].kind is FindingKind.FACT, "evidence-backed facts must not be reclassified"
    assert report.relabelled_finding_ids == []


def test_a_fact_with_nothing_behind_it_is_still_unverified() -> None:
    """Relabelling must not become a way for an unsupported claim to slip through."""
    finding = _finding(kind=FindingKind.FACT, evidence_ids=["ghost"], metric_refs=["ghost"])

    out, report = validate_findings([finding], evidence_ids=set(), metric_refs=set())

    assert out[0].status is FindingStatus.UNVERIFIED
    assert out[0].kind is FindingKind.FACT
    assert report.relabelled_finding_ids == []


def test_citations_that_do_not_resolve_are_stripped() -> None:
    finding = _finding(kind=FindingKind.FACT, evidence_ids=["e1", "ghost"], metric_refs=["m1", "ghost"])

    out, report = validate_findings([finding], evidence_ids={"e1"}, metric_refs={"m1"})

    assert out[0].evidence_ids == ["e1"]
    assert out[0].metric_refs == ["m1"]
    assert report.stripped_evidence_ids == ["ghost"]
    assert report.stripped_metric_refs == ["ghost"]


def test_a_calculated_finding_needs_a_metric() -> None:
    supported = _finding(kind=FindingKind.CALCULATED, evidence_ids=[], metric_refs=["m1"])
    unsupported = _finding(kind=FindingKind.CALCULATED, evidence_ids=["e1"], metric_refs=[], claim="Second claim.")

    out, _ = validate_findings([supported, unsupported], evidence_ids={"e1"}, metric_refs={"m1"})

    assert out[0].status is not FindingStatus.UNVERIFIED
    assert out[1].status is FindingStatus.UNVERIFIED, "a calculation with no metric behind it is not supported"


def test_an_interpretation_accepts_either_kind_of_support() -> None:
    by_evidence = _finding(kind=FindingKind.INTERPRETATION, evidence_ids=["e1"], metric_refs=[])
    by_metric = _finding(kind=FindingKind.INTERPRETATION, evidence_ids=[], metric_refs=["m1"], claim="Second claim.")

    out, _ = validate_findings([by_evidence, by_metric], evidence_ids={"e1"}, metric_refs={"m1"})

    assert all(f.status is not FindingStatus.UNVERIFIED for f in out)


def test_duplicate_claims_are_dropped() -> None:
    first = _finding(kind=FindingKind.FACT, evidence_ids=["e1"], metric_refs=[])
    second = _finding(
        kind=FindingKind.FACT, evidence_ids=["e1"], metric_refs=[], claim="  a CLAIM that needs support. "
    )

    out, report = validate_findings([first, second], evidence_ids={"e1"}, metric_refs=set())

    assert len(out) == 1, "case and whitespace must not make the same claim look like two"
    assert report.duplicate_finding_ids == [second.id]


def test_a_rejected_finding_is_never_quietly_promoted() -> None:
    finding = _finding(kind=FindingKind.FACT, evidence_ids=[], metric_refs=[])
    finding = finding.model_copy(update={"status": FindingStatus.REJECTED})

    out, report = validate_findings([finding], evidence_ids=set(), metric_refs=set())

    assert out[0].status is FindingStatus.REJECTED
    assert report.unverified_finding_ids == []
