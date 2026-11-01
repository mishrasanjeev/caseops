import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const browserPreflights = new Set(['/api/auth/me', '/api/auth/login', '/api/auth/logout', '/api/auth/refresh',
  '/api/auth/security', '/api/auth/mfa/step-up', '/api/auth/native/authorize']);
function prefixHash(requests) {
  return createHash('sha256').update(JSON.stringify(requests.map(({ sequence, method, route, status, nativeMarker, browserHandoff }) =>
    ({ sequence, method, route, status, nativeMarker, browserHandoff })))).digest('hex');
}
export function checkLedger(state) {
  assert.ok(Number.isSafeInteger(state.lastSequence) && state.lastSequence >= 0 && state.lastSequence <= 500, 'BOUNDED_REQUEST_LEDGER_REQUIRED');
  assert.equal(state.requests?.length, state.lastSequence, 'REQUEST_LEDGER_INCOMPLETE');
  for (const key of ['markerRejected', 'routeRejected']) assert.ok(Number.isSafeInteger(state[key]) && state[key] >= 0, 'GATEWAY_COUNTER_REQUIRED');
  assert.equal(state.overflow, false, 'GATEWAY_EVIDENCE_OVERFLOW');
  for (let index = 0; index < state.requests.length; index++) assert.equal(state.requests[index].sequence, index + 1, 'REQUEST_LEDGER_SEQUENCE_MISMATCH');
}
export function gatewayBaseline(state, receipt) {
  checkLedger(state);
  assert.equal(state.runId, receipt.gatewayRunId, 'WRONG_GATEWAY_RUN');
  if (receipt.gatewayImplementationSha256) assert.equal(state.implementationSha256, receipt.gatewayImplementationSha256, 'GATEWAY_IMPLEMENTATION_MISMATCH');
  const expected = { markerRejected: 0, routeRejected: 0 };
  for (const control of receipt.tlsProof?.gatewayNegativeControls || []) {
    assert.equal(control.status, 403, 'UNPROVEN_GATEWAY_NEGATIVE_CONTROL');
    if (control.code === 'AUTOMATED_MARKER_REQUIRED') expected.markerRejected++;
    else if (control.code === 'ROUTE_NOT_ADMITTED') expected.routeRejected++;
    else throw new Error('UNRECOGNIZED_GATEWAY_NEGATIVE_CONTROL');
  }
  // Do not reset counters or excuse arbitrary earlier failures as fixture setup.
  for (const key of ['markerRejected', 'routeRejected']) assert.equal(state[key], expected[key], 'UNRECONCILED_PREEXISTING_GATEWAY_REJECTION');
  assert.ok(state.requests.every((row) => Number.isInteger(row.status)), 'UNSETTLED_GATEWAY_BASELINE');
  return { runId: state.runId, lastSequence: state.lastSequence, markerRejected: state.markerRejected,
    routeRejected: state.routeRejected, implementationSha256: state.implementationSha256 || null,
    prefixSha256: prefixHash(state.requests) };
}
export function validateTraffic(state, baseline) {
  checkLedger(state);
  assert.equal(state.runId, baseline.runId, 'WRONG_GATEWAY_RUN');
  assert.ok(state.lastSequence >= baseline.lastSequence, 'GATEWAY_LEDGER_RESET');
  assert.equal(prefixHash(state.requests.slice(0, baseline.lastSequence)), baseline.prefixSha256, 'GATEWAY_HISTORY_CHANGED');
  if (baseline.implementationSha256) assert.equal(state.implementationSha256, baseline.implementationSha256, 'GATEWAY_IMPLEMENTATION_CHANGED');
  assert.equal(state.markerRejected, baseline.markerRejected, 'NATIVE_OR_BROWSER_MARKER_MISSING');
  assert.equal(state.routeRejected, baseline.routeRejected, 'UNADMITTED_NATIVE_OR_BROWSER_ROUTE');
  for (const row of state.requests.filter((request) => request.sequence > baseline.lastSequence)) {
    if (row.nativeMarker === false) {
      assert.ok(row.method === 'OPTIONS' && row.browserHandoff === true && browserPreflights.has(row.route), 'APP_REQUEST_MARKER_NOT_PRESENT');
    }
  }
  return state;
}

// The app's compatibility gate reads this public policy through its
// credential-free transport on every foreground, signed in or not; it carries
// no token or code. Signed-out checks exclude exactly this GET and nothing else.
export const PUBLIC_COMPATIBILITY_READ = '/api/auth/native/compatibility';
export function withoutPublicCompatibilityReads(requests) {
  return requests.filter((request) => !(request.method === 'GET' && request.route === PUBLIC_COMPATIBILITY_READ));
}
