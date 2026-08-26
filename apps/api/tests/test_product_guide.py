from __future__ import annotations

from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import AuditEvent, CompanyMembership, CustomRole, MembershipRole
from caseops_api.db.session import get_session_factory
from caseops_api.services.product_guide import search_product_guide
from tests.test_auth_company import auth_headers, bootstrap_company


def test_public_catalog_is_versioned_bounded_and_does_not_publish_commands(
    client: TestClient,
) -> None:
    response = client.get("/api/product-guide/catalog")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_version"] == "2026.08.26.1"
    assert body["canonical_path"] == "/guide"
    assert len(body["catalog_fingerprint"]) == 64
    assert len(body["sections"]) == 27
    assert body["sections"][0]["href"] == "/guide#getting-started"
    assert body["sections"][16]["id"] == "judge-mapping"
    assert "commands" not in body


def test_authenticated_search_ranks_navigation_and_reports_stale_clients(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])

    response = client.get(
        "/api/product-guide/search",
        headers=auth_headers(token),
        params={
            "q": "deadline control",
            "limit": 3,
            "client_version": "2026.08.22.1",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "matched"
    assert body["version_status"] == "stale"
    assert body["content_version"] == "2026.08.26.1"
    assert len(body["results"]) <= 3
    assert body["results"][0] == {
        "kind": "command",
        "id": "deadline-control",
        "title": "Deadline control",
        "summary": "Review IP deadlines, responsibility, acknowledgement, and escalation.",
        "href": "/app/ip/docket",
        "required_capabilities": ["ip:read"],
    }


def test_search_uses_effective_custom_role_and_sanitizes_denied_commands(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    membership_id = str(bootstrap["membership"]["id"])
    company_id = str(bootstrap["company"]["id"])
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        role = CustomRole(
            company_id=company_id,
            name="Client list only",
            slug="client-list-only",
            base_role=MembershipRole.VIEWER,
            permissions_json=["clients:view"],
            is_system=False,
            is_active=True,
            created_by_membership_id=membership_id,
            updated_by_membership_id=membership_id,
        )
        session.add(role)
        session.flush()
        membership.role = MembershipRole.VIEWER
        membership.custom_role_id = role.id
        session.commit()

    allowed = client.get(
        "/api/product-guide/search",
        headers=auth_headers(token),
        params={"q": "clients"},
    )
    assert allowed.status_code == 200, allowed.text
    assert any(result["id"] == "clients" for result in allowed.json()["results"])

    denied = client.get(
        "/api/product-guide/search",
        headers=auth_headers(token),
        params={"q": "microsoft 365"},
    )
    assert denied.status_code == 200, denied.text
    body = denied.json()
    assert body["status"] == "permission_required"
    assert body["results"] == []
    assert body["permission"] == {
        "required_capabilities": ["workspace:admin"],
        "message": "This task needs additional workspace access.",
    }


def test_search_abstains_without_writes_and_rejects_unbounded_inputs(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    with get_session_factory()() as session:
        before = session.scalar(select(func.count(AuditEvent.id)))

    response = client.get(
        "/api/product-guide/search",
        headers=auth_headers(token),
        params={"q": "xylophone nebula quasar"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "no_match"
    assert response.json()["results"] == []
    assert response.json()["suggested_queries"]

    punctuation = client.get(
        "/api/product-guide/search",
        headers=auth_headers(token),
        params={"q": "---"},
    )
    assert punctuation.status_code == 200
    assert punctuation.json()["status"] == "no_match"
    assert punctuation.json()["results"] == []

    too_short = client.get(
        "/api/product-guide/search",
        headers=auth_headers(token),
        params={"q": "x"},
    )
    too_many = client.get(
        "/api/product-guide/search",
        headers=auth_headers(token),
        params={"q": "matters", "limit": 11},
    )
    assert too_short.status_code == 422
    assert too_many.status_code == 422
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == before


def test_in_memory_catalog_search_has_bounded_work() -> None:
    started = perf_counter()
    for _ in range(500):
        response = search_product_guide(
            "trademark opposition deadline",
            capabilities={"ip:read"},
            limit=10,
        )
        assert len(response["results"]) <= 10
    assert perf_counter() - started < 1.5
