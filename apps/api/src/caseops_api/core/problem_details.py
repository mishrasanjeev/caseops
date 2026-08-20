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

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from caseops_api.core.observability import ensure_request_id, get_request_id

PROBLEM_CONTENT_TYPE = "application/problem+json"


class ProblemType(StrEnum):
    """Stable types for cross-revision recovery paths.

    New command/reliability code should raise :class:`ProblemHTTPException`
    with one of these values instead of depending on a detail substring.
    """

    STALE_WRITE = "stale_write"
    # PRD section 16.7 names this wire value exactly. Keep the older member
    # name as an alias so an in-flight caller cannot reintroduce the incorrect
    # ``idempotency_in_progress`` response while branches are integrated.
    OPERATION_IN_PROGRESS = "operation_in_progress"
    IDEMPOTENCY_IN_PROGRESS = "operation_in_progress"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    WORKFLOW_DISABLED = "workflow_disabled"
    WORKFLOW_NOT_CONFIGURED = "workflow_not_configured"
    INVALID_WORKFLOW_TRANSITION = "invalid_workflow_transition"


class ProblemHTTPException(HTTPException):
    """HTTP exception whose machine type is independent of human copy."""

    def __init__(
        self,
        status_code: int,
        *,
        problem_type: ProblemType | str,
        detail: str,
        headers: dict[str, str] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.problem_type = str(problem_type)
        self.problem_extras = dict(extras or {})


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
    (403, "Complete MFA step-up", "step_up_required"),
    (403, "MFA is required", "mfa_enrollment_required"),
    # 429.
    (429, "Rate limit", "rate_limited"),
    # 503.
    (503, "provider quota is exhausted", "llm_quota_exhausted"),
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
    503: "Service unavailable",
    500: "Internal server error",
}


def _generic_type_uri(status_code: int) -> str:
    """The last-resort type: it identifies the status and nothing else."""

    return f"https://httpstatuses.com/{status_code}"


def _match_type_slug(status_code: int, detail: str) -> str | None:
    """The mapped slug for this detail text, or None when nothing matches.

    Split from the generic fallback so callers can distinguish "the map knows
    this" from "the map has nothing" - previously the two were the same return
    value, which made any `or` branch after it unreachable.
    """

    detail_lower = detail.lower()
    for (code, needle, slug) in PROBLEM_TYPE_MAP:
        if code == status_code and needle.lower() in detail_lower:
            return slug
    return None


def _resolve_type_slug(status_code: int, detail: str) -> str:
    return _match_type_slug(status_code, detail) or _generic_type_uri(status_code)


def _problem_payload(
    *,
    status_code: int,
    detail: Any,
    instance: str,
    extras: dict[str, Any] | None = None,
    problem_type: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    # Pydantic validation errors are lists; normalise to a single string
    # for the human-readable `detail` field but keep the structured
    # breakdown under `errors` for machine readers.
    errors: list[Any] | None = None
    detail_extensions: dict[str, Any] = {}
    detail_slug: str | None = None
    if isinstance(detail, list):
        errors = jsonable_encoder(detail)
        detail_text = "; ".join(
            str(item.get("msg") if isinstance(item, dict) else item)
            for item in detail
        )
    elif isinstance(detail, dict):
        # HTTPException callers use dictionaries for machine-readable conflict
        # metadata. Keep RFC 7807's human-readable ``detail`` as a string and
        # expose the remaining keys as extension members instead of collapsing
        # the dictionary into an unusable Python repr.
        encoded_detail = jsonable_encoder(detail)
        detail_text = str(
            encoded_detail.pop("detail", None)
            or encoded_detail.pop("message", None)
            or STATUS_TITLES.get(status_code, "Error")
        )
        # The caller's own machine-readable code. Services across this codebase
        # raise `detail={"type": "some_slug", ...}`, and until now that slug was
        # discarded as a reserved member - so over HTTP the refusal arrived as a
        # generic https://httpstatuses.com/409 and a client could not tell "this
        # class was never reviewed" from "no such class". Service-level tests
        # never noticed, because they read exc.detail["type"] directly.
        #
        # Only a bare slug is taken: anything containing "/" is already a URI
        # the caller meant as the problem type, and is left to the paths below.
        candidate = encoded_detail.get("type")
        if isinstance(candidate, str) and candidate and "/" not in candidate:
            detail_slug = candidate

        reserved_problem_members = {
            "type",
            "title",
            "status",
            "detail",
            "instance",
            "errors",
            "request_id",
        }
        detail_extensions = {
            key: value
            for key, value in encoded_detail.items()
            if key not in reserved_problem_members
        }
    else:
        detail_text = str(detail)

    # Order is deliberate and additive. An explicit problem_type still wins, and
    # the substring map still beats the caller's dict slug, so no response that
    # already resolved to a known slug changes shape. The dict slug only fills
    # in where the answer used to be the generic status URL.
    slug = (
        problem_type
        or _match_type_slug(status_code, detail_text)
        or detail_slug
        or _generic_type_uri(status_code)
    )
    body: dict[str, Any] = {
        "type": slug,
        "title": STATUS_TITLES.get(status_code, "Error"),
        "status": status_code,
        "detail": detail_text,
        "instance": instance,
    }
    if request_id:
        body["request_id"] = request_id
    if errors:
        body["errors"] = errors
    if detail_extensions:
        body.update(detail_extensions)
    if extras:
        reserved_problem_members = {
            "type",
            "title",
            "status",
            "detail",
            "instance",
            "errors",
            "request_id",
        }
        encoded_extras = jsonable_encoder(extras)
        body.update(
            {
                key: value
                for key, value in encoded_extras.items()
                if key.lower() not in reserved_problem_members
            }
        )
    return body


def problem_json(
    status_code: int,
    *,
    detail: Any,
    request: Request,
    headers: dict[str, str] | None = None,
    extras: dict[str, Any] | None = None,
    problem_type: str | None = None,
) -> JSONResponse:
    request_id = (
        get_request_id()
        or getattr(request.state, "request_id", None)
        or ensure_request_id(request.headers.get("X-Request-ID"))
    )
    body = _problem_payload(
        status_code=status_code,
        detail=detail,
        instance=str(request.url.path),
        extras=extras,
        problem_type=problem_type,
        request_id=request_id,
    )
    merged_headers = {"Content-Type": PROBLEM_CONTENT_TYPE}
    if headers:
        merged_headers.update(
            {
                key: value
                for key, value in headers.items()
                if key.lower()
                not in {"content-length", "content-type", "x-request-id"}
            }
        )
    merged_headers["X-Request-ID"] = request_id
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
            extras=getattr(exc, "problem_extras", None),
            problem_type=getattr(exc, "problem_type", None),
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

    @application.exception_handler(Exception)
    async def _unexpected_exception(
        request: Request, _exc: Exception
    ) -> JSONResponse:  # pragma: no cover -- exercised through ServerErrorMiddleware
        # Never reflect the exception text: it may contain SQL, provider data,
        # credentials, or tenant-private content. ServerErrorMiddleware still
        # re-raises after sending this response so the server records the
        # original exception and traceback.
        return problem_json(
            500,
            detail="An unexpected error occurred.",
            request=request,
        )

__all__ = [
    "PROBLEM_CONTENT_TYPE",
    "PROBLEM_TYPE_MAP",
    "ProblemHTTPException",
    "ProblemType",
    "problem_json",
    "register_problem_handlers",
]
