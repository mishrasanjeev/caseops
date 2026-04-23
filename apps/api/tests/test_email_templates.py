"""Phase B M11 slice 2 — email templates + AutoMail send + webhook.

Covers:

- Template CRUD round-trip + tenant isolation.
- Template name uniqueness per company (409 on dup).
- Render endpoint substitutes {{var}} tokens + reports missing required.
- Compose & send refuses when required vars missing (400 with the
  list).
- Compose & send refuses when SendGrid is not configured (503).
- Compose & send happy path: SendGrid HTTP mocked, communications row
  written with status=sent + external_message_id.
- SendGrid event webhook promotes the row from sent → delivered →
  opened, idempotent (replay safe), never demotes status.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
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


def _create_template(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "Status update",
    body_template: str = "Hi {{client_name}}, hearing on {{hearing_date}}.",
    required_vars: tuple[str, ...] = ("client_name", "hearing_date"),
) -> dict[str, Any]:
    resp = client.post(
        "/api/admin/email-templates",
        headers=headers,
        json={
            "name": name,
            "kind": "general",
            "subject_template": "Update on your matter",
            "body_template": body_template,
            "variables": [
                {"name": v, "label": v.replace("_", " ").title(), "required": True}
                for v in required_vars
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_template_crud_round_trip(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    created = _create_template(client, headers, name="Round trip")
    template_id = created["id"]
    assert created["name"] == "Round trip"
    assert len(created["variables"]) == 2

    listing = client.get("/api/admin/email-templates", headers=headers)
    assert listing.status_code == 200
    names = [t["name"] for t in listing.json()["templates"]]
    assert "Round trip" in names

    fetched = client.get(
        f"/api/admin/email-templates/{template_id}", headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["subject_template"] == "Update on your matter"

    edited = client.patch(
        f"/api/admin/email-templates/{template_id}",
        headers=headers,
        json={"description": "Quarterly status email."},
    )
    assert edited.status_code == 200
    assert edited.json()["description"] == "Quarterly status email."

    archived = client.delete(
        f"/api/admin/email-templates/{template_id}", headers=headers,
    )
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    # The default list filters out inactive.
    after = client.get("/api/admin/email-templates", headers=headers)
    assert "Round trip" not in [t["name"] for t in after.json()["templates"]]


def test_template_name_uniqueness_409(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    _create_template(client, headers, name="Welcome")
    dup = client.post(
        "/api/admin/email-templates",
        headers=headers,
        json={
            "name": "Welcome",
            "kind": "general",
            "subject_template": "Hi",
            "body_template": "again",
        },
    )
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"].lower()


def test_render_endpoint_substitutes_and_reports_missing(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    tpl = _create_template(client, headers)

    resp = client.post(
        f"/api/admin/email-templates/{tpl['id']}/render",
        headers=headers,
        json={"variables": {"client_name": "Hari Gupta"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Hi Hari Gupta" in body["body"]
    # hearing_date wasn't supplied — render keeps a placeholder + lists it
    assert "[hearing_date not set]" in body["body"]
    assert "hearing_date" in body["missing_variables"]
    assert "client_name" not in body["missing_variables"]


def test_send_email_refuses_when_required_vars_missing(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "M11-S2-001")
    tpl = _create_template(client, headers)

    resp = client.post(
        f"/api/matters/{matter_id}/communications/send-email",
        headers=headers,
        json={
            "template_id": tpl["id"],
            "recipient_email": "client@example.com",
            "variables": {"client_name": "Hari"},  # hearing_date missing
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "missing" in detail
    assert "hearing_date" in detail


def test_send_email_503_when_sendgrid_not_configured(
    client: TestClient, monkeypatch,
) -> None:
    """Without CASEOPS_SENDGRID_API_KEY/SENDER_EMAIL, the compose
    action must refuse with an actionable 503 — never silently log
    a 'sent' communication that didn't actually go anywhere."""
    monkeypatch.delenv("CASEOPS_SENDGRID_API_KEY", raising=False)
    monkeypatch.delenv("CASEOPS_SENDGRID_SENDER_EMAIL", raising=False)
    from caseops_api.core.settings import get_settings

    get_settings.cache_clear()

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "M11-S2-002")
    tpl = _create_template(client, headers, required_vars=("client_name",))

    resp = client.post(
        f"/api/matters/{matter_id}/communications/send-email",
        headers=headers,
        json={
            "template_id": tpl["id"],
            "recipient_email": "client@example.com",
            "variables": {"client_name": "Hari"},
        },
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_send_email_happy_path_writes_communications_row(
    client: TestClient, monkeypatch,
) -> None:
    """End-to-end: SendGrid HTTP mocked to 202; the resulting row
    must land with status=sent + external_message_id captured for
    later webhook reconciliation."""
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "SG.test")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "noreply@caseops.example")
    from caseops_api.core.settings import get_settings

    get_settings.cache_clear()

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "M11-S2-003")
    tpl = _create_template(client, headers, required_vars=("client_name",))

    fake_response = httpx.Response(
        202,
        headers={"X-Message-Id": "TESTMSG123.filterdrecv-12345"},
        request=httpx.Request("POST", "https://api.sendgrid.com/v3/mail/send"),
    )

    with patch("httpx.post", return_value=fake_response):
        resp = client.post(
            f"/api/matters/{matter_id}/communications/send-email",
            headers=headers,
            json={
                "template_id": tpl["id"],
                "recipient_email": "client@example.com",
                "recipient_name": "Hari Gupta",
                "variables": {"client_name": "Hari Gupta"},
            },
        )
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row["status"] == "sent"
    assert row["external_message_id"] == "TESTMSG123.filterdrecv-12345"
    assert row["channel"] == "email"
    assert row["recipient_email"] == "client@example.com"


def test_sendgrid_webhook_promotes_communications_row(
    client: TestClient, monkeypatch,
) -> None:
    """The webhook handler should match a delivery event back to the
    communications row by external_message_id and promote
    sent → delivered. Idempotent: replaying delivered must not regress
    a row that already moved past it (e.g. to opened)."""
    from sqlalchemy import select

    from caseops_api.db.models import Communication
    from caseops_api.db.session import get_session_factory
    from caseops_api.services.communications import (
        apply_sendgrid_communication_event,
    )

    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "SG.test")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "noreply@caseops.example")
    from caseops_api.core.settings import get_settings

    get_settings.cache_clear()

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "M11-S2-WEBHOOK")
    tpl = _create_template(client, headers, required_vars=("client_name",))

    fake = httpx.Response(
        202,
        headers={"X-Message-Id": "WEBHOOKMSG456"},
        request=httpx.Request("POST", "https://api.sendgrid.com/v3/mail/send"),
    )
    with patch("httpx.post", return_value=fake):
        sent = client.post(
            f"/api/matters/{matter_id}/communications/send-email",
            headers=headers,
            json={
                "template_id": tpl["id"],
                "recipient_email": "client@example.com",
                "variables": {"client_name": "Hari"},
            },
        )
    assert sent.status_code == 200
    sent_id = sent.json()["id"]

    # Apply a delivered event directly via the service helper (bypasses
    # the webhook signature gate so we test the matching+update logic).
    factory = get_session_factory()
    with factory() as s:
        ok = apply_sendgrid_communication_event(
            s,
            event={
                "event": "delivered",
                "sg_message_id": "WEBHOOKMSG456.0",
                "timestamp": 1776960000,
            },
        )
        assert ok is True
        s.commit()

        row = s.scalar(select(Communication).where(Communication.id == sent_id))
        assert row is not None
        assert row.status == "delivered"
        assert row.delivered_at is not None

        # Replay the same event — should be a no-op and not regress.
        delivered_at_first = row.delivered_at
        ok2 = apply_sendgrid_communication_event(
            s,
            event={
                "event": "delivered",
                "sg_message_id": "WEBHOOKMSG456.0",
                "timestamp": 1776960500,
            },
        )
        s.commit()
        s.refresh(row)
        assert ok2 is True  # still matched
        assert row.status == "delivered"
        # Idempotent — delivered_at should not be overwritten.
        assert row.delivered_at == delivered_at_first

        # Then an open event promotes status to opened.
        ok3 = apply_sendgrid_communication_event(
            s,
            event={
                "event": "open",
                "sg_message_id": "WEBHOOKMSG456.0",
                "timestamp": 1776961000,
            },
        )
        s.commit()
        s.refresh(row)
        assert ok3 is True
        assert row.status == "opened"

        # And a stray late delivered event must NOT demote opened.
        apply_sendgrid_communication_event(
            s,
            event={
                "event": "delivered",
                "sg_message_id": "WEBHOOKMSG456.0",
                "timestamp": 1776962000,
            },
        )
        s.commit()
        s.refresh(row)
        assert row.status == "opened"


def test_template_does_not_leak_across_tenants(client: TestClient) -> None:
    """Headline tenant-isolation invariant for the template
    catalogue. Tenant B GET on tenant A's template id must 404."""
    a = bootstrap_company(client)
    headers_a = auth_headers(str(a["access_token"]))
    tpl_a = _create_template(client, headers_a, name="Tenant A only")
    client.cookies.clear()

    b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other LLP",
            "company_slug": "other-tpl",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-tpl.example",
            "owner_password": "OtherStrong!234",
        },
    )
    assert b.status_code == 200
    headers_b = auth_headers(str(b.json()["access_token"]))
    client.cookies.clear()

    leak = client.get(
        f"/api/admin/email-templates/{tpl_a['id']}", headers=headers_b,
    )
    assert leak.status_code == 404

    # And listing from tenant B must not include tenant A's template.
    listing = client.get("/api/admin/email-templates", headers=headers_b)
    assert listing.status_code == 200
    assert "Tenant A only" not in [
        t["name"] for t in listing.json()["templates"]
    ]
