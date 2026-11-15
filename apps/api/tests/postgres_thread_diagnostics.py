"""Bounded Python-frame diagnostics, without an out-of-GIL timed C stack walk.

This is an observer, not a timeout or a test retry. Fatal-signal faulthandler
remains enabled; the outer CI job and every workflow assertion keep their bounds.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

AFTER_SECONDS = 60
MAX_THREADS = 100
MAX_FRAMES = 100
MAX_BYTES = 2 * 1024 * 1024
_SAFE_LABEL = re.compile(r"[A-Za-z0-9_.<>-]{1,96}")


def _label(value: str) -> str:
    return value if _SAFE_LABEL.fullmatch(value) else "unavailable"


def _snapshot(case_hash: str, started: float) -> dict:
    # Python owns strong references to these frames and reads them while holding
    # the GIL. Do not retain locals, source text or frame references in the result.
    frames = sys._current_frames()
    stacks = []
    try:
        for _thread, frame in sorted(frames.items())[:MAX_THREADS]:
            stack = []
            try:
                for _ in range(MAX_FRAMES):
                    if frame is None:
                        break
                    code = frame.f_code
                    stack.append({"file": _label(Path(code.co_filename).name),
                                  "function": _label(code.co_name), "line": frame.f_lineno})
                    frame = frame.f_back
                stacks.append({"frames": stack, "truncated": frame is not None})
            finally:
                del frame
        return {"event": "postgres_python_thread_diagnostic", "case_sha256": case_hash,
                "after_seconds": AFTER_SECONDS, "elapsed_seconds": time.monotonic() - started,
                "thread_count": len(frames), "threads_truncated": len(frames) > MAX_THREADS,
                "stacks": stacks, "locals_retained": False, "retries": 0}
    finally:
        frames.clear()


def _write(root: Path, case_hash: str, value: dict) -> None:
    assert re.fullmatch(r"[a-f0-9]{64}", case_hash), "Exact case hash required"
    root = root.absolute()
    root.mkdir(parents=True, exist_ok=True)
    assert root.resolve(strict=True) == root, "Thread diagnostic root must be canonical"
    metadata = root.lstat()
    assert stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)
    if hasattr(os, "getuid"):
        assert metadata.st_uid == os.getuid(), "Thread diagnostic root must be owned"
    raw = (json.dumps(value, separators=(",", ":")) + "\n").encode()
    assert len(raw) <= MAX_BYTES, "Thread diagnostic byte bound exceeded"
    target = root / ("python-threads-" + case_hash + ".jsonl")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            assert count > 0, "Thread diagnostic write stalled"
            offset += count
        os.fsync(fd)
        opened, named = os.fstat(fd), target.lstat()
        assert stat.S_ISREG(opened.st_mode) and not stat.S_ISLNK(named.st_mode)
        assert opened.st_nlink == named.st_nlink == 1 and opened.st_ino == named.st_ino
        assert opened.st_size == len(raw)
    finally:
        os.close(fd)


class TimedFrames:
    def __init__(self, root: Path, nodeid: str, *, after: float = AFTER_SECONDS):
        self.root = root
        self.case_hash = hashlib.sha256(nodeid.encode()).hexdigest()
        self.started = time.monotonic()
        self.after = after
        self.stop = threading.Event()
        self.failure: BaseException | None = None
        self.thread = threading.Thread(
            target=self._run, name="postgres-thread-diagnostic", daemon=True,
        )

    def _run(self):
        if self.stop.wait(self.after):
            return
        try:
            _write(self.root, self.case_hash, _snapshot(self.case_hash, self.started))
        except Exception as error:
            self.failure = error
        finally:
            # SystemExit/KeyboardInterrupt must keep their normal thread
            # propagation and still make close fail, rather than look like a
            # successfully published observation.
            if (active_error := sys.exception()) is not None:
                self.failure = active_error

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("Thread diagnostic cleanup did not complete")
        if self.failure is not None:
            raise RuntimeError("Thread diagnostic publication failed") from self.failure


def pytest_addoption(parser):
    parser.getgroup("postgres-diagnostics").addoption(
        "--postgres-thread-diagnostics-after", type=int, choices=[AFTER_SECONDS],
        default=AFTER_SECONDS,
    )


def pytest_configure(config):
    native_timer = config.getini("faulthandler_timeout")
    if type(native_timer) not in (int, float, str) or float(native_timer) != 0:
        raise pytest.UsageError(
            "Timed native faulthandler and Python thread diagnostics must not overlap"
        )
    if sys.implementation.name != "cpython" or not getattr(sys, "_is_gil_enabled", lambda: True)():
        raise pytest.UsageError(
            "Python thread diagnostics require the normal GIL-enabled CPython runtime"
        )
    if not os.environ.get("CASEOPS_FINALIZER_EVIDENCE_DIR"):
        raise pytest.UsageError(
            "Python thread diagnostics require the uploaded native evidence directory"
        )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    observer = TimedFrames(Path(os.environ["CASEOPS_FINALIZER_EVIDENCE_DIR"]), item.nodeid)
    observer.start()
    body_failure = None
    try:
        return (yield)
    except BaseException as error:
        body_failure = error
        raise
    finally:
        try:
            observer.close()
        except BaseException:
            if body_failure is None:
                raise
            # Keep the original thrown hook exception. Its native exit is
            # already unsuccessful; never turn cleanup into an apparent pass.
            sys.stderr.write("Python thread diagnostic cleanup also failed.\n")
