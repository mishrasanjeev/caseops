"""§6.5 — OpenAPI completeness lint.

Every `/api/...` route must have:

- a non-empty `summary` (shows up in the Swagger UI sidebar — the most
  visible docs surface we have today);
- at least one `tag` (so Swagger groups endpoints coherently);
- at least one documented response code.

The lint walks the live application's `openapi()` output, so new
routes are picked up automatically. Exemptions stay narrow: the bare
openapi/docs endpoints themselves, plus the two probe endpoints on
`/api/health` and `/api/meta` (which are intentionally low-ceremony).
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


EXEMPT_PATHS: set[str] = {
    # Probe endpoints — trivially documented by their path.
    "/api/health",
    "/api/meta",
}


def _iter_operations(schema: dict[str, Any]):
    for path, methods in schema.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            method_upper = method.upper()
            if method_upper not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            yield path, method_upper, operation


def test_every_api_route_has_summary_tag_and_response(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    missing: list[str] = []
    for path, method, op in _iter_operations(schema):
        if path in EXEMPT_PATHS:
            continue
        if not path.startswith("/api/"):
            # Non-/api routes (root metadata) are out of scope.
            continue
        reasons: list[str] = []
        if not op.get("summary"):
            reasons.append("no summary")
        if not op.get("tags"):
            reasons.append("no tags")
        if not op.get("responses"):
            reasons.append("no responses")
        if reasons:
            missing.append(f"{method} {path}: {'; '.join(reasons)}")
    assert not missing, "routes with missing OpenAPI metadata:\n  " + "\n  ".join(missing)


def test_every_api_route_returns_json_or_file(client: TestClient) -> None:
    """Routes that respond with a body must declare either
    application/json, application/problem+json, or a concrete stream
    media type (docx / octet-stream / pdf). Stops a route from
    accidentally shipping `text/html` because a handler returned a
    string."""
    schema = client.get("/openapi.json").json()
    mis_typed: list[str] = []
    acceptable = {
        "application/json",
        "application/problem+json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf",
        "application/octet-stream",
        "application/x-ndjson",
    }
    for path, method, op in _iter_operations(schema):
        if not path.startswith("/api/") or path in EXEMPT_PATHS:
            continue
        responses = op.get("responses") or {}
        for status_code, body in responses.items():
            if not isinstance(body, dict):
                continue
            content = body.get("content")
            if not content:
                continue
            unexpected = [
                ctype for ctype in content.keys() if ctype not in acceptable
            ]
            if unexpected:
                mis_typed.append(
                    f"{method} {path} -> {status_code}: unexpected "
                    f"media types {unexpected}"
                )
    assert not mis_typed, "routes with unexpected media types:\n  " + "\n  ".join(
        mis_typed
    )
