from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, status
from google.cloud import storage

from caseops_api.core.settings import get_settings

_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")
_SUPPORTED_STORAGE_BACKENDS = {"local", "gcs"}


@dataclass(frozen=True)
class StoredDocument:
    storage_key: str
    size_bytes: int
    sha256_hex: str


def _storage_backend() -> str:
    backend = get_settings().document_storage_backend.strip().lower()
    if backend not in _SUPPORTED_STORAGE_BACKENDS:
        raise RuntimeError(
            "Unsupported document storage backend configured. "
            f"Expected one of {sorted(_SUPPORTED_STORAGE_BACKENDS)}."
        )
    return backend


def _document_root() -> Path:
    root = Path(get_settings().document_storage_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _document_cache_root() -> Path:
    root = Path(get_settings().document_storage_cache_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validated_relative_path(storage_key: str) -> Path:
    candidate = Path(storage_key)
    if candidate.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    normalized = Path(*candidate.parts)
    if not normalized.parts or any(part in {"", ".", ".."} for part in normalized.parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    return normalized


def _gcs_client() -> storage.Client:
    settings = get_settings()
    return storage.Client(project=settings.gcp_project_id)


def _gcs_bucket_name() -> str:
    bucket = get_settings().document_storage_gcs_bucket
    if not bucket:
        raise RuntimeError(
            "CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET must be configured when using the gcs backend."
        )
    return bucket


def _gcs_blob_name(storage_key: str) -> str:
    prefix = get_settings().document_storage_gcs_prefix.strip().strip("/")
    return f"{prefix}/{storage_key}" if prefix else storage_key


def sanitize_filename(filename: str) -> str:
    candidate = Path(filename).name.strip() or "document"
    sanitized = _FILENAME_SANITIZER.sub("_", candidate)
    return sanitized[:255] or "document"


def _write_stream_to_temp_file(stream: BinaryIO) -> tuple[Path, int, str]:
    hasher = hashlib.sha256()
    size_bytes = 0
    max_bytes = get_settings().max_attachment_size_bytes
    stream.seek(0)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".upload", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            while chunk := stream.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Attachments must be {max_bytes} bytes or smaller.",
                    )
                hasher.update(chunk)
                temp_file.write(chunk)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    if temp_path is None or size_bytes == 0:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attachment upload cannot be empty.",
        )

    return temp_path, size_bytes, hasher.hexdigest()


def persist_matter_attachment(
    *,
    company_id: str,
    matter_id: str,
    attachment_id: str,
    filename: str,
    stream: BinaryIO,
) -> StoredDocument:
    return persist_workspace_attachment(
        company_id=company_id,
        workspace_id=matter_id,
        attachment_id=attachment_id,
        filename=filename,
        stream=stream,
    )


def persist_contract_attachment(
    *,
    company_id: str,
    contract_id: str,
    attachment_id: str,
    filename: str,
    stream: BinaryIO,
) -> StoredDocument:
    return persist_workspace_attachment(
        company_id=company_id,
        workspace_id=contract_id,
        attachment_id=attachment_id,
        filename=filename,
        stream=stream,
        namespace="contracts",
    )


def persist_workspace_attachment(
    *,
    company_id: str,
    workspace_id: str,
    attachment_id: str,
    filename: str,
    stream: BinaryIO,
    namespace: str = "matters",
) -> StoredDocument:
    safe_filename = sanitize_filename(filename)
    relative_path = (
        Path(company_id) / namespace / workspace_id / f"{attachment_id}-{safe_filename}"
    )
    storage_key = relative_path.as_posix()
    temp_path, size_bytes, sha256_hex = _write_stream_to_temp_file(stream)
    backend = _storage_backend()

    try:
        if backend == "local":
            target_path = (_document_root() / relative_path).resolve()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(target_path)
        else:
            bucket = _gcs_client().bucket(_gcs_bucket_name())
            blob = bucket.blob(_gcs_blob_name(storage_key))
            blob.upload_from_filename(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)

    return StoredDocument(
        storage_key=storage_key,
        size_bytes=size_bytes,
        sha256_hex=sha256_hex,
    )


def resolve_storage_path(storage_key: str) -> Path:
    relative_path = _validated_relative_path(storage_key)
    backend = _storage_backend()
    if backend == "local":
        root = _document_root()
        target_path = (root / relative_path).resolve()
        if os.path.commonpath([str(root), str(target_path)]) != str(root):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid storage key.",
            )
        return target_path

    cache_root = _document_cache_root()
    target_path = (cache_root / relative_path).resolve()
    if os.path.commonpath([str(cache_root), str(target_path)]) != str(cache_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    if target_path.exists():
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    blob = _gcs_client().bucket(_gcs_bucket_name()).blob(_gcs_blob_name(storage_key))
    if not blob.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment file is no longer available.",
        )
    blob.download_to_filename(str(target_path))
    return target_path
