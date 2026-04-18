from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _matter_id(client: TestClient, token: str, code: str) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Audit matter {code}",
            "matter_code": code,
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _all_events(company_id: str) -> list[AuditEvent]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
        )


def test_matter_create_emits_audit_row(client: TestClient) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter_id = _matter_id(client, token, "AUD-001")

    events = _all_events(company_id)
    created = [
        e for e in events if e.action == "matter.created" and e.matter_id == matter_id
    ]
    assert len(created) == 1
    event = created[0]
    assert event.target_type == "matter"
    assert event.target_id == matter_id
    assert event.actor_type == "human"
    meta = json.loads(event.metadata_json)
    assert meta["matter_code"] == "AUD-001"
    assert meta["status"] == "active"


def test_draft_state_machine_emits_one_row_per_transition(client: TestClient) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter_id = _matter_id(client, token, "AUD-002")

    # Create draft, generate, submit, request_changes.
    draft = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Audited reply", "draft_type": "brief"},
    ).json()
    draft_id = draft["id"]
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft_id}/generate",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft_id}/submit",
        headers=auth_headers(token),
        json={},
    )
    client.post(
        f"/api/matters/{matter_id}/drafts/{draft_id}/request-changes",
        headers=auth_headers(token),
        json={"notes": "Tighten."},
    )

    events = _all_events(company_id)
    actions = [e.action for e in events if e.target_type in {"draft", "matter"}]
    # matter.created first, then draft.created, version_generated, submit,
    # request_changes. Ordering matters — this also asserts the audit
    # feed is linear.
    assert actions == [
        "matter.created",
        "draft.created",
        "draft.version_generated",
        "draft.submit",
        "draft.request_changes",
    ]


def test_audit_export_is_admin_only(client: TestClient) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    # Owner should be allowed.
    allowed = client.get(
        "/api/admin/audit/export",
        headers=auth_headers(token),
    )
    assert allowed.status_code == 200, allowed.text
    # Without a token we hit the auth layer first (401).
    anon = client.get("/api/admin/audit/export")
    assert anon.status_code == 401


def test_audit_export_streams_jsonl_and_records_itself(client: TestClient) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter_id = _matter_id(client, token, "AUD-003")

    resp = client.get(
        "/api/admin/audit/export",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert ".jsonl" in resp.headers["content-disposition"]
    lines = [line for line in resp.text.strip().split("\n") if line]
    assert len(lines) >= 1
    # Every line round-trips as JSON.
    decoded = [json.loads(line) for line in lines]
    # Our matter creation event is in the export.
    assert any(
        row["action"] == "matter.created" and row["target_id"] == matter_id
        for row in decoded
    )
    # Exports are themselves audited — check the DB directly, not the
    # response body (the response was built before the audit.exported
    # row landed).
    events = _all_events(company_id)
    exports = [e for e in events if e.action == "audit.exported"]
    assert len(exports) == 1
    assert json.loads(exports[0].metadata_json)["row_count"] >= 1


def test_audit_trail_is_tenant_scoped(client: TestClient) -> None:
    boot_a = bootstrap_company(client)
    token_a = str(boot_a["access_token"])
    company_a = boot_a["company"]["id"]
    _matter_id(client, token_a, "AUD-T-A")

    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B",
            "company_slug": "audit-tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "owner@audit-b.in",
            "owner_password": "BetaPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    token_b = str(resp.json()["access_token"])
    company_b = resp.json()["company"]["id"]
    assert company_a != company_b

    # Tenant B's export must not see tenant A's rows.
    export_b = client.get(
        "/api/admin/audit/export",
        headers=auth_headers(token_b),
    )
    assert export_b.status_code == 200
    for line in [line for line in export_b.text.strip().split("\n") if line]:
        row = json.loads(line)
        assert row["company_id"] == company_b
