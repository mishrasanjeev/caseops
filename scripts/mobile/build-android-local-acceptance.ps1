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
    'EXPO_PUBLIC_API_ORIGIN', 'EXPO_PUBLIC_WEB_ORIGIN', 'NODE_ENV', 'EXPO_NO_DOTENV')
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
    Invoke-BuildCommand 'node' @($proof, 'check', 'android', (Join-Path $run 'before.json')) 'before.log'
    Invoke-BuildCommand 'node' @('./node_modules/expo/bin/cli', 'prebuild', '--platform', 'android', '--no-install') 'prebuild.log'
    Push-Location (Join-Path $app 'android')
    try {
        # This invokes export:embed as a finite build task, never a Metro development server.
        $gradleArgs = @(':app:assembleLocalAcceptance', "-PreactNativeArchitectures=$Architecture", '--console=plain', '--no-daemon')
        Invoke-BuildCommand './gradlew.bat' $gradleArgs 'gradle.log'
    } finally { Pop-Location }
    $apk = Join-Path $app 'android/app/build/outputs/apk/localAcceptance/app-localAcceptance.apk'
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw 'Current local acceptance APK missing' }
    $aapt = Join-Path $env:ANDROID_HOME 'build-tools/37.0.0/aapt2.exe'
    $badging = @(& $aapt dump badging $apk 2>&1)
    $badging | Set-Content -LiteralPath (Join-Path $run 'apk-badging.log')
    if ($LASTEXITCODE -ne 0 -or -not ($badging -match "package: name='ai.caseops.mobile.dev.localacceptance'")) { throw 'QA package identity not proved' }
    if ($badging -match '^application-debuggable') { throw 'Acceptance APK is debuggable' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($apk)
    try {
        $bundle = $zip.GetEntry('assets/index.android.bundle')
        if (-not $bundle -or $bundle.Length -eq 0) { throw 'Bundled JavaScript missing' }
        $config = $zip.GetEntry('assets/app.config')
        if (-not $config) { throw 'Embedded Expo configuration missing' }
        $reader = [System.IO.StreamReader]::new($config.Open())
        try { [System.IO.File]::WriteAllText((Join-Path $run 'embedded-config.json'), $reader.ReadToEnd(), [System.Text.UTF8Encoding]::new($false)) }
        finally { $reader.Dispose() }
        $ca = $zip.GetEntry('res/raw/caseops_local_acceptance_ca.pem')
        if (-not $ca) { throw 'QA public CA missing from APK' }
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $stream = $ca.Open()
        try { $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally {
            $stream.Dispose()
            $sha.Dispose()
        }
        if ($actual -ne $PublicCaSha256) { throw 'APK public CA hash mismatch' }
    } finally { $zip.Dispose() }
    $retainedApk = Join-Path $run 'caseops-local-acceptance.apk'
    Copy-Item -LiteralPath $apk -Destination $retainedApk
    Invoke-BuildCommand 'node' @($proof, 'finish', 'android', (Join-Path $run 'before.json'), $retainedApk, (Join-Path $run 'embedded-config.json'), (Join-Path $run 'receipt.json')) 'receipt.log'
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
