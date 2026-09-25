from __future__ import annotations

from datetime import date

import pytest

from meridian.providers.sec.endpoints import COMPANY_TICKERS_URL, frames_url, peers_by_sic_atom_url
from meridian.providers.sec.peers import SecPeerUniverseProvider, _parse_atom_ciks
from meridian.schemas.research import CompanyIdentity

FRAME_YEAR = date.today().year - 1


@pytest.fixture
def peers_provider(http_client):
    return SecPeerUniverseProvider(http_client)


@pytest.fixture
def nvda_identity():
    return CompanyIdentity(
        name="NVIDIA CORP", ticker="NVDA", cik="1045810", sic="3674", sic_description="Semiconductors"
    )


def test_parse_atom_ciks_survives_the_broken_company_name_field(browse_edgar_sic_atom):
    # SEC's browse-edgar Atom output has a long-standing bug where the company name renders as the
    # literal string "ARRAY(0x...)"; the CIK element is still well-formed and must still parse.
    ciks = _parse_atom_ciks(browse_edgar_sic_atom)

    assert ciks == [1045810, 320193, 999999]


def test_parse_atom_ciks_empty_feed_returns_nothing(browse_edgar_sic_empty_atom):
    assert _parse_atom_ciks(browse_edgar_sic_empty_atom) == []


async def test_candidate_peers_ranked_by_frame_revenue(
    respx_mock, peers_provider, nvda_identity, company_tickers, browse_edgar_sic_atom, frames_revenue_cy
):
    respx_mock.get(peers_by_sic_atom_url("3674")).respond(
        text=browse_edgar_sic_atom, headers={"Content-Type": "application/atom+xml"}
    )
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)
    respx_mock.get(frames_url("Revenues", FRAME_YEAR)).respond(json=frames_revenue_cy)

    result = await peers_provider.candidate_peers(nvda_identity, limit=5)
    tickers = [c.company.ticker for c in result.data]

    assert "NVDA" not in tickers  # target excluded
    assert tickers  # cross-referencing the Atom CIKs against tickers found at least one peer
    assert all(c.reason.startswith("same SIC 3674") for c in result.data)
    revenues = [c.revenue for c in result.data if c.revenue is not None]
    assert revenues == sorted(revenues, reverse=True)


async def test_candidate_peers_falls_back_to_frame_wide_ranking(
    respx_mock, peers_provider, nvda_identity, company_tickers, browse_edgar_sic_empty_atom, frames_revenue_cy
):
    respx_mock.get(peers_by_sic_atom_url("3674")).respond(text=browse_edgar_sic_empty_atom)
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)
    respx_mock.get(frames_url("Revenues", FRAME_YEAR)).respond(json=frames_revenue_cy)

    result = await peers_provider.candidate_peers(nvda_identity, limit=5)

    assert result.data  # frame-wide ranking still produced candidates
    assert any("frame-wide" in w for w in result.warnings)
    tickers = [c.company.ticker for c in result.data]
    assert "NVDA" not in tickers


async def test_candidate_peers_excludes_ciks_without_a_ticker(
    respx_mock, peers_provider, nvda_identity, company_tickers, browse_edgar_sic_atom, frames_revenue_cy
):
    respx_mock.get(peers_by_sic_atom_url("3674")).respond(text=browse_edgar_sic_atom)
    respx_mock.get(COMPANY_TICKERS_URL).respond(json=company_tickers)
    respx_mock.get(frames_url("Revenues", FRAME_YEAR)).respond(json=frames_revenue_cy)

    result = await peers_provider.candidate_peers(nvda_identity, limit=5)

    # CIK 999999 is in the Atom feed but has no entry in company_tickers.json (private/no ticker).
    assert all(c.company.cik != "0000999999" for c in result.data)


async def test_candidate_peers_no_sic_returns_empty_with_warning(peers_provider):
    target = CompanyIdentity(name="Unknown Co", ticker="UNK", cik="1", sic=None)

    result = await peers_provider.candidate_peers(target)

    assert result.data == []
    assert result.warnings
