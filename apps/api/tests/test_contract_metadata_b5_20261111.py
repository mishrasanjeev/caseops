from __future__ import annotations

import json
from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_legalworkspace_contract_metadata import _create_contract


@pytest.mark.parametrize("suffix", ["/metadata", ""])
def test_full_metadata_edit_retains_values_audit_and_rejects_stale_save(
    client: TestClient, suffix: str
):
    auth = bootstrap_company(client)
    headers = auth_headers(str(auth["access_token"]))
    original = _create_contract(client, str(auth["access_token"]))
    path = f"/api/contracts/{original['id']}"
    changes = {
        "title": "Corrected vendor services agreement",
        "counterparty_name": "Corrected counterparty",
        "contract_type": "Lease",
        "contract_type_key": "lease",
        "contract_type_notes": None,
        "effective_on": "2026-11-01",
        "expires_on": "2027-10-31",
        "renewal_on": "2027-09-01",
        "auto_renewal": True,
        "summary": "Synthetic corrected description.",
    }
    response = client.patch(
        path + suffix,
        headers=headers,
        json={**changes, "expected_updated_at": original["updated_at"]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    for key, value in changes.items():
        assert updated[key] == value, key
    workspace = client.get(path + "/workspace", headers=headers).json()
    assert workspace["contract"] == updated
    with get_session_factory()() as session:
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == original["id"],
                AuditEvent.action == "contract.metadata.updated",
            )
        )
        assert event is not None
        assert event.actor_membership_id == auth["membership"]["id"]
        assert event.created_at is not None
        metadata = json.loads(event.metadata_json)
        for field in changes:
            old, new = original[field], changes[field]
            # Preserve the platform's immutable content-minimisation policy.
            if field in {"summary", "counterparty_name"}:
                old = f"[content-withheld chars={len(old or '')}]"
                new = f"[content-withheld chars={len(new or '')}]"
            assert metadata["before"][field] == old, field
            assert metadata["after"][field] == new, field
    stale = client.patch(
        path + suffix,
        headers=headers,
        json={
            "title": "A stale tab must not overwrite",
            "expected_updated_at": original["updated_at"],
        },
    )
    assert stale.status_code == 409, stale.text
    assert client.get(path, headers=headers).json()["title"] == changes["title"]
    clear = client.patch(
        path + suffix,
        headers=headers,
        json={
            "counterparty_name": None,
            "summary": None,
            "renewal_on": None,
            "expected_updated_at": updated["updated_at"],
        },
    )
    assert clear.status_code == 200, clear.text
    assert all(clear.json()[key] is None for key in ("counterparty_name", "summary", "renewal_on"))
    current = clear.json()
    with get_session_factory()() as session:
        before_ids = list(
            session.scalars(select(AuditEvent.id).where(AuditEvent.target_id == original["id"]))
        )
    noop = client.patch(
        path + suffix,
        headers=headers,
        json={
            "title": current["title"],
            "expected_updated_at": current["updated_at"],
        },
    )
    assert noop.status_code == 200, noop.text
    assert noop.json()["updated_at"] == current["updated_at"]
    with get_session_factory()() as session:
        assert (
            list(
                session.scalars(select(AuditEvent.id).where(AuditEvent.target_id == original["id"]))
            )
            == before_ids
        )
    emptied = client.patch(
        path + suffix,
        headers=headers,
        json={
            "effective_on": None,
            "expires_on": None,
            "contract_type_notes": None,
            "auto_renewal": False,
            "expected_updated_at": current["updated_at"],
        },
    )
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["effective_on"] is None
    assert emptied.json()["expires_on"] is None
    assert emptied.json()["auto_renewal"] is False


@pytest.mark.parametrize("suffix", ["/metadata", ""])
def test_metadata_edit_checks_authorization_and_merged_date_range(client: TestClient, suffix: str):
    auth = bootstrap_company(client)
    token = str(auth["access_token"])
    headers = auth_headers(token)
    original = _create_contract(client, token)
    path = f"/api/contracts/{original['id']}{suffix}"
    missing_version = client.patch(
        path, headers=headers, json={"title": "Missing version must not overwrite"}
    )
    assert missing_version.status_code == 422, missing_version.text
    for change in (
        {"title": "   "},
        {"title": None},
        {"contract_type": None},
        {"auto_renewal": None},
        {"expires_on": "2026-01-01"},
    ):
        response = client.patch(
            path, headers=headers, json={**change, "expected_updated_at": original["updated_at"]}
        )
        assert response.status_code == 422, response.text
    client.cookies.clear()
    csrf_denied = client.patch(path, json={"title": "Unauthorized edit"})
    assert csrf_denied.status_code == 403
    assert csrf_denied.json()["type"] == "https://caseops.ai/errors/csrf"
    assert (
        client.patch(
            path, headers=auth_headers("invalid-token"), json={"title": "Unauthorized edit"}
        ).status_code
        == 401
    )
    viewer = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": "Read only reviewer",
            "email": "viewer@example.com",
            "password": "ViewerPass123!",
            "role": "viewer",
        },
    )
    assert viewer.status_code == 200, viewer.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "viewer@example.com",
            "password": "ViewerPass123!",
        },
    )
    assert login.status_code == 200, login.text
    assert (
        client.patch(
            path,
            headers=auth_headers(login.json()["access_token"]),
            json={"title": "Read only edit"},
        ).status_code
        == 403
    )
    outside_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Outside B5",
            "company_slug": "b5-outsider",
            "company_type": "law_firm",
            "owner_full_name": "Outside owner",
            "owner_email": "outsider@example.com",
            "owner_password": "FoundersPass123!",
        },
    )
    assert outside_response.status_code == 200, outside_response.text
    outsider = outside_response.json()
    assert (
        client.patch(
            path,
            headers=auth_headers(str(outsider["access_token"])),
            json={"title": "Cross tenant edit", "expected_updated_at": original["updated_at"]},
        ).status_code
        == 404
    )


@pytest.mark.parametrize("kind", ["pdf", "docx"])
def test_private_preview_and_original_download_keep_bytes_and_tenant_acl(
    client: TestClient, kind: str
):
    auth = bootstrap_company(client)
    token = str(auth["access_token"])
    headers = auth_headers(token)
    contract = _create_contract(client, token)
    if kind == "docx":
        document = Document()
        document.add_paragraph("Synthetic source only. Effective on 15 November 2026.")
        document.add_page_break()
        document.add_paragraph("Synthetic source page two.")
        buffer = BytesIO()
        document.save(buffer)
        content = buffer.getvalue()
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        from fpdf import FPDF

        document = FPDF()
        for number in (1, 2):
            document.add_page()
            document.set_font("Helvetica", size=12)
            document.cell(0, 10, text=f"Synthetic source page {number}. Not a legal agreement.")
        content = bytes(document.output())
        mime = "application/pdf"
    path = f"/api/contracts/{contract['id']}/attachments"
    upload = client.post(path, headers=headers, files={"file": (f"original.{kind}", content, mime)})
    assert upload.status_code == 200, upload.text
    attachment = upload.json()
    download_path = path + f"/{attachment['id']}/download"
    download = client.get(download_path, headers=headers)
    assert download.status_code == 200, download.text
    assert download.content == content
    assert download.headers["cache-control"] == "private, no-store"
    assert f"original.{kind}" in download.headers["content-disposition"]
    preview_path = path + f"/{attachment['id']}/preview"
    preview = client.get(preview_path, headers=headers)
    assert preview.status_code == (200 if kind == "docx" else 415), preview.text
    other = _create_contract(client, token, "B5-OTHER")
    assert (
        client.get(
            f"/api/contracts/{other['id']}/attachments/{attachment['id']}/download", headers=headers
        ).status_code
        == 404
    )
    outside = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other B5",
            "company_slug": "other-b5",
            "company_type": "law_firm",
            "owner_full_name": "Other owner",
            "owner_email": "other@example.com",
            "owner_password": "FoundersPass123!",
        },
    )
    assert outside.status_code == 200, outside.text
    outside_headers = auth_headers(outside.json()["access_token"])
    assert client.get(download_path, headers=outside_headers).status_code == 404
    assert client.get(preview_path, headers=outside_headers).status_code == 404
    client.cookies.clear()
    assert client.get(download_path).status_code == 401
    assert client.get(preview_path).status_code == 401


def test_docx_preview_reuses_inert_archive_gate_without_blocking_original_download(
    client: TestClient, monkeypatch
):
    from zipfile import ZIP_DEFLATED, ZipFile

    auth = bootstrap_company(client)
    token = str(auth["access_token"])
    headers = auth_headers(token)
    contract = _create_contract(client, token)
    document = Document()
    document.add_paragraph("Synthetic text with unsafe external relationship.")
    buffer = BytesIO()
    document.save(buffer)
    output = BytesIO()
    with ZipFile(buffer) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for part in source.infolist():
            content = source.read(part.filename)
            if part.filename == "word/_rels/document.xml.rels":
                content = content.replace(
                    b"</Relationships>",
                    b'<Relationship Id="external" '
                    b'Type="http://schemas.openxmlformats.org/officeDocument/'
                    b'2006/relationships/image" Target="https://third-party.invalid/image.png" '
                    b'TargetMode="External"/></Relationships>',
                )
            target.writestr(part.filename, content)
    content = output.getvalue()
    path = f"/api/contracts/{contract['id']}/attachments"
    upload = client.post(
        path,
        headers=headers,
        files={
            "file": (
                "external.docx",
                content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert upload.status_code == 200, upload.text
    attachment_id = upload.json()["id"]
    assert client.get(path + f"/{attachment_id}/preview", headers=headers).status_code == 422
    assert client.get(path + f"/{attachment_id}/download", headers=headers).content == content

    def unavailable(_path):
        raise PermissionError("Synthetic storage read failure")

    monkeypatch.setattr("caseops_api.services.matters._validate_docx_preview_archive", unavailable)
    with pytest.raises(PermissionError, match="Synthetic storage read failure"):
        client.get(path + f"/{attachment_id}/preview", headers=headers)


@pytest.mark.parametrize("terminal", ["terminated", "expired"])
def test_status_change_fences_stale_edits_and_authorized_corrections_preserve_status(
    client: TestClient, terminal: str
):
    auth = bootstrap_company(client)
    headers = auth_headers(str(auth["access_token"]))
    original = _create_contract(client, str(auth["access_token"]))
    path = f"/api/contracts/{original['id']}"
    terminal_response = client.patch(path, headers=headers, json={"status": terminal})
    assert terminal_response.status_code == 200, terminal_response.text
    for suffix in ("/metadata", ""):
        rejected = client.patch(
            path + suffix,
            headers=headers,
            json={
                "title": "Stale edit must not persist",
                "expected_updated_at": original["updated_at"],
            },
        )
        assert rejected.status_code == 409, rejected.text
    corrected = client.patch(
        path + "/metadata",
        headers=headers,
        json={
            "summary": "Authorized historical correction",
            "expected_updated_at": terminal_response.json()["updated_at"],
        },
    )
    assert corrected.status_code == 200, corrected.text
    current = client.get(path, headers=headers).json()
    assert current["title"] == original["title"]
    assert current["status"] == terminal
    assert current["summary"] == "Authorized historical correction"


def test_term_review_requires_current_version_and_uses_shared_date_guard(client: TestClient):
    from tests.test_legalworkspace_contract_metadata import _upload_attachment

    auth = bootstrap_company(client)
    token = str(auth["access_token"])
    headers = auth_headers(token)
    contract = _create_contract(client, token)
    path = f"/api/contracts/{contract['id']}"
    source = _upload_attachment(client, token, contract["id"])
    suggestion = client.post(
        path + "/term-suggestions",
        headers=headers,
        json={
            "source_attachment_id": source["id"],
            "suggested_expires_on": "2026-01-01",
            "evidence_json": {"quote": "Synthetic conflicting expiry date"},
        },
    )
    assert suggestion.status_code == 200, suggestion.text
    review_path = path + f"/term-suggestions/{suggestion.json()['id']}/accept"
    assert client.post(review_path, headers=headers).status_code == 422
    changed = client.patch(
        path,
        headers=headers,
        json={
            "title": "A concurrent reviewed correction",
            "expected_updated_at": contract["updated_at"],
        },
    )
    assert changed.status_code == 200, changed.text
    assert (
        client.post(
            review_path, headers=headers, json={"expected_updated_at": contract["updated_at"]}
        ).status_code
        == 409
    )
    invalid = client.post(
        review_path, headers=headers, json={"expected_updated_at": changed.json()["updated_at"]}
    )
    assert invalid.status_code == 422, invalid.text
    assert "Expiry date cannot be before" in invalid.text
    workspace = client.get(path + "/workspace", headers=headers).json()
    assert workspace["term_suggestions"][0]["status"] == "suggested"
    assert workspace["contract"]["expires_on"] is None
