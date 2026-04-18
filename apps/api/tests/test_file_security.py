"""§6.3 — pre-persistence upload guards."""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException

from caseops_api.services.file_security import verify_upload


def test_accepts_pdf_with_matching_magic() -> None:
    stream = io.BytesIO(b"%PDF-1.4\n%" + b"x" * 200)
    verify_upload(filename="brief.pdf", content_type="application/pdf", stream=stream)
    # Stream cursor must be at 0 for the downstream persister.
    assert stream.tell() == 0


def test_refuses_blocked_extension() -> None:
    with pytest.raises(HTTPException) as exc:
        verify_upload(
            filename="oops.exe",
            content_type="application/octet-stream",
            stream=io.BytesIO(b"MZ\x90\x00"),
        )
    assert exc.value.status_code == 400
    assert ".exe" in exc.value.detail


def test_refuses_pdf_extension_with_wrong_magic() -> None:
    # A `malware.pdf` that's really a Windows PE: magic bytes "MZ".
    stream = io.BytesIO(b"MZ\x90\x00" + b"\x00" * 50)
    with pytest.raises(HTTPException) as exc:
        verify_upload(
            filename="malware.pdf",
            content_type="application/pdf",
            stream=stream,
        )
    assert exc.value.status_code == 400
    assert "signature" in exc.value.detail.lower()


def test_refuses_mismatched_content_type() -> None:
    stream = io.BytesIO(b"%PDF-1.4\n%" + b"x" * 50)
    with pytest.raises(HTTPException) as exc:
        verify_upload(
            filename="brief.pdf",
            content_type="image/png",
            stream=stream,
        )
    assert exc.value.status_code == 400
    assert "content-type" in exc.value.detail.lower()


def test_accepts_docx_zip_magic() -> None:
    stream = io.BytesIO(b"PK\x03\x04" + b"\x00" * 500)
    verify_upload(
        filename="contract.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        stream=stream,
    )


def test_accepts_png_with_magic() -> None:
    png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    verify_upload(
        filename="diagram.png",
        content_type="image/png",
        stream=io.BytesIO(png_magic),
    )


def test_refuses_empty_filename() -> None:
    with pytest.raises(HTTPException):
        verify_upload(filename="  ", content_type="application/pdf", stream=io.BytesIO(b"%PDF-1.4"))


def test_refuses_filename_without_extension() -> None:
    with pytest.raises(HTTPException) as exc:
        verify_upload(
            filename="README",
            content_type="text/plain",
            stream=io.BytesIO(b"hello"),
        )
    assert "extension" in exc.value.detail.lower()


def test_txt_has_no_signature_requirement() -> None:
    # .txt is allowed without magic-byte check — text has no signature.
    verify_upload(
        filename="notes.txt",
        content_type="text/plain",
        stream=io.BytesIO(b"just some text"),
    )
