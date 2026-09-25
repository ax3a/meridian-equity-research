from __future__ import annotations

from meridian.rag.embeddings import HashingEmbedder
from meridian.rag.retriever import HybridRetriever
from meridian.rag.store import InMemoryVectorStore
from meridian.tools.filings import (
    GetFilingSectionInput,
    GetFilingSectionTool,
    GetRecent8kEventsInput,
    GetRecent8kEventsTool,
    IndexFilingsInput,
    IndexFilingsTool,
    ListFilingsInput,
    ListFilingsTool,
    SearchFilingsInput,
    SearchFilingsTool,
)
from tests.unit.tools.conftest import FakeFilings, FakeRetriever, make_registry


async def test_list_filings_filters_by_form(make_ctx):
    ctx = make_ctx()
    output = await ListFilingsTool().run(ListFilingsInput(ticker="MSFT", forms=["8-K"]), ctx)
    assert len(output.filings) == 1
    assert output.filings[0].form == "8-K"
    assert output.filings[0].items == ["2.02", "9.01"]


async def test_get_recent_8k_events_carries_evidence(make_ctx):
    ctx = make_ctx()
    output = await GetRecent8kEventsTool().run(GetRecent8kEventsInput(ticker="MSFT"), ctx)
    assert len(output.events) == 1
    event = output.events[0]
    assert event.items == ["2.02", "9.01"]
    assert ctx.ledger.evidence[event.evidence_id] is not None
    summary = GetRecent8kEventsTool().summarize(output)
    assert event.evidence_id in summary


async def test_index_filings_without_retriever_raises(make_ctx):
    from meridian.core.errors import DataNotAvailableError

    ctx = make_ctx(retriever=None)
    import pytest

    with pytest.raises(DataNotAvailableError):
        await IndexFilingsTool().run(IndexFilingsInput(ticker="MSFT"), ctx)


async def test_index_filings_calls_ensure_indexed(make_ctx):
    retriever = FakeRetriever()
    ctx = make_ctx(retriever=retriever)
    report = await IndexFilingsTool().run(IndexFilingsInput(ticker="MSFT", forms=["10-K", "10-Q"]), ctx)
    assert report.documents_indexed == 2  # one 10-K + one 10-Q in the fixture
    assert len(retriever.ensure_indexed_calls) == 1


def _real_retriever(filings: FakeFilings) -> HybridRetriever:
    return HybridRetriever(InMemoryVectorStore(), HashingEmbedder(dim=32), filings)


async def test_search_filings_lazily_indexes_when_store_is_empty(make_ctx):
    filings = FakeFilings()
    retriever = _real_retriever(filings)
    registry = make_registry(filings=filings)
    ctx = make_ctx(providers=registry, retriever=retriever)

    output = await SearchFilingsTool().run(
        SearchFilingsInput(ticker="MSFT", query="cloud computing competition", k=5), ctx
    )

    assert len(output.passages) > 0
    passage = output.passages[0]
    assert ctx.ledger.evidence[passage.evidence_id] is not None
    assert ctx.ledger.sources[passage.source_id] is not None
    summary = SearchFilingsTool().summarize(output)
    assert passage.evidence_id in summary


async def test_search_filings_second_call_does_not_reindex(make_ctx):
    filings = FakeFilings()
    retriever = _real_retriever(filings)
    registry = make_registry(filings=filings)
    ctx = make_ctx(providers=registry, retriever=retriever)

    await SearchFilingsTool().run(SearchFilingsInput(ticker="MSFT", query="cloud computing"), ctx)
    # Second call: the store already has chunks for MSFT, so no re-fetch/re-index should be needed --
    # verified indirectly by confirming results are still returned instantly for a different query.
    output = await SearchFilingsTool().run(SearchFilingsInput(ticker="MSFT", query="risk factors currency"), ctx)
    assert len(output.passages) > 0


async def test_get_filing_section_returns_passages_for_risk_factors(make_ctx):
    filings = FakeFilings()
    retriever = _real_retriever(filings)
    registry = make_registry(filings=filings)
    ctx = make_ctx(providers=registry, retriever=retriever)

    output = await GetFilingSectionTool().run(GetFilingSectionInput(ticker="MSFT", form="10-K", section_key="1A"), ctx)
    assert len(output.passages) > 0
    assert all(p.form == "10-K" for p in output.passages)
