import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { OWNER_OPERATIONS, SEARCH_KINDS, validateBuildReceipt } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';
import { validateSessionDeletePolicy } from '../../apps/mobile/e2e/session-admission.mjs';

const REPO = fileURLToPath(new URL('../../', import.meta.url));
const QA_ID = 'ai.caseops.mobile.dev.simulatoracceptance';
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const encoded = (value) => `${JSON.stringify(value, null, 2)}\n`;
function reference(value) {
  assert.ok(value && path.isAbsolute(value.path || ''), 'ABSOLUTE_INPUT_REFERENCE_REQUIRED');
  assert.ok(!/(credential|secret|\.key$)/i.test(path.basename(value.path)), 'CREDENTIAL_OR_KEY_INPUT_FORBIDDEN');
  return { path: value.path, sha256: value.sha256 };
}
function read(value) {
  const ref = reference(value);
  return JSON.parse(verifiedFile(ref.path, ref.sha256));
}
function nonempty(value, code) { assert.ok(typeof value === 'string' && value.trim() && value.length <= 4000, code); }
function noSecrets(value) {
  if (!value || typeof value !== 'object') return;
  for (const [key, item] of Object.entries(value)) {
    assert.ok(!/^(password|access_token|refresh_token|totp_secret|code_verifier|cookies|private_key)$/i.test(key), 'EMBEDDED_SECRET_FORBIDDEN');
    noSecrets(item);
  }
}
function outside(file) {
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_OUTPUT_REQUIRED');
  let ancestor = path.dirname(file);
  while (!existsSync(ancestor)) ancestor = path.dirname(ancestor);
  const resolved = path.resolve(realpathSync(ancestor), path.relative(ancestor, file));
  const relative = path.relative(realpathSync(REPO), resolved);
  assert.ok(relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative), 'OUTPUT_MUST_STAY_OUTSIDE_REPOSITORY');
  assert.ok(!existsSync(file), 'OUTPUT_ALREADY_EXISTS');
  return file;
}
function requireIdentity(left, right, keys, code) {
  for (const key of keys) assert.equal(left?.[key], right?.[key], code);
}
function applyLabels(expectations, observation, extension, device) {
  assert.equal(observation.schemaVersion, 1, 'LABEL_OBSERVATION_VERSION_REQUIRED');
  assert.equal(observation.observed, true, 'ACTUAL_LABEL_OBSERVATION_REQUIRED');
  assert.equal(observation.platform, 'ios', 'IOS_LABEL_OBSERVATION_REQUIRED');
  assert.equal(observation.udid, device.udid, 'LABEL_DEVICE_MISMATCH');
  assert.equal(observation.locale, extension.locale, 'LABEL_LOCALE_MISMATCH');
  const allowed = {
    today: ['dateLabel', 'metaLabel'], 'work.task': ['metaLabel'],
    'work.draft': ['statusLabel', 'revisionLabel', 'verifiedCitationCountLabel', 'metaLabel'],
    calendar: ['dayLabel', 'metaLabel', 'nextHearingLabel'],
  };
  for (const [section, labels] of Object.entries(observation.labels || {})) {
    assert.ok(allowed[section], 'LABEL_OVERRIDE_SECTION_FORBIDDEN');
    const target = section.split('.').reduce((value, key) => value[key], expectations);
    for (const [key, value] of Object.entries(labels)) {
      assert.ok(allowed[section].includes(key), 'SOURCE_IDENTITY_OR_CONTENT_OVERRIDE_FORBIDDEN');
      nonempty(value, 'OBSERVED_LABEL_REQUIRED'); target[key] = value;
    }
  }
}

// Pure local evidence projection: no Docker, browser, credentials or mutation calls.
export function createIosLocalRun(request) {
  noSecrets(request);
  assert.equal(request.schemaVersion, 1, 'IOS_EXPORT_REQUEST_VERSION_REQUIRED');
  const refs = Object.fromEntries(['dockerReceipt', 'baseSeed', 'extensionSeed', 'buildReceipt', 'publicCa',
    'ownerControls', 'ownerBinding', 'gatewayRoutes', 'deviceInventory', 'runtimeInventory', 'bundleMetadata', 'authObservation']
    .map((key) => [key, reference(request[key])]));
  const receipt = read(refs.dockerReceipt), base = read(refs.baseSeed), extension = read(refs.extensionSeed);
  const build = read(refs.buildReceipt), owner = read(refs.ownerControls), binding = read(refs.ownerBinding);
  const devices = read(refs.deviceInventory), runtimes = read(refs.runtimeInventory);
  const metadata = read(refs.bundleMetadata), authObservation = read(refs.authObservation);
  for (const value of [receipt, base, extension, binding]) {
    assert.equal(value.environment, 'docker-integration', 'REAL_DOCKER_EVIDENCE_REQUIRED');
    assert.equal(value.syntheticDataOnly, true, 'SYNTHETIC_EVIDENCE_REQUIRED');
  }
  assert.equal(receipt.platform, 'ios', 'IOS_DOCKER_RECEIPT_REQUIRED');
  assert.equal(extension.platform, 'ios', 'IOS_EXTENSION_REQUIRED');
  assert.equal(extension.coreInventory, 'native-core-2026-10-25', 'DATED_EXTENSION_REQUIRED');
  assert.equal(extension.baseSeed?.sha256, refs.baseSeed.sha256, 'EXTENSION_BASE_SEED_HASH_MISMATCH');
  assert.equal(path.basename(refs.baseSeed.path), extension.baseSeed?.file, 'EXTENSION_BASE_SEED_FILE_MISMATCH');
  assert.equal(extension.companyId, base.companyId, 'EXTENSION_COMPANY_MISMATCH');
  assert.notEqual(extension.membershipId, base.membershipId, 'EXTENDED_MEMBER_REQUIRED');
  assert.equal(extension.ownerMembershipId, base.membershipId, 'EXTENSION_OWNER_MISMATCH');
  assert.equal(extension.destructiveControlsExecuted, false, 'FRESH_EXTENSION_REQUIRED');
  assert.equal(extension.nativeBrowserCookiesOrTokensPrepared, false, 'NATIVE_CREDENTIAL_INJECTION_FORBIDDEN');
  requireIdentity(extension.matter, base.matter, ['id', 'identityLabel', 'search'], 'EXTENSION_PRIMARY_MATTER_MISMATCH');
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
  assert.equal(extension.servingBuild?.release_sha, receipt.backendSha, 'EXTENSION_SERVING_SHA_MISMATCH');
  assert.equal(extension.servingBuild?.revision, receipt.backendRevision, 'EXTENSION_SERVING_REVISION_MISMATCH');
  for (const scope of ['api', 'web']) assert.equal(receipt.source?.[scope]?.dirty, false, 'CLEAN_SERVING_INPUTS_REQUIRED');
  assert.equal(build.platform, 'ios', 'IOS_BUILD_REQUIRED');
  assert.equal(build.profile, 'ios-simulator-acceptance', 'STANDALONE_IOS_BUILD_REQUIRED');
  assert.equal(build.appId, QA_ID, 'QA_IOS_ID_REQUIRED');
  assert.equal(build.sourceSha, receipt.backendSha, 'APP_API_SOURCE_MISMATCH');
  assert.equal(build.sourceSha, receipt.webSha, 'APP_WEB_SOURCE_MISMATCH');
  assert.equal(build.apiOrigin, receipt.apiOrigin, 'APP_API_ORIGIN_MISMATCH');
  assert.equal(build.webOrigin, receipt.webOrigin, 'APP_WEB_ORIGIN_MISMATCH');
  assert.equal(build.devEnabled, false, 'BUNDLED_STANDALONE_BUILD_REQUIRED');
  assert.equal(build.automatedTest, true, 'BUILD_MARKER_REQUIRED');
  assert.equal(binaryHash(build.artifact), build.binaryHash, 'ACTUAL_APP_BINARY_HASH_MISMATCH');
  validateBuildReceipt({ appId: QA_ID, environment: 'docker-integration', syntheticDataOnly: true,
    coreInventory: 'native-core-2026-10-25', buildReceipt: refs.buildReceipt,
    binarySourceSha: build.sourceSha, binarySourceFingerprint: build.sourceFingerprint,
    apiOrigin: build.apiOrigin, auth: { webOrigin: build.webOrigin }, appPath: build.artifact }, 'ios', build.binaryHash);
  assert.equal(metadata.CFBundleIdentifier, QA_ID, 'BUNDLE_METADATA_ID_MISMATCH');
  for (const key of ['CFBundleShortVersionString', 'CFBundleVersion']) nonempty(metadata[key], 'ACTUAL_BUNDLE_VERSION_REQUIRED');
  assert.equal(binding.extensionFile, path.basename(refs.extensionSeed.path), 'OWNER_EXTENSION_FILE_MISMATCH');
  assert.equal(binding.extensionSha256, refs.extensionSeed.sha256, 'OWNER_EXTENSION_HASH_MISMATCH');
  requireIdentity(binding, receipt, ['project', 'backendSha', 'backendRevision'], 'OWNER_BACKEND_MISMATCH');
  assert.equal(binding.destructiveControlsExecuted, false, 'FRESH_OWNER_BINDING_REQUIRED');
  assert.equal(binding.modulePath, owner.modulePath, 'OWNER_MODULE_MISMATCH');
  assert.equal(binding.moduleSha256, owner.sha256, 'OWNER_MODULE_HASH_MISMATCH');
  verifiedFile(owner.modulePath, owner.sha256);
  verifiedFile(binding.pythonPath, binding.pythonSha256);
  assert.deepEqual([...owner.capabilities].sort(), [...OWNER_OPERATIONS].sort(), 'ALL_OWNER_CAPABILITIES_REQUIRED');
  assert.deepEqual([...binding.capabilities].sort(), [...OWNER_OPERATIONS].sort(), 'OWNER_BINDING_CAPABILITIES_MISMATCH');
  const api = receipt.containers?.find(({ name }) => /-api-\d+$/.test(name));
  assert.equal(binding.apiContainerId, api?.id, 'OWNER_CONTAINER_MISMATCH');
  assert.equal(binding.apiImage, api?.image, 'OWNER_IMAGE_MISMATCH');
  assert.equal(validateSessionDeletePolicy(read(refs.gatewayRoutes), refs.gatewayRoutes, refs.dockerReceipt, receipt).mode,
    'dynamic', 'DYNAMIC_SESSION_POLICY_REQUIRED');
  verifiedFile(refs.publicCa.path, refs.publicCa.sha256);
  assert.equal(path.resolve(receipt.publicCA), path.resolve(refs.publicCa.path), 'FIXTURE_PUBLIC_CA_PATH_MISMATCH');
  const selected = Object.entries(devices.devices || {}).flatMap(([runtime, items]) => items
    .filter(({ udid }) => udid === request.udid).map((item) => ({ ...item, runtime })));
  assert.equal(selected.length, 1, 'EXACT_SIMULATOR_REQUIRED');
  const device = selected[0], runtime = runtimes.runtimes?.find(({ identifier }) => identifier === device.runtime);
  assert.equal(device.isAvailable, true, 'AVAILABLE_SIMULATOR_REQUIRED');
  assert.equal(device.state, 'Booted', 'BOOTED_SIMULATOR_REQUIRED');
  assert.equal(runtime?.isAvailable, true, 'AVAILABLE_RUNTIME_REQUIRED');
  assert.equal(runtime?.platform, 'iOS', 'IOS_RUNTIME_REQUIRED');
  const locale = read(extension.localeEvidence);
  assert.equal(locale.platform, 'ios', 'IOS_LOCALE_EVIDENCE_REQUIRED');
  assert.equal(locale.udid, request.udid, 'LOCALE_DEVICE_MISMATCH');
  assert.equal(locale.locale, extension.locale, 'EXTENSION_LOCALE_MISMATCH');
  assert.equal(authObservation.schemaVersion, 1, 'AUTH_OBSERVATION_VERSION_REQUIRED');
  assert.equal(authObservation.observed, true, 'ACTUAL_AUTH_OBSERVATION_REQUIRED');
  requireIdentity(authObservation, { platform: 'ios', udid: request.udid, mode: 'web-context',
    bundleId: QA_ID, webOrigin: receipt.webOrigin }, ['platform', 'udid', 'mode', 'bundleId', 'webOrigin'], 'AUTH_OBSERVATION_CONTEXT_MISMATCH');
  requireIdentity(authObservation, extension, ['membershipId', 'principalLabel'], 'AUTH_OBSERVATION_MEMBER_MISMATCH');
  assert.ok(['login', 'consent'].includes(authObservation.mfaStage), 'OBSERVED_MFA_STAGE_REQUIRED');
  assert.equal(typeof authObservation.iosConsent, 'boolean', 'EXPLICIT_OBSERVED_IOS_CONSENT_REQUIRED');
  assert.equal(extension.auth?.mode, 'web-context', 'IOS_BROWSER_MODE_REQUIRED');
  assert.equal(extension.auth?.mfaRequired, true, 'EXTENDED_MEMBER_MFA_REQUIRED');
  assert.equal(extension.auth?.webOrigin, receipt.webOrigin, 'EXTENSION_WEB_ORIGIN_MISMATCH');
  const expectations = Object.fromEntries(['matter', 'today', 'work', 'calendar', 'foreignMatter', 'lifecycleMatter', 'accessMatter']
    .map((key) => [key, structuredClone(extension[key])]));
  if (request.labelObservations) applyLabels(expectations, read(request.labelObservations), extension, device);
  const outputs = Object.fromEntries(['outputSeed', 'outputPlan', 'outputFixture'].map((key) => [key, outside(request[key])]));
  assert.equal(new Set(Object.values(outputs)).size, 3, 'DISTINCT_OUTPUT_PATHS_REQUIRED');
  const provenance = { baseSeed: refs.baseSeed, extensionSeed: refs.extensionSeed, localeEvidence: reference(extension.localeEvidence),
    ownerBinding: refs.ownerBinding, deviceInventory: refs.deviceInventory, runtimeInventory: refs.runtimeInventory,
    bundleMetadata: refs.bundleMetadata, authObservation: refs.authObservation,
    ...(request.labelObservations ? { labelObservations: reference(request.labelObservations) } : {}) };
  const effectiveSeed = { environment: 'docker-integration', syntheticDataOnly: true,
    principalLabel: extension.principalLabel, workspaceLabel: extension.workspaceLabel,
    companyId: extension.companyId, membershipId: extension.membershipId, userId: extension.userId,
    matter: structuredClone(extension.matter), taskId: extension.today.id, draftId: extension.work.draft.id,
    hearingId: base.hearingId, calendarDate: extension.calendar.day,
    calendar: { eventId: extension.calendar.eventId }, otherMatterId: extension.foreignMatter.id,
    mfaEnrolled: true, provenance };
  const seedBytes = encoded(effectiveSeed);
  const plan = { schemaVersion: 1, dockerReceipt: refs.dockerReceipt,
    seed: { path: outputs.outputSeed, sha256: hash(seedBytes) }, buildReceipt: refs.buildReceipt,
    publicCa: refs.publicCa, gatewayRoutes: refs.gatewayRoutes, ownerControls: owner,
    appId: QA_ID, binaryVersion: metadata.CFBundleShortVersionString, binaryBuild: metadata.CFBundleVersion,
    device: { deviceName: device.name, platformVersion: runtime.version, udid: device.udid },
    auth: { ...extension.auth, mfaStage: authObservation.mfaStage, iosConsent: authObservation.iosConsent },
    expectations, provenance, outputFixture: outputs.outputFixture };
  noSecrets(plan); noSecrets(effectiveSeed);
  return { plan, effectiveSeed, seedBytes, outputs };
}

export function prepareIosLocalRun(request) {
  const result = createIosLocalRun(request);
  for (const file of [result.outputs.outputSeed, result.outputs.outputPlan]) mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(result.outputs.outputSeed, result.seedBytes, { flag: 'wx', mode: 0o600 });
  const bytes = encoded(result.plan);
  writeFileSync(result.outputs.outputPlan, bytes, { flag: 'wx', mode: 0o600 });
  return { plan: { path: result.outputs.outputPlan, sha256: hash(bytes) }, seed: result.plan.seed,
    outputFixture: result.plan.outputFixture, environmentNamesRequired: ['emailEnv', 'passwordEnv', 'totpSecretEnv'].map((key) => result.plan.auth[key]),
    nativeExecution: 'not-run', credentialFilesRead: false, credentialValuesPrinted: false };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    assert.equal(process.argv.length, 3, 'Usage: node scripts/mobile/prepare-ios-local-run.mjs /absolute/export-request.json');
    const input = process.argv[2];
    assert.ok(path.isAbsolute(input), 'ABSOLUTE_EXPORT_REQUEST_REQUIRED');
    assert.ok(!/(credential|secret)/i.test(path.basename(input)), 'CREDENTIAL_INPUT_FORBIDDEN');
    const bytes = readFileSync(input);
    assert.ok(bytes.length > 0 && bytes.length <= 1048576, 'BOUNDED_EXPORT_REQUEST_REQUIRED');
    console.log(JSON.stringify(prepareIosLocalRun(JSON.parse(bytes)), null, 2));
  } catch (error) {
    console.error(JSON.stringify({ failed: 'prepare-ios-local-run', code: error?.code || 'IOS_EXPORT_REFUSED',
      reason: error instanceof assert.AssertionError ? error.message.split('\n')[0] : 'Local evidence preparation failed; inputs retained' }));
    process.exitCode = 1;
  }
}
