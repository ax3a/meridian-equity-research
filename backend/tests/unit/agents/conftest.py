"""Fixtures for specialist-agent tests.

The real 19 tools (Task 8) are being implemented in parallel, to the names and input/output shapes
documented in the plan's Task 8 tool table. These fakes provide matching tool names and output shapes
(one dataclass per documented output) so the agents in `meridian.agents.*` can be exercised in isolation,
without depending on the real tool implementations or any network/provider access.

Each fake tool absorbs realistic Source/Evidence pairs into `ctx.ledger`, exactly like a real tool must, so
that findings citing the evidence ids these tools return pass the platform's citation validation. Tests can
override `FakeData.search_filings_fn` to control exactly what `search_filings`/`get_filing_section` return
for a given query, and can add extra peer snapshots via `add_peer_snapshot`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest
from pydantic import BaseModel

from meridian.agents.base import AgentDeps
from meridian.core.config import Settings
from meridian.financial_engine.dcf import run_dcf as engine_run_dcf
from meridian.financial_engine.metrics import calculate as engine_calculate
from meridian.financial_engine.metrics import compute_metrics
from meridian.observability.events import ListEventSink
from meridian.providers.base import CompanyProfile, FilingRef, MacroIndicator, NewsArticle, PeerCandidate
from meridian.providers.llm.offline import OfflineLLMProvider
from meridian.providers.llm.scripted import ScriptedLLMProvider
from meridian.providers.registry import ProviderRegistry
from meridian.rag.types import IndexReport
from meridian.schemas.analysis import DCFResult, PeerSnapshot
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import (
    FinancialMetrics,
    FinancialPeriod,
    FinancialStatements,
    MetricValue,
    PeriodFinancials,
    Quote,
)
from meridian.schemas.research import CompanyIdentity, ResearchRequest, ResearchTask
from meridian.schemas.state import ResearchState
from meridian.tools.base import Tool, ToolContext, ToolRegistry

# ---------------------------------------------------------------------------
# Dummy providers -- fake tools never touch `ctx.providers`, so these just need
# to satisfy `ProviderRegistry`'s field types structurally (no runtime checks).
# ---------------------------------------------------------------------------


class _DummyProvider:
    name = "dummy"
    dim = 8


def make_provider_registry(llm: Any) -> ProviderRegistry:
    dummy = _DummyProvider()
    return ProviderRegistry(
        directory=dummy,
        fundamentals=dummy,
        filings=dummy,
        market=dummy,
        news=dummy,
        macro=dummy,
        peers=dummy,
        llm=llm,
        embeddings=dummy,
    )


# ---------------------------------------------------------------------------
# Fake tool plumbing
# ---------------------------------------------------------------------------


class _AnyArgs(BaseModel):
    model_config = {"extra": "allow"}


class FakeTool(Tool[_AnyArgs, Any]):
    input_model = _AnyArgs

    def __init__(self, name: str, description: str, handler: Callable[[Any, ToolContext], Any]) -> None:
        self.name = name
        self.description = description
        self._handler = handler

    async def run(self, args: _AnyArgs, ctx: ToolContext) -> Any:
        return await self._handler(args, ctx)


def _cite(ctx: ToolContext, source: Source, evidence: Evidence) -> str:
    ctx.ledger.add_source(source)
    ctx.ledger.add_evidence(evidence)
    return evidence.id


def make_evidence_pair(
    text: str, *, kind: SourceKind = SourceKind.SEC_FILING, title: str = "Test Source", **locator_kw: Any
) -> tuple[Source, Evidence]:
    source = Source.make(
        kind=kind,
        title=title,
        provider="test",
        publisher="Test Publisher",
        url=f"https://example.com/{title.replace(' ', '-')}",
    )
    evidence = Evidence.make(source_id=source.id, text=text, locator=EvidenceLocator(**locator_kw))
    return source, evidence


# ---------------------------------------------------------------------------
# Output shapes matching the Task 8 tool table (dataclasses: no validation needed for fixtures)
# ---------------------------------------------------------------------------


@dataclass
class ResolveCompanyOut:
    company: CompanyIdentity
    evidence_ids: list[str]


@dataclass
class ProfileOut:
    profile: CompanyProfile
    evidence_ids: list[str]


@dataclass
class PassageHit:
    evidence_id: str
    source_id: str
    section: str
    form: str
    filing_date: date
    page: int | None
    text: str
    score: float
    injection_flags: list[str] = field(default_factory=list)


@dataclass
class SearchFilingsOut:
    passages: list[PassageHit]


@dataclass
class EightKEvent:
    ticker: str
    form: str
    filed: date
    items: list[str]
    description: str
    evidence_id: str
    source_id: str


@dataclass
class EightKEventsOut:
    events: list[EightKEvent]


@dataclass
class FinancialStatementsOut:
    statements: FinancialStatements
    evidence_ids: list[str]
    is_snapshot: bool = False


@dataclass
class ComputeMetricsOut:
    metrics: FinancialMetrics
    statements: FinancialStatements
    quote: Quote | None
    evidence_ids: list[str]


@dataclass
class ListFilingsOut:
    filings: list[FilingRef]


@dataclass
class NewsOut:
    articles: list[NewsArticle]
    evidence_ids: list[str]


@dataclass
class MacroOut:
    indicators: list[MacroIndicator]
    evidence_ids: list[str]


@dataclass
class PeerCandidatesOut:
    candidates: list[PeerCandidate]


@dataclass
class QuoteOut:
    quote: Quote
    evidence_ids: list[str]


@dataclass
class RecallMemoryOut:
    found: bool
    item: Any = None


# ---------------------------------------------------------------------------
# Realistic synthetic financial data (built with the real, frozen financial_engine so that
# derived metrics -- CAGR, FCF margin, multiples -- are internally consistent).
# ---------------------------------------------------------------------------

_YEARS = (2021, 2022, 2023, 2024, 2025)
_REVENUES = (40e9, 55e9, 72e9, 95e9, 120e9)


def build_statements(ticker: str) -> FinancialStatements:
    annual = []
    for year, revenue in zip(_YEARS, _REVENUES):
        gross_profit = revenue * 0.65
        operating_income = revenue * 0.30
        net_income = revenue * 0.25
        shares = 2.5e9
        period = FinancialPeriod(
            label=f"FY{year}", fiscal_year=year, fiscal_period="FY", period_end=date(year, 1, 28), form="10-K"
        )
        annual.append(
            PeriodFinancials(
                period=period,
                revenue=revenue,
                cost_of_revenue=revenue - gross_profit,
                gross_profit=gross_profit,
                research_and_development=revenue * 0.1,
                operating_income=operating_income,
                interest_expense=revenue * 0.005,
                income_tax_expense=revenue * 0.03,
                net_income=net_income,
                eps_basic=net_income / shares,
                eps_diluted=net_income / shares,
                shares_diluted=shares,
                depreciation_amortization=revenue * 0.02,
                operating_cash_flow=net_income * 1.15,
                capex=revenue * 0.04,
                cash_and_equivalents=15e9,
                short_term_investments=8e9,
                current_assets=35e9,
                total_assets=80e9,
                current_liabilities=12e9,
                total_liabilities=25e9,
                long_term_debt=6e9,
                current_debt=1e9,
                shareholders_equity=55e9,
                shares_outstanding=shares,
            )
        )
    return FinancialStatements(ticker=ticker, annual=annual, quarterly=[])


_SECTION_KEY_RE = re.compile(r"^\s*(?:part\s+[iv]+[.,]?\s+)?item\s+(\d+[A-C]?)", re.IGNORECASE)


def _section_key_of(section_title: str) -> str:
    """Recover the section key ("1A") from a heading ("Item 1A. Risk Factors"), as the store holds both."""
    match = _SECTION_KEY_RE.match(section_title or "")
    return match.group(1).upper() if match else ""


def build_passage(text: str, section: str, *, title: str = "10-K excerpt") -> tuple[PassageHit, Source, Evidence]:
    source, evidence = make_evidence_pair(text, title=title)
    hit = PassageHit(
        evidence_id=evidence.id,
        source_id=source.id,
        section=section,
        form="10-K",
        filing_date=date(2025, 2, 20),
        page=12,
        text=text,
        score=0.82,
        injection_flags=[],
    )
    return hit, source, evidence


def build_peer_snapshot(
    ticker: str,
    name: str,
    is_target: bool,
    revenue: float,
    growth: float,
    gm: float,
    om: float,
    nm: float,
    pe: float | None,
    ev_sales: float | None,
) -> tuple[PeerSnapshot, Source, Evidence]:
    source, evidence = make_evidence_pair(
        f"{name} FY2025 reported financials.", kind=SourceKind.PEER_DATA, title=f"{ticker} peer snapshot"
    )
    snapshot = PeerSnapshot(
        company=CompanyIdentity(name=name, ticker=ticker, cik="0000000000", sic="3674"),
        is_target=is_target,
        selection_reason="" if is_target else "SIC peer",
        fiscal_period="FY2025",
        revenue=revenue,
        revenue_growth=growth,
        gross_margin=gm,
        operating_margin=om,
        net_margin=nm,
        market_cap=revenue * 10,
        pe=pe,
        ev_sales=ev_sales,
        evidence_ids=[evidence.id],
    )
    return snapshot, source, evidence


@dataclass
class FakeData:
    ticker: str
    company: CompanyIdentity
    profile: CompanyProfile
    statements: FinancialStatements
    metrics: FinancialMetrics
    quote: Quote
    filings: list[FilingRef]
    events: list[EightKEvent]
    articles: list[NewsArticle]
    indicators: list[MacroIndicator]
    candidates: list[PeerCandidate]
    snapshots: dict[str, PeerSnapshot] = field(default_factory=dict)
    filing_passages: list[PassageHit] = field(default_factory=list)
    section_passages: list[PassageHit] = field(default_factory=list)
    search_filings_fn: Callable[[str], list[PassageHit]] | None = None
    resolve_evidence: tuple[Source, Evidence] | None = None
    profile_evidence: tuple[Source, Evidence] | None = None
    quote_evidence: tuple[Source, Evidence] | None = None
    macro_evidence: tuple[Source, Evidence] | None = None
    event_evidence: dict[str, tuple[Source, Evidence]] = field(default_factory=dict)  # keyed by evidence id
    passage_evidence: dict[str, tuple[Source, Evidence]] = field(default_factory=dict)  # keyed by evidence id
    snapshot_evidence: dict[str, tuple[Source, Evidence]] = field(default_factory=dict)  # keyed by ticker

    def add_peer_snapshot(
        self,
        ticker: str,
        name: str,
        *,
        is_target: bool = False,
        revenue: float = 10e9,
        growth: float = 0.1,
        gm: float = 0.5,
        om: float = 0.2,
        nm: float = 0.15,
        pe: float | None = 20.0,
        ev_sales: float | None = 5.0,
    ) -> PeerSnapshot:
        snapshot, source, evidence = build_peer_snapshot(
            ticker, name, is_target, revenue, growth, gm, om, nm, pe, ev_sales
        )
        self.snapshots[ticker] = snapshot
        self.snapshot_evidence[ticker] = (source, evidence)
        return snapshot

    def add_passage(self, text: str, section: str = "Item 1A. Risk Factors") -> PassageHit:
        hit, source, evidence = build_passage(text, section)
        self.passage_evidence[hit.evidence_id] = (source, evidence)
        return hit


def build_fake_data(ticker: str = "NVDA") -> FakeData:
    company = CompanyIdentity(
        name="Nvidia Corp",
        ticker=ticker,
        cik="0001045810",
        exchange="NASDAQ",
        sic="3674",
        sic_description="Semiconductors",
        fiscal_year_end="0128",
    )
    profile = CompanyProfile(
        identity=company,
        description="NVIDIA designs and sells graphics processing "
        "units and AI computing platforms to data center, gaming and automotive customers "
        "worldwide.",
        category="Large accelerated filer",
    )
    statements = build_statements(ticker)
    quote = Quote(
        ticker=ticker, price=140.0, as_of=date(2025, 9, 20), currency="USD", source_id="src_quote_seed", history=[]
    )
    metrics = compute_metrics(statements, quote=quote, is_financial_institution=False)

    filings = [
        FilingRef(
            cik=company.cik,
            ticker=ticker,
            form="10-K",
            accession_number="0001-25-000001",
            filing_date=date(2025, 2, 20),
            report_date=date(2025, 1, 28),
            primary_document="nvda-10k.htm",
            url="https://sec.gov/nvda-10k",
        )
    ]

    data = FakeData(
        ticker=ticker,
        company=company,
        profile=profile,
        statements=statements,
        metrics=metrics,
        quote=quote,
        filings=filings,
        events=[],
        articles=[],
        indicators=[],
        candidates=[],
    )

    hit1 = data.add_passage(
        f"{company.name} designs GPUs and AI computing platforms sold to data center, gaming, professional "
        "visualization and automotive customers across the Americas, Asia and Europe.",
        "Item 1. Business",
    )
    hit2 = data.add_passage(
        "Revenue is generated primarily from the sale of data center and gaming GPU products through OEM and "
        "distribution partners, with concentration among a small number of large customers.",
        "Item 1. Business",
    )
    # Agents scope their searches by section, so the default corpus has to span the sections they ask
    # for. With only Item 1 here every scoped search would miss and quietly fall back to an unscoped
    # one, testing the degraded path instead of the real one.
    hit3 = data.add_passage(
        "Results of operations: revenue grew on data center demand, while gross margin expanded on a "
        "favourable product mix and improved supply terms.",
        "Item 7. Management's Discussion and Analysis",
    )
    hit4 = data.add_passage(
        "We depend on a limited number of suppliers and any disruption in supply could materially harm our "
        "ability to meet customer demand.",
        "Item 1A. Risk Factors",
    )
    data.filing_passages = [hit1, hit2, hit3, hit4]
    data.section_passages = [hit1, hit2, hit3, hit4]

    def make_event(items: list[str], description: str, filed: date) -> EightKEvent:
        source, evidence = make_evidence_pair(description, title=f"{ticker} 8-K {filed.isoformat()}")
        data.event_evidence[evidence.id] = (source, evidence)
        return EightKEvent(
            ticker=ticker,
            form="8-K",
            filed=filed,
            items=items,
            description=description,
            evidence_id=evidence.id,
            source_id=source.id,
        )

    data.events = [
        make_event(["2.02", "9.01"], "Reported quarterly results ahead of consensus estimates.", date(2025, 8, 27)),
        make_event(["5.02"], "Announced departure of the chief financial officer.", date(2025, 6, 1)),
    ]

    data.articles = [
        NewsArticle(
            title=f"{ticker} unveils next-generation AI chip",
            url="https://news.example.com/1",
            published_at=date(2025, 9, 10),
            publisher="Example Wire",
            snippet="Coverage.",
            reliability="tier1",
        ),
        NewsArticle(
            title=f"{ticker} shares rise on datacenter demand",
            url="https://news.example.com/2",
            published_at=date(2025, 9, 5),
            publisher="Example Wire",
            snippet="Coverage.",
            reliability="tier1",
        ),
    ]

    data.macro_evidence = make_evidence_pair(
        "US Treasury daily par yield curve rates.", kind=SourceKind.MACRO, title="Treasury Fiscal Data"
    )
    data.indicators = [
        MacroIndicator(
            key="ust_10y", label="10-Year Treasury Yield", unit="%", latest=4.2, as_of=date(2025, 9, 20), history=[]
        )
    ]

    data.candidates = [
        PeerCandidate(
            company=CompanyIdentity(name="Advanced Micro Devices", ticker="AMD", cik="0000002488", sic="3674"),
            revenue=25e9,
            fiscal_period="FY2025",
            reason="Direct GPU/CPU competitor in the same SIC code.",
        ),
        PeerCandidate(
            company=CompanyIdentity(name="Intel Corp", ticker="INTC", cik="0000050863", sic="3674"),
            revenue=54e9,
            fiscal_period="FY2025",
            reason="Semiconductor competitor, overlapping data center market.",
        ),
    ]

    data.add_peer_snapshot(
        ticker,
        company.name,
        is_target=True,
        revenue=120e9,
        growth=0.263,
        gm=0.65,
        om=0.30,
        nm=0.25,
        pe=45.0,
        ev_sales=15.0,
    )
    data.add_peer_snapshot(
        "AMD", "Advanced Micro Devices", revenue=25e9, growth=0.20, gm=0.50, om=0.20, nm=0.15, pe=30.0, ev_sales=8.0
    )
    data.add_peer_snapshot(
        "INTC", "Intel Corp", revenue=54e9, growth=0.05, gm=0.40, om=0.10, nm=0.05, pe=20.0, ev_sales=3.0
    )

    data.resolve_evidence = make_evidence_pair(
        f"Resolved {ticker} to CIK {company.cik}.", kind=SourceKind.COMPANY_PROFILE, title=f"{ticker} resolution"
    )
    data.profile_evidence = make_evidence_pair(
        profile.description or "", kind=SourceKind.COMPANY_PROFILE, title=f"{ticker} profile"
    )
    data.quote_evidence = make_evidence_pair(
        f"{ticker} closing price {quote.price}.", kind=SourceKind.MARKET_DATA, title=f"{ticker} quote"
    )
    return data


# ---------------------------------------------------------------------------
# Fake tool registry
# ---------------------------------------------------------------------------


def build_tool_registry(data: FakeData, *, fail: frozenset[str] = frozenset()) -> ToolRegistry:
    reg = ToolRegistry()

    async def resolve_company(args: Any, ctx: ToolContext) -> ResolveCompanyOut:
        source, evidence = data.resolve_evidence
        return ResolveCompanyOut(company=data.company, evidence_ids=[_cite(ctx, source, evidence)])

    async def get_company_profile(args: Any, ctx: ToolContext) -> ProfileOut:
        source, evidence = data.profile_evidence
        return ProfileOut(profile=data.profile, evidence_ids=[_cite(ctx, source, evidence)])

    def _search(args: Any, ctx: ToolContext, hits_default: list[PassageHit]) -> SearchFilingsOut:
        query = getattr(args, "query", "")
        k = getattr(args, "k", 6)
        hits = data.search_filings_fn(query) if data.search_filings_fn is not None else hits_default
        # The real tool filters on the chunk's section key, and agents rely on that filter to keep a
        # topical label honest. A fake that ignored it would let every scoped search "succeed", which is
        # precisely the case the agents need covered.
        section_keys = getattr(args, "section_keys", None)
        if section_keys:
            wanted = {str(key).upper() for key in section_keys}
            hits = [hit for hit in hits if _section_key_of(hit.section) in wanted]
        out = []
        for hit in hits[:k]:
            pair = data.passage_evidence.get(hit.evidence_id)
            if pair is not None:
                _cite(ctx, *pair)
            out.append(hit)
        return SearchFilingsOut(passages=out)

    async def search_filings(args: Any, ctx: ToolContext) -> SearchFilingsOut:
        return _search(args, ctx, data.filing_passages)

    async def get_filing_section(args: Any, ctx: ToolContext) -> SearchFilingsOut:
        return _search(args, ctx, data.section_passages)

    async def recall_research_memory(args: Any, ctx: ToolContext) -> RecallMemoryOut:
        return RecallMemoryOut(found=False, item=None)

    async def get_financial_statements(args: Any, ctx: ToolContext) -> FinancialStatementsOut:
        return FinancialStatementsOut(statements=data.statements, evidence_ids=[], is_snapshot=False)

    async def compute_financial_metrics(args: Any, ctx: ToolContext) -> ComputeMetricsOut:
        include_market = getattr(args, "include_market", True)
        return ComputeMetricsOut(
            metrics=data.metrics,
            statements=data.statements,
            quote=data.quote if include_market else None,
            evidence_ids=[],
        )

    async def calculate_metric(args: Any, ctx: ToolContext) -> MetricValue:
        metric = getattr(args, "metric")
        inputs = getattr(args, "inputs")
        period = getattr(args, "period", "custom")
        return engine_calculate(metric, inputs, period=period)

    async def list_filings(args: Any, ctx: ToolContext) -> ListFilingsOut:
        return ListFilingsOut(filings=data.filings)

    async def index_filings(args: Any, ctx: ToolContext) -> IndexReport:
        return IndexReport(documents_indexed=len(data.filings), chunks_created=10)

    async def get_recent_8k_events(args: Any, ctx: ToolContext) -> EightKEventsOut:
        limit = getattr(args, "limit", 10)
        out = []
        for event in data.events[:limit]:
            pair = data.event_evidence.get(event.evidence_id)
            if pair is not None:
                _cite(ctx, *pair)
            out.append(event)
        return EightKEventsOut(events=out)

    async def search_news(args: Any, ctx: ToolContext) -> NewsOut:
        evidence_ids = []
        for article in data.articles:
            src, ev = make_evidence_pair(article.snippet or article.title, kind=SourceKind.NEWS, title=article.title)
            evidence_ids.append(_cite(ctx, src, ev))
        return NewsOut(articles=list(data.articles), evidence_ids=evidence_ids)

    async def get_macro_indicators(args: Any, ctx: ToolContext) -> MacroOut:
        src, ev = data.macro_evidence
        return MacroOut(indicators=list(data.indicators), evidence_ids=[_cite(ctx, src, ev)])

    async def find_peer_candidates(args: Any, ctx: ToolContext) -> PeerCandidatesOut:
        return PeerCandidatesOut(candidates=list(data.candidates))

    async def get_peer_snapshot(args: Any, ctx: ToolContext) -> PeerSnapshot:
        ticker = getattr(args, "ticker", "").strip().upper()
        if ticker not in data.snapshots:
            raise ValueError(f"unknown ticker: {ticker}")
        src, ev = data.snapshot_evidence[ticker]
        _cite(ctx, src, ev)
        return data.snapshots[ticker]

    async def get_market_quote(args: Any, ctx: ToolContext) -> QuoteOut:
        src, ev = data.quote_evidence
        return QuoteOut(quote=data.quote, evidence_ids=[_cite(ctx, src, ev)])

    async def run_dcf(args: Any, ctx: ToolContext) -> DCFResult:
        assumptions = getattr(args, "assumptions")
        current_price = getattr(args, "current_price", None)
        return engine_run_dcf(assumptions, current_price)

    handlers: dict[str, Callable[[Any, ToolContext], Any]] = {
        "resolve_company": resolve_company,
        "get_company_profile": get_company_profile,
        "search_filings": search_filings,
        "get_filing_section": get_filing_section,
        "recall_research_memory": recall_research_memory,
        "get_financial_statements": get_financial_statements,
        "compute_financial_metrics": compute_financial_metrics,
        "calculate_metric": calculate_metric,
        "list_filings": list_filings,
        "index_filings": index_filings,
        "get_recent_8k_events": get_recent_8k_events,
        "search_news": search_news,
        "get_macro_indicators": get_macro_indicators,
        "find_peer_candidates": find_peer_candidates,
        "get_peer_snapshot": get_peer_snapshot,
        "get_market_quote": get_market_quote,
        "run_dcf": run_dcf,
    }
    for name, handler in handlers.items():
        if name in fail:

            async def failing(args: Any, ctx: ToolContext, _name: str = name) -> Any:
                raise RuntimeError(f"simulated failure for {_name}")

            reg.register(FakeTool(name, f"fake {name}", failing))
        else:
            reg.register(FakeTool(name, f"fake {name}", handler))
    return reg


# ---------------------------------------------------------------------------
# pytest fixtures + small builders
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_data() -> FakeData:
    return build_fake_data("NVDA")


@pytest.fixture
def events() -> ListEventSink:
    return ListEventSink()


@pytest.fixture
def offline_llm() -> OfflineLLMProvider:
    return OfflineLLMProvider()


@pytest.fixture
def scripted_llm() -> ScriptedLLMProvider:
    return ScriptedLLMProvider()


def make_state(
    ticker: str = "NVDA",
    *,
    company: CompanyIdentity | None = None,
    metrics: FinancialMetrics | None = None,
    peers: Any = None,
    evidence: dict[str, Evidence] | None = None,
) -> ResearchState:
    request = ResearchRequest(query=f"Analyze {ticker}", ticker=ticker)
    return ResearchState(
        session_id="sess_test", request=request, company=company, metrics=metrics, peers=peers, evidence=evidence or {}
    )


def make_deps(settings: Settings, tools: ToolRegistry, llm: Any, events: ListEventSink) -> AgentDeps:
    return AgentDeps(
        settings=settings,
        providers=make_provider_registry(llm),
        tools=tools,
        retriever=None,
        events=events,
        memory=None,
    )


def make_task(agent_name: Any, objective: str = "Research the company", wave: int = 1) -> ResearchTask:
    return ResearchTask.make(agent_name, objective, wave)
