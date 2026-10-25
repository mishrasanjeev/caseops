import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { FixtureUnavailable } from './fixture-contract.mjs';
import { collectFiles, expandSourceDetails, inventory, scenarios, source, uploadFilesSource, validateFilesContext, validateSourceAnchor, validateSourceReceipt, validateUploadFixture } from './files-20261025.mjs';
import { selector } from './native-ui.mjs';
import { gatewayBaseline } from './traffic.mjs';

// Sidecar unit/discovery tests only. No driver, browser, Appium or HTTP is run.
test('files supplement reconciles its independent exact inventory without changing the 23-case core', () => {
  assert.deepEqual(collectFiles().intended, ['android:FILES-01', 'android:FILES-02']);
  assert.deepEqual(collectFiles().discovered, ['android:FILES-01', 'android:FILES-02']);
  assert.deepEqual(scenarios.map(({ id }) => id), ['FILES-01', 'FILES-02']);
  assert.equal(inventory.cases[1].requiresNativeFixture, 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED');
  assert.throws(() => collectFiles('ios'), /FILES_ANDROID_ONLY/);
  const core = JSON.parse(readFileSync(new URL('./core-20261025.json', import.meta.url), 'utf8'));
  assert.equal(core.cases.length, 23);
  assert.equal(core.cases.some(({ id }) => id.startsWith('FILES-')), false);
});

test('files source pin matches owner supplied identities and exact committed unverified CLEAN text/hash', () => {
  assert.equal(source.matterId, 'e7cd2909-f8a3-4e6d-88e3-571711046eb4');
  assert.equal(source.attachmentId, '26bdc03b-6e23-410b-b961-d5410f15466d');
  assert.equal(source.sha256, '32df2bb8255ed04c167cd8c99bcd471b606b44aea770cc3612b13e86d8613fd6');
  const seed = readFileSync(new URL('../../../scripts/mobile/local-fixture.py', import.meta.url), 'utf8');
  assert.ok(seed.includes('CLEAN = b"Synthetic CaseOps mobile source. No legal authority or customer data.\\n"'));
  assert.equal(createHash('sha256').update(source.text).digest('hex'), source.sha256);
  validateSourceAnchor();
  for (const key of ['matterId', 'attachmentId', 'sha256', 'filename', 'text'])
    assert.throws(() => validateSourceAnchor({ ...source, [key]: '' }), /FILES_SOURCE_ANCHOR_MISMATCH/);
});

test('files supplement missing/native/production prerequisites remain blocked, not empty success', () => {
  for (const context of [undefined, {}, { platform: 'ios' }, { platform: 'android', fixture: { environment: 'production', syntheticDataOnly: true } },
    { platform: 'android', fixture: { environment: 'docker-integration', syntheticDataOnly: false } }])
    assert.throws(() => validateFilesContext(context), FixtureUnavailable);
});

test('independent source seed receipt binds the actual source identity/hash and positive seed readback before UI expectations', () => {
  const unitReceipt = { environment: 'docker-integration', syntheticDataOnly: true, matter: { id: source.matterId },
    sourceId: source.attachmentId, sourceSha256: source.sha256, cleanUploadAndDownload: true };
  validateSourceReceipt(unitReceipt); // Contract test only, not a backend receipt.
  for (const delta of [{ sourceId: '' }, { sourceSha256: '' }, { matter: null }, { cleanUploadAndDownload: false },
    { environment: 'production' }, { syntheticDataOnly: false }])
    assert.throws(() => validateSourceReceipt({ ...unitReceipt, ...delta }));
});

test('actual source components still own every fixed selector used by the supplemental read journey', () => {
  const files = readFileSync(new URL('../src/application/screens/FilesScreen.tsx', import.meta.url), 'utf8');
  const viewer = readFileSync(new URL('../src/viewer/PrivateDocumentViewer.tsx', import.meta.url), 'utf8');
  const matter = readFileSync(new URL('../src/application/screens/MatterScreen.tsx', import.meta.url), 'utf8');
  for (const id of ['files-matter-code', 'files-matter-title', 'files-reload', 'files-choose', 'files-row-', 'files-name-', 'files-source-', 'files-hash-', 'files-open-'])
    assert.ok(files.includes(`testID="${id}"`) || files.includes('testID={`' + id), 'SOURCE_OWNED_FILES_SELECTOR_MISSING');
  for (const id of ['private-document-viewer', 'viewer-filename', 'viewer-position', 'viewer-text', 'viewer-close'])
    assert.ok(viewer.includes(`testID="${id}"`), 'SOURCE_OWNED_VIEWER_SELECTOR_MISSING');
  assert.ok(matter.includes('`matter-${value.toLowerCase()}`'));
});

test('unknown picker/upload path is explicitly blocked without executing an invented native or API operation', async () => {
  await assert.rejects(uploadFilesSource(), (error) => error instanceof FixtureUnavailable && error.message === 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED');
});

test('Compose source-details wrapper text is never read; exact visible child caption is scoped to that control', async () => {
  for (const expanded of [false, true]) {
    const queried = [];
    let clicked = 0;
    const expected = selector('android', 'text', expanded ? 'Hide source details' : 'Source details');
    const control = {
      getText() { assert.fail('COMPOSE_WRAPPER_TEXT_MUST_NOT_BE_READ'); },
      async $$(query) {
        queried.push(query);
        return query === expected ? [{ async isDisplayed() { return true; }, async click() { clicked++; } }] : [];
      },
    };
    await expandSourceDetails(control, 'android');
    assert.deepEqual(queried, [selector('android', 'text', 'Source details'), selector('android', 'text', 'Hide source details')]);
    assert.equal(clicked, expanded ? 0 : 1);
  }
});

test('missing, invisible, duplicate or contradictory exact source-details captions fail without a fallback click', async () => {
  for (const state of ['missing', 'invisible', 'duplicate', 'contradictory']) {
    let clicked = 0;
    const child = { async isDisplayed() { return state !== 'invisible'; }, async click() { clicked++; } };
    const control = { async $$(query) {
      if (state === 'missing') return [];
      if (state === 'contradictory') return [child];
      return query === selector('android', 'text', 'Source details') ? (state === 'duplicate' ? [child, child] : [child]) : [];
    } };
    await assert.rejects(expandSourceDetails(control, 'android'), state === 'duplicate' ? /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/ : /FILES_SOURCE_DETAILS_STATE_UNOBSERVED/);
    assert.equal(clicked, 0);
  }
});

// Synthetic proof files and explicit UI/transport doubles, never native evidence.
function offlineUploadFixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'caseops-files-offline-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
  const evidence = (name, value) => {
    const bytes = JSON.stringify(value);
    const path = join(root, `${name}.json`);
    writeFileSync(path, bytes, { flag: 'wx' });
    return { path, sha256: sha256(bytes) };
  };
  const text = 'Synthetic CaseOps offline upload. No legal authority or customer data.\n';
  const upload = { filename: 'CaseOps-native-clean-012345abcdef.txt', text, sha256: sha256(text), sizeBytes: Buffer.byteLength(text) };
  upload.devicePath = `/sdcard/Download/${upload.filename}`;
  const device = { filename: upload.filename, devicePath: upload.devicePath, sha256: upload.sha256,
    sizeBytes: upload.sizeBytes, observedDeviceHash: upload.sha256, udid: 'offline-unit-device', syntheticDataOnly: true };
  const picker = { kind: 'observed-native-android-document-picker', package: 'com.android.documentsui',
    controls: { roots: { kind: 'label', value: 'Show roots' }, rootList: { kind: 'id', value: 'com.android.documentsui:id/roots_list' },
      downloads: { kind: 'text', value: 'Downloads' }, fileTitleId: 'android:id/title' } };
  upload.deviceEvidence = evidence('device', device);
  upload.pickerEvidence = evidence('picker', picker);
  const fixture = { environment: 'docker-integration', syntheticDataOnly: true, appId: 'ai.caseops.mobile.dev',
    udid: device.udid, backendSha: 'a'.repeat(40), webSha: 'a'.repeat(40), binarySourceSha: 'a'.repeat(40),
    apiOrigin: 'https://127.0.0.1:1', gatewayUrl: 'http://127.0.0.1:1', gatewayRunId: 'offline-files-unit',
    companyId: 'offline-company', membershipId: 'offline-member', principalLabel: 'Offline principal', workspaceLabel: 'Offline workspace',
    matter: { id: source.matterId, search: 'OFFLINE-001', identityLabel: 'OFFLINE-001', title: 'Synthetic offline Matter' }, upload };
  fixture.seedEvidence = evidence('seed', { environment: fixture.environment, syntheticDataOnly: true,
    companyId: fixture.companyId, membershipId: fixture.membershipId, matter: { id: source.matterId },
    sourceId: source.attachmentId, sourceSha256: source.sha256, cleanUploadAndDownload: true });
  const ledger = { runId: fixture.gatewayRunId, overflow: false, markerRejected: 0, routeRejected: 0, lastSequence: 0, requests: [] };
  const context = { platform: 'android', fixture, gatewayBaseline: gatewayBaseline(ledger, fixture),
    driver: { $() { assert.fail('UNEXPECTED_OFFLINE_DRIVER_CALL'); }, waitUntil() { assert.fail('UNEXPECTED_OFFLINE_DRIVER_CALL'); } },
    admitUploadedFileRead() { assert.fail('UNACKNOWLEDGED_SOURCE_MUST_NOT_BE_ADMITTED'); } };
  return { context, upload, device, picker, ledger, evidence };
}

test('offline upload validation accepts only its hash-bound synthetic seed/device/picker contract', t => {
  const { context, upload, picker } = offlineUploadFixture(t);
  assert.deepEqual(validateUploadFixture(context), { ...upload, picker });
});

for (const key of ['seedEvidence', 'deviceEvidence', 'pickerEvidence']) {
  test(`offline upload validation rejects corrupted ${key} bytes`, t => {
    const { context, upload } = offlineUploadFixture(t);
    const proof = key === 'seedEvidence' ? context.fixture[key] : upload[key];
    writeFileSync(proof.path, '{}');
    assert.throws(() => validateUploadFixture(context), /FIXTURE_EVIDENCE_CHANGED/);
  });
}

test('offline upload validation rejects other-device, wrong-path and nonsynthetic device proofs', t => {
  const { context, upload, device, evidence } = offlineUploadFixture(t);
  const deltas = [{ udid: 'other-device' }, { devicePath: '/sdcard/Download/other.txt' }, { syntheticDataOnly: false },
    { observedDeviceHash: '0'.repeat(64) }, { sha256: '0'.repeat(64) }, { sizeBytes: device.sizeBytes + 1 }];
  for (const [index, delta] of deltas.entries()) {
    upload.deviceEvidence = evidence(`bad-device-${index}`, { ...device, ...delta });
    assert.throws(() => validateUploadFixture(context), assert.AssertionError);
  }
});

test('offline upload validation rejects wrong filenames, unbound paths, content hashes and sizes before UI', t => {
  const { context, upload } = offlineUploadFixture(t);
  for (const delta of [{ filename: 'customer-document.txt' }, { filename: '../CaseOps-native-clean-012345abcdef.txt' },
    { devicePath: '/sdcard/Documents/CaseOps-native-clean-012345abcdef.txt' }, { sha256: '0'.repeat(64) },
    { sizeBytes: 0 }, { sizeBytes: 4097 }, { sizeBytes: upload.sizeBytes + 1 }, { text: 'changed' }]) {
    context.fixture.upload = { ...upload, ...delta };
    assert.throws(() => validateUploadFixture(context), assert.AssertionError);
  }
});

test('offline upload validation rejects unsafe or unobserved picker packages and actions', t => {
  const { context, upload, picker, evidence } = offlineUploadFixture(t);
  const deltas = [{ package: 'other.picker' }, { kind: 'invented-picker' },
    { controls: { ...picker.controls, roots: { kind: 'text', value: 'Show roots' } } },
    { controls: { ...picker.controls, downloads: { kind: 'text', value: 'Delete' } } },
    { controls: { ...picker.controls, fileTitleId: 'android:id/other' } },
    { controls: { ...picker.controls, extraAction: 'delete' } }];
  for (const [index, delta] of deltas.entries()) {
    upload.pickerEvidence = evidence(`bad-picker-${index}`, { ...picker, ...delta });
    assert.throws(() => validateUploadFixture(context), assert.AssertionError);
  }
});

test('offline upload requires explicit acknowledged-source read admission before any UI action', async t => {
  const { context } = offlineUploadFixture(t);
  delete context.admitUploadedFileRead;
  await assert.rejects(uploadFilesSource(context), /EXACT_ACKNOWLEDGED_UPLOAD_READ_ADMISSION_REQUIRED/);
});

function offlineFailedUpload(t, outcome) {
  const value = offlineUploadFixture(t);
  const { context, upload, ledger } = value;
  const clicks = [], queries = [], records = [];
  let selected = false, submitted = false, pickerOpen = false, downloadsOpen = false, expanded = false;
  const append = (method, route, status) => ledger.requests.push({ sequence: ++ledger.lastSequence,
    method, route, status, nativeMarker: true, requestId: `offline-${ledger.lastSequence}` });
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, `${context.fixture.gatewayUrl}/__caseops_e2e/status`);
    assert.equal(options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
    assert.equal(options.redirect, 'error');
    assert.equal(options.method, undefined);
    return new Response(JSON.stringify(ledger));
  });
  const element = (id, text = '') => ({
    async isDisplayed() { return true; }, async isEnabled() { return true; }, async getText() { return text; },
    async setValue(value) { assert.equal(id, 'matter-search'); assert.equal(value, context.fixture.matter.search); },
    async click() {
      clicks.push(id);
      if (id === 'files-choose') pickerOpen = true;
      if (id === 'Downloads') { assert.equal(pickerOpen, true); downloadsOpen = true; }
      if (id === 'picked-file') { assert.equal(downloadsOpen, true); pickerOpen = false; selected = true; }
      if (id === 'Source details') expanded = true;
      if (id === 'files-upload') {
        assert.equal(selected, true);
        assert.equal(submitted, false, 'OFFLINE_DOUBLE_DETECTED_UPLOAD_REPLAY');
        submitted = true;
        append('POST', `/api/matters/${source.matterId}/attachments`, outcome === 'rejected' ? 422 : outcome === 'no-ack' ? 200 : 0);
      }
    },
  });
  const controls = new Map(['account-open', 'back', 'tab-matters', 'screen-matters', 'matter-search', 'matter-search-submit',
    `matter-row-${source.matterId}`, 'matter-files', 'files-choose', `files-row-${source.attachmentId}`]
    .map(id => [selector('android', 'id', id), element(id)]));
  for (const [id, text] of Object.entries({ 'account-principal': context.fixture.principalLabel,
    'account-workspace': context.fixture.workspaceLabel, 'matter-code': context.fixture.matter.identityLabel,
    'files-matter-code': context.fixture.matter.identityLabel, 'files-matter-title': context.fixture.matter.title,
    [`files-name-${source.attachmentId}`]: source.filename, [`files-hash-${source.attachmentId}`]: source.sha256 }))
    controls.set(selector('android', 'id', id), element(id, text));
  controls.set(selector('android', 'text', context.fixture.matter.title), element('matter-title'));
  controls.set(selector('android', 'id', `files-source-${source.attachmentId}`), {
    async isDisplayed() { return true; }, async $$(query) {
      return query === selector('android', 'text', expanded ? 'Hide source details' : 'Source details')
        ? [element(expanded ? 'Hide source details' : 'Source details')] : [];
    },
  });
  context.driver = {
    $() { assert.fail('UNEXPECTED_SINGLE_ELEMENT_LOOKUP'); },
    async switchContext(name) { assert.equal(name, 'NATIVE_APP'); },
    async getCurrentPackage() { return pickerOpen ? 'com.android.documentsui' : context.fixture.appId; },
    async waitUntil(predicate, options) { if (!await predicate()) throw new Error(options.timeoutMsg); },
    async $$(query) {
      queries.push(query);
      if (controls.has(query)) return [controls.get(query)];
      if (query === '~Show roots' && pickerOpen) return [element('Show roots')];
      if (query === 'id=com.android.documentsui:id/roots_list' && pickerOpen) return [{ async isDisplayed() { return true; },
        async $$(child) { assert.equal(child, selector('android', 'text', 'Downloads')); return [element('Downloads')]; } }];
      if (query === `android=new UiSelector().resourceId("android:id/title").text(${JSON.stringify(upload.filename)})` && downloadsOpen)
        return [element('picked-file', upload.filename)];
      if (selected && ['id=files-selection', 'id=files-upload'].includes(query)) return [element(query.slice(3))];
      if (submitted && query === `id=files-upload-${outcome === 'no-ack' ? 'persisted' : outcome}` && outcome !== 'missing-persistence')
        return [element('outcome')];
      if ([`android=new UiSelector().resourceIdMatches("files-name-.*").text(${JSON.stringify(upload.filename)})`,
        'id=files-upload-unknown', 'id=files-upload-rejected', 'id=files-upload-persisted'].includes(query)) return [];
      assert.fail(`UNEXPECTED_OFFLINE_UI_QUERY: ${query}`);
    },
  };
  context.record = event => records.push(event);
  return { context, ledger, clicks, queries, records };
}

for (const [outcome, expected] of [['unknown', /UPLOAD_OUTCOME_UNKNOWN_NO_REPLAY/], ['rejected', /NATIVE_UPLOAD_REJECTED/],
  ['no-ack', /NATIVE_UPLOAD_NOT_ACKNOWLEDGED/], ['missing-persistence', /NATIVE_UPLOAD_PERSISTENCE_NOT_ACKNOWLEDGED/]]) {
  test(`offline ${outcome} upload response is never retried or admitted for source opening`, async t => {
    const { context, ledger, clicks, queries, records } = offlineFailedUpload(t, outcome);
    await assert.rejects(uploadFilesSource(context), expected);
    assert.equal(clicks.filter(id => id === 'files-upload').length, 1);
    assert.deepEqual(ledger.requests.map(({ method, route }) => ({ method, route })),
      [{ method: 'POST', route: `/api/matters/${source.matterId}/attachments` }]);
    assert.equal(queries.some(query => query.startsWith('id=files-open-')), false);
    assert.equal(records.some(event => event.boundary === 'native-picker-upload-reload-open'), false);
    assert.equal(clicks.includes('files-reload'), false);
  });
}
