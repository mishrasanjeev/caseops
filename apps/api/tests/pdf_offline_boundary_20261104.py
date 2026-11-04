"""Owned no-I/O boundary for the focused Unicode PDF negative/positive gate."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

attempts = []
constructor_control_denied = False


class OfflineBoundaryRefusal(RuntimeError):
    pass


def audit(event, _arguments):
    if (event.startswith("socket.") and event != "socket.gethostname") or event in (
        "sqlite3.connect",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
    ):
        attempts.append("network" if event.startswith("socket.") else "database_or_process")
        raise OfflineBoundaryRefusal("PDF_OFFLINE_BOUNDARY_REFUSED")


def pytest_configure(config):
    global constructor_control_denied
    sys.addaudithook(audit)
    try:
        socket.socket()
    except OfflineBoundaryRefusal:
        constructor_control_denied = True
    if not constructor_control_denied or attempts != ["network"]:
        raise RuntimeError("PDF_OFFLINE_CONSTRUCTOR_CONTROL_FAILED")
    attempts.clear()


def pytest_sessionfinish(session, exitstatus):
    target = Path(os.environ["CASEOPS_PDF_OFFLINE_RECEIPT"])
    row = {
        "state": "PDF_OFFLINE_CHILD_BOUNDARY_OBSERVED",
        "constructor_control_denied": constructor_control_denied,
        "subject_forbidden_attempts": attempts,
        "python": sys.version,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "dont_write_bytecode": sys.dont_write_bytecode,
        "pytest_exitstatus": int(exitstatus),
        "no_site_flag": sys.flags.no_site,
    }
    raw = (json.dumps(row, indent=2) + "\n").encode()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise RuntimeError("PDF_OFFLINE_RECEIPT_SHORT_WRITE")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
