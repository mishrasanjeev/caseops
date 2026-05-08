from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, MatterAttachment, MatterCourtOrder
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
            "title": f"LW S3 Matter {code}",
            "matter_code": code,
            "client_name": "Acme Industries",
            "opposing_party": "Beta Projects",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_attachment(
    matter_id: str,
    membership_id: str,
    *,
    filename: str = "legacy-document.pdf",
) -> str:
    factory = get_session_factory()
    with factory() as session:
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=membership_id,
            original_filename=filename,
            storage_key=f"lw-s3/{uuid4()}/{filename}",
            content_type="application/pdf",
            size_bytes=128,
            sha256_hex="b" * 64,
            processing_status="indexed",
            extracted_char_count=100,
            created_at=datetime(2026, 5, 4, 10, 0, tzinfo=UTC),
        )
        session.add(attachment)
        session.commit()
        return attachment.id


def _seed_order(matter_id: str, *, title: str = "Daily order") -> str:
    factory = get_session_factory()
    with factory() as session:
        order = MatterCourtOrder(
            matter_id=matter_id,
            order_date=date(2026, 5, 3),
            title=title,
            summary="Order sheet summary.",
            source="manual-test",
            source_reference=f"ORD/{uuid4()}",
            synced_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        )
        session.add(order)
        session.commit()
        return order.id


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


def _create_team(client: TestClient, owner_token: str, name: str, slug: str) -> str:
    response = client.post(
        "/api/teams/",
        headers=_auth(owner_token),
        json={"name": name, "slug": slug},
    )
    assert response.status_code in {200, 201}, response.text
    return str(response.json()["id"])


def _assign_matter_team(
    client: TestClient,
    *,
    owner_token: str,
    matter_id: str,
    team_id: str,
) -> None:
    response = client.patch(
        f"/api/matters/{matter_id}",
        headers=_auth(owner_token),
        json={"team_id": team_id},
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


def test_lw_s3_upload_persists_lifecycle_metadata_and_timeline_exposes_it(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-s3-upload", "owner")
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "LW-S3-UP")
    matter_id = str(matter["id"])
    order_id = _seed_order(matter_id, title="Petition admitted")

    response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=_auth(token),
        files={"file": ("petition.txt", b"Petition and annexures", "text/plain")},
        data={
            "document_type": "complaint_petition",
            "document_date": "2026-05-01",
            "sequence_index": "10",
            "linked_court_order_id": order_id,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_type"] == "complaint_petition"
    assert body["lifecycle_stage"] == "initiation"
    assert body["document_date"] == "2026-05-01"
    assert body["sequence_index"] == 10
    assert body["linked_court_order_id"] == order_id

    workspace = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=_auth(token),
    )
    assert workspace.status_code == 200, workspace.text
    attachment = workspace.json()["attachments"][0]
    assert attachment["document_type"] == "complaint_petition"
    assert attachment["lifecycle_stage"] == "initiation"

    timeline = client.get(
        f"/api/matters/{matter_id}/timeline",
        headers=_auth(token),
        params={"types": "document"},
    )
    assert timeline.status_code == 200, timeline.text
    document_item = timeline.json()["items"][0]
    assert document_item["metadata"]["document_type"] == "complaint_petition"
    assert document_item["metadata"]["lifecycle_stage"] == "initiation"
    assert document_item["metadata"]["document_date"] == "2026-05-01"
    assert document_item["metadata"]["sequence_index"] == 10
    assert document_item["metadata"]["linked_court_order_id"] == order_id
    assert (
        document_item["links"]["document"]
        == f"/app/matters/{matter_id}/documents/{body['id']}/view"
    )


def test_lw_s3_legacy_document_renders_unclassified_and_patch_audits(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-s3-patch", "owner")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    matter = _create_matter(client, token, "LW-S3-PATCH")
    matter_id = str(matter["id"])
    attachment_id = _seed_attachment(matter_id, membership_id)
    order_id = _seed_order(matter_id, title="Evidence admitted")

    legacy = client.get(
        f"/api/matters/{matter_id}/workspace",
        headers=_auth(token),
    )
    assert legacy.status_code == 200, legacy.text
    legacy_attachment = legacy.json()["attachments"][0]
    assert legacy_attachment["document_type"] is None
    assert legacy_attachment["lifecycle_stage"] is None

    patch = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(token),
        json={
            "document_type": "evidence",
            "document_date": "2026-05-02",
            "sequence_index": 30,
            "linked_court_order_id": order_id,
        },
    )
    assert patch.status_code == 200, patch.text
    patched = patch.json()
    assert patched["document_type"] == "evidence"
    assert patched["lifecycle_stage"] == "evidence"
    assert patched["linked_court_order_id"] == order_id

    cleared = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(token),
        json={"document_type": None, "lifecycle_stage": None, "linked_court_order_id": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["document_type"] is None
    assert cleared.json()["lifecycle_stage"] is None
    assert cleared.json()["linked_court_order_id"] is None

    audit = [
        event
        for event in _audit_actions(company_id)
        if event.action == "matter_attachment.metadata.updated"
    ]
    assert len(audit) == 2
    first_metadata = json.loads(audit[0].metadata_json or "{}")
    assert first_metadata["before"]["document_type"] is None
    assert first_metadata["after"]["document_type"] == "evidence"
    assert first_metadata["after"]["linked_court_order_id"] == order_id


def test_lw_s3_metadata_rejects_bad_values_and_foreign_order_links(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "lw-s3-guards", "owner")
    token = str(boot["access_token"])
    membership_id = str(boot["membership"]["id"])
    matter = _create_matter(client, token, "LW-S3-GUARD-A")
    other_matter = _create_matter(client, token, "LW-S3-GUARD-B")
    matter_id = str(matter["id"])
    attachment_id = _seed_attachment(matter_id, membership_id)
    other_order_id = _seed_order(str(other_matter["id"]), title="Other matter order")

    invalid_type = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(token),
        json={"document_type": "freeform"},
    )
    assert invalid_type.status_code == 422, invalid_type.text

    invalid_sequence = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(token),
        json={"sequence_index": -1},
    )
    assert invalid_sequence.status_code == 422, invalid_sequence.text

    wrong_matter_order = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(token),
        json={"linked_court_order_id": other_order_id},
    )
    assert wrong_matter_order.status_code == 400, wrong_matter_order.text

    other = _bootstrap(client, "lw-s3-other", "owner")
    cross_tenant = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(str(other["access_token"])),
        json={"document_type": "notice"},
    )
    assert cross_tenant.status_code == 404, cross_tenant.text


def test_lw_s3_metadata_patch_respects_team_scoping(client: TestClient) -> None:
    boot = _bootstrap(client, "lw-s3-team", "owner")
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    matter = _create_matter(client, owner_token, "LW-S3-TEAM")
    matter_id = str(matter["id"])
    attachment_id = _seed_attachment(matter_id, str(boot["membership"]["id"]))
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
        company_slug=company_slug,
        email="blocked@lw-s3-team.in",
        role="partner",
    )
    allowed_mid, allowed_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="allowed@lw-s3-team.in",
        role="partner",
    )
    _add_team_member(
        client,
        owner_token=owner_token,
        team_id=team_id,
        membership_id=allowed_mid,
    )
    _enable_team_scoping(client, owner_token)

    denied = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(blocked_token),
        json={"document_type": "notice"},
    )
    assert denied.status_code == 404, denied.text

    allowed = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(allowed_token),
        json={"document_type": "notice"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["document_type"] == "notice"
    assert allowed.json()["lifecycle_stage"] == "initiation"
    assert blocked_mid != allowed_mid
