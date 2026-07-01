from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers


def _bootstrap(client: TestClient, slug: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"Audit {slug}",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Audit Owner",
            "owner_email": f"owner-{slug}@example.com",
            "owner_password": "AuditPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login(client: TestClient, email: str, slug: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "MemberPass123!",
            "company_slug": slug,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _create_matter(
    client: TestClient,
    token: str,
    *,
    code: str,
    title: str | None = None,
) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": title or f"Audit matter {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _create_member(
    client: TestClient,
    owner_token: str,
    *,
    slug: str,
    email: str,
    role: str = "member",
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Audit Member",
            "email": email,
            "password": "MemberPass123!",
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["membership_id"]), _login(client, email, slug)


def _seed_audit_event(
    *,
    company_id: str,
    matter_id: str,
    action: str,
    actor_membership_id: str | None = None,
    actor_label: str | None = "Audit Actor",
    target_type: str = "matter",
    target_id: str | None = None,
    metadata: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        event = AuditEvent(
            company_id=company_id,
            actor_type="human",
            actor_membership_id=actor_membership_id,
            actor_label=actor_label,
            matter_id=matter_id,
            action=action,
            target_type=target_type,
            target_id=target_id or matter_id,
            result="success",
            metadata_json=json.dumps(metadata or {}),
            created_at=created_at or datetime.now(UTC),
        )
        session.add(event)
        session.commit()
        return event.id


def test_matter_audit_filters_and_pagination_are_stable(client: TestClient) -> None:
    boot = _bootstrap(client, "lw-s11-audit-filters")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    actor_id = str(boot["membership"]["id"])
    matter_id = _create_matter(client, token, code="LW-AUD-001")
    now = datetime.now(UTC)

    _seed_audit_event(
        company_id=company_id,
        matter_id=matter_id,
        action="matter.claim.updated",
        actor_membership_id=actor_id,
        actor_label="Priya Counsel",
        metadata={"field": "claim_amount", "keyword": "damages"},
        created_at=now - timedelta(days=2),
    )
    _seed_audit_event(
        company_id=company_id,
        matter_id=matter_id,
        action="matter.tags.assigned",
        actor_membership_id=actor_id,
        actor_label="Sanjay Owner",
        metadata={"tag": "urgent"},
        created_at=now - timedelta(days=1),
    )
    _seed_audit_event(
        company_id=company_id,
        matter_id=matter_id,
        action="matter_strategy.created",
        actor_membership_id=actor_id,
        actor_label="Priya Counsel",
        metadata={"title": "Settlement posture"},
        created_at=now,
    )

    by_action = client.get(
        f"/api/matters/{matter_id}/audit-events",
        headers=auth_headers(token),
        params={"action": "matter.tags.assigned"},
    )
    assert by_action.status_code == 200, by_action.text
    assert by_action.json()["total"] == 1
    assert by_action.json()["events"][0]["action"] == "matter.tags.assigned"

    by_actor = client.get(
        f"/api/matters/{matter_id}/audit-events",
        headers=auth_headers(token),
        params={"actor": "Priya"},
    )
    assert by_actor.status_code == 200, by_actor.text
    assert {event["action"] for event in by_actor.json()["events"]} == {
        "matter_strategy.created",
        "matter.claim.updated",
    }

    by_keyword = client.get(
        f"/api/matters/{matter_id}/audit-events",
        headers=auth_headers(token),
        params={"keyword": "damages"},
    )
    assert by_keyword.status_code == 200, by_keyword.text
    assert by_keyword.json()["total"] == 1
    assert by_keyword.json()["events"][0]["metadata"]["keyword"] == "damages"

    by_date = client.get(
        f"/api/matters/{matter_id}/audit-events",
        headers=auth_headers(token),
        params={
            "since": (now - timedelta(days=1, minutes=5)).isoformat(),
            "until": (now + timedelta(minutes=5)).isoformat(),
        },
    )
    assert by_date.status_code == 200, by_date.text
    date_actions = [event["action"] for event in by_date.json()["events"]]
    assert date_actions.index("matter_strategy.created") < date_actions.index(
        "matter.tags.assigned"
    )

    page = client.get(
        f"/api/matters/{matter_id}/audit-events",
        headers=auth_headers(token),
        params={"limit": 1, "offset": 1},
    )
    assert page.status_code == 200, page.text
    assert page.json()["limit"] == 1
    assert page.json()["offset"] == 1
    assert len(page.json()["events"]) == 1


def test_matter_audit_export_is_scoped_to_current_matter_and_tenant(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, "lw-s11-audit-export-a")
    token_a = str(boot_a["access_token"])
    company_a = str(boot_a["company"]["id"])
    matter_a = _create_matter(client, token_a, code="LW-AUD-A")
    matter_other = _create_matter(client, token_a, code="LW-AUD-OTHER")
    event_id = _seed_audit_event(
        company_id=company_a,
        matter_id=matter_a,
        action="matter_strategy.created",
        metadata={"title": "Exported plan"},
    )
    formula_label = '=HYPERLINK("https://evil.example")'
    _seed_audit_event(
        company_id=company_a,
        matter_id=matter_a,
        action="matter.formula_probe",
        actor_label=formula_label,
        metadata={"title": "Formula actor"},
    )
    _seed_audit_event(
        company_id=company_a,
        matter_id=matter_other,
        action="matter_strategy.created",
        metadata={"title": "Other matter"},
    )

    jsonl = client.get(
        f"/api/matters/{matter_a}/audit-events/export",
        headers=auth_headers(token_a),
    )
    assert jsonl.status_code == 200, jsonl.text
    assert jsonl.headers["content-type"].startswith("application/x-ndjson")
    rows = [json.loads(line) for line in jsonl.text.splitlines() if line]
    assert any(row["id"] == event_id for row in rows)
    assert all(row["company_id"] == company_a for row in rows)
    assert all(row["matter_id"] == matter_a for row in rows)

    csv_resp = client.get(
        f"/api/matters/{matter_a}/audit-events/export",
        headers=auth_headers(token_a),
        params={"format": "csv"},
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert csv_resp.text.splitlines()[0].startswith("id,created_at,company_id")
    assert "Exported plan" in csv_resp.text
    assert "Other matter" not in csv_resp.text
    csv_rows = list(csv.DictReader(io.StringIO(csv_resp.text)))
    formula_row = next(row for row in csv_rows if row["action"] == "matter.formula_probe")
    assert formula_row["actor_label"] == f"'{formula_label}"

    boot_b = _bootstrap(client, "lw-s11-audit-export-b")
    token_b = str(boot_b["access_token"])
    denied = client.get(
        f"/api/matters/{matter_a}/audit-events/export",
        headers=auth_headers(token_b),
    )
    assert denied.status_code == 404


def test_matter_audit_respects_restricted_access_and_ethical_walls(
    client: TestClient,
) -> None:
    slug = "lw-s11-audit-access"
    boot = _bootstrap(client, slug)
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    member_id, member_token = _create_member(
        client,
        owner_token,
        slug=slug,
        email="member-lw-s11-audit@example.com",
    )
    restricted_matter = _create_matter(client, owner_token, code="LW-AUD-REST")
    walled_matter = _create_matter(client, owner_token, code="LW-AUD-WALL")
    _seed_audit_event(
        company_id=company_id,
        matter_id=restricted_matter,
        action="matter.tags.assigned",
    )
    _seed_audit_event(
        company_id=company_id,
        matter_id=walled_matter,
        action="matter_strategy.created",
    )

    restricted = client.post(
        f"/api/matters/{restricted_matter}/access/restricted",
        headers=auth_headers(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    wall = client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=auth_headers(owner_token),
        json={"excluded_membership_id": member_id, "reason": "conflict"},
    )
    assert wall.status_code == 200, wall.text

    restricted_read = client.get(
        f"/api/matters/{restricted_matter}/audit-events",
        headers=auth_headers(member_token),
    )
    walled_read = client.get(
        f"/api/matters/{walled_matter}/audit-events",
        headers=auth_headers(member_token),
    )
    assert restricted_read.status_code == 404
    assert walled_read.status_code == 404


def test_matter_audit_respects_team_scoping(client: TestClient) -> None:
    slug = "lw-s11-audit-teams"
    boot = _bootstrap(client, slug)
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    member_id, member_token = _create_member(
        client,
        owner_token,
        slug=slug,
        email="team-member-lw-s11-audit@example.com",
    )
    owner_headers = auth_headers(owner_token)

    litigation_team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Litigation", "slug": "litigation"},
    ).json()
    ip_team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "IP", "slug": "ip"},
    ).json()
    matter_id = _create_matter(client, owner_token, code="LW-AUD-TEAM")
    assign_team = client.patch(
        f"/api/matters/{matter_id}",
        headers=owner_headers,
        json={"team_id": litigation_team["id"]},
    )
    assert assign_team.status_code == 200, assign_team.text
    _seed_audit_event(
        company_id=company_id,
        matter_id=matter_id,
        action="matter.updated",
    )
    add_to_ip = client.post(
        f"/api/teams/{ip_team['id']}/members",
        headers=owner_headers,
        json={"membership_id": member_id},
    )
    assert add_to_ip.status_code == 200, add_to_ip.text
    scoping = client.put(
        "/api/teams/scoping",
        headers=owner_headers,
        json={"enabled": True},
    )
    assert scoping.status_code == 200, scoping.text

    response = client.get(
        f"/api/matters/{matter_id}/audit-events",
        headers=auth_headers(member_token),
    )
    assert response.status_code == 404

    owner_response = client.get(
        f"/api/matters/{matter_id}/audit-events",
        headers=owner_headers,
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["total"] >= 1


def test_matter_audit_export_records_a_scoped_audit_event(client: TestClient) -> None:
    boot = _bootstrap(client, "lw-s11-audit-export-event")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, code="LW-AUD-EXPORT")
    _seed_audit_event(
        company_id=company_id,
        matter_id=matter_id,
        action="matter_strategy.created",
    )

    response = client.get(
        f"/api/matters/{matter_id}/audit-events/export",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text

    factory = get_session_factory()
    with factory() as session:
        exported = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.matter_id == matter_id,
                AuditEvent.action == "matter.audit.exported",
            )
        )
    assert exported is not None
    assert json.loads(exported.metadata_json)["row_count"] >= 1
