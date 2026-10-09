from __future__ import annotations

import hashlib
import io
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from caseops_api.services import document_storage as storage

KEY = "company-1/matters/workspace-1/attachment-1.pdf"
UNSAFE_KEYS = (
    "", ".", "..", "../file", "/file", "company/../file",
    "company/./file", "company//file", "company/file/",
    "C:/file", "C:file", "\\file", "\\\\server\\share\\file",
    "company\\..\\file", "company/file:stream", "company/file\x00.pdf",
    "company/%2e%2e/file", "company/%252e%252e/file",
    "company/%2ffile", "company/%5cfile", "company/file.",
    "company/file ", "company/CON", "company/nul.pdf", "company/LPT1.txt",
    "company/COM9", "company/CONIN$", "company/CONOUT$",
)


class Blob:
    def __init__(self, name, state):
        self.name, self.state = name, state

    def exists(self):
        self.state.calls.append(("exists", self.name))
        return self.name in self.state.objects

    def upload_from_filename(self, filename):
        self.state.calls.append(("upload", self.name))
        self.state.objects[self.name] = Path(filename).read_bytes()

    def download_to_filename(self, filename):
        self.state.calls.append(("download", self.name))
        Path(filename).write_bytes(self.state.objects[self.name])
        if self.state.after_download:
            self.state.after_download(Path(filename))

    def delete(self):
        self.state.calls.append(("delete", self.name))
        del self.state.objects[self.name]


@pytest.fixture
def configured_storage(monkeypatch, tmp_path):
    state = SimpleNamespace(objects={}, calls=[], after_download=None)
    settings = SimpleNamespace(
        document_storage_backend="local", document_storage_path=str(tmp_path / "local"),
        document_storage_cache_path=str(tmp_path / "cache"),
        document_storage_gcs_prefix="tenant-docs", document_storage_gcs_bucket="offline",
        max_attachment_size_bytes=1024,
    )
    bucket = SimpleNamespace(blob=lambda name: Blob(name, state))
    client = SimpleNamespace(bucket=lambda name: bucket)
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "_gcs_client", lambda: client)
    return settings, state


def upload(**overrides):
    args = dict(company_id="company-1", workspace_id="workspace-1",
                attachment_id="attachment-1", filename="Original Proof.pdf",
                stream=io.BytesIO(b"original bytes"))
    args.update(overrides)
    return storage.persist_workspace_attachment(**args)


def directory_link(link: Path, target: Path):
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Junctions exercise the same Windows reparse boundary without admin privileges.
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, check=False)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("backend", ["local", "gcs"])
@pytest.mark.parametrize("operation", ["read", "delete"])
@pytest.mark.parametrize("key", UNSAFE_KEYS)
def test_invalid_keys_are_rejected_before_filesystem_or_gcs_access(
    configured_storage, backend, operation, key, monkeypatch,
):
    settings, state = configured_storage
    settings.document_storage_backend = backend

    def unexpected_root():
        pytest.fail("Invalid key reached the filesystem")

    monkeypatch.setattr(storage, "_document_root", unexpected_root)
    monkeypatch.setattr(storage, "_document_cache_root", unexpected_root)
    action = storage.resolve_storage_path if operation == "read" else storage.delete_stored_document
    with pytest.raises(HTTPException) as caught:
        action(key)
    assert caught.value.status_code == 400
    assert caught.value.detail == "Invalid storage key."
    assert not state.calls and not state.objects


@pytest.mark.parametrize("backend", ["local", "gcs"])
@pytest.mark.parametrize("field", ["company_id", "workspace_id", "attachment_id", "namespace"])
@pytest.mark.parametrize(
    "value", ["../tenant", "C:tenant", "tenant\\other", "%2e%2e", "tenant.", "NUL"],
)
def test_upload_rejects_unsafe_segments_without_consuming_bytes(
    configured_storage, backend, field, value,
):
    settings, state = configured_storage
    settings.document_storage_backend = backend
    stream = io.BytesIO(b"unconsumed")
    with pytest.raises(HTTPException) as caught:
        upload(**{field: value}, stream=stream)
    assert caught.value.status_code == 400
    assert stream.tell() == 0
    assert not state.calls and not state.objects
    assert not Path(settings.document_storage_path).exists()


@pytest.mark.parametrize("backend", ["local", "gcs"])
@pytest.mark.parametrize(
    "namespace", ["matters", "contracts", "notices", "ip-documents", "audit-exports"],
)
def test_storage_contract_and_tenant_keys_remain_exact(configured_storage, backend, namespace):
    settings, state = configured_storage
    settings.document_storage_backend = backend
    first = upload(namespace=namespace)
    second = upload(namespace=namespace, company_id="company-2", stream=io.BytesIO(b"tenant two"))
    expected = KEY.replace("/matters/", f"/{namespace}/")
    assert first.storage_key == expected
    assert first.size_bytes == 14
    assert first.sha256_hex == hashlib.sha256(b"original bytes").hexdigest()
    assert storage.resolve_storage_path(first.storage_key).read_bytes() == b"original bytes"
    assert storage.resolve_storage_path(second.storage_key).read_bytes() == b"tenant two"
    storage.delete_stored_document(first.storage_key)
    assert storage.resolve_storage_path(second.storage_key).read_bytes() == b"tenant two"
    if backend == "gcs":
        assert set(state.objects) == {f"tenant-docs/{second.storage_key}"}


def test_legacy_gcs_blob_key_is_never_rewritten(configured_storage):
    settings, state = configured_storage
    settings.document_storage_backend = "gcs"
    key = "Tenant-A/contracts/Legacy-Workspace/ABC123_Original_Proof-2026.PDF"
    blob_key = f"tenant-docs/{key}"
    state.objects[blob_key] = b"immutable original"
    assert storage.resolve_storage_path(key).read_bytes() == b"immutable original"
    storage.delete_stored_document(key)
    assert not state.objects
    assert {name for _, name in state.calls} == {blob_key}


@pytest.mark.parametrize("backend", ["local", "gcs"])
@pytest.mark.parametrize("operation", ["read", "delete", "write"])
@pytest.mark.parametrize("destination", ["outside", "other-tenant", "same-tenant-alias"])
def test_directory_links_cannot_redirect_storage(
    configured_storage, tmp_path, backend, operation, destination,
):
    settings, state = configured_storage
    settings.document_storage_backend = backend
    root = Path(settings.document_storage_path if backend == "local"
                else settings.document_storage_cache_path)
    root.mkdir()
    target = (tmp_path / "outside" if destination == "outside"
              else root / ("company-2" if destination == "other-tenant" else "alias"))
    victim = target / "matters/workspace-1/attachment-1.pdf"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(b"victim")
    directory_link(root / "company-1", target)
    state.objects[f"tenant-docs/{KEY}"] = b"cloud original"
    if backend == "gcs" and operation == "write":
        # GCS writes do not touch or trust the local download cache.
        assert upload().storage_key == KEY
        assert victim.read_bytes() == b"victim"
        return
    with pytest.raises(HTTPException) as caught:
        if operation == "write":
            upload()
        elif operation == "read":
            storage.resolve_storage_path(KEY)
        else:
            storage.delete_stored_document(KEY)
    assert caught.value.status_code == 400
    assert victim.read_bytes() == b"victim"
    assert state.objects[f"tenant-docs/{KEY}"] == b"cloud original"
    assert not state.calls


@pytest.mark.parametrize("callback", ["before_store", "validate_temp_file"])
def test_upload_rechecks_parent_after_validation(configured_storage, tmp_path, callback):
    settings, _ = configured_storage
    root = Path(settings.document_storage_path)
    parent = root / "company-1/matters/workspace-1"
    other = root / "company-2/matters/workspace-1"
    other.mkdir(parents=True)
    victim = other / "attachment-1.pdf"
    victim.write_bytes(b"victim")

    def swap(_):
        parent.rename(parent.with_name("retained-staging"))
        directory_link(parent, other)

    with pytest.raises(HTTPException) as caught:
        upload(**{callback: swap})
    assert caught.value.status_code == 400
    assert victim.read_bytes() == b"victim"


def test_gcs_download_rechecks_parent_after_transport(configured_storage):
    settings, state = configured_storage
    settings.document_storage_backend = "gcs"
    root = Path(settings.document_storage_cache_path)
    other = root / "company-2/matters/workspace-1"
    other.mkdir(parents=True)
    victim = other / "attachment-1.pdf"
    victim.write_bytes(b"victim")
    state.objects[f"tenant-docs/{KEY}"] = b"cloud original"

    def swap(temp_path):
        parent = temp_path.parent
        parent.rename(parent.with_name("retained-staging"))
        directory_link(parent, other)

    state.after_download = swap
    with pytest.raises(HTTPException) as caught:
        storage.resolve_storage_path(KEY)
    assert caught.value.status_code == 400
    assert victim.read_bytes() == b"victim"
    assert state.objects[f"tenant-docs/{KEY}"] == b"cloud original"


@pytest.mark.parametrize("backend,operation", [
    ("local", "read"), ("local", "delete"), ("local", "write"),
    ("gcs", "read"), ("gcs", "delete"),
])
def test_hard_links_cannot_alias_another_tenants_bytes(configured_storage, backend, operation):
    settings, state = configured_storage
    settings.document_storage_backend = backend
    root = Path(settings.document_storage_path if backend == "local"
                else settings.document_storage_cache_path)
    victim = root / "company-2/victim.pdf"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(b"victim")
    target = root / KEY
    target.parent.mkdir(parents=True)
    target.hardlink_to(victim)
    state.objects[f"tenant-docs/{KEY}"] = b"cloud original"
    with pytest.raises(HTTPException) as caught:
        if operation == "write":
            upload()
        elif operation == "read":
            storage.resolve_storage_path(KEY)
        else:
            storage.delete_stored_document(KEY)
    assert caught.value.status_code == 400
    assert victim.read_bytes() == b"victim"
    assert not state.calls


@pytest.mark.parametrize("backend", ["local", "gcs"])
def test_linked_leaf_is_rejected_even_when_target_is_inside_root(configured_storage, backend):
    settings, state = configured_storage
    settings.document_storage_backend = backend
    root = Path(settings.document_storage_path if backend == "local"
                else settings.document_storage_cache_path)
    target = root / KEY
    target.parent.mkdir(parents=True)
    other = root / "company-2"
    other.mkdir()
    directory_link(target, other)
    with pytest.raises(HTTPException) as caught:
        storage.resolve_storage_path(KEY)
    assert caught.value.status_code == 400
    assert not state.calls


def test_sibling_root_prefix_is_not_containment(configured_storage, monkeypatch, tmp_path):
    settings, _ = configured_storage
    root = Path(settings.document_storage_path)
    root.mkdir()
    sibling = root.with_name(root.name + "-other-tenant")
    sibling.mkdir()
    directory_link(root / "company-1", sibling)
    with pytest.raises(HTTPException) as caught:
        storage.resolve_storage_path(KEY)
    assert caught.value.status_code == 400


@pytest.mark.parametrize("backend", ["local", "gcs"])
@pytest.mark.parametrize("filename", [
    "../secret.pdf", "/absolute/secret.pdf", "C:\\Windows\\secret.pdf",
    "\\\\server\\share\\secret.pdf", "..%2fsecret.pdf", "..%252fsecret.pdf",
    "CON.pdf", "folder\\..\\secret.pdf",
])
def test_display_filename_cannot_change_storage_identity(configured_storage, backend, filename):
    settings, _ = configured_storage
    settings.document_storage_backend = backend
    stored = upload(filename=filename)
    assert stored.storage_key == KEY
    assert storage.resolve_storage_path(KEY).read_bytes() == b"original bytes"


@pytest.mark.parametrize("backend", ["local", "gcs"])
@pytest.mark.parametrize("content,expected_status", [(b"", 400), (b"x" * 1025, 413)])
def test_size_and_empty_rejection_keep_cleanup_contract(
    configured_storage, backend, content, expected_status, tmp_path, monkeypatch,
):
    settings, state = configured_storage
    settings.document_storage_backend = backend
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(storage.tempfile, "tempdir", str(staging))
    with pytest.raises(HTTPException) as caught:
        upload(stream=io.BytesIO(content))
    assert caught.value.status_code == expected_status
    assert not state.calls and not state.objects
    assert not list(staging.iterdir())
    assert not list(Path(settings.document_storage_path).rglob(".caseops-*"))


def test_existing_two_argument_placement_adapters_remain_compatible(
    configured_storage, monkeypatch,
):
    place = storage._place_local_temp_file
    observed = []

    def adapter(temp, target):
        observed.append((temp, target))
        return place(temp, target)

    monkeypatch.setattr(storage, "_place_local_temp_file", adapter)
    assert upload().storage_key == KEY
    assert len(observed) == 1
    assert storage.resolve_storage_path(KEY).read_bytes() == b"original bytes"
