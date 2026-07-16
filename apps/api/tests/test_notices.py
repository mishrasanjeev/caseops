from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeMatterLink,
    Matter,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.notices import _notice_statement
from caseops_api.services.session_context import SessionContext

_PASSWORD = "NoticePass123!"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, prefix: str) -> dict[str, object]:
    slug = f"{prefix}-{uuid4().hex[:8]}"
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{prefix.title()} Legal",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{prefix.title()} Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": _PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    payload["_slug"] = slug
    return payload


def _invite(
    client: TestClient,
    *,
    owner_token: str,
    slug: str,
    role: str,
) -> tuple[str, str]:
    email = f"{role}-{uuid4().hex[:8]}@{slug}.example"
    create = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": f"Notice {role.title()}",
            "email": email,
            "password": _PASSWORD,
            "role": role,
        },
    )
    assert create.status_code == 200, create.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": slug,
            "email": email,
            "password": _PASSWORD,
        },
    )
    assert login.status_code == 200, login.text
    return str(create.json()["membership_id"]), str(login.json()["access_token"])


def _matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": f"Notice matter {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _notice(
    client: TestClient,
    token: str,
    *,
    subject: str,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {"subject": subject}
    payload.update(overrides)
    response = client.post(
        "/api/notices/",
        headers=_auth(token),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_quota(company_id: str, quota_bytes: int | None) -> None:
    with get_session_factory()() as session:
        company = session.get(Company, company_id)
        assert company is not None
        company.storage_quota_bytes = quota_bytes
        session.commit()


def _audit_actions(company_id: str) -> list[str]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc())
            )
        )


def _latest_audit_metadata(company_id: str, action: str) -> dict[str, object]:
    with get_session_factory()() as session:
        raw = session.scalar(
            select(AuditEvent.metadata_json)
            .where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == action,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
    assert raw is not None
    return json.loads(raw)


def test_unlinked_notice_is_file_optional_and_visible_to_viewer(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-unlinked")
    owner_token = str(boot["access_token"])
    _viewer_id, viewer_token = _invite(
        client,
        owner_token=owner_token,
        slug=str(boot["_slug"]),
        role="viewer",
    )

    notice = _notice(
        client,
        owner_token,
        subject="Government inquiry received",
        direction="received",
        type="Regulatory inquiry",
        status="Open",
        authority="Registrar of Companies",
        received_on="2026-07-15",
        reply_required=True,
        reply_due_on="2026-07-29",
        amount_minor=125000,
    )

    assert notice["source_kind"] == "standalone"
    assert notice["read_only"] is False
    assert notice["matter_links"] == []
    assert notice["has_file"] is False
    assert notice["filename"] is None
    assert notice["currency"] == "INR"

    listing = client.get("/api/notices/", headers=_auth(viewer_token))
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    assert listing.json()["notices"][0]["id"] == notice["id"]
    detail = client.get(
        f"/api/notices/{notice['id']}",
        headers=_auth(viewer_token),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == notice["id"]

    viewer_create = client.post(
        "/api/notices/",
        headers=_auth(viewer_token),
        json={"subject": "Viewer must not create"},
    )
    assert viewer_create.status_code == 403
    unknown_create_field = client.post(
        "/api/notices/",
        headers=_auth(owner_token),
        json={"subject": "Typo must be rejected", "statuz": "Open"},
    )
    assert unknown_create_field.status_code == 422
    viewer_patch = client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(viewer_token),
        json={
            "expected_updated_at": notice["updated_at"],
            "status": "Closed",
        },
    )
    assert viewer_patch.status_code == 403
    unknown_patch_field = client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(owner_token),
        json={
            "expected_updated_at": notice["updated_at"],
            "departmant": "Tax",
        },
    )
    assert unknown_patch_field.status_code == 422
    missing_file = client.get(
        f"/api/notices/{notice['id']}/download",
        headers=_auth(viewer_token),
    )
    assert missing_file.status_code == 404

    null_reply_required = client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(owner_token),
        json={
            "expected_updated_at": notice["updated_at"],
            "reply_required": None,
        },
    )
    assert null_reply_required.status_code == 422
    null_reply_sent = client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(owner_token),
        json={
            "expected_updated_at": notice["updated_at"],
            "reply_sent": None,
        },
    )
    assert null_reply_sent.status_code == 422

    normalized = client.patch(
        f"/api/notices/{notice['id']}",
        headers=_auth(owner_token),
        json={
            "expected_updated_at": notice["updated_at"],
            "direction": "sent",
            "sent_on": "2026-07-16",
        },
    )
    assert normalized.status_code == 200, normalized.text
    normalized_notice = normalized.json()
    assert normalized_notice["received_on"] is None
    assert normalized_notice["received_from"] is None
    assert normalized_notice["reply_due_on"] is None
    assert normalized_notice["reply_required"] is False
    assert normalized_notice["reply_sent"] is False
    assert normalized_notice["sent_on"] == "2026-07-16"

    invalid_sent_create = client.post(
        "/api/notices/",
        headers=_auth(owner_token),
        json={
            "subject": "Contradictory sent notice",
            "direction": "sent",
            "received_on": "2026-07-15",
        },
    )
    assert invalid_sent_create.status_code == 422


def test_multi_matter_notice_filters_assignment_and_updates(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-multi")
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    member_id, _member_token = _invite(
        client,
        owner_token=owner_token,
        slug=str(boot["_slug"]),
        role="member",
    )
    matter_a = _matter(client, owner_token, "NOTICE-MULTI-A")
    matter_b = _matter(client, owner_token, "NOTICE-MULTI-B")
    matter_c = _matter(client, owner_token, "NOTICE-MULTI-C")

    received = _notice(
        client,
        owner_token,
        subject="Statutory tax demand",
        direction="received",
        type="GST demand",
        status="Under Review",
        owner_membership_id=member_id,
        matter_ids=[matter_a, matter_b, matter_a],
        reply_due_on="2026-08-20",
        reply_required=True,
        department="Tax",
        summary="Demand spans two related proceedings.",
    )
    sent = _notice(
        client,
        owner_token,
        subject="Settlement demand dispatched",
        direction="sent",
        status="Closed",
        owner_membership_id=owner_id,
        matter_ids=[matter_a],
        sent_on="2026-07-14",
    )
    assert {link["matter_id"] for link in received["matter_links"]} == {
        matter_a,
        matter_b,
    }

    cases = (
        ({"query": "related proceedings"}, {received["id"]}),
        ({"direction": "sent"}, {sent["id"]}),
        ({"status": "closed"}, {sent["id"]}),
        ({"matter_id": matter_b}, {received["id"]}),
        ({"owner_membership_id": member_id}, {received["id"]}),
        (
            {"due_from": "2026-08-20", "due_to": "2026-08-20"},
            {received["id"]},
        ),
    )
    for params, expected_ids in cases:
        response = client.get(
            "/api/notices/",
            headers=_auth(owner_token),
            params=params,
        )
        assert response.status_code == 200, (params, response.text)
        assert {row["id"] for row in response.json()["notices"]} == expected_ids

    bad_range = client.get(
        "/api/notices/",
        headers=_auth(owner_token),
        params={"due_from": "2026-08-21", "due_to": "2026-08-20"},
    )
    assert bad_range.status_code == 422

    patched = client.patch(
        f"/api/notices/{received['id']}",
        headers=_auth(owner_token),
        json={
            "expected_updated_at": received["updated_at"],
            "status": "Responded",
            "owner_membership_id": owner_id,
            "matter_ids": [matter_b, matter_c],
            "reply_sent_on": "2026-08-19",
            "amount_minor": 100000,
        },
    )
    assert patched.status_code == 200, patched.text
    updated = patched.json()
    assert updated["status"] == "Responded"
    assert updated["owner_membership_id"] == owner_id
    assert updated["reply_sent"] is True
    assert updated["reply_sent_on"] == "2026-08-19"
    assert updated["amount_minor"] == 100000
    assert {link["matter_id"] for link in updated["matter_links"]} == {
        matter_b,
        matter_c,
    }

    stale = client.patch(
        f"/api/notices/{received['id']}",
        headers=_auth(owner_token),
        json={
            "expected_updated_at": received["updated_at"],
            "status": "Stale overwrite must fail",
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "notice_stale_write"
    assert stale.json()["current_updated_at"] == updated["updated_at"]

    actions = _audit_actions(str(boot["company"]["id"]))
    assert actions.count("notice.created") == 2
    assert "notice.updated" in actions
    audit = _latest_audit_metadata(
        str(boot["company"]["id"]),
        "notice.updated",
    )
    expected_snapshot_fields = {
        "direction",
        "subject",
        "type",
        "status",
        "authority",
        "received_from",
        "department",
        "mode",
        "owner_membership_id",
        "received_on",
        "sent_on",
        "reply_due_on",
        "reply_required",
        "reply_sent",
        "reply_sent_on",
        "summary",
        "remarks",
        "response",
        "internal_spoc",
        "internal_remarks",
        "counsel_engaged",
        "currency",
        "amount_minor",
        "dispute_amount_minor",
        "recovered_amount_minor",
        "matter_ids",
        "has_file",
        "updated_at",
    }
    assert expected_snapshot_fields <= set(audit["before"])
    assert expected_snapshot_fields <= set(audit["after"])
    assert audit["before"]["subject"] == "Statutory tax demand"
    assert set(audit["after"]["matter_ids"]) == {matter_b, matter_c}


def test_legacy_matter_attachment_is_aggregated_filtered_and_read_only(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-legacy")
    token = str(boot["access_token"])
    matter_id = _matter(client, token, "NOTICE-LEGACY-1")
    upload = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=_auth(token),
        data={
            "document_type": "notice",
            "notice_direction": "received",
            "notice_subject": "Legacy environmental show-cause",
            "notice_type": "Show cause",
            "notice_status": "Open",
            "notice_authority": "Pollution Control Board",
            "notice_received_from": "Regional Officer",
            "notice_received_on": "2026-07-10",
            "notice_reply_due_on": "2026-07-25",
            "notice_reply_required": "true",
            "notice_department": "Environment",
        },
        files={"file": ("legacy-notice.txt", b"legacy notice body", "text/plain")},
    )
    assert upload.status_code == 200, upload.text
    attachment_id = upload.json()["id"]
    reply_upload = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=_auth(token),
        data={
            "document_type": "notice",
            "document_date": "2026-07-20",
            "notice_direction": "received",
            "notice_document_role": "reply",
            "notice_parent_attachment_id": attachment_id,
            "notice_subject": "Reply child must not be a register row",
            "notice_reply_sent_on": "2026-07-20",
        },
        files={"file": ("legacy-reply.txt", b"reply body", "text/plain")},
    )
    assert reply_upload.status_code == 200, reply_upload.text
    reply_attachment_id = reply_upload.json()["id"]

    listing = client.get(
        "/api/notices/",
        headers=_auth(token),
        params={
            "query": "pollution control",
            "direction": "received",
            "matter_id": matter_id,
            "due_from": "2026-07-25",
            "due_to": "2026-07-25",
        },
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    legacy = listing.json()["notices"][0]
    assert legacy["id"] == attachment_id
    assert legacy["source_kind"] == "legacy_attachment"
    assert legacy["read_only"] is True
    assert legacy["subject"] == "Legacy environmental show-cause"
    assert legacy["owner_membership_id"] == boot["membership"]["id"]
    assert legacy["matter_links"] == [
        {
            "matter_id": matter_id,
            "matter_code": "NOTICE-LEGACY-1",
            "matter_title": "Notice matter NOTICE-LEGACY-1",
        }
    ]
    detail = client.get(
        f"/api/notices/{attachment_id}",
        headers=_auth(token),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["source_kind"] == "legacy_attachment"
    full_listing = client.get("/api/notices/", headers=_auth(token))
    assert full_listing.status_code == 200, full_listing.text
    full_ids = {row["id"] for row in full_listing.json()["notices"]}
    assert attachment_id in full_ids
    assert reply_attachment_id not in full_ids

    download = client.get(
        f"/api/notices/{attachment_id}/download",
        headers=_auth(token),
    )
    assert download.status_code == 200, download.text
    assert download.content == b"legacy notice body"
    assert "legacy-notice.txt" in download.headers["content-disposition"]

    patch = client.patch(
        f"/api/notices/{attachment_id}",
        headers=_auth(token),
        json={
            "expected_updated_at": "2026-07-15T00:00:00Z",
            "status": "Closed",
        },
    )
    assert patch.status_code == 409
    replace = client.post(
        f"/api/notices/{attachment_id}/file",
        headers=_auth(token),
        data={"expected_updated_at": "2026-07-15T00:00:00Z"},
        files={"file": ("replacement.txt", b"replacement", "text/plain")},
    )
    assert replace.status_code == 409

    child_download = client.get(
        f"/api/notices/{reply_attachment_id}/download",
        headers=_auth(token),
    )
    assert child_download.status_code == 404
    child_patch = client.patch(
        f"/api/notices/{reply_attachment_id}",
        headers=_auth(token),
        json={
            "expected_updated_at": "2026-07-15T00:00:00Z",
            "status": "Closed",
        },
    )
    assert child_patch.status_code == 404


def test_notice_file_round_trip_replacement_permissions_and_quota(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-file")
    owner_token = str(boot["access_token"])
    _member_id, member_token = _invite(
        client,
        owner_token=owner_token,
        slug=str(boot["_slug"]),
        role="member",
    )
    first_notice = _notice(client, owner_token, subject="File lifecycle notice")
    _set_quota(str(boot["company"]["id"]), 5)

    initial = client.post(
        f"/api/notices/{first_notice['id']}/file",
        headers=_auth(member_token),
        data={"expected_updated_at": first_notice["updated_at"]},
        files={"file": ("first.txt", b"first", "text/plain")},
    )
    assert initial.status_code == 200, initial.text
    assert initial.json()["has_file"] is True
    assert initial.json()["filename"] == "first.txt"
    assert initial.json()["size_bytes"] == 5

    download = client.get(
        f"/api/notices/{first_notice['id']}/download",
        headers=_auth(member_token),
    )
    assert download.status_code == 200
    assert download.content == b"first"

    member_replace = client.post(
        f"/api/notices/{first_notice['id']}/file",
        headers=_auth(member_token),
        data={"expected_updated_at": initial.json()["updated_at"]},
        files={"file": ("blocked.txt", b"other", "text/plain")},
    )
    assert member_replace.status_code == 403
    member_patch = client.patch(
        f"/api/notices/{first_notice['id']}",
        headers=_auth(member_token),
        json={
            "expected_updated_at": initial.json()["updated_at"],
            "status": "Closed",
        },
    )
    assert member_patch.status_code == 403

    stale_replace = client.post(
        f"/api/notices/{first_notice['id']}/file",
        headers=_auth(owner_token),
        data={"expected_updated_at": first_notice["updated_at"]},
        files={"file": ("stale.txt", b"stale", "text/plain")},
    )
    assert stale_replace.status_code == 409, stale_replace.text
    assert stale_replace.json()["code"] == "notice_stale_write"
    unchanged_download = client.get(
        f"/api/notices/{first_notice['id']}/download",
        headers=_auth(owner_token),
    )
    assert unchanged_download.content == b"first"

    owner_replace = client.post(
        f"/api/notices/{first_notice['id']}/file",
        headers=_auth(owner_token),
        data={"expected_updated_at": initial.json()["updated_at"]},
        files={"file": ("replacement.txt", b"other", "text/plain")},
    )
    assert owner_replace.status_code == 200, owner_replace.text
    replaced_download = client.get(
        f"/api/notices/{first_notice['id']}/download",
        headers=_auth(owner_token),
    )
    assert replaced_download.content == b"other"

    second_notice = _notice(client, owner_token, subject="Quota blocked notice")
    blocked = client.post(
        f"/api/notices/{second_notice['id']}/file",
        headers=_auth(owner_token),
        data={"expected_updated_at": second_notice["updated_at"]},
        files={"file": ("overflow.txt", b"x", "text/plain")},
    )
    assert blocked.status_code == 413, blocked.text
    assert "Firm storage quota exceeded" in blocked.json()["detail"]

    storage = client.get(
        "/api/admin/storage-governance",
        headers=_auth(owner_token),
    )
    assert storage.status_code == 200, storage.text
    assert storage.json()["used_bytes"] == 5
    billing_usage = client.get(
        "/api/billing/usage",
        headers=_auth(owner_token),
    )
    assert billing_usage.status_code == 200, billing_usage.text
    assert billing_usage.json()["snapshot"]["storage_used_bytes"] == 5
    actions = _audit_actions(str(boot["company"]["id"]))
    assert "notice.file.uploaded" in actions
    assert "notice.file.replaced" in actions
    assert "storage_quota.upload_blocked" in actions


def test_notice_tenant_and_partial_matter_visibility_are_isolated(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, "notice-tenant-a")
    boot_b = _bootstrap(client, "notice-tenant-b")
    token_a = str(boot_a["access_token"])
    token_b = str(boot_b["access_token"])
    admin_id, admin_token = _invite(
        client,
        owner_token=token_a,
        slug=str(boot_a["_slug"]),
        role="partner",
    )
    public_a = _matter(client, token_a, "NOTICE-A-PUBLIC")
    restricted_a = _matter(client, token_a, "NOTICE-A-RESTRICTED")
    matter_b = _matter(client, token_b, "NOTICE-B")
    restrict = client.post(
        f"/api/matters/{restricted_a}/access/restricted",
        headers=_auth(token_a),
        json={"restricted": True},
    )
    assert restrict.status_code == 200, restrict.text
    wall = client.post(
        f"/api/matters/{restricted_a}/access/walls",
        headers=_auth(token_a),
        json={
            "excluded_membership_id": admin_id,
            "reason": "Notice ACL regression",
        },
    )
    assert wall.status_code == 200, wall.text

    hidden = _notice(
        client,
        token_a,
        subject="Restricted-only notice",
        matter_ids=[restricted_a],
    )
    partial = _notice(
        client,
        token_a,
        subject="Shared across public and restricted matters",
        owner_membership_id=admin_id,
        matter_ids=[public_a, restricted_a],
    )
    partial_file_as_owner = client.post(
        f"/api/notices/{partial['id']}/file",
        headers=_auth(token_a),
        data={"expected_updated_at": partial["updated_at"]},
        files={"file": ("mixed-scope.txt", b"restricted context", "text/plain")},
    )
    assert partial_file_as_owner.status_code == 200, partial_file_as_owner.text
    partial = partial_file_as_owner.json()

    admin_listing = client.get("/api/notices/", headers=_auth(admin_token))
    assert admin_listing.status_code == 200, admin_listing.text
    admin_rows = {row["id"]: row for row in admin_listing.json()["notices"]}
    assert hidden["id"] not in admin_rows
    assert partial["id"] not in admin_rows

    partial_download = client.get(
        f"/api/notices/{partial['id']}/download",
        headers=_auth(admin_token),
    )
    assert partial_download.status_code == 404
    partial_detail = client.get(
        f"/api/notices/{partial['id']}",
        headers=_auth(admin_token),
    )
    assert partial_detail.status_code == 404

    partial_patch = client.patch(
        f"/api/notices/{partial['id']}",
        headers=_auth(admin_token),
        json={
            "expected_updated_at": partial["updated_at"],
            "status": "Admin should not mutate shared hidden context",
        },
    )
    assert partial_patch.status_code == 404
    partial_file = client.post(
        f"/api/notices/{partial['id']}/file",
        headers=_auth(admin_token),
        data={"expected_updated_at": partial["updated_at"]},
        files={"file": ("denied.txt", b"denied", "text/plain")},
    )
    assert partial_file.status_code == 404
    hidden_patch = client.patch(
        f"/api/notices/{hidden['id']}",
        headers=_auth(admin_token),
        json={
            "expected_updated_at": hidden["updated_at"],
            "status": "Still hidden",
        },
    )
    assert hidden_patch.status_code == 404

    tenant_b_listing = client.get("/api/notices/", headers=_auth(token_b))
    assert tenant_b_listing.status_code == 200
    assert tenant_b_listing.json()["notices"] == []
    cross_detail = client.get(
        f"/api/notices/{partial['id']}",
        headers=_auth(token_b),
    )
    assert cross_detail.status_code == 404
    cross_patch = client.patch(
        f"/api/notices/{partial['id']}",
        headers=_auth(token_b),
        json={
            "expected_updated_at": partial["updated_at"],
            "status": "Cross tenant",
        },
    )
    assert cross_patch.status_code == 404
    cross_file = client.post(
        f"/api/notices/{partial['id']}/file",
        headers=_auth(token_b),
        data={"expected_updated_at": partial["updated_at"]},
        files={"file": ("cross-tenant.txt", b"denied", "text/plain")},
    )
    assert cross_file.status_code == 404
    cross_link_create = client.post(
        "/api/notices/",
        headers=_auth(token_b),
        json={"subject": "Invalid cross link", "matter_ids": [public_a]},
    )
    assert cross_link_create.status_code == 404
    cross_link_patch = client.patch(
        f"/api/notices/{partial['id']}",
        headers=_auth(token_a),
        json={
            "expected_updated_at": partial["updated_at"],
            "matter_ids": [matter_b],
        },
    )
    assert cross_link_patch.status_code == 404
    public_notice = _notice(
        client,
        token_a,
        subject="Owner assignment isolation",
        matter_ids=[public_a],
    )
    cross_owner = client.patch(
        f"/api/notices/{public_notice['id']}",
        headers=_auth(token_a),
        json={
            "expected_updated_at": public_notice["updated_at"],
            "owner_membership_id": boot_b["membership"]["id"],
        },
    )
    assert cross_owner.status_code == 400


def test_notice_register_uses_bounded_keyset_pagination(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-pages")
    token = str(boot["access_token"])
    created_ids = {
        _notice(
            client,
            token,
            subject=f"Pagination regression {index}",
            received_on=f"2026-07-{10 + index:02d}",
        )["id"]
        for index in range(4)
    }

    first = client.get(
        "/api/notices/",
        headers=_auth(token),
        params={"query": "pagination regression", "limit": 2},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["total"] == 4
    assert len(first_payload["notices"]) == 2
    assert first_payload["next_cursor"]

    second = client.get(
        "/api/notices/",
        headers=_auth(token),
        params={
            "query": "pagination regression",
            "limit": 2,
            "cursor": first_payload["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["total"] == 4
    assert second_payload["next_cursor"] is None
    returned_ids = {row["id"] for row in [*first_payload["notices"], *second_payload["notices"]]}
    assert returned_ids == created_ids

    invalid = client.get(
        "/api/notices/",
        headers=_auth(token),
        params={"cursor": "this-is-not-a-cursor"},
    )
    assert invalid.status_code == 422
    structurally_invalid = client.get(
        "/api/notices/",
        headers=_auth(token),
        params={"cursor": "W10="},  # base64url for a JSON list, not an object
    )
    assert structurally_invalid.status_code == 422
    wildcard_literal = client.get(
        "/api/notices/",
        headers=_auth(token),
        params={"query": "%"},
    )
    assert wildcard_literal.status_code == 200, wildcard_literal.text
    assert wildcard_literal.json()["total"] == 0
    excessive_limit = client.get(
        "/api/notices/",
        headers=_auth(token),
        params={"limit": 101},
    )
    assert excessive_limit.status_code == 422


def test_notice_owner_options_and_create_assignment_permissions(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-owners")
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    member_id, member_token = _invite(
        client,
        owner_token=owner_token,
        slug=str(boot["_slug"]),
        role="member",
    )
    partner_id, partner_token = _invite(
        client,
        owner_token=owner_token,
        slug=str(boot["_slug"]),
        role="partner",
    )

    partner_me = client.get(
        "/api/auth/me",
        headers=_auth(partner_token),
    )
    assert partner_me.status_code == 200, partner_me.text
    assert "documents:manage" in partner_me.json()["capabilities"]
    assert "company:manage_users" not in partner_me.json()["capabilities"]
    options = client.get(
        "/api/notices/owners",
        headers=_auth(partner_token),
    )
    assert options.status_code == 200, options.text
    assert {row["membership_id"] for row in options.json()} == {
        owner_id,
        member_id,
        partner_id,
    }

    member_options = client.get(
        "/api/notices/owners",
        headers=_auth(member_token),
    )
    assert member_options.status_code == 403
    member_assign_other = client.post(
        "/api/notices/",
        headers=_auth(member_token),
        json={
            "subject": "Uploader cannot assign another member",
            "owner_membership_id": owner_id,
        },
    )
    assert member_assign_other.status_code == 403
    member_self_assign = client.post(
        "/api/notices/",
        headers=_auth(member_token),
        json={
            "subject": "Uploader may self-assign",
            "owner_membership_id": member_id,
        },
    )
    assert member_self_assign.status_code == 201, member_self_assign.text
    partner_assign_other = client.post(
        "/api/notices/",
        headers=_auth(partner_token),
        json={
            "subject": "Partner assignment without user-admin capability",
            "owner_membership_id": member_id,
        },
    )
    assert partner_assign_other.status_code == 201, partner_assign_other.text
    assert partner_assign_other.json()["owner_membership_id"] == member_id

    with get_session_factory()() as session:
        member = session.get(CompanyMembership, member_id)
        assert member is not None
        assert member.user is not None
        member.user.is_active = False
        session.commit()

    options_after_deactivation = client.get(
        "/api/notices/owners",
        headers=_auth(partner_token),
    )
    assert options_after_deactivation.status_code == 200
    assert member_id not in {row["membership_id"] for row in options_after_deactivation.json()}
    inactive_assignment = client.post(
        "/api/notices/",
        headers=_auth(partner_token),
        json={
            "subject": "Inactive users cannot own new notices",
            "owner_membership_id": member_id,
        },
    )
    assert inactive_assignment.status_code == 400


def test_notice_lock_compiles_for_postgresql_without_outer_join_lock(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-pg-lock")
    notice = _notice(
        client,
        str(boot["access_token"]),
        subject="PostgreSQL lock compilation",
    )
    with get_session_factory()() as session:
        company = session.get(Company, str(boot["company"]["id"]))
        membership = session.get(
            CompanyMembership,
            str(boot["membership"]["id"]),
        )
        assert company is not None
        assert membership is not None
        context = SessionContext(
            company=company,
            membership=membership,
            user=membership.user,
        )
        statement = _notice_statement(
            session=session,
            context=context,
            notice_id=str(notice["id"]),
            for_update=True,
        )
        sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE OF company_notices" in sql
    assert "LEFT OUTER JOIN company_memberships" not in sql
    assert "LEFT OUTER JOIN users" not in sql
    assert "LEFT OUTER JOIN matters" in sql
    assert "matters.id IS NULL" in sql


def test_notice_database_rejects_cross_tenant_owners_creators_and_links(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, "notice-db-tenant-a")
    boot_b = _bootstrap(client, "notice-db-tenant-b")
    company_a = str(boot_a["company"]["id"])
    membership_a = str(boot_a["membership"]["id"])
    membership_b = str(boot_b["membership"]["id"])
    matter_b = _matter(
        client,
        str(boot_b["access_token"]),
        "NOTICE-DB-TENANT-B",
    )
    notice_a = _notice(
        client,
        str(boot_a["access_token"]),
        subject="Tenant constrained notice",
    )

    with get_session_factory()() as session:
        session.add(
            CompanyNotice(
                company_id=company_a,
                owner_membership_id=membership_b,
                created_by_membership_id=membership_a,
                subject="Cross-tenant owner must fail",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        session.add(
            CompanyNotice(
                company_id=company_a,
                created_by_membership_id=None,
                subject="Creator provenance is mandatory",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        session.add(
            CompanyNotice(
                company_id=company_a,
                owner_membership_id=membership_a,
                created_by_membership_id=membership_b,
                subject="Cross-tenant creator must fail",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        session.add(
            CompanyNoticeMatterLink(
                company_id=company_a,
                notice_id=str(notice_a["id"]),
                matter_id=matter_b,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        session.add(
            CompanyNoticeMatterLink(
                company_id=str(boot_b["company"]["id"]),
                notice_id=str(notice_a["id"]),
                matter_id=matter_b,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_notice_database_rejects_noncanonical_direction_and_reply_states(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-db-state")
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    invalid_states: list[dict[str, object]] = [
        {"direction": "received", "sent_on": date(2026, 7, 15)},
        {"direction": "sent", "received_on": date(2026, 7, 15)},
        {"direction": "sent", "received_from": "Incompatible sender"},
        {"direction": "sent", "reply_required": True},
        {"direction": "received", "reply_sent": True, "reply_required": False},
        {
            "direction": "received",
            "reply_due_on": date(2026, 7, 20),
            "reply_required": False,
        },
        {
            "direction": "received",
            "reply_sent_on": date(2026, 7, 19),
            "reply_sent": False,
            "reply_required": False,
        },
    ]
    with get_session_factory()() as session:
        for index, invalid_state in enumerate(invalid_states):
            session.add(
                CompanyNotice(
                    company_id=company_id,
                    created_by_membership_id=membership_id,
                    subject=f"Invalid notice state {index}",
                    **invalid_state,
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()


def test_hard_matter_delete_cannot_globalize_a_restricted_notice(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-delete-policy")
    owner_token = str(boot["access_token"])
    admin_id, admin_token = _invite(
        client,
        owner_token=owner_token,
        slug=str(boot["_slug"]),
        role="partner",
    )
    restricted_matter = _matter(
        client,
        owner_token,
        "NOTICE-DELETE-RESTRICTED",
    )
    restrict = client.post(
        f"/api/matters/{restricted_matter}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restrict.status_code == 200, restrict.text
    wall = client.post(
        f"/api/matters/{restricted_matter}/access/walls",
        headers=_auth(owner_token),
        json={
            "excluded_membership_id": admin_id,
            "reason": "Notice delete-policy regression",
        },
    )
    assert wall.status_code == 200, wall.text
    notice = _notice(
        client,
        owner_token,
        subject="Must remain restricted after failed hard delete",
        matter_ids=[restricted_matter],
    )

    before = client.get("/api/notices/", headers=_auth(admin_token))
    assert before.status_code == 200, before.text
    assert notice["id"] not in {row["id"] for row in before.json()["notices"]}

    with get_session_factory()() as session:
        with pytest.raises(IntegrityError):
            session.execute(delete(Matter).where(Matter.id == restricted_matter))
            session.flush()
        session.rollback()

    owner_listing = client.get("/api/notices/", headers=_auth(owner_token))
    assert owner_listing.status_code == 200, owner_listing.text
    owner_row = next(row for row in owner_listing.json()["notices"] if row["id"] == notice["id"])
    assert [link["matter_id"] for link in owner_row["matter_links"]] == [restricted_matter]
    after = client.get("/api/notices/", headers=_auth(admin_token))
    assert after.status_code == 200, after.text
    assert notice["id"] not in {row["id"] for row in after.json()["notices"]}


def test_notice_owner_and_creator_composite_fks_explicitly_restrict_hard_delete(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, "notice-owner-delete")
    owner_token = str(boot["access_token"])
    assigned_id, assigned_token = _invite(
        client,
        owner_token=owner_token,
        slug=str(boot["_slug"]),
        role="member",
    )
    notice = _notice(
        client,
        assigned_token,
        subject="Owner membership deletion semantics",
        owner_membership_id=assigned_id,
    )

    # Memberships are soft-deactivated in normal operation.  Both the simple
    # and tenant-composite Notice FKs explicitly reject a hard delete so owner
    # and creator provenance cannot silently disappear.
    with get_session_factory()() as session:
        with pytest.raises(IntegrityError):
            session.execute(delete(CompanyMembership).where(CompanyMembership.id == assigned_id))
            session.flush()
        session.rollback()

    detail = client.get(
        f"/api/notices/{notice['id']}",
        headers=_auth(owner_token),
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["owner_membership_id"] == assigned_id
    with get_session_factory()() as session:
        stored = session.get(CompanyNotice, str(notice["id"]))
        assert stored is not None
        assert stored.created_by_membership_id == assigned_id


def test_notice_download_openapi_declares_binary_contract(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    operation = response.json()["paths"]["/api/notices/{notice_id}/download"]["get"]
    schema = operation["responses"]["200"]["content"]["application/octet-stream"]["schema"]
    assert schema == {"type": "string", "format": "binary"}
