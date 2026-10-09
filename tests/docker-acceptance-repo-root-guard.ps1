#Requires -Version 5.1
# Executes the Docker acceptance harness's own Playwright launcher and suite
# preflight from a foreign working directory that holds a decoy config and a
# decoy Playwright CLI. On 2026-09-28 the harness ran another checkout's
# browser suite because Playwright resolved its config from the caller's
# working directory.
[CmdletBinding()]
param([string]$ScriptPath)

$ErrorActionPreference = "Stop"
# Windows PowerShell leaves $PSScriptRoot empty in param defaults under -File.
if (-not $ScriptPath) {
    $ScriptPath = [IO.Path]::Combine(
        (Split-Path -Parent $MyInvocation.MyCommand.Path), "..", "scripts", "verify-docker.ps1"
    )
}
$Tokens = $null
$ParseErrors = $null
$Ast = [Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $ScriptPath).Path, [ref]$Tokens, [ref]$ParseErrors
)
if ($ParseErrors.Count) { throw "Docker acceptance script has PowerShell parse errors." }
foreach ($FunctionName in @(
    "Test-PathWithinRoot", "Assert-CandidatePlaywrightSuite", "Invoke-CandidatePlaywright"
)) {
    $Definitions = @($Ast.FindAll({
        param($Node)
        $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $Node.Name -eq $FunctionName
    }, $true))
    if ($Definitions.Count -ne 1) { throw "Expected one $FunctionName in the Docker acceptance script." }
    . ([scriptblock]::Create($Definitions[0].Extent.Text))
}

function Test-SamePath([string]$Left, [string]$Right) {
    $Comparison = if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        [StringComparison]::OrdinalIgnoreCase
    } else {
        [StringComparison]::Ordinal
    }
    return [string]::Equals(
        [IO.Path]::GetFullPath($Left).TrimEnd([char[]]"\/"),
        [IO.Path]::GetFullPath($Right).TrimEnd([char[]]"\/"),
        $Comparison
    )
}

$NodePath = (Get-Command node -ErrorAction Stop).Source
$Work = [IO.Path]::Combine([IO.Path]::GetTempPath(), "caseops-repo-root-guard-" + [Guid]::NewGuid().ToString("N"))
$RepoRoot = [IO.Path]::Combine($Work, "candidate")
$Foreign = [IO.Path]::Combine($Work, "foreign")
$ResultsDirectory = [IO.Path]::Combine($Work, "results")
$PlaywrightConfig = [IO.Path]::Combine($RepoRoot, "playwright.docker.config.ts")
$PlaywrightCli = [IO.Path]::Combine($RepoRoot, "node_modules", "@playwright", "test", "cli.js")
$CandidatePython = [IO.Path]::Combine($RepoRoot, "apps", "api", ".venv", "python")
$ForeignPython = [IO.Path]::Combine($Foreign, "apps", "api", ".venv", "python")
$DecoyMarker = [IO.Path]::Combine($Work, "decoy-used.txt")
$InvocationLog = [IO.Path]::Combine($Work, "invocations.jsonl")

$CandidateCli = @'
const fs = require("fs");
const path = require("path");
const args = process.argv.slice(2);
fs.appendFileSync(
  process.env.CASEOPS_GUARD_LOG,
  JSON.stringify({ cli: __filename, cwd: process.cwd(), args,
    json: process.env.PLAYWRIGHT_JSON_OUTPUT_FILE,
    junit: process.env.PLAYWRIGHT_JUNIT_OUTPUT_FILE }) + "\n",
);
if (args.includes("--list")) {
  const mode = process.env.CASEOPS_GUARD_MODE || "candidate";
  const config = args[args.indexOf("--config") + 1];
  const candidate = path.dirname(config);
  const foreign = path.resolve(candidate, "..", "foreign");
  const slash = (value) => value.split(path.sep).join("/");
  const rootDir = slash(path.join(mode === "foreign-root" ? foreign : candidate, "tests", "e2e"));
  const specFile = mode === "foreign-spec" ? "../../../foreign/tests/e2e/decoy.spec.ts" : "candidate.spec.ts";
  const listing = JSON.stringify({
    config: {
      configFile: mode === "foreign-config" ? path.join(foreign, "playwright.docker.config.ts") : config,
      rootDir,
      projects: [{ name: "app-chromium", testDir: rootDir }],
    },
    suites: mode === "empty" ? [] : [{
      title: specFile,
      file: specFile,
      specs: [{ title: "runs from the candidate" }],
      suites: [],
    }],
    errors: mode === "load-error" ? [{ message: "spec failed to load" }] : [],
  });
  const output = process.env.PLAYWRIGHT_JSON_OUTPUT_FILE ||
    (process.env.PLAYWRIGHT_JSON_OUTPUT_NAME && path.resolve(
      process.env.PLAYWRIGHT_JSON_OUTPUT_DIR || process.cwd(), process.env.PLAYWRIGHT_JSON_OUTPUT_NAME));
  if (output) fs.writeFileSync(output, listing);
  else process.stdout.write(listing);
} else {
  const mode = process.env.CASEOPS_GUARD_MODE || "candidate";
  const report = {
    suites: mode === "empty-execution" ? [] : [{ specs: [{ tests: [{
      results: mode === "missing-result" ? [] : [{ status: "passed" }],
    }] }] }],
    errors: [],
    stats: { expected: mode === "empty-execution" ? 0 : 1, unexpected: 0, skipped: 0, flaky: 0 },
  };
  if (mode === "unexpected-pass") {
    report.stats.expected = 0;
    report.stats.unexpected = 1;
  }
  if (mode === "interrupted-result" || mode === "invalid-result") {
    report.suites[0].specs[0].tests[0].results[0].status =
      mode === "interrupted-result" ? "interrupted" : "unknown";
  }
  if (mode !== "missing-json") {
    fs.writeFileSync(process.env.PLAYWRIGHT_JSON_OUTPUT_FILE,
      mode === "malformed-json" ? "{" : JSON.stringify(report));
  }
  if (mode !== "missing-xml") {
    const cases = mode === "empty-execution" || mode === "inconsistent-count"
      ? "" : '<testcase classname="candidate.spec.ts" name="candidate"/>';
    fs.writeFileSync(process.env.PLAYWRIGHT_JUNIT_OUTPUT_FILE,
      mode === "malformed-xml" ? "<testsuites>" : `<testsuites><testsuite>${cases}</testsuite></testsuites>`);
  }
}
process.exit(Number(process.env.CASEOPS_GUARD_EXIT || 0));
'@
$DecoyCli = @'
require("fs").writeFileSync(process.env.CASEOPS_GUARD_DECOY, process.argv.slice(2).join(" "));
process.exit(1);
'@

$GuardVariables = @(
    "CASEOPS_E2E_PYTHON", "CASEOPS_GUARD_LOG", "CASEOPS_GUARD_MODE",
    "CASEOPS_GUARD_EXIT", "CASEOPS_GUARD_DECOY", "PLAYWRIGHT_JSON_OUTPUT_FILE",
    "PLAYWRIGHT_JUNIT_OUTPUT_FILE", "PLAYWRIGHT_JSON_OUTPUT_DIR", "PLAYWRIGHT_JSON_OUTPUT_NAME"
)
$SavedEnvironment = @{}
foreach ($Name in $GuardVariables) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}
$SavedCurrentDirectory = [Environment]::CurrentDirectory
$Cases = 0

function Assert-Refused([string]$Fragment, [scriptblock]$Action) {
    $Refused = $false
    try { & $Action }
    catch {
        if ($_.Exception.Message -notlike "*$Fragment*") { throw }
        $Refused = $true
    }
    if (-not $Refused) { throw "Expected the candidate guard to refuse with '$Fragment'." }
    if (Test-Path -LiteralPath $DecoyMarker) { throw "The foreign Playwright CLI was executed." }
    $script:Cases++
}

try {
    foreach ($Directory in @(
        [IO.Path]::GetDirectoryName($PlaywrightCli),
        [IO.Path]::GetDirectoryName($CandidatePython),
        [IO.Path]::Combine($Foreign, "node_modules", "@playwright", "test"),
        [IO.Path]::GetDirectoryName($ForeignPython),
        $ResultsDirectory
    )) {
        [void](New-Item -ItemType Directory -Force -Path $Directory)
    }
    [IO.File]::WriteAllText($PlaywrightConfig, "// candidate config")
    [IO.File]::WriteAllText($PlaywrightCli, $CandidateCli)
    [IO.File]::WriteAllText($CandidatePython, "")
    [IO.File]::WriteAllText([IO.Path]::Combine($Foreign, "playwright.docker.config.ts"), "// decoy config")
    [IO.File]::WriteAllText(
        [IO.Path]::Combine($Foreign, "node_modules", "@playwright", "test", "cli.js"), $DecoyCli
    )
    [IO.File]::WriteAllText($ForeignPython, "")
    [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_LOG", $InvocationLog, "Process")
    [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_DECOY", $DecoyMarker, "Process")
    [Environment]::SetEnvironmentVariable("CASEOPS_E2E_PYTHON", $CandidatePython, "Process")
    foreach ($Name in @("PLAYWRIGHT_JSON_OUTPUT_FILE", "PLAYWRIGHT_JSON_OUTPUT_DIR", "PLAYWRIGHT_JSON_OUTPUT_NAME")) {
        [Environment]::SetEnvironmentVariable($Name, $null, "Process")
    }

    # Launch from the foreign checkout, as the 2026-09-28 run did.
    Push-Location -LiteralPath $Foreign
    [Environment]::CurrentDirectory = $Foreign
    try {
        Assert-CandidatePlaywrightSuite -Arguments @()
        Invoke-CandidatePlaywright -Arguments @("--project=app-chromium", "--shard=1/2")
        if ($LASTEXITCODE -ne 0) { throw "The candidate Playwright CLI did not run cleanly." }
        if (-not (Test-SamePath (Get-Location).Path $Foreign)) {
            throw "The launcher did not restore the caller's location."
        }
        $Invocations = @(Get-Content -LiteralPath $InvocationLog | ForEach-Object { $_ | ConvertFrom-Json })
        if ($Invocations.Count -ne 2) { throw "Expected one listing and one test run." }
        foreach ($Invocation in $Invocations) {
            if (-not (Test-SamePath $Invocation.cli $PlaywrightCli)) {
                throw "Playwright ran from $($Invocation.cli), not the candidate."
            }
            if (-not (Test-SamePath $Invocation.cwd $RepoRoot)) {
                throw "Playwright ran in $($Invocation.cwd), not the candidate root."
            }
            $Arguments = @($Invocation.args)
            $ConfigIndex = [Array]::IndexOf($Arguments, "--config")
            if ($ConfigIndex -lt 0 -or -not (Test-SamePath $Arguments[$ConfigIndex + 1] $PlaywrightConfig)) {
                throw "Playwright did not receive the candidate config by absolute path."
            }
        }
        if (($Invocations[1].args -join " ") -notlike "*--project=app-chromium --shard=1/2") {
            throw "The launcher did not forward the shard selection."
        }
        if (-not (Test-Path -LiteralPath ([IO.Path]::Combine($ResultsDirectory, "playwright-inventory.json")))) {
            throw "The suite preflight did not retain its inventory."
        }
        if (Test-Path -LiteralPath $DecoyMarker) { throw "The foreign Playwright CLI was executed." }
        $Cases++

        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JSON_OUTPUT_FILE", "caller-json", "Process")
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JUNIT_OUTPUT_FILE", "caller-xml", "Process")
        Invoke-CandidatePlaywright -Arguments @("--project=app-chromium", "--shard=2/2")
        $BrowserInvocations = @(Get-Content -LiteralPath $InvocationLog |
            ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.args -notcontains "--list" })
        if ($BrowserInvocations.Count -ne 2 -or $BrowserInvocations[0].json -eq $BrowserInvocations[1].json) {
            throw "Browser invocations did not retain unique report files."
        }
        foreach ($Invocation in $BrowserInvocations) {
            if ($Invocation.args -notcontains "--reporter=list,json,junit") {
                throw "The launcher omitted required structured reporters."
            }
            $Completion = Get-Content -LiteralPath ($Invocation.json -replace '\.json$', '.completion.json') -Raw |
                ConvertFrom-Json
            if ($Completion.event -ne "execution_finished" -or $Completion.tests -ne 1 -or $Completion.exit_code -ne 0) {
                throw "The launcher did not retain successful nonempty completion."
            }
        }
        if ($env:PLAYWRIGHT_JSON_OUTPUT_FILE -ne "caller-json" -or $env:PLAYWRIGHT_JUNIT_OUTPUT_FILE -ne "caller-xml") {
            throw "The launcher did not restore the caller's reporter environment."
        }
        $Cases++
        foreach ($Case in @(
            @{ Mode = "missing-json"; Fragment = "missing report" },
            @{ Mode = "missing-xml"; Fragment = "missing report" },
            @{ Mode = "malformed-json"; Fragment = "JSON" },
            @{ Mode = "malformed-xml"; Fragment = "invalid XML report" },
            @{ Mode = "empty-execution"; Fragment = "empty or disagreeing" },
            @{ Mode = "missing-result"; Fragment = "selected test has no result" },
            @{ Mode = "interrupted-result"; Fragment = "invalid or interrupted" },
            @{ Mode = "invalid-result"; Fragment = "invalid or interrupted" },
            @{ Mode = "inconsistent-count"; Fragment = "empty or disagreeing" },
            @{ Mode = "unexpected-pass"; Fragment = "exit zero disagrees" }
        )) {
            [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_MODE", $Case.Mode, "Process")
            Assert-Refused $Case.Fragment { Invoke-CandidatePlaywright -Arguments @("--project=app-mobile") }
            $LastInvocation = Get-Content -LiteralPath $InvocationLog -Tail 1 | ConvertFrom-Json
            if (Test-Path -LiteralPath ($LastInvocation.json -replace '\.json$', '.completion.json')) {
                throw "An incomplete/invalid browser run was given a completion record."
            }
            if ($env:PLAYWRIGHT_JSON_OUTPUT_FILE -ne "caller-json" -or $env:PLAYWRIGHT_JUNIT_OUTPUT_FILE -ne "caller-xml") {
                throw "A rejected invocation did not restore the reporter environment."
            }
        }
        [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_MODE", $null, "Process")
        Assert-Refused "owns its structured" { Invoke-CandidatePlaywright -Arguments @("--reporter=list") }
        [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_EXIT", "7", "Process")
        Invoke-CandidatePlaywright -Arguments @("--project=app-mobile")
        if ($LASTEXITCODE -ne 7) { throw "The launcher discarded the browser process failure." }
        $LastInvocation = Get-Content -LiteralPath $InvocationLog -Tail 1 | ConvertFrom-Json
        $FailedCompletion = Get-Content -LiteralPath ($LastInvocation.json -replace '\.json$', '.completion.json') -Raw |
            ConvertFrom-Json
        if ($FailedCompletion.exit_code -ne 7) { throw "The failed process was recorded as successful." }
        [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_EXIT", $null, "Process")
        $Cases++

        $CallerReport = Join-Path $Work "caller-report.json"
        [IO.File]::WriteAllText($CallerReport, "preserve caller evidence")
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JSON_OUTPUT_FILE", $CallerReport, "Process")
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JSON_OUTPUT_DIR", $Work, "Process")
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JSON_OUTPUT_NAME", "caller-name.json", "Process")
        Assert-CandidatePlaywrightSuite -Arguments @()
        if ([IO.File]::ReadAllText($CallerReport) -ne "preserve caller evidence" -or
            (Test-Path -LiteralPath (Join-Path $Work "caller-name.json")) -or
            $env:PLAYWRIGHT_JSON_OUTPUT_FILE -ne $CallerReport -or
            $env:PLAYWRIGHT_JSON_OUTPUT_DIR -ne $Work -or
            $env:PLAYWRIGHT_JSON_OUTPUT_NAME -ne "caller-name.json") {
            throw "Discovery overwrote caller evidence or failed to restore report settings."
        }
        $Cases++

        foreach ($Case in @(
            @{ Mode = "foreign-config"; Fragment = "Playwright resolved config" },
            @{ Mode = "foreign-root"; Fragment = "test directory" },
            @{ Mode = "foreign-spec"; Fragment = "listed spec" },
            @{ Mode = "empty"; Fragment = "selection is empty" },
            @{ Mode = "load-error"; Fragment = "load errors" }
        )) {
            [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_MODE", $Case.Mode, "Process")
            Assert-Refused $Case.Fragment { Assert-CandidatePlaywrightSuite -Arguments @() }
            if ($env:PLAYWRIGHT_JSON_OUTPUT_FILE -ne $CallerReport -or
                $env:PLAYWRIGHT_JSON_OUTPUT_DIR -ne $Work -or
                $env:PLAYWRIGHT_JSON_OUTPUT_NAME -ne "caller-name.json") {
                throw "Rejected discovery leaked reporter settings."
            }
        }
        [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_MODE", $null, "Process")
        [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_EXIT", "1", "Process")
        Assert-Refused "Could not list" { Assert-CandidatePlaywrightSuite -Arguments @() }
        [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_EXIT", $null, "Process")

        [Environment]::SetEnvironmentVariable("CASEOPS_E2E_PYTHON", $ForeignPython, "Process")
        Assert-Refused "Python outside the candidate" { Assert-CandidatePlaywrightSuite -Arguments @() }
        [Environment]::SetEnvironmentVariable("CASEOPS_E2E_PYTHON", $null, "Process")
        Assert-Refused "Python outside the candidate" { Assert-CandidatePlaywrightSuite -Arguments @() }
        [Environment]::SetEnvironmentVariable("CASEOPS_E2E_PYTHON", $CandidatePython, "Process")

        # Without the candidate's own Playwright nothing may fall back to the decoy.
        if (-not (Test-PathWithinRoot -Path $PlaywrightCli -Root $Work)) {
            throw "The isolated CLI move escaped its test root."
        }
        Move-Item -LiteralPath $PlaywrightCli -Destination "$PlaywrightCli.missing"
        Assert-Refused "not installed" { Assert-CandidatePlaywrightSuite -Arguments @() }
        Move-Item -LiteralPath "$PlaywrightCli.missing" -Destination $PlaywrightCli

        foreach ($Outside in @(
            "$RepoRoot-evil$([IO.Path]::DirectorySeparatorChar)spec.ts",
            [IO.Path]::Combine($RepoRoot, "..", "foreign", "spec.ts"),
            "tests$([IO.Path]::DirectorySeparatorChar)e2e",
            ""
        )) {
            if (Test-PathWithinRoot -Path $Outside -Root $RepoRoot) {
                throw "'$Outside' was accepted as inside the candidate."
            }
            $Cases++
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    [Environment]::CurrentDirectory = $SavedCurrentDirectory
    foreach ($Name in $GuardVariables) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], "Process")
    }
    if (Test-Path -LiteralPath $Work) {
        $ResolvedWork = (Resolve-Path -LiteralPath $Work).Path
        if (-not (Test-SamePath ([IO.Path]::GetDirectoryName($ResolvedWork)) ([IO.Path]::GetTempPath())) -or
            [IO.Path]::GetFileName($ResolvedWork) -notmatch '^caseops-repo-root-guard-[a-f0-9]{32}$') {
            throw "Refusing cleanup outside the isolated guard directory."
        }
        Remove-Item -LiteralPath $ResolvedWork -Recurse -Force
    }
}
Write-Host "[docker-acceptance] repository-root guard: $Cases regression cases passed"
