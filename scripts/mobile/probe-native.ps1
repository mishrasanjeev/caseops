[CmdletBinding()]
param([string]$OutputPath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'android-tooling.ps1')
function Find-Tool([string]$Name) {
    $tool = Get-Command $Name -ErrorAction SilentlyContinue
    if ($tool) { return $tool.Source }
    return $null
}
$sdk = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT, "$env:LOCALAPPDATA/Android/Sdk") |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$computer = Get-CimInstance Win32_ComputerSystem
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$result = [ordered]@{
    schemaVersion = 1
    observedAt = [DateTime]::UtcNow.ToString('o')
    platform = 'win32'
    tools = [ordered]@{}
    androidSdk = $sdk
    javaHome = $env:JAVA_HOME
    freeDiskGiB = [math]::Round($disk.FreeSpace / 1GB, 2)
    memoryGiB = [math]::Round($computer.TotalPhysicalMemory / 1GB, 2)
    cpu = $cpu.Name
    hypervisorPresent = $computer.HypervisorPresent
    firmwareVirtualizationReported = $cpu.VirtualizationFirmwareEnabled
    acceleration = 'Unverified: require emulator -accel-check; hypervisor can mask CPU flags'
    nativeProcesses = @(Get-Process -Name emulator,qemu-system-x86_64,adb,java -ErrorAction SilentlyContinue |
        Select-Object Id,ProcessName)
    ios = 'Not run: iOS Simulator and XCUITest require owner MacBook with Xcode'
    sdkLicenseAction = 'None; licence acceptance is owner-authorized and handled separately'
}
foreach ($name in @('node', 'npm', 'java', 'javac', 'adb', 'emulator', 'sdkmanager', 'appium', 'xcodebuild')) {
    $result.tools[$name] = Find-Tool $name
}
$json = $result | ConvertTo-Json -Depth 6
if ($OutputPath) {
    Write-AndroidProbe $OutputPath $json
}
$json
