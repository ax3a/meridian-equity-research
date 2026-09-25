"""URL builders for SEC EDGAR's free, keyless JSON/Atom/Archives endpoints.

All hosts used here (``www.sec.gov``, ``data.sec.gov``) are already present in
``meridian.core.http.ALLOWED_HOSTS``.
"""

from __future__ import annotations

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def submissions_url(cik10: str) -> str:
    """``https://data.sec.gov/submissions/CIK##########.json`` — profile + recent filings."""
    return f"https://data.sec.gov/submissions/CIK{cik10}.json"


def company_facts_url(cik10: str) -> str:
    """``https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`` — all XBRL facts."""
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"


def frames_url(concept: str, year: int, *, taxonomy: str = "us-gaap", unit: str = "USD") -> str:
    """``https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/CY{year}.json``.

    One concept, across every filer, for a single annual period.
    """
    return f"https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/CY{year}.json"


def accession_nodashes(accession: str) -> str:
    return accession.replace("-", "")


def filing_document_url(cik_int: int, accession_nodashes_: str, primary_document: str) -> str:
    """The fetchable filing document (used as ``FilingRef.url``)."""
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodashes_}/{primary_document}"


def filing_index_url(cik_int: int, accession_nodashes_: str, accession_dashed: str) -> str:
    """The human-browsable filing index page (used as ``Source.url`` for XBRL/filing evidence)."""
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodashes_}/{accession_dashed}-index.htm"


def peers_by_sic_atom_url(sic: str, *, count: int = 100) -> str:
    """The ``browse-edgar`` Atom company list for a SIC code.

    NOTE: the implementation plan's literal URL repeats ``action=getcompany`` twice, which SEC's
    server rejects outright ("File Unavailable"). This builder emits the corrected, single-action
    version, confirmed live to return a valid ``application/atom+xml`` feed.
    """
    return (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
        f"&SIC={sic}&type=10-K&dateb=&owner=include&count={count}&output=atom"
    )
