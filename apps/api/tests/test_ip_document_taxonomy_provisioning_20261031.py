"""BUG-008 / BUG-002(b): every IP tenant can classify a document without /seed.

These tests never call POST /api/ip/document-taxonomy/seed and never insert
taxonomy rows for the tenant under test. The default classifications must come
from the product path a law firm actually uses: configuring and enabling the
IP workspace, or uploading the first document.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    IpDocumentTaxonomyAlias,
    IpDocumentTaxonomyEntry,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_documents
from caseops_api.services.ip_documents import (
    DEFAULT_TAXONOMY,
    TAXONOMY_VERSION,
    ensure_default_ip_document_taxonomy,
)
from tests.test_auth_company import auth_headers
from tests.test_ip_manual_application_workflow import _payload as manual_trademark_payload

DEFAULT_KEYS = {key for key, _label in DEFAULT_TAXONOMY}
PROVISIONED = "ip_document_taxonomy.defaults_provisioned"


def _bootstrap(client: TestClient, slug: str) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.replace("-", " ").title(),
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Taxonomy Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "FixturePass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def workspace_configuration(membership_id: str) -> dict:
    """The body the IP workspace setup card sends; the taxonomy version is server-owned."""

    return {
        "enabled_asset_types": ["trademark"],
        "jurisdictions": ["IN"],
        "offices": ["IP India"],
        "timezone": "Asia/Kolkata",
        "holiday_calendar_key": "in-national",
        "working_day_policy": {"working_weekdays": [0, 1, 2, 3, 4]},
        "event_catalog_version": "ip-events-v1",
        "deadline_rule_versions": {"IN": "2026.1"},
        "notification_channels": ["in_app"],
        "critical_event_policy": {"escalation_after_minutes": 30},
        "escalation_owner_membership_id": membership_id,
        "provider_keys": [],
        "provider_terms_version": None,
        "accept_provider_terms": False,
    }


def enable_ip_workspace(client: TestClient, headers: dict[str, str], membership_id: str) -> dict:
    saved = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json=workspace_configuration(membership_id),
    )
    assert saved.status_code == 200, saved.text
    version = saved.json()["configuration"]["version"]
    enabled = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={"expected_config_version": version, "enabled_automations": []},
    )
    assert enabled.status_code == 200, enabled.text
    return enabled.json()


def _create_docket(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post(
        "/api/ip/trademark-applications/manual",
        headers=headers,
        json=manual_trademark_payload(number=None),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["docket"]["id"])


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    docket_id: str,
    taxonomy_key: str,
    content: bytes,
):
    return client.post(
        "/api/ip/documents/upload",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "taxonomy_key": taxonomy_key,
                    "title": "Executed deed of assignment",
                    "confidentiality": "internal",
                    "is_privileged": False,
                    "client_code": "ASTER",
                    "asset_type": "Trademark",
                    "mark": "ASTER",
                    "jurisdiction": "IN",
                    "document_date": "2026-10-31",
                    "links": [{"target_type": "docket", "target_id": docket_id}],
                }
            )
        },
        files={"upload": ("assignment-deed.txt", content, "text/plain")},
    )


def _taxonomy_rows(company_id: str) -> list[IpDocumentTaxonomyEntry]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(IpDocumentTaxonomyEntry).where(
                    IpDocumentTaxonomyEntry.company_id == company_id
                )
            ).all()
        )


def _provisioning_events(company_id: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == PROVISIONED,
                )
            ).all()
        )


def test_enabled_workspace_lists_defaults_and_accepts_assignment_without_seed(
    client: TestClient,
) -> None:
    tenant = _bootstrap(client, "taxonomy-enabled-firm")
    headers = auth_headers(str(tenant["access_token"]))
    company_id = str(tenant["company"]["id"])
    membership_id = str(tenant["membership"]["id"])

    before = client.get("/api/ip/workspace/configuration", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["document_taxonomy"] == {
        "taxonomy_version": TAXONOMY_VERSION,
        "total_entry_count": 0,
        "active_entry_count": 0,
        "ready": False,
    }

    status = enable_ip_workspace(client, headers, membership_id)
    assert status["configuration"]["workspace_enabled"] is True
    # One version string: the configuration records the server's taxonomy version.
    assert status["configuration"]["document_taxonomy_version"] == TAXONOMY_VERSION
    assert status["document_taxonomy"] == {
        "taxonomy_version": TAXONOMY_VERSION,
        "total_entry_count": len(DEFAULT_TAXONOMY),
        "active_entry_count": len(DEFAULT_TAXONOMY),
        "ready": True,
    }

    taxonomy = client.get("/api/ip/document-taxonomy", headers=headers)
    assert taxonomy.status_code == 200, taxonomy.text
    body = taxonomy.json()
    assert body["taxonomy_version"] == status["configuration"]["document_taxonomy_version"]
    assert {entry["key"] for entry in body["entries"]} == DEFAULT_KEYS
    assert all(entry["is_active"] for entry in body["entries"])
    assert [entry["label"] for entry in body["entries"]] == [
        label for _key, label in DEFAULT_TAXONOMY
    ]

    readiness = client.get("/api/ip/readiness", headers=headers)
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["configuration_status"]["document_taxonomy"]["ready"] is True

    docket_id = _create_docket(client, headers)
    uploaded = _upload(
        client,
        headers,
        docket_id=docket_id,
        taxonomy_key="assignment",
        content=b"Deed of assignment executed by the assignor in favour of the assignee. " * 20,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["outcome"] == "created"
    assert uploaded.json()["document"]["taxonomy_key"] == "assignment"
    linked = client.get(f"/api/ip/documents?docket_id={docket_id}", headers=headers)
    assert linked.status_code == 200, linked.text
    assert [row["taxonomy_label"] for row in linked.json()["items"]] == ["Assignment"]

    events = _provisioning_events(company_id)
    # Saving the configuration provisioned once; enabling found entries and
    # the upload found entries, so neither wrote a second provisioning event.
    assert len(events) == 1
    assert events[0].actor_membership_id == membership_id
    assert events[0].actor_type == "system"
    metadata = json.loads(events[0].metadata_json or "{}")
    assert metadata["trigger"] == "workspace_configuration"
    assert metadata["taxonomy_version"] == TAXONOMY_VERSION
    assert set(metadata["keys"]) == DEFAULT_KEYS
    rows = _taxonomy_rows(company_id)
    assert {row.updated_by_membership_id for row in rows} == {membership_id}
    assert all(row.is_seeded and row.version == 1 for row in rows)


def test_first_upload_provisions_a_tenant_that_has_no_taxonomy(client: TestClient) -> None:
    """A tenant enabled before default provisioning existed self-heals on upload."""

    tenant = _bootstrap(client, "taxonomy-legacy-firm")
    headers = auth_headers(str(tenant["access_token"]))
    company_id = str(tenant["company"]["id"])
    docket_id = _create_docket(client, headers)

    empty = client.get("/api/ip/document-taxonomy", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["entries"] == []

    uploaded = _upload(
        client,
        headers,
        docket_id=docket_id,
        taxonomy_key="assignment",
        content=b"Legacy tenant assignment instrument with searchable text. " * 20,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["document"]["taxonomy_key"] == "assignment"

    listed = client.get("/api/ip/document-taxonomy", headers=headers)
    assert {entry["key"] for entry in listed.json()["entries"]} == DEFAULT_KEYS
    events = _provisioning_events(company_id)
    assert len(events) == 1
    assert json.loads(events[0].metadata_json or "{}")["trigger"] == "document_upload"

    second = _upload(
        client,
        headers,
        docket_id=docket_id,
        taxonomy_key="licence",
        content=b"Licence agreement executed for the registered mark. " * 20,
    )
    assert second.status_code == 200, second.text
    assert len(_provisioning_events(company_id)) == 1
    assert len(_taxonomy_rows(company_id)) == len(DEFAULT_TAXONOMY)

    unknown = _upload(
        client,
        headers,
        docket_id=docket_id,
        taxonomy_key="not-a-classification",
        content=b"Unclassified bytes that must be rejected. " * 20,
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Active document taxonomy entry not found."


def test_firm_owned_taxonomy_is_never_overwritten(client: TestClient) -> None:
    tenant = _bootstrap(client, "taxonomy-custom-firm")
    headers = auth_headers(str(tenant["access_token"]))
    company_id = str(tenant["company"]["id"])
    membership_id = str(tenant["membership"]["id"])

    custom = client.put(
        "/api/ip/document-taxonomy/client_instructions",
        headers=headers,
        json={"label": "Client instructions", "aliases": ["Instruction letter"]},
    )
    assert custom.status_code == 200, custom.text

    status = enable_ip_workspace(client, headers, membership_id)
    assert status["document_taxonomy"]["total_entry_count"] == 1
    assert status["document_taxonomy"]["ready"] is True
    keys = [row.key for row in _taxonomy_rows(company_id)]
    assert keys == ["client_instructions"]
    assert _provisioning_events(company_id) == []

    # The upload path does not add defaults behind the firm's back either: the
    # picker offers only the firm's entry, and the validator agrees.
    docket_id = _create_docket(client, headers)
    rejected = _upload(
        client,
        headers,
        docket_id=docket_id,
        taxonomy_key="assignment",
        content=b"Assignment that this firm does not classify this way. " * 20,
    )
    assert rejected.status_code == 404
    accepted = _upload(
        client,
        headers,
        docket_id=docket_id,
        taxonomy_key="client_instructions",
        content=b"Client instruction letter for the filing. " * 20,
    )
    assert accepted.status_code == 200, accepted.text
    assert [row.key for row in _taxonomy_rows(company_id)] == ["client_instructions"]


def test_renamed_and_deactivated_defaults_survive_reconfiguration(client: TestClient) -> None:
    tenant = _bootstrap(client, "taxonomy-renamed-firm")
    headers = auth_headers(str(tenant["access_token"]))
    company_id = str(tenant["company"]["id"])
    membership_id = str(tenant["membership"]["id"])
    status = enable_ip_workspace(client, headers, membership_id)

    renamed = client.put(
        "/api/ip/document-taxonomy/evidence",
        headers=headers,
        json={"expected_version": 1, "label": "Evidence of use", "aliases": []},
    )
    assert renamed.status_code == 200, renamed.text
    deactivated = client.put(
        "/api/ip/document-taxonomy/invoice",
        headers=headers,
        json={"expected_version": 1, "label": "Invoice", "is_active": False, "aliases": []},
    )
    assert deactivated.status_code == 200, deactivated.text

    resaved = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json={
            **workspace_configuration(membership_id),
            "expected_version": status["configuration"]["version"],
        },
    )
    assert resaved.status_code == 200, resaved.text
    assert resaved.json()["document_taxonomy"]["active_entry_count"] == len(DEFAULT_TAXONOMY) - 1
    reenabled = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={
            "expected_config_version": resaved.json()["configuration"]["version"],
            "enabled_automations": [],
        },
    )
    assert reenabled.status_code == 200, reenabled.text

    rows = {row.key: row for row in _taxonomy_rows(company_id)}
    assert len(rows) == len(DEFAULT_TAXONOMY)
    assert rows["evidence"].label == "Evidence of use"
    assert rows["evidence"].version == 2
    assert rows["invoice"].is_active is False
    assert len(_provisioning_events(company_id)) == 1

    listed = client.get("/api/ip/document-taxonomy", headers=headers).json()["entries"]
    active_keys = {entry["key"] for entry in listed if entry["is_active"]}
    assert "invoice" not in active_keys
    docket_id = _create_docket(client, headers)
    inactive = _upload(
        client,
        headers,
        docket_id=docket_id,
        taxonomy_key="invoice",
        content=b"Invoice for a deactivated classification. " * 20,
    )
    assert inactive.status_code == 404


def test_provisioning_is_tenant_isolated(client: TestClient) -> None:
    first = _bootstrap(client, "taxonomy-tenant-a")
    first_headers = auth_headers(str(first["access_token"]))
    first_company = str(first["company"]["id"])
    enable_ip_workspace(client, first_headers, str(first["membership"]["id"]))
    first_ids = {row.id for row in _taxonomy_rows(first_company)}
    assert len(first_ids) == len(DEFAULT_TAXONOMY)

    second = _bootstrap(client, "taxonomy-tenant-b")
    second_headers = auth_headers(str(second["access_token"]))
    second_company = str(second["company"]["id"])
    isolated = client.get("/api/ip/document-taxonomy", headers=second_headers)
    assert isolated.status_code == 200
    assert isolated.json()["entries"] == []
    second_status = client.get("/api/ip/workspace/configuration", headers=second_headers)
    assert second_status.json()["document_taxonomy"]["total_entry_count"] == 0

    docket_id = _create_docket(client, second_headers)
    uploaded = _upload(
        client,
        second_headers,
        docket_id=docket_id,
        taxonomy_key="assignment",
        content=b"Tenant B assignment instrument with searchable text. " * 20,
    )
    assert uploaded.status_code == 200, uploaded.text

    second_rows = _taxonomy_rows(second_company)
    assert len(second_rows) == len(DEFAULT_TAXONOMY)
    assert {row.updated_by_membership_id for row in second_rows} == {
        str(second["membership"]["id"])
    }
    assert first_ids.isdisjoint({row.id for row in second_rows})
    assert {row.id for row in _taxonomy_rows(first_company)} == first_ids
    assert len(_provisioning_events(first_company)) == 1
    assert len(_provisioning_events(second_company)) == 1
    # Tenant A's document list never shows tenant B's upload.
    first_documents = client.get("/api/ip/documents", headers=first_headers)
    assert first_documents.status_code == 200
    assert first_documents.json()["items"] == []


def test_unauthorized_callers_cannot_trigger_provisioning(client: TestClient) -> None:
    tenant = _bootstrap(client, "taxonomy-roles-firm")
    owner_headers = auth_headers(str(tenant["access_token"]))
    company_id = str(tenant["company"]["id"])
    docket_id = _create_docket(client, owner_headers)
    for email, role in (
        ("viewer@taxonomy-roles-firm.example", "viewer"),
        ("member@taxonomy-roles-firm.example", "member"),
    ):
        created = client.post(
            "/api/companies/current/users",
            headers=owner_headers,
            json={
                "full_name": f"Taxonomy {role.title()}",
                "email": email,
                "password": "FixturePass123!",
                "role": role,
            },
        )
        assert created.status_code == 200, created.text

    def login(email: str) -> dict[str, str]:
        response = client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": "FixturePass123!",
                "company_slug": "taxonomy-roles-firm",
            },
        )
        assert response.status_code == 200, response.text
        return auth_headers(str(response.json()["access_token"]))

    viewer = login("viewer@taxonomy-roles-firm.example")
    viewer_upload = _upload(
        client,
        viewer,
        docket_id=docket_id,
        taxonomy_key="assignment",
        content=b"Viewer must not be able to upload or provision. " * 20,
    )
    assert viewer_upload.status_code == 403
    member = login("member@taxonomy-roles-firm.example")
    member_configuration = client.put(
        "/api/ip/workspace/configuration",
        headers=member,
        json=workspace_configuration(str(tenant["membership"]["id"])),
    )
    assert member_configuration.status_code == 403
    assert client.post("/api/ip/document-taxonomy/seed", headers=member).status_code == 403
    client.cookies.clear()
    # Unauthenticated writes stop at the CSRF or authentication boundary.
    assert client.post(
        "/api/ip/documents/upload",
        data={"metadata_json": "{}"},
        files={"upload": ("x.txt", b"x", "text/plain")},
    ).status_code in {401, 403}
    assert client.get("/api/ip/workspace/configuration").status_code == 401

    assert _taxonomy_rows(company_id) == []
    assert _provisioning_events(company_id) == []


def test_lost_provisioning_race_keeps_the_winner_and_the_transaction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = _bootstrap(client, "taxonomy-race-firm")
    headers = auth_headers(str(tenant["access_token"]))
    company_id = str(tenant["company"]["id"])
    membership_id = str(tenant["membership"]["id"])
    enable_ip_workspace(client, headers, membership_id)
    winner_ids = {row.id for row in _taxonomy_rows(company_id)}

    # Simulate the loser of a concurrent first provisioning: its emptiness
    # check ran before the winner committed, so it attempts the full insert.
    monkeypatch.setattr(ip_documents, "_company_has_taxonomy_entries", lambda *_a, **_k: False)
    with get_session_factory()() as session:
        inserted = ensure_default_ip_document_taxonomy(
            session,
            company_id=company_id,
            actor_membership_id=membership_id,
            trigger="document_upload",
        )
        assert inserted == []
        # The outer transaction survived the rejected savepoint.
        count = session.scalar(
            select(func.count(IpDocumentTaxonomyAlias.id)).where(
                IpDocumentTaxonomyAlias.company_id == company_id
            )
        )
        session.commit()
    assert count == len(DEFAULT_TAXONOMY)
    assert {row.id for row in _taxonomy_rows(company_id)} == winner_ids
    assert len(_provisioning_events(company_id)) == 1
