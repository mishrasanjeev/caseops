from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingProviderEvent,
    CaseTrackingSupportMatrix,
    ConnectorSecretRotationEvidence,
    PlatformAdminMembership,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.security import TOTP_PERIOD_SECONDS, _hotp
from tests.test_auth_company import auth_headers, bootstrap_company

NEW_P0_ROUTE_REFERENCES = (
    "/api/auth/security",
    "/api/auth/mfa/enroll",
    "/api/auth/mfa/enroll/verify",
    "/api/auth/mfa/step-up",
    "/api/auth/mfa/recovery-codes/regenerate",
    "/api/auth/mfa/disable",
    "/api/admin/security-policy",
    "/api/platform-admin/margin-readiness",
    "/api/platform-admin/pine-labs/uat-runs",
    "/api/platform-admin/pine-labs/uat-readiness",
    "/api/platform-admin/pine-labs/uat-evidence",
    "/api/platform-admin/pine-labs/production-activation",
    "/api/platform-admin/billing-signoff",
    "/api/platform-admin/billing-signoff/evidence",
    "/api/platform-admin/password-reset-readiness",
    "/api/platform-admin/production-readiness",
    "/api/platform-admin/production-readiness/evidence",
    "/api/platform-admin/secret-rotation-readiness",
    "/api/platform-admin/secret-rotation-readiness/evidence",
    "/api/platform-admin/finance/settlement-imports",
    "/api/platform-admin/finance/reconciliation-exceptions",
    "/api/platform-admin/finance/reconciliation-exceptions/export",
    "/api/platform-admin/finance/refunds",
    "/api/platform-admin/finance/credit-notes",
    "/api/platform-admin/finance/chargebacks",
    "/api/platform-admin/finance/tds",
    "/api/platform-admin/case-tracking/support-matrix",
    "/api/platform-admin/case-tracking/support-matrix/{row_id}",
    "/api/admin/enterprise-readiness",
    "/api/case-tracking/support-matrix",
)


def _founder_token(client: TestClient, monkeypatch) -> str:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    return str(bootstrap_company(client)["access_token"])


def _current_totp(secret: str) -> str:
    return _hotp(secret, int(time.time()) // TOTP_PERIOD_SECONDS)


def test_pine_labs_uat_activation_blocker_and_billing_signoff(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)

    readiness = client.get(
        "/api/platform-admin/pine-labs/uat-readiness",
        headers=auth_headers(token),
    )
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["production_activation_blocked"] is True

    blocked = client.post(
        "/api/platform-admin/pine-labs/production-activation",
        headers=auth_headers(token),
        json={"founder_go_no_go": "go", "notes": "Founder smoke go decision."},
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["blocked"] is True

    run_id = readiness.json()["run_id"]
    for scenario in readiness.json()["missing_required_scenarios"]:
        evidence = client.post(
            "/api/platform-admin/pine-labs/uat-evidence",
            headers=auth_headers(token),
            json={
                "run_id": run_id,
                "scenario_code": scenario,
                "result_status": "pass",
                "provider_order_id": f"mock-{scenario}",
                "webhook_id": f"wh-{scenario}",
                "redacted_payload": {
                    "card_number": "4111111111111111",
                    "status": "pass",
                },
                "operator_notes": "mock harness evidence",
            },
        )
        assert evidence.status_code == 200, evidence.text
    ready = client.get(
        "/api/platform-admin/pine-labs/uat-readiness",
        headers=auth_headers(token),
    )
    assert ready.json()["complete"] is True
    assert ready.json()["production_activation_blocked"] is True
    assert any("runtime mode" in blocker for blocker in ready.json()["activation_blockers"])

    go = client.post(
        "/api/platform-admin/pine-labs/production-activation",
        headers=auth_headers(token),
        json={
            "run_id": run_id,
            "founder_go_no_go": "go",
            "notes": "Founder recorded UAT go decision.",
        },
    )
    assert go.status_code == 200, go.text
    assert go.json()["blocked"] is True
    assert any("runtime mode" in blocker for blocker in go.json()["missing_scenarios"])
    assert go.json()["provider_mode_unchanged"] != "production"

    signoff = client.get("/api/platform-admin/billing-signoff", headers=auth_headers(token))
    assert signoff.status_code == 200, signoff.text
    signoff_id = signoff.json()["signoff_id"]
    for check_code in signoff.json()["missing_required_checks"]:
        recorded = client.post(
            "/api/platform-admin/billing-signoff/evidence",
            headers=auth_headers(token),
            json={
                "signoff_id": signoff_id,
                "check_code": check_code,
                "result_status": "pass",
                "evidence_ref": f"smoke://{check_code}",
                "operator_notes": "authenticated smoke evidence",
            },
        )
        assert recorded.status_code == 200, recorded.text
    complete = client.get("/api/platform-admin/billing-signoff", headers=auth_headers(token))
    assert complete.json()["complete"] is True


def test_unified_readiness_and_secret_rotation_evidence_are_founder_only_and_secret_safe(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)

    readiness = client.get(
        "/api/platform-admin/production-readiness",
        headers=auth_headers(token),
    )
    assert readiness.status_code == 200, readiness.text
    payload = readiness.json()
    assert payload["ready"] is False
    assert any("secret rotation" in reason.lower() for reason in payload["not_ready_reasons"])
    assert any(gate["gate_code"] == "historical_secret_rotation" for gate in payload["gates"])

    enterprise = client.get("/api/admin/enterprise-readiness", headers=auth_headers(token))
    assert enterprise.status_code == 200, enterprise.text
    enterprise_payload = enterprise.json()
    assert enterprise_payload["enterprise_identity"]["enabled"] is False
    assert enterprise_payload["enterprise_identity"]["readiness_classification"] == "planned"
    assert (
        enterprise_payload["agent_trust_plane"]["autonomous_execution_enabled"] is False
    )

    rejected = client.post(
        "/api/platform-admin/secret-rotation-readiness/evidence",
        headers=auth_headers(token),
        json={
            "provider": "pine_labs_plural",
            "affected_app": "caseops-api",
            "credential_label": "webhook secret",
            "status": "blocked",
            "operator_notes": "Bearer this-must-not-be-stored",
        },
    )
    assert rejected.status_code == 400

    rejected_github_token = client.post(
        "/api/platform-admin/secret-rotation-readiness/evidence",
        headers=auth_headers(token),
        json={
            "provider": "github",
            "affected_app": "connector",
            "credential_label": "oauth client",
            "status": "blocked",
            "operator_notes": "Abcdefghijklmnopqrstuvwxyz1234567890ABCD",
        },
    )
    assert rejected_github_token.status_code == 400

    rejected_signoff_secret = client.post(
        "/api/platform-admin/billing-signoff/evidence",
        headers=auth_headers(token),
        json={
            "check_code": "tenant_no_leak_checks",
            "result_status": "pass",
            "evidence": {"client_secret": "do-not-store"},
        },
    )
    assert rejected_signoff_secret.status_code == 400

    recorded = client.post(
        "/api/platform-admin/secret-rotation-readiness/evidence",
        headers=auth_headers(token),
        json={
            "provider": "pine_labs_plural",
            "affected_app": "caseops-api",
            "credential_label": "webhook secret",
            "status": "validated",
            "old_credential_revoked": True,
            "validation_performed": True,
            "evidence_ref": "provider-ticket://pine-labs-rotation-proof",
            "residual_risk": "None after external proof is attached.",
            "operator_notes": "External evidence reference only; no credential value stored.",
        },
    )
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert body["complete"] is True
    assert "Bearer" not in recorded.text
    assert "this-must-not-be-stored" not in recorded.text

    with get_session_factory()() as session:
        row = session.scalar(select(ConnectorSecretRotationEvidence))
        assert row is not None
        assert row.status == "validated"
        assert "Bearer" not in (row.operator_notes or "")
        assert row.old_credential_revoked is True
        assert row.validation_performed is True


def test_finance_support_matrix_and_tenant_no_leak_paths(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)

    imported = client.post(
        "/api/platform-admin/finance/settlement-imports",
        headers=auth_headers(token),
        json={
            "source_filename": "mock-settlement.csv",
            "rows": [
                {
                    "provider_order_id": "unknown-order",
                    "amount_minor": 1000,
                    "provider_fee_minor": 25,
                    "tax_minor": 180,
                    "net_settlement_minor": 795,
                    "raw": {"row": 1},
                },
                {
                    "provider_order_id": "unknown-order",
                    "amount_minor": 1000,
                    "provider_fee_minor": 25,
                    "tax_minor": 180,
                    "net_settlement_minor": 795,
                    "raw": {"row": 1},
                },
            ],
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["exception_count"] >= 2

    exceptions = client.get(
        "/api/platform-admin/finance/reconciliation-exceptions",
        headers=auth_headers(token),
    )
    assert exceptions.status_code == 200, exceptions.text
    exception_types = {row["exception_type"] for row in exceptions.json()["rows"]}
    assert {"unknown_provider_order_id", "duplicate_settlement_row"} <= exception_types

    exported = client.get(
        "/api/platform-admin/finance/reconciliation-exceptions/export",
        headers=auth_headers(token),
    )
    assert exported.status_code == 200, exported.text
    assert b"exception_type" in exported.content

    matrix = client.post(
        "/api/platform-admin/case-tracking/support-matrix",
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "court": "Delhi High Court",
            "bench_jurisdiction": "Delhi",
            "lookup_method": "cnr",
            "refresh_cost_minor": 42,
            "bulk_refresh_cost_minor": 21,
            "rate_limit": "100/day",
            "freshness_sla": "24h",
            "legal_tos_status": "approved",
            "failure_code_mapping": {"404": "not_found"},
            "enabled": False,
            "tenant_visible": True,
        },
    )
    assert matrix.status_code == 200, matrix.text
    assert matrix.json()["rows"][0]["refresh_cost_minor"] == 42

    tenant_matrix = client.get(
        "/api/case-tracking/support-matrix",
        headers=auth_headers(token),
    )
    assert tenant_matrix.status_code == 200, tenant_matrix.text
    tenant_text = tenant_matrix.text
    assert "refresh_cost_minor" not in tenant_text
    assert "bulk_refresh_cost_minor" not in tenant_text
    assert tenant_matrix.json()["rows"][0]["enabled"] is False

    blocked_bookmark = client.post(
        "/api/case-tracking/bookmarks",
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "court_name": "Delhi High Court",
            "case_title": "Blocked v Matrix",
        },
    )
    assert blocked_bookmark.status_code == 402

    with get_session_factory()() as session:
        row = session.scalar(select(CaseTrackingSupportMatrix))
        assert row is not None
        assert row.refresh_cost_minor == 42


def test_mfa_step_up_recovery_codes_and_platform_grace(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)

    start = client.post("/api/auth/mfa/enroll", headers=auth_headers(token))
    assert start.status_code == 200, start.text
    secret = start.json()["secret"]
    verify = client.post(
        "/api/auth/mfa/enroll/verify",
        headers=auth_headers(token),
        json={"code": _current_totp(secret)},
    )
    assert verify.status_code == 200, verify.text
    recovery_code = verify.json()["recovery_codes"][0]

    with get_session_factory()() as session:
        platform = session.scalar(select(PlatformAdminMembership))
        assert platform is not None
        platform.mfa_enforced_at = datetime.now(UTC) - timedelta(minutes=1)
        session.execute(delete(UserMFAStepUp))
        session.commit()

    denied = client.get("/api/platform-admin/overview", headers=auth_headers(token))
    assert denied.status_code == 403
    assert denied.json()["type"] == "step_up_required"

    step_up = client.post(
        "/api/auth/mfa/step-up",
        headers=auth_headers(token),
        json={"code": _current_totp(secret), "purpose": "platform_admin_access"},
    )
    assert step_up.status_code == 200, step_up.text
    overview = client.get("/api/platform-admin/overview", headers=auth_headers(token))
    assert overview.status_code == 200, overview.text

    recovery = client.post(
        "/api/auth/mfa/step-up",
        headers=auth_headers(token),
        json={
            "code": recovery_code,
            "method": "recovery_code",
            "purpose": "billing_export",
        },
    )
    assert recovery.status_code == 200, recovery.text
    reused = client.post(
        "/api/auth/mfa/step-up",
        headers=auth_headers(token),
        json={
            "code": recovery_code,
            "method": "recovery_code",
            "purpose": "billing_export",
        },
    )
    assert reused.status_code == 403


def test_login_mfa_challenge_blocks_workspace_until_policy_requirement_is_met(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)
    policy = client.patch(
        "/api/admin/security-policy",
        headers=auth_headers(token),
        json={
            "all_users_mfa_required": True,
            "mfa_grace_period_days": 0,
            "reason": "Enable enforced login challenge in smoke test.",
        },
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["all_users_mfa_required"] is True

    login = client.post(
        "/api/auth/login",
        json={
            "email": "owner@asterlegal.in",
            "password": "FoundersPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    login_payload = login.json()
    assert login_payload["mfa_required"] is True
    assert login_payload["mfa_challenge_required"] is True
    assert login_payload["mfa_enrollment_required"] is True

    challenge_token = str(login_payload["access_token"])
    blocked = client.get("/api/matters/", headers=auth_headers(challenge_token))
    assert blocked.status_code == 403
    assert blocked.json()["type"] == "mfa_enrollment_required"

    security_status = client.get("/api/auth/security", headers=auth_headers(challenge_token))
    assert security_status.status_code == 200, security_status.text

    start = client.post("/api/auth/mfa/enroll", headers=auth_headers(challenge_token))
    assert start.status_code == 200, start.text
    assert "<svg" in start.json()["qr_svg"]
    assert "Use secret below" not in start.json()["qr_svg"]
    secret = start.json()["secret"]
    verify = client.post(
        "/api/auth/mfa/enroll/verify",
        headers=auth_headers(challenge_token),
        json={"code": _current_totp(secret)},
    )
    assert verify.status_code == 200, verify.text

    with get_session_factory()() as session:
        session.execute(delete(UserMFAStepUp))
        session.commit()

    login_enrolled = client.post(
        "/api/auth/login",
        json={
            "email": "owner@asterlegal.in",
            "password": "FoundersPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login_enrolled.status_code == 200, login_enrolled.text
    enrolled_payload = login_enrolled.json()
    assert enrolled_payload["mfa_required"] is True
    assert enrolled_payload["mfa_challenge_required"] is True
    assert enrolled_payload["mfa_enrollment_required"] is False

    enrolled_token = str(enrolled_payload["access_token"])
    step_up = client.post(
        "/api/auth/mfa/step-up",
        headers=auth_headers(enrolled_token),
        json={"code": _current_totp(secret), "purpose": "step_up"},
    )
    assert step_up.status_code == 200, step_up.text
    matters = client.get("/api/matters/", headers=auth_headers(enrolled_token))
    assert matters.status_code == 200, matters.text


def test_margin_readiness_and_password_reset_production_smoke_support(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _founder_token(client, monkeypatch)

    simulation = client.post(
        "/api/platform-admin/margin-simulations/run",
        headers=auth_headers(token),
        json={
            "scenario_name": "Solo light smoke",
            "scenario_code": "solo_light_user",
            "revenue_minor": 100000,
            "tracked_case_refreshes": 10,
        },
    )
    assert simulation.status_code == 200, simulation.text
    assert simulation.json()["uses_unapproved_estimated_costs"] is True
    assert simulation.json()["readiness_blocked"] is True

    readiness = client.get("/api/platform-admin/margin-readiness", headers=auth_headers(token))
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["blocked"] is True

    reset_readiness = client.get(
        "/api/platform-admin/password-reset-readiness",
        headers=auth_headers(token),
    )
    assert reset_readiness.status_code == 200, reset_readiness.text
    reset_payload = reset_readiness.json()
    assert reset_payload["reset_link_domain"] in {"localhost:3000", "testserver"}
    assert reset_payload["reset_path"] == "/account/reset-password"
    assert reset_payload["template_kind"] == "employee_password_reset_plain_text"
    assert reset_payload["secrets_exposed"] is False
    assert "sendgrid_api_key" not in reset_readiness.text.lower()
    assert "caseops-auth-secret" not in reset_readiness.text.lower()

    monkeypatch.setenv("CASEOPS_ENV", "cloud")
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    get_settings.cache_clear()
    reset = client.post(
        "/api/auth/password-reset/start",
        json={"email": "owner@asterlegal.in", "company_slug": "aster-legal"},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["debug_token"] is None
    with get_session_factory()() as session:
        assert session.scalar(select(BillingProviderEvent)) is None
