"""BUG-003: actual message tokens, not variable declarations, fence delivery."""

from types import SimpleNamespace

import pytest

from caseops_api.services.email_templates import render_template
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_email_templates import _create_matter, _create_template, _preview_message


def _delivery_effects(company_id):
    from sqlalchemy import func, select

    from caseops_api.db.models import Communication, DomainOutboxEvent, NotificationDeliveryIntent
    from caseops_api.db.session import get_session_factory

    with get_session_factory()() as session:
        return tuple(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.company_id == company_id,
                )
            )
            for model in (Communication, DomainOutboxEvent, NotificationDeliveryIntent)
        )


@pytest.mark.parametrize("declarations", [[], [{"name": "hearing_date", "required": False}]])
def test_undeclared_or_optional_token_still_requires_a_value(declarations):
    template = SimpleNamespace(
        subject_template="Hearing {{hearing_date}}",
        body_template="Hi {{client_name}}.",
        variables_json=declarations,
    )
    result = render_template(template=template, variables={"client_name": "Client"})
    assert result.missing_variables == ["hearing_date"]


@pytest.mark.parametrize(
    "body",
    [
        "{{ hearing.date }}",
        "{{client_name",
        "client_name}}",
        "{{{client_name}}}",
        "Hi {[client_name]}, the next hearing is on {[hearing_date]}.",
        "Hi [client_name not set]",
    ],
)
def test_malformed_tokens_are_not_deliverable(body):
    template = SimpleNamespace(subject_template="Update", body_template=body, variables_json=[])
    result = render_template(template=template, variables={"client_name": "Client"})
    assert result.invalid_placeholders


def test_substituted_values_cannot_smuggle_more_tokens():
    template = SimpleNamespace(
        subject_template="Update",
        body_template="Hi {{client_name}}",
        variables_json=[],
    )
    result = render_template(template=template, variables={"client_name": "{{hearing_date}}"})
    assert result.invalid_placeholders


def test_unknown_token_with_a_value_is_still_rejected():
    result = render_template(
        template=SimpleNamespace(
            subject_template="Update",
            body_template="{{invented}}",
            variables_json=[],
        ),
        variables={"invented": "Looks resolved"},
    )
    assert result.invalid_placeholders == ["invented"]


def test_declared_custom_variable_remains_supported():
    result = render_template(
        template=SimpleNamespace(
            subject_template="Update",
            body_template="{{ custom_note }}",
            variables_json=[{"name": "custom_note", "required": False}],
        ),
        variables={"custom_note": "Reviewed text"},
    )
    assert result.body == "Reviewed text"
    assert result.missing_variables == result.invalid_placeholders == []


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("client_name", "Current Client", "Hi Current Client, hearing on 2026-11-20."),
        ("next_hearing_on", "2026-12-01", "Hi Hari Gupta, hearing on 2026-12-01."),
    ],
)
def test_matter_preview_resolves_authoritative_values_and_send_rechecks(
    client,
    monkeypatch,
    field,
    value,
    expected,
):
    from caseops_api.core.settings import get_settings
    from caseops_api.services import communications

    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    matter = _create_matter(client, headers, "B5-COMMS", hearing_date="2026-11-20")
    template = _create_template(client, headers, required_vars=())
    path = f"/api/matters/{matter}/communications"
    message = {
        "template_id": template["id"],
        "recipient_email": "client@example.com",
        "variables": {
            "client_name": "Spoofed",
            "hearing_date": "Invented",
        },
    }
    preview = client.post(f"{path}/preview-email", headers=headers, json=message)
    assert preview.status_code == 200, preview.text
    assert preview.json()["body"] == "Hi Hari Gupta, hearing on 2026-11-20."
    assert preview.json()["missing_variables"] == []
    assert preview.json()["invalid_placeholders"] == []
    preview_token = preview.json()["preview_token"]
    assert preview_token
    calls = []
    monkeypatch.setattr(
        communications,
        "_send_via_sendgrid",
        lambda **kw: (calls.append(kw) or (True, "offline-b5", None)),
    )
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "offline-fixture")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "offline@example.com")
    get_settings.cache_clear()
    # Changed source must require a fresh preview, never silently change mail.
    current = client.get(f"/api/matters/{matter}", headers=headers).json()
    changed = client.patch(
        f"/api/matters/{matter}",
        headers=headers,
        json={
            field: value,
            "expected_updated_at": current["updated_at"],
        },
    )
    assert changed.status_code == 200, changed.text
    before = _delivery_effects(actor["company"]["id"])
    sent = client.post(
        f"{path}/send-email",
        headers=headers,
        json={**message, "preview_token": preview_token},
    )
    assert sent.status_code == 409, sent.text
    assert calls == []
    assert _delivery_effects(actor["company"]["id"]) == before
    persisted = client.get(path, headers=headers).json()["communications"]
    assert persisted == []
    refreshed = _preview_message(client, headers, matter, message)
    recovered = client.post(f"{path}/send-email", headers=headers, json=refreshed)
    assert recovered.status_code == 200, recovered.text
    assert calls[0]["body_text"] == expected
    assert client.get(path, headers=headers).json()["communications"][0]["body"] == expected


def test_missing_legacy_unknown_and_nested_tokens_never_dispatch(client, monkeypatch):
    from caseops_api.services import communications

    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    matter = _create_matter(client, headers, "B5-MISSING")
    template = _create_template(client, headers, required_vars=())
    path = f"/api/matters/{matter}/communications"
    calls = []
    monkeypatch.setattr(communications, "_send_via_sendgrid", lambda **kw: calls.append(kw))
    cases = [
        {"template_id": template["id"], "variables": {"hearing_date": "Invented"}},
        {
            "subject": "Status update on your matter {[client_name]}",
            "body": "Hi {[client_name]}, the next hearing is on {[hearing_date]}.",
        },
        {"subject": "Update", "body": "{{unknown}}", "variables": {"unknown": "Provided"}},
        {"subject": "Update", "body": "{{ matter.title }}"},
    ]
    for message in cases:
        message = {"recipient_email": "client@example.com", **message}
        preview = client.post(f"{path}/preview-email", headers=headers, json=message)
        assert preview.status_code == 200, preview.text
        assert preview.json()["missing_variables"] or preview.json()["invalid_placeholders"]
        assert preview.json()["preview_token"] is None
        sent = client.post(
            f"{path}/send-email",
            headers=headers,
            json={**message, "preview_token": "not-a-valid-preview"},
        )
        assert sent.status_code == 409, sent.text
    assert calls == []
    assert client.get(path, headers=headers).json()["communications"] == []


@pytest.mark.parametrize("mode", ["manual", "template"])
def test_manual_message_persists_and_automated_delivery_remains_blocked(client, monkeypatch, mode):
    from caseops_api.core.settings import get_settings
    from caseops_api.services import communications

    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    matter = _create_matter(client, headers, "B5-MANUAL")
    path = f"/api/matters/{matter}/communications"
    calls = []
    monkeypatch.setattr(
        communications,
        "_send_via_sendgrid",
        lambda **kw: (calls.append(kw) or (True, "offline-manual", None)),
    )
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "offline-fixture")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "offline@example.com")
    get_settings.cache_clear()
    message = {
        "subject": "Reviewed update",
        "body": "Dear client, no hearing date is confirmed.",
        "recipient_email": "client@example.com",
    }
    if mode == "template":
        template = _create_template(
            client,
            headers,
            body_template="Hi {{client_name}}, no hearing date is confirmed.",
            required_vars=(),
        )
        message = {"template_id": template["id"], "recipient_email": "client@example.com"}
    signed_message = _preview_message(client, headers, matter, message)
    before = _delivery_effects(actor["company"]["id"])
    blocked = client.post(
        f"{path}/send-email",
        headers={**headers, "X-CaseOps-Automated-Test": "no-paid-providers"},
        json=signed_message,
    )
    assert blocked.status_code == 409, blocked.text
    assert "automated verification" in blocked.json()["detail"]
    assert calls == []
    assert _delivery_effects(actor["company"]["id"]) == before
    assert client.get(path, headers=headers).json()["communications"] == []
    from datetime import UTC, datetime

    from caseops_api.services import email_suppression

    with monkeypatch.context() as suppress:
        suppress.setattr(
            email_suppression,
            "is_suppressed",
            lambda *a, **kw: SimpleNamespace(
                reason="hard_bounce",
                last_event_at=datetime.now(UTC),
            ),
        )
        denied = client.post(f"{path}/send-email", headers=headers, json=signed_message)
        assert denied.status_code == 422, denied.text
        assert calls == []
    sent = client.post(f"{path}/send-email", headers=headers, json=signed_message)
    assert sent.status_code == 200, sent.text
    expected_body = (
        "Hi Hari Gupta, no hearing date is confirmed." if mode == "template" else message["body"]
    )
    assert calls[0]["body_text"] == expected_body
    assert client.get(path, headers=headers).json()["communications"][0]["body"] == expected_body
    assert sent.json()["status"] == "sent"


def test_preview_template_and_matter_scope_and_archived_send(client, monkeypatch):
    from caseops_api.services import communications

    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    matter = _create_matter(client, headers, "B5-SCOPE", hearing_date="2026-11-20")
    template = _create_template(client, headers)
    path = f"/api/matters/{matter}/communications"
    assert client.get(f"{path}/email-templates", headers=headers).status_code == 200
    archived = client.delete(f"/api/admin/email-templates/{template['id']}", headers=headers)
    assert archived.status_code == 200
    calls = []
    monkeypatch.setattr(communications, "_send_via_sendgrid", lambda **kw: calls.append(kw))
    for action in ("preview-email", "send-email"):
        message = {"template_id": template["id"], "recipient_email": "client@example.com"}
        if action == "send-email":
            message["preview_token"] = "not-a-valid-preview"
        response = client.post(f"{path}/{action}", headers=headers, json=message)
        assert response.status_code == 404
    from tests.test_communications import _invite_member, _login

    _invite_member(client, headers, email="viewer@asterlegal.in", role="viewer")
    client.cookies.clear()
    token = _login(client, "viewer@asterlegal.in", "MemberPass123!", "aster-legal")
    viewer = auth_headers(token)
    response = client.post(
        f"{path}/preview-email",
        headers=viewer,
        json={
            "subject": "Update",
            "body": "Safe message",
            "recipient_email": "client@example.com",
        },
    )
    assert response.status_code == 403, response.text
    assert calls == []


def test_preview_binding_rejects_edited_recipient_message_variables_and_tokenless_send(
    client, monkeypatch
):
    from caseops_api.services import communications

    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    matter = _create_matter(client, headers, "B5-BINDING")
    path = f"/api/matters/{matter}/communications"
    message = {
        "subject": "Reviewed subject",
        "body": "Reviewed {{client_name}} message",
        "recipient_email": "reviewed@example.com",
        "recipient_name": "Reviewed recipient",
    }
    signed = _preview_message(client, headers, matter, message)
    calls = []
    monkeypatch.setattr(communications, "_send_via_sendgrid", lambda **kw: calls.append(kw))
    before = _delivery_effects(actor["company"]["id"])
    for edit in (
        {"recipient_email": "different@example.com"},
        {"recipient_name": "Different recipient"},
        {"subject": "Unreviewed subject"},
        {"body": "Unreviewed body"},
        {"variables": {"client_name": "Spoofed old source"}},
        {
            "preview_token": signed["preview_token"][:-1]
            + ("0" if signed["preview_token"][-1] != "0" else "1")
        },
    ):
        rejected = client.post(f"{path}/send-email", headers=headers, json={**signed, **edit})
        assert rejected.status_code == 409, rejected.text
        assert calls == []
        assert _delivery_effects(actor["company"]["id"]) == before
    tokenless = client.post(f"{path}/send-email", headers=headers, json=message)
    assert tokenless.status_code == 422, tokenless.text
    assert calls == []
    assert _delivery_effects(actor["company"]["id"]) == before


def test_template_edit_away_and_back_requires_a_fresh_preview(client, monkeypatch):
    from caseops_api.services import communications

    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    matter = _create_matter(client, headers, "B5-TPL-REV", hearing_date="2026-11-20")
    template = _create_template(client, headers)
    signed = _preview_message(client, headers, matter, {"template_id": template["id"]})
    for subject in ("Temporary edited subject", template["subject_template"]):
        changed = client.patch(
            f"/api/admin/email-templates/{template['id']}",
            headers=headers,
            json={"subject_template": subject},
        )
        assert changed.status_code == 200, changed.text
    assert changed.json()["updated_at"] != template["updated_at"]
    calls = []
    monkeypatch.setattr(communications, "_send_via_sendgrid", lambda **kw: calls.append(kw))
    before = _delivery_effects(actor["company"]["id"])
    rejected = client.post(
        f"/api/matters/{matter}/communications/send-email", headers=headers, json=signed
    )
    assert rejected.status_code == 409, rejected.text
    assert calls == []
    assert _delivery_effects(actor["company"]["id"]) == before


def test_expired_preview_has_no_delivery_effects(client, monkeypatch):
    from caseops_api.services import communication_email_preview, communications

    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    matter = _create_matter(client, headers, "B5-EXPIRED")
    monkeypatch.setattr(communication_email_preview, "_now_epoch", lambda: 1000)
    signed = _preview_message(
        client, headers, matter, {"subject": "Reviewed", "body": "Reviewed body"}
    )
    monkeypatch.setattr(communication_email_preview, "_now_epoch", lambda: 1300)
    calls = []
    monkeypatch.setattr(communications, "_send_via_sendgrid", lambda **kw: calls.append(kw))
    before = _delivery_effects(actor["company"]["id"])
    rejected = client.post(
        f"/api/matters/{matter}/communications/send-email", headers=headers, json=signed
    )
    assert rejected.status_code == 409, rejected.text
    assert calls == []
    assert _delivery_effects(actor["company"]["id"]) == before


def test_preview_cannot_be_transferred_to_another_authorized_actor(client, monkeypatch):
    from uuid import uuid4

    from caseops_api.services import communications
    from tests.test_communications import _invite_member, _login

    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    matter = _create_matter(client, headers, "B5-ACTOR")
    signed = _preview_message(
        client, headers, matter, {"subject": "Reviewed", "body": "Reviewed body"}
    )
    email = f"comms-admin-{uuid4()}@asterlegal.in"
    _invite_member(client, headers, email=email, role="admin")
    client.cookies.clear()
    other_token = _login(client, email, "MemberPass123!", "aster-legal")
    other_headers = auth_headers(other_token)
    current = client.get("/api/auth/me", headers=other_headers).json()
    assert current["company"]["id"] == actor["company"]["id"]
    assert current["membership"]["id"] != actor["membership"]["id"]
    assert "communications:write" in current["capabilities"]
    calls = []
    monkeypatch.setattr(communications, "_send_via_sendgrid", lambda **kw: calls.append(kw))
    before = _delivery_effects(actor["company"]["id"])
    rejected = client.post(
        f"/api/matters/{matter}/communications/send-email", headers=other_headers, json=signed
    )
    assert rejected.status_code == 409, rejected.text
    assert calls == []
    assert _delivery_effects(actor["company"]["id"]) == before


def test_preview_and_send_keep_cross_tenant_and_terminal_matter_fences(client, monkeypatch):
    from caseops_api.services import communications
    from tests.test_matter_lifecycle import _lifecycle

    actor = bootstrap_company(client)
    token = str(actor["access_token"])
    headers = auth_headers(token)
    matter_id = _create_matter(client, headers, "B5-TERMINAL")
    path = f"/api/matters/{matter_id}/communications"
    message = {
        "subject": "Update",
        "body": "Reviewed message",
        "recipient_email": "client@example.com",
    }
    current = client.get(f"/api/matters/{matter_id}", headers=headers).json()
    disposed = _lifecycle(client, token, current, to_status="disposed")
    assert disposed.status_code == 200, disposed.text
    calls = []
    monkeypatch.setattr(communications, "_send_via_sendgrid", lambda **kw: calls.append(kw))
    for action in ("preview-email", "send-email"):
        payload = {
            **message,
            **({"preview_token": "not-a-valid-preview"} if action == "send-email" else {}),
        }
        response = client.post(f"{path}/{action}", headers=headers, json=payload)
        assert response.status_code == 409, response.text
    client.cookies.clear()
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other QA",
            "company_slug": "b5-other",
            "company_type": "law_firm",
            "owner_full_name": "Other QA",
            "owner_email": "other@b5.example",
            "owner_password": "OtherOffline!12345",
        },
    )
    assert other.status_code == 200, other.text
    client.cookies.clear()
    other_headers = auth_headers(other.json()["access_token"])
    for action in ("preview-email", "send-email"):
        payload = {
            **message,
            **({"preview_token": "not-a-valid-preview"} if action == "send-email" else {}),
        }
        response = client.post(f"{path}/{action}", headers=other_headers, json=payload)
        assert response.status_code == 404, response.text
    assert client.get(f"{path}/email-templates", headers=other_headers).status_code == 404
    assert calls == []
