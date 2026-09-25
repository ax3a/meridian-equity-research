"""FastAPI application factory.

`create_app()` (no arguments) is what `uvicorn --factory meridian.api.app:create_app` calls, and what
`meridian serve` uses. Tests pass `settings=`/`runtime=` explicitly: `runtime=` lets an integration test
swap in a `Runtime` built from a fake/scripted agent set (see `tests/integration/api/conftest.py`)
without touching any of the real provider/LLM wiring.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from meridian.api.errors import register_exception_handlers
from meridian.api.routers import companies, dashboard, preferences, research, system
from meridian.api.status import MERIDIAN_VERSION
from meridian.api.wiring import Runtime, build_runtime, check_redis, probe_database
from meridian.core.config import Settings, get_settings
from meridian.core.ids import new_id
from meridian.core.logging import configure_logging, get_logger
from meridian.observability.tracing import configure_tracing

log = get_logger(__name__)

API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    resolved_settings = settings or (runtime.settings if runtime is not None else get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        configure_tracing(resolved_settings)
        rt = runtime if runtime is not None else await build_runtime(resolved_settings)
        app.state.runtime = rt
        log.info(
            "meridian_api_started",
            database=rt.db_available,
            redis=rt.redis_available,
            llm_mode=resolved_settings.llm_mode,
            data_mode=resolved_settings.data_mode,
        )
        try:
            yield
        finally:
            await rt.aclose()

    app = FastAPI(title="Meridian Equity Research API", version=MERIDIAN_VERSION, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.middleware("http")
    async def _request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or new_id("req")
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response

    @app.get("/health", tags=["health"])
    async def health(request: Request) -> dict[str, object]:
        """Unauthenticated. Never fails even when the database/Redis are unreachable."""
        rt: Runtime = request.app.state.runtime
        database = await probe_database(rt.settings)
        redis = await check_redis(rt.settings.redis_url)
        return {
            "status": "ok",
            "version": MERIDIAN_VERSION,
            "database": database,
            "redis": redis,
            "auth_required": bool(rt.settings.api_key),  # an empty API_KEY="" env var is treated as unset
        }

    app.include_router(research.router, prefix=API_V1_PREFIX)
    app.include_router(companies.router, prefix=API_V1_PREFIX)
    app.include_router(dashboard.router, prefix=API_V1_PREFIX)
    app.include_router(preferences.router, prefix=API_V1_PREFIX)
    app.include_router(system.router, prefix=API_V1_PREFIX)

    return app
