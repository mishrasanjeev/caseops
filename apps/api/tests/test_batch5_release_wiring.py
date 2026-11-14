from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_prod_playwright_evidence import (
    BASE,
    BATCH5_BUGS_CASES,
    BATCH5_BUGS_FILE,
    ROOT,
    _tester_canonical_rows,
    evidence,
)
from tests.test_prod_playwright_evidence import capture as _native_capture
from tests.test_prod_playwright_evidence import verified_tester_union as _verified_tester_union

capture = _native_capture
verified_tester_union = _verified_tester_union


def _reviewed_batch5_counts():
    return {
        "ram-2026-11-11-statutes.spec.ts": (1, 1),
        "ram-2026-11-11-drafting.spec.ts": (1, 1),
        "ram-2026-11-11-contracts.spec.ts": (1, 1),
        "ram-2026-11-11-bugs.spec.ts": (2, 2),
    }


def _batch5_fixture_cases(file, width):
    if file == BATCH5_BUGS_FILE:
        return BATCH5_BUGS_CASES[width]
    title = dict(evidence.BATCH5_MOVED_CASES).get(file, f"B5 {file} workflow")
    scope = {
        "ram-2026-11-11-statutes.spec.ts": "workflow-outcome",
        "ram-2026-11-11-contracts.spec.ts": "workflow-outcome",
        "ram-2026-11-11-drafting.spec.ts": "retained-readonly",
    }.get(file, "legacy-workflow-outcome")
    return ((("[mobile] " if width else "") + title, scope),)


@pytest.fixture
def batch5_capture(capture, monkeypatch):
    state = capture
    counts = _reviewed_batch5_counts()
    monkeypatch.setattr(evidence, "BATCH5_CASE_COUNTS", counts)
    counts = evidence._batch5_counts()
    config = state.root / "playwright.prod-ram.config.ts"
    config.write_text("// exact offline B5 configuration\n", encoding="utf-8")
    (state.root / "playwright.app.config.ts").write_text("// offline app config\n")
    (state.root / "scripts/prod_playwright_evidence.py").write_text("# offline helper source\n")
    for file in counts:
        source = state.root / "tests/e2e" / file
        source.parent.mkdir(parents=True, exist_ok=True)
        source.touch()
    (state.root / "tests/e2e/ram-2026-11-14-prod.spec.ts").touch()
    template = copy.deepcopy(state.discovery)
    template["config"]["configFile"] = str(config)
    template["stats"]["startTime"] = "2026-10-09T00:00:00.000Z"
    template["config"]["projects"] = [
        {**template["config"]["projects"][0], "id": project, "name": project}
        for project in evidence.BATCH5_PROJECTS.values()
    ]
    template["suites"] = []
    for index, project in enumerate(evidence.BATCH5_PROJECTS.values()):
        for file, pair in counts.items():
            if not pair[index]:
                continue
            (state.root / file).touch()
            cases = _batch5_fixture_cases(file, index)
            assert len(cases) == pair[index]
            for ordinal, (title, _scope) in enumerate(cases):
                spec = copy.deepcopy(state.discovery["suites"][0]["specs"][0])
                spec.update(
                    id=f"{project}-{file}" + (f"-{ordinal}" if ordinal else ""),
                    file=file,
                    title=title,
                )
                spec["tests"][0].update(projectId=project, projectName=project)
                template["suites"].append({"title": file, "specs": [spec]})
    template["stats"].update(skipped=len(template["suites"]))
    state.batch5_canonical = copy.deepcopy(template)
    state.batch5_documents = {}
    for role, project in evidence.BATCH5_PROJECTS.items():
        discovery = copy.deepcopy(template)
        discovery["suites"] = [
            suite
            for suite in discovery["suites"]
            if suite["specs"][0]["tests"][0]["projectName"] == project
        ]
        discovery["stats"].update(skipped=len(discovery["suites"]))
        runtime = copy.deepcopy(discovery)
        for suite in runtime["suites"]:
            width = list(evidence.BATCH5_PROJECTS.values()).index(project)
            scopes = dict(_batch5_fixture_cases(suite["title"], width))
            annotation = {
                "type": "caseops-b5-proof",
                "description": scopes[suite["specs"][0]["title"]],
            }
            suite["specs"][0]["tests"][0].update(
                status="expected",
                expectedStatus="passed",
                annotations=[annotation],
                results=[
                    {"status": "passed", "retry": 0, "duration": 1, "errors": [], "annotations": []}
                ],
            )
        runtime["stats"].update(expected=len(runtime["suites"]), skipped=0)
        state.batch5_documents[role] = (discovery, runtime)
    delegate = state.launch

    def launch(command, **kwargs):
        invocation = kwargs["env"]["CASEOPS_PW_EVIDENCE_INVOCATION"]
        role = invocation.removesuffix("-canonical")
        state.path = state.root / evidence.EVIDENCE / role
        state.discovery, state.runtime = state.batch5_documents[role]
        state.junit_count = len(state.runtime["suites"])
        if invocation.endswith("-canonical"):
            assert "--list" in command and not any(arg.startswith("--project=") for arg in command)
            state.discovery = state.batch5_canonical
        result = delegate(command, **kwargs)
        if getattr(state, "change_source", False) and "--list" not in command:
            (state.root / "tests/e2e" / evidence.BATCH5_FILES[0]).write_text("// changed\n")
        return result

    state.batch5_run = lambda role: evidence.run(
        state.root,
        role,
        [
            "--config=playwright.prod-ram.config.ts",
            f"--project={evidence.BATCH5_PROJECTS[role]}",
            "--workers=1",
            "--retries=0",
            "--reporter=list",
            f"--output=test-results/{role}",
        ],
        env=state.env,
        launch=launch,
    )
    return state


def test_batch5_inventory_cannot_infer_unreviewed_counts_or_change_historical_pins():
    if not evidence.BATCH5_CASE_COUNTS:
        with pytest.raises(evidence.EvidenceError, match="unreviewed_batch5_case_counts"):
            evidence._batch5_counts()
    else:
        assert set(evidence._batch5_counts()) == {
            "ram-2026-11-11-statutes.spec.ts",
            "ram-2026-11-11-drafting.spec.ts",
            "ram-2026-11-11-contracts.spec.ts",
            "ram-2026-11-11-bugs.spec.ts",
            "ram-2026-11-07-contracts.spec.ts",
            "ram-2026-11-07-teams.spec.ts",
        }
    assert evidence.TESTER_PARTITION_COUNTS == {
        "tester": 101,
        "tester-catalog": 18,
        "tester-index": 6,
        "test-legal-write-oct13-a": 40,
        "test-legal-write-oct13-b": 11,
    }
    assert evidence.APP_BASE_PROJECT_COUNTS == {"app-chromium": 719, "app-mobile": 55}
    assert len(evidence.APP_EXPECTED_SKIPS) == 21
    assert evidence.BATCH5_CASE_COUNTS == _reviewed_batch5_counts()
    assert evidence.APP_PROJECT_COUNTS == {"app-chromium": 727, "app-mobile": 63}
    assert sum(evidence.BATCH5_CASE_COUNTS[BATCH5_BUGS_FILE]) == 4
    assert sum(sum(pair) for pair in evidence.BATCH5_CASE_COUNTS.values()) == 8 + 2
    assert evidence.BATCH5_CASE_PROOF_SCOPES == {
        BATCH5_BUGS_FILE: dict(case for cases in BATCH5_BUGS_CASES for case in cases),
    }


@pytest.mark.parametrize("role", ["batch5-desktop", "batch5-mobile"])
def test_batch5_full_native_envelopes_bind_canonical_collection_and_actual_positive_cases(
    batch5_capture, role
):
    state = batch5_capture
    assert state.batch5_run(role) == 0
    evidence.validate(state.root, [role], BASE)
    receipt = evidence._json(state.root / evidence.EVIDENCE / role / "completion.json")
    assert receipt["completed"] and receipt["canonical_discovery_exit"] == 0
    assert evidence.TESTER_CANONICAL_FILES.issubset(receipt["sha256"])
    assert receipt["test_count"] == 7
    assert len(receipt["batch5_proof_scopes"]) == receipt["test_count"]
    proofs = {row["id"]: row["scope"] for row in receipt["batch5_proof_scopes"]}
    result = evidence._json(state.root / evidence.EVIDENCE / role / "results.json")
    width = list(evidence.BATCH5_PROJECTS).index(role)
    assert {(row["title_path"][-1], proofs[row["id"]]) for row in result["tests"]
            if row["file"] == BATCH5_BUGS_FILE} == set(BATCH5_BUGS_CASES[width])


@pytest.mark.parametrize("role", ["batch5-desktop", "batch5-mobile"])
@pytest.mark.parametrize("damage", ["renamed", "duplicate_comms", "duplicate_assistant"])
def test_batch5_mixed_file_requires_both_exact_semantics_at_unchanged_counts(
    batch5_capture, role, damage,
):
    state = batch5_capture
    project = evidence.BATCH5_PROJECTS[role]
    documents = (state.batch5_canonical, *state.batch5_documents[role])
    for document in documents:
        specs = [suite["specs"][0] for suite in document["suites"]
                 if suite["specs"][0]["file"] == BATCH5_BUGS_FILE
                 and suite["specs"][0]["tests"][0]["projectName"] == project]
        assert len(specs) == 2 and specs[0]["id"] != specs[1]["id"]
        if damage == "renamed":
            specs[1]["title"] += " changed identity"
        elif damage == "duplicate_comms":
            specs[1]["title"] = specs[0]["title"]
        else:
            specs[0]["title"] = specs[1]["title"]
    assert state.batch5_run(role) == 1
    receipt = evidence._json(state.root / evidence.EVIDENCE / role / "exit.json")
    assert receipt["incomplete_reason"] == "batch5_required_case_identity_mismatch"


@pytest.mark.parametrize("role", ["batch5-desktop", "batch5-mobile"])
@pytest.mark.parametrize("case", ["communications", "assistant"])
@pytest.mark.parametrize("damage", ["swapped", "missing", "both", "workflow_outcome"])
def test_batch5_mixed_proof_annotations_cannot_reclassify_either_guard(
    batch5_capture, role, case, damage,
):
    state = batch5_capture
    runtime = state.batch5_documents[role][1]
    specs = [suite["specs"][0] for suite in runtime["suites"]
             if suite["specs"][0]["file"] == BATCH5_BUGS_FILE]
    target = specs[case == "assistant"]["tests"][0]
    alternate = ("preview-no-paid-guard" if case == "assistant"
                 else "assistant-research-no-paid-guard")
    if damage == "missing":
        target["annotations"] = []
    elif damage == "both":
        target["annotations"].append({"type": "caseops-b5-proof", "description": alternate})
    else:
        target["annotations"][0]["description"] = (
            "workflow-outcome" if damage == "workflow_outcome" else alternate
        )
    assert state.batch5_run(role) == 1
    receipt = evidence._json(state.root / evidence.EVIDENCE / role / "exit.json")
    assert receipt["incomplete_reason"] == "batch5_proof_scope_mismatch"


@pytest.mark.parametrize(
    "damage",
    ["missing", "duplicate", "foreign_file", "width", "skip", "retry", "no_scope", "wrong_scope"],
)
def test_batch5_rejects_partial_reclassified_or_nonpositive_native_cases(batch5_capture, damage):
    state = batch5_capture
    discovery, runtime = state.batch5_documents["batch5-desktop"]
    if damage == "missing":
        discovery["suites"].pop()
    elif damage == "duplicate":
        discovery["suites"][1] = copy.deepcopy(discovery["suites"][0])
    elif damage == "foreign_file":
        state.batch5_canonical["suites"][0]["specs"][0]["file"] = "other.spec.ts"
    elif damage == "width":
        state.batch5_canonical["suites"][0]["specs"][0]["title"] = "[mobile] Wrong desktop role"
    elif damage == "skip":
        native = runtime["suites"][0]["specs"][0]["tests"][0]
        native.update(status="skipped", expectedStatus="skipped")
        native["results"][0]["status"] = "skipped"
    elif damage == "retry":
        runtime["suites"][0]["specs"][0]["tests"][0]["results"][0]["retry"] = 1
    elif damage == "no_scope":
        runtime["suites"][0]["specs"][0]["tests"][0]["annotations"] = []
    else:
        runtime["suites"][1]["specs"][0]["tests"][0]["annotations"][0]["description"] = (
            "workflow-outcome"
        )
    assert state.batch5_run("batch5-desktop") == 1
    assert not (state.root / evidence.EVIDENCE / "batch5-desktop/completion.json").exists()


@pytest.mark.parametrize("damage", ["missing_canonical", "raw_result", "missing_role"])
def test_batch5_validation_rechecks_raw_channels_and_required_role_scope(batch5_capture, damage):
    state = batch5_capture
    assert state.batch5_run("batch5-desktop") == 0
    directory = state.root / evidence.EVIDENCE / "batch5-desktop"
    required = ["batch5-desktop"]
    if damage == "missing_canonical":
        (directory / "canonical-native-discovery.json").unlink()
    elif damage == "raw_result":
        raw = evidence._json(directory / "native-results.json")
        raw["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "failed"
        (directory / "native-results.json").write_text(json.dumps(raw), encoding="utf-8")
        receipt = evidence._json(directory / "completion.json")
        receipt["sha256"]["native-results.json"] = evidence._hash(directory / "native-results.json")
        (directory / "completion.json").write_text(json.dumps(receipt), encoding="utf-8")
    else:
        required.append("batch5-mobile")
    with pytest.raises((evidence.EvidenceError, OSError)):
        evidence.validate(state.root, required, BASE)


@pytest.mark.parametrize(
    "role,project", [("batch5-unknown", "batch5-prod-chromium"), ("ordinary", "batch5-prod-mobile")]
)
def test_batch5_reserved_projects_refuse_generic_invocations(role, project):
    with pytest.raises(evidence.EvidenceError, match="unreviewed_batch5_invocation"):
        evidence._batch5_partition({"invocation": role, "project": project})


def test_batch5_source_change_after_transport_cannot_produce_completion(batch5_capture):
    state = batch5_capture
    state.change_source = True
    assert state.batch5_run("batch5-desktop") == 1
    receipt = evidence._json(state.root / evidence.EVIDENCE / "batch5-desktop/exit.json")
    assert receipt["incomplete_reason"] == "batch5_source_changed_during_execution"


def test_batch5_canonical_source_binding_includes_reference_spec_but_not_local_generation(
    batch5_capture,
):
    state = batch5_capture
    before = evidence._batch5_source_hashes(state.root)
    reference = "tests/e2e/ram-2026-11-14-prod.spec.ts"
    assert reference in before
    assert "tests/e2e/draft-quality20261114.spec.ts" not in before
    (state.root / reference).write_text("// changed official-reference test\n", encoding="utf-8")
    after = evidence._batch5_source_hashes(state.root)
    assert after[reference] != before[reference]
    assert {file: digest for file, digest in after.items() if file != reference} == {
        file: digest for file, digest in before.items() if file != reference
    }
    assert not (state.root / evidence.EVIDENCE / "batch5-desktop/completion.json").exists()


@pytest.mark.parametrize(
    "damage", [None, "missing_role", "missing_moved", "renamed_moved", "overlap"]
)
def test_batch5_release_union_preserves_all176_original_cases_plus_additions(
    verified_tester_union,
    monkeypatch,
    damage,
):
    # Envelope validation is independently exercised above; this checks the union afterward.
    state = verified_tester_union
    monkeypatch.setattr(evidence, "BATCH5_CASE_COUNTS", _reviewed_batch5_counts())
    core = _tester_canonical_rows()
    batch5 = []
    for width, project in enumerate(evidence.BATCH5_PROJECTS.values()):
        for file in evidence._batch5_counts():
            for ordinal, (title, _scope) in enumerate(_batch5_fixture_cases(file, width)):
                spec_id = f"{project}-{file}" + (f"-{ordinal}" if ordinal else "")
                row = copy.deepcopy(core[0])
                row.update(
                    id=f"{spec_id}:0",
                    native_spec_id=spec_id,
                    file=file,
                    title_path=[file, title],
                    project_id=project,
                    project_name=project,
                )
                batch5.append(row)
    if damage == "missing_moved":
        batch5.pop()
    elif damage == "renamed_moved":
        batch5[-1]["title_path"][-1] = "Different journey"
    canonical = core + batch5
    for role, project in evidence.BATCH5_PROJECTS.items():
        directory = state.root / evidence.EVIDENCE / role
        directory.mkdir()
        binding = {"config": state.config.name, "config_sha256": evidence._hash(state.config)}
        selected = [row for row in batch5 if row["project_name"] == project]
        if damage == "overlap" and role == "batch5-mobile":
            selected[-1] = batch5[0]
        (directory / "results.json").write_text(json.dumps({"binding": binding, "tests": selected}))
    roles = [*evidence.TESTER_PARTITIONS, *evidence.BATCH5_PROJECTS]
    for role in roles:
        (state.root / evidence.EVIDENCE / role / "canonical-discovery.json").write_text(
            json.dumps({"tests": canonical}), encoding="utf-8"
        )
    if damage == "missing_role":
        roles.pop()
    if damage:
        with pytest.raises(evidence.EvidenceError):
            evidence.validate_batch5_release_union(state.root, roles, BASE)
    else:
        receipt = evidence.validate_batch5_release_union(state.root, roles, BASE)
        assert receipt["original_case_count"] == 176
        assert receipt["new_batch5_case_count"] == 8 + 2
        assert receipt["new_reference_case_count"] == 4
        assert receipt["test_count"] == 176 + 8 + 2 + 4


def test_batch5_workflow_is_serial_correctly_authenticated_and_required_for_certification():
    jobs = yaml.safe_load((ROOT / ".github/workflows/prod-verify.yml").read_text())["jobs"]
    job = jobs["prod-batch5-tester"]
    assert job["needs"] == ["resolve-release", "prod-batch4-tester"]
    assert job["strategy"]["max-parallel"] == 1
    assert "workflow_dispatch" in job["if"] and "always()" in job["if"]
    steps = {step.get("name"): step for step in job["steps"]}
    run = steps["Run release-owned Batch5 tester acceptance"]
    assert run["env"]["CASEOPS_RAM_PROD_SLUG"] == "test-legal"
    assert (
        run["env"]["CASEOPS_RAM_PROD_PASSWORD"] == "${{ secrets.CASEOPS_TEST_LEGAL_PROD_PASSWORD }}"
    )
    assert "steps.batch5-prerequisites.outputs.state == 'current'" in run["if"]
    assert "prod-batch5-tester" in jobs["record-release-evidence"]["needs"]
    assert "needs.prod-batch5-tester.result == 'success'" in jobs["record-release-evidence"]["if"]
    record = {step.get("name"): step for step in jobs["record-release-evidence"]["steps"]}
    assert (
        record["Retain Batch5 partition evidence"]["with"]["name"]
        == "prod-playwright-report-batch5"
    )
    validation = record["Require current release-owned Batch5 evidence before certification"]["run"]
    assert "batch5-predates.json" in validation and "exit 1" in validation
    assert "validate --required batch5-desktop batch5-mobile" in validation


@pytest.mark.parametrize(
    "mode", ["older", "newer-missing", "partial", "current", "dirty", "wrong-sha"]
)
def test_actual_batch5_workflow_guard_never_executes_new_contract_on_old_source(tmp_path, mode):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash and Path(bash).is_file()

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, check=True, encoding="utf-8"
        ).stdout.strip()

    def commit(message):
        git("add", ".")
        git(
            "-c",
            "user.name=Offline",
            "-c",
            "user.email=offline@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            message,
        )

    git("init")
    helper = tmp_path / "scripts/prod_playwright_evidence.py"
    helper.parent.mkdir()
    helper.write_text("raise RuntimeError('Old helper must not run the new contract')\n")
    for file, _ in evidence.BATCH5_MOVED_CASES:
        source = tmp_path / "tests/e2e" / file
        source.parent.mkdir(parents=True, exist_ok=True)
        source.touch()
    for file in ("playwright.app.config.ts", "playwright.prod-ram.config.ts"):
        (tmp_path / file).write_text("// older release\n")
    commit("independent pre-B5 boundary")
    boundary = git("rev-parse", "HEAD")
    if mode in {"partial", "current", "dirty"}:
        helper.write_text("BATCH5_CONTRACT_VERSION = 1\nprint('owned-contract')\n")
        (tmp_path / "playwright.prod-ram.config.ts").write_text(
            'name: "batch5-prod-chromium"\nname: "batch5-prod-mobile"\n'
        )
        (tmp_path / "playwright.app.config.ts").write_text("/ram-2026-11-11-\n")
        if mode != "partial":
            for file in evidence.BATCH5_FILES:
                path = tmp_path / "tests/e2e" / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
    if mode != "older":
        commit("independent later release")
    if mode == "dirty":
        helper.write_text(helper.read_text() + "# changed after checkout\n")
    jobs = yaml.safe_load((ROOT / ".github/workflows/prod-verify.yml").read_text())["jobs"]
    guard = next(
        step["run"]
        for step in jobs["prod-batch5-tester"]["steps"]
        if step.get("id") == "batch5-prerequisites"
    )
    script = tmp_path / "guard.sh"
    script.write_text(
        guard.replace("2816c29c30d8f13147f67a396f47321871096f0d", boundary), newline="\n"
    )
    output = tmp_path / "guard-output"
    env = dict(
        os.environ,
        GITHUB_OUTPUT=str(output),
        CASEOPS_EXPECTED_RELEASE_SHA="f" * 40 if mode == "wrong-sha" else git("rev-parse", "HEAD"),
    )
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    result = subprocess.run(
        [bash, str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    if mode in {"older", "current"}:
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.read_text().strip() == (
            "state=historical" if mode == "older" else "state=current"
        )
        assert ("owned-contract" in result.stdout) is (mode == "current")
        if mode == "older":
            marker = json.loads((tmp_path / evidence.EVIDENCE / "batch5-predates.json").read_text())
            assert marker == {
                "release_sha": boundary,
                "completed": False,
                "reason": "serving_release_predates_batch5_acceptance",
            }
    else:
        assert result.returncode != 0
        assert not output.exists()


@pytest.mark.parametrize(
    "config",
    ["playwright.app.config.ts", "playwright.docker.config.ts", "playwright.prod-ram.config.ts"],
)
def test_actual_configs_discover_all_four_b5_files_with_disjoint_desktop_mobile_roles(
    tmp_path, config
):
    cli = Path(
        os.environ.get("CASEOPS_TEST_PLAYWRIGHT_CLI", ROOT / "node_modules/@playwright/test/cli.js")
    ).resolve()
    assert cli.is_file(), "Current source metadata needs an installed Playwright runtime."
    runtime_index = cli.with_name("index.js")
    assert runtime_index.is_file()
    # Ancestor worktrees can have a different Playwright copy ahead of NODE_PATH.
    package = tmp_path / "node_modules/@playwright/test"
    package.mkdir(parents=True)
    (package / "index.js").write_text(
        f"module.exports = require({json.dumps(str(runtime_index))});\n",
        encoding="utf-8",
    )
    node = shutil.which("node")
    assert node
    for filename in (
        "playwright.app.config.ts",
        "playwright.docker.config.ts",
        "playwright.prod-ram.config.ts",
    ):
        (tmp_path / filename).write_bytes((ROOT / filename).read_bytes())
    support = tmp_path / "tests/e2e/support"
    support.mkdir(parents=True)
    (support.parent / "global-setup.ts").write_text("export default async function () {}\n")
    (support / "cost-controls.ts").write_text(
        'export const noPaidProviderHeaders = {"X-CaseOps-Automated-Test":"no-paid-providers"};\n'
        "export const localTransportHeaders = () => noPaidProviderHeaders;\n"
    )
    (support / "env.ts").write_text(
        f"export const repoRoot = {json.dumps(str(tmp_path))};\n"
        'export const e2eEnv = {}; export const apiPort = "8000";\n'
        'export const apiBaseUrl = "http://127.0.0.1:8000";\n'
    )
    for file in evidence.BATCH5_FILES:
        cases = ([case for width in BATCH5_BUGS_CASES for case in width]
                 if file == BATCH5_BUGS_FILE else
                 [("B5 desktop workflow", "workflow-outcome"),
                  ("[mobile] B5 phone workflow", "workflow-outcome")])
        (support.parent / file).write_text(
            'import { test } from "@playwright/test";\n'
            + "".join(
                f"test({json.dumps(title)}, {{ annotation: {{ type: 'caseops-b5-proof', "
                f"description: {json.dumps(scope)} }} }}, async () => {{}});\n"
                for title, scope in cases
            ),
        )
    (support.parent / "ram-2026-11-11-unreviewed.spec.ts").write_text(
        'import { test } from "@playwright/test"; test("Wrong file", async () => {});\n'
    )
    env = dict(os.environ, NODE_PATH=str(cli.parents[2]), CI="1")
    result = subprocess.run(
        [node, str(cli), "test", f"--config={config}", "--list", "--reporter=json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(result.stdout)
    assert document["errors"] == []

    def cases(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                for native in spec["tests"]:
                    yield spec["file"], spec["title"], native["projectName"], native["results"]
            yield from cases(suite.get("suites", []))

    rows = list(cases(document["suites"]))
    expected_projects = (
        {"batch5-prod-chromium", "batch5-prod-mobile"}
        if config == "playwright.prod-ram.config.ts"
        else {"app-chromium", "app-mobile"}
    )
    assert len(rows) == 8 + 2
    assert {row[0] for row in rows} == set(evidence.BATCH5_FILES)
    assert {row[2] for row in rows} == expected_projects
    assert all(
        ("[mobile]" in title) == project.endswith("mobile") and not attempts
        for _, title, project, attempts in rows
    )
    for project in expected_projects:
        assert len([row for row in rows if row[2] == project]) == 5
