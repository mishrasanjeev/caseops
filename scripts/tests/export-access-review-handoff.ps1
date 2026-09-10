param([string]$Date = '2026-09-10')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$expectedRoot = 'C:\Projects\CaseOps\caseops\.worktrees\codex-ip-foundations-ops-closure-20260909'
if ($root -ne $expectedRoot) { throw 'This export is restricted to the isolated access-review worktree.' }
$evidence = Join-Path $root '.tmp/ip-access-review-evidence'
$baseline = Join-Path $evidence 'initial-feature-source'
$frozen = 'C:/tmp/caseops-foundations-handoff-20260910'
$output = Join-Path $root 'docs/ip-implementation/evidence'

function File-Proof([string]$path) {
    $file = Get-Item -LiteralPath $path
    return @{ sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant(); bytes = $file.Length }
}
function Write-JsonNew([string]$path, $value) {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($value | ConvertTo-Json -Depth 100) + "`n")
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew)
    try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
}

$owned = @(
    'apps/api/alembic/versions/20260910_0001_access_review_campaigns.py',
    'apps/api/src/caseops_api/api/router.py',
    'apps/api/src/caseops_api/api/routes/access_reviews.py',
    'apps/api/src/caseops_api/db/models.py',
    'apps/api/src/caseops_api/schemas/access_reviews.py',
    'apps/api/src/caseops_api/services/access_reviews.py',
    'apps/api/src/caseops_api/services/matter_access.py',
    'apps/api/src/caseops_api/services/teams.py',
    'apps/api/tests/test_20260910_access_reviews.py',
    'apps/api/tests/test_20260910_access_reviews_postgres.py',
    'apps/web/app/app/admin/page.tsx',
    'apps/web/app/app/admin/access-reviews/page.tsx',
    'apps/web/app/app/admin/access-reviews/page.test.tsx',
    'apps/web/lib/api/access-reviews.ts',
    'apps/web/lib/api/access-reviews.test.ts',
    'docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md',
    'docs/ip-implementation/evidence/ip-access-review-campaign-2026-09-10.md',
    'playwright.access-reviews.config.ts',
    'scripts/tests/run-access-review-browser.sh',
    'scripts/tests/run-access-review-web.sh',
    'scripts/tests/export-access-review-handoff.ps1',
    'tests/e2e/iplf-073b-access-reviews-2026-09-10.spec.ts'
)
$scopes = @{
    'apps/api/src/caseops_api/api/router.py' = 'Only access_reviews import and /api/access-reviews router registration; preserve inherited startup/provider wiring.'
    'apps/api/src/caseops_api/db/models.py' = 'Only AccessReviewCampaign and AccessReviewDecision classes. Never replace this shared file or provider fields.'
    'apps/api/src/caseops_api/services/matter_access.py' = 'Company-first entry fences for Matter/IP access responsibility; opt-in commit=False for apply_ip_access_change/remove_access_grant. Existing defaults preserved.'
    'apps/api/src/caseops_api/services/teams.py' = 'Only Company-first entry lock in set_team_scoping.'
    'apps/web/app/app/admin/page.tsx' = 'Only canReviewAccess capability and Access reviews navigation link.'
    'docs/PRD_IP_LAW_FIRM_PLATFORM_2026-08-01.md' = 'Only appended Section 33.9; leave all other PRD content unchanged.'
}
$files = foreach ($path in $owned) {
    $proof = File-Proof (Join-Path $root $path)
    @{ path = $path; sha256 = $proof.sha256; bytes = $proof.bytes
       integration_mode = $(if ($scopes.ContainsKey($path)) { 'merge_owned_hunks' } else { 'owned_file' })
       owned_scope = $(if ($scopes.ContainsKey($path)) { $scopes[$path] } else { 'Entire new feature file.' }) }
}

$unownedCount = 0
$unownedChanges = @()
foreach ($file in Get-ChildItem -LiteralPath $baseline -Recurse -File) {
    $relative = [IO.Path]::GetRelativePath($baseline, $file.FullName).Replace('\', '/')
    if ($relative -in $owned) { continue }
    $current = Join-Path $root $relative
    if (!(Test-Path -LiteralPath $current) -or (File-Proof $current).sha256 -ne (File-Proof $file.FullName).sha256) {
        $unownedChanges += $relative
    } else { $unownedCount++ }
}
if ($unownedChanges.Count) { throw "Unowned source changed since the first campaign snapshot: $($unownedChanges -join ', ')" }
$frozenManifest = Get-Content -LiteralPath (Join-Path $root 'docs/ip-implementation/evidence/ip-foundations-owned-files-2026-09-10.json') -Raw | ConvertFrom-Json
$frozenUnchanged = @()
foreach ($file in $frozenManifest.files) {
    if ($file.path -in $owned) { continue }
    if ((File-Proof (Join-Path $root $file.path)).sha256 -ne $file.sha256) { throw "Frozen file changed: $($file.path)" }
    $frozenUnchanged += $file.path
}
$model = [IO.File]::ReadAllText((Join-Path $root 'apps/api/src/caseops_api/db/models.py'))
$start = $model.IndexOf('class AccessReviewCampaign(Base):')
$end = $model.IndexOf('class LegalHoldReleaseRequest(Base):')
$oldModel = [IO.File]::ReadAllText((Join-Path $frozen 'apps/api/src/caseops_api/db/models.py'))
if ($start -lt 0 -or $end -le $start -or $model.Remove($start, $end - $start) -cne $oldModel) { throw 'Unowned shared model content changed.' }
$modelBlock = $model.Substring($start, $end - $start)

$runs = foreach ($journal in Get-ChildItem -LiteralPath $evidence -Filter '*.jsonl') {
    $records = Get-Content -LiteralPath $journal.FullName | ConvertFrom-Json -Depth 100 -DateKind String
    $reports = @($records | Where-Object event -eq 'test_report')
    $finish = @($records | Where-Object event -eq 'session_finished')
    $inventory = @($records | Where-Object event -eq 'collection' | ForEach-Object nodeids)
    $phaseErrors = @()
    foreach ($node in $inventory) {
        $nodeReports = @($reports | Where-Object nodeid -eq $node)
        foreach ($phase in @('setup', 'call', 'teardown')) {
            if (@($nodeReports | Where-Object when -eq $phase).Count -ne 1) { $phaseErrors += "$node : $phase" }
        }
    }
    if (@($reports | Where-Object { $_.nodeid -notin $inventory }).Count) { $phaseErrors += 'Uncollected result identities.' }
    if (!$inventory.Count -or $phaseErrors.Count -or $finish.Count -ne 1) { throw "Incomplete journal: $($journal.Name)" }
    @{ journal = $journal.Name; proof = File-Proof $journal.FullName
       completed = ($finish.Count -eq 1); exitstatus = $finish.exitstatus
       collected_nodes = $inventory; reconciled_phases = $reports.Count; reconciliation_errors = $phaseErrors
       passed_calls = @($reports | Where-Object { $_.when -eq 'call' -and $_.outcome -eq 'passed' }).Count
       skipped = @($reports | Where-Object outcome -eq 'skipped').Count
       failures = @($reports | Where-Object outcome -eq 'failed' | Select-Object nodeid, when, outcome, longrepr)
       phases = @($reports | Select-Object nodeid, when, outcome, duration) }
}
foreach ($current in @(@{ name = 'access-review-pg-02.jsonl'; count = 85 }, @{ name = 'access-review-api-03.jsonl'; count = 14 }, @{ name = 'access-review-pg-03.jsonl'; count = 18 })) {
    $run = @($runs | Where-Object journal -eq $current.name)
    if ($run.Count -ne 1 -or $run[0].exitstatus -ne 0 -or $run[0].passed_calls -ne $current.count -or $run[0].failures.Count -or $run[0].skipped) {
        throw "Current API verification failed: $($current.name)"
    }
}
function Browser-Specs($suite) {
    foreach ($spec in $suite.specs) {
        foreach ($test in $spec.tests) {
            @{ title = $spec.title; file = $spec.file; line = $spec.line; status = $test.status
               results = @($test.results | Select-Object status, retry, duration, errors) }
        }
    }
    foreach ($child in $suite.suites) { Browser-Specs $child }
}
$browsers = foreach ($report in (Get-ChildItem -LiteralPath $evidence -Filter 'access-review-browser-*.json' | Where-Object Name -Match '^access-review-browser-\d+\.json$')) {
    $result = Get-Content -LiteralPath $report.FullName -Raw | ConvertFrom-Json -Depth 100 -DateKind String
    @{ report = $report.Name; stats = $result.stats; errors = $result.errors
       specs = @($result.suites | ForEach-Object { Browser-Specs $_ }) }
}
$browser = @($browsers | Where-Object report -eq 'access-review-browser-02.json')
if ($browser.Count -ne 1 -or $browser[0].stats.expected -ne 2 -or $browser[0].stats.unexpected -or $browser[0].stats.skipped -or $browser[0].stats.flaky -or $browser[0].errors.Count) { throw 'Current browser verification failed.' }
$frontend = foreach ($report in Get-ChildItem -LiteralPath $evidence -Filter 'access-review-web-*.xml') {
    [xml]$xml = Get-Content -LiteralPath $report.FullName -Raw
    @{ report = $report.Name; tests = $xml.testsuites.tests; failures = $xml.testsuites.failures; errors = $xml.testsuites.errors
       cases = @($xml.SelectNodes('//testcase') | ForEach-Object { @{ name = $_.name; classname = $_.classname; time = $_.time } }) }
}
$web = @($frontend | Where-Object report -eq 'access-review-web-02.xml')
if ($web.Count -ne 1 -or [int]$web[0].tests -ne 12 -or [int]$web[0].failures -or [int]$web[0].errors) { throw 'Current frontend verification failed.' }
if ((Get-Content -LiteralPath (Join-Path $evidence 'access-review-web-02-collection.txt') -Raw) -notmatch 'Total: 2 tests in 1 file') { throw 'Normal dated browser discovery is incomplete.' }
$containers = @()
$timeline = @()
foreach ($name in (docker ps -a --format '{{.Names}}' | Where-Object { $_ -match '^caseops-access-review-' })) {
    $container = (docker inspect $name | ConvertFrom-Json -Depth 100 -DateKind String)[0]
    if ($container.State.Running) { throw "Owned work is still running: $name" }
    if ($name -in @('caseops-access-review-api-03', 'caseops-access-review-pg-tests-02', 'caseops-access-review-pg-tests-03', 'caseops-access-review-browser-02', 'caseops-access-review-web-02', 'caseops-access-review-lint-final', 'caseops-access-review-lint-closure') -and $container.State.ExitCode -ne 0) { throw "Current verification container failed: $name" }
    $containers += @{ name = $name; id = $container.Id; image = $container.Image; state = $container.State
        nano_cpus = $container.HostConfig.NanoCpus; memory_bytes = $container.HostConfig.Memory
        network_mode = $container.HostConfig.NetworkMode; mounts = $container.Mounts }
    $timeline += @{ time = [DateTimeOffset]::Parse($container.State.StartedAt); cpu = [long]$container.HostConfig.NanoCpus; memory = [long]$container.HostConfig.Memory; kind = 1 }
    $timeline += @{ time = [DateTimeOffset]::Parse($container.State.FinishedAt); cpu = -[long]$container.HostConfig.NanoCpus; memory = -[long]$container.HostConfig.Memory; kind = 0 }
}
$cpu = 0L; $memory = 0L; $peakCpu = 0L; $peakMemory = 0L
foreach ($point in ($timeline | Sort-Object time, kind)) {
    $cpu += $point.cpu; $memory += $point.memory
    $peakCpu = [Math]::Max($peakCpu, $cpu); $peakMemory = [Math]::Max($peakMemory, $memory)
    if ($cpu -gt 1000000000 -or $memory -gt 2147483648) { throw "Owned test resource budget exceeded at $($point.time)" }
}
$artifacts = foreach ($file in Get-ChildItem -LiteralPath $evidence -File) {
    if ($file.Extension -in @('.jsonl', '.json', '.xml', '.txt', '.png', '.sha256')) {
        @{ path = '.tmp/ip-access-review-evidence/' + $file.Name; proof = File-Proof $file.FullName }
    }
}
$executionPath = Join-Path $output "ip-access-review-test-results-$Date.json"
Write-JsonNew $executionPath @{ schema_version = 1; source_root = $root; runs = @($runs); artifacts = @($artifacts); containers = $containers; peak_cpu = ($peakCpu / 1000000000); peak_memory_bytes = $peakMemory; all_owned_containers_stopped = $true
    browser = @($browsers); frontend = @($frontend)
    failure_reconciliation = @(
        @{ original = 'access-review-api-01'; failures = 4; diagnosis = 'SQLite finalization/reload timestamp UTC serialization differed. All four full call failures inspected.'; replacement = 'Typed UTC DTO normalization; same four success/reload cases passed in pg-01, pg-02 and api-03.' },
        @{ original = 'access-review-web-01'; failures = 1; diagnosis = 'Twelve unit tests and TypeScript passed; normal dated Playwright discovery rejected missing b suffix.'; replacement = 'Own spec renamed to 073b; web-02 discovers both nodes and passes all frontend checks; browser-02 executes both without retry.' }
    )
    excluded_parent_preservation_evidence = 'Parent reported 289 passed / 867 phases in foundations-integration-01. Not evidence for access-review code.' }

$program = Get-Content -LiteralPath (Join-Path $root 'docs/ip-implementation/PROGRAM_MANIFEST.yaml') -Raw | ConvertFrom-Json -Depth 100
$remaining = @{
    'IP-ACCESS-01' = 'All other list/search/export/report/AI/count paths and deployed acceptance remain allocated to their owners.'
    'IP-ACCESS-02' = 'Campaign snapshots preserve effective windows; no new grant-expiry scheduler or full domain access certification.'
    'IP-ACCESS-03' = 'Client-wide access campaigns and complete inherited-visibility preview UX remain outside this bounded adapter; generated contracts are parent integration.'
    'IP-ACCESS-04' = 'Portal campaigns and portal-session lifecycle are not implemented here.'
    'IP-ACCESS-05' = 'No permission copying is added; broad linked-record ACL journey acceptance remains separate.'
    'IP-ACCESS-06' = 'Canonical invalidation is delegated; all delivery/cache/retrieval surfaces and exact-release verification remain separate.'
    'IP-ACCESS-07' = 'Only campaign and adjacent canonical-owner regressions are covered, not every enumerated platform surface.'
    'IP-ACCESS-08' = 'No support/break-glass access is introduced.'
    'SEC-GOV-01' = 'Campaign uses mandatory record_access_change step-up; all other high-risk commands remain with existing owners.'
    'SEC-GOV-02' = 'Campaign preparer/reviewer/executor identity separation is enforced; other four-eyes policies remain separate.'
    'SEC-GOV-03' = 'Emergency sessions, expiry, session/cache revocation, notification, action logging and retrospective review remain unimplemented.'
    'SEC-GOV-04' = 'Manual trigger selection is implemented; periodic/event-driven creation, firm-policy due dates, escalation and unreviewed-grant expiry remain open.'
    'SEC-GOV-05' = 'Campaign finalization rechecks membership/user/capability. UJ-57, connector/session revocation and assignment reassignment are not implemented by this feature.'
    'SEC-GOV-14' = 'Campaign audit events and immutable snapshot/decision evidence exist; parent must register exact actions and data columns. Broader audit integrity monitoring remains separate.'
    'SEC-GOV-16' = 'Focused campaign abuse cases and ownership are retained here; consolidated integrated threat model and activation review remain parent/release work.'
}
$supported = @('IP-ACCESS-01','IP-ACCESS-02','IP-ACCESS-03','IP-ACCESS-04','IP-ACCESS-05','IP-ACCESS-06','IP-ACCESS-07','SEC-GOV-01','SEC-GOV-02','SEC-GOV-04','SEC-GOV-05','SEC-GOV-14','SEC-GOV-16')
$slices = foreach ($id in @('IPLF-073A', 'IPLF-073B')) {
    $slice = $program.slices | Where-Object id -eq $id
    $requirements = foreach ($requirementId in $slice.requirement_ids) {
        $requirement = $program.requirements | Where-Object id -eq $requirementId
        @{ id = $requirementId; canonical_text = $requirement.text; canonical_text_sha256 = $requirement.text_sha256
           campaign_support = ($requirementId -in $supported); complete_requirement_claim = $false
           remaining = $(if ($remaining.ContainsKey($requirementId)) { $remaining[$requirementId] } else { 'Not implemented or certified by this campaign feature: ' + $requirement.text }) }
    }
    @{ id = $id; title = $slice.title; overall_status = 'partial'; campaign_status = 'implemented_locally_verified'; release_status = 'not_released'
       allocation_source = $(if ($id -eq 'IPLF-073A') { 'Technical slice: reciprocal requirements and journeys are allocated to IPLF-073B below.' } else { 'Direct canonical slice allocation, reproduced without new requirement IDs.' })
       implementation_refs = @('apps/api/src/caseops_api/services/access_reviews.py', 'apps/api/alembic/versions/20260910_0001_access_review_campaigns.py', 'apps/web/app/app/admin/access-reviews/page.tsx')
       test_refs = @('apps/api/tests/test_20260910_access_reviews.py', 'apps/api/tests/test_20260910_access_reviews_postgres.py', 'apps/web/app/app/admin/access-reviews/page.test.tsx', 'apps/web/lib/api/access-reviews.test.ts', 'tests/e2e/iplf-073b-access-reviews-2026-09-10.spec.ts')
       requirements = @($requirements); journey_paths = @($slice.journey_path_ids | ForEach-Object { @{ id = $_; status = 'not_implemented'; remaining = 'UJ-63 emergency-access journey is outside this manual campaign feature.' } })
       remaining = 'Emergency sessions, automatic review policy/triggers, client/portal review scope, shared integration and deployed acceptance. Technical A inherits the B allocation without inventing new canonical requirement IDs.' }
}
$requirementsPath = Join-Path $output "ip-access-review-requirements-$Date.json"
Write-JsonNew $requirementsPath @{ schema_version = 1; source_root = $root; slices = @($slices); test_results = Split-Path $executionPath -Leaf }
$manifestPath = Join-Path $output "ip-access-review-owned-files-$Date.json"
Write-JsonNew $manifestPath @{ schema_version = 1; source_root = $root; base_revision = (git -C $root rev-parse HEAD); not_whole_worktree_copy_authority = $true; files = @($files)
    parent_integration = @{ tables = @('access_review_campaigns', 'access_review_decisions'); audit_actions = @('access.review.created', 'access.review.decided', 'access.review.finalized'); audit_target = 'access_review_campaign'; catalog_owner = 'platform-shared-foundations'; migration = '20260910_0001'; local_predecessor = '20260909_0003'; pending = 'Parent integrates exact columns/data categories, events, shared models and generated contracts/projection once. Preserve provider fields; do not copy whole shared files or add a registry override.' }
    model_insert_source = $modelBlock; model_insert_sha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($modelBlock))).ToLowerInvariant()
    preservation = @{ initial_feature_snapshot = File-Proof (Join-Path $evidence 'initial-feature-source.tar'); unowned_files_byte_identical = $unownedCount; unowned_changes = @(); frozen_unchanged_files = $frozenUnchanged; shared_model_outside_new_classes_matches_frozen = $true }
    generated_artifacts = @(@{ path = Split-Path $executionPath -Leaf; proof = File-Proof $executionPath }, @{ path = Split-Path $requirementsPath -Leaf; proof = File-Proof $requirementsPath }) }
@{ manifest = $manifestPath; proof = File-Proof $manifestPath; files = $files.Count; unowned_preserved = $unownedCount; peak_cpu = ($peakCpu / 1000000000); peak_memory_bytes = $peakMemory } | ConvertTo-Json
