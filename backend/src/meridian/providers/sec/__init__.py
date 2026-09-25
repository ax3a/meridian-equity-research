"""SEC EDGAR provider suite: company directory, filings, fundamentals and peer universe.

Every provider here is keyless and talks only to ``www.sec.gov`` / ``data.sec.gov`` through the
shared, frozen ``meridian.core.http.HttpClient`` (SEC User-Agent, rate limiting, caching, retries,
SSRF allowlist and snapshot fallback all handled there).
"""

from __future__ import annotations

from meridian.providers.sec.directory import SecCompanyDirectory
from meridian.providers.sec.facts import SecFundamentalsProvider
from meridian.providers.sec.filings import SecFilingsProvider
from meridian.providers.sec.peers import SecPeerUniverseProvider

__all__ = [
    "SecCompanyDirectory",
    "SecFilingsProvider",
    "SecFundamentalsProvider",
    "SecPeerUniverseProvider",
]
