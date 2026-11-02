$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$clock = [Diagnostics.Stopwatch]::StartNew()
function Check { if ($clock.ElapsedMilliseconds -ge 10000) { throw 'COMMAND_FIELD_DEADLINE' } }

# Execute the production field validator with independent literal ABI fixtures.
# This tests PowerShell arithmetic/guards; it never calls a Windows API or an
# ACL setter and does not establish native Windows handle acceptance.
$source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'host-node-trust-ci.mjs'))
$stream = [IO.FileStream]::new($source, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
try {
    if ($stream.Length -le 0 -or $stream.Length -gt 65536) { throw 'COMMAND_FIELD_SOURCE_BOUND' }
    $bytes = [byte[]]::new([int]$stream.Length + 1)
    $n = 0
    while ($n -lt $bytes.Length) {
        Check
        $got = $stream.Read($bytes, $n, $bytes.Length - $n)
        if ($got -eq 0) { break }
        $n += $got
    }
    if ($n -ne $stream.Length) { throw 'COMMAND_FIELD_SOURCE_EXTENT' }
    $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes, 0, $n)
} finally { $stream.Dispose() }
$entry = $text.IndexOf('export function hardenCITrustRunnerCommand(', [StringComparison]::Ordinal)
if ($entry -lt 0) { throw 'COMMAND_FIELD_ENTRY' }
$marker = 'const code = String.raw' + [char]96
$start = $text.IndexOf($marker, $entry, [StringComparison]::Ordinal)
if ($start -lt 0) { throw 'COMMAND_FIELD_PROGRAM' }
$start += $marker.Length
$finish = $text.IndexOf(([char]96).ToString() + ';', $start, [StringComparison]::Ordinal)
if ($finish -le $start) { throw 'COMMAND_FIELD_PROGRAM' }
$program = $text.Substring($start, $finish - $start)
if ($program.Contains('${')) { throw 'COMMAND_FIELD_INTERPOLATION' }
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($program, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw 'COMMAND_FIELD_PARSE' }
$definitions = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Identity' }, $true))
if ($definitions.Count -ne 1) { throw 'COMMAND_FIELD_FUNCTION' }
if ($program.IndexOf('$first=Identity', [StringComparison]::Ordinal) -ge $program.IndexOf('$f.SetAccessControl($a)', [StringComparison]::Ordinal)) { throw 'COMMAND_FIELD_EFFECT_ORDER' }
. ([ScriptBlock]::Create($definitions[0].Extent.Text))

class CaseOpsCommandFieldHandle {
    [IntPtr] DangerousGetHandle() { return [IntPtr]::new(1) }
}
class CaseOpsCommandFieldNative {
    static [byte[]] $Bytes
    static [bool] $Accept = $true
    static [bool] GetFileInformationByHandle([IntPtr] $handle, [IntPtr] $destination) {
        if (-not [CaseOpsCommandFieldNative]::Accept -or $handle -eq [IntPtr]::Zero -or [CaseOpsCommandFieldNative]::Bytes.Length -ne 52) { return $false }
        [Runtime.InteropServices.Marshal]::Copy([CaseOpsCommandFieldNative]::Bytes, 0, $destination, 52)
        return $true
    }
}
$native = [CaseOpsCommandFieldNative]
$f = [pscustomobject]@{ Length = [long]17; SafeFileHandle = [CaseOpsCommandFieldHandle]::new() }
$info = [Runtime.InteropServices.Marshal]::AllocHGlobal(52)
function Put32([byte[]] $b, [int] $offset, [uint32] $value) { [BitConverter]::GetBytes($value).CopyTo($b, $offset) }
function Fixture([string] $id) {
    $b = [byte[]]::new(52)
    Put32 $b 0 32
    [BitConverter]::GetBytes([uint64]116444736123456789).CopyTo($b, 4)
    [BitConverter]::GetBytes([uint64]116444736987654321).CopyTo($b, 20)
    Put32 $b 28 2712847316
    Put32 $b 36 17
    Put32 $b 40 1
    $index = [BitConverter]::GetBytes([uint64]::Parse($id, [Globalization.CultureInfo]::InvariantCulture))
    [Array]::Copy($index, 4, $b, 44, 4)
    [Array]::Copy($index, 0, $b, 48, 4)
    return ,$b
}
$cases = @(
    @{ name = 'literal-64-bit-identity'; pass = $true; id = '1234605616436508552' },
    @{ name = 'unsigned-high-bit-identity'; pass = $true; id = '17375808098319191535' },
    @{ name = 'same-byte-substitute-inode'; pass = $false; offset = 48; value = 1 },
    @{ name = 'foreign-volume'; pass = $false; offset = 28; value = 1 },
    @{ name = 'changed-birth'; pass = $false; offset = 4; value = 1 },
    @{ name = 'changed-write-time'; pass = $false; offset = 20; value = 1 },
    @{ name = 'hardlinked-handle'; pass = $false; offset = 40; value = 2 },
    @{ name = 'unlinked-handle'; pass = $false; offset = 40; value = 0 },
    @{ name = 'directory-handle'; pass = $false; offset = 0; value = 16 },
    @{ name = 'reparse-handle'; pass = $false; offset = 0; value = 1024 },
    @{ name = 'changed-native-size'; pass = $false; offset = 36; value = 18 },
    @{ name = 'changed-stream-size'; pass = $false; length = 18 },
    @{ name = 'failed-native-observation'; pass = $false; nativeFailure = $true }
)
$results = @()
try {
    foreach ($case in $cases) {
        Check
        $id = if ($case.ContainsKey('id')) { $case.id } else { '1234605616436508552' }
        $env:CASEOPS_COMMAND_INO = $id
        $env:CASEOPS_COMMAND_VOLUME = '2712847316'
        $env:CASEOPS_COMMAND_BIRTH = '12345678900'
        $env:CASEOPS_COMMAND_MTIME = '98765432100'
        $env:CASEOPS_COMMAND_LENGTH = '17'
        $b = Fixture $id
        if ($case.ContainsKey('offset')) { Put32 $b $case.offset $case.value }
        $f.Length = if ($case.ContainsKey('length')) { [long]$case.length } else { [long]17 }
        [CaseOpsCommandFieldNative]::Accept = -not $case.ContainsKey('nativeFailure')
        [CaseOpsCommandFieldNative]::Bytes = $b
        $failure = $null; $value = $null
        try { $value = Identity } catch { $failure = $_ }
        if ($case.pass) {
            if ($null -ne $failure -or $value -isnot [byte[]] -or $value.Length -ne 52) { throw ('COMMAND_FIELD_POSITIVE_' + $case.name) }
        } elseif ($null -eq $failure -or $failure.Exception.Message -ne 'identity') { throw ('COMMAND_FIELD_NEGATIVE_' + $case.name) }
        $results += @{ name = $case.name; passed = $true }
    }
} finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($info) }
if ($results.Count -ne 13) { throw 'COMMAND_FIELD_INVENTORY' }
@{ complete = $true; passed = 13; failed = 0; skipped = 0; cancelled = 0; todo = 0; cases = $results; nativeWindowsApiExecuted = $false; aclSettersExecuted = 0; scope = 'Production PowerShell field-validator logic with independent synthetic ABI fixtures; native Windows acceptance is separate.' } | ConvertTo-Json -Depth 5 -Compress
