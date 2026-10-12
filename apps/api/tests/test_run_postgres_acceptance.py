"""Offline fake-process contracts for complete whole-file native acceptance."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
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
def fake_native(tmp_path, monkeypatch):
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
        calls.append(command)
        return real_popen([sys.executable, str(program), *command[1:]], **kwargs)

    monkeypatch.setattr(driver, "source_snapshot", snapshot)
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
        return driver.run(api, output), output

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
    tmp_path, monkeypatch
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

    def terminate(process):
        process.terminate()
        process.wait(timeout=5)

    monkeypatch.setattr(driver, "terminate_owned_process", terminate)
    with pytest.raises(KeyboardInterrupt):
        driver.execute(api, folder, ["tests/test_native.py"])
    assert calls == [("wait", None), ("terminate", None), ("wait", 5)]
    assert not (folder / "process-completion.json").exists()
    assert json.loads((folder / "interrupted.json").read_text()) == {
        "natural_completion": False,
        "reaped": True,
    }


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


def test_actual_short_runtime_avoids_long_evidence_fixture_argument(fake_native):
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


@pytest.mark.parametrize("fault", ["outside", "identity", "marker", "extra"])
def test_owned_cleanup_refuses_changed_creation_containment_or_bytes(tmp_path, fault):
    root = tmp_path / "captured-temp-root"
    root.mkdir()
    workspace = root / "copg-original"
    workspace.mkdir()
    owner = workspace / "original-owner.json"
    owner.write_bytes(b"exclusive-original-owner")
    ownership = {
        "temp_root_identity": driver.directory_identity(root),
        "workspace_identity": driver.directory_identity(workspace),
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
    else:
        (workspace / "not-retained-original.bin").write_bytes(b"new-original-bytes")
    with pytest.raises(ValueError, match="cleanup identity or inventory changed"):
        driver.cleanup_workspace(workspace, root, ownership, expected)
    assert workspace.is_dir() and owner.is_file()


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows native descendant termination contract")
def test_windows_interruption_reaps_actual_python_descendant_and_retains_partial_files(
    tmp_path,
    monkeypatch,
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

    monkeypatch.setattr(driver.subprocess, "Popen", launch)
    try:
        with pytest.raises(KeyboardInterrupt):
            driver.execute(api, folder, ["tests/test_native.py"])
        assert all(kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles)
        assert (folder / "results.jsonl").read_bytes() == b"partial original journal\r\n\x00"
        assert json.loads((folder / "runtime-retention.json").read_bytes())["complete"]
        assert not (folder / "process-completion.json").exists()
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
