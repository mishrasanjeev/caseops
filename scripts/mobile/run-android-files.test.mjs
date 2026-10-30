import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { androidFilesInventory, collectAndroidFiles } from '../../apps/mobile/e2e/android-files.mjs';
import { assembleAndroidFilesFixture, androidFilesKnownSources, androidFilesHarnessFingerprint, assertStrictAndroidFilesEnvironment, bindAndroidFilesPrivateRoots,
  captureAndroidFilesFailure, captureAndroidFilesPrivacy, executeAndroidFilesCases, validateAndroidFilesContainers } from './run-android-files.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
test('controller keeps every preflight/checkpoint cold and overrides input flags only for final postflight', () => {
  for (const phase of ['preflight','checkpoint','postflight']) {
    let observed;
    captureAndroidFilesPrivacy({ verifyProviderBytes: phase !== 'postflight' }, phase, options => {
      observed = options.verifyProviderBytes;
      return { snapshot: { schemaVersion: 2, complete: true, providerMetadataPreserved: true, providerOriginalsRead: observed,
        providerOriginalsPreserved: observed ? true : null, providerByteVerification: observed ? 'postflight' : 'deferred-until-postflight', counts: { ownedStagingFiles: 0, privateAssetMatchCount: 0 } } };
    }); assert.equal(observed, phase === 'postflight');
  }
});
test('controller refuses early provider reads, pending final proof and private copies before returning a success', () => {
  let calls = 0; assert.throws(() => captureAndroidFilesPrivacy({}, 'unknown', () => { calls++; }), /ANDROID_FILES_PRIVACY_PHASE_REQUIRED/); assert.equal(calls, 0);
  const good = { schemaVersion: 2, complete: true, providerMetadataPreserved: true, providerOriginalsRead: false,
    providerOriginalsPreserved: null, providerByteVerification: 'deferred-until-postflight', counts: { ownedStagingFiles: 0, privateAssetMatchCount: 0 } };
  for (const change of [{ providerOriginalsRead: true }, { providerOriginalsPreserved: true }, { providerMetadataPreserved: false }, { counts: { ownedStagingFiles: 1, privateAssetMatchCount: 0 } }, { counts: { ownedStagingFiles: 0, privateAssetMatchCount: 1 } }])
    assert.throws(() => captureAndroidFilesPrivacy({}, 'checkpoint', () => ({ snapshot: { ...good, ...change } })));
  assert.throws(() => captureAndroidFilesPrivacy({}, 'postflight', () => ({ snapshot: good })));
});
function fixture(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'caseops-android-files-run-unit-')); t.after(() => rmSync(root, { recursive: true, force: true })); let serial = 0;
  const save = (name, value) => { const file = path.join(root, `${name}-${serial++}.json`), bytes = Buffer.from(JSON.stringify(value)); writeFileSync(file, bytes); return { path: file, sha256: sha(bytes) }; };
  const matterId = '11111111-2222-4333-8444-555555555555', text = 'Explicit synthetic source.\n';
  const source = { matterId, attachmentId: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', filename: 'mobile-source.txt', sha256: sha(text), sizeBytes: Buffer.byteLength(text), text };
  const seed = { environment: 'docker-integration', syntheticDataOnly: true, companyId: 'unit-company', membershipId: 'unit-member', matter: { id: matterId },
    sourceId: source.attachmentId, sourceSha256: source.sha256, cleanUploadAndDownload: true };
  const receipt = { platform: 'android', project: 'unit-project', backendSha: 'a'.repeat(40), backendRevision: 'unit-api', webSha: 'a'.repeat(40) };
  const isolationReceipt = save('isolation', receipt), buildReceipt = save('build', { unitOnly: true });
  const coreFixture = { environment: 'docker-integration', syntheticDataOnly: true, appId: 'ai.caseops.mobile.dev.localacceptance', udid: 'emulator-5584',
    companyId: seed.companyId, membershipId: seed.membershipId, matter: seed.matter, backendSha: receipt.backendSha, backendRevision: receipt.backendRevision,
    buildReceipt, isolationEvidence: isolationReceipt, seedEvidence: save('seed', seed) };
  const assets = ['txt', 'pdf', 'png', 'jpeg', 'docx', 'eicar', 'unsupported'].map(id => {
    const filename = `CaseOps-android-files-012345abcdef-${id}.${id === 'unsupported' ? 'rtf' : id === 'eicar' ? 'txt' : id}`;
    const file = path.join(root, filename), bytes = Buffer.from(`Explicit offline ${id} fixture.\n`); writeFileSync(file, bytes);
    return { id, filename, path: file, sha256: sha(bytes), sizeBytes: bytes.length, ...(id === 'pdf' ? { expected: { pages: 2 } } : {}) };
  });
  const manifest = { schemaVersion: 1, kind: 'android-files-synthetic-fixtures', platform: 'android', syntheticDataOnly: true,
    backendSha: receipt.backendSha, backendRevision: receipt.backendRevision, companyId: seed.companyId, matter: seed.matter,
    isolationReceipt, source, assets };
  const manifestEvidence = save('manifest', manifest), folderName = 'CaseOpsFiles-unit-run-files';
  const staged = { schemaVersion: 2, providerOriginalsRead: false, observed: true, platform: 'android', kind: 'android-files-provider-assets', udid: coreFixture.udid, appId: coreFixture.appId, manifestEvidence, folderName,
    assets: assets.map(({ id, filename, sha256, sizeBytes }) => ({ id, filename, sha256, sizeBytes })) };
  const providerEvidence = save('provider', staged);
  const picker = { schemaVersion: 2, providerOriginalsRead: false, stagingEvidence: providerEvidence, observed: true, platform: 'android', udid: coreFixture.udid, appId: coreFixture.appId, packageName: 'com.android.documentsui',
    manifestEvidence, buildReceipt, folderName, controls: { roots: { kind: 'label', value: 'Show roots' }, rootList: { kind: 'id', value: 'com.android.documentsui:id/roots_list' },
      downloads: { kind: 'text', value: 'Downloads' }, folder: { kind: 'text', value: folderName }, fileTitleId: 'android:id/title', cancel: 'android-back' },
    assets: assets.map(value => ({ ...value, pickerName: value.filename, transferSha256: value.sha256 })) };
  const request = { coreFixture, manifestEvidence, providerEvidence, pickerEvidence: save('picker', picker), filesCache: root };
  return { root, save, request, manifest, staged, picker, source };
}

test('assembly derives all five clean upload oracles from one real-reference shape and complete seven-original cohort', t => {
  const f = fixture(t), result = assembleAndroidFilesFixture(f.request);
  assert.equal(result.filesInventory, 'native-android-files-2026-10-26'); assert.deepEqual(result.files.source, f.source);
  assert.equal(result.files.uploads.pdf.pages, 2); assert.equal(result.files.uploads.txt.text, 'Explicit offline txt fixture.\n');
  assert.deepEqual(Object.keys(result.files.uploads), ['txt', 'pdf', 'png', 'jpeg', 'docx']);
  assert.deepEqual(result.files.provider, { folderName: f.staged.folderName, evidence: f.request.pickerEvidence });
});

test('missing original, wrong source/build/device/folder and different serving release refuse assembly', t => {
  for (const kind of ['missing-original', 'wrong-device', 'wrong-folder', 'wrong-build', 'wrong-release']) {
    const f = fixture(t), request = { ...f.request };
    if (kind === 'missing-original') request.providerEvidence = f.save('wrong-stage', { ...f.staged, assets: f.staged.assets.slice(1) });
    if (kind === 'wrong-device') request.providerEvidence = f.save('wrong-stage', { ...f.staged, udid: 'emulator-other' });
    if (kind === 'wrong-folder') request.pickerEvidence = f.save('wrong-picker', { ...f.picker, folderName: 'another' });
    if (kind === 'wrong-build') request.pickerEvidence = f.save('wrong-picker', { ...f.picker, buildReceipt: { ...f.request.coreFixture.buildReceipt, sha256: 'b'.repeat(64) } });
    if (kind === 'wrong-release') request.manifestEvidence = f.save('wrong-manifest', { ...f.manifest, backendSha: 'b'.repeat(40) });
    assert.throws(() => assembleAndroidFilesFixture(request), /ANDROID_FILES_/);
  }
});

test('privacy known sources retain the exact base TXT and every bounded prior Android cohort', t => {
  const f = fixture(t), assets = assembleAndroidFilesFixture(f.request).files;
  assets.priorManifestEvidence = [f.request.manifestEvidence];
  const known = androidFilesKnownSources(assets); assert.equal(known.length, 8); assert.equal(known[0].sha256, f.source.sha256);
  assert.ok(known.slice(1).every(value => value.id.startsWith('prior-0-')));
  assets.priorManifestEvidence = [f.save('foreign', { ...f.manifest, platform: 'ios' })];
  assert.throws(() => androidFilesKnownSources(assets), /ANDROID_FILES_PRIOR_PLATFORM_REQUIRED/);
});

test('every declared prior manifest has one unique matching complete provider-preservation cohort', t => {
  const f = fixture(t), prior = fixture(t);
  const priorStage = prior.save('prior-stage', { ...prior.staged, folderName: 'CaseOpsFiles-prior-unit-cohort' });
  const valid = { ...f.request, priorStagingEvidence: [priorStage], priorManifestEvidence: [prior.request.manifestEvidence] };
  assert.equal(assembleAndroidFilesFixture(valid).files.priorStagingEvidence.length, 1);
  for (const patch of [{ priorStagingEvidence: [] }, { priorManifestEvidence: [] },
    { priorStagingEvidence: [f.request.providerEvidence] }, { priorManifestEvidence: [f.request.manifestEvidence] },
    { priorStagingEvidence: [priorStage, priorStage], priorManifestEvidence: [prior.request.manifestEvidence, prior.request.manifestEvidence] }])
    assert.throws(() => assembleAndroidFilesFixture({ ...valid, ...patch }), /ANDROID_FILES_/);
});

function controller(options = {}) {
  const events = [], starts = [], deletions = [], authentications = [], calls = [], state = { uploads: {} };
  const cases = androidFilesInventory.cases.map(({ id }, index) => ({ id,
    ...(index === 8 ? { freshAuthentication: true } : {}), ...(index === 16 ? { requires: ['FILES-16'], requiresSignedOut: true } : {}),
    run: async () => { calls.push(id); if (options.failCall === id) { if (options.mutationUncertain) state.mutationUncertain = true; throw new Error('UNIT_CALL_FAILED'); } } }));
  let index = 0;
  const args = { cases, filesState: state, record: event => events.push(event), beforeCase: async scenario => {
    if (options.failFence === scenario.id) throw new Error('UNIT_RUNTIME_FENCE_FAILED');
  }, createDriver: async scenario => {
    starts.push(scenario.id);
    if (options.unknownCreation === scenario.id) throw new Error('UNIT_SESSION_ACK_UNKNOWN');
    const sessionId = `11111111-2222-4333-8444-${String(++index).padStart(12, '0')}`;
    return { sessionId, terminateApp: async () => {}, activateApp: async () => {}, switchContext: async () => {},
      deleteSession: async () => { deletions.push(scenario.id); if (options.failCleanup === scenario.id) throw new Error('UNIT_DELETE_ACK_UNKNOWN'); } };
  }, createContext: async (driver, scenario) => {
    if (options.failReadback === scenario.id) throw new Error('ANDROID_SESSION_CAPABILITY_MISMATCH');
    return { driver, fixture: { appId: 'unit-app' }, platform: 'android' };
  }, prepareAuthentication: async (_context, settings) => {
    authentications.push(settings.fresh); if (options.failAuth) throw new Error('UNIT_AUTH_FAILED');
  } };
  return { args, events, starts, deletions, authentications, calls };
}

test('the complete17-case controller owns seventeen distinct sessions,51 phases and fresh authentication only at first/PDF boundary', async () => {
  const f = controller(), result = await executeAndroidFilesCases(f.args);
  assert.equal(result.completed.length, 17); assert.equal(f.starts.length, 17); assert.deepEqual(f.deletions, f.starts);
  assert.equal(f.events.filter(event => event.type === 'phase_result').length, 51);
  assert.ok(f.events.filter(event => event.type === 'phase_result').every(event => event.status === 'passed'));
  assert.equal(f.authentications.length, 16); assert.deepEqual(f.authentications.map((fresh, index) => fresh ? index : null).filter(value => value !== null), [0, 8]);
  const sessions = f.events.filter(event => event.type === 'appium_session'); assert.equal(new Set(sessions.map(event => event.sessionId)).size, 17);
  assert.equal(sessions.filter(event => event.state === 'created').length, 17); assert.equal(sessions.filter(event => event.state === 'deleted').length, 17);
});

test('unknown session creation never opens a second client and keeps the failed cleanup boundary', async () => {
  const f = controller({ unknownCreation: 'FILES-01' }); await executeAndroidFilesCases(f.args);
  assert.deepEqual(f.starts, ['FILES-01']); assert.deepEqual(f.calls, []); assert.deepEqual(f.deletions, []);
  assert.equal(f.events.filter(event => event.phase === 'call' && event.status === 'not-run').length, 17);
  assert.equal(f.events.filter(event => event.phase === 'teardown' && event.status === 'failed').length, 1);
});

test('wrong server readback or real auth failure cleans the one known session once and blocks every later client', async () => {
  for (const options of [{ failReadback: 'FILES-01' }, { failAuth: true }]) {
    const f = controller(options); await executeAndroidFilesCases(f.args);
    assert.deepEqual(f.starts, ['FILES-01']); assert.deepEqual(f.deletions, ['FILES-01']); assert.deepEqual(f.calls, []);
  }
});

test('a failed runtime fence creates no session; cleanup uncertainty and unknown upload outcomes prohibit further sessions', async () => {
  const fence = controller({ failFence: 'FILES-01' }); await executeAndroidFilesCases(fence.args); assert.deepEqual(fence.starts, []);
  const cleanup = controller({ failCleanup: 'FILES-01' }); await executeAndroidFilesCases(cleanup.args); assert.deepEqual(cleanup.starts, ['FILES-01']);
  const uncertain = controller({ failCall: 'FILES-04', mutationUncertain: true }); await executeAndroidFilesCases(uncertain.args);
  assert.deepEqual(uncertain.starts, ['FILES-01','FILES-02','FILES-03','FILES-04']);
  assert.equal(uncertain.calls.filter(id => id === 'FILES-04').length, 1);
});

test('unverified logout dependency cannot create the final signed-out session or silently authenticate it', async () => {
  const f = controller({ failCall: 'FILES-16' }); await executeAndroidFilesCases(f.args);
  assert.equal(f.starts.includes('FILES-17'), false); assert.equal(f.calls.includes('FILES-17'), false);
  assert.equal(f.events.find(event => event.id === 'android:FILES-17' && event.phase === 'setup' && event.type === 'phase_result').status, 'blocked');
});

test('runtime container readback rejects a foreign/stopped/replaced image or network without inspecting environment values', () => {
  const expected = { id: 'container1', image: `sha256:${'a'.repeat(64)}`, name: '/unit-api-1', networks: ['unit_default'] };
  const receipt = { project: 'unit', containers: [expected, { ...expected, id: 'container2' }, { ...expected, id: 'container3' }] };
  const observed = receipt.containers.map(value => ({ Id: value.id, Image: value.image, Name: value.name, Running: true, Status: 'running', Project: 'unit', Networks: value.networks }));
  validateAndroidFilesContainers(receipt, observed);
  for (const patch of [{ Image: 'sha256:other' }, { Running: false }, { Project: 'foreign' }, { Networks: ['foreign'] }])
    assert.throws(() => validateAndroidFilesContainers(receipt, [{ ...observed[0], ...patch }, ...observed.slice(1)]));
});

test('canonical one-shot migrator must have exited successfully while every long-running owned service stays running', () => {
  const image = `sha256:${'a'.repeat(64)}`, containers = ['api', 'web', 'postgres', 'migrate'].map(service => ({
    id: `unit-${service}`, name: `/unit-${service}-1`, image, networks: ['unit_default'] }));
  const receipt = { project: 'unit', containers };
  // Captured actual canonical migration status: Running=false,Status=exited,
  // ExitCode=0,Service=migrate. This is completion, not a failed API daemon.
  const observed = containers.map(value => ({ Id: value.id, Image: image, Name: value.name, Project: 'unit', Networks: value.networks,
    Running: value.id !== 'unit-migrate', Status: value.id === 'unit-migrate' ? 'exited' : 'running', ExitCode: 0,
    Service: value.id.slice(5) }));
  validateAndroidFilesContainers(receipt, observed);
  for (const patch of [{ ExitCode: 1 }, { Status: 'created' }, { Running: true }, { Service: 'api' }])
    assert.throws(() => validateAndroidFilesContainers(receipt, [...observed.slice(0, 3), { ...observed[3], ...patch }]));
  assert.throws(() => validateAndroidFilesContainers(receipt, [{ ...observed[0], Running: false, Status: 'exited', ExitCode: 0 }, ...observed.slice(1)]), /ANDROID_FILES_CONTAINER_STOPPED/);
});

test('privacy boundaries include a newly attested external root before scanning and refuse replacement after observation', () => {
  const metadata = { kind: 'directory', uid: 10087, device: '1', inode: '2' }, base = { udid: 'emulator-5584', appId: 'unit',
    bootId: 'unit-boot', avdName: 'unit-avd', rootUid: 0, packageUid: 10087,
    appData: { path: '/data/user/0/unit', metadata }, provider: { path: '/storage/emulated/0/Download', metadata }, externalAppData: null };
  const observed = { ...base, externalAppData: { path: '/storage/emulated/0/Android/data/unit', metadata: { ...metadata, inode: '3' } } };
  assert.equal(bindAndroidFilesPrivateRoots(base, observed), observed);
  assert.throws(() => bindAndroidFilesPrivateRoots(observed, { ...observed, externalAppData: null }), /ANDROID_FILES_PRIVATE_ROOT_CHANGED/);
  assert.throws(() => bindAndroidFilesPrivateRoots(observed, { ...observed, externalAppData: { ...observed.externalAppData, metadata: { ...metadata, inode: '4' } } }), /ANDROID_FILES_PRIVATE_ROOT_CHANGED/);
});

test('TLS override and failure capture refuse credential surfaces before reading page source or writing evidence', async t => {
  const f = fixture(t);
  assert.throws(() => assertStrictAndroidFilesEnvironment({ publicCa: { path: '/unit-ca' } }, { NODE_TLS_REJECT_UNAUTHORIZED: '0' }), /ANDROID_FILES_STRICT_TLS_REQUIRED/);
  assert.throws(() => assertStrictAndroidFilesEnvironment({ publicCa: { path: '/unit-ca' } }, { NODE_EXTRA_CA_CERTS: '/wrong-ca' }), /ANDROID_FILES_EXACT_PUBLIC_CA_REQUIRED/);
  let reads = 0;
  const context = { fixture: f.request.coreFixture, driver: { getCurrentPackage: async () => f.request.coreFixture.appId,
    switchContext: async () => {}, $$: async () => [{}], getPageSource: async () => { reads++; return '<hierarchy/>'; } } };
  await assert.rejects(captureAndroidFilesFailure(context, path.join(f.root, 'failure.xml')), /ANDROID_FILES_CREDENTIAL_CAPTURE_REFUSED/);
  assert.equal(reads, 0);
});

test('collection CLI is a separate exact17 inventory and does not load devices, credentials or require an admission helper', () => {
  const result = JSON.parse(execFileSync(process.execPath, [fileURLToPath(new URL('./run-android-files.mjs', import.meta.url)), '--collect'], { encoding: 'utf8', timeout: 10000 }));
  assert.deepEqual(result, collectAndroidFiles()); assert.equal(result.intended.length, 17);
});

test('actual runner source preserves runtime fences, actual capability readback, raw ledger retention and bounded source admission', () => {
  const source = readFileSync(new URL('./run-android-files.mjs', import.meta.url), 'utf8');
  assert.ok(source.indexOf('verifyAndroidSessionTransport(fixture') < source.indexOf("await configureNativeDriver(driver"));
  assert.ok(source.includes('const deadline = setTimeout(')); assert.ok(source.includes('timeout: 80000'));
  assert.ok(source.includes('connectionRetryCount: 0')); assert.equal(/\.click\s*\(/.test(source), false);
  assert.ok(source.includes("newJson(path.join(report, 'gateway-after.json'), after)"));
  assert.ok(source.includes('assert.equal(source.sourceDirty, false'));
});


test('physical private-root rebinding retains the complete run-as USB identity and rejects every changed field', () => {
  const metadata = { kind: 'directory', uid: 10087, device: '1', inode: '2' };
  const base = { udid: 'CASEOPSUNITUSB01', appId: 'ai.caseops.mobile.dev.localacceptance', bootId: 'unit-boot', packageUid: 10087,
    transportMode: 'usb-reverse', deviceKind: 'physical', access: 'run-as', shellUid: 2000, runAsUid: 10087,
    usbDevPath: 'usb:1-2.5', apiLevel: 36, abi: 'arm64-v8a', qemuOff: true,
    appData: { path: '/data/user/0/ai.caseops.mobile.dev.localacceptance', metadata },
    provider: { path: '/storage/emulated/0/Download', metadata }, externalAppData: null };
  const actual = structuredClone(base); assert.equal(bindAndroidFilesPrivateRoots(base, actual), actual);
  for (const patch of [{ transportMode: 'emulator' }, { transportMode: undefined }, { deviceKind: 'emulator' }, { access: 'root' },
    { shellUid: 0 }, { runAsUid: 10088 }, { usbDevPath: 'usb:2-3' }, { apiLevel: 35 }, { abi: 'x86_64' }, { qemuOff: false },
    { rootUid: 0 }, { avdName: 'fabricated-avd' }]) {
    assert.throws(() => bindAndroidFilesPrivateRoots(base, { ...actual, ...patch }), /ANDROID_FILES_PRIVATE_RUNTIME_CHANGED/);
  }
  const external = { ...actual, externalAppData: { path: '/storage/emulated/0/Android/data/ai.caseops.mobile.dev.localacceptance',
    metadata: { ...metadata, inode: '3' } } };
  assert.equal(bindAndroidFilesPrivateRoots(base, external), external);
  assert.throws(() => bindAndroidFilesPrivateRoots(external, { ...external, externalAppData: null }), /ANDROID_FILES_PRIVATE_ROOT_CHANGED/);
});

test('physical rebinding requires complete attested fields and cannot accept two equally incomplete or fabricated identities', () => {
  const metadata = { kind: 'directory', uid: 10087, device: '1', inode: '2' };
  const base = { udid: 'CASEOPSUNITUSB01', appId: 'ai.caseops.mobile.dev.localacceptance', bootId: 'unit-boot', packageUid: 10087,
    transportMode: 'usb-reverse', deviceKind: 'physical', access: 'run-as', shellUid: 2000, runAsUid: 10087,
    usbDevPath: 'usb:1-2.5', apiLevel: 36, abi: 'arm64-v8a', qemuOff: true,
    appData: { path: '/data/user/0/ai.caseops.mobile.dev.localacceptance', metadata },
    provider: { path: '/storage/emulated/0/Download', metadata }, externalAppData: null };
  for (const key of ['deviceKind', 'access', 'shellUid', 'runAsUid', 'usbDevPath', 'apiLevel', 'abi', 'qemuOff']) {
    const incomplete = { ...base }; delete incomplete[key];
    assert.throws(() => bindAndroidFilesPrivateRoots(incomplete, structuredClone(incomplete)), /ANDROID_FILES_PRIVATE_RUNTIME_CHANGED/, key);
  }
  for (const patch of [{ shellUid: 0 }, { runAsUid: 0 }, { usbDevPath: 'tcp:127.0.0.1' }, { rootUid: 0 }, { avdName: 'fabricated' }]) {
    const invalid = { ...base, ...patch };
    assert.throws(() => bindAndroidFilesPrivateRoots(invalid, structuredClone(invalid)), /ANDROID_FILES_PRIVATE_RUNTIME_CHANGED/);
  }
});


test('actual Files fingerprint closes local transport helper bytes and refuses its missing-source boundary', t => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'caseops-files-helper-fingerprint-')); t.after(() => rmSync(directory, { recursive: true, force: true }));
  mkdirSync(path.join(directory, 'scripts/mobile'), { recursive: true }); mkdirSync(path.join(directory, 'apps/mobile/e2e'), { recursive: true });
  const source = fileURLToPath(new URL('../../', import.meta.url));
  for (const name of ['run-android-files.mjs','android-files-privacy.mjs','source-snapshot.mjs','prepare-android-files-fixture.py','admit-android-file-source.py','local-transport.py']) {
    writeFileSync(path.join(directory, 'scripts/mobile', name), readFileSync(path.join(source, 'scripts/mobile', name)));
  }
  writeFileSync(path.join(directory, 'apps/mobile/e2e/android-local-profile.mjs'), readFileSync(path.join(source, 'apps/mobile/e2e/android-local-profile.mjs')));
  const file = path.join(directory, 'scripts/mobile/local-transport.py'), original = readFileSync(file), first = androidFilesHarnessFingerprint(directory);
  writeFileSync(file, Buffer.concat([original, Buffer.from('\n# synthetic fingerprint mutation only\n')]));
  assert.notEqual(androidFilesHarnessFingerprint(directory), first);
  writeFileSync(file, original); assert.equal(androidFilesHarnessFingerprint(directory), first);
  rmSync(file); assert.throws(() => androidFilesHarnessFingerprint(directory), { code: 'ENOENT' });
});
