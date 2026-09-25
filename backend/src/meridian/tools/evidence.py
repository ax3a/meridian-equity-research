"""Citation resolution tool: lookup_evidence.

Lets an agent (or the critic, or bull/bear who only work from evidence already in state) resolve an
evidence id back to its exact quote and source, without re-fetching from a provider. Looks in both the
current call's ledger and `ctx.known_evidence`/`ctx.known_sources` (evidence already accumulated in the
research state from earlier agents).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from meridian.tools.base import Tool, ToolContext


class LookupEvidenceInput(BaseModel):
    evidence_ids: list[str] = Field(min_length=1, max_length=50)


class ResolvedEvidence(BaseModel):
    evidence_id: str
    found: bool
    text: str | None = None
    source_id: str | None = None
    source_title: str | None = None
    publisher: str | None = None
    url: str | None = None
    location: str | None = None
    is_snapshot: bool = False


class LookupEvidenceOutput(BaseModel):
    evidence: list[ResolvedEvidence]


class LookupEvidenceTool(Tool[LookupEvidenceInput, LookupEvidenceOutput]):
    """Resolve evidence ids to their exact quote, source and location."""

    name = "lookup_evidence"
    description = "Resolve one or more evidence ids to their exact quote, source title/publisher and location."
    input_model = LookupEvidenceInput

    async def run(self, args: LookupEvidenceInput, ctx: ToolContext) -> LookupEvidenceOutput:
        resolved: list[ResolvedEvidence] = []
        for eid in args.evidence_ids:
            ev = ctx.evidence(eid)
            if ev is None:
                resolved.append(ResolvedEvidence(evidence_id=eid, found=False))
                continue
            src = ctx.source(ev.source_id)
            resolved.append(
                ResolvedEvidence(
                    evidence_id=eid,
                    found=True,
                    text=ev.text,
                    source_id=ev.source_id,
                    source_title=src.title if src else None,
                    publisher=src.publisher if src else None,
                    url=src.url if src else None,
                    location=ev.locator.describe(),
                    is_snapshot=src.is_snapshot if src else False,
                )
            )
        return LookupEvidenceOutput(evidence=resolved)

    def summarize(self, output: LookupEvidenceOutput) -> str:
        lines = []
        for r in output.evidence:
            if not r.found:
                lines.append(f"{r.evidence_id}: NOT FOUND")
            else:
                lines.append(f"{r.evidence_id} ({r.publisher}, {r.location}): {(r.text or '')[:200]}")
        return "\n".join(lines)[:6000]
