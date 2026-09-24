"""US Treasury macro indicator provider.

The Fiscal Data "average interest rates" dataset
(``https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates``)
is reachable (verified live 2026-09-24) but reports the average rate the government pays across whole
security *categories* (Treasury Bills / Notes / Bonds / TIPS / FRN) -- it has no 3-month / 2-year / 10-year
*tenor* breakdown, so it cannot produce the ``ust_3m`` / ``ust_2y`` / ``ust_10y`` series this provider is
required to expose. Per the implementation plan's documented fallback, this provider instead uses the
Daily Treasury Par Yield Curve CSV, which is also keyless, also reachable (verified live 2026-09-24), and
has exactly the named tenor columns needed (``3 Mo``, ``2 Yr``, ``10 Yr``, plus others we don't use).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError
from meridian.core.http import HttpClient
from meridian.core.ids import utcnow
from meridian.providers.base import MacroIndicator, MacroPoint, ProviderResult
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind

TREASURY_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
)

# indicator key -> (CSV column name, human label)
TENORS: dict[str, tuple[str, str]] = {
    "ust_3m": ("3 Mo", "3-Month Treasury Yield"),
    "ust_2y": ("2 Yr", "2-Year Treasury Yield"),
    "ust_10y": ("10 Yr", "10-Year Treasury Yield"),
}

MAX_HISTORY_POINTS = 260  # roughly one trading year


class TreasuryMacroProvider:
    """Keyless daily par-yield-curve macro indicators from the US Treasury."""

    name = "us_treasury"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def get_indicators(self) -> ProviderResult[list[MacroIndicator]]:
        today = utcnow().date()
        rows = await self._fetch_year(today.year)
        if len(rows) < 10 and today.month == 1:
            # Early January: this year's file may barely have started. Prepend last year's tail.
            rows = await self._fetch_year(today.year - 1) + rows
        if not rows:
            raise ProviderError(self.name, "no treasury par-yield rows returned", retryable=False)
        rows.sort(key=lambda r: r[0])

        source = Source.make(
            kind=SourceKind.MACRO,
            title="US Treasury Daily Par Yield Curve Rates",
            provider=self.name,
            publisher="U.S. Department of the Treasury",
            url=self._year_url(today.year),
        )

        indicators: list[MacroIndicator] = []
        evidence: list[Evidence] = []
        for key, (column, label) in TENORS.items():
            points = [MacroPoint(day=day, value=values[column]) for day, values in rows if column in values][
                -MAX_HISTORY_POINTS:
            ]
            if not points:
                continue
            latest = points[-1]
            indicators.append(
                MacroIndicator(
                    key=key, label=label, unit="percent", latest=latest.value, as_of=latest.day, history=points
                )
            )
            evidence.append(
                Evidence.make(
                    source_id=source.id,
                    text=f"U.S. Treasury ({latest.day.isoformat()}): {label} was {latest.value:.2f}%.",
                    locator=EvidenceLocator(period=latest.day.isoformat()),
                )
            )

        if not indicators:
            raise ProviderError(self.name, "expected treasury tenor columns not found", retryable=False)

        return ProviderResult(data=indicators, provider=self.name, sources=[source], evidence=evidence)

    async def _fetch_year(self, year: int) -> list[tuple[date, dict[str, float]]]:
        url = self._year_url(year)
        result = await self._http.get_text(
            url,
            provider=self.name,
            policy=Policies.MACRO,
            params={"type": "daily_treasury_yield_curve", "field_tdr_date_value": str(year), "_format": "csv"},
        )
        return _parse_csv(result.body, provider=self.name)

    def _year_url(self, year: int) -> str:
        return TREASURY_CSV_URL.format(year=year)


def _parse_csv(text: str, *, provider: str) -> list[tuple[date, dict[str, float]]]:
    stripped = text.strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    if not first_line.startswith("Date,"):
        raise ProviderError(provider, "unexpected response body (not the treasury CSV)", retryable=False)
    reader = csv.DictReader(io.StringIO(stripped))
    rows: list[tuple[date, dict[str, float]]] = []
    for row in reader:
        try:
            day = datetime.strptime(row["Date"], "%m/%d/%Y").date()
        except (KeyError, ValueError):
            continue
        values: dict[str, float] = {}
        for column, raw in row.items():
            if column == "Date" or raw in (None, ""):
                continue
            try:
                values[column] = float(raw)
            except ValueError:
                continue
        rows.append((day, values))
    if not rows:
        raise ProviderError(provider, "no usable rows in treasury CSV", retryable=False)
    return rows
