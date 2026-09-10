param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$target = [IO.Path]::GetFullPath((Join-Path $root $OutputPath))
if (-not $target.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Evidence output must remain in the owned worktree.'
}
$owned = @(
    'apps/api/alembic/versions/20260909_0005_specialist_intake.py',
    'apps/api/src/caseops_api/db/ip_specialist_models.py',
    'docs/ip-implementation/evidence/other-ip-domains-closure-2026-09-09.md',
    'docs/ip-implementation/evidence/other-ip-resume-2026-09-10/README.md'
)
$patterns = @{
    'apps/api/src/caseops_api/api/routes' = 'ip_specialist*.py'
    'apps/api/src/caseops_api/schemas' = 'ip_specialist*.py'
    'apps/api/src/caseops_api/services' = 'ip_specialist*.py'
    'apps/api/tests' = 'test_ip_specialist*.py'
    'apps/web/components/ip' = 'Specialist*.tsx'
    'apps/web/lib/api' = 'ip-specialist*.ts'
    'docs/ip-implementation/child-prds' = '*-2026-09-*.md'
    'scripts/tests' = '*other-ip*'
    'tests/e2e' = 'iplf-090*-other-ip*.spec.ts'
}
foreach ($folder in $patterns.Keys) {
    $owned += Get-ChildItem -LiteralPath (Join-Path $root $folder) -File |
        Where-Object { $_.Name -like $patterns[$folder] } |
        ForEach-Object { [IO.Path]::GetRelativePath($root, $_.FullName).Replace('\', '/') }
}
$owned += Get-ChildItem -LiteralPath (Join-Path $root 'apps/web/app/app/ip/specialist') -Recurse -File |
    ForEach-Object { [IO.Path]::GetRelativePath($root, $_.FullName).Replace('\', '/') }
$shared = @(
    'apps/api/src/caseops_api/db/models.py',
    'apps/api/src/caseops_api/api/router.py',
    'apps/api/src/caseops_api/services/ip_domain_policy.py',
    'apps/api/src/caseops_api/services/ip_document_workflow.py',
    'apps/api/src/caseops_api/services/matter_access.py',
    'apps/api/src/caseops_api/services/shared_work.py',
    'apps/web/app/app/ip/page.tsx',
    'docs/PRD_CODEX_2026-04-23.md',
    'docs/WORK_TO_BE_DONE.md',
    'docs/PRD_COVERAGE_MOD_TS_2026-04-20.md',
    'docs/STRICT_ENTERPRISE_GAP_TASKLIST.md',
    'docs/STRICT_BUG_TASKLIST_2026-04-22.md'
)
$rows = foreach ($path in @($owned + $shared + 'apps/api/src/caseops_api/services/ip_domain_catalog.py') | Sort-Object -Unique) {
    $file = Get-Item -LiteralPath (Join-Path $root $path)
    [ordered]@{
        path = $path
        ownership = if ($owned -contains $path) { 'owned_file' } elseif ($shared -contains $path) { 'shared_hunks_only' } else { 'patent_owned_do_not_copy' }
        bytes = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$artifacts = foreach ($file in Get-ChildItem -LiteralPath (Join-Path $root 'docs/ip-implementation/evidence/other-ip-resume-2026-09-10') -File | Sort-Object Name) {
    if ($file.Extension -notin @('.jsonl', '.xml', '.log')) { continue }
    [ordered]@{
        path = [IO.Path]::GetRelativePath($root, $file.FullName).Replace('\', '/')
        bytes = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$evidence = Join-Path $root 'docs/ip-implementation/evidence/other-ip-resume-2026-09-10'
$backend = @(Get-Content -LiteralPath (Join-Path $evidence 'backend-final-09.jsonl') | ConvertFrom-Json)
$identities = @($backend | Where-Object event -eq collection | ForEach-Object nodeids)
$intended = @('tests/test_ip_specialist.py', 'tests/test_ip_specialist_workflows.py',
    'tests/test_ip_specialist_performance.py', 'tests/test_ip_specialist_schema.py',
    'tests/test_ip_specialist_disclosure.py', 'tests/test_ip_domain_boundaries.py')
$collectedFiles = @($identities | ForEach-Object { ($_ -split '::')[0] } | Sort-Object -Unique)
if ($identities.Count -ne 64 -or @(Compare-Object $intended $collectedFiles).Count) { throw 'Final backend inventory mismatch.' }
$finished = @($backend | Where-Object event -eq session_finished)
if ($finished.Count -ne 1 -or $finished[0].exitstatus -ne 0) { throw 'Final backend completion not proven.' }
foreach ($id in $identities) {
    foreach ($phase in @('setup', 'call', 'teardown')) {
        $reports = @($backend | Where-Object { $_.event -eq 'test_report' -and $_.nodeid -eq $id -and $_.when -eq $phase })
        if ($reports.Count -ne 1 -or $reports[0].outcome -ne 'passed') { throw "Final backend phase is not a single pass: $id / $phase" }
    }
}
$replacements = foreach ($file in Get-ChildItem -LiteralPath $evidence -Filter '*.jsonl') {
    $events = @(Get-Content -LiteralPath $file.FullName | ConvertFrom-Json)
    $priorIds = @($events | Where-Object event -eq collection | ForEach-Object nodeids)
    if (-not $priorIds.Count) { continue }
    $missing = @($priorIds | Where-Object { $_ -notin $identities })
    if ($missing.Count) { throw "Replacement inventory omits tests from $($file.Name)." }
    [ordered]@{attempt=$file.Name; collected=$priorIds.Count; missing_from_final=$missing}
}
[xml]$web = Get-Content -Raw -LiteralPath (Join-Path $evidence 'web-reference-04.xml')
$webCases = @($web.SelectNodes('//testcase'))
if ($webCases.Count -ne 13 -or $web.SelectNodes('//failure | //error | //skipped').Count) { throw 'Final frontend inventory is not 13 passes.' }
$webIds = @($webCases | ForEach-Object { $_.GetAttribute('classname') + '::' + $_.GetAttribute('name') })
foreach ($file in Get-ChildItem -LiteralPath $evidence -Filter 'web*.xml') {
    [xml]$priorWeb = Get-Content -Raw -LiteralPath $file.FullName
    foreach ($case in $priorWeb.SelectNodes('//testcase')) {
        $id = $case.GetAttribute('classname') + '::' + $case.GetAttribute('name')
        if ($id -notin $webIds) { throw "Final web inventory omits $id from $($file.Name)." }
    }
}
$preFinal = Get-Content -Raw -LiteralPath (Join-Path $evidence 'pre-final-owned-files.json') | ConvertFrom-Json
$changedSinceBackend = @($preFinal.files | Where-Object { $_.path.StartsWith('apps/api/') -and (Get-FileHash -LiteralPath (Join-Path $root $_.path)).Hash.ToLowerInvariant() -ne $_.sha256 } | ForEach-Object path)
if ($changedSinceBackend.Count) { throw 'Backend source changed after its final test snapshot.' }
$baseline = Get-Content -Raw -LiteralPath (Join-Path $evidence 'baseline-owned-files.json') | ConvertFrom-Json
$catalog = $baseline.files | Where-Object ownership -eq 'patent_owned_do_not_copy'
if ((Get-FileHash -LiteralPath (Join-Path $root $catalog.path)).Hash.ToLowerInvariant() -ne $catalog.sha256) { throw 'Patent-owned catalog changed during resume.' }
$static = @(Get-Content -LiteralPath (Join-Path $evidence 'static-reference-04.jsonl') | ConvertFrom-Json)
$staticResults = @($static | Where-Object event -eq finished)
if ($staticResults.Count -ne 5 -or @($staticResults | Where-Object exit_code -ne 0).Count -or -not @($static | Where-Object event -eq session_finished).Count) { throw 'Final static checks are incomplete.' }
$manifest = [ordered]@{
    schema_version = 2
    captured_at_utc = [DateTime]::UtcNow.ToString('o')
    worktree = $root
    base_commit = (& git -C $root rev-parse HEAD)
    integration_rule = 'Apply owned files and reviewed specialist shared hunks only. Never copy this worktree snapshot over the parent. Patent agent owns ip_domain_catalog.py. Migration 0005 requires parent chain integration.'
    files = @($rows)
    verification_artifacts = @($artifacts)
    reconciliation = [ordered]@{
        backend_report = 'backend-final-09.jsonl'
        backend_nodeids = $identities
        backend_phase_passes = @{setup=64; call=64; teardown=64}
        backend_replacement_inventories = @($replacements)
        backend_source_unchanged_since_pre_final_snapshot = $true
        frontend_report = 'web-reference-04.xml'
        frontend_case_ids = $webIds
        all_earlier_frontend_case_ids_in_final = $true
        patent_catalog_unchanged_since_baseline = $true
        final_static_checks = $staticResults
        not_run = @('PostgreSQL workflow/migration/races', 'Docker acceptance', 'Playwright execution and visual QA', 'production acceptance')
    }
}
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
$stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew)
try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($manifest | ConvertTo-Json -Depth 6) + "`n")
    $stream.Write($bytes, 0, $bytes.Length)
} finally { $stream.Dispose() }
Write-Output "$($rows.Count) exact file hashes retained in $target"
