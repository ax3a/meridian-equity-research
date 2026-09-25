"""SEC EDGAR peer universe provider: same-SIC company lists ranked by XBRL frame revenue.

The ``browse-edgar`` Atom feed for a SIC code is confirmed live to return a valid
``application/atom+xml`` company list with real CIK values -- but SEC's server-side template has a
long-standing bug where the company name renders as the literal string ``ARRAY(0x...)`` instead of
the actual name (see the live test for a captured example). So the feed is usable for "which CIKs
are in this SIC" but not for names/tickers. We cross-reference the CIKs against
``company_tickers.json`` to recover name + ticker, which also conveniently drops any CIK that
is not a currently-traded, ticker-bearing company. If that cross-reference yields nothing (e.g. an
unclassified SIC, or the Atom feed itself is unreachable), we fall back to ranking every entry in
the XBRL revenue frame for the year, as the plan's fallback describes, and record the limitation in
``ProviderResult.warnings``.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from meridian.cache.base import Policies
from meridian.core.errors import ProviderError
from meridian.core.http import HttpClient
from meridian.providers.base import PeerCandidate, ProviderResult
from meridian.providers.sec.endpoints import COMPANY_TICKERS_URL, frames_url, peers_by_sic_atom_url
from meridian.schemas.research import CompanyIdentity

_CIK_RE = re.compile(r"<cik>0*(\d+)</cik>", re.IGNORECASE)


class SecPeerUniverseProvider:
    """PeerUniverseProvider backed by SEC's SIC browse and the us-gaap Revenues XBRL frame."""

    name = "sec_edgar"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def _tickers_by_cik(self) -> dict[int, dict[str, Any]]:
        result = await self._http.get_json(COMPANY_TICKERS_URL, provider=self.name, policy=Policies.TICKERS)
        return {int(row["cik_str"]): row for row in result.body.values()}

    async def _sic_ciks(self, sic: str) -> list[int]:
        url = peers_by_sic_atom_url(sic)
        result = await self._http.get_text(url, provider=self.name, policy=Policies.FRAMES)
        return _parse_atom_ciks(result.body)

    async def _frame_revenue(self, year: int, warnings: list[str]) -> dict[int, dict[str, Any]]:
        try:
            result = await self._http.get_json(frames_url("Revenues", year), provider=self.name, policy=Policies.FRAMES)
        except ProviderError:
            warnings.append(f"XBRL frame lookup failed for Revenues CY{year}")
            return {}
        return {int(row["cik"]): row for row in result.body.get("data", [])}

    async def candidate_peers(self, company: CompanyIdentity, limit: int = 12) -> ProviderResult[list[PeerCandidate]]:
        warnings: list[str] = []
        sic = company.sic
        if not sic:
            return ProviderResult(data=[], provider=self.name, warnings=["no SIC code known for target company"])

        ciks = await self._sic_ciks(sic)
        if not ciks:
            warnings.append(
                f"SIC browse-edgar Atom feed returned no companies for SIC {sic}; "
                "falling back to ranking XBRL frame revenue entries only"
            )

        tickers_by_cik = await self._tickers_by_cik()
        target_cik = int(company.cik)
        peer_ciks = [c for c in ciks if c != target_cik and c in tickers_by_cik]

        year = date.today().year - 1
        revenue_by_cik = await self._frame_revenue(year, warnings)

        candidates: list[PeerCandidate] = []
        if peer_ciks:
            sic_label = company.sic_description or "unclassified"
            for cik in peer_ciks:
                row = tickers_by_cik[cik]
                rev_entry = revenue_by_cik.get(cik)
                candidates.append(
                    PeerCandidate(
                        company=CompanyIdentity(name=row["title"], ticker=row["ticker"], cik=str(cik)),
                        revenue=rev_entry["val"] if rev_entry else None,
                        fiscal_period=f"CY{year}" if rev_entry else None,
                        reason=f"same SIC {sic} ({sic_label}), ranked by FY revenue",
                    )
                )
        else:
            warnings.append(
                f"no tradable peers resolved from the SIC {sic} Atom feed "
                "(likely the SEC ARRAY(0x...) company-name bug); using frame-wide revenue ranking"
            )
            for cik, entry in revenue_by_cik.items():
                if cik == target_cik or cik not in tickers_by_cik:
                    continue
                row = tickers_by_cik[cik]
                candidates.append(
                    PeerCandidate(
                        company=CompanyIdentity(name=row["title"], ticker=row["ticker"], cik=str(cik)),
                        revenue=entry["val"],
                        fiscal_period=f"CY{year}",
                        reason=f"ranked by FY revenue (SIC-based lookup unavailable for {sic})",
                    )
                )

        candidates.sort(key=lambda c: (c.revenue is None, -(c.revenue or 0)))
        return ProviderResult(data=candidates[:limit], provider=self.name, warnings=warnings)


def _parse_atom_ciks(xml_text: str) -> list[int]:
    """Extract CIKs from the browse-edgar Atom feed via regex.

    A real ``xml.etree`` parse also works, but the feed's company-name templating bug sometimes
    emits unescaped literal ``ARRAY(...)`` text inside attribute values, which is not reliably
    well-formed XML across SEC's various renderer versions. Regex on the always-well-formed
    ``<cik>...</cik>`` element is more robust here.
    """
    return [int(m) for m in _CIK_RE.findall(xml_text)]
