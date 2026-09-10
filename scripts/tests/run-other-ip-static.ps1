param([Parameter(Mandatory=$true)][string]$Label)
$ErrorActionPreference = 'Stop'
if ($Label -notmatch '^[a-z0-9-]+$') { throw 'Use a unique simple label.' }
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$output = Join-Path $root 'docs/ip-implementation/evidence/other-ip-resume-2026-09-10'
$journal = Join-Path $output "$Label.jsonl"
$stream = [IO.File]::Open($journal, [IO.FileMode]::CreateNew)
$writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
$writer.AutoFlush = $true
$env:PYTHONDONTWRITEBYTECODE = '1'

function Invoke-Check([string]$Name, [string]$Directory, [string]$Executable, [string[]]$Arguments) {
    $log = Join-Path $output "$Label-$Name.log"
    $empty = [IO.File]::Open($log, [IO.FileMode]::CreateNew)
    $empty.Dispose()
    $writer.WriteLine((@{event='started'; name=$Name; cwd=$Directory; executable=$Executable; arguments=$Arguments} | ConvertTo-Json -Compress))
    $watch = [Diagnostics.Stopwatch]::StartNew()
    Push-Location $Directory
    try {
        & $Executable @Arguments 2>&1 | Tee-Object -FilePath $log -Append
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    $writer.WriteLine((@{event='finished'; name=$Name; exit_code=$code; seconds=$watch.Elapsed.TotalSeconds; log=$log} | ConvertTo-Json -Compress))
    if ($code -ne 0) { throw "$Name failed with exit $code; prior evidence is retained." }
}

try {
    $tsc = Join-Path $root 'node_modules/typescript/bin/tsc'
    Invoke-Check 'web-types' $root 'node' @($tsc, '--noEmit', '--incremental', 'false', '--project', 'apps/web/tsconfig.json')
    Invoke-Check 'e2e-types' $root 'node' @($tsc, '--noEmit', '--incremental', 'false', '--project', 'tsconfig.e2e.json')
    $manifest = Get-Content -Raw (Join-Path $output 'pre-final-owned-files.json') | ConvertFrom-Json
    $backend = @($manifest.files | Where-Object { $_.ownership -eq 'owned_file' -and $_.path.StartsWith('apps/api/') -and $_.path.EndsWith('.py') } | ForEach-Object path)
    Invoke-Check 'ruff' $root 'C:/Projects/CaseOps/caseops/apps/api/.venv/Scripts/ruff.exe' (@('check', '--no-cache') + $backend)
    $shared = @($manifest.files | Where-Object ownership -eq 'shared_hunks_only' | ForEach-Object path)
    Invoke-Check 'diff-check' $root 'git' (@('diff', '--check', '--') + $backend + $shared)
    Invoke-Check 'playwright-discovery-only' $root 'node' @('node_modules/@playwright/test/cli.js', 'test', '--config=playwright.app.config.ts', '--list', 'tests/e2e/iplf-090a-other-ip-domains-2026-09-09.spec.ts', 'tests/e2e/iplf-090b-other-ip-workflows-2026-09-10.spec.ts')
    $writer.WriteLine((@{event='session_finished'; exit_code=0} | ConvertTo-Json -Compress))
} finally { $writer.Dispose() }
