[CmdletBinding()]
param([switch]$Persist)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'android-tooling.ps1')
$sdk = Join-Path $env:LOCALAPPDATA 'Android/Sdk'
$jdkRoot = Join-Path $HOME '.cache/caseops-mobile/jdk21'
$jdk = Get-AndroidJdk $jdkRoot
if (-not (Test-Path -LiteralPath (Join-Path $sdk 'cmdline-tools/15859902/bin/sdkmanager.bat') -PathType Leaf)) { throw 'Run setup-android.ps1 first' }
$values = @{ JAVA_HOME = $jdk; ANDROID_HOME = $sdk; ANDROID_SDK_ROOT = $sdk; APPIUM_HOME = (Join-Path $HOME '.cache/caseops-mobile/appium') }
foreach ($name in $values.Keys) {
    Set-Item -LiteralPath "Env:$name" -Value $values[$name]
    if ($Persist) { [Environment]::SetEnvironmentVariable($name, $values[$name], 'User') }
}
# Keep Gradle caches and workstation-only build settings out of the shared home.
$env:GRADLE_USER_HOME = Join-Path $HOME '.cache/caseops-mobile/gradle'
$bins = @((Join-Path $jdk 'bin'), (Join-Path $sdk 'platform-tools'), (Join-Path $sdk 'emulator'), (Join-Path $sdk 'cmdline-tools/15859902/bin'))
$env:PATH = Merge-AndroidToolPath $bins $env:PATH
if ($Persist) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    [Environment]::SetEnvironmentVariable('Path', (Merge-AndroidToolPath $bins $userPath), 'User')
}
Write-Output 'Android environment configured for this shell.'
Write-Output 'GRADLE_USER_HOME is CaseOps-specific and session-only.'
if ($Persist) { Write-Output 'User environment persisted. Existing apps may need restart or explicit shell activation. Machine environment was not changed.' }
