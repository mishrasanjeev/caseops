"""PG-005 Sprint 11 (2026-05-01) — template governance tests.

Admin can hide drafting templates per tenant via PATCH
/api/admin/tenant-ai-policy. The /api/drafting/templates endpoint
filters its response on the disabled list.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def test_default_policy_lists_all_20_templates(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get("/api/drafting/templates", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["templates"]) == 20


def test_admin_can_disable_a_template_and_it_drops_from_the_list(
    client: TestClient,
) -> None:
    """PATCH the policy with disabled_template_types=['vakalatnama'].
    The /api/drafting/templates response should drop from 20 → 19,
    with vakalatnama specifically absent."""
    token = str(bootstrap_company(client)["access_token"])

    patch = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"disabled_template_types": ["vakalatnama"]},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert "vakalatnama" in body["disabled_template_types"]

    resp = client.get("/api/drafting/templates", headers=auth_headers(token))
    assert resp.status_code == 200
    types = {t["template_type"] for t in resp.json()["templates"]}
    assert "vakalatnama" not in types
    assert len(types) == 19


def test_disabled_template_types_validates_against_canonical_set(
    client: TestClient,
) -> None:
    """Bogus type names are silently dropped — no SQL injection / no
    accidental disabling of nothing — only known DraftTemplateType
    values land in the column."""
    token = str(bootstrap_company(client)["access_token"])

    patch = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={
            "disabled_template_types": [
                "vakalatnama",  # valid
                "not_a_real_template",  # bogus, must be dropped
                "writ_petition",  # valid
            ],
        },
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert sorted(body["disabled_template_types"]) == sorted(
        ["vakalatnama", "writ_petition"]
    )


def test_disabling_then_re_enabling_template_round_trips(
    client: TestClient,
) -> None:
    """Empty list re-enables all templates."""
    token = str(bootstrap_company(client)["access_token"])

    # Disable.
    client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"disabled_template_types": ["bail", "anticipatory_bail"]},
    )
    resp1 = client.get("/api/drafting/templates", headers=auth_headers(token))
    assert len(resp1.json()["templates"]) == 18

    # Re-enable.
    client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"disabled_template_types": []},
    )
    resp2 = client.get("/api/drafting/templates", headers=auth_headers(token))
    assert len(resp2.json()["templates"]) == 20


def test_predictive_flag_unaffected_by_disabled_templates_patch(
    client: TestClient,
) -> None:
    """Sending only disabled_template_types must not flip the
    predictive_bench flag, and vice versa. Tests the partial-update
    semantics of the PATCH route."""
    token = str(bootstrap_company(client)["access_token"])

    # Set both initially.
    client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={
            "predictive_bench_strategy_enabled": True,
            "disabled_template_types": ["caveat_petition"],
        },
    )

    # PATCH only disabled_template_types — predictive flag must stay True.
    patch = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"disabled_template_types": ["caveat_petition", "vakalatnama"]},
    )
    body = patch.json()
    assert body["predictive_bench_strategy_enabled"] is True
    assert sorted(body["disabled_template_types"]) == sorted(
        ["caveat_petition", "vakalatnama"]
    )


def _bootstrap(client: TestClient, slug: str) -> str:
    """Create a fresh tenant with the given slug + return its access
    token. Inline because tests.test_auth_company.bootstrap_company
    hard-codes the aster-legal slug — we need two distinct tenants
    for the isolation test."""
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"Tenant {slug.upper()} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"Owner {slug}",
            "owner_email": f"owner-{slug}@example.in",
            "owner_password": "TenantIsoPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


def test_tenant_isolation_disabled_template_types(client: TestClient) -> None:
    """Tenant A disabling a template must not affect tenant B's view."""
    token_a = _bootstrap(client, "firm-iso-a")
    token_b = _bootstrap(client, "firm-iso-b")

    client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token_a),
        json={"disabled_template_types": ["bail", "writ_petition"]},
    )

    a_resp = client.get("/api/drafting/templates", headers=auth_headers(token_a))
    b_resp = client.get("/api/drafting/templates", headers=auth_headers(token_b))
    a_types = {t["template_type"] for t in a_resp.json()["templates"]}
    b_types = {t["template_type"] for t in b_resp.json()["templates"]}
    assert "bail" not in a_types and "writ_petition" not in a_types
    assert "bail" in b_types and "writ_petition" in b_types
    assert len(a_types) == 18
    assert len(b_types) == 20
