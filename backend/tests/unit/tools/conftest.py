"""Fixtures for the tools test suite: fake providers implementing the frozen provider Protocols, a
small but realistic MSFT-shaped financial fixture, and a `ToolContext` factory.

Unit tests here never touch the network -- every provider is a hand-written fake, per the task brief's
instruction to "use fake provider objects or respx" for tools tests (respx would only make sense one
layer down, inside the Batch-1 provider tests already covering that).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from meridian.core.config import Settings
from meridian.core.errors import CompanyNotFoundError, ProviderUnavailableError
from meridian.observability.events import ListEventSink
from meridian.providers.base import (
    CompanyProfile,
    FilingDocument,
    FilingRef,
    MacroIndicator,
    MacroPoint,
    NewsArticle,
    PeerCandidate,
    ProviderResult,
)
from meridian.providers.llm.offline import OfflineLLMProvider
from meridian.providers.registry import ProviderRegistry
from meridian.rag.embeddings import HashingEmbedder
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import AgentName, SourceKind
from meridian.schemas.financials import FinancialPeriod, FinancialStatements, PeriodFinancials, PricePoint, Quote
from meridian.schemas.research import CompanyIdentity
from meridian.tools.base import ToolContext

MSFT = CompanyIdentity(
    name="MICROSOFT CORP",
    ticker="MSFT",
    cik="0000789019",
    exchange="Nasdaq",
    sic="7372",
    sic_description="Services-Prepackaged Software",
    fiscal_year_end="0630",
    state_of_incorporation="WA",
)

# A bank, so is_financial_institution is True (SIC 6000-6799).
BIGBANK = CompanyIdentity(name="BIG BANK CORP", ticker="BBNK", cik="0000111111", sic="6022")


def _period_with_evidence(
    *,
    label: str,
    fy: int,
    revenue: float,
    gross_profit: float,
    operating_income: float,
    net_income: float,
    ocf: float,
    capex: float,
    shares: float,
    period_end: date,
) -> PeriodFinancials:
    period = FinancialPeriod(
        label=label,
        fiscal_year=fy,
        fiscal_period="FY",
        period_end=period_end,
        form="10-K",
        accession_number=f"0000950170-{fy}-000001",
        filed=period_end,
    )
    pf = PeriodFinancials(
        period=period,
        revenue=revenue,
        gross_profit=gross_profit,
        operating_income=operating_income,
        net_income=net_income,
        operating_cash_flow=ocf,
        capex=capex,
        shares_outstanding=shares,
        cash_and_equivalents=50_000_000_000.0,
        short_term_investments=10_000_000_000.0,
        long_term_debt=40_000_000_000.0,
        current_debt=5_000_000_000.0,
        total_assets=400_000_000_000.0,
        total_liabilities=200_000_000_000.0,
        shareholders_equity=200_000_000_000.0,
        eps_diluted=net_income / shares if shares else None,
    )
    source = Source.make(
        kind=SourceKind.XBRL_FACTS,
        title=f"MICROSOFT CORP 10-K (accession {period.accession_number})",
        provider="sec_edgar",
        publisher="U.S. SEC EDGAR",
        url=f"https://sec.gov/{period.accession_number}",
        published_at=period_end,
    )
    for field_name in (
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "capex",
        "shares_outstanding",
    ):
        value = pf.value(field_name)
        ev = Evidence.make(
            source_id=source.id,
            text=f"MICROSOFT CORP 10-K: {field_name} = {value:,.0f} for {label}",
            locator=EvidenceLocator(xbrl_concept=field_name, period=label, accession_number=period.accession_number),
        )
        pf.evidence_ids[field_name] = ev.id
    return pf


def msft_statements() -> FinancialStatements:
    fy2023 = _period_with_evidence(
        label="FY2023",
        fy=2023,
        revenue=211_915_000_000.0,
        gross_profit=146_052_000_000.0,
        operating_income=88_523_000_000.0,
        net_income=72_361_000_000.0,
        ocf=87_582_000_000.0,
        capex=28_107_000_000.0,
        shares=7_432_000_000.0,
        period_end=date(2023, 6, 30),
    )
    fy2024 = _period_with_evidence(
        label="FY2024",
        fy=2024,
        revenue=245_122_000_000.0,
        gross_profit=171_008_000_000.0,
        operating_income=109_433_000_000.0,
        net_income=88_136_000_000.0,
        ocf=118_548_000_000.0,
        capex=44_477_000_000.0,
        shares=7_434_000_000.0,
        period_end=date(2024, 6, 30),
    )
    return FinancialStatements(ticker="MSFT", annual=[fy2023, fy2024], quarterly=[])


def msft_quote() -> tuple[Quote, list[Evidence]]:
    source = Source.make(
        kind=SourceKind.MARKET_DATA,
        title="Yahoo Finance chart: MSFT",
        provider="yahoo",
        publisher="Yahoo Finance",
        url="https://finance.yahoo.com/quote/MSFT",
    )
    ev = Evidence.make(
        source_id=source.id,
        text="Yahoo Finance (2024-09-20): MSFT closed at 430.50.",
        locator=EvidenceLocator(period="2024-09-20"),
    )
    quote = Quote(
        ticker="MSFT",
        price=430.50,
        as_of=date(2024, 9, 20),
        source_id=source.id,
        history=[PricePoint(day=date(2024, 9, 20), close=430.50, volume=1_000_000.0)],
    )
    return quote, [ev], source


class FakeDirectory:
    name = "fake_directory"

    def __init__(self, identities: dict[str, CompanyIdentity] | None = None, *, profile_fails: bool = False) -> None:
        self.identities = identities or {"MSFT": MSFT, "BBNK": BIGBANK}
        self.profile_fails = profile_fails

    async def search(self, query: str, limit: int = 10) -> list[CompanyIdentity]:
        q = query.lower()
        return [c for c in self.identities.values() if q in c.ticker.lower() or q in c.name.lower()][:limit]

    async def resolve(self, query: str) -> CompanyIdentity:
        key = query.strip().upper()
        if key in self.identities:
            return self.identities[key]
        raise CompanyNotFoundError(f"no company found for '{query}'")

    async def profile(self, company: CompanyIdentity) -> ProviderResult[CompanyProfile]:
        if self.profile_fails:
            raise ProviderUnavailableError(self.name, "profile lookup unavailable")
        profile = CompanyProfile(identity=company, description=f"{company.sic_description} company")
        source = Source.make(
            kind=SourceKind.COMPANY_PROFILE,
            title=f"{company.name} profile",
            provider=self.name,
            publisher="U.S. SEC EDGAR",
            url=f"https://sec.gov/{company.cik}",
        )
        ev = Evidence.make(source_id=source.id, text=f"{company.name}: SIC {company.sic}")
        return ProviderResult(data=profile, provider=self.name, sources=[source], evidence=[ev])


class FakeFundamentals:
    name = "fake_fundamentals"

    def __init__(self, statements: FinancialStatements | None = None) -> None:
        self.statements = statements or msft_statements()

    async def get_statements(self, company: CompanyIdentity, years: int = 5) -> ProviderResult[FinancialStatements]:
        st = self.statements
        sources: dict[str, Source] = {}
        for pf in (*st.annual, *st.quarterly):
            accn = pf.period.accession_number or "unknown"
            sources.setdefault(
                accn,
                Source.make(
                    kind=SourceKind.XBRL_FACTS,
                    title=f"{company.name} 10-K ({accn})",
                    provider=self.name,
                    publisher="U.S. SEC EDGAR",
                    url=f"https://sec.gov/{accn}",
                ),
            )
        evidence = []
        for pf in (*st.annual, *st.quarterly):
            accn = pf.period.accession_number or "unknown"
            for field_name, eid in pf.evidence_ids.items():
                value = pf.value(field_name)
                text = f"{company.name} 10-K: {field_name} = {value:,.0f} for {pf.period.label}"
                evidence.append(Evidence(id=eid, source_id=sources[accn].id, text=text))
        return ProviderResult(data=st, provider=self.name, sources=list(sources.values()), evidence=evidence)


class FailingFundamentals:
    name = "failing_fundamentals"

    async def get_statements(self, company: CompanyIdentity, years: int = 5) -> ProviderResult[FinancialStatements]:
        raise ProviderUnavailableError(self.name, "no data")


class FakeFilings:
    name = "fake_filings"

    def __init__(self, refs: list[FilingRef] | None = None, html_by_accession: dict[str, str] | None = None) -> None:
        self.refs = refs if refs is not None else _default_filing_refs()
        self.html_by_accession = html_by_accession or {}

    async def list_filings(self, company: CompanyIdentity, forms=("10-K", "10-Q", "8-K"), limit: int = 20):
        matched = [r for r in self.refs if r.form in forms][:limit]
        return ProviderResult(data=matched, provider=self.name)

    async def fetch_document(self, filing: FilingRef) -> ProviderResult[FilingDocument]:
        html = self.html_by_accession.get(filing.accession_number, _SAMPLE_10K_HTML)
        return ProviderResult(data=FilingDocument(ref=filing, html=html), provider=self.name)


def _default_filing_refs() -> list[FilingRef]:
    return [
        FilingRef(
            cik="0000789019",
            ticker="MSFT",
            form="10-K",
            accession_number="0000950170-24-087843",
            filing_date=date(2024, 7, 30),
            primary_document="msft-20240630.htm",
            url="https://sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm",
        ),
        FilingRef(
            cik="0000789019",
            ticker="MSFT",
            form="10-Q",
            accession_number="0000950170-24-050000",
            filing_date=date(2024, 4, 25),
            primary_document="msft-20240331.htm",
            url="https://sec.gov/Archives/edgar/data/789019/000095017024050000/msft-20240331.htm",
        ),
        FilingRef(
            cik="0000789019",
            ticker="MSFT",
            form="8-K",
            accession_number="0000950170-24-100000",
            filing_date=date(2024, 7, 30),
            primary_document="msft-8k.htm",
            items=["2.02", "9.01"],
            description="Results of Operations and Financial Condition",
            url="https://sec.gov/Archives/edgar/data/789019/000095017024100000/msft-8k.htm",
        ),
    ]


_SAMPLE_10K_HTML = """
<html><body>
<h1>MICROSOFT CORP FORM 10-K</h1>
<p>Item 1. Business</p>
<p>Microsoft develops, licenses and supports software, services, devices and solutions worldwide.
We generate revenue by licensing cloud services, software and devices to businesses and consumers.
Our products include cloud computing platforms, operating systems and productivity applications.</p>
<p>Item 1A. Risk Factors</p>
<p>Our business is subject to intense competition in cloud computing, and our results of operations
could be adversely affected by currency fluctuations, cybersecurity incidents and changes in demand
for our cloud and software offerings.</p>
<p>Item 7. Management's Discussion and Analysis</p>
<p>Revenue increased due to growth in our cloud services segment, driven by commercial bookings and
strong demand for our Azure platform, offset partly by a decline in devices revenue.</p>
</body></html>
"""


class FakeMarket:
    name = "fake_market"

    def __init__(self, fails: bool = False) -> None:
        self.fails = fails

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        if self.fails:
            raise ProviderUnavailableError(self.name, "no quote available")
        quote, evidence, source = msft_quote()
        quote = quote.model_copy(update={"ticker": ticker.upper()})
        return ProviderResult(data=quote, provider=self.name, sources=[source], evidence=evidence)


class FakeNews:
    name = "fake_news"

    async def search_news(self, company: CompanyIdentity, days: int = 90, limit: int = 25):
        articles, sources, evidence = [], [], []
        for i, (publisher, tier) in enumerate([("reuters.com", "tier1"), ("techcrunch.com", "tier2")][:limit]):
            title = f"{company.name} announces update #{i}"
            url = f"https://{publisher}/story-{i}"
            article = NewsArticle(
                title=title, url=url, published_at=date(2024, 9, 1), publisher=publisher, reliability=tier
            )
            source = Source.make(
                kind=SourceKind.NEWS,
                title=title,
                provider=self.name,
                publisher=publisher,
                url=url,
                published_at=date(2024, 9, 1),
            )
            ev = Evidence.make(source_id=source.id, text=f"{publisher} (2024-09-01): {title}")
            articles.append(article)
            sources.append(source)
            evidence.append(ev)
        return ProviderResult(data=articles, provider=self.name, sources=sources, evidence=evidence)


class FakeMacro:
    name = "fake_macro"

    async def get_indicators(self):
        source = Source.make(
            kind=SourceKind.MACRO,
            title="US Treasury Par Yield Curve",
            provider=self.name,
            publisher="U.S. Department of the Treasury",
            url="https://home.treasury.gov",
        )
        indicators, evidence = [], []
        for key, value in (("ust_3m", 5.0), ("ust_2y", 4.0), ("ust_10y", 4.2)):
            history = [MacroPoint(day=date(2024, 9, 20), value=value)]
            indicators.append(
                MacroIndicator(
                    key=key, label=key, unit="percent", latest=value, as_of=date(2024, 9, 20), history=history
                )
            )
            evidence.append(Evidence.make(source_id=source.id, text=f"Treasury: {key} = {value}%"))
        return ProviderResult(data=indicators, provider=self.name, sources=[source], evidence=evidence)


class FakePeers:
    name = "fake_peers"

    async def candidate_peers(self, company: CompanyIdentity, limit: int = 12):
        candidates = [
            PeerCandidate(
                company=CompanyIdentity(name="ORACLE CORP", ticker="ORCL", cik="0001341439"),
                revenue=50_000_000_000.0,
                fiscal_period="CY2023",
                reason="same SIC 7372, ranked by FY revenue",
            ),
        ][:limit]
        return ProviderResult(data=candidates, provider=self.name)


class FakeRetriever:
    """Programmable stand-in for the real `HybridRetriever` (used where indexing isn't under test)."""

    def __init__(self, search_results=None) -> None:
        self._search_results = search_results if search_results is not None else []
        self.ensure_indexed_calls: list[Any] = []

    async def ensure_indexed(self, company, filings):
        self.ensure_indexed_calls.append((company, filings))
        from meridian.rag.types import IndexReport

        return IndexReport(documents_indexed=len(filings))

    async def search(self, query, *, ticker, forms=None, section_keys=None, k=8):
        return self._search_results


def make_registry(**overrides: Any) -> ProviderRegistry:
    defaults = dict(
        directory=FakeDirectory(),
        fundamentals=FakeFundamentals(),
        filings=FakeFilings(),
        market=FakeMarket(),
        news=FakeNews(),
        macro=FakeMacro(),
        peers=FakePeers(),
        llm=OfflineLLMProvider(),
        embeddings=HashingEmbedder(dim=32),
    )
    defaults.update(overrides)
    return ProviderRegistry(**defaults)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        env="test",
        redis_url=None,
        llm_provider="offline",
        data_mode="live",
        snapshot_dir=tmp_path / "snapshots",
        model_cache_dir=tmp_path / "models",
        embedding_provider="hashing",
    )


@pytest.fixture
def make_ctx(settings):
    def _make(
        *,
        providers: ProviderRegistry | None = None,
        retriever=None,
        memory=None,
        agent: AgentName = AgentName.FINANCIALS,
    ) -> ToolContext:
        return ToolContext(
            session_id="sess_1",
            agent=agent,
            settings=settings,
            providers=providers or make_registry(),
            retriever=retriever,
            events=ListEventSink(),
            memory=memory,
        )

    return _make
