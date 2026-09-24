from __future__ import annotations

import httpx
import pytest
import respx

from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.providers.optional.fmp import FmpProvider
from meridian.schemas.research import CompanyIdentity

BASE = "https://financialmodelingprep.com/api/v3"
BASE_V4 = "https://financialmodelingprep.com/api/v4"


@pytest.fixture
def provider(http_client) -> FmpProvider:
    return FmpProvider(http_client, api_key="demo-key")


@pytest.fixture
def company() -> CompanyIdentity:
    return CompanyIdentity(name="Apple Inc.", ticker="AAPL", cik="320193")


async def test_missing_key_raises_unavailable_for_every_method(http_client, company: CompanyIdentity) -> None:
    unconfigured = FmpProvider(http_client, api_key=None)

    with pytest.raises(ProviderUnavailableError):
        await unconfigured.get_quote("AAPL")
    with pytest.raises(ProviderUnavailableError):
        await unconfigured.get_statements(company)
    with pytest.raises(ProviderUnavailableError):
        await unconfigured.candidate_peers(company)


@respx.mock
async def test_get_quote_parses_historical_prices(provider: FmpProvider) -> None:
    respx.get(f"{BASE}/historical-price-full/AAPL").mock(
        return_value=httpx.Response(
            200,
            json={
                "symbol": "AAPL",
                "historical": [
                    {"date": "2026-09-03", "close": 223.4, "volume": 39000000},
                    {"date": "2026-09-02", "close": 222.75, "volume": 41000000},
                    {"date": "2026-09-01", "close": 220.9, "volume": 45000000},
                ],
            },
        )
    )

    result = await provider.get_quote("AAPL", history_days=365)

    assert provider.name == "fmp"
    assert result.data.price == pytest.approx(223.4)
    assert result.data.as_of.isoformat() == "2026-09-03"
    assert len(result.data.history) == 3


@respx.mock
async def test_get_quote_raises_on_empty_history(provider: FmpProvider) -> None:
    respx.get(f"{BASE}/historical-price-full/AAPL").mock(return_value=httpx.Response(200, json={"historical": []}))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")


@respx.mock
async def test_get_statements_joins_three_endpoints(provider: FmpProvider, company: CompanyIdentity) -> None:
    respx.get(f"{BASE}/income-statement/AAPL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2025-09-27",
                    "calendarYear": "2025",
                    "period": "FY",
                    "revenue": 400000000000,
                    "costOfRevenue": 220000000000,
                    "grossProfit": 180000000000,
                    "researchAndDevelopmentExpenses": 32000000000,
                    "operatingIncome": 120000000000,
                    "interestExpense": 4000000000,
                    "incomeTaxExpense": 20000000000,
                    "netIncome": 100000000000,
                    "eps": 6.5,
                    "epsdiluted": 6.4,
                    "weightedAverageShsOutDil": 15600000000,
                },
            ],
        )
    )
    respx.get(f"{BASE}/balance-sheet-statement/AAPL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2025-09-27",
                    "cashAndCashEquivalents": 30000000000,
                    "shortTermInvestments": 20000000000,
                    "totalCurrentAssets": 140000000000,
                    "totalAssets": 350000000000,
                    "totalCurrentLiabilities": 130000000000,
                    "totalLiabilities": 280000000000,
                    "longTermDebt": 90000000000,
                    "shortTermDebt": 10000000000,
                    "totalStockholdersEquity": 70000000000,
                },
            ],
        )
    )
    respx.get(f"{BASE}/cash-flow-statement/AAPL").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2025-09-27",
                    "depreciationAndAmortization": 11000000000,
                    "netCashProvidedByOperatingActivities": 110000000000,
                    "capitalExpenditure": -10000000000,
                },
            ],
        )
    )

    result = await provider.get_statements(company, years=5)

    assert len(result.data.annual) == 1
    period = result.data.annual[0]
    assert period.period.label == "FY2025"
    assert period.revenue == pytest.approx(400000000000)
    assert period.capex == pytest.approx(10000000000)  # stored positive despite FMP's negative sign
    assert period.shareholders_equity == pytest.approx(70000000000)
    assert "revenue" in period.evidence_ids
    assert len(result.sources) == 1
    assert len(result.evidence) >= 1


@respx.mock
async def test_get_statements_raises_when_no_periods(provider: FmpProvider, company: CompanyIdentity) -> None:
    respx.get(f"{BASE}/income-statement/AAPL").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/balance-sheet-statement/AAPL").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/cash-flow-statement/AAPL").mock(return_value=httpx.Response(200, json=[]))

    with pytest.raises(ProviderError):
        await provider.get_statements(company)


@respx.mock
async def test_candidate_peers_excludes_self_and_warns(provider: FmpProvider, company: CompanyIdentity) -> None:
    respx.get(f"{BASE_V4}/stock_peers").mock(
        return_value=httpx.Response(200, json=[{"symbol": "AAPL", "peersList": ["AAPL", "MSFT", "GOOGL"]}])
    )

    result = await provider.candidate_peers(company, limit=12)

    tickers = [c.company.ticker for c in result.data]
    assert tickers == ["MSFT", "GOOGL"]
    assert any("ticker-only" in w for w in result.warnings)


@respx.mock
async def test_get_quote_maps_http_error(provider: FmpProvider) -> None:
    respx.get(f"{BASE}/historical-price-full/AAPL").mock(return_value=httpx.Response(404))

    with pytest.raises(ProviderError):
        await provider.get_quote("AAPL")
