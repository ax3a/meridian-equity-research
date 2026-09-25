from __future__ import annotations

from meridian.schemas.citations import Evidence, Source
from meridian.schemas.enums import SourceKind
from meridian.tools.evidence import LookupEvidenceInput, LookupEvidenceTool


async def test_lookup_evidence_resolves_from_ledger(make_ctx):
    ctx = make_ctx()
    source = Source.make(
        kind=SourceKind.XBRL_FACTS,
        title="Test Source",
        provider="sec_edgar",
        publisher="U.S. SEC EDGAR",
        url="https://sec.gov/x",
    )
    evidence = Evidence.make(source_id=source.id, text="revenue was 100")
    ctx.ledger.add_source(source)
    ctx.ledger.add_evidence(evidence)

    output = await LookupEvidenceTool().run(LookupEvidenceInput(evidence_ids=[evidence.id]), ctx)
    assert output.evidence[0].found is True
    assert output.evidence[0].text == "revenue was 100"
    assert output.evidence[0].publisher == "U.S. SEC EDGAR"


async def test_lookup_evidence_resolves_from_known_state(make_ctx):
    ctx = make_ctx()
    source = Source.make(
        kind=SourceKind.NEWS, title="Article", provider="gdelt", publisher="reuters.com", url="https://reuters.com/x"
    )
    evidence = Evidence.make(source_id=source.id, text="headline text")
    ctx.known_sources[source.id] = source
    ctx.known_evidence[evidence.id] = evidence

    output = await LookupEvidenceTool().run(LookupEvidenceInput(evidence_ids=[evidence.id]), ctx)
    assert output.evidence[0].found is True
    assert output.evidence[0].publisher == "reuters.com"


async def test_lookup_evidence_reports_not_found(make_ctx):
    ctx = make_ctx()
    output = await LookupEvidenceTool().run(LookupEvidenceInput(evidence_ids=["ev_doesnotexist"]), ctx)
    assert output.evidence[0].found is False
    summary = LookupEvidenceTool().summarize(output)
    assert "NOT FOUND" in summary
