from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from meridian.providers.base import FilingRef
from meridian.schemas.research import CompanyIdentity


class ChunkMetadata(BaseModel):
    ticker: str
    cik: str
    company: str
    form: str
    filing_date: date
    accession_number: str
    section: str  # e.g. "Item 1A. Risk Factors"
    section_key: str  # e.g. "1A"
    source_url: str
    document_title: str
    page: int | None = None
    chunk_index: int = 0
    is_snapshot: bool = False
    snapshot_date: date | None = None


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    text: str
    token_count: int
    metadata: ChunkMetadata
    injection_flags: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    chunk: DocumentChunk
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None


class IndexReport(BaseModel):
    documents_indexed: int = 0
    documents_skipped: int = 0  # already present
    chunks_created: int = 0
    failures: list[str] = Field(default_factory=list)


@runtime_checkable
class Retriever(Protocol):
    async def ensure_indexed(self, company: CompanyIdentity, filings: list[FilingRef]) -> IndexReport: ...

    async def search(
        self,
        query: str,
        *,
        ticker: str,
        forms: tuple[str, ...] | None = None,
        section_keys: tuple[str, ...] | None = None,
        k: int = 8,
    ) -> list[RetrievedChunk]: ...
