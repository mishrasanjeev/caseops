#requires -Version 7.0
[CmdletBinding()]
param([switch]$WithJdk, [string]$RuntimeRoot)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'This provisioner is Windows-only; use the scoped Node recipe in MACBOOK_RUNBOOK.md on macOS' }
if ($WithJdk) { throw 'JDK downloading uses another TLS runtime. Supply a separately verified platform JDK; no .NET network request is authorised here.' }
# A fresh root preserves every older successful, rejected or unknown SDK home.
$base = Join-Path $HOME '.cache/caseops-mobile'
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $base ('runtime-android-appium39-' + [Guid]::NewGuid().ToString('N')) }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
if (Test-Path -LiteralPath $RuntimeRoot) { throw 'The runtime root must not exist; retained homes are never overwritten or retried' }
$node = (Get-Command node -CommandType Application).Source
$npm = Join-Path (Split-Path -Parent $node) 'node_modules/npm/bin/npm-cli.js'
$deadline = [DateTime]::UtcNow.AddSeconds(900)
# Reject inherited competing policy, rather than silently removing it.
$inherited = [Environment]::GetEnvironmentVariables()
foreach ($key in $inherited.Keys) {
    if ($key -match '^(NODE_OPTIONS|NODE_EXTRA_CA_CERTS|NODE_USE_SYSTEM_CA|NODE_TLS_REJECT_UNAUTHORIZED|SSL_CERT_FILE|SSL_CERT_DIR|OPENSSL_CONF|OPENSSL_CONF_INCLUDE)$' -or
        $key -match '^npm_config_(ca|cafile|node_options)$' -or ($key -match '^npm_config_strict_ssl$' -and $inherited[$key] -ne 'true')) {
        throw 'Start from a validated neutral per-runtime environment; inherited trust overrides are refused'
    }
}
New-Item -ItemType Directory -Path $RuntimeRoot -ErrorAction Stop | Out-Null
$logs = Join-Path $RuntimeRoot 'logs'
New-Item -ItemType Directory -Path $logs -ErrorAction Stop | Out-Null
$environment = @{}
foreach ($key in @('PATH','SystemRoot','WINDIR','HOME','USERPROFILE','LOCALAPPDATA','APPDATA','TEMP','TMP',
    'CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE','CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256')) {
    if ($inherited.Contains($key)) { $environment[$key] = [string]$inherited[$key] }
}
function Get-ProcessSnapshot([int]$ProcessId) {
    $row = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $ProcessId) -ErrorAction Stop
    if (-not $row -or -not $row.CreationDate -or -not $row.ExecutablePath -or -not $row.CommandLine) { throw 'Process identity unavailable' }
    return @([string]$row.ProcessId, [string]$row.ParentProcessId,
        $row.CreationDate.ToUniversalTime().ToString('o'),
        [IO.Path]::GetFullPath($row.ExecutablePath), [string]$row.CommandLine)
}
function Test-ExactSnapshot($Left, $Right) {
    if ($null -eq $Left -or $null -eq $Right -or $Left.Count -ne 5 -or $Right.Count -ne 5) { return $false }
    foreach ($i in @(0,1,2,3,4)) { if (-not [String]::Equals($Left[$i], $Right[$i], [StringComparison]::Ordinal)) { return $false } }
    return $true
}
function Invoke-OwnedNode([string]$Name, [string[]]$Arguments) {
    if ([DateTime]::UtcNow -ge $deadline.AddSeconds(-30)) { throw 'Setup deadline reached before child admission' }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $node; $start.WorkingDirectory = $RuntimeRoot
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
    $start.Environment.Clear()
    foreach ($key in $environment.Keys) { $start.Environment[$key] = $environment[$key] }
    foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }
    $outPath = Join-Path $logs ($Name + '.stdout.log'); $errPath = Join-Path $logs ($Name + '.stderr.log')
    $out = [IO.File]::Open($outPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $err = $null; $process = $null; $started = $false; $childIdentity = $null; $parentIdentity = $null; $failure = $null; $cleanupFailure = $null; $exit = $null
    try {
        $err = [IO.File]::Open($errPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        $process = [Diagnostics.Process]::new(); $process.StartInfo = $start
        if (-not $process.Start()) { throw 'Owned Node child did not start' }
        $started = $true
        $created = $process.StartTime.ToUniversalTime().ToString('o')
        if (-not $process.HasExited) {
            $childIdentity = Get-ProcessSnapshot $process.Id
            $parentIdentity = Get-ProcessSnapshot $PID
            if ($childIdentity[1] -ne [string]$PID -or -not [String]::Equals($childIdentity[3], $node, [StringComparison]::OrdinalIgnoreCase)) { throw 'Owned process ancestry/executable mismatch' }
        }
        $streams = @($process.StandardOutput.BaseStream, $process.StandardError.BaseStream)
        $targets = @($out, $err); $buffers = @([byte[]]::new(32768), [byte[]]::new(32768))
        $tasks = @($streams[0].ReadAsync($buffers[0], 0, 32768), $streams[1].ReadAsync($buffers[1], 0, 32768))
        $counts = @(0L, 0L); $finished = @($false, $false)
        $childEnd = [DateTime]::UtcNow.AddSeconds(300)
        if ($childEnd -gt $deadline.AddSeconds(-30)) { $childEnd = $deadline.AddSeconds(-30) }
        while (-not ($finished[0] -and $finished[1] -and $process.HasExited)) {
            if ([DateTime]::UtcNow -ge $childEnd) { throw 'Owned Node child deadline; installation state is unknown and must not be replayed' }
            foreach ($i in @(0,1)) {
                if (-not $finished[$i] -and $tasks[$i].IsCompleted) {
                    $amount = $tasks[$i].GetAwaiter().GetResult()
                    if ($amount -eq 0) { $finished[$i] = $true; continue }
                    if ($amount -lt 0 -or $counts[$i] + $amount -gt 16777216) { throw 'Owned tool diagnostic output bound' }
                    $targets[$i].Write($buffers[$i], 0, $amount); $counts[$i] += $amount
                    $tasks[$i] = $streams[$i].ReadAsync($buffers[$i], 0, 32768)
                }
            }
            Start-Sleep -Milliseconds 10
        }
        $process.WaitForExit(); $exit = $process.ExitCode
    } catch { $failure = $_.Exception.Message }
    finally {
        if ($started) {
            try {
                if (-not $process.HasExited) {
                    $current = Get-Process -Id $process.Id -ErrorAction Stop
                    $freshChild = Get-ProcessSnapshot $process.Id; $freshParent = Get-ProcessSnapshot $PID
                    $proven = $current.StartTime.ToUniversalTime().ToString('o') -eq $created -and
                        $freshChild[1] -eq [string]$PID -and
                        (Test-ExactSnapshot $childIdentity $freshChild) -and (Test-ExactSnapshot $parentIdentity $freshParent)
                    if ($proven) {
                        # Only this exact root. Never signal an unproved child/tree.
                        $process.Kill(); $wait = [Math]::Max(0, [Math]::Min(30000, ($deadline - [DateTime]::UtcNow).TotalMilliseconds)); $null = $process.WaitForExit([int]$wait)
                    }
                    $cleanupFailure = 'Interrupted root: process metadata/descendant cleanup and installed graph require review. Retain this root; no replay.'
                }
            } catch { $cleanupFailure = 'Owned cleanup identity unavailable; no further signal; retained unknown installation.' }
        }
        if ($process) { $process.Dispose() }
        $out.Dispose(); if ($err) { $err.Dispose() }
    }
    # Successful native tools may write diagnostics on stderr. Keep both files and real status.
    if ($failure -or $cleanupFailure -or $exit -ne 0) { throw "Tool $Name failed or is unknown (exit $exit). Diagnostics: $outPath ; $errPath . Original: $failure Cleanup: $cleanupFailure" }
    return $outPath
}
# This trusted outer source holds, bounds, verifies and executes the same helper
# bytes. The policy then binds the derived inherited bootstrap and helper refs.
$prepare = @'
import fs from 'node:fs'; import path from 'node:path'; import {createHash} from 'node:crypto';
const source=path.resolve(process.argv[1]), out=path.resolve(process.argv[2]), F=['dev','ino','mode','uid','gid','nlink','size','mtimeNs','ctimeNs'];
const end=performance.now()+20000, check=()=>{if(performance.now()>=end)throw Error('HOST_TRUST_OUTER_DEADLINE')}, frame=s=>F.map(k=>String(s[k])).join(':'), hash=b=>createHash('sha256').update(b).digest('hex');
function held(file,max,pin){let fd;try{check();fd=fs.openSync(file,fs.constants.O_RDONLY|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0));const a=fs.fstatSync(fd,{bigint:true}),n=fs.lstatSync(file,{bigint:true});if(typeof process.getuid==='function'&&(a.uid!==BigInt(process.getuid())||(a.mode&0o7133n)!==0n))throw Error('HOST_TRUST_OUTER_OWNER');if(!a.isFile()||!n.isFile()||n.isSymbolicLink()||a.nlink!==1n||a.size<=0n||a.size>BigInt(max))throw Error('HOST_TRUST_OUTER_FILE');for(const k of F)if(!(process.platform==='win32'&&k==='dev'&&n.dev===0n)&&a[k]!==n[k])throw Error('HOST_TRUST_OUTER_IDENTITY');const real=fs.realpathSync.native??fs.realpathSync,canonical=real(file),namespace=()=>{let rows=[];for(let p=path.dirname(canonical);;p=path.dirname(p)){check();const s=fs.lstatSync(p,{bigint:true});if(!s.isDirectory()||s.isSymbolicLink())throw Error('HOST_TRUST_OUTER_NAMESPACE');rows.push([p,...['dev','ino','uid','gid','mode'].map(k=>String(s[k]))]);if(path.dirname(p)===p)return JSON.stringify(rows)}};const parents=namespace(),b=Buffer.alloc(Number(a.size)+1);let size=0;while(size<b.length){check();const n=fs.readSync(fd,b,size,b.length-size,null);if(!n)break;size+=n}if(BigInt(size)!==a.size||frame(fs.fstatSync(fd,{bigint:true}))!==frame(a)||frame(fs.lstatSync(file,{bigint:true}))!==frame(n)||real(file)!==canonical||namespace()!==parents)throw Error('HOST_TRUST_OUTER_CHANGED');const bytes=b.subarray(0,size);if(pin&&hash(bytes)!==pin)throw Error('HOST_TRUST_OUTER_DIGEST');return{bytes,ref:{path:canonical,sha256:hash(bytes),sizeBytes:size}}}finally{if(fd!==undefined)fs.closeSync(fd)}}
try{const pins=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(held(path.join(source,'tooling.json'),4096).bytes));if(process.versions.node!==pins.node)throw Error('HOST_TRUST_PINNED_NODE_REQUIRED');const h=held(path.join(source,'host-node-trust.mjs'),65536,pins.hostNodeTrust.helperSha256),b=held(path.join(source,'host-node-trust-start.mjs'),16384,pins.hostNodeTrust.bootstrapSha256);const module=await import('data:text/javascript;base64,'+h.bytes.toString('base64'));const prepared=module.prepareHostNodeTrust({directory:out,sourceRefs:{helper:h.ref,bootstrap:b.ref}});console.log(JSON.stringify({prepared,pins}));h.bytes.fill(0);b.bytes.fill(0)}catch{console.error('HOST_TRUST_PREPARATION_REFUSED');process.exitCode=1}
'@
$preparedPath = Invoke-OwnedNode 'trust-prepare' @('--input-type=module','-e',$prepare,$PSScriptRoot,(Join-Path $RuntimeRoot 'node-trust'))
if ((Get-Item -LiteralPath $preparedPath).Length -gt 32768) { throw 'Public trust recipe extent exceeded' }
$prepared = [IO.File]::ReadAllText($preparedPath) | ConvertFrom-Json
foreach ($property in $prepared.prepared.environment.PSObject.Properties) { $environment[$property.Name] = [string]$property.Value }
$null = Invoke-OwnedNode 'trust-verify' @((Join-Path $PSScriptRoot 'host-node-trust.mjs'),'verify')
$pins = $prepared.pins
# Anonymous public registry only; no user/global npm auth or CA configuration is read.
$config = Join-Path $RuntimeRoot 'npmrc'; $globalConfig = Join-Path $RuntimeRoot 'global-npmrc'
[IO.File]::WriteAllText($config, "registry=https://registry.npmjs.org/`nstrict-ssl=true`naudit=false`nfund=false`n")
[IO.File]::WriteAllText($globalConfig, '')
$environment['npm_config_userconfig'] = $config; $environment['npm_config_globalconfig'] = $globalConfig
$environment['npm_config_cache'] = Join-Path $RuntimeRoot 'npm-cache'; $environment['npm_config_ignore_scripts'] = 'true'
$environment['npm_config_strict_ssl'] = 'true'
$version = Invoke-OwnedNode 'npm-version' @($npm,'--version')
if ([IO.File]::ReadAllText($version).Trim() -ne $pins.npm) { throw 'Use the exact accepted npm runtime' }
$core = Join-Path $RuntimeRoot 'core'; $home = Join-Path $RuntimeRoot 'home'
New-Item -ItemType Directory -Path $core,$home -ErrorAction Stop | Out-Null
$environment['APPIUM_HOME'] = $home
$null = Invoke-OwnedNode 'core-install' @($npm,'install','--prefix',$core,'--save-exact','--ignore-scripts','--no-audit','--no-fund','--fetch-timeout=60000','--fetch-retries=1',"appium@$($pins.appium)","webdriverio@$($pins.webdriverio)")
$appium = Join-Path $core 'node_modules/appium/index.js'
$null = Invoke-OwnedNode 'driver-install' @($appium,'driver','install',"uiautomator2@$($pins.uiautomator2)")
$null = Invoke-OwnedNode 'driver-list' @($appium,'driver','list','--installed','--json')
Write-Output "CASEOPS_MOBILE_RUNTIME_ROOT=$RuntimeRoot"
Write-Output "CASEOPS_MOBILE_TOOLING_HOME=$core"
Write-Output "APPIUM_HOME=$home"
Write-Output "CASEOPS_HOST_NODE_TRUST_POLICY_FILE=$($prepared.prepared.policyRef.path)"
Write-Output "CASEOPS_HOST_NODE_TRUST_POLICY_SHA256=$($prepared.prepared.policyRef.sha256)"
Write-Output 'Preparation only. Fresh locked/physical package audits, notices, full runtime capture and loopback driver health are required before native use.'
Write-Output 'No global environment, old SDK home, Android SDK licence, system PATH or trust store was changed.'
