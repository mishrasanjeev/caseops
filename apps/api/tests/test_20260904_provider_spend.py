from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    BillingUsageEvent,
    Company,
    CompanyMembership,
    CompanyProviderSpendPolicy,
    ProviderSpendReservation,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.provider_spend import (
    DEFAULT_MONTHLY_LIMIT_MINOR,
    release_provider_spend,
    reserve_provider_spend,
    resolve_provider_spend_policy,
)
from caseops_api.services.saas_billing import record_usage
from tests.test_auth_company import auth_headers, bootstrap_company


def test_default_budget_is_machine_resolved_without_mutable_name_bypass(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    with get_session_factory()() as session:
        company = session.get(Company, str(boot["company"]["id"]))
        assert company is not None
        default = resolve_provider_spend_policy(
            session,
            company=company,
            provider_key="ecourtsindia",
        )
        assert default.monthly_limit_minor == DEFAULT_MONTHLY_LIMIT_MINOR
        assert default.unlimited is False

        company.name = "GBA Law Office"
        still_default = resolve_provider_spend_policy(
            session,
            company=company,
            provider_key="indian-kanoon",
        )
        assert still_default.unlimited is False
        assert still_default.monthly_limit_minor == DEFAULT_MONTHLY_LIMIT_MINOR


def test_atomic_reservations_prevent_parallel_requests_exceeding_the_cap(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    with get_session_factory()() as session:
        session.add(
            CompanyProviderSpendPolicy(
                company_id=company_id,
                provider_key="ecourtsindia",
                monthly_limit_minor=20,
                currency="INR",
                is_active=True,
                policy_source="test_explicit_policy",
            )
        )
        session.commit()

    first = reserve_provider_spend(
        company_id=company_id,
        actor_membership_id=membership_id,
        provider_key="ecourtsindia",
        operation_key="first",
        amount_minor=15,
    )
    assert first is not None
    with pytest.raises(HTTPException) as blocked:
        reserve_provider_spend(
            company_id=company_id,
            actor_membership_id=membership_id,
            provider_key="ecourtsindia",
            operation_key="parallel",
            amount_minor=10,
        )
    assert blocked.value.status_code == 429
    assert blocked.value.detail["code"] == "provider_budget_exhausted"

    release_provider_spend(reservation_id=first)
    second = reserve_provider_spend(
        company_id=company_id,
        actor_membership_id=membership_id,
        provider_key="ecourtsindia",
        operation_key="after_release",
        amount_minor=10,
    )
    assert second is not None
    release_provider_spend(reservation_id=second)
    with get_session_factory()() as session:
        statuses = list(
            session.scalars(
                select(ProviderSpendReservation.status).order_by(
                    ProviderSpendReservation.created_at
                )
            )
        )
        assert statuses == ["released", "released"]


def test_workspace_usage_report_publishes_spend_and_remaining_by_provider(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        record_usage(
            session,
            company_id=company_id,
            subscription_id=None,
            usage_type="case_tracking_search",
            feature_key="case_tracking_search",
            provider_key="ecourtsindia",
            quantity=1,
            unit="provider_call",
            actor_membership_id=membership_id,
            estimated_cost_minor=15,
            display_label="eCourts case search",
        )
        session.commit()

    response = client.get(
        "/api/billing/usage",
        headers=auth_headers(str(boot["access_token"])),
    )
    assert response.status_code == 200, response.text
    by_provider = {row["provider_key"]: row for row in response.json()["by_provider"]}
    assert set(by_provider) == {"ecourtsindia", "indian-kanoon"}
    assert by_provider["ecourtsindia"] == {
        "provider_key": "ecourtsindia",
        "label": "eCourtsIndia",
        "spent_minor": 15,
        "monthly_limit_minor": 100_000,
        "remaining_minor": 99_985,
        "unlimited": False,
        "currency": "INR",
        "policy_source": "caseops_default_provider_budget_2026_09_04",
    }
    assert by_provider["indian-kanoon"]["spent_minor"] == 0
    assert datetime.fromisoformat(response.json()["period_start"]).tzinfo is not None
    with get_session_factory()() as session:
        event = session.scalar(select(BillingUsageEvent))
        assert event is not None
        assert event.provider_key == "ecourtsindia"
