"""Regression contract for the simplified, non-executable dry-run workflow.

The former tenant review endpoints added a manual approval process to an
operation that the product cannot execute. The user-visible workflow now ends
at an immutable dry-run manifest; execution remains fail-closed at the API.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company

BASE = "/api/admin/data-governance"


def test_datagov05_catalog_and_tenant_scope_replace_manual_review(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])

    catalog = client.get(f"{BASE}/data-classes", headers=auth_headers(token))
    assert catalog.status_code == 200, catalog.text
    class_ids = [entry["id"] for entry in catalog.json()["data_classes"]]
    assert "tenant_data_operations" in class_ids

    created = client.post(
        f"{BASE}/operations/dry-runs/tenant-scope",
        headers=auth_headers(token),
        json={
            "operation_type": "tenant_offboarding",
            "data_class_ids": ["tenant_data_operations"],
            "request_evidence_ref": "Regression: server-owned tenant scope",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["items"][0]["target_type"] == "tenant"
    assert len(body["items"][0]["target_reference_hash"]) == 64
    assert body["approval_status"] == "not_requested"

    for suffix in ("request", "reject", "approve"):
        response = client.post(
            f"{BASE}/operations/{body['id']}/review/{suffix}",
            headers=auth_headers(token),
            json={"reason": "not applicable"} if suffix == "reject" else None,
        )
        assert response.status_code == 404


def test_datagov05_unregistered_class_is_rejected_by_server_catalog(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])

    response = client.post(
        f"{BASE}/operations/dry-runs/tenant-scope",
        headers=auth_headers(token),
        json={
            "operation_type": "tenant_offboarding",
            "data_class_ids": ["invented_by_browser"],
        },
    )
    assert response.status_code == 409, response.text
    assert "registered" in response.json()["detail"].lower()


def test_datagov05_execution_remains_machine_blocked(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    created = client.post(
        f"{BASE}/operations/dry-runs/tenant-scope",
        headers=auth_headers(token),
        json={
            "operation_type": "tenant_offboarding",
            "data_class_ids": ["tenant_data_operations"],
        },
    )
    assert created.status_code == 201, created.text

    execution = client.post(
        f"{BASE}/operations/{created.json()['id']}/execute",
        headers=auth_headers(token),
    )
    assert execution.status_code == 503, execution.text
    assert "not implemented" in execution.json()["detail"].lower()
