from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi import HTTPException

from caseops_api.db.models import CompanyMembership, ContractAttachment
from caseops_api.db.session import get_session_factory
from caseops_api.services import contract_attachment_bytes as sources
from caseops_api.services.document_storage import resolve_storage_path
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_legalworkspace_contract_metadata import _create_contract


def _uploaded(client, data=None):
    auth = bootstrap_company(client)
    token = str(auth["access_token"])
    contract = _create_contract(client, token)
    if data is None:
        document = Document()
        document.add_paragraph("Synthetic immutable source, not legal advice.")
        buffer = BytesIO()
        document.save(buffer)
        data = buffer.getvalue()
    path = f"/api/contracts/{contract['id']}/attachments"
    response = client.post(
        path,
        headers=auth_headers(token),
        files={
            "file": (
                "source.docx",
                data,
                sources.DOCX_MIME,
            )
        },
    )
    assert response.status_code == 200, response.text
    attachment = response.json()
    with get_session_factory()() as session:
        stored = resolve_storage_path(session.get(ContractAttachment, attachment["id"]).storage_key)
    return auth, auth_headers(token), path + f"/{attachment['id']}", stored, data, attachment


def test_validated_docx_and_response_are_one_buffer_even_after_path_replacement(
    client, monkeypatch
):
    from caseops_api.services.matters import _validate_docx_preview_archive

    _, headers, path, stored, original, attachment = _uploaded(client)
    replacement = stored.with_suffix(".replacement")
    replacement.write_bytes(b"untrusted replacement must never be displayed")
    inspected = []

    def validate(buffer):
        assert isinstance(buffer, BytesIO)
        inspected.append(buffer.getvalue())
        _validate_docx_preview_archive(buffer)
        replacement.replace(stored)

    monkeypatch.setattr("caseops_api.services.matters._validate_docx_preview_archive", validate)
    response = client.get(path + "/preview", headers=headers)
    assert response.status_code == 200, response.text
    assert inspected == [original]
    assert response.content == original
    assert response.headers["x-caseops-source-sha256"] == attachment["sha256_hex"]
    assert client.get(path + "/download", headers=headers).status_code == 409


def test_stored_hash_mismatch_is_rejected_before_any_preview_validation(client, monkeypatch):
    _, headers, path, stored, original, _ = _uploaded(client)
    changed = bytearray(original)
    changed[-1] ^= 1
    stored.write_bytes(changed)
    called = []
    monkeypatch.setattr(
        "caseops_api.services.matters._validate_docx_preview_archive", lambda _: called.append(True)
    )
    assert client.get(path + "/preview", headers=headers).status_code == 409
    assert client.get(path + "/download", headers=headers).status_code == 409
    assert called == []


def test_source_growth_during_descriptor_read_is_rejected(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.bin"
    original = b"original source"
    source.write_bytes(original)
    fstat = sources.os.fstat
    calls = []

    def growing(descriptor):
        calls.append(descriptor)
        if len(calls) == 2:
            with source.open("ab") as output:
                output.write(b"unexpected growth")
        return fstat(descriptor)

    monkeypatch.setattr(sources.os, "fstat", growing)
    with pytest.raises(HTTPException) as error:
        sources._read_source(source, len(original), hashlib.sha256(original).hexdigest())
    assert error.value.status_code == 409


@pytest.mark.parametrize("problem", ["mime", "limit", "archive"])
def test_source_mime_size_and_archive_are_fail_closed(client, problem):
    data = None
    if problem == "archive":
        from zipfile import ZIP_DEFLATED, ZipFile

        document, buffer, output = Document(), BytesIO(), BytesIO()
        document.add_paragraph("Synthetic source with an unsupported embedded part.")
        document.save(buffer)
        with ZipFile(buffer) as original, ZipFile(output, "w", ZIP_DEFLATED) as changed:
            for part in original.infolist():
                changed.writestr(part.filename, original.read(part.filename))
            changed.writestr("word/embeddings/unsupported.bin", b"synthetic inert fixture")
        data = output.getvalue()
    _, headers, path, _, _, attachment = _uploaded(client, data)
    with get_session_factory()() as session:
        record = session.get(ContractAttachment, attachment["id"])
        if problem == "mime":
            record.content_type = "application/pdf"
        if problem == "limit":
            record.size_bytes = sources.MAX_SOURCE_BYTES + 1
        session.commit()
    response = client.get(path + "/preview", headers=headers)
    assert response.status_code == {"mime": 415, "limit": 413, "archive": 422}[problem], (
        response.text
    )


def test_file_acquisition_releases_transaction_and_rechecks_revoked_actor(client, monkeypatch):
    auth, headers, path, _, _, _ = _uploaded(client)
    read = sources._read_source
    actor_fence = sources.lock_contract_actor
    observed_sessions = []

    def fenced(session, **kwargs):
        observed_sessions.append(session)
        return actor_fence(session, **kwargs)

    monkeypatch.setattr(sources, "lock_contract_actor", fenced)

    def revoke(*args):
        assert observed_sessions and not observed_sessions[-1].in_transaction()
        with get_session_factory()() as session:
            actor = session.get(CompanyMembership, auth["membership"]["id"])
            actor.is_active = False
            session.commit()
        return read(*args)

    monkeypatch.setattr(sources, "_read_source", revoke)
    response = client.get(path + "/preview", headers=headers)
    assert response.status_code == 403, response.text
    assert b"Synthetic immutable source" not in response.content
