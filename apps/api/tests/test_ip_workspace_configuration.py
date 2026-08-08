from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingSubscription,
    IpWorkspaceConfiguration,
    IpWorkspaceTestResult,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _configuration(membership_id: str, *, provider_keys: list[str] | None = None) -> dict:
    providers = provider_keys or []
    return {
        "enabled_asset_types": ["trademark"],
        "jurisdictions": ["IN"],
        "offices": ["IP India"],
        "timezone": "Asia/Kolkata",
        "holiday_calendar_key": "test-calendar",
        "working_day_policy": {"working_weekdays": [0, 1, 2, 3, 4]},
        "document_taxonomy_version": "ip-taxonomy-2026.1",
        "event_catalog_version": "ip-events-v1",
        "deadline_rule_versions": {"IN-TM": "2026.1"},
        "notification_channels": ["in_app"],
        "critical_event_policy": {"escalation_after_minutes": 30},
        "escalation_owner_membership_id": membership_id,
        "provider_keys": providers,
        "provider_terms_version": "2026.1" if providers else None,
        "accept_provider_terms": bool(providers),
    }


def _bootstrap_tenant(
    client: TestClient,
    *,
    slug: str,
    email: str,
) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.replace("-", " ").title(),
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Workspace Fixture Owner",
            "owner_email": email,
            "owner_password": "FixturePass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run_test(
    client: TestClient,
    headers: dict[str, str],
    *,
    version: int,
    test_kind: str,
    provider_key: str | None = None,
) -> dict:
    response = client.post(
        "/api/ip/workspace/tests",
        headers=headers,
        json={
            "expected_config_version": version,
            "test_kind": test_kind,
            "provider_key": provider_key,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_missing_provider_failure_does_not_block_manual_workspace(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])

    absent = client.get("/api/ip/workspace/configuration", headers=headers)
    assert absent.status_code == 200
    assert absent.json()["configuration"] is None
    assert absent.json()["enablement_blockers"] == ["workspace_configuration_missing"]

    saved = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json=_configuration(membership_id),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configuration"]["version"] == 1
    assert saved.json()["ready_for_manual_docketing"] is True

    failed_connection = _run_test(
        client,
        headers,
        version=1,
        test_kind="connection",
        provider_key="unconfigured-registry",
    )
    assert failed_connection["status"] == "failed"
    assert failed_connection["failure_code"] == "provider_not_configured"

    enabled = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={"expected_config_version": 1, "enabled_automations": []},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["configuration"]["workspace_enabled"] is True
    assert enabled.json()["configuration"]["enabled_automations_json"] == []
    assert enabled.json()["ready_for_manual_docketing"] is True

    registry_attempt = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={"expected_config_version": 1, "enabled_automations": ["registry_sync"]},
    )
    assert registry_attempt.status_code == 409
    assert "registry_sync:connection_not_passed" in registry_attempt.text
    assert "registry_sync:source_open_not_passed" in registry_attempt.text


def test_normal_workspace_setup_records_tests_terms_flags_and_actor(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])

    saved = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json=_configuration(membership_id, provider_keys=["ipindia-registry"]),
    )
    assert saved.status_code == 200, saved.text
    config = saved.json()["configuration"]
    assert config["provider_terms_accepted_by_membership_id"] == membership_id
    assert config["provider_terms_accepted_at"] is not None

    assert _run_test(
        client,
        headers,
        version=1,
        test_kind="connection",
        provider_key="ipindia-registry",
    )["status"] == "passed"
    assert _run_test(
        client,
        headers,
        version=1,
        test_kind="source_open",
        provider_key="ipindia-registry",
    )["details_json"]["external_call"] is False
    notification = _run_test(
        client,
        headers,
        version=1,
        test_kind="notification",
    )
    assert notification["status"] == "passed"
    assert notification["details_json"]["sent"] is False
    deadline = _run_test(
        client,
        headers,
        version=1,
        test_kind="deadline_calculation",
    )
    assert deadline["status"] == "passed"
    assert deadline["details_json"]["legal_deadline"] is False

    enabled = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={
            "expected_config_version": 1,
            "enabled_automations": [
                "registry_sync",
                "deadline_automation",
                "notification_automation",
            ],
        },
    )
    assert enabled.status_code == 200, enabled.text
    status = enabled.json()
    assert status["enablement_blockers"] == []
    assert status["configuration"]["workspace_enabled"] is True
    assert set(status["configuration"]["enabled_automations_json"]) == {
        "registry_sync",
        "deadline_automation",
        "notification_automation",
    }

    stale = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json=_configuration(membership_id, provider_keys=["ipindia-registry"])
        | {"expected_version": 999},
    )
    assert stale.status_code == 409

    with get_session_factory()() as session:
        configuration = session.scalar(
            select(IpWorkspaceConfiguration).where(
                IpWorkspaceConfiguration.company_id == company_id
            )
        )
        assert configuration is not None
        assert configuration.updated_by_membership_id == membership_id
        tests = list(
            session.scalars(
                select(IpWorkspaceTestResult).where(
                    IpWorkspaceTestResult.company_id == company_id
                )
            ).all()
        )
        assert len(tests) == 4
        assert {row.test_kind for row in tests} == {
            "connection",
            "source_open",
            "notification",
            "deadline_calculation",
        }
        audit_actions = set(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.company_id == company_id)
            ).all()
        )
    assert {
        "ip_workspace.configuration_saved",
        "ip_workspace.readiness_test_completed",
        "ip_workspace.enabled",
    }.issubset(audit_actions)


def test_workspace_configuration_is_tenant_scoped_and_admin_guarded(
    client: TestClient,
) -> None:
    first = _bootstrap_tenant(
        client,
        email="workspace-a@example.com",
        slug="workspace-a",
    )
    first_headers = auth_headers(str(first["access_token"]))
    saved = client.put(
        "/api/ip/workspace/configuration",
        headers=first_headers,
        json=_configuration(str(first["membership"]["id"])),
    )
    assert saved.status_code == 200

    second = _bootstrap_tenant(
        client,
        email="workspace-b@example.com",
        slug="workspace-b",
    )
    second_headers = auth_headers(str(second["access_token"]))
    second_status = client.get("/api/ip/workspace/configuration", headers=second_headers)
    assert second_status.status_code == 200
    assert second_status.json()["configuration"] is None

    # A cross-tenant membership cannot be installed as an escalation owner.
    rejected = client.put(
        "/api/ip/workspace/configuration",
        headers=second_headers,
        json=_configuration(str(first["membership"]["id"])),
    )
    assert rejected.status_code == 422


def test_readiness_fails_closed_on_tenant_configuration_and_test_state(
    client: TestClient,
    monkeypatch,
) -> None:
    for setting in (
        "CASEOPS_IP_WORKSPACE_ENABLED",
        "CASEOPS_IP_REGISTRY_SYNC_ENABLED",
    ):
        monkeypatch.setenv(setting, "true")
    get_settings.cache_clear()
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    with get_session_factory()() as session:
        session.add(
            BillingSubscription(
                company_id=company_id,
                status="manual_active",
                segment="law_firm",
                source="fixture",
                externally_billable=False,
                entitlement_overrides_json={
                    "ip_workspace": True,
                    "ip_registry_sync": True,
                },
            )
        )
        session.commit()

    before_config = client.get("/api/ip/readiness", headers=headers)
    assert before_config.status_code == 200, before_config.text
    before_by_id = {row["feature_id"]: row for row in before_config.json()["features"]}
    assert before_by_id["workspace_core"]["reason"] == "workspace_not_configured"
    assert before_by_id["registry_sync"]["reason"] == "workspace_not_configured"

    saved = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json=_configuration(membership_id),
    )
    assert saved.status_code == 200
    tenant_disabled = client.get("/api/ip/readiness", headers=headers).json()
    disabled_by_id = {row["feature_id"]: row for row in tenant_disabled["features"]}
    assert disabled_by_id["workspace_core"]["reason"] == "tenant_disabled"

    failed = _run_test(
        client,
        headers,
        version=1,
        test_kind="connection",
        provider_key="missing-provider",
    )
    assert failed["status"] == "failed"
    enabled = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={"expected_config_version": 1, "enabled_automations": []},
    )
    assert enabled.status_code == 200
    manual_only = client.get("/api/ip/readiness", headers=headers).json()
    manual_by_id = {row["feature_id"]: row for row in manual_only["features"]}
    assert manual_by_id["workspace_core"]["available"] is True
    assert manual_by_id["manual_docketing"]["available"] is True
    assert manual_by_id["registry_sync"]["available"] is False
    assert manual_by_id["registry_sync"]["reason"] == "tenant_disabled"
