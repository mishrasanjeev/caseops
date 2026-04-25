"""Phase C-3 (2026-04-25, MOD-TS-016) — outside-counsel portal surface.

Covers FT-074 (upload + invoice submission, cross-counsel isolation),
FT-075 (revoke invalidates active session), and the supporting role +
tenant gates that make either of those meaningful.

Tests in this file:

- list_oc_assigned_matters scopes to role='outside_counsel'
- get_oc_assigned_matter 404 on cross-tenant
- /oc/* endpoints 404 when the calling portal user has only role='client'
- work-product upload lands a MatterAttachment with
  submitted_by_portal_user_id
- list_oc_work_product hides another OC's uploads when
  oc_cross_visibility_enabled=False (default)
- list_oc_work_product reveals other OC uploads when the flag is on
- invoice submission lands status='needs_review'
- time entry submission lands the row with submitted_by_portal_user_id
- portal CSRF gate fires on every mutation (no token -> 403)
- revoking the grant invalidates further /oc/* calls (FT-075)
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    InvoiceStatus,
    Matter,
    MatterAttachment,
    MatterInvoice,
    MatterPortalGrant,
    MatterTimeEntry,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_portal_matters import (
    _bootstrap,
    _portal_csrf_headers,
    _seed_matter,
    _verify_and_session,
)


def _invite_oc_portal_user(
    client: TestClient,
    owner_token: str,
    matter_id: str,
    *,
    email: str = "oc@portal.example",
) -> tuple[str, str]:
    resp = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(owner_token),
        json={
            "email": email,
            "full_name": "OC Counsel",
            "role": "outside_counsel",
            "matter_ids": [matter_id],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["portal_user"]["id"], body["debug_token"]


def _set_oc_cross_visibility(matter_id: str, enabled: bool) -> None:
    Session = get_session_factory()
    with Session() as session:
        m = session.get(Matter, matter_id)
        assert m is not None
        m.oc_cross_visibility_enabled = enabled
        session.commit()


# ---------- list assigned matters / role gate ----------


def test_oc_lists_only_assigned_matters(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-list", email="c3-list@firm.example")
    company_id = boot["company"]["id"]
    token = str(boot["access_token"])
    granted = _seed_matter(company_id, code="C3-OC-1")
    _ungranted = _seed_matter(company_id, code="C3-OC-2")
    _, debug = _invite_oc_portal_user(client, token, granted)
    _verify_and_session(client, debug)

    resp = client.get("/api/portal/oc/matters")
    assert resp.status_code == 200
    matters = resp.json()["matters"]
    assert [m["matter_code"] for m in matters] == ["C3-OC-1"]


def test_oc_endpoints_reject_client_role(client: TestClient) -> None:
    """A portal user holding only role='client' must get 404 on /oc/*
    even when they hold a live grant on the matter — the role gate is
    the same 404 shape as a missing matter."""
    boot = _bootstrap(client, slug="c3-roleguard", email="c3-rg@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-RG-1")
    # Invite as CLIENT, then try /oc/* endpoints.
    resp = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@portal.example",
            "full_name": "Client Anchor",
            "role": "client",
            "matter_ids": [matter_id],
        },
    )
    assert resp.status_code == 201
    debug = resp.json()["debug_token"]
    _verify_and_session(client, debug)

    deny = client.get(f"/api/portal/oc/matters/{matter_id}")
    assert deny.status_code == 404


def test_oc_get_matter_404_cross_tenant(client: TestClient) -> None:
    boot_a = _bootstrap(client, slug="c3-x-a", email="c3-x-a@f.example")
    boot_b = _bootstrap(client, slug="c3-x-b", email="c3-x-b@f.example")
    matter_a = _seed_matter(boot_a["company"]["id"], code="C3-X-A")
    matter_b = _seed_matter(boot_b["company"]["id"], code="C3-X-B")
    _, debug_a = _invite_oc_portal_user(
        client, str(boot_a["access_token"]), matter_a,
        email="x-a@oc.example",
    )
    _verify_and_session(client, debug_a)
    cross = client.get(f"/api/portal/oc/matters/{matter_b}")
    assert cross.status_code == 404


# ---------- work product upload ----------


def test_oc_uploads_work_product_lands_attachment(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-up", email="c3-up@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-UP-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)

    # Minimal valid PDF magic: %PDF-1.4
    pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj <<>> endobj\ntrailer<<>>\n%%EOF"
    resp = client.post(
        f"/api/portal/oc/matters/{matter_id}/work-product",
        files={"file": ("brief.pdf", pdf_bytes, "application/pdf")},
        headers=_portal_csrf_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["original_filename"] == "brief.pdf"
    assert body["submitted_by_portal_user_id"] is not None

    Session = get_session_factory()
    with Session() as session:
        att = session.scalar(
            select(MatterAttachment).where(MatterAttachment.id == body["id"])
        )
        assert att is not None
        assert att.submitted_by_portal_user_id is not None
        assert att.uploaded_by_membership_id is None


def test_oc_upload_requires_portal_csrf(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-csrf", email="c3-csrf@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-CSRF-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)

    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer<<>>\n%%EOF"
    no_csrf = client.post(
        f"/api/portal/oc/matters/{matter_id}/work-product",
        files={"file": ("a.pdf", pdf, "application/pdf")},
        # NO X-Portal-CSRF-Token header.
    )
    assert no_csrf.status_code == 403
    assert "CSRF" in no_csrf.json()["detail"]


# ---------- cross-counsel isolation ----------


def test_oc_cannot_see_other_oc_work_product_by_default(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-iso", email="c3-iso@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-ISO-1")

    # OC #1 uploads.
    _, debug1 = _invite_oc_portal_user(
        client, token, matter_id, email="oc1@oc.example",
    )
    _verify_and_session(client, debug1)
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer<<>>\n%%EOF"
    up = client.post(
        f"/api/portal/oc/matters/{matter_id}/work-product",
        files={"file": ("oc1.pdf", pdf, "application/pdf")},
        headers=_portal_csrf_headers(client),
    )
    assert up.status_code == 201

    # Switch to OC #2's session — same matter, separate grant.
    client.cookies.clear()
    _, debug2 = _invite_oc_portal_user(
        client, token, matter_id, email="oc2@oc.example",
    )
    _verify_and_session(client, debug2)
    seen = client.get(
        f"/api/portal/oc/matters/{matter_id}/work-product"
    ).json()["items"]
    assert seen == []  # OC #2 must not see OC #1's upload


def test_oc_sees_others_when_cross_visibility_on(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-cross", email="c3-cross@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-CROSS-1")

    _, debug1 = _invite_oc_portal_user(
        client, token, matter_id, email="oc1@cross.example",
    )
    _verify_and_session(client, debug1)
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer<<>>\n%%EOF"
    client.post(
        f"/api/portal/oc/matters/{matter_id}/work-product",
        files={"file": ("oc1.pdf", pdf, "application/pdf")},
        headers=_portal_csrf_headers(client),
    )

    _set_oc_cross_visibility(matter_id, True)

    client.cookies.clear()
    _, debug2 = _invite_oc_portal_user(
        client, token, matter_id, email="oc2@cross.example",
    )
    _verify_and_session(client, debug2)
    seen = client.get(
        f"/api/portal/oc/matters/{matter_id}/work-product"
    ).json()["items"]
    assert len(seen) == 1
    assert seen[0]["original_filename"] == "oc1.pdf"


# ---------- invoice submission ----------


def test_oc_submits_invoice_lands_needs_review(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-inv", email="c3-inv@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-INV-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)

    payload = {
        "invoice_number": "OC-2026-001",
        "issued_on": "2026-04-25",
        "due_on": "2026-05-25",
        "currency": "INR",
        "line_items": [
            {"description": "Drafting brief — bail application",
             "amount_minor": 500000},
            {"description": "Court appearance", "amount_minor": 1000000},
        ],
        "notes": "Hours capped per engagement letter.",
    }
    resp = client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json=payload,
        headers=_portal_csrf_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == InvoiceStatus.NEEDS_REVIEW
    assert body["subtotal_amount_minor"] == 1500000

    Session = get_session_factory()
    with Session() as session:
        inv = session.scalar(
            select(MatterInvoice).where(MatterInvoice.id == body["id"])
        )
        assert inv is not None
        assert inv.status == InvoiceStatus.NEEDS_REVIEW
        assert inv.submitted_by_portal_user_id is not None
        assert inv.issued_by_membership_id is None


def test_oc_invoice_rejects_empty_line_items(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-inv-empty", email="c3-inv-e@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-INV-E")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    resp = client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json={
            "invoice_number": "OC-2026-X",
            "issued_on": "2026-04-25",
            "currency": "INR",
            "line_items": [],
        },
        headers=_portal_csrf_headers(client),
    )
    assert resp.status_code == 422


# ---------- time entries ----------


def test_oc_submits_time_entry(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-time", email="c3-time@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-TIME-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)

    resp = client.post(
        f"/api/portal/oc/matters/{matter_id}/time-entries",
        json={
            "work_date": "2026-04-25",
            "description": "Reviewed client documents",
            "duration_minutes": 90,
            "billable": True,
            "rate_currency": "INR",
            "rate_amount_minor": 500000,  # 5,000.00 / hr
        },
        headers=_portal_csrf_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # 5,000.00/hr × 1.5h = 7,500.00 = 750000 minor units
    assert body["total_amount_minor"] == 750000

    Session = get_session_factory()
    with Session() as session:
        te = session.scalar(
            select(MatterTimeEntry).where(MatterTimeEntry.id == body["id"])
        )
        assert te is not None
        assert te.submitted_by_portal_user_id is not None
        assert te.author_membership_id is None


# ---------- FT-075 — revoke invalidates ----------


def test_revoking_grant_blocks_further_oc_calls(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-revoke", email="c3-rv@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-RV-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    ok = client.get(f"/api/portal/oc/matters/{matter_id}")
    assert ok.status_code == 200

    # Revoke the grant directly via the DB (the admin revoke route is
    # not in scope for C-3 — it's a C-1/C-3c follow-on).
    Session = get_session_factory()
    with Session() as session:
        from datetime import UTC, datetime
        grant = session.scalar(
            select(MatterPortalGrant).where(
                MatterPortalGrant.matter_id == matter_id,
                MatterPortalGrant.role == "outside_counsel",
            )
        )
        assert grant is not None
        grant.revoked_at = datetime.now(UTC)
        session.commit()

    deny = client.get(f"/api/portal/oc/matters/{matter_id}")
    assert deny.status_code == 404


# ---------- audit ----------


def test_admin_can_toggle_oc_cross_visibility_via_matter_patch(
    client: TestClient,
) -> None:
    """C-3c: workspace owner flips Matter.oc_cross_visibility_enabled
    via the same PATCH /api/matters/{id} an internal user uses for
    every other matter field. The OC list endpoints honour the new
    value on the next request — proving the toggle is fully wired
    end-to-end (not just persisted)."""
    boot = _bootstrap(client, slug="c3c-toggle", email="c3c@firm.example")
    owner_token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3C-TOGGLE-1")

    # OC #1 uploads (default oc_cross_visibility_enabled=False).
    _, debug1 = _invite_oc_portal_user(
        client, owner_token, matter_id, email="oc1@toggle.example",
    )
    _verify_and_session(client, debug1)
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailer<<>>\n%%EOF"
    client.post(
        f"/api/portal/oc/matters/{matter_id}/work-product",
        files={"file": ("oc1.pdf", pdf, "application/pdf")},
        headers=_portal_csrf_headers(client),
    )

    # OC #2 cannot see OC #1's upload yet (default iso).
    client.cookies.clear()
    _, debug2 = _invite_oc_portal_user(
        client, owner_token, matter_id, email="oc2@toggle.example",
    )
    _verify_and_session(client, debug2)
    before = client.get(
        f"/api/portal/oc/matters/{matter_id}/work-product"
    ).json()["items"]
    assert before == []

    # Owner flips the toggle via PATCH. Bearer-authed call — conftest
    # strips cookies for this call but the portal cookies stay in the
    # client jar so OC #2's next call re-uses the same session
    # (magic-link tokens are single-use, so we cannot re-verify).
    resp = client.patch(
        f"/api/matters/{matter_id}",
        headers=auth_headers(owner_token),
        json={"oc_cross_visibility_enabled": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["oc_cross_visibility_enabled"] is True

    # OC #2 (same session) now sees OC #1's upload.
    after = client.get(
        f"/api/portal/oc/matters/{matter_id}/work-product"
    ).json()["items"]
    assert len(after) == 1
    assert after[0]["original_filename"] == "oc1.pdf"


def test_matter_record_default_oc_cross_visibility_is_false(
    client: TestClient,
) -> None:
    """A freshly-created matter must have oc_cross_visibility_enabled
    default to False so OC isolation is the safe default."""
    boot = _bootstrap(
        client, slug="c3c-default", email="c3c-d@firm.example",
    )
    token = str(boot["access_token"])
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Default-iso matter",
            "matter_code": "C3C-DEF-1",
            "client_name": "Default Client",
            "opposing_party": "Default Opposition",
            "status": "intake",
            "practice_area": "commercial",
            "forum_level": "high_court",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["oc_cross_visibility_enabled"] is False


def test_oc_invoice_submit_writes_audit_row(client: TestClient) -> None:
    boot = _bootstrap(client, slug="c3-audit", email="c3-audit@firm.example")
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="C3-AUDIT-1")
    _, debug = _invite_oc_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    client.post(
        f"/api/portal/oc/matters/{matter_id}/invoices",
        json={
            "invoice_number": "OC-AUD-1",
            "issued_on": "2026-04-25",
            "currency": "INR",
            "line_items": [{"description": "x", "amount_minor": 1000}],
        },
        headers=_portal_csrf_headers(client),
    )
    Session = get_session_factory()
    with Session() as session:
        rows = list(session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "portal_oc.submit_invoice",
            )
        ))
        assert len(rows) >= 1
        assert rows[-1].matter_id == matter_id
