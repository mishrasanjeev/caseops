from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    AuthorityDocument,
    AuthorityDocumentType,
    SourceLinkReport,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_authority(source_reference: str) -> str:
    with get_session_factory()() as session:
        row = AuthorityDocument(
            source="official",
            adapter_name="source-access-test",
            court_name="Supreme Court of India",
            forum_level="supreme_court",
            document_type=AuthorityDocumentType.JUDGMENT,
            title="Opaque Source Access Proof",
            neutral_citation="2026 INSC 404",
            case_reference="C.A. 404/2026",
            decision_date=date(2026, 8, 3),
            canonical_key=f"source-access-{uuid4()}",
            source_reference=source_reference,
            summary="Source access integration fixture.",
            document_text="Fixture text.",
            extracted_char_count=13,
        )
        session.add(row)
        session.commit()
        return row.id


def test_opaque_source_open_is_authenticated_audited_and_url_safe(
    client: TestClient,
) -> None:
    reference = "https://www.indiacode.nic.in/source-access-proof.pdf"
    authority_id = _seed_authority(reference)
    path = f"/api/source-actions/targets/authority_document/{authority_id}/open"

    unauthorized = client.get(path, follow_redirects=False)
    assert unauthorized.status_code == 401

    boot = bootstrap_company(client)
    response = client.get(
        path,
        headers=auth_headers(str(boot["access_token"])),
        params={"origin": "research"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == reference
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert reference not in str(response.request.url)

    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.company_id == boot["company"]["id"],
                AuditEvent.action == "source_access.opened",
                AuditEvent.target_id == authority_id,
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        assert reference not in (audit.metadata_json or "")
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata == {
            "origin_surface": "research",
            "permission_decision": "allowed",
            "destination_class": "verified_public",
            "source_state": "available",
            "source_version": metadata["source_version"],
            "provider": "official",
            "source_reference_sha256": hashlib.sha256(
                reference.encode("utf-8")
            ).hexdigest(),
        }


def test_opaque_source_open_fails_closed_and_keeps_typed_audit(
    client: TestClient,
) -> None:
    authority_id = _seed_authority("https://untrusted.example/expired.pdf")
    boot = bootstrap_company(client)
    response = client.get(
        f"/api/source-actions/targets/authority_document/{authority_id}/open",
        headers=auth_headers(str(boot["access_token"])),
        params={"origin": "saved_research"},
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert response.headers["x-source-state"] == "unverified"

    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.company_id == boot["company"]["id"],
                AuditEvent.action == "source_access.opened",
                AuditEvent.target_id == authority_id,
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        assert audit.result == "failed"
        assert "untrusted.example" not in (audit.metadata_json or "")
        assert json.loads(audit.metadata_json or "{}")["source_state"] == "unverified"


def test_source_report_queues_health_check_without_copying_destination(
    client: TestClient,
) -> None:
    reference = "https://www.sci.gov.in/wrong-document.pdf"
    authority_id = _seed_authority(reference)
    boot = bootstrap_company(client)
    response = client.post(
        "/api/source-actions/reports",
        headers=auth_headers(str(boot["access_token"])),
        json={
            "target_type": "authority_document",
            "target_id": authority_id,
            "origin_surface": "judge_profile",
            "issue_type": "wrong_document",
            "description": "The citation opens a different judgment.",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["source_state"] == "available"
    assert payload["destination_class"] == "verified_public"

    with get_session_factory()() as session:
        report = session.get(SourceLinkReport, payload["id"])
        assert report is not None
        assert report.company_id == boot["company"]["id"]
        assert report.reported_by_membership_id == boot["membership"]["id"]
        assert report.source_reference_sha256 == hashlib.sha256(
            reference.encode("utf-8")
        ).hexdigest()
        assert reference not in str(report.__dict__)

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == boot["company"]["id"],
                AuditEvent.action == "source_access.defect_reported",
                AuditEvent.target_id == authority_id,
            )
        )
        assert audit is not None
        assert reference not in (audit.metadata_json or "")
        assert json.loads(audit.metadata_json or "{}")["health_check_requested"] is True


def test_source_target_and_report_reject_unknown_records(client: TestClient) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    missing = "00000000-0000-0000-0000-000000000000"
    opened = client.get(
        f"/api/source-actions/targets/authority_document/{missing}/open",
        headers=headers,
        follow_redirects=False,
    )
    assert opened.status_code == 404
    reported = client.post(
        "/api/source-actions/reports",
        headers=headers,
        json={
            "target_type": "authority_document",
            "target_id": missing,
            "origin_surface": "research",
            "issue_type": "broken",
        },
    )
    assert reported.status_code == 404
