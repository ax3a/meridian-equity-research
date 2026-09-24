"""Turns a retrieved `DocumentChunk` into a citable `(Source, Evidence)` pair.

`Source.make` derives a stable id from `(provider, kind, url)`, so every chunk pulled from the same
filing document collapses onto the same `Source` -- one filing, many pieces of evidence. Injection flags
recorded on the chunk (from `security.injection.scan` at index time) are carried straight through onto
the `Evidence`, so downstream prompting/report code can see which quotes came from flagged text.
"""

from __future__ import annotations

from meridian.rag.types import DocumentChunk
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind

PROVIDER = "sec_edgar"
PUBLISHER = "SEC EDGAR"


def chunk_to_evidence(chunk: DocumentChunk) -> tuple[Source, Evidence]:
    meta = chunk.metadata
    source = Source.make(
        kind=SourceKind.SEC_FILING,
        title=meta.document_title,
        provider=PROVIDER,
        publisher=PUBLISHER,
        url=meta.source_url,
        published_at=meta.filing_date,
        is_snapshot=meta.is_snapshot,
        snapshot_date=meta.snapshot_date,
        metadata={
            "ticker": meta.ticker,
            "cik": meta.cik,
            "company": meta.company,
            "form": meta.form,
            "accession_number": meta.accession_number,
        },
    )

    locator = EvidenceLocator(
        section=meta.section,
        page=meta.page,
        accession_number=meta.accession_number,
        chunk_id=chunk.id,
    )
    evidence = Evidence.make(
        source_id=source.id,
        text=chunk.text,
        locator=locator,
        injection_flags=chunk.injection_flags,
    )
    return source, evidence
