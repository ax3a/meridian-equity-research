"""Financial Modeling Prep (FMP) provider: fundamentals, market data and a peer ticker list.

Optional: requires an API key. Fundamentals are assembled from FMP's three separate statement endpoints
(income statement, balance sheet, cash flow), joined on FMP's own ``date`` (period-end) field.

Like Finnhub, FMP's stock-peers endpoint returns bare ticker symbols with no CIK -- see the note in
``providers.optional.finnhub`` for why candidates here carry a placeholder identity and a warning.
"""

from __future__ import annotations

from datetime import datetime

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.core.http import HttpClient
from meridian.providers.base import PeerCandidate, ProviderResult
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import FinancialPeriod, FinancialStatements, PeriodFinancials, PricePoint, Quote
from meridian.schemas.research import CompanyIdentity

BASE_V3 = "https://financialmodelingprep.com/api/v3"
BASE_V4 = "https://financialmodelingprep.com/api/v4"

# PeriodFinancials field -> FMP field name, and which statement it comes from.
_INCOME_FIELDS = {
    "revenue": "revenue",
    "cost_of_revenue": "costOfRevenue",
    "gross_profit": "grossProfit",
    "research_and_development": "researchAndDevelopmentExpenses",
    "operating_income": "operatingIncome",
    "interest_expense": "interestExpense",
    "income_tax_expense": "incomeTaxExpense",
    "net_income": "netIncome",
    "eps_basic": "eps",
    "eps_diluted": "epsdiluted",
    "shares_diluted": "weightedAverageShsOutDil",
}
_BALANCE_FIELDS = {
    "cash_and_equivalents": "cashAndCashEquivalents",
    "short_term_investments": "shortTermInvestments",
    "current_assets": "totalCurrentAssets",
    "total_assets": "totalAssets",
    "current_liabilities": "totalCurrentLiabilities",
    "total_liabilities": "totalLiabilities",
    "long_term_debt": "longTermDebt",
    "current_debt": "shortTermDebt",
    "shareholders_equity": "totalStockholdersEquity",
}
_CASHFLOW_FIELDS = {
    "depreciation_amortization": "depreciationAndAmortization",
    "operating_cash_flow": "netCashProvidedByOperatingActivities",
}


class FmpProvider:
    """Fundamentals, prices and peers from Financial Modeling Prep. Requires ``FMP_API_KEY``."""

    name = "fmp"

    def __init__(self, http: HttpClient, api_key: str | None) -> None:
        self._http = http
        self._api_key = api_key

    def _require_key(self) -> str:
        if not self._api_key:
            raise ProviderUnavailableError(self.name, "no API key configured")
        return self._api_key

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        key = self._require_key()
        symbol = ticker.strip().upper()
        result = await self._http.get_json(
            f"{BASE_V3}/historical-price-full/{symbol}",
            provider=self.name,
            policy=Policies.PRICES,
            params={"apikey": key, "timeseries": history_days},
        )
        raw = (result.body or {}).get("historical") or []
        points: list[PricePoint] = []
        for row in raw:
            try:
                day = datetime.strptime(row["date"], "%Y-%m-%d").date()
                close = float(row["close"])
            except (KeyError, ValueError, TypeError):
                continue
            volume = float(row["volume"]) if row.get("volume") is not None else None
            points.append(PricePoint(day=day, close=close, volume=volume))
        if not points:
            raise ProviderError(self.name, f"no usable price rows for {symbol}", retryable=False)
        points.sort(key=lambda p: p.day)
        trimmed = points[-history_days:] if history_days > 0 else points
        last = trimmed[-1]

        source = Source.make(
            kind=SourceKind.MARKET_DATA,
            title=f"FMP daily prices: {symbol}",
            provider=self.name,
            publisher="Financial Modeling Prep",
            url=f"https://financialmodelingprep.com/financial-summary/{symbol}",
        )
        evidence = Evidence.make(
            source_id=source.id,
            text=f"FMP ({last.day.isoformat()}): {symbol} closed at {last.close:.2f}.",
            locator=EvidenceLocator(period=last.day.isoformat()),
        )
        quote = Quote(ticker=symbol, price=last.close, as_of=last.day, source_id=source.id, history=trimmed)
        return ProviderResult(data=quote, provider=self.name, sources=[source], evidence=[evidence])

    async def get_statements(self, company: CompanyIdentity, years: int = 5) -> ProviderResult[FinancialStatements]:
        key = self._require_key()
        symbol = company.ticker
        income, balance, cashflow = (
            await self._statement("income-statement", symbol, key, years),
            await self._statement("balance-sheet-statement", symbol, key, years),
            await self._statement("cash-flow-statement", symbol, key, years),
        )
        by_date_balance = {row.get("date"): row for row in balance if row.get("date")}
        by_date_cashflow = {row.get("date"): row for row in cashflow if row.get("date")}

        periods: list[PeriodFinancials] = []
        sources: list[Source] = []
        for row in income:
            period_end_str = row.get("date")
            if not period_end_str:
                continue
            try:
                period_end = datetime.strptime(period_end_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            fiscal_year = int(row.get("calendarYear") or period_end.year)
            fmp_period = row.get("period") or "FY"
            fiscal_period = fmp_period if fmp_period in ("FY", "Q1", "Q2", "Q3", "Q4") else "FY"
            label = f"FY{fiscal_year}" if fiscal_period == "FY" else f"FY{fiscal_year}{fiscal_period}"

            source = Source.make(
                kind=SourceKind.XBRL_FACTS,
                title=f"FMP financial statements: {symbol} {label}",
                provider=self.name,
                publisher="Financial Modeling Prep",
                url=f"https://financialmodelingprep.com/financial-summary/{symbol}",
                metadata={"period_end": period_end_str},
            )
            evidence_id = Evidence.make(
                source_id=source.id,
                text=f"FMP reported statements for {symbol} for the period ended {period_end_str}.",
                locator=EvidenceLocator(period=label),
            ).id

            values: dict[str, float | None] = {}
            evidence_ids: dict[str, str] = {}
            balance_row = by_date_balance.get(period_end_str, {})
            cashflow_row = by_date_cashflow.get(period_end_str, {})
            for target_map, source_row in (
                (_INCOME_FIELDS, row),
                (_BALANCE_FIELDS, balance_row),
                (_CASHFLOW_FIELDS, cashflow_row),
            ):
                for field, fmp_key in target_map.items():
                    value = _to_float(source_row.get(fmp_key))
                    values[field] = value
                    if value is not None:
                        evidence_ids[field] = evidence_id
            capex_raw = _to_float(cashflow_row.get("capitalExpenditure"))
            if capex_raw is not None:
                values["capex"] = abs(capex_raw)
                evidence_ids["capex"] = evidence_id

            periods.append(
                PeriodFinancials(
                    period=FinancialPeriod(
                        label=label,
                        fiscal_year=fiscal_year,
                        fiscal_period=fiscal_period,
                        period_end=period_end,
                    ),
                    evidence_ids=evidence_ids,
                    **values,
                )
            )
            sources.append(source)

        if not periods:
            raise ProviderError(self.name, f"no usable financial statement periods for {symbol}", retryable=False)
        periods.sort(key=lambda p: p.period.period_end)

        statements = FinancialStatements(
            ticker=symbol,
            annual=[p for p in periods if p.period.fiscal_period == "FY"],
            quarterly=[p for p in periods if p.period.fiscal_period != "FY"],
            source_ids=[s.id for s in sources],
        )
        evidence = [Evidence.make(source_id=s.id, text=s.title, locator=EvidenceLocator()) for s in sources]
        return ProviderResult(data=statements, provider=self.name, sources=sources, evidence=evidence)

    async def _statement(self, endpoint: str, symbol: str, key: str, years: int) -> list[dict]:
        result = await self._http.get_json(
            f"{BASE_V3}/{endpoint}/{symbol}",
            provider=self.name,
            policy=Policies.COMPANY_FACTS,
            params={"apikey": key, "period": "annual", "limit": years},
        )
        body = result.body
        return body if isinstance(body, list) else []

    async def candidate_peers(self, company: CompanyIdentity, limit: int = 12) -> ProviderResult[list[PeerCandidate]]:
        key = self._require_key()
        result = await self._http.get_json(
            f"{BASE_V4}/stock_peers",
            provider=self.name,
            policy=Policies.PROFILE,
            params={"symbol": company.ticker, "apikey": key},
        )
        body = result.body or []
        peers_list = body[0].get("peersList", []) if body else []
        tickers = [t for t in peers_list if isinstance(t, str) and t.upper() != company.ticker.upper()][:limit]

        source = Source.make(
            kind=SourceKind.PEER_DATA,
            title=f"FMP peers: {company.ticker}",
            provider=self.name,
            publisher="Financial Modeling Prep",
            url=f"https://financialmodelingprep.com/financial-summary/{company.ticker}",
        )
        candidates = [
            PeerCandidate(
                company=CompanyIdentity(name=ticker, ticker=ticker, cik="0"), reason="Listed as an FMP stock peer"
            )
            for ticker in tickers
        ]
        evidence = [
            Evidence.make(
                source_id=source.id,
                text=f"FMP lists {ticker} as a peer of {company.ticker}.",
                locator=EvidenceLocator(),
            )
            for ticker in tickers
        ]
        limitation = "fmp peers are ticker-only: name and CIK are placeholders pending directory lookup"
        warnings = [limitation] if tickers else []
        return ProviderResult(
            data=candidates,
            provider=self.name,
            sources=[source] if tickers else [],
            evidence=evidence,
            warnings=warnings,
        )


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
