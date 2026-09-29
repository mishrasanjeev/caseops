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
  JSON.stringify({ cli: __filename, cwd: process.cwd(), args }) + "\n",
);
if (args.includes("--list")) {
  const mode = process.env.CASEOPS_GUARD_MODE || "candidate";
  const config = args[args.indexOf("--config") + 1];
  const candidate = path.dirname(config);
  const foreign = path.resolve(candidate, "..", "foreign");
  const slash = (value) => value.split(path.sep).join("/");
  const rootDir = slash(path.join(mode === "foreign-root" ? foreign : candidate, "tests", "e2e"));
  const specFile = mode === "foreign-spec" ? "../../../foreign/tests/e2e/decoy.spec.ts" : "candidate.spec.ts";
  process.stdout.write(JSON.stringify({
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
  }));
}
process.exit(Number(process.env.CASEOPS_GUARD_EXIT || 0));
'@
$DecoyCli = @'
require("fs").writeFileSync(process.env.CASEOPS_GUARD_DECOY, process.argv.slice(2).join(" "));
process.exit(1);
'@

$GuardVariables = @(
    "CASEOPS_E2E_PYTHON", "CASEOPS_GUARD_LOG", "CASEOPS_GUARD_MODE",
    "CASEOPS_GUARD_EXIT", "CASEOPS_GUARD_DECOY"
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

        foreach ($Case in @(
            @{ Mode = "foreign-config"; Fragment = "Playwright resolved config" },
            @{ Mode = "foreign-root"; Fragment = "test directory" },
            @{ Mode = "foreign-spec"; Fragment = "listed spec" },
            @{ Mode = "empty"; Fragment = "selection is empty" },
            @{ Mode = "load-error"; Fragment = "load errors" }
        )) {
            [Environment]::SetEnvironmentVariable("CASEOPS_GUARD_MODE", $Case.Mode, "Process")
            Assert-Refused $Case.Fragment { Assert-CandidatePlaywrightSuite -Arguments @() }
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
    if (Test-Path -LiteralPath $Work) { Remove-Item -LiteralPath $Work -Recurse -Force }
}
Write-Host "[docker-acceptance] repository-root guard: $Cases regression cases passed"
