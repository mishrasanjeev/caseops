import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { admitApplication, FixtureUnavailable, verifiedFile } from './fixture-contract.mjs';
import { browserOrigin } from './browser-handoff.mjs';
import { delta, openMatter, readOnlyTraffic, traffic } from './journeys.mjs';
import { absent, backgroundAndResume, click, dispatchNativeClick, find, findQuery, nativeAction, read, restart, selector, visible } from './native-ui.mjs';
import { expandSourceDetails } from './files-20261025.mjs';
import { reconcileInventory } from './support.mjs';

const APP = 'ai.caseops.mobile.dev.localacceptance', SHA = /^[a-f0-9]{64}$/;
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const KINDS = ['txt', 'pdf', 'png', 'jpeg', 'docx'];
const json = ref => JSON.parse(verifiedFile(ref?.path, ref?.sha256));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const event = (context, boundary, facts = {}) => context.record?.({ type: 'assertion', boundary, ...facts });
const fail = code => { throw new FixtureUnavailable(code); };
export const ANDROID_UPLOAD_PERSISTED_MESSAGE = 'Upload acknowledged and the same source confirmed after reload. A separate clean-scan receipt is not supplied by this server.';
export const androidFilesInventory = Object.freeze({ schemaVersion: 1, inventoryId: 'native-android-files-2026-10-26',
  platforms: Object.freeze(['android']), scope: 'Android native document picker, five clean uploads, private readers and bounded app-owned filesystem privacy; separate from core23 and physical devices',
  cases: Object.freeze([
    ['FILES-01', 'Seeded TXT identity, authoritative reload, private read and return'],
    ['FILES-02', 'Observed Android picker cancellation creates no selection or upload'],
    ['FILES-03', 'Actual TXT selection and explicit Clear create no upload'],
    ['FILES-04', 'Rapid TXT activation admits one upload and original-byte persisted identity'],
    ['FILES-05', 'Exactly one two-page PDF upload and persisted source'],
    ['FILES-06', 'Exactly one PNG upload and persisted source'],
    ['FILES-07', 'Exactly one JPEG upload and persisted source'],
    ['FILES-08', 'Exactly one DOCX upload and persisted source'],
    ['FILES-09', 'Actual PDF page/zoom acknowledgements after fresh normal authentication'],
    ['FILES-10', 'Actual PNG and JPEG renderer zoom acknowledgements'],
    ['FILES-11', 'DOCX truthfully remains unavailable in the private reader'],
    ['FILES-12', 'Viewer Home and warm resume remove private content'],
    ['FILES-13', 'Selected-file Home and warm resume discard selection'],
    ['FILES-14', 'Selection Stay and Leave Files retain discard semantics'],
    ['FILES-15', 'Restart restores neither selection nor a private reader'],
    ['FILES-16', 'Files-history acknowledged logout purges private state'],
    ['FILES-17', 'Signed-out restart and app-owned filesystem privacy'],
  ].map(([id, title]) => Object.freeze({ id, title }))) });

export function collectAndroidFiles(platform = 'android') {
  assert.equal(platform, 'android', 'ANDROID_FILES_PLATFORM_REQUIRED');
  const intended = androidFilesInventory.cases.map(({ id }) => `android:${id}`);
  const discovered = androidFilesScenarios.map(({ id }) => `android:${id}`);
  reconcileInventory(intended, discovered);
  return { platform, inventoryId: androidFilesInventory.inventoryId, scope: androidFilesInventory.scope, intended, discovered };
}
export function validateAndroidSourceAnchor(source) {
  assert.ok(UUID.test(source?.matterId || '') && UUID.test(source?.attachmentId || ''), 'ANDROID_FILES_SOURCE_IDENTITIES_REQUIRED');
  assert.match(source.sha256 || '', SHA, 'ANDROID_FILES_SOURCE_HASH_REQUIRED');
  assert.ok(/^[A-Za-z0-9][A-Za-z0-9._-]{1,200}$/.test(source.filename || ''), 'ANDROID_FILES_SOURCE_NAME_REQUIRED');
  assert.ok(Number.isSafeInteger(source.sizeBytes) && source.sizeBytes > 0 && source.sizeBytes <= 1048576, 'ANDROID_FILES_SOURCE_SIZE_REQUIRED');
  if (source.text !== undefined) {
    assert.equal(Buffer.byteLength(source.text), source.sizeBytes, 'ANDROID_FILES_SOURCE_SIZE_MISMATCH');
    assert.equal(hash(Buffer.from(source.text)), source.sha256, 'ANDROID_FILES_SOURCE_HASH_MISMATCH');
  }
  return source;
}
export function validateAndroidSourceSeed(fixture, source) {
  validateAndroidSourceAnchor(source);
  const seed = json(fixture.seedEvidence), base = seed.provenance?.baseSeed ? json(seed.provenance.baseSeed) : seed;
  for (const value of [seed, base]) {
    assert.equal(value.environment, 'docker-integration', 'ANDROID_FILES_REAL_SEED_REQUIRED');
    assert.equal(value.syntheticDataOnly, true, 'ANDROID_FILES_SYNTHETIC_SEED_REQUIRED');
    assert.equal(value.companyId, fixture.companyId, 'ANDROID_FILES_SEED_TENANT_MISMATCH');
    assert.equal(value.matter?.id, source.matterId, 'ANDROID_FILES_SEED_MATTER_MISMATCH');
  }
  assert.equal(seed.membershipId, fixture.membershipId, 'ANDROID_FILES_SEED_MEMBER_MISMATCH');
  assert.equal(base.cleanUploadAndDownload, true, 'ANDROID_FILES_BASE_SOURCE_READBACK_REQUIRED');
  assert.equal(base.sourceId, source.attachmentId, 'ANDROID_FILES_SEED_SOURCE_ID_MISMATCH');
  assert.equal(base.sourceSha256, source.sha256, 'ANDROID_FILES_SEED_SOURCE_HASH_MISMATCH');
  if (seed.sourceId !== undefined) assert.equal(seed.sourceId, source.attachmentId, 'ANDROID_FILES_DIRECT_SOURCE_CONTRADICTS_BASE');
  if (seed.sourceSha256 !== undefined) assert.equal(seed.sourceSha256, source.sha256, 'ANDROID_FILES_DIRECT_SOURCE_CONTRADICTS_BASE');
  return source;
}
export function validateAndroidFilesContext(context) {
  assert.equal(context?.platform, 'android', 'ANDROID_FILES_PLATFORM_REQUIRED');
  const fixture = context.fixture;
  assert.equal(fixture?.environment, 'docker-integration', 'ANDROID_FILES_ISOLATION_REQUIRED');
  assert.equal(fixture.syntheticDataOnly, true, 'ANDROID_FILES_SYNTHETIC_FIXTURE_REQUIRED');
  assert.equal(admitApplication(fixture, 'android'), APP, 'ANDROID_FILES_LOCAL_QA_APP_REQUIRED');
  for (const key of ['backendSha', 'webSha', 'binarySourceSha']) assert.match(fixture[key] || '', /^[a-f0-9]{40}$/, 'ANDROID_FILES_RELEASE_IDENTITIES_REQUIRED');
  assert.equal(fixture.backendSha, fixture.binarySourceSha, 'ANDROID_FILES_API_BINARY_MISMATCH');
  assert.equal(fixture.webSha, fixture.binarySourceSha, 'ANDROID_FILES_WEB_BINARY_MISMATCH');
  browserOrigin(fixture.apiOrigin); browserOrigin(fixture.gatewayUrl);
  assert.equal(context.gatewayBaseline?.runId, fixture.gatewayRunId, 'ANDROID_FILES_GATEWAY_BASELINE_REQUIRED');
  assert.equal(typeof context.driver?.elementClick, 'function', 'ANDROID_FILES_NATIVE_PROTOCOL_REQUIRED');
  assert.equal(typeof context.driver?.$$, 'function', 'ANDROID_FILES_ACTUAL_DRIVER_REQUIRED');
  assert.ok(context.filesState && typeof context.filesState.uploads === 'object', 'ANDROID_FILES_RUN_STATE_REQUIRED');
  if (context.filesState.mutationUncertain) fail('ANDROID_FILES_UPLOAD_UNCERTAIN_NO_REPLAY');
  assert.equal(fixture.matter?.id, context.source?.matterId, 'ANDROID_FILES_SOURCE_PARENT_MISMATCH');
  return validateAndroidSourceSeed(fixture, context.source);
}
export function validateAndroidFileAsset(context, kind) {
  assert.ok(KINDS.includes(kind), 'ANDROID_FILES_ASSET_KIND_REQUIRED');
  const asset = context.assets?.uploads?.[kind]; assert.ok(asset, 'ANDROID_FILES_ASSET_REQUIRED');
  assert.equal(asset.id, kind, 'ANDROID_FILES_ASSET_KIND_MISMATCH');
  assert.ok(/^CaseOps-android-files-[a-f0-9]{12}-[a-z]+\.[a-z]+$/.test(asset.filename || ''), 'ANDROID_FILES_ASSET_NAME_REQUIRED');
  assert.match(asset.sha256 || '', SHA, 'ANDROID_FILES_ASSET_HASH_REQUIRED');
  assert.ok(Number.isSafeInteger(asset.sizeBytes) && asset.sizeBytes > 0 && asset.sizeBytes <= 262144, 'ANDROID_FILES_ASSET_BOUND');
  assert.equal(verifiedFile(asset.path, asset.sha256, 262144).length, asset.sizeBytes, 'ANDROID_FILES_ASSET_SIZE_MISMATCH');
  const manifest = json(context.assets.manifestEvidence);
  assert.equal(manifest.kind, 'android-files-synthetic-fixtures', 'ANDROID_FILES_MANIFEST_REQUIRED');
  assert.equal(manifest.platform, 'android', 'ANDROID_FILES_MANIFEST_PLATFORM_REQUIRED');
  assert.equal(manifest.syntheticDataOnly, true, 'ANDROID_FILES_SYNTHETIC_MANIFEST_REQUIRED');
  assert.equal(manifest.assets.filter(value => value.id === kind && value.filename === asset.filename
    && value.sha256 === asset.sha256 && value.sizeBytes === asset.sizeBytes).length, 1, 'ANDROID_FILES_ASSET_MANIFEST_MISMATCH');
  if (asset.text !== undefined) assert.equal(hash(Buffer.from(asset.text)), asset.sha256, 'ANDROID_FILES_TEXT_ORACLE_MISMATCH');
  if (kind === 'pdf') assert.equal(asset.pages, 2, 'ANDROID_FILES_TWO_PAGE_PDF_REQUIRED');
  return asset;
}
export function validateAndroidPicker(context, asset) {
  const value = context.provider, proof = json(value?.evidence);
  for (const [key, expected] of Object.entries({ schemaVersion: 1, observed: true, platform: 'android', udid: context.fixture.udid,
    appId: context.fixture.appId, packageName: 'com.android.documentsui' })) assert.equal(proof[key], expected, 'ANDROID_FILES_OBSERVED_PICKER_REQUIRED');
  assert.ok(/^CaseOpsFiles-[A-Za-z0-9-]{6,64}$/.test(value.folderName || ''), 'ANDROID_FILES_OWNED_FOLDER_REQUIRED');
  assert.equal(proof.folderName, value.folderName, 'ANDROID_FILES_PICKER_FOLDER_MISMATCH');
  verifiedFile(context.fixture.buildReceipt?.path, context.fixture.buildReceipt?.sha256);
  assert.deepEqual(proof.buildReceipt, context.fixture.buildReceipt, 'ANDROID_FILES_PICKER_BUILD_MISMATCH');
  assert.deepEqual(proof.manifestEvidence, context.assets.manifestEvidence, 'ANDROID_FILES_PICKER_MANIFEST_MISMATCH');
  const controls = { roots: { kind: 'label', value: 'Show roots' }, rootList: { kind: 'id', value: 'com.android.documentsui:id/roots_list' },
    downloads: { kind: 'text', value: 'Downloads' }, folder: { kind: 'text', value: value.folderName }, fileTitleId: 'android:id/title', cancel: 'android-back' };
  assert.deepEqual(proof.controls, controls, 'ANDROID_FILES_OBSERVED_PICKER_CONTROLS_REQUIRED');
  if (asset) assert.equal(proof.assets?.filter(item => item.filename === asset.filename && item.sha256 === asset.sha256
    && item.sizeBytes === asset.sizeBytes && item.observedProviderHash === asset.sha256 && item.pickerName === asset.filename).length,
  1, 'ANDROID_FILES_OBSERVED_PICKER_ASSET_REQUIRED');
  return { ...proof, controls };
}
const wait = (context, condition, timeout, code) => context.driver.waitUntil(condition, { timeout, interval: 200, timeoutMsg: code });
async function enterFiles(context) {
  validateAndroidFilesContext(context); await openMatter(context); await click(context, 'id', 'matter-files');
  assert.equal(await read(context, 'id', 'files-matter-code', { scroll: true }), context.fixture.matter.identityLabel, 'ANDROID_FILES_WRONG_MATTER');
  assert.equal(await read(context, 'id', 'files-matter-title', { scroll: true }), context.fixture.matter.title, 'ANDROID_FILES_WRONG_MATTER_TITLE');
}
async function details(context, anchor) {
  assert.equal(await read(context, 'id', `files-name-${anchor.attachmentId}`, { scroll: true }), anchor.filename, 'ANDROID_FILES_WRONG_FILENAME');
  await expandSourceDetails(context, await find(context, 'id', `files-source-${anchor.attachmentId}`, { scroll: true }));
  assert.equal(await read(context, 'id', `files-hash-${anchor.attachmentId}`, { scroll: true }), anchor.sha256, 'ANDROID_FILES_WRONG_SOURCE_HASH');
}
async function reload(context, anchor) {
  const before = await traffic(context); await click(context, 'id', 'files-reload', { scroll: true });
  await wait(context, async () => delta(before, await traffic(context)).some(row => row.method === 'GET'
    && row.route === `/api/matters/${anchor.matterId}/workspace` && row.status === 200), 10000, 'ANDROID_FILES_RELOAD_READ_REQUIRED');
  await details(context, anchor);
}
async function noSelection(context) { for (const id of ['files-selection', 'files-upload']) await absent(context, 'id', id); await find(context, 'id', 'files-choose', { scroll: true }); }
export async function chooseAndroidFile(context, asset, { cancel = false } = {}) {
  const picker = validateAndroidPicker(context, asset);
  await click(context, 'id', 'files-choose', { scroll: true });
  await wait(context, async () => await context.driver.getCurrentPackage() === picker.packageName, 15000, 'ANDROID_FILES_PICKER_PACKAGE_REQUIRED');
  if (cancel) await context.driver.pressKeyCode(4);
  else {
    await click(context, picker.controls.roots.kind, picker.controls.roots.value);
    const roots = await find(context, 'id', picker.controls.rootList.value);
    let downloads;
    await wait(context, async () => !!(downloads = await visible(roots, selector('android', 'text', 'Downloads'))), 10000, 'ANDROID_FILES_DOWNLOADS_ROOT_REQUIRED');
    await dispatchNativeClick(context, downloads, 'text', 'Downloads');
    await click(context, picker.controls.folder.kind, picker.controls.folder.value, { scroll: true });
    const selected = await findQuery(context, `android=new UiSelector().resourceId("android:id/title").text(${JSON.stringify(asset.filename)})`, { scroll: true });
    assert.equal(await selected.getText(), asset.filename, 'ANDROID_FILES_WRONG_PICKER_FILENAME');
    await dispatchNativeClick(context, selected, 'text', asset.filename);
  }
  await wait(context, async () => await context.driver.getCurrentPackage() === context.fixture.appId, 15000, 'ANDROID_FILES_PICKER_RETURN_REQUIRED');
  await find(context, 'id', 'files-matter-code');
  if (!cancel) { await find(context, 'id', 'files-selection', { scroll: true }); assert.equal(await (await find(context, 'id', 'files-upload', { scroll: true })).isEnabled(), true, 'ANDROID_FILES_UPLOAD_DISABLED'); }
}
export function validateAndroidUploadAcknowledgement(requests, matterId, { requireRead = false } = {}) {
  const posts = requests.filter(row => row.method === 'POST' && row.route === `/api/matters/${matterId}/attachments`);
  assert.equal(posts.length, 1, 'ANDROID_FILES_UPLOAD_NOT_EXACTLY_ONCE'); assert.equal(posts[0].status, 200, 'ANDROID_FILES_CANONICAL_UPLOAD_ACK_REQUIRED');
  const other = requests.filter(row => row !== posts[0]);
  assert.ok(other.every(row => ['GET', 'HEAD', 'OPTIONS'].includes(row.method)
    || row.method === 'POST' && row.route === '/api/auth/native/refresh' && row.status === 200), 'ANDROID_FILES_UNEXPECTED_MUTATION');
  if (requireRead) readOnlyTraffic(other); return posts[0];
}
export async function rapidActivateAndroidUpload(context, button) {
  assert.equal(context.platform, 'android', 'ANDROID_FILES_PLATFORM_REQUIRED');
  assert.equal(await button.isDisplayed(), true, 'ANDROID_FILES_UPLOAD_VISIBLE_REQUIRED');
  assert.equal(await button.isEnabled(), true, 'ANDROID_FILES_UPLOAD_DISABLED');
  assert.ok(typeof button.elementId === 'string' && button.elementId, 'NATIVE_CLICK_ELEMENT_ID_REQUIRED');
  assert.equal(await button.getAttribute('resource-id'), 'files-upload', 'ANDROID_FILES_UPLOAD_CONTROL_REQUIRED');
  const frame = await context.driver.getElementRect(button.elementId), window = await context.driver.getWindowRect();
  assert.ok(['x', 'y', 'width', 'height'].every(key => Number.isFinite(frame?.[key])) && frame.width > 0 && frame.height > 0
    && frame.x >= window.x && frame.y >= window.y && frame.x + frame.width <= window.x + window.width
    && frame.y + frame.height <= window.y + window.height, 'ANDROID_FILES_UPLOAD_GEOMETRY_REQUIRED');
  nativeAction(context, 'click', 'id', 'files-upload'); let failure;
  try { await context.driver.performActions([{ type: 'pointer', id: 'android-upload-repeat', parameters: { pointerType: 'touch' }, actions: [
    { type: 'pointerMove', duration: 0, x: Math.floor(frame.x + frame.width / 2), y: Math.floor(frame.y + frame.height / 2) },
    { type: 'pointerDown', button: 0 }, { type: 'pointerUp', button: 0 }, { type: 'pause', duration: 10 },
    { type: 'pointerDown', button: 0 }, { type: 'pointerUp', button: 0 }] }]); } catch (error) { failure = error; }
  try { await context.driver.releaseActions(); } catch (error) { failure ??= error; }
  if (failure) throw failure;
  event(context, 'android-native-upload-two-tap-input', { tapAttempts: 2, nativeProtocolDispatches: 1, gapMs: 10, frame });
}
async function upload(context, kind) {
  const asset = validateAndroidFileAsset(context, kind); await enterFiles(context); await noSelection(context);
  const query = `android=new UiSelector().resourceIdMatches("files-name-.*").text(${JSON.stringify(asset.filename)})`;
  assert.equal(await visible(context.driver, query), undefined, 'ANDROID_FILES_UPLOAD_FILENAME_REUSED');
  const before = await traffic(context); await chooseAndroidFile(context, asset);
  const button = await find(context, 'id', 'files-upload', { scroll: true }); context.filesState.mutationUncertain = true;
  context.filesState.pendingUpload = { kind, filename: asset.filename, sha256: asset.sha256 };
  if (kind === 'txt') await rapidActivateAndroidUpload(context, button); else await dispatchNativeClick(context, button, 'id', 'files-upload');
  await wait(context, async () => {
    if (await visible(context.driver, 'id=files-upload-unknown')) fail('ANDROID_FILES_UPLOAD_UNKNOWN_NO_REPLAY');
    assert.equal(await visible(context.driver, 'id=files-upload-rejected'), undefined, 'ANDROID_FILES_UPLOAD_REJECTED');
    return delta(before, await traffic(context)).some(row => row.method === 'POST' && row.route === `/api/matters/${context.source.matterId}/attachments` && row.status === 200);
  }, 30000, 'ANDROID_FILES_UPLOAD_ACK_REQUIRED');
  const ack = validateAndroidUploadAcknowledgement(delta(before, await traffic(context)), context.source.matterId);
  await find(context, 'id', 'files-upload-persisted', { scroll: true }); await find(context, 'text', ANDROID_UPLOAD_PERSISTED_MESSAGE, { scroll: true });
  const names = await context.driver.$$(query); assert.equal(names.length, 1, 'ANDROID_FILES_UPLOADED_FILENAME_NOT_UNIQUE');
  const id = /^files-name-([a-f0-9-]{36})$/.exec(await names[0].getAttribute('resource-id'))?.[1];
  assert.ok(UUID.test(id || '') && id !== context.source.attachmentId, 'ANDROID_FILES_ACKNOWLEDGED_NEW_ID_REQUIRED');
  const anchor = { ...asset, matterId: context.source.matterId, attachmentId: id };
  await details(context, anchor); await reload(context, anchor);
  assert.equal(validateAndroidUploadAcknowledgement(delta(before, await traffic(context)), context.source.matterId, { requireRead: true }).requestId, ack.requestId,
    'ANDROID_FILES_ACK_CHANGED');
  assert.equal(typeof context.admitUploadedFileRead, 'function', 'ANDROID_FILES_OWNER_SOURCE_ADMISSION_REQUIRED');
  const admission = await context.admitUploadedFileRead(anchor, ack);
  assert.equal(admission.route, `GET /api/matters/${anchor.matterId}/attachments/${id}/download`, 'ANDROID_FILES_SOURCE_ADMISSION_MISMATCH');
  if (admission.evidence) json(admission.evidence);
  context.filesState.uploads[kind] = anchor; context.filesState.mutationUncertain = false; delete context.filesState.pendingUpload;
  event(context, 'android-native-picker-upload-persisted', { kind, attachmentId: id, sha256: asset.sha256, sizeBytes: asset.sizeBytes,
    acknowledgementRequestId: ack.requestId, admission });
}
const uploadAnchor = (context, kind) => validateAndroidSourceAnchor(context.filesState.uploads[kind]);
export async function assertAndroidViewerAbsent(context) {
  assert.equal((await context.driver.$$('id=private-document-viewer')).length, 0, 'ANDROID_FILES_PRIVATE_VIEWER_STRUCTURE_RETAINED');
  for (const id of ['viewer-filename', 'viewer-text', 'viewer-isolated-renderer']) await absent(context, 'id', id);
}
async function openReader(context, anchor) {
  await details(context, anchor); const before = await traffic(context);
  const button = await find(context, 'id', `files-open-${anchor.attachmentId}`, { scroll: true });
  assert.equal(await button.isEnabled(), true, 'ANDROID_FILES_READER_UNAVAILABLE'); await dispatchNativeClick(context, button, 'id', `files-open-${anchor.attachmentId}`);
  await find(context, 'id', 'private-document-viewer'); assert.equal(await read(context, 'id', 'viewer-filename'), anchor.filename, 'ANDROID_FILES_WRONG_READER_SOURCE');
  for (const id of ['viewer-blocked', 'viewer-unsupported']) await absent(context, 'id', id); return before;
}
async function assertSourceRead(context, before, anchor) {
  const rows = delta(before, await traffic(context)).filter(row => row.method === 'GET' && row.route === `/api/matters/${anchor.matterId}/attachments/${anchor.attachmentId}/download`);
  assert.equal(rows.filter(row => row.status === 200).length, 1, 'ANDROID_FILES_ONE_FULL_ORIGINAL_READ_REQUIRED');
  assert.ok(rows.filter(row => row.status === 206).length >= 2 && rows.length <= 12 && rows.every(row => [200, 206].includes(row.status)), 'ANDROID_FILES_RANGE_PROBE_BOUND');
}
async function closeReader(context) { await click(context, 'id', 'viewer-close'); await assertAndroidViewerAbsent(context); await find(context, 'id', 'files-matter-code', { scroll: true }); }
export function androidTextSegments(text) { assert.ok(typeof text === 'string' && text.length > 0 && text.length <= 500000, 'ANDROID_FILES_TEXT_BOUND'); return Array.from({ length: Math.ceil(text.length / 10000) }, (_, index) => text.slice(index * 10000, (index + 1) * 10000)); }
async function readText(context, anchor) {
  const segments = androidTextSegments(anchor.text), before = await openReader(context, anchor);
  const check = async page => {
    assert.equal(await read(context, 'id', 'viewer-position'), `Segment ${page} of ${segments.length}`, 'ANDROID_FILES_SEGMENT_MISMATCH');
    assert.equal((await read(context, 'id', 'viewer-text')).trimEnd(), segments[page - 1].trimEnd(), 'ANDROID_FILES_TEXT_BYTES_MISMATCH');
    assert.equal(await (await find(context, 'id', 'viewer-previous')).isEnabled(), page > 1, 'ANDROID_FILES_PREVIOUS_STATE_MISMATCH');
    assert.equal(await (await find(context, 'id', 'viewer-next')).isEnabled(), page < segments.length, 'ANDROID_FILES_NEXT_STATE_MISMATCH');
  };
  await check(1);
  if (segments.length > 1) { await click(context, 'id', 'viewer-zoom-in'); await wait(context, async () => await read(context, 'id', 'viewer-zoom') === '125%', 15000, 'ANDROID_FILES_TEXT_ZOOM_ACK_REQUIRED'); await check(1); }
  for (let page = 2; page <= segments.length; page++) { await click(context, 'id', 'viewer-next'); await wait(context, async () => await read(context, 'id', 'viewer-position') === `Segment ${page} of ${segments.length}`, 10000, 'ANDROID_FILES_NEXT_ACK_REQUIRED'); await check(page); }
  for (let page = segments.length - 1; page >= 1; page--) { await click(context, 'id', 'viewer-previous'); await wait(context, async () => await read(context, 'id', 'viewer-position') === `Segment ${page} of ${segments.length}`, 10000, 'ANDROID_FILES_PREVIOUS_ACK_REQUIRED'); await check(page); }
  await assertSourceRead(context, before, anchor); await closeReader(context);
}
async function renderer(context, anchor, pages) {
  const before = await openReader(context, anchor); await find(context, 'id', 'viewer-isolated-renderer');
  await wait(context, async () => await read(context, 'id', 'viewer-position') === `Page 1 of ${pages}`, 15000, 'ANDROID_FILES_RENDERER_PAGE_ACK_REQUIRED');
  await click(context, 'id', 'viewer-zoom-in'); await wait(context, async () => await read(context, 'id', 'viewer-zoom') === '125%', 15000, 'ANDROID_FILES_RENDERER_ZOOM_ACK_REQUIRED');
  if (pages === 2) { await click(context, 'id', 'viewer-next'); await wait(context, async () => await read(context, 'id', 'viewer-position') === 'Page 2 of 2', 15000, 'ANDROID_FILES_PDF_PAGE2_ACK_REQUIRED'); await click(context, 'id', 'viewer-previous'); await wait(context, async () => await read(context, 'id', 'viewer-position') === 'Page 1 of 2', 15000, 'ANDROID_FILES_PDF_PAGE1_ACK_REQUIRED'); }
  else assert.equal(await (await find(context, 'id', 'viewer-next')).isEnabled(), false, 'ANDROID_FILES_SINGLE_IMAGE_PAGE_REQUIRED');
  await assertSourceRead(context, before, anchor); await closeReader(context);
}
export function validateAndroidPrivacyReceipt(context, boundary, receipt) {
  for (const [key, expected] of Object.entries({ schemaVersion: 1, observed: true, platform: 'android', udid: context.fixture.udid,
    appId: context.fixture.appId, boundary, ownedAppScopeOnly: true, providerOriginalsUnchanged: true, stagedFileCount: 0, privateByteMatchCount: 0 }))
    assert.equal(receipt[key], expected, 'ANDROID_FILES_PRIVACY_BOUNDARY_MISMATCH');
  assert.ok(receipt.rawEvidence, 'ANDROID_FILES_RAW_PRIVACY_EVIDENCE_REQUIRED'); const raw = json(receipt.rawEvidence);
  for (const [key, expected] of Object.entries({ schemaVersion: 1, kind: 'android-files-privacy-snapshot', observed: true,
    platform: 'android', udid: context.fixture.udid, appId: context.fixture.appId, ownedAppScopeOnly: true,
    complete: true, providerOriginalsPreserved: true })) assert.equal(raw[key], expected, 'ANDROID_FILES_RAW_PRIVACY_MISMATCH');
  assert.equal(raw.counts?.ownedStagingFiles, receipt.stagedFileCount, 'ANDROID_FILES_RAW_PRIVACY_MISMATCH');
  assert.equal(raw.counts?.privateAssetMatchCount, receipt.privateByteMatchCount, 'ANDROID_FILES_RAW_PRIVACY_MISMATCH');
  return receipt;
}
async function privacy(context, boundary) {
  assert.equal(typeof context.observeFilesystem, 'function', 'ANDROID_FILES_OBSERVED_FILESYSTEM_REQUIRED');
  const ref = await context.observeFilesystem(boundary, [context.source.sha256, ...KINDS.map(kind => context.assets.uploads[kind].sha256)]);
  validateAndroidPrivacyReceipt(context, boundary, json(ref)); event(context, 'android-filesystem-privacy-observed', { boundaryName: boundary, evidence: ref });
}
const noPosts = async (context, before) => readOnlyTraffic(delta(before, await traffic(context)));
async function signedOut(context) { await wait(context, async () => !await visible(context.driver, 'id=session-loading') && !await visible(context.driver, 'id=account-open') && !!await visible(context.driver, 'id=signed-out') && !!await visible(context.driver, 'id=sign-in'), 20000, 'ANDROID_FILES_SIGNED_OUT_REQUIRED'); }
async function discardSelection(context, action) {
  await click(context, 'id', 'back');
  assert.equal(await read(context, 'id', `${context.fixture.appId}:id/alert_title`), 'Discard file selection?', 'ANDROID_FILES_DISCARD_TITLE_MISMATCH');
  assert.equal(await read(context, 'id', 'android:id/button2'), 'STAY', 'ANDROID_FILES_DISCARD_STAY_MISMATCH');
  assert.equal(await read(context, 'id', 'android:id/button1'), 'LEAVE FILES', 'ANDROID_FILES_DISCARD_LEAVE_MISMATCH');
  await click(context, 'id', action === 'stay' ? 'android:id/button2' : 'android:id/button1');
}
export const androidFilesScenarios = Object.freeze([
  { id: 'FILES-01', run: async c => { await enterFiles(c); const before = await traffic(c); await reload(c, c.source); await readText(c, c.source); await noPosts(c, before); } },
  { id: 'FILES-02', run: async c => { const before = await traffic(c); await enterFiles(c); await chooseAndroidFile(c, null, { cancel: true }); await noSelection(c); await noPosts(c, before); await privacy(c, 'picker-cancel'); } },
  { id: 'FILES-03', run: async c => { const before = await traffic(c); await enterFiles(c); await chooseAndroidFile(c, validateAndroidFileAsset(c, 'txt')); await click(c, 'id', 'files-selection-clear', { scroll: true }); await noSelection(c); await noPosts(c, before); await privacy(c, 'selection-clear'); } },
  ...KINDS.map((kind, index) => ({ id: `FILES-${String(index + 4).padStart(2, '0')}`, run: async c => { await upload(c, kind); if (kind === 'txt') await readText(c, uploadAnchor(c, kind)); await privacy(c, `uploaded-${kind}`); } })),
  { id: 'FILES-09', freshAuthentication: true, requires: ['FILES-05'], run: async c => { await enterFiles(c); const before = await traffic(c); await renderer(c, uploadAnchor(c, 'pdf'), 2); await noPosts(c, before); } },
  { id: 'FILES-10', requires: ['FILES-06', 'FILES-07'], run: async c => { await enterFiles(c); const before = await traffic(c); for (const kind of ['png', 'jpeg']) await renderer(c, uploadAnchor(c, kind), 1); await noPosts(c, before); } },
  { id: 'FILES-11', requires: ['FILES-08'], run: async c => { const before = await traffic(c); await enterFiles(c); const anchor = uploadAnchor(c, 'docx'); await details(c, anchor); assert.equal(await (await find(c, 'id', `files-open-${anchor.attachmentId}`, { scroll: true })).isEnabled(), false, 'ANDROID_FILES_DOCX_READER_MUST_REMAIN_UNAVAILABLE'); await find(c, 'id', `files-viewer-unavailable-${anchor.attachmentId}`, { scroll: true }); await assertAndroidViewerAbsent(c); assert.equal(delta(before, await traffic(c)).filter(row => row.route.endsWith('/download') || row.route.endsWith('/preview')).length, 0, 'ANDROID_FILES_DOCX_WAS_OPENED'); await noPosts(c, before); } },
  { id: 'FILES-12', run: async c => { await enterFiles(c); await openReader(c, c.source); await find(c, 'id', 'viewer-text'); const before = await traffic(c); await backgroundAndResume(c); await assertAndroidViewerAbsent(c); await enterFiles(c); await noPosts(c, before); await privacy(c, 'viewer-background'); } },
  { id: 'FILES-13', run: async c => { await enterFiles(c); const before = await traffic(c); await chooseAndroidFile(c, validateAndroidFileAsset(c, 'txt')); await backgroundAndResume(c); await enterFiles(c); await noSelection(c); await noPosts(c, before); await privacy(c, 'selection-background'); } },
  { id: 'FILES-14', run: async c => { await enterFiles(c); const before = await traffic(c); await chooseAndroidFile(c, validateAndroidFileAsset(c, 'txt')); await discardSelection(c, 'stay'); await find(c, 'id', 'files-selection', { scroll: true }); await discardSelection(c, 'leave'); await enterFiles(c); await noSelection(c); await noPosts(c, before); await privacy(c, 'selection-discard'); } },
  { id: 'FILES-15', run: async c => { await enterFiles(c); const before = await traffic(c); await chooseAndroidFile(c, validateAndroidFileAsset(c, 'txt')); await restart(c); await enterFiles(c); await noSelection(c); await openReader(c, c.source); await find(c, 'id', 'viewer-text'); await restart(c); await assertAndroidViewerAbsent(c); await enterFiles(c); await noSelection(c); await noPosts(c, before); await privacy(c, 'process-restart'); } },
  { id: 'FILES-16', run: async c => { await enterFiles(c); await readText(c, c.source); const before = await traffic(c); await click(c, 'id', 'account-open'); await click(c, 'id', 'sign-out', { scroll: true }); await signedOut(c); const rows = delta(before, await traffic(c)).filter(row => row.method === 'POST' && row.route === '/api/auth/native/logout'); assert.equal(rows.length, 1, 'ANDROID_FILES_LOGOUT_NOT_ONCE'); assert.ok([200, 204].includes(rows[0].status), 'ANDROID_FILES_LOGOUT_NOT_ACKNOWLEDGED'); await assertAndroidViewerAbsent(c); await absent(c, 'id', 'files-selection'); await privacy(c, 'logout'); c.filesState.logoutAcknowledged = true; } },
  { id: 'FILES-17', requires: ['FILES-16'], requiresSignedOut: true, run: async c => { validateAndroidFilesContext(c); assert.equal(c.filesState.logoutAcknowledged, true, 'ANDROID_FILES_PRIOR_LOGOUT_REQUIRED'); const before = await traffic(c); await restart(c); await signedOut(c); await assertAndroidViewerAbsent(c); for (const id of ['files-selection', 'files-matter-code']) await absent(c, 'id', id); assert.equal(delta(before, await traffic(c)).length, 0, 'ANDROID_FILES_SIGNED_OUT_PRIVATE_TRAFFIC'); await privacy(c, 'signed-out-restart'); } },
].map(scenario => Object.freeze({ ...scenario, ...(scenario.requires ? { requires: Object.freeze([...scenario.requires]) } : {}) })));
