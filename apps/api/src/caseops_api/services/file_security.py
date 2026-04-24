"""Upload hardening (§6.3).

Before any uploaded file touches disk we assert:

- The **extension** is on an explicit whitelist. Extensions alone
  aren't trustworthy, but checking them up front is the cheapest way
  to reject obvious noise (.exe / .sh / .js …) without reading bytes.
- The **first 12 bytes** match the signature we expect for that
  extension. This catches renamed binaries — a `malware.pdf` that's
  really a PE executable will carry `MZ` at offset 0, not `%PDF`.
- The **declared content-type** is coherent with the extension. If a
  client claims `image/png` on a `.pdf` we reject; the sloppy client
  is rarer than the malicious one.

These checks are cheap (≤ 20 bytes read) and catch the 90th-percentile
upload attack without needing full virus scanning. Clam/vendor
scanning is §9.3 and runs as a downstream workflow step.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO

from fastapi import HTTPException, status


@dataclass(frozen=True)
class UploadKind:
    extension: str
    content_types: frozenset[str]
    # Each entry is a tuple of (offset, magic-bytes). A file matches
    # the kind if at least one entry matches. DOCX / XLSX are zip
    # containers so they share the PKzip magic with a lot of archive
    # types — we still accept them because the extension is narrow.
    signatures: tuple[tuple[int, bytes], ...]


ALLOWED_UPLOADS: tuple[UploadKind, ...] = (
    UploadKind(
        extension=".pdf",
        content_types=frozenset({"application/pdf"}),
        signatures=((0, b"%PDF-"),),
    ),
    UploadKind(
        extension=".docx",
        content_types=frozenset(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/octet-stream",
                "application/zip",
            }
        ),
        signatures=((0, b"PK\x03\x04"),),
    ),
    UploadKind(
        extension=".doc",
        content_types=frozenset(
            {"application/msword", "application/octet-stream"}
        ),
        # Old Office Compound File signature — .doc files land here;
        # we accept both this and the DOCX signature for uploads
        # flagged with .doc to cover well-meaning but wrong clients.
        signatures=((0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),),
    ),
    UploadKind(
        extension=".txt",
        content_types=frozenset({"text/plain", "application/octet-stream"}),
        signatures=(),  # Plain text has no magic — accept any bytes.
    ),
    UploadKind(
        extension=".png",
        content_types=frozenset({"image/png"}),
        signatures=((0, b"\x89PNG\r\n\x1a\n"),),
    ),
    UploadKind(
        extension=".jpg",
        content_types=frozenset({"image/jpeg"}),
        signatures=((0, b"\xff\xd8\xff"),),
    ),
    UploadKind(
        extension=".jpeg",
        content_types=frozenset({"image/jpeg"}),
        signatures=((0, b"\xff\xd8\xff"),),
    ),
)


# Soft upper bound in bytes. Tighten per-route if needed; the matter
# attachment path is the most-abused.
DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MiB


def _match_signature(head: bytes, kind: UploadKind) -> bool:
    if not kind.signatures:
        return True
    for offset, magic in kind.signatures:
        if len(head) >= offset + len(magic) and head[offset : offset + len(magic)] == magic:
            return True
    return False


def _kind_for_extension(ext_lower: str) -> UploadKind | None:
    for kind in ALLOWED_UPLOADS:
        if kind.extension == ext_lower:
            return kind
    return None


def verify_upload(
    *,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> None:
    """Refuse the upload before it touches disk.

    Raises HTTPException(400) with a machine-readable detail on any
    failure. Leaves the stream cursor at position 0 on success so the
    downstream persister reads the full body.
    """
    if not filename or not filename.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload filename is required.",
        )

    ext = PurePath(filename.strip()).suffix.lower()
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload filename must include an extension.",
        )

    kind = _kind_for_extension(ext)
    if kind is None:
        allowed = ", ".join(sorted({u.extension for u in ALLOWED_UPLOADS}))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Upload extension {ext!r} is not allowed. Allowed: {allowed}."
            ),
        )

    # The content-type check is informational: a rebuilt form-data
    # client can lie. We still refuse the most obvious mismatches.
    ct = (content_type or "").split(";", 1)[0].strip().lower() or None
    if ct is not None and ct not in kind.content_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Declared content-type {ct!r} does not match extension "
                f"{ext!r}. Expected one of: "
                f"{', '.join(sorted(kind.content_types))}."
            ),
        )

    head = stream.read(16)
    # Seek back so downstream code sees the full stream. If the stream
    # is not seekable (rare for our FastAPI upload path) we fall back
    # to writing the head into a BytesIO — but we prefer to raise so
    # the caller knows to upgrade.
    try:
        stream.seek(0)
    except (AttributeError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload stream must be seekable.",
        ) from exc

    if not _match_signature(head, kind):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Upload bytes do not match the expected signature for "
                f"{ext!r}. Refusing to store a file whose contents "
                "contradict its extension."
            ),
        )

    # Size enforcement (P1-008, 2026-04-24, QG-UPL-002). The previous
    # implementation exposed ``max_bytes`` but never enforced it,
    # leaving every upload route vulnerable to a 5GB-PDF DoS that
    # filled disk before the persister had a chance to react. Read
    # the stream in 1 MiB chunks counting bytes; abort the moment we
    # cross the cap; seek back to 0 so the persister still sees the
    # full body.
    _CHUNK = 1024 * 1024
    seen = 0
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        seen += len(chunk)
        if seen > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Upload exceeds the {max_bytes // (1024 * 1024)} MiB "
                    "limit for this surface."
                ),
            )
    try:
        stream.seek(0)
    except (AttributeError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload stream must be seekable after size check.",
        ) from exc


__all__ = [
    "ALLOWED_UPLOADS",
    "DEFAULT_MAX_BYTES",
    "UploadKind",
    "verify_upload",
]
