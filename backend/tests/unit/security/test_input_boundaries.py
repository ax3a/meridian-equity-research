"""Untrusted input must be constrained before it can reach an outbound URL or a prompt.

Tickers are interpolated into provider URL paths, so a ticker carrying "../" or CRLF would otherwise be
built into a request. The SSRF host allowlist is the primary control; this is defence in depth at the
schema boundary.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from meridian.core.errors import BlockedURLError
from meridian.core.http import validate_url
from meridian.schemas.research import CompanyIdentity, ResearchRequest

HOSTILE_TICKERS = [
    "../../etc/passwd",
    "MSFT/../../admin",
    "MSFT\r\nHost: evil.com",
    "MSFT?redirect=http://evil.com",
    "MSFT#fragment",
    "MSFT ",
    "'; DROP TABLE companies;--",
    "<script>alert(1)</script>",
    "A" * 40,
]


@pytest.mark.parametrize("ticker", HOSTILE_TICKERS)
def test_hostile_tickers_are_rejected_on_the_request(ticker):
    with pytest.raises(ValidationError):
        ResearchRequest(query="Analyse something", ticker=ticker)


@pytest.mark.parametrize("ticker", HOSTILE_TICKERS)
def test_hostile_tickers_are_rejected_on_company_identity(ticker):
    with pytest.raises(ValidationError):
        CompanyIdentity(name="Evil Corp", ticker=ticker, cik="0000000001")


@pytest.mark.parametrize("ticker", ["MSFT", "NVDA", "BRK.B", "RDS-A", "aapl", "F"])
def test_real_tickers_are_accepted(ticker):
    assert ResearchRequest(query="Analyse it", ticker=ticker).ticker == ticker
    assert CompanyIdentity(name="Co", ticker=ticker, cik="1").ticker == ticker.upper()


@pytest.mark.parametrize(
    "url",
    [
        "http://www.sec.gov/files/company_tickers.json",  # not https
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata by IP
        "https://127.0.0.1:8000/api/v1/research",  # loopback
        "https://localhost/admin",  # not allowlisted
        "https://evil.com/steal",  # not allowlisted
        "https://user:pass@www.sec.gov/files",  # embedded credentials
        "https://www.sec.gov:8443/files",  # non-standard port
        "file:///etc/passwd",
    ],
)
def test_ssrf_guard_blocks_untrusted_destinations(url):
    with pytest.raises(BlockedURLError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sec.gov/files/company_tickers.json",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json",
        "https://api.gdeltproject.org/api/v2/doc/doc",
    ],
)
def test_ssrf_guard_allows_declared_providers(url):
    assert validate_url(url)
