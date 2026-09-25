"""The critic: deterministic integrity checks (always run) plus an optional LLM judgement pass.

The deterministic checks are the safety net that must work with no LLM at all: a FACT finding with no
evidence id, a CALCULATED finding whose stated number disagrees with the computed metrics table, stale
evidence cited in RECENT_DEVELOPMENTS, near-duplicate claims made by different agents, contradictory
directional claims about the same metric, evidence ids that don't exist in this run's evidence store
(hallucination), and findings that validation had already marked UNVERIFIED. Only after those run does an
optional critic-tier LLM pass add judgement (unsupported claims, weak assumptions) that the deterministic
checks cannot catch.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from meridian.agents.base import AgentDraft, BaseAgent
from meridian.agents.contracts import CriticResult
from meridian.core.config import LLMTier
from meridian.core.errors import LLMOutputError
from meridian.core.ids import utcnow
from meridian.core.logging import get_logger
from meridian.schemas.analysis import CriticIssue, CriticReview, SectionReview
from meridian.schemas.enums import (
    AgentName,
    CriticIssueType,
    FindingKind,
    FindingStatus,
    ReportSection,
    Severity,
    Verdict,
)
from meridian.schemas.findings import AgentOutput, Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.schemas.telemetry import LLMUsage
from meridian.tools.base import ToolContext

log = get_logger(__name__)

STALE_RECENT_DEVELOPMENTS_DAYS = 400
_NUMBER_TOLERANCE = 0.01
_DUPLICATE_SIMILARITY = 0.9

_SEVERITY_RANK: dict[Severity, int] = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}

_SUFFIX_MULT: dict[str, float] = {
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "m": 1e6,
    "mm": 1e6,
    "million": 1e6,
    "k": 1e3,
    "thousand": 1e3,
}
_NUMBER_RE = re.compile(
    r"(?<![\w.])(-)?\$?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(trillion|billion|million|thousand|tn|bn|mm|k|t|b|m)?(%)?",
    re.IGNORECASE,
)

_POSITIVE_WORDS = {
    "increase",
    "increased",
    "increasing",
    "grew",
    "growth",
    "grow",
    "rose",
    "rising",
    "up",
    "higher",
    "expanded",
    "expansion",
    "improved",
    "improving",
    "gain",
    "gained",
    "strengthened",
    "accelerated",
}
_NEGATIVE_WORDS = {
    "decrease",
    "decreased",
    "decreasing",
    "decline",
    "declined",
    "declining",
    "fell",
    "falling",
    "down",
    "lower",
    "contracted",
    "contraction",
    "worsened",
    "worsening",
    "shrank",
    "shrinking",
    "weakened",
    "drop",
    "dropped",
    "decelerated",
}


def parse_figures(text: str) -> list[float]:
    """Extract numeric figures from free text, handling "$245.1B", "245,122 million" and "15.7%"."""
    out: list[float] = []
    for sign, num, suffix, pct in _NUMBER_RE.findall(text):
        if not num:
            continue
        value = float(num.replace(",", ""))
        if sign:
            value = -value
        if pct:
            value /= 100.0
        elif suffix:
            value *= _SUFFIX_MULT[suffix.lower()]
        out.append(value)
    return out


def within_tolerance(value: float, target: float, rel: float = _NUMBER_TOLERANCE) -> bool:
    if target == 0:
        return abs(value) < 1e-9
    return abs(value - target) / abs(target) <= rel


def _direction(text: str) -> str | None:
    words = set(re.findall(r"[a-z']+", text.lower()))
    has_pos = bool(words & _POSITIVE_WORDS)
    has_neg = bool(words & _NEGATIVE_WORDS)
    if has_pos and not has_neg:
        return "up"
    if has_neg and not has_pos:
        return "down"
    return None


def _check_hallucinated_evidence(state: ResearchState) -> list[CriticIssue]:
    """Any evidence id a finding cites must actually exist in this run's evidence store."""
    issues: list[CriticIssue] = []
    for f in state.findings():
        for eid in f.evidence_ids:
            if eid not in state.evidence:
                issues.append(
                    CriticIssue(
                        agent=f.agent,
                        finding_id=f.id,
                        issue_type=CriticIssueType.HALLUCINATION,
                        severity=Severity.HIGH,
                        description=f"cites evidence id {eid!r} which does not exist in this run's evidence store",
                        suggested_fix="Remove the citation or cite evidence that was actually retrieved.",
                    )
                )
    return issues


def _check_missing_fact_evidence(state: ResearchState) -> list[CriticIssue]:
    """A FACT finding must carry at least one evidence id."""
    issues: list[CriticIssue] = []
    for f in state.findings():
        if f.kind == FindingKind.FACT and not f.evidence_ids and f.status != FindingStatus.REJECTED:
            issues.append(
                CriticIssue(
                    agent=f.agent,
                    finding_id=f.id,
                    issue_type=CriticIssueType.UNSUPPORTED_CLAIM,
                    severity=Severity.MEDIUM,
                    description="fact claim has no supporting evidence id",
                    suggested_fix="Cite the evidence this fact was drawn from, or reclassify as interpretation.",
                )
            )
    return issues


def _check_calculated_numbers(state: ResearchState) -> list[CriticIssue]:
    """A CALCULATED finding's stated figure must agree with the metrics table within 1%."""
    issues: list[CriticIssue] = []
    if not state.metrics:
        return issues
    for f in state.findings():
        if f.kind != FindingKind.CALCULATED or not f.metric_refs:
            continue
        parsed = parse_figures(f.claim)
        if not parsed:
            continue
        bad: list[tuple[str, float]] = []
        for ref in f.metric_refs:
            mv = state.metrics.values.get(ref)
            if mv is None or mv.value is None:
                continue
            if not any(within_tolerance(p, mv.value) for p in parsed):
                bad.append((ref, mv.value))
        if bad:
            desc = "; ".join(
                f"{ref} = {val:g} per the metrics table, but the claim states a different figure" for ref, val in bad
            )
            issues.append(
                CriticIssue(
                    agent=f.agent,
                    finding_id=f.id,
                    issue_type=CriticIssueType.INCONSISTENT_FIGURE,
                    severity=Severity.HIGH,
                    description=desc,
                    suggested_fix="Restate the figure to match the computed metric value exactly.",
                )
            )
    return issues


def _check_stale_recent_developments(
    state: ResearchState, max_age_days: int = STALE_RECENT_DEVELOPMENTS_DAYS
) -> list[CriticIssue]:
    """A RECENT_DEVELOPMENTS claim citing a source older than ~400 days is probably stale."""
    issues: list[CriticIssue] = []
    today = utcnow().date()
    for f in state.findings():
        if f.section != ReportSection.RECENT_DEVELOPMENTS:
            continue
        for eid in f.evidence_ids:
            ev = state.evidence.get(eid)
            if ev is None:
                continue
            src = state.sources.get(ev.source_id)
            if src is None or src.published_at is None:
                continue
            age_days = (today - src.published_at).days
            if age_days > max_age_days:
                issues.append(
                    CriticIssue(
                        agent=f.agent,
                        finding_id=f.id,
                        issue_type=CriticIssueType.STALE_INFORMATION,
                        severity=Severity.MEDIUM,
                        description=(
                            f"cites a source published {age_days} days ago (> {max_age_days}d) for a "
                            "'recent developments' claim"
                        ),
                        suggested_fix="Refresh with a more recent source or move this out of Recent Developments.",
                    )
                )
                break
    return issues


def _check_near_duplicates(state: ResearchState) -> list[CriticIssue]:
    """Flag near-identical claims made by different agents (each agent's own duplicates are already deduped)."""
    issues: list[CriticIssue] = []
    findings = state.findings()
    seen: list[tuple[int, str]] = []
    for i, f in enumerate(findings):
        norm = " ".join(f.claim.lower().split())
        for j, prior_norm in seen:
            other = findings[j]
            if other.agent == f.agent:
                continue
            if difflib.SequenceMatcher(None, norm, prior_norm).ratio() >= _DUPLICATE_SIMILARITY:
                issues.append(
                    CriticIssue(
                        agent=f.agent,
                        finding_id=f.id,
                        issue_type=CriticIssueType.DUPLICATION,
                        severity=Severity.MEDIUM,
                        description=f"near-duplicate of a claim by {other.agent.value}: {other.claim[:120]!r}",
                        suggested_fix="Remove the redundant claim or cross-reference the original.",
                    )
                )
                break
        seen.append((i, norm))
    return issues


def _check_contradictions(state: ResearchState) -> list[CriticIssue]:
    """Flag findings that disagree on the direction of the same metric (e.g. "revenue grew" vs "declined")."""
    issues: list[CriticIssue] = []
    by_ref: dict[str, list[Finding]] = defaultdict(list)
    for f in state.findings():
        for ref in f.metric_refs:
            by_ref[ref].append(f)
    for ref, group in by_ref.items():
        directions = {f.id: _direction(f.claim) for f in group}
        agents_up = {f.agent for f in group if directions[f.id] == "up"}
        agents_down = {f.agent for f in group if directions[f.id] == "down"}
        if agents_up and agents_down:
            for f in group:
                if directions[f.id] in ("up", "down"):
                    issues.append(
                        CriticIssue(
                            agent=f.agent,
                            finding_id=f.id,
                            issue_type=CriticIssueType.CONTRADICTION,
                            severity=Severity.HIGH,
                            description=f"claims about {ref} disagree on direction across agents",
                            suggested_fix="Reconcile the conflicting directional claims before publishing.",
                        )
                    )
    return issues


def _check_prevalidated_unverified(state: ResearchState, existing_issues: list[CriticIssue]) -> list[CriticIssue]:
    """Surface findings validation already marked UNVERIFIED (citations stripped) that no other check caught."""
    already_flagged = {i.finding_id for i in existing_issues if i.finding_id}
    issues: list[CriticIssue] = []
    for f in state.findings():
        if f.status == FindingStatus.UNVERIFIED and f.id not in already_flagged:
            issues.append(
                CriticIssue(
                    agent=f.agent,
                    finding_id=f.id,
                    issue_type=CriticIssueType.MISSING_CITATION,
                    severity=Severity.MEDIUM,
                    description="already marked unverified: citations were stripped during platform validation",
                    suggested_fix="Add supporting evidence or metric refs, or leave it as an open question.",
                )
            )
    return issues


_DETERMINISTIC_CHECKS: tuple[tuple[str, Any], ...] = (
    ("hallucinated_evidence", _check_hallucinated_evidence),
    ("missing_fact_evidence", _check_missing_fact_evidence),
    ("calculated_numbers", _check_calculated_numbers),
    ("stale_recent_developments", _check_stale_recent_developments),
    ("near_duplicates", _check_near_duplicates),
    ("contradictions", _check_contradictions),
)


class LLMCriticIssue(BaseModel):
    agent: AgentName
    finding_id: str | None = None
    issue_type: CriticIssueType
    severity: Severity
    description: str = Field(min_length=1, max_length=1000)
    suggested_fix: str | None = None


class LLMCriticFindings(BaseModel):
    summary: str = ""
    issues: list[LLMCriticIssue] = Field(default_factory=list, max_length=40)


class Critic(BaseAgent):
    name: ClassVar[AgentName] = AgentName.CRITIC
    role: ClassVar[str] = "Critic"
    mission: ClassVar[str] = (
        "Validates every finding against its evidence and the deterministically computed metrics table. "
        "Runs cheap, reliable checks first, then adds LLM judgement for unsupported claims and weak "
        "assumptions. Never lets a fabricated, stale or self-contradictory claim reach the report."
    )
    tier: ClassVar[LLMTier] = "critic"
    allowed_tools: ClassVar[frozenset[str]] = frozenset()

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:  # pragma: no cover
        raise NotImplementedError("Critic is invoked via review(), not run()/execute()")

    async def review(self, state: ResearchState) -> CriticResult:
        checks_run = [name for name, _ in _DETERMINISTIC_CHECKS]
        issues: list[CriticIssue] = []
        for _, check in _DETERMINISTIC_CHECKS:
            issues += check(state)
        issues += _check_prevalidated_unverified(state, issues)
        checks_run.append("prevalidated_unverified")

        usage: list[LLMUsage] = []
        if self.generative:
            llm_issues, usage = await self._llm_pass(state)
            issues += llm_issues
            checks_run.append("llm_pass")

        updated_outputs, rework_notes, reviews = self._apply_issues(state, issues)
        has_high = any(i.severity == Severity.HIGH for i in issues)
        can_loop = state.revision_round < self.deps.settings.max_revision_rounds
        if has_high and can_loop:
            overall = Verdict.NEEDS_REVISION
        elif has_high:
            overall = Verdict.REJECTED
        else:
            overall = Verdict.APPROVED

        review_obj = CriticReview(
            round=state.revision_round,
            overall_verdict=overall,
            summary=_summarize(issues, overall),
            reviews=reviews,
            checks_run=checks_run,
        )
        return CriticResult(
            review=review_obj, updated_outputs=updated_outputs, rework_notes=rework_notes, tool_calls=[], usage=usage
        )

    async def _llm_pass(self, state: ResearchState) -> tuple[list[CriticIssue], list[LLMUsage]]:
        ctx = self.new_context(state)
        findings_by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in state.findings():
            findings_by_agent[f.agent.value].append(
                {
                    "finding_id": f.id,
                    "claim": f.claim,
                    "kind": f.kind.value,
                    "section": f.section.value,
                    "evidence_ids": f.evidence_ids,
                    "metric_refs": f.metric_refs,
                    "status": f.status.value,
                }
            )
        context = {"findings_by_agent": dict(findings_by_agent)}
        evidence = list(state.evidence.values())
        task = (
            "Review each agent's findings against its cited evidence (below) and the metrics context. Flag "
            "unsupported or hallucinated claims and weak assumptions that a purely mechanical check would "
            "miss. Only reference finding_id values that appear in findings_by_agent above; leave finding_id "
            "null for a general observation."
        )
        try:
            result = await self.llm_structured(
                ctx, task=task, schema=LLMCriticFindings, evidence=evidence, sources=state.sources, context=context
            )
        except LLMOutputError:
            log.warning("critic_llm_pass_failed", session_id=state.session_id)
            return [], self.drain_usage()
        usage = self.drain_usage()
        known_ids = {f.id for f in state.findings()}
        issues = [
            CriticIssue(
                agent=i.agent,
                finding_id=i.finding_id,
                issue_type=i.issue_type,
                severity=i.severity,
                description=i.description,
                suggested_fix=i.suggested_fix,
            )
            for i in result.issues
            if i.finding_id is None or i.finding_id in known_ids
        ]
        return issues, usage

    def _apply_issues(
        self, state: ResearchState, issues: list[CriticIssue]
    ) -> tuple[dict[str, AgentOutput], dict[str, str], list[SectionReview]]:
        worst: dict[str, Severity] = {}
        for issue in issues:
            if issue.finding_id is None:
                continue
            current = worst.get(issue.finding_id)
            if current is None or _SEVERITY_RANK[issue.severity] > _SEVERITY_RANK[current]:
                worst[issue.finding_id] = issue.severity

        updated_outputs: dict[str, AgentOutput] = {}
        for agent_str, out in state.outputs.items():
            new_findings: list[Finding] = []
            changed = False
            for f in out.findings:
                sev = worst.get(f.id)
                new_status = f.status
                if sev == Severity.HIGH:
                    new_status = FindingStatus.REJECTED
                elif sev == Severity.MEDIUM and f.status != FindingStatus.REJECTED:
                    new_status = FindingStatus.UNVERIFIED
                if new_status != f.status:
                    changed = True
                    new_findings.append(f.model_copy(update={"status": new_status}))
                else:
                    new_findings.append(f)
            if changed:
                updated_outputs[agent_str] = out.model_copy(update={"findings": new_findings})

        agent_issues: dict[AgentName, list[CriticIssue]] = defaultdict(list)
        agent_has_high: dict[AgentName, bool] = defaultdict(bool)
        for issue in issues:
            agent_issues[issue.agent].append(issue)
            if issue.severity == Severity.HIGH:
                agent_has_high[issue.agent] = True

        can_loop = state.revision_round < self.deps.settings.max_revision_rounds
        reviews: list[SectionReview] = []
        rework_notes: dict[str, str] = {}
        for agent_str in state.outputs:
            agent = AgentName(agent_str)
            my_issues = agent_issues.get(agent, [])
            if agent_has_high.get(agent) and can_loop:
                verdict = Verdict.NEEDS_REVISION
            elif agent_has_high.get(agent):
                verdict = Verdict.REJECTED
            else:
                verdict = Verdict.APPROVED
            reviews.append(SectionReview(agent=agent, verdict=verdict, issues=my_issues))
            if verdict != Verdict.APPROVED:
                high_notes = "; ".join(i.description for i in my_issues if i.severity == Severity.HIGH)
                rework_notes[agent_str] = high_notes or "critic flagged high-severity issues; see review for detail."
        return updated_outputs, rework_notes, reviews


def _summarize(issues: list[CriticIssue], overall: Verdict) -> str:
    if not issues:
        return "All findings are supported by real evidence or computed metrics; no issues found."
    counts: dict[Severity, int] = defaultdict(int)
    for i in issues:
        counts[i.severity] += 1
    parts = [f"{counts[s]} {s.value}" for s in (Severity.HIGH, Severity.MEDIUM, Severity.LOW) if counts[s]]
    return f"Found {len(issues)} issue(s) ({', '.join(parts)}); overall verdict: {overall.value}."
