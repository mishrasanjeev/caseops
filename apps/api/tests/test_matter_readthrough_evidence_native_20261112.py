"""Native owned-file fences and portable Windows metadata counterexamples."""

import ctypes
import errno
import hashlib
import os
import stat
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests import test_matter_readthrough_evidence_20261028 as evidence


def _native_values(**changes):
    return {
        "creation_ns": 100,
        "change_ns": 200,
        "write_ns": 300,
        "volume": 41,
        "file_id": 53,
        "size": 11,
        "links": 1,
        "directory": False,
        "delete_pending": False,
        "attributes": 32,
        "reparse_tag": 0,
        **changes,
    }


def _raw_stat(native, *, named=False, **changes):
    return SimpleNamespace(
        **{
            "st_dev": native["volume"],
            "st_ino": native["file_id"],
            "st_uid": 0,
            "st_gid": 0,
            "st_mode": stat.S_IFREG | 0o600,
            "st_nlink": native["links"],
            "st_size": native["size"],
            "st_mtime_ns": native["write_ns"],
            "st_ctime_ns": native["creation_ns"] if named else native["change_ns"],
            "st_birthtime_ns": native["creation_ns"],
            "st_file_attributes": native["attributes"],
            "st_reparse_tag": native["reparse_tag"],
            **changes,
        }
    )


def test_windows_snapshots_retain_creation_and_change_without_ctime_tolerance():
    native = _native_values()
    named_raw, held_raw = _raw_stat(native, named=True), _raw_stat(native)
    assert not evidence._named_equal(named_raw, held_raw, windows=True)
    named = evidence._windows_snapshot(named_raw, native)
    held = evidence._windows_snapshot(held_raw, native)
    assert evidence._named_equal(named, held, windows=True)
    assert evidence._meta(named) == evidence._meta(held)
    assert named.st_birthtime_ns == 100 and named.st_ctime_ns == 200
    assert named.raw.st_ctime_ns == 100 and held.raw.st_ctime_ns == 200
    assert not evidence._named_equal(named, held_raw, windows=True)


@pytest.mark.parametrize(
    "field",
    [
        "creation_ns",
        "change_ns",
        "write_ns",
        "volume",
        "file_id",
        "size",
        "links",
        "attributes",
        "st_uid",
        "st_gid",
        "st_mode",
    ],
)
def test_windows_each_independent_canonical_difference_remains_visible(field):
    native = _native_values()
    original = evidence._windows_snapshot(_raw_stat(native), native)
    altered_native = dict(native)
    raw_changes = {}
    if field.startswith("st_"):
        raw_changes[field] = getattr(original, field) ^ 1
    else:
        altered_native[field] += 1
    altered = evidence._windows_snapshot(
        _raw_stat(altered_native, named=True, **raw_changes), altered_native
    )
    assert not evidence._named_equal(altered, original, windows=True)
    assert evidence._meta(altered) != evidence._meta(original)
    if field in {"creation_ns", "volume", "file_id"}:
        identity = evidence._identity(original)
        assert any(getattr(altered, key) != getattr(original, key) for key in identity)
    if field == "links":
        with pytest.raises(ValueError, match="PLAN_EVIDENCE_FILE"):
            evidence._regular(altered)


@pytest.mark.parametrize(
    "field",
    [
        "st_dev",
        "st_ino",
        "st_size",
        "st_nlink",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_birthtime_ns",
        "st_file_attributes",
        "st_reparse_tag",
    ],
)
def test_windows_raw_native_disagreement_is_not_normalized_away(field):
    native = _native_values()
    raw = _raw_stat(native)
    setattr(raw, field, getattr(raw, field) + 17)
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_CHANGED"):
        evidence._windows_snapshot(raw, native)


@pytest.mark.parametrize("kind", ["reparse_attribute", "reparse_tag", "delete_pending"])
def test_windows_native_reparse_and_deleted_handles_are_refused(kind):
    changes = {
        "reparse_attribute": {"attributes": 32 | evidence._REPARSE},
        "reparse_tag": {"reparse_tag": 0xA0000003},
        "delete_pending": {"delete_pending": True},
    }[kind]
    native = _native_values(**changes)
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_FILE|PLAN_EVIDENCE_CHANGED"):
        evidence._windows_snapshot(_raw_stat(native), native)


def test_windows_zero_named_device_still_requires_native_volume_and_full_file_id():
    native = _native_values(file_id=2**100 + 53)
    named = evidence._windows_snapshot(_raw_stat(native, named=True, st_dev=0), native)
    held = evidence._windows_snapshot(_raw_stat(native), native)
    assert evidence._named_equal(named, held, windows=True)
    assert not evidence._named_equal(replace(named, native_volume=42), held, windows=True)
    assert not evidence._named_equal(replace(named, native_file_id=53), held, windows=True)


def test_posix_snapshot_and_injected_fstat_protocol_are_unchanged(monkeypatch):
    monkeypatch.setattr(evidence, "_WINDOWS", False)
    value = _raw_stat(_native_values())
    calls = []

    def fstat(fd):
        calls.append(fd)
        return value

    observed = evidence._fstat(79, io=SimpleNamespace(fstat=fstat))
    assert observed is value and calls == [79]
    assert evidence._meta(value) == tuple(getattr(value, key) for key in evidence._FIELDS)
    assert evidence._identity(value) == evidence._IDENTITY


@pytest.mark.parametrize("failure", ["none", "create", "query", "close", "replacement", "reparse"])
def test_windows_named_attribute_handle_is_nofollow_and_closed(monkeypatch, failure):
    native = _native_values()
    events = []

    class Path:
        def lstat(self):
            return _raw_stat(native, named=True)

        def __fspath__(self):
            return "C:\\owned\\plan-captured.json"

    def create(*args):
        events.append(("create", args))
        return ctypes.c_void_p(-1).value if failure == "create" else 83

    def query(handle):
        events.append(("query", handle))
        if failure == "query":
            raise OSError("native query refused")
        if failure == "replacement":
            return {**native, "file_id": native["file_id"] + 1}
        if failure == "reparse":
            return {**native, "attributes": native["attributes"] | evidence._REPARSE}
        return native

    def close(handle):
        events.append(("close", handle))
        return failure != "close"

    api = SimpleNamespace(
        create=create,
        close=close,
        ctypes=SimpleNamespace(
            c_void_p=ctypes.c_void_p,
            get_last_error=lambda: 5,
            WinError=lambda code: OSError(code, "native metadata handle refused"),
        ),
    )
    monkeypatch.setattr(evidence, "_WINDOWS", True)
    monkeypatch.setattr(evidence, "_windows_api", lambda: api)
    monkeypatch.setattr(evidence, "_windows_file_info", query)
    if failure == "none":
        snapshot = evidence._lstat(Path())
        assert snapshot.st_birthtime_ns == 100 and snapshot.st_ctime_ns == 200
    elif failure in {"replacement", "reparse"}:
        with pytest.raises(ValueError, match="PLAN_EVIDENCE_CHANGED|PLAN_EVIDENCE_FILE"):
            evidence._lstat(Path())
    else:
        with pytest.raises(OSError):
            evidence._lstat(Path())
    name, access, share, security, disposition, flags, template = events[0][1]
    assert name == "\\\\?\\C:\\owned\\plan-captured.json"
    assert (access, share, security, disposition, template) == (0x80, 7, None, 3, None)
    assert flags == 0x00200000 | 0x02000000
    assert [event[0] for event in events].count("close") == (failure != "create")


@pytest.mark.parametrize(
    "mutation", ["none", "creation", "write", "change", "attributes", "tag", "query_refusal"]
)
def test_windows_native_snapshot_rejects_interquery_changes_without_retry(monkeypatch, mutation):
    epoch = 116444736000000000
    events = []

    def basic():
        return SimpleNamespace(
            creation=epoch + 1, access=epoch, write=epoch + 3, change=epoch + 2,
            attributes=32,
        )

    def query(handle, kind, value, _size):
        events.append(kind)
        if mutation == "query_refusal" and kind == 9:
            return False
        if kind == 9 and mutation == "tag":
            value.attributes += 1
        if kind == 0 and len(events) > 1 and mutation in {
            "creation", "write", "change", "attributes"
        }:
            setattr(value, mutation, getattr(value, mutation) + 1)
        return True

    api = SimpleNamespace(
        query=query,
        Basic=basic,
        Standard=lambda: SimpleNamespace(size=11, links=1, directory=0, delete_pending=0),
        Identity=lambda: SimpleNamespace(volume=41, file_id=(2**100 + 53).to_bytes(16, "little")),
        Tag=lambda: SimpleNamespace(attributes=32, reparse_tag=0),
        ctypes=SimpleNamespace(
            byref=lambda value: value,
            sizeof=lambda _value: 40,
            get_last_error=lambda: 5,
            WinError=lambda code: OSError(code, "native metadata query refused"),
        ),
    )
    monkeypatch.setattr(evidence, "_windows_api", lambda: api)
    if mutation == "none":
        native = evidence._windows_file_info(83)
        assert native == _native_values(file_id=2**100 + 53)
    elif mutation == "query_refusal":
        with pytest.raises(OSError, match="native metadata query refused"):
            evidence._windows_file_info(83)
    else:
        with pytest.raises(ValueError, match="PLAN_EVIDENCE_CHANGED"):
            evidence._windows_file_info(83)
    assert events == ([0, 1, 18, 9] if mutation == "query_refusal" else [0, 1, 18, 9, 0])


class _IO:
    def __init__(self):
        self.fd = None
        self.flags = None
        self.reads = 0
        self.closed = []

    def __getattr__(self, key):
        return getattr(os, key)

    def open(self, path, flags, *args):
        self.fd = os.open(path, flags, *args)
        self.flags = flags
        return self.fd

    def read(self, fd, size):
        self.reads += 1
        return os.read(fd, size)

    def close(self, fd):
        os.close(fd)
        self.closed.append(fd)


def _closed(io):
    assert io.closed == [io.fd]
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    assert failure.value.errno == errno.EBADF


def _set_windows_times(fd, **changes):
    import msvcrt

    api = evidence._windows_api()
    basic = api.Basic()
    for key, value in changes.items():
        setattr(basic, key, value // 100 + 116444736000000000)
    setter = ctypes.WinDLL("kernel32", use_last_error=True).SetFileInformationByHandle
    setter.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)
    setter.restype = ctypes.c_int
    if not setter(msvcrt.get_osfhandle(fd), 0, ctypes.byref(basic), ctypes.sizeof(basic)):
        raise ctypes.WinError(ctypes.get_last_error())


def test_native_capture_load_retains_distinct_windows_birth_and_change_times(
    tmp_path, record_property
):
    path = evidence._path(tmp_path)

    class IO(_IO):
        def open(self, *args):
            fd = super().open(*args)
            if os.name == "nt":
                _set_windows_times(fd, creation=1_600_000_000_000_000_000)
            return fd

    writer = IO()
    reference = evidence.capture_plan(path, evidence._raw(), io=writer)
    _closed(writer)
    expected_flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    assert writer.flags == expected_flags and writer.reads == 0
    reader = _IO()
    loaded = evidence.load_captured_plan(path, reference, io=reader)
    _closed(reader)
    assert reader.flags == (
        os.O_RDONLY | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    assert loaded == evidence._raw()
    named = evidence._lstat(path)
    record_property("native_metadata_platform", os.name)
    if os.name == "nt":
        assert named.st_birthtime_ns == 1_600_000_000_000_000_000
        assert named.st_birthtime_ns != named.st_ctime_ns
        record_property("native_birthtime_ns", named.st_birthtime_ns)
        record_property("native_change_ns", named.st_ctime_ns)
    else:
        assert evidence._meta(named) == evidence._meta(path.lstat())
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == reference["sha256"]
    assert len(content) == reference["sizeBytes"] and content.endswith(b"\n")
    if os.name == "nt":
        import msvcrt

        class LateChange(_IO):
            def __init__(self, field):
                super().__init__()
                self.field = field
                self.mutator = None
                self.changed = False

            def read(self, fd, size):
                if not self.changed:
                    self.mutator = os.open(path, os.O_WRONLY)
                    handle = msvcrt.get_osfhandle(self.mutator)
                    before = evidence._windows_file_info(handle)
                    target = before[f"{self.field}_ns"] + 10_000_000_000
                    other = "change" if self.field == "creation" else "creation"
                    _set_windows_times(
                        self.mutator,
                        **{self.field: target, other: before[f"{other}_ns"]},
                    )
                    after = evidence._windows_file_info(handle)
                    assert after[f"{self.field}_ns"] == target
                    assert after[f"{other}_ns"] == before[f"{other}_ns"]
                    assert after["write_ns"] == before["write_ns"]
                    assert after["size"] == before["size"]
                    self.changed = True
                return super().read(fd, size)

        for field in ("creation", "change"):
            late_reader = LateChange(field)
            try:
                with pytest.raises(ValueError, match="PLAN_EVIDENCE_CHANGED"):
                    evidence.load_captured_plan(path, reference, io=late_reader)
                _closed(late_reader)
                assert late_reader.changed
            finally:
                if late_reader.mutator is not None:
                    os.close(late_reader.mutator)
        record_property("native_independent_timestamp_denials", "creation,change")


@pytest.mark.parametrize("phase", ["capture", "reader"])
@pytest.mark.parametrize(
    "field", ["st_ino", "st_size", "st_nlink", "st_mode", "st_mtime_ns", "st_ctime_ns"]
)
def test_native_capture_and_reader_do_not_bypass_injected_fstat(tmp_path, phase, field):
    path = evidence._path(tmp_path)
    reference = None
    if phase == "reader":
        reference = evidence.capture_plan(path, evidence._raw())

    class Altered:
        def __init__(self, value):
            self.value = value

        def __getattr__(self, key):
            result = getattr(self.value, key)
            return result + 17 if key == field else result

    class IO(_IO):
        armed = phase == "reader"

        def fstat(self, fd):
            value = os.fstat(fd)
            return Altered(value) if self.armed else value

        def fsync(self, fd):
            os.fsync(fd)
            self.armed = True

    io = IO()
    expected = "PLAN_EVIDENCE_CHANGED"
    if not evidence._WINDOWS:
        if field == "st_nlink":
            expected = "PLAN_EVIDENCE_FILE"
        elif phase == "reader" and field == "st_size":
            expected = "PLAN_EVIDENCE_EXTENT"
    with pytest.raises(ValueError, match=f"^{expected}$"):
        if phase == "capture":
            evidence.capture_plan(path, evidence._raw(), io=io)
        else:
            evidence.load_captured_plan(path, reference, io=io)
    _closed(io)
    assert io.reads == 0


@pytest.mark.parametrize("phase", ["capture", "reader"])
def test_native_hardlink_added_during_io_refuses_acceptance_and_closes(tmp_path, phase):
    path, alias = evidence._path(tmp_path), tmp_path / "second-owned-link"
    reference = None
    if phase == "reader":
        reference = evidence.capture_plan(path, evidence._raw())

    class IO(_IO):
        linked = False

        def fsync(self, fd):
            os.fsync(fd)
            os.link(path, alias)
            self.linked = True

        def read(self, fd, size):
            if not self.linked:
                os.link(path, alias)
                self.linked = True
            return super().read(fd, size)

    io = IO()
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_FILE|PLAN_EVIDENCE_CHANGED"):
        if phase == "capture":
            evidence.capture_plan(path, evidence._raw(), io=io)
        else:
            evidence.load_captured_plan(path, reference, io=io)
    _closed(io)
    assert io.linked and path.stat().st_nlink == alias.stat().st_nlink == 2


def test_native_preexisting_hardlink_refuses_before_read_and_excl_never_truncates(tmp_path):
    path, alias = evidence._path(tmp_path), tmp_path / "second-owned-link"
    reference = evidence.capture_plan(path, evidence._raw())
    original = path.read_bytes()
    os.link(path, alias)
    io = _IO()
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_FILE"):
        evidence.load_captured_plan(path, reference, io=io)
    _closed(io)
    assert io.reads == 0
    with pytest.raises(FileExistsError):
        evidence.capture_plan(path, {"never": "overwrite"})
    retained, linked = path.read_bytes(), alias.read_bytes()
    assert retained == linked == original


def _directory_alias(alias, target):
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(target)],
            check=True,
            capture_output=True,
            timeout=10,
        )
    else:
        alias.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("location", ["leaf", "parent"])
def test_native_reparse_or_symlink_namespace_never_writes_outside_target(tmp_path, location):
    root = (tmp_path / "owned").resolve()
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_bytes(b"outside must stay unchanged")
    alias = root / ("source-captured.json" if location == "leaf" else "redirected")
    _directory_alias(alias, outside)
    path = alias if location == "leaf" else alias / "source-captured.json"
    try:
        with pytest.raises((ValueError, OSError)):
            evidence.capture_plan(path, evidence._raw())
        io = _IO()
        reference = {"basename": path.name, "sha256": "0" * 64, "sizeBytes": 1}
        with pytest.raises((ValueError, OSError)):
            evidence.load_captured_plan(path, reference, io=io)
        assert io.reads == 0
        if io.fd is not None:
            _closed(io)
        retained, entries = marker.read_bytes(), sorted(item.name for item in outside.iterdir())
        assert retained == b"outside must stay unchanged" and entries == ["marker"]
    finally:
        if os.name == "nt":
            alias.rmdir()
        else:
            alias.unlink()


def test_native_fsync_failure_closes_without_returning_reference(tmp_path):
    path = evidence._path(tmp_path)

    class IO(_IO):
        def fsync(self, fd):
            os.fsync(fd)
            raise OSError("synthetic fsync refusal")

    io = IO()
    with pytest.raises(OSError, match="synthetic fsync refusal"):
        evidence.capture_plan(path, evidence._raw(), io=io)
    _closed(io)
    retained = path.read_bytes()
    assert retained.endswith(b"\n")


def test_native_same_size_rewrite_still_requires_original_buffer_hash(tmp_path):
    path = evidence._path(tmp_path)
    reference = evidence.capture_plan(path, evidence._raw())
    original = path.read_bytes()
    altered = original.replace(b"owner", b"other", 1)
    assert altered != original and len(altered) == len(original)
    path.write_bytes(altered)
    io = _IO()
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_HASH"):
        evidence.load_captured_plan(path, reference, io=io)
    _closed(io)


@pytest.mark.parametrize("size", [0, -1, True, evidence._MAX_CAPTURE_BYTES + 1])
def test_reference_extent_bounds_refuse_before_open(tmp_path, size):
    io = _IO()
    path = evidence._path(tmp_path)
    reference = {"basename": path.name, "sha256": "0" * 64, "sizeBytes": size}
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_REFERENCE"):
        evidence.load_captured_plan(path, reference, io=io)
    assert io.fd is None and io.reads == 0 and io.closed == []
