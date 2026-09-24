from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from meridian.rag.pgvector_store import PgVectorStore
from meridian.rag.store import StoredDocument
from meridian.rag.types import ChunkMetadata, DocumentChunk

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian"
)

_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id text PRIMARY KEY,
    ticker text,
    cik text,
    company text,
    form text,
    accession_number text,
    filing_date date,
    source_url text,
    title text,
    is_snapshot bool,
    snapshot_date date,
    content_hash text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id text PRIMARY KEY,
    document_id text REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index int,
    ticker text,
    form text,
    filing_date date,
    section_key text,
    section_title text,
    page int,
    text text,
    token_count int,
    injection_flags jsonb,
    metadata jsonb,
    embedding vector(384),
    created_at timestamptz DEFAULT now()
);
"""


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        async with eng.connect() as conn:
            await conn.run_sync(lambda _: None)
    except (SQLAlchemyError, OSError) as exc:
        await eng.dispose()
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")

    async with eng.begin() as conn:
        for stmt in _DDL.strip().split(";\n\n"):
            if stmt.strip():
                await conn.exec_driver_sql(stmt)

    yield eng

    async with eng.begin() as conn:
        await conn.exec_driver_sql("DROP TABLE IF EXISTS document_chunks")
        await conn.exec_driver_sql("DROP TABLE IF EXISTS documents")
    await eng.dispose()


def _doc() -> StoredDocument:
    return StoredDocument(
        id="doc_pg_test_1",
        ticker="ACME",
        cik="0000000001",
        company="Acme Corp",
        form="10-K",
        accession_number="0000000001-25-000001",
        filing_date=date(2025, 12, 31),
        source_url="https://example.com/filing.htm",
        title="Acme 10-K",
        content_hash="abc123",
    )


def _chunk(cid: str, doc_id: str, section_key: str, text: str, idx: int) -> DocumentChunk:
    return DocumentChunk(
        id=cid,
        document_id=doc_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            ticker="ACME",
            cik="0000000001",
            company="Acme Corp",
            form="10-K",
            filing_date=date(2025, 12, 31),
            accession_number="0000000001-25-000001",
            section=f"Item {section_key}",
            section_key=section_key,
            source_url="https://example.com/filing.htm",
            document_title="Acme 10-K",
            page=idx + 1,
            chunk_index=idx,
        ),
    )


async def test_pgvector_store_round_trip(engine: AsyncEngine) -> None:
    store = PgVectorStore(engine)
    doc_id = "doc_pg_test_1"

    assert await store.has_document(doc_id) is False

    dim = 384
    v1 = [1.0] + [0.0] * (dim - 1)
    v2 = [0.0, 1.0] + [0.0] * (dim - 2)
    chunks = [
        _chunk("chk_pg_1", doc_id, "1A", "supply chain disruption and competition risk", 0),
        _chunk("chk_pg_2", doc_id, "7", "net sales increased and margin expanded", 1),
    ]
    await store.add_document(_doc(), chunks, [v1, v2])

    assert await store.has_document(doc_id) is True

    vector_results = await store.vector_search(v1, ticker="ACME", forms=None, section_keys=None, k=5)
    assert vector_results
    assert vector_results[0][0].id == "chk_pg_1"
    assert vector_results[0][1] == pytest.approx(1.0, abs=1e-4)

    keyword_results = await store.keyword_search(
        "supply chain competition", ticker="ACME", forms=None, section_keys=None, k=5
    )
    assert keyword_results
    assert keyword_results[0][0].id == "chk_pg_1"

    filtered = await store.vector_search(v1, ticker="ACME", forms=None, section_keys=("7",), k=5)
    assert [c.id for c, _ in filtered] == ["chk_pg_2"]

    await store.delete_document(doc_id)
    assert await store.has_document(doc_id) is False
