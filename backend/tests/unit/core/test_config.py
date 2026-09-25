"""Settings must load from a human-written .env.

Regression: `CORS_ORIGINS=http://localhost:3000` (exactly what .env.example ships) raised
SettingsError, because pydantic-settings JSON-decodes complex types in the env source before field
validators run. Every process refused to start after `setup.ps1` created a .env from the example.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from meridian.core.config import Settings


def _settings_from_env(tmp_path: Path, body: str) -> Settings:
    env_file = tmp_path / ".env"
    env_file.write_text(body, encoding="utf-8")
    return Settings(_env_file=env_file)  # type: ignore[call-arg]


def test_comma_separated_cors_origins_from_env_file(tmp_path):
    settings = _settings_from_env(tmp_path, "CORS_ORIGINS=http://localhost:3000,https://app.example.com\n")

    assert settings.cors_origins == ["http://localhost:3000", "https://app.example.com"]


def test_single_cors_origin_from_env_file(tmp_path):
    assert _settings_from_env(tmp_path, "CORS_ORIGINS=http://localhost:3000\n").cors_origins == [
        "http://localhost:3000"
    ]


def test_json_array_cors_origins_still_supported(tmp_path):
    body = 'CORS_ORIGINS=["http://localhost:3000", "https://app.example.com"]\n'

    assert _settings_from_env(tmp_path, body).cors_origins == [
        "http://localhost:3000",
        "https://app.example.com",
    ]


def test_whitespace_and_empty_entries_are_ignored(tmp_path):
    assert _settings_from_env(tmp_path, "CORS_ORIGINS= http://a , ,http://b \n").cors_origins == [
        "http://a",
        "http://b",
    ]


def test_the_shipped_env_example_actually_loads(tmp_path):
    """The file a new developer copies to .env must produce valid settings."""
    example = Path(__file__).resolve().parents[4] / ".env.example"
    assert example.is_file(), f"expected .env.example at {example}"

    settings = Settings(_env_file=example)  # type: ignore[call-arg]

    assert settings.cors_origins
    assert settings.llm_mode in ("anthropic", "offline")
    assert settings.data_mode in ("live", "snapshot", "auto")


@pytest.mark.parametrize("tier", ["planner", "worker", "critic", "writer"])
def test_every_llm_tier_resolves_a_model_and_effort(tier):
    settings = Settings()

    assert settings.model_for(tier)
    assert settings.effort_for(tier) in ("low", "medium", "high", "xhigh", "max")


@pytest.mark.parametrize(
    "key",
    [
        "API_KEY",
        "ANTHROPIC_API_KEY",
        "LANGSMITH_API_KEY",
        "FMP_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "FINNHUB_API_KEY",
        "POLYGON_API_KEY",
        "FRED_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ],
)
def test_blank_optional_keys_are_unset_not_empty(tmp_path, key):
    """`.env.example` ships every optional key blank. Blank must mean "not configured".

    Regression: a blank LANGSMITH_API_KEY parsed as an empty secret rather than None, so tracing
    enabled itself and repeatedly POSTed run traces to LangSmith, failing with 401 every time.
    """
    settings = _settings_from_env(tmp_path, f"{key}=\n")

    assert getattr(settings, key.lower()) is None


def test_whitespace_only_key_is_also_unset(tmp_path):
    assert _settings_from_env(tmp_path, "ANTHROPIC_API_KEY=   \n").anthropic_api_key is None


def test_a_real_key_is_kept(tmp_path):
    settings = _settings_from_env(tmp_path, "ANTHROPIC_API_KEY=sk-ant-example\n")

    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-example"


def test_a_configured_key_selects_the_anthropic_path():
    """The test session forces LLM_PROVIDER=offline and an env var outranks the .env file, so pass
    `auto` directly: what is under test is that a present key is what flips `auto` to Anthropic."""
    assert Settings(llm_provider="auto", anthropic_api_key="sk-ant-example").llm_mode == "anthropic"
    assert Settings(llm_provider="auto", anthropic_api_key="").llm_mode == "offline"
