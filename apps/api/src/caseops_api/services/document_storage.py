from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
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
_STORAGE_PART = re.compile(r"[A-Za-z0-9._-]+")
_WINDOWS_DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)
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
    # Keys are immutable POSIX object names, not URLs or host-specific paths.
    # Validate before Path can collapse empty/dot segments or Windows aliases.
    parts = storage_key.split("/")
    if not all(_portable_storage_part(part) for part in parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    return Path(*parts)


def _portable_storage_part(part: str) -> bool:
    return bool(
        _STORAGE_PART.fullmatch(part)
        and not part.endswith(".")
        and not _WINDOWS_DEVICE.match(part)
    )


def _checked_storage_path(root: Path, relative_path: Path) -> Path:
    """Reject redirects even within the root: they can cross tenant boundaries."""
    prefix = os.path.join(str(root), "")
    candidate = os.path.abspath(root / relative_path)
    if not candidate.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    lexical_path = Path(candidate)
    try:
        target = lexical_path.resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid storage key.",
        ) from exc
    if not str(target).startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage key.",
        )
    for current in (lexical_path, *lexical_path.parents):
        if current == root:
            break
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ) or (
            stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid storage key.",
            )
    return target


def _cleanup_temp_file(temp_path: Path, root: Path | None = None) -> None:
    if root is not None:
        try:
            _checked_storage_path(root, temp_path.relative_to(root))
        except HTTPException:
            # Never clean up through a replaced parent into another tenant.
            return
    temp_path.unlink(missing_ok=True)


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
        or not _portable_storage_part(segment)
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
    storage_root: Path | None = None,
) -> tuple[Path, int, str]:
    hasher = hashlib.sha256()
    size_bytes = 0
    max_bytes = get_settings().max_attachment_size_bytes
    stream.seek(0)

    temp_path: Path | None = None
    try:
        if directory is not None and storage_root is not None:
            directory = _checked_storage_path(storage_root, directory.relative_to(storage_root))
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
        if storage_root is not None:
            _checked_storage_path(storage_root, temp_path.relative_to(storage_root))
    except Exception:
        if temp_path is not None:
            _cleanup_temp_file(temp_path, storage_root)
        raise

    if temp_path is None or size_bytes == 0:
        if temp_path is not None:
            _cleanup_temp_file(temp_path, storage_root)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attachment upload cannot be empty.",
        )

    return temp_path, size_bytes, hasher.hexdigest()


def _place_local_temp_file(temp_path: Path, target_path: Path) -> None:
    """Atomically expose an upload even when temp and storage use different mounts."""

    root = _document_root()
    temp_path = _checked_storage_path(root, temp_path.relative_to(root))
    target_path = _checked_storage_path(root, target_path.relative_to(root))
    try:
        temp_path.replace(target_path)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    staging_path: Path | None = None
    try:
        _checked_storage_path(root, target_path.relative_to(root))
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
        _checked_storage_path(root, staging_path.relative_to(root))
        _checked_storage_path(root, target_path.relative_to(root))
        os.replace(staging_path, target_path)
        staging_path = None
    finally:
        if staging_path is not None:
            _cleanup_temp_file(staging_path, root)


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
    storage_key = "/".join(
        (safe_company_id, safe_namespace, safe_workspace_id, object_name)
    )
    relative_path = _validated_relative_path(storage_key)
    backend = _storage_backend()
    target_path: Path | None = None
    root: Path | None = None
    if backend == "local":
        root = _document_root()
        target_path = _checked_storage_path(root, relative_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path, size_bytes, sha256_hex = _write_stream_to_temp_file(
        stream,
        directory=target_path.parent if target_path is not None else None,
        # Keep the local staging basename short. The storage hierarchy uses
        # UUIDs and can legitimately approach the legacy Windows MAX_PATH
        # boundary even though the final object path itself remains portable.
        prefix=".caseops-" if target_path is not None else "caseops-",
        suffix="" if target_path is not None else ".upload",
        storage_root=root,
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
            assert target_path is not None and root is not None
            _place_local_temp_file(temp_path, target_path)
        else:
            bucket = _gcs_client().bucket(_gcs_bucket_name())
            blob = bucket.blob(_gcs_blob_name(storage_key))
            blob.upload_from_filename(str(temp_path))
    finally:
        _cleanup_temp_file(temp_path, root)

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
        target_path = _checked_storage_path(root, relative_path)
        target_path.unlink(missing_ok=True)
        return

    cache_root = _document_cache_root()
    cache_path = _checked_storage_path(cache_root, relative_path)
    cache_path.unlink(missing_ok=True)
    blob = _gcs_client().bucket(_gcs_bucket_name()).blob(_gcs_blob_name(storage_key))
    if blob.exists():
        blob.delete()


def resolve_storage_path(storage_key: str) -> Path:
    relative_path = _validated_relative_path(storage_key)
    backend = _storage_backend()
    if backend == "local":
        root = _document_root()
        target_path = _checked_storage_path(root, relative_path)
        return target_path

    cache_root = _document_cache_root()
    target_path = _checked_storage_path(cache_root, relative_path)
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
        _checked_storage_path(cache_root, relative_path)
        with tempfile.NamedTemporaryFile(
            suffix=".download",
            prefix=f".{target_path.name}.",
            dir=str(target_path.parent),
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        blob.download_to_filename(str(temp_path))
        _checked_storage_path(cache_root, temp_path.relative_to(cache_root))
        _checked_storage_path(cache_root, relative_path)
        temp_path.replace(target_path)
    except Exception:
        if temp_path is not None:
            _cleanup_temp_file(temp_path, cache_root)
        raise
    return target_path
