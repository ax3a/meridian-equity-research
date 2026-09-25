"""`HybridRetriever`: indexes SEC filings into a `VectorStore` and answers hybrid (vector + keyword)
search, fused with reciprocal rank fusion.

Implements the frozen `meridian.rag.types.Retriever` protocol.
"""

from __future__ import annotations

import asyncio
import re

from meridian.core.ids import stable_id
from meridian.core.logging import get_logger
from meridian.providers.base import EmbeddingProvider, FilingRef, FilingsProvider
from meridian.rag.chunking import chunk_section
from meridian.rag.parsing import page_for_offset, parse_filing_html
from meridian.rag.sections import split_sections
from meridian.rag.store import StoredDocument, VectorStore
from meridian.rag.types import ChunkMetadata, DocumentChunk, IndexReport, RetrievedChunk
from meridian.schemas.research import CompanyIdentity
from meridian.security import injection

logger = get_logger(__name__)

_RRF_K = 60
_CANDIDATE_POOL = 30
_TOKEN_RE = re.compile(r"\w+")


class HybridRetriever:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider,
        filings_provider: FilingsProvider,
        *,
        rerank: bool = True,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.filings_provider = filings_provider
        self.rerank = rerank
        # Agents in the same wave request the same filings concurrently. Without a per-document lock each
        # one fetches, parses and embeds the same 10-K, which cost minutes and pushed agents into timeout.
        self._document_locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, document_id: str) -> asyncio.Lock:
        lock = self._document_locks.get(document_id)
        if lock is None:
            lock = asyncio.Lock()
            self._document_locks[document_id] = lock
        return lock

    async def ensure_indexed(self, company: CompanyIdentity, filings: list[FilingRef]) -> IndexReport:
        report = IndexReport()
        for filing in filings:
            document_id = stable_id("doc", filing.accession_number, filing.primary_document)
            try:
                async with self._lock_for(document_id):
                    # Re-check inside the lock: the agent that held it may have just indexed this document.
                    if await self.store.has_document(document_id):
                        report.documents_skipped += 1
                        continue

                    result = await self.filings_provider.fetch_document(filing)
                    filing_doc = result.data

                    parsed = parse_filing_html(filing_doc.html)
                    sections = split_sections(parsed.text, filing.form)

                    chunks: list[DocumentChunk] = []
                    for section in sections:
                        for draft in chunk_section(section):
                            flags = injection.scan(draft.text)
                            page = page_for_offset(parsed.page_breaks, draft.start_offset)
                            metadata = ChunkMetadata(
                                ticker=company.ticker,
                                cik=company.cik,
                                company=company.name,
                                form=filing.form,
                                filing_date=filing.filing_date,
                                accession_number=filing.accession_number,
                                section=section.title,
                                section_key=section.key,
                                source_url=filing.url,
                                document_title=parsed.title
                                or filing.description
                                or f"{filing.form} {filing.filing_date}",
                                page=page,
                                chunk_index=draft.index,
                                is_snapshot=result.is_snapshot,
                            )
                            chunk_id = stable_id("chk", document_id, section.key, draft.index)
                            chunks.append(
                                DocumentChunk(
                                    id=chunk_id,
                                    document_id=document_id,
                                    text=draft.text,
                                    token_count=draft.token_count,
                                    metadata=metadata,
                                    injection_flags=flags,
                                )
                            )

                    if not chunks:
                        report.failures.append(f"{filing.accession_number}: no chunks extracted from document")
                        continue

                    embeddings = await self.embedder.embed([c.text for c in chunks])
                    stored_doc = StoredDocument(
                        id=document_id,
                        ticker=company.ticker,
                        cik=company.cik,
                        company=company.name,
                        form=filing.form,
                        accession_number=filing.accession_number,
                        filing_date=filing.filing_date,
                        source_url=filing.url,
                        title=parsed.title or filing.description or filing.form,
                        is_snapshot=result.is_snapshot,
                        content_hash=stable_id("hash", filing_doc.html),
                    )
                    await self.store.add_document(stored_doc, chunks, embeddings)
                    report.documents_indexed += 1
                    report.chunks_created += len(chunks)
            except Exception as exc:
                logger.warning("filing_index_failed", accession=filing.accession_number, error=str(exc))
                report.failures.append(f"{filing.accession_number}: {exc}")
        return report

    async def search(
        self,
        query: str,
        *,
        ticker: str,
        forms: tuple[str, ...] | None = None,
        section_keys: tuple[str, ...] | None = None,
        k: int = 8,
    ) -> list[RetrievedChunk]:
        [query_embedding] = await self.embedder.embed([query])
        vector_hits = await self.store.vector_search(
            query_embedding, ticker=ticker, forms=forms, section_keys=section_keys, k=_CANDIDATE_POOL
        )
        keyword_hits = await self.store.keyword_search(
            query, ticker=ticker, forms=forms, section_keys=section_keys, k=_CANDIDATE_POOL
        )

        vector_rank = {chunk.id: i + 1 for i, (chunk, _) in enumerate(vector_hits)}
        keyword_rank = {chunk.id: i + 1 for i, (chunk, _) in enumerate(keyword_hits)}

        chunks_by_id: dict[str, DocumentChunk] = {}
        for chunk, _ in vector_hits:
            chunks_by_id[chunk.id] = chunk
        for chunk, _ in keyword_hits:
            chunks_by_id[chunk.id] = chunk

        fused: dict[str, float] = {}
        for chunk_id, rank in vector_rank.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
        for chunk_id, rank in keyword_rank.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)

        if self.rerank:
            query_tokens = set(_TOKEN_RE.findall(query.lower()))
            for chunk_id, chunk in chunks_by_id.items():
                if not query_tokens:
                    continue
                text_tokens = set(_TOKEN_RE.findall(chunk.text.lower()))
                overlap = len(query_tokens & text_tokens)
                if overlap:
                    fused[chunk_id] += 0.001 * overlap

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [
            RetrievedChunk(
                chunk=chunks_by_id[chunk_id],
                score=score,
                vector_rank=vector_rank.get(chunk_id),
                keyword_rank=keyword_rank.get(chunk_id),
            )
            for chunk_id, score in ordered
        ]
