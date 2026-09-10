param([string]$Label = 'v2')
$ErrorActionPreference = 'Stop'
if ($Label -notmatch '^v[0-9]+$') { throw 'Use a versioned label.' }
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$evidence = 'docs/ip-implementation/evidence/other-ip-domain-workflows-2026-09-10-v2'
$priorPath = 'docs/ip-implementation/evidence/other-ip-resume-2026-09-10/owned-files-final.json'
$priorHash = '571f1978e684c01bbb676c119c46fe5eca2f02f2159dc28de6c1a7a6d5e2ee09'
if ((Get-FileHash -LiteralPath (Join-Path $root $priorPath)).Hash.ToLowerInvariant() -ne $priorHash) { throw 'Predecessor manifest changed.' }
$prior = Get-Content -Raw -LiteralPath (Join-Path $root $priorPath) | ConvertFrom-Json
$additions = @(
    'apps/api/tests/test_ip_specialist_layout.py',
    'apps/api/tests/test_ip_specialist_layout_postgres.py',
    'apps/web/components/ip/SpecialistLayoutWorkflows.test.tsx',
    'docs/ip-implementation/child-prds/semiconductor_layout-2026-09-10.md',
    'scripts/tests/run-other-ip-next-container.sh',
    'scripts/tests/run-other-ip-next-pg.ps1',
    'scripts/tests/run-other-ip-next-web.sh',
    'scripts/tests/freeze-other-ip-handoff.ps1',
    "$evidence/HANDOFF.md"
)
$rows = foreach ($path in @($prior.files.path + $additions) | Sort-Object -Unique) {
    $previous = @($prior.files | Where-Object path -eq $path)
    $file = Get-Item -LiteralPath (Join-Path $root $path)
    $hash = (Get-FileHash -LiteralPath $file.FullName).Hash.ToLowerInvariant()
    $ownership = if ($previous.Count) { $previous[0].ownership } else { 'owned_file' }
    $changed = -not $previous.Count -or $previous[0].sha256 -ne $hash
    if ($ownership -ne 'owned_file' -and $changed) { throw "V2 cannot add shared or catalog edits: $path" }
    [ordered]@{path=$path; ownership=$ownership; bytes=$file.Length; sha256=$hash
        predecessor_sha256=$(if ($previous.Count) { $previous[0].sha256 } else { $null }); changed_since_predecessor=$changed}
}
$artifacts = foreach ($file in Get-ChildItem -LiteralPath (Join-Path $root $evidence) -File | Sort-Object Name) {
    # Active journals are deliberately excluded: their changing bytes cannot be frozen evidence.
    if ($file.Name -notmatch '^(foundation-0[12]|layout-0[34]|web-0[12])[-.]') { continue }
    [ordered]@{path="$evidence/$($file.Name)"; bytes=$file.Length; sha256=(Get-FileHash -LiteralPath $file.FullName).Hash.ToLowerInvariant()}
}
$manifest = [ordered]@{
    schema_version=3; version=$Label; captured_at_utc=[DateTime]::UtcNow.ToString('o'); worktree=$root
    base_commit=(& git -C $root rev-parse HEAD); status='FROZEN_FOR_REVIEW_NOT_RELEASE_ACCEPTANCE'
    predecessor=@{path=$priorPath; sha256=$priorHash; unchanged=$true}
    integration_rule='Owned files and predecessor specialist shared hunks only. V2 adds zero shared production hunks. Never copy a whole worktree over the newer parent. Patent agent owns final catalog; parent owns reserved migration 0005 chain.'
    files=@($rows); changed_or_new_owned_files=@($rows | Where-Object { $_.ownership -eq 'owned_file' -and $_.changed_since_predecessor })
    new_shared_hunks=@(); patent_catalog_unchanged=$true; completed_attempt_artifacts=@($artifacts)
    in_progress_excluded=@('backend-05: incomplete until complete structured replacement inventory is reconciled')
    missing_at_freeze=@('Green complete V2 PG replacement inventory','Current full Vitest replacement','Playwright execution and screenshots','Parent-integrated migration/catalog acceptance','Serving revision and production acceptance')
}
$target = Join-Path $root "$evidence/owned-files-final-$Label.json"
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew)
try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($manifest | ConvertTo-Json -Depth 7) + "`n")
    $stream.Write($bytes, 0, $bytes.Length)
} finally { $stream.Dispose() }
Get-FileHash -LiteralPath $target -Algorithm SHA256
Write-Output "$($rows.Count) files; $(@($manifest.changed_or_new_owned_files).Count) changed/new owned files; zero new shared hunks."
