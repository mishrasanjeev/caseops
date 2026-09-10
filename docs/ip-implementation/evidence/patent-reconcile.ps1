param(
    [Parameter(Mandatory)][string]$Label,
    [Parameter(Mandatory)][string[]]$ReplacementJournals
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
if ((Split-Path $root -Leaf) -ne 'codex-patent-closure-20260909') {
    throw 'This evidence generator is restricted to the isolated patent worktree.'
}
$historical = 'C:/tmp/caseops-patent-closure-20260909'
$output = Join-Path $root '.tmp/patent-resume-20260910'
if ($Label -notmatch '^[a-z0-9-]+$') { throw 'Invalid evidence label.' }

function Write-NewJson([string]$Name, $Value) {
    $target = Join-Path $output "$Label-$Name.json"
    $stream = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($false))
    try { $writer.WriteLine((ConvertTo-Json -InputObject $Value -Depth 30)) }
    finally { $writer.Dispose() }
}

function Read-Journal([string]$Path) {
    $rows = @(Get-Content -LiteralPath $Path | ForEach-Object { ConvertFrom-Json $_ })
    $collection = @($rows | Where-Object event -eq 'collection')
    $finish = @($rows | Where-Object event -eq 'session_finished')
    $failures = @($rows | Where-Object { $_.outcome -eq 'failed' -or $_.event -eq 'collection_failed' })
    $nodes = @($rows | Where-Object event -eq 'test_report' | Group-Object nodeid | ForEach-Object {
        $phases = @($_.Group)
        [pscustomobject]@{
            Node = $_.Name
            Phases = @($phases | Select-Object when,outcome,duration)
            Passed = ($phases.Count -eq 3 -and @($phases | Where-Object outcome -ne passed).Count -eq 0 -and
                @($phases.when | Sort-Object -Unique).Count -eq 3)
        }
    })
    $inventory = @($collection | ForEach-Object { $_.nodeids })
    [pscustomobject]@{
        Path = $Path
        SHA256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        Finished = ($finish.Count -eq 1)
        ExitStatus = if ($finish.Count) { $finish[0].exitstatus } else { $null }
        Inventory = $inventory
        Nodes = $nodes
        Failures = $failures
        CompletePassingInventory = ($finish.Count -eq 1 -and $finish[0].exitstatus -eq 0 -and
            $failures.Count -eq 0 -and $inventory.Count -gt 0 -and
            $inventory.Count -eq @($inventory | Sort-Object -Unique).Count -and
            $inventory.Count -eq $nodes.Count -and @($nodes | Where-Object Passed -eq $false).Count -eq 0 -and
            @(Compare-Object ($inventory | Sort-Object) ($nodes.Node | Sort-Object)).Count -eq 0)
    }
}

$replacements = @($ReplacementJournals | ForEach-Object {
    if ($_ -notmatch '^[a-z0-9-]+[.]jsonl$') { throw 'Invalid journal filename.' }
    Read-Journal (Join-Path $output $_)
})
$old = @(Get-ChildItem -LiteralPath $historical -Filter '*.jsonl' | ForEach-Object { Read-Journal $_.FullName })
$successfulNodes = @($replacements | Where-Object CompletePassingInventory | ForEach-Object { $_.Nodes.Node } | Sort-Object -Unique)
$oldNodes = @($old | ForEach-Object { $_.Nodes.Node } | Sort-Object -Unique)
Write-NewJson 'journals' @{
    Historical = $old
    Replacements = $replacements
    CurrentSuccessfulUnion = $successfulNodes
    HistoricalNodesWithoutReplacement = @($oldNodes | Where-Object { $_ -notin $successfulNodes })
    Note = 'An interrupted run stays incomplete. Union counts are distinct identities, not added pass totals.'
}

$xmlReports = @(Get-ChildItem -LiteralPath $historical,$output -Filter '*.xml' | ForEach-Object {
    [xml]$document = Get-Content -LiteralPath $_.FullName -Raw
    [pscustomobject]@{
        Path = $_.FullName
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        Tests = @($document.SelectNodes('//testcase') | ForEach-Object {
            [pscustomobject]@{
                Name = $_.name
                Class = $_.classname
                Seconds = $_.time
                Failures = @($_.SelectNodes('failure|error') | ForEach-Object { $_.InnerText })
                Skips = @($_.SelectNodes('skipped') | ForEach-Object { $_.OuterXml })
            }
        })
    }
})
Write-NewJson 'xml' $xmlReports

$containers = @(foreach ($track in @('patent-closure-20260909','patent-resume-20260910')) {
    $names = @(docker ps -a --filter "label=caseops.track=$track" --format '{{.Names}}')
    if ($LASTEXITCODE) { throw 'Docker inventory failed.' }
    foreach ($name in $names) {
        $item = (docker inspect $name | ConvertFrom-Json)[0]
        if ($LASTEXITCODE) { throw "Docker inspection failed: $name" }
        [pscustomobject]@{
            Name = $name; Id = $item.Id; Image = $item.Image; State = $item.State
            Command = $item.Config.Cmd; Network = $item.HostConfig.NetworkMode
            NanoCpus = $item.HostConfig.NanoCpus; Memory = $item.HostConfig.Memory
            Logs = @(docker logs $name 2>&1 | ForEach-Object { "$_" })
        }
    }
})
Write-NewJson 'containers' $containers

$checkpoint = Get-Content -LiteralPath (Join-Path $historical 'integration-inventory-checkpoint.json') -Raw | ConvertFrom-Json
$paths = @($checkpoint.Path) + @(
    'docs/ip-implementation/evidence/patent-resume-tests.sh',
    'docs/ip-implementation/evidence/patent-reconcile.ps1',
    'docs/ip-implementation/evidence/patent-resume-2026-09-10.md'
)
$manifest = @($paths | Sort-Object -Unique | ForEach-Object {
    $path = Join-Path $root $_
    [pscustomobject]@{
        Path = $_
        Bytes = (Get-Item -LiteralPath $path).Length
        SHA256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
})
Write-NewJson 'owned-files' $manifest
Write-Output "Wrote $Label evidence. Owned paths: $($manifest.Count); passing distinct replacement nodes: $($successfulNodes.Count)."
