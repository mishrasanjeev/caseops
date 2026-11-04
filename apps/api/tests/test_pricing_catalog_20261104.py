"""Catalog 2026.11.v1: published prices match enforced entitlements.

Decision record: docs/PRICING_COMPETITIVE_REVIEW_2026-11-04.md.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    BillingPlanVersion,
    BillingSubscription,
    BillingSubscriptionItem,
    BillingSubscriptionStatus,
    Company,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import provider_costs, saas_billing
from caseops_api.services.provider_spend import (
    DEFAULT_MONTHLY_LIMIT_MINOR,
    resolve_provider_spend_policy,
)
from caseops_api.services.saas_billing import (
    TRIAL_ENDED_DETAIL,
    _included_credit_window,
    assert_ai_credits_available,
    effective_storage_quota,
    resolve_entitlements,
)
from tests.test_auth_company import auth_headers, bootstrap_company

GIB = 1024**3
MIB = 1024**2
UNENFORCED_KEYS = (
    "case_refresh_cadence",
    "api_access_enabled",
    "audit_export_enabled",
    "sso_enabled",
)

# plan_code: (monthly paise, annual paise, users, viewers, matters, tracked,
#             credits, storage bytes, provider budget paise)
EXPECTED_PLANS = {
    "solo_core": (99900, 999000, 2, 0, 50, 15, 100, 5 * GIB, 60_000),
    "solo_pro": (199900, 1999000, 4, 0, 250, 40, 250, 20 * GIB, 100_000),
    "solo_elite": (399900, 3999000, 6, 0, 1000, 120, 600, 50 * GIB, 200_000),
    "firm_starter": (599900, 5999000, 5, 0, 300, 150, 500, 25 * GIB, 250_000),
    "firm_growth": (1799900, 17999000, 15, 10, 1500, 400, 1500, 150 * GIB, 500_000),
    "firm_pro": (4999900, 49999000, 50, 50, 5000, 1000, 3500, 500 * GIB, 1_100_000),
    "gc_monitoring": (None, 15000000, 3, 25, 500, 750, 600, 50 * GIB, 850_000),
    "gc_starter": (None, 30000000, 5, 25, 1000, 1500, 2500, 250 * GIB, 1_600_000),
    "gc_professional": (None, 80000000, 15, 100, 10000, 4000, 8000, 1024 * GIB, 4_100_000),
}


def _trial_payload(slug: str, email: str) -> dict[str, object]:
    return {
        "company_name": f"{slug.title()} Chambers",
        "company_slug": slug,
        "company_type": "solo",
        "owner_full_name": "Trial Advocate",
        "owner_email": email,
        "owner_password": "TrialPass123!",
        "source": "sign_in",
    }


def _start_trial(client: TestClient, slug: str, email: str) -> dict[str, object]:
    response = client.post("/api/billing/trials", json=_trial_payload(slug, email))
    assert response.status_code == 200, response.text
    return response.json()


def _end_trial(company_id: str) -> None:
    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription).where(BillingSubscription.company_id == company_id)
        )
        assert subscription is not None
        assert subscription.status == BillingSubscriptionStatus.TRIALING
        subscription.trial_end = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()


def _matter_payload(code: str) -> dict[str, object]:
    return {
        "title": f"Matter {code}",
        "matter_code": code,
        "practice_area": "Commercial",
        "forum_level": "high_court",
        "status": "intake",
        "claim_currency": "INR",
    }


def test_public_catalog_is_2026_11_v1_with_approved_prices_and_limits(client: TestClient) -> None:
    response = client.get("/api/billing/plans")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["version"] == "2026.11.v1"
    plans = {plan["plan_code"]: plan for plan in payload["plans"]}
    add_ons = {plan["plan_code"]: plan for plan in payload["add_ons"]}

    for code, expected in EXPECTED_PLANS.items():
        monthly, annual, users, viewers, matters, tracked, credits, storage, budget = expected
        plan = plans[code]
        assert plan["version"] == "2026.11.v1"
        prices = {price["interval"]: price["amount_minor"] for price in plan["prices"]}
        assert prices.get("month") == monthly, code
        assert prices["year"] == annual, code
        if monthly is not None:
            # Two months free on every monthly plan.
            assert annual == monthly * 10, code
        entitlements = plan["entitlements"]
        assert entitlements["users_internal_limit"] == users
        assert entitlements["users_viewer_limit"] == viewers
        assert entitlements["matters_active_limit"] == matters
        assert entitlements["tracked_cases_limit"] == tracked
        assert entitlements["ai_credits_monthly"] == credits
        assert entitlements["storage_bytes_limit"] == storage
        assert entitlements["provider_spend_monthly_minor"] == budget
        for key in UNENFORCED_KEYS:
            assert key not in entitlements, (code, key)

    assert "addon_api_access" not in add_ons
    case_pack_prices = {
        code: add_ons[code]["prices"][0]["amount_minor"]
        for code in ("addon_cases_500", "addon_cases_1000")
    }
    assert case_pack_prices == {"addon_cases_500": 499900, "addon_cases_1000": 899900}
    assert add_ons["addon_cases_500"]["entitlements"]["provider_spend_monthly_minor"] == 500_000


def test_catalog_version_constants_agree() -> None:
    migration_path = next(
        Path(__file__).resolve().parents[1].glob(
            "alembic/versions/20261104_0001_pricing_catalog_2026_11_v1.py"
        )
    )
    spec = importlib.util.spec_from_file_location("catalog_20261104", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert saas_billing.CATALOG_VERSION == provider_costs.CATALOG_VERSION == module.CATALOG_VERSION


def test_annual_period_grants_included_credits_every_month() -> None:
    start = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
    subscription = BillingSubscription(
        id="sub-annual",
        current_period_start=start,
        current_period_end=start + timedelta(days=365),
        billing_interval="year",
    )
    january = _included_credit_window(subscription, now=start + timedelta(days=3))
    february = _included_credit_window(subscription, now=datetime(2026, 3, 1, tzinfo=UTC))
    march = _included_credit_window(subscription, now=datetime(2026, 3, 31, 10, tzinfo=UTC))

    assert january == (f"sub-annual:{start.isoformat()}", datetime(2026, 2, 28, 9, 0, tzinfo=UTC))
    assert february[0] == "sub-annual:2026-02-28T09:00:00+00:00"
    assert february[1] == datetime(2026, 3, 31, 9, 0, tzinfo=UTC)
    assert march[0] == "sub-annual:2026-03-31T09:00:00+00:00"
    assert len({january[0], february[0], march[0]}) == 3

    # The last window never runs past the billing period.
    last = _included_credit_window(subscription, now=start + timedelta(days=400))
    assert last[1] == start + timedelta(days=365)

    monthly = BillingSubscription(
        id="sub-monthly",
        current_period_start=start,
        current_period_end=start + timedelta(days=31),
        billing_interval="month",
    )
    # Monthly periods keep the pre-2026.11 idempotency key.
    assert _included_credit_window(monthly, now=start + timedelta(days=20)) == (
        f"sub-monthly:{start.isoformat()}",
        start + timedelta(days=31),
    )


def test_trial_signup_issues_session_and_trial_limits(client: TestClient) -> None:
    response = client.post(
        "/api/billing/trials", json=_trial_payload("trial-cookie", "advocate@trialcookie.in")
    )
    assert response.status_code == 200, response.text
    assert "set-cookie" in response.headers
    body = response.json()
    token = str(body["auth"]["access_token"])

    current = client.get("/api/billing/current", headers=auth_headers(token))
    assert current.status_code == 200, current.text
    state = current.json()
    assert state["subscription"]["plan_code"] == "trial"
    assert state["subscription"]["status"] == "trialing"
    assert state["entitlements"]["tracked_cases_limit"] == 10
    assert state["entitlements"]["ai_credits_monthly"] == 50
    trial_end = datetime.fromisoformat(str(body["trial_end"]))
    assert timedelta(days=13, hours=23) < trial_end - datetime.now(UTC) <= timedelta(days=14)


def test_ended_trial_is_read_only_for_new_work(client: TestClient) -> None:
    body = _start_trial(client, "trial-ended", "advocate@trialended.in")
    token = str(body["auth"]["access_token"])
    company_id = str(body["auth"]["company"]["id"])
    headers = auth_headers(token)

    before = client.post("/api/matters/", headers=headers, json=_matter_payload("TR-1"))
    assert before.status_code == 200, before.text

    _end_trial(company_id)

    blocked = client.post("/api/matters/", headers=headers, json=_matter_payload("TR-2"))
    assert blocked.status_code == 402, blocked.text
    assert blocked.json()["detail"] == TRIAL_ENDED_DETAIL

    listing = client.get("/api/matters/", headers=headers)
    assert listing.status_code == 200, listing.text
    assert "TR-1" in listing.text

    with get_session_factory()() as session:
        with pytest.raises(HTTPException) as ai_block:
            assert_ai_credits_available(session, company_id=company_id, estimated_credits=1)
        assert ai_block.value.status_code == 402
        company = session.get(Company, company_id)
        assert company is not None
        assert effective_storage_quota(session, company=company) == 0
        policy = resolve_provider_spend_policy(
            session, company=company, provider_key="ecourtsindia"
        )
        assert policy.monthly_limit_minor == 0


def test_provider_budget_follows_the_plan(client: TestClient) -> None:
    trial = _start_trial(client, "trial-budget", "advocate@trialbudget.in")
    grandfathered = bootstrap_company(client)
    client.get(
        "/api/billing/current",
        headers=auth_headers(str(grandfathered["access_token"])),
    )

    with get_session_factory()() as session:
        trial_company = session.get(Company, str(trial["auth"]["company"]["id"]))
        legacy_company = session.get(Company, str(grandfathered["company"]["id"]))
        assert trial_company is not None and legacy_company is not None

        trial_policy = resolve_provider_spend_policy(
            session, company=trial_company, provider_key="indian-kanoon"
        )
        assert trial_policy.monthly_limit_minor == 30_000
        assert trial_policy.source == "billing_plan_provider_spend_monthly_minor"

        legacy_policy = resolve_provider_spend_policy(
            session, company=legacy_company, provider_key="indian-kanoon"
        )
        assert legacy_policy.monthly_limit_minor == DEFAULT_MONTHLY_LIMIT_MINOR
        assert legacy_policy.source == "caseops_default_shared_account_budget_2026_09_04"


def test_add_ons_resolve_against_the_subscription_catalog_version(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    client.get("/api/billing/current", headers=auth_headers(str(bootstrap["access_token"])))

    with get_session_factory()() as session:
        old_plan = session.scalar(
            select(BillingPlanVersion).where(
                BillingPlanVersion.plan_code == "solo_pro",
                BillingPlanVersion.version == "2026.05.v1",
            )
        )
        assert old_plan is not None
        subscription = session.scalar(
            select(BillingSubscription).where(BillingSubscription.company_id == company_id)
        )
        assert subscription is not None
        subscription.plan_version_id = old_plan.id
        subscription.status = BillingSubscriptionStatus.MANUAL_ACTIVE
        session.add(
            BillingSubscriptionItem(
                subscription_id=subscription.id,
                item_code="addon_cases_500",
                item_type="add_on",
                quantity=1,
                amount_minor=249900,
                currency="INR",
                interval="month",
                status="active",
            )
        )
        session.commit()
        session.refresh(subscription)

        entitlements = resolve_entitlements(session, subscription)
        # 2026.05.v1 solo_pro (200) + 2026.05.v1 case pack (500); the old pack
        # carries no provider budget, so the default budget still applies.
        assert entitlements["tracked_cases_limit"] == 700
        assert "provider_spend_monthly_minor" not in entitlements
