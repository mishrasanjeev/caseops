"""Retain bounded, privacy-minimized native Playwright release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("test-results/prod-native-evidence")
LIMIT = 64 * 1024 * 1024
SHA = re.compile(r"[a-f0-9]{40}")
INVOCATION = re.compile(r"[a-z][a-z0-9-]{0,63}")
OUTPUT_VARIABLES = (
    "PLAYWRIGHT_JSON_OUTPUT_FILE",
    "PLAYWRIGHT_JSON_OUTPUT_DIR",
    "PLAYWRIGHT_JSON_OUTPUT_NAME",
    "PLAYWRIGHT_JUNIT_OUTPUT_FILE",
    "PLAYWRIGHT_JUNIT_OUTPUT_DIR",
    "PLAYWRIGHT_JUNIT_OUTPUT_NAME",
)
REPORT_FILES = {
    "invocation.json",
    "discovery.json",
    "results.json",
    "results.xml",
    "native-discovery.json",
    "native-results.json",
    "native-results.xml",
    "progress.jsonl",
}
REPORTER = "./scripts/prod_playwright_reporter.cjs"
TESTER_PARTITIONS = {
    "tester": "tester-prod-chromium",
    "tester-catalog": "tester-prod-chromium",
    "tester-index": "tester-index-prod-chromium",
    "test-legal-write-oct13": "test-legal-write-prod-chromium",
}
# Reviewed exact inventory; any new or removed case requires an explicit update.
TESTER_PARTITION_COUNTS = {
    "tester": 98, "tester-catalog": 18, "tester-index": 6, "test-legal-write-oct13": 50,
}
TESTER_CATALOG_FILE = "ram-2026-09-05-bugs.spec.ts"
TESTER_PARTITION_CONTRACT = 1
TESTER_CANONICAL_FILES = {"canonical-native-discovery.json", "canonical-discovery.json"}
INDEX_FILES = {
    "ram-2026-10-10-prod.spec.ts": 4,
    "ram-2026-10-12-prod.spec.ts": 2,
}
OCT13_FILES = {
    "ram-2026-10-13-hearings.spec.ts": 2,
    "ram-2026-10-13-ip-portfolio.spec.ts": 4,
    "ram-2026-10-15-ip-controls.spec.ts": 34,
    "ram-2026-10-15-ip-renewal-tracker.spec.ts": 2,
    "ram-2026-10-17-calendar-readiness.spec.ts": 2,
    "ram-2026-10-17-ip-reminders.spec.ts": 4,
    "ram-2026-10-17-ip-tracker.spec.ts": 2,
}


class EvidenceError(ValueError):
    pass


def _tester_partition(binding):
    invocation = binding["invocation"]
    if binding["config"] != "playwright.prod-ram.config.ts" or invocation not in TESTER_PARTITIONS:
        return None
    if binding["project"] != TESTER_PARTITIONS[invocation]:
        raise EvidenceError("tester_partition_project_mismatch")
    if "--workers=1" not in binding["arguments"] or "--retries=0" not in binding["arguments"]:
        raise EvidenceError("tester_partition_serial_zero_retry_required")
    return invocation


def _tester_inventory(canonical):
    projects = set(TESTER_PARTITIONS.values())
    rows = [row for row in canonical["tests"] if row["project_name"] in projects]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise EvidenceError("empty_or_duplicate_tester_canonical_inventory")
    expected_counts = Counter()
    for invocation, count in TESTER_PARTITION_COUNTS.items():
        expected_counts[TESTER_PARTITIONS[invocation]] += count
    if Counter(row["project_name"] for row in rows) != expected_counts:
        raise EvidenceError("reviewed_tester_partition_counts_mismatch")
    semantic_cases = {
        (row["file"], tuple(row["title_path"]), row["repeat_each_index"])
        for row in rows
    }
    if len(semantic_cases) != len(rows):
        raise EvidenceError("duplicate_tester_semantic_identity")
    for invocation, expected_files in (
        ("tester-index", INDEX_FILES), ("test-legal-write-oct13", OCT13_FILES)
    ):
        actual = Counter(
            Path(row["file"]).name
            for row in rows
            if row["project_name"] == TESTER_PARTITIONS[invocation]
        )
        if actual != Counter(expected_files):
            raise EvidenceError("mandatory_tester_partition_inventory_mismatch")
    core = [row for row in rows if row["project_name"] == TESTER_PARTITIONS["tester"]]
    if not core or any(Path(row["file"]).name in INDEX_FILES | OCT13_FILES for row in core):
        raise EvidenceError("tester_core_partition_overlap")
    if sum(Path(row["file"]).name == TESTER_CATALOG_FILE for row in core) != (
        TESTER_PARTITION_COUNTS["tester-catalog"]
    ):
        raise EvidenceError("mandatory_tester_catalog_inventory_mismatch")
    return rows


def _tester_selected_rows(canonical, invocation):
    rows = [row for row in _tester_inventory(canonical)
            if row["project_name"] == TESTER_PARTITIONS[invocation]]
    if invocation in {"tester", "tester-catalog"}:
        rows = [row for row in rows if (Path(row["file"]).name == TESTER_CATALOG_FILE)
                == (invocation == "tester-catalog")]
    return rows


def _tester_file_filters(binding):
    invocation = _tester_partition(binding)
    if invocation not in {"tester", "tester-catalog"}:
        return []
    catalog = rf"(?:^|[/\\]){re.escape(TESTER_CATALOG_FILE)}$"
    return [catalog if invocation == "tester-catalog" else rf"^(?!.*{catalog}).*$"]


def _check_tester_selection(binding, discovery, canonical):
    invocation = _tester_partition(binding)
    if invocation is None:
        raise EvidenceError("unreviewed_tester_partition_binding")
    expected = [
        _tester_case_identity(row) for row in _tester_selected_rows(canonical, invocation)
    ]
    if [_tester_case_identity(row) for row in discovery["tests"]] != expected:
        raise EvidenceError("tester_partition_selection_mismatch")


def _tester_case_identity(row):
    return (
        row["id"], _identity(row), tuple(row["tags"]),
        row["retries"], row["repeat_each_index"],
    )


def _json(path: Path):
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise EvidenceError("missing_or_oversized_report")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError):
        raise EvidenceError("invalid_utf8_json") from None


def _write(path: Path, value) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe(value, env) -> str:
    result = str(value)
    for key, secret in env.items():
        if (
            re.search(r"PASSWORD|SECRET|TOKEN|API_KEY|COOKIE|AUTH", key, re.I)
            and len(secret) >= 4
        ):
            result = result.replace(secret, "[redacted]")
    # Annotation descriptions are evidence, not a response-body or attachment channel.
    if re.search(
        r"[{}<>]|authorization\s*:|cookie\s*:|\b(?:body|payload)\s*[:=]", result, re.I
    ):
        return "[redacted structured annotation]"
    result = re.sub(r"https?://\S+", "[url-redacted]", result)
    result = re.sub(
        r"\S*\?\S+|\bBearer\s+\S+", "[query-or-token-redacted]", result, flags=re.I
    )
    result = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[email-redacted]", result)
    return result


def _annotations(items, env):
    return [
        {
            "type": _safe(item.get("type", ""), env),
            "description": _safe(item.get("description", ""), env),
        }
        for item in items
    ]


def _inventory(document, env):
    rows = []

    def visit(suite, titles):
        titles = [*titles, suite.get("title", "")]
        for spec in suite.get("specs", []):
            for ordinal, test in enumerate(spec.get("tests", [])):
                rows.append(
                    {
                        "id": f"{spec['id']}:{test['projectId']}:{ordinal}",
                        "native_spec_id": spec["id"],
                        "file": _safe(spec["file"], env),
                        "line": spec["line"],
                        "column": spec.get("column", 0),
                        "tags": spec["tags"],
                        "title_path": [
                            _safe(title, env) for title in [*titles, spec["title"]]
                        ],
                        "project_id": test["projectId"],
                        "project_name": test["projectName"],
                        "expected_status": test.get("expectedStatus"),
                        "status": test.get("status"),
                        "timeout": test["timeout"],
                        "retries": test["retries"],
                        "repeat_each_index": test["repeatEachIndex"],
                        "annotations": _annotations(test.get("annotations", []), env),
                        "results": [
                            {
                                "status": result["status"],
                                "retry": result["retry"],
                                "duration": result.get("duration", 0),
                                "worker_index": result.get("workerIndex"),
                                "parallel_index": result.get("parallelIndex"),
                                "start_time": result.get("startTime"),
                                "error_count": len(result.get("errors", [])),
                                "network_evidence": result.get(
                                    "networkEvidence", {"status": "absent"}
                                ),
                                "annotations": _annotations(
                                    result.get("annotations", []), env
                                ),
                            }
                            for result in test.get("results", [])
                        ],
                    }
                )
        for child in suite.get("suites", []):
            visit(child, titles)

    for suite in document.get("suites", []):
        visit(suite, [])
    ids = [row["id"] for row in rows]
    if not ids or len(set(ids)) != len(ids):
        raise EvidenceError("empty_or_duplicate_inventory")
    return rows


def _native(path, binding, env, phase):
    document = _json(path)
    if (
        document.get("release_sha") != binding["release_sha"]
        or document.get("invocation") != binding["invocation"]
        or document.get("phase") != phase
    ):
        raise EvidenceError("native_invocation_binding_mismatch")
    config = document["config"]
    if Path(config["configFile"]).resolve() != Path(binding["config_path"]).resolve():
        raise EvidenceError("native_config_mismatch")
    root = Path(binding["config_path"]).parent.resolve()
    for directory in [config["rootDir"], *[p["testDir"] for p in config["projects"]]]:
        if not Path(directory).resolve().is_relative_to(root):
            raise EvidenceError("native_test_directory_outside_checkout")
    projects = [
        {
            **{
                key: p[key]
                for key in ("id", "name", "retries", "repeatEach", "timeout")
            },
            "test_directory": Path(p["testDir"]).resolve().relative_to(root).as_posix(),
        }
        for p in config["projects"]
    ]
    options = dict(argument[2:].split("=", 1) for argument in binding["arguments"])
    if (
        type(config["workers"]) is not int
        or config["workers"] <= 0
        or ("workers" in options and config["workers"] != int(options["workers"]))
        or ("retries" in options and options["retries"] != "0")
        or len({(p["id"], p["name"]) for p in projects}) != len(projects)
        or any(
            type(p["retries"]) is not int
            or p["retries"] != 0
            or type(p["repeatEach"]) is not int
            or p["repeatEach"] != 1
            for p in projects
        )
    ):
        raise EvidenceError("native_zero_retry_configuration_mismatch")
    rows = _inventory(document, env)
    for row in rows:
        source = (Path(config["rootDir"]) / row["file"]).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise EvidenceError("native_spec_outside_or_missing_from_checkout")
    requested = binding["project"]
    if requested and requested not in {row["project_name"] for row in rows}:
        raise EvidenceError("native_project_mismatch")
    if any(
        (row["project_id"], row["project_name"])
        not in {(p["id"], p["name"]) for p in projects}
        for row in rows
    ):
        raise EvidenceError("undeclared_native_project")
    for row in rows:
        if (
            type(row["retries"]) is not int
            or row["retries"] != 0
            or type(row["repeat_each_index"]) is not int
            or row["repeat_each_index"] != 0
            or type(row["line"]) is not int
            or row["line"] < 1
            or type(row["column"]) is not int
            or row["column"] < 1
            or not all(isinstance(title, str) for title in row["title_path"])
            or not isinstance(row["tags"], list)
            or not all(isinstance(tag, str) for tag in row["tags"])
        ):
            raise EvidenceError("native_case_metadata_mismatch")
    stats = {
        key: document["stats"][key]
        for key in (
            "startTime",
            "duration",
            "expected",
            "skipped",
            "unexpected",
            "flaky",
        )
    }
    if sum(stats[key] for key in ("expected", "skipped", "unexpected", "flaky")) != len(
        rows
    ):
        raise EvidenceError("native_stats_inventory_mismatch")
    if Counter(row["status"] for row in rows) != Counter(
        {key: stats[key] for key in ("expected", "skipped", "unexpected", "flaky")}
    ):
        raise EvidenceError("native_stats_outcome_mismatch")
    return {
        "binding": binding,
        "projects": projects,
        "configuration": {
            "workers": config["workers"],
            "root_directory": Path(config["rootDir"])
            .resolve()
            .relative_to(root)
            .as_posix(),
        },
        "tests": rows,
        "stats": stats,
        "global_error_count": len(document.get("errors", [])),
        "report_status": document["status"],
    }


def _identity(row):
    return (
        row["native_spec_id"],
        row["project_id"],
        row["project_name"],
        row["file"],
        row["line"],
        row["column"],
        tuple(row["title_path"]),
    )


def _progress(path: Path, binding, result, env, native_errors) -> None:
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise EvidenceError("missing_or_oversized_progress")
    try:
        content = path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in content.splitlines()]
    except (UnicodeError, ValueError):
        raise EvidenceError("invalid_progress_json") from None
    if not content.endswith("\n") or len(rows) < 2:
        raise EvidenceError("incomplete_progress")
    if not all(isinstance(row, dict) for row in rows):
        raise EvidenceError("progress_event_schema_mismatch")
    started, completion = rows[0], rows[-1]
    if (
        set(started) != {"event", "release_sha", "invocation"}
        or started["event"] != "invocation_started"
        or started["release_sha"] != binding["release_sha"]
        or started["invocation"] != binding["invocation"]
        or set(completion) != {"event", "status", "test_count"}
        or completion["event"] != "session_finished"
        or completion["status"] != result["report_status"]
        or type(completion["test_count"]) is not int
        or completion["test_count"] != len(result["tests"])
    ):
        raise EvidenceError("progress_binding_or_completion_mismatch")
    collections = [row for row in rows[1:-1] if row.get("event") == "collection"]
    if len(collections) != 1:
        raise EvidenceError("progress_collection_mismatch")
    collection = collections[0]
    if (
        set(collection) != {"event", "release_sha", "invocation", "suites"}
        or collection["release_sha"] != binding["release_sha"]
        or collection["invocation"] != binding["invocation"]
    ):
        raise EvidenceError("progress_collection_mismatch")
    collected = _inventory(collection, env)

    def identity(row):
        return (_identity(row), row["tags"], row["retries"], row["repeat_each_index"])

    if [identity(row) for row in collected] != [
        identity(row) for row in result["tests"]
    ] or any(row["results"] for row in collected):
        raise EvidenceError("progress_collection_mismatch")
    expected = {row["id"]: row for row in result["tests"]}
    observed = set()
    errors = []
    collection_seen = False
    for packet in rows[1:-1]:
        if packet.get("event") == "collection":
            collection_seen = True
            continue
        if packet.get("event") == "global_error":
            if set(packet) != {"event", "error"}:
                raise EvidenceError("progress_event_schema_mismatch")
            errors.append(packet["error"])
            continue
        if (
            not collection_seen
            or set(packet) != {"event", "suites"}
            or packet["event"] != "test_end"
        ):
            raise EvidenceError("progress_event_schema_mismatch")
        attempts = _inventory(packet, env)
        if len(attempts) != 1:
            raise EvidenceError("progress_attempt_inventory_mismatch")
        row = attempts[0]
        if row["id"] in observed or row != expected.get(row["id"]):
            raise EvidenceError("progress_attempt_mismatch")
        observed.add(row["id"])
    if (
        observed != set(expected)
        or len(errors) != result["global_error_count"]
        or errors != native_errors
    ):
        raise EvidenceError("progress_missing_attempt_or_error")


def _reconcile(discovery, result):
    if (
        discovery["projects"] != result["projects"]
        or discovery["configuration"] != result["configuration"]
        or [
            (r["id"], _identity(r), r["tags"], r["retries"], r["repeat_each_index"])
            for r in discovery["tests"]
        ]
        != [
            (r["id"], _identity(r), r["tags"], r["retries"], r["repeat_each_index"])
            for r in result["tests"]
        ]
    ):
        raise EvidenceError("runtime_inventory_mismatch")
    for row in result["tests"]:
        attempts = row["results"]
        if (
            len(attempts) != 1
            or type(attempts[0]["retry"]) is not int
            or attempts[0]["retry"] != 0
        ):
            raise EvidenceError("native_zero_retry_attempt_mismatch")
        actual = attempts[0]["status"]
        if row["expected_status"] not in {"passed", "failed", "timedOut", "skipped"}:
            raise EvidenceError("native_expected_status_mismatch")
        outcome = (
            "skipped"
            if actual == "skipped"
            else ("expected" if actual == row["expected_status"] else "unexpected")
        )
        if actual != "interrupted" and row["status"] != outcome:
            raise EvidenceError("native_case_outcome_mismatch")


def _junit(raw: Path, output: Path | None, env, result):
    if not raw.is_file() or raw.stat().st_size > LIMIT:
        raise EvidenceError("missing_or_oversized_junit")
    try:
        tree = ET.parse(raw)
    except ET.ParseError:
        raise EvidenceError("invalid_junit") from None
    cases = list(tree.iter("testcase"))
    if len(cases) != len(result["tests"]):
        raise EvidenceError("junit_inventory_mismatch")
    if len(list(tree.iter("skipped"))) != result["stats"]["skipped"]:
        raise EvidenceError("junit_skipped_mismatch")
    if (
        len(list(tree.iter("failure"))) + len(list(tree.iter("error")))
        != result["stats"]["unexpected"]
    ):
        raise EvidenceError("junit_failed_mismatch")
    actual = []
    root = tree.getroot()
    if root.tag != "testsuites" or any(s.tag != "testsuite" for s in root):
        raise EvidenceError("junit_structure_mismatch")
    for suite in root:
        native_cases = suite.findall("testcase")
        if len(native_cases) != 1:
            raise EvidenceError("junit_structure_mismatch")
        case = native_cases[0]
        try:
            titles = json.loads(case.attrib["caseops-title-path"])
            if (
                not isinstance(titles, list)
                or len(titles) < 2
                or not all(isinstance(title, str) for title in titles)
            ):
                raise ValueError
            line, column = int(case.attrib["line"]), int(case.attrib["column"])
            identity = (
                case.attrib["caseops-id"],
                case.attrib["caseops-project-id"],
                case.attrib["caseops-project-name"],
                case.attrib["file"],
                line,
                column,
                tuple(titles),
            )
            outcome = case.attrib["caseops-outcome"]
        except (KeyError, ValueError, TypeError):
            raise EvidenceError("junit_identity_mismatch") from None
        if (
            case.get("line") != str(line)
            or case.get("column") != str(column)
            or case.get("name") != " \u203a ".join(titles[1:])
            or case.get("classname") != titles[0]
            or suite.get("name") != titles[0]
            or suite.get("hostname") != identity[2]
            or suite.get("tests") != "1"
            or suite.get("errors") != "0"
            or suite.get("failures") != str(int(outcome == "unexpected"))
            or suite.get("skipped") != str(int(outcome == "skipped"))
            or len(case.findall("failure")) != int(outcome == "unexpected")
            or len(case.findall("skipped")) != int(outcome == "skipped")
            or case.findall("error")
            or outcome not in {"expected", "skipped", "unexpected", "flaky"}
        ):
            raise EvidenceError("junit_case_outcome_or_display_mismatch")
        actual.append((identity, outcome))
    # Multiplicity is part of the proof: never deduplicate or match joined titles.
    if Counter(actual) != Counter(
        (_identity(row), row["status"]) for row in result["tests"]
    ):
        raise EvidenceError("junit_identity_outcome_mismatch")
    if output is None:
        return
    # Native XML structure/outcomes survive; body/error/output/attachment data do not.
    for element in tree.iter():
        element.attrib = {
            key: value
            if element.tag == "testcase" and key == "caseops-title-path"
            else _safe(value, env)
            for key, value in element.attrib.items()
            if key
            in {
                "name",
                "classname",
                "file",
                "time",
                "tests",
                "failures",
                "errors",
                "skipped",
                "timestamp",
                "type",
                "value",
                "hostname",
                "line",
                "column",
                "caseops-id",
                "caseops-project-id",
                "caseops-project-name",
                "caseops-title-path",
                "caseops-outcome",
            }
            or (element.tag == "skipped" and key == "message")
        }
        if element.tag in {"failure", "error"}:
            element.text = "Native test failure; private detail omitted."
        elif element.tag == "skipped":
            element.text = _safe(element.text or "", env)
        else:
            element.text = None
        element.tail = None
        for child in list(element):
            if child.tag not in {
                "testsuite",
                "testcase",
                "properties",
                "property",
                "skipped",
                "failure",
                "error",
            }:
                element.remove(child)
    with output.open("xb") as stream:
        tree.write(stream, encoding="utf-8", xml_declaration=True)


def _binding(root, invocation, args, env):
    expected = env.get("CASEOPS_EXPECTED_RELEASE_SHA", "")
    if not SHA.fullmatch(expected) or not INVOCATION.fullmatch(invocation):
        raise EvidenceError("invalid_release_or_invocation")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != expected:
        raise EvidenceError("checkout_sha_mismatch")
    options = {}
    for argument in args:
        if not re.fullmatch(
            r"--(config|project|workers|retries|reporter|output)=[\w./-]+", argument
        ):
            raise EvidenceError("unreviewed_invocation_argument")
        key, value = argument[2:].split("=", 1)
        if key in options:
            raise EvidenceError("duplicate_invocation_option")
        options[key] = value
    if "config" not in options or "output" not in options:
        raise EvidenceError("missing_invocation_option")
    config = root / options["config"]
    if not config.resolve().is_relative_to(root.resolve()) or not config.is_file():
        raise EvidenceError("missing_release_config")
    if options.get("reporter") != "list":
        raise EvidenceError("unreviewed_reporter")
    return {
        "release_sha": expected,
        "checkout_sha": head,
        "invocation": invocation,
        "config": options["config"],
        "config_path": str(config.resolve()),
        "config_sha256": _hash(config),
        "project": options.get("project"),
        "arguments": args,
        "capture_version": 2,
    }


def run(root: Path, invocation: str, args, env=None, launch=subprocess.run) -> int:
    env = dict(os.environ if env is None else env)
    binding = _binding(root, invocation, args, env)
    destination = root / EVIDENCE / invocation
    destination.mkdir(parents=True, exist_ok=False)
    # Absolute host paths are checked internally, but never archived.
    public_binding = {
        key: value for key, value in binding.items() if key != "config_path"
    }
    _write(
        destination / "invocation.json",
        {
            "binding": public_binding,
            "source_owned_file_filters": _tester_file_filters(binding),
            "invocation_id": str(uuid4()),
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    marker = {
        "binding": public_binding,
        "phase": "discovery",
        "discovery_exit": None,
        "execution_exit": None,
        "completed": False,
    }
    code = 1
    try:
        cli = root / "node_modules/@playwright/test/cli.js"
        node = shutil.which("node")
        if not node or not cli.is_file() or not (root / REPORTER).is_file():
            raise EvidenceError("missing_release_playwright_cli")
        child_env = {
            key: value for key, value in env.items() if key not in OUTPUT_VARIABLES
        }
        child_env["CASEOPS_PW_EVIDENCE_JSON_FILE"] = str(
            destination / "native-discovery.json"
        )
        child_env["CASEOPS_PW_EVIDENCE_INVOCATION"] = invocation
        child_env["CASEOPS_PW_EVIDENCE_PHASE"] = "discovery"
        discovery_args = [arg for arg in args if not arg.startswith("--reporter=")]
        selected_args = [*discovery_args, *_tester_file_filters(binding)]
        process = launch(
            [
                node,
                str(cli),
                "test",
                *selected_args,
                "--list",
                f"--reporter={REPORTER}",
            ],
            cwd=root,
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        marker["discovery_exit"] = process.returncode
        if process.returncode:
            raise EvidenceError("discovery_process_failed")
        discovery = _native(
            destination / "native-discovery.json", binding, env, "discovery"
        )
        if (
            discovery["global_error_count"]
            or any(
                discovery["stats"][key] for key in ("expected", "unexpected", "flaky")
            )
            or any(row["results"] for row in discovery["tests"])
        ):
            raise EvidenceError("discovery_executed_tests")
        discovery["binding"] = public_binding
        _write(destination / "discovery.json", discovery)
        partition = _tester_partition(binding)
        if partition is not None:
            canonical_invocation = f"{invocation}-canonical"
            canonical_directory = root / EVIDENCE / canonical_invocation
            canonical_directory.mkdir(parents=True, exist_ok=False)
            canonical_args = [arg for arg in discovery_args if not arg.startswith("--project=")]
            canonical_binding = {
                **binding,
                "invocation": canonical_invocation,
                "project": None,
                "arguments": [arg for arg in args if not arg.startswith("--project=")],
            }
            canonical_env = {
                **child_env,
                "CASEOPS_PW_EVIDENCE_INVOCATION": canonical_invocation,
                "CASEOPS_PW_EVIDENCE_JSON_FILE": str(canonical_directory / "native-discovery.json"),
            }
            process = launch(
                [node, str(cli), "test", *canonical_args, "--list", f"--reporter={REPORTER}"],
                cwd=root,
                env=canonical_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            marker["canonical_discovery_exit"] = process.returncode
            if process.returncode:
                raise EvidenceError("canonical_tester_discovery_failed")
            canonical_path = canonical_directory / "native-discovery.json"
            canonical = _native(canonical_path, canonical_binding, env, "discovery")
            if canonical["global_error_count"] or any(row["results"] for row in canonical["tests"]):
                raise EvidenceError("canonical_tester_discovery_executed_tests")
            canonical["binding"] = {
                key: value for key, value in canonical_binding.items() if key != "config_path"
            }
            _check_tester_selection(binding, discovery, canonical)
            with (destination / "canonical-native-discovery.json").open("xb") as stream:
                stream.write(canonical_path.read_bytes())
            _write(destination / "canonical-discovery.json", canonical)
            canonical_path.unlink()
            canonical_directory.rmdir()
        marker["phase"] = "execution"
        child_env["CASEOPS_PW_EVIDENCE_JSON_FILE"] = str(
            destination / "native-results.json"
        )
        child_env["CASEOPS_PW_EVIDENCE_JUNIT_FILE"] = str(
            destination / "native-results.xml"
        )
        child_env["CASEOPS_PW_EVIDENCE_PHASE"] = "execution"
        effective = [
            f"--reporter=list,{REPORTER}" if arg == "--reporter=list" else arg
            for arg in args
        ]
        effective.extend(_tester_file_filters(binding))
        process = launch(
            [node, str(cli), "test", *effective],
            cwd=root,
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        marker["execution_exit"] = process.returncode
        result = _native(destination / "native-results.json", binding, env, "execution")
        result["binding"] = public_binding
        _write(destination / "results.json", result)
        _reconcile(discovery, result)
        if (
            process.returncode < 0
            or result["report_status"] == "interrupted"
            or any(
                r["status"] == "interrupted"
                for row in result["tests"]
                for r in row["results"]
            )
        ):
            raise EvidenceError("interrupted_execution")
        if any(
            not row["results"]
            or any(
                r["status"]
                not in {
                    "passed",
                    "failed",
                    "timedOut",
                    "skipped",
                }
                for r in row["results"]
            )
            for row in result["tests"]
        ):
            raise EvidenceError("missing_or_invalid_runtime_result")
        _junit(
            destination / "native-results.xml", destination / "results.xml", env, result
        )
        _progress(
            destination / "progress.jsonl",
            binding,
            result,
            env,
            _json(destination / "native-results.json").get("errors", []),
        )
        if _hash(root / binding["config"]) != binding["config_sha256"]:
            raise EvidenceError("config_changed_during_execution")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if head != binding["checkout_sha"]:
            raise EvidenceError("checkout_changed_during_execution")
        marker["phase"] = "complete"
        marker["completed"] = True
        code = process.returncode
        if (
            result["report_status"] != "passed"
            or result["global_error_count"]
            or any(row["status"] == "unexpected" for row in result["tests"])
        ):
            code = code or 1
        _write(
            destination / "completion.json",
            {
                **marker,
                "finished_at": datetime.now(UTC).isoformat(),
                "test_count": len(result["tests"]),
                "sha256": {
                    name: _hash(destination / name)
                    for name in sorted(
                        REPORT_FILES | (TESTER_CANONICAL_FILES if partition is not None else set())
                    )
                },
            },
        )
    except (
        EvidenceError,
        KeyError,
        TypeError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        marker["incomplete_reason"] = (
            str(error) if isinstance(error, EvidenceError) else type(error).__name__
        )
    finally:
        _write(
            destination / "exit.json",
            {
                **marker,
                "wrapper_exit": code,
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
        print(
            json.dumps(
                {
                    "invocation": invocation,
                    "release_sha": binding["release_sha"],
                    "completed": marker["completed"],
                    "exit": code,
                }
            )
        )
    return code


def validate(root: Path, required, expected: str) -> None:
    if not SHA.fullmatch(expected) or not required:
        raise EvidenceError("empty_validation_scope")
    for invocation in required:
        if not INVOCATION.fullmatch(invocation):
            raise EvidenceError("invalid_validation_invocation")
        directory = root / EVIDENCE / invocation
        completion = _json(directory / "completion.json")
        exit_marker = _json(directory / "exit.json")
        if not completion["completed"] or not exit_marker["completed"]:
            raise EvidenceError("incomplete_invocation")
        binding = completion["binding"]
        partition = _tester_partition(binding)
        report_files = REPORT_FILES | (TESTER_CANONICAL_FILES if partition is not None else set())
        if (
            binding["release_sha"] != expected
            or binding["checkout_sha"] != expected
            or binding["invocation"] != invocation
            or exit_marker["binding"] != binding
        ):
            raise EvidenceError("completion_release_mismatch")
        if exit_marker["wrapper_exit"] or completion["execution_exit"]:
            raise EvidenceError("failed_invocation")
        for name, digest in completion["sha256"].items():
            if name not in report_files:
                raise EvidenceError("unreviewed_evidence_file")
            if _hash(directory / name) != digest:
                raise EvidenceError("evidence_hash_mismatch")
        if set(completion["sha256"]) != report_files:
            raise EvidenceError("missing_required_evidence")
        for name in ("invocation.json", "discovery.json", "results.json"):
            if _json(directory / name)["binding"] != binding:
                raise EvidenceError("evidence_binding_mismatch")
        discovery = _json(directory / "discovery.json")
        result = _json(directory / "results.json")
        if partition is not None:
            canonical = _json(directory / "canonical-discovery.json")
            canonical_binding = canonical["binding"]
            if (
                canonical_binding != {
                    **binding,
                    "invocation": f"{invocation}-canonical",
                    "project": None,
                    "arguments": [
                        arg for arg in binding["arguments"] if not arg.startswith("--project=")
                    ],
                }
                or canonical["global_error_count"]
                or any(row["results"] for row in canonical["tests"])
            ):
                raise EvidenceError("canonical_tester_binding_mismatch")
            _check_tester_selection(binding, discovery, canonical)
        if (
            completion["test_count"] <= 0
            or len(result["tests"]) != completion["test_count"]
            or [r["id"] for r in discovery["tests"]]
            != [r["id"] for r in result["tests"]]
        ):
            raise EvidenceError("completion_inventory_mismatch")
        _reconcile(discovery, result)
        _junit(directory / "native-results.xml", None, {}, result)
        _junit(directory / "results.xml", None, {}, result)
        _progress(
            directory / "progress.jsonl",
            binding,
            result,
            {},
            _json(directory / "native-results.json").get("errors", []),
        )


def validate_tester_partition_union(root: Path, required, expected: str) -> None:
    if len(required) != len(TESTER_PARTITIONS) or set(required) != set(TESTER_PARTITIONS):
        raise EvidenceError("missing_or_duplicate_tester_partition")
    validate(root, required, expected)
    selected = []
    canonical_ids = None
    config_hash = None
    for invocation in TESTER_PARTITIONS:
        directory = root / EVIDENCE / invocation
        result = _json(directory / "results.json")
        binding = result["binding"]
        if _tester_partition(binding) != invocation:
            raise EvidenceError("unreviewed_tester_partition_binding")
        digest = binding["config_sha256"]
        if _hash(root / binding["config"]) != digest or (config_hash and config_hash != digest):
            raise EvidenceError("tester_partition_source_mismatch")
        config_hash = digest
        canonical = _tester_inventory(_json(directory / "canonical-discovery.json"))
        identities = [_tester_case_identity(row) for row in canonical]
        if canonical_ids is not None and canonical_ids != identities:
            raise EvidenceError("tester_canonical_inventories_disagree")
        canonical_ids = identities
        if invocation != "tester" and any(
            len(row["results"]) != 1 or row["results"][0]["status"] != "passed"
            or row["results"][0]["retry"] != 0 or row["status"] != "expected"
            for row in result["tests"]
        ):
            raise EvidenceError("mandatory_tester_partition_not_passed")
        selected.extend(_tester_case_identity(row) for row in result["tests"])
    if len(set(selected)) != len(selected) or Counter(selected) != Counter(canonical_ids):
        raise EvidenceError("tester_partition_union_mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    runner = modes.add_parser("run")
    runner.add_argument("--invocation", required=True)
    runner.add_argument("arguments", nargs=argparse.REMAINDER)
    validator = modes.add_parser("validate")
    validator.add_argument("--required", nargs="+", required=True)
    validator.add_argument("--tester-partition-union", action="store_true")
    modes.add_parser("tester-partition-contract")
    options = parser.parse_args()
    try:
        if options.mode == "tester-partition-contract":
            print(json.dumps({"tester_partition_contract": TESTER_PARTITION_CONTRACT,
                              "partitions": TESTER_PARTITION_COUNTS,
                              "catalog_file": TESTER_CATALOG_FILE}))
            return 0
        if options.mode == "validate":
            validation = (
                validate_tester_partition_union if options.tester_partition_union else validate
            )
            validation(
                ROOT,
                options.required,
                os.environ.get("CASEOPS_EXPECTED_RELEASE_SHA", ""),
            )
            return 0
        arguments = options.arguments
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        return run(ROOT, options.invocation, arguments)
    except (
        EvidenceError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {
                    "completed": False,
                    "reason": str(error)
                    if isinstance(error, EvidenceError)
                    else type(error).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
