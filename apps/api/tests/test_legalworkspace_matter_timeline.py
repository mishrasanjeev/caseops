from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    MatterActivity,
    MatterAttachment,
    MatterCourtOrder,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterHearing,
    MatterHearingStatus,
    MatterTask,
    MatterTaskPriority,
    MatterTaskStatus,
)
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


def _create_matter(client: TestClient, token: str, code: str) -> dict[str, object]:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": f"LW S2 Matter {code}",
            "matter_code": code,
            "client_name": "Acme Industries",
            "opposing_party": "Beta Projects",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_attachment(matter_id: str, membership_id: str) -> str:
    factory = get_session_factory()
    with factory() as session:
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename="interim-order.pdf",
            storage_key=f"lw-s2/{uuid4()}/interim-order.pdf",
            content_type="application/pdf",
            size_bytes=128,
            sha256_hex="a" * 64,
            processing_status="indexed",
            extracted_char_count=100,
            created_at=datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
        )
        session.add(attachment)
        session.commit()
        return attachment.id


def _seed_timeline_sources(matter_id: str, membership_id: str) -> dict[str, str]:
    attachment_id = _seed_attachment(matter_id, membership_id)
    factory = get_session_factory()
    with factory() as session:
        completed_hearing = MatterHearing(
            matter_id=matter_id,
            hearing_on=date(2026, 5, 2),
            forum_name="Delhi High Court",
            judge_name="Justice A. Rao",
            purpose="Interim arguments",
            status=MatterHearingStatus.COMPLETED,
            outcome_note="Arguments concluded.",
        )
        upcoming_hearing = MatterHearing(
            matter_id=matter_id,
            hearing_on=date(2026, 5, 20),
            forum_name="Delhi High Court",
            judge_name="Justice B. Sen",
            purpose="Final arguments",
            status=MatterHearingStatus.SCHEDULED,
        )
        order = MatterCourtOrder(
            matter_id=matter_id,
            order_date=date(2026, 5, 3),
            title="Interim stay granted",
            summary="Interim stay granted until next listing.",
            order_text="Stay granted.",
            source="manual-test",
            source_reference="DHC/123",
            bench_name="Division Bench I",
            judge_names_json=["Justice A. Rao", "Justice B. Sen"],
            order_attachment_id=attachment_id,
            order_kind="interim_order",
            is_interim_order=True,
            stay_status="granted",
            stay_effective_until=date(2026, 6, 30),
            synced_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        )
        deadline = MatterDeadline(
            matter_id=matter_id,
            source="manual",
            kind="filing",
            title="File rejoinder",
            notes="Rejoinder due before the next listing.",
            due_on=date(2026, 5, 12),
            status=MatterDeadlineStatus.OPEN,
        )
        task = MatterTask(
            matter_id=matter_id,
            created_by_membership_id=membership_id,
            title="Prepare hearing note",
            description="Brief senior counsel on stay order.",
            due_on=date(2026, 5, 18),
            status=MatterTaskStatus.TODO,
            priority=MatterTaskPriority.HIGH,
            created_at=datetime(2026, 5, 5, 9, 0, tzinfo=UTC),
        )
        activity = MatterActivity(
            matter_id=matter_id,
            actor_membership_id=membership_id,
            event_type="matter_reviewed",
            title="Partner reviewed chronology",
            detail="Marked interim stay as the current blocker.",
            created_at=datetime(2026, 5, 6, 9, 0, tzinfo=UTC),
        )
        session.add_all(
            [
                completed_hearing,
                upcoming_hearing,
                order,
                deadline,
                task,
                activity,
            ]
        )
        session.commit()
        return {
            "attachment_id": attachment_id,
            "order_id": order.id,
            "completed_hearing_id": completed_hearing.id,
            "upcoming_hearing_id": upcoming_hearing.id,
        }


def _create_team(client: TestClient, owner_token: str, name: str, slug: str) -> str:
    response = client.post(
        "/api/teams/",
        headers=_auth(owner_token),
        json={"name": name, "slug": slug},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _assign_matter_team(
    client: TestClient,
    *,
    owner_token: str,
    matter_id: str,
    team_id: str,
) -> None:
    matter = client.get(
        f"/api/matters/{matter_id}",
        headers=_auth(owner_token),
    )
    assert matter.status_code == 200, matter.text
    response = client.patch(
        f"/api/matters/{matter_id}",
        headers=_auth(owner_token),
        json={
            "team_id": team_id,
            "expected_updated_at": matter.json()["updated_at"],
        },
    )
    assert response.status_code == 200, response.text


def _add_team_member(
    client: TestClient,
    *,
    owner_token: str,
    team_id: str,
    membership_id: str,
) -> None:
    response = client.post(
        f"/api/teams/{team_id}/members",
        headers=_auth(owner_token),
        json={"membership_id": membership_id},
    )
    assert response.status_code == 200, response.text


def _enable_team_scoping(client: TestClient, owner_token: str) -> None:
    response = client.put(
        "/api/teams/scoping",
        headers=_auth(owner_token),
        json={"enabled": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True


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


def test_lw_s2_timeline_composes_sources_and_sorts(client: TestClient) -> None:
    boot = _bootstrap(client, "lw-s2-timeline", "owner")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "LW-S2-TL")
    _seed_timeline_sources(str(matter["id"]), str(boot["membership"]["id"]))

    asc = client.get(
        f"/api/matters/{matter['id']}/timeline",
        headers=_auth(token),
        params={"sort": "asc", "limit": 20},
    )
    assert asc.status_code == 200, asc.text
    body = asc.json()
    assert body["matter_id"] == matter["id"]
    assert body["sort"] == "asc"
    assert body["next_cursor"] is None
    event_types = {item["event_type"] for item in body["items"]}
    assert {
        "hearing",
        "court_order",
        "document",
        "deadline",
        "task",
        "activity",
    }.issubset(event_types)
    dates = [item["event_date"] for item in body["items"]]
    assert dates == sorted(dates)

    order_item = next(item for item in body["items"] if item["event_type"] == "court_order")
    assert order_item["order_kind"] == "interim_order"
    assert order_item["stay_status"] == "granted"
    assert order_item["linked_attachment_id"]
    assert (
        order_item["links"]["document"]
        == f"/app/matters/{matter['id']}/documents/{order_item['linked_attachment_id']}/view"
    )
    assert "interim" in order_item["badges"]
    assert any(str(badge).startswith("stay:") for badge in order_item["badges"])
    document_item = next(item for item in body["items"] if item["event_type"] == "document")
    assert (
        document_item["links"]["document"]
        == f"/app/matters/{matter['id']}/documents/{document_item['linked_attachment_id']}/view"
    )

    desc = client.get(
        f"/api/matters/{matter['id']}/timeline",
        headers=_auth(token),
        params={"sort": "desc", "limit": 20},
    )
    assert desc.status_code == 200, desc.text
    desc_dates = [item["event_date"] for item in desc.json()["items"]]
    assert desc_dates == sorted(desc_dates, reverse=True)

    typed = client.get(
        f"/api/matters/{matter['id']}/timeline",
        headers=_auth(token),
        params={"types": "hearing,court_order"},
    )
    assert typed.status_code == 200, typed.text
    assert {item["event_type"] for item in typed.json()["items"]} == {
        "hearing",
        "court_order",
    }


def test_lw_s2_timeline_enforces_matter_access_and_tenant_isolation(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-s2-access", "owner")
    owner_token = str(boot["access_token"])
    matter = _create_matter(client, owner_token, "LW-S2-ACL")
    matter_id = str(matter["id"])
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=str(boot["company"]["slug"]),
        email="member@lw-s2-access.in",
    )
    _seed_timeline_sources(matter_id, str(boot["membership"]["id"]))

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    hidden = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(member_token),
    )
    assert hidden.status_code == 404, hidden.text

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=_auth(owner_token),
        json={"membership_id": member_id, "reason": "Timeline review"},
    )
    assert grant.status_code == 200, grant.text
    visible = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(member_token),
    )
    assert visible.status_code == 200, visible.text

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    walled = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(member_token),
    )
    assert walled.status_code == 404, walled.text

    other = _bootstrap(client, "lw-s2-other", "owner")
    cross = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(str(other["access_token"])),
    )
    assert cross.status_code == 404, cross.text


def test_lw_s2_direct_timeline_and_order_update_respect_team_scoping(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-s2-team-scope", "owner")
    owner_token = str(boot["access_token"])
    matter = _create_matter(client, owner_token, "LW-S2-TEAM")
    matter_id = str(matter["id"])
    seeded = _seed_timeline_sources(matter_id, str(boot["membership"]["id"]))
    team_id = _create_team(client, owner_token, "Litigation", "litigation")
    _assign_matter_team(
        client,
        owner_token=owner_token,
        matter_id=matter_id,
        team_id=team_id,
    )
    blocked_mid, blocked_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=str(boot["company"]["slug"]),
        email="blocked@lw-s2-team-scope.in",
    )
    allowed_mid, allowed_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=str(boot["company"]["slug"]),
        email="allowed@lw-s2-team-scope.in",
    )
    admin_mid, admin_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=str(boot["company"]["slug"]),
        email="admin@lw-s2-team-scope.in",
        role="admin",
    )
    _add_team_member(
        client,
        owner_token=owner_token,
        team_id=team_id,
        membership_id=allowed_mid,
    )
    _add_team_member(
        client,
        owner_token=owner_token,
        team_id=team_id,
        membership_id=admin_mid,
    )
    _enable_team_scoping(client, owner_token)

    hidden = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(blocked_token),
    )
    assert hidden.status_code == 404, hidden.text
    denied_patch = client.patch(
        f"/api/matters/{matter_id}/court-orders/{seeded['order_id']}",
        headers=_auth(blocked_token),
        json={
            "order_kind": "interim_order",
            "is_interim_order": True,
            "stay_status": "granted",
        },
    )
    assert denied_patch.status_code == 404, denied_patch.text

    visible = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(allowed_token),
    )
    assert visible.status_code == 200, visible.text
    allowed_patch = client.patch(
        f"/api/matters/{matter_id}/court-orders/{seeded['order_id']}",
        headers=_auth(allowed_token),
        json={
            "order_kind": "interim_order",
            "is_interim_order": True,
            "stay_status": "continued",
        },
    )
    assert allowed_patch.status_code == 200, allowed_patch.text
    assert allowed_patch.json()["stay_status"] == "continued"

    admin_visible = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(admin_token),
    )
    assert admin_visible.status_code == 200, admin_visible.text
    admin_patch = client.patch(
        f"/api/matters/{matter_id}/court-orders/{seeded['order_id']}",
        headers=_auth(admin_token),
        json={"stay_status": "granted"},
    )
    assert admin_patch.status_code == 200, admin_patch.text
    assert admin_patch.json()["stay_status"] == "granted"

    owner_patch = client.patch(
        f"/api/matters/{matter_id}/court-orders/{seeded['order_id']}",
        headers=_auth(owner_token),
        json={"stay_status": "modified"},
    )
    assert owner_patch.status_code == 200, owner_patch.text
    assert owner_patch.json()["stay_status"] == "modified"
    assert blocked_mid != allowed_mid


def test_lw_s2_order_metadata_update_audits_and_sets_stay_indicators(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-s2-order", "owner")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter = _create_matter(client, token, "LW-S2-ORDER")
    matter_id = str(matter["id"])
    attachment_id = _seed_attachment(matter_id, str(boot["membership"]["id"]))
    factory = get_session_factory()
    with factory() as session:
        order = MatterCourtOrder(
            matter_id=matter_id,
            order_date=date(2026, 5, 3),
            title="Daily order",
            summary="Plain order before metadata enrichment.",
            source="manual-test",
            synced_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        )
        session.add(order)
        session.commit()
        order_id = order.id

    patch = client.patch(
        f"/api/matters/{matter_id}/court-orders/{order_id}",
        headers=_auth(token),
        json={
            "bench_name": "Division Bench II",
            "judge_names": ["Justice Kavita Rao", "Justice M. Sen"],
            "order_attachment_id": attachment_id,
            "order_kind": "interim_order",
            "is_interim_order": True,
            "stay_status": "granted",
            "stay_effective_until": "2026-06-30",
        },
    )
    assert patch.status_code == 200, patch.text
    order_payload = patch.json()
    assert order_payload["bench_name"] == "Division Bench II"
    assert order_payload["judge_names"] == ["Justice Kavita Rao", "Justice M. Sen"]
    assert order_payload["order_attachment_id"] == attachment_id
    assert order_payload["order_kind"] == "interim_order"
    assert order_payload["is_interim_order"] is True
    assert order_payload["stay_status"] == "granted"

    detail = client.get(f"/api/matters/{matter_id}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["has_stay"] is True
    assert detail.json()["has_interim_order"] is True

    filtered = client.get(
        "/api/matters/",
        headers=_auth(token),
        params={"has_stay": True},
    )
    assert filtered.status_code == 200, filtered.text
    assert [row["id"] for row in filtered.json()["matters"]] == [matter_id]

    timeline = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(token),
    )
    assert timeline.status_code == 200, timeline.text
    court_order = next(
        item for item in timeline.json()["items"] if item["event_type"] == "court_order"
    )
    assert court_order["stay_status"] == "granted"
    assert court_order["is_interim_order"] is True

    actions = _audit_actions(company_id)
    action_names = [event.action for event in actions]
    assert "matter_court_order.metadata.updated" in action_names
    assert "matter_court_order.stay.updated" in action_names
    stay_event = next(
        event
        for event in actions
        if event.action == "matter_court_order.stay.updated"
    )
    metadata = json.loads(stay_event.metadata_json or "{}")
    assert metadata["after"]["stay_status"] == "granted"
    assert metadata["after"]["is_interim_order"] is True


def test_lw_s2_legacy_orders_with_null_metadata_still_render(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-s2-legacy", "owner")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "LW-S2-LEGACY")
    matter_id = str(matter["id"])
    factory = get_session_factory()
    with factory() as session:
        order = MatterCourtOrder(
            matter_id=matter_id,
            order_date=date(2026, 5, 3),
            title="Legacy order",
            summary="Order created before metadata columns existed.",
            source="legacy-test",
            synced_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
            bench_name=None,
            judge_names_json=None,
            order_attachment_id=None,
            order_kind=None,
            is_interim_order=False,
            stay_status=None,
            stay_effective_until=None,
        )
        session.add(order)
        session.commit()

    workspace = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=_auth(token),
    )
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["court_orders"][0]["title"] == "Legacy order"

    timeline = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(token),
    )
    assert timeline.status_code == 200, timeline.text
    court_order = next(
        item for item in timeline.json()["items"] if item["event_type"] == "court_order"
    )
    assert court_order["title"] == "Legacy order"
    assert court_order["stay_status"] in (None, "none")
