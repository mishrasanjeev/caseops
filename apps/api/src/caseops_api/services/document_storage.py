from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, status

from caseops_api.core.settings import get_settings

_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StoredDocument:
    storage_key: str
    size_bytes: int
    sha256_hex: str


def _document_root() -> Path:
    root = Path(get_settings().document_storage_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_filename(filename: str) -> str:
    candidate = Path(filename).name.strip() or "document"
    sanitized = _FILENAME_SANITIZER.sub("_", candidate)
    return sanitized[:255] or "document"


def persist_matter_attachment(
    *,
    company_id: str,
    matter_id: str,
    attachment_id: str,
    filename: str,
    stream: BinaryIO,
) -> StoredDocument:
    safe_filename = sanitize_filename(filename)
    relative_path = Path(company_id) / matter_id / f"{attachment_id}-{safe_filename}"
    target_path = _document_root() / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    hasher = hashlib.sha256()
    size_bytes = 0
    max_bytes = get_settings().max_attachment_size_bytes
    stream.seek(0)

    try:
        with target_path.open("wb") as output:
            while chunk := stream.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Attachments must be {max_bytes} bytes or smaller.",
                    )
                hasher.update(chunk)
                output.write(chunk)
    except Exception:
        if target_path.exists():
            target_path.unlink()
        raise

    if size_bytes == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attachment upload cannot be empty.",
        )

    return StoredDocument(
        storage_key=relative_path.as_posix(),
        size_bytes=size_bytes,
        sha256_hex=hasher.hexdigest(),
    )


def resolve_storage_path(storage_key: str) -> Path:
    root = _document_root()
    target_path = (root / storage_key).resolve()
    if os.path.commonpath([str(root), str(target_path)]) != str(root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    return target_path
