"""RFC 7807 problem-details exception handling (§6.4).

FastAPI's default `HTTPException` serialises as ``{"detail": "..."}``.
That's fine for humans but the frontend needs a *machine-readable*
discriminator so it can render context-aware recovery copy without a
catalog of magic strings. RFC 7807 gives us that via the ``type``
field — a URI or a short slug like ``verified_citations_required`` or
``ethical_wall_matters_not_found``.

We:

- keep `HTTPException` usable throughout the codebase (no mass rewrite);
- intercept it at the FastAPI exception-handler layer and re-shape the
  response body into the RFC 7807 envelope;
- look up a short ``type`` slug by (status_code, matched-detail-pattern)
  so an existing detail like "Matter not found." becomes
  ``type="matter_not_found"``;
- fall back to ``type="https://httpstatuses.com/<code>"`` when no
  specific slug matches.

The response ``Content-Type`` is ``application/problem+json`` per spec.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


# Mapping of (status_code, detail-substring) → short machine-readable
# `type` slug. The slug doesn't resolve as a URL — it's a stable
# identifier the frontend can switch on. First match wins; order
# matters when a substring would match multiple patterns.
PROBLEM_TYPE_MAP: list[tuple[int, str, str]] = [
    # 404 — resources that exist but the caller can't see.
    (404, "Matter not found", "matter_not_found"),
    (404, "Draft not found", "draft_not_found"),
    (404, "Draft version not found", "draft_version_not_found"),
    (404, "Hearing pack not found", "hearing_pack_not_found"),
    (404, "Hearing not found", "hearing_not_found"),
    (404, "Grant not found", "access_grant_not_found"),
    (404, "Wall not found", "ethical_wall_not_found"),
    # 409 — state-machine conflicts.
    (409, "Finalized drafts cannot", "draft_finalized_immutable"),
    (409, "Draft is finalized", "draft_finalized_immutable"),
    (409, "Cannot submit from status", "draft_invalid_transition"),
    (409, "Only in-review drafts", "draft_invalid_transition"),
    (409, "Only approved drafts", "draft_invalid_transition"),
    (409, "Draft has no generated version", "draft_no_version_yet"),
    (409, "Draft has no version to export", "draft_no_version_yet"),
    (409, "Draft's current version is missing", "draft_version_missing"),
    # 422 — fail-closed gates.
    (422, "verified citations", "verified_citations_required"),
    (422, "Could not assemble", "llm_output_invalid"),
    (422, "Could not produce", "llm_output_invalid"),
    (422, "no usable items", "llm_output_invalid"),
    # 401 / 403.
    (401, "Missing bearer token", "missing_bearer_token"),
    # EG-001 (2026-04-23) widened the auth dependency to accept either
    # a cookie or a bearer token; the missing-credentials message now
    # mentions both. Keep the same machine-readable slug so existing
    # clients keep matching.
    (401, "Missing session cookie or bearer token", "missing_bearer_token"),
    (401, "Invalid", "invalid_token"),
    (401, "expired", "invalid_token"),
    (403, "Requires role", "role_required"),
    (403, "Capability", "capability_required"),
    (403, "Managing matter access", "capability_required"),
    # 429.
    (429, "Rate limit", "rate_limited"),
    # 400.
    (400, "must be an ISO-8601", "invalid_parameter"),
    (400, "password", "password_policy_violation"),
]


STATUS_TITLES: dict[int, str] = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    422: "Unprocessable content",
    429: "Too many requests",
    500: "Internal server error",
}


def _resolve_type_slug(status_code: int, detail: str) -> str:
    detail_lower = detail.lower()
    for (code, needle, slug) in PROBLEM_TYPE_MAP:
        if code == status_code and needle.lower() in detail_lower:
            return slug
    return f"https://httpstatuses.com/{status_code}"


def _problem_payload(
    *,
    status_code: int,
    detail: Any,
    instance: str,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Pydantic validation errors are lists; normalise to a single string
    # for the human-readable `detail` field but keep the structured
    # breakdown under `errors` for machine readers.
    errors: list[Any] | None = None
    if isinstance(detail, list):
        errors = jsonable_encoder(detail)
        detail_text = "; ".join(
            str(item.get("msg") if isinstance(item, dict) else item)
            for item in detail
        )
    else:
        detail_text = str(detail)

    slug = _resolve_type_slug(status_code, detail_text)
    body: dict[str, Any] = {
        "type": slug,
        "title": STATUS_TITLES.get(status_code, "Error"),
        "status": status_code,
        "detail": detail_text,
        "instance": instance,
    }
    if errors:
        body["errors"] = errors
    if extras:
        body.update(extras)
    return body


def problem_json(
    status_code: int,
    *,
    detail: Any,
    request: Request,
    headers: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
) -> JSONResponse:
    body = _problem_payload(
        status_code=status_code,
        detail=detail,
        instance=str(request.url.path),
        extras=extras,
    )
    merged_headers = {"Content-Type": PROBLEM_CONTENT_TYPE}
    if headers:
        merged_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=merged_headers,
    )


def register_problem_handlers(application: FastAPI) -> None:
    """Attach RFC 7807 handlers to the FastAPI app. Idempotent."""

    @application.exception_handler(HTTPException)
    async def _http_exception(
        request: Request, exc: HTTPException
    ) -> JSONResponse:  # pragma: no cover — thin wrapper
        return problem_json(
            exc.status_code,
            detail=exc.detail,
            request=request,
            headers=getattr(exc, "headers", None) or None,
        )

    @application.exception_handler(RequestValidationError)
    async def _validation_exception(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:  # pragma: no cover
        return problem_json(
            422,
            detail=exc.errors(),
            request=request,
        )


__all__ = [
    "PROBLEM_CONTENT_TYPE",
    "PROBLEM_TYPE_MAP",
    "problem_json",
    "register_problem_handlers",
]
