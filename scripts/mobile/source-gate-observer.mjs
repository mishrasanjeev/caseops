// Optional source-gate instrumentation only. Importing this module is inert.
// Native/build/signing entrypoints never receive a recording Session.
import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomBytes } from 'node:crypto';
import inspector from 'node:inspector';
import { stopCoverage } from 'node:v8';
import { isMainThread, threadId } from 'node:worker_threads';
import dc from 'node:diagnostics_channel';

export const SOURCE_GATE_OBSERVER_ENV = Object.freeze({
  file: 'CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE', sha256: 'CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256',
});
export const SOURCE_GATE_WORKER_PATHS = Object.freeze([
  "scripts/mobile/build-config.test.mjs",
  "scripts/mobile/tooling.test.mjs",
  "scripts/mobile/local-owner-controls.test.mjs",
  "apps/mobile/e2e/files-20261025.test.mjs",
  "apps/mobile/e2e/ios-files.test.mjs",
  "apps/mobile/e2e/android-files.test.mjs",
  "scripts/mobile/ios-browser-context.test.mjs",
  "scripts/mobile/ios-native-locators.test.mjs",
  "scripts/mobile/ios-simulator-signing.test.mjs",
  "scripts/mobile/prepare-gateway-routes.test.mjs",
  "scripts/mobile/prepare-ios-local-run.test.mjs",
  "scripts/mobile/ios-files-privacy.test.mjs",
  "scripts/mobile/camera-files-privacy.test.mjs",
  "scripts/mobile/run-ios-files.test.mjs",
  "scripts/mobile/filesystem-security.test.mjs",
  "apps/mobile/e2e/evidence.test.mjs",
  "scripts/mobile/build-android-local-acceptance.test.mjs",
  "scripts/mobile/android-native-proof.test.mjs",
  "scripts/mobile/prepare-android-local-run.test.mjs",
  "scripts/mobile/android-files-privacy.test.mjs",
  "scripts/mobile/run-android-files.test.mjs",
  "scripts/mobile/store-packaging.test.mjs",
  "scripts/mobile/store-artifact-postflight.test.mjs",
  "scripts/mobile/store-packaging-execution.test.mjs",
  "scripts/mobile/forge-security.test.mjs",
  "scripts/mobile/deepmerge-security.test.mjs",
  "scripts/mobile/deepmerge-installed.test.mjs",
  "scripts/mobile/privacy-policy.test.mjs",
  "scripts/mobile/prepare-source-exports.test.mjs",
  "apps/mobile/e2e/v1-workflows.test.mjs",
  "scripts/mobile/v1-workflows-credentials.test.mjs",
  "apps/mobile/e2e/queue-privacy.test.mjs",
  "scripts/mobile/client-extensions.test.mjs"
]);
const HASH = createHash, RANDOM = randomBytes;
const NOW = Date.now.bind(Date), HR = process.hrtime.bigint.bind(process.hrtime);
const EXIT = process.reallyExit.bind(process), ON = process.on.bind(process);
const UID = process.getuid?.(), PLATFORM = process.platform;
const FIELDS = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const IDENT = FIELDS.slice(0, 5);
const IO = Object.fromEntries(['openSync', 'closeSync', 'readSync', 'writeSync', 'fstatSync', 'lstatSync', 'realpathSync', 'opendirSync']
  .map(k => [k, fs[k].bind(fs)]));
const DIR_READ = fs.Dir.prototype.readSync, DIR_CLOSE = fs.Dir.prototype.closeSync;
const MAX_DESCRIPTOR = 16384, MAX_SELECTION = 65536, MAX_SOURCE = 65536, MAX_TARGET = 16777216;
const MAX_FILE = 2097152, MAX_RECORD = 32768, MAX_SCRIPTS = 4096, RESERVE = 8192;
const sha = value => HASH('sha256').update(value).digest('hex');
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const frame = value => FIELDS.map(k => String(value[k]));
const identity = value => IDENT.map(k => String(value[k]));
const need = (ok, code) => { if (!ok) throw new Error(code); };
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const exact = (value, keys, code) => need(object(value) && equal(Object.keys(value).sort(), [...keys].sort()), code);
const absolute = value => typeof value === 'string' && path.isAbsolute(value) && path.resolve(value) === value && !/[\0\r\n]/.test(value);
const refEqual = (a, b) => a && b && a.path === b.path && a.sha256 === b.sha256 && a.sizeBytes === b.sizeBytes;
let active = null;

function reference(value, maximum) {
  exact(value, ['path', 'sha256', 'sizeBytes'], 'SOURCE_GATE_REFERENCE');
  need(absolute(value.path) && /^[a-f0-9]{64}$/.test(value.sha256) && Number.isSafeInteger(value.sizeBytes)
    && value.sizeBytes > 0 && value.sizeBytes <= maximum, 'SOURCE_GATE_REFERENCE');
  return value;
}
function check(end) { need(Number.isSafeInteger(end) && NOW() < end, 'SOURCE_GATE_OBSERVER_DEADLINE'); }
function namespace(file, end, io = IO) {
  check(end); need(absolute(file) && io.realpathSync(file) === file, 'SOURCE_GATE_NAMESPACE');
  const rows = [];
  for (let p = path.dirname(file); ; p = path.dirname(p)) {
    check(end); need(rows.length < 128, 'SOURCE_GATE_NAMESPACE_BOUND');
    const s = io.lstatSync(p, { bigint: true });
    need(s.isDirectory() && !s.isSymbolicLink(), 'SOURCE_GATE_NAMESPACE');
    rows.push([p, ...identity(s)]);
    if (p === path.dirname(p)) return rows;
  }
}
function retainedJson(raw, maximum) {
  need(Buffer.isBuffer(raw) && raw.length > 0 && raw.length <= maximum, 'SOURCE_GATE_JSON_EXTENT');
  const text = new TextDecoder('utf-8', { fatal: true }).decode(raw), value = JSON.parse(text);
  // The producer uses this canonical encoding; duplicate keys/alternate extents
  // cannot acquire authority from JSON.parse's last-value behavior.
  need(Buffer.from(JSON.stringify(value) + '\n').equals(raw), 'SOURCE_GATE_CANONICAL_JSON');
  return value;
}
function readHeldDigest(file, digest, maximum, end, privateFile = false, expectedExtent = null) {
  need(absolute(file) && /^[a-f0-9]{64}$/.test(digest), 'SOURCE_GATE_REFERENCE'); let fd, bytes;
  try {
    check(end); fd = IO.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
    const a = IO.fstatSync(fd, { bigint: true }), n = IO.lstatSync(file, { bigint: true });
    need(a.isFile() && n.isFile() && !n.isSymbolicLink() && a.uid === BigInt(UID) && a.nlink === 1n
      && a.size > 0n && a.size <= BigInt(maximum) && (expectedExtent === null || a.size === BigInt(expectedExtent))
      && (privateFile ? (a.mode & 0o7777n) === 0o600n : (a.mode & 0o022n) === 0n)
      && equal(frame(a), frame(n)), 'SOURCE_GATE_HELD_FILE');
    const before = namespace(file, end); bytes = Buffer.alloc(Number(a.size) + 1); let count = 0;
    while (count < bytes.length) {
      check(end); const nread = IO.readSync(fd, bytes, count, Math.min(65536, bytes.length - count), null);
      if (!nread) break; count += nread;
    }
    need(count === Number(a.size) && sha(bytes.subarray(0, count)) === digest
      && equal(frame(a), frame(IO.fstatSync(fd, { bigint: true })))
      && equal(frame(n), frame(IO.lstatSync(file, { bigint: true })))
      && equal(before, namespace(file, end)), 'SOURCE_GATE_HELD_CHANGED');
    return Buffer.from(bytes.subarray(0, count));
  } finally { bytes?.fill(0); if (fd !== undefined) IO.closeSync(fd); }
}
function held(ref, maximum, end) {
  reference(ref, maximum); return readHeldDigest(ref.path, ref.sha256, maximum, end, false, ref.sizeBytes);
}

/** Public selected-policy admission only; never claims another process's TLS default. */
export function reviewCapturedBasePolicy(environment, context) {
  const end = context.deadlineEpochMs, parent = context.parentPolicy, report = context.parentReport;
  need(report?.defaultEnumerationVerified === true && report.expectedDefaultCount === 144
    && parent?.role === 'base' && parent.fixtureCA === null, 'SOURCE_GATE_PARENT_BASE_REQUIRED');
  const tuple = ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256'];
  const actualTuple = Object.keys(environment).filter(key => /^(?:NODE_OPTIONS|SSL_CERT_FILE|SSL_CERT_DIR|CASEOPS_HOST_NODE_TRUST_POLICY_(?:FILE|SHA256))$/i.test(key));
  need(equal(actualTuple.sort(), [...tuple].sort()) && !Object.keys(environment).some(key => /^(?:(?:HTTP|HTTPS|ALL|NO)_PROXY|NODE_(?:EXTRA_CA_CERTS|USE_SYSTEM_CA|USE_ENV_PROXY|TLS_REJECT_UNAUTHORIZED)|OPENSSL_CONF(?:_INCLUDE)?)$/i.test(key)), 'SOURCE_GATE_CHILD_ENV_TUPLE');
  const keys = ['schemaVersion', 'kind', 'runtime', 'role', 'nodeVersion', 'inputCount', 'inputSetSha256', 'outputCount',
    'outputSetSha256', 'removedCount', 'deniedSha256', 'runtimeSource', 'bundle', 'emptyDirectory', 'fixtureCA'];
  let descriptorBytes, childBundle, parentBundle, helperBytes, bootstrapBytes;
  try {
    const file = environment.CASEOPS_HOST_NODE_TRUST_POLICY_FILE, digest = environment.CASEOPS_HOST_NODE_TRUST_POLICY_SHA256;
    descriptorBytes = readHeldDigest(file, digest, MAX_DESCRIPTOR, end, true);
    const descriptor = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(descriptorBytes)); exact(descriptor, keys, 'SOURCE_GATE_CHILD_POLICY_KEYS');
    need(Buffer.from(JSON.stringify(descriptor, null, 2) + '\n').equals(descriptorBytes), 'SOURCE_GATE_CHILD_POLICY_ENCODING');
    for (const key of keys.filter(key => !['runtimeSource', 'bundle', 'emptyDirectory'].includes(key)))
      need(equal(descriptor[key], parent[key]), 'SOURCE_GATE_CHILD_ROOT_FIELDS');
    need(descriptor.role === 'base' && descriptor.nodeVersion === '24.15.0' && descriptor.outputCount === 144
      && descriptor.fixtureCA === null, 'SOURCE_GATE_CHILD_BASE_REQUIRED');
    exact(descriptor.runtimeSource, ['helper', 'bootstrap'], 'SOURCE_GATE_CHILD_SOURCE');
    const h = descriptor.runtimeSource.helper, b = descriptor.runtimeSource.bootstrap;
    reference(h, MAX_SOURCE); reference(b, MAX_SOURCE);
    need(h.path === path.join(context.sourceRepo, 'scripts/mobile/host-node-trust.mjs')
      && h.sha256 === '13576eb5d2a4aed86b38f6dbae240ba290d08e653107c9ffeed060fa2e048787' && h.sizeBytes === 29498
      && b.path === path.join(context.sourceRepo, 'scripts/mobile/host-node-trust-start.mjs')
      && b.sha256 === sha(context.bootstrapBytes) && b.sizeBytes === context.bootstrapBytes.length, 'SOURCE_GATE_CHILD_SOURCE');
    helperBytes = held(h, MAX_SOURCE, end); bootstrapBytes = held(b, MAX_SOURCE, end);
    need(bootstrapBytes.equals(context.bootstrapBytes), 'SOURCE_GATE_CHILD_SOURCE');
    const directory = path.dirname(file), before = namespace(directory, end), stat = IO.lstatSync(directory, { bigint: true });
    need(path.basename(file) === 'policy.json' && stat.isDirectory() && !stat.isSymbolicLink() && stat.uid === BigInt(UID)
      && (stat.mode & 0o7777n) === 0o700n, 'SOURCE_GATE_CHILD_PRIVATE_POLICY');
    reference(descriptor.bundle, 1048576); reference(parent.bundle, 1048576);
    need(descriptor.bundle.path === path.join(directory, 'roots.pem') && descriptor.emptyDirectory === path.join(directory, 'empty')
      && environment.SSL_CERT_FILE === descriptor.bundle.path && environment.SSL_CERT_DIR === descriptor.emptyDirectory
      && environment.NODE_OPTIONS === '--use-openssl-ca --import=data:text/javascript;base64,' + bootstrapBytes.toString('base64'), 'SOURCE_GATE_CHILD_ENV_TUPLE');
    childBundle = held(descriptor.bundle, 1048576, end); parentBundle = held(parent.bundle, 1048576, end);
    need(childBundle.length === parentBundle.length && childBundle.equals(parentBundle), 'SOURCE_GATE_CHILD_BUNDLE');
    const empty = descriptor.emptyDirectory, emptyBefore = namespace(empty, end), emptyStat = IO.lstatSync(empty, { bigint: true });
    need(emptyStat.isDirectory() && !emptyStat.isSymbolicLink() && emptyStat.uid === BigInt(UID)
      && (emptyStat.mode & 0o7777n) === 0o700n, 'SOURCE_GATE_CHILD_EMPTY_DIRECTORY');
    const opened = IO.opendirSync(empty); try { check(end); need(DIR_READ.call(opened) === null, 'SOURCE_GATE_CHILD_EMPTY_DIRECTORY'); } finally { DIR_CLOSE.call(opened); }
    need(equal(frame(emptyStat), frame(IO.lstatSync(empty, { bigint: true }))) && equal(emptyBefore, namespace(empty, end))
      && equal(frame(stat), frame(IO.lstatSync(directory, { bigint: true }))) && equal(before, namespace(directory, end)), 'SOURCE_GATE_CHILD_POLICY_NAMESPACE');
    return { scopedPolicyVerified: true, expectedDefaultCount: 144, childEffectiveDefaultClaim: false,
      scope: 'selected-policy-admission-only; independent fixture-worker H activation/default proof required',
      policyRef: { path: file, sha256: digest, sizeBytes: descriptorBytes.length }, parentApprovedBundleSha256: sha(parentBundle) };
  } finally { for (const buffer of [descriptorBytes, childBundle, parentBundle, helperBytes, bootstrapBytes]) buffer?.fill(0); }
}

/** Real-FS sink unit seams are explicit JS arguments, never descriptor fields. */
export function createObserverSink(output, end, io = IO) {
  exact(output, ['path', 'identity'], 'SOURCE_GATE_OUTPUT_REFERENCE');
  need(Number.isInteger(UID) && absolute(output.path) && Array.isArray(output.identity) && output.identity.length === 5,
    'SOURCE_GATE_OUTPUT_REFERENCE');
  const dir = io.lstatSync(output.path, { bigint: true }), parents = namespace(output.path, end, io);
  need(dir.isDirectory() && !dir.isSymbolicLink() && dir.uid === BigInt(UID) && (dir.mode & 0o7777n) === 0o700n
    && equal(identity(dir), output.identity), 'SOURCE_GATE_PRIVATE_OUTPUT');
  const file = path.join(output.path, `compact-${process.pid}-${threadId}-${NOW()}-${RANDOM(4).toString('hex')}.jsonl`);
  let fd, expected, bytes = 0, readbackBytes = 0, ordinal = 0;
  try {
    fd = io.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK, 0o600);
    const value = io.fstatSync(fd, { bigint: true });
    need(value.isFile() && value.uid === BigInt(UID) && value.nlink === 1n && value.size === 0n
      && (value.mode & 0o7777n) === 0o600n && equal(frame(value), frame(io.lstatSync(file, { bigint: true }))), 'SOURCE_GATE_OUTPUT_FD');
    expected = frame(value);
  } catch (error) { if (fd !== undefined) io.closeSync(fd); throw error; }
  const binding = () => {
    check(end); need(fd !== undefined && equal(expected, frame(io.fstatSync(fd, { bigint: true })))
      && equal(expected, frame(io.lstatSync(file, { bigint: true })))
      && equal(identity(dir), identity(io.lstatSync(output.path, { bigint: true })))
      && equal(parents, namespace(output.path, end, io)) && io.realpathSync(file) === file, 'SOURCE_GATE_OUTPUT_CHANGED');
  };
  function rawWrite(raw) {
    let offset = 0;
    while (offset < raw.length) {
      check(end); const position = bytes, n = io.writeSync(fd, raw, offset, raw.length - offset, position);
      need(n > 0 && n <= raw.length - offset, 'SOURCE_GATE_WRITE_PROGRESS');
      // Preserve a successful prefix even when a later fragment/readback fails.
      bytes += n; expected = frame(io.fstatSync(fd, { bigint: true }));
      need(expected[6] === String(bytes), 'SOURCE_GATE_OUTPUT_EXTENT');
      const back = Buffer.alloc(n); let count = 0;
      while (count < n) {
        check(end); const v = io.readSync(fd, back, count, n - count, position + count);
        need(v > 0 && v <= n - count, 'SOURCE_GATE_READBACK_PROGRESS'); count += v; readbackBytes += v;
      }
      need(back.equals(raw.subarray(offset, offset + n)), 'SOURCE_GATE_READBACK'); binding(); offset += n;
    }
  }
  return {
    file,
    get bytes() { return bytes; }, get readbackBytes() { return readbackBytes; },
    emit(value) {
      binding(); const raw = Buffer.from(JSON.stringify({ ordinal, ...value }) + '\n');
      need(raw.length <= MAX_RECORD && bytes + raw.length <= MAX_FILE - RESERVE, 'SOURCE_GATE_RECORD_BOUND');
      rawWrite(raw); ordinal++;
    },
    fault(code) {
      // An earlier namespace/write failure remains a failure, even if this last
      // descriptor-only fixed diagnostic cannot be appended.
      const raw = Buffer.from(JSON.stringify({ ordinal, event: 'fault', code }) + '\n');
      if (bytes + raw.length <= MAX_FILE) rawWrite(raw);
    },
    close() { const opened = fd; fd = undefined; if (opened !== undefined) io.closeSync(opened); },
  };
}

const rich = reason => ({ mode: 'unchanged-detailed-fallback', reason, sessionAllowed: false });
export function selectCompactInvocation(actual, admitted) {
  need(admitted?.admissionComplete === true, 'SOURCE_GATE_SELECTION_NOT_ADMITTED');
  if (actual.isMainThread !== true) return rich('worker-thread');
  if (actual.nodeVersion !== admitted.primaryNode.version || actual.executable !== admitted.primaryNode.path) return rich('nonprimary-runtime');
  if (!Array.isArray(actual.execArgv) || actual.execArgv.some(flag => !admitted.startupFlags.includes(flag))) return rich('unreviewed-startup-argv');
  if (!Array.isArray(actual.argv) || actual.argv[0] !== admitted.primaryNode.path) return rich('unmatched-argv');
  if (actual.cwd === admitted.workerCwd && actual.testContext === 'child-v8' && actual.argv.length === 2) {
    const source = admitted.workerTargets.find(ref => ref.path === actual.argv[1]);
    if (source && refEqual(actual.entryReference, source)) return { mode: 'compact', reason: 'exact-declared-test-worker', sessionAllowed: true };
  }
  const expo = admitted.expoConfigTarget;
  if (expo && actual.cwd === expo.cwd && refEqual(actual.entryReference, expo.entry)
    && expo.argvSuffixes.some(suffix => equal(actual.argv, [admitted.primaryNode.path, expo.entry.path, ...suffix])))
    return { mode: 'compact', reason: 'exact-pinned-expo-config', sessionAllowed: true };
  return rich('unmatched-entry-cwd-source-or-argv');
}

/** Only canonical action forms are blocked; pure collection/plan stays fallback. */
export function nativeActionEntry(repo, argv) {
  if (!Array.isArray(argv) || typeof argv[1] !== 'string') return false;
  let entry;
  try { entry = path.relative(repo, IO.realpathSync(path.resolve(argv[1]))).split(path.sep).join('/'); }
  catch { return false; }
  const args = argv.slice(2);
  if (entry === 'scripts/mobile/run-native.mjs') return args.length === 1 && ['android', 'ios'].includes(args[0]);
  if (['scripts/mobile/run-ios-files.mjs', 'scripts/mobile/run-android-files.mjs'].includes(entry)) return args.length === 0;
  if (['scripts/mobile/run-v1-workflows.mjs', 'scripts/mobile/run-queue-privacy.mjs', 'scripts/mobile/run-client-extensions.mjs'].includes(entry)) return args[1] === '--request';
  return entry === 'scripts/mobile/run-store-packaging.mjs' && args[0] === '--execute';
}

function admitSelection(value, m, bootstrapBytes) {
  exact(value, ['schemaVersion', 'kind', 'workerCwd', 'workerTargets', 'expoConfigTarget', 'nestedDriver'], 'SOURCE_GATE_SELECTION');
  need(value.schemaVersion === 1 && value.kind === 'caseops-source-gate-selection' && absolute(value.workerCwd)
    && value.workerCwd === m.source.repo && Array.isArray(value.workerTargets)
    && value.workerTargets.length <= SOURCE_GATE_WORKER_PATHS.length, 'SOURCE_GATE_SELECTION');
  const paths = new Set();
  for (const ref of value.workerTargets) {
    reference(ref, MAX_TARGET);
    need(SOURCE_GATE_WORKER_PATHS.some(name => ref.path === path.join(m.source.repo, name)), 'SOURCE_GATE_UNREVIEWED_TARGET');
    need(!paths.has(ref.path), 'SOURCE_GATE_DUPLICATE_TARGET'); paths.add(ref.path);
  }
  if (value.expoConfigTarget !== null) {
    const expo = value.expoConfigTarget; exact(expo, ['entry', 'implementation', 'package', 'cwd', 'argvSuffixes'], 'SOURCE_GATE_EXPO_TARGET');
    for (const key of ['entry', 'implementation', 'package']) reference(expo[key], MAX_TARGET);
    need(expo.entry.path === path.join(m.source.repo, 'apps/mobile/node_modules/expo/bin/cli')
      && expo.cwd === path.join(m.source.repo, 'apps/mobile')
      && equal(expo.argvSuffixes, [['config', '--type', 'public', '--json'], ['config', '--type', 'introspect', '--json']]), 'SOURCE_GATE_EXACT_EXPO_ARGV');
  }
  if (value.nestedDriver !== null) {
    exact(value.nestedDriver, ['constructorSource', 'fixture', 'cwd'], 'SOURCE_GATE_NESTED_RULE');
    reference(value.nestedDriver.constructorSource, MAX_TARGET); reference(value.nestedDriver.fixture, MAX_TARGET);
    need(value.nestedDriver.constructorSource.path === path.join(m.source.repo, 'scripts/mobile/tooling.test.mjs')
      && value.nestedDriver.fixture.path === path.join(m.source.repo, 'scripts/mobile/host-node-trust-fixture.mjs')
      && value.nestedDriver.cwd === m.source.repo, 'SOURCE_GATE_EXACT_NESTED_RULE');
  }
  const bootstrap = 'data:text/javascript;base64,' + bootstrapBytes.toString('base64');
  return { ...value, admissionComplete: true, primaryNode: { ...m.primaryNode, version: '24.15.0' },
    startupFlags: ['--use-openssl-ca', '--import=' + bootstrap,
      '--inspect-port=127.0.0.1:9229', '--inspect-publish-uid=stderr,http',
      ...(m.phase === 'product45' ? ['--experimental-transform-types'] : [])] };
}

function publicOptions(options, cwd) {
  const primitive = {};
  for (const key of Object.keys(options).sort()) {
    if (['file', 'args', 'cwd', 'env', 'envPairs', 'stdio'].includes(key)) continue;
    const v = options[key];
    need(v === undefined || v === null || ['boolean', 'number', 'string'].includes(typeof v), 'SOURCE_GATE_SPAWN_OPTION_TYPE');
    if (v !== undefined) primitive[key] = v;
  }
  need(typeof options.file === 'string' && Array.isArray(options.args) && options.args.length <= 128
    && options.args.every(v => typeof v === 'string' && v.length <= 131072)
    && Array.isArray(options.envPairs) && options.envPairs.length <= 128
    && options.envPairs.every(v => typeof v === 'string' && !v.includes('\0') && v.length <= 32768), 'SOURCE_GATE_SPAWN_OPTIONS');
  const envBytes = options.envPairs.reduce((n, v) => n + Buffer.byteLength(v) + 1, 0);
  need(envBytes <= 262144 && Array.isArray(options.stdio) && options.stdio.length <= 16, 'SOURCE_GATE_SPAWN_OPTIONS');
  return { file: options.file, args: [...options.args], cwd: options.cwd ?? cwd, envPairs: [...options.envPairs],
    options: primitive, stdio: options.stdio.map(v => ({ type: v.type, ...(v.readable === undefined ? {} : { readable: v.readable }),
      ...(v.writable === undefined ? {} : { writable: v.writable }) })) };
}


/** Pure evidence review; runtime authority still comes only from the bound B callback. */
export function reviewNestedDriverEvidence(actual, m, selection, context) {
  const rule = selection.nestedDriver;
  need(rule && actual && Number.isSafeInteger(actual.pid) && actual.pid > 0
    && refEqual(actual.parentEntryReference, rule.constructorSource), 'SOURCE_GATE_NESTED_SOURCE_OR_PID');
  const start = actual.start;
  need(start && actual.end && equal(start, actual.end), 'SOURCE_GATE_NESTED_OPTIONS_CHANGED');
  need(start.file === m.primaryNode.path && start.cwd === rule.cwd
    && equal(start.args, [m.primaryNode.path, '--test', '--test-reporter=tap', rule.fixture.path])
    && equal(start.options, { detached: false, windowsHide: true, windowsVerbatimArguments: false })
    && equal(start.stdio, [{ type: 'ignore' }, { type: 'pipe', readable: false, writable: true },
      { type: 'pipe', readable: false, writable: true }]), 'SOURCE_GATE_NESTED_EXACT_CONSTRUCTOR');
  need(Array.isArray(start.envPairs) && start.envPairs.length <= 128, 'SOURCE_GATE_NESTED_ENV');
  const env = Object.fromEntries(start.envPairs.map(pair => {
    need(typeof pair === 'string' && pair.length <= 32768 && !pair.includes('\0'), 'SOURCE_GATE_NESTED_ENV');
    const at = pair.indexOf('='); need(at > 0, 'SOURCE_GATE_NESTED_ENV'); return [pair.slice(0, at), pair.slice(at + 1)];
  }));
  need(Object.keys(env).length === start.envPairs.length && env.CASEOPS_HOST_NODE_BOOTSTRAP_TEST === '1'
    && !Object.hasOwn(env, 'NODE_TEST_CONTEXT'), 'SOURCE_GATE_NESTED_ENV');
  const review = context.reviewNestedEnvironment(env, start.args.slice(1), context.bootstrapBytes);
  need(review && review.scopedPolicyVerified === true && review.childEffectiveDefaultClaim === false && review.expectedDefaultCount === 144, 'SOURCE_GATE_NESTED_TLS_ENV');
  const safeEnv = {};
  const keys = new Set([...Object.keys(context.initialEnvironment).filter(k => !['NODE_TEST_CONTEXT', ...context.nodeEnvironmentKeys].includes(k)),
    ...context.nodeEnvironmentKeys, 'CASEOPS_HOST_NODE_BOOTSTRAP_TEST']);
  for (const [key, value] of Object.entries(env)) {
    need(keys.has(key), 'SOURCE_GATE_NESTED_UNKNOWN_ENV');
    if (!context.nodeEnvironmentKeys.includes(key) && key !== 'CASEOPS_HOST_NODE_BOOTSTRAP_TEST')
      need(value === context.initialEnvironment[key], 'SOURCE_GATE_NESTED_ENV_CHANGED');
    safeEnv[key] = key === 'NODE_OPTIONS' ? { exactHeldBootstrap: context.bootstrapReference, prefix: '--use-openssl-ca --import=' } : value;
  }
  for (const key of keys) need(Object.hasOwn(env, key), 'SOURCE_GATE_NESTED_ENV_MISSING');
  return { role: 'source-audited-nested-intrinsic-driver', scriptCompleteClaim: false,
    workerWitnessRequired: true, argv: start.args, cwd: start.cwd,
    normalizedOptions: start.options, stdio: start.stdio, environment: safeEnv,
    optionsSnapshotsEqual: true, fixture: ruleRef(selection), reviewedSelectedPolicy: review, childEffectiveDefaultClaim: false };
}

function installConstructors(emit, m, selection, context) {
  const seen = new WeakMap(); let ordinal = 0;
  const channel = dc.tracingChannel('child_process.spawn');
  channel.subscribe({
    start({ process: child, options }) {
      const row = { id: ++ordinal, options, start: null, end: null, candidate: false };
      seen.set(child, row); emit({ event: 'child-attempt', constructorId: row.id, constructorKind: 'async-spawn' });
      try {
        // Never retain arbitrary child arguments/environments. Only the single
        // reviewed nested supervisor form may acquire a public projection.
        const rule = selection.nestedDriver;
        if (rule && refEqual(context.parentEntryReference, rule.constructorSource) && options.file === m.primaryNode.path
          && equal(options.args, [m.primaryNode.path, '--test', '--test-reporter=tap', rule.fixture.path])) {
          row.candidate = true; row.start = publicOptions(options, process.cwd());
        }
      } catch { row.refusal = 'SOURCE_GATE_NESTED_OPTIONS_REFUSED'; }
      child.once('spawn', () => {
        const base = { event: 'child-spawned', constructorId: row.id, pid: child.pid,
          nodeExecutable: [m.primaryNode.path, ...m.knownFallbackNodes.map(r => r.path)].includes(child.spawnfile) };
        if (!row.candidate) { emit(base); return; }
        try {
          need(!row.refusal, 'SOURCE_GATE_NESTED_OPTIONS_REFUSED');
          const nestedDriver = reviewNestedDriverEvidence({ start: row.start, end: row.end, pid: child.pid,
            parentEntryReference: context.parentEntryReference }, m, selection, context);
          emit({ ...base, nestedDriver });
        } catch (error) { emit({ ...base, nestedDriverRefused: /^SOURCE_GATE_[A-Z_]+$/.test(error?.message || '') ? error.message : 'SOURCE_GATE_NESTED_REVIEW_REFUSED' }); }
      });
      child.once('exit', (code, signal) => emit({ event: 'child-exit', constructorId: row.id, pid: child.pid, code, signal }));
    },
    end({ process: child }) { const row = seen.get(child); if (row?.candidate) try { row.end = publicOptions(row.options, process.cwd()); } catch { row.refusal = 'SOURCE_GATE_NESTED_OPTIONS_REFUSED'; } },
  });
  dc.subscribe('worker_threads', ({ worker }) => {
    const id = ++ordinal; emit({ event: 'worker-created', constructorId: id });
    worker.once('online', () => emit({ event: 'worker-online', constructorId: id, threadId: worker.threadId }));
    worker.once('exit', code => emit({ event: 'worker-exit', constructorId: id, code }));
  });
}
const ruleRef = selection => ({ constructorSource: selection.nestedDriver.constructorSource, fixture: selection.nestedDriver.fixture });

export function sourceGateObserverStatus() { return active ? { ...active.status } : { mode: 'not-activated' }; }

/** Called only by the small fixed-hash B loader after current TLS admission. */
export function observeSourceGate(environment, manifestReference, manifestBytes, recorderBytes, helper, policy, read, canonical) {
  const context = { environment, manifestReference, manifestBytes, recorderBytes, helper, policy, read, canonical };
  const env = context.environment, keys = Object.values(SOURCE_GATE_OBSERVER_ENV);
  const present = Object.keys(env).filter(key => /^CASEOPS_SOURCE_GATE_OBSERVER_/i.test(key));
  need(present.length === 2 && keys.every(key => present.includes(key))
    && Number.isInteger(UID) && ['darwin', 'linux'].includes(PLATFORM), 'SOURCE_GATE_OBSERVER_REFUSED');
  need(Buffer.isBuffer(context.manifestBytes) && Buffer.isBuffer(context.recorderBytes)
    && context.manifestReference.path === env[keys[0]] && context.manifestReference.sha256 === env[keys[1]]
    && sha(context.manifestBytes) === env[keys[1]], 'SOURCE_GATE_OBSERVER_REFUSED');
  const m = retainedJson(context.manifestBytes, MAX_DESCRIPTOR);
  need(m.schemaVersion === 1 && m.kind === 'caseops-source-gate-observer' && m.role === 'source-gate-only'
    && m.source && absolute(m.source.repo), 'SOURCE_GATE_OBSERVER_REFUSED');
  need(!nativeActionEntry(m.source.repo, process.argv), 'SOURCE_GATE_OBSERVER_NATIVE_REFUSED');
  const directory = path.dirname(env[keys[0]]), stat = IO.lstatSync(directory, { bigint: true });
  need(context.canonical(directory) === directory && stat.isDirectory() && !stat.isSymbolicLink()
    && stat.uid === BigInt(UID) && (stat.mode & 0o7777n) === 0o700n, 'SOURCE_GATE_OBSERVER_REFUSED');
  reference(m.selection, MAX_SELECTION);
  need(m.selection.path === path.join(directory, 'selection.json'), 'SOURCE_GATE_OBSERVER_REFUSED');
  let selection, bootstrap;
  try {
    // The existing B reader keeps its original20s startup deadline, owner,
    // descriptor and canonical namespace contract. No pathname code import.
    selection = context.read(m.selection.path, m.selection.sha256, MAX_SELECTION, true);
    need(selection.length === m.selection.sizeBytes, 'SOURCE_GATE_OBSERVER_REFUSED');
    const ref = context.policy.runtimeSource.bootstrap; reference(ref, 16384);
    bootstrap = context.read(ref.path, ref.sha256, 16384);
    need(bootstrap.length === ref.sizeBytes, 'SOURCE_GATE_OBSERVER_REFUSED');
    return activateSourceGateObserver({ manifestReference: context.manifestReference, manifestBytes: context.manifestBytes,
      recorderBytes: context.recorderBytes, selectionBytes: selection, bootstrapBytes: bootstrap, bootstrapReference: ref,
      reviewNestedEnvironment(environment, _argv, heldBootstrap) {
        const parentPolicyRef = { path: process.env.CASEOPS_HOST_NODE_TRUST_POLICY_FILE, sha256: process.env.CASEOPS_HOST_NODE_TRUST_POLICY_SHA256 };
        const parentReport = context.helper.assertHostNodeTrust({ policyRef: parentPolicyRef, role: 'base' });
        return reviewCapturedBasePolicy(environment, { parentReport, parentPolicy: context.policy, sourceRepo: m.source.repo,
          bootstrapBytes: heldBootstrap, deadlineEpochMs: m.deadlineEpochMs });
      } });
  } finally { selection?.fill(0); bootstrap?.fill(0); }
}

export function activateSourceGateObserver(context) {
  need(context && Buffer.isBuffer(context.manifestBytes) && Buffer.isBuffer(context.selectionBytes)
    && Buffer.isBuffer(context.recorderBytes) && Buffer.isBuffer(context.bootstrapBytes), 'SOURCE_GATE_HELD_ACTIVATION');
  reference(context.manifestReference, MAX_DESCRIPTOR);
  need(sha(context.manifestBytes) === context.manifestReference.sha256
    && context.manifestBytes.length === context.manifestReference.sizeBytes, 'SOURCE_GATE_DESCRIPTOR_CHANGED');
  if (active) { need(active.manifestSha256 === context.manifestReference.sha256, 'SOURCE_GATE_SECOND_ACTIVATION'); return sourceGateObserverStatus(); }
  const m = retainedJson(context.manifestBytes, MAX_DESCRIPTOR);
  exact(m, ['schemaVersion', 'kind', 'role', 'runId', 'source', 'phase', 'primaryNode', 'knownFallbackNodes', 'recorder', 'selection', 'output', 'deadlineEpochMs'], 'SOURCE_GATE_DESCRIPTOR_KEYS');
  need(m.schemaVersion === 1 && m.kind === 'caseops-source-gate-observer' && m.role === 'source-gate-only'
    && /^[a-f0-9]{32}$/.test(m.runId) && ['registration', 'node33', 'product45', 'compiler-before', 'typecheck', 'compiler-after'].includes(m.phase), 'SOURCE_GATE_DESCRIPTOR');
  exact(m.source, ['repo', 'sha', 'tree'], 'SOURCE_GATE_SOURCE');
  need(absolute(m.source.repo) && /^[a-f0-9]{40}$/.test(m.source.sha) && /^[a-f0-9]{40}$/.test(m.source.tree), 'SOURCE_GATE_SOURCE');
  reference(m.primaryNode, 134217728); need(Array.isArray(m.knownFallbackNodes) && m.knownFallbackNodes.length <= 1, 'SOURCE_GATE_RUNTIMES');
  for (const ref of m.knownFallbackNodes) reference(ref, 134217728);
  reference(m.recorder, MAX_SOURCE); reference(m.selection, MAX_SELECTION);
  need(m.recorder.path === path.join(m.source.repo, 'scripts/mobile/source-gate-observer.mjs')
    && m.recorder.sizeBytes === context.recorderBytes.length && m.recorder.sha256 === sha(context.recorderBytes)
    && import.meta.url === 'data:text/javascript;base64,' + context.recorderBytes.toString('base64'), 'SOURCE_GATE_HELD_RECORDER');
  need(m.selection.sizeBytes === context.selectionBytes.length && m.selection.sha256 === sha(context.selectionBytes), 'SOURCE_GATE_SELECTION_CHANGED');
  need(Number.isInteger(UID) && ['darwin', 'linux'].includes(PLATFORM), 'SOURCE_GATE_PLATFORM_UNPROVED');
  need(Number.isSafeInteger(m.deadlineEpochMs) && m.deadlineEpochMs <= NOW() + 300000, 'SOURCE_GATE_OBSERVER_DEADLINE'); check(m.deadlineEpochMs);
  need(!nativeActionEntry(m.source.repo, process.argv), 'SOURCE_GATE_OBSERVER_NATIVE_REFUSED');
  exact(m.output, ['path', 'identity'], 'SOURCE_GATE_OUTPUT_REFERENCE');
  need(absolute(m.output.path) && Array.isArray(m.output.identity) && m.output.identity.length === 5, 'SOURCE_GATE_OUTPUT_REFERENCE');
  const outputStat = IO.lstatSync(m.output.path, { bigint: true });
  need(outputStat.isDirectory() && !outputStat.isSymbolicLink() && outputStat.uid === BigInt(UID)
    && (outputStat.mode & 0o7777n) === 0o700n && equal(identity(outputStat), m.output.identity), 'SOURCE_GATE_PRIVATE_OUTPUT');
  namespace(m.output.path, m.deadlineEpochMs);
  const selection = admitSelection(retainedJson(context.selectionBytes, MAX_SELECTION), m, context.bootstrapBytes);
  const candidate = selection.workerTargets.find(ref => ref.path === process.argv[1])
    ?? (selection.expoConfigTarget && selection.expoConfigTarget.entry.path === process.argv[1] ? selection.expoConfigTarget.entry : null);
  let entryReference = null;
  if (candidate && isMainThread && process.versions.node === '24.15.0') { const raw = held(candidate, MAX_TARGET, m.deadlineEpochMs); raw.fill(0); entryReference = candidate; }
  const result = selectCompactInvocation({ isMainThread, nodeVersion: process.versions.node, executable: process.execPath,
    execArgv: process.execArgv, argv: process.argv, cwd: process.cwd(), testContext: process.env.NODE_TEST_CONTEXT, entryReference }, selection);
  active = { manifestSha256: context.manifestReference.sha256, status: result };
  if (!result.sessionAllowed) return sourceGateObserverStatus();
  need(inspector.url() === undefined, 'SOURCE_GATE_INSPECT_LISTENER_REFUSED');
  const sink = createObserverSink(m.output, m.deadlineEpochMs); let scripts = 0, live = false, stopped = false, exitSeen = false, faulted = false;
  const ids = new Set();
  const fatal = error => {
    if (faulted) return; faulted = true;
    const code = /^SOURCE_GATE_[A-Z_]+$/.test(error?.message || '') ? error.message : 'SOURCE_GATE_OBSERVER_FAILED';
    try { sink.fault(code); } catch { /* Original failure remains nonzero. */ }
    try { sink.close(); } catch { /* Process exit closes remaining descriptors. */ } EXIT(86);
  };
  const emit = value => { if (!faulted) try { sink.emit(value); } catch (error) { fatal(error); } };
  emit({ event: 'header', schemaVersion: 1, runId: m.runId, phase: m.phase, role: m.role,
    source: m.source, manifestSha256: context.manifestReference.sha256, recorderSha256: m.recorder.sha256,
    pid: process.pid, ppid: process.ppid, threadId, isMainThread, nodeVersion: process.versions.node, v8Version: process.versions.v8,
    selection: result.reason, argumentCount: process.argv.length, startupArgumentCount: process.execArgv.length,
    startHrtime: HR().toString(), workerPolicy: 'unchanged-detailed-fallback-no-Worker-session',
    limits: { fileBytes: MAX_FILE, scripts: MAX_SCRIPTS, recordBytes: MAX_RECORD },
    outputFdLifetime: 'owning process lifetime; final group closure remains an external obligation' });
  const session = new inspector.Session();
  try { session.connect(); } catch { fatal(new Error('SOURCE_GATE_INSPECTOR_UNAVAILABLE')); }
  const location = url => {
    need(typeof url === 'string' && Buffer.byteLength(url) <= 1048576, 'SOURCE_GATE_URL_BOUND');
    if (url.startsWith('data:')) return { urlKind: 'data', urlSha256: sha(url) };
    if (url === '') return { urlKind: 'anonymous', urlSha256: sha('') };
    need(Buffer.byteLength(url) <= 8192, 'SOURCE_GATE_URL_BOUND'); return { urlKind: 'literal', url };
  };
  const script = (event, message) => {
    try {
      const p = message.params;
      need(p && typeof p.scriptId === 'string' && /^\d{1,12}$/.test(p.scriptId) && /^[a-f0-9]{64}$/.test(p.hash)
        && Number.isSafeInteger(p.length) && p.length >= 0 && p.length <= MAX_TARGET, 'SOURCE_GATE_SCRIPT_SHAPE');
      need(++scripts <= MAX_SCRIPTS && !ids.has(event + ':' + p.scriptId), 'SOURCE_GATE_SCRIPT_BOUND'); ids.add(event + ':' + p.scriptId);
      emit({ event, scriptId: p.scriptId, executionContextId: p.executionContextId, engineSha256: p.hash,
        codeUnits: p.length, isModule: p.isModule === true, language: p.scriptLanguage, ...location(p.url), afterExitMarker: exitSeen });
    } catch (error) { fatal(error); }
  };
  session.on('Debugger.scriptParsed', value => script('script', value));
  session.on('Debugger.scriptFailedToParse', value => script('parse-attempt-failed', value));
  let enabled = false;
  try { session.post('Debugger.enable', {}, error => { if (error) fatal(new Error('SOURCE_GATE_DEBUGGER_ENABLE')); enabled = true; }); }
  catch { fatal(new Error('SOURCE_GATE_DEBUGGER_ENABLE')); }
  if (!enabled) fatal(new Error('SOURCE_GATE_SYNC_ENABLE'));
  let skip = false;
  try { session.post('Debugger.setSkipAllPauses', { skip: true }, error => { if (error) fatal(new Error('SOURCE_GATE_SKIP_PAUSES')); skip = true; }); }
  catch { fatal(new Error('SOURCE_GATE_SKIP_PAUSES')); }
  if (!skip) fatal(new Error('SOURCE_GATE_SYNC_PAUSES')); live = true;
  emit({ event: 'live', replayedScripts: scripts, inspectorListening: inspector.url() !== undefined });
  try { installConstructors(emit, m, selection, { ...context, bootstrapBytes: Buffer.from(context.bootstrapBytes), parentEntryReference: entryReference, initialEnvironment: { ...process.env },
    nodeEnvironmentKeys: ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256'] }); }
  catch { fatal(new Error('SOURCE_GATE_CONSTRUCTOR_OBSERVER')); }
  ON('exit', code => {
    exitSeen = true; emit({ event: 'exit-marker', code, live, stopped, scriptsBeforeMarker: scripts,
      retainedBytesBeforeMarker: sink.bytes, readbackBytesBeforeMarker: sink.readbackBytes });
    // Keep Session/FD for later exit-listener code. No Worker Session is used.
  });
  try { stopCoverage(); stopped = true; } catch { fatal(new Error('SOURCE_GATE_STOP_COVERAGE')); }
  emit({ event: 'detailed-coverage-stopped', live, diagnosticPolicy: 'native139-byte exit diagnostic remains unfiltered' });
  active.status = { ...result, pid: process.pid, threadId, output: sink.file, scriptCompleteClaim: true };
  return sourceGateObserverStatus();
}
