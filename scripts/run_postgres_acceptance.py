"""Run the full native inventory in fresh, serial, whole-file pytest processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

SHARDS = 8
MAX_BYTES = 256 * 1024 * 1024
MAX_LINE = 16 * 1024 * 1024


def save(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


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
        if relative.is_absolute() or any(
            part in {".", ".."} for part in relative.parts
        ):
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
    if (
        rows[1].get("event") != "collection"
        or type(rows[-1].get("exitstatus")) is not int
    ):
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
        selected = [
            identity for identity in identities if module_path(identity) in assigned
        ]
        files = list(dict.fromkeys(module_path(identity) for identity in selected))
        groups.append({"shard": index, "files": files, "nodeids": selected})
    return groups


def execute(api: Path, folder: Path, arguments: list[str]) -> int:
    env = dict(os.environ, CASEOPS_TEST_RESULT_JOURNAL=str(folder / "results.jsonl"))
    env.pop("CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID", None)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-m",
        "postgres",
        "--basetemp=" + str(folder / "fixtures"),
        *arguments,
    ]
    save(
        folder / "started.json",
        {"command": command, "started_at": datetime.now(UTC).isoformat()},
    )
    with (
        (folder / "stdout.txt").open("xb") as stdout,
        (folder / "stderr.txt").open("xb") as stderr,
    ):
        process = subprocess.Popen(
            command, cwd=api, env=env, stdout=stdout, stderr=stderr
        )
        try:
            code = process.wait()
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            save(
                folder / "interrupted.json",
                {"natural_completion": False, "reaped": True},
            )
            raise
    save(
        folder / "process-completion.json",
        {
            "exit_code": code,
            "completed_at": datetime.now(UTC).isoformat(),
            "natural_completion": True,
            "pid": process.pid,
            "reaped": True,
        },
    )
    return code


def reconcile(folder: Path, expected: list[str], code: int) -> tuple[dict, ET.Element]:
    result = journal(folder / "results.jsonl")
    if result["nodeids"] != expected:
        raise ValueError("Child ordered collection differs from canonical subset")
    if code not in (0, 1) or type(result["exit"]) is not int or result["exit"] != code:
        raise ValueError(
            "Child process and journal completion disagree or are incomplete"
        )
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
        required = (
            ["setup", "teardown"] if setup_failed else ["setup", "call", "teardown"]
        )
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
        child.tag not in {"testcase", "properties", "system-out", "system-err"}
        for child in suite
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
        problems = [
            child.tag for child in case if child.tag in {"skipped", "failure", "error"}
        ]
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


def run(api: Path, output: Path) -> int:
    api, output = api.resolve(), output.resolve()
    root = api.parent.parent
    if os.environ.get("PYTEST_ADDOPTS", "").strip():
        raise ValueError(
            "Native acceptance cannot inherit pytest selection or retry options"
        )
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
    code = execute(api, collection, ["--collect-only"])
    unchanged()
    if code:
        raise ValueError(
            "Canonical PostgreSQL collection did not complete successfully"
        )
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
            api, folder, ["--junitxml=" + str(folder / "results.xml"), *group["files"]]
        )
        unchanged()
        try:
            result, suite = reconcile(folder, group["nodeids"], code)
            results[group["shard"]] = result
            suites.append(suite)
            if code:
                faults.append(
                    {"shard": group["shard"], "kind": "complete_test_failure"}
                )
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
        raise ValueError(
            "Native evidence incomplete; all available child evidence retained"
        )
    seen = [
        identity for group in groups for identity in results[group["shard"]]["nodeids"]
    ]
    if Counter(seen) != Counter(identities):
        raise ValueError(
            "Native child union does not equal canonical collection exactly once"
        )
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
        stream.write(
            json.dumps({"event": "session_finished", "exitstatus": exit_code}) + "\n"
        )
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
    args = parser.parse_args()
    if args.api_dir.resolve() != Path(__file__).resolve().parent.parent / "apps/api":
        parser.error("Native driver must use its own candidate API checkout")
    try:
        return run(args.api_dir, args.results_directory)
    except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as exc:
        print(f"[native-acceptance] NO-GO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
