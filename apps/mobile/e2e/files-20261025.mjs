import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { FixtureUnavailable, admitApplication, verifiedFile } from './fixture-contract.mjs';
import { authenticate, delta, openMatter, readOnlyTraffic, traffic } from './journeys.mjs';
import { absent, click, dispatchNativeClick, find, findQuery, read, selector, swipe, visible } from './native-ui.mjs';
import { reconcileInventory } from './support.mjs';

// Supplement only: not part of core-20261025.json or a claim of native execution.
// IDs/hash were supplied by the fixture owner. Name/text are the exact CLEAN
// fixture in scripts/mobile/local-fixture.py, independently hash-bound below.
export const source = Object.freeze({
  matterId: 'e7cd2909-f8a3-4e6d-88e3-571711046eb4',
  attachmentId: '26bdc03b-6e23-410b-b961-d5410f15466d',
  sha256: '32df2bb8255ed04c167cd8c99bcd471b606b44aea770cc3612b13e86d8613fd6',
  filename: 'mobile-source.txt',
  text: 'Synthetic CaseOps mobile source. No legal authority or customer data.\n',
});
export const inventory = Object.freeze({
  schemaVersion: 1,
  inventoryId: 'native-files-supplement-2026-10-25',
  platforms: Object.freeze(['android']),
  scope: 'Supplementary Android Files/TXT and explicit native picker upload; not full MOB-21..26 acceptance',
  cases: Object.freeze([
    Object.freeze({ id: 'FILES-01', title: 'Exact seeded Files row, source SHA-256, reload, private TXT open and return to Files', groups: ['MOB-21', 'MOB-26', 'MOB-30'],
      prerequisites: ['parent-owned admitted APK/Appium context and real Firefox/MFA authentication', 'hash-verified seedEvidence with exact sourceId/sourceSha256/matter', 'unchanged synthetic source fixture and read-admitted marked gateway', 'exact source controls and visible TXT content in the actual APK'] }),
    Object.freeze({ id: 'FILES-02', title: 'Actual Android picker upload and persisted exact source readback', groups: ['MOB-22', 'MOB-24', 'MOB-25'],
      requiresNativeFixture: 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED',
      prerequisites: ['parent-observed Android picker package, source and selectors', 'actual device file metadata/hash and explicit mutation authorization', 'exact serving upload route admission and lifecycle-version contract', 'server acknowledgement identity and persisted source readback'] }),
  ]),
});

export function validateSourceAnchor(value = source) {
  for (const key of ['matterId', 'attachmentId', 'sha256', 'filename', 'text'])
    assert.equal(value?.[key], source[key], 'FILES_SOURCE_ANCHOR_MISMATCH');
  assert.equal(createHash('sha256').update(value.text, 'utf8').digest('hex'), value.sha256, 'FILES_FIXTURE_TEXT_HASH_MISMATCH');
  return value;
}

export function validateSourceReceipt(seed) {
  assert.equal(seed?.environment, 'docker-integration', 'FILES_REAL_SEED_RECEIPT_REQUIRED');
  assert.equal(seed.syntheticDataOnly, true, 'FILES_SYNTHETIC_SEED_REQUIRED');
  assert.equal(seed.matter?.id, source.matterId, 'FILES_SEED_MATTER_MISMATCH');
  assert.equal(seed.sourceId, source.attachmentId, 'FILES_SEED_ATTACHMENT_MISMATCH');
  assert.equal(seed.sourceSha256, source.sha256, 'FILES_SEED_SOURCE_HASH_MISMATCH');
  assert.equal(seed.cleanUploadAndDownload, true, 'FILES_SEED_SOURCE_READBACK_REQUIRED');
  return validateSourceAnchor();
}

export function validateFilesContext(context) {
  const fixture = context?.fixture;
  if (context?.platform !== 'android' || !fixture || fixture.environment !== 'docker-integration' || fixture.syntheticDataOnly !== true)
    throw new FixtureUnavailable('FILES_ISOLATED_ANDROID_FIXTURE_REQUIRED');
  if (!context.driver || typeof context.driver.$ !== 'function' || typeof context.driver.waitUntil !== 'function')
    throw new FixtureUnavailable('FILES_PARENT_OWNED_APPIUM_CONTEXT_REQUIRED');
  if (!fixture.apiOrigin) throw new FixtureUnavailable('FILES_LOCAL_API_REQUIRED');
  admitApplication(fixture, 'android');
  for (const key of ['backendSha', 'webSha', 'binarySourceSha']) {
    if (!/^[a-f0-9]{40}$/.test(fixture[key] || '')) throw new FixtureUnavailable('FILES_EXACT_RELEASE_IDENTITIES_REQUIRED');
  }
  assert.equal(fixture.backendSha, fixture.binarySourceSha, 'FILES_API_APK_RELEASE_MISMATCH');
  assert.equal(fixture.webSha, fixture.binarySourceSha, 'FILES_WEB_APK_RELEASE_MISMATCH');
  const origin = new URL(fixture.apiOrigin);
  assert.equal(origin.protocol, 'https:', 'FILES_STRICT_NATIVE_TLS_REQUIRED');
  assert.ok(['localhost', '127.0.0.1', '10.0.2.2', '[::1]'].includes(origin.hostname), 'FILES_LOCAL_API_REQUIRED');
  assert.ok(!origin.username && !origin.password && !origin.search && !origin.hash && origin.pathname === '/', 'FILES_CLEAN_API_ORIGIN_REQUIRED');
  if (fixture.matter?.id !== source.matterId || !fixture.matter.search || !fixture.matter.title || !fixture.matter.identityLabel)
    throw new FixtureUnavailable('FILES_EXACT_SEEDED_MATTER_REQUIRED');
  if (!context.gatewayBaseline || !fixture.gatewayRunId || !fixture.gatewayUrl)
    throw new FixtureUnavailable('FILES_PARENT_GATEWAY_BASELINE_REQUIRED');
  assert.equal(context.gatewayBaseline.runId, fixture.gatewayRunId, 'FILES_GATEWAY_BASELINE_MISMATCH');
  if (!fixture.seedEvidence?.path || !fixture.seedEvidence.sha256)
    throw new FixtureUnavailable('FILES_HASH_VERIFIED_SEED_RECEIPT_REQUIRED');
  let seed;
  try { seed = JSON.parse(verifiedFile(fixture.seedEvidence.path, fixture.seedEvidence.sha256, 65536)); }
  catch (error) {
    if (error?.code === 'ENOENT') throw new FixtureUnavailable('FILES_HASH_VERIFIED_SEED_RECEIPT_MISSING');
    throw error;
  }
  validateSourceReceipt(seed);
  for (const key of ['companyId', 'membershipId']) {
    assert.ok(typeof fixture[key] === 'string' && fixture[key].length > 0, 'FILES_SEED_ACCOUNT_REQUIRED');
    assert.equal(seed[key], fixture[key], 'FILES_SEED_ACCOUNT_MISMATCH');
  }
  return source;
}

export async function expandSourceDetails(context, control, requested = new Set()) {
  const show = await visible(control, selector(context.platform, 'text', 'Source details'));
  const hide = await visible(control, selector(context.platform, 'text', 'Hide source details'));
  assert.equal(Number(!!show) + Number(!!hide), 1, 'FILES_SOURCE_DETAILS_STATE_UNOBSERVED');
  if (show) {
    if (requested.has(show.elementId)) return;
    assert.ok(requested.size < 2, 'FILES_SOURCE_REPLACEMENT_BOUND');
    requested.add(show.elementId);
    await dispatchNativeClick(context, show, 'text', 'Source details');
  }
}

export async function readSourceHash(context, anchor) {
  const hashId = `files-hash-${anchor.attachmentId}`;
  const detailsId = `files-source-${anchor.attachmentId}`;
  await find(context, 'id', detailsId, { scroll: true });
  const requested = new Set();
  let hash;
  // Reload unmounts FileRow. Reacquire its current control, never replay an
  // expansion whose acknowledgement is missing, and retain the existing bound.
  for (let attempt = 0; attempt <= 9; attempt++) {
    let failure;
    try {
      await context.driver.waitUntil(async () => {
        try {
          for (const id of ['files-inactive', 'files-restricted', 'files-error'])
            assert.equal(await visible(context.driver, selector(context.platform, 'id', id)), undefined, 'FILES_SOURCE_NOT_CURRENTLY_READABLE');
          if (await visible(context.driver, selector(context.platform, 'id', 'files-loading'))) return false;
          const details = await visible(context.driver, selector(context.platform, 'id', detailsId));
          if (details) {
            const prior = requested.size;
            await expandSourceDetails(context, details, requested);
            if (requested.size > prior) context.record?.({ type: 'source_details_expansion', attachmentId: anchor.attachmentId,
              requestCount: requested.size, attempt });
          }
          hash = await visible(context.driver, selector(context.platform, 'id', hashId));
          return !!hash;
        } catch (error) { failure = error; return true; }
      }, { timeout: 1500, interval: 150, timeoutMsg: 'NATIVE_CONTROL_NOT_VISIBLE' });
    } catch (error) {
      if (!error.message.includes('NATIVE_CONTROL_NOT_VISIBLE') || attempt === 9) throw error;
      await swipe(context, attempt < 3 ? 'up' : 'down');
      continue;
    }
    if (failure) throw failure;
    return hash.getText();
  }
}

async function sourceDetails(context, anchor = source) {
  await find(context, 'id', `files-row-${anchor.attachmentId}`, { scroll: true });
  assert.equal(await read(context, 'id', `files-name-${anchor.attachmentId}`, { scroll: true }), anchor.filename, 'FILES_WRONG_SOURCE_FILENAME');
  assert.equal(await readSourceHash(context, anchor), anchor.sha256, 'FILES_SOURCE_HASH_MISMATCH');
}

async function enterFiles(context) {
  validateFilesContext(context);
  await openMatter(context);
  await click(context, 'id', 'matter-files');
  assert.equal(await read(context, 'id', 'files-matter-code', { scroll: true }), context.fixture.matter.identityLabel, 'FILES_WRONG_MATTER_CODE');
  assert.equal(await read(context, 'id', 'files-matter-title', { scroll: true }), context.fixture.matter.title, 'FILES_WRONG_MATTER_TITLE');
  await sourceDetails(context);
}

export async function readFilesSource(context) {
  validateFilesContext(context);
  await authenticate(context);
  const before = await traffic(context);
  await enterFiles(context);
  const workspaceRoute = `/api/matters/${source.matterId}/workspace`;
  const reload = await traffic(context);
  await click(context, 'id', 'files-reload', { scroll: true });
  await context.driver.waitUntil(async () => delta(reload, await traffic(context)).some((row) => row.method === 'GET' && row.route === workspaceRoute && row.status === 200),
    { timeout: 10000, interval: 200, timeoutMsg: 'FILES_AUTHORITATIVE_RELOAD_MISSING' });
  await sourceDetails(context);
  const opening = await traffic(context);
  const open = await find(context, 'id', `files-open-${source.attachmentId}`, { scroll: true });
  assert.equal(await open.isEnabled(), true, 'FILES_TXT_READER_UNAVAILABLE');
  await dispatchNativeClick(context, open, 'id', `files-open-${source.attachmentId}`);
  await find(context, 'id', 'private-document-viewer');
  assert.equal(await read(context, 'id', 'viewer-filename'), source.filename, 'FILES_VIEWER_WRONG_SOURCE');
  // UiAutomator may omit a terminal line break. The byte identity is separately
  // pinned by Source details and the app's render-before-hash verification fence.
  assert.equal((await read(context, 'id', 'viewer-text')).trimEnd(), source.text.trimEnd(), 'FILES_TXT_CONTENT_MISMATCH');
  assert.equal(await read(context, 'id', 'viewer-position'), 'Segment 1 of 1', 'FILES_TXT_SEGMENT_MISMATCH');
  for (const id of ['viewer-blocked', 'viewer-unsupported', 'viewer-docx-limitation']) await absent(context, 'id', id);
  const downloadRoute = `/api/matters/${source.matterId}/attachments/${source.attachmentId}/download`;
  const reads = delta(opening, await traffic(context)).filter((row) => row.method === 'GET' && row.route === downloadRoute);
  assert.equal(reads.filter((row) => row.status === 200).length, 1, 'FILES_EXACT_FULL_SOURCE_READ_REQUIRED');
  assert.ok(reads.filter((row) => row.status === 206).length >= 2, 'FILES_BEFORE_AFTER_RANGE_PROBES_REQUIRED');
  assert.ok(reads.length <= 12 && reads.every((row) => [200, 206].includes(row.status)), 'FILES_UNEXPECTED_SOURCE_READS');
  await click(context, 'id', 'viewer-close');
  await absent(context, 'id', 'private-document-viewer');
  await absent(context, 'id', 'viewer-text');
  // "matter-files" is also the tab's ID; use a unique Files fact after return.
  await find(context, 'id', 'files-matter-code', { scroll: true });
  await sourceDetails(context);
  readOnlyTraffic(delta(before, await traffic(context)));
  context.record?.({ type: 'assertion', boundary: 'native-files-txt-read-return', matterId: source.matterId,
    attachmentId: source.attachmentId, sourceSha256: source.sha256, actualNativeText: true, uploadExercised: false });
}

// Parent may call this solely to inspect the REAL chooser after authorizing its
// owned device fixture. It is not an upload scenario or a successful receipt.
export async function openNativeFilesPickerForInspection(context) {
  validateFilesContext(context);
  await authenticate(context);
  await enterFiles(context);
  const choose = await find(context, 'id', 'files-choose', { scroll: true });
  assert.equal(await choose.isEnabled(), true, 'FILES_PICKER_UNAVAILABLE');
  await dispatchNativeClick(context, choose, 'id', 'files-choose');
  return { state: 'blocked', reason: 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED' };
}

export function validateUploadFixture(context) {
  const value = context?.fixture?.upload;
  if (!value) throw new FixtureUnavailable('ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED');
  validateFilesContext(context);
  assert.match(value.filename || '', /^CaseOps-native-clean-[a-f0-9]{12}\.txt$/, 'OWNED_PICKER_FILENAME_REQUIRED');
  assert.equal(value.devicePath, `/sdcard/Download/${value.filename}`, 'EXACT_OWNED_DEVICE_PATH_REQUIRED');
  assert.match(value.sha256 || '', /^[a-f0-9]{64}$/, 'OWNED_UPLOAD_HASH_REQUIRED');
  assert.ok(Number.isSafeInteger(value.sizeBytes) && value.sizeBytes > 0 && value.sizeBytes <= 4096, 'SMALL_SYNTHETIC_PICKER_FIXTURE_REQUIRED');
  assert.equal(Buffer.byteLength(value.text), value.sizeBytes, 'OWNED_UPLOAD_TEXT_SIZE_MISMATCH');
  assert.equal(createHash('sha256').update(value.text).digest('hex'), value.sha256, 'OWNED_UPLOAD_TEXT_HASH_MISMATCH');
  const proof = JSON.parse(verifiedFile(value.deviceEvidence.path, value.deviceEvidence.sha256, 8192));
  for (const key of ['filename', 'devicePath', 'sha256', 'sizeBytes']) assert.equal(proof[key], value[key], 'DEVICE_UPLOAD_PROOF_MISMATCH');
  assert.equal(proof.observedDeviceHash, value.sha256);
  assert.equal(proof.udid, context.fixture.udid);
  assert.equal(proof.syntheticDataOnly, true);
  const picker = JSON.parse(verifiedFile(value.pickerEvidence.path, value.pickerEvidence.sha256, 65536));
  assert.equal(picker.kind, 'observed-native-android-document-picker');
  assert.equal(picker.package, 'com.android.documentsui');
  assert.deepEqual(picker.controls, { roots: { kind: 'label', value: 'Show roots' }, rootList: { kind: 'id', value: 'com.android.documentsui:id/roots_list' }, downloads: { kind: 'text', value: 'Downloads' }, fileTitleId: 'android:id/title' });
  assert.equal(typeof context.admitUploadedFileRead, 'function', 'EXACT_ACKNOWLEDGED_UPLOAD_READ_ADMISSION_REQUIRED');
  return { ...value, picker };
}

export async function uploadFilesSource(context) {
  const upload = validateUploadFixture(context);
  await authenticate(context);
  await enterFiles(context);
  const before = await traffic(context);
  const expectedNameQuery = `android=new UiSelector().resourceIdMatches("files-name-.*").text(${JSON.stringify(upload.filename)})`;
  assert.equal(await visible(context.driver, expectedNameQuery), undefined, 'UPLOAD_FIXTURE_FILENAME_ALREADY_RETAINED');
  await click(context, 'id', 'files-choose', { scroll: true });
  await context.driver.waitUntil(async () => await context.driver.getCurrentPackage() === upload.picker.package,
    { timeout: 15000, interval: 200, timeoutMsg: 'EXACT_DOCUMENT_PICKER_NOT_OPENED' });
  await click(context, upload.picker.controls.roots.kind, upload.picker.controls.roots.value);
  const roots = await find(context, 'id', upload.picker.controls.rootList.value);
  let downloads;
  await context.driver.waitUntil(async () => !!(downloads = await visible(roots, selector('android', 'text', 'Downloads'))),
    { timeout: 10000, interval: 150, timeoutMsg: 'OBSERVED_DOWNLOADS_ROOT_NOT_READY' });
  await dispatchNativeClick(context, downloads, 'text', 'Downloads');
  const chosen = await findQuery(context, `android=new UiSelector().resourceId("android:id/title").text(${JSON.stringify(upload.filename)})`);
  assert.equal(await chosen.getText(), upload.filename);
  await dispatchNativeClick(context, chosen, 'text', upload.filename);
  await context.driver.waitUntil(async () => await context.driver.getCurrentPackage() === context.fixture.appId,
    { timeout: 15000, interval: 200, timeoutMsg: 'PICKER_DID_NOT_RETURN_TO_BOUND_APP' });
  await find(context, 'id', 'files-selection', { scroll: true });
  assert.equal(await read(context, 'id', 'files-matter-code', { scroll: true }), context.fixture.matter.identityLabel);
  const button = await find(context, 'id', 'files-upload', { scroll: true });
  assert.equal(await button.isEnabled(), true, 'NATIVE_UPLOAD_NOT_ENABLED');
  await dispatchNativeClick(context, button, 'id', 'files-upload');
  await context.driver.waitUntil(async () => {
    if (await visible(context.driver, 'id=files-upload-unknown')) throw new FixtureUnavailable('UPLOAD_OUTCOME_UNKNOWN_NO_REPLAY');
    assert.equal(await visible(context.driver, 'id=files-upload-rejected'), undefined, 'NATIVE_UPLOAD_REJECTED');
    if (await visible(context.driver, 'id=files-upload-persisted')) return true;
    // A new row can move confirmation below the viewport. Wait for the exact
    // transport acknowledgement before scrolling; never submit the file again.
    return delta(before, await traffic(context)).some(row => row.method === 'POST'
      && row.route === `/api/matters/${source.matterId}/attachments` && row.status === 200);
  }, { timeout: 30000, interval: 200, timeoutMsg: 'NATIVE_UPLOAD_PERSISTENCE_NOT_ACKNOWLEDGED' });
  const changes = delta(before, await traffic(context));
  const posts = changes.filter(row => row.method === 'POST');
  assert.equal(posts.length, 1, 'NATIVE_UPLOAD_NOT_EXACTLY_ONCE');
  assert.equal(posts[0].route, `/api/matters/${source.matterId}/attachments`);
  assert.equal(posts[0].status, 200, 'NATIVE_UPLOAD_NOT_ACKNOWLEDGED');
  await find(context, 'id', 'files-upload-persisted', { scroll: true });
  const name = await findQuery(context, expectedNameQuery, { scroll: true });
  const match = /^files-name-([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/.exec(await name.getAttribute('resource-id'));
  assert.ok(match, 'ACTUAL_UPLOADED_ATTACHMENT_ID_REQUIRED');
  const anchor = { ...upload, matterId: source.matterId, attachmentId: match[1] };
  assert.notEqual(anchor.attachmentId, source.attachmentId);
  await sourceDetails(context, anchor);
  await click(context, 'id', 'files-reload', { scroll: true });
  await sourceDetails(context, anchor);
  const admission = await context.admitUploadedFileRead({ ...anchor, acknowledgement: posts[0] });
  const downloadRoute = `/api/matters/${source.matterId}/attachments/${anchor.attachmentId}/download`;
  assert.equal(admission.route, `GET ${downloadRoute}`, 'EXACT_NEW_SOURCE_ROUTE_REQUIRED');
  const opening = await traffic(context);
  await click(context, 'id', `files-open-${anchor.attachmentId}`, { scroll: true });
  assert.equal(await read(context, 'id', 'viewer-filename'), upload.filename);
  assert.equal((await read(context, 'id', 'viewer-text')).trimEnd(), upload.text.trimEnd());
  const reads = delta(opening, await traffic(context)).filter(row => row.method === 'GET' && row.route === downloadRoute);
  assert.equal(reads.filter(row => row.status === 200).length, 1);
  assert.ok(reads.filter(row => row.status === 206).length >= 2);
  await click(context, 'id', 'viewer-close');
  await absent(context, 'id', 'viewer-text');
  assert.equal(delta(before, await traffic(context)).filter(row => row.method === 'POST').length, 1, 'UPLOAD_REPLAY_AFTER_READBACK');
  context.record?.({ type: 'assertion', boundary: 'native-picker-upload-reload-open', attachmentId: anchor.attachmentId,
    sha256: upload.sha256, sizeBytes: upload.sizeBytes, acknowledgementRequestId: posts[0].requestId, admission });
}

export const scenarios = Object.freeze([
  Object.freeze({ id: 'FILES-01', authenticateInCall: true, run: readFilesSource }),
  Object.freeze({ id: 'FILES-02', authenticateInCall: true, run: uploadFilesSource }),
]);
export function collectFiles(platform = 'android') {
  assert.equal(platform, 'android', 'FILES_ANDROID_ONLY');
  const intended = inventory.cases.map(({ id }) => `${platform}:${id}`);
  const discovered = scenarios.map(({ id }) => `${platform}:${id}`);
  reconcileInventory(intended, discovered);
  return { platform, inventoryId: inventory.inventoryId, scope: inventory.scope, intended, discovered };
}
