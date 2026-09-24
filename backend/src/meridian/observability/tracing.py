"""Optional tracing: OpenTelemetry spans (if configured and importable) and LangSmith env wiring.

Both backends are best-effort. Neither is required for the platform to run, so nothing here may ever
raise during startup: a missing `otel_exporter_otlp_endpoint`, missing `opentelemetry-*` packages, or
an exporter that can't reach its collector must all degrade to `span()` being a no-op context manager.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Any

from meridian.core.config import Settings
from meridian.core.logging import get_logger

log = get_logger(__name__)

_tracer: Any | None = None


def configure_tracing(settings: Settings) -> None:
    """Wire up LangSmith env vars (if configured) and an OpenTelemetry tracer (if configured and available).

    Safe to call multiple times (e.g. once per test); never raises.
    """
    global _tracer
    _tracer = None

    if settings.langsmith_api_key is not None:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        log.warning("otel_packages_unavailable", detail="opentelemetry packages not installed; tracing disabled")
        return

    try:
        provider = TracerProvider(resource=Resource.create({"service.name": "meridian"}))
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("meridian")
    except Exception:  # pragma: no cover - defensive: an optional backend must never break startup
        log.exception("otel_setup_failed")
        _tracer = None


@contextlib.contextmanager
def span(name: str, **attrs: Any) -> Iterator[None]:
    """A tracing span, or a no-op if OpenTelemetry was never configured.

    Only span setup/teardown is defensive; exceptions raised by the wrapped code always propagate.
    """
    if _tracer is None:
        yield
        return
    try:
        span_cm = _tracer.start_as_current_span(name, attributes=attrs)
    except Exception:  # pragma: no cover - defensive: a broken tracer must not break the caller
        log.exception("span_start_failed", name=name)
        yield
        return
    with span_cm:
        yield
