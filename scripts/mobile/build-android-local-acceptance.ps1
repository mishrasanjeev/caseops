[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PublicCaFile,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{64}$')][string]$PublicCaSha256,
    [string]$ApiOrigin = 'https://10.0.2.2:8443',
    [string]$WebOrigin = 'https://10.0.2.2:3443',
    [ValidateSet('x86_64', 'arm64-v8a')][string]$Architecture = 'x86_64'
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$app = Join-Path $repo 'apps/mobile'
$proof = Join-Path $PSScriptRoot 'build-acceptance.mjs'
$run = Join-Path $HOME ('.cache/caseops-mobile/builds/android-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $run

function Invoke-BuildCommand {
    param([string]$Command, [string[]]$Arguments, [string]$Log)
    $null = Get-Command $Command -ErrorAction Stop
    $preference = $ErrorActionPreference
    try {
        # Windows PowerShell turns native stderr into ErrorRecords, even for successful tools.
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = $null
        & $Command @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $run $Log)
        $nativeExit = $global:LASTEXITCODE
    } finally { $ErrorActionPreference = $preference }
    if ($null -eq $nativeExit -or $nativeExit -ne 0) { throw "Build step failed ($nativeExit); retained $Log in $run" }
}

$names = @('JAVA_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'APPIUM_HOME', 'GRADLE_USER_HOME', 'PATH',
    'CASEOPS_MOBILE_BUILD_PROFILE', 'CASEOPS_MOBILE_AUTOMATED_TEST', 'CASEOPS_MOBILE_RELEASE_SHA',
    'CASEOPS_MOBILE_ANDROID_CA_FILE', 'CASEOPS_MOBILE_ANDROID_CA_SHA256',
    'EXPO_PUBLIC_API_ORIGIN', 'EXPO_PUBLIC_WEB_ORIGIN', 'NODE_ENV', 'EXPO_NO_DOTENV', 'CASEOPS_MOBILE_NATIVE_STAGING')
$prior = @{}
foreach ($name in $names) { $prior[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
Push-Location $app
try {
    # Session-only tooling. Do not pass -Persist or modify any execution policy.
    . (Join-Path $PSScriptRoot 'use-android-env.ps1')
    $env:CASEOPS_MOBILE_BUILD_PROFILE = 'android-local-acceptance'
    $env:CASEOPS_MOBILE_AUTOMATED_TEST = '1'
    $env:CASEOPS_MOBILE_RELEASE_SHA = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot identify current source' }
    $env:CASEOPS_MOBILE_ANDROID_CA_FILE = $PublicCaFile
    $env:CASEOPS_MOBILE_ANDROID_CA_SHA256 = $PublicCaSha256
    $env:EXPO_PUBLIC_API_ORIGIN = $ApiOrigin
    $env:EXPO_PUBLIC_WEB_ORIGIN = $WebOrigin
    $env:NODE_ENV = 'production'
    $env:EXPO_NO_DOTENV = '1'
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $repoKey = [BitConverter]::ToString($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($repo.ToLowerInvariant()))).Replace('-', '').Substring(0, 12).ToLowerInvariant() }
    finally { $sha.Dispose() }
    $env:CASEOPS_MOBILE_NATIVE_STAGING = Join-Path $HOME ('.cache/caseops-mobile/cxx/' + $repoKey)
    Invoke-BuildCommand 'node' @($proof, 'check', 'android', (Join-Path $run 'before.json')) 'before.log'
    Invoke-BuildCommand 'node' @('./node_modules/expo/bin/cli', 'prebuild', '--platform', 'android', '--no-install') 'prebuild.log'
    Push-Location (Join-Path $app 'android')
    try {
        # This invokes export:embed as a finite build task, never a Metro development server.
        $gradleArgs = @(':app:assembleLocalAcceptance', "-PreactNativeArchitectures=$Architecture", '--console=plain', '--no-daemon', '--init-script', (Join-Path $PSScriptRoot 'windows-native-paths.gradle'))
        Invoke-BuildCommand './gradlew.bat' $gradleArgs 'gradle.log'
    } finally { Pop-Location }
    $apk = Join-Path $app 'android/app/build/outputs/apk/localAcceptance/app-localAcceptance.apk'
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw 'Current local acceptance APK missing' }
    $retainedApk = Join-Path $run 'caseops-local-acceptance.apk'
    Copy-Item -LiteralPath $apk -Destination $retainedApk
    $apk = $retainedApk
    $aapt = Join-Path $env:ANDROID_HOME 'build-tools/37.0.0/aapt2.exe'
    $badging = @(& $aapt dump badging $apk 2>&1)
    $badging | Set-Content -LiteralPath (Join-Path $run 'apk-badging.log')
    if ($LASTEXITCODE -ne 0 -or -not ($badging -match "package: name='ai.caseops.mobile.dev.localacceptance'")) { throw 'QA package identity not proved' }
    if ($badging -match '^application-debuggable') { throw 'Acceptance APK is debuggable' }
    $resourcePlanFile = Join-Path $run 'android-resources.json'
    Invoke-BuildCommand 'node' @($proof, 'android-resources', (Join-Path $run 'before.json'), $apk, $aapt, $run, $resourcePlanFile) 'resource-inspection.log'
    $resourcePlan = Get-Content -LiteralPath $resourcePlanFile -Raw | ConvertFrom-Json
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($apk)
    try {
        if ($zip.Entries.Count -gt 30000) { throw 'APK ZIP entry bound exceeded' }
        $inventory = @($zip.Entries | ForEach-Object { [pscustomobject]@{ name = $_.FullName; length = $_.Length } })
        [System.IO.File]::WriteAllText((Join-Path $run 'apk-zip-inventory.json'), (ConvertTo-Json -InputObject $inventory -Depth 3), [System.Text.UTF8Encoding]::new($false))
        foreach ($required in @('AndroidManifest.xml', 'assets/index.android.bundle', 'assets/app.config', $resourcePlan.ca.path, $resourcePlan.network.path)) {
            if (@($zip.Entries | Where-Object { $_.FullName -ceq $required }).Count -ne 1) { throw 'Required APK ZIP entry missing or duplicated' }
        }
        $bundle = $zip.GetEntry('assets/index.android.bundle')
        if (-not $bundle -or $bundle.Length -eq 0 -or $bundle.Length -gt 33554432) { throw 'Bundled JavaScript missing or unbounded' }
        $config = $zip.GetEntry('assets/app.config')
        if (-not $config -or $config.Length -eq 0 -or $config.Length -gt 1048576) { throw 'Embedded Expo configuration missing or unbounded' }
        $reader = [System.IO.StreamReader]::new($config.Open())
        try { [System.IO.File]::WriteAllText((Join-Path $run 'embedded-config.json'), $reader.ReadToEnd(), [System.Text.UTF8Encoding]::new($false)) }
        finally { $reader.Dispose() }
        $ca = $zip.GetEntry($resourcePlan.ca.path)
        if (-not $ca -or $ca.Length -eq 0 -or $ca.Length -gt 16384) { throw 'QA public CA missing or unbounded' }
        $stream = $ca.Open()
        $memory = [System.IO.MemoryStream]::new()
        try {
            $buffer = New-Object byte[] 4096
            while (($count = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                if ($memory.Length + $count -gt 16384) { throw 'APK CA stream size bound exceeded' }
                $memory.Write($buffer, 0, $count)
            }
            [System.IO.File]::WriteAllBytes((Join-Path $run 'public-ca-from-apk.pem'), $memory.ToArray())
        }
        finally {
            $stream.Dispose()
            $memory.Dispose()
        }
    } finally { $zip.Dispose() }
    $securityProof = Join-Path $run 'android-security.json'
    Invoke-BuildCommand 'node' @($proof, 'android-zip', $resourcePlanFile, (Join-Path $run 'apk-zip-inventory.json'), (Join-Path $run 'public-ca-from-apk.pem'), (Join-Path $run 'before.json'), $apk, $securityProof) 'zip-inspection.log'
    Invoke-BuildCommand 'node' @($proof, 'finish', 'android', (Join-Path $run 'before.json'), $retainedApk, (Join-Path $run 'embedded-config.json'), (Join-Path $run 'receipt.json'), $securityProof) 'receipt.log'
    Write-Output "Standalone APK and receipts: $run"
    Write-Output 'Build only. Parent owns emulator, browser trust, installation and core E2E.'
} catch {
    $_ | Format-List * -Force | Out-String | Set-Content -LiteralPath (Join-Path $run 'wrapper-error.log')
    throw
} finally {
    Pop-Location
    foreach ($name in $names) {
        [Environment]::SetEnvironmentVariable($name, $prior[$name], 'Process')
    }
    Write-Output "Raw build evidence retained: $run"
}
