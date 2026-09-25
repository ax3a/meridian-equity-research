from __future__ import annotations

from meridian.tools.news import SearchNewsInput, SearchNewsTool


async def test_search_news_pairs_articles_with_evidence(make_ctx):
    ctx = make_ctx()
    output = await SearchNewsTool().run(SearchNewsInput(ticker="MSFT", days=30, limit=10), ctx)
    assert len(output.articles) == 2
    assert len(output.evidence_ids) == 2
    for eid in output.evidence_ids:
        assert ctx.ledger.evidence[eid] is not None
    summary = SearchNewsTool().summarize(output)
    assert "reuters.com" in summary
    assert output.evidence_ids[0] in summary
