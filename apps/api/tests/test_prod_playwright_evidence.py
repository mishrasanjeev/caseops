from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
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
                        "title": "Unicode \u00a7 \u0939\u093f\u0902\u0926\u0940",
                        "tests": [
                            {
                                "projectId": "offline",
                                "projectName": "offline",
                                "timeout": 30000,
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
    )

    def launch(command, **kwargs):
        state.calls.append((command, kwargs))
        listing = "--list" in command
        doc = copy.deepcopy(state.discovery if listing else state.runtime)
        doc.update(
            release_sha=BASE,
            invocation="offline",
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
            suite = ET.SubElement(xml, "testsuite", name="offline.spec.ts")
            for _ in range(state.junit_count):
                case = ET.SubElement(
                    suite, "testcase", name="Unicode \u00a7 \u0939\u093f\u0902\u0926\u0940"
                )
                native_test = doc["suites"][0]["specs"][0]["tests"][0]
                properties = ET.SubElement(case, "properties")
                for annotation in native_test["annotations"]:
                    ET.SubElement(
                        properties,
                        "property",
                        name=annotation["type"],
                        value=annotation.get("description", ""),
                    )
                if native_test["status"] == "skipped":
                    ET.SubElement(case, "skipped")
                if native_test["status"] == "unexpected":
                    ET.SubElement(
                        case, "failure", message="Redacted native test error"
                    ).text = "Native test failure; private detail omitted."
            ET.ElementTree(xml).write(
                kwargs["env"]["CASEOPS_PW_EVIDENCE_JUNIT_FILE"], encoding="utf-8"
            )
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
        "completion.json",
        "exit.json",
    }


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


@pytest.mark.parametrize("problem", ["discovery", "json", "junit"])
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
    record_property("native_reporter_test_count", "17")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "# tests 17" in result.stdout
        and "# fail 0" in result.stdout
        and "# skipped 0" in result.stdout
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


def _assert_native_manifest(workflow):
    for job_name in ("prod-playwright-shards", "scheduled-statute-verification"):
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
        assert checkout["with"]["ref"] == job["env"]["CASEOPS_EXPECTED_RELEASE_SHA"]
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
        "legacy",
        "test-legal-readonly",
        "ip-a0",
        "ip-renewal",
        "ip-cost",
        "notice",
        "patent",
        "statute-sources",
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
