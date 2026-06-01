from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.security import create_access_token
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingCreditLedger,
    BillingManualInvoice,
    BillingPaymentOrder,
    BillingProviderEvent,
    BillingSubscription,
    BillingUsageAttribution,
    CompanyMembership,
    PlatformAdminAuditEvent,
    PlatformAdminMembership,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.identity import SessionContext
from caseops_api.services.pine_labs import verify_pine_labs_plural_signature
from caseops_api.services.platform_admin import require_platform_admin
from tests.test_auth_company import auth_headers, bootstrap_company


def _bootstrap_token(client: TestClient) -> str:
    return str(bootstrap_company(client)["access_token"])


def _plural_signature(body: bytes, webhook_id: str, timestamp: str) -> str:
    signed = f"{webhook_id}.{timestamp}.".encode() + body
    return base64.b64encode(
        hmac.new(b"pine-webhook-secret", signed, hashlib.sha256).digest()
    ).decode()


def test_billing_plan_catalog_seeded_from_prd(client: TestClient) -> None:
    response = client.get("/api/billing/plans")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"] == "2026.05.v1"
    plans = {plan["plan_code"]: plan for plan in payload["plans"]}
    add_ons = {plan["plan_code"]: plan for plan in payload["add_ons"]}

    expected_firm_plans = {
        "firm_starter": {
            "month": 599900,
            "year": 6299000,
            "users_internal_limit": 5,
            "matters_active_limit": 300,
            "tracked_cases_limit": 250,
            "ai_credits_monthly": 300,
            "storage_bytes_limit": 25 * 1024**3,
        },
        "firm_growth": {
            "month": 1999900,
            "year": 20999000,
            "users_internal_limit": 15,
            "matters_active_limit": 1500,
            "tracked_cases_limit": 1000,
            "ai_credits_monthly": 1200,
            "storage_bytes_limit": 150 * 1024**3,
        },
        "firm_pro": {
            "month": 4999900,
            "year": 52499000,
            "users_internal_limit": 50,
            "matters_active_limit": 5000,
            "tracked_cases_limit": 2500,
            "ai_credits_monthly": 3000,
            "storage_bytes_limit": 500 * 1024**3,
        },
    }
    for plan_code, expected in expected_firm_plans.items():
        plan = plans[plan_code]
        prices = {price["interval"]: price for price in plan["prices"]}
        assert prices["month"]["amount_minor"] == expected["month"]
        assert prices["year"]["amount_minor"] == expected["year"]
        assert prices["month"]["tax_rate_bps"] == 1800
        assert prices["year"]["tax_rate_bps"] == 1800
        for key, value in expected.items():
            if key in {"month", "year"}:
                continue
            assert plan["entitlements"][key] == value

    expected_add_ons = {
        "addon_user_firm": 69900,
        "addon_user_corporate_legal": 150000,
        "addon_viewer": 19900,
        "addon_cases_500": 249900,
        "addon_cases_1000": 449900,
        "addon_ai_250": 119900,
        "addon_ai_1000": 399900,
        "addon_ai_5000": 1499900,
        "addon_storage_100gb": 149900,
        "addon_api_access": 500000,
        "addon_migration_basic": 1000000,
        "addon_migration_firm": 2500000,
        "addon_migration_enterprise": 7500000,
        "addon_research_memo": 500000,
    }
    for add_on_code, amount_minor in expected_add_ons.items():
        prices = {price["interval"]: price for price in add_ons[add_on_code]["prices"]}
        assert next(iter(prices.values()))["amount_minor"] == amount_minor
    assert add_ons["addon_ai_250"]["entitlements"]["ai_credits_topup"] == 250


def test_current_billing_grandfathers_bootstrapped_tenant(client: TestClient) -> None:
    token = _bootstrap_token(client)

    response = client.get("/api/billing/current", headers=auth_headers(token))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["subscription"]["plan_code"] == "grandfathered_free"
    assert payload["subscription"]["externally_billable"] is False
    assert payload["entitlements"]["tracked_cases_limit"] is None
    assert payload["entitlements"]["storage_bytes_limit"] is None


def test_provider_disabled_checkout_does_not_activate_plan(client: TestClient) -> None:
    token = _bootstrap_token(client)

    checkout = client.post(
        "/api/billing/checkout",
        headers=auth_headers(token),
        json={"plan_code": "solo_core", "interval": "month"},
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["provider_disabled"] is True

    synced = client.post(
        f"/api/billing/checkout/{checkout.json()['id']}/sync",
        headers=auth_headers(token),
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["status"] == "provider_disabled"

    current = client.get("/api/billing/current", headers=auth_headers(token))
    assert current.json()["subscription"]["plan_code"] == "grandfathered_free"


def test_subscription_cancel_and_reactivate_routes(client: TestClient) -> None:
    token = _bootstrap_token(client)
    client.get("/api/billing/current", headers=auth_headers(token))

    cancelled = client.post(
        "/api/billing/subscription/cancel",
        headers=auth_headers(token),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["subscription"]["cancel_at_period_end"] is True

    reactivated = client.post(
        "/api/billing/subscription/reactivate",
        headers=auth_headers(token),
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["subscription"]["cancel_at_period_end"] is False


def test_missing_plural_payment_link_path_is_provider_disabled(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PINE_LABS_ENV", "uat")
    monkeypatch.setenv("CASEOPS_PINE_LABS_API_BASE_URL", "https://plural.invalid")
    monkeypatch.setenv("CASEOPS_PINE_LABS_CLIENT_ID", "client-id")
    monkeypatch.setenv("CASEOPS_PINE_LABS_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("CASEOPS_PINE_LABS_MERCHANT_ID", "merchant-id")
    monkeypatch.delenv("CASEOPS_PINE_LABS_PAYMENT_LINK_PATH", raising=False)
    get_settings.cache_clear()
    token = _bootstrap_token(client)

    checkout = client.post(
        "/api/billing/checkout",
        headers=auth_headers(token),
        json={"plan_code": "solo_core", "interval": "month"},
    )

    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["provider_disabled"] is True
    assert checkout.json()["status"] == "provider_disabled"


def test_trial_creation_blocks_duplicate_domain_mobile_or_gstin(client: TestClient) -> None:
    first = client.post(
        "/api/billing/trials",
        json={
            "company_name": "Trial One",
            "company_slug": "trial-one",
            "company_type": "law_firm",
            "owner_full_name": "Trial Owner",
            "owner_email": "owner@trialfirm.in",
            "owner_password": "TrialPass123!",
            "mobile": "+919999999999",
            "gstin": "09AANCM5923C1ZD",
            "selected_plan": "firm_starter",
        },
    )
    assert first.status_code == 200, first.text

    duplicate = client.post(
        "/api/billing/trials",
        json={
            "company_name": "Trial Two",
            "company_slug": "trial-two",
            "company_type": "law_firm",
            "owner_full_name": "Trial Owner Two",
            "owner_email": "other@trialfirm.in",
            "owner_password": "TrialPass456!",
            "mobile": "+918888888888",
            "gstin": "27ABCDE1234F1Z5",
            "selected_plan": "firm_starter",
        },
    )
    assert duplicate.status_code == 409


def test_mock_add_on_checkout_grants_credits_idempotently(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PINE_LABS_ENV", "mock")
    get_settings.cache_clear()
    token = _bootstrap_token(client)

    checkout = client.post(
        "/api/billing/add-ons/checkout",
        headers=auth_headers(token),
        json={"add_on_code": "addon_ai_250", "quantity": 2},
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["provider_disabled"] is False
    session_id = checkout.json()["id"]

    first = client.post(f"/api/billing/checkout/{session_id}/sync", headers=auth_headers(token))
    second = client.post(f"/api/billing/checkout/{session_id}/sync", headers=auth_headers(token))
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    factory = get_session_factory()
    with factory() as session:
        rows = list(
            session.scalars(
                select(BillingCreditLedger).where(
                    BillingCreditLedger.event_type == "topup_purchase"
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].delta == 500


def test_tenant_usage_report_hides_internal_costs(client: TestClient) -> None:
    token = _bootstrap_token(client)
    client.get("/api/billing/current", headers=auth_headers(token))
    factory = get_session_factory()
    with factory() as session:
        subscription = session.scalar(select(BillingSubscription))
        assert subscription is not None
        session.add(
            BillingUsageAttribution(
                company_id=subscription.company_id,
                subscription_id=subscription.id,
                feature_key="ai_generation",
                display_label="AI generation",
                credits_debited=3,
                provider_units=3,
                estimated_internal_cost_minor=999,
                tenant_visible=True,
            )
        )
        session.commit()

    response = client.get("/api/billing/usage", headers=auth_headers(token))

    assert response.status_code == 200, response.text
    body_text = response.text
    assert "estimated_internal_cost" not in body_text
    assert "profit" not in body_text.lower()
    assert response.json()["by_feature"][0]["credits"] == 3


def test_tenant_downloads_are_tenant_scoped_and_audited(client: TestClient) -> None:
    token = _bootstrap_token(client)
    client.get("/api/billing/current", headers=auth_headers(token))
    factory = get_session_factory()
    with factory() as session:
        subscription = session.scalar(select(BillingSubscription))
        assert subscription is not None
        invoice = BillingManualInvoice(
            company_id=subscription.company_id,
            subscription_id=subscription.id,
            invoice_number="BILL-001",
            amount_minor=100000,
            tax_amount_minor=18000,
            issued_on=__import__("datetime").date(2026, 5, 31),
            due_on=__import__("datetime").date(2026, 6, 30),
        )
        session.add(invoice)
        session.commit()
        invoice_id = invoice.id

    download = client.get(
        f"/api/billing/invoices/{invoice_id}/download",
        headers=auth_headers(token),
    )
    invoice_json = client.get(
        f"/api/billing/invoices/{invoice_id}/download?format=json",
        headers=auth_headers(token),
    )
    statement_csv = client.get("/api/billing/statement", headers=auth_headers(token))
    statement_pdf = client.get(
        "/api/billing/statement?format=pdf",
        headers=auth_headers(token),
    )
    ledger_export = client.get(
        "/api/billing/credit-ledger/export",
        headers=auth_headers(token),
    )
    payment_export = client.get(
        "/api/billing/payments/export",
        headers=auth_headers(token),
    )
    spend_export = client.get(
        "/api/billing/reports/spend/export",
        headers=auth_headers(token),
    )

    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF-")
    assert invoice_json.status_code == 200, invoice_json.text
    assert invoice_json.json()["invoice_number"] == "BILL-001"
    assert invoice_json.json()["seller"]["gstin"] == "09AANCM5923C1ZD"
    assert statement_csv.status_code == 200, statement_csv.text
    assert statement_pdf.status_code == 200, statement_pdf.text
    assert statement_pdf.content.startswith(b"%PDF-")
    assert ledger_export.status_code == 200, ledger_export.text
    assert ledger_export.headers["content-disposition"].endswith("caseops-credit-ledger.csv\"")
    assert payment_export.status_code == 200, payment_export.text
    assert payment_export.headers["content-disposition"].endswith("caseops-payments.csv\"")
    assert spend_export.status_code == 200, spend_export.text
    assert spend_export.headers["content-disposition"].endswith("caseops-spend-report.csv\"")

    with factory() as session:
        audit_count = session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action.in_(
                    [
                        "billing.invoice.downloaded",
                        "billing.statement.downloaded",
                        "billing.payments.exported",
                        "billing.credit_ledger.exported",
                        "billing.spend_report.exported",
                    ]
                )
            )
        )
        assert audit_count == 7


def test_plural_signature_verification_accepts_base64_hmac() -> None:
    body = b'{"order_id":"mock-order","status":"paid"}'
    webhook_id = "wh_123"
    timestamp = str(int(time.time()))
    signature = _plural_signature(body, webhook_id, timestamp)

    assert verify_pine_labs_plural_signature(
        raw_body=body,
        webhook_id=webhook_id,
        webhook_timestamp=timestamp,
        signature=signature,
        secret="pine-webhook-secret",
    )


def test_plural_webhook_rejects_bad_signature_before_json_parse(client: TestClient) -> None:
    body = b"{not-json"
    response = client.post(
        "/api/payments/pine-labs/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "webhook-id": "wh-bad-json",
            "webhook-timestamp": str(int(time.time())),
            "webhook-signature": "definitely-wrong",
        },
    )

    assert response.status_code == 401


def test_billing_webhook_is_idempotent_and_out_of_order_safe(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PINE_LABS_ENV", "mock")
    get_settings.cache_clear()
    token = _bootstrap_token(client)
    checkout = client.post(
        "/api/billing/checkout",
        headers=auth_headers(token),
        json={"plan_code": "solo_core", "interval": "month"},
    )
    assert checkout.status_code == 200, checkout.text
    provider_order_id = checkout.json()["provider_order_id"]
    payload = {"order_id": provider_order_id, "status": "paid", "amount_received_minor": 99900}
    body = json.dumps(payload, separators=(",", ":")).encode()
    webhook_id = "wh-billing-1"
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": _plural_signature(body, webhook_id, timestamp),
    }

    first = client.post("/api/payments/pine-labs/webhook", content=body, headers=headers)
    second = client.post("/api/payments/pine-labs/webhook", content=body, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["already_processed"] is True

    failed_payload = {"order_id": provider_order_id, "status": "failed"}
    failed_body = json.dumps(failed_payload, separators=(",", ":")).encode()
    failed_id = "wh-billing-2"
    failed_ts = str(int(time.time()))
    failed = client.post(
        "/api/payments/pine-labs/webhook",
        content=failed_body,
        headers={
            "Content-Type": "application/json",
            "webhook-id": failed_id,
            "webhook-timestamp": failed_ts,
            "webhook-signature": _plural_signature(failed_body, failed_id, failed_ts),
        },
    )
    assert failed.status_code == 200, failed.text

    factory = get_session_factory()
    with factory() as session:
        order = session.scalar(select(BillingPaymentOrder))
        assert order is not None
        assert order.status == "paid"
        event_statuses = {
            row.processing_status for row in session.scalars(select(BillingProviderEvent))
        }
        assert "ignored_out_of_order" in event_statuses
        first_event = session.scalar(
            select(BillingProviderEvent).where(BillingProviderEvent.webhook_id == webhook_id)
        )
        assert first_event is not None
        assert first_event.signature_digest != headers["webhook-signature"]
        assert first_event.signature_digest == hashlib.sha256(
            headers["webhook-signature"].encode()
        ).hexdigest()


def test_platform_admin_is_founder_only_and_audited(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    bootstrap_payload = bootstrap_company(client)
    founder_token = str(bootstrap_payload["access_token"])

    founder = client.get("/api/platform-admin/overview", headers=auth_headers(founder_token))
    assert founder.status_code == 200, founder.text

    create_admin = client.post(
        "/api/companies/current/users",
        headers=auth_headers(founder_token),
        json={
            "full_name": "Tenant Admin",
            "email": "admin@asterlegal.in",
            "password": "AdminPass123!",
            "role": "admin",
        },
    )
    assert create_admin.status_code == 200, create_admin.text
    factory = get_session_factory()
    with factory() as session:
        admin_user = session.scalar(select(User).where(User.email == "admin@asterlegal.in"))
        assert admin_user is not None
        admin_membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.user_id == admin_user.id)
        )
        assert admin_membership is not None
        admin_token = create_access_token(
            user_id=admin_user.id,
            company_id=admin_membership.company_id,
            membership_id=admin_membership.id,
            role=admin_membership.role,
        )
    admin_route = client.get(
        "/api/platform-admin/overview",
        headers=auth_headers(admin_token),
    )
    assert admin_route.status_code == 403

    with factory() as session:
        admin_user = session.scalar(select(User).where(User.email == "admin@asterlegal.in"))
        assert admin_user is not None
        admin_membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.user_id == admin_user.id)
        )
        assert admin_membership is not None
        try:
            require_platform_admin(
                session,
                SessionContext(
                    company=admin_membership.company,
                    user=admin_user,
                    membership=admin_membership,
                ),
            )
            raise AssertionError("tenant admin unexpectedly received platform access")
        except HTTPException as exc:
            assert exc.status_code == 403
        audit_count = session.scalar(select(func.count(PlatformAdminAuditEvent.id)))
        assert audit_count == 3


def test_tenant_owner_is_denied_from_platform_admin_route_surface(
    client: TestClient,
) -> None:
    token = _bootstrap_token(client)
    company_id = "company-deny"
    invoice_id = "invoice-deny"
    event_id = "event-deny"
    routes: list[tuple[str, str, dict[str, object] | None]] = [
        ("GET", "/api/platform-admin/enrollments", None),
        ("GET", f"/api/platform-admin/companies/{company_id}/billing", None),
        ("GET", "/api/platform-admin/provider-events", None),
        ("GET", "/api/platform-admin/usage-report", None),
        ("GET", "/api/platform-admin/profit/export", None),
        ("GET", "/api/platform-admin/revenue/export", None),
        ("GET", "/api/platform-admin/coupons", None),
        ("GET", "/api/platform-admin/margin-alerts", None),
        (
            "POST",
            f"/api/platform-admin/companies/{company_id}/subscription",
            {
                "status": "manual_active",
                "billing_interval": "custom",
                "reason": "Denied route test",
            },
        ),
        (
            "POST",
            f"/api/platform-admin/companies/{company_id}/subscription/suspend",
            {"reason": "Denied route test"},
        ),
        (
            "POST",
            f"/api/platform-admin/companies/{company_id}/subscription/resume",
            {"reason": "Denied route test"},
        ),
        (
            "POST",
            f"/api/platform-admin/companies/{company_id}/credits/grant",
            {"credits": 1, "reason": "Denied route test"},
        ),
        (
            "POST",
            "/api/platform-admin/manual-invoices",
            {
                "company_id": company_id,
                "invoice_number": "DENY-001",
                "amount_minor": 100,
                "tax_amount_minor": 18,
                "reason": "Denied route test",
            },
        ),
        (
            "POST",
            f"/api/platform-admin/manual-invoices/{invoice_id}/mark-paid",
            {
                "amount_received_minor": 100,
                "tds_deducted_minor": 0,
                "payment_reference": "DENY",
                "reason": "Denied route test",
            },
        ),
        (
            "POST",
            f"/api/platform-admin/provider-events/{event_id}/reprocess",
            {"reason": "Denied route test"},
        ),
        (
            "POST",
            "/api/platform-admin/coupons",
            {
                "code": "DENY10",
                "discount_type": "percent",
                "discount_value": 10,
                "reason": "Denied route test",
            },
        ),
        (
            "PUT",
            f"/api/platform-admin/companies/{company_id}/overage-policy",
            {"overage_allowed": False, "unit_prices": {}, "reason": "Denied route test"},
        ),
    ]

    for method, path, body in routes:
        response = client.request(method, path, headers=auth_headers(token), json=body)
        assert response.status_code == 403, f"{method} {path}: {response.text}"


def test_founder_platform_admin_read_routes_and_exports_are_audited(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])
    company_id = str(bootstrap_payload["company"]["id"])

    requests = [
        client.get("/api/platform-admin/enrollments", headers=auth_headers(token)),
        client.get(
            f"/api/platform-admin/companies/{company_id}/billing",
            headers=auth_headers(token),
        ),
        client.get("/api/platform-admin/provider-events", headers=auth_headers(token)),
        client.get("/api/platform-admin/usage-report", headers=auth_headers(token)),
        client.get("/api/platform-admin/profit/export", headers=auth_headers(token)),
        client.get("/api/platform-admin/revenue/export", headers=auth_headers(token)),
        client.get("/api/platform-admin/coupons", headers=auth_headers(token)),
        client.get("/api/platform-admin/margin-alerts", headers=auth_headers(token)),
    ]

    assert all(response.status_code == 200 for response in requests), [
        response.text for response in requests
    ]
    assert requests[4].headers["content-disposition"].endswith("caseops-platform-profit.csv\"")
    assert requests[5].headers["content-disposition"].endswith("caseops-platform-revenue.csv\"")

    factory = get_session_factory()
    with factory() as session:
        audit_actions = {
            row.action for row in session.scalars(select(PlatformAdminAuditEvent))
        }
        assert {
            "platform.enrollments.viewed",
            "platform.company_billing.viewed",
            "platform.provider_events.viewed",
            "platform.usage_report.viewed",
            "platform.profit_report.exported",
            "platform.revenue_report.exported",
            "platform.coupons.viewed",
            "platform.margin_alerts.viewed",
        }.issubset(audit_actions)


def test_configured_platform_super_admin_must_be_owner(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "admin@asterlegal.in")
    get_settings.cache_clear()
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])
    create_admin = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Tenant Admin",
            "email": "admin@asterlegal.in",
            "password": "AdminPass123!",
            "role": "admin",
        },
    )
    assert create_admin.status_code == 200, create_admin.text

    admin_login = client.post(
        "/api/auth/login",
        json={
            "email": "admin@asterlegal.in",
            "password": "AdminPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert admin_login.status_code == 200, admin_login.text
    assert "platform:admin" not in admin_login.json()["capabilities"]
    denied = client.get(
        "/api/platform-admin/overview",
        headers=auth_headers(str(admin_login.json()["access_token"])),
    )
    assert denied.status_code == 403
    factory = get_session_factory()
    with factory() as session:
        active = session.scalar(
            select(func.count(PlatformAdminMembership.id)).where(
                PlatformAdminMembership.status == "active"
            )
        )
        assert active == 0


def test_platform_profit_report_exposes_internal_costs_to_founder_only(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    monkeypatch.setenv("CASEOPS_PINE_LABS_ENV", "mock")
    get_settings.cache_clear()
    token = _bootstrap_token(client)

    checkout = client.post(
        "/api/billing/checkout",
        headers=auth_headers(token),
        json={"plan_code": "solo_core", "interval": "month"},
    )
    checkout_payload = checkout.json()
    client.post(f"/api/billing/checkout/{checkout_payload['id']}/sync", headers=auth_headers(token))

    profit = client.get("/api/platform-admin/profit-report", headers=auth_headers(token))

    assert profit.status_code == 200, profit.text
    rows = profit.json()["rows"]
    assert rows
    row = rows[0]
    assert row["gross_revenue_minor"] == checkout_payload["amount_minor"]
    assert row["recognized_revenue_minor"] == checkout_payload["amount_minor"]
    assert row["tax_minor"] == checkout_payload["tax_amount_minor"]
    assert "payment_provider_cost_minor" in row
    assert "total_variable_cost_minor" in row
    assert "gross_profit_minor" in row

    company_profit = client.get(
        "/api/platform-admin/companies/profitability",
        headers=auth_headers(token),
    )
    assert company_profit.status_code == 200, company_profit.text
    company_row = company_profit.json()["companies"][0]
    assert company_row["gross_revenue_minor"] == checkout_payload["amount_minor"]
    assert company_row["recognized_revenue_minor"] == checkout_payload["amount_minor"]
    assert "payment_provider_cost_minor" in company_row
