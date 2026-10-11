#Requires -Version 5.1
[CmdletBinding()]
param([string]$ScriptPath, [string]$EvidenceDirectory)

$ErrorActionPreference = "Stop"
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
$Definitions = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $Node.Name -eq "Invoke-IsolatedNativePostgresGate"
}, $true))
if ($Definitions.Count -ne 1) { throw "Expected one isolated native PostgreSQL gate." }
. ([scriptblock]::Create($Definitions[0].Extent.Text))
$Calls = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.CommandAst] -and
    $Node.GetCommandName() -eq "Invoke-IsolatedNativePostgresGate"
}, $true))
if ($Calls.Count -ne 1) { throw "Expected one standard native PostgreSQL invocation." }
$Blocks = @($Calls[0].CommandElements | Where-Object {
    $_ -is [Management.Automation.Language.ScriptBlockExpressionAst]
})
if ($Blocks.Count -ne 1) { throw "Expected the complete standard validation block." }
$NativeValidation = $Blocks[0].ScriptBlock.GetScriptBlock()

$Work = Join-Path ([IO.Path]::GetTempPath()) ("caseops-native-guard-" + [Guid]::NewGuid().ToString("N"))
[void][IO.Directory]::CreateDirectory($Work)
$RetainEvidence = [bool]$EvidenceDirectory
if (-not $EvidenceDirectory) { $EvidenceDirectory = Join-Path $Work "evidence" }
$EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
[void][IO.Directory]::CreateDirectory($EvidenceDirectory)
$Journal = Join-Path $EvidenceDirectory "guard-results.jsonl"
$InventoryPath = Join-Path $EvidenceDirectory "guard-inventory.json"
$CompletionPath = Join-Path $EvidenceDirectory "guard-completion.json"
foreach ($Path in @($Journal, $InventoryPath, $CompletionPath)) {
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite guard evidence: $Path" }
}
$SavedEnvironment = @{}
foreach ($Name in @("CASEOPS_TEST_POSTGRES_URL", "CASEOPS_DATABASE_URL", "CASEOPS_E2E_DATABASE_URL")) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}
$InitialLocation = (Get-Location).Path
$ApiPython = "Invoke-FakePytest"
$ApiDir = Join-Path $Work "api with spaces"
[void][IO.Directory]::CreateDirectory($ApiDir)
$ComposeFile = Join-Path $Work "compose with spaces.yml"
$Cases = @(
    @{ Name = "isolated-migrate-seed-index-and-full-pytest" },
    @{ Name = "restore-unset-native-environment"; Unset = $true },
    @{ Name = "existing-database-refused-without-drop"; Stage = "createdb"; Error = "refusing reuse"; Exit = 19 },
    @{ Name = "creation-exception-without-drop"; Stage = "createdb"; Kind = "throw"; Error = "fake createdb exception"; Exit = 1 },
    @{ Name = "extension-exit-restores-and-drops"; Stage = "extension"; Error = "vector extension"; Exit = 19 },
    @{ Name = "independent-upgrade-exit-restores-and-drops"; Stage = "upgrade"; Error = "Independent native"; Exit = 19 },
    @{ Name = "exact-image-seed-exit-restores-and-drops"; Stage = "seed"; Error = "statute catalog seed"; Exit = 19 },
    @{ Name = "pre-index-exit-restores-and-drops"; Stage = "pre-index"; Error = "pre-validation index"; Exit = 19 },
    @{ Name = "pytest-exit-preserved-after-cleanup"; Stage = "pytest"; Error = "validation failed (exit 19)"; Exit = 19 },
    @{ Name = "pytest-exception-restores-location-and-environment"; Stage = "pytest"; Kind = "throw"; Error = "fake pytest exception"; Exit = 1 },
    @{ Name = "missing-journal-fails-closed"; MissingJournal = $true; Error = "incremental result journal"; Exit = 1 },
    @{ Name = "post-index-exit-restores-and-drops"; Stage = "post-index"; Error = "post-rehearsal index"; Exit = 19 },
    @{ Name = "cleanup-only-exit-fails-gate"; Stage = "dropdb"; Error = "cleanup failed"; Exit = 19 },
    @{ Name = "cleanup-only-exception-fails-gate"; Stage = "dropdb"; Kind = "throw"; Error = "fake dropdb exception"; Exit = 1 },
    @{ Name = "primary-exit-survives-cleanup-exit"; Stage = "pytest"; CleanupKind = "exit"; Error = "validation failed (exit 19)"; Exit = 19 },
    @{ Name = "primary-exception-survives-cleanup-exception"; Stage = "pytest"; Kind = "throw"; CleanupKind = "throw"; Error = "fake pytest exception"; Exit = 1 },
    @{ Name = "reject-project-sql-shell-injection"; Field = "ComposeProject"; Value = "caseops-acceptance-111111111111-aaaaaaaaaaaa;DROP DATABASE caseops"; Error = "Invalid owned release/project"; Exit = 0 },
    @{ Name = "reject-uppercase-project-identity"; Field = "ComposeProject"; Value = "caseops-acceptance-111111111111-AAAAAAAAAAAA"; Error = "Invalid owned release/project"; Exit = 0 },
    @{ Name = "reject-mismatched-release-project"; Field = "ReleaseSha"; Value = ("2" * 40); Error = "does not belong"; Exit = 0 },
    @{ Name = "reject-malformed-release"; Field = "ReleaseSha"; Value = "not-a-release"; Error = "Invalid owned release/project"; Exit = 0 },
    @{ Name = "reject-port-injection"; Field = "PostgresPort"; Value = "5432/caseops?host=foreign"; Error = "Invalid owned PostgreSQL port"; Exit = 0 },
    @{ Name = "reject-out-of-range-port"; Field = "PostgresPort"; Value = "65536"; Error = "Invalid owned PostgreSQL port"; Exit = 0 },
    @{ Name = "reject-uninspected-image"; Field = "ApiImageId"; Value = "caseops-api-local:latest"; Error = "inspected image"; Exit = 0 },
    @{ Name = "reject-network-injection"; Field = "AcceptanceNetworkId"; Value = "foreign --network host"; Error = "acceptance network"; Exit = 0 },
    @{ Name = "reject-browser-native-url"; BrowserDatabase = "caseops_native_111111111111_aaaaaaaaaaaa"; Error = "separate application database"; Exit = 0 },
    @{ Name = "reject-foreign-browser-url"; BrowserDatabase = "foreign"; Error = "separate application database"; Exit = 0 },
    @{ Name = "second-invocation-migrates-independent-empty-database"; Repeat = $true }
)
$CaseNames = @($Cases | ForEach-Object { $_.Name })
if (@($CaseNames | Sort-Object -Unique).Count -ne $Cases.Count) { throw "Duplicate guard identity." }
[IO.File]::WriteAllText($InventoryPath, (ConvertTo-Json -InputObject $CaseNames))

function Assert-Guard([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Add-Invocation([string]$Stage, [string[]]$Arguments) {
    $script:Invocations.Add([ordered]@{
        stage = $Stage; arguments = @($Arguments); cwd = (Get-Location).Path
        test_url = $env:CASEOPS_TEST_POSTGRES_URL; database_url = $env:CASEOPS_DATABASE_URL
        browser_url = $env:CASEOPS_E2E_DATABASE_URL
    })
}

function Invoke-FakeFailure([string]$Stage) {
    $global:LASTEXITCODE = 0
    $Kind = if ($Stage -eq $script:Case.Stage) {
        if ($script:Case.Kind) { $script:Case.Kind } else { "exit" }
    } elseif ($Stage -eq "dropdb") { $script:Case.CleanupKind } else { $null }
    if ($Kind -eq "throw") { throw "fake $Stage exception" }
    if ($Kind -eq "exit") { $global:LASTEXITCODE = 19 }
}

function Save-DockerAcceptanceFailureEvidence {
    $script:CaptureCalls++
    $script:CaptureAfterCleanup = @($script:Invocations | Where-Object { $_.stage -eq "dropdb" }).Count -ne 0
}

# Function mocks take precedence over PATH, so these tests cannot reach real Docker.
function docker {
    $Arguments = @($args)
    $Stage = if ($Arguments -contains "createdb") { "createdb" }
        elseif ($Arguments -contains "psql") { "extension" }
        elseif ($Arguments -contains "alembic") { "upgrade" }
        elseif ($Arguments -contains "caseops_api.scripts.seed_statutes") { "seed" }
        elseif ($Arguments -contains "caseops-db-index-health") {
            $script:IndexCalls++
            if ($script:IndexCalls % 2 -eq 1) { "pre-index" } else { "post-index" }
        }
        elseif ($Arguments -contains "dropdb") { "dropdb" }
        else { throw "Unexpected Docker arguments: $Arguments" }
    Add-Invocation $Stage $Arguments
    Invoke-FakeFailure $Stage
    if ($LASTEXITCODE -ne 0) { return }
    if ($Stage -in @("createdb", "dropdb")) {
        $Name = $Arguments[-1]
        Assert-Guard ($Arguments[-2] -eq "--") "Database identifier must be one native argument after --."
        Assert-Guard ($Name -cmatch '^caseops_native_[0-9a-f]{12}_[0-9a-f]{12}$' -and $Name.Length -le 63) "Unbounded database name."
        Assert-Guard ($Arguments -contains $ComposeProject -and $Arguments -contains $ComposeFile) "Command escaped the owned project/file."
        Assert-Guard ($Arguments -contains "--maintenance-db" -and $Arguments -contains "postgres") "Missing neutral maintenance database."
        if ($Stage -eq "createdb") {
            Assert-Guard ($Arguments -contains "--template" -and $Arguments -contains "template0") "Native database cloned application state."
            Assert-Guard (-not $script:Databases.ContainsKey($Name)) "Database was reused."
            $script:Databases[$Name] = @{ schema = "empty"; tenants = 0; seeded = $false }
        } else {
            Assert-Guard ($Arguments -contains "--force") "Native cleanup omitted connection termination."
            $script:Databases.Remove($Name)
        }
    } elseif ($Stage -eq "extension") {
        Assert-Guard ($Arguments[-1] -eq "CREATE EXTENSION vector" -and $Arguments -contains "ON_ERROR_STOP=1") "Unsafe or fail-open extension SQL."
    } else {
        $DatabaseArguments = @($Arguments | Where-Object { $_ -like "CASEOPS_DATABASE_URL=*" })
        Assert-Guard ($DatabaseArguments.Count -eq 1) "Expected one image database URL."
        $Url = [Uri]$DatabaseArguments[0].Substring("CASEOPS_DATABASE_URL=".Length)
        $Name = $Url.AbsolutePath.TrimStart('/')
        Assert-Guard ($Url.Host -eq "postgres" -and $Url.Port -eq 5432) "Image database escaped the owned instance."
        Assert-Guard ($script:Databases.ContainsKey($Name) -and $Name -ne "caseops") "Image command targeted browser database."
        Assert-Guard ($Arguments -contains $ApiImageId -and $Arguments -contains $AcceptanceNetworkId) "Command did not pin inspected image/network."
        foreach ($Flag in @("HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "CASEOPS_AUTO_MIGRATE=false")) {
            Assert-Guard ($Arguments -contains $Flag) "Lost offline/migration flag: $Flag"
        }
        if ($Stage -eq "upgrade") {
            Assert-Guard ($script:Databases[$Name].schema -eq "empty" -and $script:Databases[$Name].tenants -eq 0) "Upgrade was not independent and fresh."
            Assert-Guard (($Arguments[-3..-1] -join " ") -eq "alembic upgrade head") "Incomplete migration upgrade."
            $script:Databases[$Name].schema = "head"
        } elseif ($Stage -eq "seed") {
            Assert-Guard ($script:Databases[$Name].schema -eq "head") "Seed preceded migration."
            $script:Databases[$Name].seeded = $true
        }
    }
}

function Invoke-FakePytest {
    $Arguments = @($args)
    Add-Invocation "pytest" $Arguments
    Assert-Guard ((Get-Location).Path -eq $ApiDir) "Pytest did not run in the candidate API directory."
    Assert-Guard (($Arguments -join "|") -eq "-m|pytest|-q|-m|postgres|--junitxml=$(Join-Path $ResultsDirectory 'postgres.xml')") "Standard full native selection changed."
    Assert-Guard ($env:CASEOPS_DATABASE_URL -ceq $env:CASEOPS_TEST_POSTGRES_URL -and
        $env:CASEOPS_DATABASE_URL -cne $env:CASEOPS_E2E_DATABASE_URL) "Native and browser databases overlap."
    $Name = ([Uri]$env:CASEOPS_DATABASE_URL).AbsolutePath.TrimStart('/')
    Assert-Guard ($script:Databases[$Name].schema -eq "head" -and $script:Databases[$Name].seeded) "Native catalog/schema not ready."
    $script:Databases[$Name].tenants = 2271
    if (-not $script:Case.MissingJournal) {
        [IO.File]::WriteAllText($AcceptanceEnvironment.CASEOPS_TEST_RESULT_JOURNAL, "retained native result evidence")
    }
    Invoke-FakeFailure "pytest"
}

$Passed = 0
try {
    foreach ($Case in $Cases) {
        $ReleaseSha = "1" * 40
        $ComposeProject = "caseops-acceptance-111111111111-aaaaaaaaaaaa"
        $PostgresPort = "25432"
        $ApiImageId = "sha256:" + ("3" * 64)
        $AcceptanceNetworkId = "4" * 12
        $ResultsDirectory = Join-Path $Work $Case.Name
        [void][IO.Directory]::CreateDirectory($ResultsDirectory)
        $AcceptanceEnvironment = @{ CASEOPS_TEST_RESULT_JOURNAL = (Join-Path $ResultsDirectory "postgres-results.jsonl") }
        $Invocations = New-Object 'System.Collections.Generic.List[object]'
        $IndexCalls = 0
        $CaptureCalls = 0
        $CaptureAfterCleanup = $false
        $Databases = @{ caseops = @{ schema = "browser-head"; tenants = 0; seeded = $true } }
        $BeforeBrowser = $Databases.caseops | ConvertTo-Json -Compress
        if ($Case.Field) { Set-Variable -Name $Case.Field -Value $Case.Value -Scope Script }
        $BrowserDatabase = if ($Case.BrowserDatabase) { $Case.BrowserDatabase } else { "caseops" }
        $BeforeTestUrl = if ($Case.Unset) { $null } else { "caller-test-url" }
        $BeforeDatabaseUrl = if ($Case.Unset) { $null } else { "caller-application-url" }
        $BeforeBrowserUrl = "postgresql+psycopg://caseops:caseops@127.0.0.1:25432/$BrowserDatabase"
        if ($Case.Unset) {
            Remove-Item -LiteralPath Env:CASEOPS_TEST_POSTGRES_URL -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath Env:CASEOPS_DATABASE_URL -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable("CASEOPS_TEST_POSTGRES_URL", $BeforeTestUrl, "Process")
            [Environment]::SetEnvironmentVariable("CASEOPS_DATABASE_URL", $BeforeDatabaseUrl, "Process")
        }
        [Environment]::SetEnvironmentVariable("CASEOPS_E2E_DATABASE_URL", $BeforeBrowserUrl, "Process")
        $global:LASTEXITCODE = 0
        $ErrorText = $null
        try { Invoke-IsolatedNativePostgresGate -Validation $NativeValidation }
        catch { $ErrorText = $_.Exception.Message }
        $ObservedExit = $LASTEXITCODE
        try {
            if ($Case.Error) {
                Assert-Guard ($ErrorText -and $ErrorText.Contains($Case.Error)) "Wrong or missing failure: $ErrorText"
                Assert-Guard ($ObservedExit -eq $Case.Exit) "Exit $ObservedExit replaced expected $($Case.Exit)."
            } else {
                Assert-Guard (-not $ErrorText -and $ObservedExit -eq 0) "Successful gate failed: $ErrorText"
            }
            Assert-Guard ($env:CASEOPS_TEST_POSTGRES_URL -ceq $BeforeTestUrl -and
                $env:CASEOPS_DATABASE_URL -ceq $BeforeDatabaseUrl -and
                $env:CASEOPS_E2E_DATABASE_URL -ceq $BeforeBrowserUrl) "Gate failed to restore database environment."
            Assert-Guard ((Get-Location).Path -eq $InitialLocation) "Gate failed to restore caller location."
            Assert-Guard (($Databases.caseops | ConvertTo-Json -Compress) -ceq $BeforeBrowser) "Native fixtures changed browser data."
            if ($Case.Field -or $Case.BrowserDatabase) {
                Assert-Guard ($Invocations.Count -eq 0) "Invalid identity reached a native command."
            } elseif ($Case.Stage -eq "createdb") {
                Assert-Guard ($Invocations.Count -eq 1 -and $Databases.Count -eq 1) "Creation failure dropped/reused a database or continued."
            } else {
                Assert-Guard ($Invocations[-1].stage -eq "dropdb") "Owned native database cleanup not attempted."
                if ($Case.Stage -ne "dropdb" -and -not $Case.CleanupKind) {
                    Assert-Guard ($Databases.Count -eq 1) "Owned native database leaked."
                }
            }
            if ($Case.Stage -and $Case.Stage -ne "dropdb" -or $Case.MissingJournal) {
                Assert-Guard ($CaptureCalls -eq 1 -and -not $CaptureAfterCleanup) "Native failure omitted pre-cleanup evidence capture."
            }
            if (-not $Case.Error) {
                $ExpectedStages = "createdb,extension,upgrade,seed,pre-index,pytest,post-index,dropdb"
                Assert-Guard (($Invocations.stage -join ',') -eq $ExpectedStages) "Wrong migration/seed/index/execution order."
            }
            if ($Case.Repeat) {
                $ComposeProject = "caseops-acceptance-111111111111-bbbbbbbbbbbb"
                Invoke-IsolatedNativePostgresGate -Validation $NativeValidation
                $Creates = @($Invocations | Where-Object { $_.stage -eq "createdb" })
                Assert-Guard ($Creates.Count -eq 2 -and $Creates[0].arguments[-1] -cne $Creates[1].arguments[-1]) "Second invocation reused a native database."
                Assert-Guard (@($Invocations | Where-Object { $_.stage -eq "upgrade" }).Count -eq 2) "Second database not independently upgraded."
                Assert-Guard ($Databases.Count -eq 1 -and $env:CASEOPS_TEST_POSTGRES_URL -ceq $BeforeTestUrl -and
                    $env:CASEOPS_DATABASE_URL -ceq $BeforeDatabaseUrl -and $env:CASEOPS_E2E_DATABASE_URL -ceq $BeforeBrowserUrl) "Second gate leaked data/environment."
            }
            $Passed++
            $Outcome = "passed"
        }
        catch {
            $Outcome = "failed"
            throw
        }
        finally {
            $Row = [ordered]@{ event = "case_report"; nodeid = $Case.Name; outcome = $Outcome; gate_error = $ErrorText; exit_code = $ObservedExit; invocations = @($Invocations.ToArray()) }
            [IO.File]::AppendAllText($Journal, (($Row | ConvertTo-Json -Depth 8 -Compress) + "`n"))
        }
    }
    Assert-Guard ($Passed -eq $Cases.Count) "Incomplete guard inventory."
    [IO.File]::WriteAllText($CompletionPath, (@{ event = "execution_finished"; tests = $Passed; exit_code = 0 } | ConvertTo-Json))
    Write-Host "[docker-acceptance] native PostgreSQL isolation guard: $Passed regression cases passed"
}
finally {
    foreach ($Name in $SavedEnvironment.Keys) {
        if ($null -eq $SavedEnvironment[$Name]) {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], "Process")
        }
    }
    # The guard owns this freshly generated temp directory, never a checkout.
    $FullWork = [IO.Path]::GetFullPath($Work)
    $FullTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]"\/") + [IO.Path]::DirectorySeparatorChar
    if (-not $FullWork.StartsWith($FullTemp, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Guard cleanup escaped its generated temp root."
    }
    if ($RetainEvidence -and ([IO.Path]::GetFullPath($EvidenceDirectory)).StartsWith($FullWork + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Retained guard evidence must live outside disposable fixtures."
    }
    Remove-Item -LiteralPath $FullWork -Recurse -Force
}
