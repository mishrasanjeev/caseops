from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    IpDocketEvent,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpPostRegistrationRecordal,
    IpTitleInterest,
    MembershipRole,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_recordals import IpRecordalCreateRequest
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket


def _lifecycle_version(client: TestClient, headers: dict[str, str], docket_id: str) -> int:
    response = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert response.status_code == 200, response.text
    return int(response.json()["lifecycle_version"])


def _supporting_document(
    client: TestClient,
    *,
    headers: dict[str, str],
    company_id: str,
    membership_id: str,
    docket_id: str,
) -> str:
    seeded = client.post("/api/ip/document-taxonomy/seed", headers=headers)
    assert seeded.status_code == 200, seeded.text
    with get_session_factory()() as session:
        taxonomy = session.scalar(
            select(IpDocumentTaxonomyEntry).where(
                IpDocumentTaxonomyEntry.company_id == company_id,
                IpDocumentTaxonomyEntry.key == "evidence",
            )
        )
        assert taxonomy is not None
        document = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Executed trademark assignment",
            created_by_membership_id=membership_id,
        )
        session.add(document)
        session.flush()
        version = IpDocumentVersion(
            company_id=company_id,
            document_id=document.id,
            version=1,
            original_filename="assignment.pdf",
            display_name="ASTER_Assignment_2026.pdf",
            storage_key=f"ip/{company_id}/{document.id}/1",
            content_type="application/pdf",
            size_bytes=256,
            sha256_hex="b" * 64,
            uploaded_by_membership_id=membership_id,
        )
        session.add(version)
        session.flush()
        session.add(
            IpDocumentLink(
                company_id=company_id,
                document_id=document.id,
                version_id=version.id,
                target_type="docket",
                target_id=docket_id,
                docket_id=docket_id,
                created_by_membership_id=membership_id,
            )
        )
        session.commit()
        return document.id


def _registry_snapshot(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket: dict,
) -> str:
    asset = _asset(client, headers, docket["id"], "ASTER")
    application = _application(client, headers, docket["id"], asset["id"])
    linked = client.post(
        f"/api/ip/dockets/{docket['id']}/registry-links",
        headers=headers,
        json={
            "application_id": application["id"],
            "provider_key": "ipindia-registry",
            "office": "IP India",
            "jurisdiction": "IN",
            "identifier_kind": "application",
            "raw_identifier": "TM / 1234567 / 2026",
            "source_url": "https://ipindia.gov.in/registry/TM-1234567-2026",
            "match_confidence": "0.9900",
            "match_evidence": {"identifier": "TM-1234567-2026"},
            "capability_version": "manual-evidence-v1",
        },
    )
    assert linked.status_code == 201, linked.text
    confirmed = client.post(
        f"/api/ip/registry-links/{linked.json()['id']}/match-decision",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "confirm",
            "reason": "The application number and registry office match.",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    link = confirmed.json()
    snapshot = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json={
            "expected_link_version": link["version"],
            "idempotency_key": "iplf-058a-accepted-recordal",
            "source_url": "https://ipindia.gov.in/registry/TM-1234567-2026",
            "source_retrieved_at": "2026-08-25T08:30:00Z",
            "parser_version": "manual-normalizer-v1",
            "schema_version": 1,
            "attribution": {"publisher": "IP India", "capture_method": "manual"},
            "raw_snapshot": {"status": "registered", "proprietors": ["Newco IP LLP"]},
            "normalized_snapshot": {
                "status": "registered",
                "mark_name": "ASTER",
                "parties": [{"role": "proprietor", "name": "Newco IP LLP"}],
            },
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    return str(snapshot.json()["snapshot"]["id"])


def _create_assignment_payload(
    *,
    docket_id: str,
    lifecycle_version: int,
    membership_id: str,
    document_id: str,
) -> dict:
    return {
        "docket_id": docket_id,
        "expected_lifecycle_version": lifecycle_version,
        "responsible_membership_id": membership_id,
        "reason": "Create the reviewed assignment recordal workspace.",
        "recordal_type": "assignment",
        "legal_basis": "Trade Marks Act, 1999 and applicable Trade Marks Rules",
        "form_code": "TM-P",
        "parties": [
            {
                "role": "assignor",
                "name": "Oldco Brands Limited",
                "evidence_reference": document_id,
            },
            {
                "role": "assignee",
                "name": "Newco IP LLP",
                "evidence_reference": document_id,
            },
            {
                "role": "assignee",
                "name": "Newco Holdings LLP",
                "evidence_reference": document_id,
            },
        ],
        "executed_on": "2026-08-01",
        "effective_on": "2026-08-01",
        "affected_registration_refs": ["TM-1234567-2026"],
        "affected_classes": [9, 42],
        "scope_kind": "whole_right",
        "supporting_instrument_refs": [document_id],
        "deadline_rule_key": "tm_assignment_recordal_follow_up",
    }


def _transaction(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket_id: str,
    recordal_id: str,
    recordal_version: int,
    membership_id: str,
    transaction_kind: str,
    document_id: str,
    extra: dict | None = None,
):
    payload = {
        "expected_version": recordal_version,
        "expected_lifecycle_version": _lifecycle_version(client, headers, docket_id),
        "transaction_kind": transaction_kind,
        "effective_at": datetime.now(UTC).isoformat(),
        "responsible_membership_id": membership_id,
        "reason": f"Record the {transaction_kind.replace('_', ' ')} transaction.",
        "evidence_refs": [document_id]
        if transaction_kind
        in {"filed", "defect_noted", "corrected", "rejected", "accepted"}
        else [],
        "document_refs": [document_id],
    }
    payload.update(extra or {})
    return client.post(
        f"/api/ip/recordals/{recordal_id}/transactions",
        headers=headers,
        json=payload,
    )


def test_assignment_recordal_projects_pending_then_registry_recorded_title(
    client: TestClient,
) -> None:
    """IPLF-UJ-36-NORMAL / EXC-03 / EXC-04: lifecycle, correction, conflict approval."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    docket = _docket(client, headers, "ASTER")
    document_id = _supporting_document(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        docket_id=docket["id"],
    )
    snapshot_id = _registry_snapshot(client, headers=headers, docket=docket)

    created = client.post(
        "/api/ip/recordals",
        headers=headers,
        json=_create_assignment_payload(
            docket_id=docket["id"],
            lifecycle_version=_lifecycle_version(client, headers, docket["id"]),
            membership_id=membership_id,
            document_id=document_id,
        ),
    )
    assert created.status_code == 201, created.text
    recordal = created.json()
    assert recordal["status"] == "draft"

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = MembershipRole.MEMBER
        session.commit()
    writer_cannot_approve = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=1,
        membership_id=membership_id,
        transaction_kind="review_approved",
        document_id=document_id,
    )
    assert writer_cannot_approve.status_code == 403
    assert "ip:approve" in writer_cannot_approve.text
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = MembershipRole.OWNER
        session.commit()

    reviewed = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=1,
        membership_id=membership_id,
        transaction_kind="review_approved",
        document_id=document_id,
    )
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["recordal"]["status"] == "ready"
    pending = reviewed.json()["projected_title_interests"]
    assert {row["party_name"] for row in pending} == {"Newco IP LLP", "Newco Holdings LLP"}
    assert all(row["recordal_status"] == "pending" for row in pending)
    assert all(row["conflict_flags_json"] == [] for row in pending)

    stale = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=1,
        membership_id=membership_id,
        transaction_kind="filed",
        document_id=document_id,
    )
    assert stale.status_code == 409
    assert "version changed" in stale.text

    filed = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=2,
        membership_id=membership_id,
        transaction_kind="filed",
        document_id=document_id,
    )
    assert filed.status_code == 201, filed.text
    assert all(
        row["recordal_status"] == "filed"
        for row in filed.json()["projected_title_interests"]
    )

    defective = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=3,
        membership_id=membership_id,
        transaction_kind="defect_noted",
        document_id=document_id,
    )
    assert defective.status_code == 201, defective.text
    assert defective.json()["recordal"]["status"] == "defective"
    corrected = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=4,
        membership_id=membership_id,
        transaction_kind="corrected",
        document_id=document_id,
    )
    assert corrected.status_code == 201, corrected.text
    refiled = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=5,
        membership_id=membership_id,
        transaction_kind="filed",
        document_id=document_id,
    )
    assert refiled.status_code == 201, refiled.text

    with get_session_factory()() as session:
        stored_recordal = session.get(IpPostRegistrationRecordal, recordal["id"])
        assert stored_recordal is not None
        stored_recordal.affected_registration_refs_json = ["TM-7654321-2026"]
        session.commit()
    mismatched_registration = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=6,
        membership_id=membership_id,
        transaction_kind="accepted",
        document_id=document_id,
        extra={
            "source_url": "https://ipindia.gov.in/registry/TM-1234567-2026",
            "source_reference": "IP India register snapshot dated 25 August 2026",
            "registry_snapshot_id": snapshot_id,
            "registry_recorded_on": "2026-08-25",
            "details": {"client_registry_conflict_reviewed": True},
        },
    )
    assert mismatched_registration.status_code == 422
    assert "explicitly affected by this recordal" in mismatched_registration.text
    with get_session_factory()() as session:
        stored_recordal = session.get(IpPostRegistrationRecordal, recordal["id"])
        assert stored_recordal is not None
        stored_recordal.affected_registration_refs_json = ["TM-1234567-2026"]
        session.commit()

    mismatched_source = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=6,
        membership_id=membership_id,
        transaction_kind="accepted",
        document_id=document_id,
        extra={
            "source_url": "https://registry.example.com/unrelated-record",
            "source_reference": "Unrelated source",
            "registry_snapshot_id": snapshot_id,
            "registry_recorded_on": "2026-08-25",
        },
    )
    assert mismatched_source.status_code == 422
    assert "must match the selected immutable snapshot" in mismatched_source.text

    unreviewed_conflict = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=6,
        membership_id=membership_id,
        transaction_kind="accepted",
        document_id=document_id,
        extra={
            "source_url": "https://ipindia.gov.in/registry/TM-1234567-2026",
            "source_reference": "IP India register snapshot dated 25 August 2026",
            "registry_snapshot_id": snapshot_id,
            "registry_recorded_on": "2026-08-25",
        },
    )
    assert unreviewed_conflict.status_code == 422
    assert "conflict review" in unreviewed_conflict.text

    accepted = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal["id"],
        recordal_version=6,
        membership_id=membership_id,
        transaction_kind="accepted",
        document_id=document_id,
        extra={
            "source_url": "https://ipindia.gov.in/registry/TM-1234567-2026",
            "source_reference": "IP India register snapshot dated 25 August 2026",
            "registry_snapshot_id": snapshot_id,
            "registry_recorded_on": "2026-08-25",
            "details": {"client_registry_conflict_reviewed": True},
        },
    )
    assert accepted.status_code == 201, accepted.text
    result = accepted.json()
    assert result["recordal"]["status"] == "accepted"
    assert result["registry_projection_applied"] is True
    assert result["event"]["source"] == "manual"
    assert result["event"]["payload_json"]["registry_evidence_source"] == "immutable_snapshot"
    assert result["event"]["payload_json"]["client_registry_conflict_detected"] is True
    assert all(
        row["recordal_status"] == "recorded"
        for row in result["projected_title_interests"]
    )
    assert all(
        row["registry_recorded_on"] == "2026-08-25"
        for row in result["projected_title_interests"]
    )

    workspace = client.get(
        f"/api/ip/recordals/{recordal['id']}/workspace", headers=headers
    )
    assert workspace.status_code == 200, workspace.text
    assert len(workspace.json()["transactions"]) == 7
    assert len(workspace.json()["current_registered_interests"]) == 2
    assert workspace.json()["pending_interests"] == []

    listed = client.get(
        "/api/ip/recordals",
        headers=headers,
        params={"docket_id": docket["id"], "status": "accepted"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    with get_session_factory()() as session:
        events = list(
            session.scalars(
                select(IpDocketEvent).where(IpDocketEvent.recordal_id == recordal["id"])
            )
        )
        assert len(events) == 7
        assert all(event.event_kind == "post_registration_recordal_transaction" for event in events)
        assert not any("opposition" in str(event.payload_json).casefold() for event in events)
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.target_id == recordal["id"],
                )
            )
        )
        assert {event.action for event in audits} == {
            "ip_recordal.created",
            "ip_recordal.transaction_recorded",
        }


def test_recordal_withdrawal_rejection_and_tenant_boundaries(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    docket = _docket(client, headers, "WITHDRAWN ASSIGNMENT")
    document_id = _supporting_document(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        docket_id=docket["id"],
    )
    payload = _create_assignment_payload(
        docket_id=docket["id"],
        lifecycle_version=_lifecycle_version(client, headers, docket["id"]),
        membership_id=membership_id,
        document_id=document_id,
    )
    created = client.post("/api/ip/recordals", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    recordal_id = created.json()["id"]
    withdrawn = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=recordal_id,
        recordal_version=1,
        membership_id=membership_id,
        transaction_kind="withdrawn",
        document_id=document_id,
    )
    assert withdrawn.status_code == 201, withdrawn.text
    assert withdrawn.json()["projected_title_interests"] == []
    with get_session_factory()() as session:
        assert session.scalars(
            select(IpTitleInterest).where(IpTitleInterest.source_recordal_id == recordal_id)
        ).all() == []

    rejected_create = client.post(
        "/api/ip/recordals",
        headers=headers,
        json=payload
        | {
            "expected_lifecycle_version": _lifecycle_version(
                client, headers, docket["id"]
            ),
            "reason": "Create a second assignment to prove registry rejection history.",
        },
    )
    assert rejected_create.status_code == 201, rejected_create.text
    rejected_id = rejected_create.json()["id"]
    review = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=rejected_id,
        recordal_version=1,
        membership_id=membership_id,
        transaction_kind="review_approved",
        document_id=document_id,
    )
    assert review.status_code == 201, review.text
    filing = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=rejected_id,
        recordal_version=2,
        membership_id=membership_id,
        transaction_kind="filed",
        document_id=document_id,
    )
    assert filing.status_code == 201, filing.text
    rejected = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        recordal_id=rejected_id,
        recordal_version=3,
        membership_id=membership_id,
        transaction_kind="rejected",
        document_id=document_id,
    )
    assert rejected.status_code == 201, rejected.text
    assert rejected.json()["recordal"]["status"] == "rejected"
    assert all(
        interest["recordal_status"] == "rejected"
        for interest in rejected.json()["projected_title_interests"]
    )

    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Recordal Boundary LLP",
            "company_slug": "recordal-boundary",
            "company_type": "law_firm",
            "owner_full_name": "Boundary Owner",
            "owner_email": "recordal-boundary@example.com",
            "owner_password": "Aa1!" + ("fixture" * 3),
        },
    )
    assert second.status_code == 200, second.text
    second_headers = auth_headers(str(second.json()["access_token"]))
    assert client.get(f"/api/ip/recordals/{recordal_id}", headers=second_headers).status_code == 404
    assert (
        client.get(f"/api/ip/recordals/{recordal_id}/workspace", headers=second_headers).status_code
        == 404
    )

    other_docket = _docket(client, headers, "OTHER DOCKET")
    mismatched = client.post(
        "/api/ip/recordals",
        headers=headers,
        json=_create_assignment_payload(
            docket_id=other_docket["id"],
            lifecycle_version=_lifecycle_version(client, headers, other_docket["id"]),
            membership_id=membership_id,
            document_id=document_id,
        ),
    )
    assert mismatched.status_code == 422
    assert "linked to the selected docket" in mismatched.text


def test_recordal_contract_rejects_missing_title_dates_and_opposition_semantics() -> None:
    base = {
        "docket_id": "docket-1",
        "expected_lifecycle_version": 1,
        "responsible_membership_id": "membership-1",
        "reason": "Create a legally reviewed recordal.",
        "recordal_type": "assignment",
        "legal_basis": "Trade Marks Act, 1999",
        "form_code": "TM-P",
        "parties": [
            {"role": "assignor", "name": "Oldco LLP", "evidence_reference": "doc-1"},
            {"role": "assignee", "name": "Newco LLP", "evidence_reference": "doc-1"},
        ],
        "affected_registration_refs": ["TM-1"],
        "supporting_instrument_refs": ["doc-1"],
    }
    with pytest.raises(ValidationError, match="effective date"):
        IpRecordalCreateRequest.model_validate(base)
    with pytest.raises(ValidationError, match="opposition deadline rule"):
        IpRecordalCreateRequest.model_validate(
            base
            | {
                "executed_on": date(2026, 8, 1),
                "effective_on": date(2026, 8, 1),
                "deadline_rule_key": "tm_opposition_counterstatement",
            }
        )
    with pytest.raises(ValidationError):
        IpRecordalCreateRequest.model_validate(
            base
            | {
                "recordal_type": "cancellation",
                "executed_on": date(2026, 8, 1),
                "effective_on": date(2026, 8, 1),
            }
        )
    with pytest.raises(ValidationError, match="supporting instrument references"):
        IpRecordalCreateRequest.model_validate(
            base
            | {
                "executed_on": date(2026, 8, 1),
                "effective_on": date(2026, 8, 1),
                "parties": [
                    {
                        "role": "assignor",
                        "name": "Oldco LLP",
                        "evidence_reference": "outside-docket-doc",
                    },
                    {
                        "role": "assignee",
                        "name": "Newco LLP",
                        "evidence_reference": "doc-1",
                    },
                ],
            }
        )
