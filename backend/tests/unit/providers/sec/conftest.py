"""Fixtures for SEC EDGAR provider tests. Unit tests here must never touch the network (respx-mocked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def company_tickers() -> dict:
    return load_json("company_tickers.json")


@pytest.fixture
def submissions_msft() -> dict:
    return load_json("submissions_msft.json")


@pytest.fixture
def companyfacts_msft() -> dict:
    return load_json("companyfacts_msft.json")


@pytest.fixture
def frames_revenue_cy() -> dict:
    return load_json("frames_revenue_cy.json")


@pytest.fixture
def browse_edgar_sic_atom() -> str:
    return load_text("browse_edgar_sic.atom")


@pytest.fixture
def browse_edgar_sic_empty_atom() -> str:
    return load_text("browse_edgar_sic_empty.atom")


@pytest.fixture
def msft_identity():
    from meridian.schemas.research import CompanyIdentity

    return CompanyIdentity(
        name="MICROSOFT CORP",
        ticker="MSFT",
        cik="789019",
        sic="7372",
        sic_description="Services-Prepackaged Software",
    )
