from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, TenantGoogleWorkspaceConfiguration
from caseops_api.db.session import get_session_factory
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company


def _configure_google_workspace(client: TestClient, token: str) -> None:
    response = client.patch(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
        json={
            "client_id": "tenant-google-client",
            "client_secret": "tenant-google-secret",
            "calendar_redirect_uri": (
                "https://api.tenant.example/api/calendar/connections/"
                "google-calendar/callback"
            ),
            "gmail_redirect_uri": "https://api.tenant.example/api/mailbox/gmail/callback",
            "drive_redirect_uri": "https://api.tenant.example/api/drive/google/callback",
            "scopes": [
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
            "oauth_consent_model_approved": True,
            "scopes_approved": True,
            "webhook_runbook_approved": True,
            "redaction_rules_approved": True,
            "calendar_enabled": True,
            "gmail_enabled": True,
            "drive_enabled": True,
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is True
    assert response.json()["config_source"] == "tenant_admin"
    assert "tenant-google-secret" not in response.text
    assert "tenant-google-client" not in response.text


def _auth_query(url: str) -> dict[str, list[str]]:
    parsed = urlparse(url)
    return parse_qs(parsed.query)


def test_google_workspace_tenant_config_is_secret_safe_audited_and_used_for_oauth(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="google-workspace",
        email="owner@google-workspace.example",
    )
    token = str(bootstrap["access_token"])

    _configure_google_workspace(client, token)

    factory = get_session_factory()
    with factory() as session:
        row = session.scalar(select(TenantGoogleWorkspaceConfiguration))
        assert row is not None
        assert row.client_id == "tenant-google-client"
        assert row.encrypted_client_secret_ref is not None
        assert row.encrypted_client_secret_ref.startswith("fernet:")
        assert "tenant-google-secret" not in row.encrypted_client_secret_ref
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "google_workspace.configuration.updated"
            )
        )
        assert audit is not None

    tested = client.post(
        "/api/admin/google-workspace-configuration/test",
        headers=_auth(token),
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "passed"
    assert "tenant-google-secret" not in tested.text
    with factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "google_workspace.configuration.tested"
            )
        )
        assert audit is not None

    calendar_start = client.post(
        "/api/calendar/connections/google-calendar/start",
        headers=_auth(token),
    )
    assert calendar_start.status_code == 200, calendar_start.text
    calendar_body = calendar_start.json()
    assert calendar_body["provider_available"] is True
    calendar_qs = _auth_query(calendar_body["auth_url"])
    assert calendar_qs["client_id"] == ["tenant-google-client"]
    assert calendar_qs["redirect_uri"] == [
        "https://api.tenant.example/api/calendar/connections/google-calendar/callback"
    ]
    assert "tenant-google-secret" not in calendar_start.text

    gmail_start = client.post("/api/mailbox/gmail/start", headers=_auth(token))
    assert gmail_start.status_code == 200, gmail_start.text
    gmail_body = gmail_start.json()
    assert gmail_body["provider_available"] is True
    gmail_qs = _auth_query(gmail_body["auth_url"])
    assert gmail_qs["client_id"] == ["tenant-google-client"]
    assert gmail_qs["redirect_uri"] == [
        "https://api.tenant.example/api/mailbox/gmail/callback"
    ]
    assert "tenant-google-secret" not in gmail_start.text

    drive_start = client.post("/api/drive/google/start", headers=_auth(token))
    assert drive_start.status_code == 200, drive_start.text
    drive_body = drive_start.json()
    assert drive_body["provider_available"] is True
    drive_qs = _auth_query(drive_body["auth_url"])
    assert drive_qs["client_id"] == ["tenant-google-client"]
    assert drive_qs["redirect_uri"] == [
        "https://api.tenant.example/api/drive/google/callback"
    ]
    assert "tenant-google-secret" not in drive_start.text

    calendar_status = client.get("/api/calendar/sync-status", headers=_auth(token))
    assert calendar_status.status_code == 200, calendar_status.text
    provider_config = {
        item["provider"]: item
        for item in calendar_status.json()["provider_config"]
    }
    assert provider_config["google_calendar"]["configured"] is True
    assert "tenant-google-secret" not in calendar_status.text

    gmail_status = client.get("/api/mailbox/gmail/status", headers=_auth(token))
    assert gmail_status.status_code == 200, gmail_status.text
    assert gmail_status.json()["configured"] is True
    assert "tenant-google-secret" not in gmail_status.text

    drive_status = client.get("/api/drive/google/status", headers=_auth(token))
    assert drive_status.status_code == 200, drive_status.text
    assert drive_status.json()["configured"] is True
    assert "tenant-google-secret" not in drive_status.text

    integrations = client.get("/api/admin/integrations", headers=_auth(token))
    assert integrations.status_code == 200, integrations.text
    assert "tenant-google-secret" not in integrations.text
    assert "tenant-google-client" not in integrations.text
    connectors = {item["key"]: item for item in integrations.json()["connectors"]}
    assert connectors["google_calendar"]["configured"] is True
    assert connectors["gmail"]["configured"] is True
    assert connectors["google_drive"]["configured"] is True
    assert "internal_cost_label" not in integrations.text
    assert "gross_profit" not in integrations.text
    assert "gross_margin" not in integrations.text

    readiness = client.get(
        "/api/admin/provider-operations/readiness",
        headers=_auth(token),
    )
    assert readiness.status_code == 200, readiness.text
    providers = {item["provider"]: item for item in readiness.json()["providers"]}
    assert providers["google_drive"]["configured"] is True
    assert providers["google_drive"]["required_config_names"] == [
        "GOOGLE_WORKSPACE_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GOOGLE_DRIVE_REDIRECT_URI",
    ]
    assert "GOOGLE_WORKSPACE_CLIENT_ID" in providers["email_connector"][
        "required_config_names"
    ]
    assert "tenant-google-secret" not in readiness.text


def test_google_workspace_configuration_is_cross_tenant_scoped(
    client: TestClient,
) -> None:
    tenant_a = _bootstrap_company(
        client,
        slug="google-tenant-a",
        email="owner@google-tenant-a.example",
    )
    token_a = str(tenant_a["access_token"])
    _configure_google_workspace(client, token_a)

    tenant_b = _bootstrap_company(
        client,
        slug="google-tenant-b",
        email="owner@google-tenant-b.example",
    )
    token_b = str(tenant_b["access_token"])

    a_start = client.post("/api/mailbox/gmail/start", headers=_auth(token_a))
    assert a_start.status_code == 200, a_start.text
    assert a_start.json()["provider_available"] is True
    assert _auth_query(a_start.json()["auth_url"])["client_id"] == [
        "tenant-google-client"
    ]

    for path in (
        "/api/calendar/connections/google-calendar/start",
        "/api/mailbox/gmail/start",
        "/api/drive/google/start",
    ):
        response = client.post(path, headers=_auth(token_b))
        assert response.status_code == 200, response.text
        assert response.json()["provider_available"] is False
        assert "tenant-google-client" not in response.text
        assert "tenant-google-secret" not in response.text

    b_integrations = client.get("/api/admin/integrations", headers=_auth(token_b))
    assert b_integrations.status_code == 200, b_integrations.text
    assert "tenant-google-client" not in b_integrations.text
    assert "tenant-google-secret" not in b_integrations.text
    connectors = {item["key"]: item for item in b_integrations.json()["connectors"]}
    assert connectors["google_calendar"]["configured"] is False
    assert connectors["gmail"]["configured"] is False
    assert connectors["google_drive"]["configured"] is False
