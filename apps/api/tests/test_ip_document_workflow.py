from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import CompanyMembership, IpDocketRecord, IpDocumentVersion
from caseops_api.db.session import get_session_factory
from caseops_api.services.document_storage import resolve_storage_path
from tests.test_auth_company import auth_headers, bootstrap_company


def _seed_and_dockets(client: TestClient) -> tuple[dict, dict[str, str], list[str]]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200
    with get_session_factory()() as session:
        dockets = [
            IpDocketRecord(
                company_id=str(bootstrap["company"]["id"]),
                record_type="trademark",
                title=f"Document workflow fixture {index}",
                status="draft",
                created_by_membership_id=str(bootstrap["membership"]["id"]),
            )
            for index in range(2)
        ]
        session.add_all(dockets)
        session.commit()
        return bootstrap, headers, [row.id for row in dockets]


def _upload(
    client: TestClient,
    headers: dict[str, str],
    *,
    filename: str,
    content: bytes,
    docket_id: str,
    taxonomy_key: str = "evidence",
    confidentiality: str = "internal",
    is_privileged: bool = False,
    client_code: str = "ACME",
) -> dict:
    response = client.post(
        "/api/ip/documents/upload",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "taxonomy_key": taxonomy_key,
                    "title": "Evidence affidavit",
                    "confidentiality": confidentiality,
                    "is_privileged": is_privileged,
                    "client_code": client_code,
                    "asset_type": "Trademark",
                    "mark": "ASTER",
                    "jurisdiction": "IN",
                    "application_no": "12345",
                    "document_date": "2026-08-09",
                    "links": [{"target_type": "docket", "target_id": docket_id}],
                }
            )
        },
        files={"upload": (filename, content, "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ip_document_end_to_end_version_processing_and_approval_lock(
    client: TestClient,
) -> None:
    bootstrap, headers, dockets = _seed_and_dockets(client)
    original = b"Evidence affidavit with enough searchable words and facts. " * 20
    created = _upload(
        client,
        headers,
        filename="=unsafe original name.txt",
        content=original,
        docket_id=dockets[0],
    )
    assert created["outcome"] == "created"
    document = created["document"]
    assert document["current_version"] == 1
    assert document["links"][0]["target_id"] == dockets[0]
    first = document["versions"][0]
    assert first["original_filename"] == "=unsafe original name.txt"
    assert first["display_name"] == "ACME_Trademark_ASTER_IN_12345_evidence_2026-08-09_1.txt"

    refreshed = client.get(f"/api/ip/documents/{document['id']}", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    first = refreshed.json()["versions"][0]
    assert first["processing_status"] == "indexed"
    assert first["ocr_quality_score"] is not None
    assert first["ocr_quality_score"] >= 0.65
    assert first["ai_eligible"] is True

    download = client.get(
        f"/api/ip/documents/{document['id']}/versions/1/download", headers=headers
    )
    assert download.status_code == 200
    assert download.content == original
    assert "unsafe%20original%20name.txt" in download.headers["content-disposition"]

    review = client.post(
        f"/api/ip/documents/{document['id']}/versions/1/transition",
        headers=headers,
        json={
            "expected_current_version": 1,
            "expected_state": "draft",
            "target_state": "review",
        },
    )
    assert review.status_code == 200, review.text

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert membership is not None
        membership.role = "member"
        session.commit()
    forbidden = client.post(
        f"/api/ip/documents/{document['id']}/versions/1/transition",
        headers=headers,
        json={
            "expected_current_version": 1,
            "expected_state": "review",
            "target_state": "approved",
        },
    )
    assert forbidden.status_code == 403

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert membership is not None
        membership.role = "owner"
        session.commit()
    approved = client.post(
        f"/api/ip/documents/{document['id']}/versions/1/transition",
        headers=headers,
        json={
            "expected_current_version": 1,
            "expected_state": "review",
            "target_state": "approved",
        },
    )
    assert approved.status_code == 200, approved.text
    approved_version = approved.json()["versions"][0]
    assert approved_version["state"] == "approved"
    assert approved_version["locked_by_membership_id"] == str(bootstrap["membership"]["id"])
    assert approved_version["locked_at"] is not None

    stale = client.post(
        f"/api/ip/documents/{document['id']}/versions/1/transition",
        headers=headers,
        json={
            "expected_current_version": 1,
            "expected_state": "review",
            "target_state": "filed",
        },
    )
    assert stale.status_code == 409

    second_content = b"A replacement version with revised evidence and annexures. " * 20
    new_version = client.post(
        f"/api/ip/documents/{document['id']}/new-version",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "expected_current_version": 1,
                    "client_code": "ACME",
                    "asset_type": "Trademark",
                    "mark": "ASTER",
                    "jurisdiction": "IN",
                    "application_no": "12345",
                    "document_date": "2026-08-09",
                }
            )
        },
        files={"upload": ("revised evidence.txt", second_content, "text/plain")},
    )
    assert new_version.status_code == 200, new_version.text
    versioned = new_version.json()["document"]
    assert versioned["current_version"] == 2
    assert [row["state"] for row in versioned["versions"]] == ["draft", "superseded"]
    assert [row["original_filename"] for row in versioned["versions"]] == [
        "revised evidence.txt",
        "=unsafe original name.txt",
    ]
    stale_version_transition = client.post(
        f"/api/ip/documents/{document['id']}/versions/1/transition",
        headers=headers,
        json={
            "expected_current_version": 1,
            "expected_state": "superseded",
            "target_state": "draft",
        },
    )
    assert stale_version_transition.status_code == 409
    with get_session_factory()() as session:
        original_version = session.scalar(
            select(IpDocumentVersion).where(
                IpDocumentVersion.document_id == document["id"],
                IpDocumentVersion.version == 1,
            )
        )
        assert original_version is not None
        resolve_storage_path(original_version.storage_key).unlink()
    missing_object = client.get(
        f"/api/ip/documents/{document['id']}/versions/1/download",
        headers=headers,
    )
    assert missing_object.status_code == 404
    assert missing_object.json()["detail"] == "Document file is no longer available."


def test_duplicate_detection_uses_content_and_reuses_one_document_across_links(
    client: TestClient,
) -> None:
    bootstrap, headers, dockets = _seed_and_dockets(client)
    shared = b"A content hash duplicate must be offered for reuse. " * 15
    first = _upload(
        client,
        headers,
        filename="first-name.txt",
        content=shared,
        docket_id=dockets[0],
    )
    document = first["document"]

    same_name_new_bytes = _upload(
        client,
        headers,
        filename="first-name.txt",
        content=b"The filename is the same but these bytes are different. " * 15,
        docket_id=dockets[1],
    )
    assert same_name_new_bytes["outcome"] == "created"

    duplicate = _upload(
        client,
        headers,
        filename="completely-different-name.txt",
        content=shared,
        docket_id=dockets[1],
    )
    assert duplicate["outcome"] == "duplicate_found"
    assert duplicate["document"] is None
    assert duplicate["duplicate_candidates"][0]["document_id"] == document["id"]
    assert duplicate["duplicate_candidates"][0]["reuse_action"] == "link_existing_document"

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert membership is not None
        membership.role = "paralegal"
        session.commit()
    forbidden_link = client.post(
        f"/api/ip/documents/{document['id']}/links",
        headers=headers,
        json={
            "expected_current_version": 1,
            "links": [{"target_type": "docket", "target_id": dockets[1]}],
        },
    )
    assert forbidden_link.status_code == 403
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert membership is not None
        membership.role = "owner"
        session.commit()
    linked = client.post(
        f"/api/ip/documents/{document['id']}/links",
        headers=headers,
        json={
            "expected_current_version": 1,
            "links": [{"target_type": "docket", "target_id": dockets[1]}],
        },
    )
    assert linked.status_code == 200, linked.text
    assert len(linked.json()["links"]) == 2
    assert len(linked.json()["versions"]) == 1

    cross_taxonomy_bytes = b"The same bytes have different legal classification metadata. " * 15
    classified_elsewhere = _upload(
        client,
        headers,
        filename="filing-copy.txt",
        content=cross_taxonomy_bytes,
        docket_id=dockets[1],
        taxonomy_key="trademark_filing",
    )
    assert classified_elsewhere["outcome"] == "created"
    replacement = client.post(
        f"/api/ip/documents/{document['id']}/new-version",
        headers=headers,
        data={
            "metadata_json": json.dumps(
                {
                    "expected_current_version": 1,
                    "client_code": "ACME",
                    "asset_type": "Trademark",
                    "document_date": "2026-08-09",
                }
            )
        },
        files={"upload": ("replacement.txt", cross_taxonomy_bytes, "text/plain")},
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["outcome"] == "created"
    assert replacement.json()["document"]["current_version"] == 2


def test_bulk_preview_is_required_and_conflicts_receive_deterministic_suffix(
    client: TestClient,
) -> None:
    _, headers, dockets = _seed_and_dockets(client)
    first = _upload(
        client,
        headers,
        filename="one.txt",
        content=b"First distinct bulk document. " * 20,
        docket_id=dockets[0],
    )["document"]
    second = _upload(
        client,
        headers,
        filename="two.txt",
        content=b"Second distinct bulk document. " * 20,
        docket_id=dockets[1],
    )["document"]
    items = [
        {
            "document_id": row["id"],
            "expected_current_version": 1,
            "expected_taxonomy_key": "evidence",
            "taxonomy_key": "correspondence",
            "naming": {
                "client_code": "ACME",
                "document_type": "Correspondence",
                "version": 1,
                "extension": "txt",
            },
        }
        for row in (first, second)
    ]
    preview = client.post("/api/ip/documents/bulk-preview", headers=headers, json={"items": items})
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["conflict_count"] == 1
    names = [row["proposed_display_name"] for row in preview_body["items"]]
    assert len({name.casefold() for name in names}) == 2
    assert any(name.endswith("_2.txt") for name in names)

    stale = client.post(
        "/api/ip/documents/bulk-apply",
        headers=headers,
        json={"items": items, "preview_token": "0" * 64},
    )
    assert stale.status_code == 409
    applied = client.post(
        "/api/ip/documents/bulk-apply",
        headers=headers,
        json={"items": items, "preview_token": preview_body["preview_token"]},
    )
    assert applied.status_code == 200, applied.text
    changed = {row["id"]: row for row in applied.json()["items"]}
    assert changed[first["id"]]["taxonomy_key"] == "correspondence"
    assert changed[second["id"]]["taxonomy_key"] == "correspondence"
    assert all(
        "_correspondence_" in row["versions"][0]["display_name"].casefold()
        for row in changed.values()
    )


def test_policy_fails_closed_for_privilege_confidentiality_and_low_ocr(
    client: TestClient,
) -> None:
    _, headers, dockets = _seed_and_dockets(client)
    privileged = _upload(
        client,
        headers,
        filename="privileged.txt",
        content=b"Privileged legal advice. " * 30,
        docket_id=dockets[0],
        confidentiality="restricted",
        is_privileged=True,
    )["document"]
    policy = client.get(f"/api/ip/documents/{privileged['id']}/policy", headers=headers)
    assert policy.status_code == 200
    assert policy.json()["ai_retrieval_allowed"] is False
    assert policy.json()["portal_share_allowed"] is False
    assert policy.json()["export_allowed"] is False
    assert policy.json()["notification_content_allowed"] is False
    denied = client.post(
        f"/api/ip/documents/{privileged['id']}/authorize-action",
        headers=headers,
        json={"action": "portal_share"},
    )
    assert denied.status_code == 403

    low_quality = _upload(
        client,
        headers,
        filename="sparse.txt",
        content=b"x",
        docket_id=dockets[1],
    )["document"]
    policy = client.get(f"/api/ip/documents/{low_quality['id']}/policy", headers=headers)
    assert policy.status_code == 200
    assert policy.json()["ai_retrieval_allowed"] is False
    assert policy.json()["portal_share_allowed"] is True
    assert any("quality" in reason.lower() for reason in policy.json()["reasons"])


def test_law_firm_alias_import_and_tenant_isolation(client: TestClient) -> None:
    first, headers, dockets = _seed_and_dockets(client)
    preview = client.post(
        "/api/ip/document-taxonomy/import-aliases",
        headers=headers,
        json={
            "dry_run": True,
            "entries": [{"taxonomy_key": "evidence", "aliases": ["Affidavit Evidence"]}],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["imported_count"] == 1
    imported = client.post(
        "/api/ip/document-taxonomy/import-aliases",
        headers=headers,
        json={
            "dry_run": False,
            "entries": [{"taxonomy_key": "evidence", "aliases": ["Affidavit Evidence"]}],
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported_count"] == 1

    created = _upload(
        client,
        headers,
        filename="tenant-one.txt",
        content=b"Tenant one document. " * 30,
        docket_id=dockets[0],
    )["document"]
    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second IP Firm",
            "company_slug": "second-ip-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "second-ip-owner@example.com",
            "owner_password": "FixturePass123!",
        },
    )
    assert second.status_code == 200, second.text
    second_headers = auth_headers(str(second.json()["access_token"]))
    assert (
        client.get(f"/api/ip/documents/{created['id']}", headers=second_headers).status_code == 404
    )
    listing = client.get("/api/ip/documents", headers=second_headers)
    assert listing.status_code == 200
    assert listing.json() == {"items": [], "total": 0}

    with get_session_factory()() as session:
        version = session.scalar(
            select(IpDocumentVersion).where(IpDocumentVersion.document_id == created["id"])
        )
        assert version is not None
        assert version.original_filename == "tenant-one.txt"
        assert version.sha256_hex != "0" * 64
        assert version.company_id == str(first["company"]["id"])
