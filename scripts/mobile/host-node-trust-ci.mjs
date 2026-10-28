import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { prepareHostNodeTrust } from './host-node-trust.mjs';

const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const identity = fields.slice(0, 6);
const frame = state => fields.map(key => String(state[key]));
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const canonical = file => (fs.realpathSync.native ?? fs.realpathSync)(file);
const MAX = 1048576;
const KEYS = ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256', 'NPM_CONFIG_USERCONFIG', 'NPM_CONFIG_GLOBALCONFIG', 'NPM_CONFIG_STRICT_SSL', 'NPM_CONFIG_REGISTRY'];
function neutralConfig(file) {
  const bytes = Buffer.from('; CaseOps isolated public npm configuration.\n'), end = performance.now() + 5000;
  const check = () => assert.ok(performance.now() < end, 'CI_TRUST_CONFIG_DEADLINE');
  const namespace = parents(file, check); let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
    const initial = fs.fstatSync(fd, { bigint: true }); commandOwner(file, initial);
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
function commandOwner(file, state) {
  if (typeof process.getuid === 'function') {
    assert.ok(state.uid === BigInt(process.getuid()) && (state.mode & 0o022n) === 0n, 'CI_TRUST_COMMAND_OWNER');
    return;
  }
  assert.ok(process.platform === 'win32' && path.isAbsolute(process.env.SystemRoot || ''), 'CI_TRUST_OWNER_UNAVAILABLE');
  const code = "$ErrorActionPreference='Stop';$a=Get-Acl -LiteralPath $env:CASEOPS_TRUST_ACL_PATH;$i=[Security.Principal.WindowsIdentity]::GetCurrent();$u=$i.User.Value;$t=$i.Owner.Value;$o=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;$ok=($o -eq $u -or ($o -eq $t -and $o -in @('S-1-5-18','S-1-5-32-544')));foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($r.AccessControlType -eq 'Allow' -and ([int]$r.FileSystemRights -band 852310) -ne 0 -and $r.IdentityReference.Value -notin @($u,'S-1-5-18','S-1-5-32-544','S-1-3-0')){$ok=$false}};if($ok){'SAFE'}else{exit 1}";
  const proof = spawnSync(path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoProfile', '-NonInteractive', '-Command', code], {
    env: { SystemRoot: process.env.SystemRoot, CASEOPS_TRUST_ACL_PATH: file }, encoding: 'utf8', timeout: 4000, maxBuffer: 4096, windowsHide: true,
  });
  assert.ok(!proof.error && proof.status === 0 && proof.stdout.trim() === 'SAFE', 'CI_TRUST_COMMAND_OWNER');
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

/** The GitHub runner owns the command file. Append through one retained FD and
 * reconcile the old bytes, exact appended bytes, full metadata and namespace.
 * Values stay in RAM; neither the existing file nor the policy is printed. */
export function appendCITrustOutputs(file, root, environment) {
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
    commandOwner(file, initial); check();
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
    check(); return { appendedKeys: KEYS.length, previousBytes: prefix.length, finalBytes: expected.length };
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}

export function prepareCIHostNodeTrust(environment = process.env) {
  const end = performance.now() + 30000;
  const check = () => assert.ok(performance.now() < end, 'CI_TRUST_PREPARATION_DEADLINE');
  assert.equal(environment.GITHUB_ACTIONS, 'true', 'CI_TRUST_GITHUB_REQUIRED');
  assert.equal(environment.CI, 'true', 'CI_TRUST_CI_REQUIRED');
  const root = environment.RUNNER_TEMP, file = environment.GITHUB_OUTPUT;
  admittedFile(file, root);
  const workspace = environment.CASEOPS_CI_WORKSPACE;
  assert.ok(typeof workspace === 'string' && path.isAbsolute(workspace) && canonical(workspace) === workspace, 'CI_TRUST_WORKSPACE');
  // These are the three actual npm working directories in the reviewed jobs.
  // Never inspect an owner's npmrc. A project configuration needs fresh review.
  const projects = projectConfigsAbsent(workspace, check);
  const parent = fs.mkdtempSync(path.join(root, 'caseops-node-trust-'));
  const prepared = prepareHostNodeTrust({ directory: path.join(parent, 'policy'), environment });
  const scoped = { ...prepared.environment,
    NPM_CONFIG_USERCONFIG: neutralConfig(path.join(parent, 'user.npmrc')),
    NPM_CONFIG_GLOBALCONFIG: neutralConfig(path.join(parent, 'global.npmrc')),
    NPM_CONFIG_STRICT_SSL: 'true', NPM_CONFIG_REGISTRY: 'https://registry.npmjs.org/',
  };
  assert.ok(equal(projects, projectConfigsAbsent(workspace, check)), 'CI_TRUST_PROJECT_CHANGED');
  const result = appendCITrustOutputs(file, root, scoped);
  assert.ok(equal(projects, projectConfigsAbsent(workspace, check)), 'CI_TRUST_PROJECT_CHANGED');
  check();
  return { nodeVersion: prepared.descriptor.nodeVersion, approvedRoots: prepared.descriptor.outputCount, ...result };
}

const DIAGNOSTICS = new Set([
  'HOST_TRUST_WINDOWS_ACL_TIMEOUT', 'HOST_TRUST_WINDOWS_ACL_COMMAND_FAILED',
  'HOST_TRUST_WINDOWS_ACL_PROTOCOL', 'HOST_TRUST_CURRENT_OWNER_REQUIRED',
  'HOST_TRUST_OVERRIDE_REFUSED', 'HOST_TRUST_CLI_OVERRIDE_REFUSED',
  'HOST_TRUST_WINDOWS_WRITE_SCOPE_REQUIRED', 'HOST_TRUST_DEADLINE',
  'HOST_TRUST_NAMED_FD_CHANGED', 'HOST_TRUST_DIRECTORY_PATH',
  'CI_TRUST_COMMAND_OWNER', 'CI_TRUST_NAMESPACE', 'CI_TRUST_CONFIG_DEADLINE',
  'CI_TRUST_APPEND_DEADLINE', 'CI_TRUST_PREPARATION_DEADLINE',
  'CI_TRUST_CANONICAL_PATH', 'CI_TRUST_PROJECT_NPMRC_UNREVIEWED',
]);
export function ciTrustFailureCode(error) {
  const first = typeof error?.message === 'string' ? error.message.split('\n', 1)[0] : '';
  return DIAGNOSTICS.has(first) ? first : 'CI_TRUST_PREPARATION_REFUSED';
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { console.log(JSON.stringify(prepareCIHostNodeTrust())); }
  catch (error) { console.error('CaseOps CI Node trust preparation refused: ' + ciTrustFailureCode(error)); process.exitCode = 1; }
}
