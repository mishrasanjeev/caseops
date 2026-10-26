import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createIosLocalRun, prepareIosLocalRun } from './prepare-ios-local-run.mjs';
import { inspectLocalPlan } from '../../apps/mobile/e2e/local-run.mjs';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';

const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const reference = (file) => ({ path: file, sha256: sha(readFileSync(file)) });
const appId = 'ai.caseops.mobile.dev.simulatoracceptance';
const operations = ['disposeMatter', 'readMatterState', 'revokeMatterAccess', 'readNoteState'];
function fixture(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'caseops-ios-export-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const save = (name, value) => {
    const file = path.join(root, name); writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`); return reference(file);
  };
  const gateway = fileURLToPath(new URL('./local-gateway.py', import.meta.url));
  const gatewaySha = sha(readFileSync(gateway));
  const modulePath = fileURLToPath(new URL('./local-owner-controls.mjs', import.meta.url));
  const pythonPath = fileURLToPath(new URL('./local-owner.py', import.meta.url));
  const localeEvidence = save('device-locale-unit.json', { platform: 'ios', udid: 'unit-udid', locale: 'en-US' });
  const base = { environment: 'docker-integration', syntheticDataOnly: true, companyId: 'company', membershipId: 'owner',
    matter: { id: 'primary', identityLabel: 'MAT-001', search: 'MAT-001' }, calendarDate: '2026-10-25',
    taskId: 'owner-task', draftId: 'draft', hearingId: 'hearing-pk', otherMatterId: 'foreign' };
  const baseSeed = save('seed.json', base);
  const matter = { ...base.matter, title: 'Synthetic primary', searches: ['matter_code', 'case_number', 'filing_number', 'cnr_number', 'temporary_e_case_number']
    .map((kind, index) => ({ kind, value: index === 0 ? 'MAT-001' : `identifier-${index}` })) };
  const task = { id: 'member-task', kind: 'task', title: 'Synthetic member task', metaLabel: 'task · Sun, Oct 25, 2026 · open · high', matter };
  const extension = { environment: 'docker-integration', syntheticDataOnly: true, coreInventory: 'native-core-2026-10-25', platform: 'ios',
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
    auth: { mode: 'web-context', webOrigin: 'https://127.0.0.1:3443', companySlug: 'test-legal', mfaRequired: true,
      emailEnv: 'CASEOPS_MOBILE_TEST_EMAIL', passwordEnv: 'CASEOPS_MOBILE_TEST_PASSWORD', totpSecretEnv: 'CASEOPS_MOBILE_TEST_TOTP', iosConsent: true },
    locale: 'en-US', localeEvidence, credentialsFile: 'credentials-file-must-never-be-opened.json',
    destructiveControlsExecuted: false, nativeBrowserCookiesOrTokensPrepared: false };
  const extensionSeed = save('extended-seed-012345abcdef.json', extension);
  const ca = path.join(root, 'ca.crt'); writeFileSync(ca, 'public unit CA bytes');
  const receipt = { environment: 'docker-integration', syntheticDataOnly: true, platform: 'ios', project: 'unit-project',
    backendSha: 'a'.repeat(40), backendRevision: 'api-revision', webSha: 'a'.repeat(40), webRevision: 'web-revision',
    webIdentity: { service: 'web', release_sha: 'a'.repeat(40), revision: 'web-revision' },
    gatewayUrl: 'https://127.0.0.1:8443', webGatewayUrl: 'https://127.0.0.1:3443', gatewayRunId: 'unit-run',
    apiOrigin: 'https://127.0.0.1:8443', webOrigin: 'https://127.0.0.1:3443', publicCA: ca,
    source: { api: { dirty: false }, web: { dirty: false } }, productionAccessed: false, metroLaunched: false,
    webAcceptanceMarkerBuild: true, webMarkerTransportSourcePresent: true, gatewayImplementationSha256: gatewaySha,
    containers: ['api', 'web', 'postgres'].map((service) => ({ id: `${service}-container`, name: `/unit-project-${service}-1`,
      project: 'unit-project', image: `sha256:${'b'.repeat(64)}`, networks: ['unit-project_default'] })) };
  const dockerReceipt = save('receipt-immutable.json', receipt);
  const owner = { modulePath, sha256: sha(readFileSync(modulePath)), capabilities: operations };
  const binding = { environment: 'docker-integration', syntheticDataOnly: true, project: receipt.project,
    backendSha: receipt.backendSha, backendRevision: receipt.backendRevision, apiContainerId: 'api-container',
    apiImage: `sha256:${'b'.repeat(64)}`, extensionFile: path.basename(extensionSeed.path), extensionSha256: extensionSeed.sha256,
    modulePath, moduleSha256: owner.sha256, pythonPath, pythonSha256: sha(readFileSync(pythonPath)),
    capabilities: operations, destructiveControlsExecuted: false };
  const statusEvidence = save('gateway-status.json', { runId: 'unit-run', implementationSha256: gatewaySha,
    markerRejected: 0, routeRejected: 0, overflow: false, lastSequence: 0, requests: [], sessionDeleteAdmissions: [] });
  const gatewayRoutes = save('gateway-descriptor.json', { schemaVersion: 2, routes: ['GET /api/auth/native/sessions'], dynamicAdmissions: {
    nativeCurrentSessionDelete: { kind: 'native-current-session-delete-v1', sourceRoute: 'GET /api/auth/native/sessions',
      sourceListLimit: 50, maxLiveIds: 1, maxAdmissionEvents: 64, nativeBearerOnly: true, cookiesAllowed: false,
      currentOnly: true, unrevokedOnly: true, consumeOnAttempt: true,
      requestEvidenceLink: 'sessionDeleteAdmissions[].sourceRequestId -> requests[].requestId', liveExecutionProofRequiredAt: 'NATIVE-20',
      gatewayRunId: 'unit-run', implementationSha256: gatewaySha, implementationEvidence: reference(gateway),
      isolationEvidence: dockerReceipt, statusEvidence } } });
  const app = path.join(root, 'CaseOps.app'); mkdirSync(app); writeFileSync(path.join(app, 'main.jsbundle'), 'synthetic standalone JS');
  const build = { platform: 'ios', profile: 'ios-simulator-acceptance', appId, sourceSha: receipt.backendSha,
    sourceFingerprint: 'c'.repeat(64), devEnabled: false, automatedTest: true, apiOrigin: receipt.apiOrigin,
    webOrigin: receipt.webOrigin, artifact: app, binaryHash: binaryHash(app) };
  const signingEvidence = path.join(root, 'explicit-synthetic-signing-evidence.log');
  writeFileSync(signingEvidence, 'Offline synthetic signing proof fixture; this is not native execution.');
  const applicationIdentifier = `UNITTEAM1.${appId}`;
  build.iosSigning = { kind: 'ios-simulator-ad-hoc-signing', appId, strictVerified: true, signingIdentity: '-',
    applicationIdentifier, keychainAccessGroups: [applicationIdentifier], entitlementsLocation: 'Mach-O __TEXT,__entitlements',
    slices: [{ architecture: 'arm64', applicationIdentifier, keychainAccessGroups: [applicationIdentifier] }],
    evidence: [reference(signingEvidence)], artifactSha256: build.binaryHash,
    distributionSigning: false, nativeExecution: 'not-run-by-signing-verifier' };
  const request = { schemaVersion: 1, dockerReceipt, baseSeed, extensionSeed,
    buildReceipt: save('build-receipt.json', build), publicCa: reference(ca), gatewayRoutes,
    ownerControls: save('owner-controls.json', owner), ownerBinding: save('owner-binding-unit.json', binding),
    deviceInventory: save('devices.json', { devices: { 'runtime-ios': [{ udid: 'unit-udid', name: 'Dedicated unit simulator', isAvailable: true, state: 'Booted' }] } }),
    runtimeInventory: save('runtimes.json', { runtimes: [{ identifier: 'runtime-ios', platform: 'iOS', version: '26.5', isAvailable: true }] }),
    bundleMetadata: save('bundle-metadata.json', { CFBundleIdentifier: appId, CFBundleShortVersionString: '0.1.0', CFBundleVersion: '1' }),
    authObservation: save('auth-observation.json', { schemaVersion: 1, observed: true, platform: 'ios', udid: 'unit-udid',
      mode: 'web-context', bundleId: appId, webOrigin: receipt.webOrigin, membershipId: 'member', principalLabel: 'Synthetic Member', mfaStage: 'consent', iosConsent: true }),
    udid: 'unit-udid', outputSeed: path.join(root, 'effective-seed.json'), outputPlan: path.join(root, 'plan.json'), outputFixture: path.join(root, 'fixture.json') };
  const replace = (key, edit) => { const value = JSON.parse(readFileSync(request[key].path)); edit(value); request[key] = save(path.basename(request[key].path), value); };
  return { request, root, replace, save, extension };
}

test('export preserves exact opaque event, separate member/task and immutable provenance; existing consumer accepts all 23 cases', (t) => {
  const f = fixture(t), result = prepareIosLocalRun(f.request);
  const seed = JSON.parse(readFileSync(result.seed.path)), plan = JSON.parse(readFileSync(result.plan.path));
  assert.equal(seed.calendar.eventId, 'opaque:calendar.event-42');
  assert.equal(seed.hearingId, 'hearing-pk'); assert.equal(seed.taskId, 'member-task'); assert.equal(seed.membershipId, 'member');
  assert.deepEqual(seed.provenance.baseSeed, f.request.baseSeed); assert.deepEqual(seed.provenance.extensionSeed, f.request.extensionSeed);
  assert.equal(existsSync(path.join(f.root, f.extension.credentialsFile)), false);
  const env = { CASEOPS_MOBILE_TEST_EMAIL: 'unit@example.com', CASEOPS_MOBILE_TEST_PASSWORD: 'unit-only-password', CASEOPS_MOBILE_TEST_TOTP: 'JBSWY3DPEHPK3PXP' };
  const inspected = inspectLocalPlan(plan, 'ios', env);
  assert.deepEqual(inspected.readiness.blockers, []); assert.equal(inspected.readiness.intended.length, 23);
  assert.equal(result.credentialFilesRead, false); assert.equal(result.nativeExecution, 'not-run');
});

test('projection is deterministic and refuses overwritten outputs before replacing retained evidence', (t) => {
  const f = fixture(t);
  assert.deepEqual(createIosLocalRun(f.request), createIosLocalRun(f.request));
  prepareIosLocalRun(f.request); const before = readFileSync(f.request.outputSeed);
  assert.throws(() => prepareIosLocalRun(f.request), /OUTPUT_ALREADY_EXISTS/);
  assert.deepEqual(readFileSync(f.request.outputSeed), before);
});

test('stale base seed bytes, replaced extension hashes and owner extension bindings are refused', (t) => {
  for (const mutation of ['base', 'binding']) {
    const f = fixture(t);
    if (mutation === 'base') f.replace('baseSeed', (value) => { value.taskId = 'different'; });
    else f.replace('ownerBinding', (value) => { value.extensionSha256 = 'd'.repeat(64); });
    assert.throws(() => createIosLocalRun(f.request), mutation === 'base' ? /EXTENSION_BASE_SEED_HASH_MISMATCH/ : /OWNER_EXTENSION_HASH_MISMATCH/);
    assert.equal(existsSync(f.request.outputSeed), false);
  }
});

test('original owner/task and absent opaque Calendar event cannot be substituted for extension evidence', (t) => {
  for (const [edit, expected] of [
    [(value) => { value.membershipId = 'owner'; }, /EXTENDED_MEMBER_REQUIRED/],
    [(value) => { value.today.id = 'owner-task'; value.work.task.id = 'owner-task'; }, /EXTENDED_MEMBER_TASK_REQUIRED/],
    [(value) => { delete value.calendar.eventId; }, /ACTUAL_CALENDAR_EVENT_ID_REQUIRED/],
  ]) { const f = fixture(t); f.replace('extensionSeed', edit); assert.throws(() => createIosLocalRun(f.request), expected); }
});

test('serving identity, dirty backend scope and changed actual app bytes prevent a plan', (t) => {
  for (const kind of ['serving', 'dirty', 'binary']) {
    const f = fixture(t);
    if (kind === 'serving') f.replace('extensionSeed', (value) => { value.servingBuild.revision = 'old-revision'; });
    if (kind === 'dirty') f.replace('dockerReceipt', (value) => { value.source.api.dirty = true; });
    if (kind === 'binary') writeFileSync(path.join(f.root, 'CaseOps.app/main.jsbundle'), 'changed after build');
    assert.throws(() => createIosLocalRun(f.request), /EXTENSION_SERVING_REVISION_MISMATCH|CLEAN_SERVING_INPUTS_REQUIRED|ACTUAL_APP_BINARY_HASH_MISMATCH/);
  }
});

test('unsigned, unverified and differently signed artifact receipts are refused before exporting a run plan', (t) => {
  for (const [edit, expected] of [
    [(value) => { delete value.iosSigning; }, /IOS_SIMULATOR_SIGNING_PROOF_REQUIRED/],
    [(value) => { value.iosSigning.strictVerified = false; }, /STRICT_SIMULATOR_SIGNATURE_REQUIRED/],
    [(value) => { value.iosSigning.artifactSha256 = 'd'.repeat(64); }, /IOS_SIGNING_ARTIFACT_MISMATCH/],
  ]) {
    const f = fixture(t); f.replace('buildReceipt', edit);
    assert.throws(() => prepareIosLocalRun(f.request), expected);
    assert.equal(existsSync(f.request.outputPlan), false); assert.equal(existsSync(f.request.outputSeed), false);
  }
});

test('wrong or unbooted simulator, incorrect runtime and invented MFA stage are rejected', (t) => {
  for (const [field, edit, code] of [
    ['deviceInventory', (value) => { value.devices['runtime-ios'][0].state = 'Shutdown'; }, /BOOTED_SIMULATOR_REQUIRED/],
    ['runtimeInventory', (value) => { value.runtimes[0].platform = 'tvOS'; }, /IOS_RUNTIME_REQUIRED/],
    ['authObservation', (value) => { value.udid = 'different-device'; }, /AUTH_OBSERVATION_CONTEXT_MISMATCH/],
    ['authObservation', (value) => { value.membershipId = 'owner'; }, /AUTH_OBSERVATION_MEMBER_MISMATCH/],
    ['authObservation', (value) => { value.principalLabel = 'Different Member'; }, /AUTH_OBSERVATION_MEMBER_MISMATCH/],
    ['authObservation', (value) => { value.mfaStage = 'guessed'; }, /OBSERVED_MFA_STAGE_REQUIRED/],
  ]) { const f = fixture(t); f.replace(field, edit); assert.throws(() => createIosLocalRun(f.request), code); }
});

test('observed locale labels may change captions but cannot override record IDs or canonical bodies', (t) => {
  const f = fixture(t);
  f.request.labelObservations = f.save('labels.json', { schemaVersion: 1, platform: 'ios', observed: true, udid: 'unit-udid',
    locale: 'en-US', labels: { today: { dateLabel: 'Sun, 25 Oct 2026', metaLabel: 'task · Sun, 25 Oct 2026 · open · high' } } });
  assert.equal(createIosLocalRun(f.request).plan.expectations.today.dateLabel, 'Sun, 25 Oct 2026');
  f.request.labelObservations = f.save('labels.json', { schemaVersion: 1, platform: 'ios', observed: true, udid: 'unit-udid',
    locale: 'en-US', labels: { 'work.draft': { body: 'fabricated body' } } });
  assert.throws(() => createIosLocalRun(f.request), /SOURCE_IDENTITY_OR_CONTENT_OVERRIDE_FORBIDDEN/);
});

test('explicit observed absence of an iOS consent prompt stays false rather than inheriting extension defaults', (t) => {
  const f = fixture(t);
  f.replace('authObservation', (value) => { value.iosConsent = false; });
  assert.equal(createIosLocalRun(f.request).plan.auth.iosConsent, false);
  f.replace('authObservation', (value) => { delete value.iosConsent; });
  assert.throws(() => createIosLocalRun(f.request), /EXPLICIT_OBSERVED_IOS_CONSENT_REQUIRED/);
});

test('secret payloads, credential-file inputs and repository-contained output paths are refused', (t) => {
  const f = fixture(t);
  assert.throws(() => createIosLocalRun({ ...f.request, password: 'unit-secret-value' }), /EMBEDDED_SECRET_FORBIDDEN/);
  assert.throws(() => createIosLocalRun({ ...f.request, baseSeed: { path: path.join(f.root, 'credentials.json'), sha256: 'a'.repeat(64) } }), /CREDENTIAL_OR_KEY_INPUT_FORBIDDEN/);
  assert.throws(() => createIosLocalRun({ ...f.request, outputPlan: fileURLToPath(new URL('./never-create-test-plan.json', import.meta.url)) }), /OUTPUT_MUST_STAY_OUTSIDE_REPOSITORY/);
});
