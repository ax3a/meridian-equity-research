"""Builds `SystemStatus`/`ProviderStatus`: a human-readable snapshot of what this process is actually
using -- which optional data providers have keys configured, and whether Postgres/Redis are reachable.
"""

from __future__ import annotations

from meridian.core.config import Settings
from meridian.schemas.api import ProviderStatus, SystemStatus

MERIDIAN_VERSION = "0.1.0"  # kept in lockstep with pyproject.toml's [project].version


def build_provider_statuses(settings: Settings) -> list[ProviderStatus]:
    return [
        ProviderStatus(name="SEC EDGAR", role="directory/fundamentals/filings/peers", configured=True),
        ProviderStatus(name="Yahoo Finance", role="market", configured=True, detail="falls back to Stooq"),
        ProviderStatus(name="GDELT", role="news", configured=True),
        ProviderStatus(name="US Treasury", role="macro", configured=True),
        ProviderStatus(
            name="Anthropic",
            role="llm",
            configured=settings.llm_mode == "anthropic",
            detail=None
            if settings.llm_mode == "anthropic"
            else "no ANTHROPIC_API_KEY; using deterministic offline mode",
        ),
        ProviderStatus(
            name="Financial Modeling Prep", role="fundamentals/market/peers", configured=bool(settings.fmp_api_key)
        ),
        ProviderStatus(name="Alpha Vantage", role="market", configured=bool(settings.alpha_vantage_api_key)),
        ProviderStatus(name="Finnhub", role="market/news/peers", configured=bool(settings.finnhub_api_key)),
        ProviderStatus(name="Polygon", role="market", configured=bool(settings.polygon_api_key)),
        ProviderStatus(name="FRED", role="macro", configured=bool(settings.fred_api_key)),
    ]


def build_system_status(
    settings: Settings, *, db_available: bool, redis_available: bool, active_runs: int
) -> SystemStatus:
    return SystemStatus(
        version=MERIDIAN_VERSION,
        llm_mode=settings.llm_mode,
        data_mode=settings.data_mode,
        database=db_available,
        redis=redis_available,
        providers=build_provider_statuses(settings),
        active_runs=active_runs,
    )
