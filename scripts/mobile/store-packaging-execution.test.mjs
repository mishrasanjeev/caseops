import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { executeStorePackaging, pendingStoreExecution, admitTools, GATES } from './store-packaging-execution.mjs';
import { digest, gitSource } from './store-packaging-inputs.mjs';

const repo = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
function fixture(t) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-store-execution-')));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const root = path.join(base, 'source'), outputs = path.join(base, 'outputs'), reservations = path.join(base, 'reservations');
  for (const p of [root, outputs, reservations]) fs.mkdirSync(p, { mode: 0o700 });
  const save = (name, value) => { const file = path.join(base, name), bytes = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
    fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 }); return { path: file, sha256: digest(bytes) }; };
  const source = { sourceSha: '1'.repeat(40), tree: '2'.repeat(40), fullSourceFingerprint: digest('full source'), files: [] };
  const sourceContract = { sourceSha: source.sourceSha, sourceFingerprint: digest('mobile source'), inputFileCount: 100 };
  const config = { schemaVersion: 1, kind: 'caseops-native-links', syntheticDataOnly: true, redirectUri: 'https://auth.contract-fixture.org/native/oauth/callback',
    ios: { bundleIdentifier: 'org.contract.storeapp', applicationIdentifierPrefix: 'PREF123456' },
    android: { packageName: 'org.contract.storeapp', signingCertificateSha256: [digest('app-signing')] } };
  const nativeLinks = save('links.json', config), identities = { iosBundleIdentifier: config.ios.bundleIdentifier, androidPackageName: config.android.packageName };
  const privacyPolicy = save('privacy-policy.json', { schemaVersion: 1, kind: 'caseops-mobile-privacy-policy', nativeLinkConfigSha256: nativeLinks.sha256,
    url: 'https://auth.contract-fixture.org/app-privacy', version: 'synthetic-contract-only' });
  const syntheticPasswords = save('synthetic-passwords.json', { storePassword: 'synthetic-only', keyPassword: 'synthetic-only' });
  const baseline = save('baseline.json', { schemaVersion: 1, kind: 'caseops-declared-store-build-baseline', syntheticDataOnly: true, identities,
    marketingVersion: '0.9.0', iosBuildNumber: '0', androidVersionCode: 0, scope: 'operator-declared-not-store-verified' });
  const storeBuild = save('build.json', { schemaVersion: 1, kind: 'caseops-store-build', syntheticDataOnly: true, nativeLinkConfigSha256: nativeLinks.sha256,
    identities, version: '1.0.0', iosBuildNumber: '1', androidVersionCode: 1, baseline });
  const gateValue = { schemaVersion: 1, kind: 'caseops-reviewed-store-gates', sourceSha: source.sourceSha, tree: source.tree,
    sourceFingerprint: sourceContract.sourceFingerprint, inputFileCount: 100, reviewedAt: new Date().toISOString(), reservationDirectory: reservations,
    inputBindings: null, results: Object.fromEntries(GATES.map(name => [name, 'passed'])), evidence: GATES.map((name, i) => save('evidence-' + i + '.json', { kind: 'SYNTHETIC_GATE_ONLY', name })) };
  const gates = save('gates.json', gateValue), historyValue = { kind: 'caseops-reviewed-actual-store-history', identities, observedAt: new Date().toISOString(),
    iosBuildNumber: '0', androidVersionCode: 0, evidence: [save('history-evidence.json', { synthetic: true })] };
  const history = save('history.json', historyValue);
  const names = ['node', 'python', 'git', 'pod', 'xcodebuild', 'codesign', 'security', 'xcrun', 'java', 'keytool', 'jarsigner', 'bundletool'];
  const allTools = Object.fromEntries(names.map(name => { const ref = save(name + '-tool', 'SYNTHETIC_TOOL'); fs.chmodSync(ref.path, 0o700);
    return [name, { ...ref, sizeBytes: 14, version: name === 'node' ? '24.15.0' : name === 'python' ? '3.13.17' : 'fixture-pinned', ownerUid: process.getuid?.() || 0 }]; }));
  const runtimeRef = save('runtime-public.txt', 'PUBLIC_RUNTIME');
  const generatedValue = platform => (platform === 'ios' ? [['Podfile', 'PUBLIC SYNTHETIC PODFILE']]
    : [['gradlew', '#!/bin/sh\n'], ['gradle/wrapper/gradle-wrapper.jar', 'PUBLIC WRAPPER JAR'], ['gradle/wrapper/gradle-wrapper.properties', 'distributionUrl=synthetic-offline\n']])
    .map(([name, body]) => ({ path: name, sha256: digest(body), sizeBytes: Buffer.byteLength(body) }));
  const toolsValue = platform => ({ schemaVersion: 1, kind: 'caseops-local-store-tools', hostPlatform: 'darwin',
    entries: Object.fromEntries((platform === 'ios' ? names.slice(0, 8) : ['node', 'python', 'git', 'java', 'keytool', 'jarsigner', 'bundletool']).map(n => [n, allTools[n]])),
    runtimeInputs: [{ ...runtimeRef, sizeBytes: 14 }], generatedInputs: generatedValue(platform) });
  for (const name of ['BUILD_TOOL_NOTICES.txt', 'CAMERA_NOTICES.txt', 'src/viewer/generated/LICENSES.txt']) {
    const p = path.join(root, 'apps/mobile', name); fs.mkdirSync(path.dirname(p), { recursive: true, mode: 0o700 }); fs.writeFileSync(p, 'PUBLIC SYNTHETIC NOTICE');
  }
  for (const name of ['store-packaging-host.py', 'store_process_owner.py', 'StoreJarVerifier.java']) {
    const p = path.join(root, 'scripts/mobile', name); fs.mkdirSync(path.dirname(p), { recursive: true, mode: 0o700 });
    const bytes = fs.readFileSync(path.join(repo, 'scripts/mobile', name)); fs.writeFileSync(p, bytes, { mode: 0o600 });
    source.files.push({ path: 'scripts/mobile/' + name, sha256: digest(bytes) });
  }
  let sequence = 0, signingReads = 0, sourceReads = 0; const calls = [];
  const make = (platform = 'ios') => {
    const n = ++sequence, s = platform === 'ios'
      ? { teamId: 'TEAM123456', applicationIdentifierPrefix: 'PREF123456', certificateSha1: 'a'.repeat(40), certificateSha256: 'b'.repeat(64),
        provisioningProfileUuid: '019b85b0-50bd-4c77-aa22-3da2e5009fe1', provisioningProfileEvidence: { path: path.join(base, 'NEVER_READ_PROFILE'), sha256: digest('absent') },
        developerDirectory: '/Applications/Synthetic-Xcode.app/Contents/Developer', podfileLockEvidence: save('pod-lock-' + n, 'PUBLIC SYNTHETIC LOCK') }
      : { uploadKeystoreEvidence: { path: path.join(base, 'NEVER_READ_KEYSTORE'), sha256: digest('absent') }, uploadKeyAlias: 'synthetic-upload',
        uploadCertificateSha256: digest('upload'), appSigningCertificateSha256: config.android.signingCertificateSha256[0],
        androidSdkRoot: '/synthetic/sdk', javaHome: '/synthetic/java21', java17Home: '/synthetic/java17', gradleUserHome: '/synthetic/gradle' };
    const recipe = { schemaVersion: 1, kind: 'caseops-store-packaging-request', preparedOnly: true, syntheticDataOnly: true, platform,
      source: sourceContract, nativeLinks, storeBuild, apiOrigin: 'https://api.contract-fixture.org', webOrigin: 'https://auth.contract-fixture.org', signing: s };
    const toolsRef = save('tools-' + n + '.json', toolsValue(platform));
    gateValue.inputBindings = { toolsSha256: toolsRef.sha256, nativeLinkConfigSha256: nativeLinks.sha256, storeBuildSha256: storeBuild.sha256,
      privacyPolicySha256: privacyPolicy.sha256, signingPublicInputs: s, architecture: pendingStoreExecution(platform).architecture };
    const boundGates = save('bound-gates-' + n + '.json', structuredClone(gateValue));
    const q = { ...pendingStoreExecution(platform), readyForLocalBuild: true, syntheticDataOnly: true, recipe: save('recipe-' + n + '.json', recipe),
      sourceTree: source.tree, gates: boundGates, tools: toolsRef, storeHistory: history,
      reservationDirectory: reservations, outputDirectory: path.join(outputs, 'attempt-' + n), signingSecrets: platform === 'android' ? syntheticPasswords : null, privacyPolicy };
    return { q, recipe, ref: () => save('execute-' + sequence + '-' + Math.random().toString(16).slice(2) + '.json', q) };
  };
  const answer = (status = 0, stderr = '') => ({ exitCode: status, timedOut: false, outputExceeded: false, failureClass: null,
    streamCleanupComplete: true, cleanup: { complete: true, signals: [] }, stdout: { bytes: 0, sha256: digest(''), base64: '' },
    stderr: { bytes: Buffer.byteLength(stderr), sha256: digest(stderr), base64: Buffer.from(stderr).toString('base64') } });
  const adapter = {
    privacyPolicy: (value, sha256) => ({ url: value.url, version: value.version, sha256 }),
    source: () => { sourceReads++; return structuredClone(source); },
    signingAdmission: async () => { signingReads++; },
    command: async command => {
      calls.push(command);
      if (command.args.includes('prebuild')) {
        const dir = path.join(root, 'apps/mobile', command.args[command.args.indexOf('--platform') + 1]); fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
        const entries = dir.endsWith('android') ? [['gradlew', '#!/bin/sh\n'], ['gradle/wrapper/gradle-wrapper.jar', 'PUBLIC WRAPPER JAR'],
          ['gradle/wrapper/gradle-wrapper.properties', 'distributionUrl=synthetic-offline\n']] : [['Podfile', 'PUBLIC SYNTHETIC PODFILE']];
        for (const [name, body] of entries) { const file = path.join(dir, name); fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 }); fs.writeFileSync(file, body, { mode: 0o700 }); }
      }
      if (command.role === 'embed') {
        const bytes = fs.readFileSync(command.args[command.args.length - 2]); const result = answer();
        const text = JSON.stringify({ embedded: true, sha256: digest(bytes) }); result.stdout = { bytes: Buffer.byteLength(text), sha256: digest(text), base64: Buffer.from(text).toString('base64') }; return result;
      }
      if (command.args.includes('-exportArchive')) { const exportDir = path.join(command.cwd, '../..'); void exportDir;
        const directory = command.args[command.args.indexOf('-exportPath') + 1]; fs.mkdirSync(directory, { recursive: true, mode: 0o700 }); fs.writeFileSync(path.join(directory, 'CaseOps.ipa'), 'SYNTHETIC_COMPILER_OUTPUT'); }
      if (command.args[0] === ':app:bundleRelease') { const directory = path.join(command.cwd, 'app/build/outputs/bundle/release'); fs.mkdirSync(directory, { recursive: true, mode: 0o700 }); fs.writeFileSync(path.join(directory, 'app-release.aab'), 'SYNTHETIC_COMPILER_OUTPUT'); }
      return answer(0, 'SYNTHETIC_SUCCESS_ON_STDERR');
    },
    postflight: async () => ({ distributionSigningVerified: true, syntheticObservation: true }),
  };
  return { base, root, save, make, adapter, answer, calls, reservations, source, gateValue, historyValue, allTools,
    reads: () => ({ signingReads, sourceReads }) };
}
test('new CLI defaults to unarmed preparation and unknown modes never read a supplied input', () => {
  const normal = spawnSync(process.execPath, ['scripts/mobile/run-store-packaging.mjs'], { cwd: repo, encoding: 'utf8', timeout: 5000 });
  assert.equal(normal.status, 0); assert.equal(JSON.parse(normal.stdout).executionEnabled, false);
  const invalid = spawnSync(process.execPath, ['scripts/mobile/run-store-packaging.mjs', '--run', 'SYNTHETIC_PRIVATE_MARKER'], { cwd: repo, encoding: 'utf8', timeout: 5000 });
  assert.equal(invalid.status, 1); assert.equal(invalid.stdout, ''); assert.equal(invalid.stderr.trim(), 'STORE_LOCAL_PACKAGING_REFUSED');
});
test('complete synthetic iOS command graph is contractOnly and cannot certify distribution signing', async t => {
  const f = fixture(t), a = f.make(); const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.observed, true, JSON.stringify(result.originalFailure)); assert.equal(result.contractOnly, true); assert.equal(result.distributionSigningVerified, false);
  assert.equal(result.storeAcceptance, false); assert.equal(result.uploaded, false); assert.deepEqual(result.phases.map(p => p.status), ['passed', 'passed', 'passed', 'passed', 'passed']);
  assert.deepEqual(f.reads(), { signingReads: 1, sourceReads: 2 }); assert.equal(f.calls.length, 6);
});
test('the same approved build batch serves both platforms but each platform can dispatch only once', async t => {
  const f = fixture(t), a = f.make('ios'); const first = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }); assert.equal(first.observed, true);
  const b = f.make('android'); const second = await executeStorePackaging(b.ref(), { root: f.root, adapter: f.adapter }); assert.equal(second.observed, true, JSON.stringify(second.originalFailure));
  assert.equal(fs.readdirSync(f.reservations).length, 5);
  // A fresh public native projection can never reset the retained number/claim
  // ledger. Only this synthetic generated project is removed to reach that fence.
  fs.rmSync(path.join(f.root, 'apps/mobile/ios'), { recursive: true });
  const c = f.make('ios'), before = f.calls.length, readBefore = f.reads().signingReads;
  const replay = await executeStorePackaging(c.ref(), { root: f.root, adapter: f.adapter }); assert.equal(replay.observed, false);
  assert.equal(f.calls.length, before); assert.equal(f.reads().signingReads, readBefore); assert.equal(replay.phases[0].status, 'failed');
});
test('a failed required gate refuses before reservation output or signing reads', async t => {
  const f = fixture(t), a = f.make(); a.q.gates = f.save('failed-gates.json', { ...f.gateValue, results: { ...f.gateValue.results, codeqlAlertVerdict: 'failed' } });
  await assert.rejects(executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }), /STORE_REQUIRED_GATE_FAILED/);
  assert.equal(f.reads().signingReads, 0); assert.equal(f.calls.length, 0); assert.deepEqual(fs.readdirSync(f.reservations), []); assert.equal(fs.existsSync(a.q.outputDirectory), false);
});
test('missing or duplicate authority fields and pending requests fail closed before private admission', async t => {
  const f = fixture(t), a = f.make(); delete a.q.gates;
  await assert.rejects(executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }), /STORE_EXECUTION_REQUEST_REQUIRED/);
  const pending = f.save('pending.json', pendingStoreExecution('ios'));
  await assert.rejects(executeStorePackaging(pending, { root: f.root, adapter: f.adapter }), /STORE_COMPLETE_REAL_REQUEST_REQUIRED/); assert.equal(f.reads().signingReads, 0);
});
test('source tree mismatch and stale source gate evidence cannot cross the signing boundary', async t => {
  const f = fixture(t), a = f.make(); a.q.sourceTree = '3'.repeat(40);
  await assert.rejects(executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }), /STORE_ACTUAL_TREE_MISMATCH/);
  const b = f.make(); b.q.gates = f.save('old-gates.json', { ...f.gateValue, reviewedAt: '2000-01-01T00:00:00Z' });
  await assert.rejects(executeStorePackaging(b.ref(), { root: f.root, adapter: f.adapter }), /STORE_CURRENT_SOURCE_GATES_REQUIRED/); assert.equal(f.reads().signingReads, 0);
});
test('independently supplied current store history must match identities and both next counters', async t => {
  const f = fixture(t), a = f.make(); a.q.storeHistory = f.save('nonmonotonic-history.json', { ...f.historyValue, androidVersionCode: 1 });
  await assert.rejects(executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }), /STORE_FRESH_MONOTONIC_HISTORY_REQUIRED/); assert.equal(f.reads().signingReads, 0);
});
test('actual public tool files are descriptor-hashed and changed size or owner declarations refuse', t => {
  const f = fixture(t), a = f.make(); const value = JSON.parse(fs.readFileSync(a.q.tools.path));
  admitTools(value, 'ios'); fs.appendFileSync(value.entries.pod.path, 'changed'); assert.throws(() => admitTools(value, 'ios'));
  const bad = structuredClone(value); bad.entries.node.ownerUid = (process.getuid?.() || 0) + 10000;
  assert.throws(() => admitTools(bad, 'ios'), /STORE_TOOL_IDENTITY_REQUIRED/);
});
test('unknown signing acknowledgement retains the consumed platform claim and no command is replayed', async t => {
  const f = fixture(t), a = f.make(); f.adapter.signingAdmission = async () => { throw new Error('PRIVATE_SYNTHETIC_PASSWORD'); };
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.observed, false); assert.equal(result.originalFailure.code, 'STORE_EXECUTION_REFUSED'); assert.equal(result.phases[1].status, 'failed');
  assert.equal(f.calls.filter(c => c.args.includes('archive') || c.args[0] === ':app:bundleRelease').length, 0);
  assert.ok(fs.readdirSync(f.reservations).some(n => n.endsWith('.claim')));
  assert.doesNotMatch(JSON.stringify(result), /PRIVATE_SYNTHETIC_PASSWORD/);
});
test('a real nonzero child exit37 and stderr evidence remain separate from cleanup and unreached phases', async t => {
  const f = fixture(t), a = f.make(); f.adapter.command = async command => { f.calls.push(command); return f.answer(37, 'SYNTHETIC_FAILURE_DIAGNOSTIC'); };
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.commands[0].exitCode, 37); assert.equal(result.commands[0].stderr.sha256, digest('SYNTHETIC_FAILURE_DIAGNOSTIC'));
  assert.equal(result.commands[0].stderr.bytes, 28); assert.equal(result.cleanup.complete, true); assert.equal(result.observed, false);
  assert.deepEqual(result.phases.map(p => p.status), ['passed', 'unreached', 'failed', 'unreached', 'unreached']); assert.equal(f.calls.length, 1); assert.equal(f.reads().signingReads, 0);
});
test('successful stderr is retained as bytecount and digest and never treated as a failed exit', async t => {
  const f = fixture(t), a = f.make(); const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.observed, true); assert.equal(result.commands[0].exitCode, 0);
  assert.equal(result.commands[0].stderr.sha256, digest('SYNTHETIC_SUCCESS_ON_STDERR')); assert.ok(result.commands[0].stderr.bytes > 0);
  assert.equal(result.cleanup.rawToolLogsRetained, false); assert.doesNotMatch(JSON.stringify(result), /SYNTHETIC_SUCCESS_ON_STDERR/);
});
test('timeout remains failed with exact unknown exit and no automatic dispatch of remaining commands', async t => {
  const f = fixture(t), a = f.make(); f.adapter.command = async command => { f.calls.push(command); return { ...f.answer(), exitCode: null, timedOut: true }; };
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.commands[0].exitCode, null); assert.equal(result.commands[0].timedOut, true); assert.equal(result.observed, false); assert.equal(f.calls.length, 1);
});
test('lost transport acknowledgement leaves command unknown and cleanup incomplete without signalling an unowned PID', async t => {
  const f = fixture(t), a = f.make(); f.adapter.command = async command => { f.calls.push(command); throw new Error('STORE_HOST_ACK_UNKNOWN'); };
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.commands[0].status, 'dispatched-outcome-unknown'); assert.equal(result.cleanup.complete, false); assert.equal(f.calls.length, 1);
});
test('artifact refusal preserves completed build and marks source-postflight unreached', async t => {
  const f = fixture(t), a = f.make(); f.adapter.postflight = async () => { throw new Error('STORE_IOS_SIGNATURE_REFUSED'); };
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.originalFailure.code, 'STORE_IOS_SIGNATURE_REFUSED'); assert.equal(result.phases[2].status, 'passed');
  assert.equal(result.phases[3].status, 'failed'); assert.equal(result.phases[4].status, 'unreached'); assert.equal(result.observed, false);
});
test('source drift after artifact validation cannot promote signing or native acceptance', async t => {
  const f = fixture(t), a = f.make(); let count = 0;
  f.adapter.source = () => ({ ...structuredClone(f.source), tree: ++count === 1 ? f.source.tree : '4'.repeat(40) });
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.phases[3].status, 'passed'); assert.equal(result.phases[4].status, 'failed'); assert.equal(result.observed, false); assert.equal(result.distributionSigningVerified, false);
});
test('existing attempt output never overwrites original receipts or consumes a new platform claim', async t => {
  const f = fixture(t), a = f.make(); fs.mkdirSync(a.q.outputDirectory, { mode: 0o700 }); fs.writeFileSync(path.join(a.q.outputDirectory, 'original'), 'retain');
  await assert.rejects(executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }), /STORE_NEW_OUTPUT_REQUIRED/);
  assert.equal(fs.readFileSync(path.join(a.q.outputDirectory, 'original'), 'utf8'), 'retain'); assert.deepEqual(fs.readdirSync(f.reservations), []);
});
test('a partial joint reservation remains unchanged and never permits signing or filling the missing half', async t => {
  const f = fixture(t), a = f.make(); const name = digest(JSON.stringify(['ios', 'org.contract.storeapp'])) + '-ios-1.json';
  fs.writeFileSync(path.join(f.reservations, name), '{"partial":true}', { mode: 0o600 });
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }); assert.equal(result.originalFailure.code, 'STORE_PARTIAL_RESERVATION_REFUSED');
  assert.deepEqual(fs.readdirSync(f.reservations), [name]); assert.equal(f.reads().signingReads, 0); assert.equal(f.calls.length, 0);
});
test('privacy descriptor drift refuses before any signing or command dispatch', async t => {
  const f = fixture(t), a = f.make(); const value = JSON.parse(fs.readFileSync(a.q.privacyPolicy.path));
  a.q.privacyPolicy = f.save('wrong-policy.json', { ...value, nativeLinkConfigSha256: 'f'.repeat(64) });
  await assert.rejects(executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter }), /STORE_PRIVACY_POLICY_PROJECTION_MISMATCH/);
  assert.equal(f.calls.length, 0); assert.equal(f.reads().signingReads, 0); assert.deepEqual(fs.readdirSync(f.reservations), []);
});
test('actual generated Podfile drift is refused before the protected signing boundary', async t => {
  const f = fixture(t), a = f.make(); const command = f.adapter.command;
  f.adapter.command = async value => { const result = await command(value); if (value.args.includes('prebuild')) fs.appendFileSync(path.join(f.root, 'apps/mobile/ios/Podfile'), 'drift'); return result; };
  const result = await executeStorePackaging(a.ref(), { root: f.root, adapter: f.adapter });
  assert.equal(result.observed, false); assert.equal(result.phases[1].status, 'unreached'); assert.equal(result.phases[2].status, 'failed'); assert.equal(f.reads().signingReads, 0);
});
test('real isolated Git source capture reconciles all tracked bytes and refuses subsequent dirt', t => {
  const f = fixture(t), git = process.env.CASEOPS_GIT_EXECUTABLE || (process.platform === 'darwin' ? '/opt/homebrew/bin/git' : 'git');
  const environment = { ...process.env, HOME: f.base, GIT_CONFIG_GLOBAL: os.devNull, GIT_CONFIG_NOSYSTEM: '1', GIT_TERMINAL_PROMPT: '0' };
  fs.writeFileSync(path.join(f.root, 'empty-public-marker'), Buffer.alloc(0), { mode: 0o600 });
  for (const args of [['init', '-q', '-b', 'synthetic-contract'], ['add', '.'], ['-c', 'user.name=ContractFixture', '-c', 'user.email=fixture@contract.invalid',
    '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'Synthetic public source fixture']]) {
    const result = spawnSync(git, args, { cwd: f.root, env: environment, encoding: 'utf8', timeout: 5000 }); assert.equal(result.status, 0, result.stderr);
  }
  const budget = { entries: 0, bytes: 0, deadline: Date.now() + 10000 };
  const before = gitSource(f.root, git, budget), after = gitSource(f.root, git, budget);
  assert.deepEqual(before, after); assert.equal(before.sourceFileCount, 7); assert.equal(budget.entries, 40);
  fs.appendFileSync(path.join(f.root, 'apps/mobile/BUILD_TOOL_NOTICES.txt'), 'changed');
  assert.throws(() => gitSource(f.root, git, budget), /STORE_CLEAN_SOURCE_REQUIRED/);
});
