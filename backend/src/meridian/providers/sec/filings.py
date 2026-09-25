"""SEC EDGAR filings provider: filing lists (10-K/10-Q/8-K) and raw filing documents."""

from __future__ import annotations

from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from meridian.cache.base import Policies
from meridian.core.http import HttpClient
from meridian.providers.base import FilingDocument, FilingRef, ProviderResult
from meridian.providers.sec.endpoints import accession_nodashes, filing_document_url, submissions_url
from meridian.schemas.research import CompanyIdentity


class SecFilingsProvider:
    """FilingsProvider backed by SEC EDGAR submissions and Archives documents."""

    name = "sec_edgar"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def list_filings(
        self, company: CompanyIdentity, forms: tuple[str, ...] = ("10-K", "10-Q", "8-K"), limit: int = 20
    ) -> ProviderResult[list[FilingRef]]:
        url = submissions_url(company.cik)
        result = await self._http.get_json(url, provider=self.name, policy=Policies.SUBMISSIONS)
        recent: dict[str, list[Any]] = result.body["filings"]["recent"]
        cik_int = int(company.cik)

        def col(name: str, i: int) -> Any:
            values = recent.get(name) or []
            return values[i] if i < len(values) else None

        refs: list[FilingRef] = []
        for i, form in enumerate(recent.get("form", [])):
            if form not in forms:
                continue
            accession = col("accessionNumber", i)
            filing_date_raw = col("filingDate", i)
            report_date_raw = col("reportDate", i)
            primary_document = col("primaryDocument", i) or ""
            items_raw = col("items", i) or ""
            items = [x.strip() for x in items_raw.split(",") if x.strip()]
            accn_nodash = accession_nodashes(accession)
            refs.append(
                FilingRef(
                    cik=company.cik,
                    ticker=company.ticker,
                    form=form,
                    accession_number=accession,
                    filing_date=date.fromisoformat(filing_date_raw),
                    report_date=date.fromisoformat(report_date_raw) if report_date_raw else None,
                    primary_document=primary_document,
                    url=filing_document_url(cik_int, accn_nodash, primary_document),
                    description=col("primaryDocDescription", i),
                    items=items,
                )
            )
        refs.sort(key=lambda r: r.filing_date, reverse=True)
        refs = refs[:limit]
        return ProviderResult(data=refs, provider=self.name, is_snapshot=result.from_snapshot, cached=result.from_cache)

    async def fetch_document(self, filing: FilingRef) -> ProviderResult[FilingDocument]:
        result = await self._http.get_text(
            filing.url, provider=self.name, policy=Policies.FILING_DOCUMENT, snapshot_transform=_strip_for_snapshot
        )
        doc = FilingDocument(ref=filing, html=result.body)
        return ProviderResult(data=doc, provider=self.name, is_snapshot=result.from_snapshot, cached=result.from_cache)


def _strip_for_snapshot(html: str) -> str:
    """Strip <script>, <style> and the inline-XBRL hidden header before recording a snapshot."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for header in soup.find_all("ix:header"):
        header.decompose()
    for hidden in soup.select('[style*="display:none"]'):
        hidden.decompose()
    return str(soup)
