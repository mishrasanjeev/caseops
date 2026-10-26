import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createAndroidLocalRun, prepareAndroidLocalRun } from './prepare-android-local-run.mjs';
import { androidSessionTransport, inspectLocalPlan, verifyAndroidSessionTransport } from '../../apps/mobile/e2e/local-run.mjs';

const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
const reference = (file) => ({ path: file, sha256: hash(readFileSync(file)) });
const APP = 'ai.caseops.mobile.dev.localacceptance', SERIAL = 'emulator-5584';
const OPERATIONS = ['disposeMatter', 'readMatterState', 'revokeMatterAccess', 'readNoteState'];
// Every service, artifact, observation and signature below is explicitly an
// offline synthetic fixture. No tool, VM, TLS connection or auth is executed.
function fixture(t, stage = 'consent') {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-android-export-unit-')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const save = (name, value) => {
    const file = path.join(root, name);
    writeFileSync(file, typeof value === 'string' ? value : `${JSON.stringify(value, null, 2)}\n`);
    return reference(file);
  };
  const gateway = fileURLToPath(new URL('./local-gateway.py', import.meta.url)), gatewaySha = hash(readFileSync(gateway));
  const modulePath = fileURLToPath(new URL('./local-owner-controls.mjs', import.meta.url));
  const pythonPath = fileURLToPath(new URL('./local-owner.py', import.meta.url));
  const localeEvidence = save('device-locale-unit.json', { platform: 'android', udid: SERIAL, locale: 'en-US' });
  const base = { environment: 'docker-integration', syntheticDataOnly: true, companyId: 'company', membershipId: 'owner',
    matter: { id: 'primary', identityLabel: 'MAT-001', search: 'MAT-001' }, calendarDate: '2026-10-25',
    taskId: 'owner-task', draftId: 'draft', hearingId: 'hearing-pk', otherMatterId: 'foreign' };
  const baseSeed = save('seed.json', base);
  const matter = { ...base.matter, title: 'Synthetic primary', searches: ['matter_code', 'case_number', 'filing_number', 'cnr_number', 'temporary_e_case_number']
    .map((kind, index) => ({ kind, value: index === 0 ? 'MAT-001' : `identifier-${index}` })) };
  const task = { id: 'member-task', kind: 'task', title: 'Synthetic member task', metaLabel: 'task · Sun, Oct 25, 2026 · open · high', matter };
  const extension = { environment: 'docker-integration', syntheticDataOnly: true, coreInventory: 'native-core-2026-10-25', platform: 'android',
    baseSeed: { file: 'seed.json', sha256: baseSeed.sha256 }, companyId: 'company', membershipId: 'member', ownerMembershipId: 'owner',
    principalLabel: 'Synthetic Member', workspaceLabel: 'Synthetic Workspace', userId: 'member-user',
    servingBuild: { release_sha: 'a'.repeat(40), revision: 'api-revision' }, matter,
    today: { ...task, dueOn: '2026-10-25', dateLabel: 'Sun, Oct 25, 2026', status: 'open' },
    work: { task, draft: { id: 'draft', kind: 'draft', title: 'Synthetic draft', matter, entry: 'matter-work',
      statusLabel: 'draft · Read-only', revisionLabel: 'Revision 1 · version-id', body: 'Synthetic draft body', citations: [],
      verifiedCitationCountLabel: '0 server-marked verified citations. This is not certification of legal accuracy.' } },
    calendar: { eventId: 'opaque:calendar.event-42', day: '2026-10-25', dayLabel: 'Sun, Oct 25, 2026', title: 'Synthetic hearing',
      metaLabel: 'Sun, Oct 25, 2026 · hearing', nextHearingLabel: 'Sun, Oct 25, 2026', matter },
    foreignMatter: { id: 'foreign', identityLabel: 'FOREIGN', title: 'Synthetic foreign', search: 'foreign-lookup' },
    lifecycleMatter: { id: 'lifecycle', identityLabel: 'LIFECYCLE', title: 'Synthetic lifecycle', search: 'lifecycle-lookup' },
    accessMatter: { id: 'access', identityLabel: 'ACCESS', title: 'Synthetic access', search: 'access-lookup' },
    auth: { mode: 'native-firefox', webOrigin: 'https://10.0.2.2:3443', companySlug: 'test-legal', mfaRequired: true,
      emailEnv: 'CASEOPS_MOBILE_CORE_EMAIL', passwordEnv: 'CASEOPS_MOBILE_CORE_PASSWORD', totpSecretEnv: 'CASEOPS_MOBILE_CORE_TOTP_SECRET' },
    locale: 'en-US', localeEvidence, credentialsFile: 'credentials-file-must-never-be-opened.json',
    destructiveControlsExecuted: false, nativeBrowserCookiesOrTokensPrepared: false };
  const extensionSeed = save('extended-seed-012345abcdef.json', extension);
  const ca = save('public-ca.crt', 'Synthetic public CA bytes; no TLS execution.');
  const receipt = { environment: 'docker-integration', syntheticDataOnly: true, platform: 'android', project: 'unit-project',
    backendSha: 'a'.repeat(40), backendRevision: 'api-revision', webSha: 'a'.repeat(40), webRevision: 'web-revision',
    webIdentity: { service: 'web', release_sha: 'a'.repeat(40), revision: 'web-revision' },
    gatewayUrl: 'https://127.0.0.1:9443', webGatewayUrl: 'https://127.0.0.1:4443', gatewayRunId: 'unit-run',
    apiOrigin: 'https://10.0.2.2:8443', webOrigin: 'https://10.0.2.2:3443', publicCA: ca.path,
    source: { api: { dirty: false, head: 'a'.repeat(40) }, web: { dirty: false, head: 'a'.repeat(40) } },
    productionAccessed: false, metroLaunched: false, webAcceptanceMarkerBuild: true, webMarkerTransportSourcePresent: true,
    gatewayImplementationSha256: gatewaySha,
    containers: ['api', 'web', 'postgres'].map((service) => ({ id: `${service}-container`, name: `/unit-project-${service}-1`,
      project: 'unit-project', image: `sha256:${'b'.repeat(64)}`, networks: ['unit-project_default'] })) };
  const dockerReceipt = save('receipt-immutable.json', receipt);
  const owner = { modulePath, sha256: hash(readFileSync(modulePath)), capabilities: OPERATIONS };
  const binding = { environment: 'docker-integration', syntheticDataOnly: true, project: receipt.project,
    backendSha: receipt.backendSha, backendRevision: receipt.backendRevision, apiContainerId: 'api-container',
    apiImage: `sha256:${'b'.repeat(64)}`, extensionFile: path.basename(extensionSeed.path), extensionSha256: extensionSeed.sha256,
    modulePath, moduleSha256: owner.sha256, pythonPath, pythonSha256: hash(readFileSync(pythonPath)),
    capabilities: OPERATIONS, destructiveControlsExecuted: false };
  const before = { runId: 'unit-run', implementationSha256: gatewaySha, markerRejected: 0, routeRejected: 0,
    overflow: false, lastSequence: 0, requests: [], sessionDeleteAdmissions: [] };
  const gatewayBefore = save('gateway-before.json', before);
  const gatewayRoutes = save('gateway-descriptor.json', { schemaVersion: 2, routes: ['GET /api/auth/native/sessions'], dynamicAdmissions: {
    nativeCurrentSessionDelete: { kind: 'native-current-session-delete-v1', sourceRoute: 'GET /api/auth/native/sessions',
      sourceListLimit: 50, maxLiveIds: 1, maxAdmissionEvents: 64, nativeBearerOnly: true, cookiesAllowed: false,
      currentOnly: true, unrevokedOnly: true, consumeOnAttempt: true,
      requestEvidenceLink: 'sessionDeleteAdmissions[].sourceRequestId -> requests[].requestId', liveExecutionProofRequiredAt: 'NATIVE-20',
      gatewayRunId: 'unit-run', implementationSha256: gatewaySha, implementationEvidence: reference(gateway),
      isolationEvidence: dockerReceipt, statusEvidence: gatewayBefore } } });
  const artifact = save('synthetic-caseops.apk', 'Explicit synthetic APK bytes; no native execution.');
  const inputs = ['build.gradle', 'settings.gradle', 'gradle.properties', 'app/build.gradle', 'gradle/wrapper/gradle-wrapper.properties']
    .map(relativePath => { const data = `synthetic generated input ${relativePath}\n`; save(relativePath.replaceAll('/', '-'), data);
      return { relativePath, sha256: hash(data), sizeBytes: Buffer.byteLength(data) }; });
  const proof = { schemaVersion: 1, kind: 'android-local-arm64-signature-proof', appId: APP, artifactSha256: artifact.sha256,
    versionCode: 7, versionName: '0.1.0-unit', architecture: 'arm64-v8a', signatureVerified: true, signatureSchemeV2: true,
    certificateSha256: '3'.repeat(64), intendedDeviceSerial: SERIAL, distributionSigning: false, nativeExecution: 'not-run-by-build-wrapper',
    evidence: [save('apk-badging.log', `package: name='${APP}' versionCode='7' versionName='0.1.0-unit'\nnative-code: 'arm64-v8a'\n`),
      save('apk-signing.log', `Verifies\nVerified using v2 scheme (APK Signature Scheme v2): true\nNumber of signers: 1\nV2 Signer: certificate SHA-256 digest: ${'3'.repeat(64)}\n`),
      save('apk-abi.json', { schemaVersion: 1, abis: ['arm64-v8a'], nativeLibraryCount: 4, elfClass: 64, elfMachine: 183 }),
      save('generated-android-inputs.json', { schemaVersion: 1, files: inputs }),
      save('java21.log', 'Temurin-21.0.12.1+1 explicit synthetic fixture'), save('java17.log', 'Temurin-17.0.20.1+1 explicit synthetic fixture')] };
  const build = { platform: 'android', profile: 'android-local-acceptance', appId: APP, sourceSha: receipt.backendSha,
    sourceFingerprint: 'c'.repeat(64), sourceDirty: false, devEnabled: false, automatedTest: true,
    apiOrigin: receipt.apiOrigin, webOrigin: receipt.webOrigin, artifact: artifact.path, binaryHash: artifact.sha256,
    publicCaSha256: ca.sha256, androidSecurity: { kind: 'compiled-android-acceptance-security', apkSha256: artifact.sha256,
      publicCaSha256: ca.sha256, nativeArtifactEvidence: save('android-native-proof.json', proof) } };
  const buildReceipt = save('build-receipt.json', build);
  const deviceObservation = save('device-observation.json', { schemaVersion: 1, kind: 'observed-android-local-device', observed: true,
    platform: 'android', udid: SERIAL, state: 'device', bootCompleted: true, deviceName: 'Explicit synthetic unit model',
    platformVersion: '16.2', apiLevel: 36, architecture: 'arm64-v8a', appId: APP, versionName: '0.1.0-unit', versionCode: 7,
    installedApkSha256: artifact.sha256, buildReceipt, adbPort: 5038, appiumUrl: 'http://127.0.0.1:4725', systemPort: 8202,
    evidence: [save('explicit-synthetic-device-command-evidence.log', 'Offline unit fixture only; this is not an actual Android observation.')] });
  const locators = Object.fromEntries(['urlOpen', 'urlValue', 'companySlug', 'email', 'password', 'submit', 'principal', 'emailFact',
    'workspace', 'connect', 'urlClose'].map(key => [key, { kind: 'id', value: `synthetic-${key}` }]));
  Object.assign(locators, { appOpen: { kind: 'id', value: 'native-app-open' }, mfaCode: { kind: 'id', value: 'native-mfa-code' },
    mfaSubmit: { kind: 'buttonText', value: 'Verify code' }, mfaVerified: { kind: 'text', value: 'Code verified. Select Connect app to continue.' } });
  const locatorsRef = save('firefox-locators.json', { kind: 'observed-native-firefox-locators', observed: true, platform: 'android',
    udid: SERIAL, appId: APP, buildReceipt, publicCa: ca, packageName: 'org.mozilla.firefox', version: '158.0.2', locators, prepare: [], afterConnect: [] });
  const firefoxRecipe = save('firefox-recipe.json', { status: 'complete', packageName: 'org.mozilla.firefox', version: '158.0.2',
    signerSha256: 'A78B62A5165B4494B2FEAD9E76A280D22D937FEE6251AECE599446B2EA319B04', caTrustedThroughSettings: true,
    locators, locatorEvidencePath: locatorsRef.path, locatorEvidenceSha256: locatorsRef.sha256, prepare: [], afterConnect: [] });
  const rows = [['POST', '/api/auth/login', 200], ...(stage === 'consent' ? [['POST', '/api/auth/native/authorize', 403]] : []),
    ['POST', '/api/auth/mfa/step-up', 200], ['GET', '/api/auth/me', 200], ['POST', '/api/auth/native/authorize', 200],
    ['POST', '/api/auth/native/token', 200], ['POST', '/api/auth/native/logout', 204]];
  const after = { ...before, lastSequence: rows.length, requests: rows.map(([method, route, status], index) => ({ sequence: index + 1,
    requestId: (index + 1).toString(16).padStart(16, '0'), method, route, status, nativeMarker: true, browserHandoff: true })) };
  const gatewayAfter = save('gateway-after.json', after);
  const authObservation = save('auth-observation.json', { schemaVersion: 1, observed: true, platform: 'android', udid: SERIAL,
    mode: 'native-firefox', appId: APP, webOrigin: receipt.webOrigin, companyId: 'company', membershipId: 'member',
    principalLabel: 'Synthetic Member', workspaceLabel: 'Synthetic Workspace', mfaStage: stage,
    dockerReceipt, buildReceipt, extensionSeed, deviceObservation, firefoxRecipe, gatewayBefore, gatewayAfter,
    pkceUnchanged: true, nativePrincipalVerified: true, nativeWorkspaceVerified: true, logoutAcknowledged: true, signedOutAfter: true, sessionClosed: true });
  const request = { schemaVersion: 1, dockerReceipt, baseSeed, extensionSeed, buildReceipt, publicCa: ca, gatewayRoutes,
    ownerControls: save('owner-controls.json', owner), ownerBinding: save('owner-binding.json', binding),
    deviceObservation, firefoxRecipe, authObservation, udid: SERIAL,
    outputSeed: path.join(root, 'effective-seed.json'), outputPlan: path.join(root, 'plan.json'), outputFixture: path.join(root, 'fixture.json') };
  const replace = (key, edit) => { const value = JSON.parse(readFileSync(request[key].path)); edit(value); request[key] = save(path.basename(request[key].path), value); };
  const rebindAuth = () => replace('authObservation', value => {
    for (const key of ['dockerReceipt', 'buildReceipt', 'extensionSeed', 'deviceObservation', 'firefoxRecipe']) value[key] = request[key];
  });
  return { request, root, replace, save, rebindAuth, extension, after, before, build, proof };
}

test('both observed MFA stages produce plans accepted by the unchanged real consumer for all 23 Android cases', (t) => {
  for (const stage of ['login', 'consent']) {
    const f = fixture(t, stage), result = prepareAndroidLocalRun(f.request);
    const plan = JSON.parse(readFileSync(result.plan.path)), seed = JSON.parse(readFileSync(result.seed.path));
    assert.equal(seed.membershipId, 'member'); assert.equal(seed.taskId, 'member-task');
    assert.equal(seed.calendar.eventId, 'opaque:calendar.event-42'); assert.equal(seed.hearingId, 'hearing-pk');
    assert.deepEqual(seed.provenance.baseSeed, f.request.baseSeed); assert.deepEqual(seed.provenance.extensionSeed, f.request.extensionSeed);
    assert.deepEqual(plan.device, { deviceName: 'Explicit synthetic unit model', platformVersion: '16.2', udid: SERIAL });
    assert.equal(plan.binaryBuild, '7'); assert.equal(plan.auth.mfaStage, stage);
    assert.deepEqual(plan.androidTransport, { adbPort: 5038, appiumUrl: 'http://127.0.0.1:4725', systemPort: 8202 });
    assert.equal(existsSync(path.join(f.root, f.extension.credentialsFile)), false);
    const env = { CASEOPS_MOBILE_CORE_EMAIL: 'unit@example.test', CASEOPS_MOBILE_CORE_PASSWORD: 'synthetic-unit-only',
      CASEOPS_MOBILE_CORE_TOTP_SECRET: 'JBSWY3DPEHPK3PXP' };
    const inspected = inspectLocalPlan(plan, 'android', env);
    assert.deepEqual(inspected.readiness.blockers, []); assert.equal(inspected.readiness.intended.length, 23);
    assert.deepEqual(inspected.fixture.androidTransport, plan.androidTransport);
    const session = androidSessionTransport(inspected.fixture, 'android', { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5038' });
    assert.equal(session.appiumUrl.port, '4725');
    assert.deepEqual(session.capabilities, { 'appium:adbPort': 5038, 'appium:systemPort': 8202 });
    const observed = verifyAndroidSessionTransport(inspected.fixture, 'android', { platformName: 'Android',
      automationName: 'UiAutomator2', udid: SERIAL, appPackage: APP, platformVersion: '16.2', adbPort: 5038, systemPort: 8202 });
    assert.equal(observed.source, 'new-session-response');
    assert.equal(result.credentialFilesRead, false); assert.equal(result.credentialValuesPrinted, false); assert.equal(result.nativeExecution, 'not-run');
  }
});

test('pure projection is deterministic and exclusive outputs preserve existing evidence', (t) => {
  const f = fixture(t); assert.deepEqual(createAndroidLocalRun(f.request), createAndroidLocalRun(f.request));
  prepareAndroidLocalRun(f.request); const before = readFileSync(f.request.outputSeed);
  assert.throws(() => prepareAndroidLocalRun(f.request), /OUTPUT_ALREADY_EXISTS/);
  assert.deepEqual(readFileSync(f.request.outputSeed), before);
});

test('missing actual observations refuse without creating a plan, seed or fixture', (t) => {
  for (const field of ['deviceObservation', 'firefoxRecipe', 'authObservation']) {
    const f = fixture(t); delete f.request[field];
    assert.throws(() => prepareAndroidLocalRun(f.request), /ABSOLUTE_INPUT_REFERENCE_REQUIRED/);
    for (const key of ['outputSeed', 'outputPlan', 'outputFixture']) assert.equal(existsSync(f.request[key]), false);
  }
});

test('fresh extended member, exact base provenance, opaque event and owner binding are mandatory', (t) => {
  for (const [field, edit, expected] of [
    ['baseSeed', value => { value.taskId = 'new-owner-task'; }, /EXTENSION_BASE_SEED_HASH_MISMATCH/],
    ['extensionSeed', value => { value.membershipId = 'owner'; }, /EXTENDED_MEMBER_REQUIRED/],
    ['extensionSeed', value => { value.today.id = 'owner-task'; value.work.task.id = 'owner-task'; }, /EXTENDED_MEMBER_TASK_REQUIRED/],
    ['extensionSeed', value => { delete value.calendar.eventId; }, /ACTUAL_CALENDAR_EVENT_ID_REQUIRED/],
    ['extensionSeed', value => { value.destructiveControlsExecuted = true; }, /FRESH_EXTENSION_REQUIRED/],
    ['extensionSeed', value => { value.nativeBrowserCookiesOrTokensPrepared = true; }, /NATIVE_CREDENTIAL_INJECTION_FORBIDDEN/],
    ['ownerBinding', value => { value.extensionSha256 = 'd'.repeat(64); }, /OWNER_EXTENSION_HASH_MISMATCH/],
    ['ownerBinding', value => { value.apiContainerId = 'another-api'; }, /OWNER_CONTAINER_MISMATCH/],
  ]) { const f = fixture(t); f.replace(field, edit); assert.throws(() => createAndroidLocalRun(f.request), expected); }
});

test('API, web and app must share the exact clean source and observed serving revision', (t) => {
  for (const [field, edit, expected] of [
    ['dockerReceipt', value => { value.source.api.dirty = true; }, /CLEAN_SERVING_INPUTS_REQUIRED/],
    ['dockerReceipt', value => { value.source.web.head = 'b'.repeat(40); }, /SERVING_SOURCE_HEAD_MISMATCH/],
    ['dockerReceipt', value => { value.webIdentity.release_sha = 'b'.repeat(40); }, /WEB_IDENTITY_SOURCE_MISMATCH/],
    ['extensionSeed', value => { value.servingBuild.revision = 'old-revision'; }, /EXTENSION_SERVING_REVISION_MISMATCH/],
    ['buildReceipt', value => { value.sourceDirty = true; }, /CLEAN_APP_INPUTS_REQUIRED/],
    ['buildReceipt', value => { value.sourceSha = 'b'.repeat(40); }, /APP_API_SOURCE_MISMATCH/],
    ['buildReceipt', value => { value.webOrigin = 'https://10.0.2.2:5443'; }, /APP_FIXTURE_ORIGIN_MISMATCH/],
  ]) { const f = fixture(t); f.replace(field, edit); assert.throws(() => createAndroidLocalRun(f.request), expected); }
});

test('changed APK or CA bytes and unsigned historical receipts cannot be exported as Mac native proof', (t) => {
  for (const kind of ['apk', 'ca', 'unsigned', 'v2false']) {
    const f = fixture(t);
    if (kind === 'apk') writeFileSync(f.build.artifact, 'changed artifact');
    if (kind === 'ca') writeFileSync(f.request.publicCa.path, 'changed CA');
    if (kind === 'unsigned') f.replace('buildReceipt', value => { delete value.androidSecurity.nativeArtifactEvidence; });
    if (kind === 'v2false') { f.proof.signatureSchemeV2 = false; f.save('android-native-proof.json', f.proof); }
    assert.throws(() => createAndroidLocalRun(f.request), /ACTUAL_APP_BINARY_HASH_MISMATCH|FIXTURE_EVIDENCE_CHANGED|MAC_ANDROID_NATIVE_PROOF_REQUIRED/);
  }
});

test('actual selected device, OS, installed version and all isolated transport observations are required', (t) => {
  for (const [key, value, expected] of [
    ['udid', 'emulator-5554', /ACTUAL_READY_ANDROID_DEVICE_REQUIRED/], ['observed', false, /ACTUAL_READY_ANDROID_DEVICE_REQUIRED/],
    ['bootCompleted', false, /ACTUAL_READY_ANDROID_DEVICE_REQUIRED/], ['architecture', 'x86_64', /ACTUAL_READY_ANDROID_DEVICE_REQUIRED/],
    ['platformVersion', '', /OBSERVED_ANDROID_OS_VERSION_REQUIRED/], ['installedApkSha256', 'd'.repeat(64), /OBSERVED_INSTALLED_APK_MISMATCH/],
    ['versionCode', 8, /INSTALLED_ANDROID_VERSION_MISMATCH/], ['adbPort', 5037, /ISOLATED_ANDROID_TRANSPORT_REQUIRED/],
    ['systemPort', 8200, /ISOLATED_ANDROID_TRANSPORT_REQUIRED/], ['appiumUrl', 'http://127.0.0.1:4723', /ISOLATED_ANDROID_TRANSPORT_REQUIRED/],
    ['evidence', [], /ACTUAL_ANDROID_DEVICE_EVIDENCE_REQUIRED/],
  ]) { const f = fixture(t); f.replace('deviceObservation', observation => { observation[key] = value; });
    assert.throws(() => createAndroidLocalRun(f.request), expected); }
});

test('wrong member, old extension/build observation and incomplete normal authentication reject', (t) => {
  for (const [edit, expected] of [
    [value => { value.membershipId = 'owner'; }, /AUTH_OBSERVATION_MEMBER_MISMATCH/],
    [value => { value.workspaceLabel = 'Other workspace'; }, /AUTH_OBSERVATION_MEMBER_MISMATCH/],
    [value => { value.extensionSeed.sha256 = 'd'.repeat(64); }, /AUTH_OBSERVATION_PROVENANCE_MISMATCH/],
    [value => { value.deviceObservation.sha256 = 'd'.repeat(64); }, /AUTH_OBSERVATION_PROVENANCE_MISMATCH/],
    [value => { value.mfaStage = 'guessed'; }, /OBSERVED_MFA_STAGE_REQUIRED/],
    [value => { value.pkceUnchanged = false; }, /COMPLETE_NORMAL_AUTH_OBSERVATION_REQUIRED/],
    [value => { value.sessionClosed = false; }, /COMPLETE_NORMAL_AUTH_OBSERVATION_REQUIRED/],
  ]) { const f = fixture(t); f.replace('authObservation', edit); assert.throws(() => createAndroidLocalRun(f.request), expected); }
});

test('browser recipe binds actual Firefox version, signer, normal CA trust and selected device locators', (t) => {
  for (const [edit, expected] of [
    [value => { value.version = '157.0'; }, /REVIEWED_FIREFOX_VERSION_REQUIRED/],
    [value => { value.caTrustedThroughSettings = false; }, /NORMAL_FIREFOX_CA_TRUST_REQUIRED/],
    [value => { value.signerSha256 = 'd'.repeat(64); }, /REVIEWED_FIREFOX_SIGNER_REQUIRED/],
    [value => { value.status = 'pending'; }, /FIREFOX_RECIPE_INCOMPLETE/],
  ]) { const f = fixture(t); f.replace('firefoxRecipe', edit); f.rebindAuth();
    assert.throws(() => createAndroidLocalRun(f.request), expected); }
  const f = fixture(t), recipe = JSON.parse(readFileSync(f.request.firefoxRecipe.path));
  const observed = JSON.parse(readFileSync(recipe.locatorEvidencePath)); observed.udid = 'emulator-5554';
  const ref = f.save('firefox-locators.json', observed);
  f.replace('firefoxRecipe', value => { value.locatorEvidenceSha256 = ref.sha256; }); f.rebindAuth();
  assert.throws(() => createAndroidLocalRun(f.request), /FIREFOX_LOCATOR_DEVICE_MISMATCH/);
  observed.udid = SERIAL; observed.publicCa.sha256 = 'd'.repeat(64);
  const wrongCa = f.save('firefox-locators.json', observed);
  f.replace('firefoxRecipe', value => { value.locatorEvidenceSha256 = wrongCa.sha256; }); f.rebindAuth();
  assert.throws(() => createAndroidLocalRun(f.request), /FIREFOX_CA_OBSERVATION_MISMATCH/);
});

test('real authorization sequence refuses absent MFA, duplicated grant, logout uncertainty and unexpected mutations', (t) => {
  for (const kind of ['no-mfa', 'duplicate-grant', 'logout-failed', 'rejected-marker', 'foreign-run', 'unexpected-post']) {
    const f = fixture(t), after = structuredClone(f.after);
    if (kind === 'no-mfa') after.requests = after.requests.filter(row => row.route !== '/api/auth/mfa/step-up');
    if (kind === 'duplicate-grant') after.requests.splice(-1, 0, { ...after.requests.find(row => row.route === '/api/auth/native/authorize' && row.status === 200) });
    if (kind === 'logout-failed') after.requests.at(-1).status = 500;
    if (kind === 'rejected-marker') after.markerRejected = 1;
    if (kind === 'foreign-run') after.runId = 'another-run';
    if (kind === 'unexpected-post') after.requests.push({ method: 'POST', route: '/api/matters/primary/notes', status: 200, nativeMarker: true });
    after.requests.forEach((row, index) => { row.sequence = index + 1; }); after.lastSequence = after.requests.length;
    const ref = f.save('gateway-after.json', after);
    f.replace('authObservation', value => { value.gatewayAfter = ref; });
    assert.throws(() => createAndroidLocalRun(f.request), /CONSENT_MFA_VERIFICATION_NOT_ONCE|EXACT_BROWSER_AUTHORIZATION_SEQUENCE_REQUIRED|OBSERVED_AUTH_MUTATION_NOT_ONCE_ACKNOWLEDGED|NATIVE_OR_BROWSER_MARKER_MISSING|WRONG_GATEWAY_RUN|UNEXPECTED_AUTH_OBSERVATION_MUTATION/);
  }
});

test('observation ledgers preserve complete prior history and evidence is hash-checked again before export', (t) => {
  const f = fixture(t), oldRow = { sequence: 1, requestId: 'f'.repeat(16), method: 'GET', route: '/api/build',
    status: 200, nativeMarker: true, browserHandoff: false };
  const before = { ...f.before, lastSequence: 1, requests: [oldRow] };
  const after = { ...f.after, lastSequence: f.after.lastSequence + 1, requests: [oldRow,
    ...f.after.requests.map(row => ({ ...row, sequence: row.sequence + 1 }))] };
  const beforeRef = f.save('gateway-before-observation.json', before), afterRef = f.save('gateway-after-observation.json', after);
  f.replace('authObservation', value => { value.gatewayBefore = beforeRef; value.gatewayAfter = afterRef; });
  createAndroidLocalRun(f.request);
  after.requests[0] = { ...oldRow, status: 404 };
  const changedRef = f.save('gateway-after-observation.json', after);
  f.replace('authObservation', value => { value.gatewayAfter = changedRef; });
  assert.throws(() => createAndroidLocalRun(f.request), /GATEWAY_HISTORY_CHANGED/);
  writeFileSync(beforeRef.path, '{}');
  assert.throws(() => createAndroidLocalRun(f.request), /FIXTURE_EVIDENCE_CHANGED/);
});

test('logout before login and login-stage MFA after token are not a completed normal authentication observation', (t) => {
  for (const [stage, mutation] of [['login', 'early-logout'], ['consent', 'early-logout'], ['login', 'late-mfa']]) {
    const f = fixture(t, stage), after = structuredClone(f.after);
    const route = mutation === 'early-logout' ? '/api/auth/native/logout' : '/api/auth/mfa/step-up';
    const row = after.requests.splice(after.requests.findIndex(item => item.route === route), 1)[0];
    if (mutation === 'early-logout') after.requests.unshift(row);
    else after.requests.splice(after.requests.length - 1, 0, row);
    after.requests.forEach((item, index) => { item.sequence = index + 1; });
    const ref = f.save('gateway-after-reordered.json', after);
    f.replace('authObservation', value => { value.gatewayAfter = ref; });
    assert.throws(() => createAndroidLocalRun(f.request), /ORDERED_NORMAL_AUTH_OBSERVATION_REQUIRED/);
  }
});

test('observed locale captions may change but source identity and content cannot be overridden', (t) => {
  const f = fixture(t);
  f.request.labelObservations = f.save('labels.json', { schemaVersion: 1, observed: true, platform: 'android', udid: SERIAL,
    locale: 'en-US', labels: { today: { dateLabel: 'Sun, 25 Oct 2026', metaLabel: 'task · Sun, 25 Oct 2026 · open · high' } } });
  assert.equal(createAndroidLocalRun(f.request).plan.expectations.today.dateLabel, 'Sun, 25 Oct 2026');
  f.request.labelObservations = f.save('labels.json', { schemaVersion: 1, observed: true, platform: 'android', udid: SERIAL,
    locale: 'en-US', labels: { 'work.draft': { body: 'fabricated' } } });
  assert.throws(() => createAndroidLocalRun(f.request), /SOURCE_IDENTITY_OR_CONTENT_OVERRIDE_FORBIDDEN/);
});

test('secret-bearing inputs, embedded auth secrets and repository-contained outputs are refused', (t) => {
  const f = fixture(t);
  assert.throws(() => createAndroidLocalRun({ ...f.request, password: 'synthetic-forbidden' }), /EMBEDDED_SECRET_FORBIDDEN/);
  assert.throws(() => createAndroidLocalRun({ ...f.request, baseSeed: { path: path.join(f.root, 'credentials.json'), sha256: 'a'.repeat(64) } }), /CREDENTIAL_OR_KEY_INPUT_FORBIDDEN/);
  assert.throws(() => createAndroidLocalRun({ ...f.request, outputPlan: fileURLToPath(new URL('./never-create-android-plan.json', import.meta.url)) }), /OUTPUT_MUST_STAY_OUTSIDE_REPOSITORY/);
  f.replace('authObservation', value => { value.accessToken = 'synthetic-forbidden'; });
  assert.throws(() => createAndroidLocalRun(f.request), /EMBEDDED_SECRET_FORBIDDEN/);
});

test('CLI refuses unsafe requests with bounded secret-free diagnostics and no output mutation', (t) => {
  const f = fixture(t), sentinel = 'synthetic-private-sentinel-never-print';
  const input = f.save('export-request.json', { ...f.request, password: sentinel });
  const result = spawnSync(process.execPath, [fileURLToPath(new URL('./prepare-android-local-run.mjs', import.meta.url)), input.path],
    { encoding: 'utf8', timeout: 10000, maxBuffer: 65536, env: { PATH: process.env.PATH } });
  assert.equal(result.status, 1); assert.equal(result.stdout, ''); assert.ok(!result.stderr.includes(sentinel));
  const failure = JSON.parse(result.stderr);
  assert.equal(failure.failed, 'prepare-android-local-run'); assert.equal(failure.reason, 'EMBEDDED_SECRET_FORBIDDEN');
  for (const key of ['outputSeed', 'outputPlan', 'outputFixture']) assert.equal(existsSync(f.request[key]), false);
});
