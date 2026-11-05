"""Independent actual-boundary control; no CaseOps app or provider imports."""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from tests import pdf_offline_boundary_20261104 as boundary  # noqa: E402

observed = []
native_entries = []


def capture(event, arguments):
    if event == "subprocess.Popen":
        observed.append(arguments)


sys.addaudithook(capture)
original_codes = (platform._syscmd_ver.__code__, platform.uname.__code__, platform.system.__code__)
if os.name == "nt":
    import _winapi

    original_create = _winapi.CreateProcess

    def must_not_create(*args, **kwargs):
        native_entries.append("CreateProcess")
        raise AssertionError("A DENIED probe reached native process creation")

    _winapi.CreateProcess = must_not_create

try:
    expected_cache = str(Path(sys.argv[2]).parent / "pycache")
    assert sys.pycache_prefix == expected_cache
    assert not any(
        getattr(module, "__cached__", None) and Path(module.__cached__).exists()
        for module in (platform, subprocess, boundary)
    )
    boundary.pytest_configure(None)
    receipt = boundary.metadata_receipt
    assert receipt["state"] == "REAL_HOST_METADATA_OBSERVED_WITHOUT_COMMAND_EXECUTION"
    assert receipt["allowed_subprocesses"] == 0
    assert boundary.attempts == []
    target = Path(os.environ["CASEOPS_PDF_OFFLINE_RECEIPT"])
    metadata_target = target.with_name(target.stem + "-metadata.json")
    assert metadata_target.is_file()  # Must exist before any subject action.
    if os.name == "nt":
        comspec = r"C:\Windows\System32\cmd.exe"
        expected = [
            (comspec, f'{comspec} /c "ver"', None, None),
            (comspec, f'{comspec} /c "command /c ver"', None, None),
            (comspec, f'{comspec} /c "cmd /c ver"', None, None),
        ]
        assert observed[:3] == expected
        control = [
            row for row in receipt["expected_denied_probes"] if row["phase"] == "fallback_control"
        ]
        assert [row["command_index"] for row in control] == [0, 1, 2]
        for arguments, command in zip(
            expected, ("ver", "command /c ver", "cmd /c ver"), strict=True
        ):
            assert boundary._metadata_argument_shape(arguments, command)
            changed = (arguments[0], arguments[1] + " & echo forbidden", None, None)
            assert not boundary._metadata_argument_shape(changed, command)
    assert native_entries == []

    # A phase flag by itself cannot turn a subject call into a platform probe.
    boundary._metadata_phase = "normal_metadata"
    boundary._metadata_thread = threading.get_ident()
    if os.name == "nt":
        boundary._metadata_codes = boundary._qualify_metadata_origin()
    try:
        subprocess.Popen("ver", shell=True)
    except boundary.OfflineBoundaryRefusal:
        pass
    else:
        raise AssertionError("Wrong-origin command was not refused")
    finally:
        boundary._metadata_phase = None
        boundary._metadata_thread = None
        boundary._metadata_codes = None

    try:
        platform._syscmd_ver(supported_platforms=(sys.platform,))
    except boundary.OfflineBoundaryRefusal:
        pass
    else:
        raise AssertionError("Subject-phase platform command was not refused")
    try:
        socket.getaddrinfo("metadata-control.invalid", 443)
    except boundary.OfflineBoundaryRefusal:
        pass
    else:
        raise AssertionError("DNS was not refused before resolver work")
    assert boundary.attempts == ["database_or_process", "database_or_process", "network"]
    assert native_entries == []
    assert original_codes == (
        platform._syscmd_ver.__code__,
        platform.uname.__code__,
        platform.system.__code__,
    )
    actual_system = platform.system()
    actual_version = platform.uname().version
    assert actual_system == receipt["system"]
    assert actual_version == receipt["version"]
    result = {
        "state": "REAL_METADATA_DENIAL_AND_SUBJECT_BOUNDARIES_PROVED",
        "windows_native_control": os.name == "nt",
        "expected_probe_denials": receipt["expected_denied_probes"],
        "native_CreateProcess_entries": len(native_entries),
        "unknown_origin_subject_command_and_DNS_denied": True,
        "platform_function_codes_unchanged": True,
        "normal_metadata_receipt_precedes_subject": True,
        "fresh_compiled_cache_prefix_verified": True,
    }
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2), encoding="utf-8")
finally:
    if os.name == "nt":
        _winapi.CreateProcess = original_create
