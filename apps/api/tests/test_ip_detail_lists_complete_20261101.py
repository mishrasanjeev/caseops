"""Per-record IP detail lists return every row, not the first 100.

The docket document list reported ``total`` as the length of a 100-row read,
the foreign-associate instruction workspace picked its selected documents out
of that read, and the Madrid record workspace showed at most 100 designations
of one international registration. Each fixture here holds more than 100 rows
with the row that matters sorted last.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_059a_foreign_associate_foundation import (
    _create_payload,
    _foundation_records,
    _matter_and_docket,
)
from tests.test_ip_international import _designation_payload, _registration_payload
from tests.test_ip_record_workflow import _application, _asset, _docket

EXTRA_DOCUMENTS = 101
DESIGNATIONS = 101


def _other_tenant_headers(client: TestClient) -> dict[str, str]:
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Detail Firm",
            "company_slug": "other-detail-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-detail.example",
            "owner_password": "OtherDetail123!",
        },
    )
    assert other.status_code == 200, other.text
    return auth_headers(str(other.json()["access_token"]))


def _link_extra_documents(*, company_id: str, membership_id: str, docket_id: str) -> None:
    with get_session_factory()() as session:
        taxonomy = session.scalar(
            select(IpDocumentTaxonomyEntry).where(
                IpDocumentTaxonomyEntry.company_id == company_id,
                IpDocumentTaxonomyEntry.key == "evidence",
            )
        )
        assert taxonomy is not None
        for index in range(EXTRA_DOCUMENTS):
            document = IpDocument(
                company_id=company_id,
                taxonomy_entry_id=taxonomy.id,
                title=f"ASTER bulk evidence {index:03d}",
                created_by_membership_id=membership_id,
            )
            session.add(document)
            session.flush()
            version = IpDocumentVersion(
                company_id=company_id,
                document_id=document.id,
                version=1,
                original_filename=f"bulk-{index:03d}.pdf",
                display_name=f"ASTER_bulk_{index:03d}.pdf",
                storage_key=f"ip/{company_id}/{document.id}/1",
                content_type="application/pdf",
                size_bytes=256,
                sha256_hex=f"{index:064x}",
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


def _age_document(document_id: str) -> None:
    with get_session_factory()() as session:
        document = session.get(IpDocument, document_id)
        assert document is not None
        document.updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        session.commit()


def test_docket_documents_and_instruction_workspace_keep_documents_past_100(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter, docket = _matter_and_docket(
        client, headers=headers, company_id=company_id, membership_id=membership_id
    )
    records = _foundation_records(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        matter=matter,
        docket_id=docket["id"],
    )
    _link_extra_documents(
        company_id=company_id, membership_id=membership_id, docket_id=docket["id"]
    )
    # The selected filing document is the oldest change, so it sorts last.
    _age_document(records["filing_document_id"])
    total = EXTRA_DOCUMENTS + 2

    listed = client.get("/api/ip/documents", headers=headers, params={"docket_id": docket["id"]})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    ids = [item["id"] for item in body["items"]]
    assert body["total"] == len(ids) == len(set(ids)) == total
    assert ids[-1] == records["filing_document_id"]

    created = client.post(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        json=_create_payload(
            docket_id=docket["id"],
            membership_id=membership_id,
            records=records,
            thread="ASTER-US-FULL-LIST",
        ),
    )
    assert created.status_code == 201, created.text
    workspace = client.get(
        f"/api/ip/foreign-associate-instructions/{created.json()['id']}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    assert {document["id"] for document in workspace.json()["documents"]} == {
        records["filing_document_id"],
        records["privileged_document_id"],
    }

    other = _other_tenant_headers(client)
    foreign = client.get("/api/ip/documents", headers=other, params={"docket_id": docket["id"]})
    # Another tenant naming this docket sees nothing of it.
    assert foreign.status_code == 200, foreign.text
    assert foreign.json() == {"items": [], "total": 0}


def test_madrid_workspace_lists_every_designation_of_a_registration(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    basic_docket = _docket(client, headers, "ASTER BASIC MARK")
    asset = _asset(client, headers, basic_docket["id"], "ASTER")
    application = _application(client, headers, basic_docket["id"], asset["id"])
    registration = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_registration_payload(basic_application_id=application["id"]),
    )
    assert registration.status_code == 201, registration.text
    registration_id = registration.json()["id"]
    designation_ids: list[str] = []
    for index in range(DESIGNATIONS):
        created = client.post(
            "/api/ip/international-registrations",
            headers=headers,
            json=_designation_payload(
                parent_registration_id=registration_id,
                member_code=f"T{index:03d}",
                national_status="protected",
            ),
        )
        assert created.status_code == 201, created.text
        designation_ids.append(created.json()["id"])

    workspace = client.get(
        f"/api/ip/international-registrations/{registration_id}/workspace", headers=headers
    )
    assert workspace.status_code == 200, workspace.text
    listed = [row["id"] for row in workspace.json()["designations"]]
    assert len(listed) == len(set(listed)) == DESIGNATIONS
    assert set(listed) == set(designation_ids)

    other = _other_tenant_headers(client)
    foreign = client.get(
        f"/api/ip/international-registrations/{registration_id}/workspace", headers=other
    )
    assert foreign.status_code == 404, foreign.text
