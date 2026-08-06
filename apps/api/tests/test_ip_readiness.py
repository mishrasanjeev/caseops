from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import BillingSubscription
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def test_ip_readiness_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/ip/readiness")
    assert response.status_code == 401


def test_ip_readiness_is_tenant_scoped_observable_and_side_effect_free(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])

    with get_session_factory()() as session:
        before = int(
            session.scalar(
                select(func.count(BillingSubscription.id)).where(
                    BillingSubscription.company_id == company_id
                )
            )
            or 0
        )

    response = client.get("/api/ip/readiness", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Asia/Calcutta"
    assert body["workspace_available"] is False
    assert body["manual_docketing_available"] is False
    assert len(body["features"]) == 11
    assert {row["feature_id"] for row in body["features"]} == {
        "workspace_core",
        "manual_docketing",
        "registry_sync",
        "deadline_automation",
        "notification_automation",
        "filing_prepare",
        "filing_confirm",
        "watch_operations",
        "cost_operations",
        "rule_governance",
        "taxonomy_admin",
    }
    for row in body["features"]:
        assert row["available"] is False
        assert row["reason"] in {"missing_entitlement", "rollout_disabled"}
        assert row["owner"]
        assert row["entitlement_key"].startswith("ip_")
        assert row["rollout_flag"].startswith("ip_")

    with get_session_factory()() as session:
        after = int(
            session.scalar(
                select(func.count(BillingSubscription.id)).where(
                    BillingSubscription.company_id == company_id
                )
            )
            or 0
        )
    assert after == before
