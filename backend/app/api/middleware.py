"""Request-ID propagation, access logging, latency metrics and safe error handlers."""

from __future__ import annotations

import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.exceptions import AppError
from app.core.logging import get_logger, request_id_ctx, user_id_ctx
from app.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = get_logger("app.access")
_VALID_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _VALID_RID.match(incoming) else uuid.uuid4().hex
        rid_token = request_id_ctx.set(rid)
        uid_token = user_id_ctx.set(None)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - start
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(elapsed)
            logger.info(
                "request",
                extra={"method": request.method, "path": path, "status": status, "latency_ms": round(elapsed * 1000, 2)},
            )
            request_id_ctx.reset(rid_token)
            user_id_ctx.reset(uid_token)


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body = {"error": code, "message": message, "request_id": request_id_ctx.get()}
    if details:
        body["details"] = details
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(status_code=status, content=body, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("Application error", extra={"code": exc.code, "error_message": exc.message})
        return _error(exc.status_code, exc.code, exc.message, exc.details or None)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return _error(422, "validation_error", "Request validation failed", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Full details go to logs only; clients get a generic message + request id.
        logger.exception("Unhandled error")
        return _error(500, "internal_error", "An unexpected error occurred")
