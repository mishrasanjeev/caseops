"""Run pytest with native child-exit evidence; never retry or change its arguments."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
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


class PublicationError(Exception):
    def __init__(self, errors, published):
        super().__init__("native_receipt_publication_failed")
        self.primary, self.published = errors[0][1], published
        self.failures = [{"stage": stage, "error_type": type(error).__name__}
                         for stage, error in errors]


def _publish(path, value, *, initial=False):
    temporary, stream, published, errors = None, None, False, []
    stage = "open"
    try:
        stream = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                              prefix=path.name + ".", delete=False)
        temporary = Path(stream.name)
        stage = "serialize"
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write("\n")
        stage = "flush"
        stream.flush()
        stage = "file_fsync"
        os.fsync(stream.fileno())
    except BaseException as error:
        errors.append((stage, error))
    finally:
        if stream is not None:
            try:
                stream.close()
            except BaseException as error:
                errors.append(("file_close", error))
    if not errors:
        try:
            (os.link if initial else os.replace)(temporary, path)
            published = True
        except BaseException as error:
            errors.append(("link" if initial else "replace", error))
    if temporary is not None:
        try:
            temporary.unlink(missing_ok=True)
        except BaseException as error:
            errors.append(("temporary_unlink", error))
    if published and os.name == "posix":
        descriptor, stage = None, "directory_open"
        try:
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            stage = "directory_fsync"
            os.fsync(descriptor)
        except BaseException as error:
            errors.append((stage, error))
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as error:
                    errors.append(("directory_close", error))
    if errors:
        raise PublicationError(errors, published) from errors[0][1]


def _error(stage, error, native_returncode=None, cleanup=None):
    # Only fixed classifications and native status: no exception text or environment values.
    try:
        publication = ({"published": error.published, "failures": error.failures}
                       if isinstance(error, PublicationError) else None)
        print(json.dumps({"native_receipt_error": stage, "error_type": type(error).__name__,
                          "native_returncode": native_returncode, "cleanup": cleanup,
                          "publication": publication, "observed_at": _utc()}),
              file=sys.stderr, flush=True)
    except BaseException:
        pass


def _cleanup(child):
    """Stop/reap only this invocation's original handle under one four-second budget."""
    deadline = time.monotonic() + 4
    result = {"budget_seconds": 4, "reaped": False, "returncode_after_cleanup": None,
              "reaped_after_attempt": None, "errors": [], "started_at": _utc()}
    for action in ("terminate", "kill"):
        try:
            getattr(child, action)()
        except BaseException as error:
            result["errors"].append({"stage": action, "error_type": type(error).__name__})
        try:
            code = child.wait(timeout=min(2, max(0, deadline - time.monotonic())))
            if type(code) is not int:
                raise RuntimeError("cleanup_native_status_missing")
        except BaseException as error:
            result["errors"].append({"stage": action + "_wait",
                                     "error_type": type(error).__name__})
        else:
            result.update(reaped=True, returncode_after_cleanup=code, reaped_after_attempt=action)
            break
    result["finished_at"] = _utc()
    return result


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
    try:
        child = popen(command)  # Inherit exact environment and raw standard streams.
    except Exception as error:
        row.update(stage="constructor_failed", error_type=type(error).__name__, finished_at=_utc())
        _error("constructor", error)
        try:
            publish(receipt, row)
        except Exception as publication:
            _error("constructor_publication", publication)
        return 1
    observed, code, observer_exit = False, None, 1
    phase = "started_publication"
    try:
        row.update(stage="started", child_pid=child.pid, started_at=_utc())
        try:
            publish(receipt, row)
        except Exception as error:
            if isinstance(error, PublicationError) and not isinstance(error.primary, Exception):
                raise
            row["publication_errors"].append("started")
            _error("started_publication", error)
        phase = "wait"
        code = child.wait()  # Existing twelve-minute CI job cap remains the outer bound.
        observed = True
    except BaseException as error:
        cleanup = _cleanup(child) if not observed else None
        primary = error.primary if isinstance(error, PublicationError) else error
        observer_exit = 130 if isinstance(primary, KeyboardInterrupt) else 1
        row.update(stage="wait_failed" if phase == "wait" else "observer_failed",
                   child_pid=child.pid, error_type=type(primary).__name__, finished_at=_utc(),
                   native_exit_observed_before_failure=observed, cleanup=cleanup)
        _error(phase, error, code if observed else None, cleanup)
    if observed:
        unix_signal = -code if code < 0 and os.name == "posix" else None
        row.update(native_returncode=code, native_signal=unix_signal,
                   exit_code=128 + unix_signal if unix_signal else code, finished_at=_utc())
        if "error_type" not in row:
            row["stage"] = "exited"
    try:
        publish(receipt, row)
    except BaseException as error:
        row["publication_errors"].append("finished")
        primary = error.primary if isinstance(error, PublicationError) else error
        observer_exit = 130 if isinstance(primary, KeyboardInterrupt) else 1
        _error("finished_publication", error, code, row.get("cleanup"))
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
