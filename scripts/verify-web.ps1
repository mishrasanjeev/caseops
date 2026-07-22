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
# Next.js resolves NEXT_PUBLIC_* values at build time.  A developer's
# .env.local may intentionally point at localhost, but the canonical marketing
# assertions verify production canonical/OG URLs.  The API origin must also be
# pinned here: setting it only on `next start` leaves the browser bundle baked
# with the default `http://localhost:8000`, while the e2e CSP permits the
# canonical `http://127.0.0.1:<port>` origin.
$E2EApiPort = if ([string]::IsNullOrWhiteSpace($env:CASEOPS_E2E_API_PORT)) {
    "8000"
} else {
    $env:CASEOPS_E2E_API_PORT
}
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:$E2EApiPort"
$env:NEXT_PUBLIC_SITE_URL = "https://caseops.ai"
$env:NEXT_PUBLIC_APP_URL = "https://caseops.ai/app"
& npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Set-Location $RepoRoot
Write-Host "[verify-web] Playwright app suite $PlaywrightArgs"
& npx playwright test --config playwright.app.config.ts @PlaywrightArgs
exit $LASTEXITCODE
