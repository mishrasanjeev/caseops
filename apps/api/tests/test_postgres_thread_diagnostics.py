"""Diagnostic contracts; no result here certifies a PostgreSQL workflow."""
import faulthandler
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import postgres_thread_diagnostics as diagnostics


def test_snapshot_retains_only_bounded_code_locations_not_locals():
    private_canary = "UNIT_PRIVATE_FRAME_LOCAL_MUST_NOT_APPEAR"
    value = diagnostics._snapshot("a" * 64, time.monotonic())
    assert private_canary not in json.dumps(value)
    assert value["after_seconds"] == 60 and value["locals_retained"] is False
    assert value["retries"] == 0 and len(value["stacks"]) <= diagnostics.MAX_THREADS
    assert all(len(stack["frames"]) <= diagnostics.MAX_FRAMES for stack in value["stacks"])
    assert all(set(frame) == {"file", "function", "line"}
               for stack in value["stacks"] for frame in stack["frames"])
    assert any(frame["file"] == Path(__file__).name
               for stack in value["stacks"] for frame in stack["frames"])


def test_actual_observer_thread_publishes_one_private_uploaded_jsonl(tmp_path):
    observer = diagnostics.TimedFrames(tmp_path, "synthetic-native-case", after=0.01)
    observer.start()
    observer.thread.join(2)
    observer.close()
    assert not observer.thread.is_alive()
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    expected = "python-threads-" + hashlib.sha256(b"synthetic-native-case").hexdigest() + ".jsonl"
    assert files[0].name == expected
    value = json.loads(files[0].read_bytes())
    assert value["event"] == "postgres_python_thread_diagnostic"
    assert value["elapsed_seconds"] >= 0.01
    assert value["thread_count"] >= 2
    assert any(frame["function"] == "_run"
               for stack in value["stacks"] for frame in stack["frames"])
    if hasattr(diagnostics.os, "getuid"):
        assert files[0].stat().st_mode & 0o777 == 0o600


def test_observer_finishing_before_original_sixty_seconds_cancels_without_output(tmp_path):
    observer = diagnostics.TimedFrames(tmp_path, "synthetic-fast-case")
    assert observer.after == 60
    observer.start()
    observer.close()
    assert not observer.thread.is_alive()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure_type", [SystemExit, KeyboardInterrupt])
def test_thread_control_flow_propagates_and_close_cannot_report_publication(
    monkeypatch, tmp_path, failure_type,
):
    original = failure_type("unit-thread-control-flow")
    escaped = []

    def fail_publication(*_args):
        raise original

    monkeypatch.setattr(diagnostics, "_write", fail_publication)
    monkeypatch.setattr(
        diagnostics.threading, "excepthook", lambda args: escaped.append(args.exc_value),
    )
    observer = diagnostics.TimedFrames(tmp_path, "synthetic-control-flow", after=0.01)
    observer.start()
    observer.thread.join(2)
    assert escaped == [original]
    assert observer.failure is original
    with pytest.raises(RuntimeError, match="publication failed") as failure:
        observer.close()
    assert failure.value.__cause__ is original
    assert not observer.thread.is_alive()
    assert list(tmp_path.iterdir()) == []


def test_exclusive_publication_preserves_existing_failure_and_never_replays(tmp_path):
    digest = "a" * 64
    diagnostics._write(tmp_path, digest, {"original": True})
    path = next(tmp_path.iterdir())
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        diagnostics._write(tmp_path, digest, {"replacement": True})
    assert path.read_bytes() == original
    with pytest.raises(AssertionError, match="byte bound"):
        diagnostics._write(tmp_path, "b" * 64, {"payload": "x" * diagnostics.MAX_BYTES})
    assert list(tmp_path.iterdir()) == [path]


def test_symlink_root_refuses_before_writing_and_observer_failure_is_not_silenced(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)
    observer = diagnostics.TimedFrames(link, "synthetic-root-refusal", after=0.01)
    observer.start()
    observer.thread.join(2)
    with pytest.raises(RuntimeError, match="publication failed") as failure:
        observer.close()
    assert isinstance(failure.value.__cause__, AssertionError)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("native_timer,environment", [(60, True), (0, False)])
def test_configuration_requires_independent_uploaded_observer_and_no_unsafe_timer_overlap(
    monkeypatch, tmp_path, native_timer, environment,
):
    if environment:
        monkeypatch.setenv("CASEOPS_FINALIZER_EVIDENCE_DIR", str(tmp_path))
    else:
        monkeypatch.delenv("CASEOPS_FINALIZER_EVIDENCE_DIR", raising=False)
    with pytest.raises(pytest.UsageError):
        diagnostics.pytest_configure(SimpleNamespace(getini=lambda _: native_timer))


@pytest.mark.parametrize("disabled_timer", [0, "0", "0.0"])
def test_exact_sixty_second_cli_contract_and_normal_gil_runtime(
    monkeypatch, tmp_path, disabled_timer,
):
    options = []
    group = SimpleNamespace(addoption=lambda *a, **k: options.append((a, k)))
    parser = SimpleNamespace(getgroup=lambda _: group)
    diagnostics.pytest_addoption(parser)
    assert options == [
        (("--postgres-thread-diagnostics-after",), {"type": int, "choices": [60], "default": 60}),
    ]
    monkeypatch.setenv("CASEOPS_FINALIZER_EVIDENCE_DIR", str(tmp_path))
    diagnostics.pytest_configure(SimpleNamespace(getini=lambda _: disabled_timer))
    assert faulthandler.is_enabled(), "Fatal crash reporting must remain active"
    monkeypatch.setattr(diagnostics.sys, "_is_gil_enabled", lambda: False)
    with pytest.raises(pytest.UsageError, match="GIL-enabled"):
        diagnostics.pytest_configure(SimpleNamespace(getini=lambda _: disabled_timer))


def test_cleanup_error_never_replaces_original_hook_failure(monkeypatch, tmp_path, capsys):
    effects = []
    class Observer:
        def __init__(self, root, nodeid):
            assert root == tmp_path and nodeid == "unit-case"
        def start(self):
            effects.append("start")
        def close(self):
            effects.append("close")
            raise RuntimeError("unit-diagnostic-cleanup")
    monkeypatch.setattr(diagnostics, "TimedFrames", Observer)
    monkeypatch.setenv("CASEOPS_FINALIZER_EVIDENCE_DIR", str(tmp_path))
    body = RuntimeError("unit-original-hook-failure")
    hook = diagnostics.pytest_runtest_protocol(SimpleNamespace(nodeid="unit-case"), None)
    next(hook)
    with pytest.raises(RuntimeError) as failure:
        hook.throw(body)
    assert failure.value is body
    assert effects == ["start", "close"]
    assert capsys.readouterr().err == "Python thread diagnostic cleanup also failed.\n"


def test_frame_limits_are_explicit_and_frame_labels_cannot_disclose_paths(monkeypatch):
    code = SimpleNamespace(co_filename="/private/workspace/unit.py", co_name="synthetic_function")
    frame = SimpleNamespace(f_code=code, f_lineno=12, f_back=None)
    frame.f_back = frame
    observed = {index: frame for index in range(diagnostics.MAX_THREADS + 1)}
    with monkeypatch.context() as scoped:
        scoped.setattr(diagnostics.sys, "_current_frames", lambda: dict(observed))
        value = diagnostics._snapshot("a" * 64, time.monotonic())
    assert value["thread_count"] == diagnostics.MAX_THREADS + 1
    assert value["threads_truncated"] is True
    assert len(value["stacks"]) == diagnostics.MAX_THREADS
    assert all(len(stack["frames"]) == diagnostics.MAX_FRAMES and stack["truncated"]
               for stack in value["stacks"])
    assert "/private/workspace" not in json.dumps(value)
    assert len(json.dumps(value).encode()) < diagnostics.MAX_BYTES
    frame.f_back = None
