"""Vector store protocol plus an in-memory implementation used by unit tests and small runs.

`PgVectorStore` (in `pgvector_store.py`) implements the same protocol against Postgres/pgvector.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from meridian.rag.types import DocumentChunk

_TOKEN_RE = re.compile(r"\w+")


@dataclass
class StoredDocument:
    id: str
    ticker: str
    cik: str
    company: str
    form: str
    accession_number: str
    filing_date: date
    source_url: str
    title: str
    is_snapshot: bool = False
    snapshot_date: date | None = None
    content_hash: str = ""


@runtime_checkable
class VectorStore(Protocol):
    async def has_document(self, document_id: str) -> bool: ...

    async def add_document(
        self, doc: StoredDocument, chunks: list[DocumentChunk], embeddings: list[list[float]]
    ) -> None: ...

    async def vector_search(
        self,
        embedding: list[float],
        *,
        ticker: str,
        forms: tuple[str, ...] | None,
        section_keys: tuple[str, ...] | None,
        k: int,
    ) -> list[tuple[DocumentChunk, float]]: ...

    async def keyword_search(
        self,
        query: str,
        *,
        ticker: str,
        forms: tuple[str, ...] | None,
        section_keys: tuple[str, ...] | None,
        k: int,
    ) -> list[tuple[DocumentChunk, float]]: ...

    async def delete_document(self, document_id: str) -> None: ...


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _matches(
    chunk: DocumentChunk,
    *,
    ticker: str,
    forms: tuple[str, ...] | None,
    section_keys: tuple[str, ...] | None,
) -> bool:
    if chunk.metadata.ticker != ticker:
        return False
    if forms and chunk.metadata.form not in forms:
        return False
    return not (section_keys and chunk.metadata.section_key not in section_keys)


class InMemoryVectorStore:
    """Plain-Python `VectorStore` for tests and small/offline runs. Not persisted, not thread-safe."""

    def __init__(self) -> None:
        self._documents: dict[str, StoredDocument] = {}
        self._chunks: dict[str, list[DocumentChunk]] = {}
        self._embeddings: dict[str, list[float]] = {}

    async def has_document(self, document_id: str) -> bool:
        return document_id in self._documents

    async def add_document(
        self, doc: StoredDocument, chunks: list[DocumentChunk], embeddings: list[list[float]]
    ) -> None:
        self._documents[doc.id] = doc
        self._chunks[doc.id] = list(chunks)
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self._embeddings[chunk.id] = embedding

    def _all_chunks(self) -> list[DocumentChunk]:
        return [chunk for chunks in self._chunks.values() for chunk in chunks]

    async def vector_search(
        self,
        embedding: list[float],
        *,
        ticker: str,
        forms: tuple[str, ...] | None,
        section_keys: tuple[str, ...] | None,
        k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        scored = [
            (chunk, _cosine(embedding, self._embeddings.get(chunk.id, [])))
            for chunk in self._all_chunks()
            if _matches(chunk, ticker=ticker, forms=forms, section_keys=section_keys)
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    async def keyword_search(
        self,
        query: str,
        *,
        ticker: str,
        forms: tuple[str, ...] | None,
        section_keys: tuple[str, ...] | None,
        k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        query_tokens = _TOKEN_RE.findall(query.lower())
        if not query_tokens:
            return []
        scored: list[tuple[DocumentChunk, float]] = []
        for chunk in self._all_chunks():
            if not _matches(chunk, ticker=ticker, forms=forms, section_keys=section_keys):
                continue
            text_tokens = _TOKEN_RE.findall(chunk.text.lower())
            if not text_tokens:
                continue
            hits = sum(text_tokens.count(t) for t in query_tokens)
            if hits == 0:
                continue
            score = hits / math.sqrt(len(text_tokens))
            scored.append((chunk, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    async def delete_document(self, document_id: str) -> None:
        self._documents.pop(document_id, None)
        for chunk in self._chunks.pop(document_id, []):
            self._embeddings.pop(chunk.id, None)
