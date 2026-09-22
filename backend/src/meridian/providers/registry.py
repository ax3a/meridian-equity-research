from __future__ import annotations

from dataclasses import dataclass

from meridian.providers.base import (
    CompanyDirectory,
    EmbeddingProvider,
    FilingsProvider,
    FundamentalsProvider,
    MacroProvider,
    MarketDataProvider,
    NewsProvider,
    PeerUniverseProvider,
)
from meridian.providers.llm.base import LLMProvider


@dataclass
class ProviderRegistry:
    """The concrete providers (usually fallback chains) the tools use for one process."""

    directory: CompanyDirectory
    fundamentals: FundamentalsProvider
    filings: FilingsProvider
    market: MarketDataProvider
    news: NewsProvider
    macro: MacroProvider
    peers: PeerUniverseProvider
    llm: LLMProvider
    embeddings: EmbeddingProvider

    def describe(self) -> dict[str, str]:
        return {
            "directory": self.directory.name,
            "fundamentals": self.fundamentals.name,
            "filings": self.filings.name,
            "market": self.market.name,
            "news": self.news.name,
            "macro": self.macro.name,
            "peers": self.peers.name,
            "llm": self.llm.name,
            "embeddings": self.embeddings.name,
        }
