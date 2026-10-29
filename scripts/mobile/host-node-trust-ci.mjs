import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createHash, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
// Windows must stage exact reviewed bytes before loading any H code.
const unixTrust = process.platform === 'win32' ? null : await import('./host-node-trust.mjs');

const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const identity = fields.slice(0, 6);
const frame = state => fields.map(key => String(state[key]));
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const canonical = file => (fs.realpathSync.native ?? fs.realpathSync)(file);
const MAX = 1048576;
const KEYS = ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256', 'NPM_CONFIG_USERCONFIG', 'NPM_CONFIG_GLOBALCONFIG', 'NPM_CONFIG_STRICT_SSL', 'NPM_CONFIG_REGISTRY'];
function neutralConfig(file, role) {
  const bytes = Buffer.from('; CaseOps isolated public npm configuration.\n'), end = performance.now() + 5000;
  const check = () => assert.ok(performance.now() < end, 'CI_TRUST_CONFIG_DEADLINE');
  const namespace = parents(file, check); let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
    const initial = fs.fstatSync(fd, { bigint: true }); commandOwner(file, initial, role);
    assert.ok(initial.isFile() && initial.nlink === 1n && initial.size === 0n, 'CI_TRUST_EXCLUSIVE_CONFIG');
    let n = 0;
    while (n < bytes.length) { check(); const width = fs.writeSync(fd, bytes, n, bytes.length - n, n); assert.ok(width > 0); n += width; }
    fs.fsyncSync(fd); const final = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    for (const key of identity) assert.equal(initial[key], final[key], 'CI_TRUST_CONFIG_IDENTITY_CHANGED');
    checkNamed(named, final); assert.equal(final.size, BigInt(bytes.length));
    const readback = Buffer.alloc(bytes.length + 1); n = 0;
    while (n < readback.length) { check(); const width = fs.readSync(fd, readback, n, readback.length - n, n); if (!width) break; n += width; }
    assert.ok(n === bytes.length && readback.subarray(0, n).equals(bytes) && equal(frame(final), frame(fs.fstatSync(fd, { bigint: true }))) && equal(frame(named), frame(fs.lstatSync(file, { bigint: true }))) && equal(namespace, parents(file, check)) && canonical(file) === file, 'CI_TRUST_CONFIG_CHANGED');
    return file;
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
const CI_INVOCATION = Symbol('native-ci-preparation');
const RUNNER_COMMAND = Symbol('native-runner-output-command');
const COMMAND_OWNER_ROLES = new Set(['GITHUB_OUTPUT', 'NPM_USER_CONFIG', 'NPM_GLOBAL_CONFIG']);
function commandOwnerPhase(stderr) {
  if (typeof stderr !== 'string' || Buffer.byteLength(stderr) > 4096) return 'UNCLASSIFIED';
  const lines = stderr.replaceAll('\r', '').split('\n');
  if (lines.at(-1) === '') lines.pop();
  if (lines.at(-1) === 'COPS_ACL_FAIL') lines.pop();
  if (lines.length > 4 || lines.some((line, index) => line !== 'COPS_ACL' + index)) return 'UNCLASSIFIED';
  return ['NO_MARKER', 'SCRIPT_ENTERED', 'ACL_READ', 'IDENTITY_READ', 'RULES_READ'][lines.length];
}
/** Fixed public classifications only; arbitrary subprocess output is never reflected. */
export function reviewCICommandOwnerResult(result, role, admission = undefined) {
  assert.ok(COMMAND_OWNER_ROLES.has(role), 'CI_TRUST_COMMAND_OWNER_PROTOCOL');
  const prefix = 'CI_TRUST_COMMAND_OWNER_' + role + '_', phase = commandOwnerPhase(result?.stderr);
  if (result?.error?.code === 'ETIMEDOUT') throw new Error(prefix + 'TIMEOUT_' + phase);
  if (!result || result.error || result.status !== 0) throw new Error(prefix + 'COMMAND_FAILED_' + phase);
  assert.ok(typeof result.stdout === 'string' && Buffer.byteLength(result.stdout) <= 4096 && typeof result.stderr === 'string' && result.stderr.replaceAll('\r', '') === 'COPS_ACL0\nCOPS_ACL1\nCOPS_ACL2\nCOPS_ACL3\n', prefix + 'PROTOCOL_' + phase);
  if (result.stdout.trim() === 'SAFE') return { ownerMatches: true, writeScopeSafe: true };
  let parsed; try { parsed = JSON.parse(result.stdout); } catch { throw new Error(prefix + 'PROTOCOL_' + phase); }
  const owners = new Set(['CURRENT_USER', 'SYSTEM', 'ADMINISTRATORS', 'TOKEN_OTHER', 'OTHER', 'MISSING']), tokens = new Set(['CURRENT_USER', 'SYSTEM', 'ADMINISTRATORS', 'OTHER', 'MISSING']);
  assert.ok(parsed && !Array.isArray(parsed) && equal(Object.keys(parsed).sort(), ['ownerClass', 'ownerMatches', 'tokenOwnerClass', 'writeScopeSafe']) && typeof parsed.ownerMatches === 'boolean' && typeof parsed.writeScopeSafe === 'boolean' && (!parsed.ownerMatches || !parsed.writeScopeSafe) && owners.has(parsed.ownerClass) && tokens.has(parsed.tokenOwnerClass), prefix + 'PROTOCOL_' + phase);
  if (admission === RUNNER_COMMAND && role === 'GITHUB_OUTPUT' && parsed.ownerMatches === false && parsed.writeScopeSafe === true && parsed.ownerClass === 'ADMINISTRATORS' && parsed.tokenOwnerClass === 'CURRENT_USER') return { ownerMatches: false, writeScopeSafe: true, authority: 'native-runner-command-safe-administrators-owner' };
  throw new Error(prefix + 'OWNER_' + parsed.ownerClass + '_TOKEN_' + parsed.tokenOwnerClass + '_MATCH_' + (parsed.ownerMatches ? 'YES' : 'NO') + '_WRITE_' + (parsed.writeScopeSafe ? 'SAFE' : 'UNSAFE'));
}
function commandOwner(file, state, role, runnerCommand = null) {
  assert.ok(COMMAND_OWNER_ROLES.has(role), 'CI_TRUST_COMMAND_OWNER_PROTOCOL');
  if (typeof process.getuid === 'function') {
    assert.ok(state.uid === BigInt(process.getuid()) && (state.mode & 0o022n) === 0n, 'CI_TRUST_COMMAND_OWNER');
    return;
  }
  assert.ok(process.platform === 'win32' && path.isAbsolute(process.env.SystemRoot || ''), 'CI_TRUST_OWNER_UNAVAILABLE');
  const code = "$ErrorActionPreference='Stop';[Console]::Error.WriteLine('COPS_ACL0');try{$s=[Security.AccessControl.AccessControlSections]'Access,Owner';$a=[IO.File]::GetAccessControl($env:CASEOPS_TRUST_ACL_PATH,$s);[Console]::Error.WriteLine('COPS_ACL1');$i=[Security.Principal.WindowsIdentity]::GetCurrent();$u=$i.User.Value;$t=$i.Owner.Value;$o=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;[Console]::Error.WriteLine('COPS_ACL2');$ok=($o -eq $u -or ($o -eq $t -and $o -in @('S-1-5-18','S-1-5-32-544')));$safe=$true;foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($r.AccessControlType -eq 'Allow' -and ([int]$r.FileSystemRights -band 852310) -ne 0 -and $r.IdentityReference.Value -notin @($u,'S-1-5-18','S-1-5-32-544','S-1-3-0')){$safe=$false}};[Console]::Error.WriteLine('COPS_ACL3');if($ok -and $safe){[Console]::Out.Write('SAFE')}else{$oc=if([string]::IsNullOrEmpty($o)){'MISSING'}elseif($o -eq $u){'CURRENT_USER'}elseif($o -eq 'S-1-5-18'){'SYSTEM'}elseif($o -eq 'S-1-5-32-544'){'ADMINISTRATORS'}elseif($o -eq $t){'TOKEN_OTHER'}else{'OTHER'};$tc=if([string]::IsNullOrEmpty($t)){'MISSING'}elseif($t -eq $u){'CURRENT_USER'}elseif($t -eq 'S-1-5-18'){'SYSTEM'}elseif($t -eq 'S-1-5-32-544'){'ADMINISTRATORS'}else{'OTHER'};[Console]::Out.Write(('{\"ownerMatches\":'+$ok.ToString().ToLowerInvariant()+',\"writeScopeSafe\":'+$safe.ToString().ToLowerInvariant()+',\"ownerClass\":\"'+$oc+'\",\"tokenOwnerClass\":\"'+$tc+'\"}'))}}catch{[Console]::Error.WriteLine('COPS_ACL_FAIL');exit 1}";
  const proof = spawnSync(path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', code], {
    env: { SystemRoot: process.env.SystemRoot, CASEOPS_TRUST_ACL_PATH: file }, encoding: 'utf8', timeout: 4000, maxBuffer: 4096, windowsHide: true,
  });
  const result = reviewCICommandOwnerResult(proof, role, runnerCommand?.token);
  runnerCommand?.reconcile(); return result;
}
function checkNamed(named, opened) {
  for (const key of fields) if (!(process.platform === 'win32' && key === 'dev' && named.dev === 0n)) assert.equal(named[key], opened[key], 'CI_TRUST_NAMED_DESCRIPTOR_CHANGED');
}
function parents(file, check) {
  const rows = [];
  for (let current = path.dirname(file); ; current = path.dirname(current)) {
    check(); assert.ok(rows.length < 64, 'CI_TRUST_PARENT_BOUND');
    const state = fs.lstatSync(current, { bigint: true });
    assert.ok(state.isDirectory() && !state.isSymbolicLink() && canonical(current) === current, 'CI_TRUST_NAMESPACE');
    rows.push([current, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(state[key]))]);
    if (current === path.dirname(current)) return rows;
  }
}
function admittedFile(file, root) {
  assert.ok(typeof file === 'string' && typeof root === 'string' && path.isAbsolute(file) && path.isAbsolute(root), 'CI_TRUST_ABSOLUTE_PATH');
  assert.equal(path.resolve(file), file, 'CI_TRUST_CANONICAL_PATH');
  assert.equal(path.resolve(root), root, 'CI_TRUST_CANONICAL_PATH');
  assert.equal(canonical(root), root, 'CI_TRUST_CANONICAL_PATH');
  assert.equal(canonical(file), file, 'CI_TRUST_CANONICAL_PATH');
  const relative = path.relative(root, file);
  assert.ok(relative !== '' && !relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative), 'CI_TRUST_RUNNER_SCOPE');
}
function projectConfigsAbsent(workspace, check) {
  const rows = [];
  for (const relative of ['', 'apps/mobile', 'apps/web']) {
    check(); const file = path.join(workspace, relative, '.npmrc');
    try { fs.lstatSync(file); assert.fail('CI_TRUST_PROJECT_NPMRC_UNREVIEWED'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    let parent = path.dirname(file), state;
    for (let depth = 0; ; depth++) {
      check(); assert.ok(depth < 64, 'CI_TRUST_PARENT_BOUND');
      try { state = fs.lstatSync(parent, { bigint: true }); break; }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      assert.notEqual(parent, workspace, 'CI_TRUST_WORKSPACE'); parent = path.dirname(parent);
    }
    assert.ok(state.isDirectory() && !state.isSymbolicLink() && canonical(parent) === parent, 'CI_TRUST_PROJECT_NAMESPACE');
    rows.push({ file, parent, metadata: frame(state), namespace: parents(parent, check) });
  }
  return rows;
}

/** The observed native runner v2.338.0 creates this one direct-child UUID
 * command file. This private context grants no authority to an arbitrary
 * exported append call, npm config or other existing path. No ACL is modified. */
function nativeRunnerCommand(file, root, fd, initial, named, context, check) {
  if (process.platform !== 'win32' || context?.token !== CI_INVOCATION) return null;
  if (context.file !== file || context.root !== root || context.environment.GITHUB_ACTIONS !== 'true' || context.environment.CI !== 'true' || context.environment.RUNNER_TEMP !== root || context.environment.GITHUB_OUTPUT !== file) return null;
  const directory = path.join(root, '_runner_file_commands');
  if (path.dirname(file) !== directory || !/^set_output_[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(path.basename(file))) return null;
  check(); checkNamed(named, initial);
  const parent = fs.lstatSync(directory, { bigint: true }), namespace = parents(file, check);
  assert.ok(parent.isDirectory() && !parent.isSymbolicLink() && canonical(directory) === directory && canonical(file) === file, 'CI_TRUST_RUNNER_COMMAND_NAMESPACE');
  const reconcile = (expectedOpened = initial, expectedNamed = named) => {
    check(); const openedNow = fs.fstatSync(fd, { bigint: true }), namedNow = fs.lstatSync(file, { bigint: true });
    checkNamed(namedNow, openedNow);
    assert.ok(equal(frame(expectedOpened), frame(openedNow)) && equal(frame(expectedNamed), frame(namedNow)) && equal(frame(parent), frame(fs.lstatSync(directory, { bigint: true }))) && equal(namespace, parents(file, check)) && canonical(directory) === directory && canonical(file) === file, 'CI_TRUST_RUNNER_COMMAND_CHANGED');
  };
  reconcile(); return { token: RUNNER_COMMAND, reconcile };
}

/** The GitHub runner owns the command file. Append through one retained FD and
 * reconcile the old bytes, exact appended bytes, full metadata and namespace.
 * Values stay in RAM; neither the existing file nor the policy is printed. */
export function appendCITrustOutputs(file, root, environment, context = undefined) {
  const end = performance.now() + 5000;
  const check = () => assert.ok(performance.now() < end, 'CI_TRUST_APPEND_DEADLINE');
  check(); admittedFile(file, root);
  assert.deepEqual(Object.keys(environment).sort(), [...KEYS].sort(), 'CI_TRUST_EXACT_KEYS');
  const lines = KEYS.map(key => {
    const value = environment[key];
    assert.ok(typeof value === 'string' && value.length > 0 && value.length <= 24000 && !/[\r\n\0]/.test(value), 'CI_TRUST_SINGLE_LINE');
    return key + '=' + value + '\n';
  });
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDWR | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const initial = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    assert.ok(initial.isFile() && named.isFile() && !named.isSymbolicLink() && initial.nlink === 1n && initial.size >= 0n && initial.size <= BigInt(MAX), 'CI_TRUST_COMMAND_FILE');
    const runnerCommand = nativeRunnerCommand(file, root, fd, initial, named, context, check);
    const ownerProof = commandOwner(file, initial, 'GITHUB_OUTPUT', runnerCommand); check();
    checkNamed(named, initial); const namespace = parents(file, check);
    const before = Buffer.alloc(Number(initial.size) + 1); let count = 0;
    while (count < before.length) { check(); const n = fs.readSync(fd, before, count, before.length - count, count); if (!n) break; count += n; }
    assert.equal(count, Number(initial.size), 'CI_TRUST_COMMAND_EXTENT');
    assert.ok(equal(frame(initial), frame(fs.fstatSync(fd, { bigint: true }))) && equal(frame(named), frame(fs.lstatSync(file, { bigint: true }))), 'CI_TRUST_COMMAND_CHANGED');
    const prefix = before.subarray(0, count), suffix = Buffer.from((count && prefix[count - 1] !== 10 ? '\n' : '') + lines.join(''));
    assert.ok(prefix.length + suffix.length <= MAX, 'CI_TRUST_COMMAND_BYTE_BOUND');
    let written = 0;
    while (written < suffix.length) { check(); const n = fs.writeSync(fd, suffix, written, Math.min(65536, suffix.length - written), prefix.length + written); assert.ok(n > 0, 'CI_TRUST_WRITE_PROGRESS'); written += n; }
    fs.fsyncSync(fd);
    const final = fs.fstatSync(fd, { bigint: true }), finalNamed = fs.lstatSync(file, { bigint: true });
    for (const key of identity) assert.equal(initial[key], final[key], 'CI_TRUST_COMMAND_IDENTITY_CHANGED');
    checkNamed(finalNamed, final); assert.equal(final.size, BigInt(prefix.length + suffix.length), 'CI_TRUST_COMMAND_EXTENT');
    const expected = Buffer.concat([prefix, suffix]), actual = Buffer.alloc(expected.length + 1); count = 0;
    while (count < actual.length) { check(); const n = fs.readSync(fd, actual, count, actual.length - count, count); if (!n) break; count += n; }
    assert.ok(count === expected.length && actual.subarray(0, count).equals(expected), 'CI_TRUST_SAME_DESCRIPTOR_READBACK');
    assert.ok(equal(frame(final), frame(fs.fstatSync(fd, { bigint: true }))) && equal(frame(finalNamed), frame(fs.lstatSync(file, { bigint: true }))) && equal(namespace, parents(file, check)) && canonical(file) === file, 'CI_TRUST_FINAL_COMMAND_CHANGED');
    runnerCommand?.reconcile(final, finalNamed);
    check(); return { appendedKeys: KEYS.length, previousBytes: prefix.length, finalBytes: expected.length, ...(ownerProof?.authority ? { commandFileAuthority: ownerProof.authority } : {}) };
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}



// Exact reviewed Git blobs at9bc9c622; these are public data inputs only.
// Executed copies must independently pass the unchanged strict owner rule.
const REVIEWED_RUNTIME_SOURCES = Object.freeze([
  Object.freeze({ role: 'helper', name: 'host-node-trust.mjs', gitMode: '100644', gitBlobSha1: 'c4d2ae68f4c9b0233e6246a8fe3ac504bec43b99', sha256: '13576eb5d2a4aed86b38f6dbae240ba290d08e653107c9ffeed060fa2e048787', sizeBytes: 29498 }),
  Object.freeze({ role: 'bootstrap', name: 'host-node-trust-start.mjs', gitMode: '100644', gitBlobSha1: 'c7fba8c4c768e3f63a4ced2a496f06c226b5fad9', sha256: '5aa448fb66bcbaec5127df7e7876a8b967eee3a005d045659f8141149f82a54b', sizeBytes: 6043 }),
]);
const sha = data => createHash('sha256').update(data).digest('hex');
function sourceAclFrames(objects, check) {
  assert.equal(objects.length, 6, 'CI_TRUST_RUNTIME_SOURCE_ACL_DOMAIN'); check();
  if (typeof process.getuid === 'function') return objects.map(({ state }) => {
    const mode = state.mode & 0o7777n;
    assert.ok(state.uid === BigInt(process.getuid()) && (state.isDirectory() ? mode === 0o700n : (mode & 0o7133n) === 0n), 'CI_TRUST_RUNTIME_SOURCE_MODE');
    return { runtimeOwner: true, reviewedAdminSource: false, writeScopeSafe: true, tokenUserPresent: true, uid: String(state.uid) };
  });
  assert.ok(process.platform === 'win32' && path.isAbsolute(process.env.SystemRoot || ''), 'CI_TRUST_OWNER_UNAVAILABLE');
  const sourceCode = "$ErrorActionPreference='Stop';try{$paths=@($env:CASEOPS_SOURCE_0,$env:CASEOPS_SOURCE_1,$env:CASEOPS_SOURCE_2,$env:CASEOPS_SOURCE_3,$env:CASEOPS_SOURCE_4,$env:CASEOPS_SOURCE_5);$i=[Security.Principal.WindowsIdentity]::GetCurrent();$u=$i.User.Value;$t=$i.Owner.Value;$present=![string]::IsNullOrEmpty($u);$sections=[Security.AccessControl.AccessControlSections]'Access,Owner';$rows=@();for($n=0;$n -lt 6;$n++){if($n -eq 2 -or $n -eq 3){$a=[IO.Directory]::GetAccessControl($paths[$n],$sections)}else{$a=[IO.File]::GetAccessControl($paths[$n],$sections)};$o=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;$runtimeOwner=($o -eq $u -or ($o -eq $t -and $o -in @('S-1-5-18','S-1-5-32-544')));$reviewedAdminSource=($present -and $o -eq 'S-1-5-32-544' -and $t -eq $u);$safe=$true;foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($r.AccessControlType -eq 'Allow' -and ([int]$r.FileSystemRights -band 852310) -ne 0 -and $r.IdentityReference.Value -notin @($u,'S-1-5-18','S-1-5-32-544','S-1-3-0')){$safe=$false}};$hash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($a.GetSecurityDescriptorBinaryForm())).Replace('-','').ToLowerInvariant();$rows+=('{\"runtimeOwner\":'+$runtimeOwner.ToString().ToLowerInvariant()+',\"reviewedAdminSource\":'+$reviewedAdminSource.ToString().ToLowerInvariant()+',\"writeScopeSafe\":'+$safe.ToString().ToLowerInvariant()+',\"tokenUserPresent\":'+$present.ToString().ToLowerInvariant()+',\"aclSha256\":\"'+$hash+'\"}')};[Console]::Out.Write('['+[string]::Join(',',$rows)+']')}catch{[Console]::Error.WriteLine('CI_SOURCE_ACL_REFUSED');exit 1}";
  const environment = { SystemRoot: process.env.SystemRoot, WINDIR: process.env.SystemRoot };
  objects.forEach((value, index) => { environment['CASEOPS_SOURCE_' + index] = value.path; });
  const remaining = Math.floor(check.deadline - performance.now()); assert.ok(remaining >= 1, 'CI_TRUST_PREPARATION_DEADLINE');
  const proof = spawnSync(path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', sourceCode], {
    env: environment, encoding: 'utf8', timeout: Math.min(5000, remaining), maxBuffer: 4096, windowsHide: true,
  });
  assert.ok(!proof.error && proof.status === 0 && proof.stderr === '', 'CI_TRUST_RUNTIME_SOURCE_ACL_COMMAND');
  // This token is available only after the fixed code-only producer constructs
  // these exact two colocated literal pin records. It grants no runtime owner
  // or output-write authority and is never accepted from environment/input.
  for (let index = 0; index < 2; index++) assert.ok(objects[index].data === true && objects[index].pin === REVIEWED_RUNTIME_SOURCES[index] && objects[index].path === fileURLToPath(new URL('./' + REVIEWED_RUNTIME_SOURCES[index].name, import.meta.url)), 'CI_TRUST_RUNTIME_SOURCE_PUBLIC_INPUT_REQUIRED');
  const values = reviewCIHostSourceAclOutput(proof.stdout, REVIEWED_PUBLIC_INPUT_DATA);
  values.forEach((value, index) => {
    assert.ok(value.runtimeOwner === true || objects[index].data === true && value.reviewedAdminSource === true, 'CI_TRUST_RUNTIME_SOURCE_OWNER_' + SOURCE_ROLES[index]);
  });
  check(); return values;
}
const REVIEWED_PUBLIC_INPUT_DATA = Symbol('literal-reviewed-public-input-data');
const SOURCE_ROLES = Object.freeze(['HELPER_INPUT', 'BOOTSTRAP_INPUT', 'PARENT_DIRECTORY', 'RUNTIME_DIRECTORY', 'HELPER_COPY', 'BOOTSTRAP_COPY']);
const SOURCE_PROTOCOL_REASONS = Object.freeze(['JSON_TYPE', 'JSON_EMPTY', 'JSON_SIZE', 'JSON_INVALID', 'ARRAY_TYPE', 'ARRAY_COUNT', 'ROW_TYPE', 'FIELDS', 'OWNER_TYPE', 'ADMIN_TYPE', 'WRITE_TYPE', 'WRITE_UNSAFE', 'USER_TYPE', 'USER_MISSING', 'HASH_TYPE', 'HASH_FORMAT']);
function sourceProtocolFailure(role, reason) {
  assert.ok((role === 'OUTPUT' || SOURCE_ROLES.includes(role)) && SOURCE_PROTOCOL_REASONS.includes(reason));
  assert.fail('CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_' + role + '_' + reason);
}
/** Only fixed classes identify a refusal. Raw ACL response bytes and unknown
 * property names never enter diagnostics. The exported decoder stays strict by
 * default. Only the private producer token admits a nonexclusive writer flag
 * on the two literal public INPUT rows, pending both immutable byte proofs. */
export function reviewCIHostSourceAclOutput(output, admission = undefined) {
  if (typeof output !== 'string') sourceProtocolFailure('OUTPUT', 'JSON_TYPE');
  if (output.length > 4096 || Buffer.byteLength(output) > 4096) sourceProtocolFailure('OUTPUT', 'JSON_SIZE');
  if (output.trim().length === 0) sourceProtocolFailure('OUTPUT', 'JSON_EMPTY');
  let values;
  try { values = JSON.parse(output); } catch { sourceProtocolFailure('OUTPUT', 'JSON_INVALID'); }
  if (!Array.isArray(values)) sourceProtocolFailure('OUTPUT', 'ARRAY_TYPE');
  if (values.length !== 6) sourceProtocolFailure('OUTPUT', 'ARRAY_COUNT');
  values.forEach((value, index) => {
    const role = SOURCE_ROLES[index];
    if (!value || typeof value !== 'object' || Array.isArray(value)) sourceProtocolFailure(role, 'ROW_TYPE');
    if (!equal(Object.keys(value).sort(), ['aclSha256', 'reviewedAdminSource', 'runtimeOwner', 'tokenUserPresent', 'writeScopeSafe'])) sourceProtocolFailure(role, 'FIELDS');
    if (typeof value.runtimeOwner !== 'boolean') sourceProtocolFailure(role, 'OWNER_TYPE');
    if (typeof value.reviewedAdminSource !== 'boolean') sourceProtocolFailure(role, 'ADMIN_TYPE');
    if (typeof value.writeScopeSafe !== 'boolean') sourceProtocolFailure(role, 'WRITE_TYPE');
    if (value.writeScopeSafe !== true && !(admission === REVIEWED_PUBLIC_INPUT_DATA && index < 2)) sourceProtocolFailure(role, 'WRITE_UNSAFE');
    if (typeof value.tokenUserPresent !== 'boolean') sourceProtocolFailure(role, 'USER_TYPE');
    if (value.tokenUserPresent !== true) sourceProtocolFailure(role, 'USER_MISSING');
    if (typeof value.aclSha256 !== 'string') sourceProtocolFailure(role, 'HASH_TYPE');
    if (!/^[a-f0-9]{64}$/.test(value.aclSha256)) sourceProtocolFailure(role, 'HASH_FORMAT');
  });
  return values;
}
function directoryFrame(directory, check) {
  check(); assert.ok(path.isAbsolute(directory) && canonical(directory) === directory, 'CI_TRUST_RUNTIME_SOURCE_NAMESPACE');
  const state = fs.lstatSync(directory, { bigint: true }); assert.ok(state.isDirectory() && !state.isSymbolicLink(), 'CI_TRUST_RUNTIME_SOURCE_DIRECTORY');
  return { path: directory, state, namespace: parents(directory, check) };
}
function sourceNames(directory, check) {
  const state = fs.lstatSync(directory, { bigint: true }), namespace = parents(directory, check), names = []; let iterator;
  try {
    iterator = fs.opendirSync(directory, { bufferSize: 1 });
    while (true) { check(); const entry = iterator.readSync(); if (!entry) break; assert.ok(names.length < 2 && !names.includes(entry.name), 'CI_TRUST_RUNTIME_SOURCE_COMPLETE_NAMES'); names.push(entry.name); }
  } finally { iterator?.closeSync(); }
  assert.ok(equal(frame(state), frame(fs.lstatSync(directory, { bigint: true }))) && equal(namespace, parents(directory, check)), 'CI_TRUST_RUNTIME_SOURCE_DIRECTORY_CHANGED');
  assert.deepEqual(names.sort(), REVIEWED_RUNTIME_SOURCES.map(value => value.name).sort(), 'CI_TRUST_RUNTIME_SOURCE_COMPLETE_NAMES');
}
/** Fixed code-only producer: no environment-selected path, digest or owner waiver. */
export function stageCIHostNodeRuntimeSources(parent, incomingCheck) {
  const deadline = incomingCheck.deadline;
  assert.ok(typeof deadline === 'number' && Number.isFinite(deadline) && deadline > performance.now() && deadline - performance.now() <= 30000, 'CI_TRUST_RUNTIME_SOURCE_DEADLINE');
  const check = () => { assert.ok(performance.now() < deadline, 'CI_TRUST_PREPARATION_DEADLINE'); incomingCheck(); };
  Object.defineProperty(check, 'deadline', { value: deadline });
  const parentFrame = directoryFrame(parent, check), directory = path.join(parent, 'runtime-source');
  fs.mkdirSync(directory, { mode: 0o700 }); const runtimeFrame = directoryFrame(directory, check);
  const inputs = [], copies = []; let retainedHelper, bodyFailed = false, closeFailed = false;
  try {
    for (const pin of REVIEWED_RUNTIME_SOURCES) {
      const original = fileURLToPath(new URL('./' + pin.name, import.meta.url)); check();
      const input = { path: original, pin, fd: fs.openSync(original, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0)) }; inputs.push(input);
      input.opened = fs.fstatSync(input.fd, { bigint: true }); input.state = fs.lstatSync(original, { bigint: true });
      assert.ok(input.opened.isFile() && input.state.isFile() && !input.state.isSymbolicLink() && input.opened.nlink === 1n && input.opened.size === BigInt(pin.sizeBytes), 'CI_TRUST_RUNTIME_SOURCE_INPUT');
      checkNamed(input.state, input.opened); input.namespace = parents(original, check);
      const file = path.join(directory, pin.name), copy = { path: file, pin, fd: fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), 0o600) }; copies.push(copy);
      copy.opened = fs.fstatSync(copy.fd, { bigint: true }); copy.state = fs.lstatSync(file, { bigint: true });
      assert.ok(copy.opened.isFile() && copy.state.isFile() && !copy.state.isSymbolicLink() && copy.opened.nlink === 1n && copy.opened.size === 0n, 'CI_TRUST_RUNTIME_SOURCE_EXCLUSIVE');
      checkNamed(copy.state, copy.opened); copy.namespace = parents(file, check);
    }
    sourceNames(directory, check);
    const objects = [...inputs.map(value => ({ ...value, data: true })), parentFrame, runtimeFrame, ...copies];
    const unchangedDirectories = () => { for (const directory of [parentFrame, runtimeFrame]) { check(); const current = fs.lstatSync(directory.path, { bigint: true }); for (const key of ['dev', 'ino', 'uid', 'gid', 'mode']) assert.equal(directory.state[key], current[key], 'CI_TRUST_RUNTIME_SOURCE_DIRECTORY_IDENTITY'); assert.ok(equal(directory.namespace, parents(directory.path, check)), 'CI_TRUST_RUNTIME_SOURCE_DIRECTORY_CHANGED'); } };
    unchangedDirectories();
    const before = sourceAclFrames(objects, check);
    unchangedDirectories();
    for (const value of [...inputs, ...copies]) assert.ok(equal(frame(value.opened), frame(fs.fstatSync(value.fd, { bigint: true }))) && equal(frame(value.state), frame(fs.lstatSync(value.path, { bigint: true }))) && equal(value.namespace, parents(value.path, check)), 'CI_TRUST_RUNTIME_SOURCE_CHANGED_BEFORE_READ');
    // Verify both public source blobs before writing any source-copy payload.
    for (const input of inputs) {
      input.bytes = Buffer.alloc(input.pin.sizeBytes + 1); let count = 0;
      while (count < input.bytes.length) { check(); const n = fs.readSync(input.fd, input.bytes, count, input.bytes.length - count, null); if (!n) break; count += n; }
      assert.ok(count === input.pin.sizeBytes && sha(input.bytes.subarray(0, count)) === input.pin.sha256
        && createHash('sha1').update(Buffer.from('blob ' + count + '\0')).update(input.bytes.subarray(0, count)).digest('hex') === input.pin.gitBlobSha1, 'CI_TRUST_RUNTIME_SOURCE_REVIEWED_BYTES');
    }
    // Reconcile BOTH immutable inputs after their complete byte proofs and
    // before the first output payload write. Source ACL observations remain
    // provenance; only these retained reviewed bytes can become executable.
    for (const input of inputs) assert.ok(equal(frame(input.opened), frame(fs.fstatSync(input.fd, { bigint: true }))) && equal(frame(input.state), frame(fs.lstatSync(input.path, { bigint: true }))) && equal(input.namespace, parents(input.path, check)) && canonical(input.path) === input.path, 'CI_TRUST_RUNTIME_SOURCE_CHANGED_BEFORE_WRITE');
    for (let index = 0; index < 2; index++) {
      const input = inputs[index], copy = copies[index], data = input.bytes.subarray(0, input.pin.sizeBytes); let count = 0;
      while (count < data.length) { check(); const n = fs.writeSync(copy.fd, data, count, data.length - count, count); assert.ok(n > 0 && n <= data.length - count, 'CI_TRUST_RUNTIME_SOURCE_WRITE_PROGRESS'); count += n; }
      fs.fsyncSync(copy.fd); fs.fchmodSync(copy.fd, 0o400); copy.final = fs.fstatSync(copy.fd, { bigint: true }); copy.named = fs.lstatSync(copy.path, { bigint: true }); checkNamed(copy.named, copy.final);
      for (const key of ['dev', 'ino', 'uid', 'gid', 'nlink']) assert.equal(copy.opened[key], copy.final[key], 'CI_TRUST_RUNTIME_SOURCE_OUTPUT_IDENTITY');
      assert.ok(copy.final.size === BigInt(data.length) && (copy.final.mode & 0o222n) === 0n, 'CI_TRUST_RUNTIME_SOURCE_OUTPUT_EXTENT');
      copy.bytes = Buffer.alloc(data.length + 1); count = 0;
      while (count < copy.bytes.length) { check(); const n = fs.readSync(copy.fd, copy.bytes, count, copy.bytes.length - count, count); if (!n) break; count += n; }
      assert.ok(count === data.length && copy.bytes.subarray(0, count).equals(data) && equal(frame(copy.final), frame(fs.fstatSync(copy.fd, { bigint: true }))) && equal(frame(copy.named), frame(fs.lstatSync(copy.path, { bigint: true }))) && equal(copy.namespace, parents(copy.path, check)), 'CI_TRUST_RUNTIME_SOURCE_OUTPUT_CHANGED');
      copy.reference = { path: copy.path, sha256: input.pin.sha256, sizeBytes: count };
    }
    sourceNames(directory, check);
    const afterObjects = [...inputs.map(value => ({ ...value, state: fs.lstatSync(value.path, { bigint: true }), data: true })), directoryFrame(parent, check), directoryFrame(directory, check), ...copies.map(value => ({ ...value, state: value.named }))];
    const after = sourceAclFrames(afterObjects, check); assert.ok(equal(before, after), 'CI_TRUST_RUNTIME_SOURCE_ACL_CHANGED'); unchangedDirectories();
    for (const input of inputs) assert.ok(equal(frame(input.opened), frame(fs.fstatSync(input.fd, { bigint: true }))) && equal(frame(input.state), frame(fs.lstatSync(input.path, { bigint: true }))) && equal(input.namespace, parents(input.path, check)) && canonical(input.path) === input.path, 'CI_TRUST_RUNTIME_SOURCE_INPUT_CHANGED');
    for (const copy of copies) assert.ok(equal(frame(copy.final), frame(fs.fstatSync(copy.fd, { bigint: true }))) && equal(frame(copy.named), frame(fs.lstatSync(copy.path, { bigint: true }))) && equal(copy.namespace, parents(copy.path, check)) && canonical(copy.path) === copy.path, 'CI_TRUST_RUNTIME_SOURCE_OUTPUT_FINAL_CHANGED');
    sourceNames(directory, check);
    const refs = Object.fromEntries(copies.map(value => [value.pin.role, value.reference])); retainedHelper = copies[0].bytes.subarray(0, copies[0].pin.sizeBytes);
    return { sourceRefs: refs, retainedHelper, provenance: inputs.map((value, index) => ({ name: value.pin.name, gitMode: value.pin.gitMode, gitBlobSha1: value.pin.gitBlobSha1, originalSha256: value.pin.sha256, originalMetadata: frame(value.state), originalAcl: before[index], inputAuthority: 'literal-sha256-gitblob-extent-retained-bytes', originalWriteScope: before[index].writeScopeSafe ? 'reviewed-writers' : 'nonexclusive-public-input-data', copied: copies[index].reference, copiedMetadata: frame(copies[index].named), copiedAcl: after[index + 4] })) };
  } catch (error) { bodyFailed = true; throw error; }
  finally {
    for (const value of [...inputs, ...copies]) {
      if (value.bytes && value.bytes.buffer !== retainedHelper?.buffer) value.bytes.fill(0);
      try { fs.closeSync(value.fd); } catch { closeFailed = true; }
    }
    if (closeFailed) {
      retainedHelper?.fill(0);
      // A fixed independent diagnostic must not mutate/replace a frozen or
      // primitive body fault. A failed diagnostic write is also not a replay.
      try { process.stderr.write('CI_TRUST_RUNTIME_SOURCE_CLOSE\n'); } catch {}
      if (!bodyFailed) throw new Error('CI_TRUST_RUNTIME_SOURCE_CLOSE');
    }
  }
}

const FRESH_PARENT = Symbol('exclusive-invocation-parent');
function freshParentClaim(parent, check) {
  check(); const state = fs.lstatSync(parent, { bigint: true });
  assert.ok(state.isDirectory() && !state.isSymbolicLink() && canonical(parent) === parent && state.birthtimeNs > 0n, 'CI_TRUST_PRIVATE_PARENT_IDENTITY');
  const namespace = parents(parent, check); let directory;
  try { directory = fs.opendirSync(parent, { bufferSize: 1 }); check(); assert.equal(directory.readSync(), null, 'CI_TRUST_PRIVATE_PARENT_NOT_EMPTY'); }
  finally { directory?.closeSync(); }
  assert.ok(equal(frame(state), frame(fs.lstatSync(parent, { bigint: true }))) && equal(namespace, parents(parent, check)), 'CI_TRUST_PRIVATE_PARENT_CHANGED');
  return { token: FRESH_PARENT, path: parent, state, namespace };
}
function privateParentSetupFailure(proof) {
  let lines = typeof proof?.stderr === 'string' ? proof.stderr.replaceAll('\r', '').split('\n') : null;
  if (lines?.at(-1) === '') lines.pop();
  if (lines?.at(-1) === 'COPS_PARENT_REFUSED') lines.pop();
  const ordered = lines && lines.length <= 5 && lines.every((line, index) => line === 'COPS_PARENT' + index);
  const stage = ordered ? lines.length ? 'STAGE_' + (lines.length - 1) : 'NO_MARKER' : 'UNCLASSIFIED';
  const reason = proof?.error?.code === 'ETIMEDOUT' ? 'TIMEOUT' : proof?.error || proof?.status !== 0 ? 'REFUSED' : 'PROTOCOL';
  return 'CI_TRUST_PRIVATE_PARENT_SETUP_' + reason + '_' + stage;
}
function protectFreshWindowsParent(context) {
  const { createdParent: claim, parent, check } = context;
  assert.ok(claim?.token === FRESH_PARENT && claim.path === parent && path.dirname(parent) === context.root && /^caseops-node-trust-[a-f0-9-]{36}$/.test(path.basename(parent)), 'CI_TRUST_PRIVATE_PARENT_CREATION_REQUIRED');
  if (process.platform !== 'win32') {
    const before = fs.lstatSync(parent, { bigint: true });
    assert.ok(equal(frame(before), frame(claim.state)) && before.birthtimeNs === claim.state.birthtimeNs && canonical(parent) === parent && equal(claim.namespace, parents(parent, check)), 'CI_TRUST_PRIVATE_PARENT_CHANGED');
    assert.ok(typeof process.getuid === 'function' && before.uid === BigInt(process.getuid()) && (before.mode & 0o777n) === 0o700n, 'CI_TRUST_PRIVATE_PARENT_POSIX_MODE');
    return { kind: 'posix-private-new-parent', modified: false };
  }
  assert.ok(claim.absent === true && equal(claim.namespace, parents(parent, check)), 'CI_TRUST_PRIVATE_PARENT_CHANGED');
  assert.ok(typeof process.env.SystemRoot === 'string' && path.isAbsolute(process.env.SystemRoot), 'CI_TRUST_OWNER_UNAVAILABLE');
  // CreateDirectoryW applies the descriptor ONLY to a newly created final leaf.
  // No path-based ownership/DACL setter ever touches an existing object. The
  // subsequent reparse-aware handle is used only for identity/security reads.
  const parentSetupCode = String.raw`$ErrorActionPreference='Stop';[Console]::Error.WriteLine('COPS_PARENT0');
$handle=[IntPtr]::Zero;$sd=[IntPtr]::Zero;$sa=[IntPtr]::Zero;$info=[IntPtr]::Zero;$pin=$null;$descriptor=$null;$readback=$null;$bodyFailed=$false;$cleanupFailed=$false;$answer=$null;$native=$null;
try{
$p=$env:CASEOPS_PARENT_CREATED_PATH;
if($p.Length -gt 240 -or $p -notmatch '^[A-Za-z]:\\' -or $p.Contains('/') -or $p.Contains([char]0)){throw 'LOCAL_SHORT_PATH_REQUIRED'};
$u=[Security.Principal.WindowsIdentity]::GetCurrent().User;if($null -eq $u -or [string]::IsNullOrEmpty($u.Value)){throw 'CURRENT_USER_REQUIRED'};
$expected=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal);[void]$expected.Add($u.Value);[void]$expected.Add('S-1-5-18');[void]$expected.Add('S-1-5-32-544');
$inherit=[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit;
$rights=[Security.AccessControl.FileSystemRights]::FullControl;$propagation=[Security.AccessControl.PropagationFlags]::None;$allow=[Security.AccessControl.AccessControlType]::Allow;
$security=[Security.AccessControl.DirectorySecurity]::new();$security.SetAccessRuleProtection($true,$false);$security.SetOwner($u);
foreach($identity in $expected){$sid=[Security.Principal.SecurityIdentifier]::new($identity);$rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,$rights,$inherit,$propagation,$allow);$security.AddAccessRule($rule)};
$descriptor=$security.GetSecurityDescriptorBinaryForm();if($descriptor.Length -lt 20 -or $descriptor.Length -gt 65536){throw 'DESCRIPTOR_BOUND'};
$assembly=[AppDomain]::CurrentDomain.DefineDynamicAssembly([Reflection.AssemblyName]::new('CaseOpsExclusiveDirectory'),[Reflection.Emit.AssemblyBuilderAccess]::Run);
$type=$assembly.DefineDynamicModule('Native').DefineType('CaseOpsExclusiveDirectory.Native',[Reflection.TypeAttributes]::Public);
$ptr=[IntPtr];$refptr=$ptr.MakeByRefType();$specs=@(
@{name='CreateDirectoryW';dll='kernel32.dll';result=[bool];args=[Type[]]@([string],$ptr)},
@{name='CreateFileW';dll='kernel32.dll';result=$ptr;args=[Type[]]@([string],[uint32],[uint32],$ptr,[uint32],[uint32],$ptr)},
@{name='GetFileInformationByHandle';dll='kernel32.dll';result=[bool];args=[Type[]]@($ptr,$ptr)},
@{name='GetFinalPathNameByHandleW';dll='kernel32.dll';result=[uint32];args=[Type[]]@($ptr,[Text.StringBuilder],[uint32],[uint32])},
@{name='GetSecurityInfo';dll='advapi32.dll';result=[uint32];args=[Type[]]@($ptr,[int],[uint32],$refptr,$refptr,$refptr,$refptr,$refptr)},
@{name='GetSecurityDescriptorLength';dll='advapi32.dll';result=[uint32];args=[Type[]]@($ptr)},
@{name='LocalFree';dll='kernel32.dll';result=$ptr;args=[Type[]]@($ptr)},
@{name='CloseHandle';dll='kernel32.dll';result=[bool];args=[Type[]]@($ptr)});
foreach($spec in $specs){$method=$type.DefinePInvokeMethod($spec.name,$spec.dll,$spec.name,[Reflection.MethodAttributes]'Public,Static,PinvokeImpl',[Reflection.CallingConventions]::Standard,$spec.result,$spec.args,[Runtime.InteropServices.CallingConvention]::Winapi,[Runtime.InteropServices.CharSet]::Unicode);$method.SetImplementationFlags($method.GetMethodImplementationFlags() -bor [Reflection.MethodImplAttributes]::PreserveSig)};
$native=$type.CreateType();
$pin=[Runtime.InteropServices.GCHandle]::Alloc($descriptor,[Runtime.InteropServices.GCHandleType]::Pinned);
$saSize=if([IntPtr]::Size -eq 8){24}else{12};$pointerOffset=if([IntPtr]::Size -eq 8){8}else{4};$inheritOffset=if([IntPtr]::Size -eq 8){16}else{8};
$sa=[Runtime.InteropServices.Marshal]::AllocHGlobal($saSize);for($offset=0;$offset -lt $saSize;$offset++){[Runtime.InteropServices.Marshal]::WriteByte($sa,$offset,0)};
[Runtime.InteropServices.Marshal]::WriteInt32($sa,0,$saSize);[Runtime.InteropServices.Marshal]::WriteIntPtr($sa,$pointerOffset,$pin.AddrOfPinnedObject());[Runtime.InteropServices.Marshal]::WriteInt32($sa,$inheritOffset,0);
[Console]::Error.WriteLine('COPS_PARENT1');
if(!$native::CreateDirectoryW($p,$sa)){throw 'EXCLUSIVE_CREATION_REQUIRED'};
[Console]::Error.WriteLine('COPS_PARENT2');
$handle=$native::CreateFileW($p,131200,3,[IntPtr]::Zero,3,35651584,[IntPtr]::Zero);
if($handle -eq [IntPtr]::Zero -or $handle -eq [IntPtr]::new(-1)){throw 'DIRECTORY_HANDLE_REQUIRED'};
$info=[Runtime.InteropServices.Marshal]::AllocHGlobal(52);if(!$native::GetFileInformationByHandle($handle,$info)){throw 'HANDLE_INFORMATION_REQUIRED'};
$first=[byte[]]::new(52);[Runtime.InteropServices.Marshal]::Copy($info,$first,0,52);
$attributes=[BitConverter]::ToUInt32($first,0);if(($attributes -band 16) -eq 0 -or ($attributes -band 1024) -ne 0){throw 'REAL_DIRECTORY_REQUIRED'};
$finalName=[Text.StringBuilder]::new(1024);$nameLength=$native::GetFinalPathNameByHandleW($handle,$finalName,1024,0);
if($nameLength -eq 0 -or $nameLength -ge 1024 -or !$finalName.ToString().StartsWith('\\?\',[StringComparison]::Ordinal) -or $finalName.ToString().Substring(4) -cne $p){throw 'HANDLE_PATH_REQUIRED'};
$owner=[IntPtr]::Zero;$group=[IntPtr]::Zero;$dacl=[IntPtr]::Zero;$sacl=[IntPtr]::Zero;
if($native::GetSecurityInfo($handle,1,5,[ref]$owner,[ref]$group,[ref]$dacl,[ref]$sacl,[ref]$sd) -ne 0 -or $sd -eq [IntPtr]::Zero){throw 'HANDLE_SECURITY_REQUIRED'};
$length=$native::GetSecurityDescriptorLength($sd);if($length -lt 20 -or $length -gt 65536){throw 'HANDLE_DESCRIPTOR_BOUND'};
$readback=[byte[]]::new($length);[Runtime.InteropServices.Marshal]::Copy($sd,$readback,0,$length);
$actual=[Security.AccessControl.DirectorySecurity]::new();$actual.SetSecurityDescriptorBinaryForm($readback,[Security.AccessControl.AccessControlSections]'Access,Owner');
if(!$actual.AreAccessRulesProtected -or $actual.GetOwner([Security.Principal.SecurityIdentifier]).Value -cne $u.Value){throw 'PROTECTED_CURRENT_OWNER_REQUIRED'};
$seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal);
foreach($r in $actual.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($r.IsInherited -or $r.AccessControlType -ne $allow -or $r.FileSystemRights -ne $rights -or $r.InheritanceFlags -ne $inherit -or $r.PropagationFlags -ne $propagation -or !$expected.Contains($r.IdentityReference.Value) -or !$seen.Add($r.IdentityReference.Value)){throw 'EXACT_NEW_DACL_REQUIRED'}};
if(!$seen.SetEquals($expected)){throw 'COMPLETE_NEW_DACL_REQUIRED'};
if(!$native::GetFileInformationByHandle($handle,$info)){throw 'FINAL_HANDLE_INFORMATION_REQUIRED'};
$last=[byte[]]::new(52);[Runtime.InteropServices.Marshal]::Copy($info,$last,0,52);foreach($offset in @(0,4,8,28,40,44,48)){if([BitConverter]::ToUInt32($first,$offset) -ne [BitConverter]::ToUInt32($last,$offset)){throw 'HANDLE_CHANGED'}};
$fileIndex=([uint64][BitConverter]::ToUInt32($first,44) -shl 32) -bor [uint64][BitConverter]::ToUInt32($first,48);
$birth=([uint64][BitConverter]::ToUInt32($first,8) -shl 32) -bor [uint64][BitConverter]::ToUInt32($first,4);
if($fileIndex -eq 0 -or $birth -le 116444736000000000){throw 'HANDLE_IDENTITY_REQUIRED'};
$birthNs=($birth - [uint64]116444736000000000) * [uint64]100;$volume=[BitConverter]::ToUInt32($first,28);
$answer='{"created":true,"ownerCurrent":true,"protected":true,"writersExact":true,"ino":"'+$fileIndex.ToString([Globalization.CultureInfo]::InvariantCulture)+'","volume":"'+$volume.ToString([Globalization.CultureInfo]::InvariantCulture)+'","birthtimeNs":"'+$birthNs.ToString([Globalization.CultureInfo]::InvariantCulture)+'"}';
[Console]::Error.WriteLine('COPS_PARENT3');
}catch{$bodyFailed=$true}
finally{
try{if($handle -ne [IntPtr]::Zero -and $handle -ne [IntPtr]::new(-1)){if(!$native::CloseHandle($handle)){$cleanupFailed=$true}}}catch{$cleanupFailed=$true};
try{if($sd -ne [IntPtr]::Zero){if($native::LocalFree($sd) -ne [IntPtr]::Zero){$cleanupFailed=$true}}}catch{$cleanupFailed=$true};
try{if($info -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::FreeHGlobal($info)}}catch{$cleanupFailed=$true};
try{if($sa -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::FreeHGlobal($sa)}}catch{$cleanupFailed=$true};
try{if($null -ne $pin -and $pin.IsAllocated){$pin.Free()}}catch{$cleanupFailed=$true};
try{if($null -ne $descriptor){[Array]::Clear($descriptor,0,$descriptor.Length)};if($null -ne $readback){[Array]::Clear($readback,0,$readback.Length)}}catch{$cleanupFailed=$true};
};
if($bodyFailed -or $cleanupFailed){[Console]::Error.WriteLine('COPS_PARENT_REFUSED');exit 1};
[Console]::Error.WriteLine('COPS_PARENT4');[Console]::Out.Write($answer)`;
  const remaining = Math.floor(check.deadline - performance.now()); assert.ok(remaining > 0, 'CI_TRUST_PREPARATION_DEADLINE');
  const proof = spawnSync(path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', parentSetupCode], {
    env: { SystemRoot: process.env.SystemRoot, WINDIR: process.env.SystemRoot, CASEOPS_PARENT_CREATED_PATH: parent },
    encoding: 'utf8', timeout: Math.min(5000, remaining), maxBuffer: 4096, windowsHide: true,
  });
  if (proof.error || proof.status !== 0 || typeof proof.stdout !== 'string' || proof.stdout.length > 1024 || typeof proof.stderr !== 'string' || proof.stderr.replaceAll('\r', '') !== 'COPS_PARENT0\nCOPS_PARENT1\nCOPS_PARENT2\nCOPS_PARENT3\nCOPS_PARENT4\n') throw new Error(privateParentSetupFailure(proof));
  let result;
  try { result = JSON.parse(proof.stdout); } catch { throw new Error('CI_TRUST_PRIVATE_PARENT_SETUP_PROTOCOL_STAGE_4'); }
  assert.ok(result && !Array.isArray(result) && equal(Object.keys(result).sort(), ['birthtimeNs', 'created', 'ino', 'ownerCurrent', 'protected', 'volume', 'writersExact']) && ['created', 'ownerCurrent', 'protected', 'writersExact'].every(key => result[key] === true) && ['ino', 'volume', 'birthtimeNs'].every(key => typeof result[key] === 'string' && /^(?:0|[1-9][0-9]{0,19})$/.test(result[key])) && BigInt(result.ino) > 0n && BigInt(result.ino) <= 18446744073709551615n && BigInt(result.volume) <= 4294967295n && BigInt(result.birthtimeNs) > 0n && BigInt(result.birthtimeNs) <= 18446744073709551615n, 'CI_TRUST_PRIVATE_PARENT_SETUP_PROTOCOL_STAGE_4');
  check(); const after = fs.lstatSync(parent, { bigint: true });
  assert.ok(after.isDirectory() && !after.isSymbolicLink() && after.ino === BigInt(result.ino) && (after.dev === 0n || after.dev === BigInt(result.volume)) && after.birthtimeNs === BigInt(result.birthtimeNs) && canonical(parent) === parent && equal(claim.namespace, parents(parent, check)), 'CI_TRUST_PRIVATE_PARENT_CHANGED');
  freshParentClaim(parent, check);
  return { kind: 'windows-protected-new-parent', owner: 'current-user', writers: ['current-user', 'system', 'administrators'], protected: true, identityBound: true, childrenCreatedAfterSetup: true, creation: 'exclusive-native-security-descriptor' };
}
function ciContext(environment, createProtectedWindowsParent = false) {
  const end = performance.now() + 30000;
  const check = () => assert.ok(performance.now() < end, 'CI_TRUST_PREPARATION_DEADLINE');
  Object.defineProperty(check, 'deadline', { value: end });
  assert.equal(environment.GITHUB_ACTIONS, 'true', 'CI_TRUST_GITHUB_REQUIRED');
  assert.equal(environment.CI, 'true', 'CI_TRUST_CI_REQUIRED');
  const root = environment.RUNNER_TEMP, file = environment.GITHUB_OUTPUT;
  admittedFile(file, root);
  const workspace = environment.CASEOPS_CI_WORKSPACE;
  assert.ok(typeof workspace === 'string' && path.isAbsolute(workspace) && canonical(workspace) === workspace, 'CI_TRUST_WORKSPACE');
  // These are the three actual npm working directories in the reviewed jobs.
  // Never inspect an owner's npmrc. A project configuration needs fresh review.
  const projects = projectConfigsAbsent(workspace, check);
  let parent, createdParent;
  if (createProtectedWindowsParent) {
    parent = path.join(root, 'caseops-node-trust-' + randomUUID());
    if (process.platform === 'win32') {
      check(); const namespace = parents(parent, check);
      try { fs.lstatSync(parent); throw Object.assign(new Error('CI_TRUST_PRIVATE_PARENT_EXCLUSIVE'), { code: 'EEXIST' }); } catch (error) { if (error.code !== 'ENOENT') throw error; }
      createdParent = { token: FRESH_PARENT, path: parent, namespace, absent: true };
    } else { fs.mkdirSync(parent, { mode: 0o700 }); createdParent = freshParentClaim(parent, check); }
  } else parent = fs.mkdtempSync(path.join(root, 'caseops-node-trust-'));
  return { token: CI_INVOCATION, environment, check, root, file, workspace, projects, parent, createdParent };
}
function finishCI(context, prepared) {
  const { check, root, file, workspace, projects, parent } = context;
  const scoped = { ...prepared.environment,
    NPM_CONFIG_USERCONFIG: neutralConfig(path.join(parent, 'user.npmrc'), 'NPM_USER_CONFIG'),
    NPM_CONFIG_GLOBALCONFIG: neutralConfig(path.join(parent, 'global.npmrc'), 'NPM_GLOBAL_CONFIG'),
    NPM_CONFIG_STRICT_SSL: 'true', NPM_CONFIG_REGISTRY: 'https://registry.npmjs.org/',
  };
  assert.ok(equal(projects, projectConfigsAbsent(workspace, check)), 'CI_TRUST_PROJECT_CHANGED');
  const result = appendCITrustOutputs(file, root, scoped, context);
  assert.ok(equal(projects, projectConfigsAbsent(workspace, check)), 'CI_TRUST_PROJECT_CHANGED');
  check();
  return { nodeVersion: prepared.descriptor.nodeVersion, approvedRoots: prepared.descriptor.outputCount, ...result };
}
export function prepareCIHostNodeTrust(environment = process.env) {
  assert.ok(unixTrust, 'CI_TRUST_WINDOWS_ASYNC_ENTRY_REQUIRED');
  const context = ciContext(environment);
  const prepared = unixTrust.prepareHostNodeTrust({ directory: path.join(context.parent, 'policy'), environment });
  return finishCI(context, prepared);
}
export async function prepareCIHostNodeTrustWindows(environment = process.env) {
  const context = ciContext(environment, true), privateParentSetup = protectFreshWindowsParent(context);
  const staged = stageCIHostNodeRuntimeSources(context.parent, context.check);
  try {
    const helper = await import('data:text/javascript;base64,' + staged.retainedHelper.toString('base64'));
    context.check(); assert.ok(context.check.deadline - performance.now() >= 20000, 'CI_TRUST_RUNTIME_SOURCE_PREPARE_BUDGET');
    const prepared = helper.prepareHostNodeTrust({ directory: path.join(context.parent, 'policy'), environment, sourceRefs: staged.sourceRefs });
    return { ...finishCI(context, prepared), runtimeSourceCopies: staged.provenance, privateParentSetup };
  } finally { staged.retainedHelper.fill(0); }
}

const DIAGNOSTICS = new Set([
  'CI_TRUST_PRIVATE_PARENT_IDENTITY', 'CI_TRUST_PRIVATE_PARENT_NOT_EMPTY',
  'CI_TRUST_PRIVATE_PARENT_CHANGED', 'CI_TRUST_PRIVATE_PARENT_CREATION_REQUIRED',
  'CI_TRUST_PRIVATE_PARENT_POSIX_MODE', 'CI_TRUST_PRIVATE_PARENT_SETUP_REFUSED',
  'HOST_TRUST_WINDOWS_ACL_TIMEOUT', 'HOST_TRUST_WINDOWS_ACL_COMMAND_FAILED',
  'HOST_TRUST_WINDOWS_ACL_PROTOCOL', 'HOST_TRUST_CURRENT_OWNER_REQUIRED',
  'HOST_TRUST_OVERRIDE_REFUSED', 'HOST_TRUST_CLI_OVERRIDE_REFUSED',
  'HOST_TRUST_WINDOWS_ACL_TIMEOUT_NO_MARKER', 'HOST_TRUST_WINDOWS_ACL_TIMEOUT_SCRIPT_ENTERED',
  'HOST_TRUST_WINDOWS_ACL_TIMEOUT_ACL_READ', 'HOST_TRUST_WINDOWS_ACL_TIMEOUT_IDENTITY_READ',
  'HOST_TRUST_WINDOWS_ACL_TIMEOUT_RULES_READ', 'HOST_TRUST_WINDOWS_ACL_TIMEOUT_UNCLASSIFIED',
  'HOST_TRUST_WINDOWS_WRITE_SCOPE_REQUIRED', 'HOST_TRUST_DEADLINE',
  'HOST_TRUST_NAMED_FD_CHANGED', 'HOST_TRUST_DIRECTORY_PATH',
  'CI_TRUST_COMMAND_OWNER', 'CI_TRUST_COMMAND_OWNER_PROTOCOL', 'CI_TRUST_RUNNER_COMMAND_NAMESPACE', 'CI_TRUST_RUNNER_COMMAND_CHANGED', 'CI_TRUST_NAMESPACE', 'CI_TRUST_CONFIG_DEADLINE',
  'CI_TRUST_APPEND_DEADLINE', 'CI_TRUST_PREPARATION_DEADLINE',
  'CI_TRUST_RUNTIME_SOURCE_ACL_COMMAND', 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL', 'CI_TRUST_RUNTIME_SOURCE_OWNER',
  'CI_TRUST_RUNTIME_SOURCE_REVIEWED_BYTES', 'CI_TRUST_RUNTIME_SOURCE_PUBLIC_INPUT_REQUIRED', 'CI_TRUST_RUNTIME_SOURCE_CHANGED_BEFORE_WRITE', 'CI_TRUST_RUNTIME_SOURCE_CHANGED_BEFORE_READ',
  'CI_TRUST_RUNTIME_SOURCE_INPUT_CHANGED', 'CI_TRUST_RUNTIME_SOURCE_ACL_CHANGED',
  'CI_TRUST_RUNTIME_SOURCE_OUTPUT_CHANGED', 'CI_TRUST_RUNTIME_SOURCE_OUTPUT_IDENTITY',
  'CI_TRUST_RUNTIME_SOURCE_OUTPUT_FINAL_CHANGED', 'CI_TRUST_RUNTIME_SOURCE_OUTPUT_ACL_CHANGED',
  'CI_TRUST_WINDOWS_ASYNC_ENTRY_REQUIRED', 'CI_TRUST_RUNTIME_SOURCE_PREPARE_BUDGET',
  'CI_TRUST_RUNTIME_SOURCE_EXCLUSIVE', 'CI_TRUST_RUNTIME_SOURCE_COMPLETE_NAMES',
  'CI_TRUST_RUNTIME_SOURCE_INPUT', 'CI_TRUST_RUNTIME_SOURCE_WRITE_PROGRESS',
  'CI_TRUST_RUNTIME_SOURCE_OUTPUT_EXTENT', 'CI_TRUST_RUNTIME_SOURCE_DIRECTORY_CHANGED',
  'CI_TRUST_RUNTIME_SOURCE_CLOSE', 'CI_TRUST_RUNTIME_SOURCE_DIRECTORY_IDENTITY',
  'CI_TRUST_RUNTIME_SOURCE_OWNER_HELPER_INPUT', 'CI_TRUST_RUNTIME_SOURCE_OWNER_BOOTSTRAP_INPUT',
  'CI_TRUST_RUNTIME_SOURCE_OWNER_PARENT_DIRECTORY', 'CI_TRUST_RUNTIME_SOURCE_OWNER_RUNTIME_DIRECTORY',
  'CI_TRUST_RUNTIME_SOURCE_OWNER_HELPER_COPY', 'CI_TRUST_RUNTIME_SOURCE_OWNER_BOOTSTRAP_COPY',
  'CI_TRUST_RUNTIME_SOURCE_MODE', 'CI_TRUST_RUNTIME_SOURCE_NAMESPACE', 'CI_TRUST_RUNTIME_SOURCE_DEADLINE',
  'CI_TRUST_CANONICAL_PATH', 'CI_TRUST_PROJECT_NPMRC_UNREVIEWED',
]);
export function ciTrustFailureCode(error) {
  const first = typeof error?.message === 'string' ? error.message.split('\n', 1)[0] : '';
  return DIAGNOSTICS.has(first) || (first.length <= 160 && /^CI_TRUST_COMMAND_OWNER_(?:GITHUB_OUTPUT|NPM_USER_CONFIG|NPM_GLOBAL_CONFIG)_(?:(?:TIMEOUT|COMMAND_FAILED|PROTOCOL)_(?:NO_MARKER|SCRIPT_ENTERED|ACL_READ|IDENTITY_READ|RULES_READ|UNCLASSIFIED)|OWNER_(?:CURRENT_USER|SYSTEM|ADMINISTRATORS|TOKEN_OTHER|OTHER|MISSING)_TOKEN_(?:CURRENT_USER|SYSTEM|ADMINISTRATORS|OTHER|MISSING)_MATCH_(?:YES|NO)_WRITE_(?:SAFE|UNSAFE))$/.test(first)) || (first.length <= 160 && /^CI_TRUST_PRIVATE_PARENT_SETUP_(?:TIMEOUT|REFUSED|PROTOCOL)_(?:NO_MARKER|UNCLASSIFIED|STAGE_[0-4])$/.test(first)) || (first.length <= 160 && /^CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_(?:OUTPUT|HELPER_INPUT|BOOTSTRAP_INPUT|PARENT_DIRECTORY|RUNTIME_DIRECTORY|HELPER_COPY|BOOTSTRAP_COPY)_(?:JSON_TYPE|JSON_EMPTY|JSON_SIZE|JSON_INVALID|ARRAY_TYPE|ARRAY_COUNT|ROW_TYPE|FIELDS|OWNER_TYPE|ADMIN_TYPE|WRITE_TYPE|WRITE_UNSAFE|USER_TYPE|USER_MISSING|HASH_TYPE|HASH_FORMAT)$/.test(first)) || (first.length <= 160 && /^HOST_TRUST_CURRENT_OWNER_REQUIRED_(?:PUBLIC_INPUT|PUBLIC_SOURCE|SOURCE_HELPER|SOURCE_BOOTSTRAP|FIXTURE_INPUT|PARENT_DIRECTORY|POLICY_DIRECTORY|OUTPUT_DIRECTORY|EMPTY_DIRECTORY|DIRECTORY|ROOTS_OUTPUT|POLICY_OUTPUT|PUBLIC_OUTPUT|POLICY_INPUT|ROOTS_INPUT)_OWNER_(?:SYSTEM|ADMINISTRATORS|TOKEN_OTHER|OTHER|MISSING)_TOKEN_(?:CURRENT_USER|SYSTEM|ADMINISTRATORS|OTHER|MISSING)_WRITE_(?:SAFE|UNSAFE)$/.test(first)) ? first : 'CI_TRUST_PREPARATION_REFUSED';
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { console.log(JSON.stringify(process.platform === 'win32' ? await prepareCIHostNodeTrustWindows() : prepareCIHostNodeTrust())); }
  catch (error) { console.error('CaseOps CI Node trust preparation refused: ' + ciTrustFailureCode(error)); process.exitCode = 1; }
}
