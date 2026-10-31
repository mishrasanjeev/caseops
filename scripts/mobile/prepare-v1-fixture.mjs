import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { sourceSnapshot } from './source-snapshot.mjs';
import { v1Inventory } from '../../apps/mobile/e2e/v1-workflows-inventory.mjs';
import { readV1Reference, v1Reference, validateV1ExecutionFixture, validateV1FixtureAggregate, strictV1Routes, v1Hash, reconcileV1ControlIdentities } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { V1_CASE_CONTROL_LIMITS } from '../../apps/mobile/e2e/v1-workflows-inventory.mjs';
import { pendingV1ProducerPlan, pendingV1InboxPlan } from '../../apps/mobile/e2e/v1-workflows-fixture.mjs';
import { pendingV1ViewerPlan } from '../../apps/mobile/e2e/v1-workflows-viewer.mjs';

const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
export function pendingV1Request() {
  return { schemaVersion: 1, inventoryId: v1Inventory.inventoryId, preparedOnly: true, readyForLive: false,
    platform: 'PENDING', repoRoot: ROOT, reportRoot: '/OWNED_FUTURE_V1_REPORT_ROOT_PENDING',
    expectedSourceSha: 'FUTURE_CANONICAL_SOURCE_PENDING', expectedSourceFingerprint: 'FUTURE_CANONICAL_INPUTS_PENDING',
    expectedInputFileCount: null, expectedBinaryHash: 'ACTUAL_FUTURE_PLATFORM_BINARY_PENDING', expectedHarnessFingerprint: 'FROZEN_V1_HARNESS_PENDING',
    fixtureEvidence: null, buildReceipt: null, dockerReceipt: null, deviceEvidence: null, installedEvidence: null,
    authObservation: null, producerEvidence: null, viewerEvidence: null, inboxEvidence: null, aggregateFixtureEvidence: null, controlsEvidence: null, gatewayEvidence: null, codeClosure: null,
    members: [{ credentialEvidence: null, fixtureEvidence: null, authObservation: null }, { credentialEvidence: null, fixtureEvidence: null, authObservation: null }],
    pending: ['canonical-source-build-backend', 'actual-installed-device-and-family', 'two-real-browser-MFA-observations',
      'normal-API-dataset-with-three-supported-IP-types', 'normal-api-viewer-MFA-and-readonly-work', 'owned-IP-wall-and-stale-work-grant', 'empty-hearing-channel-backend-proof', 'registered-bounded-QA-control-protocol',
      'actual-native-segment-control-observations', 'strict-exact-gateway-routes-and-request-body-observations'] };
}
export function pendingV1ControlRegistration() {
  return { schemaVersion: 1, kind: 'registered-v1-qa-controls', preparedOnly: true, readyForLive: false, observed: false,
    environment: 'docker-integration', syntheticDataOnly: true, noPaidMarker: 'no-paid-providers', directDatabaseWrites: false,
    nativeMutationsForwardedByControls: false, sourceSha: 'FUTURE_CANONICAL_SOURCE_PENDING', runId: 'FUTURE_OWNED_LEDGER_PENDING',
    registrationId: null, companyId: null, expiresAt: null, implementationSha256: null, backendRevision: null, webRevision: null,
    capabilities: [], caseControlLimits: V1_CASE_CONTROL_LIMITS, syntheticIds: [], exactRoutes: [], ownerExactRoutes: [], ownerRecipes: [], actors: null, inboxNotifications: [],
    authorityEvidence: null, postgresEvidence: null,
    pending: ['actual-final-ledger-and-source', 'actual-two-company-and-owner-private-file-mappings-with-descriptor-uid',
      'normal-api-policy-and-restoration-recipes', 'exact-synthetic-parent-child-source-identities',
      'attested-current-PG-system-identity-and-readonly-observer', 'explicit-disabled-default-operator-enable', 'complete-registration-and-runtime-proofs'] };
}
export function pendingV1ProjectionRequest() {
  return { schemaVersion: 1, inventoryId: v1Inventory.inventoryId, preparedOnly: true, readyForLive: false, repoRoot: ROOT, platform: 'PENDING',
    baseFixtureEvidence: null, secondaryFixtureEvidence: null, datasetEvidence: null, producerEvidence: null, viewerEvidence: null, inboxEvidence: null,
    aggregateFixtureEvidence: null, buildReceipt: null, dockerReceipt: null, authObservation: null, controlsEvidence: null, gatewayEvidence: null, nativeSelectorEvidence: null };
}
export function composeV1Fixture(request, { read = readV1Reference, snapshot = sourceSnapshot } = {}) {
  assert.equal(request?.schemaVersion, 1); assert.equal(request.readyForLive, true, 'FUTURE_V1_PROJECTION_PENDING'); assert.equal(request.preparedOnly, false);
  assert.equal(request.repoRoot, ROOT); assert.ok(v1Inventory.platforms.includes(request.platform));
  for (const key of ['baseFixtureEvidence', 'secondaryFixtureEvidence', 'datasetEvidence', 'producerEvidence', 'viewerEvidence', 'inboxEvidence', 'aggregateFixtureEvidence', 'buildReceipt', 'dockerReceipt', 'authObservation', 'controlsEvidence', 'gatewayEvidence', 'nativeSelectorEvidence']) v1Reference(request[key]);
  const core = read(request.baseFixtureEvidence), dataset = read(request.datasetEvidence), producer = read(request.producerEvidence), build = read(request.buildReceipt), isolation = read(request.dockerReceipt);
  const source = snapshot(ROOT); assert.equal(source.sourceDirty, false); assert.equal(build.sourceDirty, false);
  assert.equal(build.sourceSha, source.sourceSha); assert.equal(build.sourceFingerprint, source.sourceFingerprint); assert.equal(build.inputFileCount, source.inputFileCount);
  assert.equal(isolation.backendSha, source.sourceSha); assert.equal(isolation.webSha, source.sourceSha);
  assert.equal(producer.kind, 'actual-normal-api-v1-fixture'); assert.equal(producer.observed, true); assert.equal(producer.sourceSha, source.sourceSha);
  assert.equal(producer.directDatabaseWrites, false); assert.equal(producer.automaticRetry, false); assert.equal(producer.mutationUncertain, false);
  assert.equal(producer.companyId, dataset.companyId); assert.equal(producer.membershipId, dataset.membershipId);
  assert.equal(core.companyId, dataset.companyId); assert.equal(core.membershipId, dataset.membershipId);
  assert.equal(dataset.v1.preparedOnly, true); assert.equal(dataset.v1.readyForLive, false); assert.equal(producer.nativeReady, false);
  const aggregate = validateV1FixtureAggregate(read(request.aggregateFixtureEvidence), source.sourceSha, read);
  assert.deepEqual(aggregate.stages[3].receiptEvidence, request.producerEvidence); assert.deepEqual(aggregate.stages[1].receiptEvidence, request.viewerEvidence); assert.deepEqual(aggregate.stages[2].receiptEvidence, request.inboxEvidence);
  assert.deepEqual(producer.viewerEvidence, request.viewerEvidence);
  const viewer = read(request.viewerEvidence); assert.equal(viewer.kind, 'actual-normal-api-v1-viewer'); assert.equal(viewer.observed, true);
  assert.equal(viewer.sourceSha, source.sourceSha); assert.equal(viewer.role, 'viewer'); assert.equal(viewer.mfaEnrolled, true);
  assert.equal(viewer.capabilities.includes('matters:write'), false); assert.equal(viewer.mutationUncertain, false);
  assert.deepEqual(viewer.buildReceipt, request.buildReceipt); assert.deepEqual(viewer.dockerReceipt, request.dockerReceipt);
  assert.deepEqual(dataset.v1.records.policy.viewerEvidence, request.viewerEvidence);
  assert.deepEqual(dataset.v1.records.policy.readOnly, viewer.readOnlyWork);
  assert.equal(dataset.v1.inventoryId, v1Inventory.inventoryId); assert.equal(dataset.v1.platform, request.platform);
  assert.deepEqual(core.buildReceipt, request.buildReceipt); assert.deepEqual(core.isolationEvidence, request.dockerReceipt);
  const selectors = read(request.nativeSelectorEvidence); assert.equal(selectors.observed, true); assert.equal(selectors.udid, core.udid);
  assert.deepEqual(selectors.buildReceipt, request.buildReceipt); assert.equal(selectors.platform, request.platform);
  const controls = read(request.controlsEvidence); assert.equal(controls.kind, 'registered-v1-qa-controls'); assert.equal(controls.observed, true);
  assert.equal(controls.sourceSha, source.sourceSha); assert.equal(controls.runId, isolation.gatewayRunId);
  const fixture = { ...structuredClone(core), v1: { ...structuredClone(dataset.v1), controls: { evidence: request.controlsEvidence, capabilities: controls.capabilities,
    mutationsUseNormalApis: true, directDatabaseWrites: false, noPaidMarker: 'no-paid-providers' }, nativeSelectors: selectors } }; fixture.v1.preparedOnly = false; fixture.v1.readyForLive = true;
  const second = read(request.secondaryFixtureEvidence); assert.equal(second.companyId, viewer.companyId); assert.equal(second.membershipId, viewer.membershipId);
  assert.deepEqual(second.buildReceipt, request.buildReceipt); assert.deepEqual(second.isolationEvidence, request.dockerReceipt);
  assert.equal(second.binarySourceSha, source.sourceSha); assert.equal(second.backendSha, source.sourceSha); assert.equal(second.webSha, source.sourceSha);
  fixture.v1.records.secondCompany = { fixtureEvidence: request.secondaryFixtureEvidence };
  fixture.v1.records.policy.readOnlyMemberFixture = request.secondaryFixtureEvidence;
  fixture.v1.records.policy.viewerEvidence = request.viewerEvidence;
  fixture.v1.records.inbox.deliveryEvidence = request.inboxEvidence;
  fixture.v1.provenance = { ...fixture.v1.provenance, dataset: request.datasetEvidence, producer: request.producerEvidence,
    authObservation: request.authObservation, viewer: request.viewerEvidence, inbox: request.inboxEvidence, aggregateFixture: request.aggregateFixtureEvidence, baseFixture: request.baseFixtureEvidence,
    nativeSelectors: request.nativeSelectorEvidence, controls: request.controlsEvidence, gateway: request.gatewayEvidence };
  validateV1ExecutionFixture(fixture, request.platform);
  const routes = strictV1Routes(fixture.v1.records), gateway = read(request.gatewayEvidence);
  assert.equal(gateway.observed, true); assert.equal(gateway.gatewayRunId, isolation.gatewayRunId); assert.equal(gateway.sourceSha, source.sourceSha);
  assert.deepEqual(gateway.v1ExactRoutes, routes, 'REGISTERED_EXACT_V1_ROUTES_REQUIRED');
  assert.equal(gateway.nativeWorkBodyObservation, 'keys-and-canonical-sha256'); assert.equal(gateway.authorizationValuesRetained, false);
  const identityAudit = reconcileV1ControlIdentities(fixture.v1.records, read(gateway.v1Registration), producer.oracleIdentityEvidence);
  return { fixture, routes, source, producer, identityAudit };
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [mode, file, digest, output] = process.argv.slice(2);
    if (mode === '--pending') { assert.equal(process.argv.length, 3); console.log(JSON.stringify({ request: pendingV1Request(), projection: pendingV1ProjectionRequest(), producer: pendingV1ProducerPlan(), readthrough: { ...pendingV1ProducerPlan(), phase: 'readthrough' },
      viewer: pendingV1ViewerPlan(), inbox: pendingV1InboxPlan(), controls: pendingV1ControlRegistration() }, null, 2)); }
    else {
      assert.equal(mode, '--from-producer'); assert.equal(process.argv.length, 6);
      const request = readV1Reference({ path: file, sha256: digest }, 16384);
      assert.ok(path.isAbsolute(output) && !path.resolve(output).startsWith(ROOT + path.sep), 'OWNED_OUTSIDE_V1_OUTPUT_REQUIRED');
      const result = composeV1Fixture(request), data = Buffer.from(JSON.stringify(result.fixture, null, 2) + '\n');
      fs.writeFileSync(output, data, { flag: 'wx', mode: 0o600 });
      console.log(JSON.stringify({ prepared: true, fixtureEvidence: { path: output, sha256: v1Hash(data) }, inventoryId: v1Inventory.inventoryId,
        nativeExecution: 'not-run', producerOrAuthenticationReplayed: false, intendedCases: 17, expectedPhases: 51 }));
    }
  } catch { console.error('V1_FIXTURE_PROJECTION_REFUSED'); process.exitCode = 1; }
}
