from __future__ import annotations

from datetime import date

from meridian.rag.store import InMemoryVectorStore, StoredDocument
from meridian.rag.types import ChunkMetadata, DocumentChunk


def _chunk(cid: str, doc_id: str, *, ticker: str, form: str, section_key: str, text: str, idx: int) -> DocumentChunk:
    return DocumentChunk(
        id=cid,
        document_id=doc_id,
        text=text,
        token_count=len(text.split()),
        metadata=ChunkMetadata(
            ticker=ticker,
            cik="0000000001",
            company="Acme Corp",
            form=form,
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


def _doc(doc_id: str, ticker: str = "ACME", form: str = "10-K") -> StoredDocument:
    return StoredDocument(
        id=doc_id,
        ticker=ticker,
        cik="0000000001",
        company="Acme Corp",
        form=form,
        accession_number="0000000001-25-000001",
        filing_date=date(2025, 12, 31),
        source_url="https://example.com/filing.htm",
        title="Acme 10-K",
        content_hash="abc123",
    )


async def test_has_document_and_add_document() -> None:
    store = InMemoryVectorStore()
    doc_id = "doc_1"
    assert await store.has_document(doc_id) is False

    chunks = [
        _chunk("chk_1", doc_id, ticker="ACME", form="10-K", section_key="1A", text="risk factors competition", idx=0),
        _chunk("chk_2", doc_id, ticker="ACME", form="10-K", section_key="7", text="net sales margin expanded", idx=1),
    ]
    embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    await store.add_document(_doc(doc_id), chunks, embeddings)

    assert await store.has_document(doc_id) is True


async def test_vector_search_orders_by_similarity_and_filters() -> None:
    store = InMemoryVectorStore()
    doc_id = "doc_1"
    chunks = [
        _chunk("chk_1", doc_id, ticker="ACME", form="10-K", section_key="1A", text="risk factors", idx=0),
        _chunk("chk_2", doc_id, ticker="ACME", form="10-K", section_key="7", text="net sales", idx=1),
        _chunk("chk_3", "doc_2", ticker="OTHR", form="10-K", section_key="1A", text="other company risk", idx=0),
    ]
    embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]
    await store.add_document(_doc(doc_id), chunks[:2], embeddings[:2])
    await store.add_document(_doc("doc_2", ticker="OTHR"), chunks[2:], embeddings[2:])

    results = await store.vector_search([1.0, 0.0, 0.0], ticker="ACME", forms=None, section_keys=None, k=5)
    assert [c.id for c, _ in results] == ["chk_1", "chk_2"]
    assert results[0][0].id == "chk_1"
    assert results[0][1] == 1.0
    assert all(c.id != "chk_3" for c, _ in results)


async def test_vector_search_filters_by_form_and_section() -> None:
    store = InMemoryVectorStore()
    doc_id = "doc_1"
    chunks = [
        _chunk("chk_1", doc_id, ticker="ACME", form="10-K", section_key="1A", text="risk factors", idx=0),
        _chunk("chk_2", doc_id, ticker="ACME", form="10-Q", section_key="partI_item2", text="mdna quarterly", idx=1),
    ]
    embeddings = [[1.0, 0.0], [1.0, 0.0]]
    await store.add_document(_doc(doc_id), chunks, embeddings)

    results = await store.vector_search([1.0, 0.0], ticker="ACME", forms=("10-Q",), section_keys=None, k=5)
    assert [c.id for c, _ in results] == ["chk_2"]

    results = await store.vector_search([1.0, 0.0], ticker="ACME", forms=None, section_keys=("1A",), k=5)
    assert [c.id for c, _ in results] == ["chk_1"]


async def test_keyword_search_finds_matching_terms() -> None:
    store = InMemoryVectorStore()
    doc_id = "doc_1"
    chunks = [
        _chunk("chk_1", doc_id, ticker="ACME", form="10-K", section_key="1A", text="supply chain disruption", idx=0),
        _chunk("chk_2", doc_id, ticker="ACME", form="10-K", section_key="7", text="net sales margin expanded", idx=1),
    ]
    await store.add_document(_doc(doc_id), chunks, [[0.0], [0.0]])

    results = await store.keyword_search("supply chain competition", ticker="ACME", forms=None, section_keys=None, k=5)
    assert results
    assert results[0][0].id == "chk_1"


async def test_delete_document_removes_chunks() -> None:
    store = InMemoryVectorStore()
    doc_id = "doc_1"
    chunks = [_chunk("chk_1", doc_id, ticker="ACME", form="10-K", section_key="1A", text="risk factors", idx=0)]
    await store.add_document(_doc(doc_id), chunks, [[1.0]])
    assert await store.has_document(doc_id) is True

    await store.delete_document(doc_id)

    assert await store.has_document(doc_id) is False
    results = await store.vector_search([1.0], ticker="ACME", forms=None, section_keys=None, k=5)
    assert results == []
