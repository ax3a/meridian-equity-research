"""SEC EDGAR company directory: ticker/name resolution and entity profile."""

from __future__ import annotations

import difflib
from typing import Any

from meridian.cache.base import Policies
from meridian.core.errors import CompanyNotFoundError
from meridian.core.http import HttpClient
from meridian.providers.base import CompanyProfile, ProviderResult
from meridian.providers.sec.endpoints import COMPANY_TICKERS_URL, submissions_url
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.research import CompanyIdentity

PUBLISHER = "U.S. SEC EDGAR"
RESOLVE_CUTOFF = 0.75


class SecCompanyDirectory:
    """CompanyDirectory backed by SEC's ticker directory and submissions API."""

    name = "sec_edgar"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def _tickers(self) -> list[dict[str, Any]]:
        result = await self._http.get_json(COMPANY_TICKERS_URL, provider=self.name, policy=Policies.TICKERS)
        return list(result.body.values())

    @staticmethod
    def _to_identity(row: dict[str, Any]) -> CompanyIdentity:
        return CompanyIdentity(name=row["title"], ticker=row["ticker"], cik=str(row["cik_str"]))

    async def search(self, query: str, limit: int = 10) -> list[CompanyIdentity]:
        rows = await self._tickers()
        q = query.strip().lower()
        if not q:
            return []
        prefix = [r for r in rows if str(r["ticker"]).lower().startswith(q)]
        substring = [r for r in rows if q in str(r["title"]).lower()]
        seen: set[int] = set()
        ordered: list[dict[str, Any]] = []
        for r in (*prefix, *substring):
            if r["cik_str"] not in seen:
                seen.add(r["cik_str"])
                ordered.append(r)
        return [self._to_identity(r) for r in ordered[:limit]]

    async def resolve(self, query: str) -> CompanyIdentity:
        rows = await self._tickers()
        q = query.strip()
        if not q:
            raise CompanyNotFoundError("empty query")

        for r in rows:
            if str(r["ticker"]).upper() == q.upper():
                return self._to_identity(r)
        for r in rows:
            if str(r["title"]).lower() == q.lower():
                return self._to_identity(r)

        # SEC titles are upper case ("MICROSOFT CORP"), so all name matching is case-insensitive.
        # Prefer a prefix match, then a substring match, taking the shortest title (the parent entity
        # rather than a longer subsidiary/fund name), before falling back to fuzzy matching.
        ql = q.lower()
        lowered = [(str(r["title"]).lower(), r) for r in rows]
        for bucket in ([r for t, r in lowered if t.startswith(ql)], [r for t, r in lowered if ql in t]):
            if bucket:
                return self._to_identity(min(bucket, key=lambda r: len(str(r["title"]))))

        best = difflib.get_close_matches(ql, [t for t, _ in lowered], n=1, cutoff=RESOLVE_CUTOFF)
        if best:
            for title, r in lowered:
                if title == best[0]:
                    return self._to_identity(r)

        raise CompanyNotFoundError(f"no company found for '{query}'")

    async def profile(self, company: CompanyIdentity) -> ProviderResult[CompanyProfile]:
        url = submissions_url(company.cik)
        result = await self._http.get_json(url, provider=self.name, policy=Policies.SUBMISSIONS)
        body: dict[str, Any] = result.body

        exchanges = body.get("exchanges") or []
        sic = body.get("sic") or company.sic
        sic_description = body.get("sicDescription")
        entity_type = body.get("entityType")

        identity = CompanyIdentity(
            name=body.get("name", company.name),
            ticker=company.ticker,
            cik=company.cik,
            exchange=exchanges[0] if exchanges else None,
            sic=sic,
            sic_description=sic_description,
            fiscal_year_end=body.get("fiscalYearEnd"),
            state_of_incorporation=body.get("stateOfIncorporation"),
            website=body.get("website") or None,
        )
        description = " - ".join(p for p in (sic_description, entity_type) if p) or None
        former_names = [fn.get("name", "") for fn in body.get("formerNames", []) if fn.get("name")]

        profile = CompanyProfile(
            identity=identity,
            description=description,
            former_names=former_names,
            business_address=_format_address(body.get("addresses", {}).get("business")),
            category=body.get("category"),
        )

        source = Source.make(
            kind=SourceKind.COMPANY_PROFILE,
            title=f"{identity.name} SEC EDGAR submissions",
            provider=self.name,
            publisher=PUBLISHER,
            url=url,
            published_at=None,
            metadata={"cik": company.cik},
        )
        text = (
            f"{identity.name} (CIK {company.cik}): SIC {identity.sic} ({identity.sic_description}), "
            f"exchange {identity.exchange}, fiscal year end {identity.fiscal_year_end}, "
            f"state of incorporation {identity.state_of_incorporation}, category {profile.category}"
        )
        evidence = Evidence.make(source_id=source.id, text=text, locator=EvidenceLocator(section="submissions"))

        is_snapshot = result.from_snapshot
        if is_snapshot:
            source.is_snapshot = True
            source.snapshot_date = result.snapshot_date

        return ProviderResult(
            data=profile,
            provider=self.name,
            sources=[source],
            evidence=[evidence],
            is_snapshot=is_snapshot,
            cached=result.from_cache,
        )


def _format_address(addr: dict[str, Any] | None) -> str | None:
    if not addr:
        return None
    parts = [
        addr.get("street1"),
        addr.get("street2"),
        addr.get("city"),
        addr.get("stateOrCountry"),
        addr.get("zipCode"),
    ]
    joined = ", ".join(p for p in parts if p)
    return joined or None
