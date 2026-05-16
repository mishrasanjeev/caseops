"""BUG-032 (Hari 2026-05-09) — manual ``POST /api/matters/{id}/court-orders``.

Hari's reported symptom: the matter Hearings page had no "Add order"
affordance, so the Linked-order list on Documents was effectively
unavailable for any matter that hadn't been court-synced. Backend
already had ``MatterCourtOrder``, the matter-attachment upload route,
and the workspace fetch — the gap was a manual create endpoint.

These tests cover the create endpoint contract:
  - Metadata-only create succeeds with the required fields.
  - Optional pre-uploaded attachment links via ``order_attachment_id``.
  - Cross-matter (and therefore cross-tenant) attachment IDs are
    rejected with 400 — no linkability across matters.
  - The created order appears in the matter workspace's
    ``court_orders`` array (the documents page Linked-order selector
    feeds off the same array).
  - Tenant isolation: a tenant B user cannot create an order on
    tenant A's matter (404 — same opacity the PATCH path enforces).
  - An audit + activity event is recorded.
  - Notification rule fires when an attachment is linked.
"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    InAppNotification,
    MatterActivity,
    MatterCourtOrder,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> dict:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"BUG-032 matter {code}",
            "matter_code": code,
            "practice_area": "criminal",
            "forum_level": "high_court",
            "status": "intake",
            "court_name": "Delhi High Court",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _upload_attachment(
    client: TestClient,
    token: str,
    matter_id: str,
    *,
    filename: str = "order.pdf",
    body: bytes = b"%PDF-1.4\nfake order pdf bytes\n%%EOF",
) -> dict:
    resp = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        data={"document_type": "order_judgment"},
        files={"file": (filename, body, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _new_order_payload(**overrides) -> dict:
    base = {
        "order_date": date.today().isoformat(),
        "title": "Stay continued — bail application",
        "summary": "Honble Court continued the interim stay until next hearing.",
        "source": "manual_upload",
        "order_kind": "interim_order",
        "is_interim_order": True,
        "stay_status": "continued",
    }
    base.update(overrides)
    return base


def test_create_court_order_metadata_only_succeeds_and_appears_in_workspace(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "B032-META")

    create = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json=_new_order_payload(),
    )
    assert create.status_code == 200, create.text
    record = create.json()
    assert record["title"] == "Stay continued — bail application"
    assert record["source"] == "manual_upload"
    assert record["order_attachment_id"] is None
    assert record["order_kind"] == "interim_order"
    assert record["is_interim_order"] is True
    assert record["stay_status"] == "continued"
    order_id = record["id"]

    # The workspace fetch must include the new order — that's what
    # the documents-page Linked-order selector feeds from. No
    # additional plumbing should be required (Matter.court_orders
    # is selectinload'd on the workspace query).
    workspace = client.get(
        f"/api/matters/{matter['id']}/workspace", headers=auth_headers(token),
    )
    assert workspace.status_code == 200
    workspace_orders = workspace.json()["court_orders"]
    assert any(o["id"] == order_id for o in workspace_orders)


def test_create_court_order_with_uploaded_attachment_links_cleanly(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "B032-ATTACH")

    attachment = _upload_attachment(client, token, matter["id"])
    create = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json=_new_order_payload(order_attachment_id=attachment["id"]),
    )
    assert create.status_code == 200, create.text
    assert create.json()["order_attachment_id"] == attachment["id"]


def test_create_court_order_rejects_attachment_from_other_matter(
    client: TestClient,
) -> None:
    """Cross-matter linkability would let an admin reference another
    matter's PDF as the order's evidence. Same-tenant cross-matter
    is the most likely accident; the validator rejects with 400.
    Cross-tenant cross-matter is impossible because the attachment
    upload itself enforces tenant scoping."""
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter_a = _create_matter(client, token, "B032-A")
    matter_b = _create_matter(client, token, "B032-B")
    # Upload an attachment on matter A.
    attach_a = _upload_attachment(client, token, matter_a["id"])

    # Try to attach matter A's attachment to matter B's new order.
    create = client.post(
        f"/api/matters/{matter_b['id']}/court-orders",
        headers=auth_headers(token),
        json=_new_order_payload(order_attachment_id=attach_a["id"]),
    )
    assert create.status_code == 400, create.text


def _bootstrap_with_slug(
    client: TestClient, *, slug: str, email: str
) -> dict:
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "BUG-032 Owner",
            "owner_email": email,
            "owner_password": "OwnerPass1234!",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_court_order_enforces_tenant_isolation(
    client: TestClient,
) -> None:
    boot_a = _bootstrap_with_slug(
        client, slug="b032-tenant-a", email="a@example.com",
    )
    boot_b = _bootstrap_with_slug(
        client, slug="b032-tenant-b", email="b@example.com",
    )
    token_a = str(boot_a["access_token"])
    token_b = str(boot_b["access_token"])
    matter_a = _create_matter(client, token_a, "B032-TA-1")

    # Tenant B user attempts to POST on tenant A's matter — 404 (the
    # matter is invisible, mirroring the PATCH path).
    cross = client.post(
        f"/api/matters/{matter_a['id']}/court-orders",
        headers=auth_headers(token_b),
        json=_new_order_payload(),
    )
    assert cross.status_code == 404, cross.text

    factory = get_session_factory()
    with factory() as session:
        rows = list(session.scalars(select(MatterCourtOrder)))
        # No order was created on tenant A's matter from tenant B's
        # call.
        assert all(r.matter_id != matter_a["id"] for r in rows) or rows == []


def test_create_court_order_records_audit_and_activity(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "B032-AUDIT")
    create = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json=_new_order_payload(),
    )
    assert create.status_code == 200
    order_id = create.json()["id"]

    factory = get_session_factory()
    with factory() as session:
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "matter_court_order.created",
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].target_id == order_id
        # Tenant scoping on the audit row.
        assert audits[0].company_id == boot["company"]["id"]

        activities = list(
            session.scalars(
                select(MatterActivity).where(
                    MatterActivity.matter_id == matter["id"],
                    MatterActivity.event_type == "court_order_added",
                )
            )
        )
        assert len(activities) == 1


def test_create_court_order_with_attachment_fires_in_app_notification(
    client: TestClient,
) -> None:
    """Mirror the attachment-upload path: when an attachment is
    linked, a `new_order_uploaded` notification rule should fire so
    other workspace members see the order in their notifications.
    Without an explicit rule the call is a no-op (the rule list is
    empty); with a tenant rule enabled, an InAppNotification row is
    written for matched recipients."""
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "B032-NOTIF")

    # Owner enables a company-wide notification rule for new orders
    # routed to in-app channel.
    rule = client.post(
        "/api/notification-rules",
        headers=auth_headers(token),
        json={
            "scope_type": "company",
            "event_type": "new_order_uploaded",
            "channels": ["in_app"],
            "enabled": True,
        },
    )
    assert rule.status_code == 200, rule.text

    attach = _upload_attachment(client, token, matter["id"])

    # Snapshot in-app notifications BEFORE the create; the upload
    # itself doesn't link, so it shouldn't have fired one yet.
    factory = get_session_factory()
    with factory() as session:
        before = list(session.scalars(select(InAppNotification)))

    create = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json=_new_order_payload(order_attachment_id=attach["id"]),
    )
    assert create.status_code == 200, create.text

    with factory() as session:
        after = list(session.scalars(select(InAppNotification)))
        assert len(after) > len(before), (
            "creating a court order linked to an attachment must fire "
            "the new_order_uploaded notification rule"
        )


def test_create_court_order_validates_required_fields(client: TestClient) -> None:
    """Pydantic validation: missing required fields surface as 422.
    Title must be ≥2 chars; summary ≥2 chars; order_date is required."""
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _create_matter(client, token, "B032-VALID")

    # Missing order_date -> 422
    bad = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json={"title": "X", "summary": "Y", "source": "manual_upload"},
    )
    assert bad.status_code == 422
    # Empty title -> 422 (min_length=2)
    bad2 = client.post(
        f"/api/matters/{matter['id']}/court-orders",
        headers=auth_headers(token),
        json={
            "order_date": "2026-05-10",
            "title": "",
            "summary": "ok",
            "source": "manual_upload",
        },
    )
    assert bad2.status_code == 422
