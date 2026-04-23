"""Phase B / J12 / M11 — communications log slice 1.

Slice 1 contract:

- POST /api/matters/{id}/communications creates a log row.
- GET  /api/matters/{id}/communications returns rows newest-first.
- Tenant isolation: company B cannot read or write company A's
  matter communications. (The most important test in this file.)
- Capability gate: a viewer can READ but cannot WRITE — without this
  the role grid drifts from the dependencies.py truth.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, headers: dict[str, str], code: str) -> str:
    resp = client.post(
        "/api/matters",
        headers=headers,
        json={
            "matter_code": code,
            "title": f"Matter {code}",
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_create_then_list_communication(client: TestClient) -> None:
    """Round-trip — POST a manual log, GET the list, see it back."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "M11-001")

    resp = client.post(
        f"/api/matters/{matter_id}/communications",
        headers=headers,
        json={
            "channel": "phone",
            "direction": "outbound",
            "subject": "Status call",
            "body": "Called client at 3pm — confirmed Friday hearing.",
            "recipient_name": "Hari Gupta",
        },
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["channel"] == "phone"
    assert created["status"] == "logged"
    assert created["matter_id"] == matter_id
    # created_by_membership_id must be populated so the audit trail
    # ties back to the user — without it we lose the "who logged it"
    # column on the Communications tab.
    assert created["created_by_membership_id"] is not None
    assert created["created_at"] is not None

    listing = client.get(
        f"/api/matters/{matter_id}/communications", headers=headers,
    )
    assert listing.status_code == 200
    body = listing.json()
    assert body["matter_id"] == matter_id
    assert len(body["communications"]) == 1
    assert body["communications"][0]["body"].startswith("Called client")


def test_list_returns_newest_first(client: TestClient) -> None:
    """Lawyers expect "what's new" at the top of the list. The
    service orders by occurred_at DESC; assert it explicitly so a
    stray ASC change cannot regress unnoticed."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "M11-002")

    base = datetime.now(UTC)
    for i, label in enumerate(["oldest", "middle", "newest"]):
        client.post(
            f"/api/matters/{matter_id}/communications",
            headers=headers,
            json={
                "channel": "note",
                "body": label,
                "occurred_at": (base + timedelta(hours=i)).isoformat(),
            },
        )

    listing = client.get(
        f"/api/matters/{matter_id}/communications", headers=headers,
    )
    assert listing.status_code == 200
    bodies = [c["body"] for c in listing.json()["communications"]]
    assert bodies == ["newest", "middle", "oldest"]


def test_communications_do_not_leak_across_tenants(client: TestClient) -> None:
    """Tenant A logs a call. Tenant B requesting the same matter id
    must 404 — never reveal that the matter exists, never return any
    of A's rows. This is the core security invariant for M11."""
    company_a = bootstrap_company(client)
    headers_a = auth_headers(str(company_a["access_token"]))
    matter_a = _create_matter(client, headers_a, "TENANT-A")
    client.post(
        f"/api/matters/{matter_a}/communications",
        headers=headers_a,
        json={"channel": "email", "body": "Tenant A privileged note"},
    )
    # EG-001 (cookie wins over bearer) — clear before the second
    # bootstrap so headers_a / headers_b actually act as their
    # respective tenants.
    client.cookies.clear()

    resp_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other LLP",
            "company_slug": "other-comms",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-comms.example",
            "owner_password": "OtherStrong!234",
        },
    )
    assert resp_b.status_code == 200
    headers_b = auth_headers(str(resp_b.json()["access_token"]))
    client.cookies.clear()

    # Tenant B GET on Tenant A's matter — 404, never 200, never 403.
    leak_get = client.get(
        f"/api/matters/{matter_a}/communications", headers=headers_b,
    )
    assert leak_get.status_code == 404
    # And tenant B can't write into tenant A's matter either.
    leak_post = client.post(
        f"/api/matters/{matter_a}/communications",
        headers=headers_b,
        json={"channel": "note", "body": "should not land"},
    )
    assert leak_post.status_code == 404


def test_create_requires_communications_write_capability(
    client: TestClient,
) -> None:
    """A viewer-role user can READ comms but POSTing must 403. This
    enforces the capability table mirror between dependencies.py
    (truth) and capabilities.ts (UI hint)."""
    # Bootstrap an owner so we have a viewer to invite.
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    matter_id = _create_matter(client, auth_headers(owner_token), "M11-VIEWER")

    # Invite a viewer. The exact invite shape depends on the existing
    # admin endpoint; we read the demo memberships table directly via
    # an endpoint that we know exists. For slice 1 we'll instead
    # downgrade the bootstrapped owner's membership row directly via
    # the SQLAlchemy session to keep the test surface tight.
    from sqlalchemy import update

    from caseops_api.db.models import CompanyMembership, MembershipRole
    from caseops_api.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        session.execute(
            update(CompanyMembership)
            .where(CompanyMembership.id == bootstrap["membership"]["id"])
            .values(role=MembershipRole.VIEWER)
        )
        session.commit()

    # The same owner_token still resolves to the same membership but
    # the role is now VIEWER. Read should still work, write should
    # 403.
    read = client.get(
        f"/api/matters/{matter_id}/communications",
        headers=auth_headers(owner_token),
    )
    assert read.status_code == 200

    write = client.post(
        f"/api/matters/{matter_id}/communications",
        headers=auth_headers(owner_token),
        json={"channel": "note", "body": "viewer attempt — should 403"},
    )
    assert write.status_code == 403
