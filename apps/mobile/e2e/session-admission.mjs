import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from './evidence.mjs';
import { checkLedger } from './traffic.mjs';

const SOURCE = 'GET /api/auth/native/sessions';
const DELETE_ROUTE = /^DELETE \/api\/auth\/native\/sessions\/([a-zA-Z0-9_-]{1,100})$/;
const REQUEST_ID = /^[a-f0-9]{16}$/;
export const MAX_SESSION_ADMISSION_EVENTS = 64;
const readReference = (reference) => JSON.parse(verifiedFile(reference?.path, reference?.sha256));

function admissionRows(state) {
  checkLedger(state);
  assert.ok(Array.isArray(state.sessionDeleteAdmissions) && state.sessionDeleteAdmissions.length <= MAX_SESSION_ADMISSION_EVENTS, 'BOUNDED_SESSION_ADMISSION_LEDGER_REQUIRED');
  const requestIds = new Set();
  for (const request of state.requests) {
    assert.match(request.requestId || '', REQUEST_ID, 'SESSION_ADMISSION_REQUEST_ID_REQUIRED');
    assert.ok(!requestIds.has(request.requestId), 'DUPLICATE_SESSION_ADMISSION_REQUEST_ID');
    requestIds.add(request.requestId);
    assert.ok(Number.isInteger(request.status), 'UNSETTLED_SESSION_ADMISSION_LEDGER');
  }
  const sourceIds = new Set();
  return state.sessionDeleteAdmissions.map((event) => {
    assert.equal(event.type, 'session-delete-admitted', 'SESSION_ADMISSION_EVENT_REQUIRED');
    assert.match(event.route || '', DELETE_ROUTE, 'EXACT_SESSION_ADMISSION_ROUTE_REQUIRED');
    assert.match(event.sourceRequestId || '', REQUEST_ID, 'SESSION_ADMISSION_SOURCE_REQUEST_REQUIRED');
    assert.ok(!sourceIds.has(event.sourceRequestId), 'DUPLICATE_SESSION_ADMISSION_SOURCE');
    sourceIds.add(event.sourceRequestId);
    const source = state.requests.find(({ requestId }) => requestId === event.sourceRequestId);
    assert.ok(source && `${source.method} ${source.route}` === SOURCE && source.status === 200
      && source.nativeMarker === true && source.browserHandoff === false, 'SUCCESSFUL_MARKED_NATIVE_SESSION_SOURCE_REQUIRED');
    return { event, source };
  });
}

export function validateSessionDeletePolicy(descriptor, routeEvidence, isolationEvidence, receipt) {
  assert.ok(Array.isArray(descriptor.routes) && descriptor.routes.length <= 500
    && descriptor.routes.every((route) => typeof route === 'string' && route.length <= 400), 'GATEWAY_ROUTE_INVENTORY_REQUIRED');
  assert.equal(new Set(descriptor.routes).size, descriptor.routes.length, 'DUPLICATE_GATEWAY_ROUTE');
  if (descriptor.routeInventoryEvidence) {
    assert.deepEqual(readReference(descriptor.routeInventoryEvidence).routes, descriptor.routes, 'GATEWAY_ROUTE_SOURCE_CHANGED');
  }
  assert.ok(descriptor.routes.includes(SOURCE), 'DEVICE_SESSION_LIST_ROUTE_MISSING');
  const deletes = descriptor.routes.filter((route) => route.startsWith('DELETE /api/auth/native/sessions'));
  for (const route of deletes) assert.match(route, DELETE_ROUTE, 'SESSION_DELETE_WILDCARD_FORBIDDEN');
  const policy = descriptor.dynamicAdmissions?.nativeCurrentSessionDelete;
  if (!policy) {
    assert.ok(deletes.length > 0, 'CURRENT_SESSION_DELETE_ADMISSION_MISSING');
    return { mode: 'static', routeEvidence, routes: deletes };
  }
  assert.equal(descriptor.schemaVersion, 2, 'DYNAMIC_SESSION_POLICY_VERSION_REQUIRED');
  for (const [key, value] of Object.entries({ kind: 'native-current-session-delete-v1', sourceRoute: SOURCE,
    sourceListLimit: 50, maxLiveIds: 1, maxAdmissionEvents: MAX_SESSION_ADMISSION_EVENTS, nativeBearerOnly: true, cookiesAllowed: false, currentOnly: true,
    unrevokedOnly: true, consumeOnAttempt: true,
    requestEvidenceLink: 'sessionDeleteAdmissions[].sourceRequestId -> requests[].requestId', liveExecutionProofRequiredAt: 'NATIVE-20' })) {
    assert.equal(policy[key], value, 'DYNAMIC_SESSION_POLICY_INVARIANT_MISMATCH');
  }
  assert.equal(receipt.environment, 'docker-integration', 'REAL_DOCKER_FIXTURE_REQUIRED');
  assert.equal(receipt.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
  assert.equal(policy.gatewayRunId, receipt.gatewayRunId, 'DYNAMIC_SESSION_POLICY_RUN_MISMATCH');
  assert.match(policy.implementationSha256 || '', /^[a-f0-9]{64}$/, 'DYNAMIC_SESSION_IMPLEMENTATION_HASH_REQUIRED');
  assert.equal(policy.implementationSha256, receipt.gatewayImplementationSha256, 'DYNAMIC_SESSION_IMPLEMENTATION_MISMATCH');
  assert.equal(policy.implementationEvidence?.sha256, policy.implementationSha256, 'DYNAMIC_SESSION_IMPLEMENTATION_MISMATCH');
  const sourcePath = fileURLToPath(new URL('../../../scripts/mobile/local-gateway.py', import.meta.url));
  assert.equal(path.resolve(policy.implementationEvidence?.path || ''), path.resolve(sourcePath), 'REVIEWED_GATEWAY_SOURCE_REQUIRED');
  verifiedFile(policy.implementationEvidence.path, policy.implementationSha256);
  assert.equal(path.resolve(policy.isolationEvidence?.path || ''), path.resolve(isolationEvidence.path), 'DYNAMIC_SESSION_ISOLATION_REFERENCE_MISMATCH');
  assert.equal(policy.isolationEvidence?.sha256, isolationEvidence.sha256, 'DYNAMIC_SESSION_ISOLATION_REFERENCE_MISMATCH');
  assert.deepEqual(readReference(policy.isolationEvidence), receipt, 'DYNAMIC_SESSION_ISOLATION_CHANGED');
  const status = readReference(policy.statusEvidence);
  assert.equal(status.runId, policy.gatewayRunId, 'DYNAMIC_SESSION_POLICY_RUN_MISMATCH');
  assert.equal(status.implementationSha256, policy.implementationSha256, 'DYNAMIC_SESSION_IMPLEMENTATION_MISMATCH');
  assert.equal(status.markerRejected, 0, 'DYNAMIC_SESSION_POLICY_REJECTED_TRAFFIC');
  assert.equal(status.routeRejected, 0, 'DYNAMIC_SESSION_POLICY_REJECTED_TRAFFIC');
  admissionRows(status);
  return { mode: 'dynamic', routeEvidence, policy };
}

export function configuredSessionDeleteAdmission(fixture) {
  const configured = fixture.nativeSessionDeleteAdmission;
  assert.ok(configured, 'NATIVE_SESSION_DELETE_ADMISSION_REQUIRED');
  const receipt = readReference(fixture.isolationEvidence);
  assert.equal(receipt.gatewayRunId, fixture.gatewayRunId, 'DYNAMIC_SESSION_POLICY_RUN_MISMATCH');
  const admitted = validateSessionDeletePolicy(readReference(configured.routeEvidence), configured.routeEvidence,
    fixture.isolationEvidence, receipt);
  assert.deepEqual(configured, admitted, 'CONFIGURED_SESSION_ADMISSION_CHANGED');
  return admitted;
}

export function proveCurrentSessionDeletion(before, after, admission) {
  assert.equal(after.runId, before.runId, 'SESSION_ADMISSION_RUN_CHANGED');
  assert.ok(after.lastSequence >= before.lastSequence, 'SESSION_ADMISSION_LEDGER_RESET');
  assert.deepEqual(after.requests.slice(0, before.requests.length), before.requests, 'SESSION_ADMISSION_HISTORY_CHANGED');
  const requests = after.requests.filter(({ sequence }) => sequence > before.lastSequence);
  const deletes = requests.filter(({ method }) => method === 'DELETE');
  assert.equal(deletes.length, 1, 'DEVICE_REVOCATION_NOT_EXACTLY_ONCE');
  const deletion = deletes[0];
  assert.match(`DELETE ${deletion.route}`, DELETE_ROUTE, 'EXACT_NATIVE_DEVICE_REVOCATION_REQUIRED');
  assert.equal(deletion.status, 204, 'DEVICE_REVOCATION_NOT_ACKNOWLEDGED');
  assert.equal(deletion.nativeMarker, true, 'MARKED_NATIVE_DEVICE_REVOCATION_REQUIRED');
  assert.equal(deletion.browserHandoff, false, 'NATIVE_DEVICE_REVOCATION_REQUIRED');
  if (admission.mode === 'static') {
    assert.ok(admission.routes.includes(`DELETE ${deletion.route}`), 'UNADMITTED_STATIC_SESSION_DELETE');
    return { mode: 'static', deleteSequence: deletion.sequence };
  }
  assert.equal(admission.mode, 'dynamic', 'SESSION_ADMISSION_MODE_REQUIRED');
  assert.equal(after.runId, admission.policy.gatewayRunId, 'DYNAMIC_SESSION_POLICY_RUN_MISMATCH');
  for (const state of [before, after]) {
    assert.equal(state.implementationSha256, admission.policy.implementationSha256, 'DYNAMIC_SESSION_IMPLEMENTATION_MISMATCH');
    assert.equal(state.markerRejected, 0, 'DYNAMIC_SESSION_POLICY_REJECTED_TRAFFIC');
    assert.equal(state.routeRejected, 0, 'DYNAMIC_SESSION_POLICY_REJECTED_TRAFFIC');
    admissionRows(state);
  }
  assert.deepEqual(after.sessionDeleteAdmissions.slice(0, before.sessionDeleteAdmissions.length),
    before.sessionDeleteAdmissions, 'SESSION_ADMISSION_HISTORY_CHANGED');
  const applicable = admissionRows(after).filter(({ source }) => source.sequence < deletion.sequence);
  const current = applicable.at(-1);
  assert.ok(current && current.source.sequence > before.lastSequence, 'FRESH_CURRENT_SESSION_ADMISSION_REQUIRED');
  assert.equal(current.event.route, `DELETE ${deletion.route}`, 'DELETE_TARGET_NOT_LATEST_CURRENT_SESSION');
  assert.match(deletion.requestId || '', REQUEST_ID, 'SESSION_ADMISSION_REQUEST_ID_REQUIRED');
  return { mode: 'dynamic', sourceRequestId: current.event.sourceRequestId, sourceSequence: current.source.sequence,
    deleteRequestId: deletion.requestId, deleteSequence: deletion.sequence,
    currentSessionId: DELETE_ROUTE.exec(current.event.route)[1], implementationSha256: admission.policy.implementationSha256 };
}
