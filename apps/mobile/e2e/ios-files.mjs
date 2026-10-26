import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { admitApplication, FixtureUnavailable, verifiedFile } from './fixture-contract.mjs';
import { browserOrigin } from './browser-handoff.mjs';
import { delta, openMatter, readOnlyTraffic, traffic } from './journeys.mjs';
import { absent, backgroundAndResume, click, dispatchNativeClick, find, findQuery, nativeAction, read, restart, selector, swipe, visible } from './native-ui.mjs';
import { reconcileInventory } from './support.mjs';

const SHA = /^[a-f0-9]{64}$/;
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const QA_ID = 'ai.caseops.mobile.dev.simulatoracceptance';
const KINDS = ['txt', 'pdf', 'png', 'jpeg', 'docx'];
export const IOS_UPLOAD_PERSISTED_MESSAGE = 'Upload acknowledged and the same source confirmed after reload. A separate clean-scan receipt is not supplied by this server.';
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const json = (reference, max = 1048576) => JSON.parse(verifiedFile(reference?.path, reference?.sha256, max));
const event = (context, boundary, extra = {}) => context.record?.({ type: 'assertion', boundary, ...extra });
const fail = (code) => { throw new FixtureUnavailable(code); };

export const iosFilesInventory = Object.freeze({
  schemaVersion: 1, inventoryId: 'native-ios-files-2026-10-26', platforms: Object.freeze(['ios']),
  scope: 'Actual iOS Files picker, five clean uploads, private readers and bounded app-owned privacy; separate from the 23-case core and physical-device acceptance',
  cases: Object.freeze([
    ['FILES-01', 'Seeded TXT source identity, authoritative reload, private read and return'],
    ['FILES-02', 'Actual iOS picker cancellation creates no selection or upload'],
    ['FILES-03', 'Actual TXT selection and explicit clear create no upload'],
    ['FILES-04', 'Rapid repeated TXT activation admits exactly one upload, persisted identity and original bytes'],
    ['FILES-05', 'Exactly one native two-page PDF upload and persisted source'],
    ['FILES-06', 'Exactly one native PNG upload and persisted source'],
    ['FILES-07', 'Exactly one native JPEG upload and persisted source'],
    ['FILES-08', 'Exactly one native DOCX upload and persisted source'],
    ['FILES-09', 'Actual two-page PDF page and zoom acknowledgements, then Files return'],
    ['FILES-10', 'Actual PNG and JPEG renderer zoom acknowledgements, then Files return'],
    ['FILES-11', 'Uploaded DOCX truthfully remains unavailable in the private reader'],
    ['FILES-12', 'Viewer Home background and warm resume remove private content'],
    ['FILES-13', 'Selected file background and warm resume discard selection without upload'],
    ['FILES-14', 'Selection Stay and explicit Leave Files preserve discard semantics'],
    ['FILES-15', 'Process restart restores neither selection nor a private reader'],
    ['FILES-16', 'Files-history logout is acknowledged once and purges private state'],
    ['FILES-17', 'Signed-out restart and app-owned filesystem privacy evidence'],
  ].map(([id, title]) => Object.freeze({ id, title }))),
});

export function collectIosFiles(platform = 'ios') {
  assert.equal(platform, 'ios', 'IOS_FILES_PLATFORM_REQUIRED');
  const intended = iosFilesInventory.cases.map(({ id }) => `ios:${id}`);
  const discovered = iosFilesScenarios.map(({ id }) => `ios:${id}`);
  reconcileInventory(intended, discovered);
  return { platform, inventoryId: iosFilesInventory.inventoryId, scope: iosFilesInventory.scope, intended, discovered };
}

export function validateSourceAnchor(anchor) {
  assert.ok(anchor && UUID.test(anchor.matterId) && UUID.test(anchor.attachmentId), 'IOS_FILES_SOURCE_IDENTITIES_REQUIRED');
  assert.match(anchor.sha256 || '', SHA, 'IOS_FILES_SOURCE_HASH_REQUIRED');
  assert.ok(typeof anchor.filename === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{1,200}$/.test(anchor.filename), 'IOS_FILES_SOURCE_FILENAME_REQUIRED');
  assert.ok(Number.isSafeInteger(anchor.sizeBytes) && anchor.sizeBytes > 0 && anchor.sizeBytes <= 1048576, 'IOS_FILES_SMALL_SYNTHETIC_SOURCE_REQUIRED');
  if (anchor.text !== undefined) {
    assert.equal(Buffer.byteLength(anchor.text), anchor.sizeBytes, 'IOS_FILES_SOURCE_TEXT_SIZE_MISMATCH');
    assert.equal(hash(Buffer.from(anchor.text)), anchor.sha256, 'IOS_FILES_SOURCE_TEXT_HASH_MISMATCH');
  }
  return anchor;
}

export function validateSourceSeed(fixture, source) {
  validateSourceAnchor(source);
  assert.equal(fixture.environment, 'docker-integration', 'IOS_FILES_ISOLATION_REQUIRED');
  assert.equal(fixture.syntheticDataOnly, true, 'IOS_FILES_SYNTHETIC_FIXTURE_REQUIRED');
  const seed = json(fixture.seedEvidence);
  assert.equal(seed.environment, 'docker-integration', 'IOS_FILES_HASH_BOUND_SEED_REQUIRED');
  assert.equal(seed.syntheticDataOnly, true, 'IOS_FILES_HASH_BOUND_SEED_REQUIRED');
  assert.equal(seed.matter?.id, source.matterId, 'IOS_FILES_SEED_PARENT_MISMATCH');
  assert.equal(fixture.matter?.id, source.matterId, 'IOS_FILES_SOURCE_PARENT_MISMATCH');
  for (const key of ['companyId', 'membershipId']) {
    assert.ok(typeof fixture[key] === 'string' && fixture[key].length > 0, 'IOS_FILES_SEED_ACCOUNT_REQUIRED');
    assert.equal(seed[key], fixture[key], 'IOS_FILES_SEED_ACCOUNT_MISMATCH');
  }
  const sourceId = seed.sourceId ?? seed.source?.id;
  const sourceHash = seed.sourceSha256 ?? seed.source?.sha256;
  const direct = sourceId !== undefined || sourceHash !== undefined || seed.source !== undefined;
  let original;
  if (seed.provenance?.baseSeed !== undefined) {
    original = json(seed.provenance.baseSeed);
    assert.equal(original.environment, 'docker-integration', 'IOS_FILES_ORIGINAL_SEED_REQUIRED');
    assert.equal(original.syntheticDataOnly, true, 'IOS_FILES_ORIGINAL_SEED_REQUIRED');
    assert.equal(original.companyId, fixture.companyId, 'IOS_FILES_ORIGINAL_TENANT_MISMATCH');
    assert.equal(original.matter?.id, source.matterId, 'IOS_FILES_ORIGINAL_PARENT_MISMATCH');
    assert.equal(original.cleanUploadAndDownload, true, 'IOS_FILES_ORIGINAL_SOURCE_READBACK_REQUIRED');
    assert.equal(original.sourceId, source.attachmentId, 'IOS_FILES_ORIGINAL_ATTACHMENT_MISMATCH');
    assert.equal(original.sourceSha256, source.sha256, 'IOS_FILES_ORIGINAL_HASH_MISMATCH');
  }
  assert.ok(direct || original, 'IOS_FILES_SOURCE_PROVENANCE_REQUIRED');
  if (direct) {
    assert.equal(sourceId, source.attachmentId, 'IOS_FILES_SEED_ATTACHMENT_MISMATCH');
    assert.equal(sourceHash, source.sha256, 'IOS_FILES_SEED_HASH_MISMATCH');
    if (original) {
      assert.equal(sourceId, original.sourceId, 'IOS_FILES_SOURCE_PROVENANCE_MISMATCH');
      assert.equal(sourceHash, original.sourceSha256, 'IOS_FILES_SOURCE_PROVENANCE_MISMATCH');
    } else assert.equal(seed.cleanUploadAndDownload, true, 'IOS_FILES_ORIGINAL_SOURCE_READBACK_REQUIRED');
  }
  // The original source may be owner-created. Current member identity comes
  // from the effective seed; source lineage must retain its exact tenant/parent.
  return source;
}

export function validateIosFilesContext(context) {
  assert.equal(context?.platform, 'ios', 'IOS_FILES_PLATFORM_REQUIRED');
  const fixture = context.fixture;
  assert.equal(fixture?.environment, 'docker-integration', 'IOS_FILES_ISOLATION_REQUIRED');
  assert.equal(fixture.syntheticDataOnly, true, 'IOS_FILES_SYNTHETIC_FIXTURE_REQUIRED');
  assert.equal(admitApplication(fixture, 'ios'), QA_ID, 'IOS_FILES_SIGNED_QA_APP_REQUIRED');
  for (const key of ['backendSha', 'webSha', 'binarySourceSha']) assert.match(fixture[key] || '', /^[a-f0-9]{40}$/, 'IOS_FILES_RELEASE_IDENTITIES_REQUIRED');
  assert.equal(fixture.backendSha, fixture.binarySourceSha, 'IOS_FILES_API_BINARY_RELEASE_MISMATCH');
  assert.equal(fixture.webSha, fixture.binarySourceSha, 'IOS_FILES_WEB_BINARY_RELEASE_MISMATCH');
  browserOrigin(fixture.apiOrigin); browserOrigin(fixture.gatewayUrl);
  assert.equal(context.gatewayBaseline?.runId, fixture.gatewayRunId, 'IOS_FILES_GATEWAY_BASELINE_REQUIRED');
  assert.ok(context.driver && typeof context.driver.$$ === 'function' && typeof context.driver.waitUntil === 'function', 'IOS_FILES_ACTUAL_DRIVER_REQUIRED');
  const source = validateSourceAnchor(context.source);
  validateSourceSeed(fixture, source);
  assert.ok(context.filesState && typeof context.filesState.uploads === 'object', 'IOS_FILES_RUN_STATE_REQUIRED');
  if (context.filesState.mutationUncertain === true) fail('IOS_FILES_PREVIOUS_UPLOAD_UNCERTAIN_NO_REPLAY');
  return source;
}

export function validateAsset(context, kind) {
  assert.ok(KINDS.includes(kind), 'IOS_FILES_ASSET_KIND_REQUIRED');
  const asset = context.assets?.uploads?.[kind];
  if (!asset) fail('IOS_FILES_VERIFIED_ASSET_REQUIRED');
  const filename = asset.filename ?? asset.name;
  assert.ok(/^[A-Za-z0-9][A-Za-z0-9._-]{1,200}$/.test(filename || ''), 'IOS_FILES_ASSET_FILENAME_REQUIRED');
  assert.match(asset.sha256 || '', SHA, 'IOS_FILES_ASSET_HASH_REQUIRED');
  assert.ok(Number.isSafeInteger(asset.sizeBytes) && asset.sizeBytes > 0 && asset.sizeBytes <= 1040000, 'IOS_FILES_GATEWAY_ASSET_BOUND_REQUIRED');
  assert.equal(verifiedFile(asset.path, asset.sha256, 1040000).length, asset.sizeBytes, 'IOS_FILES_ASSET_SIZE_MISMATCH');
  const manifest = json(context.assets.manifestEvidence);
  assert.equal(manifest.syntheticDataOnly, true, 'IOS_FILES_SYNTHETIC_ASSET_MANIFEST_REQUIRED');
  const entries = Array.isArray(manifest.assets) ? manifest.assets : Object.values(manifest.assets ?? manifest.uploads ?? {});
  const matches = entries.filter((entry) => entry.sha256 === asset.sha256 && (entry.filename ?? entry.name) === filename && entry.sizeBytes === asset.sizeBytes);
  assert.equal(matches.length, 1, 'IOS_FILES_ASSET_MANIFEST_MISMATCH');
  if (asset.text !== undefined) assert.equal(hash(Buffer.from(asset.text)), asset.sha256, 'IOS_FILES_ASSET_TEXT_MISMATCH');
  if (kind === 'pdf') assert.equal(asset.pages, 2, 'IOS_FILES_TWO_PAGE_PDF_REQUIRED');
  return { ...asset, filename, kind };
}

function observedLocalPickerRoot(context, proof) {
  const root = proof.localRoot;
  assert.ok(root && typeof root === 'object', 'IOS_FILES_OBSERVED_LOCAL_ROOT_REQUIRED');
  const inventory = json(root.deviceInventory);
  assert.ok(inventory.devices && typeof inventory.devices === 'object' && !Array.isArray(inventory.devices), 'IOS_FILES_DEVICE_INVENTORY_REQUIRED');
  const runtimes = Object.entries(inventory.devices);
  assert.ok(runtimes.length > 0 && runtimes.length <= 64
    && runtimes.every(([, devices]) => Array.isArray(devices) && devices.length <= 256), 'IOS_FILES_DEVICE_INVENTORY_REQUIRED');
  const matches = runtimes.flatMap(([runtime, devices]) => devices
    .filter((device) => device?.udid === context.fixture.udid).map((device) => ({ ...device, runtime })));
  assert.equal(matches.length, 1, 'IOS_FILES_EXACT_PICKER_DEVICE_REQUIRED');
  const device = matches[0];
  assert.equal(device.isAvailable, true, 'IOS_FILES_AVAILABLE_PICKER_DEVICE_REQUIRED');
  assert.equal(device.state, 'Booted', 'IOS_FILES_BOOTED_PICKER_DEVICE_REQUIRED');
  assert.match(device.runtime, /^com\.apple\.CoreSimulator\.SimRuntime\.iOS-[0-9]+(?:-[0-9]+)*$/, 'IOS_FILES_PICKER_RUNTIME_REQUIRED');
  const family = /^com\.apple\.CoreSimulator\.SimDeviceType\.(iPhone|iPad)-[A-Za-z0-9-]+$/.exec(device.deviceTypeIdentifier || '');
  assert.ok(family, 'IOS_FILES_PICKER_DEVICE_FAMILY_REQUIRED');
  const label = family[1] === 'iPad' ? 'On My iPad' : 'On My iPhone';
  assert.equal(root.label, label, 'IOS_FILES_OBSERVED_LOCAL_ROOT_MISMATCH');
  return label;
}

export function validatePickerProvider(context) {
  const value = context.provider;
  if (!value?.evidence) fail('IOS_FILES_OBSERVED_PICKER_REQUIRED');
  const proof = json(value.evidence);
  assert.equal(proof.observed, true, 'IOS_FILES_OBSERVED_PICKER_REQUIRED');
  assert.equal(proof.platform, 'ios', 'IOS_FILES_PICKER_PLATFORM_MISMATCH');
  assert.equal(proof.udid, context.fixture.udid, 'IOS_FILES_PICKER_DEVICE_MISMATCH');
  observedLocalPickerRoot(context, proof);
  assert.ok(typeof value.folderName === 'string' && value.folderName.length > 0 && value.folderName.length <= 160 && !/[\x00-\x1f/\\]/.test(value.folderName), 'IOS_FILES_OWNED_PROVIDER_FOLDER_REQUIRED');
  assert.equal(proof.folderName, value.folderName, 'IOS_FILES_PICKER_FOLDER_MISMATCH');
  for (const key of ['folderQuery', 'fileQueryTemplate']) assert.equal(proof[key], value[key], 'IOS_FILES_PICKER_CONTROLS_MISMATCH');
  assert.ok(typeof value.folderQuery === 'string' && value.folderQuery.startsWith('-ios predicate string:'), 'IOS_FILES_OBSERVED_FOLDER_SELECTOR_REQUIRED');
  assert.equal((value.fileQueryTemplate?.match(/\{pickerNameJSON\}/g) || []).length, 1, 'IOS_FILES_FILENAME_SELECTOR_TEMPLATE_REQUIRED');
  assert.ok(value.fileQueryTemplate.startsWith('-ios predicate string:'), 'IOS_FILES_TYPED_FILE_SELECTOR_REQUIRED');
  return value;
}

export function validatePickerAsset(context, asset) {
  const observed = validatePickerProvider(context), proof = json(observed.evidence);
  const files = Array.isArray(proof.assets) ? proof.assets : Object.values(proof.assets || {});
  const matches = files.filter((file) => (file.filename ?? file.name) === asset.filename
    && file.sha256 === asset.sha256 && file.sizeBytes === asset.sizeBytes && file.observedProviderHash === asset.sha256);
  assert.equal(matches.length, 1, 'IOS_FILES_OBSERVED_PROVIDER_ASSET_REQUIRED');
  const dot = asset.filename.lastIndexOf('.');
  assert.ok(dot > 0, 'IOS_FILES_PICKER_EXTENSION_REQUIRED');
  const pickerName = `${asset.filename.slice(0, dot)}, ${asset.filename.slice(dot + 1)}`;
  assert.equal(matches[0].pickerName, pickerName, 'IOS_FILES_OBSERVED_PICKER_NAME_REQUIRED');
  return { ...observed, pickerName };
}

const cancelPicker = '-ios predicate string:type == "XCUIElementTypeButton" AND name == "Cancel" AND label == "Cancel"';
const browsePicker = '-ios predicate string:type == "XCUIElementTypeButton" AND name == "Browse" AND label == "Browse"';
const pickerBar = '-ios predicate string:type == "XCUIElementTypeNavigationBar" AND name == "FullDocumentManagerViewControllerNavigationBar"';
function pickerRootControls(label) {
  return {
    back: '-ios predicate string:type == "XCUIElementTypeButton" AND name == "BackButton" AND label == ' + JSON.stringify(label),
    root: '-ios predicate string:type == "XCUIElementTypeStaticText" AND name == ' + JSON.stringify(label) + ' AND label == ' + JSON.stringify(label),
    location: '-ios predicate string:type == "XCUIElementTypeCell" AND name == ' + JSON.stringify(`DOC.sidebar.item.${label}`)
      + ' AND label == ' + JSON.stringify(label),
  };
}
const folderHeading = (folderName) => '-ios predicate string:type == "XCUIElementTypeButton" AND name == '
  + JSON.stringify(`${folderName}, Actions Menu`) + ' AND label == ' + JSON.stringify(`${folderName}, Actions Menu`);

async function wait(context, condition, timeout, code) {
  await context.driver.waitUntil(condition, { timeout, interval: 200, timeoutMsg: code });
}
function validFrame(rect) {
  return rect && ['x', 'y', 'width', 'height'].every((key) => Number.isFinite(rect[key])) && rect.width > 0 && rect.height > 0;
}
function containsFrame(outer, inner) {
  return inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.width <= outer.x + outer.width
    && inner.y + inner.height <= outer.y + outer.height;
}
async function marker(context, id, { required = true } = {}) {
  const matches = await context.driver.$$(selector('ios', 'id', id));
  assert.ok(matches.length <= 1, 'IOS_FILES_STRUCTURAL_MARKER_NOT_UNIQUE');
  if (!matches.length) { assert.equal(required, false, 'IOS_FILES_STRUCTURAL_MARKER_REQUIRED'); return undefined; }
  const control = matches[0];
  assert.equal(await control.getAttribute('name'), id, 'IOS_FILES_STRUCTURAL_MARKER_ID_MISMATCH');
  assert.equal(await control.getAttribute('type'), 'XCUIElementTypeOther', 'IOS_FILES_STRUCTURAL_MARKER_TYPE_REQUIRED');
  return control;
}
async function visibleFact(context, id, type) {
  const matches = await context.driver.$$(selector('ios', 'id', id));
  assert.equal(matches.length, 1, 'IOS_FILES_VISIBLE_FACT_NOT_UNIQUE');
  const control = matches[0];
  assert.equal(await control.getAttribute('name'), id, 'IOS_FILES_VISIBLE_FACT_ID_MISMATCH');
  assert.equal(await control.getAttribute('type'), type, 'IOS_FILES_VISIBLE_FACT_TYPE_MISMATCH');
  assert.equal(await control.isDisplayed(), true, 'IOS_FILES_VISIBLE_FACT_REQUIRED');
  return control;
}
export async function assertIosUploadErrorsAbsent(context) {
  if (await marker(context, 'files-upload-unknown', { required: false })) fail('IOS_FILES_UPLOAD_UNKNOWN_NO_REPLAY');
  assert.equal(await marker(context, 'files-upload-rejected', { required: false }), undefined, 'IOS_FILES_UPLOAD_REJECTED');
}
export async function proveIosReaderEntry(context, anchor) {
  const root = await marker(context, 'private-document-viewer');
  const window = await context.driver.getWindowRect(), rootFrame = await context.driver.getElementRect(root.elementId);
  assert.ok(validFrame(window) && validFrame(rootFrame) && containsFrame(window, rootFrame), 'IOS_FILES_READER_FRAME_REQUIRED');
  const filename = await visibleFact(context, 'viewer-filename', 'XCUIElementTypeStaticText');
  assert.equal(await filename.getText(), anchor.filename, 'IOS_FILES_WRONG_READER_SOURCE');
  assert.equal(await filename.getAttribute('label'), anchor.filename, 'IOS_FILES_WRONG_READER_SOURCE');
  const close = await visibleFact(context, 'viewer-close', 'XCUIElementTypeButton');
  assert.equal(await close.getAttribute('label'), 'Return to Files', 'IOS_FILES_READER_CLOSE_IDENTITY_REQUIRED');
  const toolbar = await visibleFact(context, 'viewer-toolbar', 'XCUIElementTypeOther');
  const facts = [];
  for (const [id, control] of [['viewer-filename', filename], ['viewer-close', close], ['viewer-toolbar', toolbar]]) {
    const rect = await context.driver.getElementRect(control.elementId);
    assert.ok(validFrame(rect) && containsFrame(rootFrame, rect), 'IOS_FILES_READER_FACT_OUTSIDE_MARKER');
    facts.push({ id, rect });
  }
  for (const id of ['viewer-blocked', 'viewer-unsupported']) assert.equal(await marker(context, id, { required: false }), undefined, 'IOS_FILES_READER_FAILURE_PRESENT');
  event(context, 'ios-reader-structure-and-visible-facts', { rootFrame, facts });
  return { rootFrame, facts };
}
export async function proveIosUploadPersisted(context, message) {
  const root = await marker(context, 'files-upload-persisted');
  assert.ok(message, 'IOS_FILES_VISIBLE_UPLOAD_ACK_REQUIRED');
  assert.equal(await message.getAttribute('type'), 'XCUIElementTypeStaticText', 'IOS_FILES_UPLOAD_ACK_TYPE_REQUIRED');
  assert.equal(await message.isDisplayed(), true, 'IOS_FILES_VISIBLE_UPLOAD_ACK_REQUIRED');
  assert.equal(await message.getText(), IOS_UPLOAD_PERSISTED_MESSAGE, 'IOS_FILES_UPLOAD_ACK_TEXT_MISMATCH');
  assert.equal(await message.getAttribute('label'), IOS_UPLOAD_PERSISTED_MESSAGE, 'IOS_FILES_UPLOAD_ACK_TEXT_MISMATCH');
  const window = await context.driver.getWindowRect(), rootFrame = await context.driver.getElementRect(root.elementId);
  const messageFrame = await context.driver.getElementRect(message.elementId);
  assert.ok(validFrame(window) && validFrame(rootFrame) && validFrame(messageFrame), 'IOS_FILES_UPLOAD_ACK_FRAME_REQUIRED');
  assert.ok(containsFrame(window, rootFrame) && containsFrame(rootFrame, messageFrame), 'IOS_FILES_UPLOAD_ACK_OUTSIDE_MARKER');
  return { rootFrame, messageFrame };
}
export async function findIosUploadPersisted(context) {
  const query = selector('ios', 'text', IOS_UPLOAD_PERSISTED_MESSAGE);
  for (let attempt = 0; attempt <= 9; attempt++) {
    let message;
    try {
      await context.driver.waitUntil(async () => {
        await assertIosUploadErrorsAbsent(context);
        message = await visible(context.driver, query);
        if (!message) return false;
        const root = await marker(context, 'files-upload-persisted', { required: false });
        if (!root) return false;
        const window = await context.driver.getWindowRect(), frame = await context.driver.getElementRect(root.elementId);
        assert.ok(validFrame(window) && validFrame(frame), 'IOS_FILES_UPLOAD_ACK_FRAME_REQUIRED');
        return containsFrame(window, frame);
      }, { timeout: 1500, interval: 150, timeoutMsg: 'IOS_FILES_VISIBLE_UPLOAD_ACK_REQUIRED' });
    } catch (error) {
      if (/AMBIGUOUS_VISIBLE_NATIVE_LOCATOR|NOT_UNIQUE|MISMATCH|UNKNOWN_NO_REPLAY|UPLOAD_REJECTED|TYPE_REQUIRED|FRAME_REQUIRED/.test(error.message) || attempt === 9) throw error;
      await swipe(context, 'down'); continue;
    }
    const proof = await proveIosUploadPersisted(context, message);
    event(context, 'ios-upload-structure-and-visible-ack', proof); return;
  }
}
export async function assertIosViewerAbsent(context) {
  assert.equal((await context.driver.$$(selector('ios', 'id', 'private-document-viewer'))).length, 0, 'IOS_FILES_PRIVATE_VIEWER_STRUCTURE_RETAINED');
  for (const id of ['viewer-filename', 'viewer-text', 'viewer-isolated-renderer']) await absent(context, 'id', id);
}
async function noSelection(context) {
  for (const id of ['files-selection', 'files-upload']) assert.equal((await context.driver.$$(selector('ios', 'id', id))).length, 0, 'IOS_FILES_SELECTION_STRUCTURALLY_RETAINED');
  assert.equal(await (await findIosFileFact(context, 'files-choose', 'XCUIElementTypeButton')).getAttribute('label'), 'Choose file', 'IOS_FILES_SELECTION_NOT_CLEARED');
}
async function enterFiles(context) {
  validateIosFilesContext(context);
  await wait(context, async () => {
    if (await visible(context.driver, '~session-loading')) return false;
    const account = await visible(context.driver, '~account-open');
    return !!account && await account.isEnabled();
  }, 20000, 'IOS_FILES_AUTHENTICATED_FOREGROUND_REQUIRED');
  await openMatter(context);
  const picker = await findQuery(context, '-ios predicate string:type == "XCUIElementTypeSegmentedControl" AND label == "Matter view"');
  const button = await visible(picker, '-ios predicate string:type == "XCUIElementTypeButton" AND label == "Files"');
  assert.ok(button && await button.isEnabled(), 'IOS_FILES_MATTER_SECTION_REQUIRED');
  await dispatchNativeClick(context, button);
  assert.equal(await read(context, 'id', 'files-matter-code', { scroll: true }), context.fixture.matter.identityLabel, 'IOS_FILES_WRONG_MATTER');
  assert.equal(await read(context, 'id', 'files-matter-title', { scroll: true }), context.fixture.matter.title, 'IOS_FILES_WRONG_MATTER_TITLE');
}
export async function expandIosSourceDetails(context, button) {
  assert.equal(await button.getAttribute('type'), 'XCUIElementTypeButton', 'IOS_FILES_DETAILS_BUTTON_REQUIRED');
  assert.equal(await button.getAttribute('accessible'), 'true', 'IOS_FILES_ACCESSIBLE_DETAILS_BUTTON_REQUIRED');
  const label = await button.getAttribute('label');
  assert.ok(['Source details', 'Hide source details'].includes(label), 'IOS_FILES_DETAILS_STATE_REQUIRED');
  assert.equal(await button.isEnabled(), true, 'IOS_FILES_DETAILS_BUTTON_DISABLED');
  if (label === 'Source details') await dispatchNativeClick(context, button);
}
export async function findIosFileFact(context, id, type) {
  const query = selector('ios', 'id', id);
  nativeAction(context, 'find', 'id', id);
  let control;
  for (let attempt = 0; attempt <= 9; attempt++) {
    let direction, frame, viewport;
    try {
      await context.driver.waitUntil(async () => {
        const matches = await context.driver.$$(query);
        assert.ok(matches.length <= 1, 'IOS_FILES_FACT_ID_NOT_UNIQUE');
        if (!matches.length) return false;
        control = matches[0];
        assert.equal(await control.getAttribute('name'), id, 'IOS_FILES_FACT_ID_MISMATCH');
        assert.equal(await control.getAttribute('type'), type, 'IOS_FILES_FACT_TYPE_MISMATCH');
        const scroll = await visible(context.driver, '-ios predicate string:type == "XCUIElementTypeScrollView"');
        assert.ok(scroll, 'IOS_FILES_VIEWPORT_REQUIRED');
        viewport = await context.driver.getElementRect(scroll.elementId);
        frame = await context.driver.getElementRect(control.elementId);
        const window = await context.driver.getWindowRect();
        assert.ok(validFrame(frame) && validFrame(viewport) && validFrame(window) && containsFrame(window, viewport), 'IOS_FILES_FACT_GEOMETRY_REQUIRED');
        assert.ok(frame.x >= viewport.x && frame.x + frame.width <= viewport.x + viewport.width, 'IOS_FILES_FACT_HORIZONTAL_BOUNDS_REQUIRED');
        direction = frame.y < viewport.y ? 'up' : frame.y + frame.height > viewport.y + viewport.height ? 'down' : undefined;
        return !direction && await control.isDisplayed();
      }, { timeout: 1500, interval: 150, timeoutMsg: 'IOS_FILES_FACT_NOT_VISIBLE' });
      return control;
    } catch (error) {
      if (/NOT_UNIQUE|MISMATCH|GEOMETRY_REQUIRED|HORIZONTAL_BOUNDS_REQUIRED|VIEWPORT_REQUIRED|AMBIGUOUS_VISIBLE_NATIVE_LOCATOR/.test(error.message)
        || !direction || attempt === 9) throw error;
      event(context, 'ios-file-fact-scroll-geometry', { controlId: id, attempt: attempt + 1, direction, frame, viewport });
      assert.equal(await visible(context.driver, '-ios predicate string:type == "XCUIElementTypeKeyboard"'), undefined, 'IOS_FILES_KEYBOARD_MUST_BE_ABSENT');
      // A full-height flick can carry a short row from below the viewport to
      // above it in one gesture. Drag only the measured gap, slowly, through
      // the same non-interactive left gutter and remeasure before continuing.
      const gap = direction === 'up' ? viewport.y - frame.y : frame.y + frame.height - viewport.y - viewport.height;
      const far = gap > viewport.height / 2;
      const room = far ? Math.floor(viewport.height - 64) : Math.min(160, Math.floor((viewport.height - 32) / 2));
      assert.ok(room >= 44, 'IOS_FILES_SCROLL_SPAN_REQUIRED');
      const distance = Math.min(room, Math.max(44, Math.ceil(gap + 24)));
      const x = viewport.x + 8, start = far ? Math.round(direction === 'up' ? viewport.y + 32 : viewport.y + viewport.height - 32)
        : Math.round(viewport.y + viewport.height / 2);
      const end = start + (direction === 'up' ? distance : -distance);
      event(context, 'ios-file-fact-bounded-drag', { controlId: id, attempt: attempt + 1, x, start, end, duration: 650 });
      await context.driver.performActions([{ type: 'pointer', id: 'ios-files-scroll', parameters: { pointerType: 'touch' }, actions: [
        { type: 'pointerMove', duration: 0, x, y: start }, { type: 'pointerDown', button: 0 },
        { type: 'pointerMove', duration: 650, x, y: end }, { type: 'pointerUp', button: 0 },
      ] }]);
      await context.driver.releaseActions();
    }
  }
}
async function clickIosFileFact(context, id, type = 'XCUIElementTypeButton') {
  const control = await findIosFileFact(context, id, type);
  await dispatchNativeClick(context, control, 'id', id);
}
async function details(context, anchor) {
  const name = await findIosFileFact(context, `files-name-${anchor.attachmentId}`, 'XCUIElementTypeStaticText');
  assert.equal(await name.getText(), anchor.filename, 'IOS_FILES_WRONG_FILENAME');
  const row = await marker(context, `files-row-${anchor.attachmentId}`);
  assert.ok(containsFrame(await context.driver.getElementRect(row.elementId), await context.driver.getElementRect(name.elementId)), 'IOS_FILES_FILENAME_OUTSIDE_ROW');
  const button = await findIosFileFact(context, `files-source-${anchor.attachmentId}`, 'XCUIElementTypeButton');
  await expandIosSourceDetails(context, button);
  assert.equal(await (await findIosFileFact(context, `files-hash-${anchor.attachmentId}`, 'XCUIElementTypeStaticText')).getText(), anchor.sha256, 'IOS_FILES_WRONG_SOURCE_HASH');
}
async function reload(context, anchor) {
  const before = await traffic(context);
  await clickIosFileFact(context, 'files-reload');
  await wait(context, async () => delta(before, await traffic(context)).some(({ method, route, status }) => method === 'GET'
    && route === `/api/matters/${anchor.matterId}/workspace` && status === 200), 10000, 'IOS_FILES_AUTHORITATIVE_RELOAD_REQUIRED');
  // Loading can shrink the list and reset its offset; the row direction is not
  // implied by the earlier Reload button position.
  await details(context, anchor);
}
async function choose(context, asset, { cancel = false } = {}) {
  const observed = cancel ? validatePickerProvider(context) : validatePickerAsset(context, asset);
  const { back: pickerBackToRoot, root: pickerRoot, location: pickerLocation } = pickerRootControls(
    observedLocalPickerRoot(context, json(observed.evidence)));
  await clickIosFileFact(context, 'files-choose');
  await findQuery(context, pickerBar);
  let navigationActions = 0;
  const navigate = async (control) => {
    assert.ok(control && await control.isEnabled(), 'IOS_FILES_PICKER_NAVIGATION_NOT_READY');
    assert.ok(++navigationActions <= 5, 'IOS_FILES_PICKER_NAVIGATION_BOUND');
    await dispatchNativeClick(context, control);
  };
  if (cancel) {
    if (!await visible(context.driver, cancelPicker)) {
      // Files retains its last successfully selected folder across cohorts.
      // Cancellation needs only the observed provider parent, never a match
      // against the new cohort's folder or a click on any file.
      await navigate(await findQuery(context, pickerBackToRoot));
      await findQuery(context, pickerRoot);
    }
    await navigate(await findQuery(context, cancelPicker));
  }
  else {
    const heading = folderHeading(observed.folderName);
    if (!await visible(context.driver, heading)) {
      let parent = await visible(context.driver, pickerBackToRoot);
      let location = await visible(context.driver, pickerLocation);
      if (!parent && !location && !await visible(context.driver, pickerRoot)) {
        await navigate(await findQuery(context, browsePicker));
        await wait(context, async () => !!await visible(context.driver, heading)
          || !!await visible(context.driver, pickerBackToRoot) || !!await visible(context.driver, pickerRoot)
          || !!await visible(context.driver, pickerLocation), 10000, 'IOS_FILES_KNOWN_PICKER_LOCATION_REQUIRED');
        parent = await visible(context.driver, pickerBackToRoot);
        location = await visible(context.driver, pickerLocation);
      }
      if (!await visible(context.driver, heading)) {
        if (parent) await navigate(parent);
        else if (location) await navigate(location);
        await findQuery(context, pickerRoot);
        await navigate(await findQuery(context, observed.folderQuery));
      }
    }
    await findQuery(context, heading);
    const query = observed.fileQueryTemplate.replace('{pickerNameJSON}', JSON.stringify(observed.pickerName));
    const selected = await findQuery(context, query);
    await navigate(selected);
  }
  await wait(context, async () => !await visible(context.driver, pickerBar), 15000, 'IOS_FILES_PICKER_RETURN_REQUIRED');
  await findIosFileFact(context, 'files-matter-code', 'XCUIElementTypeStaticText');
  if (!cancel) await proveIosSelectedFile(context, asset);
}
export async function proveIosSelectedFile(context, asset) {
  const upload = await findIosFileFact(context, 'files-upload', 'XCUIElementTypeButton');
  assert.equal(await upload.isEnabled(), true, 'IOS_FILES_UPLOAD_DISABLED');
  const selection = await marker(context, 'files-selection');
  const name = await find(context, 'text', asset.filename);
  const frame = await context.driver.getElementRect(selection.elementId);
  assert.ok(validFrame(frame) && containsFrame(frame, await context.driver.getElementRect(upload.elementId))
    && containsFrame(frame, await context.driver.getElementRect(name.elementId)), 'IOS_FILES_SELECTION_FACT_OUTSIDE_MARKER');
  event(context, 'ios-selected-file-structure-and-visible-facts', { frame });
}
export { choose as chooseIosFile };
function uploadAnchor(context, kind) {
  const value = context.filesState.uploads[kind];
  if (!value) fail('IOS_FILES_ACKNOWLEDGED_UPLOAD_DEPENDENCY_REQUIRED');
  return validateSourceAnchor(value);
}
async function admit(context, anchor, acknowledgement) {
  assert.equal(typeof context.admitUploadedFileRead, 'function', 'IOS_FILES_EXACT_SOURCE_ADMISSION_REQUIRED');
  const proof = await context.admitUploadedFileRead(anchor, acknowledgement);
  assert.equal(proof.route, `GET /api/matters/${anchor.matterId}/attachments/${anchor.attachmentId}/download`, 'IOS_FILES_NEW_SOURCE_ADMISSION_MISMATCH');
  if (proof.evidence) json(proof.evidence);
  return proof;
}
export function validateIosUploadAcknowledgement(requests, matterId, { requireRead = false } = {}) {
  const route = `/api/matters/${matterId}/attachments`;
  const uploads = requests.filter((row) => row.method === 'POST' && row.route === route);
  assert.equal(uploads.length, 1, 'IOS_FILES_UPLOAD_NOT_EXACTLY_ONCE');
  assert.equal(uploads[0].status, 200, 'IOS_FILES_CANONICAL_UPLOAD_ACK_REQUIRED');
  const other = requests.filter((row) => row !== uploads[0]);
  assert.ok(other.every((row) => ['GET', 'HEAD', 'OPTIONS'].includes(row.method)
    || row.method === 'POST' && row.route === '/api/auth/native/refresh' && row.status === 200), 'IOS_FILES_UNEXPECTED_UPLOAD_JOURNEY_MUTATION');
  if (requireRead) readOnlyTraffic(other);
  return uploads[0];
}
export async function rapidActivateIosUpload(context, button) {
  assert.equal(context.platform, 'ios', 'IOS_FILES_PLATFORM_REQUIRED');
  assert.ok(typeof button.elementId === 'string' && button.elementId.length > 0, 'NATIVE_CLICK_ELEMENT_ID_REQUIRED');
  assert.equal(await button.getAttribute('name'), 'files-upload', 'IOS_FILES_UPLOAD_CONTROL_REQUIRED');
  assert.equal(await button.getAttribute('type'), 'XCUIElementTypeButton', 'IOS_FILES_UPLOAD_CONTROL_REQUIRED');
  assert.equal(await button.isDisplayed(), true, 'IOS_FILES_UPLOAD_CONTROL_REQUIRED');
  assert.equal(await button.isEnabled(), true, 'IOS_FILES_UPLOAD_DISABLED');
  const frame = await context.driver.getElementRect(button.elementId), window = await context.driver.getWindowRect();
  assert.ok(validFrame(frame) && validFrame(window) && containsFrame(window, frame), 'IOS_FILES_UPLOAD_INPUT_GEOMETRY_REQUIRED');
  assert.equal(typeof context.driver.performActions, 'function', 'IOS_FILES_NATIVE_TOUCH_REQUIRED');
  assert.equal(typeof context.driver.releaseActions, 'function', 'IOS_FILES_NATIVE_TOUCH_REQUIRED');
  const x = Math.floor(frame.x + frame.width / 2), y = Math.floor(frame.y + frame.height / 2);
  nativeAction(context, 'click', 'id', 'files-upload');
  let failure;
  try {
    await context.driver.performActions([{ type: 'pointer', id: 'ios-upload-repeat', parameters: { pointerType: 'touch' }, actions: [
      { type: 'pointerMove', duration: 0, x, y }, { type: 'pointerDown', button: 0 }, { type: 'pointerUp', button: 0 },
      { type: 'pause', duration: 10 }, { type: 'pointerDown', button: 0 }, { type: 'pointerUp', button: 0 },
    ] }]);
  } catch (error) { failure = error; }
  try { await context.driver.releaseActions(); }
  catch (error) {
    if (!failure) failure = error;
    else context.record?.({ type: 'native_input_cleanup_failed', operation: 'release-actions', controlId: 'files-upload' });
  }
  if (failure) throw failure;
  event(context, 'ios-native-upload-two-tap-input', { tapAttempts: 2, nativeProtocolDispatches: 1, gapMs: 10, frame });
}
async function upload(context, kind) {
  const asset = validateAsset(context, kind);
  await enterFiles(context); await noSelection(context);
  const nameQuery = '-ios predicate string:type == "XCUIElementTypeStaticText" AND name BEGINSWITH "files-name-" AND label == ' + JSON.stringify(asset.filename);
  assert.equal(await visible(context.driver, nameQuery), undefined, 'IOS_FILES_UPLOAD_FILENAME_ALREADY_EXISTS');
  const before = await traffic(context);
  await choose(context, asset);
  const button = await findIosFileFact(context, 'files-upload', 'XCUIElementTypeButton');
  context.filesState.mutationUncertain = true;
  context.filesState.pendingUpload = { kind, filename: asset.filename, sha256: asset.sha256 };
  if (kind === 'txt') await rapidActivateIosUpload(context, button);
  else await dispatchNativeClick(context, button, 'id', 'files-upload');
  await wait(context, async () => {
    await assertIosUploadErrorsAbsent(context);
    return delta(before, await traffic(context)).some(({ method, route, status }) => method === 'POST'
      && route === `/api/matters/${context.source.matterId}/attachments` && status === 200);
  }, 30000, 'IOS_FILES_UPLOAD_ACK_REQUIRED');
  const acknowledgement = validateIosUploadAcknowledgement(delta(before, await traffic(context)), context.source.matterId);
  await findIosUploadPersisted(context);
  const names = await context.driver.$$(nameQuery);
  assert.equal(names.length, 1, 'IOS_FILES_ACKNOWLEDGED_FILENAME_NOT_UNIQUE');
  const id = /^files-name-([a-f0-9-]{36})$/.exec(await names[0].getAttribute('name'))?.[1];
  assert.ok(UUID.test(id || ''), 'IOS_FILES_ACKNOWLEDGED_ID_REQUIRED');
  const anchor = { ...asset, matterId: context.source.matterId, attachmentId: id };
  assert.notEqual(id, context.source.attachmentId, 'IOS_FILES_UPLOAD_ID_REUSED');
  await details(context, anchor); await reload(context, anchor);
  assert.equal(validateIosUploadAcknowledgement(delta(before, await traffic(context)), context.source.matterId, { requireRead: true }).requestId,
    acknowledgement.requestId, 'IOS_FILES_UPLOAD_ACK_CHANGED');
  context.filesState.uploads[kind] = anchor;
  context.filesState.mutationUncertain = false;
  delete context.filesState.pendingUpload;
  const admission = await admit(context, anchor, acknowledgement);
  event(context, 'ios-native-picker-upload-persisted', { kind, attachmentId: id, sha256: asset.sha256,
    sizeBytes: asset.sizeBytes, acknowledgementRequestId: acknowledgement.requestId, admission });
}
async function openReader(context, anchor) {
  await details(context, anchor);
  const before = await traffic(context);
  const button = await findIosFileFact(context, `files-open-${anchor.attachmentId}`, 'XCUIElementTypeButton');
  assert.equal(await button.isEnabled(), true, 'IOS_FILES_READER_UNAVAILABLE');
  await dispatchNativeClick(context, button, 'id', `files-open-${anchor.attachmentId}`);
  await find(context, 'id', 'viewer-filename');
  await proveIosReaderEntry(context, anchor);
  return before;
}
async function assertSourceRead(context, before, anchor) {
  const route = `/api/matters/${anchor.matterId}/attachments/${anchor.attachmentId}/download`;
  const rows = delta(before, await traffic(context)).filter((row) => row.method === 'GET' && row.route === route);
  assert.equal(rows.filter(({ status }) => status === 200).length, 1, 'IOS_FILES_ONE_FULL_ORIGINAL_READ_REQUIRED');
  assert.ok(rows.filter(({ status }) => status === 206).length >= 2, 'IOS_FILES_BEFORE_AFTER_RANGE_CHECKS_REQUIRED');
  assert.ok(rows.length <= 12 && rows.every(({ status }) => [200, 206].includes(status)), 'IOS_FILES_ORIGINAL_READ_BOUND');
}
async function closeReader(context) {
  await click(context, 'id', 'viewer-close');
  await assertIosViewerAbsent(context);
  await findIosFileFact(context, 'files-matter-code', 'XCUIElementTypeStaticText');
}
export function textSegments(text) {
  assert.ok(typeof text === 'string' && text.length > 0 && text.length <= 500000, 'IOS_FILES_BOUNDED_TEXT_ORACLE_REQUIRED');
  return Array.from({ length: Math.ceil(text.length / 10000) }, (_, index) => text.slice(index * 10000, (index + 1) * 10000));
}
async function readText(context, anchor) {
  assert.equal(typeof anchor.text, 'string', 'IOS_FILES_EXACT_TEXT_ORACLE_REQUIRED');
  const before = await openReader(context, anchor);
  const segments = textSegments(anchor.text);
  const check = async (page) => {
    assert.equal(await read(context, 'id', 'viewer-position'), `Segment ${page} of ${segments.length}`, 'IOS_FILES_TEXT_SEGMENT_MISMATCH');
    assert.equal((await read(context, 'id', 'viewer-text')).trimEnd(), segments[page - 1].trimEnd(), 'IOS_FILES_TEXT_BYTES_DISPLAY_MISMATCH');
    assert.equal(await (await find(context, 'id', 'viewer-previous')).isEnabled(), page > 1, 'IOS_FILES_TEXT_PREVIOUS_STATE_MISMATCH');
    assert.equal(await (await find(context, 'id', 'viewer-next')).isEnabled(), page < segments.length, 'IOS_FILES_TEXT_NEXT_STATE_MISMATCH');
  };
  await check(1);
  if (segments.length > 1) {
    await click(context, 'id', 'viewer-zoom-in');
    await wait(context, async () => await read(context, 'id', 'viewer-zoom') === '125%', 15000, 'IOS_FILES_TEXT_ZOOM_ACK_REQUIRED');
    await check(1);
  }
  for (let page = 2; page <= segments.length; page++) {
    await click(context, 'id', 'viewer-next');
    await wait(context, async () => await read(context, 'id', 'viewer-position') === `Segment ${page} of ${segments.length}`, 10000, 'IOS_FILES_TEXT_NEXT_ACK_REQUIRED');
    await check(page);
  }
  for (let page = segments.length - 1; page >= 1; page--) {
    await click(context, 'id', 'viewer-previous');
    await wait(context, async () => await read(context, 'id', 'viewer-position') === `Segment ${page} of ${segments.length}`, 10000, 'IOS_FILES_TEXT_PREVIOUS_ACK_REQUIRED');
    await check(page);
  }
  await assertSourceRead(context, before, anchor);
  await closeReader(context);
  event(context, 'ios-private-text-segments-read', { attachmentId: anchor.attachmentId, sha256: anchor.sha256,
    segments: segments.length, traversedBothDirections: segments.length > 1, zoomAcknowledged: segments.length > 1 ? 125 : 100 });
}
export function validatePrivacyReceipt(context, boundary, receipt) {
  assert.equal(receipt.schemaVersion, 1, 'IOS_FILES_PRIVACY_SCHEMA_REQUIRED');
  assert.equal(receipt.observed, true, 'IOS_FILES_ACTUAL_PRIVACY_OBSERVATION_REQUIRED');
  assert.equal(receipt.platform, 'ios', 'IOS_FILES_PRIVACY_PLATFORM_MISMATCH');
  assert.equal(receipt.udid, context.fixture.udid, 'IOS_FILES_PRIVACY_DEVICE_MISMATCH');
  assert.equal(receipt.bundleId, context.fixture.appId, 'IOS_FILES_PRIVACY_APP_MISMATCH');
  assert.equal(receipt.boundary, boundary, 'IOS_FILES_PRIVACY_BOUNDARY_MISMATCH');
  assert.equal(receipt.ownedAppScopeOnly, true, 'IOS_FILES_OWNED_SCOPE_REQUIRED');
  assert.equal(receipt.providerOriginalsUnchanged, true, 'IOS_FILES_PROVIDER_ORIGINALS_CHANGED');
  assert.equal(receipt.stagedFileCount, 0, 'IOS_FILES_STAGED_BYTES_RETAINED');
  assert.equal(receipt.privateByteMatchCount, 0, 'IOS_FILES_PRIVATE_BYTES_RETAINED');
  return receipt;
}
async function privacy(context, boundary) {
  const callback = context.observeFilesystem ?? context.privacySnapshot;
  if (typeof callback !== 'function') fail('IOS_FILES_OBSERVED_FILESYSTEM_REQUIRED');
  const hashes = [...new Set([context.source.sha256, ...KINDS.map((kind) => context.assets?.uploads?.[kind]?.sha256).filter(Boolean)])];
  const reference = await callback.call(context, boundary, hashes);
  validatePrivacyReceipt(context, boundary, json(reference));
  event(context, 'ios-filesystem-privacy-observed', { boundaryName: boundary, evidence: reference });
}
async function noPosts(context, before) {
  readOnlyTraffic(delta(before, await traffic(context)));
}
async function signedOut(context) {
  await wait(context, async () => !await visible(context.driver, '~session-loading') && !await visible(context.driver, '~account-open')
    && !!await visible(context.driver, '~signed-out') && !!await visible(context.driver, '~sign-in'), 20000, 'IOS_FILES_SIGNED_OUT_REQUIRED');
}
async function renderer(context, anchor, pages) {
  const before = await openReader(context, anchor);
  await find(context, 'id', 'viewer-isolated-renderer');
  await wait(context, async () => await read(context, 'id', 'viewer-position') === `Page 1 of ${pages}`, 15000, 'IOS_FILES_NATIVE_PAGE_EVENT_REQUIRED');
  await click(context, 'id', 'viewer-zoom-in');
  await wait(context, async () => await read(context, 'id', 'viewer-zoom') === '125%', 15000, 'IOS_FILES_NATIVE_ZOOM_EVENT_REQUIRED');
  if (pages === 2) {
    await click(context, 'id', 'viewer-next');
    await wait(context, async () => await read(context, 'id', 'viewer-position') === 'Page 2 of 2', 15000, 'IOS_FILES_SECOND_PAGE_EVENT_REQUIRED');
    await click(context, 'id', 'viewer-previous');
    await wait(context, async () => await read(context, 'id', 'viewer-position') === 'Page 1 of 2', 15000, 'IOS_FILES_PREVIOUS_PAGE_EVENT_REQUIRED');
  } else assert.equal(await (await find(context, 'id', 'viewer-next')).isEnabled(), false, 'IOS_FILES_SINGLE_IMAGE_PAGE_REQUIRED');
  await assertSourceRead(context, before, anchor);
  await closeReader(context);
  event(context, 'ios-private-native-renderer-acknowledged', { attachmentId: anchor.attachmentId, sha256: anchor.sha256, pages, zoom: 125, privateDomRead: false });
}

export const iosFilesScenarios = Object.freeze([
  { id: 'FILES-01', run: async (context) => { await enterFiles(context); const before = await traffic(context); await reload(context, context.source); await readText(context, context.source); await noPosts(context, before); } },
  { id: 'FILES-02', run: async (context) => { const before = await traffic(context); await enterFiles(context); await choose(context, null, { cancel: true }); await noSelection(context); await noPosts(context, before); await privacy(context, 'picker-cancel'); } },
  { id: 'FILES-03', run: async (context) => { const before = await traffic(context); await enterFiles(context); await choose(context, validateAsset(context, 'txt')); await clickIosFileFact(context, 'files-selection-clear'); await noSelection(context); await noPosts(context, before); await privacy(context, 'selection-clear'); } },
  ...KINDS.map((kind, index) => ({ id: `FILES-${String(index + 4).padStart(2, '0')}`, ...(kind === 'jpeg' ? { freshAuthentication: true } : {}), run: async (context) => { await upload(context, kind); if (kind === 'txt') await readText(context, uploadAnchor(context, kind)); await privacy(context, `uploaded-${kind}`); } })),
  { id: 'FILES-09', freshAuthentication: true, requires: ['FILES-05'], run: async (context) => { await enterFiles(context); const before = await traffic(context); await renderer(context, uploadAnchor(context, 'pdf'), 2); await noPosts(context, before); } },
  { id: 'FILES-10', requires: ['FILES-06', 'FILES-07'], run: async (context) => { await enterFiles(context); const before = await traffic(context); for (const kind of ['png', 'jpeg']) await renderer(context, uploadAnchor(context, kind), 1); await noPosts(context, before); } },
  { id: 'FILES-11', requires: ['FILES-08'], run: async (context) => { const before = await traffic(context); await enterFiles(context); const anchor = uploadAnchor(context, 'docx'); await details(context, anchor); assert.equal(await (await findIosFileFact(context, `files-open-${anchor.attachmentId}`, 'XCUIElementTypeButton')).isEnabled(), false, 'IOS_FILES_DOCX_MUST_REMAIN_UNAVAILABLE'); await findIosFileFact(context, `files-viewer-unavailable-${anchor.attachmentId}`, 'XCUIElementTypeStaticText'); await assertIosViewerAbsent(context); assert.equal(delta(before, await traffic(context)).filter(({ route }) => route.endsWith('/download') || route.endsWith('/preview')).length, 0, 'IOS_FILES_UNSUPPORTED_DOCX_WAS_OPENED'); await noPosts(context, before); } },
  { id: 'FILES-12', run: async (context) => { await enterFiles(context); await openReader(context, context.source); await find(context, 'id', 'viewer-text'); const before = await traffic(context); await backgroundAndResume(context); await assertIosViewerAbsent(context); await enterFiles(context); await noPosts(context, before); await privacy(context, 'viewer-background'); } },
  { id: 'FILES-13', run: async (context) => { await enterFiles(context); const before = await traffic(context); await choose(context, validateAsset(context, 'txt')); await backgroundAndResume(context); await enterFiles(context); await noSelection(context); await noPosts(context, before); await privacy(context, 'selection-background'); } },
  { id: 'FILES-14', run: async (context) => { await enterFiles(context); const before = await traffic(context); await choose(context, validateAsset(context, 'txt')); await click(context, 'id', 'back'); await find(context, 'text', 'Discard file selection?'); await click(context, 'text', 'Stay'); await proveIosSelectedFile(context, validateAsset(context, 'txt')); await click(context, 'id', 'back'); await find(context, 'text', 'Discard file selection?'); await click(context, 'text', 'Leave Files'); await enterFiles(context); await noSelection(context); await noPosts(context, before); await privacy(context, 'selection-discard'); } },
  { id: 'FILES-15', run: async (context) => { await enterFiles(context); const before = await traffic(context); await choose(context, validateAsset(context, 'txt')); await restart(context); await enterFiles(context); await noSelection(context); await openReader(context, context.source); await find(context, 'id', 'viewer-text'); await restart(context); await assertIosViewerAbsent(context); await enterFiles(context); await noSelection(context); await noPosts(context, before); await privacy(context, 'process-restart'); } },
  { id: 'FILES-16', run: async (context) => { await enterFiles(context); await readText(context, context.source); const before = await traffic(context); await click(context, 'id', 'account-open'); await click(context, 'id', 'sign-out', { scroll: true }); await signedOut(context); const changes = delta(before, await traffic(context)), rows = changes.filter(({ method, route }) => method === 'POST' && route === '/api/auth/native/logout'); assert.equal(rows.length, 1, 'IOS_FILES_LOGOUT_NOT_ONCE'); assert.ok([200, 204].includes(rows[0].status), 'IOS_FILES_LOGOUT_NOT_ACKNOWLEDGED'); await assertIosViewerAbsent(context); await absent(context, 'id', 'files-selection'); await privacy(context, 'logout'); context.filesState.logoutAcknowledged = true; } },
  { id: 'FILES-17', requires: ['FILES-16'], requiresSignedOut: true, run: async (context) => { validateIosFilesContext(context); assert.equal(context.filesState.logoutAcknowledged, true, 'IOS_FILES_PRIOR_LOGOUT_ACK_REQUIRED'); const before = await traffic(context); await restart(context); await signedOut(context); await assertIosViewerAbsent(context); for (const id of ['files-selection', 'files-matter-code']) await absent(context, 'id', id); assert.equal(delta(before, await traffic(context)).length, 0, 'IOS_FILES_SIGNED_OUT_RESTORED_PRIVATE_TRAFFIC'); await privacy(context, 'signed-out-restart'); } },
].map((scenario) => Object.freeze({ ...scenario, ...(scenario.requires ? { requires: Object.freeze([...scenario.requires]) } : {}) })));
