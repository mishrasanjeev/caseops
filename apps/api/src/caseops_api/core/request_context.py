"""Starlette middleware that sets request-scoped context vars.

Must run BEFORE route handlers so every log line and every DB query
inside the request can pick up ``request_id`` from ``contextvars``.
We propagate it back to the caller as the ``X-Request-ID`` header so
distributed traces can correlate across services.

The tenant / user / membership / matter fields are set later by the
auth dependency + route bodies — this middleware only plants the
``request_id`` seed and clears everything on response.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from caseops_api.core.observability import (
    clear_context,
    ensure_request_id,
    set_request_id,
)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        candidate = request.headers.get(REQUEST_ID_HEADER)
        rid = ensure_request_id(candidate)
        set_request_id(rid)
        try:
            response = await call_next(request)
        finally:
            # Even if the handler raises, drop the identifiers so the
            # next request starts clean. FastAPI reuses threads across
            # requests under uvicorn workers.
            clear_context()
        response.headers[REQUEST_ID_HEADER] = rid
        return response


__all__ = ["REQUEST_ID_HEADER", "RequestContextMiddleware"]
