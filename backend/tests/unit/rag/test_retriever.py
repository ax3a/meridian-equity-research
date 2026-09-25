from __future__ import annotations

from datetime import date

import pytest

from meridian.providers.base import FilingDocument, FilingRef, ProviderResult
from meridian.rag.embeddings import HashingEmbedder
from meridian.rag.retriever import HybridRetriever
from meridian.rag.store import InMemoryVectorStore
from meridian.rag.types import ChunkMetadata, DocumentChunk, RetrievedChunk
from meridian.schemas.research import CompanyIdentity

from .conftest import read_fixture


def _company() -> CompanyIdentity:
    return CompanyIdentity(name="Acme Corp", ticker="ACME", cik="1")


def _filing_ref(html_name: str, form: str, accession: str) -> FilingRef:
    return FilingRef(
        cik="0000000001",
        ticker="ACME",
        form=form,
        accession_number=accession,
        filing_date=date(2025, 12, 31),
        primary_document="filing.htm",
        url=f"https://www.sec.gov/Archives/edgar/data/1/{accession}/filing.htm",
    )


class _FakeFilingsProvider:
    name = "fake_sec"

    def __init__(self, html_by_accession: dict[str, str]) -> None:
        self._html = html_by_accession
        self.fetch_calls: list[str] = []

    async def list_filings(self, company, forms=("10-K", "10-Q", "8-K"), limit=20):
        raise NotImplementedError

    async def fetch_document(self, filing: FilingRef) -> ProviderResult[FilingDocument]:
        self.fetch_calls.append(filing.accession_number)
        html = self._html[filing.accession_number]
        return ProviderResult(data=FilingDocument(ref=filing, html=html), provider=self.name)


@pytest.fixture
def indexed_retriever():
    async def _build():
        ref = _filing_ref("sample_10k.html", "10-K", "0000000001-25-000001")
        provider = _FakeFilingsProvider({ref.accession_number: read_fixture("sample_10k.html")})
        store = InMemoryVectorStore()
        embedder = HashingEmbedder(dim=384)
        retriever = HybridRetriever(store, embedder, provider)
        report = await retriever.ensure_indexed(_company(), [ref])
        return retriever, provider, ref, report

    return _build


async def test_ensure_indexed_creates_chunks(indexed_retriever) -> None:
    _retriever, provider, ref, report = await indexed_retriever()

    assert report.documents_indexed == 1
    assert report.documents_skipped == 0
    assert report.chunks_created > 0
    assert report.failures == []
    assert provider.fetch_calls == [ref.accession_number]


async def test_ensure_indexed_skips_already_indexed_documents(indexed_retriever) -> None:
    retriever, provider, ref, _ = await indexed_retriever()

    report2 = await retriever.ensure_indexed(_company(), [ref])

    assert report2.documents_indexed == 0
    assert report2.documents_skipped == 1
    # fetch_document must not be called again for an already-indexed filing
    assert provider.fetch_calls == [ref.accession_number]


async def test_ensure_indexed_records_failures_without_raising() -> None:
    ref = _filing_ref("broken", "10-K", "0000000001-25-000002")

    class _BrokenProvider:
        name = "broken"

        async def list_filings(self, company, forms=("10-K", "10-Q", "8-K"), limit=20):
            raise NotImplementedError

        async def fetch_document(self, filing: FilingRef):
            raise RuntimeError("network exploded")

    retriever = HybridRetriever(InMemoryVectorStore(), HashingEmbedder(dim=384), _BrokenProvider())
    report = await retriever.ensure_indexed(_company(), [ref])

    assert report.documents_indexed == 0
    assert len(report.failures) == 1
    assert "network exploded" in report.failures[0]


async def test_injection_flags_survive_indexing(indexed_retriever) -> None:
    retriever, *_ = await indexed_retriever()
    results = await retriever.search("strong buy recommendation", ticker="ACME", k=8)

    flagged = [r for r in results if r.chunk.injection_flags]
    assert flagged, "expected at least one retrieved chunk to carry injection flags"
    flags = flagged[0].chunk.injection_flags
    assert "override_instructions" in flags or "rating_manipulation" in flags


async def test_search_filters_by_section_and_returns_retrieved_chunks(indexed_retriever) -> None:
    retriever, *_ = await indexed_retriever()
    results = await retriever.search("risk factors competition supply chain", ticker="ACME", section_keys=("1A",), k=8)

    assert results
    assert all(isinstance(r, RetrievedChunk) for r in results)
    assert all(r.chunk.metadata.section_key == "1A" for r in results)


class _StubStore:
    """Deterministic vector/keyword result stub to test RRF math in isolation."""

    def __init__(self, vector_order: list[DocumentChunk], keyword_order: list[DocumentChunk]) -> None:
        self._vector_order = vector_order
        self._keyword_order = keyword_order

    async def has_document(self, document_id: str) -> bool:
        return False

    async def add_document(self, doc, chunks, embeddings) -> None:
        raise NotImplementedError

    async def vector_search(self, embedding, *, ticker, forms, section_keys, k):
        return [(c, 1.0 - i * 0.1) for i, c in enumerate(self._vector_order[:k])]

    async def keyword_search(self, query, *, ticker, forms, section_keys, k):
        return [(c, 1.0 - i * 0.1) for i, c in enumerate(self._keyword_order[:k])]

    async def delete_document(self, document_id: str) -> None:
        raise NotImplementedError


def _bare_chunk(cid: str) -> DocumentChunk:
    return DocumentChunk(
        id=cid,
        document_id="doc_1",
        text=f"text for {cid}",
        token_count=4,
        metadata=ChunkMetadata(
            ticker="ACME",
            cik="0000000001",
            company="Acme Corp",
            form="10-K",
            filing_date=date(2025, 12, 31),
            accession_number="0000000001-25-000001",
            section="Item 1A. Risk Factors",
            section_key="1A",
            source_url="https://example.com/filing.htm",
            document_title="Acme 10-K",
        ),
    )


async def test_reciprocal_rank_fusion_orders_chunks_present_in_both_lists() -> None:
    a, b, c = _bare_chunk("chk_a"), _bare_chunk("chk_b"), _bare_chunk("chk_c")
    # "a" ranks 2nd in vector but 1st in keyword -> should out-fuse "b" which is 1st in vector only.
    store = _StubStore(vector_order=[b, a, c], keyword_order=[a, c, b])
    retriever = HybridRetriever(store, HashingEmbedder(dim=384), filings_provider=None, rerank=False)

    results = await retriever.search("irrelevant query text", ticker="ACME", k=3)

    rrf = {r.chunk.id: r.score for r in results}
    expected_a = 1 / (60 + 2) + 1 / (60 + 1)
    expected_b = 1 / (60 + 1) + 1 / (60 + 3)
    assert rrf["chk_a"] == pytest.approx(expected_a)
    assert rrf["chk_b"] == pytest.approx(expected_b)
    assert results[0].chunk.id == "chk_a"
    assert results[0].vector_rank == 2
    assert results[0].keyword_rank == 1
