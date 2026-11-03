"""Run pytest with native child-exit evidence; never retry or change its arguments."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


def _utc():
    return datetime.now(UTC).isoformat()


def _runtime_modes_match(opened, named, *, windows_executable=False):
    if not stat.S_ISREG(opened) or not stat.S_ISREG(named):
        return False
    # Windows derives executable bits from the pathname; its opened descriptor
    # retains0666. Admit only that observed pair, never an arbitrary mode change.
    return opened == named or (
        windows_executable and (opened, named) == (stat.S_IFREG | 0o666, stat.S_IFREG | 0o777)
    )


def _runtime():
    target = Path(sys.executable).resolve(strict=True)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")

    def identity(value):
        return tuple(getattr(value, key) for key in fields)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(target, flags)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            before, named = os.fstat(stream.fileno()), target.lstat()
            modes_match = _runtime_modes_match(
                before.st_mode, named.st_mode,
                windows_executable=os.name == "nt" and target.suffix.lower() == ".exe",
            )
            if not modes_match or identity(before) != identity(named):
                raise RuntimeError("runtime_identity_refused")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            after, final = os.fstat(stream.fileno()), target.lstat()
            if (identity(before) != identity(after) or identity(named) != identity(final)
                    or before.st_mode != after.st_mode or named.st_mode != final.st_mode
                    or before.st_ctime_ns != after.st_ctime_ns
                    or named.st_ctime_ns != final.st_ctime_ns):
                raise RuntimeError("runtime_changed_during_read")
    finally:
        os.close(descriptor)
    return {"executable": sys.executable, "resolved": str(target), "sha256": digest,
            "bytes": before.st_size, "device": before.st_dev, "inode": before.st_ino}


class FailureKind(Enum):
    ERROR = "error"
    INTERRUPT = "interrupt"
    EXIT = "exit"
    CONTROL = "other_control"


class Failure:
    """Keep control requests distinct from recoverable operational errors."""
    def __init__(self, error):
        self.error = error
        if isinstance(error, KeyboardInterrupt):
            self.kind = FailureKind.INTERRUPT
        elif isinstance(error, SystemExit):
            self.kind = FailureKind.EXIT
        elif isinstance(error, Exception):
            self.kind = FailureKind.ERROR
        else:
            # Includes GeneratorExit and custom direct control exceptions.
            self.kind = FailureKind.CONTROL

    @property
    def observer_exit(self):
        return 130 if self.kind is FailureKind.INTERRUPT else 1


class OperationOutcome:
    """Transfer an operation's failure to its explicit resource owner.

    This boundary makes no recovery decision. Callers must inspect failure;
    controls are not interchangeable with recoverable Exception failures.
    """
    def __init__(self):
        self.failure = None

    def __enter__(self):
        return self

    def __exit__(self, _type, error, _traceback):
        if error is None:
            return False
        self.failure = Failure(error)
        return True


class PublicationError(Exception):
    def __init__(self, errors, published):
        super().__init__("native_receipt_publication_failed")
        self.primary, self.published = errors[0][1], published
        self.failures = [{"stage": stage, "error_type": type(error).__name__}
                         for stage, error in errors]


class PublicationAttempt:
    """One publication owns its stream, temporary name and directory descriptor."""
    def __init__(self, path, initial):
        self.path, self.initial = path, initial
        self.stream, self.temporary = None, None
        self.published, self.stage, self.errors = False, "open", []

    def __enter__(self):
        return self

    def record(self, stage, outcome):
        if outcome.failure is not None:
            self.errors.append((stage, outcome.failure.error))

    def __exit__(self, _type, error, _traceback):
        if error is not None:
            self.errors.append((self.stage, error))
        if self.stream is not None:
            with OperationOutcome() as closed:
                self.stream.close()
            self.record("file_close", closed)
        if not self.errors:
            with OperationOutcome() as linked:
                (os.link if self.initial else os.replace)(self.temporary, self.path)
                self.published = True
            self.record("link" if self.initial else "replace", linked)
        if self.temporary is not None:
            with OperationOutcome() as removed:
                self.temporary.unlink(missing_ok=True)
            self.record("temporary_unlink", removed)
        if self.published and os.name == "posix":
            descriptor, stage = None, "directory_open"
            with OperationOutcome() as synced:
                descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                stage = "directory_fsync"
                os.fsync(descriptor)
            self.record(stage, synced)
            if descriptor is not None:
                with OperationOutcome() as closed:
                    os.close(descriptor)
                self.record("directory_close", closed)
        # All failures become one chained publication failure immediately after
        # this owner finishes. A control never turns into a published success.
        return error is not None


def _publish(path, value, *, initial=False):
    with PublicationAttempt(path, initial) as attempt:
        attempt.stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                      prefix=path.name + ".", delete=False)
        attempt.temporary = Path(attempt.stream.name)
        attempt.stage = "serialize"
        json.dump(value, attempt.stream, ensure_ascii=True, indent=2)
        attempt.stream.write("\n")
        attempt.stage = "flush"
        attempt.stream.flush()
        attempt.stage = "file_fsync"
        os.fsync(attempt.stream.fileno())
    if attempt.errors:
        raise PublicationError(attempt.errors, attempt.published) from attempt.errors[0][1]


def _error(stage, error, native_returncode=None, cleanup=None):
    """Best-effort diagnostics have an explicit delivered/undelivered outcome."""
    with OperationOutcome() as emitted:
        publication = ({"published": error.published, "failures": error.failures}
                       if isinstance(error, PublicationError) else None)
        print(json.dumps({"native_receipt_error": stage, "error_type": type(error).__name__,
                          "native_returncode": native_returncode, "cleanup": cleanup,
                          "publication": publication, "observed_at": _utc()}),
              file=sys.stderr, flush=True)
    failure = emitted.failure
    return {"delivered": failure is None,
            "failure_kind": None if failure is None else failure.kind.value,
            "error_type": None if failure is None else type(failure.error).__name__}


def _cleanup(child):
    """Stop/reap only this invocation's original handle under one four-second budget."""
    deadline = None
    result = {"budget_seconds": 4, "reaped": False, "returncode_after_cleanup": None,
              "reaped_after_attempt": None, "errors": [], "started_at": None,
              "finished_at": None}

    def telemetry(stage, operation):
        value = None
        with OperationOutcome() as observed:
            value = operation()
        if observed.failure is not None:
            result["errors"].append({"stage": stage,
                                     "error_type": type(observed.failure.error).__name__})
        return value

    def scheduling_clock():
        value = time.monotonic()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise RuntimeError("cleanup_clock_unavailable")
        return value

    started = telemetry("deadline_clock", scheduling_clock)
    if type(started) in (int, float):
        deadline = started + 4
    result["started_at"] = telemetry("started_timestamp", _utc)
    for action in ("terminate", "kill"):
        with OperationOutcome() as stopped:
            getattr(child, action)()
        if stopped.failure is not None:
            result["errors"].append({"stage": action,
                                     "error_type": type(stopped.failure.error).__name__})
        # If the scheduling clock is unavailable, an immediate wait is the
        # only justified budget. Stop/reap is still attempted; no new allowance
        # is invented and telemetry cannot prevent original-handle cleanup.
        remaining = 0
        if deadline is not None:
            current = telemetry("remaining_clock", scheduling_clock)
            if type(current) in (int, float):
                remaining = min(2, max(0, deadline - current))
        code = None
        with OperationOutcome() as waited:
            code = child.wait(timeout=remaining)
            if type(code) is not int:
                raise RuntimeError("cleanup_native_status_missing")
        if waited.failure is not None:
            result["errors"].append({"stage": action + "_wait",
                                     "error_type": type(waited.failure.error).__name__})
        else:
            result.update(reaped=True, returncode_after_cleanup=code, reaped_after_attempt=action)
            break
    result["finished_at"] = telemetry("finished_timestamp", _utc)
    return result


class ChildObservation:
    """Own the original child through every post-constructor observer boundary."""
    def __init__(self):
        self.child, self.pid, self.phase = None, None, "started_publication"
        self.code, self.failure, self.error, self.cleanup = None, None, None, None
        self.first_failure = None

    def __enter__(self):
        return self

    @property
    def observed(self):
        return type(self.code) is int

    def record_failure(self, error):
        primary = error.primary if isinstance(error, PublicationError) else error
        failure = Failure(primary)
        if self.first_failure is None:
            self.first_failure = failure
        return failure

    def __exit__(self, _type, error, _traceback):
        if error is None or self.child is None:
            return False
        self.error = error
        self.failure = self.record_failure(error)  # Retain the first cause before cleanup can fail.
        if not self.observed:
            with OperationOutcome() as cleaned:
                self.cleanup = _cleanup(self.child)
            if cleaned.failure is not None:
                self.cleanup = {"budget_seconds": 4, "reaped": False, "observer_failed": True,
                                "errors": [{"stage": "cleanup_observer",
                                            "error_type": type(cleaned.failure.error).__name__}]}
        # This CLI translates observer controls into failed receipt outcomes;
        # it never substitutes a cleanup result for the missing native exit.
        return True


def run(command, receipt, *, popen=subprocess.Popen, publish=_publish):
    """The CLI supplies only pytest; units may supply an owned trivial Python child."""
    row = {"schema_version": 1, "stage": "planned", "source_sha": os.getenv("GITHUB_SHA"),
           "launcher_pid": os.getpid(), "child_pid": None, "planned_at": _utc(),
           "started_at": None, "finished_at": None, "native_returncode": None,
           "native_signal": None, "exit_code": None, "publication_errors": []}
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", row["source_sha"] or ""):
            raise ValueError("source_sha_required")
        row["runtime"] = _runtime()
        publish(receipt, row, initial=True)
    except Exception as error:
        _error("prelaunch", error)
        return 1
    observer_exit = 1
    # Ownership is entered before Popen; even pid/clock/started-record failures
    # remain inside the lifetime of the exact returned child handle.
    with ChildObservation() as observation:
        try:
            # Inherit exact environment and raw standard streams.
            observation.child = popen(command)
        except Exception as error:
            row.update(stage="constructor_failed", error_type=type(error).__name__,
                       finished_at=_utc())
            _error("constructor", error)
            try:
                publish(receipt, row)
            except Exception as publication:
                _error("constructor_publication", publication)
            return 1
        observation.pid = observation.child.pid
        row.update(stage="started", child_pid=observation.pid, started_at=_utc())
        try:
            publish(receipt, row)
        except Exception as error:
            if (isinstance(error, PublicationError)
                    and Failure(error.primary).kind is not FailureKind.ERROR):
                raise
            observation.record_failure(error)
            row["publication_errors"].append("started")
            _error("started_publication", error)
        observation.phase = "wait"
        # Existing twelve-minute CI job cap remains the outer bound.
        observation.code = observation.child.wait()
        if not observation.observed:
            raise RuntimeError("native_status_missing")
        observation.phase = "exit_record"
        unix_signal = -observation.code if observation.code < 0 and os.name == "posix" else None
        row.update(native_returncode=observation.code, native_signal=unix_signal,
                   exit_code=128 + unix_signal if unix_signal else observation.code,
                   finished_at=_utc(), stage="exited")
    observed, code = observation.observed, observation.code
    if observation.failure is not None:
        failure = observation.failure
        finished_at = None
        with OperationOutcome() as timestamp:
            finished_at = _utc()
        row.update(stage="wait_failed" if observation.phase == "wait" else "observer_failed",
                   child_pid=observation.pid, error_type=type(failure.error).__name__,
                   finished_at=finished_at if timestamp.failure is None else None,
                   native_exit_observed_before_failure=observed, cleanup=observation.cleanup)
        if timestamp.failure is not None:
            row["observer_secondary_errors"] = [
                {"stage": "failure_timestamp",
                 "error_type": type(timestamp.failure.error).__name__},
            ]
        _error(observation.phase, observation.error, code if observed else None,
               observation.cleanup)
    if observed:
        unix_signal = -code if code < 0 and os.name == "posix" else None
        row.update(native_returncode=code, native_signal=unix_signal,
                   exit_code=128 + unix_signal if unix_signal else code)
    with OperationOutcome() as final_publication:
        publish(receipt, row)
    if final_publication.failure is not None:
        error = final_publication.failure.error
        row["publication_errors"].append("finished")
        observation.record_failure(error)
        _error("finished_publication", error, code, row.get("cleanup"))
    if observation.first_failure is not None:
        observer_exit = observation.first_failure.observer_exit
    if observed and code:
        return row["exit_code"]
    return observer_exit if not observed or row["publication_errors"] or "error_type" in row else 0


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if len(arguments) < 2 or arguments[1] != "--":
        raise SystemExit("Usage: pytest_native_receipt.py RECEIPT -- PYTEST_ARGS")
    return run([sys.executable, "-m", "pytest", *arguments[2:]], Path(arguments[0]))


if __name__ == "__main__":
    raise SystemExit(main())
