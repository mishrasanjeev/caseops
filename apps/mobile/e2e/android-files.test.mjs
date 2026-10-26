import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { androidFilesInventory, androidFilesScenarios, androidTextSegments, assertAndroidViewerAbsent, chooseAndroidFile,
  collectAndroidFiles, rapidActivateAndroidUpload, validateAndroidFileAsset, validateAndroidFilesContext,
  validateAndroidPicker, validateAndroidPrivacyReceipt, validateAndroidSourceAnchor, validateAndroidSourceSeed,
  validateAndroidUploadAcknowledgement } from './android-files.mjs';
import { selector } from './native-ui.mjs';
import { gatewayBaseline } from './traffic.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const APP = 'ai.caseops.mobile.dev.localacceptance', matterId = '11111111-2222-4333-8444-555555555555';
function fixture(t) {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'caseops-android-files-unit-'));
  t.after(() => rmSync(directory, { recursive: true, force: true })); let serial = 0;
  const evidence = (name, value) => { const file = path.join(directory, `${name}-${serial++}.json`), bytes = Buffer.from(JSON.stringify(value)); writeFileSync(file, bytes); return { path: file, sha256: sha(bytes) }; };
  const text = 'Public synthetic Android source. No legal authority or customer data.\n';
  const source = { matterId, attachmentId: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee', filename: 'mobile-source.txt', text, sizeBytes: Buffer.byteLength(text), sha256: sha(text) };
  const seed = { environment: 'docker-integration', syntheticDataOnly: true, matter: { id: matterId }, companyId: 'unit-company',
    membershipId: 'unit-member', sourceId: source.attachmentId, sourceSha256: source.sha256, cleanUploadAndDownload: true };
  const uploads = {};
  for (const id of ['txt', 'pdf', 'png', 'jpeg', 'docx']) {
    const filename = `CaseOps-android-files-012345abcdef-${id}.${id}`, bytes = Buffer.from(`Explicit synthetic ${id} fixture; no native rendering claimed.\n`);
    const file = path.join(directory, filename); writeFileSync(file, bytes);
    uploads[id] = { id, filename, path: file, sha256: sha(bytes), sizeBytes: bytes.length,
      ...(id === 'txt' ? { text: bytes.toString() } : {}), ...(id === 'pdf' ? { pages: 2 } : {}) };
  }
  const buildReceipt = evidence('build', { kind: 'explicit-unit-fixture-not-native-execution' });
  const manifestEvidence = evidence('manifest', { schemaVersion: 1, kind: 'android-files-synthetic-fixtures', platform: 'android', syntheticDataOnly: true, assets: Object.values(uploads) });
  const folderName = 'CaseOpsFiles-unit-files-run';
  const picker = { schemaVersion: 1, observed: true, platform: 'android', udid: 'emulator-5584', appId: APP, packageName: 'com.android.documentsui',
    folderName, buildReceipt, manifestEvidence, controls: { roots: { kind: 'label', value: 'Show roots' }, rootList: { kind: 'id', value: 'com.android.documentsui:id/roots_list' },
      downloads: { kind: 'text', value: 'Downloads' }, folder: { kind: 'text', value: folderName }, fileTitleId: 'android:id/title', cancel: 'android-back' },
    assets: Object.values(uploads).map(asset => ({ filename: asset.filename, sha256: asset.sha256, sizeBytes: asset.sizeBytes, observedProviderHash: asset.sha256, pickerName: asset.filename })) };
  const context = { platform: 'android', source, filesState: { uploads: {} }, gatewayBaseline: { runId: 'unit-run' },
    assets: { uploads, manifestEvidence }, provider: { folderName, evidence: evidence('picker', picker) },
    driver: { $$: async () => [], elementClick: async () => assert.fail('NO_ACTUAL_NATIVE_DEVICE_IN_UNIT') },
    fixture: { appId: APP, udid: 'emulator-5584', environment: 'docker-integration', syntheticDataOnly: true, coreInventory: 'native-core-2026-10-25',
      backendSha: 'a'.repeat(40), webSha: 'a'.repeat(40), binarySourceSha: 'a'.repeat(40), apiOrigin: 'https://10.0.2.2:8453',
      gatewayUrl: 'https://127.0.0.1:8453', gatewayRunId: 'unit-run', companyId: seed.companyId, membershipId: seed.membershipId,
      matter: { id: matterId }, seedEvidence: evidence('seed', seed), buildReceipt } };
  const rawPrivacy = delta => evidence('raw-privacy', { schemaVersion: 1, kind: 'android-files-privacy-snapshot', observed: true,
    platform: 'android', udid: context.fixture.udid, appId: APP, ownedAppScopeOnly: true, complete: true, providerOriginalsPreserved: true,
    counts: { ownedStagingFiles: 0, privateAssetMatchCount: 0 }, ...delta });
  return { context, source, seed, uploads, picker, evidence, rawPrivacy };
}

test('Android Files owns an independent exact17-case inventory and never changes core23 or iOS inventory', () => {
  const ids = ['FILES-01','FILES-02','FILES-03','FILES-04','FILES-05','FILES-06','FILES-07','FILES-08','FILES-09','FILES-10','FILES-11','FILES-12','FILES-13','FILES-14','FILES-15','FILES-16','FILES-17'];
  assert.deepEqual(androidFilesInventory.cases.map(value => value.id), ids); assert.deepEqual(androidFilesScenarios.map(value => value.id), ids);
  assert.deepEqual(collectAndroidFiles().intended, ids.map(id => `android:${id}`));
  assert.deepEqual(collectAndroidFiles().intended, collectAndroidFiles().discovered);
  assert.throws(() => collectAndroidFiles('ios'), /ANDROID_FILES_PLATFORM_REQUIRED/);
  assert.deepEqual(androidFilesScenarios.filter(value => value.freshAuthentication).map(value => value.id), ['FILES-09']);
  assert.deepEqual(androidFilesScenarios[8].requires, ['FILES-05']); assert.deepEqual(androidFilesScenarios[16].requires, ['FILES-16']);
  assert.equal(androidFilesScenarios[16].requiresSignedOut, true);
  assert.equal(JSON.parse(readFileSync(new URL('./core-20261025.json', import.meta.url))).cases.length, 23);
});

test('current Android source context binds real fixture/account/parent/TLS and refuses unknown upload outcomes', t => {
  const f = fixture(t); assert.equal(validateAndroidFilesContext(f.context), f.source);
  for (const patch of [{ platform: 'ios' }, { source: { ...f.source, matterId: f.source.attachmentId } },
    { gatewayBaseline: { runId: 'another' } }, { filesState: { uploads: {}, mutationUncertain: true } }]) {
    assert.throws(() => validateAndroidFilesContext({ ...f.context, ...patch }));
  }
  for (const patch of [{ environment: 'production' }, { appId: 'ai.caseops.mobile' }, { apiOrigin: 'http://10.0.2.2:8453' }, { webSha: 'b'.repeat(40) }]) {
    assert.throws(() => validateAndroidFilesContext({ ...f.context, fixture: { ...f.context.fixture, ...patch } }));
  }
});

test('effective member source provenance preserves original bytes and rejects contradictory direct metadata', t => {
  const f = fixture(t), base = { ...f.seed, membershipId: 'unit-owner' }, baseSeed = f.evidence('base', base);
  const seed = { environment: 'docker-integration', syntheticDataOnly: true, companyId: f.seed.companyId,
    membershipId: f.seed.membershipId, matter: f.seed.matter, provenance: { baseSeed } };
  const current = { ...f.context.fixture, seedEvidence: f.evidence('effective', seed) };
  validateAndroidSourceSeed(current, f.source);
  for (const patch of [{ sourceId: matterId }, { sourceSha256: 'b'.repeat(64) }, { membershipId: 'other' }, { companyId: 'other' }])
    assert.throws(() => validateAndroidSourceSeed({ ...current, seedEvidence: f.evidence('bad-effective', { ...seed, ...patch }) }, f.source));
  for (const patch of [{ sourceId: matterId }, { cleanUploadAndDownload: false }, { sourceSha256: 'b'.repeat(64) }])
    assert.throws(() => validateAndroidSourceSeed({ ...current, seedEvidence: f.evidence('wrong-base-link', { ...seed, provenance: { baseSeed: f.evidence('wrong-base', { ...base, ...patch }) } }) }, f.source));
});

test('bounded TXT segmentation retains independent literal windows and exact newline bytes', () => {
  const text = 'A'.repeat(9999) + '\n' + 'B'.repeat(10000) + 'C'.repeat(4000);
  assert.deepEqual(androidTextSegments(text), ['A'.repeat(9999) + '\n', 'B'.repeat(10000), 'C'.repeat(4000)]);
  for (const value of ['', null, 'x'.repeat(500001)]) assert.throws(() => androidTextSegments(value));
});

test('five clean upload kinds require exact manifest bytes and two-page PDF oracle', t => {
  const f = fixture(t); for (const kind of ['txt', 'pdf', 'png', 'jpeg', 'docx']) assert.equal(validateAndroidFileAsset(f.context, kind).sha256, f.uploads[kind].sha256);
  assert.throws(() => validateAndroidFileAsset(f.context, 'eicar'), /ANDROID_FILES_ASSET_KIND_REQUIRED/);
  const bad = { ...f.context, assets: { ...f.context.assets, uploads: { ...f.uploads, pdf: { ...f.uploads.pdf, pages: 1 } } } };
  assert.throws(() => validateAndroidFileAsset(bad, 'pdf'), /ANDROID_FILES_TWO_PAGE_PDF_REQUIRED/);
  writeFileSync(f.uploads.txt.path, 'changed'); assert.throws(() => validateAndroidFileAsset(f.context, 'txt'), /FIXTURE_EVIDENCE_CHANGED/);
});

test('observed Android picker binds exact selected device, app, build, manifest, folder and original file hash', t => {
  const f = fixture(t); validateAndroidPicker(f.context, f.uploads.txt);
  for (const patch of [{ observed: false }, { platform: 'ios' }, { udid: 'other' }, { packageName: 'other.picker' },
    { manifestEvidence: { ...f.context.assets.manifestEvidence, sha256: 'd'.repeat(64) } }, { assets: [] },
    { controls: { ...f.picker.controls, cancel: 'invented-tap' } }]) {
    const changed = { ...f.context, provider: { ...f.context.provider, evidence: f.evidence('bad-picker', { ...f.picker, ...patch }) } };
    assert.throws(() => validateAndroidPicker(changed, f.uploads.txt));
  }
});

function pickerDouble(context, asset, cancel = false) {
  let state = 'app'; const commands = [], callbacks = new Map();
  const element = (id, text = '', next) => {
    callbacks.set(id, () => { commands.push(id); if (next) state = next; });
    return { elementId: id, isDisplayed: async () => true, isEnabled: async () => true, getText: async () => text,
      click: async () => assert.fail('WRAPPED_NATIVE_CLICK_FORBIDDEN') };
  };
  const driver = { elementClick: async id => { assert.ok(callbacks.has(id)); callbacks.get(id)(); },
    getCurrentPackage: async () => state === 'app' || state === 'selected' ? APP : 'com.android.documentsui',
    pressKeyCode: async code => { assert.equal(code, 4); assert.equal(cancel, true); commands.push('android-back'); state = 'app'; },
    waitUntil: async (predicate, options) => { if (!await predicate()) throw new Error(options.timeoutMsg); },
    $$: async query => {
      if (query === 'id=files-choose') return [element('choose', '', 'picker')];
      if (query === '~Show roots' && state === 'picker') return [element('roots', '', 'roots')];
      if (query === 'id=com.android.documentsui:id/roots_list' && state === 'roots') return [{ isDisplayed: async () => true,
        $$: async value => { assert.equal(value, selector('android', 'text', 'Downloads')); return [element('downloads', '', 'downloads')]; } }];
      if (query === selector('android', 'text', context.provider.folderName) && state === 'downloads') return [element('folder', '', 'folder')];
      if (query === `android=new UiSelector().resourceId("android:id/title").text(${JSON.stringify(asset?.filename)})` && state === 'folder') return [element('chosen-file', asset.filename, 'selected')];
      if (query === 'id=files-matter-code' || query === 'id=files-selection' && state === 'selected' || query === 'id=files-upload' && state === 'selected') return [element('returned')];
      return [];
    } };
  context.driver = driver; return { driver, commands, state: () => state };
}
test('actual Android picker wrapper uses only observed Downloads/folder/file controls or one explicit Back cancellation', async t => {
  for (const cancel of [false, true]) {
    const f = fixture(t), fake = pickerDouble(f.context, f.uploads.txt, cancel);
    await chooseAndroidFile(f.context, cancel ? null : f.uploads.txt, { cancel });
    assert.deepEqual(fake.commands, cancel ? ['choose', 'android-back'] : ['choose', 'roots', 'downloads', 'folder', 'chosen-file']);
    assert.equal(fake.state(), cancel ? 'app' : 'selected');
  }
});

test('lost native picker file-click acknowledgement cannot refetch or select a second file', async t => {
  const f = fixture(t), fake = pickerDouble(f.context, f.uploads.txt), original = fake.driver.elementClick.bind(fake.driver);
  const failure = new Error('UNIT_PICKER_ACK_UNKNOWN'); let attempts = 0;
  fake.driver.elementClick = async id => { if (id === 'chosen-file') { attempts++; await original(id); throw failure; } await original(id); };
  await assert.rejects(chooseAndroidFile(f.context, f.uploads.txt), error => error === failure);
  assert.equal(attempts, 1); assert.equal(fake.commands.filter(id => id === 'chosen-file').length, 1);
});

test('one canonical upload acknowledgement permits refresh but rejects retries, unknown statuses and unrelated mutations', () => {
  const post = { method: 'POST', route: `/api/matters/${matterId}/attachments`, status: 200, requestId: 'unit-ack' },
    read = { method: 'GET', route: `/api/matters/${matterId}/workspace`, status: 200 }, refresh = { method: 'POST', route: '/api/auth/native/refresh', status: 200 };
  assert.equal(validateAndroidUploadAcknowledgement([refresh, post, read], matterId, { requireRead: true }), post);
  for (const rows of [[], [post, post, read], [{ ...post, status: 201 }, read], [{ ...post, status: 0 }, read],
    [post, read, { method: 'POST', route: '/api/matters/other/notes', status: 200 }], [post, { ...refresh, status: 403 }]])
    assert.throws(() => validateAndroidUploadAcknowledgement(rows, matterId, { requireRead: true }));
});

test('rapid TXT activation is one measured native protocol dispatch with two taps and no replay after lost acknowledgement', async () => {
  const calls = [], button = { elementId: 'unit-upload', isDisplayed: async () => true, isEnabled: async () => true, getAttribute: async () => 'files-upload' };
  const context = { platform: 'android', driver: { getWindowRect: async () => ({ x: 0, y: 0, width: 400, height: 800 }),
    getElementRect: async () => ({ x: 100, y: 400, width: 100, height: 50 }), performActions: async actions => calls.push(actions), releaseActions: async () => calls.push('release') } };
  await rapidActivateAndroidUpload(context, button);
  assert.deepEqual(calls[0][0].actions.map(value => value.type), ['pointerMove','pointerDown','pointerUp','pause','pointerDown','pointerUp']);
  assert.equal(calls[0][0].actions[3].duration, 10); assert.equal(calls.length, 2);
  const failure = new Error('UNIT_UPLOAD_INPUT_ACK_UNKNOWN'); let attempts = 0;
  context.driver.performActions = async () => { attempts++; throw failure; };
  await assert.rejects(rapidActivateAndroidUpload(context, button), error => error === failure); assert.equal(attempts, 1);
});

test('normalized privacy facts must equal complete raw evidence and cannot hide one retained byte or staging file', t => {
  const f = fixture(t), boundary = 'selection-clear';
  const receipt = { schemaVersion: 1, observed: true, platform: 'android', udid: f.context.fixture.udid, appId: APP, boundary,
    ownedAppScopeOnly: true, providerOriginalsUnchanged: true, stagedFileCount: 0, privateByteMatchCount: 0, rawEvidence: f.rawPrivacy() };
  validateAndroidPrivacyReceipt(f.context, boundary, receipt);
  for (const patch of [{ udid: 'other' }, { boundary: 'other' }, { stagedFileCount: 1 }, { privateByteMatchCount: 1 },
    { rawEvidence: f.rawPrivacy({ complete: false }) }, { rawEvidence: f.rawPrivacy({ counts: { ownedStagingFiles: 0, privateAssetMatchCount: 1 } }) }])
    assert.throws(() => validateAndroidPrivacyReceipt(f.context, boundary, { ...receipt, ...patch }));
});

test('reader privacy rejects retained structural roots even when an element claims to be invisible', async () => {
  const context = { platform: 'android', driver: { $$: async query => query === 'id=private-document-viewer' ? [{ isDisplayed: async () => false }] : [] } };
  await assert.rejects(assertAndroidViewerAbsent(context), /ANDROID_FILES_PRIVATE_VIEWER_STRUCTURE_RETAINED/);
});

test('signed-out final case requires earlier logout, restarts only the app and performs no authentication/private HTTP', async t => {
  const f = fixture(t), calls = [], ledger = { runId: 'unit-run', lastSequence: 0, requests: [], markerRejected: 0, routeRejected: 0, overflow: false };
  f.context.gatewayBaseline = gatewayBaseline(ledger, { gatewayRunId: 'unit-run' }); f.context.filesState.logoutAcknowledged = true;
  t.mock.method(globalThis, 'fetch', async (_url, options) => { assert.equal(options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers'); return new Response(JSON.stringify(ledger)); });
  f.context.driver = { elementClick: async () => assert.fail('SIGNED_OUT_CASE_MUST_NOT_CLICK'),
    terminateApp: async id => { assert.equal(id, APP); calls.push('terminate'); }, activateApp: async id => { assert.equal(id, APP); calls.push('activate'); },
    switchContext: async value => assert.equal(value, 'NATIVE_APP'), waitUntil: async predicate => assert.ok(await predicate()),
    $$: async query => ['id=signed-out', 'id=sign-in'].includes(query) ? [{ isDisplayed: async () => true }] : [] };
  f.context.observeFilesystem = async boundary => f.evidence('privacy', { schemaVersion: 1, observed: true, platform: 'android', udid: f.context.fixture.udid,
    appId: APP, boundary, ownedAppScopeOnly: true, providerOriginalsUnchanged: true, stagedFileCount: 0, privateByteMatchCount: 0, rawEvidence: f.rawPrivacy() });
  await androidFilesScenarios.at(-1).run(f.context); assert.deepEqual(calls, ['terminate', 'activate']); assert.deepEqual(ledger.requests, []);
  f.context.filesState.logoutAcknowledged = false;
  await assert.rejects(androidFilesScenarios.at(-1).run(f.context), /ANDROID_FILES_PRIOR_LOGOUT_REQUIRED/);
  assert.deepEqual(calls, ['terminate', 'activate']);
});
