"""Provider interfaces. Every data source implements one of these so providers can be swapped or chained."""

from __future__ import annotations

from datetime import date
from typing import Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

from meridian.schemas.citations import Evidence, Source
from meridian.schemas.financials import FinancialStatements, Quote
from meridian.schemas.research import CompanyIdentity

T = TypeVar("T")


class ProviderResult(BaseModel, Generic[T]):
    """Data plus the provenance needed to cite it."""

    data: T
    provider: str
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    is_snapshot: bool = False
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    identity: CompanyIdentity
    description: str | None = None
    former_names: list[str] = Field(default_factory=list)
    business_address: str | None = None
    category: str | None = None  # e.g. "Large accelerated filer"


class FilingRef(BaseModel):
    cik: str
    ticker: str
    form: str  # "10-K", "10-Q", "8-K"
    accession_number: str
    filing_date: date
    report_date: date | None = None
    primary_document: str
    url: str
    description: str | None = None
    items: list[str] = Field(default_factory=list)  # 8-K item codes, e.g. ["2.02", "9.01"]


class FilingDocument(BaseModel):
    ref: FilingRef
    html: str


class NewsArticle(BaseModel):
    title: str
    url: str
    published_at: date | None
    publisher: str  # domain or outlet name
    snippet: str | None = None
    language: str | None = None
    reliability: str = "unrated"  # "primary" | "tier1" | "tier2" | "unrated"


class MacroPoint(BaseModel):
    day: date
    value: float


class MacroIndicator(BaseModel):
    key: str  # "ust_10y", "ust_3m", "cpi_yoy", ...
    label: str
    unit: str
    latest: float | None
    as_of: date | None
    history: list[MacroPoint] = Field(default_factory=list)


class PeerCandidate(BaseModel):
    company: CompanyIdentity
    revenue: float | None = None
    fiscal_period: str | None = None
    reason: str


@runtime_checkable
class CompanyDirectory(Protocol):
    name: str

    async def search(self, query: str, limit: int = 10) -> list[CompanyIdentity]: ...

    async def resolve(self, query: str) -> CompanyIdentity:
        """Resolve a ticker or company name. Raises CompanyNotFoundError."""
        ...

    async def profile(self, company: CompanyIdentity) -> ProviderResult[CompanyProfile]: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    name: str

    async def get_statements(self, company: CompanyIdentity, years: int = 5) -> ProviderResult[FinancialStatements]: ...


@runtime_checkable
class FilingsProvider(Protocol):
    name: str

    async def list_filings(
        self, company: CompanyIdentity, forms: tuple[str, ...] = ("10-K", "10-Q", "8-K"), limit: int = 20
    ) -> ProviderResult[list[FilingRef]]: ...

    async def fetch_document(self, filing: FilingRef) -> ProviderResult[FilingDocument]: ...


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]: ...


@runtime_checkable
class NewsProvider(Protocol):
    name: str

    async def search_news(
        self, company: CompanyIdentity, days: int = 90, limit: int = 25
    ) -> ProviderResult[list[NewsArticle]]: ...


@runtime_checkable
class MacroProvider(Protocol):
    name: str

    async def get_indicators(self) -> ProviderResult[list[MacroIndicator]]: ...


@runtime_checkable
class PeerUniverseProvider(Protocol):
    name: str

    async def candidate_peers(
        self, company: CompanyIdentity, limit: int = 12
    ) -> ProviderResult[list[PeerCandidate]]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
