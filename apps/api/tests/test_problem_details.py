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
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

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
    # Detail is a human-readable join that names each field; errors[]
    # preserves the raw shape, request source included.
    assert isinstance(body["detail"], str) and len(body["detail"]) > 0
    assert "Forum level: Input should be" in body["detail"]
    assert not body["detail"].lower().startswith("body")
    assert isinstance(body["errors"], list) and body["errors"]
    assert {tuple(error["loc"])[:1] for error in body["errors"]} == {("body",)}
    assert ["body", "forum_level"] in [error["loc"] for error in body["errors"]]
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


class _DatabaseError(Exception):
    def __init__(self, sqlstate: str | None = None) -> None:
        self.sqlstate = sqlstate


def test_database_statement_timeout_is_safe_actionable_gateway_timeout() -> None:
    application = FastAPI()
    register_problem_handlers(application)

    @application.get("/database-timeout")
    async def _database_timeout() -> None:
        raise OperationalError("private SQL", {}, _DatabaseError("57014"))

    with TestClient(application, raise_server_exceptions=False) as isolated_client:
        response = isolated_client.get("/database-timeout")

    assert response.status_code == 504
    assert response.json()["type"] == "database_statement_timeout"
    assert "private SQL" not in response.text


def test_database_lock_and_pool_timeouts_are_retryable_without_details() -> None:
    application = FastAPI()
    register_problem_handlers(application)

    @application.get("/database-lock")
    async def _database_lock() -> None:
        raise OperationalError("private lock details", {}, _DatabaseError("55P03"))

    @application.get("/database-pool")
    async def _database_pool() -> None:
        raise SQLAlchemyTimeoutError("private pool details")

    @application.get("/database-connection")
    async def _database_connection() -> None:
        raise OperationalError("private connection details", {}, _DatabaseError())

    with TestClient(application, raise_server_exceptions=False) as isolated_client:
        lock_response = isolated_client.get("/database-lock")
        pool_response = isolated_client.get("/database-pool")
        connection_response = isolated_client.get("/database-connection")

    assert lock_response.status_code == 503
    assert lock_response.headers["Retry-After"] == "1"
    assert lock_response.json()["type"] == "database_lock_timeout"
    assert pool_response.status_code == 503
    assert pool_response.headers["Retry-After"] == "1"
    assert pool_response.json()["type"] == "database_capacity_exhausted"
    assert connection_response.status_code == 503
    assert connection_response.json()["type"] == "database_temporarily_unavailable"
    assert "private" not in lock_response.text + pool_response.text + connection_response.text


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


class _Publication(BaseModel):
    class_numbers: list[int] = Field(min_length=1)
    goods_services: dict[str, list[str]] = Field(default_factory=dict)
    source_url: str

    @model_validator(mode="after")
    def _scope_within_classes(self) -> _Publication:
        if self.class_numbers and str(self.class_numbers[0]) == "30":
            raise ValueError("Goods/services scope must belong to a published class.")
        return self


class _JournalIngest(BaseModel):
    publications: list[_Publication] = Field(min_length=1)


def _journal_client() -> TestClient:
    application = FastAPI()
    register_problem_handlers(application)

    @application.post("/journal")
    async def _ingest(payload: _JournalIngest) -> dict[str, int]:
        return {"count": len(payload.publications)}

    @application.get("/dockets")
    async def _dockets(cursor_position: int) -> dict[str, int]:
        return {"cursor_position": cursor_position}

    return TestClient(application)


def test_422_detail_names_each_field_without_request_source_or_index() -> None:
    # Ram 2026-10-30 (BUG-014): "List should have at least 1 item after
    # validation, not 0; Input should be a valid list" named no field, so the
    # tester blamed the evidence box. Each line now names its field.
    with _journal_client() as isolated_client:
        response = isolated_client.post(
            "/journal",
            json={
                "publications": [
                    {
                        "class_numbers": [],
                        "goods_services": {"45": "Confidential legal services"},
                        "source_url": "https://search.ipindia.gov.in/journal",
                    }
                ]
            },
        )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == (
        "Publications › Class numbers: List should have at least 1 item after "
        "validation, not 0; Publications › Goods services › 45: Input should "
        "be a valid list"
    )
    # errors[] is unchanged: raw loc, msg and type, and never the input value.
    assert body["errors"] == [
        {
            "loc": ["body", "publications", 0, "class_numbers"],
            "msg": "List should have at least 1 item after validation, not 0",
            "type": "too_short",
        },
        {
            "loc": ["body", "publications", 0, "goods_services", "45"],
            "msg": "Input should be a valid list",
            "type": "list_type",
        },
    ]
    assert "Confidential legal services" not in response.text
    assert body["type"] == "https://httpstatuses.com/422"


def test_422_detail_drops_the_pydantic_value_error_prefix() -> None:
    with _journal_client() as isolated_client:
        response = isolated_client.post(
            "/journal",
            json={"publications": [{"class_numbers": [30], "source_url": "https://x.test"}]},
        )
        query_error = isolated_client.get("/dockets", params={"cursor_position": "first"})

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Publications: Goods/services scope must belong to a published class."
    )
    assert "Value error" not in response.json()["detail"]
    # The raw machine message is left untouched for clients that parse it.
    assert response.json()["errors"][0]["msg"].startswith("Value error, ")
    assert query_error.status_code == 422
    assert query_error.json()["detail"].startswith(
        "Cursor position: Input should be a valid integer"
    )
    assert "first" not in query_error.json()["detail"]


def test_422_detail_humanizes_acronyms_and_keeps_bare_messages() -> None:
    body = _problem_payload(
        status_code=422,
        detail=[
            {"loc": ["body", "source_url"], "msg": "Field required", "type": "missing"},
            {"loc": ["body", "matter_id"], "msg": "Field required", "type": "missing"},
            {
                "loc": ["body", "payload", "function-after[check(), str]"],
                "msg": "Assertion failed, Payload must be signed.",
                "type": "assertion_error",
            },
            {
                "loc": ["body"],
                "msg": "Value error, Choose exactly one target.",
                "type": "value_error",
            },
            "A plain string problem",
        ],
        instance="/api/x",
    )

    assert body["detail"] == (
        "Source URL: Field required; Matter ID: Field required; "
        "Payload: Payload must be signed.; Choose exactly one target.; A plain string problem"
    )


def test_422_field_names_never_change_the_resolved_problem_type() -> None:
    # PROBLEM_TYPE_MAP matches 422 + "verified citations"; a field whose name
    # contains that phrase must not turn a plain validation error into it.
    body = _problem_payload(
        status_code=422,
        detail=[
            {"loc": ["body", "verified_citations"], "msg": "Field required", "type": "missing"}
        ],
        instance="/api/x",
    )

    assert body["detail"] == "Verified citations: Field required"
    assert body["type"] == "https://httpstatuses.com/422"
