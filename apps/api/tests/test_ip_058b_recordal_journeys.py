"""IPLF-058B per-path acceptance for post-registration recordals."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_058a_recordal_foundation import (
    _create_assignment_payload,
    _lifecycle_version,
    _supporting_document,
    _transaction,
)
from tests.test_ip_record_workflow import _docket


def _fixture(client: TestClient, title: str):
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    docket = _docket(client, headers, title)
    document_id = _supporting_document(
        client,
        headers=headers,
        company_id=str(bootstrap["company"]["id"]),
        membership_id=membership_id,
        docket_id=docket["id"],
    )
    proprietor = client.post(
        f"/api/ip/dockets/{docket['id']}/title-interests",
        headers=headers,
        json={
            "interest_type": "ownership",
            "party_name": "Oldco Brands Limited",
            "party_role": "registered_proprietor",
            "effective_from": "2020-01-01",
            "evidence_reference": document_id,
            "recordal_status": "recorded",
            "registry_recorded_on": "2020-02-01",
        },
    )
    assert proprietor.status_code == 200, proprietor.text
    return headers, membership_id, docket, document_id


def _reviewed_assignment(
    client: TestClient,
    *,
    headers: dict[str, str],
    membership_id: str,
    docket: dict,
    document_id: str,
    partial: bool = False,
):
    payload = _create_assignment_payload(
        docket_id=docket["id"],
        lifecycle_version=_lifecycle_version(client, headers, docket["id"]),
        membership_id=membership_id,
        document_id=document_id,
    )
    if partial:
        payload |= {
            "scope_kind": "partial",
            "affected_classes": [9],
            "scope_details": {"goods_services": "Downloadable legal software only"},
        }
    created = client.post("/api/ip/recordals", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    reviewed = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=created.json()["id"],
        recordal_version=1,
        membership_id=membership_id,
        transaction_kind="review_approved",
        document_id=document_id,
    )
    assert reviewed.status_code == 201, reviewed.text
    return reviewed.json()


def test_uj36_exc01_pending_recordal_does_not_replace_registered_proprietor(
    client: TestClient,
) -> None:
    """IPLF-UJ-36-EXC-01: pending beneficial title remains separate from Registry title."""

    headers, membership_id, docket, document_id = _fixture(client, "PENDING ASSIGNMENT")
    reviewed = _reviewed_assignment(
        client,
        headers=headers,
        membership_id=membership_id,
        docket=docket,
        document_id=document_id,
    )
    assert all(
        row["recordal_status"] == "pending"
        for row in reviewed["projected_title_interests"]
    )

    current = client.get(f"/api/ip/dockets/{docket['id']}", headers=headers)
    assert current.status_code == 200, current.text
    interests = current.json()["title_interests"]
    assert any(
        row["party_name"] == "Oldco Brands Limited"
        and row["recordal_status"] == "recorded"
        for row in interests
    )
    assert any(
        row["party_name"] == "Newco IP LLP"
        and row["recordal_status"] == "pending"
        for row in interests
    )


def test_uj36_exc02_partial_assignment_preserves_scope_and_prior_title(
    client: TestClient,
) -> None:
    """IPLF-UJ-36-EXC-02: partial assignment retains classes and prior title."""

    headers, membership_id, docket, document_id = _fixture(client, "PARTIAL ASSIGNMENT")
    reviewed = _reviewed_assignment(
        client,
        headers=headers,
        membership_id=membership_id,
        docket=docket,
        document_id=document_id,
        partial=True,
    )
    projected = reviewed["projected_title_interests"]
    assert projected
    assert all(row["scope_json"]["scope_kind"] == "partial" for row in projected)
    assert all(row["scope_json"]["affected_classes"] == [9] for row in projected)
    assert all(
        row["scope_json"]["goods_services"] == "Downloadable legal software only"
        for row in projected
    )

    current = client.get(f"/api/ip/dockets/{docket['id']}", headers=headers)
    interests = current.json()["title_interests"]
    prior = next(row for row in interests if row["party_name"] == "Oldco Brands Limited")
    assert prior["recordal_status"] == "recorded"
    assert prior["scope_json"] == {}
