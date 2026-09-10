from __future__ import annotations

import pytest

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_HEADER,
    NO_PAID_PROVIDERS_VALUE,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import Company
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


@pytest.mark.parametrize(
    ("slug", "base_url", "expected_reason"),
    [
        ("test-legal", "https://webapi.ecourtsindia.com", "configured_test_tenant"),
        ("ram-e2e-unique", "https://webapi.ecourtsindia.com", "synthetic_test_tenant"),
        ("gba-law-office", "https://webapi.ecourtsindia.com", None),
        ("pinelabs", "https://webapi.ecourtsindia.com", None),
        ("test-legal", "http://case-provider:8080", None),
    ],
)
def test_scheduled_eligibility_is_tenant_scoped_and_independent_of_request_marker(
    client, monkeypatch, slug, base_url, expected_reason
):
    boot = bootstrap_company(client)
    with get_session_factory()() as session:
        company = session.get(Company, boot["company"]["id"])
        company.slug = slug
        session.commit()
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_PROVIDER", "ecourtsindia")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "deterministic-unused-token")
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_BASE_URL", base_url)
    monkeypatch.setenv("CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS", "test-legal")
    get_settings.cache_clear()
    try:
        for marked in (False, True):
            headers = auth_headers(str(boot["access_token"]))
            if marked:
                headers[NO_PAID_PROVIDERS_HEADER] = NO_PAID_PROVIDERS_VALUE
            response = client.get("/api/case-tracking/status", headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["configured"] is True
            assert body["scheduled_sync_disabled_reason"] == expected_reason
            assert body["scheduled_sync_eligible"] is (expected_reason is None)
            assert body["scheduled_sync_local_time"] == "18:00"
            assert body["scheduled_sync_window_end_local_time"] == "20:00"
            assert body["workspace_monthly_reserved_minor"] == 0
            assert body["scheduled_sync_timezone"] == "Asia/Kolkata"
            assert body["performs_external_probe"] is False
            assert body["provider_prepaid_balance_checked"] is False
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("enabled", [False, True])
def test_missing_configuration_never_claims_scheduled_eligibility(client, monkeypatch, enabled):
    boot = bootstrap_company(client)
    monkeypatch.setenv("CASEOPS_CASE_TRACKING_ENABLED", str(enabled).lower())
    monkeypatch.setenv("CASEOPS_ECOURTSINDIA_API_TOKEN", "")
    get_settings.cache_clear()
    try:
        response = client.get(
            "/api/case-tracking/status", headers=auth_headers(str(boot["access_token"]))
        )
        assert response.status_code == 200, response.text
        assert response.json()["scheduled_sync_eligible"] is False
        assert response.json()["scheduled_sync_disabled_reason"] == (
            "provider_not_configured" if enabled else "tracking_disabled"
        )
    finally:
        get_settings.cache_clear()
