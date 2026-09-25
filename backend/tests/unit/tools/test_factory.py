from __future__ import annotations

from meridian.core.config import Settings
from meridian.providers.factory import build_llm, build_providers
from meridian.providers.llm.anthropic_provider import AnthropicLLMProvider
from meridian.providers.llm.offline import OfflineLLMProvider
from meridian.tools.factory import build_tool_registry

EXPECTED_TOOL_NAMES = {
    "resolve_company",
    "search_companies",
    "get_company_profile",
    "get_financial_statements",
    "compute_financial_metrics",
    "calculate_metric",
    "run_dcf",
    "list_filings",
    "index_filings",
    "search_filings",
    "get_filing_section",
    "get_recent_8k_events",
    "get_market_quote",
    "search_news",
    "get_macro_indicators",
    "find_peer_candidates",
    "get_peer_snapshot",
    "lookup_evidence",
    "recall_research_memory",
}


def test_build_tool_registry_has_exactly_nineteen_tools():
    registry = build_tool_registry()
    names = set(registry.names())
    assert len(names) == 19
    assert names == EXPECTED_TOOL_NAMES


def test_build_tool_registry_specs_are_retrievable_for_an_allowlist():
    registry = build_tool_registry()
    specs = registry.specs(frozenset({"resolve_company", "get_financial_statements"}))
    assert {s.name for s in specs} == {"resolve_company", "get_financial_statements"}


def _settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        env="test",
        redis_url=None,
        llm_provider="offline",
        data_mode="live",
        snapshot_dir=tmp_path / "snapshots",
        model_cache_dir=tmp_path / "models",
        embedding_provider="hashing",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_build_providers_with_no_keys_uses_only_keyless_chains(tmp_path):
    settings = _settings(tmp_path)
    registry = build_providers(settings)
    described = registry.describe()

    assert described["fundamentals"] == "chain(sec_edgar)"
    assert described["filings"] == "sec_edgar"
    assert described["market"] == "chain(yahoo>stooq)"
    assert described["news"] == "chain(gdelt)"
    assert described["macro"] == "chain(us_treasury)"
    assert described["peers"] == "chain(sec_edgar)"
    assert described["llm"] == "offline"
    assert described["embeddings"] == "hashing"


def test_build_providers_activates_optional_adapters_only_when_keyed(tmp_path):
    settings = _settings(
        tmp_path,
        fmp_api_key="fmp-key",
        alpha_vantage_api_key="av-key",
        finnhub_api_key="finnhub-key",
        polygon_api_key="polygon-key",
        fred_api_key="fred-key",
    )
    registry = build_providers(settings)
    described = registry.describe()

    assert described["fundamentals"] == "chain(sec_edgar>fmp)"
    assert described["market"] == "chain(yahoo>stooq>fmp>alpha_vantage>finnhub>polygon)"
    assert described["news"] == "chain(gdelt>finnhub)"
    assert described["macro"] == "chain(us_treasury>fred)"
    assert described["peers"] == "chain(sec_edgar>fmp>finnhub)"


def test_build_llm_offline_when_no_anthropic_key(tmp_path):
    settings = _settings(tmp_path, llm_provider="auto", anthropic_api_key=None)
    assert isinstance(build_llm(settings), OfflineLLMProvider)


def test_build_llm_anthropic_when_key_present(tmp_path):
    settings = _settings(tmp_path, llm_provider="auto", anthropic_api_key="sk-test-key")
    assert isinstance(build_llm(settings), AnthropicLLMProvider)
