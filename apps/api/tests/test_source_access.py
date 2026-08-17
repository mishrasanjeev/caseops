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
    MatterAttachment,
    SourceLinkReport,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_authority(source_reference: str) -> str:
    with get_session_factory()() as session:
        row = AuthorityDocument(
            # 2026-08-16 (FMB-01): this fixture used source="official", a value
            # no ingest path ever writes. The predicate under test compared
            # against that literal, so the fixture was the only thing that could
            # satisfy it - the suite stayed green while production could never
            # pass. Use a real registry source key instead.
            source="supreme_court_latest_orders",
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


def _bootstrap_tenant(client: TestClient, slug: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} Legal",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug.title()} Owner",
            "owner_email": f"owner@{slug}.in",
            "owner_password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_matter_attachment(client: TestClient, boot: dict[str, object]) -> tuple[str, str]:
    token = str(boot["access_token"])
    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Protected source matter",
            "matter_code": f"SRC-{uuid4().hex[:8]}",
            "client_name": "Protected Client",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert matter_response.status_code == 200, matter_response.text
    matter_id = str(matter_response.json()["id"])
    content = b"Protected source fixture"
    with get_session_factory()() as session:
        attachment = MatterAttachment(
            matter_id=matter_id,
            uploaded_by_membership_id=str(boot["membership"]["id"]),
            original_filename="protected-source.txt",
            storage_key=f"test/source-access/{uuid4().hex}.txt",
            content_type="text/plain",
            size_bytes=len(content),
            sha256_hex=hashlib.sha256(content).hexdigest(),
        )
        session.add(attachment)
        session.commit()
        return matter_id, attachment.id


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
            "provider": "supreme_court_latest_orders",
            "source_reference_sha256": hashlib.sha256(
                reference.encode("utf-8")
            ).hexdigest(),
        }


def test_resolved_source_action_exposes_only_canonical_target_identity(
    client: TestClient,
) -> None:
    reference = "https://www.indiacode.nic.in/target-contract.pdf"
    authority_id = _seed_authority(reference)
    boot = bootstrap_company(client)
    response = client.post(
        "/api/authorities/search",
        headers=auth_headers(str(boot["access_token"])),
        json={"query": "Opaque Source Access Proof", "limit": 10},
    )
    assert response.status_code == 200, response.text
    action = response.json()["results"][0]["source_action"]
    assert action["target_type"] == "authority_document"
    assert action["target_id"] == authority_id
    assert reference not in action["open_url"]


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

    repeated = client.get(
        f"/api/source-actions/targets/authority_document/{authority_id}/open",
        headers=auth_headers(str(boot["access_token"])),
        params={"origin": "saved_research"},
        follow_redirects=False,
    )
    assert repeated.status_code == 409

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
        reports = session.scalars(
            select(SourceLinkReport).where(
                SourceLinkReport.company_id == boot["company"]["id"],
                SourceLinkReport.target_type == "authority_document",
                SourceLinkReport.target_id == authority_id,
                SourceLinkReport.origin_surface == "saved_research",
            )
        ).all()
        assert len(reports) == 1
        assert reports[0].issue_type == "stale"
        assert reports[0].source_state == "unverified"
        assert reference_host_absent(reports[0], "untrusted.example")


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


def test_protected_matter_source_reauthorizes_and_never_crosses_tenants(
    client: TestClient,
) -> None:
    owner = _bootstrap_tenant(client, f"source-owner-{uuid4().hex[:8]}")
    other = _bootstrap_tenant(client, f"source-other-{uuid4().hex[:8]}")
    matter_id, attachment_id = _seed_matter_attachment(client, owner)
    path = f"/api/source-actions/targets/matter_attachment/{attachment_id}/open"

    opened = client.get(
        path,
        headers=auth_headers(str(owner["access_token"])),
        params={"origin": "uploaded_case_analysis"},
        follow_redirects=False,
    )
    assert opened.status_code == 307, opened.text
    assert opened.headers["location"] == (
        f"/api/matters/{matter_id}/attachments/{attachment_id}/download"
    )
    assert opened.headers["cache-control"] == "no-store"
    assert opened.headers["referrer-policy"] == "no-referrer"

    denied_open = client.get(
        path,
        headers=auth_headers(str(other["access_token"])),
        follow_redirects=False,
    )
    assert denied_open.status_code == 404
    denied_report = client.post(
        "/api/source-actions/reports",
        headers=auth_headers(str(other["access_token"])),
        json={
            "target_type": "matter_attachment",
            "target_id": attachment_id,
            "origin_surface": "uploaded_case_analysis",
            "issue_type": "broken",
        },
    )
    assert denied_report.status_code == 404

    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.company_id == owner["company"]["id"],
                AuditEvent.action == "source_access.opened",
                AuditEvent.target_id == attachment_id,
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert metadata["destination_class"] == "caseops_protected"
        assert metadata["origin_surface"] == "uploaded_case_analysis"


def reference_host_absent(report: SourceLinkReport, hostname: str) -> bool:
    return hostname not in str(report.__dict__)
