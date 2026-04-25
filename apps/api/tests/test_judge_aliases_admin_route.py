"""Slice D follow-up — admin GET /api/courts/judges/aliases route.

Smoke-tests the read-only admin listing wired in
``apps/api/src/caseops_api/api/routes/courts.py`` for the
``/app/admin/judge-aliases`` page.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.db.models import Judge
from caseops_api.services.judge_aliases import backfill_canonical_aliases
from tests.test_auth_company import auth_headers, bootstrap_company


def test_alias_listing_returns_aliases_per_judge(client: TestClient) -> None:
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    with get_session_factory()() as s:
        s.add(
            Judge(
                court_id="supreme-court-india",
                full_name="Test Alias Judge",
                honorific="Justice",
                current_position="Judge of the SC",
                is_active=True,
            ),
        )
        s.commit()
        backfill_canonical_aliases(s)

    resp = client.get(
        "/api/courts/judges/aliases", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["judge_count"] >= 1
    assert body["alias_count"] >= 4  # canonical generator emits ≥ 4
    judge_names = {a["judge_full_name"] for a in body["aliases"]}
    assert "Test Alias Judge" in judge_names
    sample = next(
        a for a in body["aliases"]
        if a["judge_full_name"] == "Test Alias Judge"
    )
    assert sample["court_short_name"] == "SC"
    assert sample["source"] == "auto_extract"
    assert sample["created_at"]  # ISO timestamp present


def test_alias_listing_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/courts/judges/aliases")
    assert resp.status_code == 401
    assert resp.json()["type"] == "missing_bearer_token"
