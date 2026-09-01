from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.security import create_access_token
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingAccount,
    BillingCreditLedger,
    BillingManualInvoice,
    BillingMarginSimulation,
    BillingPaymentOrder,
    BillingProviderEvent,
    BillingSubscription,
    BillingUsageAttribution,
    Company,
    CompanyMembership,
    Matter,
    PlatformAdminAuditEvent,
    PlatformAdminMembership,
    ProviderCostProfile,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.pine_labs import verify_pine_labs_plural_signature
from caseops_api.services.platform_admin import (
    ensure_configured_platform_super_admin,
    platform_capabilities_for_user,
    require_platform_admin,
)
from caseops_api.services.saas_billing import (
    assert_ai_credits_available,
    debit_ai_credits,
    ensure_billing_account,
)
from caseops_api.services.security import login_mfa_challenge_state
from caseops_api.services.session_context import SessionContext
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


def test_billing_account_creation_is_idempotent_across_parallel_sqlite_sessions(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    first_inserted = Event()
    release_first = Event()
    second_started = Event()
    factory = get_session_factory()

    def create_account(*, hold_transaction: bool) -> str:
        with factory() as session:
            company = session.get(Company, company_id)
            assert company is not None
            if not hold_transaction:
                second_started.set()
            account = ensure_billing_account(session, company)
            if hold_transaction:
                first_inserted.set()
                assert release_first.wait(timeout=5)

            # Both callers must retain a usable outer transaction. A recovery
            # that merely catches IntegrityError without a savepoint would
            # leave this statement (and the route's later commit) poisoned.
            assert session.scalar(select(1)) == 1
            session.commit()
            return account.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(create_account, hold_transaction=True)
        assert first_inserted.wait(timeout=5)
        second = executor.submit(create_account, hold_transaction=False)
        assert second_started.wait(timeout=5)
        try:
            with pytest.raises(FutureTimeoutError):
                second.result(timeout=0.25)
        finally:
            release_first.set()
        account_ids = {first.result(timeout=5), second.result(timeout=5)}

    with factory() as session:
        assert (
            session.scalar(
                select(func.count(BillingAccount.id)).where(
                    BillingAccount.company_id == company_id
                )
            )
            == 1
        )
    assert len(account_ids) == 1


def test_ai_credit_preflight_without_subscription_is_side_effect_free(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    factory = get_session_factory()
    with factory() as session:
        assert_ai_credits_available(
            session,
            company_id=company_id,
            estimated_credits=2,
        )
        assert session.scalar(
            select(func.count(BillingAccount.id)).where(
                BillingAccount.company_id == company_id
            )
        ) == 0
        assert session.scalar(
            select(func.count(BillingSubscription.id)).where(
                BillingSubscription.company_id == company_id
            )
        ) == 0
        assert not session.info.get("caseops_sqlite_write_lock_held", False)


def test_ai_credit_preflight_preserves_subscription_credit_and_tenant_semantics(
    client: TestClient,
) -> None:
    def bootstrap_named(slug: str, email: str) -> dict[str, object]:
        response = client.post(
            "/api/bootstrap/company",
            json={
                "company_name": f"{slug.title()} LLP",
                "company_slug": slug,
                "company_type": "law_firm",
                "owner_full_name": f"{slug.title()} Owner",
                "owner_email": email,
                "owner_password": "FoundersPass123!",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    limited = bootstrap_named("credit-limited", "owner@limited.in")
    other_tenant = bootstrap_named("credit-unlimited", "owner@unlimited.in")
    limited_company_id = str(limited["company"]["id"])
    other_company_id = str(other_tenant["company"]["id"])

    for payload in (limited, other_tenant):
        response = client.get(
            "/api/billing/current",
            headers=auth_headers(str(payload["access_token"])),
        )
        assert response.status_code == 200, response.text

    factory = get_session_factory()
    with factory() as session:
        assert_ai_credits_available(
            session,
            company_id=other_company_id,
            estimated_credits=10_000,
        )
        assert session.scalar(
            select(func.count(BillingCreditLedger.id)).where(
                BillingCreditLedger.company_id == other_company_id
            )
        ) == 0
        assert not session.info.get("caseops_sqlite_write_lock_held", False)

    with factory() as session:
        limited_subscription = session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.company_id == limited_company_id
            )
        )
        assert limited_subscription is not None
        limited_subscription.entitlement_overrides_json = {
            "ai_credits_monthly": 1,
        }
        other_subscription = session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.company_id == other_company_id
            )
        )
        assert other_subscription is not None
        other_subscription.entitlement_overrides_json = {
            "ai_credits_monthly": 100,
        }
        matter = Matter(
            company_id=limited_company_id,
            matter_code="SUBSCRIBED-AI-PREFLIGHT-RACE",
            title="Subscribed AI preflight lifecycle race",
            practice_area="civil",
            forum_level="high_court",
            status="intake",
        )
        session.add(matter)
        session.commit()
        matter_id = matter.id

    with factory() as request_session:
        # Each tenant sees only its own projected grant, and both missing
        # grants remain unmaterialized until a completion is successfully
        # debited.
        assert_ai_credits_available(
            request_session,
            company_id=other_company_id,
            estimated_credits=100,
        )
        assert_ai_credits_available(
            request_session,
            company_id=limited_company_id,
            estimated_credits=1,
        )
        with pytest.raises(HTTPException) as exc_info:
            assert_ai_credits_available(
                request_session,
                company_id=limited_company_id,
                estimated_credits=2,
            )
        assert exc_info.value.status_code == 402
        assert request_session.scalar(
            select(func.count(BillingCreditLedger.id)).where(
                BillingCreditLedger.company_id == limited_company_id
            )
        ) == 0
        assert not request_session.new
        assert not request_session.dirty
        assert not request_session.deleted
        assert not request_session.info.get("caseops_sqlite_write_lock_held", False)

        # This is the exact provider-callback shape that deadlocked when the
        # finite-credit preflight flushed its missing grant and retained the
        # process-wide SQLite writer lock.
        def dispose_from_provider_callback() -> None:
            with factory() as lifecycle_session:
                lifecycle_matter = lifecycle_session.get(Matter, matter_id)
                assert lifecycle_matter is not None
                lifecycle_matter.status = "disposed"
                lifecycle_matter.is_active = False
                lifecycle_session.commit()

        with ThreadPoolExecutor(max_workers=1) as executor:
            lifecycle_write = executor.submit(dispose_from_provider_callback)
            try:
                lifecycle_write.result(timeout=5)
            except FutureTimeoutError:
                request_session.rollback()
                lifecycle_write.result(timeout=5)
                pytest.fail("Subscribed AI preflight blocked the lifecycle writer")

    with factory() as session:
        debit_ai_credits(
            session,
            company_id=limited_company_id,
            actor_membership_id=None,
            matter_id=matter_id,
            purpose="matter_file_qa",
            credits=1,
            source_object_type="llm_completion",
            source_object_id="successful-completion",
        )
        session.commit()
        rows = list(
            session.scalars(
                select(BillingCreditLedger)
                .where(BillingCreditLedger.company_id == limited_company_id)
                .order_by(BillingCreditLedger.created_at, BillingCreditLedger.id)
            )
        )
        assert [row.delta for row in rows] == [1, -1]
        assert rows[-1].balance_after == 0

    with factory() as session:
        debit_ai_credits(
            session,
            company_id=other_company_id,
            actor_membership_id=None,
            matter_id=None,
            purpose="matter_file_qa",
            credits=1,
            source_object_type="llm_completion",
            source_object_id="other-tenant-completion",
        )
        session.commit()

    with factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            assert_ai_credits_available(
                session,
                company_id=limited_company_id,
                estimated_credits=1,
            )
        assert exc_info.value.status_code == 402
        assert_ai_credits_available(
            session,
            company_id=other_company_id,
            estimated_credits=99,
        )
        with pytest.raises(HTTPException) as other_exc_info:
            assert_ai_credits_available(
                session,
                company_id=other_company_id,
                estimated_credits=100,
            )
        assert other_exc_info.value.status_code == 402

    with factory() as session:
        expiring_grant = session.scalar(
            select(BillingCreditLedger).where(
                BillingCreditLedger.company_id == other_company_id,
                BillingCreditLedger.delta > 0,
            )
        )
        assert expiring_grant is not None
        expiring_grant.expires_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()

    with factory() as session:
        with pytest.raises(HTTPException) as expired_exc_info:
            assert_ai_credits_available(
                session,
                company_id=other_company_id,
                estimated_credits=1,
            )
        assert expired_exc_info.value.status_code == 402
        assert session.scalar(
            select(func.count(BillingCreditLedger.id)).where(
                BillingCreditLedger.company_id == other_company_id
            )
        ) == 2
        assert session.scalar(
            select(func.count(BillingCreditLedger.id)).where(
                BillingCreditLedger.company_id == other_company_id,
                BillingCreditLedger.event_type == "expiry",
            )
        ) == 0
        assert not session.info.get("caseops_sqlite_write_lock_held", False)


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


def test_platform_admin_seed_and_capability_lookup_are_write_idempotent(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    bootstrap_company(client)

    factory = get_session_factory()
    with factory() as session:
        founder = session.scalar(
            select(User).where(User.email == "owner@asterlegal.in")
        )
        assert founder is not None
        platform_admin = session.scalar(select(PlatformAdminMembership))
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.user_id == founder.id)
        )
        assert platform_admin is not None and membership is not None
        original_updated_at = platform_admin.updated_at
        context = SessionContext(
            company=membership.company,
            membership=membership,
            user=founder,
        )
        session.expunge(platform_admin)

        assert login_mfa_challenge_state(session, context=context)["mfa_required"]
        assert "platform:admin" in platform_capabilities_for_user(session, founder.id)
        assert membership_has_capability(session, membership, "matters:create")
        assert not any(
            isinstance(row, PlatformAdminMembership)
            for row in session.identity_map.values()
        )
        platform_admin = ensure_configured_platform_super_admin(session)
        assert platform_admin is not None
        session.flush()
        session.refresh(platform_admin)

        assert platform_admin.updated_at == original_updated_at
        assert not session.dirty


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
        ("GET", "/api/platform-admin/integrations", None),
        ("GET", "/api/platform-admin/cost-profiles", None),
        ("GET", "/api/platform-admin/margin-simulations", None),
        (
            "POST",
            "/api/platform-admin/cost-profiles",
            {
                "category": "case_refresh",
                "provider": "case_tracking",
                "unit_amount_minor": 10,
                "source": "Denied route test",
            },
        ),
        (
            "PATCH",
            "/api/platform-admin/cost-profiles/cost-deny",
            {"unit_amount_minor": 11},
        ),
        (
            "POST",
            "/api/platform-admin/margin-simulations/run",
            {
                "scenario_name": "Denied route test",
                "revenue_minor": 1000,
            },
        ),
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
        client.get("/api/platform-admin/integrations", headers=auth_headers(token)),
        client.get("/api/platform-admin/cost-profiles", headers=auth_headers(token)),
        client.get("/api/platform-admin/margin-simulations", headers=auth_headers(token)),
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
            "platform.integrations.viewed",
            "platform.cost_profiles.viewed",
            "platform.margin_simulations.viewed",
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


def test_platform_cost_profiles_and_margin_simulations_are_founder_only_audited(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    token = _bootstrap_token(client)

    create_cost = client.post(
        "/api/platform-admin/cost-profiles",
        headers=auth_headers(token),
        json={
            "category": "case_refresh",
            "provider": "case_tracking",
            "currency": "INR",
            "unit_amount_minor": 10,
            "source": "provider invoice",
            "notes": "Founder-reviewed actual refresh cost.",
        },
    )
    assert create_cost.status_code == 200, create_cost.text
    profile = create_cost.json()
    assert profile["created_by_platform_admin_id"]
    assert profile["unit_amount_minor"] == 10

    update_cost = client.patch(
        f"/api/platform-admin/cost-profiles/{profile['id']}",
        headers=auth_headers(token),
        json={"unit_amount_minor": 12, "source": "settlement reconciliation"},
    )
    assert update_cost.status_code == 200, update_cost.text
    assert update_cost.json()["unit_amount_minor"] == 12

    simulation = client.post(
        "/api/platform-admin/margin-simulations/run",
        headers=auth_headers(token),
        json={
            "scenario_name": "Founder smoke margin",
            "revenue_minor": 1999900,
            "tracked_case_refreshes": 1000,
            "ai_credits": 1200,
        },
    )
    assert simulation.status_code == 200, simulation.text
    body = simulation.json()
    assert body["result"]["gross_profit_minor"] < body["result"]["revenue_minor"]
    assert any(warning["type"] == "case_refresh_cost_guardrail" for warning in body["warnings"])

    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(func.count(ProviderCostProfile.id))) == 1
        assert session.scalar(select(func.count(BillingMarginSimulation.id))) == 1
        audit_actions = {
            row.action for row in session.scalars(select(PlatformAdminAuditEvent))
        }
        assert {
            "platform.cost_profile.created",
            "platform.cost_profile.updated",
            "platform.margin_simulation.ran",
        }.issubset(audit_actions)


def test_profit_rollup_uses_configured_provider_cost_profile_when_available(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    monkeypatch.setenv("CASEOPS_PINE_LABS_ENV", "mock")
    get_settings.cache_clear()
    token = _bootstrap_token(client)

    mdr = client.post(
        "/api/platform-admin/cost-profiles",
        headers=auth_headers(token),
        json={
            "category": "payment_mdr",
            "provider": "pine_labs_plural",
            "currency": "INR",
            "unit_amount_bps": 1000,
            "source": "MDR smoke",
        },
    )
    assert mdr.status_code == 200, mdr.text
    fixed = client.post(
        "/api/platform-admin/cost-profiles",
        headers=auth_headers(token),
        json={
            "category": "payment_fixed_fee",
            "provider": "pine_labs_plural",
            "currency": "INR",
            "unit_amount_minor": 25,
            "source": "MDR smoke",
        },
    )
    assert fixed.status_code == 200, fixed.text

    checkout = client.post(
        "/api/billing/checkout",
        headers=auth_headers(token),
        json={"plan_code": "solo_core", "interval": "month"},
    )
    assert checkout.status_code == 200, checkout.text
    checkout_payload = checkout.json()
    sync = client.post(
        f"/api/billing/checkout/{checkout_payload['id']}/sync",
        headers=auth_headers(token),
    )
    assert sync.status_code == 200, sync.text

    profit = client.get("/api/platform-admin/profit-report", headers=auth_headers(token))
    assert profit.status_code == 200, profit.text
    row = profit.json()["rows"][0]
    expected_cost = round(checkout_payload["total_amount_minor"] * 1000 / 10_000) + 25
    assert row["payment_provider_cost_minor"] == expected_cost


def test_tenant_integrations_registry_is_safe_and_audited(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "sendgrid-secret-token")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "billing@example.test")
    monkeypatch.setenv("CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY", "sendgrid-public-key")
    get_settings.cache_clear()
    token = _bootstrap_token(client)

    response = client.get("/api/admin/integrations", headers=auth_headers(token))

    assert response.status_code == 200, response.text
    text = response.text
    for forbidden in (
        "sendgrid-secret-token",
        "billing@example.test",
        "sendgrid-public-key",
        "internal_cost_label",
        "gross_profit",
        "gross_margin",
        "payment_provider_cost",
        "platform_notes",
    ):
        assert forbidden not in text
    body = response.json()
    keys = {connector["key"] for connector in body["connectors"]}
    assert {
        "outlook_calendar",
        "microsoft_mailbox",
        "gmail",
        "google_calendar",
        "google_drive",
        "pine_labs",
        "sendgrid",
        "sms",
        "whatsapp",
        "case_tracking",
        "prs_legal_updates",
        "temporal",
        "clamav",
        "storage",
    }.issubset(keys)
    pine = next(connector for connector in body["connectors"] if connector["key"] == "pine_labs")
    assert pine["enabled"] is False
    assert pine["blocked"] is True
    assert pine["status"] == "disabled"

    factory = get_session_factory()
    with factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "connector_registry.viewed")
        )
        assert audit is not None


def test_tenant_integrations_do_not_leak_other_tenant_outlook_sync_times(
    client: TestClient,
) -> None:
    tenant_a = bootstrap_company(client)
    token_a = str(tenant_a["access_token"])
    company_a = str(tenant_a["company"]["id"])
    membership_a = str(tenant_a["membership"]["id"])

    tenant_b_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Beta Legal",
            "company_slug": "beta-legal",
            "company_type": "law_firm",
            "owner_full_name": "Beta Owner",
            "owner_email": "owner@betalegal.in",
            "owner_password": "FoundersPass123!",
        },
    )
    assert tenant_b_response.status_code == 200, tenant_b_response.text
    token_b = str(tenant_b_response.json()["access_token"])

    factory = get_session_factory()
    with factory() as session:
        from caseops_api.db.models import (
            CalendarEventSync,
            CalendarEventSyncStatus,
            CalendarProvider,
            UserCalendarConnection,
        )

        connection = UserCalendarConnection(
            company_id=company_a,
            membership_id=membership_a,
            provider=CalendarProvider.OUTLOOK,
            status="connected",
            display_email="owner@asterlegal.in",
        )
        session.add(connection)
        session.flush()
        session.add(
            CalendarEventSync(
                company_id=company_a,
                calendar_connection_id=connection.id,
                source_type="matter_hearing",
                source_id="hearing-1",
                sync_status=CalendarEventSyncStatus.SYNCED,
                last_synced_at=datetime(2026, 6, 8, tzinfo=UTC),
            )
        )
        session.commit()

    a_response = client.get("/api/admin/integrations", headers=auth_headers(token_a))
    b_response = client.get("/api/admin/integrations", headers=auth_headers(token_b))

    assert a_response.status_code == 200, a_response.text
    assert b_response.status_code == 200, b_response.text
    a_outlook = next(
        connector
        for connector in a_response.json()["connectors"]
        if connector["key"] == "outlook_calendar"
    )
    b_outlook = next(
        connector
        for connector in b_response.json()["connectors"]
        if connector["key"] == "outlook_calendar"
    )
    assert a_outlook["last_success"] is not None
    assert b_outlook["last_success"] is None
