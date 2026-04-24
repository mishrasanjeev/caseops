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


# ---------------------------------------------------------------------
# P1-008 (2026-04-24, QG-UPL-002..QG-UPL-009) — abuse cases.
# ---------------------------------------------------------------------


def test_oversized_upload_rejected_413() -> None:
    """QG-UPL-002. Pre-fix the size cap was advertised but never
    enforced — a 5GB upload would burn disk before the persister
    had a chance to react. Now verify_upload counts bytes and
    refuses past max_bytes."""
    body = b"%PDF-1.4\n" + b"a" * (1024 * 1024 + 100)  # 1 MiB + 100 B
    stream = io.BytesIO(body)
    with pytest.raises(HTTPException) as exc:
        verify_upload(
            filename="huge.pdf",
            content_type="application/pdf",
            stream=stream,
            max_bytes=1024 * 1024,  # 1 MiB cap
        )
    assert exc.value.status_code == 413
    assert "exceeds" in exc.value.detail.lower()


def test_size_check_seeks_back_to_zero() -> None:
    """The persister downstream reads the FULL body. After our
    size enforcement loop reads to EOF, we must seek(0) so the
    persister still sees byte 1."""
    body = b"%PDF-1.4\n" + b"x" * 200
    stream = io.BytesIO(body)
    verify_upload(
        filename="ok.pdf",
        content_type="application/pdf",
        stream=stream,
        max_bytes=1024 * 1024,
    )
    assert stream.tell() == 0
    assert stream.read() == body


def test_polyglot_pdf_with_zip_tail_still_passes_signature_check() -> None:
    """QG-UPL-004 partial: a 'polyglot' file is one whose bytes
    satisfy multiple format signatures. PDF + ZIP polyglots have
    real attack history (PDF magic at offset 0, ZIP central
    directory at end). Our signature check matches at offset 0
    only, so a PDF-signed polyglot with ZIP appended is currently
    ACCEPTED. The downstream pdfminer parser is the next defence;
    document explicitly that this layer alone does not catch
    polyglots so the test serves as a permanent reminder."""
    body = b"%PDF-1.4\n" + b"x" * 200 + b"PK\x03\x04" + b"\x00" * 200
    stream = io.BytesIO(body)
    # Today this passes — the gap is the multi-stream parser. We
    # assert the current behavior so anyone tightening this
    # changes the test deliberately.
    verify_upload(
        filename="polyglot.pdf",
        content_type="application/pdf",
        stream=stream,
    )


def test_extension_case_insensitivity() -> None:
    """An uploader can supply BRIEF.PDF and the extension check
    must still apply. Verify lowercasing works."""
    stream = io.BytesIO(b"%PDF-1.4\n" + b"x" * 100)
    verify_upload(
        filename="BRIEF.PDF",
        content_type="application/pdf",
        stream=stream,
    )


def test_zero_byte_pdf_rejected_at_signature_stage() -> None:
    """A zero-byte file has no magic bytes to match. Reject."""
    stream = io.BytesIO(b"")
    with pytest.raises(HTTPException) as exc:
        verify_upload(
            filename="empty.pdf",
            content_type="application/pdf",
            stream=stream,
        )
    assert exc.value.status_code == 400
    assert "signature" in exc.value.detail.lower()


def test_archive_extension_rejected_even_with_pdf_magic() -> None:
    """QG-UPL-003 (allowed-extension-only). A .zip extension is
    NOT in the allow-list; an upload with .zip + PDF magic still
    fails at the extension check, not the signature check."""
    stream = io.BytesIO(b"%PDF-1.4\n" + b"x" * 100)
    with pytest.raises(HTTPException) as exc:
        verify_upload(
            filename="archive.zip",
            content_type="application/zip",
            stream=stream,
        )
    assert exc.value.status_code == 400
    assert ".zip" in exc.value.detail


def test_path_traversal_filename_rejected() -> None:
    """A filename with .. components must not slip through. The
    extension check looks at the suffix; path-traversal goes to
    the persister which sanitises. We assert that the persister's
    sanitize_filename strips traversal — surfaced here as a unit
    sanity so a future rewrite can't quietly drop the protection."""
    from caseops_api.services.document_storage import sanitize_filename
    cleaned = sanitize_filename("../../etc/passwd.pdf")
    assert ".." not in cleaned
    assert "/" not in cleaned and "\\" not in cleaned
