"""Shared helpers for KYC tests (BUG-003).

A KYC pack is the client's uploaded files. Tests that need a submitted or
verified client upload a real PAN and a masked Aadhaar first, through the
same HTTP endpoint the web uses. A reviewer must open each file before naming
it in an approval or rejection, so the helpers open files through the same
download endpoint the web preview uses.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def upload_kyc_document(
    client: TestClient,
    token: str,
    client_id: str,
    *,
    document_type: str,
    filename: str = "pan.pdf",
    content: bytes = PDF_BYTES,
    content_type: str = "application/pdf",
    label: str | None = None,
):
    data = {"document_type": document_type}
    if label is not None:
        data["label"] = label
    return client.post(
        f"/api/clients/{client_id}/kyc/documents",
        headers=auth_headers(token),
        data=data,
        files={"file": (filename, content, content_type)},
    )


def upload_complete_kyc_pack(client: TestClient, token: str, client_id: str) -> list[str]:
    """Upload a PAN (PDF) and a masked Aadhaar (PNG); return their ids."""
    pan = upload_kyc_document(client, token, client_id, document_type="pan")
    assert pan.status_code == 201, pan.text
    aadhaar = upload_kyc_document(
        client, token, client_id,
        document_type="aadhaar_masked",
        filename="aadhaar-masked.png",
        content=PNG_BYTES,
        content_type="image/png",
    )
    assert aadhaar.status_code == 201, aadhaar.text
    return [pan.json()["id"], aadhaar.json()["id"]]


def current_kyc_document_ids(client: TestClient, token: str, client_id: str) -> list[str]:
    resp = client.get(f"/api/clients/{client_id}/kyc/documents", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return [doc["id"] for doc in resp.json()["documents"]]


def open_kyc_documents(
    client: TestClient, token: str, client_id: str, document_ids: list[str],
) -> None:
    """Open each file inline as the reviewer, as the web preview does."""
    for document_id in document_ids:
        resp = client.get(
            f"/api/clients/{client_id}/kyc/documents/{document_id}/download?inline=true",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text


def verify_kyc(client: TestClient, token: str, client_id: str):
    ids = current_kyc_document_ids(client, token, client_id)
    open_kyc_documents(client, token, client_id, ids)
    return client.post(
        f"/api/clients/{client_id}/kyc/verify",
        headers=auth_headers(token),
        json={"reviewed_document_ids": ids},
    )


def portal_upload_kyc_document(
    client: TestClient,
    matter_id: str,
    client_id: str,
    headers: dict[str, str],
    *,
    document_type: str,
    filename: str = "pan.pdf",
    content: bytes = PDF_BYTES,
    content_type: str = "application/pdf",
    label: str | None = None,
):
    data = {"client_id": client_id, "document_type": document_type}
    if label is not None:
        data["label"] = label
    return client.post(
        f"/api/portal/matters/{matter_id}/kyc/documents",
        headers=headers,
        data=data,
        files={"file": (filename, content, content_type)},
    )


def portal_upload_complete_kyc_pack(
    client: TestClient, matter_id: str, client_id: str, headers: dict[str, str],
) -> list[str]:
    pan = portal_upload_kyc_document(
        client, matter_id, client_id, headers, document_type="pan",
    )
    assert pan.status_code == 201, pan.text
    aadhaar = portal_upload_kyc_document(
        client, matter_id, client_id, headers,
        document_type="aadhaar_masked", filename="aadhaar-masked.jpg",
        content=JPEG_BYTES, content_type="image/jpeg",
    )
    assert aadhaar.status_code == 201, aadhaar.text
    return [pan.json()["id"], aadhaar.json()["id"]]
