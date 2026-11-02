"""Compact plan evidence contracts, using real owned files and no database."""

import errno
import hashlib
import json
import os
import re
import stat

import pytest

_FIELDS = (
    "st_dev",
    "st_ino",
    "st_uid",
    "st_gid",
    "st_mode",
    "st_nlink",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)
_IDENTITY = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink")
_MAX_CAPTURE_BYTES = 16 * 1024**2


def _meta(value):
    return tuple(getattr(value, key) for key in _FIELDS)


def _named_equal(named, opened, *, windows):
    return all(
        getattr(named, key) == getattr(opened, key)
        for key in _FIELDS
        if not (windows and key == "st_dev")
    )


def _namespace(path):
    if not path.is_absolute() or path.parent.resolve(strict=True) != path.parent:
        raise ValueError("PLAN_EVIDENCE_NAMESPACE")
    result = {}
    for parent in path.parents:
        value = parent.lstat()
        if not stat.S_ISDIR(value.st_mode) or stat.S_ISLNK(value.st_mode):
            raise ValueError("PLAN_EVIDENCE_NAMESPACE")
        result[parent] = value
    return result


def _regular(value):
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError("PLAN_EVIDENCE_FILE")
    if os.name != "nt" and value.st_uid != os.getuid():
        raise ValueError("PLAN_EVIDENCE_FILE")


def _reference(value):
    if not isinstance(value, dict) or set(value) != {"basename", "sha256", "sizeBytes"}:
        raise ValueError("PLAN_EVIDENCE_REFERENCE")
    name, digest, size = value["basename"], value["sha256"], value["sizeBytes"]
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,240}-captured\.json", name)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or type(size) is not int
        or not 0 < size <= _MAX_CAPTURE_BYTES
    ):
        raise ValueError("PLAN_EVIDENCE_REFERENCE")
    return value


def capture_plan(path, row, *, io=os):
    """Encode once; EXCL-write/fsync that buffer; retain its exact immutable ref."""
    payload = (json.dumps(row, indent=2, default=str) + "\n").encode("utf-8")
    result = _reference(
        {
            "basename": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "sizeBytes": len(payload),
        }
    )
    parents = _namespace(path)
    fd = io.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
        0o600,
    )
    try:
        opened = io.fstat(fd)
        _regular(opened)
        if os.name != "nt":
            io.fchmod(fd, 0o600)
            opened = io.fstat(fd)
        named = path.lstat()
        _regular(named)
        if opened.st_size != 0 or not _named_equal(named, opened, windows=os.name == "nt"):
            raise ValueError("PLAN_EVIDENCE_CHANGED")
        initial_named = named
        after_create = _namespace(path)
        for parent, original in parents.items():
            # APFS counts a new file in its directory's link count; Linux
            # generally leaves that count unchanged. Only this owned EXCL
            # creation may change the immediate parent's extent/timestamps.
            fields = (
                tuple(key for key in _IDENTITY if key != "st_nlink")
                if parent == path.parent
                else _FIELDS
            )
            if any(getattr(original, key) != getattr(after_create[parent], key) for key in fields):
                raise ValueError("PLAN_EVIDENCE_NAMESPACE")
            if parent == path.parent and after_create[parent].st_nlink not in {
                original.st_nlink,
                original.st_nlink + 1,
            }:
                raise ValueError("PLAN_EVIDENCE_NAMESPACE")
        remaining = memoryview(payload)
        while remaining:
            count = io.write(fd, remaining)
            if not 0 < count <= len(remaining):
                raise ValueError("PLAN_EVIDENCE_WRITE_INCOMPLETE")
            remaining = remaining[count:]
        io.fsync(fd)
        final, named = io.fstat(fd), path.lstat()
        _regular(final)
        _regular(named)
        if (
            not _named_equal(named, final, windows=os.name == "nt")
            or any(getattr(final, key) != getattr(opened, key) for key in _IDENTITY)
            or any(getattr(named, key) != getattr(initial_named, key) for key in _IDENTITY)
            or final.st_size != len(payload)
            or _meta(io.fstat(fd)) != _meta(final)
            or {p: _meta(s) for p, s in _namespace(path).items()}
            != {p: _meta(s) for p, s in after_create.items()}
        ):
            raise ValueError("PLAN_EVIDENCE_CHANGED")
        return result
    finally:
        io.close(fd)


def load_captured_plan(path, reference, *, io=os):
    """Read/hash/parse the same bounded descriptor, never a path after its hash."""
    reference = _reference(reference)
    if path.name != reference["basename"]:
        raise ValueError("PLAN_EVIDENCE_REFERENCE")
    parents = {p: _meta(s) for p, s in _namespace(path).items()}
    fd = io.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        opened = io.fstat(fd)
        _regular(opened)
        if opened.st_size != reference["sizeBytes"]:
            raise ValueError("PLAN_EVIDENCE_EXTENT")
        named = path.lstat()
        _regular(named)
        if not _named_equal(named, opened, windows=os.name == "nt"):
            raise ValueError("PLAN_EVIDENCE_CHANGED")
        held = bytearray()
        while len(held) <= reference["sizeBytes"]:
            value = io.read(fd, min(65536, reference["sizeBytes"] + 1 - len(held)))
            if not value:
                break
            held.extend(value)
        final_named = path.lstat()
        if (
            len(held) != reference["sizeBytes"]
            or _meta(io.fstat(fd)) != _meta(opened)
            or _meta(final_named) != _meta(named)
            or not _named_equal(final_named, opened, windows=os.name == "nt")
            or parents != {p: _meta(s) for p, s in _namespace(path).items()}
        ):
            raise ValueError("PLAN_EVIDENCE_CHANGED")
        if hashlib.sha256(held).hexdigest() != reference["sha256"]:
            raise ValueError("PLAN_EVIDENCE_HASH")
        try:
            value = json.loads(held.decode("utf-8", "strict"))
        except (UnicodeError, ValueError):
            raise ValueError("PLAN_EVIDENCE_JSON") from None
        if not isinstance(value, dict):
            raise ValueError("PLAN_EVIDENCE_JSON")
        return value
    finally:
        io.close(fd)


def compact_plan_record(raw, reference, *, measured=False, index_timing=None, cohort_order=None):
    reference = _reference(reference)
    if (
        type(measured) is not bool
        or reference["basename"] != raw["label"].replace("/", "-") + "-captured.json"
    ):
        raise ValueError("PLAN_EVIDENCE_REFERENCE")
    result = {key: value for key, value in raw.items() if key != "plan"}
    result["capturedPlan"] = dict(reference)
    if measured:
        if index_timing not in {"before_seed", "after_seed"} or cohort_order not in {
            "visible_first",
            "competing_first",
        }:
            raise ValueError("PLAN_EVIDENCE_COHORT")
        result.update(
            status="measured",
            completeProjectionRowsEqualDefault=True,
            actualSourceProjectionBoundToHTTPIdentity=True,
            indexTiming=index_timing,
            cohortOrder=cohort_order,
        )
    return result


def load_plan_record(directory, record, *, io=os):
    """Reconcile every retained verdict field with its exact full raw plan."""
    if not isinstance(record, dict) or "capturedPlan" not in record:
        raise ValueError("PLAN_EVIDENCE_RECORD")
    reference = _reference(record["capturedPlan"])
    raw = load_captured_plan(directory / reference["basename"], reference, io=io)
    if raw.get("status") != "plan_captured_projection_unverified":
        raise ValueError("PLAN_EVIDENCE_RECORD")
    measured = record.get("status") == "measured"
    expected = compact_plan_record(
        raw,
        reference,
        measured=measured,
        index_timing=record.get("indexTiming"),
        cohort_order=record.get("cohortOrder"),
    )
    if record != expected:
        raise ValueError("PLAN_EVIDENCE_RECORD")
    return raw


def _raw():
    return {
        "label": "owner/positive/source/page/default",
        "status": "plan_captured_projection_unverified",
        "work": 401,
        "cap": 400,
        "actualOccurrences": 2,
        "occurrenceWeightedWork": 802,
        "actualTypedSQL": "SELECT fixed",
        "actualPublicBindings": {"limit": 26},
        "allNodeAttribution": [{"node": "Result", "work": 401}],
        "cleanCanonicalSourceReads": [],
        "plan": {"Plan": {"Node Type": "Result", "Actual Rows": 401, "Actual Loops": 1}},
    }


def _path(tmp_path):
    return tmp_path.resolve() / "owner-positive-source-page-default-captured.json"


def test_capture_is_exclusive_and_hashes_written_utf8_buffer_without_path_reopen(
    tmp_path, monkeypatch
):
    path = _path(tmp_path)
    raw = _raw()
    with monkeypatch.context() as patch:
        patch.setattr(
            type(path), "read_bytes", lambda *_: (_ for _ in ()).throw(AssertionError("No reopen"))
        )
        patch.setattr(
            type(path),
            "read_text",
            lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("No reopen")),
        )
        reference = capture_plan(path, raw)
    content = path.read_bytes()
    assert reference == {
        "basename": path.name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "sizeBytes": len(content),
    }
    assert b"\r\n" not in content and content.endswith(b"\n")
    loaded = load_captured_plan(path, reference)
    assert loaded == raw
    with pytest.raises(FileExistsError):
        capture_plan(path, {"must": "not replace original"})
    retained = path.read_bytes()
    assert retained == content


def test_capture_refuses_symlink_leaf_and_parent_without_writing_target(tmp_path):
    root = tmp_path.resolve()
    target = root / "target"
    target.write_bytes(b"original")
    path = _path(root)
    path.symlink_to(target)
    with pytest.raises(FileExistsError):
        capture_plan(path, _raw())
    retained = target.read_bytes()
    assert retained == b"original"
    path.unlink()
    link = root / "linked"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="NAMESPACE"):
        capture_plan(link / path.name, _raw())


@pytest.mark.parametrize("part", ["basename", "sha256", "sizeBytes"])
def test_read_reference_identity_is_strict(tmp_path, part):
    path = _path(tmp_path)
    reference = capture_plan(path, _raw())
    wrong = {
        **reference,
        part: {
            "basename": "wrong-captured.json",
            "sha256": "0" * 64,
            "sizeBytes": reference["sizeBytes"] + 1,
        }[part],
    }
    with pytest.raises(ValueError, match="REFERENCE|HASH|EXTENT"):
        load_captured_plan(path, wrong)


def test_partial_write_failure_closes_descriptor_and_preserves_incomplete_file(tmp_path):
    path = _path(tmp_path)

    class IO:
        def __getattr__(self, key):
            return getattr(os, key)

        def open(self, *args):
            self.fd = os.open(*args)
            return self.fd

        def write(self, fd, data):
            os.write(fd, data[:7])
            raise OSError("synthetic write refusal")

    io = IO()
    with pytest.raises(OSError):
        capture_plan(path, _raw(), io=io)
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    remaining_size = path.stat().st_size
    assert failure.value.errno == errno.EBADF and remaining_size == 7


def test_named_replacement_after_write_refuses_and_closes_descriptor(tmp_path):
    path = _path(tmp_path)

    class IO:
        def __getattr__(self, key):
            return getattr(os, key)

        def open(self, *args):
            self.fd = os.open(*args)
            return self.fd

        def fsync(self, fd):
            os.fsync(fd)
            path.rename(path.with_suffix(".retained"))
            path.write_bytes(b"replacement")

    io = IO()
    with pytest.raises(ValueError, match="CHANGED"):
        capture_plan(path, _raw(), io=io)
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    assert failure.value.errno == errno.EBADF
    retained_exists = path.with_suffix(".retained").exists()
    replacement = path.read_bytes()
    assert retained_exists and replacement == b"replacement"


def test_read_growth_is_bounded_and_descriptor_always_closed(tmp_path):
    path = _path(tmp_path)
    reference = capture_plan(path, _raw())

    class IO:
        done = False

        def __getattr__(self, key):
            return getattr(os, key)

        def open(self, *args):
            self.fd = os.open(*args)
            return self.fd

        def read(self, fd, size):
            if not self.done:
                self.done = True
                with path.open("ab") as stream:
                    stream.write(b"unexpected growth")
            return os.read(fd, size)

    io = IO()
    with pytest.raises(ValueError, match="CHANGED"):
        load_captured_plan(path, reference, io=io)
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    assert failure.value.errno == errno.EBADF


def test_compact_record_preserves_all_nonplan_facts_without_promoting_unverified_or_work(tmp_path):
    raw = _raw()
    path = _path(tmp_path)
    reference = capture_plan(path, raw)
    pending = compact_plan_record(raw, reference)
    assert (
        pending["status"] == "plan_captured_projection_unverified"
        and "completeProjectionRowsEqualDefault" not in pending
    )
    measured = compact_plan_record(
        raw, reference, measured=True, index_timing="after_seed", cohort_order="competing_first"
    )
    assert measured["status"] == "measured" and "plan" not in measured
    assert (
        measured["work"] == 401
        and measured["cap"] == 400
        and measured["occurrenceWeightedWork"] == 802
    )
    assert measured["capturedPlan"] == reference
    for key, value in raw.items():
        if key not in {"plan", "status"}:
            assert measured[key] == value
    assert (
        measured["completeProjectionRowsEqualDefault"] is True
        and measured["actualSourceProjectionBoundToHTTPIdentity"] is True
    )
    assert measured["indexTiming"] == "after_seed" and measured["cohortOrder"] == "competing_first"
    loaded = load_captured_plan(path, reference)
    assert raw["status"] == "plan_captured_projection_unverified" and loaded == raw


@pytest.mark.parametrize("payload", [b"{invalid", b"\xff", b"[]"])
def test_reader_refuses_fixed_json_utf8_boundaries_and_closes(tmp_path, payload):
    path = _path(tmp_path)
    path.write_bytes(payload)
    reference = {
        "basename": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "sizeBytes": len(payload),
    }

    class IO:
        def __getattr__(self, key):
            return getattr(os, key)

        def open(self, *args):
            self.fd = os.open(*args)
            return self.fd

    io = IO()
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_JSON"):
        load_captured_plan(path, reference, io=io)
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    assert failure.value.errno == errno.EBADF


@pytest.mark.parametrize("measured", [False, True])
def test_consumer_reconciles_every_verdict_field_and_exact_raw_plan(tmp_path, measured):
    path = _path(tmp_path)
    raw = _raw()
    reference = capture_plan(path, raw)
    record = compact_plan_record(
        raw, reference, measured=measured, index_timing="before_seed", cohort_order="visible_first"
    )
    loaded = load_plan_record(path.parent, record)
    assert loaded == raw
    tampered = {**record, "work": 399}
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_RECORD"):
        load_plan_record(path.parent, tampered)
    if measured:
        omitted = {key: value for key, value in record.items() if key != "indexTiming"}
        with pytest.raises(ValueError, match="PLAN_EVIDENCE_COHORT"):
            load_plan_record(path.parent, omitted)


def test_schema1_small_verdict_is_refused_without_reading_any_plan(tmp_path):
    old = {"status": "measured", "work": 401, "actualOccurrences": 2, "occurrenceWeightedWork": 802}

    class IO:
        def open(self, *_args):
            raise AssertionError("Legacy reference cannot authorize a file read")

    with pytest.raises(ValueError, match="PLAN_EVIDENCE_RECORD"):
        load_plan_record(tmp_path.resolve(), old, io=IO())


def test_close_failure_prevents_capture_acceptance_and_preserves_written_file(tmp_path):
    path = _path(tmp_path)

    class IO:
        def __getattr__(self, key):
            return getattr(os, key)

        def close(self, fd):
            os.close(fd)
            self.fd = fd
            raise OSError("synthetic close refusal")

    io = IO()
    with pytest.raises(OSError, match="synthetic close refusal"):
        capture_plan(path, _raw(), io=io)
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    content = path.read_bytes()
    assert failure.value.errno == errno.EBADF and content.endswith(b"\n")


def test_namespace_change_during_write_refuses_complete_file_and_closes(tmp_path):
    path = _path(tmp_path)

    class IO:
        def __getattr__(self, key):
            return getattr(os, key)

        def open(self, *args):
            self.fd = os.open(*args)
            return self.fd

        def fsync(self, fd):
            os.fsync(fd)
            (path.parent / "unexpected-sibling").write_bytes(b"public synthetic")

    io = IO()
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_CHANGED"):
        capture_plan(path, _raw(), io=io)
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    assert failure.value.errno == errno.EBADF


def test_named_replacement_after_open_admission_refuses_before_any_read_and_closes(tmp_path):
    path = _path(tmp_path)
    reference = capture_plan(path, _raw())

    class IO:
        reads = 0
        replaced = False

        def __getattr__(self, key):
            return getattr(os, key)

        def open(self, *args):
            self.fd = os.open(*args)
            return self.fd

        def fstat(self, fd):
            admitted = os.fstat(fd)
            if not self.replaced:
                self.replaced = True
                path.rename(path.with_suffix(".retained"))
                path.write_bytes(b"replacement")
            return admitted

        def read(self, *_args):
            self.reads += 1
            raise AssertionError("Replaced named leaf must not authorize any read")

    io = IO()
    with pytest.raises(ValueError, match="PLAN_EVIDENCE_CHANGED"):
        load_captured_plan(path, reference, io=io)
    with pytest.raises(OSError) as failure:
        os.fstat(io.fd)
    replacement = path.read_bytes()
    assert io.reads == 0 and failure.value.errno == errno.EBADF and replacement == b"replacement"
