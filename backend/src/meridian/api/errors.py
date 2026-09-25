"""Maps every error the API can raise -- platform (`MeridianError`), local (defined here), FastAPI
validation, and anything unexpected -- onto the frozen `ErrorResponse` shape.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from meridian.core.errors import MeridianError
from meridian.core.logging import get_logger
from meridian.schemas.api import ErrorBody, ErrorResponse

log = get_logger(__name__)


class TooManyActiveRunsError(MeridianError):
    """Raised by the admission guard when the concurrent-run cap is reached."""

    code = "too_many_active_runs"
    status_code = 429
    retryable = True


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _respond(
    request: Request, status_code: int, code: str, message: str, details: dict[str, object] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or {}, request_id=_request_id(request))
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(MeridianError)
    async def _meridian_error(request: Request, exc: MeridianError) -> JSONResponse:
        if exc.status_code >= 500:
            log.exception("unhandled_meridian_error", code=exc.code, path=request.url.path)
        return _respond(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _respond(
            request,
            422,
            "validation_failed",
            "request failed validation",
            {"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthenticated", 403: "forbidden"}.get(
            exc.status_code, "http_error"
        )
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _respond(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_exception", path=request.url.path)
        return _respond(request, 500, "internal_error", "internal server error")
