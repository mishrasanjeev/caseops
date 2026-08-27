from __future__ import annotations

import errno
import hashlib
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, status
from google.cloud import storage

from caseops_api.core.settings import get_settings

_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")
_STORAGE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
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


def _storage_object_name(attachment_id: str, filename: str) -> str:
    """Build a portable object name without duplicating the display filename.

    Attachment records retain the sanitized original filename. Embedding that
    value again in the storage key can exceed Windows' 260-character path
    boundary once tenant and workspace identifiers are included.
    """

    raw_suffix = Path(Path(filename).name.strip()).suffix
    suffix = _FILENAME_SANITIZER.sub("_", raw_suffix)[:16]
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix.lstrip('_')}"
    return f"{attachment_id}{suffix}"


def _safe_storage_segment(value: str, label: str) -> str:
    segment = str(value or "").strip()
    if (
        not segment
        or segment in {".", ".."}
        or "/" in segment
        or "\\" in segment
        or not _STORAGE_SEGMENT.fullmatch(segment)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label} for document storage.",
        )
    return segment


def _write_stream_to_temp_file(
    stream: BinaryIO,
    *,
    directory: Path | None = None,
    prefix: str = "caseops-",
    suffix: str = ".upload",
) -> tuple[Path, int, str]:
    hasher = hashlib.sha256()
    size_bytes = 0
    max_bytes = get_settings().max_attachment_size_bytes
    stream.seek(0)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix=prefix,
            dir=str(directory) if directory is not None else None,
            delete=False,
        ) as temp_file:
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
            temp_file.flush()
            os.fsync(temp_file.fileno())
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


def _place_local_temp_file(temp_path: Path, target_path: Path) -> None:
    """Atomically expose an upload even when temp and storage use different mounts."""

    try:
        temp_path.replace(target_path)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    staging_path: Path | None = None
    try:
        with temp_path.open("rb") as source_file:
            with tempfile.NamedTemporaryFile(
                prefix=".caseops-",
                dir=str(target_path.parent),
                delete=False,
            ) as staging_file:
                staging_path = Path(staging_file.name)
                while chunk := source_file.read(1024 * 1024):
                    staging_file.write(chunk)
                staging_file.flush()
                os.fsync(staging_file.fileno())
        os.replace(staging_path, target_path)
        staging_path = None
    finally:
        if staging_path is not None:
            staging_path.unlink(missing_ok=True)


def persist_matter_attachment(
    *,
    company_id: str,
    matter_id: str,
    attachment_id: str,
    filename: str,
    stream: BinaryIO,
    before_store: Callable[[int], None] | None = None,
    validate_temp_file: Callable[[Path], None] | None = None,
) -> StoredDocument:
    return persist_workspace_attachment(
        company_id=company_id,
        workspace_id=matter_id,
        attachment_id=attachment_id,
        filename=filename,
        stream=stream,
        before_store=before_store,
        validate_temp_file=validate_temp_file,
    )


def persist_contract_attachment(
    *,
    company_id: str,
    contract_id: str,
    attachment_id: str,
    filename: str,
    stream: BinaryIO,
    validate_temp_file: Callable[[Path], None] | None = None,
) -> StoredDocument:
    return persist_workspace_attachment(
        company_id=company_id,
        workspace_id=contract_id,
        attachment_id=attachment_id,
        filename=filename,
        stream=stream,
        namespace="contracts",
        validate_temp_file=validate_temp_file,
    )


def persist_workspace_attachment(
    *,
    company_id: str,
    workspace_id: str,
    attachment_id: str,
    filename: str,
    stream: BinaryIO,
    namespace: str = "matters",
    before_store: Callable[[int], None] | None = None,
    validate_temp_file: Callable[[Path], None] | None = None,
) -> StoredDocument:
    safe_company_id = _safe_storage_segment(company_id, "company id")
    safe_namespace = _safe_storage_segment(namespace, "storage namespace")
    safe_workspace_id = _safe_storage_segment(workspace_id, "workspace id")
    safe_attachment_id = _safe_storage_segment(attachment_id, "attachment id")
    object_name = _storage_object_name(safe_attachment_id, filename)
    relative_path = (
        Path(safe_company_id)
        / safe_namespace
        / safe_workspace_id
        / object_name
    )
    backend = _storage_backend()
    storage_key = relative_path.as_posix()
    target_path: Path | None = None
    if backend == "local":
        root = _document_root()
        target_path = (root / relative_path).resolve()
        if os.path.commonpath([str(root), str(target_path)]) != str(root):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid storage key.",
            )
        target_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path, size_bytes, sha256_hex = _write_stream_to_temp_file(
        stream,
        directory=target_path.parent if target_path is not None else None,
        # Keep the local staging basename short. The storage hierarchy uses
        # UUIDs and can legitimately approach the legacy Windows MAX_PATH
        # boundary even though the final object path itself remains portable.
        prefix=".caseops-" if target_path is not None else "caseops-",
        suffix="" if target_path is not None else ".upload",
    )

    try:
        if before_store is not None:
            before_store(size_bytes)
        if validate_temp_file is not None:
            # Security validation belongs on the bytes already materialized
            # for persistence.  Scanning this temporary file before either a
            # local move or a GCS upload avoids storing rejected content and
            # avoids an immediate GCS download solely to scan the same bytes.
            validate_temp_file(temp_path)
        if backend == "local":
            assert target_path is not None
            _place_local_temp_file(temp_path, target_path)
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


def delete_stored_document(storage_key: str) -> None:
    """Best-effort removal for a persisted document.

    Upload routes call this when a post-persistence guard, such as the
    virus scanner, rejects the file. The previous cleanup path unlinked
    only the local materialized path returned by ``resolve_storage_path``;
    for GCS that left the just-uploaded blob behind in the bucket.
    """
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
        target_path.unlink(missing_ok=True)
        return

    cache_root = _document_cache_root()
    cache_path = (cache_root / relative_path).resolve()
    if os.path.commonpath([str(cache_root), str(cache_path)]) != str(cache_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    cache_path.unlink(missing_ok=True)
    blob = _gcs_client().bucket(_gcs_bucket_name()).blob(_gcs_blob_name(storage_key))
    if blob.exists():
        blob.delete()


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
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".download",
            prefix=f".{target_path.name}.",
            dir=str(target_path.parent),
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        blob.download_to_filename(str(temp_path))
        temp_path.replace(target_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return target_path
