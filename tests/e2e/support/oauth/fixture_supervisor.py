"""One bounded, offline unittest child; never retry or leave its process tree alive."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

EVENT_PREFIX = "CASEOPS_FIXTURE_EVENT "


def emit(event: str, **fields: object) -> None:
    print(EVENT_PREFIX + json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


class WindowsJob:
    """Kernel-owned identity: no PID lookup/tree walk and no breakaway permission."""

    def __init__(self) -> None:
        import ctypes.wintypes as wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Limits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
            ]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL,
            ),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "QueryInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                 ctypes.c_void_p], wintypes.BOOL,
            ),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process: subprocess.Popen) -> None:
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, process: subprocess.Popen) -> None:
        import ctypes.wintypes as wintypes

        class ThreadEntry(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                ("thread_id", wintypes.DWORD), ("owner_pid", wintypes.DWORD),
                ("base_priority", wintypes.LONG), ("delta_priority", wintypes.LONG),
                ("flags", wintypes.DWORD),
            ]

        signatures = {
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(ThreadEntry)], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(ThreadEntry)], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        snapshot = self.api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        thread = None
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = self.api.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.owner_pid == process.pid:
                    thread = self.api.OpenThread(2, False, entry.thread_id)
                    break
                found = self.api.Thread32Next(snapshot, ctypes.byref(entry))
            if not thread:
                raise OSError("owned_suspended_thread_not_found")
            if self.api.ResumeThread(thread) != 1:
                raise OSError("owned_thread_resume_failed")
        finally:
            if thread:
                self.api.CloseHandle(thread)
            self.api.CloseHandle(snapshot)

    def kill(self) -> None:
        if not self.api.TerminateJobObject(self.handle, 124):
            raise ctypes.WinError(ctypes.get_last_error())

    def active(self) -> int:
        # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four LARGE_INTEGERs, four DWORDs.
        data = (ctypes.c_uint64 * 6)()
        if not self.api.QueryInformationJobObject(
            self.handle, 1, ctypes.byref(data), ctypes.sizeof(data), None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return (ctypes.c_uint32 * 12).from_buffer(data)[10]

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def child_exited(process: subprocess.Popen) -> bool:
    if os.name == "nt":
        return process.poll() is not None
    # Retain the unreaped leader's PID until group cleanup, avoiding PGID reuse.
    return os.waitid(
        os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT,
    ) is not None


def cleanup(process: subprocess.Popen, job: WindowsJob | None, grace: float) -> bool:
    end = time.monotonic() + grace
    emit("cleanup_started", pid=process.pid)
    try:
        if job is None:
            os.killpg(process.pid, signal.SIGTERM)
        elif process.poll() is None:
            process.terminate()
        until = min(end, time.monotonic() + grace / 3)
        while not child_exited(process) and time.monotonic() < until:
            time.sleep(0.01)
        if job is None:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            job.kill()
        emit("cleanup_kill_sent", pid=process.pid)
        process.wait(timeout=max(0.001, end - time.monotonic()))
        while time.monotonic() < end:
            if job is not None:
                if job.active() == 0:
                    return True
            else:
                try:
                    # Linux subreaper adopts only this session's orphaned descendants.
                    while os.waitpid(-process.pid, os.WNOHANG)[0]:
                        pass
                except ChildProcessError:
                    # No adopted descendant remains in this owned process group.
                    pass
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return True
            time.sleep(0.01)
        return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass


def run_fixture(args: argparse.Namespace) -> int:
    started = time.monotonic()
    process = None
    job = None
    previous_subreaper = ctypes.c_int()
    libc = None
    status, reason, cleaned = 2, "start_failed", True
    emit("supervisor_started", pattern=args.pattern, deadline_seconds=args.deadline_seconds)
    try:
        directory = Path(args.start_directory)
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError("invalid_source_directory")
        directory = directory.resolve(strict=True)
        if not re.fullmatch(r"test_[a-zA-Z0-9_]+\.py", args.pattern):
            raise ValueError("invalid_pattern")
        source = directory / args.pattern
        if not source.is_file() or source.is_symlink() or source.resolve().parent != directory:
            raise ValueError("invalid_source_file")
        if (
            not math.isfinite(args.deadline_seconds) or not 0 < args.deadline_seconds <= 50
            or not math.isfinite(args.cleanup_grace_seconds)
            or not 0 < args.cleanup_grace_seconds <= 6
            or args.cleanup_grace_seconds >= args.deadline_seconds or args.expected_tests < 1
        ):
            raise ValueError("invalid_budget_or_inventory")
        if os.name == "nt":
            job = WindowsJob()
        elif sys.platform.startswith("linux"):
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(37, ctypes.byref(previous_subreaper), 0, 0, 0) != 0:
                raise OSError("subreaper_query_failed")
            if libc.prctl(36, 1, 0, 0, 0) != 0:
                raise OSError("subreaper_setup_failed")
        else:
            raise ValueError("unsupported_process_ownership")
        command = [
            sys.executable, "-I", "-S", "-B", "-u", str(Path(__file__).resolve()), "--child",
            "--start-directory", str(directory), "--pattern", args.pattern,
            "--expected-tests", str(args.expected_tests),
        ]
        environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, env=environment,
            start_new_session=os.name != "nt",
            creationflags=0x00000004 if os.name == "nt" else 0,  # CREATE_SUSPENDED
        )
        if job is not None:
            job.assign(process)
            # A venv launcher must not spawn its interpreter before job ownership.
            job.resume(process)
        emit("child_started", pid=process.pid, source_sha256=hashlib.sha256(
            source.read_bytes(),
        ).hexdigest())
        # -I -S keeps site/test imports behind ownership assignment on Windows.
        process.stdin.write(b"1")
        process.stdin.flush()
        # Reserve cleanup INSIDE the total deadline, never another six seconds after it.
        expires = started + args.deadline_seconds - args.cleanup_grace_seconds
        while True:
            if time.monotonic() >= expires:
                status, reason = 124, "deadline_exceeded"
                emit("child_timeout", pid=process.pid)
                break
            if child_exited(process):
                status, reason = 0, "child_exited"
                break
            time.sleep(0.01)
    except (KeyboardInterrupt, InterruptedError):
        status, reason = 130, "interrupted"
        emit("supervisor_interrupted")
    except (OSError, ValueError) as error:
        emit("supervisor_error", error_type=type(error).__name__)
    finally:
        if process is not None:
            remaining = max(0.001, started + args.deadline_seconds - time.monotonic())
            cleaned = cleanup(process, job, min(args.cleanup_grace_seconds, remaining))
            if status == 0:
                status = process.returncode if process.returncode is not None else 125
        if job is not None:
            job.close()
        if libc is not None:
            libc.prctl(36, previous_subreaper.value, 0, 0, 0)
        if not cleaned:
            status, reason = 125, "cleanup_incomplete"
        status = status if 0 <= status <= 255 else 1
        emit(
            "supervisor_finished", exit_code=status, reason=reason, tree_reaped=cleaned,
            child_exit_code=process.returncode if process is not None else None,
            duration_seconds=round(time.monotonic() - started, 3),
        )
    return status


def run_child(args: argparse.Namespace) -> int:
    if sys.stdin.buffer.read(1) != b"1":
        return 2
    import site

    site.main()
    import unittest

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            emit("test_started", test_id=test.id())
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            emit("test_finished", test_id=test.id())

    def identities(suite):
        for test in suite:
            if isinstance(test, unittest.TestSuite):
                yield from identities(test)
            else:
                yield test.id()

    sys.path.insert(0, args.start_directory)
    suite = unittest.TestLoader().discover(args.start_directory, pattern=args.pattern)
    inventory = list(identities(suite))
    emit("collection", test_ids=inventory)
    if len(inventory) != args.expected_tests or len(set(inventory)) != len(inventory):
        emit("inventory_rejected", expected=args.expected_tests, actual=len(inventory))
        return 2
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    emit(
        "unittest_finished", tests_run=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped),
    )
    return 0 if result.wasSuccessful() and not result.skipped else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-directory", required=True)
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--expected-tests", type=int, required=True)
    parser.add_argument("--deadline-seconds", type=float, default=50)
    parser.add_argument("--cleanup-grace-seconds", type=float, default=6)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return run_child(args)

    def interrupted(_signal, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise InterruptedError

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        return run_fixture(args)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
