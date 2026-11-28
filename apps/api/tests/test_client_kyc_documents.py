"""BUG-003 (Nov 27 2026, Ram, test-legal): KYC documents are real uploads.

Tester's report: the KYC form only asked for document names or numbers, so the
admin could not check the documents the client submitted. These tests pin the
fixed contract on every path that writes a KYC submission or decision:

- firm users upload PAN / masked Aadhaar / passport / address proof / other
  files, list them, open them inline and download them (audited);
- submit (internal, matter verification PATCH, client portal) is refused until
  the uploaded files meet the KYC requirements; approval names every current
  file it reviewed and is refused when the pack changed;
- type, label, extension, content type, magic bytes, size and malware are
  validated with the Matter-upload primitives;
- tenant, client and role isolation; portal users see only their own files;
- full Aadhaar numbers are refused in text fields and masked on read;
- KYC bytes count toward the workspace storage quota.

Review round 2 adds:

- the server refuses an approval (internal verify, matter verification PATCH)
  or a rejection naming a file this reviewer has not opened since it was
  uploaded; the browser tick is not the control;
- no writer can move a pack under review (which freezes uploads) without the
  required files;
- a full Aadhaar number is masked in stored / returned / downloaded file
  names and refused in the rejection reason on every reject path.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from caseops_api.db.models import (
    AuditEvent,
    Client,
    ClientKycDocument,
    ClientKycStatus,
    CompanyMembership,
    MembershipRole,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.aadhaar_privacy import verhoeff_valid
from caseops_api.services.document_storage import resolve_storage_path
from tests.kyc_test_support import (
    JPEG_BYTES,
    PDF_BYTES,
    PNG_BYTES,
    open_kyc_documents,
    portal_upload_complete_kyc_pack,
    portal_upload_kyc_document,
    upload_complete_kyc_pack,
    upload_kyc_document,
)
from tests.test_auth_company import auth_headers
from tests.test_portal_matters import (
    _invite_client_portal_user,
    _portal_csrf_headers,
    _seed_client_and_link,
    _seed_matter,
    _verify_and_session,
)


def _owner(client: TestClient, slug: str) -> dict:
    client.cookies.clear()
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug} Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "FoundersPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return resp.json()


def _client(client: TestClient, token: str, name: str = "Ram Kumar") -> str:
    resp = client.post(
        "/api/clients/",
        headers=auth_headers(token),
        json={"name": name, "client_type": "individual"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _full_aadhaar() -> str:
    stem = "23412341234"
    for digit in "0123456789":
        if verhoeff_valid(stem + digit):
            return stem + digit
    raise AssertionError("no Verhoeff digit")


def _audit(action: str, target_id: str) -> list[AuditEvent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.action == action, AuditEvent.target_id == target_id)
                .order_by(AuditEvent.created_at)
            )
        )


def _meta(event: AuditEvent) -> dict:
    raw = event.metadata_json
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


def _member(
    client: TestClient, owner_token: str, slug: str, role: str = "admin",
) -> tuple[str, str]:
    """A second firm user in the same workspace: (membership id, token)."""
    email = f"{role}-reviewer@{slug}.example"
    resp = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={"full_name": "Second Reviewer", "email": email, "role": role,
              "password": "MemberPass123!"},
    )
    assert resp.status_code == 200, resp.text
    login = client.post(
        "/api/auth/login",
        json={"company_slug": slug, "email": email, "password": "MemberPass123!"},
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return str(resp.json()["membership_id"]), str(login.json()["access_token"])


def _submitted_pack(client: TestClient, slug: str) -> tuple[dict, str, str, list[str]]:
    boot = _owner(client, slug)
    token = boot["access_token"]
    cid = _client(client, token)
    ids = upload_complete_kyc_pack(client, token, cid)
    submitted = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={},
    )
    assert submitted.status_code == 200, submitted.text
    return boot, token, cid, ids


def _assert_unreviewed(cid: str, status: str = "submitted") -> None:
    with get_session_factory()() as session:
        assert session.get(Client, cid).kyc_status == status
        assert all(
            doc.review_decision is None
            for doc in session.scalars(
                select(ClientKycDocument).where(ClientKycDocument.client_id == cid)
            )
        )


def _set_role(membership_id: str, role: str) -> None:
    with get_session_factory()() as session:
        session.execute(
            update(CompanyMembership)
            .where(CompanyMembership.id == membership_id)
            .values(role=MembershipRole(role))
        )
        session.commit()


# ---------------------------------------------------------------------------
# The tester's journey, end to end through HTTP
# ---------------------------------------------------------------------------


def test_bug003_upload_resubmit_open_each_document_then_approve(client: TestClient) -> None:
    boot = _owner(client, "kyc-journey")
    token = boot["access_token"]
    cid = _client(client, token)

    # Rejected pack (the tester's starting point: "Re-submit verification").
    pan = upload_kyc_document(client, token, cid, document_type="pan")
    assert pan.status_code == 201, pan.text
    aadhaar = upload_kyc_document(
        client, token, cid, document_type="aadhaar_masked",
        filename="aadhaar-masked.png", content=PNG_BYTES, content_type="image/png",
    )
    assert aadhaar.status_code == 201, aadhaar.text
    assert aadhaar.json()["document_type"] == "aadhaar_masked"
    assert aadhaar.json()["previewable"] is True
    assert "storage_key" not in aadhaar.text and "sha256" not in aadhaar.text

    listing = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token))
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert [d["document_type"] for d in body["documents"]] == ["pan", "aadhaar_masked"]
    assert body["requirements_met"] is True
    assert all(r["satisfied"] for r in body["requirements"])
    assert body["upload_allowed"] is True
    assert body["accepted_extensions"] == [".pdf", ".png", ".jpg", ".jpeg"]
    assert {o["value"] for o in body["document_types"]} == {
        "pan", "aadhaar_masked", "passport", "address_proof", "other",
    }

    submitted = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={"documents": []},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["kyc_status"] == "submitted"

    # Reviewer opens each document inline and gets the uploaded bytes back.
    ids = [d["id"] for d in body["documents"]]
    for doc_id, expected, media in (
        (ids[0], PDF_BYTES, "application/pdf"),
        (ids[1], PNG_BYTES, "image/png"),
    ):
        opened = client.get(
            f"/api/clients/{cid}/kyc/documents/{doc_id}/download?inline=true",
            headers=auth_headers(token),
        )
        assert opened.status_code == 200, opened.text
        assert opened.content == expected
        assert opened.headers["content-type"].startswith(media)
        assert opened.headers["content-disposition"].startswith("inline")
        assert opened.headers["cache-control"].startswith("private, no-store")
        assert opened.headers["x-content-type-options"] == "nosniff"
        # A direct navigation to the file is a sandboxed, unframeable document.
        assert opened.headers["content-security-policy"] == (
            "default-src 'none'; frame-ancestors 'none'; sandbox"
        )
        downloaded = client.get(
            f"/api/clients/{cid}/kyc/documents/{doc_id}/download",
            headers=auth_headers(token),
        )
        assert downloaded.status_code == 200
        assert downloaded.headers["content-disposition"].startswith("attachment")

    approved = client.post(
        f"/api/clients/{cid}/kyc/verify",
        headers=auth_headers(token),
        json={"reviewed_document_ids": ids},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["kyc_status"] == "verified"

    after = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token)).json()
    assert {d["review_decision"] for d in after["documents"]} == {"approved"}
    assert all(d["reviewed_by_membership_id"] for d in after["documents"])
    assert after["upload_allowed"] is False

    assert len(_audit("client.kyc_document_uploaded", cid)) == 2
    assert len(_audit("client.kyc_document_viewed", cid)) == 2
    assert len(_audit("client.kyc_document_downloaded", cid)) == 2
    verified = _audit("client.kyc_verified", cid)
    assert len(verified) == 1
    assert _meta(verified[0])["reviewed_document_ids"] == ids
    assert [d["document_type"] for d in _meta(verified[0])["reviewed_documents"]] == [
        "pan", "aadhaar_masked",
    ]
    # Audit never carries the filename (it routinely names the person).
    uploads = json.dumps([_meta(e) for e in _audit("client.kyc_document_uploaded", cid)])
    assert "aadhaar-masked.png" not in uploads


def test_submit_and_approve_refused_until_required_documents_are_uploaded(
    client: TestClient,
) -> None:
    token = _owner(client, "kyc-required")["access_token"]
    cid = _client(client, token)

    empty = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token),
        json={"documents": [{"name": "PAN"}, {"name": "Aadhaar"}]},
    )
    assert empty.status_code == 409
    assert "PAN card" in empty.json()["detail"]
    assert "Masked Aadhaar, passport or another address proof" in empty.json()["detail"]

    assert upload_kyc_document(client, token, cid, document_type="pan").status_code == 201
    only_pan = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={"documents": []},
    )
    assert only_pan.status_code == 409
    assert "PAN card" not in only_pan.json()["detail"]
    listing = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token))
    assert listing.json()["requirements_met"] is False

    # A passport satisfies the identity / address proof requirement too.
    passport = upload_kyc_document(
        client, token, cid, document_type="passport",
        filename="passport.jpg", content=JPEG_BYTES, content_type="image/jpeg",
    )
    assert passport.status_code == 201, passport.text
    ok = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={"documents": []},
    )
    assert ok.status_code == 200, ok.text
    with get_session_factory()() as session:
        assert session.get(Client, cid).kyc_status == "submitted"


def test_approval_must_name_every_current_document_and_refuses_a_changed_pack(
    client: TestClient,
) -> None:
    token = _owner(client, "kyc-review")["access_token"]
    cid = _client(client, token)
    ids = upload_complete_kyc_pack(client, token, cid)
    assert client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={},
    ).status_code == 200

    missing_body = client.post(f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token))
    assert missing_body.status_code == 422
    partial = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": ids[:1]},
    )
    assert partial.status_code == 409
    duplicate = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": [ids[0], ids[0], ids[1]]},
    )
    assert duplicate.status_code == 422
    # A file added while the pack waits for review is not approved blind.
    late = upload_kyc_document(
        client, token, cid, document_type="other", label="Board resolution",
    )
    assert late.status_code == 201, late.text
    stale = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": ids},
    )
    assert stale.status_code == 409
    assert "changed" in stale.json()["detail"]
    foreign = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": [*ids, late.json()["id"], "not-a-current-document"]},
    )
    assert foreign.status_code == 409
    with get_session_factory()() as session:
        assert session.get(Client, cid).kyc_status == "submitted"
        assert all(
            doc.review_decision is None
            for doc in session.scalars(select(ClientKycDocument))
        )

    open_kyc_documents(client, token, cid, [*ids, late.json()["id"]])
    ok = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": [*ids, late.json()["id"]]},
    )
    assert ok.status_code == 200, ok.text


def test_reject_records_reviewed_documents_then_resubmit_with_replacement(
    client: TestClient,
) -> None:
    token = _owner(client, "kyc-reject")["access_token"]
    cid = _client(client, token)
    pan_id, aadhaar_id = upload_complete_kyc_pack(client, token, cid)
    client.post(f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={})
    open_kyc_documents(client, token, cid, [aadhaar_id])

    rejected = client.post(
        f"/api/clients/{cid}/kyc/reject", headers=auth_headers(token),
        json={"reason": "Aadhaar image is unreadable", "reviewed_document_ids": [aadhaar_id]},
    )
    assert rejected.status_code == 200, rejected.text
    event = _audit("client.kyc_rejected", cid)[0]
    assert _meta(event)["reviewed_document_ids"] == [aadhaar_id]

    with get_session_factory()() as session:
        reviewed = session.get(ClientKycDocument, aadhaar_id)
        assert reviewed.review_decision == "rejected"
        assert session.get(ClientKycDocument, pan_id).review_decision is None
        reviewed_key = reviewed.storage_key
        pan_key = session.get(ClientKycDocument, pan_id).storage_key

    # The reviewed file is decision evidence: removing it retires it.
    removed = client.delete(
        f"/api/clients/{cid}/kyc/documents/{aadhaar_id}", headers=auth_headers(token),
    )
    assert removed.status_code == 204
    with get_session_factory()() as session:
        retired = session.get(ClientKycDocument, aadhaar_id)
        assert retired is not None and retired.retired_at is not None
    assert resolve_storage_path(reviewed_key).exists()
    still_openable = client.get(
        f"/api/clients/{cid}/kyc/documents/{aadhaar_id}/download",
        headers=auth_headers(token),
    )
    assert still_openable.status_code == 200
    listing = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token))
    assert [d["id"] for d in listing.json()["documents"]] == [pan_id]
    assert listing.json()["requirements_met"] is False

    # An unreviewed file is deleted outright, bytes included.
    pan_removed = client.delete(
        f"/api/clients/{cid}/kyc/documents/{pan_id}", headers=auth_headers(token),
    )
    assert pan_removed.status_code == 204
    with get_session_factory()() as session:
        assert session.get(ClientKycDocument, pan_id) is None
    assert not resolve_storage_path(pan_key).exists()
    removed_events = _audit("client.kyc_document_removed", cid)
    assert [_meta(e)["outcome"] for e in removed_events] == ["retired", "deleted"]

    upload_complete_kyc_pack(client, token, cid)
    resubmitted = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["kyc_rejection_reason"] is None


def test_documents_are_frozen_under_review_and_after_verification(client: TestClient) -> None:
    token = _owner(client, "kyc-frozen")["access_token"]
    cid = _client(client, token)
    ids = upload_complete_kyc_pack(client, token, cid)
    client.post(f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={})
    open_kyc_documents(client, token, cid, ids)
    assert client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": ids},
    ).status_code == 200

    upload = upload_kyc_document(client, token, cid, document_type="passport")
    assert upload.status_code == 409
    delete = client.delete(
        f"/api/clients/{cid}/kyc/documents/{ids[0]}", headers=auth_headers(token),
    )
    assert delete.status_code == 409
    with get_session_factory()() as session:
        session.get(Client, cid).kyc_status = "under_review"
        session.commit()
    assert upload_kyc_document(client, token, cid, document_type="passport").status_code == 409


# ---------------------------------------------------------------------------
# Validation (same primitives as Matter uploads)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "file", "status", "detail"),
    [
        ({"document_type": "voter_id"}, ("x.pdf", PDF_BYTES, "application/pdf"), 422, None),
        (
            {"document_type": "other"},
            ("x.pdf", PDF_BYTES, "application/pdf"),
            422,
            "Name the document",
        ),
        (
            {"document_type": "other", "label": "Aadhaar " + "{aadhaar}"},
            ("x.pdf", PDF_BYTES, "application/pdf"),
            422,
            "full Aadhaar",
        ),
        (
            {"document_type": "pan"},
            ("pan.docx", b"PK\x03\x04rest", "application/zip"),
            400,
            "PDF, PNG or JPEG",
        ),
        (
            {"document_type": "pan"},
            ("pan.exe", b"MZ\x90\x00", "application/octet-stream"),
            400,
            "PDF, PNG or JPEG",
        ),
        (
            {"document_type": "pan"},
            ("pan.pdf", b"MZ\x90\x00binary", "application/pdf"),
            400,
            "signature",
        ),
        ({"document_type": "pan"}, ("pan.pdf", PDF_BYTES, "image/png"), 400, "content-type"),
        ({"document_type": "pan"}, ("pan.png", PDF_BYTES, "image/png"), 400, "signature"),
        ({"document_type": "pan"}, ("pan.pdf", b"", "application/pdf"), 400, None),
    ],
    ids=[
        "unknown-type", "other-without-label", "label-with-full-aadhaar", "docx", "exe",
        "pe-renamed-pdf", "content-type-mismatch", "pdf-renamed-png", "empty",
    ],
)
def test_upload_validation_rejects_without_storing(
    client: TestClient, data: dict, file: tuple, status: int, detail: str | None,
) -> None:
    token = _owner(client, "kyc-validate")["access_token"]
    cid = _client(client, token)
    data = {k: v.replace("{aadhaar}", _full_aadhaar()) for k, v in data.items()}
    resp = client.post(
        f"/api/clients/{cid}/kyc/documents",
        headers=auth_headers(token),
        data=data,
        files={"file": file},
    )
    assert resp.status_code == status, resp.text
    if detail:
        assert detail in resp.text
    with get_session_factory()() as session:
        assert session.scalar(select(ClientKycDocument.id)) is None


def test_upload_over_the_size_limit_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.services import client_kyc_documents

    monkeypatch.setattr(client_kyc_documents, "kyc_max_upload_bytes", lambda: 64)
    token = _owner(client, "kyc-size")["access_token"]
    cid = _client(client, token)
    resp = upload_kyc_document(client, token, cid, document_type="pan", content=PDF_BYTES * 4)
    assert resp.status_code == 413, resp.text
    listing = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token))
    assert listing.json()["max_upload_bytes"] == 64
    assert listing.json()["documents"] == []


def test_infected_upload_is_refused_and_leaves_no_object(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from caseops_api.services import virus_scan

    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda path: virus_scan.ScanResult(status="infected", signature="Eicar-Test-Signature"),
    )
    token = _owner(client, "kyc-virus")["access_token"]
    cid = _client(client, token)
    resp = upload_kyc_document(client, token, cid, document_type="pan")
    assert resp.status_code == 400
    assert "virus signature" in resp.json()["detail"]
    with get_session_factory()() as session:
        assert session.scalar(select(ClientKycDocument.id)) is None
    stored = list((tmp_path / "documents").rglob("*.pdf"))
    assert stored == []


def test_kyc_bytes_count_toward_the_storage_quota(client: TestClient) -> None:
    from caseops_api.db.models import Company

    boot = _owner(client, "kyc-quota")
    token = boot["access_token"]
    cid = _client(client, token)
    assert upload_kyc_document(client, token, cid, document_type="pan").status_code == 201
    with get_session_factory()() as session:
        company = session.get(Company, boot["company"]["id"])
        company.storage_quota_bytes = len(PDF_BYTES) + 10
        session.commit()
    resp = upload_kyc_document(client, token, cid, document_type="passport")
    assert resp.status_code == 413, resp.text
    blocked = _audit("storage_quota.upload_blocked", cid)
    assert blocked and _meta(blocked[0])["actor_surface"] == "client_kyc"


# ---------------------------------------------------------------------------
# Isolation and roles
# ---------------------------------------------------------------------------


def test_cross_tenant_and_cross_client_access_is_404(client: TestClient) -> None:
    token_a = _owner(client, "kyc-tenant-a")["access_token"]
    cid_a = _client(client, token_a)
    other_cid_a = _client(client, token_a, name="Another Client")
    doc_id = upload_complete_kyc_pack(client, token_a, cid_a)[0]
    token_b = _owner(client, "kyc-tenant-b")["access_token"]
    cid_b = _client(client, token_b)

    for token, path_cid in ((token_b, cid_a), (token_a, other_cid_a), (token_b, cid_b)):
        download = client.get(
            f"/api/clients/{path_cid}/kyc/documents/{doc_id}/download?inline=true",
            headers=auth_headers(token),
        )
        assert download.status_code == 404, (path_cid, download.text)
        delete = client.delete(
            f"/api/clients/{path_cid}/kyc/documents/{doc_id}", headers=auth_headers(token),
        )
        assert delete.status_code in {404, 409}, delete.text
        assert delete.status_code == 404
    assert client.get(
        f"/api/clients/{cid_a}/kyc/documents", headers=auth_headers(token_b),
    ).status_code == 404
    assert upload_kyc_document(client, token_b, cid_a, document_type="pan").status_code == 404
    with get_session_factory()() as session:
        assert session.get(ClientKycDocument, doc_id) is not None
        assert session.scalar(
            select(ClientKycDocument.id).where(ClientKycDocument.client_id == cid_b)
        ) is None


def test_viewer_cannot_list_open_or_upload_kyc_documents(client: TestClient) -> None:
    boot = _owner(client, "kyc-viewer")
    token = boot["access_token"]
    cid = _client(client, token)
    doc_id = upload_complete_kyc_pack(client, token, cid)[0]
    _set_role(boot["membership"]["id"], "viewer")

    assert client.get(
        f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token),
    ).status_code == 403
    assert client.get(
        f"/api/clients/{cid}/kyc/documents/{doc_id}/download", headers=auth_headers(token),
    ).status_code == 403
    assert upload_kyc_document(client, token, cid, document_type="pan").status_code == 403
    removed = client.delete(
        f"/api/clients/{cid}/kyc/documents/{doc_id}", headers=auth_headers(token),
    )
    assert removed.status_code == 403


def test_paralegal_uploads_and_opens_but_cannot_approve(client: TestClient) -> None:
    boot = _owner(client, "kyc-paralegal")
    token = boot["access_token"]
    cid = _client(client, token)
    _set_role(boot["membership"]["id"], "paralegal")
    ids = upload_complete_kyc_pack(client, token, cid)
    assert client.get(
        f"/api/clients/{cid}/kyc/documents/{ids[0]}/download?inline=true",
        headers=auth_headers(token),
    ).status_code == 200
    client.post(f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={})
    assert client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": ids},
    ).status_code == 403


# ---------------------------------------------------------------------------
# Sibling paths: create / generic update / matter verification PATCH
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_value", ["submitted", "under_review", "verified", "rejected"])
def test_create_and_generic_update_cannot_set_workflow_statuses(
    client: TestClient, status_value: str,
) -> None:
    token = _owner(client, "kyc-generic")["access_token"]
    created = client.post(
        "/api/clients/", headers=auth_headers(token),
        json={"name": "Born Verified", "client_type": "individual", "kyc_status": status_value},
    )
    assert created.status_code == 400, created.text
    cid = _client(client, token)
    patched = client.patch(
        f"/api/clients/{cid}", headers=auth_headers(token), json={"kyc_status": status_value},
    )
    assert patched.status_code in {400, 409}, patched.text
    with get_session_factory()() as session:
        assert session.get(Client, cid).kyc_status == "not_required"


def test_matter_verification_patch_follows_the_same_pack_rules(client: TestClient) -> None:
    from tests.test_clients import _mk_matter

    token = _owner(client, "kyc-matter")["access_token"]
    cid = _client(client, token)
    matter = _mk_matter(client, token, code="KYC-MV-1")
    assert client.post(
        f"/api/matters/{matter['id']}/clients", headers=auth_headers(token),
        json={"client_id": cid},
    ).status_code == 200
    path = f"/api/matters/{matter['id']}/client-verification/{cid}"

    no_files = client.patch(path, headers=auth_headers(token), json={"status": "submitted"})
    assert no_files.status_code == 409
    ids = upload_complete_kyc_pack(client, token, cid)
    assert client.patch(
        path, headers=auth_headers(token), json={"status": "submitted"},
    ).status_code == 200
    unreviewed = client.patch(path, headers=auth_headers(token), json={"status": "verified"})
    assert unreviewed.status_code == 409
    open_kyc_documents(client, token, cid, ids)
    ok = client.patch(
        path, headers=auth_headers(token),
        json={"status": "verified", "reviewed_document_ids": ids},
    )
    assert ok.status_code == 200, ok.text
    event = _audit("client.verification_updated", cid)[-1]
    assert _meta(event)["reviewed_document_ids"] == ids


# ---------------------------------------------------------------------------
# Aadhaar privacy
# ---------------------------------------------------------------------------


def test_full_aadhaar_is_refused_in_text_fields_and_masked_on_read(client: TestClient) -> None:
    full = _full_aadhaar()
    spaced = f"{full[:4]} {full[4:8]} {full[8:]}"
    token = _owner(client, "kyc-aadhaar")["access_token"]
    cid = _client(client, token)

    assert client.post(
        "/api/clients/", headers=auth_headers(token),
        json={"name": "Aadhaar In Pan", "client_type": "individual", "pan": full},
    ).status_code == 422
    assert client.patch(
        f"/api/clients/{cid}", headers=auth_headers(token), json={"gstin": spaced},
    ).status_code == 422
    upload_complete_kyc_pack(client, token, cid)
    typed = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token),
        json={"documents": [{"name": "Aadhaar", "note": f"number {spaced}"}]},
    )
    assert typed.status_code == 422
    assert "full Aadhaar" in typed.text
    # Masked values and ordinary 12-digit numbers that fail the checksum pass.
    not_aadhaar = full[:-1] + str((int(full[-1]) + 1) % 10)
    ok = client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token),
        json={"documents": [{"name": "Aadhaar XXXX XXXX " + full[-4:], "note": not_aadhaar}]},
    )
    assert ok.status_code == 200, ok.text

    # Data written before the guard is masked on every read.
    with get_session_factory()() as session:
        row = session.get(Client, cid)
        row.pan = full
        row.kyc_documents_json = [{"name": "Aadhaar", "note": spaced, "status": "received"}]
        session.commit()
    profile = client.get(f"/api/clients/{cid}", headers=auth_headers(token))
    assert profile.status_code == 200
    assert full not in profile.text and spaced not in profile.text
    assert profile.json()["pan"] == f"XXXX XXXX {full[-4:]}"
    assert profile.json()["kyc_documents"][0]["note"] == f"XXXX XXXX {full[-4:]}"


# ---------------------------------------------------------------------------
# Client portal path
# ---------------------------------------------------------------------------


def test_portal_user_uploads_submits_and_sees_only_own_files(client: TestClient) -> None:
    boot = _owner(client, "kyc-portal")
    token = boot["access_token"]
    company_id = boot["company"]["id"]
    matter_id = _seed_matter(company_id, code="KYC-P1")
    client_id = _seed_client_and_link(company_id, matter_id)
    other_matter = _seed_matter(company_id, code="KYC-P2")
    other_client = _seed_client_and_link(company_id, other_matter)
    firm_doc = upload_kyc_document(
        client, token, client_id, document_type="other", label="Firm engagement letter",
    )
    assert firm_doc.status_code == 201
    _, debug = _invite_client_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    headers = _portal_csrf_headers(client)

    early = client.post(
        f"/api/portal/matters/{matter_id}/kyc",
        json={"client_id": client_id, "documents": []},
        headers=headers,
    )
    assert early.status_code == 409

    pan_id, aadhaar_id = portal_upload_complete_kyc_pack(client, matter_id, client_id, headers)
    listing = client.get(
        f"/api/portal/matters/{matter_id}/kyc/documents?client_id={client_id}",
    )
    assert listing.status_code == 200, listing.text
    assert [d["id"] for d in listing.json()["documents"]] == [pan_id, aadhaar_id]
    assert listing.json()["requirements_met"] is True
    assert all(d["uploaded_by_portal"] for d in listing.json()["documents"])

    own = client.get(
        f"/api/portal/matters/{matter_id}/kyc/documents/{aadhaar_id}/download"
        f"?client_id={client_id}&inline=true",
    )
    assert own.status_code == 200 and own.content == JPEG_BYTES
    assert own.headers["x-content-type-options"] == "nosniff"
    assert own.headers["cache-control"].startswith("private, no-store")
    assert "sandbox" in own.headers["content-security-policy"]
    firm = client.get(
        f"/api/portal/matters/{matter_id}/kyc/documents/{firm_doc.json()['id']}/download"
        f"?client_id={client_id}",
    )
    assert firm.status_code == 404
    cross = portal_upload_kyc_document(
        client, matter_id, other_client, headers, document_type="pan",
    )
    assert cross.status_code == 404
    unlinked_list = client.get(
        f"/api/portal/matters/{other_matter}/kyc/documents?client_id={other_client}",
    )
    assert unlinked_list.status_code == 404
    no_csrf = client.post(
        f"/api/portal/matters/{matter_id}/kyc/documents",
        data={"client_id": client_id, "document_type": "pan"},
        files={"file": ("pan.pdf", PDF_BYTES, "application/pdf")},
    )
    assert no_csrf.status_code == 403

    submitted = client.post(
        f"/api/portal/matters/{matter_id}/kyc",
        json={"client_id": client_id, "documents": []},
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    uploaded = _audit("portal.kyc_document_uploaded", client_id)
    assert len(uploaded) == 2
    assert all(_meta(e)["portal_user_id"] for e in uploaded)
    assert len(_audit("portal.kyc_document_viewed", client_id)) == 1
    submit_event = _audit("portal.kyc.submitted", client_id)[0]
    assert set(_meta(submit_event)["uploaded_document_ids"]) == {
        pan_id, aadhaar_id, firm_doc.json()["id"],
    }

    # The firm reviewer sees the portal files and approves them.
    client.cookies.clear()
    firm_listing = client.get(
        f"/api/clients/{client_id}/kyc/documents", headers=auth_headers(token),
    ).json()
    assert {d["id"] for d in firm_listing["documents"]} == {
        firm_doc.json()["id"], pan_id, aadhaar_id,
    }
    portal_file = client.get(
        f"/api/clients/{client_id}/kyc/documents/{pan_id}/download?inline=true",
        headers=auth_headers(token),
    )
    assert portal_file.status_code == 200 and portal_file.content == PDF_BYTES
    all_ids = [d["id"] for d in firm_listing["documents"]]
    # The portal user's own open of the Aadhaar is not the reviewer's open.
    not_opened = client.post(
        f"/api/clients/{client_id}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": all_ids},
    )
    assert not_opened.status_code == 409, not_opened.text
    assert "Aadhaar (masked)" in not_opened.json()["detail"]
    open_kyc_documents(client, token, client_id, [firm_doc.json()["id"], aadhaar_id])
    approved = client.post(
        f"/api/clients/{client_id}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": [d["id"] for d in firm_listing["documents"]]},
    )
    assert approved.status_code == 200, approved.text

    # A verified client cannot be reset from the portal.
    _verify_and_session(client, _invite_client_portal_user(
        client, token, matter_id, email="second@portal.example",
    )[1])
    reset = client.post(
        f"/api/portal/matters/{matter_id}/kyc",
        json={"client_id": client_id, "documents": []},
        headers=_portal_csrf_headers(client),
    )
    assert reset.status_code == 409
    with get_session_factory()() as session:
        assert session.get(Client, client_id).kyc_status == "verified"


def test_portal_user_removes_only_own_unreviewed_files(client: TestClient) -> None:
    boot = _owner(client, "kyc-portal-rm")
    token = boot["access_token"]
    matter_id = _seed_matter(boot["company"]["id"], code="KYC-PR")
    client_id = _seed_client_and_link(boot["company"]["id"], matter_id)
    firm_doc = upload_kyc_document(client, token, client_id, document_type="pan").json()["id"]
    _, debug = _invite_client_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    headers = _portal_csrf_headers(client)
    own = portal_upload_kyc_document(
        client, matter_id, client_id, headers, document_type="passport",
    ).json()["id"]

    firm = client.delete(
        f"/api/portal/matters/{matter_id}/kyc/documents/{firm_doc}?client_id={client_id}",
        headers=headers,
    )
    assert firm.status_code == 404
    mine = client.delete(
        f"/api/portal/matters/{matter_id}/kyc/documents/{own}?client_id={client_id}",
        headers=headers,
    )
    assert mine.status_code == 204
    with get_session_factory()() as session:
        assert session.get(ClientKycDocument, own) is None
        assert session.get(ClientKycDocument, firm_doc) is not None
    assert len(_audit("portal.kyc_document_removed", client_id)) == 1


# ---------------------------------------------------------------------------
# Review round 2: the server enforces "open each file before deciding"
# ---------------------------------------------------------------------------


def test_direct_approval_is_refused_until_the_reviewer_opened_each_document(
    client: TestClient,
) -> None:
    _boot, token, cid, (pan_id, aadhaar_id) = _submitted_pack(client, "kyc-opened")
    path = f"/api/clients/{cid}/kyc/verify"

    # A direct POST naming every current file, with nothing opened.
    blind = client.post(
        path, headers=auth_headers(token), json={"reviewed_document_ids": [pan_id, aadhaar_id]},
    )
    assert blind.status_code == 409, blind.text
    detail = blind.json()["detail"]
    assert detail.startswith("Open each KYC document before you approve the pack.")
    assert "PAN card (pan.pdf)" in detail
    assert "Aadhaar (masked) (aadhaar-masked.png)" in detail
    _assert_unreviewed(cid)

    # A download counts as opening; the refusal now names only the other file.
    downloaded = client.get(
        f"/api/clients/{cid}/kyc/documents/{pan_id}/download", headers=auth_headers(token),
    )
    assert downloaded.status_code == 200
    half = client.post(
        path, headers=auth_headers(token), json={"reviewed_document_ids": [pan_id, aadhaar_id]},
    )
    assert half.status_code == 409, half.text
    assert "PAN card" not in half.json()["detail"]
    assert "Aadhaar (masked) (aadhaar-masked.png)" in half.json()["detail"]
    _assert_unreviewed(cid)

    open_kyc_documents(client, token, cid, [aadhaar_id])
    ok = client.post(
        path, headers=auth_headers(token), json={"reviewed_document_ids": [pan_id, aadhaar_id]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["kyc_status"] == "verified"


def test_only_this_reviewers_own_opens_after_upload_count(client: TestClient) -> None:
    boot, owner_token, cid, (pan_id, aadhaar_id) = _submitted_pack(client, "kyc-opened-by")
    reviewer_id, reviewer_token = _member(client, owner_token, "kyc-opened-by")
    # The owner opened both files; that does not make them opened by the reviewer.
    open_kyc_documents(client, owner_token, cid, [pan_id, aadhaar_id])

    # Audit rows that are not this reviewer's successful open, after upload,
    # in this workspace, do not count either.
    other = _owner(client, "kyc-opened-other")
    with get_session_factory()() as session:
        aadhaar = session.get(ClientKycDocument, aadhaar_id)
        before_upload = aadhaar.created_at - timedelta(minutes=5)
        common = dict(
            action="client.kyc_document_viewed", target_type="client", target_id=cid,
            actor_type="human", actor_membership_id=reviewer_id,
        )
        session.add_all([
            AuditEvent(  # another tenant's row naming this client and file
                company_id=other["company"]["id"], result="success",
                metadata_json=json.dumps({"document_id": pan_id}), **common,
            ),
            AuditEvent(  # recorded before the file was uploaded
                company_id=boot["company"]["id"], result="success",
                metadata_json=json.dumps({"document_id": aadhaar_id}),
                created_at=before_upload, **common,
            ),
            AuditEvent(  # a refused open
                company_id=boot["company"]["id"], result="denied",
                metadata_json=json.dumps({"document_id": pan_id}), **common,
            ),
        ])
        session.commit()

    refused = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(reviewer_token),
        json={"reviewed_document_ids": [pan_id, aadhaar_id]},
    )
    assert refused.status_code == 409, refused.text
    assert "PAN card" in refused.json()["detail"]
    assert "Aadhaar (masked)" in refused.json()["detail"]
    _assert_unreviewed(cid)

    open_kyc_documents(client, reviewer_token, cid, [pan_id, aadhaar_id])
    ok = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(reviewer_token),
        json={"reviewed_document_ids": [pan_id, aadhaar_id]},
    )
    assert ok.status_code == 200, ok.text
    with get_session_factory()() as session:
        assert {
            doc.reviewed_by_membership_id
            for doc in session.scalars(
                select(ClientKycDocument).where(ClientKycDocument.client_id == cid)
            )
        } == {reviewer_id}


def test_rejection_may_name_only_documents_the_reviewer_opened(client: TestClient) -> None:
    _boot, token, cid, (pan_id, aadhaar_id) = _submitted_pack(client, "kyc-reject-open")
    blind = client.post(
        f"/api/clients/{cid}/kyc/reject", headers=auth_headers(token),
        json={"reason": "Aadhaar image is unreadable", "reviewed_document_ids": [aadhaar_id]},
    )
    assert blind.status_code == 409, blind.text
    assert blind.json()["detail"].startswith("Open each KYC document before you reject the pack.")
    _assert_unreviewed(cid)

    # A rejection that names no file (wrong or missing pack) needs no open.
    unnamed = client.post(
        f"/api/clients/{cid}/kyc/reject", headers=auth_headers(token),
        json={"reason": "Wrong client's documents uploaded"},
    )
    assert unnamed.status_code == 200, unnamed.text
    with get_session_factory()() as session:
        assert session.get(ClientKycDocument, pan_id).review_decision is None
        assert session.get(ClientKycDocument, aadhaar_id).review_decision is None


def test_matter_verification_patch_requires_opened_documents_to_approve_or_reject(
    client: TestClient,
) -> None:
    from tests.test_clients import _mk_matter

    token = _owner(client, "kyc-matter-open")["access_token"]
    cid = _client(client, token)
    matter = _mk_matter(client, token, code="KYC-MO-1")
    assert client.post(
        f"/api/matters/{matter['id']}/clients", headers=auth_headers(token),
        json={"client_id": cid},
    ).status_code == 200
    path = f"/api/matters/{matter['id']}/client-verification/{cid}"
    ids = upload_complete_kyc_pack(client, token, cid)
    assert client.patch(
        path, headers=auth_headers(token), json={"status": "submitted"},
    ).status_code == 200

    blind_approve = client.patch(
        path, headers=auth_headers(token),
        json={"status": "verified", "reviewed_document_ids": ids},
    )
    assert blind_approve.status_code == 409, blind_approve.text
    assert "before you approve" in blind_approve.json()["detail"]
    blind_reject = client.patch(
        path, headers=auth_headers(token),
        json={"status": "rejected", "rejection_reason": "Blurred PAN",
              "reviewed_document_ids": ids[:1]},
    )
    assert blind_reject.status_code == 409, blind_reject.text
    assert "before you reject" in blind_reject.json()["detail"]
    _assert_unreviewed(cid)

    open_kyc_documents(client, token, cid, ids)
    ok = client.patch(
        path, headers=auth_headers(token),
        json={"status": "verified", "reviewed_document_ids": ids},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "verified"


# ---------------------------------------------------------------------------
# Review round 2: no writer moves an incomplete pack under review
# ---------------------------------------------------------------------------


def test_matter_patch_cannot_move_an_incomplete_pack_under_review(client: TestClient) -> None:
    from tests.test_clients import _mk_matter

    token = _owner(client, "kyc-under-review")["access_token"]
    cid = _client(client, token)
    matter = _mk_matter(client, token, code="KYC-UR-1")
    assert client.post(
        f"/api/matters/{matter['id']}/clients", headers=auth_headers(token),
        json={"client_id": cid},
    ).status_code == 200
    path = f"/api/matters/{matter['id']}/client-verification/{cid}"
    assert client.patch(
        path, headers=auth_headers(token), json={"status": "requested"},
    ).status_code == 200

    # requested -> under review with no files: refused, uploads stay open.
    empty = client.patch(path, headers=auth_headers(token), json={"status": "under_review"})
    assert empty.status_code == 409, empty.text
    assert "KYC cannot be moved to review yet" in empty.json()["detail"]
    assert "PAN card" in empty.json()["detail"]
    with get_session_factory()() as session:
        assert session.get(Client, cid).kyc_status == "requested"
    pan_id, aadhaar_id = upload_complete_kyc_pack(client, token, cid)

    # A submitted pack that lost a required file cannot go under review either.
    assert client.patch(
        path, headers=auth_headers(token), json={"status": "submitted"},
    ).status_code == 200
    removed = client.delete(
        f"/api/clients/{cid}/kyc/documents/{aadhaar_id}", headers=auth_headers(token),
    )
    assert removed.status_code == 204
    lost = client.patch(path, headers=auth_headers(token), json={"status": "under_review"})
    assert lost.status_code == 409, lost.text
    assert "Masked Aadhaar, passport or another address proof" in lost.json()["detail"]
    listing = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token))
    assert listing.json()["kyc_status"] == "submitted"
    assert listing.json()["upload_allowed"] is True

    # With the pack complete the review proceeds to a decision.
    passport = upload_kyc_document(
        client, token, cid, document_type="passport",
        filename="passport.jpg", content=JPEG_BYTES, content_type="image/jpeg",
    )
    assert passport.status_code == 201, passport.text
    moved = client.patch(path, headers=auth_headers(token), json={"status": "under_review"})
    assert moved.status_code == 200, moved.text
    assert client.get(
        f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token),
    ).json()["upload_allowed"] is False
    current = [pan_id, passport.json()["id"]]
    open_kyc_documents(client, token, cid, current)
    approved = client.patch(
        path, headers=auth_headers(token),
        json={"status": "verified", "reviewed_document_ids": current},
    )
    assert approved.status_code == 200, approved.text


def test_every_upload_frozen_status_needs_a_complete_pack_to_enter() -> None:
    """Transition-table invariant: a status that freezes uploads can only be
    entered by a writer that checks the pack, and never by create or the
    generic client PATCH."""
    from caseops_api.services import clients as client_service
    from caseops_api.services.client_kyc_documents import UPLOAD_OPEN_STATUSES

    frozen = {s.value for s in ClientKycStatus} - set(UPLOAD_OPEN_STATUSES)
    assert frozen == {"under_review", "verified"}
    entered = {
        new
        for current, allowed in client_service._ALLOWED_VERIFICATION_TRANSITIONS.items()
        for new in allowed
        if new != current
    }
    assert frozen & entered <= set(client_service._PACK_REQUIRED_KYC_ACTIONS)
    assert frozen <= client_service._WORKFLOW_ONLY_KYC_STATUSES


# ---------------------------------------------------------------------------
# Review round 2: full Aadhaar in file names and the rejection reason
# ---------------------------------------------------------------------------


def test_full_aadhaar_in_a_file_name_is_masked_on_write_and_on_read(client: TestClient) -> None:
    full = _full_aadhaar()
    masked = f"XXXX_XXXX_{full[-4:]}"
    boot = _owner(client, "kyc-aadhaar-name")
    token = boot["access_token"]
    cid = _client(client, token)

    cases = [
        ("aadhaar_masked", f"aadhaar {full[:4]} {full[4:8]} {full[8:]}.pdf",
         f"aadhaar_{masked}.pdf"),
        ("pan", f"pan-{full}.pdf", f"pan-{masked}.pdf"),
        ("passport", f"{full[:4]}.{full[4:8]}.{full[8:]}.pdf", f"{masked}.pdf"),
    ]
    for document_type, filename, expected in cases:
        resp = upload_kyc_document(
            client, token, cid, document_type=document_type, filename=filename,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["original_filename"] == expected
        with get_session_factory()() as session:
            assert session.get(ClientKycDocument, resp.json()["id"]).original_filename == expected
        for inline in ("true", "false"):
            opened = client.get(
                f"/api/clients/{cid}/kyc/documents/{resp.json()['id']}/download?inline={inline}",
                headers=auth_headers(token),
            )
            assert opened.status_code == 200
            assert full[:8] not in opened.headers["content-disposition"]
            assert expected in opened.headers["content-disposition"]
    listing = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token))
    assert full not in listing.text and full[:8] not in listing.text

    # A row stored before the rule is masked on every read.
    legacy_id = listing.json()["documents"][0]["id"]
    with get_session_factory()() as session:
        session.get(ClientKycDocument, legacy_id).original_filename = f"aadhaar_{full}.pdf"
        session.commit()
    listing = client.get(f"/api/clients/{cid}/kyc/documents", headers=auth_headers(token))
    assert listing.json()["documents"][0]["original_filename"] == f"aadhaar_{masked}.pdf"
    assert full not in listing.text
    legacy = client.get(
        f"/api/clients/{cid}/kyc/documents/{legacy_id}/download", headers=auth_headers(token),
    )
    assert full not in legacy.headers["content-disposition"]
    assert f"aadhaar_{masked}.pdf" in legacy.headers["content-disposition"]
    # The refusal that names an unopened file uses the masked name too.
    assert client.post(
        f"/api/clients/{cid}/kyc/submit", headers=auth_headers(token), json={},
    ).status_code == 200
    with get_session_factory()() as session:
        session.query(AuditEvent).filter(
            AuditEvent.action.in_(
                ["client.kyc_document_viewed", "client.kyc_document_downloaded"],
            ),
            AuditEvent.target_id == cid,
        ).delete(synchronize_session=False)
        session.commit()
    refused = client.post(
        f"/api/clients/{cid}/kyc/verify", headers=auth_headers(token),
        json={"reviewed_document_ids": [d["id"] for d in listing.json()["documents"]]},
    )
    assert refused.status_code == 409
    assert full not in refused.text and masked in refused.text

    # The portal upload path masks the same way.
    matter_id = _seed_matter(boot["company"]["id"], code="KYC-AN-P")
    portal_client = _seed_client_and_link(boot["company"]["id"], matter_id)
    _, debug = _invite_client_portal_user(client, token, matter_id)
    _verify_and_session(client, debug)
    portal = portal_upload_kyc_document(
        client, matter_id, portal_client, _portal_csrf_headers(client),
        document_type="pan", filename=f"pan {full}.pdf",
    )
    assert portal.status_code == 201, portal.text
    assert portal.json()["original_filename"] == f"pan_{masked}.pdf"
    portal_open = client.get(
        f"/api/portal/matters/{matter_id}/kyc/documents/{portal.json()['id']}/download"
        f"?client_id={portal_client}",
    )
    assert portal_open.status_code == 200
    assert full not in portal_open.headers["content-disposition"]


def test_full_aadhaar_is_refused_in_the_rejection_reason_on_every_reject_path(
    client: TestClient,
) -> None:
    from tests.test_clients import _mk_matter

    full = _full_aadhaar()
    spaced = f"{full[:4]} {full[4:8]} {full[8:]}"
    _boot, token, cid, _ids = _submitted_pack(client, "kyc-aadhaar-reason")
    internal = client.post(
        f"/api/clients/{cid}/kyc/reject", headers=auth_headers(token),
        json={"reason": f"Aadhaar {spaced} does not match the PAN"},
    )
    assert internal.status_code == 422, internal.text
    assert "full Aadhaar" in internal.text

    matter = _mk_matter(client, token, code="KYC-AR-1")
    assert client.post(
        f"/api/matters/{matter['id']}/clients", headers=auth_headers(token),
        json={"client_id": cid},
    ).status_code == 200
    path = f"/api/matters/{matter['id']}/client-verification/{cid}"
    patched = client.patch(
        path, headers=auth_headers(token),
        json={"status": "rejected", "rejection_reason": f"Number {full} is wrong"},
    )
    assert patched.status_code == 422, patched.text
    assert "full Aadhaar" in patched.text
    _assert_unreviewed(cid)
    # The masked form is accepted.
    ok = client.post(
        f"/api/clients/{cid}/kyc/reject", headers=auth_headers(token),
        json={"reason": f"Aadhaar XXXX XXXX {full[-4:]} does not match the PAN"},
    )
    assert ok.status_code == 200, ok.text

    # A reason stored before the rule is masked on every read.
    with get_session_factory()() as session:
        session.get(Client, cid).kyc_rejection_reason = f"Aadhaar {spaced} is wrong"
        session.commit()
    profile = client.get(f"/api/clients/{cid}", headers=auth_headers(token))
    assert spaced not in profile.text
    assert profile.json()["kyc_rejection_reason"] == f"Aadhaar XXXX XXXX {full[-4:]} is wrong"
    verification = client.get(
        f"/api/matters/{matter['id']}/client-verification", headers=auth_headers(token),
    )
    assert spaced not in verification.text
    assert verification.json()["clients"][0]["rejection_reason"] == (
        f"Aadhaar XXXX XXXX {full[-4:]} is wrong"
    )


def test_kyc_documents_are_not_part_of_retrieval_sources() -> None:
    """SEC-016: no retrieval, OCR or translation module reads KYC files."""
    from pathlib import Path

    services = Path(__file__).resolve().parents[1] / "src" / "caseops_api" / "services"
    readers = sorted(
        path.name
        for path in services.glob("*.py")
        if "ClientKycDocument" in path.read_text(encoding="utf-8")
    )
    assert readers == ["client_kyc_documents.py", "storage_governance.py"]
