"""Offline fake-process contracts for complete whole-file native acceptance."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/run_postgres_acceptance.py"
SPEC = importlib.util.spec_from_file_location("native_acceptance_driver", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)

# This standalone child only writes fake pytest artifacts. It imports no CaseOps,
# SDK, DB or network package and receives explicit argument arrays, never a shell.
FAKE = r"""
import json
import os
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

args = sys.argv[1:]
config = json.loads(Path(os.environ["FAKE_PLAN"]).read_text())
journal = Path(os.environ["CASEOPS_TEST_RESULT_JOURNAL"])
folder = journal.parent
with (folder / "received.json").open("x") as stream:
    json.dump({"args": args, "owner_removed":
               "CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID" not in os.environ}, stream)
collect = "--collect-only" in args
fault = config["fault"] if folder.name == "child-01" else None
if collect and config["fault"] in ("empty_collection", "duplicate_collection", "missing_file"):
    fault = config["fault"]
selected = config["identities"]
if collect:
    if fault == "empty_collection": selected = []
    if fault == "duplicate_collection": selected += [selected[0]]
    if fault == "missing_file": selected[0] = "tests/test_missing.py::test_a"
else:
    files = [arg for arg in args if arg.startswith("tests/")]
    selected = [identity for identity in selected if identity.split("::", 1)[0] in files]
    if fault == "reordered": selected = list(reversed(selected))
rows = [{"event": "session_started", "pid": os.getpid()},
        {"event": "collection", "nodeids": selected}]
counts = {"failures": 0, "errors": 0, "skipped": 0}
suite = ET.Element("testsuite", tests=str(len(selected)), failures="0", errors="0", skipped="0")
code = 0
if not collect:
    for index, identity in enumerate(selected):
        head, bracket, params = identity.partition("[")
        module, *parts = head.split("::")
        case = ET.SubElement(suite, "testcase", classname=".".join(
            [module[:-3].replace("/", "."), *parts[:-1]]), name=parts[-1] + bracket + params)
        failed = index == 0 and fault == "failed"
        setup_failed = index == 0 and fault == "setup_failed"
        if failed or setup_failed:
            tag = "error" if setup_failed else "failure"
            counts["errors" if setup_failed else "failures"] += 1
            ET.SubElement(case, tag, message="deterministic fake failure").text = (
                "Full fake failure details retained")
            code = 1
        for phase in (["setup", "teardown"] if setup_failed else ["setup", "call", "teardown"]):
            if index == 0 and fault == "missing_phase" and phase == "call": continue
            bad_phase = failed and phase == "call" or setup_failed and phase == "setup"
            outcome = "failed" if bad_phase else "passed"
            if index == 0 and fault == "skipped" and phase == "call":
                outcome = "skipped"
                counts["skipped"] += 1
                ET.SubElement(case, "skipped")
            row = {"event": "test_report", "nodeid": identity, "when": phase,
                   "outcome": outcome, "duration": 0.001,
                   "longrepr": "Full fake failure details retained" if outcome == "failed" else "",
                   "sections": []}
            rows.append(row)
            if index == 0 and fault == "duplicate_phase" and phase == "call": rows.append(row)
    for key, value in counts.items(): suite.set(key, str(value))
    if fault == "empty_xml":
        for case in list(suite): suite.remove(case)
        suite.set("tests", "0")
    if fault == "wrong_xml": suite[0].set("name", "unselected-test")
    if fault == "xml_totals": suite.set("tests", str(len(selected) + 1))
    if fault == "xml_outcome": ET.SubElement(suite[0], "failure")
    if fault == "duplicate_xml": suite.append(ET.fromstring(ET.tostring(suite[0])))
    if fault == "unknown_xml": ET.SubElement(suite[0], "unexpected")
    root = ET.Element("testsuites")
    root.append(suite)
    xml = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--junitxml=")))
    if fault != "missing_xml":
        with xml.open("xb") as stream: ET.ElementTree(root).write(stream, encoding="utf-8")
if fault not in ("interrupted", "missing_finish"):
    rows.append({"event": "session_finished", "exitstatus": code})
if fault == "interrupted": code = 2
if fault == "wrong_exit": code = 1
if fault == "malformed_member": rows.insert(2, [])
if fault == "duplicate_session": rows.insert(0, rows[0])
with journal.open("x") as stream:
    for row in rows:
        stream.write(json.dumps(row) + "\n")
        stream.flush()
if fault == "source_drift" and not collect:
    Path(config["source_path"]).write_text("Changed fake source after child invocation")
if config.get("make_fixture"):
    base = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--basetemp=")))
    target = (base / "test_an_ip_docket_event_locks_0" / "documents" /
              "00000000-0000-4000-8000-000000000001" / "ip-documents" /
              "00000000-0000-4000-8000-000000000002" / "original-document.bin")
    target.parent.mkdir(parents=True)
    target.write_bytes(bytes(range(256)) + b"\r\n\x00\xff")
sys.exit(code)
"""


@pytest.fixture
def runtime_parent():
    base = Path(os.environ["LOCALAPPDATA"]) if os.name == "nt" else Path.home()
    container = Path(tempfile.mkdtemp(prefix="copg-u-", dir=base)).resolve()
    original = driver.directory_identity(container)
    marker = container / ".unit-owner"
    token = os.urandom(32)
    with marker.open("xb") as stream:
        stream.write(token)
    yield container / "r"
    assert driver.directory_identity(container) == original and marker.read_bytes() == token
    # Refuse reparse entries before disposing this unit sandbox.
    driver.fixture_inventory(container)
    shutil.rmtree(container)


@pytest.fixture
def fake_native(tmp_path, monkeypatch, runtime_parent):
    root = tmp_path / "candidate with spaces"
    api = root / "apps/api"
    tests = api / "tests"
    tests.mkdir(parents=True)
    identities = []
    for index in range(12):
        module = f"tests/test_native_{index:02}.py"
        (api / module).write_text("# deterministic fake native module\n", encoding="utf-8")
        identities.extend(
            f"{module}::TestNative::test_ok[value::{value}]" for value in range(1 + index % 3)
        )
    config = tmp_path / "fake-plan.json"
    program = tmp_path / "fake_pytest.py"
    program.write_text(FAKE, encoding="utf-8")
    calls = []
    real_popen = subprocess.Popen

    def snapshot(candidate):
        assert candidate == root
        return {
            "head": "1" * 40,
            "files": {
                path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(tests.glob("*.py"))
            },
        }

    def popen(command, **kwargs):
        assert command[:6] == [sys.executable, "-m", "pytest", "-q", "-m", "postgres"]
        assert isinstance(command, list) and "shell" not in kwargs
        assert kwargs["cwd"] == api
        assert "CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID" not in kwargs["env"]
        for key in (
            "CASEOPS_TEST_POSTGRES_URL",
            "CASEOPS_DATABASE_URL",
            "CASEOPS_E2E_DATABASE_URL",
        ):
            assert kwargs["env"][key] == (
                "fake-browser-db" if key == "CASEOPS_E2E_DATABASE_URL" else "fake-owned-native-db"
            )
        for key in (
            "TEMP", "TMP", "HOME", "LOCALAPPDATA", "PATH", "XDG_CACHE_HOME",
            "CASEOPS_TEMPORAL_TEST_SERVER_PATH", "CASEOPS_TEMPORAL_TEST_SERVER_SHA256",
        ):
            assert kwargs["env"].get(key) == os.environ.get(key)
        calls.append(command)
        return real_popen([sys.executable, str(program), *command[1:]], **kwargs)

    monkeypatch.setattr(driver, "source_snapshot", snapshot)
    monkeypatch.setattr(driver, "private_directory_owner", lambda path: {"fake_owner": "unit"})
    monkeypatch.setattr(driver.subprocess, "Popen", popen)
    monkeypatch.setenv("FAKE_PLAN", str(config))
    monkeypatch.setenv("CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID", "fake-inherited-owner")
    monkeypatch.setenv("CASEOPS_TEST_POSTGRES_URL", "fake-owned-native-db")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "fake-owned-native-db")
    monkeypatch.setenv("CASEOPS_E2E_DATABASE_URL", "fake-browser-db")

    def run(fault=None, *, output_dir=None, make_fixture=False):
        config.write_text(
            json.dumps(
                {
                    "identities": identities,
                    "fault": fault,
                    "source_path": str(api / "tests/test_native_00.py"),
                    "make_fixture": make_fixture,
                }
            )
        )
        output = output_dir or tmp_path / "evidence with spaces"
        return driver.run(api, output, runtime_parent=runtime_parent), output

    return run, tmp_path / "evidence with spaces", calls, identities, api


def test_complete_fresh_whole_file_processes_preserve_every_identity_and_drive_arg(fake_native):
    run, output, calls, identities, _api = fake_native
    code, _ = run()
    assert code == 0 and len(calls) == 9
    inventory = json.loads((output / "postgres-processes/inventory.json").read_text())
    assert inventory["canonical"] == identities
    all_files = [file for group in inventory["groups"] for file in group["files"]]
    assert len(all_files) == len(set(all_files)) == 12
    union = [identity for group in inventory["groups"] for identity in group["nodeids"]]
    assert sorted(union) == sorted(identities)
    for group, command in zip(inventory["groups"], calls[1:], strict=True):
        assert [arg for arg in command if arg.startswith("tests/")] == group["files"]
        folder = output / f"postgres-processes/child-{group['shard']:02}"
        received = json.loads((folder / "received.json").read_text())
        assert received["args"] == command[1:] and received["owner_removed"]
        workspace = json.loads((folder / "runtime-workspace.json").read_text())
        assert "--basetemp=" + str(Path(workspace["runtime"]) / "fixtures") in command
        retained = json.loads((folder / "runtime-retention.json").read_text())
        assert retained["complete"] and retained["files"]
        for row in retained["files"]:
            target = driver.native_path(Path(row["destination_path"]))
            assert target.read_bytes() == (folder / row["relative_path"]).read_bytes()
            assert hashlib.sha256(target.read_bytes()).hexdigest() == row["sha256"]
        completion = json.loads((folder / "process-completion.json").read_text())
        assert completion["natural_completion"] and completion["reaped"]
        parent = Path(workspace["runtime_parent"])
        assert parent.is_dir() and (parent / driver.PARENT_MARKER).is_file()
        assert not Path(workspace["workspace"]).exists()
        assert json.loads((folder / "runtime-cleanup.json").read_bytes()) == {
            "workspace": workspace["workspace"], "removed": True,
        }
        result = driver.journal(folder / "results.jsonl")
        assert result["nodeids"] == group["nodeids"]
    result = driver.journal(output / "postgres-results.jsonl")
    assert result["nodeids"] == identities and len(result["reports"]) == 3 * len(identities)
    completion = json.loads((output / "postgres-driver-completion.json").read_text())
    assert completion["collected"] == len(identities) and completion["phase_count"] == 72
    assert completion["source_unchanged"] and completion["skipped"] == completion["retries"] == 0
    assert (
        completion["journal_sha256"]
        == hashlib.sha256((output / "postgres-results.jsonl").read_bytes()).hexdigest()
    )
    assert (
        completion["junit_sha256"]
        == hashlib.sha256((output / "postgres.xml").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("fault", ["failed", "setup_failed"])
def test_failed_child_keeps_full_details_and_continues_complete_union(fake_native, fault):
    run, output, calls, identities, _api = fake_native
    code, _ = run(fault)
    assert code == 1 and len(calls) == 9
    result = driver.journal(output / "postgres-results.jsonl")
    assert result["nodeids"] == identities and result["exit"] == 1
    failures = [row for row in result["reports"] if row["outcome"] == "failed"]
    assert len(failures) == 1 and failures[0]["longrepr"] == "Full fake failure details retained"
    completion = json.loads((output / "postgres-driver-completion.json").read_text())
    assert completion["exit_code"] == 1 and completion["shards"] == 8
    assert completion["faults"] == [{"shard": 1, "kind": "complete_test_failure"}]
    failed = output / "postgres-processes/child-01"
    workspace = json.loads((failed / "runtime-workspace.json").read_bytes())
    assert Path(workspace["workspace"]).is_dir()
    assert Path(workspace["runtime"]).joinpath("results.jsonl").read_bytes() == (
        failed / "results.jsonl"
    ).read_bytes()
    assert not (failed / "runtime-cleanup.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "interrupted",
        "missing_finish",
        "missing_phase",
        "duplicate_phase",
        "reordered",
        "skipped",
        "empty_xml",
        "wrong_xml",
        "xml_totals",
        "xml_outcome",
        "duplicate_xml",
        "missing_xml",
        "wrong_exit",
        "unknown_xml",
        "malformed_member",
        "duplicate_session",
    ],
)
def test_invalid_child_retains_all_eight_attempts_but_no_combined_completion(fake_native, fault):
    run, output, calls, _ids, _api = fake_native
    with pytest.raises(ValueError, match="evidence incomplete"):
        run(fault)
    assert len(calls) == 9
    assert not (output / "postgres-results.jsonl").exists()
    assert not (output / "postgres.xml").exists()
    assert not (output / "postgres-driver-completion.json").exists()
    faults = json.loads((output / "postgres-processes/faults.json").read_text())
    assert len(faults) == 1 and faults[0]["kind"] == "incomplete_evidence"
    assert (output / "postgres-processes/child-08/process-completion.json").exists()


@pytest.mark.parametrize("fault", ["empty_collection", "duplicate_collection", "missing_file"])
def test_bad_canonical_inventory_never_launches_selected_children(fake_native, fault):
    run, output, calls, _ids, _api = fake_native
    with pytest.raises(ValueError):
        run(fault)
    assert len(calls) == 1 and not (output / "postgres-driver-completion.json").exists()


def test_source_drift_stops_before_another_candidate_child(fake_native):
    run, output, calls, _ids, _api = fake_native
    with pytest.raises(ValueError, match="source changed"):
        run("source_drift")
    assert len(calls) == 2
    assert (output / "postgres-processes/child-01/results.jsonl").exists()
    assert not (output / "postgres-driver-completion.json").exists()


def test_existing_evidence_is_never_overwritten(fake_native):
    run, output, calls, _ids, _api = fake_native
    output.mkdir()
    path = output / "postgres.xml"
    path.write_bytes(b"prior failed evidence")
    with pytest.raises(ValueError, match="overwrite"):
        run()
    assert path.read_bytes() == b"prior failed evidence" and calls == []


def test_ambient_test_filter_cannot_narrow_canonical_acceptance(fake_native, monkeypatch):
    run, _output, calls, _ids, _api = fake_native
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k only_one_case")
    with pytest.raises(ValueError, match="inherit pytest selection"):
        run()
    assert calls == []


def test_runtime_parent_is_claimed_exclusively_and_reused_without_changing_claim(
    tmp_path, runtime_parent,
):
    source, evidence = tmp_path / "source", tmp_path / "evidence"
    admitted = driver.admit_runtime_parent(runtime_parent, source, evidence)
    original = (runtime_parent / driver.PARENT_MARKER).read_bytes()
    assert admitted == driver.admit_runtime_parent(runtime_parent, source, evidence)
    assert (runtime_parent / driver.PARENT_MARKER).read_bytes() == original
    assert admitted["parent_claim"]["identity"] == driver.directory_identity(runtime_parent)
    assert admitted["parent_claim_sha256"] == hashlib.sha256(original).hexdigest()


def test_unclaimed_existing_runtime_parent_is_never_adopted_or_modified(tmp_path, runtime_parent):
    runtime_parent.mkdir(mode=0o700)
    foreign = runtime_parent / "foreign.bin"
    foreign.write_bytes(b"not ours\x00\r\n")
    before = driver.fixture_inventory(runtime_parent)
    with pytest.raises(ValueError, match="unclaimed"):
        driver.admit_runtime_parent(runtime_parent, tmp_path / "source", tmp_path / "evidence")
    assert driver.fixture_inventory(runtime_parent) == before
    assert not (runtime_parent / driver.PARENT_MARKER).exists()


@pytest.mark.parametrize("location", ["temp", "onedrive", "source", "evidence"])
def test_runtime_parent_refuses_each_forbidden_namespace_before_creation(
    tmp_path, runtime_parent, monkeypatch, location,
):
    locations = {
        "temp": Path(driver.tempfile.gettempdir()),
        "onedrive": tmp_path / "sync",
        "source": tmp_path / "source",
        "evidence": tmp_path / "evidence",
    }
    monkeypatch.setenv("OneDriveCommercial", str(locations["onedrive"]))
    base = locations[location]
    base.mkdir(parents=True, exist_ok=True)
    parent = base / "must-not-create"
    with pytest.raises(ValueError, match="overlaps"):
        driver.admit_runtime_parent(parent, locations["source"], locations["evidence"])
    assert not parent.exists()


def test_runtime_parent_refuses_a_physical_directory_alias_before_claim(tmp_path):
    target, alias = tmp_path / "physical", tmp_path / "alias"
    target.mkdir()
    if os.name == "nt":
        result = subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(alias), str(target)],
            capture_output=True, check=False, timeout=5,
        )
        assert result.returncode == 0, "Owned admission junction fixture creation failed"
    else:
        alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="physical path|unsafe"):
        driver.admit_runtime_parent(alias / "r", tmp_path / "source", tmp_path / "evidence")
    assert not (target / "r").exists()


@pytest.mark.parametrize("fault", ["owner", "identity", "nonce", "hardlink"])
def test_claimed_parent_refuses_changed_claim_or_link_count(tmp_path, runtime_parent, fault):
    source, evidence = tmp_path / "source", tmp_path / "evidence"
    driver.admit_runtime_parent(runtime_parent, source, evidence)
    marker = runtime_parent / driver.PARENT_MARKER
    claim = json.loads(marker.read_bytes())
    if fault == "hardlink":
        os.link(marker, runtime_parent / "second-claim-name")
    else:
        if fault == "owner":
            claim["owner"] = {"foreign": "owner"}
        elif fault == "identity":
            claim["identity"]["inode"] += 1
        else:
            claim["nonce"] = "not a nonce"
        marker.write_text(json.dumps(claim), encoding="utf-8")
    before = marker.read_bytes()
    with pytest.raises(ValueError, match="claim"):
        driver.admit_runtime_parent(runtime_parent, source, evidence)
    assert marker.read_bytes() == before and runtime_parent.is_dir()


def test_windows_private_admission_uses_sid_acl_proof_without_getuid(tmp_path, monkeypatch):
    owner = {"user_sid": "S-1-5-21-123", "owner_sid": "S-1-5-21-123", "sddl": "private-test"}
    fake_os = SimpleNamespace(name="nt", environ={"SystemRoot": str(tmp_path)})
    monkeypatch.setattr(driver, "os", fake_os)  # Deliberately has no getuid attribute.
    monkeypatch.setattr(driver, "windows_acl_host", lambda path: (
        tmp_path / "trusted-powershell.exe", {"CASEOPS_NATIVE_ACL_PATH": str(path)},
    ))
    calls = []

    def inspect(command, **kwargs):
        calls.append(command)
        assert command[1:4] == ["-NoProfile", "-NonInteractive", "-Command"]
        assert "Get-Acl -LiteralPath" in command[4] and "Set-Acl" not in command[4]
        assert kwargs["env"]["CASEOPS_NATIVE_ACL_PATH"] == str(tmp_path)
        assert kwargs["timeout"] == 10 and kwargs["check"] is False
        return SimpleNamespace(returncode=0, stdout=json.dumps(owner).encode(), stderr=b"")

    monkeypatch.setattr(driver.subprocess, "run", inspect)
    assert driver.private_directory_owner(tmp_path) == owner
    assert len(calls) == 1


def test_windows_acl_host_cannot_inherit_poisoned_executable_or_module_paths(tmp_path, monkeypatch):
    windows = tmp_path / "native-windows"
    shell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    modules = shell.parent / "Modules"
    modules.mkdir(parents=True)
    shell.write_bytes(b"owned host-path fixture, never executed")
    monkeypatch.setattr(driver, "windows_system_directory", lambda: windows)
    for key in ("SystemRoot", "windir", "PATH", "PSModulePath", "POISONED_EXTRA"):
        monkeypatch.setenv(key, str(tmp_path / "caller-controlled"))
    monkeypatch.setenv("TEMP", "unchanged-temp")
    monkeypatch.setenv("TMP", "unchanged-tmp")
    executable, env = driver.windows_acl_host(tmp_path / "admitted")
    assert executable == shell
    assert env == {
        "SystemRoot": str(windows), "windir": str(windows),
        "PATH": str(windows / "System32"), "PSModulePath": str(modules),
        "CASEOPS_NATIVE_ACL_PATH": str(tmp_path / "admitted"),
        "TEMP": "unchanged-temp", "TMP": "unchanged-tmp",
    }


def test_windows_acl_probe_never_launches_without_trusted_native_host(monkeypatch):
    def unavailable():
        raise ValueError("Trusted native Windows directory unavailable")

    def unexpected(*args, **kwargs):
        pytest.fail("Unadmitted native host must not launch a child")

    monkeypatch.setattr(driver, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(driver, "windows_system_directory", unavailable)
    monkeypatch.setattr(driver.subprocess, "run", unexpected)
    with pytest.raises(ValueError, match="native Windows directory unavailable"):
        driver.private_directory_owner(Path("unused"))


@pytest.mark.skipif(os.name != "nt", reason="Canonical Windows SID/ACL policy script")
@pytest.mark.parametrize("shape", [
    "private", "owner-rights", "admin-owner", "admin-owner-ow", "inherited-writer", "unprotected",
])
def test_windows_acl_policy_refuses_admin_ownership_and_inherited_writers(
    tmp_path, monkeypatch, shape,
):
    real_run = subprocess.run
    # Exercise the actual admission script with in-memory ACL policy fixtures;
    # never change any directory's native owner or ACL to construct a refusal.
    fixture = r"""
function Get-Acl {
    param($LiteralPath)
    $current = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $owner = if ($env:CASEOPS_UNIT_ACL_SHAPE -in @('admin-owner', 'admin-owner-ow')) {
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    } else { $current }
    $principal = if ($env:CASEOPS_UNIT_ACL_SHAPE -in @('owner-rights', 'admin-owner-ow')) {
        [Security.Principal.SecurityIdentifier]::new('S-1-3-4')
    } else { $current }
    $rule = [pscustomobject]@{
        IdentityReference=$principal; AccessControlType='Allow'; IsInherited=$false
        FileSystemRights=[Security.AccessControl.FileSystemRights]::FullControl
        PropagationFlags=[Security.AccessControl.PropagationFlags]::None
    }
    $rules = @($rule)
    if ($env:CASEOPS_UNIT_ACL_SHAPE -eq 'inherited-writer') {
        $rules += [pscustomobject]@{
            IdentityReference=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-545')
            AccessControlType='Allow'; IsInherited=$true
            FileSystemRights=[Security.AccessControl.FileSystemRights]::Modify
            PropagationFlags=[Security.AccessControl.PropagationFlags]::None
        }
    }
    $acl = [pscustomobject]@{
        FixtureOwner=$owner; FixtureRules=$rules; Sddl='unit-policy-fixture'
        AreAccessRulesProtected=($env:CASEOPS_UNIT_ACL_SHAPE -ne 'unprotected')
    }
    $acl | Add-Member ScriptMethod GetOwner { param($type) $this.FixtureOwner }
    $acl | Add-Member ScriptMethod GetAccessRules { param($a,$b,$type) $this.FixtureRules }
    return $acl
}
"""

    def inspect(command, **kwargs):
        command = [*command[:-1], fixture + command[-1]]
        kwargs["env"]["CASEOPS_UNIT_ACL_SHAPE"] = shape
        return real_run(command, **kwargs)

    monkeypatch.setattr(driver.subprocess, "run", inspect)
    if shape in {"private", "owner-rights"}:
        owner = driver.private_directory_owner(tmp_path)
        assert owner["user_sid"] == owner["owner_sid"]
    else:
        with pytest.raises(ValueError, match="ownership unconfirmed"):
            driver.private_directory_owner(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Real Python 3.13 Windows mkdir(0700) DACL")
def test_native_windows_mkdir700_parent_and_workspace_are_current_user_private(
    tmp_path, runtime_parent,
):
    claim = driver.admit_runtime_parent(runtime_parent, tmp_path / "source", tmp_path / "evidence")
    owner = driver.private_directory_owner(runtime_parent)
    assert owner["owner_sid"] == owner["user_sid"] == claim["parent_claim"]["owner"]["user_sid"]
    workspace = Path(tempfile.mkdtemp(prefix="copg-", dir=runtime_parent))
    workspace_owner = driver.private_directory_owner(workspace)
    assert workspace_owner["owner_sid"] == workspace_owner["user_sid"] == owner["user_sid"]
    (workspace / "exclusive-unit-marker").write_bytes(b"original owned native bytes\x00\r\n")
    ownership = {
        **claim,
        "temp_root_identity": driver.directory_identity(runtime_parent),
        "workspace_identity": driver.directory_identity(workspace),
        "workspace_owner": workspace_owner,
    }
    driver.cleanup_workspace(
        workspace, runtime_parent, ownership, driver.fixture_inventory(workspace),
    )
    assert not workspace.exists() and runtime_parent.is_dir()
    assert (runtime_parent / driver.PARENT_MARKER).is_file()


@pytest.mark.parametrize("boundary", [
    "open", "fstat-1", "write", "fsync", "fstat-2", "fstat-3",
    pytest.param(
        "fstat-4", marks=pytest.mark.skipif(os.name == "nt", reason="POSIX fchmod observation"),
    ),
])
def test_original_capture_guards_survive_global_temp_and_sibling_scratch_activity(
    tmp_path, runtime_parent, monkeypatch, boundary,
):
    from tests import test_matter_readthrough_evidence_20261028 as evidence

    helper_hash = hashlib.sha256(Path(evidence.__file__).read_bytes()).hexdigest()
    api, folder = tmp_path / "api", tmp_path / "retained"
    api.mkdir()
    folder.mkdir()
    ambient = Path(tempfile.gettempdir()).resolve()
    assert not runtime_parent.is_relative_to(ambient)
    original_owner = driver.private_directory_owner(runtime_parent.parent)
    monkeypatch.setattr(driver, "private_directory_owner", lambda path: original_owner)
    noise, observations = [], []
    expected_payload = (json.dumps({"plan": "unchanged\r\nbinary-safe"}, indent=2) + "\n").encode()
    reference = None

    def launch(command, **kwargs):
        nonlocal reference
        runtime = Path(kwargs["env"]["CASEOPS_TEST_RESULT_JOURNAL"]).parent
        plans, scratch = runtime / "fixtures/plans", runtime / "scratch"
        plans.mkdir(parents=True)
        scratch.mkdir()
        path = plans / "original-captured.json"
        assert scratch not in path.parents and ambient not in path.parents
        counts = {"fstat": 0}

        def activity(event):
            observations.append(event)
            if event != boundary:
                return
            name = "copg-unit-noise-" + os.urandom(12).hex()
            global_file = ambient / name
            payload = b"owned global-temp and sibling-scratch activity\x00\r\n"
            with global_file.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            noise.append((global_file, payload))
            with (scratch / name).open("xb") as stream:
                stream.write(payload)

        def opened(name, flags, mode):
            assert flags & os.O_EXCL and flags & os.O_CREAT
            if os.name == "nt":
                assert flags & os.O_BINARY
            activity("open")
            return os.open(name, flags, mode)

        def fstat(fd):
            counts["fstat"] += 1
            activity(f"fstat-{counts['fstat']}")
            return os.fstat(fd)

        def write(fd, data):
            activity("write")
            return os.write(fd, data)

        def fsync(fd):
            activity("fsync")
            return os.fsync(fd)

        io = SimpleNamespace(open=opened, fstat=fstat, write=write, fsync=fsync,
                             close=os.close, fchmod=getattr(os, "fchmod", None))
        reference = evidence.capture_plan(path, {"plan": "unchanged\r\nbinary-safe"}, io=io)
        assert reference == {
            "basename": path.name, "sha256": hashlib.sha256(expected_payload).hexdigest(),
            "sizeBytes": len(expected_payload),
        }
        assert path.read_bytes() == expected_payload
        assert evidence.load_captured_plan(path, reference) == {"plan": "unchanged\r\nbinary-safe"}
        return SimpleNamespace(pid=os.getpid(), wait=lambda: 0)

    monkeypatch.setattr(driver.subprocess, "Popen", launch)
    try:
        assert driver.execute(
            api, folder, ["tests/unit_capture.py"], runtime_parent=runtime_parent,
        ) == 0
        assert observations.count(boundary) == 1 and len(noise) == 1
        retained = json.loads((folder / "runtime-retention.json").read_bytes())
        indexed = {row["relative_path"]: row for row in retained["files"]}
        assert indexed["fixtures/plans/original-captured.json"]["sha256"] == reference["sha256"]
        assert (folder / "fixtures/plans/original-captured.json").read_bytes() == expected_payload
        assert (folder / "scratch" / noise[0][0].name).read_bytes() == noise[0][1]
        assert (folder / "runtime-cleanup.json").is_file()
        assert hashlib.sha256(Path(evidence.__file__).read_bytes()).hexdigest() == helper_hash
    finally:
        for path, payload in noise:
            assert not path.is_symlink() and path.lstat().st_nlink == 1
            assert path.read_bytes() == payload
            path.unlink()  # Only this unit's exclusive global-temp leaf, never its shared parent.


def test_driver_requires_an_explicit_runtime_parent(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--api-dir", "api", "--results-directory", "out"],
    )
    with pytest.raises(SystemExit) as error:
        driver.main()
    assert error.value.code == 2


def test_child_launch_failure_keeps_exclusive_workspace_and_original_evidence(
    fake_native, monkeypatch,
):
    run, output, _calls, _identities, _api = fake_native

    def refused(*args, **kwargs):
        raise OSError("deterministic child launch refusal")

    monkeypatch.setattr(driver.subprocess, "Popen", refused)
    with pytest.raises(OSError, match="launch refusal"):
        run()
    folder = output / "postgres-processes/collection"
    workspace = json.loads((folder / "runtime-workspace.json").read_bytes())
    assert Path(workspace["workspace"]).joinpath(".caseops-runtime-owner.json").is_file()
    assert Path(workspace["runtime"]).joinpath("started.json").is_file()
    assert not (folder / "runtime-cleanup.json").exists()
    assert not (output / "postgres-driver-completion.json").exists()


def test_partition_is_deterministic_balanced_and_whole_file(fake_native):
    _run, _output, _calls, identities, api = fake_native
    groups = driver.plan(identities, api)
    assert groups == driver.plan(list(identities), api)
    lengths = [len(group["nodeids"]) for group in groups]
    assert max(lengths) - min(lengths) <= 2
    with pytest.raises(ValueError, match="eight nonempty"):
        driver.plan(identities[:2], api)


@pytest.mark.parametrize(
    "identity",
    [
        "",
        "tests/../evil.py::test_x",
        "C:/test.py::test_x",
        "tests//test.py::test_x",
        "tests\\test.py::test_x",
    ],
)
def test_noncanonical_identity_is_rejected(identity):
    with pytest.raises(ValueError):
        driver.module_path(identity)


@pytest.mark.parametrize("fault", [None, "git_error", "bad_head", "duplicate", "missing"])
def test_source_pin_reader_rejects_incomplete_inventory_without_real_git(
    tmp_path, monkeypatch, fault
):
    source = tmp_path / "source.py"
    source.write_bytes(b"original source bytes")
    calls = []

    def git(command, **kwargs):
        calls.append(command)
        assert command[:3] == ["git", "-C", str(tmp_path)]
        assert kwargs == {"capture_output": True, "check": False}
        if fault == "git_error":
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"not printed")
        if command[-2:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(
                returncode=0, stdout=(b"invalid" if fault == "bad_head" else b"1" * 40)
            )
        assert command[3:] == ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        names = {"duplicate": b"source.py\0source.py\0", "missing": b"absent.py\0"}
        return SimpleNamespace(returncode=0, stdout=names.get(fault, b"source.py\0"))

    monkeypatch.setattr(driver.subprocess, "run", git)
    if fault:
        with pytest.raises(ValueError):
            driver.source_snapshot(tmp_path)
    else:
        assert driver.source_snapshot(tmp_path) == {
            "head": "1" * 40,
            "files": {"source.py": hashlib.sha256(source.read_bytes()).hexdigest()},
        }
    assert calls


def test_external_interruption_reaps_child_and_never_claims_natural_completion(
    tmp_path, monkeypatch, runtime_parent
):
    api = tmp_path / "api"
    folder = tmp_path / "interrupted-child"
    api.mkdir()
    folder.mkdir()
    calls = []

    class Interrupted:
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if len(calls) == 1:
                raise KeyboardInterrupt
            return -15

        def poll(self):
            return None

        def terminate(self):
            calls.append(("terminate", None))

    monkeypatch.setattr(driver.subprocess, "Popen", lambda *args, **kwargs: Interrupted())
    monkeypatch.setattr(driver, "private_directory_owner", lambda path: {"fake_owner": "unit"})

    def terminate(process):
        process.terminate()
        process.wait(timeout=5)

    monkeypatch.setattr(driver, "terminate_owned_process", terminate)
    with pytest.raises(KeyboardInterrupt):
        driver.execute(api, folder, ["tests/test_native.py"], runtime_parent=runtime_parent)
    assert calls == [("wait", None), ("terminate", None), ("wait", 5)]
    assert not (folder / "process-completion.json").exists()
    assert json.loads((folder / "interrupted.json").read_text()) == {
        "natural_completion": False,
        "reaped": True,
    }
    workspace = json.loads((folder / "runtime-workspace.json").read_bytes())
    assert Path(workspace["workspace"]).is_dir()
    assert not (folder / "runtime-cleanup.json").exists()


def test_complete_runtime_retention_preserves_long_binary_and_empty_directory_paths(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    relative = Path("fixtures/test_original_fixture_name") / ("nested" * 14) / "original.bin"
    original = driver.native_path(source / relative)
    original.parent.mkdir(parents=True)
    data = bytes(range(256)) + b"\r\n\x00\xff" * 37
    original.write_bytes(data)
    driver.native_path(source / "empty-original-directory").mkdir()
    destination = tmp_path / ("long-destination-" * 6) / ("long-original-evidence-" * 5)
    driver.native_path(destination).mkdir(parents=True)
    assert len(str(destination / relative)) > 260
    result = driver.retain_runtime(source, destination)
    assert result["complete"]
    assert result["directories"] == sorted(
        [
            "empty-original-directory",
            "fixtures",
            "fixtures/test_original_fixture_name",
            "fixtures/test_original_fixture_name/" + "nested" * 14,
        ]
    )
    assert len(result["files"]) == 1
    row = result["files"][0]
    assert row["relative_path"] == relative.as_posix()
    assert row["bytes"] == len(data) and row["sha256"] == hashlib.sha256(data).hexdigest()
    assert driver.native_path(destination / relative).read_bytes() == data
    assert driver.native_path(destination / "empty-original-directory").is_dir()
    assert (
        json.loads(driver.native_path(destination / "runtime-retention.json").read_bytes())
        == result
    )
    assert not driver.native_path(destination / "runtime-retention.pending").exists()


@pytest.mark.parametrize("fault", ["copy", "changed", "bound", "empty", "overwrite"])
def test_runtime_retention_fails_closed_and_keeps_original_bytes(tmp_path, monkeypatch, fault):
    source, destination = tmp_path / "original", tmp_path / "retained"
    source.mkdir()
    destination.mkdir()
    original = source / "original.bin"
    if fault != "empty":
        original.write_bytes(b"original\x00\r\nbytes")
    if fault == "copy":
        real_open = Path.open

        def fail_open(path, *args, **kwargs):
            if path == driver.native_path(destination / "original.bin"):
                raise OSError("deterministic destination IO refusal")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_open)
    elif fault == "changed":
        inventory = driver.fixture_inventory
        calls = []

        def changed(path):
            calls.append(path)
            if len(calls) == 2:
                original.write_bytes(b"changed-original")
            return inventory(path)

        monkeypatch.setattr(driver, "fixture_inventory", changed)
    elif fault == "bound":
        monkeypatch.setattr(driver, "MAX_RETAIN_BYTES", 1)
    elif fault == "overwrite":
        (destination / "original.bin").write_bytes(b"earlier failed evidence")
    with pytest.raises((OSError, ValueError)):
        driver.retain_runtime(source, destination)
    assert not (destination / "runtime-retention.json").exists()
    if fault not in {"empty", "changed"}:
        assert original.read_bytes() == b"original\x00\r\nbytes"
    if fault == "overwrite":
        assert (destination / "original.bin").read_bytes() == b"earlier failed evidence"


def test_short_runtime_retains_long_evidence_without_changing_environment(fake_native):
    run, output, calls, _ids, _api = fake_native
    long_output = output / ("long-destination-" * 6) / ("long-original-evidence-" * 5)
    assert len(str(long_output)) > 260
    assert run(output_dir=long_output, make_fixture=True)[0] == 0
    for command in calls:
        fixture = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--basetemp="))
        assert not Path(fixture).is_relative_to(long_output)
        if os.name == "nt":
            assert len(fixture) <= 100
    work = driver.native_path(long_output / "postgres-processes")
    for folder in [work / "collection", *sorted(work.glob("child-*"))]:
        receipt = json.loads((folder / "runtime-retention.json").read_bytes())
        originals = [
            r for r in receipt["files"] if r["relative_path"].endswith("original-document.bin")
        ]
        assert len(originals) == 1 and len(originals[0]["destination_path"]) > 260
        row = originals[0]
        assert row["bytes"] == 260
        assert (
            driver.native_path(Path(row["destination_path"])).read_bytes()
            == bytes(range(256)) + b"\r\n\x00\xff"
        )


def test_retention_failure_never_starts_another_child_and_preserves_runtime(
    fake_native, monkeypatch
):
    run, output, calls, _ids, _api = fake_native

    def refused(*args):
        raise OSError("deterministic native evidence copy failure")

    monkeypatch.setattr(driver, "retain_runtime", refused)
    with pytest.raises(OSError, match="evidence copy failure"):
        run()
    assert len(calls) == 1 and not (output / "postgres-driver-completion.json").exists()
    folder = output / "postgres-processes/collection"
    incomplete = json.loads((folder / "retention-incomplete.json").read_bytes())
    assert incomplete["complete"] is False and incomplete["preserved"] is True
    runtime = Path(incomplete["runtime"])
    assert runtime.is_dir() and (runtime / "results.jsonl").is_file()


def test_runtime_reparse_directory_is_rejected_without_copying_outside(tmp_path):
    source, target, destination = tmp_path / "source", tmp_path / "outside", tmp_path / "retained"
    for path in (source, target, destination):
        path.mkdir()
    (target / "not-runtime.bin").write_bytes(b"outside-original")
    link = source / "linked-outside"
    if os.name == "nt":
        result = subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0, "Owned junction fixture creation failed"
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="Reparse point"):
        driver.retain_runtime(source, destination)
    assert not (destination / "runtime-retention.json").exists()
    assert not (destination / "linked-outside/not-runtime.bin").exists()
    assert (target / "not-runtime.bin").read_bytes() == b"outside-original"


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("This process may not create symbolic links")


@pytest.mark.parametrize("target_kind", ["absolute", "relative"])
def test_pytest_current_links_are_dropped_and_their_numbered_targets_retained(
    tmp_path, target_kind
):
    """An elevated Windows run lets pytest link each numbered basetemp entry."""
    fixtures, destination = tmp_path / "fixtures", tmp_path / "retained"
    numbered = fixtures / "test_upload_commit0"
    numbered.mkdir(parents=True)
    (numbered / "evidence.bin").write_bytes(b"retained bytes")
    destination.mkdir()
    target = numbered if target_kind == "absolute" else Path(numbered.name)
    _symlink_or_skip(fixtures / "test_upload_commitcurrent", target)

    removed = driver.drop_pytest_current_links(fixtures)
    assert removed == ["test_upload_commitcurrent"]
    assert not os.path.lexists(fixtures / "test_upload_commitcurrent")
    driver.retain_runtime(fixtures, destination)
    assert (destination / "test_upload_commit0/evidence.bin").read_bytes() == b"retained bytes"


@pytest.mark.parametrize("alias_kind", ["ordinary_entry", "relative_symlink"])
def test_pytest_current_link_cleanup_rejects_root_junction_without_touching_outside(
    tmp_path, alias_kind
):
    fixtures, outside = tmp_path / "fixtures", tmp_path / "outside"
    numbered = outside / "test_case0"
    numbered.mkdir(parents=True)
    evidence = numbered / "evidence.bin"
    evidence.write_bytes(b"outside-original\x00\r\nbytes")
    alias = outside / "test_casecurrent"
    expected_target = numbered.name
    if alias_kind == "relative_symlink":
        _symlink_or_skip(alias, Path(expected_target))
    else:
        alias.mkdir()
        (alias / "untouched.bin").write_bytes(b"outside-current-entry")
    if os.name == "nt":
        result = subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(fixtures), str(outside)],
            capture_output=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0, "Owned root junction fixture creation failed"
        assert fixtures.is_dir() and not fixtures.is_symlink()
        assert fixtures.lstat().st_file_attributes & 0x400
    else:
        fixtures.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="Reparse point"):
        driver.drop_pytest_current_links(fixtures)
    if alias_kind == "relative_symlink":
        assert alias.is_symlink() and os.readlink(alias) == expected_target
    else:
        assert not alias.is_symlink()
        assert (alias / "untouched.bin").read_bytes() == b"outside-current-entry"
    assert numbered.is_dir()
    assert evidence.read_bytes() == b"outside-original\x00\r\nbytes"


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param(SimpleNamespace(st_mode=driver.stat.S_IFLNK), id="symlink-mode"),
        pytest.param(
            SimpleNamespace(st_mode=driver.stat.S_IFDIR, st_file_attributes=0x400),
            id="directory-reparse-attribute",
        ),
    ],
)
def test_pytest_current_link_cleanup_rejects_reparse_metadata_before_io(monkeypatch, metadata):
    root = SimpleNamespace(
        lstat=lambda: metadata,
        is_dir=lambda: True,
        is_symlink=lambda: False,
    )

    def unexpected_io(*args, **kwargs):
        pytest.fail("Reparse root must be rejected before scanning or deleting entries")

    with monkeypatch.context() as scoped:
        scoped.setattr(driver, "native_path", lambda path: root)
        for operation in ("scandir", "unlink", "rmdir"):
            scoped.setattr(driver.os, operation, unexpected_io)
        with pytest.raises(ValueError, match="Reparse point"):
            driver.drop_pytest_current_links(Path("fixtures"))


@pytest.mark.parametrize("shape", ["outside", "unnumbered", "other-name"])
def test_any_other_link_is_kept_and_still_refused(tmp_path, shape):
    fixtures, outside = tmp_path / "fixtures", tmp_path / "outside"
    fixtures.mkdir()
    outside.mkdir()
    (outside / "not-runtime.bin").write_bytes(b"outside")
    sibling = fixtures / ("test_casex" if shape == "unnumbered" else "test_case0")
    sibling.mkdir()
    (sibling / "evidence.bin").write_bytes(b"inside")
    name = "test_case_link" if shape == "other-name" else "test_casecurrent"
    target = outside if shape == "outside" else sibling
    _symlink_or_skip(fixtures / name, target)

    assert driver.drop_pytest_current_links(fixtures) == []
    assert os.path.lexists(fixtures / name)
    with pytest.raises(ValueError, match="Reparse point"):
        driver.fixture_inventory(fixtures)


@pytest.mark.parametrize("fault", ["outside", "identity", "marker", "extra", "parent-claim"])
def test_owned_cleanup_refuses_changed_creation_containment_or_bytes(
    tmp_path, runtime_parent, fault,
):
    root = runtime_parent
    parent_claim = driver.admit_runtime_parent(root, tmp_path / "source", tmp_path / "evidence")
    workspace = root / "copg-original"
    workspace.mkdir(mode=0o700)
    owner = workspace / "original-owner.json"
    owner.write_bytes(b"exclusive-original-owner")
    ownership = {
        **parent_claim,
        "temp_root_identity": driver.directory_identity(root),
        "workspace_identity": driver.directory_identity(workspace),
        "workspace_owner": driver.private_directory_owner(workspace),
    }
    expected = driver.fixture_inventory(workspace)
    if fault == "outside":
        other = tmp_path / "unrelated-temp-root"
        other.mkdir()
        root = other
    elif fault == "identity":
        ownership["workspace_identity"]["inode"] += 1
    elif fault == "marker":
        owner.write_bytes(b"changed-owner")
    elif fault == "parent-claim":
        (root / driver.PARENT_MARKER).write_bytes(b"changed parent claim")
    else:
        (workspace / "not-retained-original.bin").write_bytes(b"new-original-bytes")
    with pytest.raises(ValueError, match="cleanup identity or inventory changed"):
        driver.cleanup_workspace(workspace, root, ownership, expected)
    assert workspace.is_dir() and owner.is_file()


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows native descendant termination contract")
def test_windows_interruption_reaps_actual_python_descendant_and_retains_partial_files(
    tmp_path,
    monkeypatch,
    runtime_parent,
):
    import ctypes

    api, folder = tmp_path / "api", tmp_path / "evidence"
    api.mkdir()
    folder.mkdir()
    pid_file = tmp_path / "descendant.json"
    program = tmp_path / "parent.py"
    program.write_text(
        "import json,os,subprocess,sys,threading\n"
        "from pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import threading;threading.Event().wait(60)'])\n"
        "Path(os.environ['CASEOPS_TEST_RESULT_JOURNAL']).write_bytes("
        "b'partial original journal\\r\\n\\x00')\n"
        f"Path({str(pid_file)!r}).write_text(json.dumps({{'parent':os.getpid(),'child':child.pid}}))\n"
        "threading.Event().wait(60)\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    handles = []
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]

    def launch(command, **kwargs):
        if command[0] == "taskkill":
            return real_popen(command, **kwargs)
        process = real_popen([sys.executable, str(program)], **kwargs)
        original_wait = process.wait
        calls = []

        def wait(timeout=None):
            if not calls:
                calls.append("interrupt")
                deadline = time.monotonic() + 5
                while not pid_file.exists():
                    assert time.monotonic() < deadline
                    time.sleep(0.02)
                ids = json.loads(pid_file.read_bytes())
                assert ids["child"] != ids["parent"]
                for pid in {process.pid, ids["parent"], ids["child"]}:
                    handle = kernel.OpenProcess(0x100000, 0, pid)
                    assert handle
                    handles.append(handle)
                raise KeyboardInterrupt
            return original_wait(timeout=timeout)

        process.wait = wait
        return process

    # The process-tree fake must not intercept the independent read-only ACL probe.
    private_owner = driver.private_directory_owner(runtime_parent.parent)
    monkeypatch.setattr(driver, "private_directory_owner", lambda path: private_owner)
    monkeypatch.setattr(driver.subprocess, "Popen", launch)
    try:
        with pytest.raises(KeyboardInterrupt):
            driver.execute(api, folder, ["tests/test_native.py"], runtime_parent=runtime_parent)
        assert all(kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles)
        assert (folder / "results.jsonl").read_bytes() == b"partial original journal\r\n\x00"
        assert json.loads((folder / "runtime-retention.json").read_bytes())["complete"]
        assert not (folder / "process-completion.json").exists()
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
