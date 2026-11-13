"""Run the full native inventory in fresh, serial, whole-file pytest processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

SHARDS = 8
MAX_BYTES = 256 * 1024 * 1024
MAX_LINE = 16 * 1024 * 1024
MAX_RETAIN_FILES = 100_000
MAX_RETAIN_BYTES = 16 * 1024**3
PARENT_MARKER = ".caseops-native-parent.json"


def native_path(path: Path) -> Path:
    """Use extended-path IO for evidence, never for the pytest fixture argument."""
    value = str(path.absolute())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def save(path: Path, value) -> None:
    with native_path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def fixture_inventory(root: Path) -> dict:
    files, directories, total = {}, [], 0
    pending = [(native_path(root), "")]
    while pending:
        directory, relative = pending.pop()
        metadata = directory.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError("Reparse point in native runtime evidence")
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                name = relative + entry.name
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise ValueError("Reparse point in native runtime evidence")
                if stat.S_ISDIR(info.st_mode):
                    if len(files) + len(directories) >= MAX_RETAIN_FILES:
                        raise ValueError("Native runtime evidence retention bound exceeded")
                    directories.append(name)
                    pending.append((Path(entry.path), name + "/"))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Nonregular native runtime evidence")
                total += info.st_size
                if len(files) + len(directories) >= MAX_RETAIN_FILES or total > MAX_RETAIN_BYTES:
                    raise ValueError("Native runtime evidence retention bound exceeded")
                hashed = hashlib.sha256()
                with Path(entry.path).open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        hashed.update(block)
                files[name] = {"bytes": info.st_size, "sha256": hashed.hexdigest()}
    if not files:
        raise ValueError("Empty native runtime evidence inventory")
    return {"files": files, "directories": sorted(directories)}


def drop_pytest_current_links(fixtures: Path) -> list[str]:
    """Remove pytest's ``<name>current`` convenience links from the basetemp root.

    pytest links each numbered temporary directory as ``<name>current`` when
    the process may create symbolic links (an elevated Windows shell can). Only
    a symlink whose target is an existing sibling ``<name><digits>`` directory
    is removed; the target bytes stay, and any other link or junction is still
    refused by ``fixture_inventory``.
    """
    root = native_path(fixtures)
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return []
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise ValueError("Reparse point in native runtime evidence")
    if not stat.S_ISDIR(metadata.st_mode):
        return []
    removed = []
    with os.scandir(root) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            if not entry.is_symlink() or not entry.name.endswith("current"):
                continue
            prefix = entry.name[: -len("current")]
            target = Path(os.readlink(entry.path))
            sibling = native_path(target if target.is_absolute() else root / target)
            if (
                not prefix
                or os.path.normcase(str(sibling.parent)) != os.path.normcase(str(root))
                or not re.fullmatch(re.escape(prefix) + r"\d+", sibling.name)
                or sibling.is_symlink()
                or not sibling.is_dir()
            ):
                continue
            try:
                os.unlink(entry.path)
            except (IsADirectoryError, PermissionError):
                os.rmdir(entry.path)
            removed.append(entry.name)
    return removed


def retain_runtime(source: Path, destination: Path) -> dict:
    """Retain complete binary bytes before publishing the completion manifest."""
    before = fixture_inventory(source)
    for name in before["directories"]:
        native_path(destination / name).mkdir(parents=True, exist_ok=True)
    for name, record in before["files"].items():
        original = native_path(source / name)
        retained = native_path(destination / name)
        retained.parent.mkdir(parents=True, exist_ok=True)
        hashed, size = hashlib.sha256(), 0
        with original.open("rb") as src, retained.open("xb") as dst:
            for block in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(block)
                hashed.update(block)
                size += len(block)
            dst.flush()
            os.fsync(dst.fileno())
        if {"bytes": size, "sha256": hashed.hexdigest()} != record:
            raise ValueError("Native runtime bytes changed during retention")
        with retained.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if retained.stat().st_size != size or actual != record["sha256"]:
            raise ValueError("Retained native runtime bytes differ")
    if fixture_inventory(source) != before:
        raise ValueError("Native runtime inventory changed during retention")
    receipt = {
        "complete": True,
        "source": str(source),
        "destination": str(destination),
        "directories": before["directories"],
        "files": [
            {
                "relative_path": name,
                "source_path": str(source / name),
                "destination_path": str(destination / name),
                **row,
            }
            for name, row in sorted(before["files"].items())
        ],
    }
    pending = native_path(destination / "runtime-retention.pending")
    final = native_path(destination / "runtime-retention.json")
    save(pending, receipt)
    if os.name == "nt":
        # Windows rename rejects an existing target. POSIX link is also exclusive.
        pending.rename(final)
    else:
        os.link(pending, final)
        pending.unlink()
    return receipt


def terminate_owned_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        if result.returncode:
            raise ValueError("Owned native process tree termination unconfirmed")
        process.wait(timeout=5)
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def directory_identity(path: Path) -> dict:
    metadata = native_path(path).lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_file_attributes", 0) & 0x400
        or getattr(metadata, "st_reparse_tag", 0)
    ):
        raise ValueError("Owned runtime directory identity is unsafe")
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "birthtime_ns": getattr(metadata, "st_birthtime_ns", None),
    }


def physical_directory(path: Path) -> None:
    if not path.is_absolute() or os.path.normcase(str(path.resolve())) != os.path.normcase(str(path)):
        raise ValueError("Native runtime parent must be an absolute physical path without aliases")
    for ancestor in reversed([path, *path.parents]):
        directory_identity(ancestor)


def comparison_path(path: Path) -> Path:
    value = str(path.resolve())
    if os.name == "nt" and value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif os.name == "nt" and value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def windows_system_directory() -> Path:
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.GetSystemWindowsDirectoryW
    query.argtypes = (ctypes.c_wchar_p, ctypes.c_uint)
    query.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = query(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise ValueError("Trusted native Windows directory unavailable")
    return Path(buffer.value)


def windows_acl_host(path: Path) -> tuple[Path, dict]:
    windows = windows_system_directory()
    physical_directory(windows)
    system32 = windows / "System32"
    shell = system32 / "WindowsPowerShell/v1.0/powershell.exe"
    modules = shell.parent / "Modules"
    physical_directory(shell.parent)
    physical_directory(modules)
    info = shell.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or getattr(info, "st_reparse_tag", 0)
        or os.path.normcase(str(shell.resolve())) != os.path.normcase(str(shell))
    ):
        raise ValueError("Trusted native PowerShell path unavailable")
    env = {
        "SystemRoot": str(windows), "windir": str(windows), "PATH": str(system32),
        "PSModulePath": str(modules), "CASEOPS_NATIVE_ACL_PATH": str(path),
    }
    for key in ("TEMP", "TMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    return shell, env


def private_directory_owner(path: Path) -> dict:
    """Read ownership/permissions; never repair an existing directory's ACL."""
    if os.name != "nt":
        info = path.lstat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("Native runtime directory must be current-user private (0700)")
        return {"uid": info.st_uid}
    # Python 3.13 mkdir(0700) supplies the private Windows DACL at creation.
    # Inspect SID rules, not localized account names or Windows st_uid placeholders.
    command = r"""
$ErrorActionPreference = 'Stop'
$u = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$a = Get-Acl -LiteralPath $env:CASEOPS_NATIVE_ACL_PATH
$owner = $a.GetOwner([Security.Principal.SecurityIdentifier]).Value
if ($owner -ne $u) { throw 'Runtime owner must be the current user SID' }
if (-not $a.AreAccessRulesProtected) { throw 'Runtime DACL must be protected' }
# OWNER RIGHTS is meaningful only after the exact current-user owner check.
$allowed = @($u, 'S-1-3-4', 'S-1-5-18', 'S-1-5-32-544')
$full = $false
foreach ($r in $a.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
    if ($r.IsInherited -or $r.AccessControlType -ne 'Allow' -or
        $r.IdentityReference.Value -notin $allowed) {
        throw 'Nonprivate runtime ACL'
    }
    if ($r.IdentityReference.Value -in @($u, 'S-1-3-4') -and
        ($r.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
            [Security.AccessControl.FileSystemRights]::FullControl -and
        ($r.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -eq 0) {
        $full = $true
    }
}
if (-not $full) { throw 'Current user lacks runtime ownership access' }
@{user_sid=$u; owner_sid=$owner; sddl=$a.Sddl} | ConvertTo-Json -Compress
"""
    shell, env = windows_acl_host(path)
    try:
        result = subprocess.run(
            [str(shell), "-NoProfile", "-NonInteractive", "-Command", command],
            env=env,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Native runtime private Windows ownership unconfirmed") from exc
    if result.returncode or not 0 < len(result.stdout) <= 16_384:
        raise ValueError("Native runtime private Windows ownership unconfirmed")
    owner = json.loads(result.stdout)
    if not isinstance(owner, dict) or set(owner) != {"user_sid", "owner_sid", "sddl"} or not all(
        isinstance(value, str) and value for value in owner.values()
    ) or owner["owner_sid"] != owner["user_sid"]:
        raise ValueError("Malformed Windows runtime ownership receipt")
    return owner


def read_parent_claim(parent: Path) -> tuple[dict, str]:
    physical_directory(parent)
    marker = parent / PARENT_MARKER
    before = marker.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_file_attributes", 0) & 0x400
        or getattr(before, "st_reparse_tag", 0)
        or before.st_nlink != 1
        or not 0 < before.st_size <= 4096
    ):
        raise ValueError("Unsafe native runtime parent claim")

    def identity(info):
        # Windows named st_dev can be zero. The physical parent is separately
        # bound; retain the full file ID rather than equating unlike dev views.
        device = () if os.name == "nt" else (info.st_dev,)
        return (*device, info.st_ino, info.st_mode, info.st_nlink, info.st_size)

    def stable(info):
        return (
            info.st_dev, *identity(info), info.st_mtime_ns, info.st_ctime_ns,
            getattr(info, "st_birthtime_ns", None), getattr(info, "st_file_attributes", 0),
            getattr(info, "st_reparse_tag", 0),
        )

    with marker.open("rb") as stream:
        held = os.fstat(stream.fileno())
        # Named and descriptor ctime have distinct Windows semantics. Each is
        # checked against itself; cross-view identity never substitutes for time.
        if identity(held) != identity(before):
            raise ValueError("Native runtime parent claim identity changed")
        data = stream.read(4097)
        if stable(os.fstat(stream.fileno())) != stable(held) or stable(marker.lstat()) != stable(before):
            raise ValueError("Native runtime parent claim changed")
    claim = json.loads(data)
    if (
        not isinstance(claim, dict)
        or set(claim) != {"version", "kind", "path", "identity", "owner", "nonce"}
        or type(claim["version"]) is not int
        or claim["version"] != 1
        or claim["kind"] != "caseops-native-runtime-parent"
        or claim["path"] != str(parent)
        or claim["identity"] != directory_identity(parent)
        or claim["owner"] != private_directory_owner(parent)
        or not isinstance(claim["nonce"], str)
        or re.fullmatch(r"[0-9a-f]{32}", claim["nonce"]) is None
    ):
        raise ValueError("Native runtime parent claim does not match current ownership/identity")
    return claim, hashlib.sha256(data).hexdigest()


def admit_runtime_parent(parent: Path, source: Path, evidence: Path) -> dict:
    if not parent.is_absolute() or ".." in parent.parts or str(parent).startswith("\\\\"):
        raise ValueError("Native runtime parent must be an absolute local physical path")
    physical_directory(parent.parent)
    excluded = [Path(tempfile.gettempdir()), source, evidence]
    excluded.extend(
        Path(value) for key, value in os.environ.items()
        if key.lower() in {"onedrive", "onedriveconsumer", "onedrivecommercial"} and value
    )
    if os.environ.get("USERPROFILE"):
        excluded.append(Path(os.environ["USERPROFILE"]) / "OneDrive")
    for location in excluded:
        location = comparison_path(location)
        if parent.is_relative_to(location) or location.is_relative_to(parent):
            raise ValueError("Native runtime parent overlaps global temp, OneDrive, source or evidence")
    if os.name == "nt" and len(str(parent / "copg-12345678/collection/fixtures")) > 100:
        raise ValueError("Native runtime fixture workspace is not short enough")
    try:
        parent.mkdir(mode=0o700)
    except FileExistsError:
        # Never adopt, chmod, or place a claim in an existing unclaimed directory.
        if not (parent / PARENT_MARKER).is_file():
            raise ValueError("Existing native runtime parent is unclaimed; left untouched") from None
    else:
        physical_directory(parent)
        save(parent / PARENT_MARKER, {
            "version": 1,
            "kind": "caseops-native-runtime-parent",
            "path": str(parent),
            "identity": directory_identity(parent),
            "owner": private_directory_owner(parent),
            "nonce": secrets.token_hex(16),
        })
    claim, digest = read_parent_claim(parent)
    return {"parent_claim": claim, "parent_claim_sha256": digest}


def cleanup_workspace(workspace: Path, root: Path, ownership: dict, expected: dict) -> None:
    try:
        claim, digest = read_parent_claim(root)
        physical_directory(workspace)
        workspace_owner = private_directory_owner(workspace)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Owned runtime cleanup identity or inventory changed; retained") from exc
    resolved_root, resolved_workspace = root.resolve(), workspace.resolve()
    if (
        resolved_workspace.parent != resolved_root
        or not resolved_workspace.is_relative_to(resolved_root)
        or workspace.parent != root
        or not workspace.name.startswith("copg-")
        or claim != ownership["parent_claim"]
        or digest != ownership["parent_claim_sha256"]
        or workspace_owner != ownership["workspace_owner"]
        or directory_identity(root) != ownership["temp_root_identity"]
        or directory_identity(workspace) != ownership["workspace_identity"]
        or fixture_inventory(workspace) != expected
    ):
        raise ValueError("Owned runtime cleanup identity or inventory changed; retained")
    shutil.rmtree(native_path(resolved_workspace))


def source_snapshot(root: Path) -> dict:
    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ValueError("Candidate source inventory unavailable")
        return result.stdout

    head = git("rev-parse", "HEAD").decode("ascii").strip()
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head):
        raise ValueError("Invalid candidate HEAD")
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    paths = names.decode("utf-8").split("\0")
    if not paths[-1] == "" or not paths[:-1] or len(set(paths[:-1])) != len(paths[:-1]):
        raise ValueError("Candidate source inventory is empty or duplicated")
    files = {}
    for name in sorted(paths[:-1]):
        relative = PurePosixPath(name)
        if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
            raise ValueError("Invalid candidate source path")
        path = root / name
        if not path.is_file() or path.resolve().is_relative_to(root) is False:
            raise ValueError("Candidate source is missing or outside checkout")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"head": head, "files": files}


def module_path(nodeid: str) -> str:
    if not isinstance(nodeid, str) or "::" not in nodeid:
        raise ValueError("Invalid collected test identity")
    module = nodeid.split("::", 1)[0]
    path = PurePosixPath(module)
    if (
        not module.startswith("tests/")
        or not module.endswith(".py")
        or "\\" in module
        or ":" in module
        or path.as_posix() != module
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise ValueError("Noncanonical collected test module")
    return module


def journal(path: Path, *, collect: bool = False) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Missing or oversized incremental journal")
    rows = []
    with path.open("rb") as stream:
        while line := stream.readline(MAX_LINE + 1):
            if len(line) > MAX_LINE or not line.endswith(b"\n"):
                raise ValueError("Incomplete or oversized journal row")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Malformed journal member")
            rows.append(row)
    if not rows or rows[0].get("event") != "session_started":
        raise ValueError("Missing journal start")
    if rows[-1].get("event") != "session_finished":
        raise ValueError("Missing natural journal completion")
    events = Counter(row.get("event") for row in rows)
    if events["session_started"] != 1 or events["session_finished"] != 1:
        raise ValueError("Duplicate journal session boundary")
    if events["collection"] != 1 or set(events) - {
        "session_started",
        "collection",
        "test_report",
        "session_finished",
    }:
        raise ValueError("Unexpected or missing journal events")
    identities = next(row["nodeids"] for row in rows if row["event"] == "collection")
    if not isinstance(identities, list) or not identities:
        raise ValueError("Empty collected inventory")
    for identity in identities:
        module_path(identity)
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate collected identity")
    reports = [row for row in rows if row["event"] == "test_report"]
    if rows[1].get("event") != "collection" or type(rows[-1].get("exitstatus")) is not int:
        raise ValueError("Malformed collection order or completion status")
    if collect and (reports or rows[-1]["exitstatus"] != 0):
        raise ValueError("Canonical collection failed or executed tests")
    return {"nodeids": identities, "reports": reports, "exit": rows[-1]["exitstatus"]}


def plan(identities: list[str], api: Path) -> list[dict]:
    modules = defaultdict(list)
    for identity in identities:
        module = module_path(identity)
        path = api / module
        if not path.is_file() or not path.resolve().is_relative_to(api):
            raise ValueError("Collected PostgreSQL file is missing or outside API root")
        modules[module].append(identity)
    if len(modules) < SHARDS:
        raise ValueError("Cannot populate eight nonempty whole-file groups")
    assignments, loads = [[] for _ in range(SHARDS)], [0] * SHARDS
    # Same deterministic largest-processing-time pattern as pytest_shard_plan.py,
    # weighted by actual collected native cases rather than guessed static test names.
    for module in sorted(modules, key=lambda name: (-len(modules[name]), name)):
        target = min(range(SHARDS), key=lambda index: (loads[index], index))
        assignments[target].append(module)
        loads[target] += len(modules[module])
    groups = []
    for index, assigned in enumerate(assignments, 1):
        selected = [identity for identity in identities if module_path(identity) in assigned]
        files = list(dict.fromkeys(module_path(identity) for identity in selected))
        groups.append({"shard": index, "files": files, "nodeids": selected})
    return groups


def execute(api: Path, folder: Path, arguments: list[str], *, runtime_parent: Path) -> int:
    parent_claim = admit_runtime_parent(runtime_parent, api.parent.parent, folder)
    temp_root = runtime_parent
    root_identity = directory_identity(temp_root)
    workspace = Path(tempfile.mkdtemp(prefix="copg-", dir=temp_root))
    runtime = workspace / folder.name
    ownership = {
        **parent_claim,
        "runtime_parent": str(temp_root),
        "temp_root": str(temp_root),
        "temp_root_identity": root_identity,
        "workspace_identity": directory_identity(workspace),
        "workspace_owner": private_directory_owner(workspace),
    }
    physical_directory(workspace)
    marker = workspace / ".caseops-runtime-owner.json"
    save(marker, {"workspace": str(workspace), "evidence_destination": str(folder), **ownership})
    marker_bytes = marker.read_bytes()
    save(
        folder / "runtime-workspace.json",
        {
            "workspace": str(workspace),
            "runtime": str(runtime),
            "evidence_destination": str(folder),
            "incremental_journal": str(runtime / "results.jsonl"),
            "owner_marker_sha256": hashlib.sha256(marker_bytes).hexdigest(),
            **ownership,
        },
    )
    if os.name == "nt" and len(str(runtime / "fixtures")) > 100:
        raise ValueError("Native runtime fixture workspace is not short enough")
    runtime.mkdir()
    forwarded = []
    for argument in arguments:
        if argument.startswith("--junitxml="):
            if native_path(Path(argument.split("=", 1)[1])) != native_path(folder / "results.xml"):
                raise ValueError("Unexpected native JUnit destination")
            argument = "--junitxml=" + str(runtime / "results.xml")
        forwarded.append(argument)
    env = dict(os.environ, CASEOPS_TEST_RESULT_JOURNAL=str(runtime / "results.jsonl"))
    env.pop("CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID", None)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "postgres",
        "--basetemp=" + str(runtime / "fixtures"),
        *forwarded,
    ]
    save(
        runtime / "started.json",
        {"command": command, "started_at": datetime.now(UTC).isoformat()},
    )
    with (
        (runtime / "stdout.txt").open("xb") as stdout,
        (runtime / "stderr.txt").open("xb") as stderr,
    ):
        process = subprocess.Popen(command, cwd=api, env=env, stdout=stdout, stderr=stderr)
        try:
            code = process.wait()
        except BaseException:
            if process.poll() is None:
                terminate_owned_process(process)
            save(
                runtime / "interrupted.json",
                {"natural_completion": False, "reaped": True},
            )
            # Close logs before retaining every partial fixture and phase journal.
            stdout.close()
            stderr.close()
            drop_pytest_current_links(runtime / "fixtures")
            retain_runtime(runtime, folder)
            raise
    save(
        runtime / "process-completion.json",
        {
            "exit_code": code,
            "completed_at": datetime.now(UTC).isoformat(),
            "natural_completion": True,
            "pid": process.pid,
            "reaped": True,
        },
    )
    try:
        drop_pytest_current_links(runtime / "fixtures")
        retained = retain_runtime(runtime, folder)
    except (OSError, ValueError):
        save(
            folder / "retention-incomplete.json",
            {"complete": False, "runtime": str(runtime), "preserved": True},
        )
        raise
    if code == 0:
        # Only the uniquely created runtime is removed, after all bytes verify.
        expected = {
            "files": {
                marker.name: {
                    "bytes": len(marker_bytes),
                    "sha256": hashlib.sha256(marker_bytes).hexdigest(),
                },
                **{
                    runtime.name + "/" + row["relative_path"]: {
                        "bytes": row["bytes"],
                        "sha256": row["sha256"],
                    }
                    for row in retained["files"]
                },
            },
            "directories": sorted(
                [runtime.name, *[runtime.name + "/" + name for name in retained["directories"]]]
            ),
        }
        cleanup_workspace(workspace, temp_root, ownership, expected)
        save(folder / "runtime-cleanup.json", {"workspace": str(workspace), "removed": True})
    return code


def reconcile(folder: Path, expected: list[str], code: int) -> tuple[dict, ET.Element]:
    result = journal(folder / "results.jsonl")
    if result["nodeids"] != expected:
        raise ValueError("Child ordered collection differs from canonical subset")
    if code not in (0, 1) or type(result["exit"]) is not int or result["exit"] != code:
        raise ValueError("Child process and journal completion disagree or are incomplete")
    phases = defaultdict(list)
    for report in result["reports"]:
        if report.get("nodeid") not in expected or report.get("outcome") not in {
            "passed",
            "failed",
        }:
            raise ValueError("Unexpected, skipped or malformed phase result")
        if (
            not isinstance(report.get("longrepr"), str)
            or not isinstance(report.get("sections"), list)
            or type(report.get("duration")) not in (int, float)
            or not 0 <= report["duration"] < float("inf")
        ):
            raise ValueError("Malformed phase details")
        phases[report["nodeid"]].append(report)
    if list(phases) != expected:
        raise ValueError("Missing, duplicated or reordered executed identities")
    statuses = {}
    for identity in expected:
        rows = phases[identity]
        setup_failed = rows[0].get("when") == "setup" and rows[0]["outcome"] == "failed"
        required = ["setup", "teardown"] if setup_failed else ["setup", "call", "teardown"]
        if [row.get("when") for row in rows] != required:
            raise ValueError("Wrong, duplicate or incomplete test phases")
        statuses[identity] = (
            "error"
            if any(row["outcome"] == "failed" and row["when"] != "call" for row in rows)
            else "failure"
            if any(row["outcome"] == "failed" for row in rows)
            else "passed"
        )
    if (code == 0) != all(value == "passed" for value in statuses.values()):
        raise ValueError("Native exit disagrees with structured outcomes")
    xml = folder / "results.xml"
    if not xml.is_file() or xml.stat().st_size > MAX_BYTES:
        raise ValueError("Missing or oversized child JUnit")
    content = xml.read_bytes()
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        raise ValueError("Unexpected JUnit declarations")
    root = ET.fromstring(content)
    if root.tag != "testsuites" or len(root) != 1 or root[0].tag != "testsuite":
        raise ValueError("Unexpected JUnit structure")
    suite = root[0]
    if any(
        child.tag not in {"testcase", "properties", "system-out", "system-err"} for child in suite
    ):
        raise ValueError("Unexpected JUnit suite member")
    cases = list(suite.findall("testcase"))
    if len(cases) != len(expected):
        raise ValueError("Empty, duplicate or incomplete JUnit cases")
    for case, identity in zip(cases, expected, strict=True):
        head, bracket, parameters = identity.partition("[")
        module, *parts = head.split("::")
        classname = ".".join([module[:-3].replace("/", "."), *parts[:-1]])
        name = parts[-1] + bracket + parameters
        if (case.get("classname"), case.get("name")) != (classname, name):
            raise ValueError("Unexpected or reordered JUnit identity")
        problems = [child.tag for child in case if child.tag in {"skipped", "failure", "error"}]
        if any(
            child.tag
            not in {
                "skipped",
                "failure",
                "error",
                "properties",
                "system-out",
                "system-err",
            }
            for child in case
        ):
            raise ValueError("Unexpected JUnit case member")
        required = [] if statuses[identity] == "passed" else [statuses[identity]]
        if problems != required:
            raise ValueError("JUnit and structured outcome disagree")
    counts = Counter(statuses.values())
    for name, count in {
        "tests": len(expected),
        "failures": counts["failure"],
        "errors": counts["error"],
        "skipped": 0,
    }.items():
        if suite.get(name) != str(count):
            raise ValueError("JUnit declared totals differ from actual cases")
    return result, suite


def run(api: Path, output: Path, *, runtime_parent: Path) -> int:
    api, output = api.resolve(), native_path(output.resolve())
    root = api.parent.parent
    if os.environ.get("PYTEST_ADDOPTS", "").strip():
        raise ValueError("Native acceptance cannot inherit pytest selection or retry options")
    targets = [
        output / name
        for name in (
            "postgres-results.jsonl",
            "postgres.xml",
            "postgres-driver-completion.json",
        )
    ]
    if any(path.exists() for path in targets):
        raise ValueError("Refusing to overwrite native acceptance evidence")
    admit_runtime_parent(runtime_parent, root, output)
    work = output / "postgres-processes"
    work.mkdir(parents=True, exist_ok=False)
    baseline = source_snapshot(root)
    save(work / "source-before.json", baseline)

    def unchanged():
        if source_snapshot(root) != baseline:
            raise ValueError("Candidate source changed during native acceptance")

    collection = work / "collection"
    collection.mkdir()
    unchanged()
    code = execute(api, collection, ["--collect-only"], runtime_parent=runtime_parent)
    unchanged()
    if code:
        raise ValueError("Canonical PostgreSQL collection did not complete successfully")
    identities = journal(collection / "results.jsonl", collect=True)["nodeids"]
    groups = plan(identities, api)
    save(work / "inventory.json", {"canonical": identities, "groups": groups})
    results, suites, faults = {}, [], []
    for group in groups:
        unchanged()
        folder = work / f"child-{group['shard']:02}"
        folder.mkdir()
        save(folder / "inventory.json", group)
        code = execute(
            api, folder, ["--junitxml=" + str(folder / "results.xml"), *group["files"]],
            runtime_parent=runtime_parent,
        )
        unchanged()
        try:
            result, suite = reconcile(folder, group["nodeids"], code)
            results[group["shard"]] = result
            suites.append(suite)
            if code:
                faults.append({"shard": group["shard"], "kind": "complete_test_failure"})
        except (
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            ET.ParseError,
        ) as exc:
            faults.append(
                {
                    "shard": group["shard"],
                    "kind": "incomplete_evidence",
                    "reason": str(exc),
                }
            )
        save(
            folder / "reconciliation.json",
            {"faults": [row for row in faults if row["shard"] == group["shard"]]},
        )
        print(
            f"[native-acceptance] child {group['shard']}/{SHARDS} exit={code}",
            flush=True,
        )
    unchanged()
    save(work / "source-after.json", baseline)
    save(work / "faults.json", faults)
    if len(results) != SHARDS:
        raise ValueError("Native evidence incomplete; all available child evidence retained")
    seen = [identity for group in groups for identity in results[group["shard"]]["nodeids"]]
    if Counter(seen) != Counter(identities):
        raise ValueError("Native child union does not equal canonical collection exactly once")
    reports = defaultdict(list)
    for result in results.values():
        for report in result["reports"]:
            reports[report["nodeid"]].append(report)
    exit_code = 1 if faults else 0
    combined = work / "combined-results.pending"
    with combined.open("x", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "event": "session_started",
                    "pid": os.getpid(),
                    "driver": "whole-file-fresh-processes",
                }
            )
            + "\n"
        )
        stream.write(json.dumps({"event": "collection", "nodeids": identities}) + "\n")
        for identity in identities:
            for report in reports[identity]:
                stream.write(json.dumps(report) + "\n")
        stream.write(json.dumps({"event": "session_finished", "exitstatus": exit_code}) + "\n")
    xml = work / "combined-junit.pending"
    xml_root = ET.Element("testsuites")
    xml_root.extend(suites)
    with xml.open("xb") as stream:
        ET.ElementTree(xml_root).write(stream, encoding="utf-8", xml_declaration=True)
    completion = work / "driver-completion.pending"
    save(
        completion,
        {
            "event": "execution_finished",
            "exit_code": exit_code,
            "shards": SHARDS,
            "collected": len(identities),
            "phase_count": sum(map(len, reports.values())),
            "skipped": 0,
            "retries": 0,
            "source_unchanged": True,
            "faults": faults,
            "completed_at": datetime.now(UTC).isoformat(),
            "journal_sha256": hashlib.sha256(combined.read_bytes()).hexdigest(),
            "junit_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
        },
    )
    for source, destination in zip((combined, xml, completion), targets, strict=True):
        # Exclusive creation never replaces old evidence, including a concurrent producer.
        with destination.open("xb") as stream:
            stream.write(source.read_bytes())
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--results-directory", type=Path, required=True)
    parser.add_argument("--runtime-parent", type=Path, required=True)
    args = parser.parse_args()
    if args.api_dir.resolve() != Path(__file__).resolve().parent.parent / "apps/api":
        parser.error("Native driver must use its own candidate API checkout")
    try:
        return run(args.api_dir, args.results_directory, runtime_parent=args.runtime_parent)
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as exc:
        print(f"[native-acceptance] NO-GO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
