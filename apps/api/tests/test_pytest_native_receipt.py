"""Native exit observability, independent of pytest outcomes and uv status mapping."""
import hashlib
import importlib.util
import io
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "pytest_native_receipt", ROOT / "scripts/pytest_native_receipt.py",
)
assert SPEC and SPEC.loader
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)
SOURCE = "a" * 40


@pytest.fixture(autouse=True)
def source_binding(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", SOURCE)


@pytest.mark.parametrize("windows,opened,named,expected", [
    (False, 0o100666, 0o100666, True),
    (True, 0o100666, 0o100666, True),
    (True, 0o100666, 0o100777, True),
    (False, 0o100666, 0o100777, False),
    (True, 0o100666, 0o100755, False),
    (True, 0o100644, 0o100755, False),
    (True, 0o100777, 0o100666, False),
    (True, 0o040777, 0o100777, False),
])
def test_runtime_mode_projection_is_exact_and_windows_only(windows, opened, named, expected):
    matched = native._runtime_modes_match(opened, named, windows_executable=windows)
    assert matched is expected


@pytest.mark.parametrize("channel", ["descriptor", "pathname"])
def test_runtime_rejects_same_channel_mode_change_after_read(monkeypatch, channel):
    if channel not in {"descriptor", "pathname"}:
        raise ValueError("Unsupported runtime-mode observation channel")
    target = Path(sys.executable).resolve(strict=True)
    original_fstat, original_lstat = os.fstat, Path.lstat
    observed = []

    def changed(value):
        fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        values = {key: getattr(value, key) for key in fields}
        values["st_mode"] = stat.S_IFREG | 0o600
        return SimpleNamespace(**values)

    def descriptor(fd):
        value = original_fstat(fd)
        observed.append(fd)
        return changed(value) if len(observed) == 2 else value

    def pathname(path):
        value = original_lstat(path)
        if path == target:
            observed.append(str(path))
            if len(observed) == 2:
                return changed(value)
        return value

    with monkeypatch.context() as scoped:
        if channel == "descriptor":
            scoped.setattr(native.os, "fstat", descriptor)
        else:
            scoped.setattr(Path, "lstat", pathname)
        with pytest.raises(RuntimeError, match="runtime_changed_during_read"):
            native._runtime()
    assert len(observed) == 2


@pytest.mark.parametrize("damage", ["fdopen", "fstat", "digest"])
def test_runtime_descriptor_closes_on_constructor_or_read_failure(monkeypatch, damage):
    if damage not in {"fdopen", "fstat", "digest"}:
        raise ValueError("Unsupported runtime-read failure control")
    target = Path(sys.executable).resolve(strict=True)
    open_fd, stat_fd = os.open, os.fstat
    opened = []

    def tracked_open(name, flags, *args, **kwargs):
        descriptor = open_fd(name, flags, *args, **kwargs)
        if isinstance(name, (str, os.PathLike)) and Path(name) == target:
            opened.append(descriptor)
        return descriptor

    def refuse(*_args, **_kwargs):
        raise OSError("owned-runtime-read-control")

    with monkeypatch.context() as scoped:
        scoped.setattr(native.os, "open", tracked_open)
        if damage == "fdopen":
            scoped.setattr(native.os, "fdopen", refuse)
        elif damage == "fstat":
            scoped.setattr(native.os, "fstat", refuse)
        else:
            scoped.setattr(native.hashlib, "file_digest", refuse)
        with pytest.raises(OSError, match="owned-runtime-read-control"):
            native._runtime()
    assert len(opened) == 1
    with pytest.raises(OSError):
        stat_fd(opened[0])


@pytest.mark.parametrize("code", [0, 17, 139])
def test_real_owned_child_preserves_native_numeric_exit_and_opened_runtime(tmp_path, code):
    path = tmp_path / "receipt.json"
    result = native.run([sys.executable, "-c", f"raise SystemExit({code})"], path)
    assert result == code
    row = json.loads(path.read_text())
    assert row["stage"] == "exited" and row["source_sha"] == SOURCE
    assert row["native_returncode"] == code and row["native_signal"] is None
    assert row["exit_code"] == code and row["publication_errors"] == []
    assert row["launcher_pid"] == os.getpid()
    assert row["child_pid"] > 0 and row["child_pid"] != row["launcher_pid"]
    runtime = Path(sys.executable).resolve(strict=True)
    with runtime.open("rb") as stream:
        expected_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert row["runtime"]["sha256"] == expected_digest
    assert row["runtime"]["bytes"] == runtime.stat().st_size
    assert row["runtime"]["executable"] == sys.executable
    assert row["runtime"]["resolved"] == str(runtime)
    assert row["planned_at"] <= row["started_at"] <= row["finished_at"]
    assert all(row[key].endswith("+00:00")
               for key in ("planned_at", "started_at", "finished_at"))


@pytest.mark.skipif(os.name != "posix", reason="Native Unix wait status requires POSIX")
def test_owned_signal_termination_is_distinct_from_normal139(tmp_path):
    path = tmp_path / "receipt.json"
    result = native.run([
        sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)",
    ], path)
    row = json.loads(path.read_text())
    assert result == 143
    assert row["native_returncode"] == -signal.SIGTERM
    assert row["native_signal"] == signal.SIGTERM and row["exit_code"] == 143


def test_prelaunch_and_pid_are_published_before_native_wait_without_stream_or_env_changes(
    tmp_path, monkeypatch, capfdbinary,
):
    path = tmp_path / "receipt.json"
    monkeypatch.setenv("PYTEST_ADDOPTS", "owned-literal-parent-options")
    calls = []

    def popen(command, **kwargs):
        planned = json.loads(path.read_text())
        assert planned["stage"] == "planned" and planned["child_pid"] is None
        assert kwargs == {}
        child = subprocess.Popen(command, **kwargs)
        calls.append(child.pid)

        def wait():
            started = json.loads(path.read_text())
            assert started["stage"] == "started" and started["child_pid"] == child.pid
            return child.wait()

        return SimpleNamespace(pid=child.pid, wait=wait)

    code = (
        "import os;assert os.environ['PYTEST_ADDOPTS']=='owned-literal-parent-options';"
        "os.write(1,b'owned-stdout\\xff');os.write(2,b'owned-stderr\\xfe')"
    )
    result = native.run([sys.executable, "-c", code], path, popen=popen)
    assert result == 0
    captured = capfdbinary.readouterr()
    assert captured.out == b"owned-stdout\xff" and captured.err == b"owned-stderr\xfe"
    assert len(calls) == 1


def test_constructor_failure_retains_prelaunch_identity_without_reflecting_exception_text(
    tmp_path, capsys,
):
    path = tmp_path / "receipt.json"

    def popen(_command):
        assert json.loads(path.read_text())["stage"] == "planned"
        raise OSError("private-constructor-input-must-not-be-reflected")

    result = native.run([sys.executable, "-c", "raise AssertionError"], path, popen=popen)
    assert result == 1
    row = json.loads(path.read_text())
    assert row["stage"] == "constructor_failed" and row["error_type"] == "OSError"
    assert row["child_pid"] is None and row["native_returncode"] is None
    assert "private-constructor-input" not in capsys.readouterr().err


def test_existing_receipt_refuses_before_constructor_and_retains_original_bytes(tmp_path):
    path = tmp_path / "receipt.json"
    original = b"retained-first-attempt\n"
    path.write_bytes(original)
    calls = []
    result = native.run([], path, popen=lambda *_: calls.append(True))
    assert result == 1
    assert calls == [] and path.read_bytes() == original


def test_wait_failure_retains_started_identity_without_fabricating_native_success(tmp_path):
    path = tmp_path / "receipt.json"
    waits, actions = [], []

    def wait(timeout=None):
        waits.append(timeout)
        if len(waits) == 1:
            raise ChildProcessError("private-wait-value")
        return 0

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait,
                            terminate=lambda: actions.append("terminate"),
                            kill=lambda: actions.append("kill"))
    result = native.run([], path, popen=lambda _: child)
    assert result == 1
    row = json.loads(path.read_text())
    assert row["stage"] == "wait_failed" and row["error_type"] == "ChildProcessError"
    assert row["child_pid"] == os.getpid() + 1
    assert row["native_returncode"] is None and row["native_signal"] is None
    assert row["native_exit_observed_before_failure"] is False
    assert row["cleanup"]["reaped"] is True
    assert row["cleanup"]["returncode_after_cleanup"] == 0
    assert actions == ["terminate"] and waits[0] is None and 0 <= waits[1] <= 2


@pytest.mark.parametrize("stage", ["planned", "started", "exited"])
@pytest.mark.parametrize("code", [0, 17])
def test_publication_failure_never_hides_first_native_failure_or_certifies_success(
    tmp_path, capsys, stage, code,
):
    path = tmp_path / "receipt.json"
    calls = []

    def publish(target, row, **kwargs):
        if row["stage"] == stage:
            raise PermissionError("private-publication-value")
        native._publish(target, row, **kwargs)

    def popen(command):
        calls.append(command)
        return subprocess.Popen(command)

    actual = native.run([sys.executable, "-c", f"raise SystemExit({code})"], path,
                        popen=popen, publish=publish)
    assert actual == (17 if code == 17 and stage != "planned" else 1)
    assert len(calls) == (0 if stage == "planned" else 1)
    errors = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert errors and all(row["error_type"] == "PermissionError" for row in errors)
    assert "private-publication-value" not in json.dumps(errors)
    if stage == "exited":
        assert errors[-1]["native_returncode"] == code
        assert json.loads(path.read_text())["stage"] == "started"
    elif stage == "started":
        row = json.loads(path.read_text())
        assert row["native_returncode"] == code and row["publication_errors"] == ["started"]


def test_constructor_failure_and_failed_error_publication_are_both_retained(tmp_path, capsys):
    def popen(_command):
        raise OSError("private-constructor-value")

    def publish(path, row, **kwargs):
        if row["stage"] == "constructor_failed":
            raise PermissionError("private-publication-value")
        native._publish(path, row, **kwargs)

    result = native.run([], tmp_path / "receipt.json", popen=popen, publish=publish)
    assert result == 1
    rows = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [row["native_receipt_error"] for row in rows] == [
        "constructor", "constructor_publication",
    ]
    assert [row["error_type"] for row in rows] == ["OSError", "PermissionError"]


def test_cli_constructs_only_same_runtime_pytest_without_changing_forwarded_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(
        native, "run", lambda command, receipt: calls.append((command, receipt)) or 17,
    )
    result = native.main(["receipt.json", "--", "-q", "-m", "postgres"])
    assert result == 17
    assert calls == [([sys.executable, "-m", "pytest", "-q", "-m", "postgres"],
                      Path("receipt.json"))]


@pytest.mark.parametrize("arguments", [[], ["receipt.json", "-q"]])
def test_cli_refuses_malformed_invocation_before_any_child(monkeypatch, arguments):
    calls = []
    monkeypatch.setattr(native, "run", lambda *_: calls.append(True))
    with pytest.raises(SystemExit, match="Usage"):
        native.main(arguments)
    assert calls == []


def test_unbound_source_refuses_before_constructor(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_SHA")
    calls = []
    result = native.run([], tmp_path / "receipt.json", popen=lambda *_: calls.append(True))
    assert result == 1
    assert calls == [] and not (tmp_path / "receipt.json").exists()


def _contained_run(*args, **kwargs):
    try:
        return native.run(*args, **kwargs)
    except BaseException as error:
        raise AssertionError("observer_exception_escaped:" + type(error).__name__) from None


@pytest.mark.parametrize("phase", ["wait", "started_publication"])
def test_real_owned_child_is_reaped_after_observer_failure_or_interruption(tmp_path, phase):
    path, children = tmp_path / "receipt.json", []

    def popen(command):
        child = subprocess.Popen(command)
        children.append(child)

        def wait(timeout=None):
            if timeout is None and phase == "wait":
                before_failure = child.poll()
                assert before_failure is None
                raise ChildProcessError("private-first-wait")
            return child.wait(timeout=timeout)

        return SimpleNamespace(pid=child.pid, wait=wait,
                               terminate=child.terminate, kill=child.kill)

    def publish(target, row, **kwargs):
        if phase == "started_publication" and row["stage"] == "started":
            before_failure = children[0].poll()
            assert before_failure is None
            raise KeyboardInterrupt("private-cancellation")
        native._publish(target, row, **kwargs)

    try:
        result = _contained_run([sys.executable, "-c", "import time;time.sleep(30)"], path,
                                popen=popen, publish=publish)
        assert result == (130 if phase == "started_publication" else 1)
        assert len(children) == 1
        completed = children[0].poll()
        assert completed is not None
        row = json.loads(path.read_text())
        assert row["native_returncode"] is None and row["native_signal"] is None
        assert row["native_exit_observed_before_failure"] is False
        assert row["cleanup"]["reaped"] is True
        assert type(row["cleanup"]["returncode_after_cleanup"]) is int
        assert row["error_type"] == (
            "KeyboardInterrupt" if phase == "started_publication" else "ChildProcessError"
        )
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, InterruptedError])
def test_interrupted_wait_keeps_first_failure_and_does_not_promote_cleanup_zero(
    tmp_path, error_type,
):
    path, waits, actions = tmp_path / "receipt.json", [], []

    def wait(timeout=None):
        waits.append(timeout)
        if timeout is None:
            raise error_type("private-first-wait")
        return 0

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait,
                            terminate=lambda: actions.append("terminate"),
                            kill=lambda: actions.append("kill"))
    result = _contained_run([], path, popen=lambda _: child)
    assert result == (130 if error_type is KeyboardInterrupt else 1)
    row = json.loads(path.read_text())
    assert row["error_type"] == error_type.__name__ and row["stage"] == "wait_failed"
    assert row["native_returncode"] is None and row["exit_code"] is None
    assert row["cleanup"]["returncode_after_cleanup"] == 0
    assert row["cleanup"]["reaped"] is True and row["cleanup"]["errors"] == []
    assert actions == ["terminate"] and waits[0] is None and 0 <= waits[1] <= 2


@pytest.mark.parametrize("fault", [None, "terminate", "kill", "kill_wait"])
def test_cleanup_fallback_is_owned_bounded_and_keeps_failures_separate(
    tmp_path, monkeypatch, fault,
):
    path, waits, actions = tmp_path / "receipt.json", [], []
    monkeypatch.setattr(native.time, "monotonic", lambda: 100.0)

    def wait(timeout=None):
        waits.append(timeout)
        if len(waits) == 1:
            raise ChildProcessError("private-first-wait")
        if len(waits) == 2:
            raise subprocess.TimeoutExpired("owned-child", timeout)
        if fault in {"kill", "kill_wait"}:
            raise ChildProcessError("private-cleanup-wait")
        return -9

    def terminate():
        actions.append("terminate")
        if fault == "terminate":
            raise PermissionError("private-terminate")

    def kill():
        actions.append("kill")
        if fault == "kill":
            raise PermissionError("private-kill")

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait, terminate=terminate, kill=kill)
    result = _contained_run([], path, popen=lambda _: child)
    row = json.loads(path.read_text())
    assert result == 1 and row["error_type"] == "ChildProcessError"
    assert row["native_returncode"] is None and row["native_signal"] is None
    cleanup = row["cleanup"]
    assert cleanup["budget_seconds"] == 4 and waits == [None, 2, 2]
    assert actions == ["terminate", "kill"]
    assert cleanup["reaped"] is (fault not in {"kill", "kill_wait"})
    assert cleanup["returncode_after_cleanup"] == (
        None if fault in {"kill", "kill_wait"} else -9
    )
    stages = [item["stage"] for item in cleanup["errors"]]
    assert "terminate_wait" in stages
    assert ("terminate" in stages) is (fault == "terminate")
    assert ("kill" in stages) is (fault == "kill")
    assert ("kill_wait" in stages) is (fault in {"kill", "kill_wait"})


@pytest.mark.parametrize("code", [0, 17])
def test_native_exit_before_interrupted_final_publication_is_not_replaced(tmp_path, code, capsys):
    path = tmp_path / "receipt.json"

    def publish(target, row, **kwargs):
        if row["stage"] == "exited":
            raise KeyboardInterrupt("private-final-publication")
        native._publish(target, row, **kwargs)

    result = _contained_run([sys.executable, "-c", f"raise SystemExit({code})"], path,
                            publish=publish)
    assert result == (17 if code else 130)
    error = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert error["native_returncode"] == code and error["error_type"] == "KeyboardInterrupt"
    assert error["cleanup"] is None
    assert json.loads(path.read_text())["stage"] == "started"


@pytest.mark.parametrize("stage", ["started", "exited"])
@pytest.mark.parametrize("code", [0, 17])
def test_closed_stderr_never_orphans_child_or_masks_native_failure(
    tmp_path, monkeypatch, stage, code,
):
    path, children = tmp_path / "receipt.json", []
    release = tmp_path / "owned-release"
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(native.sys, "stderr", closed)

    def popen(command):
        child = subprocess.Popen(command)
        children.append(child)

        def wait(timeout=None):
            release.touch()
            return child.wait(timeout=timeout)

        return SimpleNamespace(pid=child.pid, wait=wait,
                               terminate=child.terminate, kill=child.kill)

    def publish(target, row, **kwargs):
        if row["stage"] == stage:
            observed = children[0].poll()
            assert (observed is None) is (stage == "started")
            assert release.exists() is (stage == "exited")
            raise PermissionError("private-publication")
        native._publish(target, row, **kwargs)

    try:
        command = ("from pathlib import Path\nimport time,sys\n"
                   f"release=Path({str(release)!r})\n"
                   "while not release.exists(): time.sleep(0.01)\n"
                   f"raise SystemExit({code})\n")
        result = _contained_run([sys.executable, "-c", command], path,
                                popen=popen, publish=publish)
        assert result == (17 if code else 1)
        assert len(children) == 1
        completed = children[0].poll()
        assert completed is not None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize("drop_virtual_env", [False, True])
def test_cli_direct_child_preserves_the_already_uv_activated_environment(
    tmp_path, monkeypatch, capfdbinary, drop_virtual_env,
):
    expected = {
        "PATH": os.environ.get("PATH", ""), "VIRTUAL_ENV": "owned-activated-venv-marker",
        "UV_RUN_RECURSION_DEPTH": "7", "UV_CACHE_DIR": "owned-cache-marker",
        "PYTEST_ADDOPTS": "owned-parent-options", "CASEOPS_TEST_LITERAL_MARKER": "kept",
    }
    for key, value in expected.items():
        monkeypatch.setenv(key, value)
    original_run = native.run
    calls = []

    def run(command, receipt):
        assert command == [sys.executable, "-m", "pytest", "-q", "-m", "postgres"]
        calls.append(command)
        code = "import json,os;actual={k:os.environ.get(k) for k in " + repr(list(expected))
        code += "};assert actual==" + repr(expected) + ";print(json.dumps(actual))"

        def launch(child_command):
            assert child_command == [sys.executable, "-c", code]
            environment = os.environ.copy()
            if drop_virtual_env:
                environment.pop("VIRTUAL_ENV")
            return subprocess.Popen(child_command, env=environment)

        return original_run([sys.executable, "-c", code], receipt, popen=launch)

    monkeypatch.setattr(native, "run", run)
    result = native.main([str(tmp_path / "receipt.json"), "--", "-q", "-m", "postgres"])
    captured = capfdbinary.readouterr()
    assert result == (1 if drop_virtual_env else 0) and len(calls) == 1
    if drop_virtual_env:
        assert captured.out == b"" and b"AssertionError" in captured.err
    else:
        assert json.loads(captured.out) == expected
    row = json.loads((tmp_path / "receipt.json").read_text())
    assert row["native_returncode"] == result and row["native_signal"] is None


@pytest.mark.parametrize("stage", ["serialize", "file_fsync", "link", "replace"])
@pytest.mark.parametrize("unlink_failure", [False, True])
def test_internal_publisher_retains_primary_then_cleanup_errors_and_closes_files(
    tmp_path, monkeypatch, capsys, stage, unlink_failure,
):
    path, descriptors = tmp_path / "receipt.json", []
    original = b"retained-publication\n"
    if stage == "replace":
        path.write_bytes(original)
    primary, secondary = OSError("private-primary"), PermissionError("private-cleanup")
    factory, dump, fsync = native.tempfile.NamedTemporaryFile, native.json.dump, native.os.fsync
    unlink = Path.unlink

    def create(**kwargs):
        stream = factory(**kwargs)
        descriptors.append(stream.fileno())
        return stream

    def serialize(*args, **kwargs):
        if stage == "serialize":
            raise primary
        return dump(*args, **kwargs)

    def sync(descriptor):
        if stage == "file_fsync" and descriptor in descriptors:
            raise primary
        return fsync(descriptor)

    def publish(*_args):
        raise primary

    def remove(target, *args, **kwargs):
        if unlink_failure and target.parent == tmp_path and target.name.startswith(path.name + "."):
            raise secondary
        return unlink(target, *args, **kwargs)

    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", create)
    monkeypatch.setattr(native.json, "dump", serialize)
    monkeypatch.setattr(native.os, "fsync", sync)
    if stage in {"link", "replace"}:
        monkeypatch.setattr(native.os, stage, publish)
    monkeypatch.setattr(Path, "unlink", remove)
    with pytest.raises(native.PublicationError) as caught:
        native._publish(path, {"owned": True}, initial=stage != "replace")
    error = caught.value
    assert error.primary is primary and error.__cause__ is primary and error.published is False
    expected = [{"stage": stage, "error_type": "OSError"}]
    if unlink_failure:
        expected.append({"stage": "temporary_unlink", "error_type": "PermissionError"})
    assert error.failures == expected
    assert len(descriptors) == 1
    for descriptor in descriptors:
        with pytest.raises(OSError):
            native.os.fstat(descriptor)
    assert path.read_bytes() == original if stage == "replace" else not path.exists()
    native._error("owned_publisher", error)
    logged = capsys.readouterr().err
    assert "private-" not in logged
    assert json.loads(logged)["publication"] == {"published": False, "failures": expected}


def test_internal_file_close_error_cannot_replace_the_serialization_failure(tmp_path, monkeypatch):
    path, descriptors = tmp_path / "receipt.json", []
    primary, secondary = OSError("private-primary"), PermissionError("private-close")
    factory = native.tempfile.NamedTemporaryFile

    def create(**kwargs):
        stream = factory(**kwargs)
        descriptors.append(stream.fileno())
        close = stream.close

        def closed_error():
            close()
            raise secondary

        stream.close = closed_error
        return stream

    def serialize(*_args, **_kwargs):
        raise primary

    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", create)
    monkeypatch.setattr(native.json, "dump", serialize)
    with pytest.raises(native.PublicationError) as caught:
        native._publish(path, {"owned": True}, initial=True)
    assert caught.value.primary is primary and caught.value.__cause__ is primary
    assert caught.value.failures == [
        {"stage": "serialize", "error_type": "OSError"},
        {"stage": "file_close", "error_type": "PermissionError"},
    ]
    for descriptor in descriptors:
        with pytest.raises(OSError):
            native.os.fstat(descriptor)
    assert not path.exists() and list(tmp_path.glob(path.name + ".*")) == []


@pytest.mark.skipif(os.name != "posix", reason="Directory fsync publication requires POSIX")
@pytest.mark.parametrize("close_failure", [False, True])
def test_directory_fsync_retains_published_state_and_does_not_mask_primary(
    tmp_path, monkeypatch, close_failure,
):
    path, file_descriptors, directories = tmp_path / "receipt.json", [], []
    primary, secondary = OSError("private-dir-sync"), PermissionError("private-dir-close")
    factory = native.tempfile.NamedTemporaryFile
    open_fd, close_fd, sync_fd = native.os.open, native.os.close, native.os.fsync

    def create(**kwargs):
        stream = factory(**kwargs)
        file_descriptors.append(stream.fileno())
        return stream

    def opened(name, flags, *args, **kwargs):
        descriptor = open_fd(name, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY:
            directories.append(descriptor)
        return descriptor

    def synced(descriptor):
        if descriptor in directories:
            raise primary
        sync_fd(descriptor)

    def closed(descriptor):
        close_fd(descriptor)
        if close_failure and descriptor in directories:
            raise secondary

    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", create)
    monkeypatch.setattr(native.os, "open", opened)
    monkeypatch.setattr(native.os, "fsync", synced)
    monkeypatch.setattr(native.os, "close", closed)
    with pytest.raises(native.PublicationError) as caught:
        native._publish(path, {"owned": True}, initial=True)
    error = caught.value
    assert error.primary is primary and error.__cause__ is primary and error.published is True
    expected = [{"stage": "directory_fsync", "error_type": "OSError"}]
    if close_failure:
        expected.append({"stage": "directory_close", "error_type": "PermissionError"})
    assert error.failures == expected
    assert len(file_descriptors) == len(directories) == 1
    for descriptor in file_descriptors + directories:
        with pytest.raises(OSError):
            native.os.fstat(descriptor)
    assert json.loads(path.read_text()) == {"owned": True}
    assert list(tmp_path.glob(path.name + ".*")) == []


# Control requests are distinct from operational failures, including direct
# control subclasses that are outside Exception/KeyboardInterrupt/SystemExit.
class OwnedDirectControl(BaseException):
    pass


CONTROL_LABELS = ("keyboard", "system-exit", "generator-exit", "direct-base")


def _owned_control(label):
    if label not in CONTROL_LABELS:
        raise ValueError("Unsupported owned control label")
    if label == "keyboard":
        return KeyboardInterrupt("private-control-value")
    if label == "system-exit":
        return SystemExit(0)
    if label == "generator-exit":
        return GeneratorExit("private-control-value")
    return OwnedDirectControl("private-control-value")


@pytest.mark.parametrize("label", CONTROL_LABELS)
@pytest.mark.parametrize("phase", [
    "pid", "started_clock", "started_publication", "wrapped_publication", "wait",
])
def test_owned_child_controls_keep_handle_through_identity_clock_publication_and_wait(
    tmp_path, monkeypatch, label, phase,
):
    if phase not in {"pid", "started_clock", "started_publication", "wrapped_publication", "wait"}:
        raise ValueError("Unsupported owned child control phase")
    control, children, waits, reads, live_at_fault = _owned_control(label), [], [], [], []
    path = tmp_path / "receipt.json"
    clock, interrupted = native._utc, []
    original_dump = native.json.dump

    def dump(value, *args, **kwargs):
        if phase == "wrapped_publication" and value["stage"] == "started":
            live_at_fault.append(children[0].poll())
            raise control
        return original_dump(value, *args, **kwargs)

    def utc():
        if phase == "started_clock" and children and not interrupted:
            interrupted.append(True)
            live_at_fault.append(children[0].poll())
            raise control
        return clock()

    class Child:
        @property
        def pid(self):
            reads.append(True)
            if phase == "pid":
                live_at_fault.append(children[0].poll())
                raise control
            return children[0].pid

        def wait(self, timeout=None):
            waits.append(timeout)
            if timeout is None and phase == "wait":
                live_at_fault.append(children[0].poll())
                raise control
            return children[0].wait(timeout=timeout)

        def terminate(self):
            children[0].terminate()

        def kill(self):
            children[0].kill()

    def popen(command):
        children.append(subprocess.Popen(command))
        return Child()

    def publish(target, row, **kwargs):
        if phase == "started_publication" and row["stage"] == "started":
            live_at_fault.append(children[0].poll())
            raise control
        native._publish(target, row, **kwargs)

    monkeypatch.setattr(native, "_utc", utc)
    monkeypatch.setattr(native.json, "dump", dump)
    try:
        result = _contained_run([sys.executable, "-c", "import time;time.sleep(30)"], path,
                                popen=popen, publish=publish)
        row = json.loads(path.read_text())
        completed = children[0].poll() if children else None
        cleanup_waits = [timeout for timeout in waits if timeout is not None]
        assert result == (130 if label == "keyboard" else 1)
        assert len(children) == 1 and completed is not None
        assert reads == [True]
        assert live_at_fault == [None]
        assert row["child_pid"] == (None if phase == "pid" else children[0].pid)
        assert row["error_type"] == type(control).__name__
        assert row["stage"] == ("wait_failed" if phase == "wait" else "observer_failed")
        assert row["native_returncode"] is None and row["native_signal"] is None
        assert row["exit_code"] is None and row["native_exit_observed_before_failure"] is False
        assert row["cleanup"]["reaped"] is True and row["cleanup"]["budget_seconds"] == 4
        assert 1 <= len(cleanup_waits) <= 2 and all(0 <= timeout <= 2 for timeout in cleanup_waits)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize("label", CONTROL_LABELS)
@pytest.mark.parametrize("code", [0, 17])
def test_completed_native_status_precedes_every_final_publication_control(
    tmp_path, capsys, label, code,
):
    path, calls, control = tmp_path / "receipt.json", [], _owned_control(label)

    def publish(target, row, **kwargs):
        calls.append(row["stage"])
        if row["stage"] == "exited":
            raise control
        native._publish(target, row, **kwargs)

    result = _contained_run([sys.executable, "-c", f"raise SystemExit({code})"], path,
                            publish=publish)
    logged = json.loads(capsys.readouterr().err.splitlines()[-1])
    retained = json.loads(path.read_text())
    assert result == (17 if code else 130 if label == "keyboard" else 1)
    assert calls == ["planned", "started", "exited"]
    assert logged["native_returncode"] == code and logged["cleanup"] is None
    assert logged["error_type"] == type(control).__name__
    assert retained["stage"] == "started"


@pytest.mark.parametrize("label", CONTROL_LABELS)
@pytest.mark.parametrize("code", [0, 17])
def test_observed_native_failure_survives_exit_record_clock_controls(
    tmp_path, monkeypatch, label, code,
):
    path, completed, actions, children = tmp_path / "receipt.json", [], [], []
    clock, control, interrupted = native._utc, _owned_control(label), []

    def utc():
        if completed and not interrupted:
            interrupted.append(True)
            raise control
        return clock()

    def popen(command):
        child = subprocess.Popen(command)
        children.append(child)

        def wait(timeout=None):
            value = child.wait(timeout=timeout)
            completed.append(value)
            return value

        return SimpleNamespace(pid=child.pid, wait=wait,
                               terminate=lambda: actions.append("terminate"),
                               kill=lambda: actions.append("kill"))

    monkeypatch.setattr(native, "_utc", utc)
    try:
        result = _contained_run([sys.executable, "-c", f"raise SystemExit({code})"], path,
                                popen=popen)
        row = json.loads(path.read_text())
        native_status = children[0].poll()
        assert result == (17 if code else 130 if label == "keyboard" else 1)
        assert completed == [code] and actions == [] and native_status == code
        assert row["stage"] == "observer_failed" and row["error_type"] == type(control).__name__
        assert row["native_returncode"] == code and row["exit_code"] == code
        assert row["native_exit_observed_before_failure"] is True and row["cleanup"] is None
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize("label", CONTROL_LABELS)
def test_publication_controls_retain_primary_then_close_and_unlink_failures(
    tmp_path, monkeypatch, label,
):
    control, closed_control = _owned_control(label), SystemExit(7)
    unlink_control = OwnedDirectControl("private-unlink")
    path, descriptors = tmp_path / "receipt.json", []
    factory, unlink = native.tempfile.NamedTemporaryFile, Path.unlink

    def create(**kwargs):
        stream = factory(**kwargs)
        descriptors.append(stream.fileno())
        close = stream.close

        def closed():
            close()
            raise closed_control

        stream.close = closed
        return stream

    def dump(*_args, **_kwargs):
        raise control

    def remove(target, *args, **kwargs):
        unlink(target, *args, **kwargs)
        raise unlink_control

    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", create)
    monkeypatch.setattr(native.json, "dump", dump)
    monkeypatch.setattr(Path, "unlink", remove)
    with pytest.raises(native.PublicationError) as caught:
        native._publish(path, {"owned": True}, initial=True)
    error = caught.value
    assert error.primary is control and error.__cause__ is control and error.published is False
    assert error.failures == [
        {"stage": "serialize", "error_type": type(control).__name__},
        {"stage": "file_close", "error_type": "SystemExit"},
        {"stage": "temporary_unlink", "error_type": "OwnedDirectControl"},
    ]
    retained_exists = path.exists()
    assert len(descriptors) == 1 and not retained_exists
    for descriptor in descriptors:
        with pytest.raises(OSError):
            native.os.fstat(descriptor)


@pytest.mark.parametrize("label", CONTROL_LABELS)
@pytest.mark.parametrize("phase", ["terminate", "terminate_wait"])
def test_cleanup_control_is_secondary_and_original_wait_failure_stays_first(
    tmp_path, monkeypatch, label, phase,
):
    if phase not in {"terminate", "terminate_wait"}:
        raise ValueError("Unsupported cleanup control phase")
    path, waits, actions, control = tmp_path / "receipt.json", [], [], _owned_control(label)
    monkeypatch.setattr(native.time, "monotonic", lambda: 100.0)

    def wait(timeout=None):
        waits.append(timeout)
        if timeout is None:
            raise ChildProcessError("private-first-wait")
        if len(waits) == 2 and phase == "terminate_wait":
            raise control
        return 0

    def terminate():
        actions.append("terminate")
        if phase == "terminate":
            raise control

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait, terminate=terminate,
                            kill=lambda: actions.append("kill"))
    result = _contained_run([], path, popen=lambda _: child)
    row = json.loads(path.read_text())
    assert result == 1 and row["error_type"] == "ChildProcessError"
    assert row["native_returncode"] is None and row["exit_code"] is None
    assert row["cleanup"]["reaped"] is True and row["cleanup"]["returncode_after_cleanup"] == 0
    assert row["cleanup"]["budget_seconds"] == 4
    assert row["cleanup"]["errors"] == [{"stage": phase, "error_type": type(control).__name__}]
    assert waits == ([None, 2] if phase == "terminate" else [None, 2, 2])
    assert actions == (["terminate"] if phase == "terminate" else ["terminate", "kill"])


@pytest.mark.parametrize("label", CONTROL_LABELS)
def test_diagnostic_sink_reports_each_control_as_undelivered_without_raising(monkeypatch, label):
    control = _owned_control(label)

    class Sink:
        def write(self, _value):
            raise control

        def flush(self):
            raise control

    with monkeypatch.context() as scoped:
        scoped.setattr(native.sys, "stderr", Sink())
        result = native._error("owned-control", OSError("private-primary"))
    expected = {"keyboard": "interrupt", "system-exit": "exit",
                "generator-exit": "other_control", "direct-base": "other_control"}
    assert result == {"delivered": False, "failure_kind": expected[label],
                      "error_type": type(control).__name__}


@pytest.mark.parametrize("label", CONTROL_LABELS)
@pytest.mark.parametrize("phase", ["prelaunch", "constructor"])
def test_prechild_controls_propagate_without_claiming_or_constructing_an_owned_child(
    tmp_path, label, phase,
):
    if phase not in {"prelaunch", "constructor"}:
        raise ValueError("Unsupported prechild control phase")
    path, calls, control = tmp_path / "receipt.json", [], _owned_control(label)

    def publish(target, row, **kwargs):
        if phase == "prelaunch":
            raise control
        native._publish(target, row, **kwargs)

    def popen(_command):
        calls.append(True)
        raise control

    with pytest.raises(type(control)) as caught:
        native.run([], path, popen=popen, publish=publish)
    retained_exists = path.exists()
    retained = json.loads(path.read_text()) if retained_exists else None
    assert caught.value is control
    assert calls == ([] if phase == "prelaunch" else [True])
    assert not retained_exists if phase == "prelaunch" else retained["child_pid"] is None


@pytest.mark.parametrize("label", CONTROL_LABELS)
def test_child_ownership_entry_control_happens_before_any_popen(tmp_path, monkeypatch, label):
    control, calls = _owned_control(label), []

    def enter(_self):
        raise control

    monkeypatch.setattr(native.ChildObservation, "__enter__", enter)
    with pytest.raises(type(control)) as caught:
        native.run([], tmp_path / "receipt.json", popen=lambda _: calls.append(True))
    assert caught.value is control and calls == []


@pytest.mark.parametrize("invalid", [None, "0"])
def test_missing_native_wait_status_still_cleans_owned_child_without_promoting_cleanup_zero(
    tmp_path, invalid,
):
    waits, actions = [], []

    def wait(timeout=None):
        waits.append(timeout)
        return invalid if timeout is None else 0

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait,
                            terminate=lambda: actions.append("terminate"),
                            kill=lambda: actions.append("kill"))
    path = tmp_path / "receipt.json"
    result = _contained_run([], path, popen=lambda _: child)
    row = json.loads(path.read_text())
    assert result == 1 and row["error_type"] == "RuntimeError"
    assert row["native_returncode"] is None and row["exit_code"] is None
    assert row["cleanup"]["returncode_after_cleanup"] == 0
    assert waits[0] is None and len(waits) == 2 and actions == ["terminate"]


@pytest.mark.parametrize("label", CONTROL_LABELS)
def test_internal_prelaunch_publication_controls_close_resources_and_never_construct_child(
    tmp_path, monkeypatch, label,
):
    control, calls, descriptors = _owned_control(label), [], []
    path = tmp_path / "receipt.json"
    factory = native.tempfile.NamedTemporaryFile

    def create(**kwargs):
        stream = factory(**kwargs)
        descriptors.append(stream.fileno())
        return stream

    def dump(*_args, **_kwargs):
        raise control

    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", create)
    monkeypatch.setattr(native.json, "dump", dump)
    result = _contained_run([], path, popen=lambda _: calls.append(True))
    exists = path.exists()
    temporary_paths = list(tmp_path.glob(path.name + ".*"))
    assert result == 1 and calls == [] and not exists and temporary_paths == []
    assert len(descriptors) == 1
    for descriptor in descriptors:
        with pytest.raises(OSError):
            native.os.fstat(descriptor)


@pytest.mark.parametrize("label", CONTROL_LABELS)
def test_persistent_timestamp_controls_cannot_prevent_real_owned_child_cleanup(
    tmp_path, monkeypatch, label,
):
    control, children, first_live = _owned_control(label), [], []
    path, clock = tmp_path / "receipt.json", native._utc

    def utc():
        if children:
            if not first_live:
                first_live.append(children[0].poll())
            raise control
        return clock()

    def popen(command):
        child = subprocess.Popen(command)
        children.append(child)
        return child

    monkeypatch.setattr(native, "_utc", utc)
    try:
        result = _contained_run([sys.executable, "-c", "import time;time.sleep(30)"], path,
                                popen=popen)
        row = json.loads(path.read_text())
        completed = children[0].poll()
        assert result == (130 if label == "keyboard" else 1) and first_live == [None]
        assert completed is not None and row["error_type"] == type(control).__name__
        assert row["native_returncode"] is None
        assert row["native_exit_observed_before_failure"] is False
        assert row["finished_at"] is None and row["cleanup"]["reaped"] is True
        assert row["cleanup"]["budget_seconds"] == 4
        assert row["cleanup"]["started_at"] is None and row["cleanup"]["finished_at"] is None
        assert row["cleanup"]["errors"] == [
            {"stage": "started_timestamp", "error_type": type(control).__name__},
            {"stage": "finished_timestamp", "error_type": type(control).__name__},
        ]
        assert row["observer_secondary_errors"] == [
            {"stage": "failure_timestamp", "error_type": type(control).__name__},
        ]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize("label", CONTROL_LABELS)
@pytest.mark.parametrize("clock_phase", ["deadline", "remaining"])
def test_unavailable_cleanup_clock_uses_no_invented_wait_allowance(
    tmp_path, monkeypatch, label, clock_phase,
):
    if clock_phase not in {"deadline", "remaining"}:
        raise ValueError("Unsupported scheduling-clock failure phase")
    control, reads, waits, actions = _owned_control(label), [], [], []

    def monotonic():
        reads.append(True)
        if clock_phase == "deadline" or len(reads) > 1:
            raise control
        return 100.0

    def wait(timeout=None):
        waits.append(timeout)
        if timeout is None:
            raise ChildProcessError("private-first-wait")
        return 0

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait,
                            terminate=lambda: actions.append("terminate"),
                            kill=lambda: actions.append("kill"))
    path = tmp_path / "receipt.json"
    with monkeypatch.context() as scoped:
        scoped.setattr(native.time, "monotonic", monotonic)
        result = _contained_run([], path, popen=lambda _: child)
    row = json.loads(path.read_text())
    assert result == 1 and row["error_type"] == "ChildProcessError"
    assert row["native_returncode"] is None and row["exit_code"] is None
    assert actions == ["terminate"] and waits == [None, 0]
    assert row["cleanup"]["reaped"] is True and row["cleanup"]["returncode_after_cleanup"] == 0
    assert row["cleanup"]["budget_seconds"] == 4
    assert row["cleanup"]["errors"] == [{
        "stage": "deadline_clock" if clock_phase == "deadline" else "remaining_clock",
        "error_type": type(control).__name__,
    }]


@pytest.mark.parametrize("clock_value", [None, float("nan"), float("inf")])
def test_invalid_cleanup_clock_never_creates_a_positive_wait_budget(
    tmp_path, monkeypatch, clock_value,
):
    waits, actions = [], []

    def wait(timeout=None):
        waits.append(timeout)
        if timeout is None:
            raise ChildProcessError("private-first-wait")
        return 0

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait,
                            terminate=lambda: actions.append("terminate"),
                            kill=lambda: actions.append("kill"))
    path = tmp_path / "receipt.json"
    with monkeypatch.context() as scoped:
        scoped.setattr(native.time, "monotonic", lambda: clock_value)
        result = _contained_run([], path, popen=lambda _: child)
    row = json.loads(path.read_text())
    assert result == 1 and waits == [None, 0] and actions == ["terminate"]
    assert row["error_type"] == "ChildProcessError" and row["native_returncode"] is None
    assert row["cleanup"]["errors"] == [{"stage": "deadline_clock", "error_type": "RuntimeError"}]


@pytest.mark.parametrize("first_label", [*CONTROL_LABELS, "error"])
@pytest.mark.parametrize("final_label", ["keyboard", "error", "direct-base"])
@pytest.mark.parametrize("closed_stderr", [False, True])
def test_first_observer_failure_wins_later_publication_and_diagnostic_failures(
    tmp_path, monkeypatch, first_label, final_label, closed_stderr,
):
    if (first_label not in {*CONTROL_LABELS, "error"}
            or final_label not in {"keyboard", "error", "direct-base"}):
        raise ValueError("Unsupported combined first/final failure fixture")
    first = (ChildProcessError("private-first") if first_label == "error"
             else _owned_control(first_label))
    final = (PermissionError("private-final") if final_label == "error"
             else _owned_control(final_label))
    calls, actions, captured = [], [], []
    path = tmp_path / "receipt.json"

    def wait(timeout=None):
        calls.append(timeout)
        if timeout is None:
            raise first
        return 0

    def publish(target, row, **kwargs):
        if row["stage"] == "wait_failed":
            captured.append(json.loads(json.dumps(row)))
            raise final
        native._publish(target, row, **kwargs)

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait,
                            terminate=lambda: actions.append("terminate"),
                            kill=lambda: actions.append("kill"))
    with monkeypatch.context() as scoped:
        if closed_stderr:
            sink = io.StringIO()
            sink.close()
            scoped.setattr(native.sys, "stderr", sink)
        result = _contained_run([], path, popen=lambda _: child, publish=publish)
    assert result == (130 if first_label == "keyboard" else 1)
    assert len(captured) == 1 and captured[0]["error_type"] == type(first).__name__
    assert captured[0]["native_returncode"] is None and captured[0]["exit_code"] is None
    assert captured[0]["cleanup"]["reaped"] is True
    assert captured[0]["cleanup"]["returncode_after_cleanup"] == 0
    assert actions == ["terminate"] and calls[0] is None and len(calls) == 2


@pytest.mark.parametrize("code", [0, 17])
@pytest.mark.parametrize("closed_stderr", [False, True])
def test_recoverable_started_failure_stays_first_over_later_interrupt(
    tmp_path, monkeypatch, code, closed_stderr,
):
    path, stages = tmp_path / "receipt.json", []

    def publish(target, row, **kwargs):
        stages.append(row["stage"])
        if row["stage"] == "started":
            raise PermissionError("private-first-started")
        if row["stage"] == "exited":
            raise KeyboardInterrupt("private-late-interrupt")
        native._publish(target, row, **kwargs)

    with monkeypatch.context() as scoped:
        if closed_stderr:
            sink = io.StringIO()
            sink.close()
            scoped.setattr(native.sys, "stderr", sink)
        result = _contained_run([sys.executable, "-c", f"raise SystemExit({code})"], path,
                                publish=publish)
    retained = json.loads(path.read_text())
    assert result == (17 if code else 1)
    assert stages == ["planned", "started", "exited"] and retained["stage"] == "planned"


def test_stop_calls_with_unavailable_clock_do_not_claim_reaping_or_native_completion(
    tmp_path, monkeypatch,
):
    actions, waits = [], []

    def clock():
        raise OwnedDirectControl("private-clock")

    def wait(timeout=None):
        waits.append(timeout)
        if timeout is None:
            raise ChildProcessError("private-first-wait")
        raise subprocess.TimeoutExpired("private-owned-child", timeout)

    child = SimpleNamespace(pid=os.getpid() + 1, wait=wait,
                            terminate=lambda: actions.append("terminate"),
                            kill=lambda: actions.append("kill"))
    path = tmp_path / "receipt.json"
    with monkeypatch.context() as scoped:
        scoped.setattr(native.time, "monotonic", clock)
        result = _contained_run([], path, popen=lambda _: child)
    row = json.loads(path.read_text())
    assert result == 1 and row["error_type"] == "ChildProcessError"
    assert actions == ["terminate", "kill"] and waits == [None, 0, 0]
    assert row["native_returncode"] is None and row["native_signal"] is None
    assert row["exit_code"] is None
    assert row["cleanup"]["reaped"] is False and row["cleanup"]["returncode_after_cleanup"] is None
    assert row["cleanup"]["errors"] == [
        {"stage": "deadline_clock", "error_type": "OwnedDirectControl"},
        {"stage": "terminate_wait", "error_type": "TimeoutExpired"},
        {"stage": "kill_wait", "error_type": "TimeoutExpired"},
    ]


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("label", ["error", "keyboard", "system-exit", "direct-base"])
def test_directory_open_refusal_keeps_published_bytes_without_inventing_owned_descriptor(
    tmp_path, monkeypatch, initial, label,
):
    if (type(initial) is not bool
            or label not in {"error", "keyboard", "system-exit", "direct-base"}):
        raise ValueError("Unsupported synthetic directory-opener fixture")
    primary = OSError("owned-synthetic-open") if label == "error" else _owned_control(label)
    path = tmp_path / "receipt.json"
    expected_publication = (
        b'{\r\n  "owned": true\r\n}\r\n' if sys.platform == "win32"
        else b'{\n  "owned": true\n}\n'
    )
    if not initial:
        path.write_bytes(b"previous-owned-publication\n")
    owners, streams, descriptors, opens, syncs, closes = [], [], [], [], [], []
    owner_type, temporary_factory = native.PublicationAttempt, native.tempfile.NamedTemporaryFile
    real_fsync, real_fstat = os.fsync, os.fstat
    directory_flag = 0x10000

    def owner(target, first):
        value = owner_type(target, first)
        owners.append(value)
        return value

    def temporary(**kwargs):
        stream = temporary_factory(**kwargs)
        streams.append(stream)
        descriptors.append(stream.fileno())
        return stream

    def refuse_open(target, flags):
        value = owners[0]
        opens.append((target, flags, value.directory_descriptor, value.directory_stage))
        raise primary

    def sync(descriptor):
        syncs.append(descriptor)
        if descriptor not in descriptors:
            raise AssertionError("Synthetic opener must not invent a directory descriptor")
        real_fsync(descriptor)

    def close(descriptor):
        closes.append(descriptor)
        raise AssertionError("Failed synthetic opener has no directory descriptor to close")

    # Only this helper's os binding is synthetic. Global os.name, tempfile and
    # pathlib retain the actual platform. No POSIX directory syscall occurs.
    proxy = SimpleNamespace(name="posix", O_RDONLY=os.O_RDONLY, O_DIRECTORY=directory_flag,
                            open=refuse_open, fsync=sync, close=close,
                            link=os.link, replace=os.replace)
    monkeypatch.setattr(native, "os", proxy)
    monkeypatch.setattr(native, "PublicationAttempt", owner)
    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", temporary)
    with pytest.raises(native.PublicationError) as caught:
        native._publish(path, {"owned": True}, initial=initial)
    error = caught.value
    retained = path.read_bytes()
    temporary_paths = list(tmp_path.glob(path.name + ".*"))
    owner_states = [(value.directory_descriptor, value.directory_stage, value.published)
                    for value in owners]
    stream_states = [stream.closed for stream in streams]
    assert error.primary is primary and error.__cause__ is primary and error.published is True
    assert error.failures == [{"stage": "directory_open", "error_type": type(primary).__name__}]
    assert retained == expected_publication and temporary_paths == []
    assert owner_states == [(None, "directory_open", True)]
    assert opens == [(path.parent, os.O_RDONLY | directory_flag, None, "directory_open")]
    assert syncs == descriptors and len(descriptors) == 1 and closes == []
    assert stream_states == [True]
    for descriptor in descriptors:
        with pytest.raises(OSError):
            real_fstat(descriptor)
