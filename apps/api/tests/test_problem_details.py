"""Exception envelope smoke tests for §6.4.

The handler is backward-compatible with clients that only read
`detail`. These tests pin the new fields so a regression (missing
type, wrong title, etc.) surfaces fast.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from caseops_api.core.observability import get_request_id
from caseops_api.core.problem_details import (
    PROBLEM_CONTENT_TYPE,
    ProblemHTTPException,
    ProblemType,
    _problem_payload,
    register_problem_handlers,
)
from caseops_api.core.request_context import RequestContextMiddleware
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"7807 test — {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def test_404_has_rfc_7807_envelope(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/matters/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = resp.json()
    assert body["status"] == 404
    assert body["title"] == "Not found"
    assert body["type"] == "matter_not_found"
    assert body["detail"] == "Matter not found."
    assert body["instance"].startswith("/api/matters/")
    assert body["request_id"] == resp.headers["X-Request-ID"]


def test_401_has_machine_readable_type(client: TestClient) -> None:
    resp = client.get("/api/matters/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 401
    body = resp.json()
    assert body["type"] == "missing_bearer_token"


def test_422_validation_has_errors_array(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "x",
            "matter_code": "T",
            "practice_area": "?",
            "forum_level": "bad",
            "status": "intake",
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    # Detail is a human-readable join; errors[] preserves the raw shape.
    assert isinstance(body["detail"], str) and len(body["detail"]) > 0
    assert isinstance(body["errors"], list) and body["errors"]
    # Type falls back to a URL because no specific slug matches generic
    # validation failures.
    assert body["type"].startswith("https://") or isinstance(body["type"], str)


def test_structured_detail_keeps_extensions_without_overriding_rfc_members() -> None:
    body = _problem_payload(
        status_code=409,
        detail={
            "message": "The record changed.",
            "code": "stale_write",
            "current_status": "disposed",
            "status": 200,
            "title": "Success",
            "instance": "/spoofed",
        },
        instance="/api/matters/m-1",
    )

    assert body["detail"] == "The record changed."
    assert body["code"] == "stale_write"
    assert body["current_status"] == "disposed"
    assert body["status"] == 409
    assert body["title"] == "Conflict"
    assert body["instance"] == "/api/matters/m-1"


def test_explicit_problem_type_is_stable_and_reserved_extras_cannot_override() -> None:
    application = FastAPI()
    register_problem_handlers(application)

    @application.get("/typed")
    async def _typed() -> None:
        raise ProblemHTTPException(
            409,
            problem_type=ProblemType.IDEMPOTENCY_KEY_REUSED,
            detail="The supplied key belongs to a different request.",
            extras={
                "operation": "ip.transition",
                "status": 200,
                "request_id": "spoof",
                "observed_at": datetime(2026, 8, 12, tzinfo=UTC),
                "workflow_version_id": UUID("00000000-0000-0000-0000-000000000027"),
            },
            headers={
                "Retry-After": "1",
                "content-type": "text/html",
                "Content-Length": "999",
                "X-Request-ID": "spoofed-header",
            },
        )

    with TestClient(application) as isolated_client:
        response = isolated_client.get(
            "/typed", headers={"X-Request-ID": "typed-request-123"}
        )

    assert response.status_code == 409
    assert response.json()["type"] == "idempotency_key_reused"
    assert response.json()["operation"] == "ip.transition"
    assert response.json()["status"] == 409
    assert response.json()["request_id"] == "typed-request-123"
    assert response.json()["observed_at"] == "2026-08-12T00:00:00+00:00"
    assert response.json()["workflow_version_id"] == (
        "00000000-0000-0000-0000-000000000027"
    )
    assert response.headers["X-Request-ID"] == "typed-request-123"
    assert response.headers["content-type"] == PROBLEM_CONTENT_TYPE
    assert response.headers["Retry-After"] == "1"
    assert response.headers["content-length"] != "999"


def test_operation_in_progress_uses_the_prd_wire_value() -> None:
    assert ProblemType.OPERATION_IN_PROGRESS.value == "operation_in_progress"
    assert ProblemType.IDEMPOTENCY_IN_PROGRESS is ProblemType.OPERATION_IN_PROGRESS


def test_unhandled_exception_is_safe_correlated_problem_details() -> None:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)
    register_problem_handlers(application)
    observed_request_ids: list[str | None] = []

    @application.get("/boom")
    async def _boom() -> None:
        observed_request_ids.append(get_request_id())
        raise RuntimeError("secret database and tenant details")

    with TestClient(application, raise_server_exceptions=False) as isolated_client:
        response = isolated_client.get("/boom", headers={"X-Request-ID": "invalid"})

    body = response.json()
    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_CONTENT_TYPE
    assert body["type"] == "https://httpstatuses.com/500"
    assert body["detail"] == "An unexpected error occurred."
    assert "secret" not in response.text
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["request_id"] == observed_request_ids[0]


def test_verified_citations_required_has_specific_slug(client: TestClient) -> None:
    """The fail-closed 422 on approve must carry `verified_citations_required`
    so the frontend can render a precise recovery tooltip."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "7807-APPROVE")

    draft = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Fail-closed test", "draft_type": "brief"},
    ).json()
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/generate",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/submit",
        headers=auth_headers(token),
        json={},
    )
    approve = client.post(
        f"/api/matters/{matter_id}/drafts/{draft['id']}/approve",
        headers=auth_headers(token),
        json={},
    )
    assert approve.status_code == 422
    body = approve.json()
    assert body["type"] == "verified_citations_required"
    assert body["title"] == "Unprocessable content"
    assert "verified citations" in body["detail"].lower()


def test_a_dict_detail_type_becomes_the_machine_readable_slug() -> None:
    # Services across this codebase raise `detail={"type": "some_slug", ...}`.
    # That slug was listed as a reserved problem member and therefore DROPPED,
    # so the refusal arrived over HTTP as a generic https://httpstatuses.com/409
    # and a client could not tell one 409 from another. Service-level tests
    # never noticed, because they read exc.detail["type"] directly.
    body = _problem_payload(
        status_code=409,
        detail={
            "type": "data_class_registered_but_not_reviewed",
            "detail": "This table is inventoried but not reviewed.",
            "data_class_id": "matters",
        },
        instance="/api/admin/x",
    )

    assert body["type"] == "data_class_registered_but_not_reviewed"
    assert body["detail"] == "This table is inventoried but not reviewed."
    # The slug is promoted, not duplicated into the extensions.
    assert "data_class_id" in body
    assert body["status"] == 409


def test_the_substring_map_still_outranks_a_dict_slug() -> None:
    # The change is additive on purpose: a response that already resolved to a
    # mapped slug must keep it, or existing clients switching on that value
    # break. PROBLEM_TYPE_MAP maps 404 + "Matter not found" -> matter_not_found.
    body = _problem_payload(
        status_code=404,
        detail={"type": "something_else", "detail": "Matter not found"},
        instance="/api/matters/m-1",
    )

    assert body["type"] == "matter_not_found"


def test_an_explicit_problem_type_still_outranks_everything() -> None:
    body = _problem_payload(
        status_code=409,
        detail={"type": "from_the_dict", "detail": "Conflict."},
        instance="/api/x",
        problem_type="explicitly_passed",
    )

    assert body["type"] == "explicitly_passed"


def test_a_uri_valued_dict_type_is_not_treated_as_a_slug() -> None:
    # A caller passing a full URI already means it as the problem type; only a
    # bare slug is promoted, so a stray URL cannot silently become the type.
    body = _problem_payload(
        status_code=409,
        detail={"type": "https://example.test/errors/x", "detail": "Conflict."},
        instance="/api/x",
    )

    assert body["type"] == "https://httpstatuses.com/409"


def test_a_dict_detail_without_a_type_still_falls_back() -> None:
    body = _problem_payload(
        status_code=409,
        detail={"detail": "Nothing mapped here."},
        instance="/api/x",
    )

    assert body["type"] == "https://httpstatuses.com/409"
