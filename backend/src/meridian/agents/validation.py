"""Deterministic citation/metric validation applied to every agent's findings before they enter state."""

from __future__ import annotations

from collections.abc import Collection

from pydantic import BaseModel, Field

from meridian.schemas.enums import FindingKind, FindingStatus
from meridian.schemas.findings import Finding


class ValidationReport(BaseModel):
    stripped_evidence_ids: list[str] = Field(default_factory=list)
    stripped_metric_refs: list[str] = Field(default_factory=list)
    unverified_finding_ids: list[str] = Field(default_factory=list)
    relabelled_finding_ids: list[str] = Field(default_factory=list)
    duplicate_finding_ids: list[str] = Field(default_factory=list)

    @property
    def problems(self) -> int:
        return len(self.stripped_evidence_ids) + len(self.stripped_metric_refs) + len(self.unverified_finding_ids)


def validate_findings(
    findings: list[Finding], *, evidence_ids: Collection[str], metric_refs: Collection[str]
) -> tuple[list[Finding], ValidationReport]:
    """Strip citations that don't exist, mark unsupported claims UNVERIFIED, drop duplicates.

    Never fabricates support: a claim either keeps real references or is visibly marked unverified.
    """
    report = ValidationReport()
    out: list[Finding] = []
    seen_claims: set[str] = set()
    for f in findings:
        norm = " ".join(f.claim.lower().split())
        if norm in seen_claims:
            report.duplicate_finding_ids.append(f.id)
            continue
        seen_claims.add(norm)

        good_ev = [e for e in dict.fromkeys(f.evidence_ids) if e in evidence_ids]
        good_m = [m for m in dict.fromkeys(f.metric_refs) if m in metric_refs]
        report.stripped_evidence_ids += [e for e in f.evidence_ids if e not in evidence_ids]
        report.stripped_metric_refs += [m for m in f.metric_refs if m not in metric_refs]

        kind = f.kind
        # A claim labelled FACT but supported only by a computed metric is a calculation, and saying so
        # is both true and what keeps it. Discarding it was strictly worse: a live model produced nine
        # such findings in one run -- every one correctly citing a real metric -- and all nine were
        # thrown away over the label rather than the substance. Relabelling rather than merely accepting
        # keeps the report's Fact/Calculated badge honest, which is the whole point of having it.
        if kind is FindingKind.FACT and good_m and not good_ev:
            kind = FindingKind.CALCULATED
            report.relabelled_finding_ids.append(f.id)

        supported = {
            FindingKind.FACT: bool(good_ev),
            FindingKind.CALCULATED: bool(good_m),
            FindingKind.INTERPRETATION: bool(good_ev or good_m),
        }[kind]
        status = f.status
        if not supported and status != FindingStatus.REJECTED:
            status = FindingStatus.UNVERIFIED
            report.unverified_finding_ids.append(f.id)
        out.append(
            f.model_copy(update={"evidence_ids": good_ev, "metric_refs": good_m, "status": status, "kind": kind})
        )
    return out, report
