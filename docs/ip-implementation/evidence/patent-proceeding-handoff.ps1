param([string]$Label = 'handoff-v2')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$out = Join-Path $root '.tmp/patent-proceeding-20260910'
$priorPath = Join-Path $root '.tmp/patent-resume-20260910/handoff-owned-files.json'
$priorHash = (Get-FileHash -LiteralPath $priorPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($priorHash -ne '5e68835d853562953105f26cd1d7df0e016f0d0eabf538c5f9513d75652c9a2c') {
    throw 'The immutable previous handoff changed.'
}
$prior = @(Get-Content -LiteralPath $priorPath -Raw | ConvertFrom-Json)
$candidateHashes = @{}
Get-Content -LiteralPath (Join-Path $out 'proceeding-06-files.sha256') | ForEach-Object {
    if ($_ -match '^(?<Hash>[a-f0-9]{64})  (?<Path>.+)$') {
        $candidateHashes[$Matches.Path] = $Matches.Hash
    }
}
$webHashes = @{}
Get-Content -LiteralPath (Join-Path $out 'proceeding-candidate-01-files.sha256') | ForEach-Object {
    if ($_ -match '^(?<Hash>[a-f0-9]{64})  (?<Path>.+)$') { $webHashes[$Matches.Path] = $Matches.Hash }
}
$webInputs = @($candidateHashes.Keys | Where-Object {
    $_.StartsWith('apps/web/') -or $_ -in @('package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock')
})
foreach ($inputPath in $webInputs) {
    if ($webHashes[$inputPath] -ne $candidateHashes[$inputPath]) {
        throw "The frontend build input changed: $inputPath"
    }
}
$newPaths = @(
    'apps/api/src/caseops_api/api/routes/ip_patent_proceedings.py',
    'apps/api/src/caseops_api/db/patent_proceeding_models.py',
    'apps/api/src/caseops_api/schemas/ip_patent_proceedings.py',
    'apps/api/src/caseops_api/services/ip_patent_proceedings.py',
    'apps/api/tests/test_ip_patent_proceedings.py',
    'apps/api/tests/test_ip_patent_proceedings_postgres.py',
    'apps/web/components/ip/PatentProceedingsWorkspace.tsx',
    'apps/web/components/ip/PatentProceedingsWorkspace.test.tsx',
    'apps/web/lib/api/ip-patent-proceedings.ts',
    'docs/PRD_PATENT_PREGRANT_PROCEEDING_2026-09-10.md',
    'docs/ip-implementation/evidence/patent-proceeding-web.sh',
    'docs/ip-implementation/evidence/patent-proceeding-browser.sh',
    'docs/ip-implementation/evidence/patent-proceeding-snapshot.sh',
    'docs/ip-implementation/evidence/patent-proceeding-handoff.ps1',
    'docs/ip-implementation/evidence/patent-proceeding-2026-09-10-v2.md',
    'tests/e2e/iplf-080b-patent-pregrant-proceeding-2026-09-10.spec.ts'
)
function Write-NewJson([string]$name, $value) {
    $path = Join-Path $out "$Label-$name.json"
    $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Depth 100) + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
    } finally { $stream.Dispose() }
}
$manifest = @(@($prior.Path) + $newPaths | Sort-Object -Unique | ForEach-Object {
    $path = Join-Path $root $_
    $old = $prior | Where-Object Path -eq $_
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $runtime = $_.StartsWith('apps/') -and $_ -notmatch '/tests/|\.test\.'
    if ($runtime -and $candidateHashes[$_] -ne $hash) { throw "Runtime source drifted: $_" }
    [pscustomobject]@{
        Path = $_; Bytes = (Get-Item -LiteralPath $path).Length; SHA256 = $hash
        PreviousSHA256 = $old.SHA256; ChangedSincePrevious = ($old.SHA256 -ne $hash)
        Runtime = $runtime; CandidateSHA256 = $candidateHashes[$_]
        MatchesCandidate = ($candidateHashes[$_] -eq $hash)
        FrontendBuildSHA256 = $webHashes[$_]
        SharedOwnedHunksOnly = ($_ -in @('apps/api/src/caseops_api/db/models.py',
            'apps/api/src/caseops_api/api/routes/ip_patents.py',
            'apps/web/components/ip/PatentApplicationWorkspace.tsx'))
    }
})
Write-NewJson 'owned-files' $manifest
Write-NewJson 'frontend-build-identity' ([pscustomobject]@{
    BuildArchive = 'proceeding-candidate-01-source.tar'; FinalApiArchive = 'proceeding-06-source.tar'
    VerifiedIdenticalFrontendInputs = $webInputs.Count
})
$reference = Join-Path $out "$Label-reference"
New-Item -ItemType Directory -Path $reference -ErrorAction Stop | Out-Null
$shared = @($manifest | Where-Object SharedOwnedHunksOnly | ForEach-Object Path)
& tar -xf (Join-Path $root '.tmp/patent-resume-20260910/resume-02-source.tar') -C $reference @shared
if ($LASTEXITCODE -ne 0) { throw 'Unable to recover immutable shared-file baseline.' }
$patch = [Text.StringBuilder]::new()
foreach ($relative in $shared) {
    $oldFile = Join-Path $reference $relative
    $oldHash = (Get-FileHash -LiteralPath $oldFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($oldHash -ne ($prior | Where-Object Path -eq $relative).SHA256) {
        throw "Previous shared-file hash mismatch: $relative"
    }
    $diff = @(& git --no-pager diff --no-index --no-ext-diff --text --unified=4 -- $oldFile (Join-Path $root $relative))
    if ($LASTEXITCODE -notin @(0, 1)) { throw "Unable to diff $relative" }
    $start = -1
    for ($i = 0; $i -lt $diff.Count; $i++) {
        if ($diff[$i].StartsWith('@@ ')) { $start = $i; break }
    }
    if ($start -ge 0) {
        [void]$patch.Append("diff --git a/$relative b/$relative`n--- a/$relative`n+++ b/$relative`n")
        [void]$patch.Append(($diff[$start..($diff.Count - 1)] -join "`n") + "`n")
    }
}
$patchPath = Join-Path $out "$Label-shared-delta.patch"
$stream = [IO.File]::Open($patchPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($patch.ToString())
    $stream.Write($bytes, 0, $bytes.Length)
} finally { $stream.Dispose() }
& git -C $root apply --reverse --check -- $patchPath
if ($LASTEXITCODE -ne 0) { throw 'Shared delta does not match current source.' }
$baselinePatch = Join-Path $root '.tmp/patent-resume-20260910/owned-shared-hunks.patch'
if ((Get-FileHash -LiteralPath $baselinePatch -Algorithm SHA256).Hash.ToLowerInvariant() -ne
    'b3c851f5ddcd9176883eaf54abeeab525ae2e7247d118a499314896cba9fc7a6') {
    throw 'The immutable previous shared patch changed.'
}
[IO.File]::Copy($baselinePatch, (Join-Path $out "$Label-shared-baseline.patch"), $false)
$ownedArchive = Join-Path $out "$Label-owned-files.tar"
if (Test-Path -LiteralPath $ownedArchive) { throw 'Owned archive already exists.' }
$wholeFiles = @($manifest | Where-Object { -not $_.SharedOwnedHunksOnly } | ForEach-Object Path)
& tar -cf $ownedArchive -C $root @wholeFiles
if ($LASTEXITCODE -ne 0) { throw 'Unable to freeze owned files.' }
$frozen = Join-Path $out "$Label-owned-files"
New-Item -ItemType Directory -Path $frozen -ErrorAction Stop | Out-Null
& tar -xf $ownedArchive -C $frozen
if ($LASTEXITCODE -ne 0) { throw 'Unable to verify owned archive.' }
foreach ($relative in $wholeFiles) {
    $frozenHash = (Get-FileHash -LiteralPath (Join-Path $frozen $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($frozenHash -ne ($manifest | Where-Object Path -eq $relative).SHA256) {
        throw "Frozen archive differs: $relative"
    }
}
$journals = @(Get-ChildItem -LiteralPath $out -Filter '*.jsonl' | Sort-Object Name | ForEach-Object {
    $entries = @(Get-Content -LiteralPath $_.FullName | ForEach-Object { $_ | ConvertFrom-Json })
    $reports = @($entries | Where-Object event -eq 'test_report')
    $collection = @($entries | Where-Object event -eq 'collection')
    $finish = @($entries | Where-Object event -eq 'session_finished')
    $completedNodes = @($reports | Group-Object nodeid | Where-Object {
        @($_.Group).Count -eq 3 -and @($_.Group | Where-Object outcome -ne 'passed').Count -eq 0 -and
        (@($_.Group.when | Sort-Object -Unique) -join ',') -eq 'call,setup,teardown'
    } | ForEach-Object Name)
    [pscustomobject]@{
        File = $_.Name; SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        Collected = @($collection.nodeids); PhaseCount = $reports.Count
        CompletedPassingNodes = $completedNodes; Finish = $finish
        NonpassingPhases = @($reports | Where-Object outcome -ne 'passed')
        MissingCompletePass = @($collection.nodeids | Where-Object { $_ -notin $completedNodes })
    }
})
Write-NewJson 'journals' $journals
$successful = @($journals | Where-Object { $_.Finish.Count -eq 1 -and $_.Finish[0].exitstatus -eq 0 })
$inventory = @($successful.CompletedPassingNodes | Sort-Object -Unique)
$replacements = @($journals | ForEach-Object {
    $failedJournal = $_.File
    $_.NonpassingPhases | ForEach-Object {
        $node = $_.nodeid
        $replacementRuns = @($successful | Where-Object { $node -in $_.CompletedPassingNodes } | ForEach-Object File)
        if (-not $replacementRuns.Count) { throw "Unreconciled failed node: $node" }
        [pscustomobject]@{ FailedJournal = $failedJournal; Node = $node; Phase = $_.when
            PassingReplacements = $replacementRuns }
    }
})
Write-NewJson 'reconciliation' ([pscustomobject]@{
    DistinctCompletePassingNodes = $inventory; EarlierNonpassingPhases = $replacements
    FinalChangedServiceJournal = 'proceeding-06.jsonl'
    UnchangedProsecutionAndMigrationJournal = 'proceeding-03.jsonl'
})
$xml = @(Get-ChildItem -LiteralPath $out -Filter '*.xml' | Sort-Object Name | ForEach-Object {
    [xml]$document = Get-Content -LiteralPath $_.FullName -Raw
    [pscustomobject]@{ File = $_.Name; Tests = @($document.SelectNodes('//testcase') | ForEach-Object {
        [pscustomobject]@{ Name = $_.name; Class = $_.classname; Time = $_.time
            Failure = @($_.SelectNodes('failure|error|skipped') | ForEach-Object OuterXml) }
    }) }
})
Write-NewJson 'xml' $xml
$names = @(& docker ps -a --filter 'label=caseops.track=patent-proceeding-20260910' --format '{{.Names}}')
$containers = @($names | ForEach-Object {
    $container = @(& docker inspect $_ | ConvertFrom-Json)[0]
    [pscustomobject]@{ Name = $_; Image = $container.Image; State = $container.State
        NanoCpus = $container.HostConfig.NanoCpus; Memory = $container.HostConfig.Memory
        NetworkMode = $container.HostConfig.NetworkMode; Command = $container.Config.Cmd
        Log = @(& docker logs $_ 2>&1 | ForEach-Object { "$_" }) }
})
Write-NewJson 'containers' $containers
$artifacts = @(Get-ChildItem -LiteralPath $out -Recurse -File | Where-Object {
    $_.FullName -notlike '*\next-docs\*' -and $_.Name -notlike "$Label-*"
} | Sort-Object FullName | ForEach-Object {
    [pscustomobject]@{ Path = [IO.Path]::GetRelativePath($root, $_.FullName).Replace('\', '/')
        Bytes = $_.Length; SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
})
Write-NewJson 'artifacts' $artifacts
$checkpointFiles = @(Get-ChildItem -LiteralPath $out -File | Where-Object Name -like "$Label-*" |
    Sort-Object Name | ForEach-Object {
        [pscustomobject]@{ Name = $_.Name; Bytes = $_.Length
            SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
Write-NewJson 'checkpoint' ([pscustomobject]@{
    Label = $Label; OwnedFiles = $manifest.Count; WholeFilesInArchive = $wholeFiles.Count
    SharedFilesRequireOwnedPatches = $shared
    SourceArchive = 'proceeding-06-source.tar'
    SourceArchiveSHA256 = (Get-FileHash -LiteralPath (Join-Path $out 'proceeding-06-source.tar') -Algorithm SHA256).Hash.ToLowerInvariant()
    PreviousHandoffUnchanged = $true; Files = $checkpointFiles
})
[pscustomobject]@{ PreviousManifestSHA256 = $priorHash; OwnedFiles = $manifest.Count
    ChangedFiles = @($manifest | Where-Object ChangedSincePrevious).Count
    Journals = $journals.Count; XmlFiles = $xml.Count; Containers = $containers.Count }
