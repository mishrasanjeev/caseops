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
