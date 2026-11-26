[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'android-tooling.ps1')
$cache = Join-Path $HOME '.cache/caseops-mobile'
$downloads = Join-Path $cache 'downloads'
$sdk = Join-Path $env:LOCALAPPDATA 'Android/Sdk'
$tools = Join-Path $sdk 'cmdline-tools/15859902'
$jdkRoot = Join-Path $cache 'jdk21'
New-Item -ItemType Directory -Path $downloads -Force | Out-Null

# Refuse partial existing installations before acquiring anything; never repair them in place.
if (Test-Path -LiteralPath $jdkRoot) { Get-AndroidJdk $jdkRoot | Out-Null }
if ((Test-Path -LiteralPath $tools) -and -not (Test-Path -LiteralPath (Join-Path $tools 'bin/sdkmanager.bat') -PathType Leaf)) {
    throw "Refusing to replace an incomplete command-tools installation: $tools"
}
if (-not (Test-Path -LiteralPath (Join-Path $tools 'bin/sdkmanager.bat'))) {
    $archive = Get-VerifiedArchive 'https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip' 'commandlinetools-win-15859902_latest.zip' '90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a' $downloads
    Install-AndroidCommandTools $archive $sdk | Out-Null
}

if (-not (Test-Path -LiteralPath $jdkRoot)) {
    $archive = Get-VerifiedArchive 'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13.1%2B2/OpenJDK21U-jdk_x64_windows_hotspot_21.0.13.1_2.zip' 'temurin21-21.0.13.1_2.zip' 'bbebea1469996b276683c9299c227b294f85c847039c82633218186a4ad4fbf2' $downloads
    Install-AndroidJdk $archive $jdkRoot | Out-Null
}
$jdk = Get-AndroidJdk $jdkRoot
$env:JAVA_HOME = $jdk
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
$bins = @((Join-Path $jdk 'bin'), (Join-Path $sdk 'platform-tools'), (Join-Path $sdk 'emulator'), (Join-Path $tools 'bin'))
$env:PATH = Merge-AndroidToolPath $bins $env:PATH
Write-Output "ANDROID_HOME=$sdk"
Write-Output "JAVA_HOME=$jdk"
Write-Output 'Tool/JDK preparation complete. This command does not install SDK packages or accept licences; owner-authorized package setup is separate.'
