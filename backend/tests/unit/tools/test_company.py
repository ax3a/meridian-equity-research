from __future__ import annotations

import pytest

from meridian.tools.company import (
    GetCompanyProfileInput,
    GetCompanyProfileTool,
    ResolveCompanyInput,
    ResolveCompanyTool,
    SearchCompaniesInput,
    SearchCompaniesTool,
)
from tests.unit.tools.conftest import FakeDirectory, make_registry


async def test_resolve_company_returns_identity(make_ctx):
    ctx = make_ctx()
    output = await ResolveCompanyTool().run(ResolveCompanyInput(query="MSFT"), ctx)
    assert output.company.ticker == "MSFT"
    assert output.company.cik == "0000789019"
    assert output.evidence_ids == []


async def test_resolve_company_not_found_raises(make_ctx):
    ctx = make_ctx()
    with pytest.raises(Exception):
        await ResolveCompanyTool().run(ResolveCompanyInput(query="ZZZZZZ"), ctx)


def test_resolve_company_summarize_is_readable():
    from meridian.schemas.research import CompanyIdentity
    from meridian.tools.company import ResolveCompanyOutput

    tool = ResolveCompanyTool()
    out = ResolveCompanyOutput(company=CompanyIdentity(name="MICROSOFT CORP", ticker="msft", cik="789019"))
    text = tool.summarize(out)
    assert "MICROSOFT CORP" in text and "MSFT" in text


async def test_search_companies_matches_ticker_and_name(make_ctx):
    ctx = make_ctx()
    output = await SearchCompaniesTool().run(SearchCompaniesInput(query="ms"), ctx)
    tickers = [c.ticker for c in output.results]
    assert "MSFT" in tickers


async def test_get_company_profile_carries_evidence(make_ctx):
    ctx = make_ctx()
    output = await GetCompanyProfileTool().run(GetCompanyProfileInput(ticker="MSFT"), ctx)
    assert output.profile.identity.sic == "7372"
    assert len(output.evidence_ids) == 1
    # The evidence must actually be resolvable through the ledger -- not just an id in a list.
    assert ctx.ledger.evidence[output.evidence_ids[0]] is not None
    summary = GetCompanyProfileTool().summarize(output)
    assert output.evidence_ids[0] in summary


async def test_get_company_profile_propagates_provider_failure(make_ctx):
    registry = make_registry(directory=FakeDirectory(profile_fails=True))
    ctx = make_ctx(providers=registry)
    with pytest.raises(Exception):
        await GetCompanyProfileTool().run(GetCompanyProfileInput(ticker="MSFT"), ctx)
