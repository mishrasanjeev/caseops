"""The internal sales_demo plan: IP on, paid providers off, never sold.

Decision record: sales demo workspace plan accepted by the owner on 2026-11-21.
A platform admin assigns the plan to the synthetic-data ``caseops-sales-demo``
workspace through the existing manual subscription control.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import Settings, get_settings
from caseops_api.db.models import BillingPlanVersion, BillingSubscription, Company
from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_capability_catalog import IP_FEATURES, evaluate_ip_feature
from caseops_api.services.provider_spend import (
    reserve_provider_spend,
    resolve_provider_spend_policy,
)
from caseops_api.services.saas_billing import current_entitlements_for_company
from tests.test_auth_company import auth_headers, bootstrap_company

GIB = 1024**3
IP_KEYS = sorted({feature.entitlement_key for feature in IP_FEATURES})
WORKING_LIMITS = {
    "users_internal_limit": 15,
    "users_viewer_limit": 10,
    "matters_active_limit": 1500,
    "tracked_cases_limit": 400,
    "ai_credits_monthly": 1500,
    "storage_bytes_limit": 150 * GIB,
    "manual_case_refreshes_daily": 50,
    "provider_spend_monthly_minor": 0,
}


def _plan(session) -> BillingPlanVersion:
    plan = session.scalar(
        select(BillingPlanVersion).where(
            BillingPlanVersion.plan_code == "sales_demo",
            BillingPlanVersion.version == "2026.11.v1",
        )
    )
    assert plan is not None
    return plan


def test_sales_demo_plan_is_internal_hidden_free_and_exact(client: TestClient) -> None:
    with get_session_factory()() as session:
        plan = _plan(session)
        assert plan.status == "active"
        assert plan.segment == "internal"
        assert plan.publicly_visible is False
        assert plan.trial_eligible is False
        assert [(p.amount_minor, p.interval) for p in plan.prices] == [(0, "custom")]
        entitlements = {row.entitlement_key: row.value_json for row in plan.entitlements}
    assert entitlements == {**WORKING_LIMITS, **dict.fromkeys(IP_KEYS, True)}


def test_sales_demo_plan_is_not_in_the_public_catalog(client: TestClient) -> None:
    response = client.get("/api/billing/plans")
    assert response.status_code == 200, response.text
    codes = {plan["plan_code"] for plan in response.json()["plans"]}
    assert "sales_demo" not in codes
    assert "firm_growth" in codes


def test_platform_admin_assignment_enables_ip_and_blocks_paid_providers(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    founder_token = str(bootstrap_company(client)["access_token"])

    trial = client.post(
        "/api/billing/trials",
        json={
            "company_name": "Mehra & Rao Associates (demo)",
            "company_slug": "caseops-sales-demo",
            "company_type": "law_firm",
            "owner_full_name": "Demo Owner",
            "owner_email": "owner@sales-demo.example.com",
            "owner_password": "DemoPass123!",
            "source": "sign_in",
        },
    )
    assert trial.status_code == 200, trial.text
    company_id = str(trial.json()["auth"]["company"]["id"])

    assigned = client.post(
        f"/api/platform-admin/companies/{company_id}/subscription",
        headers=auth_headers(founder_token),
        json={
            "plan_code": "sales_demo",
            "billing_interval": "month",
            "status": "manual_active",
            "reason": "Sales demo workspace, synthetic data only",
        },
    )
    assert assigned.status_code == 200, assigned.text

    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription).where(BillingSubscription.company_id == company_id)
        )
        assert subscription is not None
        assert subscription.status == "manual_active"
        assert subscription.externally_billable is False
        assert subscription.plan_version_id == _plan(session).id

        entitlements = current_entitlements_for_company(session, company_id)
        settings = Settings()
        for feature in IP_FEATURES:
            decision = evaluate_ip_feature(
                feature.feature_id,
                granted_capabilities=set(feature.required_capabilities),
                entitlements=entitlements,
                settings=settings,
            )
            assert decision.entitled is True, feature.feature_id
            assert "missing_entitlement" not in decision.blocked_reasons

        company = session.get(Company, company_id)
        assert company is not None
        for provider_key in ("indian-kanoon", "ecourtsindia"):
            policy = resolve_provider_spend_policy(
                session, company=company, provider_key=provider_key
            )
            assert policy.monthly_limit_minor == 0
            assert policy.source == "billing_plan_provider_spend_monthly_minor"

    # The smallest paid call is refused before any external request.
    with pytest.raises(HTTPException) as refused:
        reserve_provider_spend(
            company_id=company_id,
            actor_membership_id=None,
            provider_key="ecourtsindia",
            operation_key="sales-demo-refresh",
            amount_minor=1,
        )
    assert refused.value.status_code == 429
    assert refused.value.detail["code"] == "provider_budget_exhausted"
