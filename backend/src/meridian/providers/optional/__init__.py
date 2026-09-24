"""Optional key-based data providers.

Every adapter here raises ``ProviderUnavailableError`` immediately when its API key is absent, so it can
sit at the end of a fallback chain without ever being contacted -- never crashing, never inventing data.
API keys are always passed as HTTP query params via ``HttpClient`` (never headers built by hand, never
logged), so they are redacted from cache keys and snapshots by ``meridian.providers.snapshots.SECRET_PARAMS``.
"""

from __future__ import annotations

from meridian.providers.optional.alpha_vantage import AlphaVantageProvider
from meridian.providers.optional.finnhub import FinnhubProvider
from meridian.providers.optional.fmp import FmpProvider
from meridian.providers.optional.fred import FredMacroProvider
from meridian.providers.optional.polygon import PolygonProvider

__all__ = ["AlphaVantageProvider", "FinnhubProvider", "FmpProvider", "FredMacroProvider", "PolygonProvider"]
