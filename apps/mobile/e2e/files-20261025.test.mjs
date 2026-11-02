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
        return query === expected ? [{ elementId: 'source-details-unit', async isDisplayed() { return true; },
          async click() { assert.fail('ELEMENT_CLICK_WRAPPER_MUST_NOT_BE_CALLED'); } }] : [];
      },
    };
    const context = { platform: 'android', driver: { async elementClick(id) { assert.equal(id, 'source-details-unit'); clicked++; } } };
    await expandSourceDetails(context, control);
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
    await assert.rejects(expandSourceDetails({ platform: 'android', driver: { elementClick() { clicked++; } } }, control),
      state === 'duplicate' ? /AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/ : /FILES_SOURCE_DETAILS_STATE_UNOBSERVED/);
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

function offlineUpload(t, outcome, { status = 200, acknowledgement = 'visible' } = {}) {
  const value = offlineUploadFixture(t);
  const { context, upload, ledger } = value;
  const clicks = [], queries = [], records = [], reads = [], admissions = [], swipes = [];
  const uploadedId = '11111111-2222-4333-8444-555555555555';
  const downloadRoute = `/api/matters/${source.matterId}/attachments/${uploadedId}/download`;
  let selected = false, submitted = false, pickerOpen = false, downloadsOpen = false, expanded = false;
  let reloaded = false, admitted = false, viewerOpen = false;
  let acknowledgementVisible = acknowledgement === 'visible';
  const append = (method, route, status) => ledger.requests.push({ sequence: ++ledger.lastSequence,
    method, route, status, nativeMarker: true, requestId: `offline-${ledger.lastSequence}` });
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, `${context.fixture.gatewayUrl}/__caseops_e2e/status`);
    assert.equal(options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
    assert.equal(options.redirect, 'error');
    assert.equal(options.method, 'GET');
    assert.equal(options.body, undefined);
    return new Response(JSON.stringify(ledger));
  });
  const nativeClicks = new Map();
  const element = (id, text = '') => {
    const control = { elementId: id,
    async isDisplayed() { return true; }, async isEnabled() { return true; },
    async getText() { reads.push({ id, text }); return text; },
    async getAttribute(name) { assert.equal(name, 'resource-id'); return id; },
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
        append('POST', `/api/matters/${source.matterId}/attachments`, outcome === 'rejected' ? 422 : outcome === 'persisted' ? status : 0);
      }
      if (id === 'files-reload') {
        assert.equal(submitted, true);
        assert.equal(reloaded, false);
        reloaded = true;
        append('GET', `/api/matters/${source.matterId}/workspace`, 200);
      }
      if (id === `files-open-${uploadedId}`) {
        assert.equal(reloaded, true, 'OPEN_MUST_FOLLOW_PERSISTED_RELOAD');
        assert.equal(admitted, true, 'OPEN_MUST_FOLLOW_EXACT_READ_ADMISSION');
        viewerOpen = true;
        for (const code of [206, 200, 206]) append('GET', downloadRoute, code);
      }
      if (id === 'viewer-close') { assert.equal(viewerOpen, true); viewerOpen = false; }
    },
    };
    nativeClicks.set(id, control.click.bind(control));
    return control;
  };
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
  const uploadedControls = new Map([
    [`files-row-${uploadedId}`, ''], [`files-name-${uploadedId}`, upload.filename],
    [`files-hash-${uploadedId}`, upload.sha256], [`files-open-${uploadedId}`, 'Open'], ['files-reload', 'Reload'],
  ].map(([id, text]) => [selector('android', 'id', id), element(id, text)]));
  uploadedControls.set(selector('android', 'id', `files-source-${uploadedId}`), {
    async isDisplayed() { return true; },
    async $$(query) {
      return query === selector('android', 'text', expanded ? 'Hide source details' : 'Source details')
        ? [element(expanded ? 'Hide source details' : 'Source details')] : [];
    },
  });
  if (outcome === 'persisted') context.admitUploadedFileRead = async anchor => {
    assert.equal(reloaded, true, 'ADMISSION_MUST_FOLLOW_PERSISTED_RELOAD');
    assert.equal(admissions.length, 0, 'READ_ADMISSION_MUST_NOT_REPLAY');
    assert.equal(anchor.matterId, source.matterId);
    assert.equal(anchor.attachmentId, uploadedId);
    assert.equal(anchor.filename, upload.filename);
    assert.equal(anchor.sha256, upload.sha256);
    assert.equal(anchor.sizeBytes, upload.sizeBytes);
    assert.equal(anchor.text, upload.text);
    assert.deepEqual(anchor.acknowledgement, ledger.requests[0]);
    assert.equal(anchor.acknowledgement.status, 200);
    admissions.push(anchor);
    admitted = true;
    return { route: `GET ${downloadRoute}` };
  };
  context.driver = {
    async elementClick(id) {
      assert.ok(nativeClicks.has(id), 'UNIT_RESOLVED_NATIVE_ID_REQUIRED');
      await nativeClicks.get(id)();
    },
    $() { assert.fail('UNEXPECTED_SINGLE_ELEMENT_LOOKUP'); },
    async switchContext(name) { assert.equal(name, 'NATIVE_APP'); },
    async getCurrentPackage() { return pickerOpen ? 'com.android.documentsui' : context.fixture.appId; },
    async waitUntil(predicate, options) { if (!await predicate()) throw new Error(options.timeoutMsg); },
    async getWindowRect() { return { width: 1080, height: 2424 }; },
    async performActions(actions) {
      assert.equal(submitted, true, 'OUTCOME_SCROLL_REQUIRES_PRIOR_EXPLICIT_UPLOAD');
      const moves = actions[0].actions.filter(action => action.type === 'pointerMove');
      const direction = moves[1].y < moves[0].y ? 'down' : 'up';
      swipes.push(direction);
      if (acknowledgement === 'after-scroll' && direction === 'down') acknowledgementVisible = true;
    },
    async releaseActions() {},
    async $$(query) {
      queries.push(query);
      if (query === selector('android', 'id', 'session-loading')) return [];
      if (controls.has(query)) return [controls.get(query)];
      if (submitted && outcome === 'persisted') {
        if (uploadedControls.has(query)) return [uploadedControls.get(query)];
        if (query === `android=new UiSelector().resourceIdMatches("files-name-.*").text(${JSON.stringify(upload.filename)})`)
          return [element(`files-name-${uploadedId}`, upload.filename)];
      }
      if (viewerOpen && query === 'id=viewer-filename') return [element('viewer-filename', upload.filename)];
      if (viewerOpen && query === 'id=viewer-text') return [element('viewer-text', upload.text)];
      if (viewerOpen && query === 'id=viewer-close') return [element('viewer-close')];
      if (!viewerOpen && query === 'id=viewer-text') return [];
      if (query === '~Show roots' && pickerOpen) return [element('Show roots')];
      if (query === 'id=com.android.documentsui:id/roots_list' && pickerOpen) return [{ async isDisplayed() { return true; },
        async $$(child) { assert.equal(child, selector('android', 'text', 'Downloads')); return [element('Downloads')]; } }];
      if (query === `android=new UiSelector().resourceId("android:id/title").text(${JSON.stringify(upload.filename)})` && downloadsOpen)
        return [element('picked-file', upload.filename)];
      if (selected && ['id=files-selection', 'id=files-upload'].includes(query)) return [element(query.slice(3))];
      if (query === 'id=files-upload-persisted' && outcome === 'persisted' && !acknowledgementVisible) return [];
      if (submitted && query === `id=files-upload-${outcome === 'no-ack' ? 'persisted' : outcome}` && outcome !== 'missing-persistence')
        return [element('outcome')];
      if ([`android=new UiSelector().resourceIdMatches("files-name-.*").text(${JSON.stringify(upload.filename)})`,
        'id=files-upload-unknown', 'id=files-upload-rejected', 'id=files-upload-persisted'].includes(query)) return [];
      assert.fail(`UNEXPECTED_OFFLINE_UI_QUERY: ${query}`);
    },
  };
  context.record = event => records.push(event);
  return { context, ledger, clicks, queries, records, reads, admissions, swipes, uploadedId, downloadRoute, upload };
}

test('actual Android Files wrapper never refetches or replays resolved details, picker or upload clicks after stale/lost acknowledgements', async t => {
  for (const target of ['Source details', 'Downloads', 'picked-file', 'files-upload']) for (const lostAcknowledgement of [false, true]) {
    const fake = offlineUpload(t, 'persisted'), { driver } = fake.context;
    const lookup = driver.$$.bind(driver), rawClick = driver.elementClick.bind(driver);
    let wrapperClicks = 0, lookups = 0, lookupsAtFailure;
    const dispatched = [], failure = new Error(lostAcknowledgement ? 'UNIT_NATIVE_CLICK_ACK_UNKNOWN' : 'UNIT_STALE_NATIVE_ELEMENT');
    driver.$$ = async query => {
      lookups++;
      const controls = await lookup(query);
      for (const control of controls) {
        if (control.elementId === target) control.click = async () => { wrapperClicks++; throw new Error('ELEMENT_CLICK_WRAPPER_MUST_NOT_BE_CALLED'); };
        if (typeof control.$$ === 'function') {
          const scoped = control.$$.bind(control);
          control.$$ = async value => {
            lookups++;
            const children = await scoped(value);
            for (const child of children) if (child.elementId === target) {
              child.click = async () => { wrapperClicks++; throw new Error('ELEMENT_CLICK_WRAPPER_MUST_NOT_BE_CALLED'); };
            }
            return children;
          };
        }
      }
      return controls;
    };
    driver.elementClick = async id => {
      dispatched.push(id);
      if (id !== target) return rawClick(id);
      if (lostAcknowledgement) await rawClick(id);
      lookupsAtFailure = lookups;
      throw failure;
    };
    await assert.rejects(uploadFilesSource(fake.context), error => error === failure);
    assert.equal(wrapperClicks, 0); assert.equal(dispatched.filter(id => id === target).length, 1);
    assert.equal(lookups, lookupsAtFailure, 'FAILED_NATIVE_CLICK_MUST_NOT_REFETCH');
    assert.equal(fake.clicks.filter(id => id === target).length, lostAcknowledgement ? 1 : 0);
    assert.equal(fake.ledger.requests.filter(row => row.method === 'POST').length, target === 'files-upload' && lostAcknowledgement ? 1 : 0);
    assert.deepEqual(fake.admissions, []); assert.equal(fake.clicks.includes('files-reload'), false);
  }
});

test('Android source-details wrapper requires the resolved native element ID before any dispatch', async () => {
  let rawClicks = 0, wrapperClicks = 0;
  const context = { platform: 'android', driver: { async elementClick() { rawClicks++; } } };
  const control = { async $$(query) { return query === selector('android', 'text', 'Source details')
    ? [{ async isDisplayed() { return true; }, async click() { wrapperClicks++; } }] : []; } };
  await assert.rejects(expandSourceDetails(context, control), /NATIVE_CLICK_ELEMENT_ID_REQUIRED/);
  assert.equal(rawClicks, 0); assert.equal(wrapperClicks, 0);
});

for (const [outcome, expected] of [['unknown', /UPLOAD_OUTCOME_UNKNOWN_NO_REPLAY/], ['rejected', /NATIVE_UPLOAD_REJECTED/],
  ['no-ack', /NATIVE_UPLOAD_NOT_ACKNOWLEDGED/], ['missing-persistence', /NATIVE_UPLOAD_PERSISTENCE_NOT_ACKNOWLEDGED/]]) {
  test(`offline ${outcome} upload response is never retried or admitted for source opening`, async t => {
    const { context, ledger, clicks, queries, records } = offlineUpload(t, outcome);
    await assert.rejects(uploadFilesSource(context), expected);
    assert.equal(clicks.filter(id => id === 'files-upload').length, 1);
    assert.deepEqual(ledger.requests.map(({ method, route }) => ({ method, route })),
      [{ method: 'POST', route: `/api/matters/${source.matterId}/attachments` }]);
    assert.equal(queries.some(query => query.startsWith('id=files-open-')), false);
    assert.equal(records.some(event => event.boundary === 'native-picker-upload-reload-open'), false);
    assert.equal(clicks.includes('files-reload'), false);
  });
}

test('offline canonical 200 upload completes once through persisted UUID/hash/name reload and exact source opening', async t => {
  const { context, ledger, clicks, queries, records, reads, admissions, uploadedId, downloadRoute, upload } = offlineUpload(t, 'persisted');
  await uploadFilesSource(context);
  assert.deepEqual(ledger.requests.map(({ method, route, status }) => ({ method, route, status })), [
    { method: 'POST', route: `/api/matters/${source.matterId}/attachments`, status: 200 },
    { method: 'GET', route: `/api/matters/${source.matterId}/workspace`, status: 200 },
    ...[206, 200, 206].map(status => ({ method: 'GET', route: downloadRoute, status })),
  ]);
  for (const id of ['files-upload', 'files-reload', `files-open-${uploadedId}`, 'viewer-close'])
    assert.equal(clicks.filter(value => value === id).length, 1);
  for (const [id, text] of [[`files-name-${uploadedId}`, upload.filename], [`files-hash-${uploadedId}`, upload.sha256]])
    assert.deepEqual(reads.filter(row => row.id === id), [{ id, text }, { id, text }]);
  assert.deepEqual(reads.filter(row => row.id === 'viewer-text'), [{ id: 'viewer-text', text: upload.text }]);
  assert.equal(createHash('sha256').update(upload.text).digest('hex'), upload.sha256);
  assert.equal(Buffer.byteLength(upload.text), upload.sizeBytes);
  assert.equal(admissions.length, 1);
  assert.equal(admissions[0].attachmentId, uploadedId);
  assert.equal(admissions[0].acknowledgement.status, 200);
  assert.ok(queries.includes(`id=files-name-${uploadedId}`));
  assert.deepEqual(records.filter(event => event.boundary === 'native-picker-upload-reload-open'), [{
    type: 'assertion', boundary: 'native-picker-upload-reload-open', attachmentId: uploadedId,
    sha256: upload.sha256, sizeBytes: upload.sizeBytes, acknowledgementRequestId: ledger.requests[0].requestId,
    admission: { route: `GET ${downloadRoute}` },
  }]);
  assert.equal(ledger.requests.filter(row => row.method === 'POST').length, 1);
});

test('offline persisted upload rejects 201 and other noncanonical success statuses without retry or read admission', async t => {
  for (const status of [201, 202, 204]) {
    const { context, ledger, clicks, queries, records, admissions } = offlineUpload(t, 'persisted', { status });
    await assert.rejects(uploadFilesSource(context), /NATIVE_UPLOAD_NOT_ACKNOWLEDGED/);
    assert.equal(clicks.filter(id => id === 'files-upload').length, 1);
    assert.deepEqual(ledger.requests.map(({ method, route, status }) => ({ method, route, status })),
      [{ method: 'POST', route: `/api/matters/${source.matterId}/attachments`, status }]);
    assert.deepEqual(admissions, []);
    assert.equal(queries.some(query => query.startsWith('id=files-open-')), false);
    assert.equal(clicks.includes('files-reload'), false);
    assert.equal(records.some(event => event.boundary === 'native-picker-upload-reload-open'), false);
  }
});

test('acknowledged upload below a growing file list is scrolled into view before exact source opening', async t => {
  const { context, ledger, clicks, admissions, swipes } = offlineUpload(t, 'persisted', { acknowledgement: 'after-scroll' });
  await uploadFilesSource(context);
  assert.equal(clicks.filter(id => id === 'files-upload').length, 1);
  assert.equal(ledger.requests.filter(row => row.method === 'POST').length, 1);
  assert.ok(swipes.includes('down'));
  assert.equal(admissions.length, 1);
});

test('server acknowledgement without reachable UI confirmation stays failed and never reuploads or opens', async t => {
  const { context, ledger, clicks, admissions, swipes } = offlineUpload(t, 'persisted', { acknowledgement: 'never' });
  await assert.rejects(uploadFilesSource(context), /NATIVE_CONTROL_NOT_VISIBLE/);
  assert.equal(clicks.filter(id => id === 'files-upload').length, 1);
  assert.equal(ledger.requests.filter(row => row.method === 'POST').length, 1);
  assert.equal(swipes.length, 9);
  assert.deepEqual(admissions, []);
  assert.equal(clicks.includes('files-reload'), false);
});
