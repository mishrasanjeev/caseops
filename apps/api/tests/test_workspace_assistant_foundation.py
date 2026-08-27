from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AssistantCitation,
    AssistantSession,
    AssistantSessionScope,
    AssistantTurn,
    AuditEvent,
    Client,
    IpDocument,
    IpDocumentTaxonomyEntry,
    Matter,
    MatterAttachment,
    ModelRun,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket


def _enable(client: TestClient, token: str, *, expected_version: int = 1) -> dict:
    response = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={
            "workspace_assistant_enabled": True,
            "assistant_retention_days": 45,
            "allowed_models_assistant": ["caseops-approved-assistant"],
            "expected_version": expected_version,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create(
    client: TestClient,
    token: str,
    *,
    title: str = "Trademark deadline review",
    scopes: list[dict] | None = None,
):
    return client.post(
        "/api/workspace-assistant/sessions",
        headers=auth_headers(token),
        json={"title": title, "scopes": scopes or []},
    )


def _create_matter(client: TestClient, token: str, code: str = "AI-062A") -> dict:
    response = client.post(
        "/api/matters",
        headers=auth_headers(token),
        json={
            "matter_code": code,
            "title": f"Workspace assistant {code}",
            "practice_area": "Intellectual Property",
            "forum_level": "high_court",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_policy_is_fail_closed_and_admin_policy_is_versioned(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])

    disabled = _create(
        client,
        token,
        scopes=[{"scope_type": "tenant", "scope_id": company_id}],
    )
    assert disabled.status_code == 403
    assert disabled.json()["type"] == "workspace_assistant_disabled"

    policy = _enable(client, token)
    assert policy["workspace_assistant_enabled"] is True
    assert policy["allowed_models_assistant"] == ["caseops-approved-assistant"]
    assert policy["assistant_retention_days"] == 45
    assert policy["policy_version"] == 2

    stale = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"workspace_assistant_enabled": False, "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["type"] == "tenant_ai_policy_version_conflict"
    assert stale.json()["current_version"] == 2


def test_session_lifecycle_is_bounded_audited_and_does_not_generate(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    _enable(client, token)

    created = _create(
        client,
        token,
        title="  Trademark   deadline review  ",
        scopes=[{"scope_type": "tenant", "scope_id": company_id}],
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Trademark deadline review"
    assert body["status"] == "active"
    assert body["version"] == 1
    assert body["policy_version"] == 2
    assert body["scope_state"] == "current"
    assert body["scopes"][0]["scope_type"] == "tenant"

    listed = client.get(
        "/api/workspace-assistant/sessions",
        headers=auth_headers(token),
        params={"limit": 1},
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == body["id"]
    assert listed.json()["has_more"] is False

    duplicate = client.put(
        f"/api/workspace-assistant/sessions/{body['id']}/scopes",
        headers=auth_headers(token),
        json={
            "expected_version": 1,
            "scopes": [
                {"scope_type": "tenant", "scope_id": company_id},
                {"scope_type": "tenant", "scope_id": company_id},
            ],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["type"] == "duplicate_assistant_scope"

    archived = client.post(
        f"/api/workspace-assistant/sessions/{body['id']}/archive",
        headers=auth_headers(token),
        json={"expected_version": 1},
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert archived.json()["version"] == 2

    stale = client.post(
        f"/api/workspace-assistant/sessions/{body['id']}/archive",
        headers=auth_headers(token),
        json={"expected_version": 1},
    )
    assert stale.status_code == 409

    with get_session_factory()() as session:
        assert session.scalar(select(func.count(AssistantSession.id))) == 1
        assert session.scalar(select(func.count(AssistantSessionScope.id))) == 1
        assert session.scalar(select(func.count(AssistantTurn.id))) == 0
        assert session.scalar(select(func.count(AssistantCitation.id))) == 0
        assert session.scalar(select(func.count(ModelRun.id))) == 0
        audit = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "workspace_assistant.session_created")
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["scope_types"] == ["tenant"]
        assert metadata["scope_count"] == 1
        assert "Trademark deadline review" not in (audit.metadata_json or "")
        assert company_id not in (audit.metadata_json or "")


def test_all_supported_scope_types_resolve_through_canonical_records(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable(client, token)
    matter = _create_matter(client, token)
    docket = _docket(client, headers, "AI-062A MARK")
    asset = _asset(client, headers, docket["id"], "AI-062A MARK")
    application = _application(client, headers, docket["id"], asset["id"])
    proceeding_response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": application["id"],
            "proceeding_kind": "rectification",
            "side": "respondent",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "stage": "draft",
            "origin_kind": "linked_application",
        },
    )
    assert proceeding_response.status_code == 201, proceeding_response.text
    proceeding = proceeding_response.json()

    with get_session_factory()() as session:
        client_row = Client(company_id=company_id, name="Assistant Client")
        attachment = MatterAttachment(
            matter_id=matter["id"],
            uploaded_by_membership_id=membership_id,
            original_filename="assistant-evidence.pdf",
            storage_key=f"assistant/{matter['id']}/evidence.pdf",
            content_type="application/pdf",
            size_bytes=128,
            sha256_hex="a" * 64,
        )
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key="assistant-evidence",
            label="Assistant evidence",
            updated_by_membership_id=membership_id,
        )
        session.add_all([client_row, attachment, taxonomy])
        session.flush()
        document = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Assistant registry evidence",
            created_by_membership_id=membership_id,
        )
        session.add(document)
        session.commit()
        scope_rows = [
            {"scope_type": "tenant", "scope_id": company_id},
            {"scope_type": "client", "scope_id": client_row.id},
            {"scope_type": "matter", "scope_id": matter["id"]},
            {"scope_type": "ip_docket", "scope_id": docket["id"]},
            {"scope_type": "ip_asset", "scope_id": asset["id"]},
            {"scope_type": "trademark_application", "scope_id": application["id"]},
            {"scope_type": "ip_proceeding", "scope_id": proceeding["id"]},
            {"scope_type": "matter_document", "scope_id": attachment.id},
            {"scope_type": "ip_document", "scope_id": document.id},
        ]

    created = _create(client, token, scopes=scope_rows)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["scope_state"] == "current"
    assert {scope["scope_type"] for scope in body["scopes"]} == {
        "tenant",
        "client",
        "matter",
        "ip_docket",
        "ip_asset",
        "trademark_application",
        "ip_proceeding",
        "matter_document",
        "ip_document",
    }
    assert all(scope["resource_version"] for scope in body["scopes"])


def test_scope_access_is_non_enumerating_creator_private_and_reauthorized(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    _enable(client, owner_token)
    matter = _create_matter(client, owner_token, "AI-062A-ACL")

    member_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Assistant Lawyer",
            "email": "assistant-lawyer@asterlegal.in",
            "password": "AssistantPass123!",
            "role": "member",
        },
    )
    assert member_response.status_code == 200, member_response.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "assistant-lawyer@asterlegal.in",
            "password": "AssistantPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    member_token = str(login.json()["access_token"])

    created = _create(
        client,
        member_token,
        scopes=[{"scope_type": "matter", "scope_id": matter["id"]}],
    )
    assert created.status_code == 201, created.text
    assistant_session = created.json()

    owner_read = client.get(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}",
        headers=auth_headers(owner_token),
    )
    assert owner_read.status_code == 404
    owner_list = client.get(
        "/api/workspace-assistant/sessions",
        headers=auth_headers(owner_token),
    )
    assert owner_list.status_code == 200
    assert owner_list.json()["items"] == []

    with get_session_factory()() as session:
        row = session.get(Matter, matter["id"])
        assert row is not None
        row.restricted_access = True
        session.commit()

    revoked = client.get(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}",
        headers=auth_headers(member_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["scope_state"] == "permission_changed"
    assert revoked.json()["scopes"] == []

    reset = client.put(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/scopes",
        headers=auth_headers(member_token),
        json={
            "expected_version": assistant_session["version"],
            "scopes": [{"scope_type": "tenant", "scope_id": company_id}],
        },
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["scope_state"] == "current"
    assert reset.json()["version"] == 2

    cross_tenant = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Assistant Tenant",
            "company_slug": "other-assistant-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-assistant.in",
            "owner_password": "OtherAssistant123!",
        },
    )
    assert cross_tenant.status_code == 200
    other_company_id = str(cross_tenant.json()["company"]["id"])
    denied = _create(
        client,
        member_token,
        scopes=[{"scope_type": "tenant", "scope_id": other_company_id}],
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "One or more assistant scopes were not found."
    with get_session_factory()() as session:
        denied_audit = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "workspace_assistant.scope_access_denied")
            .order_by(AuditEvent.created_at.desc())
        )
        assert denied_audit is not None
        assert other_company_id not in (denied_audit.metadata_json or "")
