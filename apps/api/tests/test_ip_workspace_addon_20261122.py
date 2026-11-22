"""The paid IP workspace add-on (owner decision 2026-11-22).

Rs 9,999 a month or Rs 99,990 a year, GST-exclusive, sold only on Firm and GC
plans. It grants exactly the entitlement keys the IP gates check, through the
same entitlement resolution and gate code the rest of the product uses. It is
activated by the platform admin after an invoice (production) or by a paid
mock/UAT checkout.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingPlanVersion,
    BillingSubscription,
    BillingSubscriptionItem,
    CompanyMembership,
    PlatformAdminAuditEvent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_capability_catalog import IP_FEATURES, assert_ip_feature_entitled
from caseops_api.services.qa_manual_ip_entitlement import FULL_IP_ENTITLEMENT_KEYS
from caseops_api.services.saas_billing import current_entitlements_for_company
from caseops_api.services.session_context import SessionContext
from tests.migration_index_catalog import require_revision
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config

ADD_ON = "addon_ip_workspace"
PARENT = "20261122_0001"
HEAD = "20261122_0002"
MIGRATION = Path(__file__).resolve().parents[1] / (
    "alembic/versions/20261122_0002_ip_workspace_addon.py"
)
IP_KEYS = sorted({feature.entitlement_key for feature in IP_FEATURES})
REFUSAL = "The IP workspace add-on is restore-forward; restore the reviewed backup."


def _founder(client: TestClient, monkeypatch) -> str:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    return str(bootstrap_company(client)["access_token"])


def _tenant(client: TestClient, slug: str, *, company_type: str = "law_firm") -> tuple[str, str]:
    response = client.post(
        "/api/billing/trials",
        json={
            "company_name": f"{slug.title()} Associates",
            "company_slug": slug,
            "company_type": company_type,
            "owner_full_name": "Tenant Owner",
            "owner_email": f"owner@{slug}.example.com",
            "owner_password": "TenantPass123!",
            "source": "sign_in",
        },
    )
    assert response.status_code == 200, response.text
    auth = response.json()["auth"]
    return str(auth["access_token"]), str(auth["company"]["id"])


def _assign_plan(client: TestClient, founder: str, company_id: str, plan_code: str) -> None:
    response = client.post(
        f"/api/platform-admin/companies/{company_id}/subscription",
        headers=auth_headers(founder),
        json={
            "plan_code": plan_code,
            "billing_interval": "month",
            "status": "manual_active",
            "reason": "Invoice settled for the requested plan",
        },
    )
    assert response.status_code == 200, response.text


def _set_add_on(
    client: TestClient,
    founder: str,
    company_id: str,
    *,
    status: str = "active",
    interval: str = "year",
):
    return client.post(
        f"/api/platform-admin/companies/{company_id}/subscription/add-ons",
        headers=auth_headers(founder),
        json={
            "add_on_code": ADD_ON,
            "billing_interval": interval,
            "status": status,
            "reason": "Invoice settled for the IP workspace add-on",
        },
    )


def _entitled(client: TestClient, token: str) -> dict[str, bool]:
    response = client.get("/api/ip/readiness", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return {row["feature_id"]: row["entitled"] for row in response.json()["features"]}


def _all_ip(value: bool) -> dict[str, bool]:
    return {feature.feature_id: value for feature in IP_FEATURES}


def _writer_gate(company_id: str) -> HTTPException | None:
    with get_session_factory()() as session:
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == company_id)
        )
        assert membership is not None
        context = SessionContext(
            company=membership.company, user=membership.user, membership=membership
        )
        try:
            assert_ip_feature_entitled(session, context=context, feature_id="workspace_core")
        except HTTPException as exc:
            return exc
    return None


def _items(company_id: str) -> list[tuple[str, str, int | None, str]]:
    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription).where(BillingSubscription.company_id == company_id)
        )
        assert subscription is not None
        return [
            (item.item_code, item.interval, item.amount_minor, item.status)
            for item in session.scalars(
                select(BillingSubscriptionItem)
                .where(
                    BillingSubscriptionItem.subscription_id == subscription.id,
                    BillingSubscriptionItem.item_type == "add_on",
                )
                .order_by(BillingSubscriptionItem.created_at)
            )
        ]


def test_catalog_lists_the_ip_workspace_add_on_at_the_owner_prices(client: TestClient) -> None:
    response = client.get("/api/billing/plans")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"] == "2026.11.v1"
    add_on = {row["plan_code"]: row for row in payload["add_ons"]}[ADD_ON]
    assert add_on["display_name"] == "IP workspace"
    assert add_on["segment"] == "add_on"
    assert add_on["publicly_visible"] is True
    assert add_on["trial_eligible"] is False
    assert add_on["eligible_segments"] == ["firm", "gc"]
    prices = {
        price["interval"]: (price["amount_minor"], price["tax_behavior"], price["tax_rate_bps"])
        for price in add_on["prices"]
    }
    assert prices == {
        "month": (999900, "exclusive", 1800),
        "year": (9999000, "exclusive", 1800),
    }
    # Annual is ten months, the catalog convention.
    assert prices["year"][0] == prices["month"][0] * 10
    assert add_on["entitlements"] == dict.fromkeys(IP_KEYS, True)
    # Other add-ons stay unrestricted, and no base plan is sold with IP.
    assert {row["plan_code"]: row["eligible_segments"] for row in payload["add_ons"]}[
        "addon_storage_100gb"
    ] is None
    for plan in payload["plans"]:
        assert not any(key.startswith("ip_") for key in plan["entitlements"]), plan["plan_code"]


def test_add_on_grants_exactly_the_keys_the_ip_gates_check(client: TestClient) -> None:
    assert IP_KEYS == sorted(FULL_IP_ENTITLEMENT_KEYS)
    with get_session_factory()() as session:
        plan = session.scalar(
            select(BillingPlanVersion).where(
                BillingPlanVersion.plan_code == ADD_ON,
                BillingPlanVersion.version == "2026.11.v1",
            )
        )
        assert plan is not None
        assert sorted(row.entitlement_key for row in plan.entitlements) == IP_KEYS
        assert {row.value_type for row in plan.entitlements} == {"boolean"}
        assert {row.value_json for row in plan.entitlements} == {True}


def test_invoice_activation_turns_ip_on_and_ending_turns_it_off_with_audit(
    client: TestClient, monkeypatch
) -> None:
    founder = _founder(client, monkeypatch)
    token, company_id = _tenant(client, "kapoor-ip")
    _assign_plan(client, founder, company_id, "firm_growth")

    # Off: a Firm plan without the add-on does not include IP.
    assert _entitled(client, token) == _all_ip(False)
    refused = _writer_gate(company_id)
    assert refused is not None and refused.status_code == 403
    assert refused.detail["reason"] == "missing_entitlement"
    assert "plan does not include ip_workspace" in refused.detail["detail"]

    activated = _set_add_on(client, founder, company_id, interval="year")
    assert activated.status_code == 200, activated.text
    assert activated.json()["entitlements"]["ip_workspace"] is True
    assert _items(company_id) == [(ADD_ON, "year", 9999000, "active")]
    assert _entitled(client, token) == _all_ip(True)
    assert _writer_gate(company_id) is None

    # Re-activating switches the term instead of stacking a second item.
    monthly = _set_add_on(client, founder, company_id, interval="month")
    assert monthly.status_code == 200, monthly.text
    assert _items(company_id) == [(ADD_ON, "month", 999900, "active")]

    ended = _set_add_on(client, founder, company_id, status="ended")
    assert ended.status_code == 200, ended.text
    assert _items(company_id) == [(ADD_ON, "month", 999900, "ended")]
    assert _entitled(client, token) == _all_ip(False)
    assert _writer_gate(company_id) is not None
    assert _set_add_on(client, founder, company_id, status="ended").status_code == 404

    with get_session_factory()() as session:
        platform_actions = list(
            session.scalars(
                select(PlatformAdminAuditEvent.action)
                .where(
                    PlatformAdminAuditEvent.company_id == company_id,
                    PlatformAdminAuditEvent.target_type == "billing_subscription_item",
                )
                .order_by(PlatformAdminAuditEvent.created_at)
            )
        )
        tenant_rows = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action.like("billing.add_on.%"),
                )
                .order_by(AuditEvent.created_at)
            )
        )
    assert platform_actions == [
        "platform.subscription.add_on_activated",
        "platform.subscription.add_on_activated",
        "platform.subscription.add_on_ended",
    ]
    assert [row.action for row in tenant_rows] == [
        "billing.add_on.activated",
        "billing.add_on.activated",
        "billing.add_on.ended",
    ]
    assert {row.actor_type for row in tenant_rows} == {"system"}
    assert {row.actor_label for row in tenant_rows} == {"platform_admin"}


def test_add_on_expires_with_its_subscription(client: TestClient, monkeypatch) -> None:
    founder = _founder(client, monkeypatch)
    token, company_id = _tenant(client, "expiry-ip")
    _assign_plan(client, founder, company_id, "gc_starter")
    assert _set_add_on(client, founder, company_id).status_code == 200
    assert _entitled(client, token) == _all_ip(True)

    for lapsed in ("expired", "past_due", "suspended"):
        response = client.post(
            f"/api/platform-admin/companies/{company_id}/subscription",
            headers=auth_headers(founder),
            json={"billing_interval": "year", "status": lapsed, "reason": "Invoice unpaid"},
        )
        assert response.status_code == 200, response.text
        with get_session_factory()() as session:
            entitlements = current_entitlements_for_company(session, company_id)
        assert not any(key.startswith("ip_") for key in entitlements), lapsed
        assert _writer_gate(company_id) is not None, lapsed

    resumed = client.post(
        f"/api/platform-admin/companies/{company_id}/subscription/resume",
        headers=auth_headers(founder),
        json={"reason": "Invoice settled"},
    )
    assert resumed.status_code == 200, resumed.text
    assert _entitled(client, token) == _all_ip(True)


def test_solo_and_trial_plans_cannot_buy_or_keep_the_add_on(
    client: TestClient, monkeypatch
) -> None:
    founder = _founder(client, monkeypatch)
    token, company_id = _tenant(client, "solo-ip", company_type="solo")

    # A trial (any company type) is not a Firm or GC plan.
    trial = _set_add_on(client, founder, company_id)
    assert trial.status_code == 409, trial.text
    assert trial.json()["code"] == "add_on_not_available_on_plan"

    _assign_plan(client, founder, company_id, "solo_elite")
    refused = _set_add_on(client, founder, company_id)
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert (body["code"], body["add_on_code"], body["detail"]) == (
        "add_on_not_available_on_plan",
        ADD_ON,
        "IP workspace is available only on Firm and GC plans.",
    )
    assert _items(company_id) == []

    monkeypatch.setenv("CASEOPS_PINE_LABS_ENV", "mock")
    get_settings.cache_clear()
    checkout = client.post(
        "/api/billing/add-ons/checkout",
        headers=auth_headers(token),
        json={"add_on_code": ADD_ON, "interval": "year"},
    )
    assert checkout.status_code == 409, checkout.text
    assert checkout.json()["code"] == "add_on_not_available_on_plan"

    # A Firm company that keeps the item after moving to Solo loses IP.
    _assign_plan(client, founder, company_id, "firm_starter")
    assert _set_add_on(client, founder, company_id).status_code == 200
    assert _entitled(client, token) == _all_ip(True)
    _assign_plan(client, founder, company_id, "solo_pro")
    assert _items(company_id) == [(ADD_ON, "year", 9999000, "active")]
    assert _entitled(client, token) == _all_ip(False)
    assert _writer_gate(company_id) is not None


def test_another_tenants_add_on_never_grants_access(client: TestClient, monkeypatch) -> None:
    founder = _founder(client, monkeypatch)
    buyer_token, buyer_id = _tenant(client, "buyer-ip")
    other_token, other_id = _tenant(client, "other-ip")
    _assign_plan(client, founder, buyer_id, "firm_growth")
    _assign_plan(client, founder, other_id, "firm_growth")
    assert _set_add_on(client, founder, buyer_id).status_code == 200

    assert _entitled(client, buyer_token) == _all_ip(True)
    assert _entitled(client, other_token) == _all_ip(False)
    assert _writer_gate(other_id) is not None
    assert _items(other_id) == []
    with get_session_factory()() as session:
        assert not any(
            key.startswith("ip_") for key in current_entitlements_for_company(session, other_id)
        )

    # A tenant owner cannot reach the platform activation route, for itself or
    # for the buyer.
    for target in (other_id, buyer_id):
        denied = _set_add_on(client, other_token, target)
        assert denied.status_code == 403, denied.text
    assert _entitled(client, other_token) == _all_ip(False)


def test_mock_checkout_sells_the_add_on_monthly_or_annually(
    client: TestClient, monkeypatch
) -> None:
    founder = _founder(client, monkeypatch)
    annual_token, annual_id = _tenant(client, "annual-ip")
    monthly_token, monthly_id = _tenant(client, "monthly-ip")
    _assign_plan(client, founder, annual_id, "firm_pro")
    _assign_plan(client, founder, monthly_id, "gc_professional")
    monkeypatch.setenv("CASEOPS_PINE_LABS_ENV", "mock")
    get_settings.cache_clear()

    for token, company_id, interval, amount in (
        (annual_token, annual_id, "year", 9999000),
        (monthly_token, monthly_id, "month", 999900),
    ):
        checkout = client.post(
            "/api/billing/add-ons/checkout",
            headers=auth_headers(token),
            json={"add_on_code": ADD_ON, "interval": interval},
        )
        assert checkout.status_code == 200, checkout.text
        body = checkout.json()
        assert body["checkout_type"] == "addon"
        assert body["provider_disabled"] is False
        # GST-exclusive: 18% is added on top.
        assert (body["amount_minor"], body["tax_amount_minor"]) == (amount, amount * 18 // 100)
        assert body["total_amount_minor"] == amount + amount * 18 // 100
        assert _entitled(client, token) == _all_ip(False)

        synced = client.post(
            f"/api/billing/checkout/{body['id']}/sync", headers=auth_headers(token)
        )
        assert synced.status_code == 200, synced.text
        assert synced.json()["status"] == "paid"
        assert _items(company_id) == [(ADD_ON, interval, amount, "active")]
        assert _entitled(client, token) == _all_ip(True)

        again = client.post(
            "/api/billing/add-ons/checkout",
            headers=auth_headers(token),
            json={"add_on_code": ADD_ON, "interval": interval},
        )
        assert again.status_code == 409, again.text
        with get_session_factory()() as session:
            audit = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "billing.add_on.activated",
                )
            )
            assert audit is not None
            assert (audit.actor_type, audit.actor_label) == ("system", "billing_payment")

    # The founder's own grandfathered (internal) tenant is not eligible.
    internal = client.post(
        "/api/billing/add-ons/checkout",
        headers=auth_headers(founder),
        json={"add_on_code": ADD_ON},
    )
    assert internal.status_code == 409, internal.text

    # One add-on is all a workspace can use, so it cannot be bought twice over.
    quantity_token, quantity_id = _tenant(client, "quantity-ip")
    _assign_plan(client, founder, quantity_id, "firm_starter")
    two = client.post(
        "/api/billing/add-ons/checkout",
        headers=auth_headers(quantity_token),
        json={"add_on_code": ADD_ON, "quantity": 2},
    )
    assert two.status_code == 400, two.text
    assert _items(quantity_id) == []


def test_provider_disabled_checkout_does_not_grant_ip(client: TestClient, monkeypatch) -> None:
    founder = _founder(client, monkeypatch)
    token, company_id = _tenant(client, "disabled-ip")
    _assign_plan(client, founder, company_id, "firm_growth")

    checkout = client.post(
        "/api/billing/add-ons/checkout",
        headers=auth_headers(token),
        json={"add_on_code": ADD_ON, "interval": "month"},
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["provider_disabled"] is True
    synced = client.post(
        f"/api/billing/checkout/{checkout.json()['id']}/sync", headers=auth_headers(token)
    )
    assert synced.json()["status"] == "provider_disabled"
    assert _items(company_id) == []
    assert _entitled(client, token) == _all_ip(False)


def _catalog_rows(engine) -> tuple[list[tuple], list[tuple], list[tuple]]:
    plans = sa.table(
        "billing_plan_versions",
        sa.column("id"),
        sa.column("plan_code"),
        sa.column("version"),
        sa.column("segment"),
        sa.column("display_name"),
        sa.column("status"),
        sa.column("publicly_visible", sa.Boolean),
        sa.column("trial_eligible", sa.Boolean),
        sa.column("feature_summary_json", sa.JSON),
    )
    prices = sa.table(
        "billing_plan_prices",
        sa.column("id"),
        sa.column("plan_version_id"),
        sa.column("currency"),
        sa.column("amount_minor"),
        sa.column("interval"),
        sa.column("tax_behavior"),
        sa.column("tax_rate_bps"),
        sa.column("provider_plan_reference"),
    )
    entitlements = sa.table(
        "billing_plan_entitlements",
        sa.column("plan_version_id"),
        sa.column("entitlement_key"),
        sa.column("value_type"),
        sa.column("value_json", sa.JSON),
    )
    with engine.connect() as connection:
        plan_rows = [
            tuple(row)
            for row in connection.execute(
                select(plans).where(plans.c.plan_code == ADD_ON).order_by(plans.c.id)
            )
        ]
        price_rows = [
            tuple(row)
            for row in connection.execute(
                select(prices)
                .where(prices.c.plan_version_id == "bpv-addon-ip-workspace-202611")
                .order_by(prices.c.id)
            )
        ]
        entitlement_rows = [
            tuple(row)
            for row in connection.execute(
                select(entitlements)
                .where(entitlements.c.plan_version_id == "bpv-addon-ip-workspace-202611")
                .order_by(entitlements.c.entitlement_key)
            )
        ]
    return plan_rows, price_rows, entitlement_rows


def _replay_upgrade(engine) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("ip_workspace_addon_20261122", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with context.begin_transaction(), Operations.context(context):
            module.upgrade()


@pytest.mark.parametrize("kind", KINDS)
def test_migration_up_is_exact_and_idempotent_and_down_refuses(
    kind, tmp_path, monkeypatch
) -> None:
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        assert _catalog_rows(engine) == ([], [], [])

        command.upgrade(config, HEAD)
        require_revision(engine, HEAD)
        rows = _catalog_rows(engine)
        assert rows == (
            [
                (
                    "bpv-addon-ip-workspace-202611",
                    ADD_ON,
                    "2026.11.v1",
                    "add_on",
                    "IP workspace",
                    "active",
                    True,
                    False,
                    {"eligible_segments": ["firm", "gc"]},
                )
            ],
            [
                (
                    "bpp-addon-ip-workspace-month-202611",
                    "bpv-addon-ip-workspace-202611",
                    "INR",
                    999900,
                    "month",
                    "exclusive",
                    1800,
                    "2026.11.v1:addon_ip_workspace:month",
                ),
                (
                    "bpp-addon-ip-workspace-year-202611",
                    "bpv-addon-ip-workspace-202611",
                    "INR",
                    9999000,
                    "year",
                    "exclusive",
                    1800,
                    "2026.11.v1:addon_ip_workspace:year",
                ),
            ],
            [("bpv-addon-ip-workspace-202611", key, "boolean", True) for key in IP_KEYS],
        )

        # A replay on a database that already has the add-on is a no-op.
        _replay_upgrade(engine)
        assert _catalog_rows(engine) == rows

        with pytest.raises(RuntimeError) as refused:
            command.downgrade(config, PARENT)
        assert str(refused.value) == REFUSAL
        assert _catalog_rows(engine) == rows
        require_revision(engine, HEAD)
