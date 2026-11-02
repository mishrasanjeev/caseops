import fs from 'node:fs';
import path from 'node:path';
import tls from 'node:tls';
import { X509Certificate, createHash, constants as cryptoConstants } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const HOST_NODE_TRUST_ENV = Object.freeze({ file: 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', sha256: 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256' });
export const DENIED_HOST_CA = '86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b';
export const HOST_NODE_ROOTS = Object.freeze({
  '22.23.4': Object.freeze({ inputCount: 116, inputSetSha256: 'f5c557f94fddcecbd61b66da4634ca2537f1b153cccf581170b4b25e29b084cb', outputCount: 116, outputSetSha256: 'f5c557f94fddcecbd61b66da4634ca2537f1b153cccf581170b4b25e29b084cb' }),
  '24.15.0': Object.freeze({ inputCount: 145, inputSetSha256: '198226aedca48a2d2d256da63ffb5836367954a983de81a6a3482b0a3e34ec50', outputCount: 144, outputSetSha256: '22fcf2da4698a68fd7afcdaa3ec278b38628829ed5ff408b5b99b763102951b2' }),
  '22.14.0': Object.freeze({ inputCount: 149, inputSetSha256: '8679e032ebe303c8fc30036873fabda30ded10de2dc72aea982a4cb2808f1456', outputCount: 148, outputSetSha256: '910a81f587619fcf2ebc76d0093a29de8ec4cfef62523ec7ec8f394557e8c0d7' }),
});
const FIELDS = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const DIGEST = /^[a-f0-9]{64}$/;
const fail = code => { throw new Error(code); };
const requireThat = (condition, code) => { if (!condition) fail(code); };
const publicSha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const frame = value => FIELDS.map(key => String(value[key]));
const equal = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const canonical = file => (fs.realpathSync.native ?? fs.realpathSync)(file);
const exactKeys = (value, keys) => requireThat(value && typeof value === 'object' && !Array.isArray(value) && equal(Object.keys(value).sort(), [...keys].sort()), 'HOST_TRUST_SCHEMA');
const setDigest = values => publicSha256(Buffer.from([...values].sort().join('\n') + '\n'));

/** A controlled build fixture is only a unit input; production always uses the actual config. */
export function reviewHostNodeBuildConfiguration(variables = process.config.variables) {
  requireThat(variables && typeof variables === 'object' && !Array.isArray(variables), 'HOST_TRUST_COMPILED_CA_PATH_UNREVIEWED');
  const compiled = variables.openssl_system_ca_path;
  requireThat(compiled === undefined || compiled === '', 'HOST_TRUST_COMPILED_CA_PATH_UNREVIEWED');
  return { compiledSystemCaPathEmpty: true };
}

function certificates(pem) {
  requireThat(typeof pem === 'string' && Buffer.byteLength(pem) <= 1048576, 'HOST_TRUST_CERTIFICATE_BOUND');
  const matches = [...pem.matchAll(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g)];
  requireThat(matches.length > 0 && matches.length <= 256 && pem.replace(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g, '').trim() === '', 'HOST_TRUST_CERTIFICATES_ONLY');
  try { return matches.map(([value]) => { const cert = new X509Certificate(value); requireThat(cert.ca, 'HOST_TRUST_CA_REQUIRED'); return { pem: value + '\n', cert, fingerprint: publicSha256(cert.raw) }; }); }
  catch { fail('HOST_TRUST_CERTIFICATE_INVALID'); }
}

/** Only the exact version-bound reviewed sets, or their already-clean equivalents. */
export function reviewHostNodeRoots(pems = tls.rootCertificates, version = process.versions.node) {
  const spec = HOST_NODE_ROOTS[version]; requireThat(spec && Array.isArray(pems) && pems.length <= 256, 'HOST_TRUST_NODE_OR_ROOTS_UNREVIEWED');
  const values = pems.flatMap(pem => { const rows = certificates(pem); requireThat(rows.length === 1, 'HOST_TRUST_ONE_CERTIFICATE_PER_ROOT'); return rows; });
  const ids = values.map(value => value.fingerprint), inputSetSha256 = setDigest(ids);
  requireThat(new Set(ids).size === ids.length, 'HOST_TRUST_DUPLICATE_ROOT');
  const original = ids.length === spec.inputCount && inputSetSha256 === spec.inputSetSha256;
  const alreadyClean = ids.length === spec.outputCount && inputSetSha256 === spec.outputSetSha256;
  requireThat(original || alreadyClean, 'HOST_TRUST_ROOT_SET_UNREVIEWED');
  const output = values.filter(value => value.fingerprint !== DENIED_HOST_CA);
  requireThat(values.length - output.length === (alreadyClean ? 0 : 1) && output.length === spec.outputCount && setDigest(output.map(value => value.fingerprint)) === spec.outputSetSha256, 'HOST_TRUST_OUTPUT_SET_MISMATCH');
  return { version, inputCount: values.length, inputSetSha256, outputCount: output.length, outputSetSha256: spec.outputSetSha256, removedCount: values.length - output.length, pem: output.map(value => value.pem).join(''), fingerprints: output.map(value => value.fingerprint).sort() };
}

function operation() {
  const end = performance.now() + 20000;
  return () => requireThat(performance.now() < end, 'HOST_TRUST_DEADLINE');
}
function namespace(file, check) {
  check(); const resolved = canonical(file), rows = [];
  for (let p = path.dirname(resolved); ; p = path.dirname(p)) {
    check(); const value = fs.lstatSync(p, { bigint: true }); requireThat(value.isDirectory() && !value.isSymbolicLink(), 'HOST_TRUST_NAMESPACE');
    rows.push([p, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(value[key]))]);
    if (path.dirname(p) === p) return { resolved, rows };
  }
}
function namedDescriptor(named, opened) {
  for (const key of FIELDS) if (!(process.platform === 'win32' && key === 'dev' && named.dev === 0n)) requireThat(named[key] === opened[key], 'HOST_TRUST_NAMED_FD_CHANGED');
}
const WINDOWS_OWNER_ROLES = new Set(["PUBLIC_INPUT", "PUBLIC_SOURCE", "SOURCE_HELPER", "SOURCE_BOOTSTRAP", "FIXTURE_INPUT", "PARENT_DIRECTORY", "POLICY_DIRECTORY", "OUTPUT_DIRECTORY", "EMPTY_DIRECTORY", "DIRECTORY", "ROOTS_OUTPUT", "POLICY_OUTPUT", "PUBLIC_OUTPUT", "POLICY_INPUT", "ROOTS_INPUT"]);
const WINDOWS_OWNER_CLASSES = new Set(['CURRENT_USER', 'SYSTEM', 'ADMINISTRATORS', 'TOKEN_OTHER', 'OTHER', 'MISSING']);
const WINDOWS_TOKEN_CLASSES = new Set(['CURRENT_USER', 'SYSTEM', 'ADMINISTRATORS', 'OTHER', 'MISSING']);
function ownerRefusalCode(parsed, role) {
  exactKeys(parsed, ['ownerMatches', 'writeScopeSafe', 'ownerClass', 'tokenOwnerClass']);
  requireThat(parsed.ownerMatches === false && typeof parsed.writeScopeSafe === 'boolean' && WINDOWS_OWNER_ROLES.has(role) && WINDOWS_OWNER_CLASSES.has(parsed.ownerClass) && parsed.ownerClass !== 'CURRENT_USER' && WINDOWS_TOKEN_CLASSES.has(parsed.tokenOwnerClass), 'HOST_TRUST_WINDOWS_ACL_PROTOCOL');
  return 'HOST_TRUST_CURRENT_OWNER_REQUIRED_' + role + '_OWNER_' + parsed.ownerClass + '_TOKEN_' + parsed.tokenOwnerClass + '_WRITE_' + (parsed.writeScopeSafe ? 'SAFE' : 'UNSAFE');
}
function ownership(file, value, directory = false, publicCertificate = false, role = 'PUBLIC_INPUT') {
  requireThat(WINDOWS_OWNER_ROLES.has(role), 'HOST_TRUST_WINDOWS_ACL_PROTOCOL');
  if (typeof process.getuid === 'function') {
    requireThat(value.uid === BigInt(process.getuid()), 'HOST_TRUST_CURRENT_OWNER_REQUIRED');
    const mode = value.mode & 0o7777n;
    requireThat(directory ? mode === 0o700n : publicCertificate ? (mode & 0o400n) !== 0n && (mode & 0o7133n) === 0n : mode === 0o600n, 'HOST_TRUST_PRIVATE_MODE_REQUIRED');
    return;
  }
  requireThat(process.platform === 'win32' && path.isAbsolute(process.env.SystemRoot || ''), 'HOST_TRUST_OWNER_UNAVAILABLE');
  // Read-only ACL proof. The fixed command never returns SID/account values.
  const code = "$ErrorActionPreference='Stop';[Console]::Error.WriteLine('COPS_ACL0');try{$s=[Security.AccessControl.AccessControlSections]'Access,Owner';if($env:CASEOPS_TRUST_ACL_KIND -eq 'directory'){$a=[IO.Directory]::GetAccessControl($env:CASEOPS_TRUST_ACL_PATH,$s)}elseif($env:CASEOPS_TRUST_ACL_KIND -eq 'file'){$a=[IO.File]::GetAccessControl($env:CASEOPS_TRUST_ACL_PATH,$s)}else{throw 'ACL_KIND'};[Console]::Error.WriteLine('COPS_ACL1');$i=[Security.Principal.WindowsIdentity]::GetCurrent();$u=$i.User.Value;$t=$i.Owner.Value;$o=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;[Console]::Error.WriteLine('COPS_ACL2');$ok=($o -eq $u -or ($o -eq $t -and $o -in @('S-1-5-18','S-1-5-32-544')));$safe=$true;foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($r.AccessControlType -eq 'Allow' -and ([int]$r.FileSystemRights -band 852310) -ne 0 -and $r.IdentityReference.Value -notin @($u,'S-1-5-18','S-1-5-32-544','S-1-3-0')){$safe=$false}};[Console]::Error.WriteLine('COPS_ACL3');if($ok){[Console]::Out.Write(('{\"ownerMatches\":'+$ok.ToString().ToLowerInvariant()+',\"writeScopeSafe\":'+$safe.ToString().ToLowerInvariant()+'}'))}else{$oc=if([string]::IsNullOrEmpty($o)){'MISSING'}elseif($o -eq $u){'CURRENT_USER'}elseif($o -eq 'S-1-5-18'){'SYSTEM'}elseif($o -eq 'S-1-5-32-544'){'ADMINISTRATORS'}elseif($o -eq $t){'TOKEN_OTHER'}else{'OTHER'};$tc=if([string]::IsNullOrEmpty($t)){'MISSING'}elseif($t -eq $u){'CURRENT_USER'}elseif($t -eq 'S-1-5-18'){'SYSTEM'}elseif($t -eq 'S-1-5-32-544'){'ADMINISTRATORS'}else{'OTHER'};[Console]::Out.Write(('{\"ownerMatches\":false,\"writeScopeSafe\":'+$safe.ToString().ToLowerInvariant()+',\"ownerClass\":\"'+$oc+'\",\"tokenOwnerClass\":\"'+$tc+'\"}'))}}catch{[Console]::Error.WriteLine('COPS_ACL_FAIL');exit 1}";
  const executable = path.join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const result = spawnSync(executable, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', code], { encoding: 'utf8', timeout: 5000, maxBuffer: 4096, windowsHide: true, env: { SystemRoot: process.env.SystemRoot, WINDIR: process.env.SystemRoot, CASEOPS_TRUST_ACL_PATH: file, CASEOPS_TRUST_ACL_KIND: directory ? 'directory' : 'file' } });
  const phase = reviewHostNodeWindowsAclPhase(result.stderr);
  requireThat(result.error?.code !== 'ETIMEDOUT', 'HOST_TRUST_WINDOWS_ACL_TIMEOUT_' + phase);
  requireThat(!result.error && result.status === 0, 'HOST_TRUST_WINDOWS_ACL_COMMAND_FAILED');
  requireThat(phase === 'RULES_READ', 'HOST_TRUST_WINDOWS_ACL_PROTOCOL');
  let parsed; try { parsed = JSON.parse(result.stdout); } catch { fail('HOST_TRUST_WINDOWS_ACL_PROTOCOL'); }
  if (parsed?.ownerMatches === false && (Object.hasOwn(parsed, 'ownerClass') || Object.hasOwn(parsed, 'tokenOwnerClass'))) fail(ownerRefusalCode(parsed, role));
  reviewHostNodeWindowsAclProof(parsed);
}
/** Fixed progress only; never return a path, SID or unreviewed stderr text. */
export function reviewHostNodeWindowsAclPhase(stderr) {
  if (stderr === undefined || stderr === '') return 'NO_MARKER';
  if (typeof stderr !== 'string' || Buffer.byteLength(stderr) > 4096) return 'UNCLASSIFIED';
  const rows = stderr.trim().split(/\r?\n/);
  if (rows.length > 4 || rows.some((row, index) => row !== 'COPS_ACL' + index)) return 'UNCLASSIFIED';
  return ['NO_MARKER', 'SCRIPT_ENTERED', 'ACL_READ', 'IDENTITY_READ', 'RULES_READ'][rows.length];
}
/** Windows applies the current token's default owner to newly created objects.
 * The alternate owner must also be SYSTEM or Builtin Administrators, already
 * trusted for writes. An arbitrary default-owner group is never admitted. */
export function reviewHostNodeWindowsAclProof(parsed) {
  exactKeys(parsed, ['ownerMatches', 'writeScopeSafe']);
  requireThat(parsed.ownerMatches === true, 'HOST_TRUST_CURRENT_OWNER_REQUIRED');
  requireThat(parsed.writeScopeSafe === true, 'HOST_TRUST_WINDOWS_WRITE_SCOPE_REQUIRED');
  return { ownerMatches: true, writeScopeSafe: true };
}

function readHeld(file, limit, check, publicCertificate = false, role = 'PUBLIC_INPUT') {
  requireThat(typeof file === 'string' && path.isAbsolute(file) && path.resolve(file) === file, 'HOST_TRUST_ABSOLUTE_PATH');
  let fd;
  try {
    check(); fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const opened = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    requireThat(opened.isFile() && named.isFile() && !named.isSymbolicLink() && opened.nlink === 1n && opened.size > 0n && opened.size <= BigInt(limit), 'HOST_TRUST_FILE_BOUND');
    namedDescriptor(named, opened); ownership(file, named, false, publicCertificate, role); const ns = namespace(file, check), storage = Buffer.alloc(Number(opened.size) + 1); let count = 0;
    while (count < storage.length) { check(); const n = fs.readSync(fd, storage, count, storage.length - count, null); if (!n) break; count += n; }
    requireThat(BigInt(count) === opened.size && equal(frame(fs.fstatSync(fd, { bigint: true })), frame(opened)) && equal(frame(fs.lstatSync(file, { bigint: true })), frame(named)) && equal(namespace(file, check), ns), 'HOST_TRUST_FILE_CHANGED');
    return { bytes: storage.subarray(0, count), path: ns.resolved };
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
function privateDirectory(file, check, empty = false, role = 'DIRECTORY') {
  check(); requireThat(path.isAbsolute(file) && path.resolve(file) === file && canonical(file) === file, 'HOST_TRUST_DIRECTORY_PATH');
  const before = fs.lstatSync(file, { bigint: true }); requireThat(before.isDirectory() && !before.isSymbolicLink(), 'HOST_TRUST_DIRECTORY_REQUIRED'); ownership(file, before, true, false, role);
  const ns = namespace(file, check); let iterator;
  try { if (empty) { iterator = fs.opendirSync(file, { bufferSize: 1 }); check(); requireThat(iterator.readSync() === null, 'HOST_TRUST_EMPTY_DIRECTORY_REQUIRED'); } }
  finally { iterator?.closeSync(); }
  requireThat(equal(frame(fs.lstatSync(file, { bigint: true })), frame(before)) && equal(namespace(file, check), ns), 'HOST_TRUST_DIRECTORY_CHANGED');
}
function writeExclusive(file, bytes, check) {
  privateDirectory(path.dirname(file), check, false, 'OUTPUT_DIRECTORY'); let fd;
  try {
    check(); fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0), 0o600);
    const before = fs.fstatSync(fd, { bigint: true }); requireThat(before.isFile() && before.nlink === 1n && before.size === 0n, 'HOST_TRUST_EXCLUSIVE_WRITE'); ownership(file, before, false, false, path.basename(file) === 'roots.pem' ? 'ROOTS_OUTPUT' : path.basename(file) === 'policy.json' ? 'POLICY_OUTPUT' : 'PUBLIC_OUTPUT');
    const ns = namespace(file, check); let count = 0;
    while (count < bytes.length) { check(); const n = fs.writeSync(fd, bytes, count, Math.min(65536, bytes.length - count)); requireThat(n > 0 && n <= bytes.length - count, 'HOST_TRUST_WRITE_PROGRESS'); count += n; }
    fs.fsyncSync(fd); const finished = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true }); namedDescriptor(named, finished);
    requireThat(finished.size === BigInt(bytes.length) && ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink'].every(key => before[key] === finished[key]), 'HOST_TRUST_WRITE_CHANGED');
    const readback = Buffer.alloc(bytes.length + 1); let n = 0;
    while (n < readback.length) { check(); const part = fs.readSync(fd, readback, n, readback.length - n, n); if (!part) break; n += part; }
    requireThat(n === bytes.length && readback.subarray(0, n).equals(bytes) && equal(frame(fs.fstatSync(fd, { bigint: true })), frame(finished)) && equal(frame(fs.lstatSync(file, { bigint: true })), frame(named)) && equal(namespace(file, check), ns), 'HOST_TRUST_WRITE_CHANGED');
    return { path: canonical(file), sha256: publicSha256(bytes), sizeBytes: bytes.length };
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
function envValue(environment, name) {
  const keys = Object.keys(environment).filter(key => key.toUpperCase() === name);
  requireThat(keys.length <= 1 && keys.every(key => key === name), 'HOST_TRUST_ENVIRONMENT_CASE'); return environment[name];
}
function rejectOverrides(environment, bootstrap, role, fixture, argv, approvedImport = null) {
  requireThat(['base', 'native-qa'].includes(role), 'HOST_TRUST_ROLE');
  for (const [key, value] of Object.entries(environment)) {
    requireThat(!/^npm_config_(?:ca|cafile|node_options)$/i.test(key), 'HOST_TRUST_NPM_OVERRIDE_REFUSED');
    if (/^npm_config_strict_ssl$/i.test(key)) requireThat(value === 'true', 'HOST_TRUST_NPM_OVERRIDE_REFUSED');
  }
  for (const key of ['NODE_USE_SYSTEM_CA', 'NODE_USE_ENV_PROXY', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'OPENSSL_CONF', 'OPENSSL_CONF_INCLUDE', 'NODE_TLS_REJECT_UNAUTHORIZED']) requireThat(envValue(environment, key) === undefined, 'HOST_TRUST_OVERRIDE_REFUSED');
  const forbidden = ['--use-bundled-ca', '--use-system-ca', '--use-openssl-ca', '--no-use-bundled-ca', '--no-use-system-ca', '--no-use-openssl-ca', '--security-revert', '--use-env-proxy', '--no-use-env-proxy'];
  const compiledCipherOption = '--tls-cipher-list=' + cryptoConstants.defaultCoreCipherList;
  requireThat(!argv.some(arg => arg !== compiledCipherOption && arg !== approvedImport && arg !== '--use-openssl-ca' && (arg.startsWith('-r') || /^--(?:tls-|openssl-|require|import|experimental-loader|loader)/.test(arg) || forbidden.some(flag => arg === flag || arg.startsWith(flag + '=')))), 'HOST_TRUST_CLI_OVERRIDE_REFUSED');
  const extra = envValue(environment, 'NODE_EXTRA_CA_CERTS'); requireThat(extra === undefined || role === 'native-qa' && fixture && extra === fixture.path, 'HOST_TRUST_EXTRA_CA_REFUSED');
  if (role === 'native-qa') for (const key of ['K_SERVICE', 'K_REVISION', 'CLOUD_RUN_JOB', 'FUNCTION_TARGET', 'GAE_ENV']) requireThat(environment[key] === undefined, 'HOST_TRUST_QA_CLOUD_REFUSED');
  if (bootstrap) for (const key of ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR']) requireThat(envValue(environment, key) === undefined, 'HOST_TRUST_BOOTSTRAP_ENVIRONMENT');
  else requireThat(typeof envValue(environment, 'NODE_OPTIONS') === 'string' && envValue(environment, 'NODE_OPTIONS').startsWith('--use-openssl-ca --import=data:text/javascript;base64,'), 'HOST_TRUST_NODE_OPTIONS_REQUIRED');
}
function fixtureCertificate(reference, check) {
  exactKeys(reference, ['path', 'sha256', 'certificateSha256']); requireThat(DIGEST.test(reference.sha256) && DIGEST.test(reference.certificateSha256), 'HOST_TRUST_FIXTURE_REFERENCE');
  const input = readHeld(reference.path, 65536, check, true, 'FIXTURE_INPUT');
  try {
    const rows = certificates(new TextDecoder('utf-8', { fatal: true }).decode(input.bytes)); requireThat(rows.length === 1 && rows[0].fingerprint === reference.certificateSha256 && rows[0].fingerprint !== DENIED_HOST_CA && rows[0].cert.subject === rows[0].cert.issuer && rows[0].cert.verify(rows[0].cert.publicKey), 'HOST_TRUST_ISOLATED_FIXTURE_REQUIRED');
    requireThat(publicSha256(input.bytes) === reference.sha256 && input.path === reference.path, 'HOST_TRUST_FIXTURE_CHANGED'); return rows[0];
  } finally { input.bytes.fill(0); }
}
function publicSource(file, limit, check) {
  const retained = readHeld(file, limit, check, true, path.basename(file) === 'host-node-trust.mjs' ? 'SOURCE_HELPER' : path.basename(file) === 'host-node-trust-start.mjs' ? 'SOURCE_BOOTSTRAP' : 'PUBLIC_SOURCE');
  return { retained, reference: { path: retained.path, sha256: publicSha256(retained.bytes), sizeBytes: retained.bytes.length } };
}
function sourceRecipe(runtimeSource, check) {
  exactKeys(runtimeSource, ['helper', 'bootstrap']);
  for (const name of ['helper', 'bootstrap']) {
    const ref = runtimeSource[name]; exactKeys(ref, ['path', 'sha256', 'sizeBytes']);
    requireThat(DIGEST.test(ref.sha256) && Number.isSafeInteger(ref.sizeBytes), 'HOST_TRUST_SOURCE_REFERENCE');
  }
  requireThat(path.basename(runtimeSource.helper.path) === 'host-node-trust.mjs' && runtimeSource.bootstrap.path === path.join(path.dirname(runtimeSource.helper.path), 'host-node-trust-start.mjs'), 'HOST_TRUST_SOURCE_PATHS');
  let helper, bootstrap;
  try {
    helper = publicSource(runtimeSource.helper.path, 65536, check); bootstrap = publicSource(runtimeSource.bootstrap.path, 16384, check);
    requireThat(equal(helper.reference, runtimeSource.helper) && equal(bootstrap.reference, runtimeSource.bootstrap), 'HOST_TRUST_SOURCE_CHANGED');
    const result = '--use-openssl-ca --import=data:text/javascript;base64,' + bootstrap.retained.bytes.toString('base64');
    requireThat(result.length <= 24000, 'HOST_TRUST_BOOTSTRAP_URI_BOUND'); return result;
  } finally { helper?.retained.bytes.fill(0); bootstrap?.retained.bytes.fill(0); }
}
export function prepareHostNodeTrust({ directory, role = 'base', fixtureCA = null, environment = process.env, sourceRefs = null } = {}) {
  const check = operation(); rejectOverrides(environment, true, role, fixtureCA, []); reviewHostNodeBuildConfiguration(); const roots = reviewHostNodeRoots();
  requireThat(role === 'native-qa' ? fixtureCA !== null : fixtureCA === null, 'HOST_TRUST_FIXTURE_ROLE');
  if (fixtureCA) { const fixture = fixtureCertificate(fixtureCA, check); requireThat(!roots.fingerprints.includes(fixture.fingerprint), 'HOST_TRUST_DUPLICATE_FIXTURE_CA'); }
  let runtimeSource = sourceRefs;
  if (runtimeSource === null) {
    requireThat(import.meta.url.startsWith('file:'), 'HOST_TRUST_PREPARE_REVIEWED_SOURCE');
    let helper, bootstrap;
    try {
      helper = publicSource(fileURLToPath(import.meta.url), 65536, check); bootstrap = publicSource(fileURLToPath(new URL('./host-node-trust-start.mjs', import.meta.url)), 16384, check);
      runtimeSource = { helper: helper.reference, bootstrap: bootstrap.reference };
    } finally { helper?.retained.bytes.fill(0); bootstrap?.retained.bytes.fill(0); }
  } else {
    const held = publicSource(runtimeSource.helper.path, 65536, check);
    try { requireThat(equal(held.reference, runtimeSource.helper) && import.meta.url === 'data:text/javascript;base64,' + held.retained.bytes.toString('base64'), 'HOST_TRUST_PREPARE_REVIEWED_SOURCE'); }
    finally { held.retained.bytes.fill(0); }
  }
  const options = sourceRecipe(runtimeSource, check);
  rejectOverrides(environment, true, role, fixtureCA, process.execArgv, options.slice('--use-openssl-ca '.length));
  requireThat(typeof directory === 'string' && path.isAbsolute(directory) && path.resolve(directory) === directory, 'HOST_TRUST_OUTPUT_DIRECTORY');
  const parent = canonical(path.dirname(directory)); privateDirectory(parent, check, false, 'PARENT_DIRECTORY'); const target = path.join(parent, path.basename(directory));
  fs.mkdirSync(target, { mode: 0o700 }); privateDirectory(target, check, false, 'POLICY_DIRECTORY'); const empty = path.join(target, 'empty'); fs.mkdirSync(empty, { mode: 0o700 }); privateDirectory(empty, check, true, 'EMPTY_DIRECTORY');
  const bundle = writeExclusive(path.join(target, 'roots.pem'), Buffer.from(roots.pem), check);
  const descriptor = { schemaVersion: 1, kind: 'caseops-host-node-trust-v1', runtime: 'node', role, nodeVersion: roots.version, inputCount: roots.inputCount, inputSetSha256: roots.inputSetSha256, outputCount: roots.outputCount, outputSetSha256: roots.outputSetSha256, removedCount: roots.removedCount, deniedSha256: DENIED_HOST_CA, runtimeSource, bundle, emptyDirectory: empty, fixtureCA };
  const written = writeExclusive(path.join(target, 'policy.json'), Buffer.from(JSON.stringify(descriptor, null, 2) + '\n'), check), policyRef = { path: written.path, sha256: written.sha256 };
  const scoped = { NODE_OPTIONS: options, SSL_CERT_FILE: bundle.path, SSL_CERT_DIR: empty, [HOST_NODE_TRUST_ENV.file]: policyRef.path, [HOST_NODE_TRUST_ENV.sha256]: policyRef.sha256 };
  if (fixtureCA) scoped.NODE_EXTRA_CA_CERTS = fixtureCA.path;
  return { policyRef, descriptor, environment: scoped, effectiveDefaultVerified: false, globalTrustChanges: 0 };
}
function validatePolicy({ policyRef, role = 'base', expectedFixtureCA = null } = {}) {
  const environment = process.env, execArgv = process.execArgv;
  const check = operation(); reviewHostNodeBuildConfiguration(); requireThat(policyRef && DIGEST.test(policyRef.sha256 || ''), 'HOST_TRUST_POLICY_REFERENCE');
  const input = readHeld(policyRef.path, 16384, check, false, 'POLICY_INPUT'); let descriptor;
  try {
    descriptor = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(input.bytes));
    exactKeys(descriptor, ['schemaVersion', 'kind', 'runtime', 'role', 'nodeVersion', 'inputCount', 'inputSetSha256', 'outputCount', 'outputSetSha256', 'removedCount', 'deniedSha256', 'runtimeSource', 'bundle', 'emptyDirectory', 'fixtureCA']);
    requireThat(descriptor.schemaVersion === 1 && descriptor.kind === 'caseops-host-node-trust-v1' && descriptor.runtime === 'node' && descriptor.role === role && descriptor.nodeVersion === process.versions.node && descriptor.deniedSha256 === DENIED_HOST_CA && publicSha256(input.bytes) === policyRef.sha256 && input.path === policyRef.path, 'HOST_TRUST_POLICY_MISMATCH');
  } finally { input.bytes.fill(0); }
  const roots = reviewHostNodeRoots(); requireThat(descriptor.inputCount === roots.inputCount && descriptor.inputSetSha256 === roots.inputSetSha256 && descriptor.removedCount === roots.removedCount && descriptor.outputCount === roots.outputCount && descriptor.outputSetSha256 === roots.outputSetSha256, 'HOST_TRUST_POLICY_ROOTS');
  const options = sourceRecipe(descriptor.runtimeSource, check);
  rejectOverrides(environment, false, role, expectedFixtureCA, execArgv, options.slice('--use-openssl-ca '.length));
  requireThat(envValue(environment, 'NODE_OPTIONS') === options || envValue(environment, 'NODE_OPTIONS') === options + ' --enable-source-maps', 'HOST_TRUST_BOOTSTRAP_SOURCE_REQUIRED');
  requireThat(equal(descriptor.fixtureCA, expectedFixtureCA) && (role === 'native-qa' ? expectedFixtureCA !== null : expectedFixtureCA === null), 'HOST_TRUST_EXPECTED_FIXTURE_REQUIRED');
  const parent = path.dirname(policyRef.path); privateDirectory(parent, check, false, 'POLICY_DIRECTORY'); exactKeys(descriptor.bundle, ['path', 'sha256', 'sizeBytes']);
  requireThat(path.basename(policyRef.path) === 'policy.json' && descriptor.bundle.path === path.join(parent, 'roots.pem') && descriptor.emptyDirectory === path.join(parent, 'empty'), 'HOST_TRUST_POLICY_PATHS');
  requireThat(envValue(environment, HOST_NODE_TRUST_ENV.file) === policyRef.path && envValue(environment, HOST_NODE_TRUST_ENV.sha256) === policyRef.sha256 && envValue(environment, 'SSL_CERT_FILE') === descriptor.bundle.path && envValue(environment, 'SSL_CERT_DIR') === descriptor.emptyDirectory, 'HOST_TRUST_SCOPED_ENVIRONMENT_REQUIRED');
  const bundle = readHeld(descriptor.bundle.path, 1048576, check, false, 'ROOTS_INPUT'); let pems;
  try { const rows = certificates(new TextDecoder('utf-8', { fatal: true }).decode(bundle.bytes)), ids = rows.map(row => row.fingerprint); requireThat(ids.length === roots.outputCount && new Set(ids).size === ids.length && setDigest(ids) === roots.outputSetSha256 && !ids.includes(DENIED_HOST_CA) && bundle.bytes.length === descriptor.bundle.sizeBytes && publicSha256(bundle.bytes) === descriptor.bundle.sha256, 'HOST_TRUST_BUNDLE_CHANGED'); pems = rows.map(row => row.pem); }
  finally { bundle.bytes.fill(0); }
  privateDirectory(descriptor.emptyDirectory, check, true, 'EMPTY_DIRECTORY'); const expected = [...roots.fingerprints];
  if (expectedFixtureCA) { const fixture = fixtureCertificate(expectedFixtureCA, check); requireThat(!expected.includes(fixture.fingerprint) && envValue(environment, 'NODE_EXTRA_CA_CERTS') === expectedFixtureCA.path, 'HOST_TRUST_FIXTURE_ENVIRONMENT'); expected.push(fixture.fingerprint); pems.push(fixture.pem); }
  return { descriptor, roots, expected, pems, check };
}
function effectiveReport(validated) {
  const { descriptor, roots, expected, check } = validated; let enumerated = false;
  if (typeof tls.getCACertificates === 'function') { const actual = tls.getCACertificates('default').flatMap(certificates).map(row => row.fingerprint); requireThat(actual.length === expected.length && new Set(actual).size === actual.length && setDigest(actual) === setDigest(expected) && !actual.includes(DENIED_HOST_CA), 'HOST_TRUST_EFFECTIVE_DEFAULT_MISMATCH'); enumerated = true; }
  privateDirectory(descriptor.emptyDirectory, check, true, 'EMPTY_DIRECTORY');
  return { runtime: 'node', nodeVersion: roots.version, role: descriptor.role, expectedDefaultCount: expected.length, expectedDefaultSetSha256: setDigest(expected), defaultEnumerationVerified: enumerated, selectedStoreVerified: true, node22EnumerationUnavailable: !enumerated, activationScope: 'current-thread-before-entry', workersRequireInheritedBootstrap: true, globalTrustChanges: 0 };
}
/** Called only by the reviewed inherited bootstrap, before the actual entry. */
export function activateHostNodeTrust(options) {
  const admitted = validatePolicy(options);
  if (typeof tls.setDefaultCACertificates === 'function') tls.setDefaultCACertificates(admitted.pems);
  return effectiveReport(admitted);
}
/** No setter here: this checks the real current process, not a supplied env double. */
export function assertHostNodeTrust(options) { return effectiveReport(validatePolicy(options)); }

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const args = process.argv.slice(2);
    if (args.length === 2 && args[0] === 'prepare') console.log(JSON.stringify(prepareHostNodeTrust({ directory: path.resolve(args[1]) })));
    else if (args.length === 1 && args[0] === 'verify') console.log(JSON.stringify(assertHostNodeTrust({ policyRef: { path: process.env[HOST_NODE_TRUST_ENV.file], sha256: process.env[HOST_NODE_TRUST_ENV.sha256] } })));
    else fail('HOST_TRUST_CLI_USAGE');
  } catch (error) { console.error(JSON.stringify({ code: /^HOST_TRUST_[A-Z_]+$/.test(error.message) ? error.message : 'HOST_TRUST_REFUSED' })); process.exitCode = 1; }
}
