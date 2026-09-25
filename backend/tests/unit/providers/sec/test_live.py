"""Live reachability/shape checks against the real SEC EDGAR API for MSFT.

Excluded by default (see pyproject `addopts = "-ra -m 'not live'"`). Run explicitly with:
    .\\.venv\\Scripts\\python.exe -m pytest tests/unit/providers/sec -q -m live
"""

from __future__ import annotations

import pytest

from meridian.providers.sec.directory import SecCompanyDirectory
from meridian.providers.sec.facts import SecFundamentalsProvider
from meridian.providers.sec.filings import SecFilingsProvider
from meridian.providers.sec.peers import SecPeerUniverseProvider

pytestmark = pytest.mark.live


@pytest.fixture
async def live_http(settings, memory_cache, snapshot_store):
    from meridian.core.http import HttpClient

    client = HttpClient(settings, memory_cache, snapshot_store)
    yield client
    await client.aclose()


async def test_live_directory_resolves_and_profiles_msft(live_http):
    directory = SecCompanyDirectory(live_http)

    identity = await directory.resolve("MSFT")
    assert identity.ticker == "MSFT"
    assert identity.cik == "0000789019"

    result = await directory.profile(identity)
    assert result.sources and result.evidence
    assert result.data.identity.sic is not None


async def test_live_filings_lists_and_fetches_a_10k(live_http):
    provider = SecFilingsProvider(live_http)
    from meridian.schemas.research import CompanyIdentity

    company = CompanyIdentity(name="MICROSOFT CORP", ticker="MSFT", cik="789019")
    result = await provider.list_filings(company, forms=("10-K",), limit=1)
    assert result.data
    ref = result.data[0]
    assert ref.form == "10-K"

    doc_result = await provider.fetch_document(ref)
    assert len(doc_result.data.html) > 1000


async def test_live_fundamentals_resolves_expected_concepts_for_msft(live_http):
    from meridian.schemas.research import CompanyIdentity

    provider = SecFundamentalsProvider(live_http)
    company = CompanyIdentity(name="MICROSOFT CORP", ticker="MSFT", cik="789019")

    result = await provider.get_statements(company, years=3)
    assert len(result.data.annual) >= 1
    latest = result.data.annual[-1]
    # As of writing, MSFT reports RevenueFromContractWithCustomerExcludingAssessedTax and GrossProfit
    # directly (no fallback/derivation needed) -- assert the concrete values are populated at all,
    # since exact figures roll forward every fiscal year.
    assert latest.revenue is not None
    assert latest.net_income is not None
    assert latest.evidence_ids  # every populated line item has a citation


async def test_live_peers_sic_atom_feed_shape(live_http):
    """Documents the real behaviour of the browse-edgar SIC Atom feed for the report."""
    from meridian.cache.base import Policies
    from meridian.providers.sec.endpoints import peers_by_sic_atom_url

    result = await live_http.get_text(peers_by_sic_atom_url("7372"), provider="sec_edgar", policy=Policies.FRAMES)
    assert "<feed" in result.body
    assert "<cik>" in result.body


async def test_live_peers_candidate_peers_for_msft(live_http):
    from meridian.schemas.research import CompanyIdentity

    provider = SecPeerUniverseProvider(live_http)
    company = CompanyIdentity(
        name="MICROSOFT CORP", ticker="MSFT", cik="789019", sic="7372", sic_description="Services-Prepackaged Software"
    )

    result = await provider.candidate_peers(company, limit=5)
    # Whether or not the Atom cross-reference finds tradable peers, this must not raise and must
    # return *something* actionable, with any limitation recorded in warnings.
    assert isinstance(result.data, list)
