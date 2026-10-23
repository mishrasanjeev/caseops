from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
BASE = "99297e17b00dd51178e21baf596ba2ebfd92c5f7"
# Pinned from the exact base's native workflow, not from the changed manifest.
# Ordinary CI shards are shallow checkouts; regressions must not fetch history.
BASE_COMMANDS = {
    "Run canonical tester production regressions": (
        "--config=playwright.prod-ram.config.ts --project=tester-prod-chromium "
        "--workers=1 --retries=0 --reporter=list --output=test-results/tester"
    ),
    "Run legacy QA production regressions": (
        "--config=playwright.prod-ram.config.ts --project=prod-chromium "
        "--workers=1 --retries=0 --reporter=list --output=test-results/legacy"
    ),
    "Run test-legal read-only hearing acceptance": (
        "--config=playwright.prod-ram.config.ts --project=test-legal-readonly-prod-chromium "
        "--workers=1 --retries=0 --reporter=list --output=test-results/test-legal-readonly"
    ),
    "Run IPLF-027B A0 quiescence acceptance": (
        "--config=playwright.ip-a0-prod.config.ts --reporter=list --output=test-results/ip-a0"
    ),
    "Run IPLF-037B renewal acceptance": (
        "--config=playwright.ip-renewal-prod.config.ts --reporter=list "
        "--output=test-results/ip-renewal"
    ),
    "Run IPLF-039F cost acceptance": (
        "--config=playwright.ip-cost-prod.config.ts --reporter=list --output=test-results/ip-cost"
    ),
    "Run prod-Playwright suite (notice module)": (
        "--config=playwright.notice-prod.config.ts --reporter=list --output=test-results/notice"
    ),
    "Run exact-release patent and domain journeys": (
        "--config=playwright.prod-ram.config.ts --project=patent-prod-chromium "
        "--workers=1 --retries=0 --reporter=list --output=test-results/patent"
    ),
    "Verify every release-owned statute source record": (
        "--config=playwright.prod-ram.config.ts --project=statute-source-prod-chromium "
        "--workers=4 --retries=0 --reporter=list --output=test-results/statute-sources"
    ),
}
SPEC = importlib.util.spec_from_file_location(
    "prod_native_evidence", ROOT / "scripts/prod_playwright_evidence.py"
)
assert SPEC and SPEC.loader
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


@pytest.fixture
def capture(tmp_path, monkeypatch):
    config = tmp_path / "playwright.offline.config.ts"
    config.write_text("// deterministic offline contract\n", encoding="utf-8")
    (tmp_path / "offline.spec.ts").touch()
    cli = tmp_path / "node_modules/@playwright/test/cli.js"
    cli.parent.mkdir(parents=True)
    cli.touch()
    reporter = tmp_path / evidence.REPORTER
    reporter.parent.mkdir()
    reporter.touch()
    node = shutil.which("node")
    monkeypatch.setattr(evidence.shutil, "which", lambda _: "offline-node")
    monkeypatch.setattr(evidence.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=BASE))
    env = {
        "CASEOPS_EXPECTED_RELEASE_SHA": BASE,
        "CASEOPS_QA_PASSWORD": "private-test-password",
        "PLAYWRIGHT_JSON_OUTPUT_DIR": "must-not-be-used",
        "PLAYWRIGHT_JUNIT_OUTPUT_NAME": "must-not-be-used.xml",
    }
    args = [
        "--config=playwright.offline.config.ts",
        "--project=offline",
        "--workers=1",
        "--retries=0",
        "--reporter=list",
        "--output=test-results/offline",
    ]
    report = {
        "config": {
            "configFile": str(config),
            "rootDir": str(tmp_path),
            "workers": 1,
            "projects": [
                {
                    "id": "offline",
                    "name": "offline",
                    "testDir": str(tmp_path),
                    "retries": 0,
                    "repeatEach": 1,
                    "timeout": 30000,
                },
            ],
        },
        "suites": [
            {
                "title": "offline.spec.ts",
                "specs": [
                    {
                        "id": "native-id",
                        "file": "offline.spec.ts",
                        "line": 5,
                        "column": 1,
                        "tags": [],
                        "title": "Unicode \u00a7 \u0939\u093f\u0902\u0926\u0940",
                        "tests": [
                            {
                                "projectId": "offline",
                                "projectName": "offline",
                                "timeout": 30000,
                                "retries": 0,
                                "repeatEachIndex": 0,
                                "annotations": [],
                                "expectedStatus": "passed",
                                "status": "skipped",
                                "results": [],
                            }
                        ],
                    }
                ],
            }
        ],
        "errors": [],
        "stats": {
            "startTime": "2026-10-09T00:00:00Z",
            "duration": 1,
            "expected": 0,
            "skipped": 1,
            "unexpected": 0,
            "flaky": 0,
        },
    }
    runtime = copy.deepcopy(report)
    test = runtime["suites"][0]["specs"][0]["tests"][0]
    test["status"] = "expected"
    test["results"] = [
        {
            "status": "passed",
            "duration": 1,
            "retry": 0,
            "errors": [{"message": "Redacted native test error"}],
            "annotations": [],
        }
    ]
    runtime["stats"].update(expected=1, skipped=0)
    state = SimpleNamespace(
        root=tmp_path,
        env=env,
        args=args,
        discovery=report,
        runtime=runtime,
        calls=[],
        discovery_exit=0,
        execution_exit=0,
        missing=None,
        junit_count=1,
        mutate_xml=None,
        node=node,
    )

    def launch(command, **kwargs):
        state.calls.append((command, kwargs))
        listing = "--list" in command
        invocation = kwargs["env"]["CASEOPS_PW_EVIDENCE_INVOCATION"]
        doc = copy.deepcopy(state.discovery if listing else state.runtime)
        doc.update(
            release_sha=BASE,
            invocation=invocation,
            phase="discovery" if listing else "execution",
            status=doc.get("status", "passed"),
        )
        for suite in doc["suites"]:
            for spec in suite.get("specs", []):
                for native_test in spec["tests"]:
                    native_test["annotations"] = evidence._annotations(
                        native_test["annotations"], env
                    )
                    for result in native_test["results"]:
                        result["annotations"] = evidence._annotations(
                            result.get("annotations", []), env
                        )
        key = "discovery" if listing else "json"
        if state.missing != key:
            Path(kwargs["env"]["CASEOPS_PW_EVIDENCE_JSON_FILE"]).write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8"
            )
        if not listing and state.missing != "junit":
            xml = ET.Element("testsuites")
            rows = evidence._inventory(doc, env)
            for row in rows[: state.junit_count]:
                suite = ET.SubElement(
                    xml,
                    "testsuite",
                    name=row["title_path"][0],
                    hostname=row["project_name"],
                    tests="1",
                    errors="0",
                    failures=str(int(row["status"] == "unexpected")),
                    skipped=str(int(row["status"] == "skipped")),
                )
                case = ET.SubElement(
                    suite,
                    "testcase",
                    {
                        "name": " \u203a ".join(row["title_path"][1:]),
                        "classname": row["title_path"][0],
                        "file": row["file"],
                        "line": str(row["line"]),
                        "column": str(row["column"]),
                        "caseops-id": row["native_spec_id"],
                        "caseops-project-id": row["project_id"],
                        "caseops-project-name": row["project_name"],
                        "caseops-title-path": json.dumps(row["title_path"], ensure_ascii=False),
                        "caseops-outcome": row["status"],
                    },
                )
                properties = ET.SubElement(case, "properties")
                for annotation in row["annotations"]:
                    ET.SubElement(
                        properties,
                        "property",
                        name=annotation["type"],
                        value=annotation.get("description", ""),
                    )
                if row["status"] == "skipped":
                    ET.SubElement(case, "skipped")
                if row["status"] == "unexpected":
                    ET.SubElement(
                        case, "failure", message="Redacted native test error"
                    ).text = "Native test failure; private detail omitted."
            if state.mutate_xml:
                state.mutate_xml(xml)
            ET.ElementTree(xml).write(
                kwargs["env"]["CASEOPS_PW_EVIDENCE_JUNIT_FILE"], encoding="utf-8"
            )
        if not listing and state.missing != "progress":
            collection = copy.deepcopy(doc["suites"])

            def strip_attempts(suites):
                for suite in suites:
                    for spec in suite.get("specs", []):
                        for native_test in spec["tests"]:
                            native_test["results"] = []
                    strip_attempts(suite.get("suites", []))

            def individual_cases(suites):
                for suite in suites:
                    for spec in suite.get("specs", []):
                        for native_test in spec["tests"]:
                            current = copy.deepcopy(spec)
                            current["tests"] = [copy.deepcopy(native_test)]
                            yield {"title": suite["title"], "specs": [current]}
                    for child in individual_cases(suite.get("suites", [])):
                        yield {"title": suite["title"], "specs": [], "suites": [child]}

            strip_attempts(collection)
            packets = [
                {"event": "invocation_started", "release_sha": BASE, "invocation": invocation},
                {
                    "event": "collection",
                    "release_sha": BASE,
                    "invocation": invocation,
                    "suites": collection,
                }
            ]
            packets.extend(
                {"event": "test_end", "suites": [suite]}
                for suite in individual_cases(doc["suites"])
            )
            packets.extend(
                {"event": "global_error", "error": value} for value in doc.get("errors", [])
            )
            packets.append(
                {
                    "event": "session_finished",
                    "status": doc["status"],
                    "test_count": len(evidence._inventory(doc, env)),
                }
            )
            if getattr(state, "mutate_progress", None):
                state.mutate_progress(packets)
            with (state.path / "progress.jsonl").open("x", encoding="utf-8") as stream:
                for packet in packets:
                    stream.write(json.dumps(packet, ensure_ascii=False) + "\n")
        return SimpleNamespace(returncode=state.discovery_exit if listing else state.execution_exit)

    state.launch = launch
    state.run = lambda: evidence.run(tmp_path, "offline", args, env=env, launch=launch)
    state.path = tmp_path / evidence.EVIDENCE / "offline"
    return state


def test_complete_native_evidence_binds_release_config_and_full_utf8_inventory(capture):
    assert capture.run() == 0
    evidence.validate(capture.root, ["offline"], BASE)
    inventory = json.loads((capture.path / "discovery.json").read_text(encoding="utf-8"))
    assert (
        inventory["tests"][0]["title_path"][-1] == "Unicode \u00a7 \u0939\u093f\u0902\u0926\u0940"
    )
    assert inventory["tests"][0]["id"] == "native-id:offline:0"
    assert inventory["binding"]["arguments"] == capture.args
    assert inventory["binding"]["release_sha"] == inventory["binding"]["checkout_sha"] == BASE
    assert inventory["binding"]["config_sha256"] == evidence._hash(
        capture.root / "playwright.offline.config.ts"
    )
    for command, kwargs in capture.calls:
        assert "PLAYWRIGHT_JSON_OUTPUT_DIR" not in kwargs["env"]
        assert "PLAYWRIGHT_JUNIT_OUTPUT_NAME" not in kwargs["env"]
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["check"] is False
        assert "--workers=1" in command and "--retries=0" in command
    assert "--list" in capture.calls[0][0]
    assert f"--reporter=list,{evidence.REPORTER}" in capture.calls[1][0]
    assert capture.env["PLAYWRIGHT_JSON_OUTPUT_DIR"] == "must-not-be-used"
    assert set(p.name for p in capture.path.iterdir()) == {
        "invocation.json",
        "discovery.json",
        "results.json",
        "results.xml",
        "native-discovery.json",
        "native-results.json",
        "native-results.xml",
        "progress.jsonl",
        "completion.json",
        "exit.json",
    }


BATCH3_EXPECTED_CASES = {
    "batch3-clients-desktop": (
        "batch3-clients-prod-chromium", "ram-2026-10-22-bugs.spec.ts",
        "B3-CLIENT-01/02/03 contact edits preserve retained verified KYC and matter links",
    ),
    "batch3-clients-mobile": (
        "batch3-clients-prod-mobile", "ram-2026-10-22-bugs.spec.ts",
        "[mobile] B3-CLIENT-06 verified-client contact editing persists at 393px",
    ),
    "batch3-drafts-readonly": (
        "batch3-drafts-readonly-prod-chromium", "ram-2026-10-22-drafting.prod.spec.ts",
        "B3-DRAFT-PROD read-only retained finalized and mutable Appeal controls persist after "
        "reload",
    ),
}


def _batch3_capture(state, invocation):
    project, file, title = BATCH3_EXPECTED_CASES[invocation]
    config = state.root / "playwright.prod-ram.config.ts"
    config.write_text("// synthetic offline Batch3 evidence contract\n", encoding="utf-8")
    (state.root / file).touch()
    state.args[:2] = [f"--config={config.name}", f"--project={project}"]
    state.path = state.root / evidence.EVIDENCE / invocation
    for document in (state.discovery, state.runtime):
        document["config"]["configFile"] = str(config)
        document["config"]["projects"][0].update(id=project, name=project)
        suite = document["suites"][0]
        suite["title"] = file
        suite["specs"][0].update(file=file, title=title)
        suite["specs"][0]["tests"][0].update(projectId=project, projectName=project)
    state.run = lambda: evidence.run(
        state.root, invocation, state.args, env=state.env, launch=state.launch,
    )
    return state


def _damage_batch3_capture(state, damage):
    if damage in {"skipped", "expected_failure"}:
        test = state.runtime["suites"][0]["specs"][0]["tests"][0]
        status = "skipped" if damage == "skipped" else "failed"
        test.update(expectedStatus=status, status="skipped" if status == "skipped" else "expected")
        test["results"][0]["status"] = status
        state.runtime["stats"].update(
            expected=int(status != "skipped"), skipped=int(status == "skipped"),
        )
        return
    if damage == "wrong_config":
        state.args[0] = "--config=playwright.offline.config.ts"
    elif damage == "wrong_project":
        state.args[1] = "--project=unreviewed-project"
    elif damage == "parallel_workers":
        state.args[2] = "--workers=2"
    elif damage == "missing_retry_flag":
        state.args.remove("--retries=0")
    for document in (state.discovery, state.runtime):
        suite = document["suites"][0]
        spec = suite["specs"][0]
        if damage == "missing":
            document["suites"] = []
            document["stats"].update(expected=0, skipped=0)
        elif damage == "duplicate":
            extra = copy.deepcopy(spec)
            extra["id"] += "-duplicate"
            suite["specs"].append(extra)
            document["stats"]["skipped" if document is state.discovery else "expected"] = 2
            state.junit_count = 2
        elif damage == "wrong_project":
            document["config"]["projects"][0].update(
                id="unreviewed-project", name="unreviewed-project",
            )
            spec["tests"][0].update(
                projectId="unreviewed-project", projectName="unreviewed-project",
            )
        elif damage == "wrong_title":
            spec["title"] += " substituted"
        elif damage == "wrong_file":
            suite["title"] = spec["file"] = "unreviewed.spec.ts"
            (state.root / spec["file"]).touch(exist_ok=True)
        elif damage == "substitution":
            replacement = BATCH3_EXPECTED_CASES[
                "batch3-clients-desktop" if "DRAFT" in spec["title"] else "batch3-drafts-readonly"
            ]
            suite["title"] = spec["file"] = replacement[1]
            spec["title"] = replacement[2]
            (state.root / spec["file"]).touch(exist_ok=True)
        elif damage == "wrong_config":
            document["config"]["configFile"] = str(state.root / "playwright.offline.config.ts")
        elif damage == "parallel_workers":
            document["config"]["workers"] = 2


@pytest.mark.parametrize("invocation", BATCH3_EXPECTED_CASES)
def test_batch3_full_envelope_requires_one_actual_pass_for_each_owned_case(capture, invocation):
    state = _batch3_capture(capture, invocation)
    assert state.run() == 0
    evidence.validate(state.root, [invocation], BASE)
    completion = json.loads((state.path / "completion.json").read_text())
    assert completion["completed"] is True and completion["test_count"] == 1
    assert set(completion["sha256"]) == evidence.REPORT_FILES
    assert len(state.calls) == 2
    assert len(list(ET.parse(state.path / "results.xml").iter("testcase"))) == 1
    assert not list(ET.parse(state.path / "results.xml").iter("skipped"))
    result = json.loads((state.path / "results.json").read_text())["tests"][0]
    project, file, title = BATCH3_EXPECTED_CASES[invocation]
    assert (result["project_name"], result["file"], result["title_path"]) == (
        project, file, [file, title],
    )
    assert result["expected_status"] == "passed" and result["status"] == "expected"
    assert len(result["results"]) == 1
    assert result["results"][0]["status"] == "passed" and result["results"][0]["retry"] == 0


@pytest.mark.parametrize("invocation", BATCH3_EXPECTED_CASES)
@pytest.mark.parametrize("damage", [
    "expected_failure", "skipped", "missing", "duplicate", "wrong_project", "wrong_title",
    "wrong_file", "substitution", "wrong_config", "parallel_workers", "missing_retry_flag",
])
@pytest.mark.parametrize("phase", ["run", "validate"])
def test_batch3_full_envelope_rejects_nonpositive_or_substituted_evidence(
    capture, monkeypatch, invocation, damage, phase,
):
    state = _batch3_capture(capture, invocation)
    if damage == "missing":
        reason = (
            "empty_or_duplicate_inventory" if phase == "run" else "completion_inventory_mismatch"
        )
    elif damage in {"expected_failure", "skipped"}:
        reason = "mandatory_batch3_case_not_passed"
    elif damage in {"wrong_project", "wrong_config", "parallel_workers", "missing_retry_flag"}:
        reason = "batch3_role_binding_mismatch"
    else:
        reason = "mandatory_batch3_case_inventory_mismatch"
    if phase == "run":
        _damage_batch3_capture(state, damage)
        assert state.run() == 1
        assert not (state.path / "completion.json").exists()
        exit_marker = json.loads((state.path / "exit.json").read_text())
        assert exit_marker["completed"] is False
        assert exit_marker["incomplete_reason"] == reason
        if damage not in {"expected_failure", "skipped"}:
            assert all("--list" in command for command, _ in state.calls)
        return

    if damage != "missing":
        _damage_batch3_capture(state, damage)
    # Simulate an older producer accepting a malformed but internally consistent
    # full envelope. Restore the real policy before independent final validation.
    with monkeypatch.context() as producer:
        producer.setattr(evidence, "_check_batch3_evidence", lambda *a, **kw: None, raising=False)
        assert state.run() == 0
    if damage == "missing":
        for name in ("discovery.json", "results.json"):
            document = json.loads((state.path / name).read_text())
            document["tests"] = []
            (state.path / name).write_text(json.dumps(document), encoding="utf-8")
        completion = json.loads((state.path / "completion.json").read_text())
        completion["test_count"] = 0
        for name in ("discovery.json", "results.json"):
            completion["sha256"][name] = evidence._hash(state.path / name)
        (state.path / "completion.json").write_text(json.dumps(completion), encoding="utf-8")
    assert (state.path / "completion.json").is_file()
    with pytest.raises(evidence.EvidenceError, match=f"^{reason}$"):
        evidence.validate(state.root, [invocation], BASE)


@pytest.mark.parametrize("invocation", ["legacy", "batch3-clients-desktop-historical"])
def test_batch3_policy_preserves_other_roles_legitimate_skipped_envelopes(capture, invocation):
    _damage_batch3_capture(capture, "skipped")
    capture.path = capture.root / evidence.EVIDENCE / invocation
    assert evidence.run(
        capture.root, invocation, capture.args, env=capture.env, launch=capture.launch,
    ) == 0
    evidence.validate(capture.root, [invocation], BASE)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_release",
        "wrong_invocation",
        "missing_finish",
        "finish_status",
        "finish_count",
        "boolean_count",
        "extra_finish_key",
        "missing_attempt",
        "duplicate_attempt",
        "attempt_status",
        "collection_identity",
        "collection_tags",
        "collection_attempt",
        "extra_event_key",
        "nonobject_event",
        "multi_attempt_packet",
        "wrong_header", "missing_header", "duplicate_collection", "attempt_before_collection",
    ],
)
def test_progress_mutation_cannot_complete_an_invocation(capture, mutation):
    def mutate(packets):
        started, collection, attempt, finish = packets
        if mutation == "wrong_release":
            collection["release_sha"] = "f" * 40
        elif mutation == "wrong_invocation":
            collection["invocation"] = "other"
        elif mutation == "missing_finish":
            packets.pop()
        elif mutation == "finish_status":
            finish["status"] = "failed"
        elif mutation == "finish_count":
            finish["test_count"] = 2
        elif mutation == "boolean_count":
            finish["test_count"] = True
        elif mutation == "extra_finish_key":
            finish["extra"] = "not-reviewed"
        elif mutation == "missing_attempt":
            packets.pop(2)
        elif mutation == "duplicate_attempt":
            packets.insert(2, copy.deepcopy(attempt))
        elif mutation == "attempt_status":
            attempt["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "failed"
        elif mutation == "collection_identity":
            collection["suites"][0]["specs"][0]["id"] = "other-id"
        elif mutation == "collection_tags":
            collection["suites"][0]["specs"][0]["tags"] = ["@unexpected"]
        elif mutation == "collection_attempt":
            collection["suites"][0]["specs"][0]["tests"][0]["results"] = copy.deepcopy(
                attempt["suites"][0]["specs"][0]["tests"][0]["results"]
            )
        elif mutation == "extra_event_key":
            attempt["extra"] = "not-reviewed"
        elif mutation == "nonobject_event":
            packets[2] = None
        elif mutation == "multi_attempt_packet":
            other = copy.deepcopy(attempt["suites"][0])
            other["specs"][0]["id"] = "other-id"
            attempt["suites"].append(other)
        elif mutation == "wrong_header":
            started["invocation"] = "other"
        elif mutation == "missing_header":
            packets.pop(0)
        elif mutation == "duplicate_collection":
            packets.insert(1, copy.deepcopy(collection))
        elif mutation == "attempt_before_collection":
            packets[1], packets[2] = packets[2], packets[1]

    capture.mutate_progress = mutate
    assert capture.run() == 1
    assert not (capture.path / "completion.json").exists()
    marker = json.loads((capture.path / "exit.json").read_text(encoding="utf-8"))
    assert marker["completed"] is False
    assert marker["incomplete_reason"].startswith("progress_")
    assert (capture.path / "native-results.json").is_file()


def test_rehashed_incomplete_progress_still_fails_independent_validation(capture):
    assert capture.run() == 0
    progress = capture.path / "progress.jsonl"
    packets = progress.read_text(encoding="utf-8").splitlines()
    progress.write_text("\n".join([packets[0], packets[1], packets[-1]]) + "\n", encoding="utf-8")
    completion_path = capture.path / "completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["sha256"]["progress.jsonl"] = evidence._hash(progress)
    completion_path.write_text(json.dumps(completion), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError, match="progress_missing_attempt_or_error"):
        evidence.validate(capture.root, ["offline"], BASE)


def test_progress_tamper_is_detected_by_completion_hash(capture):
    assert capture.run() == 0
    with (capture.path / "progress.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("{}\n")
    with pytest.raises(evidence.EvidenceError, match="evidence_hash_mismatch"):
        evidence.validate(capture.root, ["offline"], BASE)


def test_missing_incremental_global_error_cannot_complete_failed_run(capture):
    capture.runtime["errors"] = [{"message": "Redacted native test error"}]
    capture.runtime["status"] = "failed"
    capture.execution_exit = 1
    capture.mutate_progress = lambda packets: packets.pop(-2)
    assert capture.run() == 1
    marker = json.loads((capture.path / "exit.json").read_text(encoding="utf-8"))
    assert marker["incomplete_reason"] == "progress_missing_attempt_or_error"
    assert not (capture.path / "completion.json").exists()


def test_incremental_global_error_must_match_the_native_final_error(capture):
    capture.runtime["errors"] = [{"message": "Redacted native test error"}]
    capture.runtime["status"] = "failed"
    capture.execution_exit = 1
    capture.mutate_progress = lambda packets: packets[-2].update(error={"message": "different"})
    assert capture.run() == 1
    marker = json.loads((capture.path / "exit.json").read_text(encoding="utf-8"))
    assert marker["incomplete_reason"] == "progress_missing_attempt_or_error"
    assert not (capture.path / "completion.json").exists()


@pytest.mark.parametrize("before_collection", [False, True])
def test_real_killed_reporter_retains_failure_but_wrapper_stays_incomplete(
    capture, before_collection,
):
    assert capture.node, "Native release evidence requires Node.js."
    shutil.copyfile(ROOT / "scripts/prod_playwright_reporter.cjs", capture.root / evidence.REPORTER)
    script = (
        '"use strict"; const path = require("node:path"); '
        'const Reporter = require("./scripts/prod_playwright_reporter.cjs"); '
        f"const doc = {json.dumps(capture.runtime)}; "
        "const spec = doc.suites[0].specs[0]; const native = spec.tests[0]; "
        "const results = []; const testcase = { ...spec, ...native, results, "
        "parent: { project: () => doc.config.projects[0] }, "
        "location: { file: path.join(doc.config.rootDir, spec.file), "
        "line: spec.line, column: spec.column }, "
        'titlePath: () => ["", "offline", "offline.spec.ts", spec.title], '
        'outcome: () => results.length ? "unexpected" : "skipped", ok: () => false }; '
        "const reporter = new Reporter(); reporter.configure(doc.config); "
        + ("" if before_collection else
           "reporter.onBegin(doc.config, { allTests: () => [testcase] }); ")
        + 'const result = { status: "failed", retry: 0, duration: 1, '
        'workerIndex: 1, parallelIndex: 0, '
        'startTime: new Date("2026-10-10T00:00:00Z"), annotations: [], attachments: [], '
        'errors: [{ message: "Authorization: Bearer private-test-password '
        'private-legal-body" }] }; '
        + ("" if before_collection else
           "results.push(result); reporter.onTestEnd(testcase, result); ")
        + 'reporter.onError({ message: "private-legal-body" }); '
        'process.stdout.write("READY\\n"); setInterval(() => {}, 1000);'
    )

    def launch(command, **kwargs):
        if "--list" in command:
            return capture.launch(command, **kwargs)
        child_env = {**os.environ, **kwargs["env"]}
        child = subprocess.Popen(
            [capture.node, "-e", script],
            cwd=capture.root,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        progress = capture.path / "progress.jsonl"
        expected_packets = 2 if before_collection else 4
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and child.poll() is None:
                if (
                    progress.is_file()
                    and len(progress.read_bytes().splitlines()) == expected_packets
                ):
                    break
                time.sleep(0.02)
            else:
                pytest.fail(
                    "Killed-process fixture did not durably emit every expected native packet."
                )
            child.kill()
            child.communicate(timeout=10)
            assert child.returncode != 0
            return SimpleNamespace(returncode=child.returncode)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

    assert evidence.run(capture.root, "offline", capture.args, env=capture.env, launch=launch) == 1
    progress = (capture.path / "progress.jsonl").read_text(encoding="utf-8")
    packets = [json.loads(line) for line in progress.splitlines()]
    expected_events = ["invocation_started", "global_error"] if before_collection else [
        "invocation_started", "collection", "test_end", "global_error",
    ]
    assert [packet["event"] for packet in packets] == expected_events
    assert packets[0]["release_sha"] == BASE
    if not before_collection:
        attempt = evidence._inventory(packets[2], {})[0]
        assert attempt["native_spec_id"] == "native-id"
        assert attempt["results"][0]["status"] == "failed"
    assert "private-test-password" not in progress and "private-legal-body" not in progress
    assert not (capture.path / "completion.json").exists()
    assert not (capture.path / "native-results.json").exists()
    marker = json.loads((capture.path / "exit.json").read_text(encoding="utf-8"))
    assert marker["completed"] is False and marker["execution_exit"] != 0
    assert (capture.path / "discovery.json").is_file()


def test_runtime_skip_reason_and_annotations_are_retained_in_json_and_native_junit(capture):
    test = capture.runtime["suites"][0]["specs"][0]["tests"][0]
    test.update(
        status="skipped",
        expectedStatus="skipped",
        annotations=[
            {
                "type": "skip",
                "description": "Owner consent remains pending "
                "\u00a7 \u0939\u093f\u0902\u0926\u0940",
            }
        ],
    )
    test["results"][0].update(status="skipped", annotations=test["annotations"])
    capture.runtime["stats"].update(expected=0, skipped=1)
    assert capture.run() == 0
    evidence.validate(capture.root, ["offline"], BASE)
    rows = json.loads((capture.path / "results.json").read_text(encoding="utf-8"))["tests"]
    assert rows[0]["annotations"] == rows[0]["results"][0]["annotations"] == test["annotations"]
    junit = ET.parse(capture.path / "results.xml")
    assert len(list(junit.iter("skipped"))) == 1
    assert next(junit.iter("property")).attrib == {
        "name": "skip",
        "value": test["annotations"][0]["description"],
    }


def test_privacy_minimization_removes_raw_detail_and_redacts_annotation_secrets(capture):
    test = capture.runtime["suites"][0]["specs"][0]["tests"][0]
    test["annotations"] = [
        {
            "type": "skip",
            "description": "private-test-password user@test.invalid https://example.invalid/?token=x",
        },
        {"type": "skip", "description": '{"private_attachment": "bytes"}'},
    ]
    assert capture.run() == 0
    archived = "\n".join(p.read_text(encoding="utf-8") for p in capture.path.iterdir())
    for secret in (
        "private-test-password",
        "user@test.invalid",
        "?token",
        "private-auth-state",
        "private raw response",
        "private-bytes",
        "private-error-body",
        "private_attachment",
    ):
        assert secret not in archived
    assert "redacted" in archived


@pytest.mark.parametrize("problem", ["discovery", "json", "junit", "progress"])
def test_missing_native_files_never_create_completion(capture, problem):
    capture.missing = problem
    assert capture.run() != 0
    assert not (capture.path / "completion.json").exists()
    assert json.loads((capture.path / "exit.json").read_text())["completed"] is False
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(capture.root, ["offline"], BASE)


@pytest.mark.parametrize(
    "problem",
    [
        "empty",
        "duplicate",
        "load-error",
        "executed",
        "bad-config",
        "bad-project",
        "outside",
        "missing-spec",
    ],
)
def test_invalid_discovery_never_launches_execution(capture, problem):
    spec = capture.discovery["suites"][0]["specs"][0]
    if problem == "empty":
        capture.discovery["suites"] = []
    elif problem == "duplicate":
        capture.discovery["suites"].append(copy.deepcopy(capture.discovery["suites"][0]))
    elif problem == "load-error":
        capture.discovery["errors"] = [{"message": "private failure"}]
    elif problem == "executed":
        spec["tests"][0]["results"] = [{"status": "passed"}]
    elif problem == "bad-config":
        capture.discovery["config"]["configFile"] += ".wrong"
    elif problem == "bad-project":
        spec["tests"][0]["projectName"] = "unselected"
    elif problem == "outside":
        capture.discovery["config"]["projects"][0]["testDir"] = str(capture.root.parent)
    else:
        spec["file"] = "missing.spec.ts"
    assert capture.run() != 0
    assert len(capture.calls) == 1
    assert not (capture.path / "completion.json").exists()


@pytest.mark.parametrize(
    "problem",
    [
        "interrupted",
        "full-interrupted",
        "negative-exit",
        "unexecuted",
        "changed-inventory",
        "stats",
        "xml-count",
        "xml-skips",
        "xml-failures",
    ],
)
def test_incomplete_or_disagreeing_runtime_preserves_failed_evidence(capture, problem):
    test = capture.runtime["suites"][0]["specs"][0]["tests"][0]
    if problem == "interrupted":
        test["results"][0]["status"] = "interrupted"
    elif problem == "full-interrupted":
        capture.runtime["status"] = "interrupted"
    elif problem == "negative-exit":
        capture.execution_exit = -9
    elif problem == "unexecuted":
        test["results"] = []
    elif problem == "changed-inventory":
        capture.runtime["suites"][0]["specs"][0]["id"] = "different-native-id"
    elif problem == "stats":
        capture.runtime["stats"]["expected"] = 2
    elif problem == "xml-count":
        capture.junit_count = 0
    elif problem == "xml-skips":
        capture.runtime["stats"].update(expected=0, skipped=1)
    else:
        capture.runtime["stats"].update(expected=0, unexpected=1)
    assert capture.run() != 0
    assert (capture.path / "discovery.json").exists()
    assert not (capture.path / "completion.json").exists()


@pytest.mark.parametrize("native_exit", [0, 1])
def test_failed_native_results_are_complete_but_never_successful(capture, native_exit):
    test = capture.runtime["suites"][0]["specs"][0]["tests"][0]
    test["status"] = "unexpected"
    test["results"][0]["status"] = "failed"
    capture.runtime["stats"].update(expected=0, unexpected=1)
    capture.execution_exit = native_exit
    assert capture.run() != 0
    assert json.loads((capture.path / "completion.json").read_text())["completed"] is True
    assert len(list(ET.parse(capture.path / "results.xml").iter("failure"))) == 1
    with pytest.raises(evidence.EvidenceError, match="failed_invocation"):
        evidence.validate(capture.root, ["offline"], BASE)


@pytest.mark.parametrize("problem", ["sha", "missing", "tampered", "binding", "scope"])
def test_required_invocation_receipts_fail_closed(capture, problem):
    assert capture.run() == 0
    required, expected = ["offline"], BASE
    if problem == "sha":
        expected = "a" * 40
    elif problem == "missing":
        required.append("another-required-invocation")
    elif problem == "tampered":
        (capture.path / "results.xml").write_text("changed")
    elif problem == "binding":
        path = capture.path / "exit.json"
        report = json.loads(path.read_text())
        report["binding"]["project"] = "wrong"
        path.write_text(json.dumps(report))
    else:
        required = []
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(capture.root, required, expected)


def test_duplicate_invocation_cannot_overwrite_failed_or_successful_evidence(capture):
    assert capture.run() == 0
    before = {p.name: p.read_bytes() for p in capture.path.iterdir()}
    with pytest.raises(FileExistsError):
        capture.run()
    assert {p.name: p.read_bytes() for p in capture.path.iterdir()} == before


def _two_cases(capture, outcomes=("expected", "expected")):
    for document in (capture.discovery, capture.runtime):
        spec = document["suites"][0]["specs"][0]
        second = copy.deepcopy(spec)
        second.update(id="native-second", line=9, title="Second identity")
        document["suites"][0]["specs"].append(second)
    for spec, outcome in zip(capture.runtime["suites"][0]["specs"], outcomes, strict=True):
        test = spec["tests"][0]
        test.update(status=outcome, expectedStatus="skipped" if outcome == "skipped" else "passed")
        test["results"][0]["status"] = {
            "expected": "passed",
            "skipped": "skipped",
            "unexpected": "failed",
        }[outcome]
    capture.discovery["stats"]["skipped"] = 2
    for key in ("expected", "skipped", "unexpected", "flaky"):
        capture.runtime["stats"][key] = outcomes.count(key)
    capture.junit_count = 2


@pytest.mark.parametrize(
    "problem",
    [
        "replacement",
        "duplicate",
        "outcome-permutation",
        "failure-permutation",
        "name",
        "title-path",
        "location",
        "project",
        "outcome-tag",
    ],
)
def test_equal_count_junit_identity_or_per_case_outcome_drift_is_incomplete(capture, problem):
    _two_cases(
        capture,
        ("expected", "skipped")
        if problem == "outcome-permutation"
        else ("expected", "unexpected")
        if problem == "failure-permutation"
        else ("expected", "expected"),
    )

    def mutate(xml):
        suites = list(xml)
        first, second = [suite.find("testcase") for suite in suites]
        if problem == "replacement":
            first.set("caseops-id", "different-native-id")
        elif problem == "duplicate":
            xml.remove(suites[1])
            xml.append(copy.deepcopy(suites[0]))
        elif problem == "outcome-permutation":
            second.remove(second.find("skipped"))
            ET.SubElement(first, "skipped")
            first.set("caseops-outcome", "skipped")
            second.set("caseops-outcome", "expected")
            suites[0].set("skipped", "1")
            suites[1].set("skipped", "0")
        elif problem == "failure-permutation":
            failure = second.find("failure")
            second.remove(failure)
            first.append(failure)
            first.set("caseops-outcome", "unexpected")
            second.set("caseops-outcome", "expected")
            suites[0].set("failures", "1")
            suites[1].set("failures", "0")
        elif problem == "name":
            first.set("name", "Wrong human title")
        elif problem == "title-path":
            first.set("caseops-title-path", json.dumps(["offline.spec.ts", "Wrong identity"]))
        elif problem == "location":
            first.set("line", "6")
        elif problem == "project":
            first.set("caseops-project-name", "another")
        else:
            first.set("caseops-outcome", "skipped")

    capture.mutate_xml = mutate
    assert capture.run() != 0
    assert not (capture.path / "completion.json").exists()
    assert (capture.path / "native-results.xml").is_file()
    assert (capture.path / "native-results.json").is_file()


@pytest.mark.parametrize(
    "field",
    [
        "file",
        "line",
        "column",
        "title",
        "suite-title",
        "project",
        "tags",
        "repeatEachIndex",
        "retries",
        "workers",
        "project-timeout",
    ],
)
def test_same_native_id_cannot_hide_execution_metadata_or_configuration_drift(capture, field):
    spec = capture.runtime["suites"][0]["specs"][0]
    test = spec["tests"][0]
    if field == "file":
        (capture.root / "other.spec.ts").touch()
        spec["file"] = "other.spec.ts"
    elif field in {"line", "column"}:
        spec[field] += 1
    elif field == "title":
        spec["title"] = "Different native title"
    elif field == "suite-title":
        capture.runtime["suites"][0]["title"] = "Different suite"
    elif field == "project":
        test["projectName"] = "another"
    elif field == "tags":
        spec["tags"] = ["@different"]
    elif field in {"repeatEachIndex", "retries"}:
        test[field] = 1
    elif field == "workers":
        capture.runtime["config"]["workers"] = 2
    else:
        capture.runtime["config"]["projects"][0]["timeout"] += 1
    assert capture.run() != 0
    assert not (capture.path / "completion.json").exists()


@pytest.mark.parametrize(
    "problem",
    [
        "retry-one",
        "missing-retry",
        "duplicate-attempt",
        "missing-case-retries",
        "project-retries",
        "repeat-each",
        "wrong-outcome",
        "wrong-expected-status",
    ],
)
def test_zero_retry_release_evidence_requires_exact_native_attempt_and_outcome(capture, problem):
    test = capture.runtime["suites"][0]["specs"][0]["tests"][0]
    if problem == "retry-one":
        test["results"][0]["retry"] = 1
    elif problem == "missing-retry":
        del test["results"][0]["retry"]
    elif problem == "duplicate-attempt":
        test["results"].append(copy.deepcopy(test["results"][0]))
    elif problem == "missing-case-retries":
        del test["retries"]
    elif problem == "project-retries":
        capture.runtime["config"]["projects"][0]["retries"] = 1
    elif problem == "repeat-each":
        capture.runtime["config"]["projects"][0]["repeatEach"] = 2
    elif problem == "wrong-outcome":
        test["status"] = "unexpected"
        capture.runtime["stats"].update(expected=0, unexpected=1)
    else:
        test["expectedStatus"] = "failed"
    assert capture.run() != 0
    assert not (capture.path / "completion.json").exists()


@pytest.mark.parametrize(
    "title_path",
    [
        ["offline.spec.ts", "Root title"],
        ["offline.spec.ts", "Outer", "Inner", "Nested title"],
        ["offline.spec.ts", "", "Whitespace\t\r\n \u00a7 \u0939\u093f\u0902\u0926\u0940"],
        ["offline.spec.ts", "Joined \u203a title", "Leaf"],
        ["offline.spec.ts", "Joined", "title \u203a Leaf"],
    ],
)
def test_canonical_title_shapes_and_xml_whitespace_are_preserved_without_normalization(
    capture, title_path
):
    for document in (capture.discovery, capture.runtime):
        spec = document["suites"][0]["specs"][0]
        spec["title"] = title_path[-1]
        node = {"title": title_path[0], "specs": []}
        document["suites"] = [node]
        for title in title_path[1:-1]:
            child = {"title": title, "specs": []}
            node["suites"] = [child]
            node = child
        node["specs"].append(spec)
    assert capture.run() == 0
    evidence.validate(capture.root, ["offline"], BASE)
    row = json.loads((capture.path / "results.json").read_text(encoding="utf-8"))["tests"][0]
    case = next(ET.parse(capture.path / "results.xml").iter("testcase"))
    assert row["title_path"] == title_path
    assert json.loads(case.get("caseops-title-path")) == title_path
    assert case.get("name") == " \u203a ".join(title_path[1:])


def test_junit_order_is_not_identity_and_colliding_display_names_remain_distinct(capture):
    _two_cases(capture)
    for document in (capture.discovery, capture.runtime):
        specs = document["suites"][0]["specs"]
        specs[1]["title"] = specs[0]["title"]
    capture.mutate_xml = lambda xml: xml.append(xml[0]) or xml.remove(xml[0])
    assert capture.run() == 0
    evidence.validate(capture.root, ["offline"], BASE)


def test_legitimate_runtime_expected_failure_skip_and_timeout_changes_are_not_identity_drift(
    capture,
):
    test = capture.runtime["suites"][0]["specs"][0]["tests"][0]
    test.update(expectedStatus="failed", timeout=60000)
    test["results"][0]["status"] = "failed"
    assert capture.run() == 0
    evidence.validate(capture.root, ["offline"], BASE)


@pytest.mark.parametrize("arguments", list(BASE_COMMANDS.values()), ids=list(BASE_COMMANDS))
def test_every_original_config_project_binding_has_exact_json_xml_identity(capture, arguments):
    capture.args[:] = arguments.split()
    options = dict(argument[2:].split("=", 1) for argument in capture.args)
    config = capture.root / options["config"]
    config.write_text("// deterministic original invocation binding\n", encoding="utf-8")
    project = options.get(
        "project",
        {
            "playwright.ip-a0-prod.config.ts": "ip-a0-prod-chromium",
            "playwright.ip-renewal-prod.config.ts": "ip-renewal-prod-chromium",
            "playwright.ip-cost-prod.config.ts": "",
            "playwright.notice-prod.config.ts": "notice-prod-chromium",
        }.get(options["config"], ""),
    )
    for document in (capture.discovery, capture.runtime):
        document["config"].update(configFile=str(config), workers=int(options.get("workers", "1")))
        document["config"]["projects"][0].update(id=project, name=project)
        document["suites"][0]["specs"][0]["tests"][0].update(projectId=project, projectName=project)
    assert capture.run() == 0
    evidence.validate(capture.root, ["offline"], BASE)
    row = json.loads((capture.path / "results.json").read_text(encoding="utf-8"))["tests"][0]
    case = next(ET.parse(capture.path / "results.xml").iter("testcase"))
    assert (
        case.get("caseops-project-id")
        == case.get("caseops-project-name")
        == row["project_id"]
        == project
    )


@pytest.mark.parametrize("status", ["failed", "timedout"])
def test_failed_full_native_status_cannot_be_hidden_by_green_case_or_exit(capture, status):
    capture.runtime["status"] = status
    assert capture.run() != 0
    assert json.loads((capture.path / "completion.json").read_text())["completed"] is True
    with pytest.raises(evidence.EvidenceError, match="failed_invocation"):
        evidence.validate(capture.root, ["offline"], BASE)


def test_missing_release_owned_reporter_fails_before_native_execution(capture):
    (capture.root / evidence.REPORTER).unlink()
    assert capture.run() != 0
    assert not capture.calls
    assert not (capture.path / "completion.json").exists()


def test_reviewed_native_network_diagnostics_survive_normalized_runtime_and_hashed_receipts(
    capture,
):
    diagnostic = {
        "status": "retained",
        "name": "sanitized-network-evidence",
        "contentType": "application/json",
        "snapshot": {
            "schemaVersion": 1,
            "drainTimedOut": False,
            "omitted": 0,
            "records": [
                {
                    "route": "matter/attachment",
                    "method": "POST",
                    "startedAt": "2026-10-10T00:00:00.000Z",
                    "finishedAt": "2026-10-10T00:00:00.100Z",
                    "outcome": "response_completed",
                    "status": 503,
                    "requestId": "01234567-89ab-cdef-0123-456789abcdef",
                    "problemType": "database_lock_timeout",
                }
            ],
        },
    }
    capture.runtime["suites"][0]["specs"][0]["tests"][0]["results"][0]["networkEvidence"] = (
        diagnostic
    )
    assert capture.run() == 0
    evidence.validate(capture.root, ["offline"], BASE)
    result = json.loads((capture.path / "results.json").read_text(encoding="utf-8"))
    assert result["tests"][0]["results"][0]["network_evidence"] == diagnostic
    completion = json.loads((capture.path / "completion.json").read_text(encoding="utf-8"))
    assert "native-results.json" in completion["sha256"]


def test_complete_native_reporter_pre_disk_privacy_contracts(tmp_path, record_property):
    node = shutil.which("node")
    assert node, "The standard release evidence contracts require Node.js."
    result = subprocess.run(
        [
            node,
            "--test",
            "--test-reporter=tap",
            str(ROOT / "scripts/prod_playwright_reporter.test.cjs"),
        ],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    path = tmp_path / "native-reporter.tap"
    path.write_text(result.stdout + result.stderr, encoding="utf-8")
    record_property("native_reporter_inventory", str(path))
    record_property("native_reporter_test_count", "34")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "# tests 34" in result.stdout
        and "# pass 34" in result.stdout
        and "# fail 0" in result.stdout
        and "# skipped 0" in result.stdout
        and "# cancelled 0" in result.stdout
        and "# todo 0" in result.stdout
    )


@pytest.mark.parametrize("argument", ["--grep=hidden", "--workers=8", "--config=../outside.ts"])
def test_unreviewed_or_duplicate_invocation_arguments_fail_before_execution(capture, argument):
    capture.args.append(argument)
    with pytest.raises(evidence.EvidenceError):
        capture.run()
    assert not capture.calls


def test_new_native_capture_cli_parses_invocation_and_original_options(capture, monkeypatch):
    monkeypatch.setattr(evidence, "ROOT", capture.root)
    monkeypatch.setenv("CASEOPS_EXPECTED_RELEASE_SHA", BASE)
    seen = []
    monkeypatch.setattr(
        evidence, "run", lambda root, invocation, args: seen.append((root, invocation, args)) or 0
    )
    monkeypatch.setattr(
        evidence.sys, "argv", ["capture", "run", "--invocation", "offline", "--", *capture.args]
    )
    assert evidence.main() == 0
    assert seen == [(capture.root, "offline", capture.args)]


def _tester_canonical_rows():
    rows = []
    partitions = {
        "tester": {"ordinary-prod.spec.ts": 97},
        "tester-catalog": {evidence.TESTER_CATALOG_FILE: 18},
        "tester-index": evidence.INDEX_FILES,
        "test-legal-write-oct13": evidence.OCT13_FILES,
    }
    for invocation, files in partitions.items():
        for file, count in files.items():
            for index in range(count):
                native_id = f"{file}-{index}"
                project = evidence.TESTER_PARTITIONS[invocation]
                rows.append({
                    "id": f"{native_id}:{project}:0", "native_spec_id": native_id,
                    "file": file, "line": index + 1, "column": 1, "tags": [],
                    "title_path": [file, (
                        "NOTES22 newest three of four saved notes persist after reload at 1280px "
                        "and 393px" if file == "ram-2026-10-22-prod.spec.ts"
                        else f"case {index} with literal::parameter"
                    )],
                    "project_id": project, "project_name": project, "retries": 0,
                    "repeat_each_index": 0, "timeout": 120000, "status": "expected",
                    "expected_status": "passed",
                    "results": [{"status": "passed", "retry": 0}],
                })
    return rows


def test_reviewed_tester_inventory_includes_all_breakpoint_and_guard_cases():
    assert evidence.TESTER_PARTITION_COUNTS == {
        "tester": 97, "tester-catalog": 18,
        "tester-index": 6, "test-legal-write-oct13": 51,
    }
    assert evidence.OCT13_FILES == {
        "ram-2026-10-13-hearings.spec.ts": 2,
        "ram-2026-10-13-ip-portfolio.spec.ts": 4,
        "ram-2026-10-15-ip-controls.spec.ts": 34,
        "ram-2026-10-15-ip-renewal-tracker.spec.ts": 2,
        "ram-2026-10-17-calendar-readiness.spec.ts": 2,
        "ram-2026-10-17-ip-reminders.spec.ts": 4,
        "ram-2026-10-17-ip-tracker.spec.ts": 2,
        "ram-2026-10-22-prod.spec.ts": 1,
    }
    assert len(evidence._tester_inventory({"tests": _tester_canonical_rows()})) == 172


def test_tester_budget_split_keeps_original_project_and_complete_case_counts():
    assert evidence.TESTER_PARTITION_COUNTS == {
        "tester": 97, "tester-catalog": 18,
        "tester-index": 6, "test-legal-write-oct13": 51,
    }
    assert evidence.TESTER_PARTITIONS["tester-catalog"] == "tester-prod-chromium"


@pytest.mark.parametrize("execution", [False, True])
@pytest.mark.parametrize("damage", [
    None, "missing", "duplicate", "wrong_title", "wrong_project", "row_retries",
    "repeat", "expected_skip", "expected_failure", "wrong_config", "wrong_binding",
    "parallel_workers", "missing_retry_flag", "boolean_workers",
])
def test_notes22_requires_the_exact_positive_case_in_the_authorized_write_role(execution, damage):
    invocation = "test-legal-write-oct13"
    project = "test-legal-write-prod-chromium"
    binding = {
        "invocation": invocation, "config": "playwright.prod-ram.config.ts", "project": project,
        "arguments": ["--config=playwright.prod-ram.config.ts", f"--project={project}",
                      "--workers=1", "--retries=0"],
    }
    document = {
        "configuration": {"workers": 1}, "report_status": "passed", "global_error_count": 0,
        "tests": copy.deepcopy(evidence._tester_selected_rows(
            {"tests": _tester_canonical_rows()}, invocation,
        )),
    }
    row = next(item for item in document["tests"] if item["file"] == "ram-2026-10-22-prod.spec.ts")
    if damage == "missing":
        document["tests"].remove(row)
    elif damage == "duplicate":
        document["tests"].append(copy.deepcopy(row))
    elif damage == "wrong_title":
        row["title_path"][-1] += " substituted"
    elif damage == "wrong_project":
        row["project_id"] = row["project_name"] = "tester-prod-chromium"
    elif damage == "row_retries":
        row["retries"] = 1
    elif damage == "repeat":
        row["repeat_each_index"] = 1
    elif damage in {"expected_skip", "expected_failure"}:
        row["expected_status"] = "skipped" if damage == "expected_skip" else "failed"
    elif damage == "wrong_config":
        binding["config"] = "playwright.offline.config.ts"
    elif damage == "wrong_binding":
        binding["project"] = "tester-prod-chromium"
    elif damage == "parallel_workers":
        document["configuration"]["workers"] = 2
    elif damage == "boolean_workers":
        document["configuration"]["workers"] = True
    elif damage == "missing_retry_flag":
        binding["arguments"].remove("--retries=0")
    if damage:
        with pytest.raises(evidence.EvidenceError, match="notes22"):
            evidence._check_notes22_evidence(binding, document, execution=execution)
    else:
        evidence._check_notes22_evidence(binding, document, execution=execution)


@pytest.mark.parametrize("damage", [
    "skipped", "failed", "retry", "missing_result", "duplicate_result", "global_error",
    "interrupted_report",
])
def test_notes22_runtime_evidence_cannot_certify_a_skip_or_an_incomplete_attempt(damage):
    project = "test-legal-write-prod-chromium"
    binding = {
        "invocation": "test-legal-write-oct13", "config": "playwright.prod-ram.config.ts",
        "project": project, "arguments": ["--config=playwright.prod-ram.config.ts",
                                           f"--project={project}", "--workers=1", "--retries=0"],
    }
    row = copy.deepcopy(next(item for item in _tester_canonical_rows()
                             if item["file"] == "ram-2026-10-22-prod.spec.ts"))
    document = {"configuration": {"workers": 1}, "tests": [row],
                "report_status": "passed", "global_error_count": 0}
    if damage in {"skipped", "failed"}:
        row["status"] = "skipped" if damage == "skipped" else "unexpected"
        row["results"][0]["status"] = damage
    elif damage == "retry":
        row["results"][0]["retry"] = 1
    elif damage == "missing_result":
        row["results"] = []
    elif damage == "duplicate_result":
        row["results"].append(copy.deepcopy(row["results"][0]))
    elif damage == "global_error":
        document["global_error_count"] = 1
    else:
        document["report_status"] = "interrupted"
    with pytest.raises(evidence.EvidenceError, match="mandatory_notes22_case_not_passed"):
        evidence._check_notes22_evidence(binding, document, execution=True)


def test_tester_partition_selection_preserves_complete_ordered_literal_identities():
    canonical = {"tests": _tester_canonical_rows()}
    for invocation, project in evidence.TESTER_PARTITIONS.items():
        binding = {
            "config": "playwright.prod-ram.config.ts", "invocation": invocation,
            "project": project, "arguments": ["--workers=1", "--retries=0"],
        }
        selected = {"tests": evidence._tester_selected_rows(canonical, invocation)}
        evidence._check_tester_selection(binding, selected, canonical)


@pytest.mark.parametrize("invocation", ["tester", "tester-catalog"])
def test_tester_file_filters_preserve_whole_catalog_and_do_not_accept_lookalikes(invocation):
    binding = {
        "config": "playwright.prod-ram.config.ts", "invocation": invocation,
        "project": "tester-prod-chromium", "arguments": ["--workers=1", "--retries=0"],
    }
    filters = evidence._tester_file_filters(binding)
    assert len(filters) == 1
    for path in (
        "tests/e2e/ram-2026-09-05-bugs.spec.ts",
        "C:\\repo\\tests\\e2e\\ram-2026-09-05-bugs.spec.ts",
        "ram-2026-09-05-bugs.spec.ts",
        "tests/e2e/ram-2026-09-05-bugsXspecYts",
        "tests/e2e/prefix-ram-2026-09-05-bugs.spec.ts",
        "tests/e2e/ram-2026-09-05-bugs.spec.ts/other.spec.ts",
        "tests/e2e/ordinary-prod.spec.ts",
    ):
        expected = path.replace("\\", "/").split("/")[-1] == evidence.TESTER_CATALOG_FILE
        assert bool(re.search(filters[0], path)) == (expected == (invocation == "tester-catalog"))


@pytest.mark.parametrize("invocation", ["tester", "tester-catalog"])
@pytest.mark.parametrize("damage", ["missing", "extra", "foreign", "reordered", "metadata"])
def test_core_and_catalog_selection_reject_incomplete_or_overlapping_inventory(invocation, damage):
    canonical = {"tests": _tester_canonical_rows()}
    selected = copy.deepcopy(evidence._tester_selected_rows(canonical, invocation))
    other = evidence._tester_selected_rows(
        canonical, "tester-catalog" if invocation == "tester" else "tester",
    )[0]
    if damage == "missing":
        selected.pop()
    elif damage == "extra":
        selected.append(other)
    elif damage == "foreign":
        selected[-1] = other
    elif damage == "reordered":
        selected.reverse()
    else:
        selected[0]["title_path"][-1] += " changed"
    with pytest.raises(evidence.EvidenceError, match="tester_partition_selection_mismatch"):
        evidence._check_tester_selection({
            "config": "playwright.prod-ram.config.ts", "invocation": invocation,
            "project": "tester-prod-chromium", "arguments": ["--workers=1", "--retries=0"],
        }, {"tests": selected}, canonical)


def test_catalog_cannot_be_replaced_behind_unchanged_canonical_total():
    rows = _tester_canonical_rows()
    for row in rows:
        if row["file"] == evidence.TESTER_CATALOG_FILE:
            row["file"] = "replacement-prod.spec.ts"
    with pytest.raises(evidence.EvidenceError, match="mandatory_tester_catalog_inventory_mismatch"):
        evidence._tester_inventory({"tests": rows})


@pytest.mark.parametrize("file", [
    "ram-2026-10-15-ip-controls.spec.ts",
    "ram-2026-10-15-ip-renewal-tracker.spec.ts",
    "ram-2026-10-17-calendar-readiness.spec.ts",
    "ram-2026-10-17-ip-reminders.spec.ts",
    "ram-2026-10-17-ip-tracker.spec.ts",
])
def test_oct15_ip_file_cannot_disappear_behind_unchanged_partition_total(file):
    rows = _tester_canonical_rows()
    removed = next(row for row in rows if row["file"] == file)
    rows.remove(removed)
    replacement = copy.deepcopy(
        next(row for row in rows if row["file"] == "ram-2026-10-13-hearings.spec.ts")
    )
    replacement["id"] += "-substitute"
    replacement["native_spec_id"] += "-substitute"
    replacement["title_path"][-1] += " substitute"
    rows.append(replacement)
    project = evidence.TESTER_PARTITIONS["test-legal-write-oct13"]
    assert sum(row["project_name"] == project for row in rows) == 51
    with pytest.raises(
        evidence.EvidenceError, match="mandatory_tester_partition_inventory_mismatch"
    ):
        evidence._tester_inventory({"tests": rows})


@pytest.mark.parametrize("damage", [
    "omitted", "extra", "duplicate", "semantic_duplicate", "rerouted",
])
def test_matching_truncated_or_changed_core_inventories_cannot_certify(damage):
    rows = _tester_canonical_rows()
    if damage == "omitted":
        rows.pop(0)
    elif damage == "extra":
        extra = copy.deepcopy(rows[0])
        extra["id"] += "-unreviewed"
        extra["native_spec_id"] += "-unreviewed"
        rows.append(extra)
    elif damage == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif damage == "semantic_duplicate":
        replacement = copy.deepcopy(rows[0])
        replacement.update(id=rows[1]["id"], native_spec_id=rows[1]["native_spec_id"])
        rows[1] = replacement
    else:
        rows[0]["project_id"] = rows[0]["project_name"] = evidence.TESTER_PARTITIONS[
            "tester-index"
        ]
    project = evidence.TESTER_PARTITIONS["tester"]
    selected = {"tests": [row for row in rows if row["project_name"] == project]}
    with pytest.raises(evidence.EvidenceError):
        evidence._check_tester_selection({
            "config": "playwright.prod-ram.config.ts", "invocation": "tester",
            "project": project, "arguments": ["--workers=1", "--retries=0"],
        }, selected, {"tests": rows})


@pytest.mark.parametrize("invocation", list(evidence.TESTER_PARTITIONS))
@pytest.mark.parametrize("damage", [None, "missing_case", "missing_report", "executed_discovery"])
def test_native_tester_capture_retains_unfiltered_inventory_before_execution(
    capture, invocation, damage,
):
    state = capture
    config = state.root / "playwright.prod-ram.config.ts"
    config.write_text("// offline partition contract\n", encoding="utf-8")
    project = evidence.TESTER_PARTITIONS[invocation]
    rows = _tester_canonical_rows()
    template = copy.deepcopy(state.discovery)
    template["config"]["configFile"] = str(config)
    template["config"]["projects"] = [
        {**template["config"]["projects"][0], "id": name, "name": name}
        for name in dict.fromkeys(evidence.TESTER_PARTITIONS.values())
    ]

    def document(selected, runtime=False):
        doc = copy.deepcopy(template)
        doc["suites"] = []
        for row in selected:
            (state.root / row["file"]).touch(exist_ok=True)
            spec = copy.deepcopy(state.discovery["suites"][0]["specs"][0])
            spec.update(id=row["native_spec_id"], file=row["file"], line=row["line"],
                        title=row["title_path"][-1])
            test = copy.deepcopy((state.runtime if runtime else state.discovery)[
                "suites"][0]["specs"][0]["tests"][0])
            test.update(projectId=row["project_id"], projectName=row["project_name"])
            spec["tests"] = [test]
            doc["suites"].append({"title": row["file"], "specs": [spec]})
        doc["stats"].update(expected=len(selected) if runtime else 0,
                            skipped=0 if runtime else len(selected))
        return doc

    selected = evidence._tester_selected_rows({"tests": rows}, invocation)
    state.discovery = document(selected)
    state.runtime = document(selected, runtime=True)
    state.junit_count = len(selected)
    state.path = state.root / evidence.EVIDENCE / invocation
    args = [f"--config={config.name}", f"--project={project}", *state.args[2:]]
    base_launch = state.launch

    def launch(command, **kwargs):
        canonical = kwargs["env"]["CASEOPS_PW_EVIDENCE_INVOCATION"].endswith("-canonical")
        saved = state.discovery
        if canonical:
            assert "--list" in command and not any(arg.startswith("--project=") for arg in command)
            assert not any(arg in command for arg in evidence._tester_file_filters({
                "config": config.name, "invocation": invocation, "project": project,
                "arguments": args,
            }))
            state.discovery = document(rows[:-1] if damage == "missing_case" else rows)
            if damage == "executed_discovery":
                state.discovery["suites"][0]["specs"][0]["tests"][0]["results"] = [
                    {"status": "passed", "retry": 0}
                ]
        try:
            result = base_launch(command, **kwargs)
        finally:
            state.discovery = saved
        path = Path(kwargs["env"]["CASEOPS_PW_EVIDENCE_JSON_FILE"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["invocation"] = kwargs["env"]["CASEOPS_PW_EVIDENCE_INVOCATION"]
        path.write_text(json.dumps(doc), encoding="utf-8")
        if canonical and damage == "missing_report":
            path.unlink()
        if "--list" not in command:
            progress = state.path / "progress.jsonl"
            packets = [json.loads(line) for line in progress.read_text().splitlines()]
            for packet in packets:
                if "invocation" in packet:
                    packet["invocation"] = invocation
            progress.write_text("".join(json.dumps(packet) + "\n" for packet in packets))
        return result

    code = evidence.run(state.root, invocation, args, env=state.env, launch=launch)
    execution = [command for command, _ in state.calls if "--list" not in command]
    if damage:
        assert code == 1 and execution == []
        assert not (state.path / "completion.json").exists()
        assert (state.path / "exit.json").is_file()
    else:
        assert code == 0 and len(execution) == 1
        filters = evidence._tester_file_filters({
            "config": config.name, "invocation": invocation, "project": project,
            "arguments": args,
        })
        assert all(value in execution[0] for value in filters)
        selected_calls = [command for command, kw in state.calls
                          if not kw["env"]["CASEOPS_PW_EVIDENCE_INVOCATION"].endswith("-canonical")]
        assert all(all(value in command for value in filters) for command in selected_calls)
        receipt = json.loads((state.path / "invocation.json").read_text())
        assert receipt["source_owned_file_filters"] == filters
        evidence.validate(state.root, [invocation], BASE)
        completion = json.loads((state.path / "completion.json").read_text())
        assert set(completion["sha256"]) == evidence.REPORT_FILES | evidence.TESTER_CANONICAL_FILES
        assert not (state.root / evidence.EVIDENCE / f"{invocation}-canonical").exists()


@pytest.mark.parametrize("damage", [
    "missing_core", "missing_index", "missing_oct13", "duplicate_id", "extra_index",
    "wrong_index_file", "core_index_overlap", "core_oct13_overlap",
])
def test_tester_canonical_inventory_rejects_dropped_or_overlapping_cases(damage):
    rows = _tester_canonical_rows()
    if damage == "missing_core":
        rows = rows[1:]
    elif damage in {"missing_index", "missing_oct13"}:
        project = evidence.TESTER_PARTITIONS[
            "tester-index" if damage == "missing_index" else "test-legal-write-oct13"
        ]
        rows.remove(next(row for row in rows if row["project_name"] == project))
    elif damage in {"duplicate_id", "extra_index"}:
        row = copy.deepcopy(next(
            row for row in rows if row["project_name"] == evidence.TESTER_PARTITIONS["tester-index"]
        ))
        if damage == "extra_index":
            row["id"] += "-extra"
        rows.append(row)
    elif damage == "wrong_index_file":
        next(row for row in rows if row["project_name"] == evidence.TESTER_PARTITIONS[
            "tester-index"
        ])["file"] = "not-the-owned-spec.ts"
    else:
        rows[0]["file"] = next(iter(
            evidence.INDEX_FILES if damage == "core_index_overlap" else evidence.OCT13_FILES
        ))
    with pytest.raises(evidence.EvidenceError):
        evidence._tester_inventory({"tests": rows})


@pytest.mark.parametrize("damage", ["missing", "reordered", "foreign", "same_id_changed_metadata"])
def test_tester_selection_rejects_noncanonical_subset(damage):
    rows = _tester_canonical_rows()
    project = evidence.TESTER_PARTITIONS["tester-index"]
    selected = copy.deepcopy([row for row in rows if row["project_name"] == project])
    if damage == "missing":
        selected.pop()
    elif damage == "reordered":
        selected.reverse()
    elif damage == "foreign":
        selected[-1] = rows[0]
    else:
        selected[0]["title_path"][-1] = "different identity despite copied native ID"
    with pytest.raises(evidence.EvidenceError, match="tester_partition_selection_mismatch"):
        evidence._check_tester_selection({
            "config": "playwright.prod-ram.config.ts", "invocation": "tester-index",
            "project": project, "arguments": ["--workers=1", "--retries=0"],
        }, {"tests": selected}, {"tests": rows})


@pytest.fixture
def verified_tester_union(tmp_path, monkeypatch):
    """Unit control after envelope validation; not a real browser execution."""
    config = tmp_path / "playwright.prod-ram.config.ts"
    config.write_text("// source-bound offline config\n", encoding="utf-8")
    rows = _tester_canonical_rows()
    checked = []
    monkeypatch.setattr(evidence, "validate", lambda *args: checked.append(args))
    directories = {}
    for invocation, project in evidence.TESTER_PARTITIONS.items():
        directory = tmp_path / evidence.EVIDENCE / invocation
        directory.mkdir(parents=True)
        binding = {
            "config": config.name, "config_sha256": evidence._hash(config),
            "invocation": invocation, "project": project,
            "arguments": ["--workers=1", "--retries=0"],
        }
        (directory / "results.json").write_text(json.dumps({
            "binding": binding,
            "tests": evidence._tester_selected_rows({"tests": rows}, invocation),
        }), encoding="utf-8")
        (directory / "canonical-discovery.json").write_text(
            json.dumps({"tests": rows}), encoding="utf-8"
        )
        directories[invocation] = directory
    return SimpleNamespace(root=tmp_path, directories=directories, checked=checked, config=config)


def test_verified_tester_union_requires_all_four_envelopes_before_certification(
    verified_tester_union,
):
    state = verified_tester_union
    required = list(evidence.TESTER_PARTITIONS)
    evidence.validate_tester_partition_union(state.root, required, BASE)
    assert state.checked == [(state.root, required, BASE)]


@pytest.mark.parametrize("invocation", ["tester", "tester-catalog"])
def test_verified_union_rejects_missing_or_overlapping_core_catalog_envelope(
    verified_tester_union, invocation,
):
    state = verified_tester_union
    other = "tester-catalog" if invocation == "tester" else "tester"
    directory = state.directories[invocation]
    other_result = json.loads((state.directories[other] / "results.json").read_text())
    result_path = directory / "results.json"
    result = json.loads(result_path.read_text())
    result["tests"][0] = other_result["tests"][0]
    result_path.write_text(json.dumps(result))
    with pytest.raises(evidence.EvidenceError, match="tester_partition_union_mismatch"):
        evidence.validate_tester_partition_union(state.root, list(evidence.TESTER_PARTITIONS), BASE)
    with pytest.raises(evidence.EvidenceError, match="missing_or_duplicate_tester_partition"):
        evidence.validate_tester_partition_union(
            state.root, [name for name in evidence.TESTER_PARTITIONS if name != invocation], BASE,
        )


@pytest.mark.parametrize("damage", [
    "missing_partition", "duplicate_partition", "canonical_disagreement", "source_changed",
    "mandatory_skipped", "mandatory_failed", "mandatory_retry", "mandatory_unended",
    "wrong_project", "overlap", "workers_increased", "metadata_disagreement",
])
def test_verified_tester_union_is_fail_closed(verified_tester_union, damage):
    state = verified_tester_union
    required = list(evidence.TESTER_PARTITIONS)
    directory = state.directories["tester-index"]
    result_path = directory / "results.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if damage == "missing_partition":
        required.pop()
    elif damage == "duplicate_partition":
        required[-1] = required[0]
    elif damage == "source_changed":
        state.config.write_text("// changed\n", encoding="utf-8")
    elif damage in {"canonical_disagreement", "metadata_disagreement"}:
        path = directory / "canonical-discovery.json"
        canonical = json.loads(path.read_text(encoding="utf-8"))
        if damage == "canonical_disagreement":
            canonical["tests"][0]["id"] += "-changed"
        else:
            canonical["tests"][0]["title_path"][-1] += "-changed"
        path.write_text(json.dumps(canonical), encoding="utf-8")
    elif damage == "mandatory_unended":
        result["tests"][0]["results"] = []
    elif damage == "wrong_project":
        result["binding"]["project"] = "unreviewed"
    elif damage == "workers_increased":
        result["binding"]["arguments"][0] = "--workers=2"
    elif damage == "overlap":
        result["tests"].append(copy.deepcopy(result["tests"][0]))
    else:
        result["tests"][0]["results"][0].update({
            "status": (
                "skipped" if damage == "mandatory_skipped"
                else "passed" if damage == "mandatory_retry" else "failed"
            ),
            "retry": 1 if damage == "mandatory_retry" else 0,
        })
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(evidence.EvidenceError):
        evidence.validate_tester_partition_union(state.root, required, BASE)


def _assert_native_manifest(workflow):
    for job_name in (
        "prod-playwright-shards", "prod-tester-index", "prod-test-legal-write-oct13",
        "scheduled-statute-verification",
    ):
        job = workflow["jobs"][job_name]
        steps = {step.get("name"): step for step in job["steps"]}
        prepare = steps["Prepare release-owned native Playwright evidence"]
        assert "scripts/prod_playwright_evidence.py" in prepare["run"]
        assert f"git merge-base --is-ancestor HEAD {BASE}" in prepare["run"]
        assert "serving_release_predates_native_capture" in prepare["run"]
        assert "git fetch" not in prepare["run"]
        assert (
            job["env"]["CASEOPS_EXPECTED_RELEASE_SHA"]
            == "${{ needs.resolve-release.outputs.release_sha }}"
        )
        checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v4")
        assert checkout["with"]["fetch-depth"] == 0
        assert checkout["with"]["ref"] == "main"
        assert checkout["with"]["persist-credentials"] is False
        trust = steps["Validate canonical serving commit before release code"]
        assert trust["env"]["CASEOPS_EXPECTED_RELEASE_SHA"] == (
            job["env"]["CASEOPS_EXPECTED_RELEASE_SHA"]
        )
        assert 'trusted_release_checkout.py --release-sha "$CASEOPS_EXPECTED_RELEASE_SHA"' in (
            trust["run"]
        )
        assert job["steps"].index(trust) < job["steps"].index(prepare)
        upload = steps["Upload native Playwright evidence"]
        assert upload["if"] == "always()"
        assert upload["with"]["path"].strip() == "test-results/prod-native-evidence/"
        assert upload["with"]["if-no-files-found"] == (
            "${{ steps.prod-playwright-prerequisites.outputs.ready == 'true' "
            "&& 'error' || 'warn' }}"
        )
        assert "always()" in steps["Reconcile required native Playwright evidence"]["if"]
        assert (
            "steps.native-evidence.outputs.mode == 'native'"
            in steps["Reconcile required native Playwright evidence"]["if"]
        )
        assert (
            steps["Reconcile required native Playwright evidence"]["if"].find("!cancelled()") == -1
        )


def test_all_production_invocations_have_native_capture_and_success_artifacts():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/prod-verify.yml").read_text(encoding="utf-8")
    )
    _assert_native_manifest(workflow)
    shard = workflow["jobs"]["prod-playwright-shards"]
    invocations = []
    for step in shard["steps"]:
        for line in step.get("run", "").splitlines():
            if line.strip().startswith('bash "$RUNNER_TEMP/caseops-prod-playwright" '):
                invocations.append(line.split('caseops-prod-playwright" ', 1)[1].split(" ", 1)[0])
    assert invocations == [
        "tester",
        "tester-catalog",
        "tester-index",
        "test-legal-write-oct13",
        "batch3-clients-desktop",
        "batch3-clients-mobile",
        "batch3-drafts-readonly",
        "legacy",
        "test-legal-readonly",
        "ip-a0",
        "ip-renewal",
        "ip-cost",
        "notice",
        "patent",
        "statute-sources",
        "public-pages",
        "platform-reports",
    ]


def test_pre_fix_reporting_shape_cannot_satisfy_native_contract():
    old_workflow = {
        "jobs": {
            "prod-playwright-shards": {
                "steps": [
                    *[
                        {"name": name, "run": f"npx playwright test {args}"}
                        for name, args in BASE_COMMANDS.items()
                    ],
                    {
                        "name": "Upload Playwright report on failure",
                        "if": "failure()",
                        "uses": "actions/upload-artifact@v4",
                        "with": {"path": "test-results/"},
                    },
                ]
            }
        }
    }
    with pytest.raises(KeyError):
        _assert_native_manifest(old_workflow)


def test_all_suite_arguments_filters_and_order_are_unchanged_from_release_base():
    new = yaml.safe_load((ROOT / ".github/workflows/prod-verify.yml").read_text(encoding="utf-8"))
    bindings = []
    for job_name in ("prod-playwright-shards", "scheduled-statute-verification"):
        for step in new["jobs"][job_name]["steps"]:
            if step.get("name") not in BASE_COMMANDS:
                continue
            wrapped = [
                line.strip()
                for line in step["run"].splitlines()
                if line.strip().startswith('bash "$RUNNER_TEMP/caseops-prod-playwright" ')
            ]
            assert len(wrapped) == 1
            arguments = wrapped[0][wrapped[0].index("--config=") :]
            assert arguments == BASE_COMMANDS[step["name"]]
            bindings.append(
                dict(
                    job=job_name,
                    name=step["name"],
                    condition=step.get("if"),
                    timeout=step.get("timeout-minutes"),
                    env=step.get("env"),
                    arguments=arguments,
                )
            )
    assert len(bindings) == 10
    digest = hashlib.sha256(
        json.dumps(bindings, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == "7f81f4e287bfbf9a60903f48803b10954d6405c02dc3debb15f8c68fa22eb1de"


@pytest.mark.parametrize(
    "mode", ["older", "newer-missing", "newer-half-present", "newer-native", "wrong-sha"]
)
def test_workflow_prepare_uses_only_release_owned_capture_or_proven_older_ancestor(tmp_path, mode):
    # Execute the real workflow shell offline; only substitute its immutable
    # compatibility boundary with this independently created local Git history.
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash and Path(bash).is_file(), "The offline workflow contract requires Bash."

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, check=True, encoding="utf-8"
        ).stdout.strip()

    git("init")
    git(
        "-c",
        "user.name=Offline",
        "-c",
        "user.email=offline@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "local compatibility boundary",
    )
    boundary = git("rev-parse", "HEAD")
    if mode.startswith("newer"):
        git(
            "-c",
            "user.name=Offline",
            "-c",
            "user.email=offline@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "local later release",
        )
    if mode in {"newer-native", "newer-half-present"}:
        script = tmp_path / "scripts/prod_playwright_evidence.py"
        script.parent.mkdir()
        script.write_text("# Release-owned helper is present; preparation never executes it.\n")
        git("add", "scripts/prod_playwright_evidence.py")
        if mode == "newer-native":
            (script.parent / "prod_playwright_reporter.cjs").write_text(
                "// Release-owned reporter.\n"
            )
            git("add", "scripts/prod_playwright_reporter.cjs")
        git(
            "-c",
            "user.name=Offline",
            "-c",
            "user.email=offline@example.invalid",
            "commit",
            "-m",
            "release-owned capture fixture",
        )
    workflow = yaml.safe_load((ROOT / ".github/workflows/prod-verify.yml").read_text())
    scripts = [
        next(s["run"] for s in workflow["jobs"][job]["steps"] if s.get("id") == "native-evidence")
        for job in ("prod-playwright-shards", "scheduled-statute-verification")
    ]
    assert scripts[0] == scripts[1]
    output = tmp_path / "outputs"
    runner = tmp_path / "runner"
    runner.mkdir()
    env = dict(
        os.environ,
        CASEOPS_EXPECTED_RELEASE_SHA=(
            "f" * 40 if mode == "wrong-sha" else git("rev-parse", "HEAD")
        ),
        GITHUB_OUTPUT=str(output),
        RUNNER_TEMP=str(runner),
    )
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    script_path = tmp_path / "prepare.sh"
    script_path.write_text(scripts[0].replace(BASE, boundary), encoding="utf-8", newline="\n")
    result = subprocess.run(
        [bash, str(script_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if mode in {"newer-missing", "newer-half-present", "wrong-sha"}:
        assert result.returncode != 0
        assert not (runner / "caseops-prod-playwright").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.read_text().strip() == ("mode=legacy" if mode == "older" else "mode=native")
        assert (runner / "caseops-prod-playwright").is_file()
        if mode == "older":
            marker = json.loads((tmp_path / evidence.EVIDENCE / "legacy.json").read_text())
            assert marker["completed"] is False
            assert marker["release_sha"] == boundary
