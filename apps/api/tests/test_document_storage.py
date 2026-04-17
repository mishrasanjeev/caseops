from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import HTTPException

from caseops_api.core.settings import get_settings
from caseops_api.services.document_storage import (
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

    assert stored.storage_key == "company-1/matters/matter-1/attachment-1-Proof_Bundle.pdf"
    assert (
        objects["tenant-docs/company-1/matters/matter-1/attachment-1-Proof_Bundle.pdf"]
        == b"matter evidence"
    )

    resolved_path = resolve_storage_path(stored.storage_key)
    assert resolved_path.exists()
    assert resolved_path.read_bytes() == b"matter evidence"

    del objects["tenant-docs/company-1/matters/matter-1/attachment-1-Proof_Bundle.pdf"]
    cached_path = resolve_storage_path(stored.storage_key)
    assert cached_path == resolved_path
    assert cached_path.read_bytes() == b"matter evidence"


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
