"""The report writer: composes the final `ResearchReport` strictly from approved/unverified findings.

REJECTED findings never reach the report. UNVERIFIED findings only ever appear in OPEN_QUESTIONS, visibly
marked. In generative mode the writer-tier LLM drafts each section's prose constrained to the findings
supplied to it and must cite `[ev_xxx]` markers; any marker that doesn't resolve to a real evidence id in
this run's evidence store is rejected and the section is retried, falling back to deterministic composition
if it still can't produce a clean draft. In offline mode (or on that fallback) prose is composed directly
from the finding claims themselves, so every citation is trivially real.

The Executive Summary is a synthesis over already-approved findings from every other section (company
overview, headline financials pulled straight from `state.metrics`, valuation, the strongest bull/bear
points, and the top risks) rather than one agent's raw output. It reuses existing finding ids for
traceability and never mints new findings; when nothing was approved at all it says so explicitly instead
of rendering an empty section or invented filler.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import ClassVar

from pydantic import BaseModel, Field

from meridian.agents import report_assembly
from meridian.agents.base import AgentDraft, BaseAgent
from meridian.agents.claims import describe_claim
from meridian.agents.contracts import WriterResult
from meridian.agents.critic import parse_figures, within_tolerance
from meridian.core.config import LLMTier
from meridian.core.errors import LLMOutputError, ValidationFailedError
from meridian.core.ids import new_id, utcnow
from meridian.core.logging import get_logger
from meridian.schemas.enums import AgentName, FindingKind, FindingStatus, ReportSection
from meridian.schemas.financials import MetricValue
from meridian.schemas.findings import Finding
from meridian.schemas.report import ReportParagraph, ReportSectionContent, ResearchReport
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import ToolContext

log = get_logger(__name__)

_MARKER_RE = re.compile(r"\[(ev_[0-9a-f]+)\]")

_NO_FINDINGS_SENTENCE = "This run produced no approved findings, so no executive summary could be generated."

_HEADLINE_METRIC_LABELS: dict[str, str] = {
    "revenue": "revenue of",
    "revenue_growth": "revenue growth of",
    "operating_margin": "operating margin of",
    "net_margin": "net margin of",
    "free_cash_flow": "free cash flow of",
}

# Section order for the generic per-section writer. EXECUTIVE_SUMMARY is handled separately (see `write`)
# since it synthesizes across every other section rather than rendering one agent's findings.
_SECTION_ORDER: tuple[ReportSection, ...] = (
    ReportSection.COMPANY_OVERVIEW,
    ReportSection.BUSINESS_MODEL,
    ReportSection.FINANCIAL_PERFORMANCE,
    ReportSection.FINANCIAL_TRENDS,
    ReportSection.KEY_RATIOS,
    ReportSection.RECENT_DEVELOPMENTS,
    ReportSection.INDUSTRY_COMPETITION,
    ReportSection.MACRO,
    ReportSection.VALUATION,
    ReportSection.BULL_CASE,
    ReportSection.BEAR_CASE,
    ReportSection.KEY_RISKS,
    ReportSection.CATALYSTS,
)

_SECTION_TITLES: dict[ReportSection, str] = {
    ReportSection.EXECUTIVE_SUMMARY: "Executive Summary",
    ReportSection.COMPANY_OVERVIEW: "Company Overview",
    ReportSection.BUSINESS_MODEL: "Business Model",
    ReportSection.FINANCIAL_PERFORMANCE: "Financial Performance",
    ReportSection.FINANCIAL_TRENDS: "Financial Trends",
    ReportSection.KEY_RATIOS: "Key Ratios",
    ReportSection.RECENT_DEVELOPMENTS: "Recent Developments",
    ReportSection.INDUSTRY_COMPETITION: "Industry & Competition",
    ReportSection.MACRO: "Macro Environment",
    ReportSection.VALUATION: "Valuation",
    ReportSection.BULL_CASE: "Bull Case",
    ReportSection.BEAR_CASE: "Bear Case",
    ReportSection.KEY_RISKS: "Key Risks",
    ReportSection.CATALYSTS: "Catalysts",
    ReportSection.OPEN_QUESTIONS: "Open Questions",
}


class DraftParagraph(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    kind: FindingKind


class SectionDraft(BaseModel):
    title: str = ""
    paragraphs: list[DraftParagraph] = Field(default_factory=list, max_length=20)


class ReportWriter(BaseAgent):
    name: ClassVar[AgentName] = AgentName.REPORT_WRITER
    role: ClassVar[str] = "Report Writer"
    mission: ClassVar[str] = (
        "Writes the final research report strictly from approved findings. Every fact or calculated figure "
        "must carry a citation marker that resolves to real evidence. Unverified content is confined to "
        "Open Questions and clearly marked. Never invents content beyond what the findings support."
    )
    tier: ClassVar[LLMTier] = "writer"
    allowed_tools: ClassVar[frozenset[str]] = frozenset()
    max_section_retries: ClassVar[int] = 2

    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft:  # pragma: no cover
        raise NotImplementedError("ReportWriter is invoked via write(), not run()/execute()")

    async def write(self, state: ResearchState) -> WriterResult:
        if state.company is None:
            raise ValidationFailedError("cannot write a report before the company has been resolved")
        ctx = self.new_context(state)

        approved = [f for f in state.findings() if f.status == FindingStatus.APPROVED]
        unverified = [f for f in state.findings() if f.status == FindingStatus.UNVERIFIED]

        by_section: dict[ReportSection, list[Finding]] = defaultdict(list)
        for f in approved:
            by_section[f.section].append(f)

        sections: list[ReportSectionContent] = [await self._write_executive_summary(ctx, state, approved)]
        for section in _SECTION_ORDER:
            findings = by_section.get(section, [])
            if not findings:
                continue
            sections.append(await self._write_section(ctx, state, section, findings))

        if unverified:
            oq_paragraphs = [self._offline_paragraph(f, unverified=True) for f in unverified]
            sections.append(
                ReportSectionContent(
                    section=ReportSection.OPEN_QUESTIONS,
                    title=_SECTION_TITLES[ReportSection.OPEN_QUESTIONS],
                    paragraphs=oq_paragraphs,
                )
            )

        cited_ids: set[str] = set()
        for s in sections:
            for p in s.paragraphs:
                cited_ids.update(p.evidence_ids)
        citations = report_assembly.resolve_citations(cited_ids, state)

        report = ResearchReport(
            id=new_id("report"),
            session_id=state.session_id,
            version=1,
            company=state.company,
            title=f"{state.company.name} ({state.company.ticker}) Equity Research",
            generated_at=utcnow(),
            llm_mode=self.deps.settings.llm_mode,
            data_mode=self.deps.settings.data_mode,
            uses_snapshot_data=state.uses_snapshot_data(),
            sections=sections,
            key_metrics=report_assembly.build_key_metrics(state.metrics),
            charts=report_assembly.build_chart_series(state.metrics),
            valuation=state.valuation,
            peers=state.peers,
            citations=citations,
            unverified_claims=len(unverified),
            critic_rounds=state.revision_round,
        )
        return WriterResult(report=report, usage=self.drain_usage())

    # ---- executive summary (synthesis across sections) --------------------------------------------------------
    async def _write_executive_summary(
        self, ctx: ToolContext, state: ResearchState, approved: list[Finding]
    ) -> ReportSectionContent:
        if not approved:
            return ReportSectionContent(
                section=ReportSection.EXECUTIVE_SUMMARY,
                title=_SECTION_TITLES[ReportSection.EXECUTIVE_SUMMARY],
                paragraphs=[ReportParagraph(text=_NO_FINDINGS_SENTENCE, kind=FindingKind.FACT)],
            )
        if self.generative:
            content = await self._write_executive_summary_generative(ctx, state, approved)
            if content is not None:
                return content
            log.warning("writer_section_fallback_offline", section=ReportSection.EXECUTIVE_SUMMARY.value)
        return self._build_executive_summary_offline(state, approved)

    def _executive_summary_candidates(self, approved: list[Finding]) -> list[Finding]:
        """The bounded set of findings the summary may draw from: one best pick per category."""
        company = report_assembly.pick_best_finding(
            [f for f in approved if f.agent == AgentName.COMPANY and f.section == ReportSection.COMPANY_OVERVIEW]
        )
        financials = report_assembly.pick_top_findings(
            [f for f in approved if f.agent == AgentName.FINANCIALS and f.kind == FindingKind.CALCULATED], limit=4
        )
        valuation = report_assembly.pick_best_finding(
            [f for f in approved if f.agent == AgentName.VALUATION],
            prefer_kinds=(FindingKind.CALCULATED,),
        )
        bull = report_assembly.pick_best_finding([f for f in approved if f.section == ReportSection.BULL_CASE])
        bear = report_assembly.pick_best_finding([f for f in approved if f.section == ReportSection.BEAR_CASE])
        risks = report_assembly.pick_top_findings(
            [f for f in approved if f.section == ReportSection.KEY_RISKS], limit=2
        )

        picks = [f for f in (company, valuation, bull, bear) if f is not None]
        picks.extend(financials)
        picks.extend(risks)
        return picks

    def _build_executive_summary_offline(self, state: ResearchState, approved: list[Finding]) -> ReportSectionContent:
        paragraphs: list[ReportParagraph] = []
        company_name = state.company.name if state.company else "The company"
        ticker = state.company.ticker if state.company else ""

        company_finding = report_assembly.pick_best_finding(
            [f for f in approved if f.agent == AgentName.COMPANY and f.section == ReportSection.COMPANY_OVERVIEW]
        )
        if company_finding is not None:
            markers = "".join(f" [{eid}]" for eid in company_finding.evidence_ids)
            paragraphs.append(
                ReportParagraph(
                    text=f"{company_name} ({ticker}): {company_finding.claim.rstrip('.')}.{markers}",
                    kind=company_finding.kind,
                    evidence_ids=list(company_finding.evidence_ids),
                    metric_refs=list(company_finding.metric_refs),
                    finding_ids=[company_finding.id],
                )
            )
        else:
            paragraphs.append(ReportParagraph(text=f"{company_name} ({ticker}).", kind=FindingKind.FACT))

        fin_para = self._financial_headline_paragraph(state, approved)
        if fin_para is not None:
            paragraphs.append(fin_para)

        valuation_finding = report_assembly.pick_best_finding(
            [f for f in approved if f.agent == AgentName.VALUATION], prefer_kinds=(FindingKind.CALCULATED,)
        )
        if valuation_finding is not None:
            paragraphs.append(self._reused_paragraph("Valuation", valuation_finding))

        bull_finding = report_assembly.pick_best_finding([f for f in approved if f.section == ReportSection.BULL_CASE])
        if bull_finding is not None:
            paragraphs.append(self._reused_paragraph("Bull case", bull_finding))

        bear_finding = report_assembly.pick_best_finding([f for f in approved if f.section == ReportSection.BEAR_CASE])
        if bear_finding is not None:
            paragraphs.append(self._reused_paragraph("Bear case", bear_finding))

        # The bear case is usually built from a risk factor, so skip any risk that would restate the
        # passage already quoted above -- a summary that says the same thing twice wastes the reader's time.
        used_evidence = {eid for p in paragraphs for eid in p.evidence_ids}
        risk_pool = [
            f for f in approved if f.section == ReportSection.KEY_RISKS and not (set(f.evidence_ids) & used_evidence)
        ]
        for risk_finding in report_assembly.pick_top_findings(risk_pool, limit=2):
            paragraphs.append(self._reused_paragraph("Key risk", risk_finding))

        return ReportSectionContent(
            section=ReportSection.EXECUTIVE_SUMMARY,
            title=_SECTION_TITLES[ReportSection.EXECUTIVE_SUMMARY],
            paragraphs=paragraphs,
        )

    def _reused_paragraph(self, label: str, f: Finding) -> ReportParagraph:
        """Wrap an already-approved finding's own claim/citations as one executive-summary sentence.

        Reuses the finding's real evidence_ids/metric_refs/id rather than minting anything new, so the
        sentence is exactly as traceable and honest (same `kind`) as the finding it came from. Evidence ids
        are appended as visible `[ev_xxx]` markers, matching how every other section cites its sources.
        """
        markers = "".join(f" [{eid}]" for eid in f.evidence_ids)
        # describe_claim avoids "Bull case: Bull case: ..." when the finding already carries the label.
        sentence = describe_claim(label, f.claim, max_chars=320).rstrip(".")
        return ReportParagraph(
            text=f"{sentence}.{markers}",
            kind=f.kind,
            evidence_ids=list(f.evidence_ids),
            metric_refs=list(f.metric_refs),
            finding_ids=[f.id],
        )

    def _financial_headline_paragraph(self, state: ResearchState, approved: list[Finding]) -> ReportParagraph | None:
        """The headline revenue/margin/FCF figures for the latest period, read straight off `state.metrics`."""
        metrics = state.metrics
        period = report_assembly.latest_metrics_period(metrics)
        if metrics is None or period is None:
            return None

        picked_refs: list[str] = []
        phrases: list[str] = []
        margin_key_used = False
        for key in ("revenue", "revenue_growth", "operating_margin", "net_margin", "free_cash_flow"):
            if key == "net_margin" and margin_key_used:
                continue
            mv = metrics.get(period, key)
            if mv is None or mv.value is None:
                continue
            picked_refs.append(mv.ref)
            phrases.append(f"{_HEADLINE_METRIC_LABELS[key]} {report_assembly.format_metric_value(mv.value, mv.unit)}")
            if key == "operating_margin":
                margin_key_used = True
        if not picked_refs:
            return None

        text = f"For {period}, " + ", ".join(phrases) + "."
        finding_ids = list(
            dict.fromkeys(
                f.id for f in approved if f.agent == AgentName.FINANCIALS and set(f.metric_refs) & set(picked_refs)
            )
        )
        return ReportParagraph(text=text, kind=FindingKind.CALCULATED, metric_refs=picked_refs, finding_ids=finding_ids)

    async def _write_executive_summary_generative(
        self, ctx: ToolContext, state: ResearchState, approved: list[Finding]
    ) -> ReportSectionContent | None:
        candidates = self._executive_summary_candidates(approved)
        evidence_ids = {eid for f in candidates for eid in f.evidence_ids}
        evidence = [state.evidence[eid] for eid in evidence_ids if eid in state.evidence]
        known_metric_values = list(state.metrics.values.values()) if state.metrics else []
        context = {
            "findings": [
                {
                    "finding_id": f.id,
                    "claim": f.claim,
                    "kind": f.kind.value,
                    "section": f.section.value,
                    "evidence_ids": f.evidence_ids,
                    "metric_refs": f.metric_refs,
                }
                for f in candidates
            ],
            "metrics": {mv.ref: mv.value for mv in known_metric_values},
        }
        base_task = (
            "Write the Executive Summary: 4-6 sentences covering what the company does, headline financials, "
            "the valuation headline if present, the strongest bull point, the strongest bear point, and the "
            "top risk(s) -- using ONLY the findings and metrics listed in context. Every sentence with a fact "
            "or calculated figure must end with a citation marker like [ev_xxx] using an evidence id that "
            "actually appears in the evidence block below. Any number you write must match a value in the "
            "metrics context (rounding is fine). Do not invent ids, figures or claims beyond what is given."
        )
        known_ids = set(state.evidence)
        error_note = ""
        for _ in range(self.max_section_retries + 1):
            task = base_task if not error_note else f"{base_task}\n\nYour previous attempt was rejected: {error_note}"
            try:
                draft = await self.llm_structured(
                    ctx, task=task, schema=SectionDraft, evidence=evidence, sources=state.sources, context=context
                )
            except LLMOutputError:
                return None
            bad_markers = {m for p in draft.paragraphs for m in _MARKER_RE.findall(p.text) if m not in known_ids}
            bad_numbers = _numbers_not_grounded_in_metrics(draft.paragraphs, known_metric_values)
            if not bad_markers and not bad_numbers:
                paragraphs = [self._paragraph_from_draft(p, candidates) for p in draft.paragraphs]
                return ReportSectionContent(
                    section=ReportSection.EXECUTIVE_SUMMARY,
                    title=draft.title or _SECTION_TITLES[ReportSection.EXECUTIVE_SUMMARY],
                    paragraphs=paragraphs,
                )
            problems = []
            if bad_markers:
                problems.append(f"marker(s) {sorted(bad_markers)} do not resolve to any real evidence id")
            if bad_numbers:
                problems.append(f"figure(s) {bad_numbers} do not match any value in the metrics table")
            error_note = "; ".join(problems) + ". Remove or fix them."
        return None

    # ---- per-section composition -----------------------------------------------------------------------------
    async def _write_section(
        self, ctx: ToolContext, state: ResearchState, section: ReportSection, findings: list[Finding]
    ) -> ReportSectionContent:
        if self.generative:
            content = await self._write_section_generative(ctx, state, section, findings)
            if content is not None:
                return content
            log.warning("writer_section_fallback_offline", section=section.value)
        return self._write_section_offline(section, findings)

    def _write_section_offline(self, section: ReportSection, findings: list[Finding]) -> ReportSectionContent:
        paragraphs = [self._offline_paragraph(f) for f in findings]
        return ReportSectionContent(section=section, title=_SECTION_TITLES[section], paragraphs=paragraphs)

    def _offline_paragraph(self, f: Finding, *, unverified: bool | None = None) -> ReportParagraph:
        is_unverified = (f.status == FindingStatus.UNVERIFIED) if unverified is None else unverified
        markers = "".join(f" [{eid}]" for eid in f.evidence_ids)
        text = f.claim.rstrip(".") + "." + markers
        if is_unverified:
            text += " (unverified)"
        return ReportParagraph(
            text=text,
            kind=f.kind,
            evidence_ids=list(f.evidence_ids),
            metric_refs=list(f.metric_refs),
            finding_ids=[f.id],
            unverified=is_unverified,
        )

    async def _write_section_generative(
        self, ctx: ToolContext, state: ResearchState, section: ReportSection, findings: list[Finding]
    ) -> ReportSectionContent | None:
        evidence_ids = {eid for f in findings for eid in f.evidence_ids}
        evidence = [state.evidence[eid] for eid in evidence_ids if eid in state.evidence]
        context = {
            "section": section.value,
            "findings": [
                {
                    "finding_id": f.id,
                    "claim": f.claim,
                    "kind": f.kind.value,
                    "evidence_ids": f.evidence_ids,
                    "metric_refs": f.metric_refs,
                }
                for f in findings
            ],
        }
        base_task = (
            f"Write the '{_SECTION_TITLES[section]}' section of the research report using ONLY the findings "
            "listed in context. Every sentence carrying a fact or calculated figure must end with a citation "
            "marker like [ev_xxx] using an evidence id that actually appears in the evidence block below. Do "
            "not invent ids, figures or claims beyond what the findings support."
        )
        known_ids = set(state.evidence)
        error_note = ""
        for _ in range(self.max_section_retries + 1):
            task = base_task if not error_note else f"{base_task}\n\nYour previous attempt was rejected: {error_note}"
            try:
                draft = await self.llm_structured(
                    ctx, task=task, schema=SectionDraft, evidence=evidence, sources=state.sources, context=context
                )
            except LLMOutputError:
                return None
            bad_markers = {m for p in draft.paragraphs for m in _MARKER_RE.findall(p.text) if m not in known_ids}
            if not bad_markers:
                paragraphs = [self._paragraph_from_draft(p, findings) for p in draft.paragraphs]
                return ReportSectionContent(
                    section=section, title=draft.title or _SECTION_TITLES[section], paragraphs=paragraphs
                )
            error_note = f"marker(s) {sorted(bad_markers)} do not resolve to any real evidence id; remove or fix them."
        return None

    def _paragraph_from_draft(self, p: DraftParagraph, findings: list[Finding]) -> ReportParagraph:
        markers = list(dict.fromkeys(_MARKER_RE.findall(p.text)))
        finding_ids = [f.id for f in findings if any(m in f.evidence_ids for m in markers)]
        metric_refs = [ref for f in findings if f.id in finding_ids for ref in f.metric_refs]
        return ReportParagraph(
            text=p.text,
            kind=p.kind,
            evidence_ids=markers,
            metric_refs=metric_refs,
            finding_ids=finding_ids,
            unverified=False,
        )


def _numbers_not_grounded_in_metrics(paragraphs: list[DraftParagraph], known_values: list[MetricValue]) -> list[float]:
    """Every numeric figure the model wrote must match some value in the metrics table (1% tolerance)."""
    numeric_values = [mv.value for mv in known_values if mv.value is not None]
    bad: list[float] = []
    for p in paragraphs:
        for num in parse_figures(p.text):
            if not any(within_tolerance(num, v) for v in numeric_values):
                bad.append(num)
    return bad
