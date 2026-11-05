"""Owned no-I/O boundary for the focused Unicode PDF negative/positive gate."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import CodeType

attempts = []
constructor_control_denied = False
metadata_receipt = None
metadata_denials = []
_metadata_phase = None
_metadata_thread = None
_metadata_codes = None
_METADATA_COMMANDS = ("ver", "command /c ver", "cmd /c ver")
_METADATA_SOURCE_PINS = {
    "platform.py": (47345, "75fe9b94662e55b91e19602bb75e6ca6132f7a53fb22844fc44a507a639127e1"),
    "subprocess.py": (90827, "e4049ed91ed101b09b0dc96bbf234f646c1728090d643a474b024276cc2a028c"),
}


class OfflineBoundaryRefusal(RuntimeError):
    pass


class MetadataProbeDenied(PermissionError):
    """Real platform.py handles a denied shell probe through its OSError path."""


def _qualified_stdlib_codes(function, source_name):
    path = Path(function.__code__.co_filename)
    expected_path = Path(sys.base_prefix) / "Lib" / source_name
    if path.resolve() != expected_path.resolve():
        raise OfflineBoundaryRefusal("PDF_METADATA_STDLIB_PATH_REFUSED")
    named = path.lstat()
    with path.open("rb") as stream:
        first = os.fstat(stream.fileno())
        body = stream.read(_METADATA_SOURCE_PINS[source_name][0] + 1)
        last = os.fstat(stream.fileno())
    final = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")

    def version(value):
        return tuple(getattr(value, field) for field in fields)

    if (
        not stat.S_ISREG(named.st_mode)
        or version(named) != version(final)
        or version(first) != version(last)
        or (named.st_dev, named.st_ino, named.st_size, named.st_mtime_ns)
        != (first.st_dev, first.st_ino, len(body), first.st_mtime_ns)
        or (len(body), hashlib.sha256(body).hexdigest()) != _METADATA_SOURCE_PINS[source_name]
    ):
        raise OfflineBoundaryRefusal("PDF_METADATA_STDLIB_BYTES_REFUSED")
    compiled = compile(body, function.__code__.co_filename, "exec", dont_inherit=True)
    pending = [compiled]
    codes = []
    while pending:
        code = pending.pop()
        codes.append(code)
        pending.extend(value for value in code.co_consts if isinstance(value, CodeType))
    return codes


def _qualify_metadata_origin():
    if sys.version_info[:3] != (3, 13, 14):
        raise OfflineBoundaryRefusal("PDF_METADATA_ACCEPTED_PYTHON_REQUIRED")
    platform_codes = _qualified_stdlib_codes(platform._syscmd_ver, "platform.py")
    process_codes = _qualified_stdlib_codes(subprocess.Popen._execute_child, "subprocess.py")
    actual = (
        platform._syscmd_ver.__code__,
        subprocess.check_output.__code__,
        subprocess.run.__code__,
        subprocess.Popen.__init__.__code__,
        subprocess.Popen._execute_child.__code__,
    )
    for code in actual:
        qualified = platform_codes if code is actual[0] else process_codes
        # marshal's interned-reference encoding is not a semantic code identity.
        # Compare actual code structures and their separately qualified origin.
        if not any(
            candidate == code and candidate.co_filename == code.co_filename
            for candidate in qualified
        ):
            raise OfflineBoundaryRefusal("PDF_METADATA_STDLIB_CODE_REFUSED")
    return actual


def _metadata_argument_shape(arguments, command):
    if command not in _METADATA_COMMANDS or len(arguments) != 4:
        return False
    comspec = os.environ.get("COMSPEC", "")
    if comspec.casefold() != r"c:\windows\system32\cmd.exe":
        return False
    executable, native_args, cwd, environment = arguments
    return (
        executable == comspec
        and native_args == f'{comspec} /c "{command}"'
        and cwd is None
        and environment is None
    )


def _known_metadata_probe(arguments):
    if (
        _metadata_phase not in ("fallback_control", "normal_metadata")
        or _metadata_thread != threading.get_ident()
        or _metadata_codes is None
    ):
        return None
    frame = sys._getframe(1)
    found = []
    command = None
    bootstrap_seen = False
    for _ in range(48):
        if frame is None:
            break
        if any(frame.f_code is code for code in _metadata_codes):
            found.append(frame.f_code)
            if frame.f_code is _metadata_codes[0]:
                command = frame.f_locals.get("cmd")
        if frame.f_code is _observe_platform_metadata.__code__:
            bootstrap_seen = True
        frame = frame.f_back
    if (
        not bootstrap_seen
        or found != list(reversed(_metadata_codes))
        or not _metadata_argument_shape(arguments, command)
    ):
        return None
    prior = [row for row in metadata_denials if row["phase"] == _metadata_phase]
    index = _METADATA_COMMANDS.index(command)
    if index != len(prior):
        return None
    return index


def audit(event, arguments):
    if event == "subprocess.Popen":
        index = _known_metadata_probe(arguments)
        if index is not None:
            metadata_denials.append({"phase": _metadata_phase, "command_index": index})
            # No command is admitted. platform.py catches this OSError and uses
            # its normal sys.getwindowsversion fallback after all three probes.
            raise MetadataProbeDenied("PDF_METADATA_SUBPROCESS_DENIED")
    if (event.startswith("socket.") and event != "socket.gethostname") or event in (
        "sqlite3.connect",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
    ):
        attempts.append("network" if event.startswith("socket.") else "database_or_process")
        raise OfflineBoundaryRefusal("PDF_OFFLINE_BOUNDARY_REFUSED")


def _observe_platform_metadata():
    global _metadata_phase, _metadata_thread, _metadata_codes
    if metadata_receipt is not None or _metadata_phase is not None:
        raise OfflineBoundaryRefusal("PDF_METADATA_ALREADY_OBSERVED")
    started = time.monotonic()
    _metadata_thread = threading.get_ident()
    try:
        if os.name == "nt":
            _metadata_codes = _qualify_metadata_origin()
            _metadata_phase = "fallback_control"
            fallback = platform._syscmd_ver()
            control = [row["command_index"] for row in metadata_denials]
            if fallback != ("", "", "") or control != [0, 1, 2]:
                raise OfflineBoundaryRefusal("PDF_METADATA_REAL_DENIAL_CONTROL_REFUSED")
        _metadata_phase = "normal_metadata"
        system = platform.system()
        observed = platform.uname()
        normal = [
            row["command_index"] for row in metadata_denials if row["phase"] == "normal_metadata"
        ]
        if normal not in ([], [0, 1, 2]) or system != observed.system or not system:
            raise OfflineBoundaryRefusal("PDF_METADATA_NORMAL_OBSERVATION_REFUSED")
        if os.name == "nt" and normal:
            native = sys.getwindowsversion()
            version = ".".join(str(value) for value in (native.platform_version or native[:3]))
            if observed.version != version:
                raise OfflineBoundaryRefusal("PDF_METADATA_NATIVE_FALLBACK_REFUSED")
        return {
            "state": "REAL_HOST_METADATA_OBSERVED_WITHOUT_COMMAND_EXECUTION",
            "system": system,
            "machine": observed.machine,
            "version": observed.version,
            "expected_denied_probes": list(metadata_denials),
            "allowed_subprocesses": 0,
            "normal_api_observation": True,
            "platform_cache_writes_by_fixture": 0,
            "node_or_environment_values_retained": False,
            "elapsed_seconds": time.monotonic() - started,
        }
    finally:
        _metadata_phase = None
        _metadata_thread = None
        _metadata_codes = None


def _publish(path, value):
    raw = (json.dumps(value, indent=2) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
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


def pytest_configure(config):
    global constructor_control_denied, metadata_receipt
    sys.addaudithook(audit)
    try:
        socket.socket()
    except OfflineBoundaryRefusal:
        constructor_control_denied = True
    if not constructor_control_denied or attempts != ["network"]:
        raise RuntimeError("PDF_OFFLINE_CONSTRUCTOR_CONTROL_FAILED")
    attempts.clear()
    target = Path(os.environ["CASEOPS_PDF_OFFLINE_RECEIPT"])
    metadata_target = target.with_name(target.stem + "-metadata.json")
    try:
        metadata_receipt = _observe_platform_metadata()
    except BaseException as error:
        _publish(
            metadata_target,
            {
                "state": "HOST_METADATA_FAILED_BEFORE_COLLECTION",
                "kind": type(error).__name__,
                "expected_denied_probes": metadata_denials,
                "subject_forbidden_attempts": attempts,
            },
        )
        raise
    _publish(metadata_target, metadata_receipt)


def pytest_sessionfinish(session, exitstatus):
    target = Path(os.environ["CASEOPS_PDF_OFFLINE_RECEIPT"])
    row = {
        "state": "PDF_OFFLINE_CHILD_BOUNDARY_OBSERVED",
        "constructor_control_denied": constructor_control_denied,
        "subject_forbidden_attempts": attempts,
        "host_metadata": metadata_receipt,
        "python": sys.version,
        "executable": sys.executable,
        "prefix": sys.prefix,
        "dont_write_bytecode": sys.dont_write_bytecode,
        "pytest_exitstatus": int(exitstatus),
        "no_site_flag": sys.flags.no_site,
    }
    _publish(target, row)
