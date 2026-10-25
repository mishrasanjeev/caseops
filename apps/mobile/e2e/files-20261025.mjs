import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { FixtureUnavailable, admitApplication, verifiedFile } from './fixture-contract.mjs';
import { authenticate, delta, openMatter, readOnlyTraffic, traffic } from './journeys.mjs';
import { absent, click, find, read, selector, visible } from './native-ui.mjs';
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
  scope: 'Supplementary real Android Files/TXT read; not full MOB-21..26 or an upload acceptance receipt',
  cases: Object.freeze([
    Object.freeze({ id: 'FILES-01', title: 'Exact seeded Files row, source SHA-256, reload, private TXT open and return to Files', groups: ['MOB-21', 'MOB-26', 'MOB-30'],
      prerequisites: ['parent-owned admitted APK/Appium context and real Firefox/MFA authentication', 'hash-verified seedEvidence with exact sourceId/sourceSha256/matter', 'unchanged synthetic source fixture and read-admitted marked gateway', 'exact source controls and visible TXT content in the actual APK'] }),
    Object.freeze({ id: 'FILES-02', title: 'Actual Android picker upload and persisted exact source readback', groups: ['MOB-22', 'MOB-24', 'MOB-25'],
      blocked: 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED',
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

export async function expandSourceDetails(control, platform) {
  const show = await visible(control, selector(platform, 'text', 'Source details'));
  const hide = await visible(control, selector(platform, 'text', 'Hide source details'));
  assert.equal(Number(!!show) + Number(!!hide), 1, 'FILES_SOURCE_DETAILS_STATE_UNOBSERVED');
  if (show) await show.click();
}

async function sourceDetails(context) {
  await find(context, 'id', `files-row-${source.attachmentId}`, { scroll: true });
  assert.equal(await read(context, 'id', `files-name-${source.attachmentId}`, { scroll: true }), source.filename, 'FILES_WRONG_SOURCE_FILENAME');
  const hashId = `files-hash-${source.attachmentId}`;
  const details = await find(context, 'id', `files-source-${source.attachmentId}`, { scroll: true });
  await expandSourceDetails(details, context.platform);
  assert.equal(await read(context, 'id', hashId, { scroll: true }), source.sha256, 'FILES_SOURCE_HASH_MISMATCH');
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
  await open.click();
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
  await choose.click();
  return { state: 'blocked', reason: 'ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED' };
}

export async function uploadFilesSource() {
  // Never guess DocumentsUI selectors, push private bytes, use direct API upload,
  // fabricate a returned attachment ID, or treat an opened picker as an upload.
  throw new FixtureUnavailable('ANDROID_PICKER_AND_UPLOAD_EVIDENCE_REQUIRED');
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
