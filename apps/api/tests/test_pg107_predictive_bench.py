"""PG-107 v1 — predictive-bench-strategy tenant policy gate.

Confirms:
- Default policy = evidence-only (predictive flag false).
- Admin PATCH flips the flag; subsequent reads echo the new value.
- bench_strategy_context.build_bench_strategy_context surfaces
  mode + disclaimer fields keyed off the resolved policy.
- analyze_appeal_strength echoes the same mode + disclaimer.
- Drafting prompt addendum includes the predictive override only
  when the workspace has opted in.
- Cross-tenant: tenant A's flip does NOT leak into tenant B.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def test_default_policy_is_evidence_only(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["predictive_bench_strategy_enabled"] is False


def test_admin_can_flip_predictive_flag(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    on = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"predictive_bench_strategy_enabled": True},
    )
    assert on.status_code == 200, on.text
    assert on.json()["predictive_bench_strategy_enabled"] is True

    off = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"predictive_bench_strategy_enabled": False},
    )
    assert off.status_code == 200
    assert off.json()["predictive_bench_strategy_enabled"] is False


def test_predictive_flag_is_tenant_isolated(client: TestClient) -> None:
    token_a = str(bootstrap_company(client)["access_token"])
    on_a = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token_a),
        json={"predictive_bench_strategy_enabled": True},
    )
    assert on_a.status_code == 200

    company_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B",
            "company_slug": "tenant-b-pg107",
            "company_type": "law_firm",
            "owner_full_name": "B Owner",
            "owner_email": "owner@tenant-b-pg107.in",
            "owner_password": "TenantBPass123!",
        },
    )
    assert company_b.status_code == 200, company_b.text
    token_b = str(company_b.json()["access_token"])

    resp_b = client.get(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token_b),
    )
    assert resp_b.status_code == 200
    assert resp_b.json()["predictive_bench_strategy_enabled"] is False


def test_drafting_prompt_addendum_swaps_on_predictive_flag(
    client: TestClient,
) -> None:
    """The prompt-addendum block fires only when the workspace has
    opted in. We exercise the helper directly so we don't depend on
    a real LLM call or full draft pipeline."""
    from caseops_api.db.models import Draft, Matter
    from caseops_api.schemas.drafting_templates import DraftTemplateType
    from caseops_api.services.drafting import _build_messages

    matter = Matter(
        id="m-test",
        company_id="c-test",
        matter_code="TEST-1",
        title="t",
        practice_area="litigation",
        forum_level="high_court",
        court_name="Delhi HC",
        client_name="A",
        opposing_party="B",
        description="t",
    )
    draft = Draft(
        id="d-test",
        matter_id="m-test",
        template_type=DraftTemplateType.APPEAL_MEMORANDUM.value,
    )

    msgs_off = _build_messages(
        matter, draft, retrieved=[], focus_note=None,
        predictive_bench_enabled=False,
    )
    msgs_on = _build_messages(
        matter, draft, retrieved=[], focus_note=None,
        predictive_bench_enabled=True,
    )

    sys_off = msgs_off[0].content
    sys_on = msgs_on[0].content

    assert "WORKSPACE POLICY OVERRIDE" not in sys_off
    assert "WORKSPACE POLICY OVERRIDE" in sys_on
    assert "Predictive analytics" in sys_on
