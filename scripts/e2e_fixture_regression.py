"""Run the fixed 18-process/51-SQLite E2E fixture inventory without installing anything."""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests/e2e/fixture-tests"
SUPPORT = ROOT / "tests/e2e/support"
SUPERVISOR = SUPPORT / "oauth/fixture_supervisor.py"
PHASE_TIMEOUT_SECONDS = 180
RUN_TIMEOUT_SECONDS = 210
REAP_SECONDS = 5


def save(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def record(path: Path, **value) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value) + "\n")
        stream.flush()


def snapshot() -> dict:
    head = subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, check=True, timeout=5).stdout.decode("ascii").strip()
    files = set((ROOT / "apps/api/src").rglob("*.py"))
    files.update(path for path in TESTS.iterdir() if path.is_file())
    files.update(SUPPORT / name for name in ("iplf063b.ts", "iplf058b.ts", "env.ts",
                 "fixture-database.ts", "ip-entitlement-fixture.ts", "ip_entitlement_fixture.py"))
    files.add(SUPERVISOR)
    files.update(ROOT / name for name in ("scripts/e2e_fixture_regression.py", "package.json",
                 "package-lock.json", "apps/web/package.json", "tsconfig.e2e.json"))
    hashes = {}
    for path in sorted(files):
        if not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("Fixture source input is missing or outside the checkout")
        hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"head": head, "files": hashes}


def load_supervisor():
    spec = importlib.util.spec_from_file_location("caseops_e2e_fixture_supervisor", SUPERVISOR)
    if spec is None or spec.loader is None:
        raise ImportError("The fixture supervisor could not be loaded")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def run_phase(name: str, argv: list[str], env: dict, directory: Path, journal: Path,
              run_deadline: float, supervisor) -> None:
    directory.mkdir()
    timeout = min(PHASE_TIMEOUT_SECONDS, run_deadline - time.monotonic())
    if timeout <= REAP_SECONDS:
        raise RuntimeError("Fixture regression supervisor budget exhausted")
    deadline = time.monotonic() + timeout
    save(directory / "invocation.json", {"argv": argv, "timeout_seconds": timeout,
                                       "cleanup_reserve_seconds": REAP_SECONDS})
    record(journal, event="started", phase=name)
    process = job = libc = None
    previous_subreaper = ctypes.c_int()
    cleaned = True
    try:
        if os.name == "nt":
            job = supervisor.WindowsJob()
        elif sys.platform.startswith("linux"):
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(37, ctypes.byref(previous_subreaper), 0, 0, 0) != 0:
                libc = None
                raise OSError("Fixture subreaper status is unknown")
            if libc.prctl(36, 1, 0, 0, 0) != 0:
                raise OSError("Fixture subreaper setup failed")
        else:
            raise ValueError("Unsupported fixture process ownership")
        with (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
            process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                start_new_session=os.name != "nt", creationflags=(0x4 | 0x200 | 0x8000000) if job else 0)
            if job:
                job.assign(process)
                job.resume(process)
            record(journal, event="spawned", phase=name, pid=process.pid)
            while time.monotonic() < deadline - REAP_SECONDS:
                if supervisor.child_exited(process):
                    record(journal, event="exit_observed", phase=name)
                    break
                time.sleep(0.01)
            else:
                raise TimeoutError("Fixture phase exceeded its execution budget")
    except BaseException as error:
        record(journal, event="phase_failed", phase=name, error_type=type(error).__name__)
        raise
    finally:
        # Retain the POSIX leader's identity until the public cleanup has signalled
        # the owned group. Never poll/wait/reap it beforehand.
        previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            try:
                if process is not None:
                    grace = min(REAP_SECONDS, max(0.001, deadline - time.monotonic()))
                    cleaned = False
                    cleaned = supervisor.cleanup(process, job, grace)
                    record(journal, event="cleanup_reaped" if cleaned else "cleanup_failed",
                           phase=name, tree_reaped=cleaned, returncode=process.returncode)
            except BaseException as cleanup_error:
                record(journal, event="cleanup_failed", phase=name, error_type=type(cleanup_error).__name__)
                raise
            finally:
                if job:
                    job.close()
                if libc is not None and libc.prctl(36, previous_subreaper.value, 0, 0, 0) != 0:
                    cleaned = False
                    record(journal, event="cleanup_failed", phase=name, reason="subreaper_restore_failed")
            if not cleaned:
                raise RuntimeError("Fixture owned-tree cleanup or subreaper restoration was not confirmed")
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    code = process.returncode
    record(journal, event="reaped", phase=name, returncode=code)
    if code != 0:
        raise RuntimeError(f"Fixture {name} process exited unsuccessfully")


def read_json(path: Path):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Fixture report exceeded its evidence bound")
    return json.loads(path.read_text(encoding="utf-8"))


def junit_names(path: Path, count: int) -> list[str]:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Fixture JUnit exceeded its evidence bound")
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    if len(cases) != count:
        raise ValueError("Fixture JUnit did not contain the exact expected case count")
    if any(root.find(".//" + tag) is not None for tag in ("failure", "error", "skipped")):
        raise ValueError("Failed, errored, skipped or todo fixture cases are not acceptance")
    names = [case.attrib["name"] for case in cases]
    if len(set(names)) != count:
        raise ValueError("Duplicate fixture JUnit identity")
    return names


def reconcile_node(directory: Path):
    inventory = read_json(directory / "inventory.json")
    if not isinstance(inventory, list) or len(inventory) != 18 or any(not isinstance(item, str) for item in inventory):
        raise ValueError("Expected exactly 18 registered Node test identities")
    if len(set(inventory)) != 18 or set(inventory) != set(junit_names(directory / "junit.xml", 18)):
        raise ValueError("Node registered/JUnit identities disagree")
    return inventory


def reconcile_sqlite(directory: Path):
    path = directory / "phases.jsonl"
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Fixture phase journal exceeded its evidence bound")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    collections = [item for item in records if item["event"] == "collection"]
    completions = [item for item in records if item["event"] == "complete"]
    if len(collections) != 1 or len(completions) != 1 or completions[0] != {
        "event": "complete", "exitstatus": 0, "collected": 51,
    }:
        raise ValueError("Missing or unsuccessful complete SQLite inventory")
    ids = collections[0]["ids"]
    module = "tests/e2e/fixture-tests/test_ip_entitlement_fixture.py"
    if len(ids) != 51 or len(set(ids)) != 51 or any(item.split("::", 1)[0] != module for item in ids):
        raise ValueError("Expected exactly 51 identities from the selected SQLite fixture file")
    phases = [item for item in records if item["event"] == "phase"]
    expected = Counter((identity, phase) for identity in ids for phase in ("setup", "call", "teardown"))
    if (len(records) != 155 or Counter((item["id"], item["phase"]) for item in phases) != expected
            or any(item["outcome"] != "passed" for item in phases)):
        raise ValueError("SQLite setup/call/teardown identities are incomplete or unsuccessful")
    if {item.split("::", 1)[1] for item in ids} != set(junit_names(directory / "junit.xml", 51)):
        raise ValueError("SQLite collection/JUnit identities disagree")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-directory", required=True, type=Path)
    parser.add_argument("--scratch-root", type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    results = args.results_directory.absolute()
    results.mkdir(parents=True, exist_ok=False)
    journal = results / "supervisor.jsonl"
    state = {"complete": False, "passed": False, "expected": {"process": 18, "sqlite": 51}, "phases": []}
    before = None
    run_deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    try:
        scratch_root = args.scratch_root.resolve(strict=True)
        if not scratch_root.is_dir() or scratch_root.is_relative_to(ROOT):
            raise ValueError("Scratch must be an existing directory outside the checkout")
        if not args.node or not Path(args.node).is_file():
            raise ValueError("An existing Node executable is required")
        if any(key.upper().startswith("PG") for key in os.environ):
            raise ValueError("Ambient PG overrides are not allowed")
        scratch = Path(tempfile.mkdtemp(prefix="coe2e-", dir=scratch_root))
        state["scratch_directory"] = str(scratch)
        before = snapshot()
        save(results / "source-before.json", before)
        supervisor = load_supervisor()
        env = {**os.environ, "CASEOPS_ENV": "e2e", "CASEOPS_E2E_PYTHON": sys.executable,
               "CASEOPS_IP_FIXTURE_SOURCE_ROOT": str(ROOT), "CASEOPS_IP_FIXTURE_SUPPORT_ROOT": str(SUPPORT),
               "CASEOPS_IP_FIXTURE_SCRATCH_ROOT": str(scratch), "CASEOPS_IP_FIXTURE_TEST_BACKENDS": "sqlite",
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH": os.pathsep.join((str(TESTS), str(ROOT / "apps/api/src"))),
               "TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)}
        for key in ("CASEOPS_IP_FIXTURE_TEST_POSTGRES_URL", "CASEOPS_IP_FIXTURE_TEST_POSTGRES_DATABASE"):
            env.pop(key, None)
        node = results / "process"
        node_env = {**env, "CASEOPS_IP_FIXTURE_NODE_INVENTORY": str(node / "inventory.json")}
        run_phase("process", [str(Path(args.node).absolute()), "--test", "--test-concurrency=1",
                  "--test-reporter=tap", "--test-reporter-destination=" + str(node / "results.tap"),
                  "--test-reporter=junit", "--test-reporter-destination=" + str(node / "junit.xml"),
                  str(TESTS / "run-node-tests.cjs")], node_env, node, journal, run_deadline, supervisor)
        inventory = reconcile_node(node)
        save(node / "reconciled.json", {"complete": True, "ids": inventory})
        state["phases"].append({"phase": "process", "passed": 18})
        record(journal, event="verified", phase="process", count=18)
        if snapshot() != before:
            raise ValueError("Fixture source changed before SQLite execution")
        sqlite = results / "sqlite"
        sqlite_env = {**env, "CASEOPS_IP_FIXTURE_PHASE_JOURNAL": str(sqlite / "phases.jsonl")}
        run_phase("sqlite", [sys.executable, "-B", "-m", "pytest", "-p", "fixture_test_evidence",
                  "-p", "no:cacheprovider", "--confcutdir", str(TESTS), "--rootdir", str(ROOT),
                  "--import-mode=importlib", "--basetemp", str(scratch / "pytest"),
                  "--junitxml=" + str(sqlite / "junit.xml"), "-q",
                  str(TESTS / "test_ip_entitlement_fixture.py")], sqlite_env, sqlite, journal, run_deadline, supervisor)
        inventory = reconcile_sqlite(sqlite)
        save(sqlite / "reconciled.json", {"complete": True, "ids": inventory})
        state["phases"].append({"phase": "sqlite", "passed": 51})
        record(journal, event="verified", phase="sqlite", count=51)
        state.update(complete=True, passed=True)
    except BaseException as error:
        state["error_type"] = type(error).__name__
        record(journal, event="incomplete", error_type=type(error).__name__)
    finally:
        try:
            after = snapshot()
            save(results / "source-after.json", after)
            if before is None or after != before:
                state.update(complete=False, passed=False, source_unchanged=False)
            else:
                state["source_unchanged"] = True
        except BaseException as error:
            state.update(complete=False, passed=False, source_error_type=type(error).__name__)
        save(results / "completion.json", state)
        record(journal, event="complete" if state["passed"] else "incomplete_final", passed=state["passed"])
    print(f"Fixture regression {'passed' if state['passed'] else 'incomplete/failed'}: {results}")
    return 0 if state["passed"] else 1


if __name__ == "__main__":
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupted)
    sys.exit(main())
