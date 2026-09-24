from __future__ import annotations

import pytest

from meridian.core.errors import ProviderError, ProviderUnavailableError
from meridian.providers.base import ProviderResult
from meridian.providers.chain import MarketChain


class _StubProvider:
    def __init__(self, name: str, *, error: Exception | None = None, value: str = "") -> None:
        self.name = name
        self._error = error
        self._value = value
        self.calls = 0

    async def get_quote(self, ticker: str, history_days: int = 365) -> ProviderResult[str]:
        self.calls += 1
        if self._error:
            raise self._error
        return ProviderResult(data=self._value, provider=self.name)


async def test_chain_uses_first_available_provider() -> None:
    a = _StubProvider("a", value="from-a")
    b = _StubProvider("b", value="from-b")
    chain = MarketChain([a, b])

    result = await chain.get_quote("AAPL")

    assert result.data == "from-a"
    assert result.provider == "a"  # exact answering provider is surfaced, not the chain
    assert result.warnings == []
    assert b.calls == 0


async def test_chain_name_reflects_configured_order() -> None:
    chain = MarketChain([_StubProvider("stooq"), _StubProvider("yahoo"), _StubProvider("fmp")])
    assert chain.name == "chain(stooq>yahoo>fmp)"


async def test_chain_skips_unavailable_provider_with_warning() -> None:
    a = _StubProvider("fmp", error=ProviderUnavailableError("fmp", "no API key configured"))
    b = _StubProvider("stooq", value="stooq-data")
    chain = MarketChain([a, b])

    result = await chain.get_quote("AAPL")

    assert result.data == "stooq-data"
    assert result.provider == "stooq"
    assert result.warnings == ["fmp unavailable: no API key configured"]


async def test_chain_skips_failed_provider_with_warning() -> None:
    """A live-but-broken keyless source (e.g. Stooq blocked) should not abort the whole chain."""
    a = _StubProvider("stooq", error=ProviderError("stooq", "unexpected response body (not CSV)", retryable=False))
    b = _StubProvider("yahoo", value="yahoo-data")
    chain = MarketChain([a, b])

    result = await chain.get_quote("AAPL")

    assert result.data == "yahoo-data"
    assert result.warnings == ["stooq failed: unexpected response body (not CSV)"]


async def test_chain_accumulates_multiple_warnings_before_success() -> None:
    a = _StubProvider("fmp", error=ProviderUnavailableError("fmp", "no API key configured"))
    b = _StubProvider("alpha_vantage", error=ProviderUnavailableError("alpha_vantage", "no API key configured"))
    c = _StubProvider("stooq", value="ok")
    chain = MarketChain([a, b, c])

    result = await chain.get_quote("AAPL")

    assert result.data == "ok"
    assert result.warnings == [
        "fmp unavailable: no API key configured",
        "alpha_vantage unavailable: no API key configured",
    ]


async def test_chain_reraises_last_error_when_all_fail() -> None:
    a = _StubProvider("fmp", error=ProviderUnavailableError("fmp", "no API key configured"))
    b = _StubProvider("stooq", error=ProviderError("stooq", "blocked", retryable=False))
    chain = MarketChain([a, b])

    with pytest.raises(ProviderError) as excinfo:
        await chain.get_quote("AAPL")

    assert excinfo.value.provider == "stooq"


def test_chain_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError):
        MarketChain([])
