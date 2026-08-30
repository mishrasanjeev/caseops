from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, TenantGoogleWorkspaceConfiguration
from caseops_api.db.session import get_session_factory
from caseops_api.services import google_workspace as google_workspace_service
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
            # Compatibility input from a previous web revision; current API
            # ignores these internal acknowledgements instead of persisting
            # them as readiness evidence.
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
    assert {
        item["key"] for item in response.json()["required_approvals"]
    } == {"oauth_consent_model_approved", "scopes_approved"}
    assert response.json()["missing_machine_control_keys"] == []
    assert all(
        item["status"] == "passed"
        for item in response.json()["machine_controls"]
    )
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
        assert row.webhook_runbook_approved is False
        assert row.redaction_rules_approved is False
        row.webhook_runbook_approved = True
        row.redaction_rules_approved = True
        session.add(row)
        session.commit()
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
    assert tested.json()["machine_control_version"].startswith(
        "google-workspace-connector-controls/"
    )
    assert "tenant-google-secret" not in tested.text
    with factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "google_workspace.configuration.tested"
            )
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["external_provider_calls"] == 0
        assert metadata["missing_machine_control_keys"] == []

    legacy_true = client.get(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
    )
    assert legacy_true.status_code == 200, legacy_true.text
    assert legacy_true.json()["missing_approval_keys"] == []
    assert {item["key"] for item in legacy_true.json()["required_approvals"]} == {
        "oauth_consent_model_approved",
        "scopes_approved",
    }

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


def test_google_readiness_blocks_partial_webhook_configuration_offline(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="google-workspace-partial-webhook",
        email="owner@google-workspace-partial-webhook.example",
    )
    token = str(bootstrap["access_token"])
    _configure_google_workspace(client, token)
    monkeypatch.setenv(
        "CASEOPS_GMAIL_PUBSUB_TOPIC",
        "projects/caseops/topics/partial-webhook",
    )
    monkeypatch.delenv("CASEOPS_GMAIL_WEBHOOK_VERIFICATION_TOKEN", raising=False)
    get_settings.cache_clear()

    tested = client.post(
        "/api/admin/google-workspace-configuration/test",
        headers=_auth(token),
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "blocked"
    control = next(
        item
        for item in tested.json()["checks"]
        if item["key"] == "gmail_webhook_disable_boundary"
    )
    assert control["status"] == "blocked"

    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "google_workspace.configuration.tested"
            )
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["external_provider_calls"] == 0
        assert metadata["missing_machine_control_keys"] == [
            "gmail_webhook_disable_boundary"
        ]


def test_google_scope_authority_rejects_partial_approved_scope_set(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="google-workspace-partial-scopes",
        email="owner@google-workspace-partial-scopes.example",
    )
    token = str(bootstrap["access_token"])
    _configure_google_workspace(client, token)

    response = client.patch(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
        json={
            "scopes": ["https://www.googleapis.com/auth/calendar.events"],
            "oauth_consent_model_approved": True,
            "scopes_approved": True,
            "calendar_enabled": True,
            "gmail_enabled": True,
            "drive_enabled": True,
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is True
    assert response.json()["missing_approval_keys"] == ["scopes_approved"]
    scopes = next(
        item
        for item in response.json()["required_approvals"]
        if item["key"] == "scopes_approved"
    )
    assert scopes["approved"] is False


def test_disabled_google_tenant_row_never_falls_back_to_environment_credentials(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="google-workspace-disabled-env",
        email="owner@google-workspace-disabled-env.example",
    )
    token = str(bootstrap["access_token"])
    _configure_google_workspace(client, token)
    for prefix in ("GOOGLE_CALENDAR", "GMAIL", "GOOGLE_DRIVE"):
        monkeypatch.setenv(f"CASEOPS_{prefix}_CLIENT_ID", "environment-client")
        monkeypatch.setenv(f"CASEOPS_{prefix}_CLIENT_SECRET", "environment-secret")
        monkeypatch.setenv(
            f"CASEOPS_{prefix}_REDIRECT_URI",
            f"https://environment.example.test/{prefix.lower()}/callback",
        )
    get_settings.cache_clear()

    disabled = client.patch(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
        json={
            "oauth_consent_model_approved": True,
            "scopes_approved": True,
            "calendar_enabled": True,
            "gmail_enabled": True,
            "drive_enabled": True,
            "enabled": False,
        },
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["configured"] is False
    assert disabled.json()["config_source"] == "tenant_admin"
    # The kill switch must not depend on being able to decrypt a dormant
    # credential (for example, during key rotation).
    with get_session_factory()() as session:
        row = session.scalar(select(TenantGoogleWorkspaceConfiguration))
        assert row is not None
        row.encrypted_client_secret_ref = "legacy-unreadable-secret-ref"
        session.add(row)
        session.commit()

    for path in (
        "/api/calendar/connections/google-calendar/start",
        "/api/mailbox/gmail/start",
        "/api/drive/google/start",
    ):
        start = client.post(path, headers=_auth(token))
        assert start.status_code == 200, start.text
        assert start.json()["provider_available"] is False
        assert "environment-client" not in start.text
        assert "environment-secret" not in start.text


def test_google_workspace_status_loads_tenant_configuration_once(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="google-workspace-query-bound",
        email="owner@google-workspace-query-bound.example",
    )
    token = str(bootstrap["access_token"])
    _configure_google_workspace(client, token)
    factory = get_session_factory()
    with factory() as session:
        bind = session.bind
    assert bind is not None
    tenant_selects = 0

    def count_tenant_selects(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal tenant_selects
        normalized = str(statement).lower()
        if (
            normalized.lstrip().startswith("select")
            and "tenant_google_workspace_configurations" in normalized
        ):
            tenant_selects += 1

    event.listen(bind, "before_cursor_execute", count_tenant_selects)
    try:
        response = client.get(
            "/api/admin/google-workspace-configuration",
            headers=_auth(token),
        )
    finally:
        event.remove(bind, "before_cursor_execute", count_tenant_selects)
    assert response.status_code == 200, response.text
    assert tenant_selects == 1


def test_google_machine_controls_fail_closed_when_policy_checks_fail(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="google-workspace-policy-failure",
        email="owner@google-workspace-policy-failure.example",
    )
    token = str(bootstrap["access_token"])
    _configure_google_workspace(client, token)
    monkeypatch.setattr(
        google_workspace_service,
        "DEFAULT_SAFE_HTTP_RETRY_MAX_ATTEMPTS",
        1,
    )
    monkeypatch.setattr(
        google_workspace_service,
        "redact_provider_error",
        lambda value: str(value),
    )

    status_response = client.get(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
    )
    assert status_response.status_code == 200, status_response.text
    assert set(status_response.json()["missing_machine_control_keys"]) == {
        "provider_retry_policy",
        "provider_error_redaction",
    }
    assert status_response.json()["readiness"] == (
        "blocked_pending_admin_configuration"
    )


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
