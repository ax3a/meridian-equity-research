"""Wires the Batch-1 providers into the fallback chains + registry the tools call.

Preference order per protocol is free/keyless first, then optional (keyed) adapters -- and only when
their key is actually configured, so a chain never carries a provider that will just raise
`ProviderUnavailableError` on every call. With no optional keys configured at all, every chain reduces to
its single keyless provider (SEC EDGAR for fundamentals/filings/peers, Yahoo Finance for market data,
GDELT for news, US Treasury for macro indicators) -- the platform works end to end without any API keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from meridian.cache.base import Cache, build_cache
from meridian.core.config import Settings
from meridian.core.http import HttpClient
from meridian.providers.base import (
    CompanyDirectory,
    FilingsProvider,
    FundamentalsProvider,
    MacroProvider,
    MarketDataProvider,
    NewsProvider,
    PeerUniverseProvider,
)
from meridian.providers.chain import FundamentalsChain, MacroChain, MarketChain, NewsChain, PeerChain
from meridian.providers.llm.anthropic_provider import AnthropicLLMProvider
from meridian.providers.llm.base import LLMProvider
from meridian.providers.llm.offline import OfflineLLMProvider
from meridian.providers.macro.treasury import TreasuryMacroProvider
from meridian.providers.market.stooq import StooqMarketProvider
from meridian.providers.market.yahoo import YahooMarketProvider
from meridian.providers.news.gdelt import GdeltNewsProvider
from meridian.providers.optional.alpha_vantage import AlphaVantageProvider
from meridian.providers.optional.finnhub import FinnhubProvider
from meridian.providers.optional.fmp import FmpProvider
from meridian.providers.optional.fred import FredMacroProvider
from meridian.providers.optional.polygon import PolygonProvider
from meridian.providers.registry import ProviderRegistry
from meridian.providers.sec.directory import SecCompanyDirectory
from meridian.providers.sec.facts import SecFundamentalsProvider
from meridian.providers.sec.filings import SecFilingsProvider
from meridian.providers.sec.peers import SecPeerUniverseProvider
from meridian.providers.snapshots import SnapshotStore
from meridian.rag.embeddings import build_embedder
from meridian.rag.pipeline import build_retriever as _build_retriever

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from meridian.rag.types import Retriever

__all__ = ["build_llm", "build_providers", "build_retriever"]


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def build_llm(settings: Settings) -> LLMProvider:
    """Anthropic when `settings.llm_mode == "anthropic"` (a key is configured), else the offline mode."""
    if settings.llm_mode == "anthropic":
        return AnthropicLLMProvider(settings)
    return OfflineLLMProvider()


def build_providers(
    settings: Settings, *, http: HttpClient | None = None, cache: Cache | None = None
) -> ProviderRegistry:
    """Assemble the concrete `ProviderRegistry` (fallback chains + LLM + embeddings) for one process."""
    cache = cache if cache is not None else build_cache(settings.redis_url)
    http = http if http is not None else HttpClient(settings, cache, SnapshotStore(settings.snapshot_dir))

    fmp_key = _secret(settings.fmp_api_key)
    alpha_vantage_key = _secret(settings.alpha_vantage_api_key)
    finnhub_key = _secret(settings.finnhub_api_key)
    polygon_key = _secret(settings.polygon_api_key)
    fred_key = _secret(settings.fred_api_key)

    fmp = FmpProvider(http, fmp_key) if fmp_key else None
    finnhub = FinnhubProvider(http, finnhub_key) if finnhub_key else None

    directory: CompanyDirectory = SecCompanyDirectory(http)
    filings: FilingsProvider = SecFilingsProvider(http)

    fundamentals_chain: list[FundamentalsProvider] = [SecFundamentalsProvider(http)]
    if fmp is not None:
        fundamentals_chain.append(fmp)
    fundamentals = FundamentalsChain(fundamentals_chain)

    # Stooq is the documented keyless source but is currently blocked by an anti-bot challenge (see
    # providers.market.stooq) -- Yahoo's unofficial chart endpoint goes first because it actually works
    # today, with Stooq kept as a second keyless attempt in case that changes.
    market_chain: list[MarketDataProvider] = [YahooMarketProvider(http), StooqMarketProvider(http)]
    if fmp is not None:
        market_chain.append(fmp)
    if alpha_vantage_key:
        market_chain.append(AlphaVantageProvider(http, alpha_vantage_key))
    if finnhub is not None:
        market_chain.append(finnhub)
    if polygon_key:
        market_chain.append(PolygonProvider(http, polygon_key))
    market = MarketChain(market_chain)

    news_chain: list[NewsProvider] = [GdeltNewsProvider(http)]
    if finnhub is not None:
        news_chain.append(finnhub)
    news = NewsChain(news_chain)

    macro_chain: list[MacroProvider] = [TreasuryMacroProvider(http)]
    if fred_key:
        macro_chain.append(FredMacroProvider(http, fred_key))
    macro = MacroChain(macro_chain)

    peers_chain: list[PeerUniverseProvider] = [SecPeerUniverseProvider(http)]
    if fmp is not None:
        peers_chain.append(fmp)
    if finnhub is not None:
        peers_chain.append(finnhub)
    peers = PeerChain(peers_chain)

    return ProviderRegistry(
        directory=directory,
        fundamentals=fundamentals,
        filings=filings,
        market=market,
        news=news,
        macro=macro,
        peers=peers,
        llm=build_llm(settings),
        embeddings=build_embedder(settings),
    )


def build_retriever(settings: Settings, providers: ProviderRegistry, engine: AsyncEngine | None = None) -> Retriever:
    """Convenience wrapper over `rag.pipeline.build_retriever` that takes an assembled registry."""
    return _build_retriever(settings, providers.filings, engine=engine)
