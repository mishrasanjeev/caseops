import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { gatewayBaseline } from './traffic.mjs';
import { collectIosFiles, expandIosSourceDetails, proveIosSelectedFile, iosFilesInventory, iosFilesScenarios, validateAsset, validateIosFilesContext,
  validatePickerAsset, validatePickerProvider, validatePrivacyReceipt, validateSourceAnchor, validateSourceSeed, textSegments, chooseIosFile,
  awaitIosTextReady, readIosText, repeatIosFileSelection,
  IOS_UPLOAD_PERSISTED_MESSAGE, proveIosReaderEntry, proveIosUploadPersisted, findIosUploadPersisted,
  assertIosUploadErrorsAbsent, assertIosViewerAbsent, findIosFileFact, validateIosUploadAcknowledgement, rapidActivateIosUpload } from './ios-files.mjs';

const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const matterId = '11111111-1111-4111-8111-111111111111', attachmentId = '22222222-2222-4222-8222-222222222222';
function fixture(t) {
  const directory = mkdtempSync(path.join(tmpdir(), 'caseops-ios-files-unit-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  let serial = 0;
  const evidence = (name, value) => { const file = path.join(directory, `${name}-${serial++}.json`), bytes = Buffer.from(JSON.stringify(value)); writeFileSync(file, bytes); return { path: file, sha256: sha(bytes) }; };
  const text = 'Synthetic offline unit fixture.\n';
  const source = { matterId, attachmentId, filename: 'mobile-source.txt', text, sizeBytes: Buffer.byteLength(text), sha256: sha(Buffer.from(text)) };
  const seed = { environment: 'docker-integration', syntheticDataOnly: true, matter: { id: matterId }, sourceId: attachmentId,
    sourceSha256: source.sha256, cleanUploadAndDownload: true, companyId: 'offline-company', membershipId: 'offline-member' };
  const uploads = {};
  for (const kind of ['txt', 'pdf', 'png', 'jpeg', 'docx']) {
    const bytes = Buffer.from(`Offline ${kind} fixture.\n`), filename = `CaseOps-ios-${kind}-unit.${kind === 'jpeg' ? 'jpg' : kind}`;
    const file = path.join(directory, filename); writeFileSync(file, bytes);
    uploads[kind] = { kind, filename, path: file, sha256: sha(bytes), sizeBytes: bytes.length, ...(kind === 'txt' ? { text: bytes.toString() } : {}), ...(kind === 'pdf' ? { pages: 2 } : {}) };
  }
  const context = { platform: 'ios', driver: { $$: async () => [], waitUntil: async () => {} }, source, filesState: { uploads: {} },
    gatewayBaseline: { runId: 'offline-ios-files' }, fixture: { appId: 'ai.caseops.mobile.dev.simulatoracceptance', environment: 'docker-integration', syntheticDataOnly: true,
      coreInventory: 'native-core-2026-10-25', backendSha: 'a'.repeat(40), webSha: 'a'.repeat(40), binarySourceSha: 'a'.repeat(40),
      apiOrigin: 'https://127.0.0.1:8443', gatewayUrl: 'https://127.0.0.1:8443', gatewayRunId: 'offline-ios-files', udid: '33333333-3333-4333-8333-333333333333',
      matter: { id: matterId }, companyId: 'offline-company', membershipId: 'offline-member', seedEvidence: evidence('seed', seed) },
    assets: { uploads, manifestEvidence: evidence('assets', { syntheticDataOnly: true, assets: Object.values(uploads) }) } };
  const provider = { folderName: 'CaseOps offline fixtures', folderQuery: '-ios predicate string:type == "XCUIElementTypeCell" AND name == "CaseOps offline fixtures"',
    fileQueryTemplate: '-ios predicate string:type == "XCUIElementTypeCell" AND name == {pickerNameJSON}' };
  const deviceInventory = evidence('devices', { devices: { 'com.apple.CoreSimulator.SimRuntime.iOS-26-5': [
    { udid: context.fixture.udid, name: 'CaseOps offline phone', state: 'Booted', isAvailable: true,
      deviceTypeIdentifier: 'com.apple.CoreSimulator.SimDeviceType.iPhone-17' },
  ] } });
  context.assets.providerEvidence = evidence('provider-staging', { kind: 'explicit-synthetic-v2-provider-stage' });
  const picker = { schemaVersion: 2, providerOriginalsRead: false, stagingEvidence: context.assets.providerEvidence, observed: true, platform: 'ios', udid: context.fixture.udid, ...provider,
    localRoot: { label: 'On My iPhone', deviceInventory },
    assets: Object.values(uploads).map((asset) => ({ ...asset, transferSha256: asset.sha256,
      pickerName: asset.filename.slice(0, asset.filename.lastIndexOf('.')) + ', ' + asset.filename.slice(asset.filename.lastIndexOf('.') + 1) })) };
  context.provider = { ...provider, evidence: evidence('picker', picker) };
  return { context, source, seed, uploads, evidence, picker };
}
function measuredFileDriver(context, frameFor = () => ({ x: 20, y: 200, width: 362, height: 52 })) {
  const driver = context.driver, query = driver.$$.bind(driver), scrollId = 'measured-test-scroll';
  const callbacks = new Map();
  let sequence = 0;
  const scroll = { elementId: scrollId, isDisplayed: async () => true, getAttribute: async () => 'XCUIElementTypeScrollView' };
  driver.$$ = async (value) => {
    if (value === '-ios predicate string:type == "XCUIElementTypeScrollView"') return [scroll];
    const matches = (await query(value)).map(control => value.startsWith('~files-') ? { ...control, elementId: value.slice(1),
      getAttribute: async (key) => key === 'name' ? value.slice(1) : key === 'type'
        ? value === '~files-selection' ? 'XCUIElementTypeOther' : ['files-choose','files-upload','files-reload','files-selection-clear'].includes(value.slice(1)) ? 'XCUIElementTypeButton' : 'XCUIElementTypeStaticText'
        : control.getAttribute ? control.getAttribute(key) : key === 'label' ? 'Choose file' : null } : control);
    for (const element of matches) if (typeof element.click === 'function') {
      element.elementId ??= `unit-native-${++sequence}`;
      callbacks.set(element.elementId, element.click.bind(element));
    }
    return matches;
  };
  driver.elementClick = async id => {
    assert.ok(callbacks.has(id), 'UNIT_RESOLVED_NATIVE_ID_REQUIRED');
    await callbacks.get(id)();
  };
  driver.getWindowRect = async () => ({ x: 0, y: 0, width: 402, height: 874 });
  driver.getElementRect = async (id) => id === scrollId ? { x: 0, y: 125, width: 402, height: 638 } : frameFor(id);
}

test('separate frozen iOS files inventory reconciles all17 literal identities without changing Android or core', () => {
  const ids = ['FILES-01','FILES-02','FILES-03','FILES-04','FILES-05','FILES-06','FILES-07','FILES-08','FILES-09','FILES-10','FILES-11','FILES-12','FILES-13','FILES-14','FILES-15','FILES-16','FILES-17'];
  assert.deepEqual(iosFilesInventory.cases.map(({ id }) => id), ids);
  assert.deepEqual(iosFilesScenarios.map(({ id }) => id), ids);
  assert.deepEqual(collectIosFiles().intended, ids.map((id) => `ios:${id}`));
  assert.deepEqual(collectIosFiles().intended, collectIosFiles().discovered);
  assert.ok(iosFilesScenarios.every((scenario) => Object.isFrozen(scenario)));
  assert.ok(iosFilesScenarios.filter(({ requires }) => requires).every(({ requires }) => Object.isFrozen(requires)));
  assert.throws(() => collectIosFiles('android'), /IOS_FILES_PLATFORM_REQUIRED/);
  assert.equal(iosFilesScenarios.at(-1).requiresSignedOut, true);
  assert.deepEqual(iosFilesScenarios[8].requires, ['FILES-05']);
  assert.deepEqual(iosFilesScenarios.flatMap((scenario, index) => scenario.freshAuthentication ? [{ id: scenario.id, index }] : []),
    [{ id: 'FILES-07', index: 6 }, { id: 'FILES-09', index: 8 }]);
  assert.deepEqual(iosFilesScenarios.slice(3, 8).map(({ id }) => id), ['FILES-04', 'FILES-05', 'FILES-06', 'FILES-07', 'FILES-08']);
  const core = JSON.parse(readFileSync(new URL('./core-20261025.json', import.meta.url)));
  assert.equal(core.cases.length, 23);
  assert.equal(core.cases.some(({ id }) => id.startsWith('FILES-')), false);
});
test('current source contract binds actual iOS account, source receipt, TLS and parent without Windows constants', (t) => {
  const { context, source, seed, evidence } = fixture(t);
  assert.equal(validateIosFilesContext(context), source);
  for (const change of [{ platform: 'android' }, { gatewayBaseline: { runId: 'other' } }, { filesState: undefined }, { source: { ...source, attachmentId: matterId } }])
    assert.throws(() => validateIosFilesContext({ ...context, ...change }));
  assert.throws(() => validateIosFilesContext({ ...context, filesState: { uploads: {}, mutationUncertain: true } }), /IOS_FILES_PREVIOUS_UPLOAD_UNCERTAIN_NO_REPLAY/);
  for (const change of [{ membershipId: 'other' }, { sourceSha256: 'b'.repeat(64) }, { sourceId: matterId }]) {
    const fixtureValue = { ...context.fixture, seedEvidence: evidence('wrong-seed', { ...seed, ...change }) };
    assert.throws(() => validateIosFilesContext({ ...context, fixture: fixtureValue }));
  }
  for (const change of [{ appId: 'ai.caseops.mobile' }, { environment: 'production' }, { apiOrigin: 'http://127.0.0.1:8443' }, { webSha: 'b'.repeat(40) }])
    assert.throws(() => validateIosFilesContext({ ...context, fixture: { ...context.fixture, ...change } }));
});
test('exact synthetic text hash and newline bytes cannot be replaced by a filename-only source claim', (t) => {
  const { source } = fixture(t);
  validateSourceAnchor(source);
  for (const change of [{ text: source.text.trimEnd() }, { sizeBytes: 0 }, { filename: '../file.txt' }, { sha256: 'b'.repeat(64) }])
    assert.throws(() => validateSourceAnchor({ ...source, ...change }));
});
test('effective core source provenance binds current member to independently hash-verified original bytes and tenant', (t) => {
  const {context,source,seed,evidence}=fixture(t);
  const base={...seed,membershipId:'original-owner'};
  const baseReference=evidence('original-source-seed',base);
  const effective={environment:'docker-integration',syntheticDataOnly:true,companyId:seed.companyId,membershipId:seed.membershipId,
    matter:seed.matter,provenance:{baseSeed:baseReference}};
  const current={...context.fixture,seedEvidence:evidence('effective-core-seed',effective)};
  assert.equal(validateSourceSeed(current,source),source);
  validateIosFilesContext({...context,fixture:current});
  for(const change of [{companyId:'foreign-tenant'},{matter:{id:attachmentId}},{sourceId:matterId},{sourceSha256:'b'.repeat(64)},{cleanUploadAndDownload:false}]){
    const reference=evidence('wrong-original-source', {...base,...change});
    assert.throws(()=>validateSourceSeed({...current,seedEvidence:evidence('wrong-effective-source',{...effective,provenance:{baseSeed:reference}})},source));
  }
  const changedHash={...baseReference,sha256:'b'.repeat(64)};
  assert.throws(()=>validateSourceSeed({...current,seedEvidence:evidence('changed-original-reference',{...effective,provenance:{baseSeed:changedHash}})},source),/FIXTURE_EVIDENCE_CHANGED/);
  assert.throws(()=>validateSourceSeed({...current,seedEvidence:evidence('contradictory-direct-source',{...effective,sourceId:matterId,sourceSha256:source.sha256})},source));
  assert.throws(()=>validateSourceSeed({...current,seedEvidence:evidence('missing-source',{...effective,provenance:{}})},source),/IOS_FILES_SOURCE_PROVENANCE_REQUIRED/);
});
test('private TXT expectations preserve all three independent literal windows and their exact bytes', () => {
  const text = 'A'.repeat(9999) + '\n' + 'B'.repeat(10000) + 'C'.repeat(4000);
  const segments = textSegments(text);
  assert.deepEqual(segments, ['A'.repeat(9999) + '\n', 'B'.repeat(10000), 'C'.repeat(4000)]);
  assert.equal(segments.join(''), text);
  assert.equal(textSegments('Short source.\n').length, 1);
  assert.equal(textSegments('x'.repeat(500000)).length, 50);
  for (const value of ['', null, 'x'.repeat(500001)]) assert.throws(() => textSegments(value), /IOS_FILES_BOUNDED_TEXT_ORACLE_REQUIRED/);
});
test('all five upload assets require exact manifest and descriptor-bound bytes; missing or changed files fail', (t) => {
  const { context, uploads, evidence } = fixture(t);
  for (const kind of ['txt','pdf','png','jpeg','docx']) assert.equal(validateAsset(context, kind).sha256, uploads[kind].sha256);
  assert.throws(() => validateAsset(context, 'exe'), /IOS_FILES_ASSET_KIND_REQUIRED/);
  assert.throws(() => validateAsset({ ...context, assets: { ...context.assets, uploads: {} } }, 'txt'), /IOS_FILES_VERIFIED_ASSET_REQUIRED/);
  const changed = { ...context, assets: { ...context.assets, uploads: { ...uploads, pdf: { ...uploads.pdf, pages: 1 } } } };
  assert.throws(() => validateAsset(changed, 'pdf'), /IOS_FILES_TWO_PAGE_PDF_REQUIRED/);
  const wrongManifest = { ...context, assets: { ...context.assets, manifestEvidence: evidence('wrong-manifest', { syntheticDataOnly: true, assets: [] }) } };
  assert.throws(() => validateAsset(wrongManifest, 'txt'), /IOS_FILES_ASSET_MANIFEST_MISMATCH/);
  writeFileSync(uploads.txt.path, 'changed bytes');
  assert.throws(() => validateAsset(context, 'txt'), /FIXTURE_EVIDENCE_CHANGED/);
});
test('observed iOS provider binds the same Simulator, folder, exact selectors and actual provider bytes', (t) => {
  const { context, picker, uploads, evidence } = fixture(t);
  assert.equal(validatePickerProvider(context), context.provider);
  assert.equal(validatePickerAsset(context, uploads.txt).pickerName, 'CaseOps-ios-txt-unit, txt');
  for (const change of [{ observed: false }, { platform: 'android' }, { udid: 'other' }, { folderQuery: 'invented' }, { assets: [] }]) {
    const value = { ...context, provider: { ...context.provider, evidence: evidence('wrong-picker', { ...picker, ...change }) } };
    assert.throws(() => validatePickerAsset(value, uploads.txt));
  }
  const provider = { ...context.provider, fileQueryTemplate: '-ios predicate string:name == {pickerNameJSON} OR name == {pickerNameJSON}' };
  provider.evidence = evidence('ambiguous-template', { ...picker, fileQueryTemplate: provider.fileQueryTemplate });
  assert.throws(() => validatePickerProvider({ ...context, provider }), /IOS_FILES_FILENAME_SELECTOR_TEMPLATE_REQUIRED/);
});
test('real observed picker recipe handles retained folder cancellation and extensionless Cell names without a first-match fallback', async (t) => {
  for (const cancel of [true, false]) {
    const { context, uploads } = fixture(t), asset = uploads.txt;
    let state = 'files'; const clicks = [];
    const element = (name, next) => ({ isDisplayed: async () => true, isEnabled: async () => true,
      click: async () => { clicks.push(name); state = next ?? state; } });
    context.driver = {
      async waitUntil(check, options) { if (!await check()) throw new Error(options?.timeoutMsg || 'OFFLINE_CONDITION_FAILED'); },
      async $$(query) {
        if (query === '~files-choose' && state === 'files') return [element('choose', 'folder')];
        if (query.includes('FullDocumentManagerViewControllerNavigationBar')) return ['root','folder'].includes(state) ? [element('bar')] : [];
        if (query.includes('name == "Cancel"')) return state === 'root' ? [element('cancel', 'files')] : [];
        if (query.includes('Actions Menu')) return state === 'folder' && !cancel ? [element('folder-heading')] : [];
        if (query.includes('XCUIElementTypeStaticText') && query.includes('name == "On My iPhone"')) return state === 'root' ? [element('On-My-iPhone-root')] : [];
        if (query.includes('name == "BackButton"')) return state === 'folder' ? [element('back-On-My-iPhone', 'root')] : [];
        if (query.includes('name == "Browse"')) return state === 'root' ? [element('browse')] : [];
        if (query === context.provider.folderQuery) return state === 'root' ? [element('folder', 'folder')] : [];
        if (query.includes('name == "CaseOps-ios-txt-unit, txt"')) return state === 'folder' ? [element('exact-provider-file', 'selected')] : [];
        if (query === '~files-matter-code') return ['files','selected'].includes(state) ? [element('matter-code')] : [];
        if (query === '~files-selection' || query === '~files-upload' || query.includes(`label == "${asset.filename}"`)) return state === 'selected' ? [element('selected-source')] : [];
        return [];
      },
    };
    measuredFileDriver(context);
    await chooseIosFile(context, { ...asset, kind: 'txt' }, { cancel });
    assert.equal(state, cancel ? 'files' : 'selected');
    assert.deepEqual(clicks, cancel ? ['choose','back-On-My-iPhone','cancel'] : ['choose','exact-provider-file']);
    assert.equal(clicks.filter((value) => value === 'exact-provider-file').length, cancel ? 0 : 1);
  }
});
test('iOS 27 history Back leaves a retained folder for the exact observed root before cancelling', async (t) => {
  const { context } = fixture(t);
  let state = 'files'; const clicks = [];
  const element = (name, next) => ({ isDisplayed: async () => true, isEnabled: async () => true,
    click: async () => { clicks.push(name); state = next ?? state; } });
  context.driver = {
    async waitUntil(check, options) { if (!await check()) throw new Error(options?.timeoutMsg || 'OFFLINE_CONDITION_FAILED'); },
    async $$(query) {
      if (query === '~files-choose' && state === 'files') return [element('choose', 'folder')];
      if (query.includes('FullDocumentManagerViewControllerNavigationBar')) return ['root','folder'].includes(state) ? [element('bar')] : [];
      if (query.includes('name == "Cancel"')) return state === 'root' ? [element('cancel', 'files')] : [];
      // No parent-labelled BackButton exists; only the history control does.
      if (query.includes('name == "DOC.navBarButton.backInHistory" AND label == "Back"')) return state === 'folder' ? [element('history-back', 'root')] : [];
      if (query.includes('XCUIElementTypeStaticText') && query.includes('name == "On My iPhone"')) return state === 'root' ? [element('On-My-iPhone-root')] : [];
      if (query === '~files-matter-code') return state === 'files' ? [element('matter-code')] : [];
      return [];
    },
  };
  measuredFileDriver(context);
  await chooseIosFile(context, undefined, { cancel: true });
  assert.equal(state, 'files');
  assert.deepEqual(clicks, ['choose', 'history-back', 'cancel']);
});
function ios27PickerDouble(context, initial) {
  let state = 'files'; const clicks = [];
  const element = (name, next) => ({ isDisplayed: async () => true, isEnabled: async () => true,
    click: async () => { clicks.push(name); state = next ?? state; } });
  context.driver = {
    async waitUntil(check, options) { if (!await check()) throw new Error(options?.timeoutMsg || 'OFFLINE_CONDITION_FAILED'); },
    async $$(query) {
      if (query === '~files-choose' && state === 'files') return [element('choose', initial)];
      if (query.includes('FullDocumentManagerViewControllerNavigationBar')) return ['root','locations','folder','old-folder'].includes(state) ? [element('bar')] : [];
      // iOS 27 shows history Back at the root too; it leads to Locations.
      if (query.includes('name == "DOC.navBarButton.backInHistory"')) return ['root','folder','old-folder'].includes(state) ? [element('history-back', 'locations')] : [];
      if (query.includes('name == "DOC.sidebar.item.On My iPhone"')) return state === 'locations' ? [element('location', 'root')] : [];
      // The Locations cell repeats the root's name as a StaticText.
      if (query.includes('XCUIElementTypeStaticText') && query.includes('name == "On My iPhone"')) return ['root','locations'].includes(state) ? [element('root-text')] : [];
      if (query === context.provider.folderQuery) return state === 'root' ? [element('owned-folder', 'folder')] : [];
      if (query.includes('Actions Menu')) return state === 'folder' ? [element('owned-folder-heading')] : [];
      if (query.includes('name == "CaseOps-ios-txt-unit, txt"')) return state === 'folder' ? [element('exact-owned-file', 'selected')] : [];
      if (query === '~files-matter-code') return ['files','selected'].includes(state) ? [element('matter-code')] : [];
      if (query === '~files-selection' || query === '~files-upload' || query.includes('label == "')) return state === 'selected' ? [element('selection')] : [];
      return [];
    },
  };
  measuredFileDriver(context);
  return { clicks, state: () => state };
}
test('iOS 27 picker opened at the root goes straight to the owned folder without history Back', async (t) => {
  const { context, uploads } = fixture(t), fake = ios27PickerDouble(context, 'root');
  await chooseIosFile(context, { ...uploads.txt, kind: 'txt' });
  assert.equal(fake.state(), 'selected');
  assert.deepEqual(fake.clicks, ['choose', 'owned-folder', 'exact-owned-file']);
});
test('iOS 27 retained folder whose history Back lands on Locations still reaches the exact root', async (t) => {
  const { context, uploads } = fixture(t), fake = ios27PickerDouble(context, 'old-folder');
  await chooseIosFile(context, { ...uploads.txt, kind: 'txt' });
  assert.equal(fake.state(), 'selected');
  assert.deepEqual(fake.clicks, ['choose', 'history-back', 'location', 'owned-folder', 'exact-owned-file']);
});
test('iOS 27 Locations list opens the local location cell, never treating its label as the root', async (t) => {
  const { context, uploads } = fixture(t), fake = ios27PickerDouble(context, 'locations');
  await chooseIosFile(context, { ...uploads.txt, kind: 'txt' });
  assert.equal(fake.state(), 'selected');
  assert.deepEqual(fake.clicks, ['choose', 'location', 'owned-folder', 'exact-owned-file']);
});
function pickerRouteDouble(context, asset, initial, { duplicateLocation = false, unknownAfterBrowse = false,
  localRootLabel = 'On My iPhone', actualRootLabel = localRootLabel } = {}) {
  const rootToken = actualRootLabel.replaceAll(' ', '-');
  let state = 'files';
  const clicks = [];
  const element = (name, next) => ({ isDisplayed: async () => true, isEnabled: async () => true,
    click: async () => { clicks.push(name); state = next ?? state; } });
  context.driver = {
    async waitUntil(check, options) { if (!await check()) throw new Error(options?.timeoutMsg || 'OFFLINE_PICKER_STATE_NOT_READY'); },
    async $$(query) {
      if (query === '~files-choose' && state === 'files') return [element('choose', initial)];
      if (query === '~files-selection-clear' && state === 'selected') return [element('clear-selection', 'files')];
      if (query.includes('FullDocumentManagerViewControllerNavigationBar')) return !['files','selected'].includes(state) ? [element('bar')] : [];
      if (query.includes('name == "Cancel"')) return ['root','locations'].includes(state) ? [element('cancel', 'files')] : [];
      if (query.includes('Actions Menu')) return state === 'folder' ? [element('owned-folder-heading')] : [];
      if (query.includes('name == "BackButton"') && query.includes(`label == ${JSON.stringify(actualRootLabel)}`)) return state === 'old-folder' ? [element(`back-${rootToken}`, 'root')] : [];
      if (query.includes(`name == ${JSON.stringify(`DOC.sidebar.item.${actualRootLabel}`)}`)) return state === 'locations'
        ? Array.from({ length: duplicateLocation ? 2 : 1 }, () => element(`${rootToken}-location`, 'root')) : [];
      if (query.includes('XCUIElementTypeStaticText') && query.includes(`name == ${JSON.stringify(actualRootLabel)}`)) return state === 'root' ? [element(`${rootToken}-root`)] : [];
      if (query.includes('name == "Browse"')) return state === 'recents' ? [element('browse', unknownAfterBrowse ? 'unknown-provider' : 'locations')] : [];
      if (query === context.provider.folderQuery) return state === 'root' ? [element('owned-folder', 'folder')] : [];
      if (query.includes('name == "CaseOps-ios-txt-unit, txt"')) return state === 'folder' ? [element('exact-owned-file', 'selected')] : [];
      if (query === '~files-matter-code') return ['files','selected'].includes(state) ? [element('matter-code')] : [];
      if (query === '~files-selection' || query === '~files-upload' || query.includes(`label == "${asset.filename}"`)) return state === 'selected' ? [element('selection')] : [];
      return [];
    },
  };
  measuredFileDriver(context);
  return { clicks, state: () => state };
}
function repeatSelectionFixture(t) {
  const f = fixture(t), fake = pickerRouteDouble(f.context, f.uploads.txt, 'folder');
  const before = { runId: f.context.fixture.gatewayRunId, lastSequence: 0, requests: [] };
  const ledger = { ...before, lastSequence: 1, markerRejected: 0, routeRejected: 0, overflow: false,
    requests: [{ sequence: 1, method: 'GET', route: `/api/matters/${matterId}/workspace`, status: 200, nativeMarker: true }] };
  f.context.gatewayBaseline = gatewayBaseline({ ...ledger, lastSequence: 0, requests: [] }, { gatewayRunId: ledger.runId });
  const fetch = globalThis.fetch; t.after(() => { globalThis.fetch = fetch; });
  globalThis.fetch = async () => new Response(JSON.stringify(ledger), { status: 200 });
  const boundaries = [];
  f.context.observeFilesystem = async boundary => { boundaries.push({ boundary, clicks: [...fake.clicks] }); return f.evidence('repeat-privacy', {
    schemaVersion: 2, observed: true, platform: 'ios', udid: f.context.fixture.udid, bundleId: f.context.fixture.appId,
    boundary, ownedAppScopeOnly: true, providerOriginalsUnchanged: null, providerMetadataUnchanged: true,
    providerOriginalsRead: false, providerByteVerification: 'deferred-until-postflight', stagedFileCount: 0, privateByteMatchCount: 0 }); };
  return { ...f, fake, before, ledger, boundaries };
}
test('repeat selection composes exact picker and single clear commands twice with cold cleanup between selections', async t => {
  const f = repeatSelectionFixture(t); await repeatIosFileSelection(f.context, f.before);
  assert.deepEqual(f.fake.clicks, ['choose','exact-owned-file','clear-selection','choose','exact-owned-file','clear-selection']);
  assert.equal(f.fake.state(), 'files'); assert.deepEqual(f.boundaries.map(row => row.boundary), ['selection-clear-first','selection-clear']);
  assert.equal(f.boundaries[0].clicks.filter(value => value === 'choose').length, 1);
  assert.ok(f.ledger.requests.every(row => row.method === 'GET'));
});
test('lost first clear acknowledgement stops repeat selection without another click or fabricated cleanup', async t => {
  const f = repeatSelectionFixture(t), click = f.context.driver.elementClick, lost = Error('SYNTHETIC_CLEAR_ACK_UNKNOWN'); let clears = 0;
  f.context.driver.elementClick = async id => { await click(id); if (id === 'files-selection-clear') { clears++; throw lost; } };
  await assert.rejects(repeatIosFileSelection(f.context, f.before), error => error === lost);
  assert.equal(clears, 1); assert.deepEqual(f.fake.clicks, ['choose','exact-owned-file','clear-selection']); assert.deepEqual(f.boundaries, []);
});
test('picker selection follows only observed old-folder, On My iPhone, Locations and single-Browse routes to the exact owned file', async (t) => {
  for (const [initial, expected] of [
    ['folder', ['choose','exact-owned-file']],
    ['old-folder', ['choose','back-On-My-iPhone','owned-folder','exact-owned-file']],
    ['root', ['choose','owned-folder','exact-owned-file']],
    ['locations', ['choose','On-My-iPhone-location','owned-folder','exact-owned-file']],
    ['recents', ['choose','browse','On-My-iPhone-location','owned-folder','exact-owned-file']],
  ]) {
    const { context, uploads } = fixture(t), asset = uploads.txt;
    const fake = pickerRouteDouble(context, asset, initial);
    await chooseIosFile(context, asset);
    assert.equal(fake.state(), 'selected');
    assert.deepEqual(fake.clicks, expected);
    assert.equal(fake.clicks.filter((name) => name === 'exact-owned-file').length, 1);
    assert.ok(fake.clicks.length <= 5);
  }
});
test('picker local root binds exact booted device family and inventory bytes without guessing a display name', (t) => {
  const { context, picker, evidence } = fixture(t);
  const runtime = 'com.apple.CoreSimulator.SimRuntime.iOS-26-5';
  const device = { udid: context.fixture.udid, name: 'Renamed iPhone display name', state: 'Booted', isAvailable: true,
    deviceTypeIdentifier: 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-11-inch-M5-12GB' };
  const bind = (value, inventory = { devices: { [runtime]: [device] } }) => ({ ...context, provider: { ...context.provider,
    evidence: evidence('device-root', { ...picker, localRoot: { label: 'On My iPad', deviceInventory: evidence('device-inventory', inventory) }, ...value }) } });
  assert.equal(validatePickerProvider(bind({})).folderName, context.provider.folderName);
  for (const inventory of [
    { devices: { [runtime]: [{ ...device, udid: '44444444-4444-4444-8444-444444444444' }] } },
    { devices: { [runtime]: [device, device] } },
    { devices: { [runtime]: [device], 'com.apple.CoreSimulator.SimRuntime.iOS-27-0': [device] } },
    { devices: { [runtime]: [{ ...device, state: 'Shutdown' }] } },
    { devices: { [runtime]: [{ ...device, isAvailable: false }] } },
    { devices: { [runtime]: [{ ...device, deviceTypeIdentifier: 'com.apple.CoreSimulator.SimDeviceType.Apple-TV-4K' }] } },
    { devices: { [runtime]: [{ ...device, deviceTypeIdentifier: 'iPad-Pro-11-inch' }] } },
    { devices: { 'com.apple.CoreSimulator.SimRuntime.tvOS-27-0': [device] } },
  ]) assert.throws(() => validatePickerProvider(bind({}, inventory)));
  for (const label of ['On My iPhone', 'On my iPad', 'iCloud Drive', '', ['On My iPad']]) {
    const current = bind({}), proof = JSON.parse(readFileSync(current.provider.evidence.path));
    current.provider.evidence = evidence('wrong-local-root', { ...proof, localRoot: { ...proof.localRoot, label } });
    assert.throws(() => validatePickerProvider(current), /IOS_FILES_OBSERVED_LOCAL_ROOT_MISMATCH/);
  }
  assert.throws(() => validatePickerProvider(bind({ localRoot: undefined })), /IOS_FILES_OBSERVED_LOCAL_ROOT_REQUIRED/);
  const changed = bind({}), proof = JSON.parse(readFileSync(changed.provider.evidence.path));
  changed.provider.evidence = evidence('wrong-inventory-hash', { ...proof,
    localRoot: { ...proof.localRoot, deviceInventory: { ...proof.localRoot.deviceInventory, sha256: 'b'.repeat(64) } } });
  assert.throws(() => validatePickerProvider(changed), /FIXTURE_EVIDENCE_CHANGED/);
  const replaced = bind({}), replacement = JSON.parse(readFileSync(replaced.provider.evidence.path));
  writeFileSync(replacement.localRoot.deviceInventory.path, '{}');
  assert.throws(() => validatePickerProvider(replaced), /FIXTURE_EVIDENCE_CHANGED/);
});
function ipadPickerFixture(t) {
  const value = fixture(t), { context, picker, evidence } = value;
  const inventory = evidence('ipad-inventory', { devices: { 'com.apple.CoreSimulator.SimRuntime.iOS-26-5': [
    { udid: context.fixture.udid, name: 'CaseOps tablet', state: 'Booted', isAvailable: true,
      deviceTypeIdentifier: 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-11-inch-M5-12GB' },
  ] } });
  context.provider.evidence = evidence('ipad-observation', { ...picker, localRoot: { label: 'On My iPad', deviceInventory: inventory } });
  return value;
}
test('device-bound iPad picker selection and cancellation use only exact tablet root controls within the original action bound', async (t) => {
  for (const [initial, expected] of [
    ['folder', ['choose','exact-owned-file']],
    ['old-folder', ['choose','back-On-My-iPad','owned-folder','exact-owned-file']],
    ['root', ['choose','owned-folder','exact-owned-file']],
    ['locations', ['choose','On-My-iPad-location','owned-folder','exact-owned-file']],
    ['recents', ['choose','browse','On-My-iPad-location','owned-folder','exact-owned-file']],
  ]) {
    const { context, uploads } = ipadPickerFixture(t), asset = uploads.txt;
    const fake = pickerRouteDouble(context, asset, initial, { localRootLabel: 'On My iPad' });
    await chooseIosFile(context, asset);
    assert.deepEqual(fake.clicks, expected);
    assert.equal(fake.state(), 'selected');
    assert.equal(fake.clicks.filter((name) => name === 'exact-owned-file').length, 1);
    assert.ok(fake.clicks.length <= 5);
  }
  for (const initial of ['old-folder','root','locations']) {
    const { context, uploads } = ipadPickerFixture(t);
    const fake = pickerRouteDouble(context, uploads.txt, initial, { localRootLabel: 'On My iPad' });
    await chooseIosFile(context, uploads.txt, { cancel: true });
    assert.equal(fake.state(), 'files');
    assert.deepEqual(fake.clicks, initial === 'old-folder' ? ['choose','back-On-My-iPad','cancel'] : ['choose','cancel']);
  }
});
test('iPad picker rejects ambiguous or mismatched actual root controls before any owned-folder or file selection', async (t) => {
  for (const [options, reason] of [
    [{ duplicateLocation: true }, 'AMBIGUOUS_VISIBLE_NATIVE_LOCATOR'],
    [{ actualRootLabel: 'On My iPhone' }, 'NATIVE_CONTROL_NOT_VISIBLE'],
  ]) {
    const { context, uploads } = ipadPickerFixture(t), asset = uploads.txt;
    const fake = pickerRouteDouble(context, asset, 'locations', { localRootLabel: 'On My iPad', ...options });
    await assert.rejects(chooseIosFile(context, asset), new RegExp(reason));
    assert.equal(fake.clicks.includes('exact-owned-file'), false);
    assert.equal(fake.clicks.includes('owned-folder'), false);
    assert.ok(fake.clicks.filter((name) => name === 'browse').length <= 1);
  }
});
test('picker cancellation is cohort-independent while duplicate and unknown location states never select a file', async (t) => {
  for (const initial of ['old-folder','root','locations']) {
    const { context, uploads } = fixture(t), asset = uploads.txt;
    const fake = pickerRouteDouble(context, asset, initial);
    await chooseIosFile(context, asset, { cancel: true });
    assert.equal(fake.state(), 'files');
    assert.deepEqual(fake.clicks, initial === 'old-folder' ? ['choose','back-On-My-iPhone','cancel'] : ['choose','cancel']);
  }
  for (const [initial, options, reason] of [
    ['locations', { duplicateLocation: true }, 'AMBIGUOUS_VISIBLE_NATIVE_LOCATOR'],
    ['recents', { unknownAfterBrowse: true }, 'IOS_FILES_KNOWN_PICKER_LOCATION_REQUIRED'],
  ]) {
    const { context, uploads } = fixture(t), asset = uploads.txt;
    const fake = pickerRouteDouble(context, asset, initial, options);
    await assert.rejects(chooseIosFile(context, asset), new RegExp(reason));
    assert.equal(fake.clicks.includes('exact-owned-file'), false);
    assert.equal(fake.clicks.includes('owned-folder'), false);
    assert.ok(fake.clicks.filter((name) => name === 'browse').length <= 1);
  }
});
test('selection proof binds a hidden typed marker to its visible exact filename and enabled upload control', async (t) => {
  for (const change of ['hidden-marker','duplicate-marker','wrong-frame','missing-name','missing-upload']) {
    const {context,uploads}=fixture(t),asset=uploads.txt;
    pickerRouteDouble(context,asset,'folder');
    const query=context.driver.$$,rect=context.driver.getElementRect;
    context.driver.$$=async(value)=>{
      const controls=await query(value);
      if(value==='~files-selection')return change==='duplicate-marker'?[...controls,...controls]:controls.map(control=>({...control,isDisplayed:async()=>assert.fail('STRUCTURAL_SELECTION_VISIBILITY_MUST_NOT_BE_USED')}));
      if(change==='missing-upload'&&value==='~files-upload'||change==='missing-name'&&value.includes(`label == "${asset.filename}"`))return [];
      return controls;
    };
    context.driver.getElementRect=async(id)=>change==='wrong-frame'&&id==='files-selection'?{x:20,y:400,width:362,height:52}:rect(id);
    if(change==='hidden-marker')await chooseIosFile(context,asset);
    else await assert.rejects(chooseIosFile(context,asset));
  }
});
test('known Files footer and picker-return heading directions reach a four-swipe boundary without changing locator uniqueness', async (t) => {
  const { context, uploads } = fixture(t), asset=uploads.txt;
  let state='files',offset=0; const directions=[];
  const element=(shown,next)=>({isDisplayed:async()=>shown(),isEnabled:async()=>true,click:async()=>{if(next)state=next;}});
  const scroll={elementId:'outer-scroll',isDisplayed:async()=>true,getAttribute:async()=> 'XCUIElementTypeScrollView'};
  context.driver={
    async waitUntil(check,options){if(!await check())throw new Error(options?.timeoutMsg||'OFFLINE_CONDITION_FAILED');},
    async getWindowRect(){return {x:0,y:0,width:402,height:874};},
    async getElementRect(){return {x:0,y:125,width:402,height:691};},
    async performActions(actions){
      const points=actions[0].actions.filter(({type})=>type==='pointerMove');
      const direction=points[0].y>points[1].y?'down':'up';directions.push(direction);
      offset=Math.max(0,Math.min(4,offset+(direction==='down'?1:-1)));
    },
    async releaseActions(){},
    async $$(query){
      if(query.includes('XCUIElementTypeScrollView'))return [scroll];
      if(query==='~files-choose'&&state==='files')return [element(()=>offset===4,'folder')];
      if(query.includes('FullDocumentManagerViewControllerNavigationBar'))return state==='folder'?[element(()=>true)]:[];
      if(query.includes('Actions Menu'))return state==='folder'?[element(()=>true)]:[];
      if(query.includes('name == "CaseOps-ios-txt-unit, txt"'))return state==='folder'?[element(()=>true,'selected')]:[];
      if(query==='~files-matter-code')return state==='selected'?[element(()=>offset===0)]:[];
      if(query==='~files-selection'||query==='~files-upload'||query.includes(`label == "${asset.filename}"`))return state==='selected'?[element(()=>offset===4)]:[];
      return [];
    },
  };
  measuredFileDriver(context,(id)=>({x:20,y:id==='files-matter-code'?200-offset*200:700+(4-offset)*200,width:362,height:52}));
  await chooseIosFile(context,{...asset,kind:'txt'});
  assert.equal(state,'selected');
  assert.deepEqual(directions,[...Array(4).fill('down'),...Array(4).fill('up'),...Array(4).fill('down')]);
  assert.ok(directions.length===12,'each proven boundary uses four of its original nine allowed swipes');
});
test('source-details disclosure uses the actual unique SwiftUI button label without a child-text fallback', async () => {
  for (const label of ['Source details','Hide source details']) {
    let clicks=0;
    const button = { elementId: 'exact-source-details', getAttribute: async (key) => key === 'type' ? 'XCUIElementTypeButton' : key === 'accessible' ? 'true' : label,
      isEnabled: async () => true, click: async () => assert.fail('ELEMENT_MONAD_CLICK_FORBIDDEN'), $$: () => assert.fail('IOS_CHILD_TEXT_MUST_NOT_BE_INVENTED') };
    await expandIosSourceDetails({ driver: { elementClick: async id => { assert.equal(id, button.elementId); clicks++; } } }, button); assert.equal(clicks, label === 'Source details' ? 1 : 0);
  }
  for (const label of ['Delete','',null]) {
    let clicks=0;
    await assert.rejects(expandIosSourceDetails({ driver: { elementClick: async () => { clicks++; } } }, { getAttribute: async (key) => key === 'type' ? 'XCUIElementTypeButton' : key === 'accessible' ? 'true' : label,
      isEnabled: async () => true, click: async () => { clicks++; } }), /IOS_FILES_DETAILS_STATE_REQUIRED/);
    assert.equal(clicks,0);
  }
});
test('exact Files facts scroll from measured target and viewport geometry while preserving uniqueness and nine-swipe bounds', async () => {
  const fake = ({ y = -79, shift = 200, duplicate = false, hidden = false, type = 'XCUIElementTypeButton' } = {}) => {
    const directions = [], id = 'files-source-exact', viewport = { x: 0, y: 125, width: 402, height: 638 };
    const target = { elementId: id, getAttribute: async (key) => key === 'name' ? id : type,
      isDisplayed: async () => !hidden && y >= 125 && y + 51 <= 763 };
    const scroll = { elementId: 'scroll', isDisplayed: async () => true, getAttribute: async () => 'XCUIElementTypeScrollView' };
    const context = { platform: 'ios', driver: {
      $$: async (query) => query === `~${id}` ? duplicate ? [target,target] : [target]
        : query === '-ios predicate string:type == "XCUIElementTypeScrollView"' ? [scroll] : [],
      getWindowRect: async () => ({ x: 0, y: 0, width: 402, height: 874 }),
      getElementRect: async (elementId) => elementId === 'scroll' ? viewport : ({ x: 127, y, width: 149, height: 51 }),
      waitUntil: async (condition, options) => { if (!await condition()) throw new Error(options.timeoutMsg); },
      performActions: async (actions) => {
        const points = actions[0].actions.filter(({ type }) => type === 'pointerMove');
        assert.equal(points[1].duration,650);
        assert.ok(Math.abs(points[1].y-points[0].y)>=44 && Math.abs(points[1].y-points[0].y)<=574);
        assert.ok(points.every(({y})=>y>125&&y<763));
        assert.equal(points[0].x,8);assert.equal(points[1].x,8);
        const direction = points[0].y > points[1].y ? 'down' : 'up';
        directions.push(direction); y += direction === 'up' ? shift : -shift;
      }, releaseActions: async () => {},
    } };
    return { context, id, target, directions };
  };
  for (const [y, expected] of [[-79,['up','up']], [900,['down']]]) {
    const value = fake({ y });
    assert.equal(await findIosFileFact(value.context, value.id, 'XCUIElementTypeButton'), value.target);
    assert.deepEqual(value.directions, expected);
  }
  const far = fake({y:3000,shift:500});
  await findIosFileFact(far.context,far.id,'XCUIElementTypeButton');
  assert.deepEqual(far.directions,Array(5).fill('down'));
  for (const options of [{ duplicate: true }, { hidden: true, y: 300 }, { type: 'XCUIElementTypeOther' }]) {
    const value = fake(options);
    await assert.rejects(findIosFileFact(value.context, value.id, 'XCUIElementTypeButton'));
    assert.deepEqual(value.directions, []);
  }
  const oscillating = fake({ shift: 1000 });
  await assert.rejects(findIosFileFact(oscillating.context, oscillating.id, 'XCUIElementTypeButton'), /IOS_FILES_FACT_NOT_VISIBLE/);
  assert.equal(oscillating.directions.length, 9);
  assert.deepEqual(oscillating.directions, ['up','down','up','down','up','down','up','down','up']);
});
test('one canonical attachment acknowledgement remains exact with a legitimate refresh and rejects every extra formal write', () => {
  const upload={method:'POST',route:`/api/matters/${matterId}/attachments`,status:200,requestId:'offline-upload'},
    read={method:'GET',route:`/api/matters/${matterId}/workspace`,status:200},
    refresh={method:'POST',route:'/api/auth/native/refresh',status:200};
  assert.equal(validateIosUploadAcknowledgement([refresh,upload,read],matterId,{requireRead:true}),upload);
  for(const rows of [[],[upload,upload,read],[{...upload,status:201},read],
    [upload,read,{method:'POST',route:`/api/matters/${matterId}/notes`,status:200}],
    [upload,read,{method:'DELETE',route:`/api/matters/${matterId}/attachments`,status:200}],
    [upload,read,{...refresh,status:403}]])assert.throws(()=>validateIosUploadAcknowledgement(rows,matterId,{requireRead:true}));
  assert.throws(()=>validateIosUploadAcknowledgement([upload,refresh],matterId,{requireRead:true}),/READ_ONLY_READ_MISSING/);
});
test('rapid upload uses two measured native touches in one dispatch and never retries a lost acknowledgement', async () => {
  const make=()=>{
    const calls=[],events=[],button={elementId:'native-upload',getAttribute:async(key)=>key==='name'?'files-upload':'XCUIElementTypeButton',isDisplayed:async()=>true,isEnabled:async()=>true};
    const context={platform:'ios',record:event=>events.push(event),driver:{getWindowRect:async()=>({x:0,y:0,width:402,height:874}),getElementRect:async()=>({x:140,y:690,width:122,height:51}),performActions:async(actions)=>calls.push(actions),releaseActions:async()=>calls.push('release')}};
    return{calls,events,button,context};
  };
  const good=make();await rapidActivateIosUpload(good.context,good.button);
  const input=good.calls[0][0];assert.equal(input.parameters.pointerType,'touch');
  assert.deepEqual(input.actions.map(({type})=>type),['pointerMove','pointerDown','pointerUp','pause','pointerDown','pointerUp']);
  assert.deepEqual(input.actions[0],{type:'pointerMove',duration:0,x:201,y:715});assert.equal(input.actions[3].duration,10);
  assert.equal(good.calls.length,2);assert.equal(good.calls[1],'release');
  assert.equal(good.events.filter(({action})=>action==='click').length,1);
  const lost=make(),original=new Error('LOST_NATIVE_ACK');let dispatches=0;
  lost.context.driver.performActions=async()=>{dispatches++;throw original;};
  await assert.rejects(rapidActivateIosUpload(lost.context,lost.button),error=>error===original);
  assert.equal(dispatches,1);assert.deepEqual(lost.calls,['release']);
  const offscreen=make();offscreen.context.driver.getElementRect=async()=>({x:140,y:-20,width:122,height:51});
  await assert.rejects(rapidActivateIosUpload(offscreen.context,offscreen.button),/IOS_FILES_UPLOAD_INPUT_GEOMETRY_REQUIRED/);assert.deepEqual(offscreen.calls,[]);
});
test('privacy acceptance rejects wrong device, unowned scans, altered originals and even one retained private byte match', (t) => {
  const { context } = fixture(t), boundary='selection-clear';
  const receipt = { schemaVersion: 2, observed: true, platform: 'ios', udid: context.fixture.udid, bundleId: context.fixture.appId,
    boundary, ownedAppScopeOnly: true, providerOriginalsUnchanged: null, providerMetadataUnchanged: true, providerOriginalsRead: false, providerByteVerification: 'deferred-until-postflight', stagedFileCount: 0, privateByteMatchCount: 0 };
  assert.equal(validatePrivacyReceipt(context,boundary,receipt),receipt);
  for (const change of [{ observed:false }, {udid:'other'}, {boundary:'other'}, {ownedAppScopeOnly:false}, {providerOriginalsUnchanged:false}, {stagedFileCount:1}, {privateByteMatchCount:1}])
    assert.throws(()=>validatePrivacyReceipt(context,boundary,{...receipt,...change}));
});
test('picker cancel includes authoritative entry read even when the actual chooser emits no HTTP', async (t) => {
  const {context,evidence}=fixture(t);
  context.fixture.matter={id:matterId,identityLabel:'OFFLINE-001',title:'Synthetic offline matter',search:'OFFLINE-001'};
  const ledger={runId:context.fixture.gatewayRunId,lastSequence:0,requests:[],markerRejected:0,routeRejected:0,overflow:false};
  context.gatewayBaseline=gatewayBaseline(ledger,{gatewayRunId:ledger.runId});
  const oldFetch=globalThis.fetch,reads=[];t.after(()=>{globalThis.fetch=oldFetch;});
  globalThis.fetch=async(url,options)=>{
    assert.equal(url,context.fixture.gatewayUrl+'/__caseops_e2e/status');
    assert.equal(options.headers['X-CaseOps-Automated-Test'],'no-paid-providers');
    reads.push(ledger.lastSequence);
    return new Response(JSON.stringify(ledger),{status:200,headers:{'content-type':'application/json'}});
  };
  let ui='home',cancelled=0;
  const control=(text='',clicked)=>({isDisplayed:async()=>true,isEnabled:async()=>true,getText:async()=>text,
    getAttribute:async(key)=>key==='label'?'Choose file':null,setValue:async()=>{},click:async()=>{clicked?.();}});
  const files=Object.assign(control('',()=>{
    ui='files';ledger.requests.push({sequence:++ledger.lastSequence,method:'GET',route:`/api/matters/${matterId}/workspace`,status:200,nativeMarker:true});
  }),{elementId:'scoped-files-section'});
  // iOS input focuses this field, waits for the keyboard and reads its text back.
  let typed='';
  const search=Object.assign(control(),{elementId:'matter-search-field',clearValue:async()=>{typed='';},
    addValue:async(value)=>{typed+=value;},getAttribute:async(key)=>key==='value'?typed:null});
  context.driver={
    async pause(){},
    async waitUntil(check,options){if(!await check())throw new Error(options?.timeoutMsg||'OFFLINE_UI_NOT_READY');},
    async $$(query){
      if(query==='~account-open')return [control()];
      if(query==='~tab-matters')return [control('',()=>{ui='matters';})];
      if(query==='~screen-matters')return ui==='matters'?[control()]:[];
      if(query==='~matter-search')return [search];
      if(query==='~matter-search-submit')return [control()];
      if(query==='-ios predicate string:type == "XCUIElementTypeKeyboard"')return [control()];
      if(query===`~matter-row-${matterId}`)return [control('',()=>{ui='matter';})];
      if(query==='~matter-code'||query==='~files-matter-code')return [control('OFFLINE-001')];
      if(query.includes('label == "Synthetic offline matter"')||query==='~files-matter-title')return [control('Synthetic offline matter')];
      if(query.includes('XCUIElementTypeSegmentedControl'))return [{...control(),$$:async()=>[files]}];
      if(query==='~files-choose')return [control('',()=>{ui='picker';})];
      if(query.includes('FullDocumentManagerViewControllerNavigationBar'))return ui==='picker'?[control()]:[];
      if(query.includes('name == "Cancel"'))return ui==='picker'?[control('',()=>{ui='files';cancelled++;})]:[];
      return [];
    },
  };
  context.observeFilesystem=async(boundary)=>evidence('cancel-privacy',{schemaVersion:2,observed:true,platform:'ios',udid:context.fixture.udid,
    bundleId:context.fixture.appId,boundary,ownedAppScopeOnly:true,providerOriginalsUnchanged:null,providerMetadataUnchanged:true,providerOriginalsRead:false,providerByteVerification:'deferred-until-postflight',stagedFileCount:0,privateByteMatchCount:0});
  measuredFileDriver(context);
  const protocolClick=context.driver.elementClick;
  context.driver.elementClick=async id=>id===files.elementId?files.click():protocolClick(id);
  await iosFilesScenarios.find(({id})=>id==='FILES-02').run(context);
  assert.equal(cancelled,1);
  assert.deepEqual(reads,[0,1],'readonly interval must begin before entry, rather than requiring a fake chooser request');
  assert.equal(ledger.requests.length,1);assert.equal(ledger.requests[0].method,'GET');
});
function markerFixture() {
  const nodes=new Map(),rects=new Map();
  const add=(id,type,rect,{label=id,text=label,displayed=true,marker=false}={})=>{
    const element={elementId:id,getAttribute:async(key)=>key==='name'?id:key==='type'?type:key==='label'?label:null,
      isDisplayed:async()=>{assert.equal(marker,false,'STRUCTURAL_MARKER_VISIBILITY_MUST_NOT_BE_USED');return displayed;},getText:async()=>text};
    nodes.set(id,[element]);rects.set(id,rect);return element;
  };
  add('private-document-viewer','XCUIElementTypeOther',{x:0,y:62,width:402,height:778},{marker:true});
  add('viewer-filename','XCUIElementTypeStaticText',{x:60,y:79,width:334,height:26},{label:'mobile-source.txt'});
  add('viewer-close','XCUIElementTypeButton',{x:8,y:70,width:44,height:44},{label:'Return to Files'});
  add('viewer-toolbar','XCUIElementTypeOther',{x:0,y:123,width:402,height:53});
  add('files-upload-persisted','XCUIElementTypeOther',{x:20,y:529,width:362,height:74},{marker:true});
  const message=add('ack-text','XCUIElementTypeStaticText',{x:20,y:529,width:362,height:74},{label:IOS_UPLOAD_PERSISTED_MESSAGE});
  const context={platform:'ios',driver:{
    async $$(query){if(query=== '-ios predicate string:label == '+JSON.stringify(IOS_UPLOAD_PERSISTED_MESSAGE)+' OR value == '+JSON.stringify(IOS_UPLOAD_PERSISTED_MESSAGE))return nodes.get('ack-text')||[];
      return nodes.get(query.slice(1))||[];},
    async getWindowRect(){return {x:0,y:0,width:402,height:874};},
    async getElementRect(id){return rects.get(id);},
    async waitUntil(check,options){if(!await check())throw new Error(options?.timeoutMsg||'OFFLINE_FACT_NOT_READY');},
  }};
  return {context,nodes,rects,message,add};
}
test('iOS reader accepts a hidden structural Other only when every exact visible reader fact fits its on-screen frame', async () => {
  const good=markerFixture();
  const proof=await proveIosReaderEntry(good.context,{filename:'mobile-source.txt'});
  assert.equal(proof.facts.length,3);
  for(const change of ['marker-only','wrong-filename','wrong-frame','duplicate-marker','duplicate-fact']){
    const fake=markerFixture();
    if(change==='marker-only')for(const id of ['viewer-filename','viewer-close','viewer-toolbar'])fake.nodes.delete(id);
    if(change==='wrong-filename')fake.add('viewer-filename','XCUIElementTypeStaticText',fake.rects.get('viewer-filename'),{label:'wrong.txt'});
    if(change==='wrong-frame')fake.rects.set('private-document-viewer',{x:0,y:62,width:100,height:100});
    if(change==='duplicate-marker')fake.nodes.get('private-document-viewer').push(fake.nodes.get('private-document-viewer')[0]);
    if(change==='duplicate-fact')fake.nodes.get('viewer-filename').push(fake.nodes.get('viewer-filename')[0]);
    await assert.rejects(proveIosReaderEntry(fake.context,{filename:'mobile-source.txt'}));
  }
});
test('iOS persisted proof requires the exact visible acknowledgement inside its unique typed marker', async () => {
  const good=markerFixture();
  await proveIosUploadPersisted(good.context,good.message);
  await findIosUploadPersisted(good.context);
  for(const change of ['marker-only','wrong-text','wrong-frame','duplicate-marker','duplicate-message']){
    const fake=markerFixture();
    let message=fake.message;
    if(change==='marker-only')message=undefined;
    if(change==='wrong-text')message=fake.add('ack-text','XCUIElementTypeStaticText',fake.rects.get('ack-text'),{label:'Upload started'});
    if(change==='wrong-frame')fake.rects.set('ack-text',{x:20,y:300,width:362,height:74});
    if(change==='duplicate-marker')fake.nodes.get('files-upload-persisted').push(fake.nodes.get('files-upload-persisted')[0]);
    if(change==='duplicate-message'){
      fake.nodes.get('ack-text').push({...fake.message,elementId:'another-ack',getAttribute:async(key)=>key==='type'?'XCUIElementTypeStaticText':key==='accessible'?'true':IOS_UPLOAD_PERSISTED_MESSAGE});
      await assert.rejects(findIosUploadPersisted(fake.context));continue;
    }
    await assert.rejects(proveIosUploadPersisted(fake.context,message));
  }
});
test('hidden unknown and rejected structural upload statuses fail independently of layout-wrapper visibility', async () => {
  for(const id of ['files-upload-unknown','files-upload-rejected']){
    const fake=markerFixture();fake.add(id,'XCUIElementTypeOther',{x:20,y:529,width:362,height:74},{marker:true});
    await assert.rejects(assertIosUploadErrorsAbsent(fake.context),/IOS_FILES_UPLOAD_UNKNOWN_NO_REPLAY|IOS_FILES_UPLOAD_REJECTED/);
    fake.nodes.get(id).push(fake.nodes.get(id)[0]);
    await assert.rejects(assertIosUploadErrorsAbsent(fake.context),/IOS_FILES_STRUCTURAL_MARKER_NOT_UNIQUE/);
  }
});
test('reader privacy requires structural root removal plus absence of visible private filename, text and renderer', async () => {
  const fake=markerFixture();
  await assert.rejects(assertIosViewerAbsent(fake.context),/IOS_FILES_PRIVATE_VIEWER_STRUCTURE_RETAINED/);
  fake.nodes.delete('private-document-viewer');
  await assert.rejects(assertIosViewerAbsent(fake.context),/PRIVATE_OR_FORBIDDEN_SURFACE_VISIBLE/);
  fake.nodes.delete('viewer-filename');await assertIosViewerAbsent(fake.context);
  for(const id of ['viewer-text','viewer-isolated-renderer']){
    fake.add(id,'XCUIElementTypeStaticText',{x:16,y:192,width:370,height:73});
    await assert.rejects(assertIosViewerAbsent(fake.context),/PRIVATE_OR_FORBIDDEN_SURFACE_VISIBLE/);
    fake.nodes.delete(id);
  }
});

test('native source disclosure preserves the resolved identity and dispatches a lost acknowledgement once', async () => {
  const failure = new Error('lost native acknowledgement');let dispatches=0,monadClicks=0;
  const button={elementId:'owned-source-button',getAttribute:async key=>({type:'XCUIElementTypeButton',accessible:'true',label:'Source details'})[key],isEnabled:async()=>true,click:async()=>{monadClicks++;}};
  const context={driver:{elementClick:async id=>{dispatches++;assert.equal(id,button.elementId);throw failure;},$$:()=>assert.fail('REFETCH_FORBIDDEN')}};
  await assert.rejects(expandIosSourceDetails(context,button),error=>error===failure);assert.equal(dispatches,1);assert.equal(monadClicks,0);
});

test('selected-file proof requires exact visible filename and enabled Upload within a unique structural marker', async t => {
  const create=options=>{const {context,uploads}=fixture(t),asset=uploads.txt;
    const control=(id,shown=true)=>({elementId:id,isDisplayed:async()=>shown,isEnabled:async()=>true,getText:async()=>asset.filename,getAttribute:async key=>key==='type'?(id==='files-selection'?'XCUIElementTypeOther':'XCUIElementTypeStaticText'):key==='name'?id:key==='accessible'?'true':asset.filename});
    context.driver={waitUntil:async(check,opts)=>{if(!await check())throw new Error(opts?.timeoutMsg||'EXPECTED_FACT_MISSING');},$$:async query=>query==='~files-upload'?[control('files-upload')]:query==='~files-selection'?Array.from({length:options.duplicate?2:1},()=>control('files-selection',false)):query.includes('label == '+JSON.stringify(asset.filename))&&!options.wrongName?[control('selected-filename')]:[]};
    measuredFileDriver(context,id=>id==='files-selection'?{x:20,y:150,width:362,height:options.outside?20:200}:id==='files-upload'?{x:140,y:250,width:122,height:51}:{x:20,y:160,width:300,height:25});return{context,asset};};
  const good=create({});await proveIosSelectedFile(good.context,good.asset);
  for(const options of[{duplicate:true},{wrongName:true},{outside:true}]){const c=create(options);await assert.rejects(proveIosSelectedFile(c.context,c.asset));}
});

// Full existing reader composition with public synthetic bytes and an offline
// native/gateway double. The initial state matches the retained FILES04 facts.
const originalTextReaderFetch = globalThis.fetch;
function textReaderDouble(t, options = {}) {
  const text = 'A'.repeat(9999) + '\n' + 'B'.repeat(10000) + 'C'.repeat(4000);
  const anchor = { matterId: '11111111-1111-4111-8111-111111111111', attachmentId: '22222222-2222-4222-8222-222222222222', filename: 'synthetic-three-segments.txt', text, sizeBytes: Buffer.byteLength(text), sha256: createHash('sha256').update(text).digest('hex') };
  const segments = textSegments(text), clicks = [], waits = [], events = [];
  const ledger = { runId: 'offline-text-ready', requests: [], lastSequence: 0, overflow: false, markerRejected: 0, routeRejected: 0 };
  let ui = 'files', ready = false, page = 1, zoom = 100, polls = 0;
  t.after(() => { globalThis.fetch = originalTextReaderFetch; });
  globalThis.fetch = async (url) => { assert.equal(url, 'https://127.0.0.1:8443/__caseops_e2e/status'); return Response.json(ledger); };
  const rect = id => id === 'scroll' ? { x: 0, y: 125, width: 402, height: 638 }
    : id.startsWith('files-row-') ? { x: 10, y: 140, width: 382, height: 200 }
      : id.startsWith('files-') ? { x: 20, y: 150, width: 362, height: 44 }
        : id === 'private-document-viewer' ? { x: 0, y: 62, width: 402, height: 778 }
          : id === 'viewer-close' ? { x: 8, y: 70, width: 44, height: 44 }
            : id === 'viewer-toolbar' ? { x: 0, y: 123, width: 402, height: 53 }
              : { x: 60, y: 79, width: 334, height: 26 };
  const type = id => id === 'scroll' ? 'XCUIElementTypeScrollView'
    : ['private-document-viewer', 'viewer-toolbar', 'viewer-loading', 'viewer-blocked', 'viewer-unsupported', 'viewer-closed'].includes(id) || id.startsWith('files-row-') ? 'XCUIElementTypeOther'
      : ['viewer-close', 'viewer-next', 'viewer-previous', 'viewer-zoom-in'].includes(id) || id.startsWith('files-source-') || id.startsWith('files-open-') ? 'XCUIElementTypeButton' : 'XCUIElementTypeStaticText';
  const textFor = id => id.startsWith('files-name-') ? anchor.filename : id.startsWith('files-hash-') ? anchor.sha256
    : id === 'viewer-filename' ? options.wrongFilename ? 'stale-source.txt' : anchor.filename
      : id === 'viewer-position' ? options.position ?? (ready ? `Segment ${page} of 3` : 'No page displayed')
        : id === 'viewer-text' ? options.wrongText ? 'Wrong source bytes' : segments[page - 1]
          : id === 'viewer-zoom' ? `${zoom}%` : id === 'viewer-close' ? 'Return to Files' : id.startsWith('files-source-') ? 'Hide source details' : id;
  const control = id => ({ elementId: id, isDisplayed: async () => true,
    isEnabled: async () => id === 'viewer-previous' ? ready && page > 1 : id === 'viewer-next' ? ready && page < 3 : true,
    getText: async () => { if (id === 'viewer-position' && options.transport) throw options.transport; if (id === 'viewer-text' && options.unreadable) throw options.unreadable; return textFor(id); },
    getAttribute: async key => key === 'name' ? id : key === 'type' ? type(id) : key === 'label' ? textFor(id) : key === 'accessible' ? 'true' : null,
  });
  const context = { platform: 'ios', fixture: { gatewayUrl: 'https://127.0.0.1:8443', gatewayRunId: ledger.runId }, record: value => events.push(value), driver: {
    async $$(query) {
      if (query === '-ios predicate string:type == "XCUIElementTypeScrollView"') return [control('scroll')];
      const id = query.startsWith('~') ? query.slice(1) : '';
      if (id.startsWith('files-')) return ui === 'files' ? [control(id)] : [];
      if (!id || ui !== 'viewer') return [];
      if (['viewer-blocked', 'viewer-unsupported', 'viewer-closed'].includes(id)) return options.terminal === id ? [control(id)] : [];
      if (id === 'viewer-idle' || id === 'viewer-renewing') return [];
      if (id === 'viewer-loading') return !ready ? [control(id)] : [];
      if (id === 'viewer-text' && !ready) return [];
      return Array.from({length: options.duplicatePosition && id === 'viewer-position' ? 2 : 1}, () => control(id));
    },
    async waitUntil(check, args) {
      waits.push(args);
      if (args.timeoutMsg === 'IOS_FILES_INITIAL_TEXT_READY_REQUIRED') {
        assert.ok(args.timeout > 0 && args.timeout <= 15000); assert.equal(args.interval, 200);
        for (let attempt = 0; attempt < 4; attempt++) {
          polls++;
          if (!options.neverReady && attempt >= (options.readyAfter ?? 1)) ready = true;
          const before = clicks.length;
          const result = await check();
          assert.equal(clicks.length, before, 'INITIAL_READINESS_POLL_MUST_NOT_DISPATCH');
          if (result) return;
        }
        throw new Error(args.timeoutMsg);
      }
      if (!await check()) throw new Error(args.timeoutMsg);
    },
    async getWindowRect() { return { x: 0, y: 0, width: 402, height: 874 }; },
    async getElementRect(id) { return rect(id); },
    async elementClick(id) {
      clicks.push(id);
      if (id.startsWith('files-open-')) {
        ui = 'viewer'; ready = options.readyAfter === 0;
        for (const status of [206,200,206]) ledger.requests.push({ sequence: ++ledger.lastSequence, method: 'GET', route: `/api/matters/${anchor.matterId}/attachments/${anchor.attachmentId}/download`, status, nativeMarker: true });
      } else if (id === 'viewer-zoom-in') { assert.equal(ready, true); zoom = 125; }
      else if (id === 'viewer-next') { assert.equal(ready, true); page++; }
      else if (id === 'viewer-previous') { assert.equal(ready, true); page--; }
      else if (id === 'viewer-close') ui = 'files';
      else assert.fail('UNEXPECTED_OFFLINE_NATIVE_DISPATCH');
    },
  } };
  return { context, anchor, clicks, waits, events, ledger, polls: () => polls, startReader: () => { ui = 'viewer'; } };
}

test('initial TXT No page/loading may settle within the existing 15s budget before exact three-segment traversal', async t => {
  for (const readyAfter of [0, 1]) {
    const f = textReaderDouble(t, { readyAfter });
    await readIosText(f.context, f.anchor);
    assert.deepEqual(f.clicks, [`files-open-${f.anchor.attachmentId}`, 'viewer-zoom-in', 'viewer-next', 'viewer-next', 'viewer-previous', 'viewer-previous', 'viewer-close']);
    assert.equal(f.events.filter(e => e.boundary === 'ios-private-text-segments-read').length, 1);
    assert.ok(f.polls() >= 1); assert.equal(f.ledger.requests.filter(row => row.method === 'POST').length, 0);
  }
});

test('initial TXT never-ready or stale segment count refuses before zoom/Next and never substitutes bytes', async t => {
  for (const options of [{ neverReady: true }, { position: 'Segment 1 of 1' }, { position: 'Segment 2 of 3' }]) {
    const f = textReaderDouble(t, options);
    await assert.rejects(readIosText(f.context, f.anchor), /IOS_FILES_INITIAL_TEXT_READY_REQUIRED|IOS_FILES_TEXT_INITIAL_POSITION_MISMATCH/);
    assert.deepEqual(f.clicks, [`files-open-${f.anchor.attachmentId}`]);
    assert.equal(f.events.some(e => e.boundary === 'ios-private-text-segments-read'), false);
  }
});

test('initial TXT error/closed/ambiguous/wrong-source and transport remain terminal without polling mutations', async t => {
  const original = new Error('Synthetic stale element transport');
  for (const options of [{terminal:'viewer-blocked'}, {terminal:'viewer-unsupported'}, {terminal:'viewer-closed'}, {duplicatePosition:true}, {wrongFilename:true}, {transport:original}]) {
    const f = textReaderDouble(t, options); f.startReader();
    await assert.rejects(awaitIosTextReady(f.context, f.anchor, 3), options.transport ? error => error === original : /IOS_FILES_READER_FAILURE_PRESENT|IOS_FILES_TEXT_FACT_NOT_UNIQUE|IOS_FILES_WRONG_READER_SOURCE/);
    assert.deepEqual(f.clicks, []); assert.equal(f.polls(), 1);
  }
});

test('TXT readiness does not excuse unreadable or wrong content once the native page is ready', async t => {
  const original = new Error('Synthetic unreadable text');
  for (const options of [{readyAfter:0,unreadable:original}, {readyAfter:0,wrongText:true}]) {
    const f = textReaderDouble(t, options);
    await assert.rejects(readIosText(f.context, f.anchor), options.unreadable ? error => error === original : /IOS_FILES_TEXT_BYTES_DISPLAY_MISMATCH/);
    assert.deepEqual(f.clicks, [`files-open-${f.anchor.attachmentId}`]);
  }
});
