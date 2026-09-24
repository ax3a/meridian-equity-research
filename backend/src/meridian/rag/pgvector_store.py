"""`VectorStore` implementation backed by Postgres + pgvector.

This module never creates or alters schema -- the `documents` and `document_chunks` tables (and the
`vector` extension) are owned by the DB-layer migration (Task 5). The column names used here must match
that migration exactly:

  documents(id, ticker, cik, company, form, accession_number, filing_date, source_url, title,
            is_snapshot, snapshot_date, content_hash, created_at)
  document_chunks(id, document_id, chunk_index, ticker, form, filing_date, section_key, section_title,
                   page, text, token_count, injection_flags, metadata, embedding, created_at)

Vector search orders by `embedding <=> :q` (pgvector cosine distance) ascending and reports
`score = 1 - distance`. Keyword search uses Postgres full-text search
(`to_tsvector('english', text) @@ websearch_to_tsquery('english', :q)`) ranked by `ts_rank_cd`.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from meridian.rag.store import StoredDocument
from meridian.rag.types import ChunkMetadata, DocumentChunk


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def _row_to_chunk(row) -> DocumentChunk:
    metadata_json = row.metadata if isinstance(row.metadata, dict) else json.loads(row.metadata or "{}")
    metadata = ChunkMetadata(
        ticker=row.ticker,
        cik=metadata_json.get("cik", ""),
        company=metadata_json.get("company", ""),
        form=row.form,
        filing_date=row.filing_date,
        accession_number=metadata_json.get("accession_number", ""),
        section=row.section_title,
        section_key=row.section_key,
        source_url=metadata_json.get("source_url", ""),
        document_title=metadata_json.get("document_title", ""),
        page=row.page,
        chunk_index=row.chunk_index,
        is_snapshot=metadata_json.get("is_snapshot", False),
        snapshot_date=metadata_json.get("snapshot_date"),
    )
    injection_flags = (
        row.injection_flags if isinstance(row.injection_flags, list) else json.loads(row.injection_flags or "[]")
    )
    return DocumentChunk(
        id=row.id,
        document_id=row.document_id,
        text=row.text,
        token_count=row.token_count or 0,
        metadata=metadata,
        injection_flags=injection_flags,
    )


class PgVectorStore:
    """`VectorStore` over an existing Postgres schema. Never issues DDL."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def has_document(self, document_id: str) -> bool:
        async with self.engine.connect() as conn:
            result = await conn.execute(text("SELECT 1 FROM documents WHERE id = :id"), {"id": document_id})
            return result.first() is not None

    async def add_document(
        self, doc: StoredDocument, chunks: list[DocumentChunk], embeddings: list[list[float]]
    ) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO documents
                        (id, ticker, cik, company, form, accession_number, filing_date, source_url,
                         title, is_snapshot, snapshot_date, content_hash)
                    VALUES
                        (:id, :ticker, :cik, :company, :form, :accession_number, :filing_date, :source_url,
                         :title, :is_snapshot, :snapshot_date, :content_hash)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": doc.id,
                    "ticker": doc.ticker,
                    "cik": doc.cik,
                    "company": doc.company,
                    "form": doc.form,
                    "accession_number": doc.accession_number,
                    "filing_date": doc.filing_date,
                    "source_url": doc.source_url,
                    "title": doc.title,
                    "is_snapshot": doc.is_snapshot,
                    "snapshot_date": doc.snapshot_date,
                    "content_hash": doc.content_hash,
                },
            )

            for chunk, embedding in zip(chunks, embeddings, strict=True):
                meta = chunk.metadata
                metadata_json = json.dumps(
                    {
                        "cik": meta.cik,
                        "company": meta.company,
                        "accession_number": meta.accession_number,
                        "source_url": meta.source_url,
                        "document_title": meta.document_title,
                        "is_snapshot": meta.is_snapshot,
                        "snapshot_date": meta.snapshot_date.isoformat() if meta.snapshot_date else None,
                    }
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO document_chunks
                            (id, document_id, chunk_index, ticker, form, filing_date, section_key,
                             section_title, page, text, token_count, injection_flags, metadata, embedding)
                        VALUES
                            (:id, :document_id, :chunk_index, :ticker, :form, :filing_date, :section_key,
                             :section_title, :page, :text, :token_count,
                             CAST(:injection_flags AS jsonb), CAST(:metadata AS jsonb),
                             CAST(:embedding AS vector))
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": chunk.id,
                        "document_id": chunk.document_id,
                        "chunk_index": meta.chunk_index,
                        "ticker": meta.ticker,
                        "form": meta.form,
                        "filing_date": meta.filing_date,
                        "section_key": meta.section_key,
                        "section_title": meta.section,
                        "page": meta.page,
                        "text": chunk.text,
                        "token_count": chunk.token_count,
                        "injection_flags": json.dumps(chunk.injection_flags),
                        "metadata": metadata_json,
                        "embedding": _vector_literal(embedding),
                    },
                )

    async def vector_search(
        self,
        embedding: list[float],
        *,
        ticker: str,
        forms: tuple[str, ...] | None,
        section_keys: tuple[str, ...] | None,
        k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        clauses = ["ticker = :ticker"]
        params: dict[str, object] = {"ticker": ticker, "q": _vector_literal(embedding), "k": k}
        if forms:
            clauses.append("form = ANY(:forms)")
            params["forms"] = list(forms)
        if section_keys:
            clauses.append("section_key = ANY(:section_keys)")
            params["section_keys"] = list(section_keys)
        where = " AND ".join(clauses)

        # `where` is assembled only from the fixed clause strings above (never raw user text), so this
        # is not an actual injection vector -- ruff's string-built-SQL check can't see that.
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT id, document_id, chunk_index, ticker, form, filing_date, section_key,
                           section_title, page, text, token_count, injection_flags, metadata,
                           1 - (embedding <=> CAST(:q AS vector)) AS score
                    FROM document_chunks
                    WHERE {where}
                    ORDER BY embedding <=> CAST(:q AS vector) ASC
                    LIMIT :k
                    """  # noqa: S608
                ),
                params,
            )
            rows = result.mappings().all()
        return [(_row_to_chunk(_Row(row)), row["score"]) for row in rows]

    async def keyword_search(
        self,
        query: str,
        *,
        ticker: str,
        forms: tuple[str, ...] | None,
        section_keys: tuple[str, ...] | None,
        k: int,
    ) -> list[tuple[DocumentChunk, float]]:
        clauses = ["ticker = :ticker", "to_tsvector('english', text) @@ websearch_to_tsquery('english', :q)"]
        params: dict[str, object] = {"ticker": ticker, "q": query, "k": k}
        if forms:
            clauses.append("form = ANY(:forms)")
            params["forms"] = list(forms)
        if section_keys:
            clauses.append("section_key = ANY(:section_keys)")
            params["section_keys"] = list(section_keys)
        where = " AND ".join(clauses)

        # Same as vector_search: `where` is built only from the fixed clause strings above.
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT id, document_id, chunk_index, ticker, form, filing_date, section_key,
                           section_title, page, text, token_count, injection_flags, metadata,
                           ts_rank_cd(to_tsvector('english', text), websearch_to_tsquery('english', :q)) AS score
                    FROM document_chunks
                    WHERE {where}
                    ORDER BY score DESC
                    LIMIT :k
                    """  # noqa: S608
                ),
                params,
            )
            rows = result.mappings().all()
        return [(_row_to_chunk(_Row(row)), row["score"]) for row in rows]

    async def delete_document(self, document_id: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})


class _Row:
    """Thin attribute-access wrapper so `_row_to_chunk` works for both `Row` and `RowMapping`."""

    def __init__(self, mapping) -> None:
        self._mapping = mapping

    def __getattr__(self, item: str):
        return self._mapping[item]
