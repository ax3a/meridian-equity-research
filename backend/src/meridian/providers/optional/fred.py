"""FRED (Federal Reserve Economic Data) macro provider. Optional: requires an API key.

Series used: ``CPIAUCSL`` (CPI, YoY inflation is computed from the monthly level), ``FEDFUNDS`` (federal
funds rate, used as-is), ``UNRATE`` (unemployment rate, used as-is), ``GDPC1`` (real GDP level, YoY growth
is computed from the quarterly level).
"""

from __future__ import annotations

from datetime import date, datetime

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.core.http import HttpClient
from meridian.providers.base import MacroIndicator, MacroPoint, ProviderResult
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

# indicator key -> (series id, label, year-over-year lag in observations; 0 = use the level as-is)
SERIES: tuple[tuple[str, str, str, int], ...] = (
    ("cpi_yoy", "CPIAUCSL", "CPI YoY Inflation", 12),
    ("fed_funds", "FEDFUNDS", "Federal Funds Rate", 0),
    ("unemployment", "UNRATE", "Unemployment Rate", 0),
    ("real_gdp_growth", "GDPC1", "Real GDP Growth (YoY)", 4),
)


class FredMacroProvider:
    """Macro indicators from FRED. Requires ``FRED_API_KEY``; raises ``ProviderUnavailableError`` without one."""

    name = "fred"

    def __init__(self, http: HttpClient, api_key: str | None) -> None:
        self._http = http
        self._api_key = api_key

    async def get_indicators(self) -> ProviderResult[list[MacroIndicator]]:
        if not self._api_key:
            raise ProviderUnavailableError(self.name, "no API key configured")

        indicators: list[MacroIndicator] = []
        sources: list[Source] = []
        evidence: list[Evidence] = []
        for key, series_id, label, lag in SERIES:
            observations = await self._fetch_series(series_id)
            points = _to_points(observations) if lag == 0 else _yoy_points(observations, lag)
            if not points:
                continue
            latest = points[-1]
            source = Source.make(
                kind=SourceKind.MACRO,
                title=f"FRED series {series_id}",
                provider=self.name,
                publisher="Federal Reserve Bank of St. Louis (FRED)",
                url=f"https://fred.stlouisfed.org/series/{series_id}",
            )
            evidence.append(
                Evidence.make(
                    source_id=source.id,
                    text=f"FRED ({latest.day.isoformat()}): {label} was {latest.value:.2f}%.",
                    locator=EvidenceLocator(period=latest.day.isoformat()),
                )
            )
            indicators.append(
                MacroIndicator(
                    key=key, label=label, unit="percent", latest=latest.value, as_of=latest.day, history=points
                )
            )
            sources.append(source)

        if not indicators:
            raise ProviderError(self.name, "no usable FRED observations", retryable=False)
        return ProviderResult(data=indicators, provider=self.name, sources=sources, evidence=evidence)

    async def _fetch_series(self, series_id: str) -> list[tuple[date, float]]:
        result = await self._http.get_json(
            FRED_URL,
            provider=self.name,
            policy=Policies.MACRO,
            params={
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "sort_order": "asc",
            },
        )
        raw = (result.body or {}).get("observations", [])
        out: list[tuple[date, float]] = []
        for obs in raw:
            try:
                value = float(obs["value"])
                day = datetime.strptime(obs["date"], "%Y-%m-%d").date()
            except (KeyError, TypeError, ValueError):
                continue
            out.append((day, value))
        return out


def _to_points(observations: list[tuple[date, float]]) -> list[MacroPoint]:
    return [MacroPoint(day=day, value=value) for day, value in observations]


def _yoy_points(observations: list[tuple[date, float]], lag: int) -> list[MacroPoint]:
    points: list[MacroPoint] = []
    for i in range(lag, len(observations)):
        day, current = observations[i]
        _, prior = observations[i - lag]
        if prior:
            points.append(MacroPoint(day=day, value=(current / prior - 1) * 100))
    return points
