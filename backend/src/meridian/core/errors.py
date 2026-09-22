from __future__ import annotations


class MeridianError(Exception):
    """Base error. `code` is stable and safe to expose through the API."""

    code = "internal_error"
    status_code = 500
    retryable = False

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(MeridianError):
    code = "not_found"
    status_code = 404


class ValidationFailedError(MeridianError):
    code = "validation_failed"
    status_code = 422


class ConflictError(MeridianError):
    code = "conflict"
    status_code = 409


class AuthenticationError(MeridianError):
    code = "unauthenticated"
    status_code = 401


class RateLimitedError(MeridianError):
    code = "rate_limited"
    status_code = 429
    retryable = True


class CompanyNotFoundError(NotFoundError):
    code = "company_not_found"


class ProviderError(MeridianError):
    """An external data/LLM provider failed."""

    code = "provider_error"
    status_code = 502
    retryable = True

    def __init__(self, provider: str, message: str, *, retryable: bool = True, **kw: object) -> None:
        super().__init__(f"[{provider}] {message}", details={"provider": provider, **kw})
        self.provider = provider
        self.retryable = retryable


class ProviderUnavailableError(ProviderError):
    """Provider not configured (missing key) or no snapshot available."""

    code = "provider_unavailable"
    status_code = 503

    def __init__(self, provider: str, message: str, **kw: object) -> None:
        super().__init__(provider, message, retryable=False, **kw)


class DataNotAvailableError(MeridianError):
    code = "data_not_available"
    status_code = 404


class BlockedURLError(MeridianError):
    code = "blocked_url"
    status_code = 400


class LLMOutputError(MeridianError):
    """LLM returned output that failed schema validation after retries."""

    code = "llm_output_invalid"
    status_code = 502
    retryable = True


class AgentTimeoutError(MeridianError):
    code = "agent_timeout"
    status_code = 504
    retryable = True
