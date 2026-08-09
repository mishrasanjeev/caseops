from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AuditEvent,
    CompanyMembership,
    DocumentProcessingTargetType,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyAlias,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_documents import (
    IpDocumentNamingPreviewRequest,
    IpDocumentTaxonomyUpsertRequest,
)
from caseops_api.services.ip_documents import preview_ip_document_name
from tests.test_auth_company import auth_headers, bootstrap_company


def _bootstrap_tenant(client: TestClient, *, slug: str, email: str) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.replace("-", " ").title(),
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Document Foundation Owner",
            "owner_email": email,
            "owner_password": "FixturePass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_document_foundation_contract_and_naming_preview(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    contract = client.get("/api/ip/documents/foundation-contract", headers=headers)
    assert contract.status_code == 200, contract.text
    assert contract.json() == {
        "identity_owner": "ip_documents",
        "version_owner": "ip_document_versions",
        "link_owner": "ip_document_links",
        "binary_storage_owner": "shared_document_storage",
        "processing_queue_owner": "document_processing_jobs",
        "processing_target_type": "ip_document_version",
        "taxonomy_version": "ip-document-taxonomy-v1",
        "naming_pattern": (
            "[ClientCode]_[AssetType]_[Mark]_[Jurisdiction]_[ApplicationNo]_"
            "[ProceedingType]_[ProceedingNo]_[DocumentType]_[YYYY-MM-DD]_[Version]"
        ),
        "supported_link_targets": [
            "docket",
            "application",
            "proceeding",
            "event",
            "deadline",
        ],
    }
    assert DocumentProcessingTargetType.IP_DOCUMENT_VERSION == "ip_document_version"

    first = client.post(
        "/api/ip/documents/naming-preview",
        headers=headers,
        json={
            "client_code": "ACME/01",
            "asset_type": "Trademark",
            "mark": "=SUM(1/1)",
            "jurisdiction": "IN",
            "application_no": None,
            "document_type": "Examination Report",
            "document_date": "2026-08-09",
            "version": 2,
            "extension": ".PDF<script>",
        },
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["requested_name"] == (
        "ACME_01_Trademark__=SUM(1_1)_IN_Examination_Report_2026-08-09_2.pdfscript"
    )
    assert payload["resolved_name"] == payload["requested_name"]
    assert payload["conflict_detected"] is False
    assert {"application_no", "proceeding_type", "proceeding_no"}.issubset(
        payload["omitted_components"]
    )
    assert any("sanitized" in warning for warning in payload["warnings"])

    conflict = client.post(
        "/api/ip/documents/naming-preview",
        headers=headers,
        json={
            "client_code": "Acme",
            "document_type": "Order",
            "version": 1,
            "extension": "pdf",
            "existing_names": ["ACME_ORDER_1.PDF", "Acme_Order_1_2.pdf"],
        },
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["requested_name"] == "Acme_Order_1.pdf"
    assert conflict.json()["resolved_name"] == "Acme_Order_1_3.pdf"
    assert conflict.json()["conflict_detected"] is True
    assert conflict.json()["conflict_suffix"] == 3


def test_taxonomy_seed_upsert_aliases_audit_and_tenant_isolation(client: TestClient) -> None:
    first = _bootstrap_tenant(
        client,
        slug="ip-doc-foundation-a",
        email="ip-doc-foundation-a@example.com",
    )
    first_headers = auth_headers(str(first["access_token"]))
    first_company_id = str(first["company"]["id"])

    before_seed = client.get("/api/ip/document-taxonomy", headers=first_headers)
    assert before_seed.status_code == 200
    assert before_seed.json()["entries"] == []

    seeded = client.post("/api/ip/document-taxonomy/seed", headers=first_headers)
    assert seeded.status_code == 200, seeded.text
    entries = seeded.json()["entries"]
    assert len(entries) == 14
    assert {row["key"] for row in entries} == {
        "trademark_filing",
        "examination",
        "opposition",
        "evidence",
        "hearing",
        "order",
        "appeal",
        "renewal",
        "assignment",
        "licence",
        "correspondence",
        "search",
        "watch",
        "invoice",
    }
    assert all(row["is_seeded"] and row["version"] == 1 for row in entries)

    idempotent = client.post("/api/ip/document-taxonomy/seed", headers=first_headers)
    assert idempotent.status_code == 200
    assert len(idempotent.json()["entries"]) == 14

    with get_session_factory()() as session:
        missing = session.scalar(
            select(IpDocumentTaxonomyEntry).where(
                IpDocumentTaxonomyEntry.company_id == first_company_id,
                IpDocumentTaxonomyEntry.key == "invoice",
            )
        )
        assert missing is not None
        session.delete(missing)
        session.commit()
    partial_reseed = client.post("/api/ip/document-taxonomy/seed", headers=first_headers)
    assert partial_reseed.status_code == 200
    assert len(partial_reseed.json()["entries"]) == 14

    updated = client.put(
        "/api/ip/document-taxonomy/examination",
        headers=first_headers,
        json={
            "expected_version": 1,
            "label": "Examination response",
            "description": "Tenant-controlled examination documents.",
            "sort_order": 12,
            "is_active": True,
            "aliases": ["Exam report", "FER"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert {alias["normalized_alias"] for alias in updated.json()["aliases"]} == {
        "examination response",
        "exam report",
        "fer",
    }

    stale = client.put(
        "/api/ip/document-taxonomy/examination",
        headers=first_headers,
        json={
            "expected_version": 1,
            "label": "Stale overwrite",
            "aliases": [],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ip_document_taxonomy_version_conflict"

    alias_collision = client.put(
        "/api/ip/document-taxonomy/custom_exam",
        headers=first_headers,
        json={"label": "Custom exam", "aliases": ["FER"]},
    )
    assert alias_collision.status_code == 409
    assert alias_collision.json()["code"] == "ip_document_taxonomy_alias_conflict"

    nonexistent_expected_version = client.put(
        "/api/ip/document-taxonomy/new_with_stale_version",
        headers=first_headers,
        json={"expected_version": 1, "label": "Not created", "aliases": []},
    )
    assert nonexistent_expected_version.status_code == 409

    invalid_alias = client.put(
        "/api/ip/document-taxonomy/invalid_alias",
        headers=first_headers,
        json={"label": "***", "aliases": []},
    )
    assert invalid_alias.status_code == 422

    second = _bootstrap_tenant(
        client,
        slug="ip-doc-foundation-b",
        email="ip-doc-foundation-b@example.com",
    )
    second_headers = auth_headers(str(second["access_token"]))
    isolated = client.get("/api/ip/document-taxonomy", headers=second_headers)
    assert isolated.status_code == 200
    assert isolated.json()["entries"] == []

    with get_session_factory()() as session:
        first_entries = list(
            session.scalars(
                select(IpDocumentTaxonomyEntry).where(
                    IpDocumentTaxonomyEntry.company_id == first_company_id
                )
            ).all()
        )
        first_aliases = list(
            session.scalars(
                select(IpDocumentTaxonomyAlias).where(
                    IpDocumentTaxonomyAlias.company_id == first_company_id
                )
            ).all()
        )
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.company_id == first_company_id)
            ).all()
        )
    assert len(first_entries) == 14
    assert len(first_aliases) == 16
    assert {
        "ip_document_taxonomy.seeded",
        "ip_document_taxonomy.updated",
    }.issubset(actions)


def test_taxonomy_contract_rejects_invalid_key_and_unauthenticated_access(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    invalid_key = client.put(
        "/api/ip/document-taxonomy/Unsafe Key!",
        headers=headers,
        json={"label": "Unsafe entry", "aliases": []},
    )
    assert invalid_key.status_code == 422

    client.cookies.clear()
    assert client.get("/api/ip/document-taxonomy").status_code == 401
    assert client.post("/api/ip/document-taxonomy/seed").status_code in {401, 403}
    assert client.post(
        "/api/ip/documents/naming-preview",
        json={"document_type": "Order", "version": 1},
    ).status_code in {401, 403}


def test_taxonomy_schema_and_naming_edge_contracts() -> None:
    with pytest.raises(ValidationError, match="label cannot be blank"):
        IpDocumentTaxonomyUpsertRequest(label="  ")
    with pytest.raises(ValidationError, match="blank values"):
        IpDocumentTaxonomyUpsertRequest(label="Valid", aliases=["  "])
    with pytest.raises(ValidationError, match="duplicates"):
        IpDocumentTaxonomyUpsertRequest(label="Valid", aliases=["FER", "fer"])
    with pytest.raises(ValidationError, match="existing_names cannot contain blank"):
        IpDocumentNamingPreviewRequest(version=1, existing_names=[" "])

    empty = preview_ip_document_name(IpDocumentNamingPreviewRequest(version=1))
    assert empty.requested_name == "1"
    assert "client_code" in empty.omitted_components

    reserved_and_long = preview_ip_document_name(
        IpDocumentNamingPreviewRequest(
            client_code="CON",
            mark="x" * 160,
            document_type="y" * 160,
            version=1,
            extension=".<>",
        )
    )
    assert reserved_and_long.resolved_name.startswith("_CON_")
    assert len(reserved_and_long.resolved_name) <= 240
    assert any("truncated" in warning for warning in reserved_and_long.warnings)
    assert any("extension" in warning for warning in reserved_and_long.warnings)

    omitted_unsafe = preview_ip_document_name(
        IpDocumentNamingPreviewRequest(mark="***", version=1)
    )
    assert "mark" in omitted_unsafe.omitted_components
    assert any("no filename-safe" in warning for warning in omitted_unsafe.warnings)


def test_taxonomy_admin_capability_is_required_for_mutation(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = "member"
        session.add(membership)
        session.commit()

    readable = client.get("/api/ip/document-taxonomy", headers=headers)
    assert readable.status_code == 200
    forbidden = client.post("/api/ip/document-taxonomy/seed", headers=headers)
    assert forbidden.status_code == 403


def test_document_version_and_typed_link_constraints_fail_closed(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200

    with get_session_factory()() as session:
        taxonomy = session.scalar(
            select(IpDocumentTaxonomyEntry).where(
                IpDocumentTaxonomyEntry.company_id == company_id,
                IpDocumentTaxonomyEntry.key == "evidence",
            )
        )
        assert taxonomy is not None
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Typed link fixture",
            status="draft",
            created_by_membership_id=membership_id,
        )
        document = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Evidence affidavit",
            created_by_membership_id=membership_id,
        )
        session.add_all([docket, document])
        session.flush()
        version = IpDocumentVersion(
            company_id=company_id,
            document_id=document.id,
            version=1,
            original_filename="evidence.pdf",
            display_name="ACME_Trademark_Evidence_1.pdf",
            storage_key=f"ip/{company_id}/{document.id}/1",
            content_type="application/pdf",
            size_bytes=128,
            sha256_hex="a" * 64,
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
                target_id=docket.id,
                docket_id=docket.id,
                created_by_membership_id=membership_id,
            )
        )
        session.commit()

        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(
                    IpDocumentLink(
                        company_id=company_id,
                        document_id=document.id,
                        target_type="application",
                        target_id=docket.id,
                        docket_id=docket.id,
                        created_by_membership_id=membership_id,
                    )
                )
                session.flush()

        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(
                    IpDocumentVersion(
                        company_id=company_id,
                        document_id=document.id,
                        version=2,
                        original_filename="bad.pdf",
                        display_name="bad.pdf",
                        storage_key=f"ip/{company_id}/{document.id}/2",
                        size_bytes=1,
                        sha256_hex="short",
                        state="approved",
                        uploaded_by_membership_id=membership_id,
                    )
                )
                session.flush()
