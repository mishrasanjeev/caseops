// Host-only Android role composition. The outer owned controller bounds the
// canonical compile; this module never changes a global CA or a generated gradlew.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { assertHostNodeTrust } from './host-node-trust.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';

export const ANDROID_HOST_ENV = Object.freeze({ file: 'CASEOPS_ANDROID_HOST_POLICY_FILE', sha256: 'CASEOPS_ANDROID_HOST_POLICY_SHA256' });
export const ANDROID_MARKER = Object.freeze({ name: 'X-CaseOps-Automated-Test', value: 'no-paid-providers' });
const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
const NODE = '/Users/sanjeevkumar/.nvm/versions/node/v24.15.0/bin/node';
const PYTHON = '/Users/sanjeevkumar/.cache/caseops-mobile/release-tooling/python/cpython-3.13.17-macos-aarch64-none/bin/python3.13';
const JAVA21 = '/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-21.0.12.1+1/Contents/Home';
const JAVA17 = '/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-17.0.20.1+1/Contents/Home';
const FRAME = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const IDENTITY = ['dev', 'ino', 'mode', 'uid', 'gid'];
const NODE_KEYS = ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256'];
const PLATFORM_KEYS = ['JAVA_TOOL_OPTIONS', 'CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE', 'CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256'];
const BAD = /^(?:BASH_ENV|ENV|PYTHONPATH|PYTHONHOME|RUBYOPT|DYLD_.*|LD_.*|NODE_PATH|NODE_EXTRA_CA_CERTS|NODE_USE_SYSTEM_CA|NODE_USE_ENV_PROXY|NODE_TLS_REJECT_UNAUTHORIZED|OPENSSL_CONF(?:_INCLUDE)?|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE|CURL_SSL_BACKEND|CMAKE_TLS_.*|CMAKE_NETRC(?:_FILE)?|PIP_CERT|JAVA_OPTS|GRADLE_OPTS|CLASSPATH|JDK_JAVA_OPTIONS|_JAVA_OPTIONS|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY)$/i;
const sha = data => createHash('sha256').update(data).digest('hex');
const same = (a, b) => FRAME.every(key => a[key] === b[key]);
const keys = (value, expected) => assert.ok(value && typeof value === 'object' && !Array.isArray(value) && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort()), 'ANDROID_HOST_EXACT_KEYS');
const check = end => assert.ok(performance.now() < end, 'ANDROID_HOST_DEADLINE');
const absolute = file => typeof file === 'string' && path.isAbsolute(file) && path.resolve(file) === file;
function closeOwned(fd, bodyFailed, retained = null) {
  try { fs.closeSync(fd); } catch {
    retained?.fill(0);
    try { process.stderr.write('ANDROID_HOST_DESCRIPTOR_CLOSE\n'); } catch {}
    if (!bodyFailed) throw new Error('ANDROID_HOST_DESCRIPTOR_CLOSE');
  }
}
function namespace(file, end) {
  const rows = [];
  for (let parent = path.dirname(file);;) {
    check(end); const state = fs.lstatSync(parent, { bigint: true });
    assert.ok(rows.length < 128 && state.isDirectory() && !state.isSymbolicLink(), 'ANDROID_HOST_NAMESPACE');
    rows.push([parent, ...IDENTITY.map(key => String(state[key]))]);
    if (parent === path.dirname(parent)) return rows;
    parent = path.dirname(parent);
  }
}
function privateDirectory(file, end) {
  check(end); const state = fs.lstatSync(file, { bigint: true });
  assert.ok(absolute(file) && fs.realpathSync(file) === file && state.isDirectory() && !state.isSymbolicLink() && typeof process.getuid === 'function' && state.uid === BigInt(process.getuid()) && (state.mode & 0o077n) === 0n, 'ANDROID_HOST_OWNED_DIRECTORY');
}
export function readAndroidHostInput(reference, { end = performance.now() + 5000, limit = 1048576 } = {}) {
  keys(reference, Object.hasOwn(reference, 'sizeBytes') ? ['path', 'sha256', 'sizeBytes'] : ['path', 'sha256']);
  assert.ok(absolute(reference.path) && /^[a-f0-9]{64}$/.test(reference.sha256) && (reference.sizeBytes === undefined || Number.isSafeInteger(reference.sizeBytes) && reference.sizeBytes > 0 && reference.sizeBytes <= limit) && Number.isSafeInteger(limit) && limit > 0 && limit <= 33554432 && typeof process.getuid === 'function', 'ANDROID_HOST_REFERENCE');
  check(end); const fd = fs.openSync(reference.path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK); let buffer, retained, bodyFailed = false;
  try {
    const initial = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(reference.path, { bigint: true });
    assert.ok(initial.isFile() && named.isFile() && !named.isSymbolicLink() && initial.nlink === 1n && initial.uid === BigInt(process.getuid()) && (initial.mode & 0o022n) === 0n && initial.size > 0n && initial.size <= BigInt(limit) && (reference.sizeBytes === undefined || initial.size === BigInt(reference.sizeBytes)) && same(initial, named), 'ANDROID_HOST_FILE');
    assert.equal(fs.realpathSync(reference.path), reference.path, 'ANDROID_HOST_CANONICAL'); const parents = namespace(reference.path, end);
    const size = Number(initial.size); buffer = Buffer.alloc(size + 1); let count = 0;
    while (count < buffer.length) { check(end); const n = fs.readSync(fd, buffer, count, Math.min(65536, buffer.length - count), null); if (!n) break; count += n; }
    assert.ok(count === size && sha(buffer.subarray(0, count)) === reference.sha256 && same(initial, fs.fstatSync(fd, { bigint: true })) && same(named, fs.lstatSync(reference.path, { bigint: true })) && fs.realpathSync(reference.path) === reference.path, 'ANDROID_HOST_INPUT_CHANGED');
    assert.deepEqual(namespace(reference.path, end), parents, 'ANDROID_HOST_NAMESPACE_CHANGED'); retained = Buffer.from(buffer.subarray(0, count)); return retained;
  } catch (error) { bodyFailed = true; throw error; }
  finally { buffer?.fill(0); closeOwned(fd, bodyFailed, retained); }
}
function readJson(reference, options) {
  const bytes = readAndroidHostInput(reference, options);
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  finally { bytes.fill(0); }
}
function reference(file, end, limit = 1048576) {
  check(end); const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK); let data, bodyFailed = false;
  try {
    const state = fs.fstatSync(fd, { bigint: true });
    assert.ok(state.isFile() && state.uid === BigInt(process.getuid()) && state.nlink === 1n && (state.mode & 0o022n) === 0n && state.size > 0n && state.size <= BigInt(limit) && same(state, fs.lstatSync(file, { bigint: true })) && fs.realpathSync(file) === file, 'ANDROID_HOST_SOURCE');
    const parents = namespace(file, end); data = Buffer.alloc(Number(state.size) + 1); let n = 0;
    while (n < data.length) { check(end); const width = fs.readSync(fd, data, n, Math.min(65536, data.length - n), null); if (!width) break; n += width; }
    assert.ok(BigInt(n) === state.size && same(state, fs.fstatSync(fd, { bigint: true })) && same(state, fs.lstatSync(file, { bigint: true })) && fs.realpathSync(file) === file, 'ANDROID_HOST_INPUT_CHANGED');
    assert.deepEqual(namespace(file, end), parents); return { path: file, sha256: sha(data.subarray(0, n)), sizeBytes: n };
  } catch (error) { bodyFailed = true; throw error; }
  finally { data?.fill(0); closeOwned(fd, bodyFailed); }
}
export function writeAndroidHostOutput(file, data, end = performance.now() + 5000, mode = 0o400) {
  assert.ok(Buffer.isBuffer(data) && data.length > 0 && data.length <= 1048576 && [0o400, 0o500].includes(mode), 'ANDROID_HOST_OUTPUT_BOUND');
  privateDirectory(path.dirname(file), end); const parents = namespace(file, end), fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, mode); let probe, bodyFailed = false;
  try {
    const initial = fs.fstatSync(fd, { bigint: true }); assert.ok(initial.isFile() && initial.uid === BigInt(process.getuid()) && initial.nlink === 1n && initial.size === 0n && (initial.mode & 0o777n) === BigInt(mode), 'ANDROID_HOST_EXCLUSIVE_OUTPUT');
    const initialNamed = fs.lstatSync(file, { bigint: true });
    assert.ok(initialNamed.isFile() && !initialNamed.isSymbolicLink() && same(initial, initialNamed) && fs.realpathSync(file) === file, 'ANDROID_HOST_OUTPUT_PREWRITE_BINDING');
    assert.deepEqual(namespace(file, end), parents, 'ANDROID_HOST_OUTPUT_PREWRITE_NAMESPACE');
    let n = 0; while (n < data.length) { check(end); const width = fs.writeSync(fd, data, n, Math.min(65536, data.length - n), n); assert.ok(width > 0 && width <= data.length - n, 'ANDROID_HOST_WRITE_PROGRESS'); n += width; }
    fs.fsyncSync(fd); const written = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    for (const key of ['dev', 'ino', 'uid', 'gid', 'mode', 'nlink']) assert.equal(written[key], initial[key], 'ANDROID_HOST_OUTPUT_IDENTITY');
    assert.ok(same(written, named) && !named.isSymbolicLink() && written.size === BigInt(data.length), 'ANDROID_HOST_OUTPUT_IDENTITY');
    probe = Buffer.alloc(data.length + 1); n = 0;
    while (n < probe.length) { check(end); const width = fs.readSync(fd, probe, n, Math.min(65536, probe.length - n), n); if (!width) break; n += width; }
    assert.ok(n === data.length && probe.subarray(0, n).equals(data) && same(written, fs.fstatSync(fd, { bigint: true })) && same(named, fs.lstatSync(file, { bigint: true })) && fs.realpathSync(file) === file, 'ANDROID_HOST_OUTPUT_CHANGED');
    assert.deepEqual(namespace(file, end), parents); return { path: file, sha256: sha(data), sizeBytes: data.length };
  } catch (error) { bodyFailed = true; throw error; }
  finally { probe?.fill(0); closeOwned(fd, bodyFailed); }
}
const quote = value => { assert.ok(typeof value === 'string' && value.length > 0 && !/[\0\r\n]/.test(value), 'ANDROID_HOST_SHELL_VALUE'); return "'" + value.replaceAll("'", "'\\''") + "'"; };
export function androidGradleArguments(java21 = JAVA21, java17 = JAVA17) {
  assert.equal(java21, JAVA21, 'ANDROID_HOST_JAVA21'); assert.equal(java17, JAVA17, 'ANDROID_HOST_JAVA17');
  return ['./gradlew', ':app:assembleLocalAcceptance', '-PreactNativeArchitectures=arm64-v8a', '-Pandroid.compileSdkVersion=37', '-Pandroid.buildToolsVersion=37.0.0', '-Pandroid.ndkVersion=27.1.12297006', '-Pandroid.cmakeVersion=3.30.5', '-Pandroid.builder.sdkDownload=false', `-Dorg.gradle.java.installations.paths=${java17},${java21}`, '-Dorg.gradle.java.installations.auto-download=false', '--no-daemon', '--max-workers=2', '--console=plain'];
}
/** Pure source-owned projection; actual role admission must precede dispatch. */
export function androidGradleExecutionArguments(args, policy, environment, end = performance.now() + 5000) {
  assert.equal(environment.JAVA_HOME, JAVA21, 'PINNED_JDK21_REQUIRED');
  assert.equal(environment.CASEOPS_ANDROID_JDK17_HOME, JAVA17, 'PINNED_JDK17_REQUIRED');
  assert.deepEqual(args, androidGradleArguments(environment.JAVA_HOME, environment.CASEOPS_ANDROID_JDK17_HOME), 'ANDROID_HOST_CANONICAL_GRADLE_ARGV');
  assert.equal(environment.JAVA_TOOL_OPTIONS, policy.javaOptions, 'ANDROID_HOST_BOUND_JAVA_OPTIONS');
  const binding = { privateJavaHome: policy.privateJavaHome, privateJavaTmp: policy.privateJavaTmp,
    sharedJavaOptions: policy.sharedJavaOptions, javaOptions: policy.javaOptions, gradlePolicyReference: policy.gradlePolicyReference };
  bindAndroidJavaHome({ ...environment, JAVA_TOOL_OPTIONS: policy.sharedJavaOptions }, binding, end);
  return [...args, '-Pkotlin.daemon.jvmargs=' + policy.javaOptions];
}
export function neutralAndroidGradleEnvironment(environment, expectedNodeEnvironment) {
  keys(expectedNodeEnvironment, NODE_KEYS); const output = {};
  for (const [key, value] of Object.entries(environment)) {
    assert.ok(typeof value === 'string' && ((!BAD.test(key) && !PLATFORM_KEYS.some(expected => key.toUpperCase() === expected) && !/^(?:NODE_OPTIONS|SSL_CERT_FILE|SSL_CERT_DIR|CASEOPS_HOST_NODE_TRUST_POLICY_(?:FILE|SHA256))$/i.test(key)) || (NODE_KEYS.includes(key) && value === expectedNodeEnvironment[key])), 'ANDROID_HOST_CROSS_ROLE_OVERRIDE');
    if (!NODE_KEYS.includes(key)) output[key] = value;
  }
  for (const key of NODE_KEYS) assert.equal(environment[key], expectedNodeEnvironment[key], 'ANDROID_HOST_NODE_RECIPE_REQUIRED');
  return output;
}
export function assertAndroidNodePath(environment, nodeShimPath, sourcePath) {
  assert.ok(absolute(nodeShimPath) && path.basename(nodeShimPath) === 'node' && typeof sourcePath === 'string' && sourcePath.length > 0 && !/[\0\r\n]/.test(sourcePath), 'ANDROID_HOST_SOURCE_PATH');
  const directory = path.dirname(nodeShimPath), entries = sourcePath.split(path.delimiter);
  assert.ok(entries.length <= 64 && entries.every(entry => absolute(entry) && entry !== directory), 'ANDROID_HOST_SOURCE_PATH');
  assert.equal(environment.PATH, directory + path.delimiter + sourcePath, 'ANDROID_HOST_NODE_SHIM_PATH_REQUIRED');
}
function privateJavaTemporaryBinding(file, end) {
  assert.ok(absolute(file) && !/[\s\0"'\\]/.test(file) && file !== ROOT && !file.startsWith(ROOT + path.sep), 'ANDROID_HOST_PRIVATE_JAVA_TMP');
  privateDirectory(file, end);
  const initial = fs.lstatSync(file, { bigint: true }), parents = namespace(file, end);
  assert.equal(initial.mode & 0o777n, 0o700n, 'ANDROID_HOST_PRIVATE_JAVA_TMP_MODE');
  const current = fs.lstatSync(file, { bigint: true });
  assert.ok(IDENTITY.every(key => initial[key] === current[key]) && fs.realpathSync(file) === file, 'ANDROID_HOST_PRIVATE_JAVA_TMP_CHANGED');
  assert.deepEqual(namespace(file, end), parents, 'ANDROID_HOST_PRIVATE_JAVA_TMP_NAMESPACE');
  return { path: file, identity: IDENTITY.map(key => String(initial[key])), namespace: parents };
}
export function bindAndroidJavaHome(environment, binding, end = performance.now() + 5000) {
  assert.ok(environment && typeof environment === 'object' && !Array.isArray(environment), 'ANDROID_HOST_JAVA_ENVIRONMENT');
  keys(binding, ['privateJavaHome', 'privateJavaTmp', 'sharedJavaOptions', 'javaOptions', 'gradlePolicyReference']);
  keys(binding.gradlePolicyReference, ['path', 'sha256', 'sizeBytes']);
  const { privateJavaHome, privateJavaTmp, sharedJavaOptions, javaOptions, gradlePolicyReference } = binding;
  assert.ok(absolute(gradlePolicyReference.path) && /^[a-f0-9]{64}$/.test(gradlePolicyReference.sha256) && Number.isSafeInteger(gradlePolicyReference.sizeBytes) && gradlePolicyReference.sizeBytes > 0 && gradlePolicyReference.sizeBytes <= 1048576, 'ANDROID_HOST_GRADLE_REFERENCE');
  assert.ok(absolute(privateJavaHome) && !/[\s\0"'\\]/.test(privateJavaHome) && privateJavaHome !== ROOT && !privateJavaHome.startsWith(ROOT + path.sep), 'ANDROID_HOST_PRIVATE_JAVA_HOME');
  privateDirectory(privateJavaHome, end);
  assert.equal(environment.HOME, privateJavaHome, 'ANDROID_HOST_PRIVATE_JAVA_HOME');
  keys(privateJavaTmp, ['path', 'identity', 'namespace']);
  assert.notEqual(privateJavaTmp.path, privateJavaHome, 'ANDROID_HOST_PRIVATE_JAVA_TMP');
  assert.deepEqual(privateJavaTmp, privateJavaTemporaryBinding(privateJavaTmp.path, end), 'ANDROID_HOST_PRIVATE_JAVA_TMP_IDENTITY');
  assert.equal(environment.TMPDIR, privateJavaTmp.path, 'ANDROID_HOST_BOUND_TMPDIR');
  assert.ok(typeof sharedJavaOptions === 'string' && /^-Djavax\.net\.ssl\.trustStore=\/[^\s\0"'\\]+ -Djavax\.net\.ssl\.trustStoreType=PKCS12 -Djavax\.net\.ssl\.trustStorePassword=changeit$/.test(sharedJavaOptions), 'ANDROID_HOST_SHARED_JAVA_OPTIONS');
  assert.equal(javaOptions, sharedJavaOptions + ' -Djava.io.tmpdir=' + privateJavaTmp.path + ' -Duser.home=' + privateJavaHome, 'ANDROID_HOST_BOUND_JAVA_OPTIONS');
  // This check deliberately precedes addition: the real shared helper must have
  // returned its exact production three-option recipe, with no inherited home.
  assert.equal(environment.JAVA_TOOL_OPTIONS, sharedJavaOptions, 'ANDROID_GRADLE_JAVA117_RECIPE');
  assert.equal(environment.CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE, gradlePolicyReference.path, 'ANDROID_GRADLE_POLICY_RECIPE');
  assert.equal(environment.CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256, gradlePolicyReference.sha256, 'ANDROID_GRADLE_POLICY_RECIPE');
  for (const key of Object.keys(environment)) assert.ok(!BAD.test(key) && !NODE_KEYS.some(expected => key.toUpperCase() === expected) && (!PLATFORM_KEYS.some(expected => key.toUpperCase() === expected) || PLATFORM_KEYS.includes(key)), 'ANDROID_HOST_CROSS_ROLE_OVERRIDE');
  return { ...environment, JAVA_TOOL_OPTIONS: javaOptions };
}
/** Public declaration projection only; fresh dual-JDK byte/root admission remains required. */
export function androidSharedJavaOptions(value) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value) && value.schemaVersion === 1 && value.kind === 'caseops-host-gradle-jdks-trust-v1' && value.runtimeScope === 'gradle-java21-java17' && value.qaOnly === false && value.type === 'PKCS12', 'ANDROID_HOST_PRODUCTION_JAVA117_REQUIRED');
  const aliases = value.aliases;
  assert.ok(aliases && typeof aliases === 'object' && !Array.isArray(aliases) && Object.getPrototypeOf(aliases) === Object.prototype && Object.keys(aliases).length === 117 && Object.entries(aliases).every(([name, digest]) => name.length > 0 && name.length <= 512 && typeof digest === 'string' && /^[a-f0-9]{64}$/.test(digest)) && new Set(Object.values(aliases)).size === 117, 'ANDROID_HOST_PRODUCTION_JAVA117_ALIASES');
  keys(value.store, ['path', 'sha256', 'sizeBytes']);
  assert.ok(absolute(value.store.path) && !/[\s\0"'\\]/.test(value.store.path) && typeof value.store.sha256 === 'string' && /^[a-f0-9]{64}$/.test(value.store.sha256) && Number.isSafeInteger(value.store.sizeBytes) && value.store.sizeBytes > 0 && value.store.sizeBytes <= 1048576, 'ANDROID_HOST_SHARED_STORE_REFERENCE');
  return `-Djavax.net.ssl.trustStore=${value.store.path} -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=changeit`;
}
export function renderAndroidNodeShim(nodeExecutable, nodeEnvironment, gradlePolicyReference, javaOptions) {
  keys(nodeEnvironment, NODE_KEYS); keys(gradlePolicyReference, ['path', 'sha256', 'sizeBytes']);
  assert.ok(absolute(nodeExecutable), 'ANDROID_HOST_NODE_EXECUTABLE');
  const lines = ['#!/bin/bash', 'set -euo pipefail'];
  for (const key of NODE_KEYS) lines.push(`[[ -z "\${${key}:-}" || "\${${key}}" = ${quote(nodeEnvironment[key])} ]] || { echo ANDROID_HOST_NODE_RECIPE_REFUSED >&2; exit 37; }`);
  lines.push(`[[ -z "\${JAVA_TOOL_OPTIONS:-}" || "$JAVA_TOOL_OPTIONS" = ${quote(javaOptions)} ]] || { echo ANDROID_HOST_JAVA_RECIPE_REFUSED >&2; exit 37; }`);
  for (const [key, value] of [['CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE', gradlePolicyReference.path], ['CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256', gradlePolicyReference.sha256]]) lines.push(`[[ -z "\${${key}:-}" || "\${${key}}" = ${quote(value)} ]] || { echo ANDROID_HOST_JAVA_RECIPE_REFUSED >&2; exit 37; }`);
  for (const key of ['NODE_PATH', 'NODE_EXTRA_CA_CERTS', 'NODE_USE_SYSTEM_CA', 'NODE_USE_ENV_PROXY', 'NODE_TLS_REJECT_UNAUTHORIZED', 'OPENSSL_CONF', 'OPENSSL_CONF_INCLUDE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'CURL_SSL_BACKEND', 'CMAKE_TLS_VERIFY', 'CMAKE_TLS_CAINFO', 'CMAKE_TLS_VERSION', 'CMAKE_NETRC', 'CMAKE_NETRC_FILE', 'PIP_CERT', 'JAVA_OPTS', 'GRADLE_OPTS', 'CLASSPATH', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY']) lines.push(`[[ -z "\${${key}:-}" ]] || { echo ANDROID_HOST_OVERRIDE_REFUSED >&2; exit 37; }`);
  lines.push('unset JAVA_TOOL_OPTIONS CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256');
  for (const key of NODE_KEYS) lines.push(`export ${key}=${quote(nodeEnvironment[key])}`);
  lines.push(`exec ${quote(nodeExecutable)} "$@"`, ''); return Buffer.from(lines.join('\n'));
}
function sourceEnvironment(environment, end) {
  assert.equal(environment.HOME, process.env.HOME, 'ANDROID_HOST_ACTUAL_SOURCE_ENVIRONMENT');
  assert.equal(environment.PATH, process.env.PATH, 'ANDROID_HOST_ACTUAL_SOURCE_ENVIRONMENT');
  assert.equal(environment.TMPDIR, process.env.TMPDIR, 'ANDROID_HOST_ACTUAL_SOURCE_ENVIRONMENT');
  privateJavaTemporaryBinding(environment.TMPDIR, end);
  privateDirectory(environment.HOME, end);
  assert.ok(environment.HOME !== ROOT && !environment.HOME.startsWith(ROOT + path.sep), 'ANDROID_HOST_EXTERNAL_HOME');
  for (const [key, expected] of [['GIT_CONFIG_GLOBAL', '/dev/null'], ['GIT_CONFIG_NOSYSTEM', '1'], ['GIT_OPTIONAL_LOCKS', '0'], ['GIT_TERMINAL_PROMPT', '0']]) {
    assert.equal(environment[key], expected, 'ANDROID_HOST_ANONYMOUS_GIT'); assert.equal(process.env[key], expected, 'ANDROID_HOST_ACTUAL_SOURCE_ENVIRONMENT');
  }
  for (const key of Object.keys(environment)) assert.ok(!/^GIT_CONFIG_(?:COUNT|KEY_.*|VALUE_.*)$/.test(key), 'ANDROID_HOST_GIT_OVERRIDE');
}
function cleanSource() {
  const value = sourceSnapshot(ROOT); assert.ok(value.sourceDirty === false && /^[a-f0-9]{40}$/.test(value.sourceSha) && /^[a-f0-9]{64}$/.test(value.sourceFingerprint), 'ANDROID_HOST_CLEAN_SOURCE_REQUIRED'); return value;
}
export function prepareAndroidHostLauncher({ directory, nodePolicyReference, gradlePolicyReference, environment = process.env } = {}) {
  const end = performance.now() + 20000; assert.equal(process.versions.node, '24.15.0', 'ANDROID_HOST_PINNED_NODE'); assert.equal(process.execPath, NODE, 'ANDROID_HOST_PINNED_NODE_PATH');
  privateDirectory(path.dirname(directory), end); assert.ok(absolute(directory) && directory !== ROOT && !directory.startsWith(ROOT + path.sep), 'ANDROID_HOST_EXTERNAL_DIRECTORY');
  const report = assertHostNodeTrust({ policyRef: nodePolicyReference, role: 'base' }); assert.ok(report.expectedDefaultCount === 144 && report.defaultEnumerationVerified === true, 'ANDROID_HOST_NODE144_REQUIRED');
  const nodePolicy = readJson(nodePolicyReference, { end, limit: 32768 });
  sourceEnvironment(environment, end); const source = cleanSource(), sourceFiles = {};
  for (const [name, relative] of Object.entries({ helper: 'scripts/mobile/android-host-launch.mjs', marker: 'scripts/mobile/android-no-paid.gradle', platform: 'scripts/mobile/host-platform-trust.py', javaFixture: 'scripts/mobile/fixtures/host-platform-trust/HostPlatformTrust.java' })) sourceFiles[name] = reference(path.join(ROOT, relative), end);
  assert.equal(nodePolicy.runtimeSource.helper.path, path.join(ROOT, 'scripts/mobile/host-node-trust.mjs'), 'ANDROID_HOST_NODE_SOURCE_ROOT');
  assert.equal(nodePolicy.runtimeSource.bootstrap.path, path.join(ROOT, 'scripts/mobile/host-node-trust-start.mjs'), 'ANDROID_HOST_NODE_SOURCE_ROOT');
  const bootstrap = readAndroidHostInput(nodePolicy.runtimeSource.bootstrap, { end, limit: 16384 });
  const nodeEnvironment = { NODE_OPTIONS: '--use-openssl-ca --import=data:text/javascript;base64,' + bootstrap.toString('base64'), SSL_CERT_FILE: nodePolicy.bundle.path, SSL_CERT_DIR: nodePolicy.emptyDirectory, CASEOPS_HOST_NODE_TRUST_POLICY_FILE: nodePolicyReference.path, CASEOPS_HOST_NODE_TRUST_POLICY_SHA256: nodePolicyReference.sha256 }; bootstrap.fill(0);
  neutralAndroidGradleEnvironment(environment, nodeEnvironment);
  const gradle = readJson(gradlePolicyReference, { end });
  const sharedJavaOptions = androidSharedJavaOptions(gradle);
  const runtimeEnvironment = { [ANDROID_HOST_ENV.file]: path.join(directory, 'policy.json'), PATH: directory + path.delimiter + environment.PATH };
  assertAndroidNodePath(runtimeEnvironment, path.join(directory, 'node'), environment.PATH);
  fs.mkdirSync(directory, { mode: 0o700 }); privateDirectory(directory, end);
  const privateJavaHome = environment.HOME, privateJavaTmp = privateJavaTemporaryBinding(environment.TMPDIR, end);
  const javaOptions = sharedJavaOptions + ' -Djava.io.tmpdir=' + privateJavaTmp.path + ' -Duser.home=' + privateJavaHome;
  // Validate the public binding before staging either executable or policy.
  bindAndroidJavaHome({ HOME: privateJavaHome, TMPDIR: privateJavaTmp.path, JAVA_TOOL_OPTIONS: sharedJavaOptions, CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE: gradlePolicyReference.path, CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256: gradlePolicyReference.sha256 }, { privateJavaHome, privateJavaTmp, sharedJavaOptions, javaOptions, gradlePolicyReference }, end);
  const nodeShim = writeAndroidHostOutput(path.join(directory, 'node'), renderAndroidNodeShim(process.execPath, nodeEnvironment, gradlePolicyReference, javaOptions), end, 0o500);
  const value = { schemaVersion: 1, kind: 'caseops-android-host-role-v1', sourceRoot: ROOT, source, sourceFiles, sourcePath: environment.PATH, nodeExecutable: process.execPath, pythonExecutable: PYTHON, nodePolicyReference, gradlePolicyReference, nodeEnvironment, privateJavaHome, privateJavaTmp, sharedJavaOptions, javaOptions, nodeShim, limits: { compileSeconds: 1800, cleanupSeconds: 30, pipeBytes: 67108864 } };
  const policyReference = writeAndroidHostOutput(path.join(directory, 'policy.json'), Buffer.from(JSON.stringify(value) + '\n'), end);
  return { policyReference, descriptor: value, environment: { ...runtimeEnvironment, [ANDROID_HOST_ENV.sha256]: policyReference.sha256 }, actualGradleAdmission: 'required-fresh-before-dispatch', downloads: 0, nativeBuilds: 0 };
}
export function readAndroidHostPolicy(policyReference) {
  const end = performance.now() + 20000;
  const value = readJson(policyReference, { end, limit: 131072 });
  keys(value, ['schemaVersion', 'kind', 'sourceRoot', 'source', 'sourceFiles', 'sourcePath', 'nodeExecutable', 'pythonExecutable', 'nodePolicyReference', 'gradlePolicyReference', 'nodeEnvironment', 'privateJavaHome', 'privateJavaTmp', 'sharedJavaOptions', 'javaOptions', 'nodeShim', 'limits']);
  assert.ok(value.schemaVersion === 1 && value.kind === 'caseops-android-host-role-v1' && value.sourceRoot === ROOT && value.pythonExecutable === PYTHON && value.nodeExecutable === NODE && process.execPath === NODE, 'ANDROID_HOST_POLICY');
  sourceEnvironment(process.env, end);
  assert.deepEqual(value.limits, { compileSeconds: 1800, cleanupSeconds: 30, pipeBytes: 67108864 }); assert.deepEqual(value.source, cleanSource(), 'ANDROID_HOST_SOURCE_CHANGED');
  keys(value.sourceFiles, ['helper', 'marker', 'platform', 'javaFixture']);
  for (const [name, relative] of Object.entries({ helper: 'scripts/mobile/android-host-launch.mjs', marker: 'scripts/mobile/android-no-paid.gradle', platform: 'scripts/mobile/host-platform-trust.py', javaFixture: 'scripts/mobile/fixtures/host-platform-trust/HostPlatformTrust.java' })) {
    assert.equal(value.sourceFiles[name].path, path.join(ROOT, relative), 'ANDROID_HOST_SOURCE_PATH'); readAndroidHostInput(value.sourceFiles[name], { end }).fill(0);
  }
  assert.equal(value.nodeShim.path, path.join(path.dirname(policyReference.path), 'node'), 'ANDROID_HOST_NODE_SHIM_PATH');
  assertAndroidNodePath(process.env, value.nodeShim.path, value.sourcePath);
  bindAndroidJavaHome({ HOME: process.env.HOME, TMPDIR: process.env.TMPDIR, JAVA_TOOL_OPTIONS: value.sharedJavaOptions, CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE: value.gradlePolicyReference.path, CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256: value.gradlePolicyReference.sha256 }, { privateJavaHome: value.privateJavaHome, privateJavaTmp: value.privateJavaTmp, sharedJavaOptions: value.sharedJavaOptions, javaOptions: value.javaOptions, gradlePolicyReference: value.gradlePolicyReference }, end);
  const shim = readAndroidHostInput(value.nodeShim, { end }); try { assert.ok(shim.equals(renderAndroidNodeShim(value.nodeExecutable, value.nodeEnvironment, value.gradlePolicyReference, value.javaOptions)), 'ANDROID_HOST_NODE_SHIM_BYTES'); } finally { shim.fill(0); }
  assertHostNodeTrust({ policyRef: value.nodePolicyReference, role: 'base' }); neutralAndroidGradleEnvironment(process.env, value.nodeEnvironment); return value;
}
async function gradleEnvironment(policy, logFile, end) {
  const data = readAndroidHostInput(policy.sourceFiles.platform, { end }), neutral = neutralAndroidGradleEnvironment(process.env, policy.nodeEnvironment);
  const program = "import os,sys,json,base64,time\ns={'__name__':'retained_android_platform','__file__':sys.argv[1]};exec(compile(base64.b64decode(sys.argv[2]),sys.argv[1],'exec'),s)\ncharged=0\ndef record(value):\n global charged\n b=(json.dumps(value,separators=(',',':'))+'\\n').encode();charged+=len(b)\n if charged>1048576:raise RuntimeError('ANDROID_GRADLE_DIAGNOSTIC_BOUND')\n n=0\n while n<len(b):\n  w=os.write(3,b[n:]);assert w>0;n+=w\n os.fsync(3)\nenv=s['scoped_gradle_environment'](json.loads(sys.argv[3]),dict(os.environ),verification_log=record);print(json.dumps(env,separators=(',',':')))\n";
  let fd, output = Buffer.alloc(0), overflow = false, bodyFailed = false;
  try {
    fd = fs.openSync(logFile, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW, 0o600);
    const initial = fs.fstatSync(fd, { bigint: true }), initialNamed = fs.lstatSync(logFile, { bigint: true }), parents = namespace(logFile, end);
    assert.ok(initial.isFile() && initial.uid === BigInt(process.getuid()) && initial.nlink === 1n && initial.size === 0n && (initial.mode & 0o777n) === 0o600n && same(initial, initialNamed), 'ANDROID_GRADLE_EXCLUSIVE_DIAGNOSTIC');
    await new Promise((resolve, reject) => {
      const child = spawn(PYTHON, ['-I', '-B', '-c', program, policy.sourceFiles.platform.path, data.toString('base64'), JSON.stringify(policy.gradlePolicyReference)], { env: neutral, stdio: ['ignore', 'pipe', 'inherit', fd] });
      child.stdout.on('data', part => { if (part.length <= 65536 - output.length && !overflow) output = Buffer.concat([output, part]); else overflow = true; }); child.on('error', reject); child.on('close', (code, signal) => code === 0 && signal === null && !overflow ? resolve() : reject(new Error('ANDROID_GRADLE_ADMISSION_REFUSED')));
    });
    fs.fsyncSync(fd); const state = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(logFile, { bigint: true }); assert.ok(state.isFile() && state.nlink === 1n && state.uid === BigInt(process.getuid()) && state.size > 0n && state.size <= 1048576n && same(state, named), 'ANDROID_GRADLE_DIAGNOSTIC_FILE');
    for (const key of ['dev', 'ino', 'uid', 'gid', 'mode', 'nlink']) assert.equal(initial[key], state[key], 'ANDROID_GRADLE_DIAGNOSTIC_IDENTITY');
    assert.deepEqual(namespace(logFile, end), parents, 'ANDROID_GRADLE_DIAGNOSTIC_NAMESPACE'); check(end);
    const result = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(output));
    const binding = { privateJavaHome: policy.privateJavaHome, privateJavaTmp: policy.privateJavaTmp, sharedJavaOptions: policy.sharedJavaOptions, javaOptions: policy.javaOptions, gradlePolicyReference: policy.gradlePolicyReference };
    return bindAndroidJavaHome(result, binding, end);
  } catch (error) { bodyFailed = true; throw error; }
  finally { data.fill(0); output.fill(0); if (fd !== undefined) closeOwned(fd, bodyFailed); }
}
/** Fresh shared-JDK admission only. It never starts Gradle or builds an app. */
export async function prepareAndroidGradleEnvironment(policyReference) {
  const policy = readAndroidHostPolicy(policyReference), end = performance.now() + 60000;
  return { environment: await gradleEnvironment(policy, path.join(path.dirname(policyReference.path), 'gradle-verification.jsonl'), end), policy };
}
export async function runAndroidGradle(policyReference, args) {
  const policy = readAndroidHostPolicy(policyReference), cwd = path.join(ROOT, 'apps/mobile/android'); assert.equal(fs.realpathSync(process.cwd()), cwd, 'ANDROID_HOST_GENERATED_PROJECT_REQUIRED');
  assert.deepEqual(args, androidGradleArguments(process.env.JAVA_HOME, process.env.CASEOPS_ANDROID_JDK17_HOME), 'ANDROID_HOST_CANONICAL_GRADLE_ARGV');
  assert.equal(process.env.CASEOPS_ANDROID_COMPILE_READY_GO, policy.source.sourceSha, 'ANDROID_HOST_COMPILE_NOT_ARMED');
  const end = performance.now() + 60000, logFile = path.join(path.dirname(policyReference.path), 'gradle-verification.jsonl'), env = await gradleEnvironment(policy, logFile, end);
  const executionArgs = androidGradleExecutionArguments(args, policy, env, end);
  env.CASEOPS_ANDROID_MARKED_SOURCE_ROOT = ROOT;
  const initDirectory = path.join(env.GRADLE_USER_HOME, 'init.d'); privateDirectory(env.GRADLE_USER_HOME, end); fs.mkdirSync(initDirectory, { mode: 0o700 });
  const marker = readAndroidHostInput(policy.sourceFiles.marker, { end }); try { writeAndroidHostOutput(path.join(initDirectory, 'caseops-no-paid.gradle'), marker, end); } finally { marker.fill(0); }
  return await new Promise((resolve, reject) => { const child = spawn(executionArgs[0], executionArgs.slice(1), { cwd, env, stdio: 'inherit' }); child.on('error', reject); child.on('close', (code, signal) => signal === null && Number.isInteger(code) ? resolve(code) : reject(new Error('ANDROID_GRADLE_OUTCOME_UNKNOWN'))); });
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const [role, ...args] = process.argv.slice(2);
    if (role === 'gradle' && args.shift() === '--') process.exitCode = await runAndroidGradle({ path: process.env[ANDROID_HOST_ENV.file], sha256: process.env[ANDROID_HOST_ENV.sha256] }, args);
    else throw new Error('ANDROID_HOST_COMMAND');
  } catch { console.error('Android host role preparation refused.'); process.exitCode = 1; }
}
