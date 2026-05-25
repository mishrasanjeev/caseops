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

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.test_auth_company import auth_headers, bootstrap_company

REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _login(client: TestClient, email: str, password: str, slug: str) -> str:
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "company_slug": slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _invite_member(
    client: TestClient,
    owner_headers: dict[str, str],
    *,
    email: str,
    role: str = "member",
) -> dict:
    resp = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Comms Member",
            "email": email,
            "password": "MemberPass123!",
            "role": role,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _email_payload(message_id: str = "msg-001") -> dict:
    return {
        "provider": "manual",
        "provider_message_id": message_id,
        "sender_email": "client@example.in",
        "sender_name": "Client Sender",
        "to_recipients": ["lawyer@asterlegal.in"],
        "cc_recipients": ["associate@asterlegal.in"],
        "subject": "Filing instructions",
        "received_at": "2026-05-15T10:30:00Z",
        "body_preview": "Client sent filing instructions and a notice attachment.",
        "body_text": (
            "Privileged filing instructions. Full text must live in "
            "document storage, not the audit metadata."
        ),
        "attachments": [
            {
                "filename": "notice.pdf",
                "content_type": "application/pdf",
                "content_base64": base64.b64encode(
                    b"%PDF-1.4\n% inbound email attachment\n"
                ).decode("ascii"),
            }
        ],
    }


def _calendar_invite_payload(
    message_id: str,
    *,
    subject: str = "Invitation: Strategy conference",
    body_preview: str = (
        "Calendar invitation for 2026-06-15 at 10:30 AM. "
        "Venue: Courtroom 4. Please attend with the case file."
    ),
) -> dict:
    return {
        "provider": "manual",
        "provider_message_id": message_id,
        "sender_email": "client@example.in",
        "sender_name": "Client Sender",
        "to_recipients": ["lawyer@asterlegal.in"],
        "subject": subject,
        "received_at": "2026-05-15T10:30:00Z",
        "body_preview": body_preview,
        "attachments": [],
    }


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


def test_inbound_email_import_stores_preview_attachments_and_redacted_audit(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "G116-001")

    payload = _email_payload()
    resp = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=payload,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["duplicate"] is False
    assert body["match_basis"] == "explicit_matter_selection"
    assert body["automation_mode"] == "manual_only"
    assert body["communication"]["direction"] == "inbound"
    assert body["communication"]["channel"] == "email"
    assert body["communication"]["subject"] == "Filing instructions"
    assert body["communication"]["recipient_email"] == "client@example.in"
    assert body["communication"]["body"] == (
        "Client sent filing instructions and a notice attachment."
    )
    assert body["body_attachment_id"] in body["attachment_ids"]
    assert len(body["attachment_ids"]) == 2
    assert len(body["processing_job_ids"]) == 2

    from caseops_api.db.models import (
        AuditEvent,
        Communication,
        DocumentProcessingJob,
        MatterAttachment,
    )
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        comm = session.get(Communication, body["communication"]["id"])
        assert comm is not None
        assert comm.external_message_id == "manual:msg-001"
        assert comm.metadata_json["sender_email"] == "client@example.in"
        assert comm.metadata_json["to_recipients"] == ["lawyer@asterlegal.in"]
        assert comm.metadata_json["cc_recipients"] == ["associate@asterlegal.in"]
        assert comm.metadata_json["bcc_recipient_count"] == 0
        assert comm.metadata_json["match_basis"] == "explicit_matter_selection"
        assert comm.metadata_json["automation_mode"] == "manual_only"
        assert comm.body != payload["body_text"]

        attachments = list(
            session.scalars(
                select(MatterAttachment).where(
                    MatterAttachment.id.in_(body["attachment_ids"])
                )
            )
        )
        assert {a.original_filename for a in attachments} == {
            "email-body.txt",
            "notice.pdf",
        }
        assert all(a.matter_id == matter_id for a in attachments)
        assert all("/matters/" in a.storage_key for a in attachments)
        assert all(a.document_type == "correspondence" for a in attachments)

        job_count = session.scalar(
            select(func.count())
            .select_from(DocumentProcessingJob)
            .where(DocumentProcessingJob.attachment_id.in_(body["attachment_ids"]))
        )
        assert job_count == 2

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "inbound_email.imported",
                AuditEvent.target_id == comm.id,
            )
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["provider"] == "manual"
        assert metadata["match_basis"] == "explicit_matter_selection"
        assert metadata["automation_mode"] == "manual_only"
        assert metadata["attachment_count"] == 1
        audit_surface = audit.metadata_json or ""
        assert "Privileged filing instructions" not in audit_surface
        assert "inbound email attachment" not in audit_surface
        assert "msg-001" not in audit_surface


def test_inbound_email_import_is_idempotent_by_provider_message_and_scope(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "G116-IDEMP")
    other_matter_id = _create_matter(client, headers, "G116-IDEMP-OTHER")
    payload = _email_payload("thread-777")

    first = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=payload,
    )
    second = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json={**payload, "subject": "Duplicate should not overwrite"},
    )
    other_scope = client.post(
        f"/api/matters/{other_matter_id}/communications/import-email",
        headers=headers,
        json={**payload, "subject": "Same provider id, different matter"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert other_scope.status_code == 200, other_scope.text
    first_body = first.json()
    second_body = second.json()
    other_body = other_scope.json()
    assert second_body["duplicate"] is True
    assert second_body["communication"]["id"] == first_body["communication"]["id"]
    assert second_body["attachment_ids"] == first_body["attachment_ids"]
    assert other_body["duplicate"] is False
    assert other_body["communication"]["id"] != first_body["communication"]["id"]
    assert other_body["attachment_ids"] != first_body["attachment_ids"]

    from caseops_api.db.models import Communication, MatterAttachment
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        comm_count = session.scalar(
            select(func.count())
            .select_from(Communication)
            .where(
                Communication.matter_id == matter_id,
                Communication.external_message_id == "manual:thread-777",
            )
        )
        assert comm_count == 1
        scoped_comm_count = session.scalar(
            select(func.count())
            .select_from(Communication)
            .where(Communication.external_message_id == "manual:thread-777")
        )
        assert scoped_comm_count == 2
        attachment_count = session.scalar(
            select(func.count())
            .select_from(MatterAttachment)
            .where(MatterAttachment.matter_id == matter_id)
        )
        assert attachment_count == 2
        other_attachment_count = session.scalar(
            select(func.count())
            .select_from(MatterAttachment)
            .where(MatterAttachment.matter_id == other_matter_id)
        )
        assert other_attachment_count == 2


def test_unified_communication_timeline_mixes_sources_and_redacts_payloads(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADP05-MIXED")

    old_comm = client.post(
        f"/api/matters/{matter_id}/communications",
        headers=headers,
        json={
            "channel": "phone",
            "direction": "outbound",
            "subject": "Intro call",
            "body": "Called the client to confirm receipt.",
            "occurred_at": "2026-05-15T09:00:00Z",
        },
    )
    assert old_comm.status_code == 200, old_comm.text
    payload = _email_payload("timeline-mixed")
    imported = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=payload,
    )
    assert imported.status_code == 200, imported.text
    note = client.post(
        f"/api/matters/{matter_id}/notes",
        headers=headers,
        json={"body": "Internal note for firm-only follow-up."},
    )
    assert note.status_code == 200, note.text

    timeline = client.get(
        f"/api/matters/{matter_id}/communications/timeline",
        headers=headers,
    )
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()
    assert body["matter_id"] == matter_id
    assert body["filter"] == "all"

    items = body["items"]
    item_types = {item["item_type"] for item in items}
    assert {
        "platform_message",
        "imported_email",
        "internal_note",
        "attachment",
    }.issubset(item_types)
    occurred = [item["occurred_at"] for item in items]
    assert occurred == sorted(occurred)

    imported_item = next(
        item for item in items if item["item_type"] == "imported_email"
    )
    assert imported_item["visibility"] == "imported_email"
    assert imported_item["preview"] == payload["body_preview"]
    assert imported_item["thread_key"] == "manual:timeline-mixed"
    assert imported_item["metadata"]["body_is_preview"] is True

    attachment_items = [
        item for item in items if item["item_type"] == "attachment"
    ]
    assert len(attachment_items) == 2
    assert all(item["attachment"] for item in attachment_items)
    assert all(item["visibility"] == "imported_email" for item in attachment_items)
    assert any(
        item["metadata"]["is_email_body_attachment"] is True
        for item in attachment_items
    )

    response_surface = json.dumps(body)
    assert payload["body_text"] not in response_surface
    assert payload["attachments"][0]["content_base64"] not in response_surface
    assert "storage_key" not in response_surface
    assert "sha256" not in response_surface
    assert "extracted_text" not in response_surface


def test_unified_communication_timeline_filters_and_visibility_labels(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADP05-FILTER")

    client.post(
        f"/api/matters/{matter_id}/communications",
        headers=headers,
        json={
            "channel": "meeting",
            "body": "Platform meeting note.",
            "occurred_at": "2026-05-15T08:00:00Z",
        },
    )
    client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=_email_payload("thread-777"),
    )
    client.post(
        f"/api/matters/{matter_id}/notes",
        headers=headers,
        json={"body": "Internal note should stay internal."},
    )

    email = client.get(
        f"/api/matters/{matter_id}/communications/timeline?filter=email",
        headers=headers,
    )
    assert email.status_code == 200, email.text
    email_items = email.json()["items"]
    assert email_items
    assert all(
        item["visibility"] == "imported_email" or item["channel"] == "email"
        for item in email_items
    )
    assert {
        item["thread_key"] for item in email_items if item["thread_key"]
    } == {"manual:thread-777"}

    attachments = client.get(
        f"/api/matters/{matter_id}/communications/timeline?filter=attachments",
        headers=headers,
    )
    assert attachments.status_code == 200, attachments.text
    assert {
        item["item_type"] for item in attachments.json()["items"]
    } == {"attachment"}

    notes = client.get(
        f"/api/matters/{matter_id}/communications/timeline?filter=notes",
        headers=headers,
    )
    assert notes.status_code == 200, notes.text
    assert any(item["item_type"] == "internal_note" for item in notes.json()["items"])

    from caseops_api.db.models import MatterAttachment, PortalUser, PortalUserRole
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        portal_user = PortalUser(
            company_id=bootstrap["company"]["id"],
            email="oc-timeline@example.in",
            full_name="Outside Counsel",
            role=PortalUserRole.OUTSIDE_COUNSEL,
        )
        session.add(portal_user)
        session.flush()
        session.add(
            MatterAttachment(
                matter_id=matter_id,
                uploaded_by_membership_id=None,
                submitted_by_portal_user_id=portal_user.id,
                original_filename="oc-work-product.pdf",
                storage_key="test-only/no-payload",
                content_type="application/pdf",
                size_bytes=128,
                sha256_hex="1" * 64,
            )
        )
        session.commit()

    refreshed = client.get(
        f"/api/matters/{matter_id}/communications/timeline?filter=attachments",
        headers=headers,
    )
    assert refreshed.status_code == 200, refreshed.text
    assert any(
        item["visibility"] == "outside_counsel_visible"
        for item in refreshed.json()["items"]
    )


def test_unified_communication_timeline_enforces_tenant_and_matter_access(
    client: TestClient,
) -> None:
    company_a = bootstrap_company(client)
    headers_a = auth_headers(str(company_a["access_token"]))
    matter_a = _create_matter(client, headers_a, "ADP05-TENANT-A")
    client.post(
        f"/api/matters/{matter_a}/communications",
        headers=headers_a,
        json={"channel": "note", "body": "Tenant A timeline item"},
    )
    client.cookies.clear()

    resp_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Timeline LLP",
            "company_slug": "other-timeline",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-timeline.example",
            "owner_password": "OtherStrong!234",
        },
    )
    assert resp_b.status_code == 200, resp_b.text
    headers_b = auth_headers(str(resp_b.json()["access_token"]))
    client.cookies.clear()

    leak = client.get(
        f"/api/matters/{matter_a}/communications/timeline",
        headers=headers_b,
    )
    assert leak.status_code == 404

    slug = "adp05-access"
    bootstrap = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "ADP05 Access LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Access Owner",
            "owner_email": "owner@adp05-access.example",
            "owner_password": "OwnerStrong!234",
        },
    ).json()
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    member = _invite_member(
        client,
        owner_headers,
        email="member@adp05-access.example",
    )
    member_token = _login(
        client,
        "member@adp05-access.example",
        "MemberPass123!",
        slug,
    )
    member_headers = auth_headers(member_token)

    restricted_matter = _create_matter(client, owner_headers, "ADP05-REST")
    assert client.post(
        f"/api/matters/{restricted_matter}/access/restricted",
        headers=owner_headers,
        json={"restricted": True},
    ).status_code == 200
    restricted = client.get(
        f"/api/matters/{restricted_matter}/communications/timeline",
        headers=member_headers,
    )
    assert restricted.status_code == 404

    walled_matter = _create_matter(client, owner_headers, "ADP05-WALL")
    assert client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=owner_headers,
        json={"excluded_membership_id": member["membership_id"]},
    ).status_code == 200
    walled = client.get(
        f"/api/matters/{walled_matter}/communications/timeline",
        headers=member_headers,
    )
    assert walled.status_code == 404

    team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Timeline Team", "slug": "timeline-team"},
    )
    assert team.status_code == 201, team.text
    team_matter = _create_matter(client, owner_headers, "ADP05-TEAM")
    assert client.patch(
        f"/api/matters/{team_matter}",
        headers=owner_headers,
        json={"team_id": team.json()["id"]},
    ).status_code == 200
    assert client.put(
        "/api/teams/scoping",
        headers=owner_headers,
        json={"enabled": True},
    ).status_code == 200
    team_denied = client.get(
        f"/api/matters/{team_matter}/communications/timeline",
        headers=member_headers,
    )
    assert team_denied.status_code == 404


def test_internal_matter_notes_do_not_leak_to_portal_communications(
    client: TestClient,
) -> None:
    from tests.test_portal_matters import (
        _bootstrap,
        _invite_client_portal_user,
        _seed_matter,
        _verify_and_session,
    )

    boot = _bootstrap(
        client,
        slug="adp05-portal",
        email="owner@adp05-portal.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="ADP05-PORTAL")
    headers = auth_headers(token)
    note = client.post(
        f"/api/matters/{matter_id}/notes",
        headers=headers,
        json={"body": "Internal ADP-05 note hidden from portal."},
    )
    assert note.status_code == 200, note.text

    _, debug = _invite_client_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    listing = client.get(f"/api/portal/matters/{matter_id}/communications")
    assert listing.status_code == 200, listing.text
    surface = json.dumps(listing.json())
    assert "Internal ADP-05 note hidden from portal." not in surface


def test_inbound_email_import_rejects_oversized_base64_before_storage(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "G116-SIZE")

    from caseops_api.core.settings import get_settings
    from caseops_api.db.models import Communication, DocumentProcessingJob, MatterAttachment
    from caseops_api.db.session import get_session_factory

    settings = get_settings()
    original_max = settings.max_attachment_size_bytes
    settings.max_attachment_size_bytes = 4
    try:
        payload = _email_payload("oversized-base64")
        payload["body_text"] = None
        payload["attachments"][0]["content_base64"] = "A" * 32
        resp = client.post(
            f"/api/matters/{matter_id}/communications/import-email",
            headers=headers,
            json=payload,
        )
    finally:
        settings.max_attachment_size_bytes = original_max

    assert resp.status_code == 413, resp.text
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Communication)
                .where(Communication.matter_id == matter_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterAttachment)
                .where(MatterAttachment.matter_id == matter_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(DocumentProcessingJob)
            )
            == 0
        )


def test_inbound_email_import_does_not_cross_tenant_source_matter(
    client: TestClient,
) -> None:
    company_a = bootstrap_company(client)
    headers_a = auth_headers(str(company_a["access_token"]))
    matter_a = _create_matter(client, headers_a, "G116-TENANT-A")
    import_a = client.post(
        f"/api/matters/{matter_a}/communications/import-email",
        headers=headers_a,
        json=_email_payload("tenant-shared"),
    )
    assert import_a.status_code == 200, import_a.text
    client.cookies.clear()

    resp_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Inbound LLP",
            "company_slug": "other-inbound",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-inbound.example",
            "owner_password": "OtherStrong!234",
        },
    )
    assert resp_b.status_code == 200, resp_b.text
    headers_b = auth_headers(str(resp_b.json()["access_token"]))
    matter_b = _create_matter(client, headers_b, "G116-TENANT-B")
    import_b = client.post(
        f"/api/matters/{matter_b}/communications/import-email",
        headers=headers_b,
        json=_email_payload("tenant-shared"),
    )
    assert import_b.status_code == 200, import_b.text
    assert import_b.json()["duplicate"] is False
    assert import_b.json()["communication"]["id"] != import_a.json()["communication"]["id"]
    client.cookies.clear()

    leak = client.post(
        f"/api/matters/{matter_a}/communications/import-email",
        headers=headers_b,
        json=_email_payload("tenant-leak"),
    )
    assert leak.status_code == 404

    from caseops_api.db.models import Communication
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Communication)
                .where(Communication.external_message_id == "manual:tenant-shared")
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(Communication)
                .where(Communication.external_message_id == "manual:tenant-leak")
            )
            == 0
        )


def test_inbound_email_import_respects_restricted_wall_and_team_scoping(
    client: TestClient,
) -> None:
    slug = "g116-access"
    bootstrap = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "G116 Access LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Access Owner",
            "owner_email": "owner@g116-access.example",
            "owner_password": "OwnerStrong!234",
        },
    ).json()
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    member = _invite_member(
        client,
        owner_headers,
        email="member@g116-access.example",
    )
    member_token = _login(
        client,
        "member@g116-access.example",
        "MemberPass123!",
        slug,
    )
    member_headers = auth_headers(member_token)

    restricted_matter = _create_matter(client, owner_headers, "G116-REST")
    restricted = client.post(
        f"/api/matters/{restricted_matter}/access/restricted",
        headers=owner_headers,
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    denied = client.post(
        f"/api/matters/{restricted_matter}/communications/import-email",
        headers=member_headers,
        json=_email_payload("restricted-denied"),
    )
    assert denied.status_code == 404

    walled_matter = _create_matter(client, owner_headers, "G116-WALL")
    wall = client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=owner_headers,
        json={"excluded_membership_id": member["membership_id"]},
    )
    assert wall.status_code == 200, wall.text
    walled = client.post(
        f"/api/matters/{walled_matter}/communications/import-email",
        headers=member_headers,
        json=_email_payload("walled-denied"),
    )
    assert walled.status_code == 404

    team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Litigation", "slug": "litigation"},
    )
    assert team.status_code == 201, team.text
    team_matter = _create_matter(client, owner_headers, "G116-TEAM")
    assign = client.patch(
        f"/api/matters/{team_matter}",
        headers=owner_headers,
        json={"team_id": team.json()["id"]},
    )
    assert assign.status_code == 200, assign.text
    scope = client.put(
        "/api/teams/scoping",
        headers=owner_headers,
        json={"enabled": True},
    )
    assert scope.status_code == 200, scope.text
    team_denied = client.post(
        f"/api/matters/{team_matter}/communications/import-email",
        headers=member_headers,
        json=_email_payload("team-denied"),
    )
    assert team_denied.status_code == 404


def test_email_invitation_candidate_review_creates_internal_calendar_event(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADP19-001")

    imported = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=_calendar_invite_payload("invite-001"),
    )
    assert imported.status_code == 200, imported.text
    communication_id = imported.json()["communication"]["id"]

    extracted = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=headers,
        json={"matter_id": matter_id},
    )
    assert extracted.status_code == 200, extracted.text
    body = extracted.json()
    assert body["examined_count"] == 1
    assert body["created_count"] == 1
    assert body["duplicate_count"] == 0
    candidate = body["candidates"][0]
    assert candidate["communication_id"] == communication_id
    assert candidate["status"] == "needs_review"
    assert candidate["detected_title"] == "Strategy conference"
    assert candidate["detected_start_at"].startswith("2026-06-15T10:30:00")
    assert candidate["detected_location"] == "Courtroom 4"
    assert candidate["confidence_band"] == "high"
    assert len(candidate["source_preview"]) <= 280
    assert "body_text" not in extracted.text
    assert "storage_key" not in extracted.text

    approved = client.patch(
        f"/api/calendar/email-invitation-candidates/{candidate['id']}",
        headers=headers,
        json={"action": "approve"},
    )
    assert approved.status_code == 200, approved.text
    reviewed = approved.json()
    assert reviewed["status"] == "approved_created"
    assert reviewed["created_deadline_id"] is not None
    assert reviewed["reviewed_by_membership_id"] is not None
    assert reviewed["reviewed_at"] is not None

    event_resp = client.get(
        "/api/calendar/events",
        headers=headers,
        params={"from": "2026-06-01", "to": "2026-06-30", "kinds": ["deadline"]},
    )
    assert event_resp.status_code == 200, event_resp.text
    events = event_resp.json()["events"]
    assert any(
        event["title"] == "Strategy conference"
        and event["id"] == f"deadline:{reviewed['created_deadline_id']}"
        for event in events
    )

    from caseops_api.db.models import AuditEvent, MatterDeadline
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        deadline = session.get(MatterDeadline, reviewed["created_deadline_id"])
        assert deadline is not None
        assert deadline.source == "email_invitation"
        assert deadline.source_ref_type == "communication"
        assert deadline.source_ref_id == communication_id
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_(
                        [
                            "calendar.email_candidate.extracted",
                            "calendar.email_candidate.approved",
                        ]
                    )
                )
            )
        )
        assert len(audits) == 2
        audit_blob = "\n".join(str(row.metadata_json or "") for row in audits)
        assert "Strategy conference" not in audit_blob
        assert "Courtroom 4" not in audit_blob
        assert "client@example.in" not in audit_blob


def test_email_invitation_candidate_duplicates_are_idempotent(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADP19-DUP")

    for suffix in ("a", "b"):
        imported = client.post(
            f"/api/matters/{matter_id}/communications/import-email",
            headers=headers,
            json=_calendar_invite_payload(f"invite-dup-{suffix}"),
        )
        assert imported.status_code == 200, imported.text

    first = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=headers,
        json={"matter_id": matter_id},
    )
    assert first.status_code == 200, first.text
    candidates = sorted(first.json()["candidates"], key=lambda item: item["status"])
    statuses = {item["status"] for item in candidates}
    assert statuses == {"duplicate_skipped", "needs_review"}
    duplicate = next(
        item for item in first.json()["candidates"] if item["status"] == "duplicate_skipped"
    )
    assert duplicate["duplicate_of_candidate_id"] is not None

    second = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=headers,
        json={"matter_id": matter_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["created_count"] == 0
    assert len(second.json()["candidates"]) == 2

    duplicate_approval = client.patch(
        f"/api/calendar/email-invitation-candidates/{duplicate['id']}",
        headers=headers,
        json={"action": "approve"},
    )
    assert duplicate_approval.status_code == 409

    from caseops_api.db.models import EmailCalendarCandidate, MatterDeadline
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EmailCalendarCandidate)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterDeadline)
                .where(MatterDeadline.source == "email_invitation")
            )
            == 0
        )


def test_email_invitation_candidate_rejection_does_not_create_event(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "ADP19-REJ")
    imported = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=headers,
        json=_calendar_invite_payload("invite-reject"),
    )
    assert imported.status_code == 200, imported.text

    extracted = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=headers,
        json={"matter_id": matter_id},
    )
    assert extracted.status_code == 200, extracted.text
    candidate_id = extracted.json()["candidates"][0]["id"]
    rejected = client.patch(
        f"/api/calendar/email-invitation-candidates/{candidate_id}",
        headers=headers,
        json={"action": "reject"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["created_deadline_id"] is None

    from caseops_api.db.models import MatterDeadline
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MatterDeadline)
                .where(MatterDeadline.source == "email_invitation")
            )
            == 0
        )


def test_email_invitation_candidates_respect_matter_access_boundaries(
    client: TestClient,
) -> None:
    slug = "adp19-access"
    bootstrap = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "ADP19 Access LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Access Owner",
            "owner_email": "owner@adp19-access.example",
            "owner_password": "OwnerStrong!234",
        },
    ).json()
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    member = _invite_member(
        client,
        owner_headers,
        email="member@adp19-access.example",
    )
    member_headers = auth_headers(
        _login(client, "member@adp19-access.example", "MemberPass123!", slug)
    )
    matter_id = _create_matter(client, owner_headers, "ADP19-WALL")
    imported = client.post(
        f"/api/matters/{matter_id}/communications/import-email",
        headers=owner_headers,
        json=_calendar_invite_payload("invite-walled"),
    )
    assert imported.status_code == 200, imported.text
    extracted = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=owner_headers,
        json={"matter_id": matter_id},
    )
    assert extracted.status_code == 200, extracted.text
    candidate_id = extracted.json()["candidates"][0]["id"]

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=owner_headers,
        json={"excluded_membership_id": member["membership_id"]},
    )
    assert wall.status_code == 200, wall.text
    denied_extract = client.post(
        "/api/calendar/email-invitation-candidates/extract",
        headers=member_headers,
        json={"matter_id": matter_id},
    )
    assert denied_extract.status_code == 404
    hidden_list = client.get(
        "/api/calendar/email-invitation-candidates",
        headers=member_headers,
    )
    assert hidden_list.status_code == 200, hidden_list.text
    assert hidden_list.json()["candidates"] == []
    denied_review = client.patch(
        f"/api/calendar/email-invitation-candidates/{candidate_id}",
        headers=member_headers,
        json={"action": "approve"},
    )
    assert denied_review.status_code == 404


def test_inbound_email_import_has_no_autonomous_sweep_surface() -> None:
    service_src = (REPO_ROOT / Path(
        "apps/api/src/caseops_api/services/communications.py"
    )).read_text(encoding="utf-8")
    route_src = (REPO_ROOT / Path(
        "apps/api/src/caseops_api/api/routes/communications.py"
    )).read_text(encoding="utf-8")
    combined = service_src + "\n" + route_src
    assert "mailbox_sweep" not in combined
    assert "sync_mailbox" not in combined
    assert "poll_inbound" not in combined
    assert '"automation_mode": "manual_only"' in combined


def test_g116_docs_mark_inbound_email_foundation_partial() -> None:
    future = (REPO_ROOT / "docs/FUTURE_WORKPLAN_2026-05-14.md").read_text(
        encoding="utf-8"
    )
    strict = (REPO_ROOT / "docs/STRICT_ENTERPRISE_GAP_TASKLIST.md").read_text(
        encoding="utf-8"
    )
    assert "`G-116` inbound email ingest" in future
    assert "manual inbound email import foundation" in future
    assert "`WTD-12.3b` `Partially implemented`" in strict
    assert "explicit matter selection" in strict
