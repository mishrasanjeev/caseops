from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Court, Matter
from caseops_api.db.session import get_session_factory


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, slug: str, email_prefix: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} Firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug.title()} Owner",
            "owner_email": f"{email_prefix}@{slug}.in",
            "owner_password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _invite_member(
    client: TestClient,
    *,
    owner_token: str,
    company_slug: str,
    email: str,
    role: str = "member",
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": f"Member {email.split('@')[0]}",
            "email": email,
            "role": role,
            "password": "MemberPass123!",
        },
    )
    assert response.status_code == 200, response.text
    membership_id = response.json()["membership_id"]
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": company_slug,
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return membership_id, str(login.json()["access_token"])


def _create_matter(
    client: TestClient,
    token: str,
    code: str,
    *,
    title: str | None = None,
    client_name: str | None = None,
    opposing_party: str | None = None,
    status: str = "active",
    claim_amount_minor: int | None = None,
    forum_level: str = "high_court",
    court_name: str | None = None,
    next_hearing_on: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": title or f"Matter {code}",
        "matter_code": code,
        "client_name": client_name,
        "opposing_party": opposing_party,
        "practice_area": "Commercial",
        "forum_level": forum_level,
        "court_name": court_name,
        "status": status,
        "next_hearing_on": next_hearing_on,
        "claim_amount_minor": claim_amount_minor,
        "claim_currency": "INR",
        "claim_amount_notes": "Initial pleadings estimate"
        if claim_amount_minor is not None else None,
    }
    response = client.post("/api/matters/", headers=_auth(token), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _seed_court_and_attach(matter_id: str, *, forum_level: str = "high_court") -> str:
    court_id = str(uuid4())
    factory = get_session_factory()
    with factory() as session:
        court = Court(
            id=court_id,
            name=f"LW S1 Court {uuid4()}",
            short_name="LW S1",
            forum_level=forum_level,
            jurisdiction="Test",
            seat_city="Delhi",
            is_active=True,
        )
        session.add(court)
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.court_id = court.id
        session.add(matter)
        session.commit()
    return court_id


def _set_matter_created_at(matter_id: str, created_at: datetime) -> None:
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.created_at = created_at
        session.add(matter)
        session.commit()


def _set_matter_updated_at(matter_id: str, updated_at: datetime) -> None:
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.updated_at = updated_at
        session.add(matter)
        session.commit()


def _audit_actions(company_id: str) -> list[AuditEvent]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc())
            )
        )


def test_lw_s1_claim_filters_tags_bulk_and_audit(client: TestClient) -> None:
    boot = _bootstrap(client, "lw-alpha", "owner")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    high = _create_matter(
        client,
        token,
        "LW-CLAIM-1",
        title="Acme Industries v Beta Projects",
        client_name="Acme Industries",
        opposing_party="Beta Projects",
        claim_amount_minor=50_000_000,
    )
    low = _create_matter(
        client,
        token,
        "LW-CLAIM-2",
        title="Zenith advisory",
        client_name="Zenith Holdings",
        status="intake",
        claim_amount_minor=1_000_000,
    )

    tag_response = client.post(
        "/api/matter-tags/",
        headers=_auth(token),
        json={"name": "Urgent", "color_key": "amber"},
    )
    assert tag_response.status_code == 201, tag_response.text
    tag = tag_response.json()

    assignment = client.post(
        f"/api/matters/{high['id']}/tags",
        headers=_auth(token),
        json={"tag_id": tag["id"], "source": "manual"},
    )
    assert assignment.status_code == 200, assignment.text

    filtered = client.get(
        "/api/matters/",
        headers=_auth(token),
        params={
            "q": "Beta",
            "tag": "urgent",
            "min_claim_amount_minor": 10_000_000,
            "max_claim_amount_minor": 60_000_000,
        },
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()["matters"]
    assert [row["matter_code"] for row in rows] == ["LW-CLAIM-1"]
    assert rows[0]["claim_amount_minor"] == 50_000_000
    assert rows[0]["tags"][0]["slug"] == "urgent"
    assert rows[0]["has_stay"] is False

    suggestions = client.get(
        f"/api/matters/{high['id']}/tag-suggestions",
        headers=_auth(token),
    )
    assert suggestions.status_code == 200, suggestions.text
    suggestion_slugs = {item["slug"] for item in suggestions.json()["suggestions"]}
    assert {"acme-industries", "beta-projects"}.issubset(suggestion_slugs)

    bulk = client.post(
        "/api/matters/bulk-tags",
        headers=_auth(token),
        json={"matter_ids": [high["id"], low["id"]], "tag_id": tag["id"]},
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["assigned_count"] == 1
    assert bulk.json()["skipped_count"] == 1

    patched = client.patch(
        f"/api/matters/{high['id']}",
        headers=_auth(token),
        json={"claim_amount_minor": 75_000_000, "claim_amount_notes": "Amended claim"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["claim_amount_minor"] == 75_000_000

    events = _audit_actions(company_id)
    actions = [event.action for event in events]
    assert "matter_tag.created" in actions
    assert "matter_tag.assigned" in actions
    assert "matter_tag.bulk_assigned" in actions
    assert "matter.claim_amount.updated" in actions
    claim_event = next(event for event in events if event.action == "matter.claim_amount.updated")
    metadata = json.loads(claim_event.metadata_json or "{}")
    assert metadata["before"]["claim_amount_minor"] == 50_000_000
    assert metadata["after"]["claim_amount_minor"] == 75_000_000

    tag_update = client.patch(
        f"/api/matter-tags/{tag['id']}",
        headers=_auth(token),
        json={"name": "Urgent Updated", "color_key": "red"},
    )
    assert tag_update.status_code == 200, tag_update.text
    unassign = client.delete(
        f"/api/matters/{high['id']}/tags/{tag['id']}",
        headers=_auth(token),
    )
    assert unassign.status_code == 204, unassign.text
    delete_tag = client.delete(
        f"/api/matter-tags/{tag['id']}",
        headers=_auth(token),
    )
    assert delete_tag.status_code == 204, delete_tag.text

    actions = [event.action for event in _audit_actions(company_id)]
    assert "matter_tag.updated" in actions
    assert "matter_tag.unassigned" in actions
    assert "matter_tag.deleted" in actions


def test_lw_s1_tags_are_tenant_scoped(client: TestClient) -> None:
    tenant_a = _bootstrap(client, "lw-tenant-a", "owner-a")
    tenant_b = _bootstrap(client, "lw-tenant-b", "owner-b")
    token_a = str(tenant_a["access_token"])
    token_b = str(tenant_b["access_token"])
    matter_a = _create_matter(client, token_a, "TENANT-A")
    matter_b = _create_matter(client, token_b, "TENANT-B")

    tag_a = client.post(
        "/api/matter-tags/",
        headers=_auth(token_a),
        json={"name": "Tenant A Only", "color_key": "blue"},
    ).json()

    list_b = client.get("/api/matter-tags/", headers=_auth(token_b))
    assert list_b.status_code == 200
    assert list_b.json()["tags"] == []

    cross_assign = client.post(
        f"/api/matters/{matter_b['id']}/tags",
        headers=_auth(token_b),
        json={"tag_id": tag_a["id"]},
    )
    assert cross_assign.status_code == 404

    cross_bulk = client.post(
        "/api/matters/bulk-tags",
        headers=_auth(token_a),
        json={"matter_ids": [matter_a["id"], matter_b["id"]], "tag_id": tag_a["id"]},
    )
    assert cross_bulk.status_code == 404

    list_a = client.get(
        "/api/matters/",
        headers=_auth(token_a),
        params={"tag": "tenant-a-only"},
    )
    assert list_a.status_code == 200
    assert list_a.json()["matters"] == []


def test_lw_s1_tag_listing_respects_matter_access_boundaries(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-acl-tags", "owner")
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="member@lw-acl-tags.in",
    )
    _, admin_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="admin@lw-acl-tags.in",
        role="admin",
    )
    open_matter = _create_matter(
        client,
        owner_token,
        "ACL-TAG-OPEN",
        title="Open matter",
        client_name="Restricted Mirror",
    )
    restricted_matter = _create_matter(
        client,
        owner_token,
        "ACL-TAG-RESTRICTED",
        title="Restricted matter",
    )
    walled_matter = _create_matter(
        client,
        owner_token,
        "ACL-TAG-WALLED",
        title="Walled matter",
    )

    visible_tag = client.post(
        "/api/matter-tags/",
        headers=_auth(owner_token),
        json={"name": "Visible Shared"},
    ).json()
    restricted_tag = client.post(
        "/api/matter-tags/",
        headers=_auth(owner_token),
        json={"name": "Restricted Mirror"},
    ).json()
    walled_tag = client.post(
        "/api/matter-tags/",
        headers=_auth(owner_token),
        json={"name": "Walled Secret"},
    ).json()
    for matter, tag in (
        (open_matter, visible_tag),
        (restricted_matter, restricted_tag),
        (walled_matter, walled_tag),
    ):
        response = client.post(
            f"/api/matters/{matter['id']}/tags",
            headers=_auth(owner_token),
            json={"tag_id": tag["id"]},
        )
        assert response.status_code == 200, response.text

    restricted = client.post(
        f"/api/matters/{restricted_matter['id']}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    wall = client.post(
        f"/api/matters/{walled_matter['id']}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text

    owner_tags = client.get("/api/matter-tags/", headers=_auth(owner_token))
    assert owner_tags.status_code == 200
    assert {tag["slug"] for tag in owner_tags.json()["tags"]}.issuperset(
        {"visible-shared", "restricted-mirror", "walled-secret"}
    )

    admin_tags = client.get("/api/matter-tags/", headers=_auth(admin_token))
    assert admin_tags.status_code == 200
    assert {tag["slug"] for tag in admin_tags.json()["tags"]}.issuperset(
        {"visible-shared", "restricted-mirror", "walled-secret"}
    )

    member_tags = client.get("/api/matter-tags/", headers=_auth(member_token))
    assert member_tags.status_code == 200
    assert [tag["slug"] for tag in member_tags.json()["tags"]] == ["visible-shared"]

    member_create = client.post(
        "/api/matter-tags/",
        headers=_auth(member_token),
        json={"name": "Member Catalog Probe"},
    )
    assert member_create.status_code == 403, member_create.text

    suggestions = client.get(
        f"/api/matters/{open_matter['id']}/tag-suggestions",
        headers=_auth(member_token),
    )
    assert suggestions.status_code == 200, suggestions.text
    mirror = next(
        item
        for item in suggestions.json()["suggestions"]
        if item["slug"] == "restricted-mirror"
    )
    assert mirror["existing_tag_id"] is None

    hidden_bulk = client.post(
        "/api/matters/bulk-tags",
        headers=_auth(member_token),
        json={"matter_ids": [open_matter["id"]], "tag_id": restricted_tag["id"]},
    )
    assert hidden_bulk.status_code == 404, hidden_bulk.text

    hidden_filter = client.get(
        "/api/matters/",
        headers=_auth(member_token),
        params={"tag": "restricted-mirror"},
    )
    assert hidden_filter.status_code == 200, hidden_filter.text
    assert hidden_filter.json()["matters"] == []


def test_lw_s1_claim_currency_validation(client: TestClient) -> None:
    boot = _bootstrap(client, "lw-currency", "owner")
    token = str(boot["access_token"])

    lower = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": "Currency normalisation",
            "matter_code": "CUR-LOWER",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
            "claim_amount_minor": 1_000,
            "claim_currency": "usd",
        },
    )
    assert lower.status_code == 200, lower.text
    matter = lower.json()
    assert matter["claim_currency"] == "USD"

    null_patch = client.patch(
        f"/api/matters/{matter['id']}",
        headers=_auth(token),
        json={"claim_currency": None},
    )
    assert null_patch.status_code == 422, null_patch.text

    malformed_create = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": "Bad currency",
            "matter_code": "CUR-BAD",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
            "claim_amount_minor": 1_000,
            "claim_currency": "12$",
        },
    )
    assert malformed_create.status_code == 422, malformed_create.text

    patch = client.patch(
        f"/api/matters/{matter['id']}",
        headers=_auth(token),
        json={"claim_currency": "inr"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["claim_currency"] == "INR"


def test_lw_s1_matter_filters_and_filtered_pagination(client: TestClient) -> None:
    boot = _bootstrap(client, "lw-filters", "owner")
    token = str(boot["access_token"])
    alpha = _create_matter(
        client,
        token,
        "FLT-ALPHA",
        title="Alpha injunction",
        client_name="Acme Industries",
        opposing_party="Beta Projects",
        status="active",
        forum_level="high_court",
        court_name="Delhi High Court",
        next_hearing_on="2026-05-10",
        claim_amount_minor=5_000_000,
    )
    beta = _create_matter(
        client,
        token,
        "FLT-BETA",
        title="Beta advisory",
        client_name="Zenith Holdings",
        opposing_party="Gamma LLP",
        status="intake",
        forum_level="tribunal",
        court_name="NCLT",
        next_hearing_on="2026-06-20",
        claim_amount_minor=2_500_000,
    )
    page_a = _create_matter(
        client,
        token,
        "FLT-PAGE-A",
        title="Page A",
        client_name="Page Client",
        opposing_party="Page Opponent",
        status="active",
        claim_amount_minor=100,
    )
    page_b = _create_matter(
        client,
        token,
        "FLT-PAGE-B",
        title="Page B",
        client_name="Page Client",
        opposing_party="Page Opponent",
        status="active",
        claim_amount_minor=200,
    )
    court_id = _seed_court_and_attach(str(alpha["id"]))
    _set_matter_created_at(str(alpha["id"]), datetime(2026, 5, 1, 9, tzinfo=UTC))
    _set_matter_created_at(str(beta["id"]), datetime(2026, 5, 3, 9, tzinfo=UTC))
    _set_matter_updated_at(str(page_a["id"]), datetime(2026, 5, 4, 10, tzinfo=UTC))
    _set_matter_updated_at(str(page_b["id"]), datetime(2026, 5, 4, 9, tzinfo=UTC))

    cases = [
        ({"client_name": "Acme"}, ["FLT-ALPHA"]),
        ({"opposing_party": "Gamma"}, ["FLT-BETA"]),
        ({"forum_level": "tribunal"}, ["FLT-BETA"]),
        ({"court_id": court_id}, ["FLT-ALPHA"]),
        ({"status": "intake"}, ["FLT-BETA"]),
        ({"created_from": "2026-05-01", "created_to": "2026-05-01"}, ["FLT-ALPHA"]),
        (
            {"next_hearing_from": "2026-06-01", "next_hearing_to": "2026-06-30"},
            ["FLT-BETA"],
        ),
    ]
    for params, expected_codes in cases:
        response = client.get("/api/matters/", headers=_auth(token), params=params)
        assert response.status_code == 200, response.text
        assert [row["matter_code"] for row in response.json()["matters"]] == expected_codes

    invalid_range = client.get(
        "/api/matters/",
        headers=_auth(token),
        params={"min_claim_amount_minor": 200, "max_claim_amount_minor": 100},
    )
    assert invalid_range.status_code == 400, invalid_range.text

    page1 = client.get(
        "/api/matters/",
        headers=_auth(token),
        params={"client_name": "Page Client", "limit": 1},
    )
    assert page1.status_code == 200, page1.text
    assert [row["matter_code"] for row in page1.json()["matters"]] == ["FLT-PAGE-A"]
    assert page1.json()["next_cursor"]

    page2 = client.get(
        "/api/matters/",
        headers=_auth(token),
        params={
            "client_name": "Page Client",
            "limit": 1,
            "cursor": page1.json()["next_cursor"],
        },
    )
    assert page2.status_code == 200, page2.text
    assert [row["matter_code"] for row in page2.json()["matters"]] == ["FLT-PAGE-B"]
    assert page2.json()["next_cursor"] is None
