"""Domain exceptions and their mapping to safe HTTP error responses.

Domain code raises these exceptions; the API layer converts them into JSON
responses that never leak stack traces or internal details to clients.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, client-presentable errors."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaError(AppError):
    status_code = 415
    code = "unsupported_media_type"


class DocumentParsingError(AppError):
    status_code = 422
    code = "document_parsing_failed"


class EmbeddingDimensionError(AppError):
    status_code = 500
    code = "embedding_dimension_mismatch"


class LLMProviderError(AppError):
    """Raised when an LLM provider fails after retries (timeouts, auth, outages)."""

    status_code = 502
    code = "llm_provider_error"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
