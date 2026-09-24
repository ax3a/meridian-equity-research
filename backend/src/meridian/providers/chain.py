"""Generic fallback chains, one per provider protocol.

Every chain tries its providers in the order given, records a warning and moves on when a provider
fails (whether because it isn't configured -- ``ProviderUnavailableError``, e.g. a missing API key -- or
because a keyless source misbehaved at runtime -- any other ``ProviderError``, e.g. Stooq answering with
an anti-bot page instead of CSV), and only raises once every provider has failed. The successful
``ProviderResult.provider`` always names the provider that actually answered (never the chain itself), so
callers can attribute data honestly; the chain's own accumulated warnings are prepended to that result's
``warnings`` list.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Generic, Protocol, TypeVar

from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.core.logging import get_logger
from meridian.providers.base import (
    FundamentalsProvider,
    MacroIndicator,
    MacroProvider,
    MarketDataProvider,
    NewsArticle,
    NewsProvider,
    PeerCandidate,
    PeerUniverseProvider,
    ProviderResult,
)
from meridian.schemas.financials import FinancialStatements, Quote
from meridian.schemas.research import CompanyIdentity

log = get_logger(__name__)

R = TypeVar("R")


class _Named(Protocol):
    name: str


P = TypeVar("P", bound=_Named)


def _reason(exc: ProviderError) -> str:
    """The provider-specific message, without the '[provider] ' prefix ProviderError adds."""
    prefix = f"[{exc.provider}] "
    return exc.message[len(prefix) :] if exc.message.startswith(prefix) else exc.message


class _FallbackChain(Generic[P]):
    """Shared try-in-order / warn-and-continue / re-raise-last-error behaviour."""

    def __init__(self, providers: list[P]) -> None:
        if not providers:
            raise ValueError(f"{type(self).__name__} needs at least one provider")
        self.providers: list[P] = providers
        self.name = "chain(" + ">".join(p.name for p in providers) + ")"

    async def _run(self, call: Callable[[P], Awaitable[ProviderResult[R]]]) -> ProviderResult[R]:
        warnings: list[str] = []
        last_error: ProviderError | None = None
        for provider in self.providers:
            try:
                result = await call(provider)
            except ProviderUnavailableError as exc:
                warning = f"{provider.name} unavailable: {_reason(exc)}"
                log.warning("provider_skipped", chain=self.name, provider=provider.name, reason=_reason(exc))
                warnings.append(warning)
                last_error = exc
                continue
            except ProviderError as exc:
                warning = f"{provider.name} failed: {_reason(exc)}"
                log.warning("provider_failed", chain=self.name, provider=provider.name, reason=_reason(exc))
                warnings.append(warning)
                last_error = exc
                continue
            result.warnings = [*warnings, *result.warnings]
            return result
        assert last_error is not None  # guaranteed: providers is non-empty, so the loop always assigns or returns
        raise last_error


class MarketChain(_FallbackChain[MarketDataProvider]):
    """Fallback chain over ``MarketDataProvider`` implementations."""

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[Quote]:
        return await self._run(lambda p: p.get_quote(ticker, history_days))


class NewsChain(_FallbackChain[NewsProvider]):
    """Fallback chain over ``NewsProvider`` implementations."""

    async def search_news(
        self, company: CompanyIdentity, days: int = 90, limit: int = 25
    ) -> ProviderResult[list[NewsArticle]]:
        return await self._run(lambda p: p.search_news(company, days, limit))


class MacroChain(_FallbackChain[MacroProvider]):
    """Fallback chain over ``MacroProvider`` implementations."""

    async def get_indicators(self) -> ProviderResult[list[MacroIndicator]]:
        return await self._run(lambda p: p.get_indicators())


class PeerChain(_FallbackChain[PeerUniverseProvider]):
    """Fallback chain over ``PeerUniverseProvider`` implementations."""

    async def candidate_peers(self, company: CompanyIdentity, limit: int = 12) -> ProviderResult[list[PeerCandidate]]:
        return await self._run(lambda p: p.candidate_peers(company, limit))


class FundamentalsChain(_FallbackChain[FundamentalsProvider]):
    """Fallback chain over ``FundamentalsProvider`` implementations."""

    async def get_statements(self, company: CompanyIdentity, years: int = 5) -> ProviderResult[FinancialStatements]:
        return await self._run(lambda p: p.get_statements(company, years))
