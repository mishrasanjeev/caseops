"""Run only the real launcher's AST functions with an offline fake CLI.

The fake replaces shared output on every invocation, just as Playwright does.
No Docker, browser, database, Git or external provider process is launched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
RUNNER = REPO / "scripts/verify-docker.ps1"
SHELLS = ("powershell", "pwsh") if os.name == "nt" else ("pwsh",)

FAKE_CLI = r"""
const fs = require('fs');
const path = require('path');
const args = process.argv.slice(2);
const root = process.cwd();
const requestedMode = process.env.RETENTION_CASE;
const forwardSlashes = requestedMode.startsWith('forward-slash-');
const mode = forwardSlashes ? requestedMode.slice('forward-slash-'.length) : requestedMode;
const output = mode === 'custom-output' ? path.join(root, 'custom-results/deep') :
  mode === 'ancestor-reparse' ? path.join(root, 'linked-parent/results') :
  args.includes('--output') ? args[args.indexOf('--output') + 1] : path.join(root, 'test-results');
if (mode === 'ancestor-reparse') {
  const target = path.join(root, 'parent-target');
  if (!fs.existsSync(target)) {
    fs.mkdirSync(target);
    fs.symlinkSync(target, path.join(root, 'linked-parent'),
      process.platform === 'win32' ? 'junction' : 'dir');
  }
}
const log = path.join(root, 'invocations.jsonl');
const prior = fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n') : [];
const invocation = prior.length + 1;
const project = args.includes('--project=app-mobile') ? 'app-mobile' : 'app-chromium';
const config = {
  configFile: args[args.indexOf('--config') + 1],
  rootDir: path.join(root, 'tests/e2e'),
  projects: [{ name: project, testDir: path.join(root, 'tests/e2e'), outputDir: output }],
};
if (forwardSlashes) {
  config.projects[0].outputDir = output.replace(/\\/g, '/');
}
if (mode === 'extended-output') {
  config.projects[0].outputDir = '\\\\?\\' + output;
}
if (mode === 'custom-output') config.projects.push({name: 'not-invoked',
  testDir: path.join(root, 'tests/e2e'), outputDir: path.join(root, 'absent-unused')});
if (mode === 'multiple-output') config.projects.push({name: 'secondary',
  testDir: path.join(root, 'tests/e2e'), outputDir: path.join(root, 'second-results')});
if (args.includes('--list')) {
  fs.writeFileSync(process.env.PLAYWRIGHT_JSON_OUTPUT_FILE, JSON.stringify({config,
    suites: mode === 'empty-discovery' ? [] : [{file: 'fixture.spec.ts', specs: [{
      title: 'offline receipt', tests: [
      {projectName: project, results: []}]}]}], errors: [],
    stats: {expected: 0, unexpected: 0, skipped: mode === 'empty-discovery' ? 0 : 1, flaky: 0}}));
  process.exit(0);
}
fs.appendFileSync(log, JSON.stringify({invocation, args, project,
  json: process.env.PLAYWRIGHT_JSON_OUTPUT_FILE,
  junit: process.env.PLAYWRIGHT_JUNIT_OUTPUT_FILE}) + '\n');
// Only this fresh isolated candidate's directory is removed.
fs.rmSync(output, {recursive: true, force: true});
const unit = path.join(output, 'fixture-' + invocation +
  (mode === 'long-source' ? '-' + 'retained-'.repeat(16) : ''));
fs.mkdirSync(path.join(unit, 'attachments'), {recursive: true});
fs.mkdirSync(path.join(output, 'empty-directory'));
const receipt = {version: 1, test_id: 'offline-' + invocation, project,
  exit_code: mode === 'failed' ? 7 : 0, error: null, duration_ms: 3};
fs.writeFileSync(path.join(unit, 'selection-process.json'), JSON.stringify(receipt));
fs.writeFileSync(path.join(unit, 'drive-process.json'), JSON.stringify(receipt));
const names = [
  'test_fixture_inventory_is_bounded',
  'test_install_rejects_non_e2e_and_cloud_before_touching_application',
  'test_provider_cannot_authorize_exchange_or_browse_google',
  'test_provider_does_not_allow_cross_fixture_tokens',
  'test_provider_enforces_the_captured_version_size_and_deadline',
  'test_provider_returns_exact_registered_bytes_only',
];
fs.writeFileSync(path.join(unit, 'drive-six-units.txt'),
  names.map(name => name + ' ... ok').join('\n') + '\nRan 6 tests\nOK\n');
// Bytes are a known one-pixel PNG, not a browser execution claim.
fs.writeFileSync(path.join(unit, 'screenshot.png'), Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
  'base64'));
fs.writeFileSync(path.join(unit, '.control.json'),
  JSON.stringify({status: 'rejected', sha256: null}));
fs.writeFileSync(path.join(unit, 'empty.txt'), '');
const originals = ['selection-process.json', 'drive-process.json', 'drive-six-units.txt',
  'screenshot.png', '.control.json', 'empty.txt'];
const attachments = originals.map((name, index) => {
  const saved = path.join(unit, 'attachments', name);
  fs.copyFileSync(path.join(unit, name), saved);
  return {name, contentType: name.endsWith('.png') ? 'image/png' : 'text/plain',
    path: forwardSlashes ?
      (index % 2 ? path.relative(root, saved) : saved).replace(/\\/g, '/') :
      index % 2 ? path.relative(root, saved) : saved};
});
if (mode === 'missing-attachment') attachments[0].path = path.join(unit, 'missing.json');
if (mode === 'escape-attachment') attachments[0].path = path.join(root, '../outside.json');
if (mode === 'escape-output') config.projects[0].outputDir = path.join(root, '../outside');
if (mode === 'missing-output') fs.rmSync(output, {recursive: true});
if (mode === 'linked-output') {
  fs.renameSync(output, path.join(root, 'link-target'));
  fs.symlinkSync(path.join(root, 'link-target'), output,
    process.platform === 'win32' ? 'junction' : 'dir');
}
const report = {config, suites: mode === 'empty' ? [] : [{file: 'fixture.spec.ts', specs: [{
  title: 'offline receipt', tests: [{id: 'offline-' + invocation, projectName: project,
    results: [{status: mode === 'failed' ? 'failed' : 'passed', attachments}]}]}]}], errors: [],
  stats: {expected: mode === 'empty' || mode === 'failed' ? 0 : 1,
    unexpected: mode === 'failed' ? 1 : 0, skipped: 0, flaky: 0}};
if (mode === 'multiple-output') {
  const second = path.join(root, 'second-results');
  fs.rmSync(second, {recursive: true, force: true});
  fs.mkdirSync(second);
  const secondFile = path.join(second, 'secondary.json');
  fs.writeFileSync(secondFile, JSON.stringify({status: 'offline-secondary'}));
  report.suites[0].specs.push({title: 'secondary', tests: [{id: 'secondary-' + invocation,
    projectName: 'secondary',
    results: [{status: 'passed', attachments: [{name: 'secondary', path: secondFile}]}]}]});
  report.stats.expected = 2;
}
fs.writeFileSync(process.env.PLAYWRIGHT_JSON_OUTPUT_FILE,
  mode === 'malformed-json' ? '{' : JSON.stringify(report));
fs.writeFileSync(process.env.PLAYWRIGHT_JUNIT_OUTPUT_FILE,
  '<testsuites><testsuite>' + (mode === 'empty' ? '' : '<testcase name="offline receipt"/>') +
  (mode === 'multiple-output' ? '<testcase name="secondary"/>' : '') +
  '</testsuite></testsuites>');
const reporterPath = args.find(arg => arg.startsWith('--reporter=')).slice('--reporter='.length)
  .split(',').find(file => file.endsWith('prod_playwright_reporter.cjs'));
if (reporterPath !== path.join(root, 'scripts/prod_playwright_reporter.cjs')) {
  throw new Error('Foreign reporter');
}
const Reporter = require(reporterPath);
const reporter = new Reporter();
config.workers = 1;
for (const p of config.projects) Object.assign(p, {retries: 0, repeatEach: 1, timeout: 1000});
const cases = [];
for (const suite of report.suites) for (const spec of suite.specs) {
  Object.assign(spec, {file: suite.file, line: 1, column: 1});
  for (const test of spec.tests) {
    spec.id = test.id;
    Object.assign(test, {expectedStatus: 'passed',
      status: mode === 'failed' ? 'unexpected' : 'expected'});
    for (const run of test.results) Object.assign(run, {retry: 0, workerIndex: 0, parallelIndex: 0,
      startTime: new Date('2026-10-20T00:00:00Z'), duration: 1, annotations: [], errors: []});
    const results = [];
    const testcase = {id: test.id, title: spec.title, expectedStatus: test.expectedStatus,
      annotations: [], tags: [], retries: 0, repeatEachIndex: 0, timeout: 1000, results,
      parent: {project: () => config.projects.find(p => p.name === test.projectName)},
      location: {file: path.join(config.rootDir, spec.file), line: 1, column: 1},
      titlePath: () => ['', test.projectName, spec.file, spec.title],
      outcome: () => results.length ? test.status : 'skipped',
      ok: () => test.status !== 'unexpected'};
    cases.push({testcase, runs: test.results});
  }
}
reporter.onBegin(config, {allTests: () => cases.map(c => c.testcase)});
for (const {testcase, runs} of cases) for (const run of runs) {
  testcase.results.push(run);
  reporter.onTestEnd(testcase, run);
}
reporter.onEnd({status: mode === 'failed' ? 'failed' : 'passed',
  startTime: new Date(), duration: 1});
// The original JSON reporter still owns all raw path attachments.
if (mode !== 'malformed-json') {
  fs.writeFileSync(process.env.PLAYWRIGHT_JSON_OUTPUT_FILE, JSON.stringify(report));
}
process.exit(mode === 'failed' ? 7 : 0);
"""

HARNESS = r"""
param([string]$Runner, [string]$Root, [string]$Node, [string]$Case)
$ErrorActionPreference = 'Stop'
$Ast = [Management.Automation.Language.Parser]::ParseFile($Runner, [ref]$null, [ref]$null)
foreach ($Name in @(
    'Test-PathWithinRoot', 'Assert-CandidatePlaywrightSuite', 'Invoke-CandidatePlaywright'
)) {
    $Found = @($Ast.FindAll({param($n)
        $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name
    }, $true))
    if ($Found.Count -ne 1) { throw "Expected exactly one $Name" }
    $Text = $Found[0].Extent.Text
    if ($Name -eq 'Invoke-CandidatePlaywright' -and $Case -eq 'missing-metadata') {
        $Enumeration = '$Directory.GetFileSystemInfos()'
        if (-not $Text.Contains($Enumeration)) { throw 'Missing native enumeration boundary' }
        $Missing = '@($Directory.GetFileSystemInfos()) + [IO.FileInfo]::new(' +
            '(& $IoPath (Join-Path $RepoRoot ''missing-observed-entry'')))'
        $Text = $Text.Replace($Enumeration, $Missing)
    }
    if ($Name -eq 'Invoke-CandidatePlaywright' -and
        $Case -in @('copy-error', 'corrupt-copy', 'changed-source', 'changed-inventory')) {
        $NativeCopy = '[IO.File]::Copy((& $IoPath $Item.FullName), (& $IoPath $Target), $false)'
        if (-not $Text.Contains($NativeCopy)) { throw 'Missing native copy injection boundary' }
        $Replacement = 'Copy-Item -LiteralPath $Item.FullName ' +
            '-Destination $Target -ErrorAction Stop'
        $Text = $Text.Replace($NativeCopy, $Replacement)
    }
    . ([scriptblock]::Create($Text))
}
$RepoRoot = Join-Path $Root 'candidate'
$ResultsDirectory = Join-Path $Root 'evidence'
$PlaywrightConfig = Join-Path $RepoRoot 'playwright.docker.config.ts'
$PlaywrightCli = Join-Path $RepoRoot 'offline-cli.cjs'
$NodePath = $Node
$ReleaseSha = '1111111111111111111111111111111111111111'
$env:CASEOPS_E2E_PYTHON = Join-Path $RepoRoot 'fake-python'
$env:RETENTION_CASE = $Case
$env:PLAYWRIGHT_JSON_OUTPUT_FILE = 'caller-json'
$env:PLAYWRIGHT_JUNIT_OUTPUT_FILE = 'caller-xml'
$env:PLAYWRIGHT_JSON_OUTPUT_DIR = 'caller-dir'
$env:PLAYWRIGHT_JSON_OUTPUT_NAME = 'caller-name'
$NativeEnvironment = @('CASEOPS_EXPECTED_RELEASE_SHA', 'CASEOPS_PW_EVIDENCE_PHASE',
  'CASEOPS_PW_EVIDENCE_INVOCATION', 'CASEOPS_PW_EVIDENCE_JSON_FILE',
  'CASEOPS_PW_EVIDENCE_JUNIT_FILE')
foreach ($Name in $NativeEnvironment) {
    [Environment]::SetEnvironmentVariable($Name, 'caller-' + $Name, 'Process')
}
$CopyCount = 0
if ($Case -in @('copy-error', 'corrupt-copy', 'changed-source', 'changed-inventory')) {
    function Copy-Item {
        param([string]$LiteralPath, [string]$Destination, [string]$ErrorAction)
        $script:CopyCount++
        if ($Case -eq 'copy-error' -and $script:CopyCount -eq 2) {
            throw 'Injected isolated copy error'
        }
        [IO.File]::Copy((& $IoPath $LiteralPath), (& $IoPath $Destination), $false)
        if ($Case -eq 'corrupt-copy') {
            [IO.File]::AppendAllText((& $IoPath $Destination), 'corrupt')
        }
        if ($Case -eq 'changed-source') {
            [IO.File]::AppendAllText((& $IoPath $LiteralPath), 'changed')
        }
        if ($Case -eq 'changed-inventory' -and $script:CopyCount -eq 1) {
            $Added = Join-Path (Split-Path -Parent $LiteralPath) 'new-file.json'
            [IO.File]::WriteAllText($Added, '{}')
        }
    }
}
$Observed = @()
$Rejected = $null
$ExitCode = $null
try {
    Assert-CandidatePlaywrightSuite -Arguments @()
    foreach ($Arguments in @(
        @('--project=app-chromium', '--shard=1/2'),
        @('--project=app-chromium', '--shard=2/2'),
        @('--project=app-mobile')
    )) {
        Invoke-CandidatePlaywright -Arguments $Arguments
        $ExitCode = $LASTEXITCODE
        $Observed += [ordered]@{ arguments = $Arguments; exit_code = $ExitCode }
        if ($ExitCode -ne 0) { throw 'Caller stops on nonzero exit' }
    }
}
catch { $Rejected = $_.Exception.Message }
finally {
    [ordered]@{
        observed = @($Observed); rejected = $Rejected; last_exit_code = $ExitCode
        restored = ($env:PLAYWRIGHT_JSON_OUTPUT_FILE -eq 'caller-json' -and
          $env:PLAYWRIGHT_JUNIT_OUTPUT_FILE -eq 'caller-xml' -and
          $env:PLAYWRIGHT_JSON_OUTPUT_DIR -eq 'caller-dir' -and
          $env:PLAYWRIGHT_JSON_OUTPUT_NAME -eq 'caller-name' -and
          @($NativeEnvironment | Where-Object {
            [Environment]::GetEnvironmentVariable($_, 'Process') -cne ('caller-' + $_)
          }).Count -eq 0)
    } | ConvertTo-Json -Depth 12 |
        Set-Content -LiteralPath (Join-Path $Root 'harness-result.json') -Encoding UTF8
}
"""


def _hash(path: Path) -> str:
    return hashlib.sha256(_long(path).read_bytes()).hexdigest()


def _long(path: Path) -> Path:
    # The retained layout deliberately exercises Windows' legacy 260-byte limit.
    if os.name == "nt" and not str(path).startswith("\\\\?\\"):
        return Path("\\\\?\\" + str(path.resolve()))
    return path


def _read(path: Path):
    return json.loads(_long(path).read_text(encoding="utf-8-sig"))


def _read_progress(path: Path):
    return [json.loads(line) for line in _long(path).read_text(encoding="utf-8").splitlines()]


def _run(tmp_path: Path, shell: str, case: str):
    executable = shutil.which(shell)
    node = shutil.which("node")
    assert executable and node, "The offline launcher regression requires its declared tools"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (tmp_path / "evidence").mkdir()
    (candidate / "tests/e2e").mkdir(parents=True)
    (candidate / "scripts").mkdir()
    shutil.copyfile(
        REPO / "scripts/prod_playwright_reporter.cjs",
        candidate / "scripts/prod_playwright_reporter.cjs",
    )
    (candidate / "tests/e2e/fixture.spec.ts").write_text("// offline source identity\n")
    unrelated = candidate / "test-results/prod-native-evidence/unrelated/private.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("must not archive another invocation\n")
    (candidate / "playwright.docker.config.ts").write_text("// offline fixture\n")
    (candidate / "fake-python").write_bytes(b"")
    (candidate / "offline-cli.cjs").write_text(FAKE_CLI, encoding="utf-8")
    harness = tmp_path / "harness.ps1"
    harness.write_text(HARNESS, encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("PLAYWRIGHT_")}
    process = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            "-Runner",
            str(RUNNER),
            "-Root",
            str(tmp_path),
            "-Node",
            node,
            "-Case",
            case,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    (tmp_path / "stdout.bin").write_bytes(process.stdout)
    (tmp_path / "stderr.bin").write_bytes(process.stderr)
    assert process.returncode == 0, (process.stdout, process.stderr)
    result = _read(tmp_path / "harness-result.json")
    assert result["restored"], result
    return result, tmp_path / "evidence"


def _validator_source() -> str:
    matches = re.findall(
        r"\$ValidateNative = @'\r?\n([\s\S]*?)\r?\n'@", RUNNER.read_text(encoding="utf-8")
    )
    assert len(matches) == 1, "Exercise the launcher's one actual native validator"
    return matches[0]


def _identity_reports(tmp_path: Path, *, reverse_pools: bool = False):
    root = tmp_path / "candidate"
    tests = root / "tests/e2e"
    tests.mkdir(parents=True)
    (tests / "fixture.spec.ts").write_text("// offline identity fixture\n")
    config = root / "playwright.docker.config.ts"
    config.write_text("// offline config\n")
    directory = root / "test-results/prod-native-evidence/playwright-identity"
    directory.mkdir(parents=True)
    specs = []
    for index in range(6):
        skipped = index == 2
        specs.append(
            {
                "id": f"stable-case-{index}",
                "file": "fixture.spec.ts",
                "line": 10 + index,
                "column": 3,
                "tests": [
                    {
                        "projectName": "app-chromium",
                        "expectedStatus": "passed",
                        "status": "skipped" if skipped else "expected",
                        "results": [{"status": "skipped" if skipped else "passed", "retry": 0}],
                    }
                ],
            }
        )
    native = {
        "release_sha": "1" * 40,
        "invocation": "playwright-identity",
        "phase": "execution",
        "status": "passed",
        "config": {
            "configFile": str(config),
            "rootDir": str(tests),
            "projects": [{"name": "app-chromium", "testDir": str(tests)}],
        },
        "suites": [{"specs": [spec]} for spec in specs],
        "stats": {"expected": 5, "unexpected": 0, "skipped": 1, "flaky": 0},
        "errors": [],
    }
    # allTests() retains interleaved entries; JSON groups direct specs and pools.
    pools = [
        {"title": "pool-one", "specs": [specs[1], specs[3]]},
        {"title": "pool-two", "specs": [specs[5]]},
    ]
    raw = deepcopy(native)
    raw["suites"] = [
        {"specs": deepcopy(specs[::2]), "suites": deepcopy(pools[::-1] if reverse_pools else pools)}
    ]
    collection = deepcopy(native["suites"])
    for suite in collection:
        suite["specs"][0]["tests"][0]["results"] = []
    packets = [
        {
            "event": "invocation_started",
            "release_sha": "1" * 40,
            "invocation": "playwright-identity",
        },
        {
            "event": "collection",
            "release_sha": "1" * 40,
            "invocation": "playwright-identity",
            "suites": collection,
        },
        *[{"event": "test_end", "suites": [deepcopy(suite)]} for suite in native["suites"]],
        {"event": "session_finished", "status": "passed", "test_count": 6},
    ]
    return directory, config, native, raw, packets


def _run_validator(tmp_path: Path, reports, *, complete_tail: bool = True):
    directory, config, native, raw, packets = reports
    (directory / "native-results.json").write_text(json.dumps(native), encoding="utf-8")
    progress = "\n".join(json.dumps(packet) for packet in packets)
    (directory / "progress.jsonl").write_text(
        progress + ("\n" if complete_tail else ""), encoding="utf-8"
    )
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    node = shutil.which("node")
    assert node, "The canonical validator requires Node"
    process = subprocess.run(
        [
            node,
            "-e",
            _validator_source(),
            str(directory),
            "1" * 40,
            "playwright-identity",
            str(raw_path),
            str(config),
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    (tmp_path / "validator-stdout.bin").write_bytes(process.stdout)
    (tmp_path / "validator-stderr.bin").write_bytes(process.stderr)
    assert not list(directory.glob("*.completion.json"))
    return process


@pytest.mark.parametrize("reverse_pools", [False, True])
def test_native_cross_reporter_accepts_reordered_nested_fixture_pools(
    tmp_path: Path, reverse_pools: bool
) -> None:
    reports = _identity_reports(tmp_path, reverse_pools=reverse_pools)
    process = _run_validator(tmp_path, reports)
    assert process.returncode == 0, process.stderr
    assert process.stdout == b"native-progress-verified"


@pytest.mark.parametrize(
    "corruption",
    [
        "missing-raw",
        "extra-raw",
        "duplicate-raw",
        "identity-id",
        "identity-file",
        "identity-line",
        "identity-column",
        "identity-project",
        "expected-status",
        "case-status",
        "attempt-status",
        "retry",
        "extra-attempt",
        "missing-attempt",
        "collection-order",
        "collection-missing",
        "collection-duplicate",
        "progress-case",
        "progress-duplicate",
        "progress-missing",
        "release-sha",
        "invocation",
        "config",
        "session-status",
        "session-count",
        "global-errors",
        "stats",
        "partial-tail",
    ],
)
def test_native_cross_reporter_rejects_identity_outcome_and_progress_drift(
    tmp_path: Path, corruption: str
) -> None:
    reports = _identity_reports(tmp_path)
    _directory, _config, native, raw, packets = reports
    spec = raw["suites"][0]["specs"][0]
    test = spec["tests"][0]
    if corruption == "missing-raw":
        raw["suites"][0]["specs"].pop()
    elif corruption in {"extra-raw", "duplicate-raw"}:
        extra = deepcopy(spec)
        if corruption == "extra-raw":
            extra["id"] = "unselected-extra-id"
        raw["suites"][0]["specs"].append(extra)
    elif corruption.startswith("identity-"):
        field = corruption.removeprefix("identity-")
        if field == "project":
            test["projectName"] = "foreign-project"
        else:
            spec[field] = spec[field] + 1 if field in {"line", "column"} else "foreign"
    elif corruption == "expected-status":
        test["expectedStatus"] = "failed"
    elif corruption == "case-status":
        test["status"] = "unexpected"
    elif corruption == "attempt-status":
        test["results"][0]["status"] = "failed"
    elif corruption == "retry":
        test["results"][0]["retry"] = 1
    elif corruption == "extra-attempt":
        test["results"].append(deepcopy(test["results"][0]))
    elif corruption == "missing-attempt":
        test["results"] = []
    elif corruption == "collection-order":
        packets[1]["suites"].reverse()
    elif corruption == "collection-missing":
        packets[1]["suites"].pop()
    elif corruption == "collection-duplicate":
        packets[1]["suites"].append(deepcopy(packets[1]["suites"][0]))
    elif corruption == "progress-case":
        packets[2]["suites"][0]["specs"][0]["tests"][0]["results"][0]["retry"] = 1
    elif corruption == "progress-duplicate":
        packets.insert(3, deepcopy(packets[2]))
    elif corruption == "progress-missing":
        packets.pop(2)
    elif corruption == "release-sha":
        packets[0]["release_sha"] = "2" * 40
    elif corruption == "invocation":
        packets[0]["invocation"] = "foreign"
    elif corruption == "config":
        native["config"]["configFile"] = str(tmp_path / "foreign.config.ts")
    elif corruption == "session-status":
        packets[-1]["status"] = "failed"
    elif corruption == "session-count":
        packets[-1]["test_count"] = 5
    elif corruption == "global-errors":
        packets.insert(-1, {"event": "global_error", "error": {"message": "fixture"}})
    elif corruption == "stats":
        raw["stats"]["skipped"] = 0
    process = _run_validator(tmp_path, reports, complete_tail=corruption != "partial-tail")
    assert process.returncode != 0
    assert process.stdout == b""
    assert b"Native Playwright progress is incomplete or inconsistent." in process.stderr


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "case",
    ["success", "long-source", "forward-slash-output", "forward-slash-long-source"],
)
def test_serial_invocations_retain_complete_bound_artifacts(
    tmp_path: Path, shell: str, case: str
) -> None:
    result, evidence = _run(tmp_path, shell, case)
    assert result["rejected"] is None, result
    inventory = _read(evidence / "playwright-inventory.json")
    assert len(inventory["suites"][0]["specs"][0]["tests"]) == 1
    completions = sorted(evidence.glob("*.completion.json"))
    assert len(completions) == 3
    assert not (tmp_path / "candidate/test-results/fixture-1").exists()
    for completion_path in completions:
        completion = _read(completion_path)
        assert completion["event"] == "execution_finished" and completion["tests"] == 1
        manifest_path = Path(completion["artifacts_manifest"])
        manifest = _read(manifest_path)
        assert manifest["event"] == "artifacts_retained"
        assert manifest["release_sha"] == completion["release_sha"]
        assert Path(manifest["json"]) == Path(completion["json"])
        assert len(manifest["files"]) == 15
        native_files = [
            f for f in manifest["files"] if "/prod-native-evidence/" in f["relative_path"]
        ]
        assert len(native_files) == 3
        assert {Path(f["original_path"]).parent.name for f in native_files} == {
            completion_path.name.removesuffix(".completion.json")
        }
        packets = _read_progress(Path(completion["progress"]))
        assert [p["event"] for p in packets] == [
            "invocation_started",
            "collection",
            "test_end",
            "session_finished",
        ]
        assert packets[0]["invocation"] == completion_path.name.removesuffix(".completion.json")
        assert packets[0]["release_sha"] == completion["release_sha"]
        assert len(manifest["attachments"]) == 6
        payload = _long(manifest_path.parent)
        actual = {
            str(p.relative_to(payload)).replace("\\", "/")
            for p in (payload / "payload").rglob("*")
            if p.is_file()
        }
        assert actual == {file["retained_path"] for file in manifest["files"]}
        for file in manifest["files"]:
            retained = payload / file["retained_path"]
            assert retained.stat().st_size == file["size"]
            assert _hash(retained) == file["sha256"]
            assert file["relative_path"].startswith("test-results/")
            assert file["retained_path"] == "payload/" + file["relative_path"]
        if case.endswith("long-source"):
            assert max(len(file["original_path"]) for file in manifest["files"]) > 260
            assert (
                max(len(str(payload / file["retained_path"])) for file in manifest["files"]) > 260
            )
        report = _read(Path(completion["json"]))
        test = report["suites"][0]["specs"][0]["tests"][0]
        assert {a["original_path"] for a in manifest["attachments"]} == {
            a["path"] for a in test["results"][0]["attachments"]
        }
        for attachment in manifest["attachments"]:
            assert attachment["test_id"] == test["id"]
            assert attachment["project_name"] == test["projectName"]
            assert _hash(payload / attachment["retained_path"]) == attachment["sha256"]
        six = next(
            f
            for f in manifest["files"]
            if f["relative_path"].endswith("/drive-six-units.txt")
            and "/attachments/" not in f["relative_path"]
        )
        transcript = (payload / six["retained_path"]).read_text()
        assert transcript.count(" ... ok\n") == 6 and transcript.endswith("Ran 6 tests\nOK\n")
        assert any(
            (payload / directory).name == "empty-directory" and (payload / directory).is_dir()
            for directory in manifest["directories"]
        )
    assert not list(evidence.glob("*.partial"))
    assert not list(evidence.glob("*.retention-failed.json"))


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize(
    "case, fragment",
    [
        ("copy-error", "Injected isolated copy error"),
        ("corrupt-copy", "copy verification"),
        ("missing-attachment", "attachment"),
        ("escape-attachment", "attachment"),
        ("escape-output", "output directory"),
        pytest.param(
            "extended-output",
            "output directory",
            marks=pytest.mark.skipif(
                os.name != "nt", reason="Native Windows extended-path admission requires Windows"
            ),
        ),
        ("missing-output", "output directory"),
        ("linked-output", "reparse"),
        ("ancestor-reparse", "reparse"),
        ("forward-slash-linked-output", "reparse"),
        ("forward-slash-ancestor-reparse", "reparse"),
        ("missing-metadata", "metadata is unavailable"),
        ("changed-source", "source bytes changed"),
        ("changed-inventory", "source inventory changed"),
    ],
)
def test_retention_rejection_stops_next_invocation_and_preserves_failure(
    tmp_path: Path,
    shell: str,
    case: str,
    fragment: str,
) -> None:
    result, evidence = _run(tmp_path, shell, case)
    assert fragment in result["rejected"], result
    invocations = (tmp_path / "candidate/invocations.jsonl").read_text().splitlines()
    assert len(invocations) == 1, "a later call could erase rejected evidence"
    assert not list(evidence.glob("*.completion.json"))
    assert not list(evidence.glob("*.artifacts/manifest.json")), (
        "a partial copy was published as complete"
    )
    failure = _read(next(evidence.glob("*.retention-failed.json")))
    assert failure["event"] == "artifact_retention_failed"
    assert failure["release_sha"] == "1" * 40
    if case in {"ancestor-reparse", "forward-slash-ancestor-reparse"}:
        assert (tmp_path / "candidate/parent-target/results").is_dir()
        link = tmp_path / "candidate/linked-parent"
        assert link.is_symlink() or link.is_junction()
    else:
        assert (tmp_path / "candidate/test-results").exists() or case == "missing-output"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("case", ["failed", "empty", "malformed-json"])
def test_unsuccessful_execution_is_retained_without_false_success(
    tmp_path: Path,
    shell: str,
    case: str,
) -> None:
    result, evidence = _run(tmp_path, shell, case)
    assert result["rejected"], result
    assert len((tmp_path / "candidate/invocations.jsonl").read_text().splitlines()) == 1
    manifests = list(evidence.glob("*.artifacts/manifest.json"))
    assert len(manifests) == 1
    assert len(_read(manifests[0])["files"]) == 15
    completions = list(evidence.glob("*.completion.json"))
    if case == "failed":
        assert len(completions) == 1 and _read(completions[0])["exit_code"] == 7
    else:
        assert not completions, "invalid/empty execution must not claim completion"


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("case", ["custom-output", "multiple-output"])
def test_selected_projects_retain_nondefault_and_multiple_outputs(
    tmp_path: Path,
    shell: str,
    case: str,
) -> None:
    result, evidence = _run(tmp_path, shell, case)
    assert result["rejected"] is None, result
    completions = list(evidence.glob("*.completion.json"))
    assert len(completions) == 3
    for path in completions:
        completion = _read(path)
        manifest_path = Path(completion["artifacts_manifest"])
        manifest = _read(manifest_path)
        expected_files = 16 if case == "multiple-output" else 15
        assert len(manifest["files"]) == expected_files
        assert completion["tests"] == (2 if case == "multiple-output" else 1)
        assert len(manifest["attachments"]) == (7 if case == "multiple-output" else 6)
        assert all("absent-unused" not in directory for directory in manifest["output_directories"])
        for file in manifest["files"]:
            assert _hash(manifest_path.parent / file["retained_path"]) == file["sha256"]
        roots = {file["relative_path"].split("/")[0] for file in manifest["files"]}
        assert roots == (
            {"test-results", "second-results"}
            if case == "multiple-output"
            else {"custom-results", "test-results"}
        )


@pytest.mark.parametrize("shell", SHELLS)
def test_empty_discovery_is_rejected_before_any_execution(tmp_path: Path, shell: str) -> None:
    result, evidence = _run(tmp_path, shell, "empty-discovery")
    assert "selection is empty" in result["rejected"]
    assert not (tmp_path / "candidate/invocations.jsonl").exists()
    assert not list(evidence.glob("*.completion.json"))


@pytest.mark.parametrize("shell", SHELLS)
def test_existing_launcher_contract_still_passes_without_guard_edits(
    tmp_path: Path, shell: str
) -> None:
    executable = shutil.which(shell)
    assert executable and shutil.which("node"), (
        "CI needs pwsh and node for offline launcher coverage"
    )
    process = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO / "tests/docker-acceptance-repo-root-guard.ps1"),
        ],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    (tmp_path / "stdout.bin").write_bytes(process.stdout)
    (tmp_path / "stderr.bin").write_bytes(process.stderr)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert b"repository-root guard: 54 regression cases passed" in process.stdout
