#Requires -Version 5.1
# Canonical backend verification (Windows PowerShell variant).
# Same goal as scripts/verify-backend.sh — see that file for rationale.
#
# Usage:
#   ./scripts/verify-backend.ps1                    # full backend suite
#   ./scripts/verify-backend.ps1 tests/test_intake.py
#   ./scripts/verify-backend.ps1 -k "reminders or intake"
#
# QG-REL-001 (P0-002, 2026-04-24): the previous version embedded a
# Python sanity check as a here-string passed to ``python -c``.
# PowerShell 5.1's parser was unhappy with that combination on this
# workspace and the script aborted before lint/pytest ran. The check
# now lives in ``scripts/_backend_sanity_check.py`` and is invoked
# as a real script file, which removes every quoting/parsing
# ambiguity. Failure messages identify the stage explicitly so an
# agent reading the output can tell bootstrap apart from sanity, ruff,
# and pytest failures.

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$ApiDir = Join-Path $RepoRoot "apps\api"
$SanityScript = Join-Path $PSScriptRoot "_backend_sanity_check.py"
Set-Location $ApiDir

$VenvPy = Join-Path $ApiDir ".venv\Scripts\python.exe"
$VenvPytest = Join-Path $ApiDir ".venv\Scripts\pytest.exe"
$VenvRuff = Join-Path $ApiDir ".venv\Scripts\ruff.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "[verify-backend] venv missing - bootstrapping with uv sync --frozen"
    & uv sync --frozen --no-install-project
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[verify-backend] STAGE=bootstrap exit=$LASTEXITCODE"
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path $SanityScript)) {
    Write-Host "[verify-backend] STAGE=sanity FATAL: $SanityScript missing"
    exit 2
}

& $VenvPy $SanityScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "[verify-backend] STAGE=sanity exit=$LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "[verify-backend] running ruff"
& $VenvRuff check src tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[verify-backend] STAGE=ruff exit=$LASTEXITCODE"
    exit $LASTEXITCODE
}

if ($args.Count -eq 0) {
    Write-Host "[verify-backend] running pytest (full backend suite)"
} else {
    Write-Host "[verify-backend] running pytest $args"
}
& $VenvPytest @args
$pytestExit = $LASTEXITCODE
if ($pytestExit -ne 0) {
    Write-Host "[verify-backend] STAGE=pytest exit=$pytestExit"
}
exit $pytestExit
