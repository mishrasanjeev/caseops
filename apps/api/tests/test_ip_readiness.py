from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
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


def _configured_workspace(client: TestClient) -> tuple[dict[str, str], str]:
    """A company whose IP workspace is configured and enabled, so only the
    capability, entitlement and rollout gates remain in play."""

    from tests.test_ip_workspace_configuration import _configuration

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    configured = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json=_configuration(str(bootstrap["membership"]["id"])),
    )
    assert configured.status_code == 200, configured.text
    enabled = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={"expected_config_version": 1, "enabled_automations": []},
    )
    assert enabled.status_code == 200, enabled.text
    return headers, str(bootstrap["company"]["id"])


@pytest.mark.parametrize(
    ("entitled", "rollout", "reason", "blocked_reasons"),
    [
        (False, False, "missing_entitlement", ["missing_entitlement", "rollout_disabled"]),
        (True, False, "rollout_disabled", ["rollout_disabled"]),
        (True, True, "available", []),
    ],
    ids=["unentitled-rollout-off", "entitled-rollout-off", "entitled-rollout-on"],
)
def test_readiness_reports_every_failing_gate_not_only_the_first(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    entitled: bool,
    rollout: bool,
    reason: str,
    blocked_reasons: list[str],
) -> None:
    """A plan refusal must not hide a platform rollout pause (and vice versa)."""

    from tests.ip_rule_governance_support import grant_ip_rule_governance_entitlement

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true" if rollout else "false")
    monkeypatch.delenv("CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT", raising=False)
    get_settings.cache_clear()
    headers, company_id = _configured_workspace(client)
    if entitled:
        grant_ip_rule_governance_entitlement(company_id)

    response = client.get("/api/ip/readiness", headers=headers)
    assert response.status_code == 200, response.text
    features = {row["feature_id"]: row for row in response.json()["features"]}
    governance = features["rule_governance"]
    assert governance["reason"] == reason
    assert governance["blocked_reasons"] == blocked_reasons
    assert governance["available"] is (blocked_reasons == [])
    assert governance["entitled"] is entitled
    assert governance["rollout_enabled"] is rollout

    # The compatibility contract holds for every feature in the response.
    for row in features.values():
        if row["available"]:
            assert row["reason"] == "available" and row["blocked_reasons"] == []
        else:
            assert row["blocked_reasons"], row["feature_id"]
            assert row["reason"] == row["blocked_reasons"][0], row["feature_id"]
            assert len(row["blocked_reasons"]) == len(set(row["blocked_reasons"]))


def test_readiness_blocked_reasons_include_workspace_configuration_gates(
    client: TestClient,
) -> None:
    """An unconfigured workspace is a failing gate even when others fail too."""

    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    response = client.get("/api/ip/readiness", headers=headers)
    assert response.status_code == 200, response.text
    for row in response.json()["features"]:
        assert row["available"] is False
        assert row["blocked_reasons"][-1] == "workspace_not_configured", row
        assert "missing_entitlement" in row["blocked_reasons"]
        assert "rollout_disabled" in row["blocked_reasons"]
        assert row["reason"] == row["blocked_reasons"][0]
