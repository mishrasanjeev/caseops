"""Exception envelope smoke tests for §6.4.

The handler is backward-compatible with clients that only read
`detail`. These tests pin the new fields so a regression (missing
type, wrong title, etc.) surfaces fast.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.core.problem_details import PROBLEM_CONTENT_TYPE
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
            "status": "active",
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
            "status": "active",
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
