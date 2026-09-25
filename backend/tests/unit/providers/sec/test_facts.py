from __future__ import annotations

import pytest

from meridian.providers.sec.endpoints import company_facts_url
from meridian.providers.sec.facts import SecFundamentalsProvider
from meridian.schemas.enums import SourceKind


@pytest.fixture
def fundamentals(http_client):
    return SecFundamentalsProvider(http_client)


async def test_annual_statements_limited_to_requested_years(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=2)

    labels = [p.period.label for p in result.data.annual]
    assert labels == ["FY2023", "FY2024"]


async def test_revenue_falls_back_to_revenues_concept(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    # The fixture deliberately omits RevenueFromContractWithCustomerExcludingAssessedTax so this
    # exercises the second concept in the fallback chain.
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)
    fy2024 = result.data.annual[-1]

    assert fy2024.period.label == "FY2024"
    assert fy2024.revenue == pytest.approx(245122000000)
    ev = next(e for e in result.evidence if e.id == fy2024.evidence_ids["revenue"])
    assert ev.locator.xbrl_concept == "Revenues"
    assert ev.locator.period == "FY2024"
    assert ev.locator.accession_number == "0000950170-24-087843"
    assert ev.text == (
        "MICROSOFT CORP 10-K (accession 0000950170-24-087843, filed 2024-07-30): "
        "us-gaap:Revenues = 245,122,000,000 USD for period 2023-07-01..2024-06-30"
    )


async def test_gross_profit_is_derived_and_says_so(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)
    fy2024 = result.data.annual[-1]

    assert fy2024.gross_profit == pytest.approx(245122000000 - 74114000000)
    ev = next(e for e in result.evidence if e.id == fy2024.evidence_ids["gross_profit"])
    assert "derived as revenue - cost_of_revenue" in ev.text


async def test_unit_mismatch_is_ignored(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    # CostOfRevenue has a bogus extra "shares" unit entry that must never be picked up.
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)
    fy2024 = result.data.annual[-1]

    assert fy2024.cost_of_revenue == pytest.approx(74114000000)


async def test_dedupe_keeps_latest_filed_accession(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    # FY2022 revenue appears in both the original FY2022 10-K (accession A) and as a comparative
    # row in the later-filed FY2023 10-K (accession B); the latter must win.
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)
    fy2022 = result.data.annual[0]

    assert fy2022.period.label == "FY2022"
    ev = next(e for e in result.evidence if e.id == fy2022.evidence_ids["revenue"])
    assert ev.locator.accession_number == "0000950170-23-035122"


async def test_instant_comparative_row_does_not_corrupt_the_true_period(
    respx_mock, fundamentals, companyfacts_msft, msft_identity
):
    # Assets is tagged with two rows per accession (current + prior-year comparative, same fy);
    # only the later `end` date per accession must be kept.
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)
    fy2023 = result.data.annual[1]

    assert fy2023.period.label == "FY2023"
    assert fy2023.total_assets == pytest.approx(411976000000)  # not the FY2022 comparative 364,840,000,000


async def test_q4_is_derived_as_fy_minus_q1_q2_q3(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)
    q4 = next(p for p in result.data.quarterly if p.period.label == "FY2024Q4")

    assert q4.period.form == "derived"
    assert q4.period.accession_number is None
    expected = 245122000000 - (56517000000 + 62020000000 + 61858000000)
    assert q4.revenue == pytest.approx(expected)
    ev = next(e for e in result.evidence if e.id == q4.evidence_ids["revenue"])
    assert "derived as FY2024 total minus Q1+Q2+Q3" in ev.text


async def test_reported_quarters_are_not_marked_derived(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)
    q1 = next(p for p in result.data.quarterly if p.period.label == "FY2024Q1")

    assert q1.period.form == "10-Q"
    assert q1.revenue == pytest.approx(56517000000)


async def test_evidence_ids_cover_every_populated_line_item(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=1)
    fy = result.data.annual[0]

    for item, ev_id in fy.evidence_ids.items():
        assert fy.value(item) is not None
        assert any(e.id == ev_id for e in result.evidence)


async def test_one_source_per_accession_with_expected_shape(respx_mock, fundamentals, companyfacts_msft, msft_identity):
    respx_mock.get(company_facts_url(msft_identity.cik)).respond(json=companyfacts_msft)

    result = await fundamentals.get_statements(msft_identity, years=3)

    accessions = [s.metadata["accession"] for s in result.sources]
    assert len(accessions) == len(set(accessions))
    for source in result.sources:
        assert source.kind == SourceKind.XBRL_FACTS
        assert source.publisher == "U.S. SEC EDGAR"
        assert source.provider == "sec_edgar"
        assert source.url is not None
        assert source.url.endswith("-index.htm")
    assert set(result.data.source_ids) == {s.id for s in result.sources}


async def test_snapshot_provenance_propagates_to_sources(
    fundamentals, companyfacts_msft, msft_identity, settings, memory_cache, snapshot_store
):
    from meridian.core.http import HttpClient
    from meridian.providers.sec.endpoints import company_facts_url as facts_url
    from meridian.providers.sec.facts import SecFundamentalsProvider as Provider

    snapshot_store.save("sec_edgar", facts_url(msft_identity.cik), None, companyfacts_msft, "json")
    snapshot_settings = settings.model_copy(update={"data_mode": "snapshot"})
    client = HttpClient(snapshot_settings, memory_cache, snapshot_store)
    provider = Provider(client)

    result = await provider.get_statements(msft_identity, years=1)

    assert result.is_snapshot is True
    assert result.sources
    assert all(s.is_snapshot for s in result.sources)
    assert all(s.snapshot_date is not None for s in result.sources)
    await client.aclose()
