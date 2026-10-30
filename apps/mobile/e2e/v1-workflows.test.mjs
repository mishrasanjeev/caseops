import { validateAndroidTransport } from './local-run.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import childProcess from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { v1Inventory, V1_BUDGETS, V1_CASE_CONTROL_LIMITS, collectV1 } from './v1-workflows-inventory.mjs';
import { collectV1Workflows, v1WorkflowScenarios, dispatchV1SaveOnce, readOnlyV1Row, closeRejectedV1Editor } from './v1-workflows.mjs';
import { validateV1Fixture, v1Version, v1Lifecycle, validateMutationTrace, validateV1MutationEvidence, strictV1Routes,
  createV1CaseBudget, readV1Reference, V1_CONTROL_CAPABILITIES, v1Hash, reconcileV1Sessions, V1_FIXTURE_ENVELOPE, V1_FIXTURE_ADMISSION_HTTP, createV1FixtureAggregate, validateV1InboxMutationEvidence,
  V1_NATIVE_CREATION_RESERVE, v1OracleIdentityEvidence, validateV1OracleIdentityEvidence, requiredV1ControlIdentities, validateV1ControlIdentityCapacity, reconcileV1ControlIdentities } from './v1-workflows-contract.mjs';
import { pendingV1ProducerPlan, requireV1ProducerPlan, produceV1Dataset, resolveV1ResponseReferences, produceV1Inbox, pendingV1InboxPlan } from './v1-workflows-fixture.mjs';
import { pendingV1ViewerPlan, produceV1Viewer } from './v1-workflows-viewer.mjs';
import { selector } from './native-ui.mjs';
import { pendingV1Request } from '../../../scripts/mobile/prepare-v1-fixture.mjs';
import { admitV1BeforeMembers, observeInstalled, validateAndroidLayoutEvidence, androidLayoutSummary } from '../../../scripts/mobile/run-v1-workflows.mjs';
import { createControls, V1_CONTROL_PROTOCOL } from '../../../scripts/mobile/v1-workflows-controls.mjs';

const ids = ['SOURCE-01', 'SOURCE-02', 'SOURCE-03', 'SOURCE-04', 'SOURCE-05', 'SOURCE-06', 'SOURCE-07', 'WORK-01', 'WORK-02', 'WORK-03', 'WORK-04', 'WORK-05', 'WORK-06', 'WORK-07', 'WORK-08', 'COUNSEL-01', 'INBOX-01'];
const uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const ref = n => ({ path: `/unit/${n}.json`, sha256: 'a'.repeat(64) });
const privateRef = n => ({ ...ref(n), uid: process.getuid() });
const source = 'b'.repeat(40), fingerprint = 'c'.repeat(64), binary = 'd'.repeat(64), version = '2026-10-27T00:00:00+00:00';
function fixture() {
  const companyId = uuid(1), contracts = Array.from({ length: 26 }, (_, index) => ({ id: uuid(20 + index), company_id: companyId,
    contract_code: `SYNTHETIC-${index}`, title: `Synthetic native contract ${index}`, status: 'draft', currency: 'INR',
    effective_on: null, expires_on: null, renewal_on: null, total_value_minor: index === 1 ? 1 : null, updated_at: version }));
  return { coreInventory: 'native-core-2026-10-25', environment: 'docker-integration', syntheticDataOnly: true,
    appId: 'ai.caseops.mobile.dev.simulatoracceptance', companyId, membershipId: uuid(2),
    v1: { inventoryId: v1Inventory.inventoryId, platform: 'ios', readyForLive: true, preparedOnly: false,
      records: { companyId, ...featureRecords(companyId), calendar: { sources: ['patent', 'design', 'trademark'].map((family, index) => ({ family,
        docket: { id: uuid(50 + index), company_id: companyId, record_type: ['patent_family', 'design_intake', 'trademark'][index] },
        event: { ip_docket_id: uuid(50 + index) }, expected: { sourceId: uuid(50 + index) } })) },
      contracts: { pages: [{ contracts: contracts.slice(0, 25), next_cursor: 'synthetic-public-continuation' }, { contracts: contracts.slice(25), next_cursor: null }],
        nullable: contracts[0], minorUnit: contracts[1], minorUnitExpectedLabel: 'INR 1 minor unit' },
      access: { wall: { docket: { id: uuid(50), company_id: companyId, matter_id: uuid(100) }, linkedMatter: { id: uuid(100), company_id: companyId }, subjectMembershipId: uuid(2), initialPolicyEvidence: ref('wall-initial') }, faults: ['readiness-revoked', 'grant-revoked', 'missing', 'offline', 'malformed'].map(mode => ({ mode })) },
      policy: { viewerEvidence: ref('viewer'), readOnlyMemberFixture: ref('fixture-b'), readOnly: { expectedRole: 'viewer', expectedCanWrite: false, matter: { id: uuid(109), company_id: uuid(9), lifecycle_version: 0, is_disposed: false }, task: { id: uuid(110), matter_id: uuid(109), updated_at: version, immutable_lifecycle_history: false }, hearing: { id: uuid(111), matter_id: uuid(109), record_version: 'mhv1:' + 'ab'.repeat(32), immutable_lifecycle_history: false } }, revokedWork: { matter: { id: uuid(112), company_id: companyId, restricted_access: true }, task: { id: uuid(113), matter_id: uuid(112) }, grantId: uuid(114), subjectMembershipId: uuid(2) } },
      work: { targets: Array.from({ length: 6 }, (_, index) => ({ matter: { id: uuid(100 + index), company_id: companyId, lifecycle_version: 0, is_disposed: false },
        ...(index === 4 ? { races: [{ kind: 'parent' }, { kind: 'child' }] } : {}) })) } },
      notificationPolicy: { explicitEmptyChannelsBackendVerified: true, evidence: ref('notification-policy'), channels: [], critical: false },
      controls: { evidence: ref('controls'), capabilities: [...V1_CONTROL_CAPABILITIES], mutationsUseNormalApis: true, directDatabaseWrites: false, noPaidMarker: 'no-paid-providers' } } };
}
function featureRecords(companyId) {
  const obligations = Array.from({ length: 11 }, (_, index) => ({ id: uuid(300 + index), contract_id: uuid(20), title: 'Synthetic obligation ' + index,
    description: null, description_truncated: false, due_on: index === 1 ? '2026-10-28' : null, owner_membership_id: index === 1 ? uuid(2) : null,
    owner_name: index === 1 ? 'Synthetic native member A' : null, status: 'pending', priority: 'medium', completed_at: null, created_at: version }));
  const obligationPage = rows => ({ company_id: companyId, contract_id: uuid(20), limit: 10, ordering: 'id_ascending', obligations: rows, next_after: rows.length === 10 ? rows.at(-1).id : null });
  const assignment = n => ({ id: uuid(n), company_id: companyId, matter_id: uuid(100), counsel_id: uuid(390), currency: 'INR', budget_amount_minor: n === 410 ? 1 : 3 }), spend = n => ({ id: uuid(n), company_id: companyId, matter_id: uuid(100), counsel_id: uuid(390) });
  const assignments = Array.from({ length: 11 }, (_, i) => assignment(400 + i)), spends = Array.from({ length: 26 }, (_, i) => spend(500 + i));
  const counsel = (a, p) => ({ matter_id: uuid(100), assignment_limit: 10, spend_limit: 25, totals_scope: 'page', assignments: a, spend_records: p,
    assignment_next_after: a.length === 10 ? a.at(-1).id : null, spend_next_after: p.length === 25 ? p.at(-1).id : null, currencies: [{ currency: 'INR' }] });
  return { obligations: { companyId, contractId: uuid(20), pages: [obligationPage(obligations.slice(0, 10)), obligationPage(obligations.slice(10))], retainedPreview: null },
    counsel: { matter: { id: uuid(100), company_id: companyId }, pages: [counsel(assignments.slice(0, 10), spends.slice(0, 25)), counsel(assignments.slice(10), spends.slice(0, 25)), counsel(assignments.slice(10), spends.slice(25))],
      moneyFacts: [{ recordId: uuid(410), fieldId: 'counsel-assignment-budget', currency: 'INR', minorUnits: 1, expectedLabel: 'INR 0.01 (1 paisa)' }] },
    inbox: { companyId, membershipId: uuid(2), deliveryEvidence: ref('inbox'), notification: { id: uuid(600), status: 'unread', target: { kind: 'matter', id: uuid(100) } },
      matter: { id: uuid(100), company_id: companyId }, transitions: ['read', 'dismissed', 'unread'], externalCalls: 0, manualReceiptInsertion: false } };
}
function aggregateDouble(runId = 'v1-' + uuid(1)) { return { begin() {}, request() {}, worker() {}, observer() {}, remaining: () => 180000, publicState: () => ({ runId, sourceSha: source, stages: [{ stage: 'inbox', started: 1793059200000 }] }) }; }
function admittedProducer() { return { aggregate: aggregateDouble(), planEvidence: ref('phase-plan'), persistPrivate: async () => ({ evidence: privateRef('secondary-owner-private'), mode: 0o600, canonicalWriter: 'local-fixture.py', identity: { dev: '1', ino: '2', uid: process.getuid() }, ownedNoFollowSingleLink: true }), admit: async () => ({ beforeMemberRead: true, sourceSha: source, apiSourceSha: source, webSourceSha: source, companyId: uuid(1), membershipId: uuid(3), role: 'owner' }) }; }
function validProducerPlan() {
  const plan = pendingV1ProducerPlan(); Object.assign(plan, { readyForLive: true, preparedOnly: false, sourceSha: source,
    runId: 'v1-00000000-0000-4000-8000-000000000001', platform: 'ios', companyId: uuid(1), membershipId: uuid(2), ownerMembershipId: uuid(3), secondaryOwner: { companySlug: 'synthetic-b', companyName: 'Synthetic B', fullName: 'Synthetic B owner', email: 'owner-b@example.invalid' },
    catalogueEvidence: ref('catalogue'), emptyNotificationPlanEvidence: ref('notification'), viewerEvidence: ref('viewer'), fixtureProjection: fixture() });
  plan.steps = [...Array.from({ length: 26 }, (_, i) => ({ key: `contract-${i}`, purpose: 'contract-create', method: 'POST', route: '/api/contracts/', body: { title: 'Synthetic native contract' }, expectedStatuses: [200] })),
    ...['patent', 'design', 'trademark'].map(family => ({ key: `ip-${family}`, purpose: 'ip-create', family, method: 'POST', idempotent: true,
      route: { patent: '/api/ip/patents/families', design: '/api/ip/specialist/records', trademark: '/api/ip/trademark-applications/manual' }[family],
      body: { title: 'Synthetic native source', ...(family === 'design' ? { details: { domain: 'design' } } : {}) }, expectedStatuses: [201] })),
    ...Array.from({ length: 8 }, (_, i) => ({ key: `matter-${i}`, purpose: 'work-parent-create', method: 'POST', route: '/api/matters/', body: { title: 'Synthetic native work' }, expectedStatuses: [200] })),
    { key: 'wall-link', purpose: 'wall-matter-link', method: 'POST', route: '/api/ip/dockets/{docket}/matter-links', routeIds: { docket: 'ip-patent.docket_id' }, body: { matter_id: { $response: 'matter-0.id' }, relation_role: 'operational', expected_docket_updated_at: version, reason: 'Synthetic native wall lineage' }, expectedStatuses: [200] },
    { key: 'restricted', purpose: 'revoked-restricted', method: 'POST', route: '/api/matters/{matter}/access/restricted', routeIds: { matter: 'matter-7.id' }, body: { restricted: true }, expectedStatuses: [200] },
    { key: 'grant', purpose: 'revoked-grant', method: 'POST', route: '/api/matters/{matter}/access/grants', routeIds: { matter: 'matter-7.id' }, body: { membership_id: uuid(2) }, expectedStatuses: [200] }];
  return plan;
}
function admissionFixture() {
  const root = path.resolve(fileURLToPath(new URL('../../../', import.meta.url))), q = pendingV1Request(), values = new Map(), log = [];
  const store = (name, value) => { const r = ref(name); values.set(r.path, value); return r; };
  Object.assign(q, { readyForLive: true, preparedOnly: false, platform: 'ios', repoRoot: root, reportRoot: '/unit/reports',
    expectedSourceSha: source, expectedSourceFingerprint: fingerprint, expectedInputFileCount: 140,
    expectedBinaryHash: binary, expectedHarnessFingerprint: 'e'.repeat(64) });
  const sourceProof = { sourceSha: source, sourceFingerprint: fingerprint, sourceDirty: false, inputFileCount: 140 };
  const f = fixture(); Object.assign(f, { binarySourceSha: source, backendSha: source, webSha: source, binarySourceFingerprint: fingerprint,
    apiOrigin: 'https://127.0.0.1:8443', udid: 'synthetic-iphone', publicCa: { path: '/unit/ca.crt' }, principalLabel: 'Synthetic native member A',
    auth: { webOrigin: 'https://127.0.0.1:3443', companySlug: 'synthetic-a', mode: 'web-context', mfaRequired: true, mfaStage: 'consent', iosConsent: false,
      emailEnv: 'CASEOPS_MOBILE_V1_A_EMAIL', passwordEnv: 'CASEOPS_MOBILE_V1_A_PASSWORD', totpSecretEnv: 'CASEOPS_MOBILE_V1_A_TOTP' } });
  const b = structuredClone(f); b.companyId = uuid(9); b.membershipId = uuid(10); b.principalLabel = 'Synthetic native member B'; b.auth = { ...b.auth, companySlug: 'synthetic-b', emailEnv: 'CASEOPS_MOBILE_V1_B_EMAIL', passwordEnv: 'CASEOPS_MOBILE_V1_B_PASSWORD', totpSecretEnv: 'CASEOPS_MOBILE_V1_B_TOTP' };
  q.buildReceipt = store('build', { sourceSha: source, sourceFingerprint: fingerprint, sourceDirty: false, inputFileCount: 140, artifact: '/unit/app.app' });
  q.dockerReceipt = store('isolation', { backendSha: source, webSha: source, gatewayUrl: f.apiOrigin, webGatewayUrl: f.auth.webOrigin,
    apiOrigin: f.apiOrigin, webOrigin: f.auth.webOrigin, backendRevision: 'synthetic-api', webRevision: 'synthetic-web', gatewayRunId: 'synthetic-run', publicCA: '/unit/ca.crt' });
  for (const item of [f, b]) { item.buildReceipt = q.buildReceipt; item.isolationEvidence = q.dockerReceipt; }
  q.fixtureEvidence = store('fixture', f); q.deviceEvidence = store('device', { observed: true, platform: 'ios', udid: f.udid, appId: f.appId,
    buildReceipt: q.buildReceipt, deviceTypeIdentifier: 'com.apple.CoreSimulator.SimDeviceType.iPhone-17' });
  q.installedEvidence = store('installed', { udid: f.udid, appId: f.appId, binaryHash: binary, buildReceipt: q.buildReceipt, appDataPath: '/unit/app-data' });
  const module = { path: path.join(root, 'scripts/mobile/v1-workflows-controls.mjs'), sha256: 'a'.repeat(64) };
  const gatewayImplementationEvidence = { path: path.join(root, 'scripts/mobile/local-v1-controls.py'), sha256: 'a'.repeat(64) };
  const workerEvidence = { path: path.join(root, 'scripts/mobile/local-v1-inbox.py'), sha256: 'a'.repeat(64) };
  q.codeClosure = store('closure', { code: [module, gatewayImplementationEvidence, workerEvidence] });
  q.producerEvidence = store('producer', { kind: 'actual-normal-api-v1-fixture', phase: 'readthrough', nativeReady: false, observed: true, sourceSha: source, companyId: f.companyId, directDatabaseWrites: false, automaticRetry: false, mutationUncertain: false, requests: 54, writes: 49 });
  const actors = { owner: { companyId: f.companyId, membershipId: uuid(3), credentialEvidence: privateRef('private-owner') }, member: { companyId: f.companyId, membershipId: f.membershipId, credentialEvidence: privateRef('private-a') }, 'second-company': { companyId: b.companyId, membershipId: b.membershipId, credentialEvidence: privateRef('private-b') } };
  const registration = store('registration', { synthetic: true, actors, authorityEvidence: privateRef('authority'), exactRoutes: strictV1Routes(f.v1.records), ownerExactRoutes: [], ownerRecipes: [] });
  q.controlsEvidence = store('controls', { capabilities: V1_CONTROL_CAPABILITIES, sourceSha: source, nativeMutationsForwardedByControls: false,
    directDatabaseWrites: false, module, gatewayImplementationEvidence, registrationSha256: registration.sha256 });
  q.gatewayEvidence = store('gateway', { observed: true, sourceSha: source, gatewayRunId: 'synthetic-run', v1ExactRoutes: strictV1Routes(f.v1.records),
    nativeWorkBodyObservation: 'keys-and-canonical-sha256', authorizationValuesRetained: false, v1Registration: registration });
  const authFor = item => ({ observed: true, mode: 'web-context', udid: f.udid, bundleId: f.appId, buildReceipt: q.buildReceipt, dockerReceipt: q.dockerReceipt,
    binaryHash: binary, membershipId: item.membershipId, nativePrincipalVerified: true, nativeWorkspaceVerified: true,
    pkceUnchanged: true, logoutAcknowledged: true, sessionCleanup: 'passed', importedSource: sourceProof, mfaStage: 'consent', iosConsent: false });
  q.authObservation = store('auth-a', authFor(f));
  q.members = [{ credentialEvidence: privateRef('private-a'), fixtureEvidence: store('fixture-a', f), authObservation: q.authObservation },
    { credentialEvidence: privateRef('private-b'), fixtureEvidence: store('fixture-b', b), authObservation: store('auth-b', authFor(b)) }];
  f.v1.records.secondCompany = { fixtureEvidence: q.members[1].fixtureEvidence };
  f.v1.records.policy.readOnlyMemberFixture = q.members[1].fixtureEvidence;
  q.viewerEvidence = store('viewer', { kind: 'actual-normal-api-v1-viewer', observed: true, sourceSha: source, companyId: b.companyId, membershipId: b.membershipId, role: 'viewer', capabilities: ['matters:read'], mfaEnrolled: true, credentialEvidence: q.members[1].credentialEvidence, buildReceipt: q.buildReceipt, dockerReceipt: q.dockerReceipt, installedEvidence: q.installedEvidence, binaryHash: binary, readOnlyWork: f.v1.records.policy.readOnly, noPaidMarker: 'no-paid-providers', directDatabaseWrites: false, automaticRetry: false, mutationUncertain: false });
  f.v1.records.policy.viewerEvidence = q.viewerEvidence;
  q.inboxEvidence = store('inbox', { kind: 'actual-canonical-in-app-fixture', observed: true, sourceSha: source, companyId: f.companyId, membershipId: f.membershipId, notification: f.v1.records.inbox.notification,
    automaticRetry: false, mutationUncertain: false, externalCalls: 0, manualReceiptInsertion: false, workerEvidence, worker: { workerExecutions: 1, observerStatements: 5 }, requests: 4, writes: 1 });
  f.v1.records.inbox.deliveryEvidence = q.inboxEvidence;
  const runId = 'v1-' + uuid(900), baseReceipt = store('base-producer', { kind: 'actual-normal-api-v1-base-fixture', observed: true, sourceSha: source, runId,
    automaticRetry: false, mutationUncertain: false, requests: 40, writes: 40 });
  Object.assign(values.get(q.viewerEvidence.path), { phase: 'viewer', runId, requests: 10, writes: 7 });
  Object.assign(values.get(q.producerEvidence.path), { runId }); Object.assign(values.get(q.inboxEvidence.path), { phase: 'inbox', runId });
  const receipts = [baseReceipt, q.viewerEvidence, q.inboxEvidence, q.producerEvidence];
  q.aggregateFixtureEvidence = store('aggregate', { schemaVersion: 1, kind: 'actual-complete-v1-fixture-aggregate', observed: true, sourceSha: source, runId, automaticRetry: false,
    elapsedMilliseconds: 5000, envelope: V1_FIXTURE_ENVELOPE, stages: ['base', 'viewer', 'inbox', 'readthrough'].map((stage, index) => ({ stage, completed: true, started: 0,
      requests: index ? V1_FIXTURE_ENVELOPE.stages[stage].requests : 40, posts: index ? V1_FIXTURE_ENVELOPE.stages[stage].posts : 40,
      admissionRequests: 7, admissionPosts: 2, workerExecutions: stage === 'inbox' ? 1 : 0, observerStatements: stage === 'inbox' ? 5 : 0,
      planEvidence: store(`phase-plan-${index}`, { synthetic: true, sourceSha: source, runId, readyForLive: true, preparedOnly: false }), receiptEvidence: receipts[index] })) });
  f.v1.provenance = { aggregateFixture: q.aggregateFixtureEvidence };
  Object.assign(values.get(registration.path), { caseControlLimits: V1_CASE_CONTROL_LIMITS, inboxNotifications: [{ id: f.v1.records.inbox.notification.id, companyId: f.companyId,
    recipientMembershipId: f.membershipId, target: f.v1.records.inbox.notification.target, deliveryEvidence: q.inboxEvidence }] });
  values.get(registration.path).syntheticIds = requiredV1ControlIdentities(f.v1.records, values.get(registration.path));
  const oracleIdentityEvidence = v1OracleIdentityEvidence(f.v1.records, actors);
  for (const receipt of receipts) values.get(receipt.path).oracleIdentityEvidence = oracleIdentityEvidence;
  const actual = { udid: f.udid, appId: f.appId, binaryHash: binary, deviceTypeIdentifier: 'com.apple.CoreSimulator.SimDeviceType.iPhone-17', appDataPath: '/unit/app-data' };
  const dependencies = { read: r => { assert.ok(values.has(r.path)); return structuredClone(values.get(r.path)); }, bytes: () => Buffer.from('synthetic public code'),
    snapshot: () => { log.push('source'); return structuredClone(sourceProof); }, installed: () => { log.push('installed'); return { ...actual }; },
    artifactHash: () => binary, reader: file => { log.push('private-reader'); const item = file.endsWith('private-a.json') ? f : b; return { bytes: Buffer.from('synthetic'), sha256: 'a'.repeat(64), uid: process.getuid(),
      value: { full_name: item.principalLabel, company_slug: item.auth.companySlug, email: 'synthetic@example.invalid', password: 'synthetic-only-password', totp_secret: 'SYNTHETIC_ONLY' } }; },
    getJson: async url => { log.push(url.includes('release-identity') ? 'web' : url.includes('/status') ? 'controls' : 'api');
      return url.includes('/status') ? { runId: 'synthetic-run', v1ControlsEnabled: true, v1ControlsImplementationSha256: gatewayImplementationEvidence.sha256, v1RegistrationSha256: registration.sha256 }
        : { release_sha: source, revision: url.includes('release-identity') ? 'synthetic-web' : 'synthetic-api' }; },
    environment: { NODE_EXTRA_CA_CERTS: '/unit/ca.crt' }, buildCheck: () => {}, fixtureCheck: () => {}, coreCheck: () => {}, harness: () => 'e'.repeat(64) };
  return { q, f, b, values, dependencies, log };
}
test('both platforms collect the independent seventeen literal cases and all51 phases', () => {
  assert.deepEqual(v1Inventory.cases.map(x => x.id), ids); assert.equal(v1Inventory.cases.length, 17);
  for (const platform of ['android', 'ios']) { const result = collectV1Workflows(platform); assert.deepEqual(result.intended, ids.map(id => `${platform}:${id}`)); assert.deepEqual(result.intended, result.discovered); assert.equal(result.expectedPhases, 51); assert.equal(result.expectedSessions, 17); }
});
test('missing duplicate reordered or nonexecutable cases cannot be collected', () => {
  for (const scenarios of [v1WorkflowScenarios.slice(1), [...v1WorkflowScenarios, v1WorkflowScenarios[0]], [...v1WorkflowScenarios].reverse(), v1WorkflowScenarios.map(x => ({ ...x, run: null }))]) assert.throws(() => collectV1('ios', scenarios));
});
test('pending request and producer templates refuse before any loader or transport', async () => {
  let read = 0; await assert.rejects(admitV1BeforeMembers(pendingV1Request(), { read() { read++; } })); assert.equal(read, 0);
  const producer = pendingV1ProducerPlan(); assert.throws(() => requireV1ProducerPlan(producer)); assert.equal(producer.readyForLive, false);
});
test('simulated public source installed API ANDweb admission all precede either private reader', async () => {
  const f = admissionFixture(); const admitted = await admitV1BeforeMembers(f.q, f.dependencies);
  assert.equal(admitted.members.length, 2); const first = f.log.indexOf('private-reader');
  assert.ok(first > f.log.lastIndexOf('source')); assert.ok(first > f.log.lastIndexOf('installed'));
  assert.ok(first > f.log.indexOf('api')); assert.ok(first > f.log.indexOf('web'));
  assert.ok(first > f.log.indexOf('controls'));
  assert.equal(f.log.filter(x => x === 'private-reader').length, 2);
});
test('simulated source binary API web or secondcompany drift refuses with zero private reads', async () => {
  const changes = [
    f => { f.dependencies.snapshot = () => ({ sourceSha: 'f'.repeat(40) }); },
    f => { const original = f.dependencies.installed; f.dependencies.installed = (...args) => ({ ...original(...args), binaryHash: 'f'.repeat(64) }); },
    f => { f.dependencies.getJson = async url => ({ release_sha: 'f'.repeat(40), revision: url.includes('release-identity') ? 'synthetic-web' : 'synthetic-api' }); },
    f => { f.dependencies.getJson = async url => ({ release_sha: url.includes('release-identity') ? 'f'.repeat(40) : source, revision: url.includes('release-identity') ? 'synthetic-web' : 'synthetic-api' }); },
    f => { f.values.get(f.q.members[1].fixtureEvidence.path).auth.webOrigin = 'https://other.invalid'; },
    ...['v1ControlsEnabled', 'v1ControlsImplementationSha256', 'v1RegistrationSha256'].map(key => f => {
      const original = f.dependencies.getJson;
      f.dependencies.getJson = async url => ({ ...await original(url), ...(url.includes('/status') ? { [key]: key === 'v1ControlsEnabled' ? false : 'f'.repeat(64) } : {}) });
    }),
  ];
  for (const change of changes) { const f = admissionFixture(); change(f); await assert.rejects(admitV1BeforeMembers(f.q, f.dependencies)); assert.equal(f.log.includes('private-reader'), false); }
});
test('generic source families bind actual docket types and exact Calendar IDs', () => {
  assert.equal(validateV1Fixture(fixture(), 'ios').v1.platform, 'ios');
  for (const change of [f => f.v1.records.calendar.sources[0].docket.record_type = 'trademark', f => f.v1.records.calendar.sources[0].event.ip_docket_id = uuid(900), f => f.v1.records.calendar.sources[0].docket.company_id = uuid(999)]) { const f = fixture(); change(f); assert.throws(() => validateV1Fixture(f, 'ios')); }
});
test('complete25-record page cursor and unique continuation membership remain strict', () => {
  for (const change of [f => f.v1.records.contracts.pages[0].contracts.pop(), f => f.v1.records.contracts.pages[0].next_cursor = null,
    f => f.v1.records.contracts.pages[1].contracts[0] = f.v1.records.contracts.pages[0].contracts[0]]) { const f = fixture(); change(f); assert.throws(() => validateV1Fixture(f, 'ios')); }
});
test('nullable values and literal one minor unit cannot silently become0 or a guessed exponent', () => {
  for (const change of [f => f.v1.records.contracts.nullable.total_value_minor = 0, f => f.v1.records.contracts.minorUnit.total_value_minor = 0,
    f => f.v1.records.contracts.minorUnitExpectedLabel = 'INR 0.01']) { const f = fixture(); change(f); assert.throws(() => validateV1Fixture(f, 'ios')); }
});
test('aware task versions and keyed hearing versions reject lookalikes and lifecycle bools', () => {
  assert.equal(v1Version(version, 'task'), version); const hmac = 'mhv1:' + 'ab'.repeat(32); assert.equal(v1Version(hmac, 'hearing'), hmac);
  for (const value of ['2026-10-27T00:00:00', '1', true, null]) assert.throws(() => v1Version(value, 'task'));
  for (const value of [version, 'mhv1:unknown', 1]) assert.throws(() => v1Version(value, 'hearing'));
  for (const value of [true, -1, 0.5, '0']) assert.throws(() => v1Lifecycle(value));
});
test('allfive source refusal modes bothworkraces and emptynotification proof are mandatory', () => {
  for (const change of [f => f.v1.records.access.faults.pop(), f => f.v1.records.work.targets[4].races.pop(),
    f => f.v1.notificationPolicy.explicitEmptyChannelsBackendVerified = false, f => f.v1.notificationPolicy.channels.push('email')]) { const f = fixture(); change(f); assert.throws(() => validateV1Fixture(f, 'ios')); }
});
test('gateway plan contains exact returned IDs and never wildcard or manufacturedMatterIP routes', () => {
  const f = fixture(), routes = strictV1Routes(f.v1.records); assert.ok(routes.includes(`GET /api/ip/dockets/${uuid(50)}/summary`));
  assert.equal(routes.includes(`GET /api/matters/${uuid(50)}/workspace`), false); assert.equal(routes.some(x => /[*{}?]/.test(x)), false);
  assert.equal(routes.filter(x => /^GET \/api\/contracts\/[a-f0-9-]{36}$/.test(x)).length, 26);
});
test('one actual dirtyonly mutation hash with native refresh is accepted', () => {
  const body = { expected_lifecycle_version: 1, due_on: null, expected_updated_at: version, status: 'completed' };
  const row = { requestId: 'synthetic-ack', method: 'PATCH', route: `/api/matters/${uuid(1)}/tasks/${uuid(2)}`, status: 200,
    bodyObservation: { keys: Object.keys(body).sort(), canonicalSha256: v1Hash(Buffer.from(JSON.stringify(Object.fromEntries(Object.entries(body).sort(([a], [b]) => a.localeCompare(b)))))) } };
  assert.equal(validateMutationTrace([row, { method: 'POST', route: '/api/auth/native/refresh' }], { method: 'PATCH', route: row.route, body, expectedStatus: [200] }), row);
});
test('duplicatePOST unexpectedfields badhash and wrongstatus remain refused', () => {
  const body = { title: 'Synthetic native task', expected_lifecycle_version: 0 }, route = `/api/matters/${uuid(1)}/tasks`;
  const row = { method: 'POST', route, status: 200, bodyObservation: { keys: Object.keys(body).sort(), canonicalSha256: v1Hash(Buffer.from(JSON.stringify(Object.fromEntries(Object.entries(body).sort(([a], [b]) => a.localeCompare(b)))))) } };
  for (const rows of [[row, row], [{ ...row, status: 500 }], [{ ...row, bodyObservation: { ...row.bodyObservation, keys: [...row.bodyObservation.keys, 'owner_membership_id'] } }], [{ ...row, bodyObservation: { ...row.bodyObservation, canonicalSha256: '0'.repeat(64) } }]]) assert.throws(() => validateMutationTrace(rows, { method: 'POST', route, body, expectedStatus: [200] }));
});
test('exact body observation also agrees with the complete journey and rejects an unrelated second write', () => {
  const body = { title: 'Synthetic native task', expected_lifecycle_version: 0 }, route = `/api/matters/${uuid(1)}/tasks`;
  const observed = { sequence: 4, requestId: 'synthetic-ack', method: 'POST', route, status: 200,
    bodyObservation: { keys: Object.keys(body).sort(), canonicalSha256: v1Hash(Buffer.from(JSON.stringify(Object.fromEntries(Object.entries(body).sort(([a], [b]) => a.localeCompare(b)))))) } };
  const expected = { method: 'POST', route, body, expectedStatus: [200] }, gateway = { ...observed }; delete gateway.bodyObservation;
  assert.equal(validateV1MutationEvidence([observed], [gateway], expected), observed);
  assert.throws(() => validateV1MutationEvidence([observed], [gateway, { method: 'PATCH', route: `/api/matters/${uuid(2)}/tasks/${uuid(3)}`, status: 200 }], expected), /ONE_MUTATION_ACROSS_COMPLETE_NATIVE_JOURNEY_REQUIRED/);
  assert.throws(() => validateV1MutationEvidence([observed], [{ ...gateway, requestId: 'wrong-ack' }], expected), /CONTROL_AND_GATEWAY_ACK_MUST_AGREE/);
});
test('normal fixture projection takes only earlier actual response properties without evaluation', () => {
  const actual = { id: uuid(3), metadata: { items: [{ id: uuid(4) }] } }, observed = new Map([['actual-record', actual]]);
  const result = resolveV1ResponseReferences({ parent: { $response: 'actual-record.id' }, child: { $response: 'actual-record.metadata.items.0.id' } }, observed);
  assert.deepEqual(result, { parent: uuid(3), child: uuid(4) }); assert.deepEqual(actual, { id: uuid(3), metadata: { items: [{ id: uuid(4) }] } });
  for (const key of ['actual-record.__proto__', 'actual-record.constructor', 'actual-record.missing', 'missing-record.id', 'actual-record[0]']) assert.throws(() => resolveV1ResponseReferences({ $response: key }, observed));
});
test('real designregistration absence refuses before all normalAPI writes', async () => {
  const plan = validProducerPlan(); let requests = 0, events = 0;
  const catalogue = { sourceSha: source, syntheticDataOnly: true, designIntakeRegistered: false };
  await assert.rejects(produceV1Dataset(plan, { request() { requests++; }, catalogue, readEvidence: () => catalogue, persist() { events++; } }), /REAL_DESIGN_REGISTRATION_REQUIRED/);
  assert.equal(requests, 0); assert.equal(events, 0);
});
test('producer transport uncertainty stops after one request and retains the original failure', async () => {
  const error = Error('SYNTHETIC_LOST_RESPONSE'), plan = validProducerPlan(), events = []; let calls = 0;
  const catalogue = { sourceSha: source, syntheticDataOnly: true, designIntakeRegistered: true, patentFamilyAvailable: true, trademarkManualAvailable: true };
  const viewer = { kind: 'actual-normal-api-v1-viewer', observed: true, sourceSha: source, role: 'viewer', companyId: uuid(9), mfaEnrolled: true, capabilities: [], directDatabaseWrites: false, automaticRetry: false, mutationUncertain: false };
  await assert.rejects(produceV1Dataset(plan, { ...admittedProducer(), request() { calls++; throw error; }, catalogue, readEvidence: ref => ref.path.endsWith('viewer.json') ? viewer : catalogue, claim() {}, persist: e => events.push(e) }), e => e === error);
  assert.equal(calls, 1); assert.equal(events.at(-1).mutationUncertain, true); assert.equal(events.at(-1).automaticRetry, false);
});
test('native save uses one original protocolID and a lostACK never refetches or rearms', async () => {
  let finds = 0, dispatches = 0, forbidden = 0; const failure = Error('SYNTHETIC_LOST_NATIVE_ACK');
  const element = { elementId: 'original-native-id', isDisplayed: async () => true, isEnabled: async () => true, click: async () => { forbidden++; } };
  const c = { platform: 'android', state: { dispatched: new Set() }, budget: createV1CaseBudget(), driver: {
    $$: async () => { finds++; return [element]; }, waitUntil: async cb => assert.equal(await cb(), true), elementClick: async id => { assert.equal(id, element.elementId); dispatches++; throw failure; },
  } };
  await assert.rejects(dispatchV1SaveOnce(c, 'WORK-01:task'), e => e === failure); await assert.rejects(dispatchV1SaveOnce(c, 'WORK-01:task'), /WORK_MUTATION_REPLAY_REFUSED/);
  assert.equal(finds, 1); assert.equal(dispatches, 1); assert.equal(forbidden, 0);
});
test('percase owner read and action budgets are finite and cannot be silently enlarged', () => {
  const b = createV1CaseBudget(); for (let i = 0; i < V1_BUDGETS.maxControlCallsPerCase; i++) b.owner(); assert.throws(() => b.owner(), /V1_CONTROL_CALL_BOUND/);
  assert.equal(V1_BUDGETS.maxScrolls, 9); assert.equal(V1_BUDGETS.transportMs, 60000); assert.equal(V1_BUDGETS.nativeTransitionMs, 20000);
});
test('publicfixtureJSON is descriptor verified and malformed input has a fixed error', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'v1-public-unit-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true })); const file = path.join(dir, 'public.json');
  fs.writeFileSync(file, JSON.stringify({ synthetic: true })); const reference = { path: file, sha256: v1Hash(fs.readFileSync(file)) }; assert.deepEqual(readV1Reference(reference), { synthetic: true });
  fs.writeFileSync(file, '{SYNTHETIC_INVALID_JSON'); const bad = { path: file, sha256: v1Hash(fs.readFileSync(file)) }; assert.throws(() => readV1Reference(bad), /^Error: V1_EVIDENCE_JSON_REQUIRED$/);
  assert.throws(() => readV1Reference(reference), /V1_EVIDENCE_HASH_MISMATCH/);
});
test('V1 public evidence dev-zero portability refuses nonzero pairs before bytes and retains both final frames', t => {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'v1-public-portability-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'public.json'), data = Buffer.from('{"synthetic":true}'); fs.writeFileSync(file, data);
  const reference = { path: file, sha256: v1Hash(data) }, platform = Object.getOwnPropertyDescriptor(process, 'platform');
  const original = Object.fromEntries(['openSync', 'fstatSync', 'lstatSync', 'readSync'].map(key => [key, fs[key]]));
  for (const change of ['zero', 'same', 'nonzero', 'inode', 'owner', 'fd-dev', 'named-dev', 'named-owner', 'darwin']) {
    let fd, reads = 0;
    Object.defineProperty(process, 'platform', { ...platform, value: change === 'darwin' ? 'darwin' : 'win32' });
    fs.openSync = (...args) => { fd = original.openSync(...args); return fd; };
    fs.fstatSync = (...args) => { const stat = original.fstatSync(...args); return change === 'fd-dev' && reads > 0
      ? new Proxy(stat, { get: (target, key) => key === 'dev' ? stat.dev + 1n : Reflect.get(target, key) }) : stat; };
    fs.lstatSync = (name, options) => {
      const stat = original.lstatSync(name, options); if (name !== file) return stat;
      const patch = { dev: change === 'same' || change === 'named-dev' && reads > 0 ? stat.dev : change === 'nonzero' ? stat.dev + 1n : 0n,
        ...(change === 'inode' ? { ino: stat.ino + 1n } : {}), ...((change === 'owner' || change === 'named-owner' && reads > 0) ? { uid: stat.uid + 1n } : {}) };
      return new Proxy(stat, { get: (target, key) => Object.hasOwn(patch, key) ? patch[key] : Reflect.get(target, key) });
    };
    fs.readSync = (...args) => { reads++; return original.readSync(...args); }; syncBuiltinESMExports();
    try {
      if (['zero', 'same'].includes(change)) assert.deepEqual(readV1Reference(reference), { synthetic: true });
      else assert.throws(() => readV1Reference(reference), /V1_EVIDENCE_(?:IDENTITY_CHANGED|CHANGED_OR_OVERBOUND)/, change);
      if (['nonzero', 'inode', 'owner', 'darwin'].includes(change)) assert.equal(reads, 0, change);
      assert.throws(() => original.fstatSync(fd), { code: 'EBADF' });
    } finally { Object.assign(fs, original); syncBuiltinESMExports(); Object.defineProperty(process, 'platform', platform); }
  }
});
test('new separate inventory does not overwrite the dated23core or17Files inventory sources', () => {
  const root = fileURLToPath(new URL('../../../', import.meta.url));
  const core = JSON.parse(fs.readFileSync(path.join(root, 'apps/mobile/e2e/core-20261025.json'), 'utf8')), files = fs.readFileSync(path.join(root, 'apps/mobile/e2e/ios-files.mjs'), 'utf8');
  assert.equal(core.inventoryId, 'native-core-2026-10-25'); assert.equal(core.cases.length, 23); assert.ok(files.includes('native-ios-files-2026-10-26'));
  assert.equal(core.cases.some(row => row.id === 'SOURCE-01'), false); assert.equal(files.includes('WORK-01'), false);
});
test('no-session refusal is not native execution and complete acceptance needs seventeen distinct paired sessions', () => {
  assert.equal(reconcileV1Sessions([]).nativeExecution, 'not-started');
  const rows = ids.flatMap((id, index) => ['created', 'deleted'].map(state => ({ type: 'appium_session', id: `ios:${id}`, sessionId: uuid(index + 1000), state })));
  assert.deepEqual(reconcileV1Sessions(rows, { requireComplete: true }), { createdSessions: 17, deletedSessions: 17, allCreatedSessionsClosed: true, nativeExecution: 'actual' });
  assert.throws(() => reconcileV1Sessions(rows.slice(0, -1), { requireComplete: true }));
  assert.equal(reconcileV1Sessions(rows.slice(0, -1)).allCreatedSessionsClosed, false);
  assert.throws(() => reconcileV1Sessions([...rows, rows[0]]));
  assert.throws(() => reconcileV1Sessions([{ ...rows[0], id: 'android:SOURCE-01' }, ...rows.slice(1)]));
  assert.throws(() => reconcileV1Sessions([rows[1], rows[0]]));
  assert.throws(() => reconcileV1Sessions([{ type: 'appium_session', state: 'deleted', id: 'ios:SOURCE-01', sessionId: uuid(5000) }]));
});
test('wall lineage readonly authority and revoked grant identities are independent required controls', () => {
  for (const change of [f => f.v1.records.access.wall.docket.matter_id = uuid(999), f => f.v1.records.access.wall.subjectMembershipId = uuid(999),
    f => f.v1.records.policy.readOnly.expectedCanWrite = true, f => f.v1.records.policy.readOnly.matter.company_id = f.companyId,
    f => f.v1.records.policy.revokedWork.grantId = null, f => f.v1.records.policy.revokedWork.matter.id = f.v1.records.work.targets[0].matter.id]) {
    const value = fixture(); change(value); assert.throws(() => validateV1Fixture(value, 'ios'));
  }
});
test('viewer receipt and exact control actor mappings are admitted before either private reader', async () => {
  for (const change of [f => f.values.get(f.q.viewerEvidence.path).role = 'member', f => f.values.get(f.q.viewerEvidence.path).capabilities.push('matters:write'),
    f => f.values.get(f.q.viewerEvidence.path).binaryHash = 'f'.repeat(64), f => f.values.get(f.q.viewerEvidence.path).membershipId = uuid(999),
    f => f.values.get(f.values.get(f.q.gatewayEvidence.path).v1Registration.path).actors['second-company'].credentialEvidence = privateRef('private-a')]) {
    const value = admissionFixture(); change(value); await assert.rejects(admitV1BeforeMembers(value.q, value.dependencies)); assert.equal(value.log.includes('private-reader'), false);
  }
});
function readonlyRowDouble() {
  const facts = ['Synthetic readonly task', 'Unassigned', 'todo · No due date · Read-only'], rect = { x: 20, y: 150, width: 360, height: 90 };
  const element = { elementId: 'row', getAttribute: async key => key === 'type' ? 'XCUIElementTypeOther' : 'false',
    $$: async query => query.startsWith('xpath=ancestor::') ? [{ elementId: 'scroll', isDisplayed: async () => true }] : facts.filter(value => selector('ios', 'text', value) === query).map((value, index) => ({ elementId: `leaf-${index}`, isDisplayed: async () => true, getText: async () => value })) };
  const c = { platform: 'ios', budget: createV1CaseBudget(), driver: { $$: async () => [element], getWindowRect: async () => ({ x: 0, y: 0, width: 402, height: 844 }),
    getElementRect: async id => id === 'scroll' ? { x: 0, y: 125, width: 402, height: 638 } : id === 'row' ? rect : { x: 30, y: 160, width: 300, height: 15 } } };
  return { c, element, facts, rect };
}
test('readonly hidden layout marker requires unique actual facts and contained geometry without an edit role', async () => {
  const value = readonlyRowDouble();
  // Use the canonical selector itself; no row.isDisplayed prerequisite exists.
  assert.equal(await readOnlyV1Row(value.c, 'task-synthetic', value.facts), value.element);
  for (const change of [v => v.c.driver.$$ = async () => [v.element, v.element], v => v.element.getAttribute = async () => 'XCUIElementTypeButton',
    v => v.element.$$ = async () => [], v => v.c.driver.getElementRect = async id => id === 'scroll' ? { x: 0, y: 125, width: 402, height: 638 } : id === 'row' ? v.rect : { x: 0, y: 0, width: 10, height: 10 }]) {
    const item = readonlyRowDouble(); item.element.$$ = value.element.$$; change(item); await assert.rejects(readOnlyV1Row(item.c, 'task-synthetic', item.facts));
  }
});
function viewerProducerDouble() {
  const plan = { ...pendingV1ViewerPlan(), readyForLive: true, preparedOnly: false, sourceSha: source, runId: 'v1-' + uuid(1), companyId: uuid(9),
    fullName: 'Synthetic viewer', email: 'synthetic-viewer@example.invalid', companySlug: 'synthetic-b', buildReceipt: ref('build'), dockerReceipt: ref('docker'), installedEvidence: ref('installed'), codeClosure: ref('closure'), ownerEvidence: ref('base-owner'), ownerMembershipId: uuid(11),
    work: { matter: { title: 'Synthetic readonly Matter' }, task: { title: 'Synthetic readonly task' }, hearing: { purpose: 'Synthetic readonly hearing', reminder_channels: [], reminder_recipient_membership_ids: [], notification_critical: false },
      rowFacts: { task: ['Synthetic readonly task', 'Unassigned', 'todo · No due date · Read-only'], hearing: ['Synthetic readonly hearing', 'Forum not recorded', '27 Oct 2026 · scheduled · Read-only'] } } };
  const identity = { company: { id: uuid(9) }, membership: { id: uuid(10), role: 'viewer', is_active: true }, user: { is_active: true }, capabilities: ['matters:read'] };
  const matter = { id: uuid(109), company_id: uuid(9), title: 'Synthetic readonly Matter', matter_code: 'SYNTHETIC-READONLY', is_disposed: false, lifecycle_version: 0 }, task = { id: uuid(110), matter_id: uuid(109), title: plan.work.task.title, owner_membership_id: null }, hearing = { id: uuid(111), matter_id: uuid(109), purpose: plan.work.hearing.purpose };
  const values = [{ membership_id: uuid(10), role: 'viewer' }, identity, { secret: 'JBSWY3DPEHPK3PXP' }, { status: 'enrolled' }, identity, { mfa_status: 'enrolled' }, matter, task, hearing, { matter, tasks: [task], hearings: [hearing] }], calls = [], events = [], files = [];
  const dependencies = { aggregate: aggregateDouble(), planEvidence: ref('viewer-plan'), readEvidence: () => ({ kind: 'actual-normal-api-v1-base-fixture', observed: true, sourceSha: source, secondaryOwner: { companyId: uuid(9), membershipId: uuid(11), mfaEnrolled: true, credentialEvidence: privateRef('secondary-owner-private') } }), admit: async () => ({ beforeMemberRead: true, companyId: uuid(9), membershipId: uuid(11), role: 'owner', capabilities: ['company:manage_users'], credentialEvidence: privateRef('secondary-owner-private'), sourceSha: source, apiSourceSha: source, webSourceSha: source, buildReceipt: plan.buildReceipt, dockerReceipt: plan.dockerReceipt, installedEvidence: plan.installedEvidence, binaryHash: binary }),
    request: async value => { calls.push(value); return { status: 200, releaseSha: source, value: structuredClone(values[calls.length - 1]), requestId: `synthetic-${calls.length}` }; },
    persistPrivate: async (value, contract) => { files.push({ value: structuredClone(value), contract }); return { evidence: privateRef('viewer-private'), mode: 0o600, canonicalWriter: 'local-fixture.py', identity: { dev: '1', ino: '2', uid: process.getuid() }, ownedNoFollowSingleLink: true }; },
    persist: value => events.push(value), claim() {}, now: () => 1793059200000, password: () => 'SYNTHETIC_ONLY_PASSWORD_NEVER_PUBLIC_1234' };
  return { plan, dependencies, calls, events, files };
}
test('viewer producer executes normal APIs once including MFA and readonly workspace and keeps private data out of events', async () => {
  const value = viewerProducerDouble(), result = await produceV1Viewer(value.plan, value.dependencies);
  assert.equal(value.calls.length, 10); assert.equal(result.role, 'viewer'); assert.equal(result.mfaEnrolled, true);
  assert.equal(value.files.length, 2); assert.equal(value.files[0].contract.createExclusive, true); assert.equal(value.files[0].contract.mode, 0o600);
  assert.equal(value.files[1].contract.createExclusive, false); assert.equal(value.files[1].contract.sameOwnedDescriptor, true);
  assert.equal(value.files[0].value.totp_secret, undefined); assert.equal(value.files[1].value.totp_secret, 'JBSWY3DPEHPK3PXP'); assert.equal(result.readOnlyWork.task.id, uuid(110));
  assert.ok(value.calls.every(call => call.automaticRetry === false && call.timeoutMs <= 10000 && call.headers['X-CaseOps-Automated-Test'] === 'no-paid-providers'));
  const publicLog = JSON.stringify(value.events); assert.equal(publicLog.includes(value.files[0].value.password), false); assert.equal(publicLog.includes(value.files[1].value.totp_secret), false);
  assert.equal(value.calls.filter(call => call.route.endsWith('/hearings'))[0].body.notification_critical, false);
});
test('viewer pending or serving drift refuses without transport and an uncertain create is never replayed', async () => {
  const pending = viewerProducerDouble(); await assert.rejects(produceV1Viewer(pendingV1ViewerPlan(), pending.dependencies)); assert.equal(pending.calls.length, 0);
  const drift = viewerProducerDouble(); drift.dependencies.admit = async () => ({ beforeMemberRead: true, sourceSha: source, apiSourceSha: source, webSourceSha: 'f'.repeat(40) });
  await assert.rejects(produceV1Viewer(drift.plan, drift.dependencies)); assert.equal(drift.calls.length, 0);
  const run = viewerProducerDouble(); run.plan.runId = 'v1-' + uuid(999); await assert.rejects(produceV1Viewer(run.plan, run.dependencies), /EXACT_FIXTURE_RUN_REQUIRED/); assert.equal(run.calls.length, 0);
  const lost = viewerProducerDouble(); let calls = 0; lost.dependencies.request = async () => { calls++; throw Error('synthetic-secret-response-not-for-log'); };
  await assert.rejects(produceV1Viewer(lost.plan, lost.dependencies), /^Error: V1_VIEWER_PRODUCTION_INCOMPLETE_NO_REPLAY$/);
  assert.equal(calls, 1); assert.equal(lost.events.at(-1).mutationUncertain, true); assert.equal(lost.files.length, 1);
});
test('viewer credentials are private before create and MFA updates must retain the admitted inode', async () => {
  const ordered = viewerProducerDouble(), request = ordered.dependencies.request;
  ordered.dependencies.request = async value => { assert.equal(ordered.files.length >= 1, true); return request(value); };
  await produceV1Viewer(ordered.plan, ordered.dependencies);
  const moved = viewerProducerDouble(), writer = moved.dependencies.persistPrivate;
  moved.dependencies.persistPrivate = async (value, contract) => ({ ...await writer(value, contract), ...(contract.createExclusive ? {} : { identity: { dev: '1', ino: 'changed' } }) });
  await assert.rejects(produceV1Viewer(moved.plan, moved.dependencies), /V1_VIEWER_PRODUCTION_INCOMPLETE_NO_REPLAY/);
  assert.equal(moved.calls.length, 3); assert.equal(moved.events.at(-1).mutationUncertain, false);
  const mode = viewerProducerDouble(); mode.dependencies.persistPrivate = async () => ({ evidence: ref('private'), mode: 0o644, canonicalWriter: 'local-fixture.py' });
  await assert.rejects(produceV1Viewer(mode.plan, mode.dependencies)); assert.equal(mode.calls.length, 0);
});
test('supplement exact list and producer create routes match actual canonical trailing slash contracts', () => {
  const routes = strictV1Routes(fixture().v1.records);
  assert.ok(routes.includes('GET /api/contracts/')); assert.ok(routes.includes('GET /api/matters/'));
  assert.equal(routes.includes('GET /api/contracts'), false); assert.equal(routes.includes('GET /api/matters'), false);
  const plan = validProducerPlan(); assert.equal(requireV1ProducerPlan(plan), plan);
  for (const purpose of ['contract-create', 'work-parent-create']) {
    const changed = structuredClone(plan), step = changed.steps.find(value => value.purpose === purpose); step.route = step.route.slice(0, -1);
    assert.throws(() => requireV1ProducerPlan(changed));
  }
});
test('old eleven-case request identity refuses before any evidence or private loader', async () => {
  const value = admissionFixture(); value.q.inventoryId = 'native-v1-source-work-2026-10-27'; let reads = 0;
  value.dependencies.read = () => { reads++; throw Error('must not read'); };
  await assert.rejects(admitV1BeforeMembers(value.q, value.dependencies), /EXACT_V1_REQUEST_INVENTORY_REQUIRED/); assert.equal(reads, 0);
});
test('purged rejected editor closes directly while retained dirty conflict still requires one Leave confirmation', async () => {
  for (const dirty of [false, true]) {
    let editor = true, confirmation = false; const clicks = [];
    const button = elementId => ({ elementId, isDisplayed: async () => true, isEnabled: async () => true });
    const context = { platform: 'android', budget: createV1CaseBudget(), driver: {
      $$: async query => query === selector('android', 'id', 'quick-close') && editor ? [button('close')]
        : query === selector('android', 'text', 'Leave editor') && confirmation ? [button('leave')]
        : query === selector('android', 'id', 'quick-work-editor') && editor ? [button('editor')] : [],
      waitUntil: async fn => assert.equal(await fn(), true), elementClick: async id => { clicks.push(id); if (id === 'close' && dirty) confirmation = true; else { editor = false; confirmation = false; } },
    } };
    await closeRejectedV1Editor(context, dirty); assert.deepEqual(clicks, dirty ? ['close', 'leave'] : ['close']); assert.equal(editor, false);
  }
});

function aggregateModel() {
  let clock = 0; const claims = new Set(), events = [];
  const aggregate = createV1FixtureAggregate({ runId: 'v1-' + uuid(900), sourceSha: source, now: () => clock,
    claim: key => { assert.equal(claims.has(key), false); claims.add(key); }, persist: value => events.push(structuredClone(value)) });
  const admission = stage => { for (const [key, value] of Object.entries(V1_FIXTURE_ADMISSION_HTTP)) aggregate.request(stage, { key, ...value, admission: true }); };
  const stage = name => { aggregate.begin(name, ref(name + '-plan')); admission(name);
    const limits = V1_FIXTURE_ENVELOPE.stages[name]; for (let n = 0; n < limits.requests; n++) aggregate.request(name, { key: `normal-${n}`, method: n < limits.posts ? 'POST' : 'GET', route: '/api/synthetic' });
    if (name === 'inbox') { aggregate.worker(name); aggregate.observer(name); }
    aggregate.complete(name, ref(name + '-receipt'));
  };
  return { aggregate, stage, admission, claims, events, clock: value => { clock = value; } };
}
test('whole fixture charges four fixed stages plus every admission read and write without changing old base limits', () => {
  assert.deepEqual(V1_FIXTURE_ENVELOPE.stages.base, { requests: 96, posts: 64, milliseconds: 180000 });
  const value = aggregateModel(); for (const stage of ['base', 'viewer', 'inbox', 'readthrough']) value.stage(stage);
  const result = value.aggregate.finish(); assert.equal(result.stages.reduce((sum, phase) => sum + phase.requests + phase.admissionRequests, 0), 192);
  assert.equal(result.stages.reduce((sum, phase) => sum + phase.posts + phase.admissionPosts, 0), 129);
  assert.equal(result.stages[2].workerExecutions, 1); assert.equal(value.claims.size, 6);
  assert.equal(Object.values(V1_CASE_CONTROL_LIMITS).reduce((sum, limit) => sum + limit, 1), 255);
});
test('unknown fixture stage and HTTP claims remain consumed and metadata cannot evade exact admission or deadline', () => {
  const value = aggregateModel(); value.aggregate.begin('base', ref('base-plan'));
  value.aggregate.request('base', { key: 'normal-once', method: 'POST', route: '/api/contracts/' });
  assert.throws(() => value.aggregate.request('base', { key: 'normal-once', method: 'POST', route: '/api/contracts/' }), /FIXTURE_HTTP_REPLAY_REFUSED/);
  assert.throws(() => value.aggregate.begin('base', ref('base-again')), /MUST_NOT_REPLAY/);
  assert.throws(() => value.aggregate.begin('viewer', ref('viewer-plan')), /EARLIER_ORIGINAL_STAGE_RECEIPT_REQUIRED/);
  assert.throws(() => value.aggregate.request('base', { key: 'api-before', method: 'GET', route: '/api/auth/me', admission: true }), /EXACT_ADMISSION_HTTP_INVENTORY_REQUIRED/);
  value.clock(180001); assert.throws(() => value.aggregate.request('base', { key: 'late', method: 'GET', route: '/api/build' }), /V1_WHOLE_FIXTURE_DEADLINE/);
  assert.throws(() => value.aggregate.finish());
});
test('aggregate admission requires original phase receipts and exact worker counters before any member read', async () => {
  for (const change of [value => value.values.get(value.q.aggregateFixtureEvidence.path).stages[2].workerExecutions = 2,
    value => value.values.get(value.q.aggregateFixtureEvidence.path).stages[2].observerStatements = 21,
    value => value.values.get(value.q.aggregateFixtureEvidence.path).stages[1].admissionRequests = 6,
    value => value.values.get(value.q.producerEvidence.path).requests = 53,
    value => value.values.get(value.q.inboxEvidence.path).externalCalls = 1]) {
    const value = admissionFixture(); change(value); await assert.rejects(admitV1BeforeMembers(value.q, value.dependencies)); assert.equal(value.log.includes('private-reader'), false);
  }
});
test('inbox mutation proof binds one exact status-only DTO and recipient response to the canonical gateway ACK', () => {
  const id = uuid(600), target = { kind: 'matter', id: uuid(100) }, body = { status: 'read', expected_status: 'unread' };
  const row = { method: 'PATCH', route: `/api/recipient-inbox/${id}`, status: 200, sequence: 7, requestId: 'one-inbox-ack',
    bodyObservation: { keys: ['expected_status', 'status'], canonicalSha256: v1Hash(Buffer.from(JSON.stringify({ expected_status: 'unread', status: 'read' }))) },
    responseObservation: { id, status: 'read', target } };
  assert.equal(validateV1InboxMutationEvidence([row], [row, { method: 'POST', route: '/api/auth/native/refresh' }], { id, body, target }), row);
  for (const [observed, gateway, expected] of [[[row, row], [row], body], [[row], [row, row], body],
    [[{ ...row, responseObservation: { ...row.responseObservation, id: uuid(999) } }], [row], body],
    [[row], [{ ...row, requestId: 'other-ack' }], body], [[row], [row], { ...body, title: 'not allowed' }]])
    assert.throws(() => validateV1InboxMutationEvidence(observed, gateway, { id, body: expected, target }));
});
function inboxProducerDouble() {
  const root = path.resolve(fileURLToPath(new URL('../../../', import.meta.url))), start = 1793059200000, calls = [], events = [], charges = [];
  const plan = { ...pendingV1InboxPlan(), readyForLive: true, preparedOnly: false, sourceSha: source, runId: 'v1-' + uuid(900), companyId: uuid(1), membershipId: uuid(2), matterId: uuid(100),
    workerEvidence: { ...ref('worker'), path: path.join(root, 'scripts/mobile/local-v1-inbox.py') }, managerEvidence: { ...ref('manager'), path: path.join(root, 'scripts/mobile/local-v1-controls.py') }, postgresEvidence: ref('postgres') };
  const matter = { id: plan.matterId, company_id: plan.companyId, is_disposed: false, lifecycle_version: 2, matter_code: 'SYNTHETIC-INBOX', title: 'Synthetic Inbox Matter' };
  let hearing;
  const dependencies = { aggregate: { ...aggregateDouble(plan.runId), request: (...value) => charges.push(value) }, planEvidence: ref('inbox-plan'), now: () => start,
    readCode: () => Buffer.from('synthetic public source'), readEvidence: () => ({ observed: true, readOnly: true, database: 'caseops_mobile' }),
    admit: async () => ({ beforeMemberRead: true, sourceSha: source, apiSourceSha: source, webSourceSha: source, membershipId: plan.membershipId, companyId: plan.companyId, role: 'member', capabilities: ['matters:write'] }),
    request: async value => { calls.push(structuredClone(value)); if (value.method === 'POST') hearing = { id: uuid(700), matter_id: plan.matterId, hearing_on: value.body.hearing_on, hearing_time: value.body.hearing_time, reminder_policy: { channels: ['in_app'], critical: false } };
      return { status: 200, releaseSha: source, requestId: 'synthetic-' + calls.length, value: value.method === 'POST' ? hearing : value.route.startsWith('/api/recipient-inbox')
        ? { scope: 'delivered_hearing_and_ip_renewal', items: [{ id: uuid(600), status: 'unread', title: 'Synthetic hearing due', target: { kind: 'matter', id: plan.matterId } }] } : { matter, hearings: hearing ? [hearing] : [] } }; },
    persistWorkerRequest: async value => { events.push({ type: 'worker-request', value }); return ref('actual-worker-request'); },
    executeWorker: async value => { for (let sequence = 1; sequence <= 5; sequence++) value.onObserverStatement(sequence);
      return { kind: 'actual-canonical-in-app-worker', observed: true, sourceSha: source, runId: plan.runId, companyId: plan.companyId, membershipId: plan.membershipId, hearingId: hearing.id,
        notificationId: uuid(600), externalCalls: 0, manualReceiptInsertion: false, workerExecutions: 1, observerStatements: 5 }; }, persist: value => events.push(value) };
  return { plan, dependencies, calls, events, charges, matter };
}
test('inbox fixture uses four normal member HTTP calls and one due worker under one shared phase', async () => {
  const value = inboxProducerDouble(), result = await produceV1Inbox(value.plan, value.dependencies);
  assert.equal(result.requests, 4); assert.equal(result.writes, 1); assert.equal(result.worker.workerExecutions, 1); assert.equal(value.charges.length, 4);
  const body = value.calls[1].body; assert.deepEqual(body.reminder_channels, ['in_app']); assert.deepEqual(body.reminder_recipient_membership_ids, [value.plan.membershipId]); assert.equal(body.expected_lifecycle_version, 2);
  const worker = value.events.find(event => event.type === 'worker-request').value;
  assert.equal(worker.phaseStartedMilliseconds, 1793059200000); assert.equal(worker.hearingAcknowledgement.requestId, 'synthetic-2'); assert.equal(worker.manualReceiptInsertion, false);
  assert.ok(value.calls.every(call => call.automaticRetry === false && call.timeoutMs <= 10000));
});
test('inbox fixture pending, stale parent, unknown hearing and worker result refuse without replay', async () => {
  const pending = inboxProducerDouble(); await assert.rejects(produceV1Inbox(pendingV1InboxPlan(), pending.dependencies)); assert.equal(pending.calls.length, 0);
  const run = inboxProducerDouble(); run.plan.runId = 'v1-' + uuid(999); await assert.rejects(produceV1Inbox(run.plan, run.dependencies), /EXACT_FIXTURE_RUN_REQUIRED/); assert.equal(run.calls.length, 0);
  const lifecycle = inboxProducerDouble(); lifecycle.matter.lifecycle_version = true; await assert.rejects(produceV1Inbox(lifecycle.plan, lifecycle.dependencies)); assert.equal(lifecycle.calls.length, 1);
  const lost = inboxProducerDouble(), request = lost.dependencies.request; lost.dependencies.request = async value => { if (value.method === 'POST') { lost.calls.push(value); throw Error('SYNTHETIC_PRIVATE_NOT_REFLECTED'); } return request(value); };
  await assert.rejects(produceV1Inbox(lost.plan, lost.dependencies), /^Error: V1_INBOX_FIXTURE_INCOMPLETE_NO_REPLAY$/); assert.equal(lost.calls.length, 2); assert.equal(lost.events.at(-1).mutationUncertain, true);
  const worker = inboxProducerDouble(); worker.dependencies.executeWorker = async () => { throw Error('SYNTHETIC_UNKNOWN_WORKER'); };
  await assert.rejects(produceV1Inbox(worker.plan, worker.dependencies)); assert.equal(worker.calls.length, 3); assert.equal(worker.events.at(-1).mutationUncertain, true);
});

test('normal secondary owner credentials precede bootstrap and MFA verification while private responses stay omitted', async () => {
  const plan = validProducerPlan(), events = [], privateWrites = [], calls = [], catalogue = { sourceSha: source, syntheticDataOnly: true, designIntakeRegistered: true, patentFamilyAvailable: true, trademarkManualAvailable: true };
  const dependencies = { ...admittedProducer(), catalogue, readEvidence: () => catalogue, claim() {}, persist: value => events.push(value),
    persistPrivate: async (value, contract) => { privateWrites.push({ value: structuredClone(value), contract }); return { evidence: privateRef('secondary-owner-private'), mode: 0o600, canonicalWriter: 'local-fixture.py', identity: { dev: '1', ino: '2', uid: process.getuid() }, ownedNoFollowSingleLink: true }; },
    request: async value => { calls.push(value); assert.ok(privateWrites.length > 0); if (calls.length === 1) return { status: 200, releaseSha: source, requestId: 'bootstrap', value: { company: { id: uuid(9), slug: 'synthetic-b' }, membership: { id: uuid(11), role: 'owner' }, user: { full_name: 'Synthetic B owner' }, capabilities: ['company:manage_users'], access_token: 'SYNTHETIC_PRIVATE_TOKEN' } };
      if (calls.length === 2) return { status: 200, releaseSha: source, requestId: 'enroll', value: { secret: 'JBSWY3DPEHPK3PXP' } };
      if (calls.length === 3) { assert.equal(privateWrites.length, 2); assert.equal(privateWrites[1].value.totp_secret, 'JBSWY3DPEHPK3PXP'); return { status: 200, releaseSha: source, requestId: 'verify', value: { status: 'enrolled' } }; }
      if (calls.length === 4) return { status: 200, releaseSha: source, requestId: 'security', value: { mfa_status: 'enrolled' } };
      throw Error('SYNTHETIC_FIRST_CONTRACT_UNKNOWN'); } };
  await assert.rejects(produceV1Dataset(plan, dependencies), /SYNTHETIC_FIRST_CONTRACT_UNKNOWN/); assert.equal(calls.length, 5);
  assert.equal(privateWrites[0].contract.createExclusive, true); assert.equal(privateWrites[1].contract.sameOwnedDescriptor, true);
  const publicEvents = JSON.stringify(events); for (const secret of [privateWrites[0].value.password, 'SYNTHETIC_PRIVATE_TOKEN', 'JBSWY3DPEHPK3PXP']) assert.equal(publicEvents.includes(secret), false);
  assert.equal(events.at(-1).mutationUncertain, true); assert.equal(events.at(-1).automaticRetry, false);
});

test('control receipt polling charges every actual RPC to its literal case ceiling and never retries a write', async () => {
  const previous = process.env.NODE_EXTRA_CA_CERTS; process.env.NODE_EXTRA_CA_CERTS = '/unit/ca.crt';
  const f = { binarySourceSha: source, gatewayRunId: 'synthetic-run', gatewayUrl: 'https://127.0.0.1:8443', publicCa: { path: '/unit/ca.crt' } };
  const descriptor = { observed: true, kind: 'registered-v1-qa-controls', binaryHash: binary, sourceSha: source, runId: f.gatewayRunId,
    capabilities: V1_CONTROL_CAPABILITIES, protocol: V1_CONTROL_PROTOCOL, origin: f.gatewayUrl, authorityEvidence: privateRef('authority'), registrationSha256: 'e'.repeat(64) };
  const sent = []; let clock = 0;
  try {
    const controls = createControls({ fixture: f, descriptor, admission: { beforeMemberRead: true, source: { sourceSha: source }, installed: { binaryHash: binary } } }, {
      member: () => ({ bytes: Buffer.from('synthetic'), value: { control_secret: 'f'.repeat(64) }, sha256: descriptor.authorityEvidence.sha256, uid: process.getuid() }),
      now: () => clock, sleep: async milliseconds => { clock += milliseconds; }, fetch: async (_url, options) => {
        const request = JSON.parse(options.body); sent.push(request); return new Response(JSON.stringify({ ...request, observed: true, sourceSha: source,
          noPaidMarker: 'no-paid-providers', directDatabaseWrites: false, nativeMutationsForwardedByControls: false, reached: false }), { status: 200 }); },
    });
    await assert.rejects(controls.readControlReceipt({ caseId: 'SOURCE-01', id: 'synthetic-arm', waitFor: 'reached' }), /V1_CASE_RPC_BOUND/);
    assert.equal(sent.length, V1_CASE_CONTROL_LIMITS['SOURCE-01']); assert.equal(new Set(sent.map(value => value.operationId)).size, sent.length);
    assert.ok(sent.every(value => value.capability === 'readControlReceipt')); assert.ok(clock < V1_CONTROL_PROTOCOL.completionMs);
    controls.dispose(); await assert.rejects(controls.readWorkspace({ caseId: 'WORK-01' }), /V1_CONTROLS_CLOSED/); assert.equal(sent.length, 14);
  } finally { if (previous === undefined) delete process.env.NODE_EXTRA_CA_CERTS; else process.env.NODE_EXTRA_CA_CERTS = previous; }
});

test('identity capacity accepts92 and refuses93 before a protected read while reserving the four named create cases', () => {
  assert.deepEqual(V1_NATIVE_CREATION_RESERVE.map(({ caseId, kind }) => [caseId, kind]), [['WORK-01', 'task'], ['WORK-03', 'hearing'], ['WORK-04', 'follow-up-task'], ['WORK-06', 'unknown-save-task']]);
  let reads = 0; const admit = identities => { const result = validateV1ControlIdentityCapacity(identities); reads++; return result; };
  const result = admit(Array.from({ length: 92 }, (_, index) => uuid(2000 + index))); assert.equal(reads, 1); assert.equal(result.maximumKnownCount, 96); assert.equal(result.unusedHeadroom, 0);
  assert.throws(() => admit(Array.from({ length: 93 }, (_, index) => uuid(2000 + index))), /FOUR_NATIVE_IDENTITIES_MUST_BE_RESERVED/); assert.equal(reads, 1);
});
test('complete control authority differs explicitly from retained payload oracles and rejects extra or unregistered IDs', async () => {
  const value = admissionFixture(), registered = value.values.get(value.values.get(value.q.gatewayEvidence.path).v1Registration.path), evidence = value.values.get(value.q.producerEvidence.path).oracleIdentityEvidence;
  const audit = reconcileV1ControlIdentities(value.f.v1.records, registered, evidence);
  assert.equal(audit.registeredCount, registered.syntheticIds.length); assert.equal(audit.oracleCount, evidence.identities.length); assert.ok(audit.payloadOnlyCount > 0);
  // Exact synthetic model census, not a claim about future response-derived IDs.
  assert.equal(audit.registeredCount, 50); assert.equal(audit.oracleCount, 96); assert.equal(audit.payloadOnlyCount, 46); assert.equal(audit.unusedHeadroom, 42);
  const readthrough = [uuid(390), ...Array.from({ length: 11 }, (_, index) => uuid(300 + index)), ...Array.from({ length: 11 }, (_, index) => uuid(400 + index)), ...Array.from({ length: 26 }, (_, index) => uuid(500 + index))];
  assert.equal(new Set(readthrough).size, 49); for (const id of readthrough) assert.ok(evidence.identities.includes(id));
  for (const id of value.f.v1.records.obligations.pages.flatMap(page => page.obligations).map(record => record.id)) assert.ok(evidence.identities.includes(id));
  assert.ok(audit.unusedHeadroom >= 0); assert.equal(audit.maximumKnownCount + audit.unusedHeadroom, 96);
  for (const change of [r => r.syntheticIds.push(uuid(999)), r => r.syntheticIds.pop()]) {
    const next = admissionFixture(), registration = next.values.get(next.values.get(next.q.gatewayEvidence.path).v1Registration.path); change(registration);
    await assert.rejects(admitV1BeforeMembers(next.q, next.dependencies), /EXACT_COMPLETE_CONTROL_AUTHORITY_SET_REQUIRED/); assert.equal(next.log.includes('private-reader'), false);
  }
  const overflow = admissionFixture(), registration = overflow.values.get(overflow.values.get(overflow.q.gatewayEvidence.path).v1Registration.path); registration.syntheticIds = Array.from({ length: 93 }, (_, index) => uuid(2000 + index));
  await assert.rejects(admitV1BeforeMembers(overflow.q, overflow.dependencies)); assert.equal(overflow.log.includes('private-reader'), false);
});
test('all four producer oracle corpora are hashed without auth secrets and omissions refuse late admission', async () => {
  const safe = v1OracleIdentityEvidence({ id: uuid(1), access_token: uuid(999), nested: { secret: uuid(998), actual: uuid(2) } });
  assert.deepEqual(safe.identities, [uuid(1), uuid(2)]); assert.equal(validateV1OracleIdentityEvidence(safe), safe);
  assert.throws(() => validateV1OracleIdentityEvidence({ ...safe, identities: safe.identities.slice(1) }), /ORACLE_IDENTITY_HASH_REQUIRED/);
  const value = admissionFixture(), final = value.values.get(value.q.producerEvidence.path); final.oracleIdentityEvidence = v1OracleIdentityEvidence(uuid(1));
  await assert.rejects(admitV1BeforeMembers(value.q, value.dependencies), /ALL_FOUR_PHASE_PAYLOAD_ORACLES_REQUIRED/); assert.equal(value.log.includes('private-reader'), false);
});


function installedAndroidDouble(physical = true) {
  const appId = 'ai.caseops.mobile.dev.localacceptance', app = `/data/user/0/${appId}`, provider = '/storage/emulated/0/Download';
  const apk = '/data/app/~~unit==/unit/base.apk', calls = [], state = { usbDevPath: 'usb:1-2.5', pageSizeRaw: '4096\n', bootReads: 0, statFailure: null };
  const f = { appId, udid: physical ? 'CASEOPSUNITUSB01' : 'emulator-5584', appPath: '/unit/never-opened.apk',
    environment: 'docker-integration', syntheticDataOnly: true, coreInventory: 'native-core-2026-10-25',
    androidTransport: { adbPort: physical ? 5042 : 5038, appiumUrl: physical ? 'http://127.0.0.1:4729' : 'http://127.0.0.1:4725',
      systemPort: physical ? 8206 : 8202, ...(physical ? { transportMode: 'usb-reverse' } : {}) } };
  const environment = { PATH: '/unit/no-adb', HOME: '/unit/home', ADB_SERVER_SOCKET: `tcp:127.0.0.1:${f.androidTransport.adbPort}`,
    CASEOPS_MOBILE_CORE_PASSWORD: 'PRIVATE_UNIT_VALUE_MUST_NOT_REACH_ADB',
    ...(physical ? { CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE: 'usb-reverse' } : {}) };
  const metadata = privateRoot => `directory|${privateRoot ? 10087 : 1023}|10|${privateRoot ? 2 : 3}|0|2026-10-30 00:00:00 +0000|2026-10-30 00:00:00 +0000`;
  const command = (file, args, options) => {
    assert.equal(file, 'adb', 'NO_LIVE_OR_NON_ADB_COMMAND_FALLTHROUGH'); assert.deepEqual(args.slice(0, 2), ['-s', f.udid]);
    assert.equal(options.shell, false); assert.ok(options.timeout > 0 && options.timeout <= 20000); assert.ok(options.maxBuffer <= 1048576);
    assert.equal(options.env.ADB_SERVER_SOCKET, environment.ADB_SERVER_SOCKET);
    assert.equal(Object.hasOwn(options.env, 'CASEOPS_MOBILE_CORE_PASSWORD'), false); calls.push({ args: args.slice(2), environment: { ...options.env } });
    const a = args.slice(2), joined = a.join(' '); let value;
    if (joined === `shell pm list packages ${appId}`) value = `package:${appId}`;
    else if (joined === `shell pm path ${appId}`) value = `package:${apk}`;
    else if (joined === `shell sha256sum ${apk}`) value = `${binary}  ${apk}`;
    else if (joined === 'get-state') value = 'device';
    else if (joined === 'shell id -u') value = physical ? '2000' : '0';
    else if (joined === 'shell am get-current-user') value = '0';
    else if (joined === 'shell getprop ro.build.version.sdk') value = '36';
    else if (joined === 'shell getprop ro.product.cpu.abi') value = 'arm64-v8a';
    else if (joined === 'shell getprop ro.kernel.qemu') { assert.equal(physical, true); value = '0'; }
    else if (joined === 'get-devpath') { assert.equal(physical, true); value = state.usbDevPath; }
    else if (joined === 'emu avd name') { assert.equal(physical, false); value = 'CaseOps_Pixel9_API36_arm64\nOK\n'; }
    else if (joined === 'shell cat /proc/sys/kernel/random/boot_id') value = state.bootSequence?.[state.bootReads++] ?? '11111111-2222-4333-8444-555555555555';
    else if (joined === 'shell getconf PAGESIZE') { assert.equal(physical, true); assert.equal(options.timeout, 5000); assert.equal(options.maxBuffer, 64); if (state.pageFailure) throw state.pageFailure; value = state.pageSizeRaw; }
    else if (joined === `shell cmd package list packages -U ${appId}`) value = `package:${appId} uid:10087`;
    else if (joined === `shell run-as ${appId} id -u`) { assert.equal(physical, true); value = '10087'; }
    else if (joined === `shell run-as ${appId} pwd`) { assert.equal(physical, true); value = app; }
    else if (joined === `shell run-as ${appId} readlink -f ${app}`) { assert.equal(physical, true); value = app; }
    else if (joined === 'shell readlink -f /sdcard/Download') value = provider;
    else if (joined === `shell readlink -f ${app}`) { assert.equal(physical, false); value = app; }
    else if (a[0] === 'shell' && a[1] === '-T') {
      assert.equal(a.length, 3); const source = a[2], target = /'([^']*)'$/.exec(source)?.[1];
      if (physical) {
        assert.ok(source.includes("'env' 'LC_ALL=C' '/system/bin/toybox' 'stat' '-c'"));
        assert.equal(source.startsWith(`'run-as' '${appId}'`), target !== provider);
        if (target.endsWith(`/Android/data/${appId}`)) {
          if (state.statFailure) throw state.statFailure;
          throw Object.assign(new Error('UNIT_OWNED_MISSING_EXTERNAL'), { status: 1, signal: null, stdout: '', stderr: `stat: '${target}': No such file or directory\n` });
        }
      } else assert.ok(source.includes('CASEOPS_ANDROID_STAT_V1'));
      if (target === app) value = metadata(true);
      else if (target === provider) value = metadata(false);
      else { assert.equal(target, `/storage/emulated/0/Android/data/${appId}`); value = 'ABSENT'; }
    } else assert.fail(`UNEXPECTED_OWNED_ANDROID_COMMAND: ${a[0]}`);
    return options.encoding === 'utf8' ? value : Buffer.from(value);
  };
  return { fixture: f, environment, command, calls, state, app, provider };
}
function withInstalledAndroidDouble(f, action) {
  const original = childProcess.execFileSync; childProcess.execFileSync = f.command; syncBuiltinESMExports();
  try { return action(); } finally { childProcess.execFileSync = original; syncBuiltinESMExports(); }
}

test('actual observeInstalled composes binary and run-as attestation with fixture mode and filtered explicit tool environment', () => {
  for (const explicitEnvironmentMode of [true, false]) {
    const f = installedAndroidDouble(); if (!explicitEnvironmentMode) delete f.environment.CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE;
    const observed = withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment));
    assert.equal(observed.binaryHash, binary); assert.equal(observed.appDataPath, f.app); assert.equal(observed.pageSizeBytes, 4096); assert.equal(Object.hasOwn(observed, 'pageSizeRequired'), false);
    assert.equal(observed.transportMode, 'usb-reverse'); assert.equal(observed.deviceKind, 'physical'); assert.equal(observed.access, 'run-as');
    assert.equal(observed.shellUid, 2000); assert.equal(observed.runAsUid, 10087); assert.equal(observed.usbDevPath, f.state.usbDevPath);
    assert.equal(observed.apiLevel, 36); assert.equal(observed.abi, 'arm64-v8a'); assert.equal(observed.qemuOff, true);
    assert.equal(Object.hasOwn(observed, 'rootUid'), false); assert.equal(Object.hasOwn(observed, 'avdName'), false);
    assert.ok(f.calls.some(row => row.args.join(' ') === `shell run-as ${f.fixture.appId} id -u`));
    assert.ok(f.calls.every(row => row.environment.CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE === (explicitEnvironmentMode ? 'usb-reverse' : undefined)));
    assert.equal(f.calls.some(row => ['root', 'push', 'install', 'emu', 'reboot'].includes(row.args[0])), false);
  }
});

test('actual observeInstalled rejects fixture and explicit environment mode disagreement before device reads', () => {
  for (const patch of [{ CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE: 'emulator' }, { CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE: 'unknown' }]) {
    const f = installedAndroidDouble(); Object.assign(f.environment, patch);
    assert.throws(() => withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment)), /V1_ANDROID_TRANSPORT_MODE_MISMATCH/);
    assert.equal(f.calls.length, 0);
  }
  const f = installedAndroidDouble(); delete f.fixture.androidTransport.transportMode;
  assert.throws(() => withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment)), /V1_ANDROID_TRANSPORT_MODE_MISMATCH/);
  assert.equal(f.calls.length, 0);
});

test('actual observeInstalled keeps the complete historical emulator return shape and rooted AVD path', () => {
  const f = installedAndroidDouble(false), observed = withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment));
  assert.deepEqual(observed, { platform: 'android', udid: f.fixture.udid, appId: f.fixture.appId, binaryHash: binary,
    bootId: '11111111-2222-4333-8444-555555555555', appDataPath: f.app,
    appDataIdentity: { kind: 'directory', uid: 10087, device: '10', inode: '2' }, pageSizeRequired: 16384 });
  assert.ok(f.calls.some(row => row.args.join(' ') === 'emu avd name'));
  assert.equal(f.calls.some(row => row.args.includes('run-as')), false);
});

test('actual observeInstalled returns physical USB identity so later installed fences detect a changed endpoint', () => {
  const f = installedAndroidDouble(), first = withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment));
  f.state.usbDevPath = 'usb:2-3';
  const later = withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment));
  assert.notDeepEqual(later, first); assert.equal(later.usbDevPath, 'usb:2-3'); assert.equal(later.binaryHash, first.binaryHash);
});

test('actual observeInstalled retains original run-as stat denial without fallback or private body reads', () => {
  const f = installedAndroidDouble(); f.state.statFailure = Object.assign(new Error('UNIT_ORIGINAL_PRIVATE_STAT_DENIED'), {
    status: 1, signal: null, stdout: '', stderr: `stat: '/storage/emulated/0/Android/data/${f.fixture.appId}': Permission denied\n` });
  assert.throws(() => withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment)), error => error === f.state.statFailure);
  assert.equal(f.calls.some(row => row.args.some(value => value.includes('CASEOPS_ANDROID_READ_FD_V1'))), false);
  assert.equal(f.calls.some(row => ['root', 'push', 'install', 'rm'].includes(row.args[0])), false);
});


function layoutAdmission(pageSize = 4096, physical = true) {
  const x = admissionFixture(), d = installedAndroidDouble(physical); d.state.pageSizeRaw = `${pageSize}\n`;
  const actual = withInstalledAndroidDouble(d, () => observeInstalled(d.fixture, 'android', binary, d.environment));
  x.q.platform = 'android';
  const seen = new Set(); const change = value => {
    if (!value || typeof value !== 'object' || seen.has(value)) return; seen.add(value);
    for (const [key, child] of Object.entries(value)) {
      if (child === 'ai.caseops.mobile.dev.simulatoracceptance') value[key] = d.fixture.appId;
      else if (child === 'synthetic-iphone') value[key] = d.fixture.udid;
      else if (key === 'platform' && child === 'ios') value[key] = 'android';
      else change(child);
    }
  };
  for (const value of x.values.values()) change(value);
  for (const f of [x.f, x.b]) {
    f.androidTransport = d.fixture.androidTransport;
    if (physical) { f.apiOrigin = 'https://127.0.0.1:8443'; f.auth.webOrigin = 'https://127.0.0.1:3443'; }
  }
  if (physical) Object.assign(x.values.get(x.q.buildReceipt.path), { apiOrigin: x.f.apiOrigin, webOrigin: x.f.auth.webOrigin });
  validateAndroidTransport(x.f, 'android', x.values.get(x.q.buildReceipt.path));
  for (const ref of [x.q.deviceEvidence, x.q.installedEvidence]) {
    const value = x.values.get(ref.path); delete value.deviceTypeIdentifier;
    Object.assign(value, structuredClone(actual), { pageSizeBytes: pageSize });
  }
  x.dependencies.installed = () => structuredClone(actual); x.actual = actual;
  return x;
}
test('actual physical getconf accepts only4096 or16384 and brackets the observation with the same boot', () => {
  for (const pageSize of [4096, 16384]) {
    const f = installedAndroidDouble(); f.state.pageSizeRaw = `${pageSize}\n`;
    const value = withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment));
    assert.equal(value.pageSizeBytes, pageSize); assert.equal(value.androidLayout.returnedOutputBytes.pageSize, Buffer.byteLength(f.state.pageSizeRaw));
    assert.equal(value.androidLayout.acceptanceScope, 'physical-workflow-only'); assert.equal(value.androidLayout.sixteenKEmulatorAcceptance, false);
    assert.equal(value.androidLayout.bootId, value.bootId); assert.deepEqual(androidLayoutSummary(value), { androidAcceptanceScope: 'physical-workflow-only', androidPageSizeBytes: pageSize, sixteenKEmulatorAcceptance: false, sixteenKEmulator83Acceptance: 'required-separately' });
  }
  for (const raw of ['8192\n', '4096\nextra', '', '4096 '.repeat(20)]) {
    const f = installedAndroidDouble(); f.state.pageSizeRaw = raw;
    assert.throws(() => withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment)), /ANDROID_(?:PHYSICAL_PAGE_SIZE_REQUIRED|LAYOUT_OUTPUT_BOUND)/);
  }
  const f = installedAndroidDouble(); f.state.bootSequence = ['11111111-2222-4333-8444-555555555555', '11111111-2222-4333-8444-555555555555', 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'];
  assert.throws(() => withInstalledAndroidDouble(f, () => observeInstalled(f.fixture, 'android', binary, f.environment)), /ANDROID_LAYOUT_BOOT_CHANGED/);
  const failed = installedAndroidDouble(); failed.state.pageFailure = new Error('UNIT_GETCONF_FAILURE');
  assert.throws(() => withInstalledAndroidDouble(failed, () => observeInstalled(failed.fixture, 'android', binary, failed.environment)), error => error === failed.state.pageFailure);
});
test('complete V1 admission binds4K and16K physical current layout to both immutable receipts before readers', async () => {
  for (const page of [4096, 16384]) { const x = layoutAdmission(page), result = await admitV1BeforeMembers(x.q, x.dependencies); assert.equal(result.installed.pageSizeBytes, page); assert.equal(x.log.filter(v => v === 'private-reader').length, 2); }
  for (const mutation of [x => { x.values.get(x.q.deviceEvidence.path).pageSizeBytes = 16384; }, x => { x.values.get(x.q.installedEvidence.path).bootId = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'; },
    x => { x.values.get(x.q.deviceEvidence.path).androidLayout.binaryHash = 'f'.repeat(64); }, x => { x.values.get(x.q.installedEvidence.path).androidLayout = undefined; }, x => { x.values.get(x.q.deviceEvidence.path).runAsUid++; }]) {
    const x = layoutAdmission(); mutation(x); await assert.rejects(admitV1BeforeMembers(x.q, x.dependencies)); assert.equal(x.log.includes('private-reader'), false);
  }
});
test('legacy V1 admission still requires literal16K device evidence and physical flags never certify the emulator path', async () => {
  const good = layoutAdmission(16384, false); await admitV1BeforeMembers(good.q, good.dependencies); assert.equal(good.actual.pageSizeRequired, 16384); assert.deepEqual(androidLayoutSummary(good.actual), {});
  const bad = layoutAdmission(4096, false); await assert.rejects(admitV1BeforeMembers(bad.q, bad.dependencies)); assert.equal(bad.log.includes('private-reader'), false);
  const x = layoutAdmission(); const disguised = { ...x.f, androidTransport: { adbPort: 5038, appiumUrl: 'http://127.0.0.1:4725', systemPort: 8202 } };
  assert.throws(() => validateAndroidLayoutEvidence(disguised, x.actual, x.values.get(x.q.deviceEvidence.path), x.values.get(x.q.installedEvidence.path)), /ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR/);
});


test('actual Root four-field USB transport composes with layout validation and rejects invented fifth field before admission', async () => {
  const x = layoutAdmission(4096), transport = validateAndroidTransport(x.f, 'android', x.values.get(x.q.buildReceipt.path));
  assert.deepEqual(Object.keys(transport).sort(), ['adbPort', 'appiumUrl', 'systemPort', 'transportMode']);
  assert.equal(Object.hasOwn(x.f.androidTransport, 'deviceKind'), false);
  validateAndroidLayoutEvidence(x.f, x.actual, x.values.get(x.q.deviceEvidence.path), x.values.get(x.q.installedEvidence.path));
  const admitted = await admitV1BeforeMembers(x.q, x.dependencies); assert.equal(admitted.installed.pageSizeBytes, 4096);
  const forged = { ...x.f, androidTransport: { ...x.f.androidTransport, deviceKind: 'physical' } };
  assert.throws(() => validateAndroidTransport(forged, 'android', x.values.get(x.q.buildReceipt.path)), /ANDROID_TRANSPORT_SCHEMA_REQUIRED/);
  assert.throws(() => validateAndroidLayoutEvidence(forged, x.actual, x.values.get(x.q.deviceEvidence.path), x.values.get(x.q.installedEvidence.path)), /ANDROID_LAYOUT_PHYSICAL_PROFILE_REQUIRED/);
});
