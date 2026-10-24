[CmdletBinding()]
param([switch]$WithJdk)
$ErrorActionPreference = 'Stop'
$pins = Get-Content -LiteralPath "$PSScriptRoot/tooling.json" -Raw | ConvertFrom-Json
$cache = Join-Path $HOME '.cache/caseops-mobile'
$tooling = Join-Path $cache 'tooling'
New-Item -ItemType Directory -Path $tooling -Force | Out-Null
$nodeVersion = & node -p 'process.versions.node'
$node = [version]$nodeVersion
if ($LASTEXITCODE -ne 0 -or -not (($node.Major -eq 22 -and $node -ge [version]'22.19.0') -or $node.Major -ge 24)) {
    throw 'Use Node 22.x >=22.19.0 or Node >=24 (24 LTS recommended); no global Node changes are performed'
}
$npmVersion = & npm --version
if ($LASTEXITCODE -ne 0 -or [version]$npmVersion -lt [version]'10.0.0') { throw 'npm >=10 is required' }
$npmArguments = @('install', '--prefix', $tooling, '--save-exact', '--no-audit', '--no-fund',
    '--fetch-timeout=60000', '--fetch-retries=1', "appium@$($pins.appium)", "webdriverio@$($pins.webdriverio)")
& npm @npmArguments
if ($LASTEXITCODE -ne 0) { throw "npm tooling installation failed: $LASTEXITCODE" }
$env:APPIUM_HOME = Join-Path $cache 'appium'
$appium = Join-Path $tooling 'node_modules/appium/index.js'
$drivers = & node $appium driver list --installed --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect installed Appium drivers' }
if ($drivers.uiautomator2 -and $drivers.uiautomator2.version -ne $pins.uiautomator2) {
    throw 'A different cached UiAutomator2 version exists; review it rather than overwrite it'
}
if (-not $drivers.uiautomator2) {
    & node $appium driver install "uiautomator2@$($pins.uiautomator2)"
    if ($LASTEXITCODE -ne 0) { throw "UiAutomator2 installation failed: $LASTEXITCODE" }
}
if ($WithJdk) {
    $archive = Join-Path $cache 'temurin17.zip'
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -Uri $pins.jdk.url -OutFile $archive -TimeoutSec 240
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pins.jdk.sha256) {
        throw 'JDK checksum mismatch; archive retained, not executed'
    }
    $jdkRoot = Join-Path $cache 'jdk'
    if (-not (Test-Path -LiteralPath $jdkRoot)) { Expand-Archive -LiteralPath $archive -DestinationPath $jdkRoot }
    $jdk = Get-ChildItem -LiteralPath $jdkRoot -Directory | Select-Object -First 1
    & (Join-Path $jdk.FullName 'bin/java.exe') -version
    if ($LASTEXITCODE -ne 0) { throw 'JDK execution failed' }
    Write-Output "Session JAVA_HOME: $($jdk.FullName)"
}
Write-Output "CASEOPS_MOBILE_TOOLING_HOME=$tooling"
Write-Output "APPIUM_HOME=$env:APPIUM_HOME"
Write-Output 'Android SDK not downloaded or installed. No SDK licenses accepted. No system PATH modified.'
