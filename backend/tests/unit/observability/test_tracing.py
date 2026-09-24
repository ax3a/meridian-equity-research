from __future__ import annotations

import builtins

from meridian.core.config import Settings
from meridian.observability import tracing


def _settings(**overrides: object) -> Settings:
    return Settings(env="test", redis_url=None, llm_provider="offline", **overrides)


def test_span_is_noop_without_otel_endpoint() -> None:
    tracing.configure_tracing(_settings(otel_exporter_otlp_endpoint=None))
    with tracing.span("do_work", agent="company"):
        pass  # must not raise


def test_configure_tracing_never_raises_when_otel_packages_missing(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name.startswith("opentelemetry"):
            raise ImportError(f"simulated missing package: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # Must not raise even though an OTLP endpoint is configured but the packages are "missing".
    tracing.configure_tracing(_settings(otel_exporter_otlp_endpoint="http://localhost:4318"))
    with tracing.span("do_work"):
        pass


def test_configure_tracing_sets_langsmith_env(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    tracing.configure_tracing(_settings(langsmith_api_key="secret-key", langsmith_project="meridian-test"))

    import os

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "secret-key"
    assert os.environ["LANGSMITH_PROJECT"] == "meridian-test"


def test_configure_tracing_does_not_break_startup_with_real_otel_packages() -> None:
    # opentelemetry is installed in this environment; ensure a real (but unreachable) endpoint
    # still configures without raising and without making network calls at setup time.
    from opentelemetry import trace

    tracing.configure_tracing(_settings(otel_exporter_otlp_endpoint="http://127.0.0.1:4318"))
    try:
        with tracing.span("do_work", foo="bar"):
            pass
    finally:
        # Avoid leaking a background BatchSpanProcessor export thread (unreachable endpoint) into
        # later test modules; shutdown flushes/stops it immediately instead of on its own schedule.
        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
        tracing.configure_tracing(_settings(otel_exporter_otlp_endpoint=None))  # reset for other tests
