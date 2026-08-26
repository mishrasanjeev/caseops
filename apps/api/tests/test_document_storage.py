from __future__ import annotations

import errno
import io
from pathlib import Path

import pytest
from fastapi import HTTPException

from caseops_api.core.settings import get_settings
from caseops_api.services.document_storage import (
    delete_stored_document,
    persist_workspace_attachment,
    resolve_storage_path,
)


class _FakeBlob:
    def __init__(self, name: str, objects: dict[str, bytes]) -> None:
        self.name = name
        self._objects = objects

    def upload_from_filename(self, filename: str) -> None:
        self._objects[self.name] = Path(filename).read_bytes()

    def exists(self) -> bool:
        return self.name in self._objects

    def download_to_filename(self, filename: str) -> None:
        Path(filename).write_bytes(self._objects[self.name])

    def delete(self) -> None:
        self._objects.pop(self.name, None)


class _FakeBucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(name, self._objects)


class _FakeStorageClient:
    def __init__(self, objects: dict[str, bytes], project: str | None) -> None:
        self._objects = objects
        self.project = project

    def bucket(self, name: str) -> _FakeBucket:
        assert name == "caseops-documents"
        return _FakeBucket(self._objects)


@pytest.fixture
def reset_storage_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_gcs_backend_persists_and_materializes_cached_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    objects: dict[str, bytes] = {}
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET", "caseops-documents")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_PREFIX", "tenant-docs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_CACHE_PATH", (tmp_path / "cache").as_posix())
    monkeypatch.setenv("CASEOPS_GCP_PROJECT_ID", "caseops-dev")
    monkeypatch.setattr(
        "caseops_api.services.document_storage.storage.Client",
        lambda project=None: _FakeStorageClient(objects, project),
    )

    stored = persist_workspace_attachment(
        company_id="company-1",
        workspace_id="matter-1",
        attachment_id="attachment-1",
        filename="Proof Bundle.pdf",
        stream=io.BytesIO(b"matter evidence"),
    )

    assert stored.storage_key == "company-1/matters/matter-1/attachment-1.pdf"
    assert objects["tenant-docs/company-1/matters/matter-1/attachment-1.pdf"] == b"matter evidence"

    resolved_path = resolve_storage_path(stored.storage_key)
    assert resolved_path.exists()
    assert resolved_path.read_bytes() == b"matter evidence"

    del objects["tenant-docs/company-1/matters/matter-1/attachment-1.pdf"]
    cached_path = resolve_storage_path(stored.storage_key)
    assert cached_path == resolved_path
    assert cached_path.read_bytes() == b"matter evidence"


def test_gcs_backend_validates_temporary_bytes_before_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    objects: dict[str, bytes] = {}
    observed: dict[str, object] = {}
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET", "caseops-documents")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_PREFIX", "tenant-docs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_CACHE_PATH", (tmp_path / "cache").as_posix())
    monkeypatch.setattr(
        "caseops_api.services.document_storage.storage.Client",
        lambda project=None: _FakeStorageClient(objects, project),
    )

    def validate(path: Path) -> None:
        observed["path"] = path
        observed["exists_during_validation"] = path.exists()
        observed["contents"] = path.read_bytes()
        observed["objects_before_validation"] = dict(objects)

    persist_workspace_attachment(
        company_id="company-1",
        workspace_id="matter-1",
        attachment_id="attachment-1",
        filename="proof.txt",
        stream=io.BytesIO(b"scan these exact bytes"),
        validate_temp_file=validate,
    )

    assert observed["exists_during_validation"] is True
    assert observed["contents"] == b"scan these exact bytes"
    assert observed["objects_before_validation"] == {}
    assert not Path(observed["path"]).exists()
    assert next(iter(objects.values())) == b"scan these exact bytes"


def test_gcs_backend_does_not_upload_when_temporary_validation_rejects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    objects: dict[str, bytes] = {}
    observed_path: Path | None = None
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET", "caseops-documents")
    monkeypatch.setattr(
        "caseops_api.services.document_storage.storage.Client",
        lambda project=None: _FakeStorageClient(objects, project),
    )

    def reject(path: Path) -> None:
        nonlocal observed_path
        observed_path = path
        assert path.read_bytes() == b"rejected bytes"
        raise HTTPException(status_code=400, detail="infected")

    with pytest.raises(HTTPException, match="infected"):
        persist_workspace_attachment(
            company_id="company-1",
            workspace_id="matter-1",
            attachment_id="attachment-1",
            filename="malware.txt",
            stream=io.BytesIO(b"rejected bytes"),
            validate_temp_file=reject,
        )

    assert observed_path is not None
    assert not observed_path.exists()
    assert objects == {}


def test_delete_stored_document_removes_gcs_blob_and_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    objects: dict[str, bytes] = {}
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET", "caseops-documents")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_PREFIX", "tenant-docs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_CACHE_PATH", (tmp_path / "cache").as_posix())
    monkeypatch.setattr(
        "caseops_api.services.document_storage.storage.Client",
        lambda project=None: _FakeStorageClient(objects, project),
    )

    stored = persist_workspace_attachment(
        company_id="company-1",
        workspace_id="matter-1",
        attachment_id="attachment-1",
        filename="quarantine.pdf",
        stream=io.BytesIO(b"%PDF-1.4 clean enough"),
    )
    cached_path = resolve_storage_path(stored.storage_key)
    assert cached_path.exists()
    assert objects

    delete_stored_document(stored.storage_key)

    assert not cached_path.exists()
    assert objects == {}


def test_persist_rejects_unsafe_storage_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_PATH", (tmp_path / "documents").as_posix())

    with pytest.raises(HTTPException) as exc_info:
        persist_workspace_attachment(
            company_id="../company",
            workspace_id="matter-1",
            attachment_id="attachment-1",
            filename="proof.pdf",
            stream=io.BytesIO(b"%PDF-1.4"),
        )

    assert exc_info.value.status_code == 400
    assert "company id" in exc_info.value.detail.lower()


def test_local_storage_key_does_not_embed_a_long_original_filename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_PATH", (tmp_path / "documents").as_posix())

    stored = persist_workspace_attachment(
        company_id="company-1",
        workspace_id="matter-1",
        attachment_id="attachment-1",
        filename=f"{'payment-recovery-notice-' * 12}.txt",
        stream=io.BytesIO(b"portable local storage path"),
    )

    assert stored.storage_key == "company-1/matters/matter-1/attachment-1.txt"
    assert resolve_storage_path(stored.storage_key).read_bytes() == b"portable local storage path"


def test_local_storage_handles_cross_filesystem_temp_move_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    storage_root = tmp_path / "documents"
    observed_temp_path: Path | None = None
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_PATH", storage_root.as_posix())

    def reject_cross_filesystem_replace(source: Path, target: Path) -> Path:
        nonlocal observed_temp_path
        observed_temp_path = source
        raise OSError(errno.EXDEV, "Invalid cross-device link", source, target)

    monkeypatch.setattr(Path, "replace", reject_cross_filesystem_replace)

    stored = persist_workspace_attachment(
        company_id="company-1",
        workspace_id="matter-1",
        attachment_id="attachment-1",
        filename="court-order.txt",
        stream=io.BytesIO(b"cross-volume court order"),
    )

    stored_path = resolve_storage_path(stored.storage_key)
    assert stored_path.read_bytes() == b"cross-volume court order"
    assert observed_temp_path is not None
    assert not observed_temp_path.exists()
    assert list(stored_path.parent.glob("*.staging")) == []


def test_local_storage_does_not_mask_non_cross_filesystem_move_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    observed_temp_path: Path | None = None
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_PATH", (tmp_path / "documents").as_posix())

    def reject_replace(source: Path, target: Path) -> Path:
        nonlocal observed_temp_path
        observed_temp_path = source
        raise OSError(errno.EACCES, "Permission denied", source, target)

    monkeypatch.setattr(Path, "replace", reject_replace)

    with pytest.raises(OSError) as exc_info:
        persist_workspace_attachment(
            company_id="company-1",
            workspace_id="matter-1",
            attachment_id="attachment-1",
            filename="court-order.txt",
            stream=io.BytesIO(b"must not be persisted"),
        )

    assert exc_info.value.errno == errno.EACCES
    assert observed_temp_path is not None
    assert not observed_temp_path.exists()
    assert [path for path in (tmp_path / "documents").rglob("*") if path.is_file()] == []


def test_resolve_storage_path_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_PATH", (tmp_path / "documents").as_posix())

    with pytest.raises(HTTPException) as exc_info:
        resolve_storage_path("../secrets.txt")

    assert exc_info.value.status_code == 400


def test_gcs_backend_raises_not_found_for_missing_blob(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_storage_settings,
) -> None:
    objects: dict[str, bytes] = {}
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET", "caseops-documents")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_GCS_PREFIX", "tenant-docs")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_CACHE_PATH", (tmp_path / "cache").as_posix())
    monkeypatch.setattr(
        "caseops_api.services.document_storage.storage.Client",
        lambda project=None: _FakeStorageClient(objects, project),
    )

    with pytest.raises(HTTPException) as exc_info:
        resolve_storage_path("company-1/matters/matter-1/missing.txt")

    assert exc_info.value.status_code == 404
