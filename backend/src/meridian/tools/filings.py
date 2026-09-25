"""SEC filing tools: list_filings, index_filings, search_filings, get_filing_section,
get_recent_8k_events.

`search_filings` and `get_filing_section` lazily index a ticker's filings into the RAG retriever the
first time they are asked about it: they probe the retriever first, and only fetch + index the latest
10-K and 10-Q when that probe comes back empty, so a cold research session doesn't need a separate
`index_filings` call before it can search.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from meridian.core.errors import DataNotAvailableError, MeridianError
from meridian.providers.base import FilingRef
from meridian.rag.evidence import chunk_to_evidence
from meridian.rag.types import IndexReport, RetrievedChunk
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.research import CompanyIdentity
from meridian.tools.base import Tool, ToolContext

DEFAULT_FORMS: tuple[str, ...] = ("10-K", "10-Q", "8-K")


class ListFilingsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    forms: list[str] = Field(default_factory=lambda: list(DEFAULT_FORMS))
    limit: int = Field(default=12, ge=1, le=100)


class ListFilingsOutput(BaseModel):
    filings: list[FilingRef]


class ListFilingsTool(Tool[ListFilingsInput, ListFilingsOutput]):
    """List a company's recent SEC filings (10-K/10-Q/8-K by default), newest first."""

    name = "list_filings"
    description = "List a company's recent SEC filings (form, filing date, accession number, URL)."
    input_model = ListFilingsInput

    async def run(self, args: ListFilingsInput, ctx: ToolContext) -> ListFilingsOutput:
        identity = await ctx.providers.directory.resolve(args.ticker)
        result = await ctx.providers.filings.list_filings(identity, tuple(args.forms), args.limit)
        ctx.ledger.absorb(result)
        return ListFilingsOutput(filings=result.data)

    def summarize(self, output: ListFilingsOutput) -> str:
        lines = []
        for f in output.filings:
            items = f" items {','.join(f.items)}" if f.items else ""
            lines.append(f"{f.form} filed {f.filing_date} (accession {f.accession_number}){items}")
        return "\n".join(lines)[:6000]


class IndexFilingsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    forms: list[str] = Field(default_factory=lambda: ["10-K", "10-Q"])
    limit: int = Field(default=3, ge=1, le=10)


class IndexFilingsTool(Tool[IndexFilingsInput, IndexReport]):
    """Fetch, parse and index filings into the RAG store so `search_filings` can find them."""

    name = "index_filings"
    description = "Fetch and index a company's recent filings into the retrieval store for later search."
    input_model = IndexFilingsInput

    async def run(self, args: IndexFilingsInput, ctx: ToolContext) -> IndexReport:
        if ctx.retriever is None:
            raise DataNotAvailableError("no document retriever is configured for this session")
        identity = await ctx.providers.directory.resolve(args.ticker)
        filings_result = await ctx.providers.filings.list_filings(identity, tuple(args.forms), args.limit)
        return await ctx.retriever.ensure_indexed(identity, filings_result.data)

    def summarize(self, output: IndexReport) -> str:
        msg = (
            f"indexed {output.documents_indexed} document(s) ({output.chunks_created} chunks), "
            f"{output.documents_skipped} already indexed"
        )
        if output.failures:
            msg += "; failures: " + "; ".join(output.failures)
        return msg[:6000]


class PassageHit(BaseModel):
    evidence_id: str
    source_id: str
    section: str
    form: str
    filing_date: date
    page: int | None = None
    text: str
    score: float
    injection_flags: list[str] = Field(default_factory=list)


async def _passages_from_chunks(ctx: ToolContext, hits: list[RetrievedChunk]) -> list[PassageHit]:
    passages: list[PassageHit] = []
    for hit in hits:
        source, evidence = chunk_to_evidence(hit.chunk)
        ctx.ledger.add_source(source)
        ctx.ledger.add_evidence(evidence)
        passages.append(
            PassageHit(
                evidence_id=evidence.id,
                source_id=source.id,
                section=hit.chunk.metadata.section,
                form=hit.chunk.metadata.form,
                filing_date=hit.chunk.metadata.filing_date,
                page=hit.chunk.metadata.page,
                text=hit.chunk.text,
                score=hit.score,
                injection_flags=hit.chunk.injection_flags,
            )
        )
    return passages


def _summarize_passages(passages: list[PassageHit]) -> str:
    lines = []
    for p in passages:
        flag_str = f" [FLAGGED: {','.join(p.injection_flags)}]" if p.injection_flags else ""
        lines.append(f"[{p.form} {p.section}] {p.text[:200]}...{flag_str} [{p.evidence_id}]")
    return "\n".join(lines)[:6000]


async def _latest_10k_and_10q(ctx: ToolContext, identity: CompanyIdentity) -> list[FilingRef]:
    refs: list[FilingRef] = []
    for form in ("10-K", "10-Q"):
        try:
            result = await ctx.providers.filings.list_filings(identity, (form,), 1)
        except MeridianError:
            continue
        refs.extend(result.data)
    return refs


async def _search_with_lazy_index(
    ctx: ToolContext,
    identity: CompanyIdentity,
    query: str,
    forms: tuple[str, ...] | None,
    section_keys: tuple[str, ...] | None,
    k: int,
) -> list[RetrievedChunk]:
    if ctx.retriever is None:
        return []
    hits = await ctx.retriever.search(query, ticker=identity.ticker, forms=forms, section_keys=section_keys, k=k)
    if hits:
        return hits
    refs = await _latest_10k_and_10q(ctx, identity)
    if not refs:
        return hits
    await ctx.retriever.ensure_indexed(identity, refs)
    return await ctx.retriever.search(query, ticker=identity.ticker, forms=forms, section_keys=section_keys, k=k)


class SearchFilingsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    query: str = Field(min_length=1, max_length=500)
    forms: list[str] | None = None
    section_keys: list[str] | None = None
    k: int = Field(default=6, ge=1, le=30)


class SearchFilingsOutput(BaseModel):
    passages: list[PassageHit]


class SearchFilingsTool(Tool[SearchFilingsInput, SearchFilingsOutput]):
    """Hybrid (vector + keyword) search over a company's indexed filings."""

    name = "search_filings"
    description = (
        "Search a company's SEC filings (indexing the latest 10-K/10-Q on first use if needed) for "
        "passages relevant to a query. Returns exact excerpts, each with an evidence id to cite."
    )
    input_model = SearchFilingsInput

    async def run(self, args: SearchFilingsInput, ctx: ToolContext) -> SearchFilingsOutput:
        identity = await ctx.providers.directory.resolve(args.ticker)
        hits = await _search_with_lazy_index(
            ctx,
            identity,
            args.query,
            tuple(args.forms) if args.forms else None,
            tuple(args.section_keys) if args.section_keys else None,
            args.k,
        )
        return SearchFilingsOutput(passages=await _passages_from_chunks(ctx, hits))

    def summarize(self, output: SearchFilingsOutput) -> str:
        return _summarize_passages(output.passages)


class GetFilingSectionInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    form: str = "10-K"
    section_key: str = Field(min_length=1, max_length=20)
    k: int = Field(default=8, ge=1, le=30)


class GetFilingSectionOutput(BaseModel):
    passages: list[PassageHit]


class GetFilingSectionTool(Tool[GetFilingSectionInput, GetFilingSectionOutput]):
    """Retrieve chunks from one named section of a filing (e.g. Item 1A Risk Factors)."""

    name = "get_filing_section"
    description = (
        "Retrieve passages from a specific section of a company's filing (e.g. section_key '1A' for "
        "Risk Factors, '7' for MD&A). Indexes the filing on first use if needed."
    )
    input_model = GetFilingSectionInput

    async def run(self, args: GetFilingSectionInput, ctx: ToolContext) -> GetFilingSectionOutput:
        identity = await ctx.providers.directory.resolve(args.ticker)
        hits = await _search_with_lazy_index(ctx, identity, args.section_key, (args.form,), (args.section_key,), args.k)
        return GetFilingSectionOutput(passages=await _passages_from_chunks(ctx, hits))

    def summarize(self, output: GetFilingSectionOutput) -> str:
        return _summarize_passages(output.passages)


class EightKEvent(BaseModel):
    evidence_id: str
    source_id: str
    accession_number: str
    filing_date: date
    items: list[str] = Field(default_factory=list)
    description: str | None = None
    url: str


class GetRecent8kEventsInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    limit: int = Field(default=10, ge=1, le=50)


class GetRecent8kEventsOutput(BaseModel):
    events: list[EightKEvent]


class GetRecent8kEventsTool(Tool[GetRecent8kEventsInput, GetRecent8kEventsOutput]):
    """Recent 8-K current-report filings with their item codes (material events)."""

    name = "get_recent_8k_events"
    description = "List a company's recent 8-K filings with item codes (e.g. 2.02 earnings, 5.02 officer changes)."
    input_model = GetRecent8kEventsInput

    async def run(self, args: GetRecent8kEventsInput, ctx: ToolContext) -> GetRecent8kEventsOutput:
        identity = await ctx.providers.directory.resolve(args.ticker)
        result = await ctx.providers.filings.list_filings(identity, ("8-K",), args.limit)
        events: list[EightKEvent] = []
        for ref in result.data:
            source = Source.make(
                kind=SourceKind.SEC_FILING,
                title=f"{identity.name} 8-K filed {ref.filing_date}",
                provider="sec_edgar",
                publisher="U.S. SEC EDGAR",
                url=ref.url,
                published_at=ref.filing_date,
                metadata={"accession": ref.accession_number, "items": ref.items},
            )
            items_desc = ", ".join(ref.items) if ref.items else "no item codes listed"
            text = (
                f"{identity.name} Form 8-K filed {ref.filing_date} (accession {ref.accession_number}): "
                f"items {items_desc}"
            )
            if ref.description:
                text += f" - {ref.description}"
            evidence = Evidence.make(
                source_id=source.id, text=text, locator=EvidenceLocator(accession_number=ref.accession_number)
            )
            ctx.ledger.add_source(source)
            ctx.ledger.add_evidence(evidence)
            events.append(
                EightKEvent(
                    evidence_id=evidence.id,
                    source_id=source.id,
                    accession_number=ref.accession_number,
                    filing_date=ref.filing_date,
                    items=ref.items,
                    description=ref.description,
                    url=ref.url,
                )
            )
        return GetRecent8kEventsOutput(events=events)

    def summarize(self, output: GetRecent8kEventsOutput) -> str:
        lines = [f"8-K {e.filing_date} items {','.join(e.items) or 'none'} [{e.evidence_id}]" for e in output.events]
        return "\n".join(lines)[:6000]
