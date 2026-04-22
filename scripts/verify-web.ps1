#Requires -Version 5.1
# Canonical web verification (PowerShell). Same goal as
# scripts/verify-web.sh — rebuild Next.js FIRST so Playwright sees
# the current source, not a stale bundle.
#
# Usage:
#   ./scripts/verify-web.ps1
#   ./scripts/verify-web.ps1 -Quick           # skip build + Playwright
#   ./scripts/verify-web.ps1 -E2EOnly -g "BUG-011"

[CmdletBinding(PositionalBinding=$false)]
param(
    [switch]$Quick,
    [switch]$E2EOnly,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$PlaywrightArgs = @()
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$WebDir = Join-Path $RepoRoot "apps\web"
Set-Location $WebDir

if (-not $E2EOnly) {
    Write-Host "[verify-web] vitest"
    & npx vitest run --reporter=dot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "[verify-web] tsc --noEmit"
    & npx tsc --noEmit
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Quick) {
    Write-Host "[verify-web] -Quick set; skipping build + Playwright"
    exit 0
}

# REBUILD-FIRST is the whole point of this script.
Write-Host "[verify-web] npm run build (mandatory; prevents stale-bundle false negatives)"
& npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Set-Location $RepoRoot
Write-Host "[verify-web] Playwright app suite $PlaywrightArgs"
& npx playwright test --config playwright.app.config.ts @PlaywrightArgs
exit $LASTEXITCODE
