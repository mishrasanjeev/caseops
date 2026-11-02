import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { OWNER_OPERATIONS, SEARCH_KINDS, validateBuildReceipt } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { validateAndroidNativeProof } from '../../apps/mobile/e2e/android-native-proof.mjs';
import { validateFirefoxRecipe } from '../../apps/mobile/e2e/firefox-handoff.mjs';
import { validateAuthorizationTraffic } from '../../apps/mobile/e2e/mfa.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';
import { validateSessionDeletePolicy } from '../../apps/mobile/e2e/session-admission.mjs';
import { androidLocalProfile, validateUsbReverseOrigins } from '../../apps/mobile/e2e/android-local-profile.mjs';

const REPO = fileURLToPath(new URL('../../', import.meta.url));
const QA_ID = 'ai.caseops.mobile.dev.localacceptance';
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const encoded = (value) => `${JSON.stringify(value, null, 2)}\n`;
function reference(value) {
  assert.ok(value && path.isAbsolute(value.path || ''), 'ABSOLUTE_INPUT_REFERENCE_REQUIRED');
  assert.ok(!/(credential|secret|\.(key|jks|keystore|p12)$)/i.test(path.basename(value.path)), 'CREDENTIAL_OR_KEY_INPUT_FORBIDDEN');
  assert.match(value.sha256 || '', /^[a-f0-9]{64}$/, 'INPUT_REFERENCE_HASH_REQUIRED');
  return { path: value.path, sha256: value.sha256 };
}
function read(value) {
  const ref = reference(value), result = JSON.parse(verifiedFile(ref.path, ref.sha256));
  noSecrets(result); return result;
}
function nonempty(value, code) { assert.ok(typeof value === 'string' && value.trim() && value.length <= 4000, code); }
function noSecrets(value, locatorMap = false) {
  if (!value || typeof value !== 'object') return;
  for (const [key, item] of Object.entries(value)) {
    const passwordLocator = locatorMap && key === 'password' && item && typeof item === 'object'
      && Object.keys(item).length === 2 && ['id', 'text', 'label', 'buttonText'].includes(item.kind) && typeof item.value === 'string';
    assert.ok(passwordLocator || !/^(password|access_?token|refresh_?token|totp_?secret|code_?verifier|cookies?|private_?key|client_?secret|authorization)$/i.test(key), 'EMBEDDED_SECRET_FORBIDDEN');
    noSecrets(item, key === 'locators');
  }
}
function outside(file) {
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_OUTPUT_REQUIRED');
  let ancestor = path.dirname(file);
  while (!existsSync(ancestor)) ancestor = path.dirname(ancestor);
  const resolved = path.resolve(realpathSync(ancestor), path.relative(ancestor, file));
  const relative = path.relative(realpathSync(REPO), resolved);
  assert.ok(relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative), 'OUTPUT_MUST_STAY_OUTSIDE_REPOSITORY');
  assert.ok(!existsSync(resolved), 'OUTPUT_ALREADY_EXISTS');
  return resolved;
}
function identity(left, right, keys, code) {
  for (const key of keys) assert.equal(left?.[key], right?.[key], code);
}
function sameReference(actual, expected, code) { assert.deepEqual(reference(actual), expected, code); }

function observedDevice(observation, request, build, buildRef) {
  const profile = androidLocalProfile(request.udid, 'DEDICATED_ANDROID_SERIAL_REQUIRED', request.androidTransportMode);
  identity(observation, { schemaVersion: 1, kind: 'observed-android-local-device', observed: true,
    platform: 'android', udid: request.udid, state: 'device', bootCompleted: true,
    apiLevel: 36, architecture: 'arm64-v8a', appId: QA_ID },
  ['schemaVersion', 'kind', 'observed', 'platform', 'udid', 'state', 'bootCompleted', 'apiLevel', 'architecture', 'appId'], 'ACTUAL_READY_ANDROID_DEVICE_REQUIRED');
  nonempty(observation.deviceName, 'OBSERVED_ANDROID_DEVICE_NAME_REQUIRED');
  assert.match(observation.platformVersion || '', /^\d{1,3}(?:\.\d{1,3}){0,2}$/, 'OBSERVED_ANDROID_OS_VERSION_REQUIRED');
  assert.ok(Number.isSafeInteger(observation.versionCode) && observation.versionCode > 0, 'OBSERVED_ANDROID_APP_VERSION_REQUIRED');
  nonempty(observation.versionName, 'OBSERVED_ANDROID_APP_VERSION_REQUIRED');
  assert.equal(observation.installedApkSha256, build.binaryHash, 'OBSERVED_INSTALLED_APK_MISMATCH');
  sameReference(observation.buildReceipt, buildRef, 'DEVICE_BUILD_REFERENCE_MISMATCH');
  identity(observation, profile,
    ['adbPort', 'appiumUrl', 'systemPort'], 'ISOLATED_ANDROID_TRANSPORT_REQUIRED');
  if (profile.deviceKind === 'physical') {
    identity(observation, { transportMode: 'usb-reverse', deviceKind: 'physical', shellUid: 2000 },
      ['transportMode', 'deviceKind', 'shellUid'], 'ACTUAL_PHYSICAL_ANDROID_USB_REQUIRED');
    assert.ok(/^usb:[A-Za-z0-9.:_-]{1,128}$/.test(observation.usbDevPath || ''), 'ACTUAL_PHYSICAL_ANDROID_USB_REQUIRED');
    assert.ok(observation.kernelQemu === '' || observation.kernelQemu === '0', 'ACTUAL_PHYSICAL_ANDROID_USB_REQUIRED');
    assert.equal(Object.hasOwn(observation, 'avdName'), false, 'PHYSICAL_ANDROID_CANNOT_CLAIM_AVD');
  } else if (profile.requiresAvdName || Object.hasOwn(observation, 'avdName')) {
    assert.equal(observation.avdName, profile.avdName, 'OBSERVED_ANDROID_AVD_MISMATCH');
  }
  assert.ok(Array.isArray(observation.evidence) && observation.evidence.length > 0 && observation.evidence.length <= 16,
    'ACTUAL_ANDROID_DEVICE_EVIDENCE_REQUIRED');
  const paths = new Set();
  for (const item of observation.evidence) {
    const ref = reference(item); assert.ok(!paths.has(ref.path), 'DUPLICATE_ANDROID_DEVICE_EVIDENCE'); paths.add(ref.path);
    verifiedFile(ref.path, ref.sha256);
  }
  return observation;
}

// A logged-out browser can retain non-secret workspace context and make one
// rejected refresh attempt after /auth/me. This is a rejected browser probe,
// separate from the exact successful login/MFA/native grant/token/logout spine.
export function validateObservedAndroidAuthTraffic(requests, auth) {
  assert.ok(Array.isArray(requests) && requests.length <= 500, 'BOUNDED_AUTH_OBSERVATION_REQUIRED');
  validateAuthorizationTraffic(requests, auth, { single: true });
  for (const [route, statuses] of [['/api/auth/login', [200]], ['/api/auth/mfa/step-up', [200]], ['/api/auth/native/logout', [200, 204]]]) {
    const attempts = requests.filter((row) => row.method === 'POST' && row.route === route);
    assert.ok(attempts.length === 1 && statuses.includes(attempts[0].status), 'OBSERVED_AUTH_MUTATION_NOT_ONCE_ACKNOWLEDGED');
  }
  const loginIndex = requests.findIndex(({ method, route }) => method === 'POST' && route === '/api/auth/login');
  const refreshes = requests.filter(({ method, route }) => method === 'POST' && route === '/api/auth/refresh');
  assert.ok(refreshes.length <= 1, 'SINGLE_REJECTED_PRELOGIN_BROWSER_REFRESH_REQUIRED');
  const unauthorizedIdentity = requests.filter((row, index) => index < loginIndex && row.method === 'GET'
    && row.route === '/api/auth/me' && row.status === 401);
  assert.ok(unauthorizedIdentity.length <= 2, 'BOUNDED_LOGGED_OUT_BROWSER_IDENTITY_PROBES_REQUIRED');
  for (const row of requests.filter(({ status }) => status === 401)) {
    assert.ok(requests.indexOf(row) < loginIndex && row.browserHandoff === true && row.nativeMarker === true
      && ((row.method === 'GET' && row.route === '/api/auth/me') || refreshes.includes(row)),
    'UNEXPECTED_AUTH_OBSERVATION_401');
  }
  for (const row of refreshes) {
    const index = requests.indexOf(row), preceding = requests.slice(0, index);
    assert.ok(index < loginIndex && row.status === 401 && row.browserHandoff === true && row.nativeMarker === true,
      'REJECTED_PRELOGIN_BROWSER_REFRESH_REQUIRED');
    assert.ok(preceding.some((item) => unauthorizedIdentity.includes(item)), 'PRECEDING_LOGGED_OUT_BROWSER_IDENTITY_REQUIRED');
    assert.ok(!preceding.some(({ method, route, status }) => method !== 'OPTIONS' && route.startsWith('/api/auth/')
      && status >= 200 && status < 400), 'NO_AUTH_SUCCESS_BEFORE_REJECTED_REFRESH');
  }
  const mutations = new Set(['/api/auth/login', '/api/auth/mfa/step-up', '/api/auth/native/authorize', '/api/auth/native/token', '/api/auth/native/logout']);
  assert.ok(requests.every((row) => ['GET', 'HEAD', 'OPTIONS'].includes(row.method)
    || (row.method === 'POST' && (mutations.has(row.route) || refreshes.includes(row)))), 'UNEXPECTED_AUTH_OBSERVATION_MUTATION');
  const spine = requests.filter((row) => row.method === 'POST' && !refreshes.includes(row)).map(({ route, status }) => ({ route, status }));
  assert.deepEqual(spine, [{ route: '/api/auth/login', status: 200 },
    ...(auth.mfaStage === 'consent' ? [{ route: '/api/auth/native/authorize', status: 403 }] : []),
    { route: '/api/auth/mfa/step-up', status: 200 }, { route: '/api/auth/native/authorize', status: 200 },
    { route: '/api/auth/native/token', status: 200 }, { route: '/api/auth/native/logout', status: spine.at(-1)?.status }],
  'ORDERED_NORMAL_AUTH_OBSERVATION_REQUIRED');
  return { rejectedPreLoginBrowserRefreshes: refreshes.length, loggedOutBrowserIdentityReads: unauthorizedIdentity.length };
}

function observedAuth(observation, refs, receipt, extension, device, recipe) {
  identity(observation, { schemaVersion: 1, observed: true, platform: 'android', udid: device.udid,
    mode: 'native-firefox', appId: QA_ID, webOrigin: receipt.webOrigin },
  ['schemaVersion', 'observed', 'platform', 'udid', 'mode', 'appId', 'webOrigin'], 'ACTUAL_ANDROID_AUTH_OBSERVATION_REQUIRED');
  identity(observation, extension, ['companyId', 'membershipId', 'principalLabel', 'workspaceLabel'], 'AUTH_OBSERVATION_MEMBER_MISMATCH');
  for (const key of ['dockerReceipt', 'buildReceipt', 'extensionSeed', 'deviceObservation', 'firefoxRecipe']) {
    sameReference(observation[key], refs[key], 'AUTH_OBSERVATION_PROVENANCE_MISMATCH');
  }
  for (const key of ['pkceUnchanged', 'nativePrincipalVerified', 'nativeWorkspaceVerified', 'logoutAcknowledged', 'signedOutAfter', 'sessionClosed']) {
    assert.equal(observation[key], true, 'COMPLETE_NORMAL_AUTH_OBSERVATION_REQUIRED');
  }
  assert.ok(['login', 'consent'].includes(observation.mfaStage), 'OBSERVED_MFA_STAGE_REQUIRED');
  const auth = { ...extension.auth, mfaStage: observation.mfaStage, firefoxUi: recipe };
  validateFirefoxRecipe(auth);
  const locatorEvidence = read({ path: recipe.locatorEvidencePath, sha256: recipe.locatorEvidenceSha256 });
  identity(locatorEvidence, { observed: true, platform: 'android', udid: device.udid, appId: QA_ID },
    ['observed', 'platform', 'udid', 'appId'], 'FIREFOX_LOCATOR_DEVICE_MISMATCH');
  sameReference(locatorEvidence.buildReceipt, refs.buildReceipt, 'FIREFOX_LOCATOR_BUILD_MISMATCH');
  sameReference(locatorEvidence.publicCa, refs.publicCa, 'FIREFOX_CA_OBSERVATION_MISMATCH');
  const before = read(observation.gatewayBefore), after = read(observation.gatewayAfter);
  validateTraffic(after, gatewayBaseline(before, receipt));
  assert.deepEqual(after.requests.slice(0, before.requests.length), before.requests, 'AUTH_OBSERVATION_HISTORY_CHANGED');
  const requests = after.requests.slice(before.lastSequence);
  assert.ok(requests.every(({ status }) => Number.isInteger(status)), 'SETTLED_AUTH_OBSERVATION_REQUIRED');
  validateObservedAndroidAuthTraffic(requests, auth);
  return auth;
}

function applyLabels(expectations, observation, extension, device) {
  identity(observation, { schemaVersion: 1, observed: true, platform: 'android', udid: device.udid, locale: extension.locale },
    ['schemaVersion', 'observed', 'platform', 'udid', 'locale'], 'ACTUAL_ANDROID_LABEL_OBSERVATION_REQUIRED');
  const allowed = { today: ['dateLabel', 'metaLabel'], 'work.task': ['metaLabel'],
    'work.draft': ['statusLabel', 'revisionLabel', 'verifiedCitationCountLabel', 'metaLabel'],
    calendar: ['dayLabel', 'metaLabel', 'nextHearingLabel'] };
  for (const [section, labels] of Object.entries(observation.labels || {})) {
    assert.ok(allowed[section], 'LABEL_OVERRIDE_SECTION_FORBIDDEN');
    const target = section.split('.').reduce((value, key) => value[key], expectations);
    for (const [key, value] of Object.entries(labels)) {
      assert.ok(allowed[section].includes(key), 'SOURCE_IDENTITY_OR_CONTENT_OVERRIDE_FORBIDDEN');
      nonempty(value, 'OBSERVED_LABEL_REQUIRED'); target[key] = value;
    }
  }
}

// Projects existing immutable evidence only. It never launches tools, reads
// member credentials, contacts services, installs packages or creates fixtures.
export function createAndroidLocalRun(request) {
  noSecrets(request);
  assert.equal(request.schemaVersion, 1, 'ANDROID_EXPORT_REQUEST_VERSION_REQUIRED');
  const refs = Object.fromEntries(['dockerReceipt', 'baseSeed', 'extensionSeed', 'buildReceipt', 'publicCa',
    'ownerControls', 'ownerBinding', 'gatewayRoutes', 'deviceObservation', 'firefoxRecipe', 'authObservation']
    .map((key) => [key, reference(request[key])]));
  const receipt = read(refs.dockerReceipt), base = read(refs.baseSeed), extension = read(refs.extensionSeed);
  const build = read(refs.buildReceipt), owner = read(refs.ownerControls), binding = read(refs.ownerBinding);
  for (const value of [receipt, base, extension, binding]) {
    assert.equal(value.environment, 'docker-integration', 'REAL_DOCKER_EVIDENCE_REQUIRED');
    assert.equal(value.syntheticDataOnly, true, 'SYNTHETIC_EVIDENCE_REQUIRED');
  }
  assert.equal(receipt.platform, 'android', 'ANDROID_DOCKER_RECEIPT_REQUIRED');
  assert.equal(extension.platform, 'android', 'ANDROID_EXTENSION_REQUIRED');
  for (const value of [receipt, extension]) assert.equal(value.androidTransportMode, request.androidTransportMode,
    'ANDROID_TRANSPORT_MODE_PROVENANCE_MISMATCH');
  if (request.androidTransportMode === 'usb-reverse') validateUsbReverseOrigins(receipt.apiOrigin, receipt.webOrigin);
  assert.equal(extension.coreInventory, 'native-core-2026-10-25', 'DATED_EXTENSION_REQUIRED');
  assert.equal(extension.baseSeed?.sha256, refs.baseSeed.sha256, 'EXTENSION_BASE_SEED_HASH_MISMATCH');
  assert.equal(path.basename(refs.baseSeed.path), extension.baseSeed?.file, 'EXTENSION_BASE_SEED_FILE_MISMATCH');
  assert.equal(extension.companyId, base.companyId, 'EXTENSION_COMPANY_MISMATCH');
  assert.notEqual(extension.membershipId, base.membershipId, 'EXTENDED_MEMBER_REQUIRED');
  assert.equal(extension.ownerMembershipId, base.membershipId, 'EXTENSION_OWNER_MISMATCH');
  for (const key of ['principalLabel', 'workspaceLabel', 'membershipId', 'userId']) nonempty(extension[key], 'ACTUAL_EXTENDED_MEMBER_REQUIRED');
  assert.equal(extension.destructiveControlsExecuted, false, 'FRESH_EXTENSION_REQUIRED');
  assert.equal(extension.nativeBrowserCookiesOrTokensPrepared, false, 'NATIVE_CREDENTIAL_INJECTION_FORBIDDEN');
  identity(extension.matter, base.matter, ['id', 'identityLabel', 'search'], 'EXTENSION_PRIMARY_MATTER_MISMATCH');
  assert.equal(extension.calendar?.day, base.calendarDate, 'EXTENSION_DATE_MISMATCH');
  assert.equal(extension.work?.draft?.id, base.draftId, 'EXTENSION_DRAFT_MISMATCH');
  assert.equal(extension.foreignMatter?.id, base.otherMatterId, 'EXTENSION_FOREIGN_MATTER_MISMATCH');
  assert.equal(extension.today?.id, extension.work?.task?.id, 'MEMBER_TASK_MISMATCH');
  assert.notEqual(extension.today?.id, base.taskId, 'EXTENDED_MEMBER_TASK_REQUIRED');
  assert.match(extension.calendar?.eventId || '', /^[A-Za-z0-9_:.-]{1,160}$/, 'ACTUAL_CALENDAR_EVENT_ID_REQUIRED');
  assert.deepEqual(extension.matter.searches?.map(({ kind }) => kind), SEARCH_KINDS, 'EXACT_SEARCH_INVENTORY_REQUIRED');
  assert.equal(new Set(extension.matter.searches.map(({ value }) => value)).size, SEARCH_KINDS.length, 'DISTINCT_SEARCH_IDENTIFIERS_REQUIRED');
  for (const value of extension.matter.searches) nonempty(value.value, 'ACTUAL_SEARCH_IDENTIFIER_REQUIRED');
  for (const key of ['lifecycleMatter', 'accessMatter']) {
    nonempty(extension[key]?.id, 'FRESH_NEGATIVE_TARGET_REQUIRED');
    assert.notEqual(extension[key].id, extension.matter.id, 'SEPARATE_NEGATIVE_TARGET_REQUIRED');
  }
  assert.notEqual(extension.lifecycleMatter.id, extension.accessMatter.id, 'DISTINCT_NEGATIVE_TARGETS_REQUIRED');
  for (const key of ['backendSha', 'webSha']) assert.match(receipt[key] || '', /^[a-f0-9]{40}$/, 'EXACT_SERVING_SHA_REQUIRED');
  assert.equal(receipt.webIdentity?.release_sha, receipt.webSha, 'WEB_IDENTITY_SOURCE_MISMATCH');
  assert.equal(receipt.webIdentity?.revision, receipt.webRevision, 'WEB_IDENTITY_REVISION_MISMATCH');
  assert.equal(extension.servingBuild?.release_sha, receipt.backendSha, 'EXTENSION_SERVING_SHA_MISMATCH');
  assert.equal(extension.servingBuild?.revision, receipt.backendRevision, 'EXTENSION_SERVING_REVISION_MISMATCH');
  for (const scope of ['api', 'web']) {
    assert.equal(receipt.source?.[scope]?.dirty, false, 'CLEAN_SERVING_INPUTS_REQUIRED');
    assert.equal(receipt.source[scope].head, receipt[scope === 'api' ? 'backendSha' : 'webSha'], 'SERVING_SOURCE_HEAD_MISMATCH');
  }
  assert.equal(build.platform, 'android', 'ANDROID_BUILD_REQUIRED');
  assert.equal(build.profile, 'android-local-acceptance', 'STANDALONE_ANDROID_BUILD_REQUIRED');
  assert.equal(build.appId, QA_ID, 'QA_ANDROID_ID_REQUIRED');
  assert.equal(build.sourceDirty, false, 'CLEAN_APP_INPUTS_REQUIRED');
  assert.equal(build.sourceSha, receipt.backendSha, 'APP_API_SOURCE_MISMATCH');
  assert.equal(build.sourceSha, receipt.webSha, 'APP_WEB_SOURCE_MISMATCH');
  assert.match(build.sourceFingerprint || '', /^[a-f0-9]{64}$/, 'EXACT_APP_SOURCE_FINGERPRINT_REQUIRED');
  identity(build, receipt, ['apiOrigin', 'webOrigin'], 'APP_FIXTURE_ORIGIN_MISMATCH');
  assert.equal(build.devEnabled, false, 'BUNDLED_STANDALONE_BUILD_REQUIRED');
  assert.equal(build.automatedTest, true, 'BUILD_MARKER_REQUIRED');
  assert.ok(path.isAbsolute(build.artifact || '') && build.artifact.endsWith('.apk'), 'ABSOLUTE_ANDROID_APK_REQUIRED');
  assert.equal(binaryHash(build.artifact), build.binaryHash, 'ACTUAL_APP_BINARY_HASH_MISMATCH');
  verifiedFile(refs.publicCa.path, refs.publicCa.sha256);
  assert.equal(path.resolve(receipt.publicCA), path.resolve(refs.publicCa.path), 'FIXTURE_PUBLIC_CA_PATH_MISMATCH');
  const buildTarget = { appId: QA_ID, udid: request.udid, environment: 'docker-integration', syntheticDataOnly: true,
    coreInventory: 'native-core-2026-10-25', buildReceipt: refs.buildReceipt,
    binarySourceSha: build.sourceSha, binarySourceFingerprint: build.sourceFingerprint,
    apiOrigin: build.apiOrigin, auth: { webOrigin: build.webOrigin }, appPath: build.artifact, publicCa: refs.publicCa };
  validateBuildReceipt(buildTarget, 'android', build.binaryHash);
  const proof = validateAndroidNativeProof(buildTarget, build, build.binaryHash);
  assert.ok(proof, 'MAC_ANDROID_NATIVE_PROOF_REQUIRED');
  const device = observedDevice(read(refs.deviceObservation), request, build, refs.buildReceipt);
  identity(device, proof, ['versionCode', 'versionName'], 'INSTALLED_ANDROID_VERSION_MISMATCH');
  assert.equal(binding.extensionFile, path.basename(refs.extensionSeed.path), 'OWNER_EXTENSION_FILE_MISMATCH');
  assert.equal(binding.extensionSha256, refs.extensionSeed.sha256, 'OWNER_EXTENSION_HASH_MISMATCH');
  identity(binding, receipt, ['project', 'backendSha', 'backendRevision'], 'OWNER_BACKEND_MISMATCH');
  assert.equal(binding.destructiveControlsExecuted, false, 'FRESH_OWNER_BINDING_REQUIRED');
  assert.equal(binding.modulePath, owner.modulePath, 'OWNER_MODULE_MISMATCH');
  assert.equal(binding.moduleSha256, owner.sha256, 'OWNER_MODULE_HASH_MISMATCH');
  verifiedFile(owner.modulePath, owner.sha256); verifiedFile(binding.pythonPath, binding.pythonSha256);
  assert.deepEqual([...owner.capabilities].sort(), [...OWNER_OPERATIONS].sort(), 'ALL_OWNER_CAPABILITIES_REQUIRED');
  assert.deepEqual([...binding.capabilities].sort(), [...OWNER_OPERATIONS].sort(), 'OWNER_BINDING_CAPABILITIES_MISMATCH');
  const api = receipt.containers?.filter(({ name }) => /-api-\d+$/.test(name));
  assert.equal(api?.length, 1, 'EXACT_OWNER_API_CONTAINER_REQUIRED');
  assert.equal(binding.apiContainerId, api[0].id, 'OWNER_CONTAINER_MISMATCH');
  assert.equal(binding.apiImage, api[0].image, 'OWNER_IMAGE_MISMATCH');
  assert.equal(validateSessionDeletePolicy(read(refs.gatewayRoutes), refs.gatewayRoutes, refs.dockerReceipt, receipt).mode,
    'dynamic', 'DYNAMIC_SESSION_POLICY_REQUIRED');
  const locale = read(extension.localeEvidence);
  identity(locale, { platform: 'android', udid: request.udid, locale: extension.locale },
    ['platform', 'udid', 'locale'], 'ACTUAL_ANDROID_LOCALE_EVIDENCE_REQUIRED');
  nonempty(extension.locale, 'OBSERVED_ANDROID_LOCALE_REQUIRED');
  assert.equal(extension.auth?.mode, 'native-firefox', 'ANDROID_NATIVE_BROWSER_MODE_REQUIRED');
  assert.equal(extension.auth?.mfaRequired, true, 'EXTENDED_MEMBER_MFA_REQUIRED');
  assert.equal(extension.auth?.webOrigin, receipt.webOrigin, 'EXTENSION_WEB_ORIGIN_MISMATCH');
  assert.match(extension.auth.companySlug || '', /^[a-z0-9-]{2,80}$/, 'ACTUAL_WORKSPACE_SLUG_REQUIRED');
  for (const key of ['emailEnv', 'passwordEnv', 'totpSecretEnv']) {
    assert.match(extension.auth[key] || '', /^CASEOPS_MOBILE_[A-Z0-9_]+$/, 'CREDENTIAL_ENVIRONMENT_NAME_REQUIRED');
  }
  assert.equal(new Set(['emailEnv', 'passwordEnv', 'totpSecretEnv'].map(key => extension.auth[key])).size, 3,
    'DISTINCT_CREDENTIAL_ENVIRONMENT_NAMES_REQUIRED');
  const auth = observedAuth(read(refs.authObservation), refs, receipt, extension, device, read(refs.firefoxRecipe));
  const expectations = Object.fromEntries(['matter', 'today', 'work', 'calendar', 'foreignMatter', 'lifecycleMatter', 'accessMatter']
    .map((key) => [key, structuredClone(extension[key])]));
  if (request.labelObservations) applyLabels(expectations, read(request.labelObservations), extension, device);
  const outputs = Object.fromEntries(['outputSeed', 'outputPlan', 'outputFixture'].map((key) => [key, outside(request[key])]));
  assert.equal(new Set(Object.values(outputs)).size, 3, 'DISTINCT_OUTPUT_PATHS_REQUIRED');
  const provenance = { baseSeed: refs.baseSeed, extensionSeed: refs.extensionSeed, localeEvidence: reference(extension.localeEvidence),
    ownerBinding: refs.ownerBinding, deviceObservation: refs.deviceObservation, authObservation: refs.authObservation,
    firefoxRecipe: refs.firefoxRecipe, ...(request.labelObservations ? { labelObservations: reference(request.labelObservations) } : {}) };
  const effectiveSeed = { environment: 'docker-integration', syntheticDataOnly: true,
    principalLabel: extension.principalLabel, workspaceLabel: extension.workspaceLabel,
    companyId: extension.companyId, membershipId: extension.membershipId, userId: extension.userId,
    matter: structuredClone(extension.matter), taskId: extension.today.id, draftId: extension.work.draft.id,
    hearingId: base.hearingId, calendarDate: extension.calendar.day, calendar: { eventId: extension.calendar.eventId },
    otherMatterId: extension.foreignMatter.id, mfaEnrolled: true, provenance };
  const seedBytes = encoded(effectiveSeed);
  const plan = { schemaVersion: 1, dockerReceipt: refs.dockerReceipt, seed: { path: outputs.outputSeed, sha256: hash(seedBytes) },
    buildReceipt: refs.buildReceipt, publicCa: refs.publicCa, gatewayRoutes: refs.gatewayRoutes, ownerControls: owner,
    appId: QA_ID, binaryVersion: device.versionName, binaryBuild: String(device.versionCode),
    device: { deviceName: device.deviceName, platformVersion: device.platformVersion, udid: device.udid },
    androidTransport: { adbPort: device.adbPort, appiumUrl: device.appiumUrl, systemPort: device.systemPort,
      ...(request.androidTransportMode === 'usb-reverse' ? { transportMode: 'usb-reverse' } : {}) },
    auth: Object.fromEntries(Object.entries(auth).filter(([key]) => key !== 'firefoxUi')),
    firefoxRecipe: refs.firefoxRecipe, expectations, provenance, outputFixture: outputs.outputFixture };
  noSecrets(plan); noSecrets(effectiveSeed);
  return { plan, effectiveSeed, seedBytes, outputs };
}

export function prepareAndroidLocalRun(request) {
  const result = createAndroidLocalRun(request);
  for (const file of [result.outputs.outputSeed, result.outputs.outputPlan]) mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(result.outputs.outputSeed, result.seedBytes, { flag: 'wx', mode: 0o600 });
  const bytes = encoded(result.plan);
  writeFileSync(result.outputs.outputPlan, bytes, { flag: 'wx', mode: 0o600 });
  return { plan: { path: result.outputs.outputPlan, sha256: hash(bytes) }, seed: result.plan.seed,
    outputFixture: result.plan.outputFixture,
    environmentNamesRequired: ['emailEnv', 'passwordEnv', 'totpSecretEnv'].map((key) => result.plan.auth[key]),
    nativeExecution: 'not-run', credentialFilesRead: false, credentialValuesPrinted: false };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    assert.equal(process.argv.length, 3, 'Usage: node scripts/mobile/prepare-android-local-run.mjs /absolute/export-request.json');
    const input = process.argv[2];
    assert.ok(path.isAbsolute(input), 'ABSOLUTE_EXPORT_REQUEST_REQUIRED');
    assert.ok(!/(credential|secret)/i.test(path.basename(input)), 'CREDENTIAL_INPUT_FORBIDDEN');
    const bytes = readFileSync(input);
    assert.ok(bytes.length > 0 && bytes.length <= 1048576, 'BOUNDED_EXPORT_REQUEST_REQUIRED');
    console.log(JSON.stringify(prepareAndroidLocalRun(JSON.parse(bytes)), null, 2));
  } catch (error) {
    const message = error instanceof assert.AssertionError ? error.message.split('\n')[0] : '';
    console.error(JSON.stringify({ failed: 'prepare-android-local-run', code: error?.code || 'ANDROID_EXPORT_REFUSED',
      reason: /^[A-Z][A-Z0-9_]{2,100}$/.test(message) ? message : 'Local evidence preparation failed; inputs retained' }));
    process.exitCode = 1;
  }
}
