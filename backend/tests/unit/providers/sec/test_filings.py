from __future__ import annotations

from datetime import date

import pytest

from meridian.providers.base import FilingRef
from meridian.providers.sec.endpoints import filing_document_url, submissions_url
from meridian.providers.sec.filings import SecFilingsProvider, _strip_for_snapshot


@pytest.fixture
def filings_provider(http_client):
    return SecFilingsProvider(http_client)


async def test_list_filings_filters_to_requested_forms(respx_mock, filings_provider, submissions_msft, msft_identity):
    respx_mock.get(submissions_url(msft_identity.cik)).respond(json=submissions_msft)

    result = await filings_provider.list_filings(msft_identity, forms=("10-K", "10-Q", "8-K"), limit=20)

    forms = {r.form for r in result.data}
    assert forms <= {"10-K", "10-Q", "8-K"}
    assert "4" not in forms


async def test_list_filings_newest_first(respx_mock, filings_provider, submissions_msft, msft_identity):
    respx_mock.get(submissions_url(msft_identity.cik)).respond(json=submissions_msft)

    result = await filings_provider.list_filings(msft_identity)
    dates = [r.filing_date for r in result.data]

    assert dates == sorted(dates, reverse=True)


async def test_list_filings_respects_limit(respx_mock, filings_provider, submissions_msft, msft_identity):
    respx_mock.get(submissions_url(msft_identity.cik)).respond(json=submissions_msft)

    result = await filings_provider.list_filings(msft_identity, limit=2)

    assert len(result.data) == 2


async def test_8k_items_split_on_comma(respx_mock, filings_provider, submissions_msft, msft_identity):
    respx_mock.get(submissions_url(msft_identity.cik)).respond(json=submissions_msft)

    result = await filings_provider.list_filings(msft_identity, forms=("8-K",), limit=20)
    newest_8k = result.data[0]

    assert newest_8k.items == ["2.02", "9.01"]


async def test_10k_ref_url_points_at_the_fetchable_document(
    respx_mock, filings_provider, submissions_msft, msft_identity
):
    respx_mock.get(submissions_url(msft_identity.cik)).respond(json=submissions_msft)

    result = await filings_provider.list_filings(msft_identity, forms=("10-K",), limit=1)
    ref = result.data[0]

    assert ref.url == filing_document_url(789019, "000095017024087843", "msft-20240630.htm")


async def test_fetch_document_returns_raw_html(respx_mock, filings_provider):
    ref = FilingRef(
        cik="0000789019",
        ticker="MSFT",
        form="10-K",
        accession_number="0000950170-24-087843",
        filing_date=date(2024, 7, 30),
        primary_document="msft-20240630.htm",
        url=filing_document_url(789019, "000095017024087843", "msft-20240630.htm"),
    )
    html = "<html><body><p>Item 1. Business</p></body></html>"
    respx_mock.get(ref.url).respond(text=html)

    result = await filings_provider.fetch_document(ref)

    assert result.data.ref == ref
    assert "Item 1. Business" in result.data.html


def test_strip_for_snapshot_removes_scripts_styles_and_ix_header():
    html = (
        "<html><head><script>evil()</script><style>.a{color:red}</style></head>"
        "<body><ix:header>hidden xbrl</ix:header>"
        '<div style="display:none">hidden div</div>'
        "<p>Item 1. Business is retained.</p></body></html>"
    )

    stripped = _strip_for_snapshot(html)

    assert "evil()" not in stripped
    assert "color:red" not in stripped
    assert "hidden xbrl" not in stripped
    assert "hidden div" not in stripped
    assert "Item 1. Business is retained." in stripped
