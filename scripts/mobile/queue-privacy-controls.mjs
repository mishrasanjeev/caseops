import assert from 'node:assert/strict';
import { v1PrivateReference } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { readV1Member } from '../../apps/mobile/e2e/v1-workflows-credentials.mjs';
import { QP, hash as v1Hash } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
const V1_CONTROL_CAPABILITIES=QP.capabilities;
const V1_CASE_CONTROL_LIMITS=QP.caseControls;

export const V1_CONTROL_PROTOCOL = Object.freeze({ schemaVersion: 1, pathname: '/__caseops_e2e/v1-control',
  perReadMs: 5000, completionMs: 20000, statusReads: 1, intervalMs: 200, responseBytes: 1048576,
  mutationRetries: 0, nativeMutationForwarding: false, finalCleanupOperations: 1 });
const writeCapabilities = new Set(['changeAnchor','armPrivacyAckLoss','closeCaseControls','closeRunControls']);
function noSecrets(value) {
  if (Array.isArray(value)) { value.forEach(noSecrets); return; }
  if (value && typeof value === 'object') for (const [key, item] of Object.entries(value)) {
    assert.ok(!/(password|secret|token|authorization|cookie)/i.test(key), 'PUBLIC_V1_CONTROL_ARGUMENTS_REQUIRED'); noSecrets(item);
  }
}
async function boundedResponse(response, maximum) {
  const reader = response.body?.getReader(); assert.ok(reader, 'V1_CONTROL_BODY_REQUIRED'); const buffers = []; let count = 0;
  try { for (;;) { const { done, value } = await reader.read(); if (done) break; count += value.length; assert.ok(count <= maximum, 'V1_CONTROL_RESPONSE_BOUND'); buffers.push(value); } }
  finally { try { await reader.cancel(); } finally { reader.releaseLock(); } }
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(buffers))); }
  catch { throw Error('V1_CONTROL_JSON_REQUIRED'); }
}
/** Client for the separately reviewed, owned QA gateway control registration.
 * It is not a tenant API or a native-auth bypass. The registration must confine
 * every normal API mutation/read to its admitted synthetic IDs, preserve source
 * fences and require this private authority. No registration means no live run.
 */
export function createControls({ fixture, descriptor, admission }, dependencies = {}) {
  assert.ok(admission?.beforeMemberRead && admission.source?.sourceSha === fixture.binarySourceSha, 'PUBLIC_V1_ADMISSION_BEFORE_CONTROL_SECRET_REQUIRED');
  assert.equal(admission.installed.binaryHash, descriptor.binaryHash, 'CONTROL_ARTIFACT_MISMATCH');
  assert.equal(descriptor.profile, QP.profile); assert.equal(descriptor.observed, true); assert.equal(descriptor.kind, 'registered-queue-privacy-controls');
  assert.equal(descriptor.sourceSha, fixture.binarySourceSha); assert.equal(descriptor.runId, fixture.gatewayRunId);
  assert.deepEqual(descriptor.capabilities, V1_CONTROL_CAPABILITIES); assert.deepEqual(descriptor.protocol, V1_CONTROL_PROTOCOL);
  const origin = new URL(descriptor.origin); assert.equal(origin.origin, new URL(fixture.gatewayUrl).origin);
  assert.equal(origin.protocol, 'https:'); assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname)); assert.equal(origin.pathname, '/');
  assert.notEqual(process.env.NODE_TLS_REJECT_UNAUTHORIZED, '0'); assert.equal(process.env.NODE_EXTRA_CA_CERTS, fixture.publicCa.path);
  const io = { member: readV1Member, fetch: globalThis.fetch, now: Date.now, sleep: ms => new Promise(resolve => setTimeout(resolve, ms)), ...dependencies };
  v1PrivateReference(descriptor.authorityEvidence);
  const loaded = io.member(descriptor.authorityEvidence.path); let authority;
  try { assert.equal(loaded.sha256, descriptor.authorityEvidence.sha256); assert.equal(loaded.uid, descriptor.authorityEvidence.uid); authority = loaded.value.control_secret; assert.match(authority || '', /^[a-f0-9]{64}$/); }
  finally { loaded.bytes.fill(0); }
  let sequence = 0, disposed = false, finalCleanup = 0; const attempted = new Set(), caseCounts = {};
  const call = async (capability, supplied = {}, deadline = io.now() + V1_CONTROL_PROTOCOL.perReadMs) => {
    assert.equal(disposed, false, 'V1_CONTROLS_CLOSED'); assert.ok(V1_CONTROL_CAPABILITIES.includes(capability));
    const { caseId, ...args } = supplied; assert.ok(Object.hasOwn(V1_CASE_CONTROL_LIMITS, caseId || ''), 'EXACT_V1_CONTROL_CASE_REQUIRED'); noSecrets(args);
    if (capability === 'closeRunControls') { assert.equal(caseId, 'PRIVACY-01'); assert.ok(++finalCleanup <= 1, 'ONE_FINAL_CONTROL_CLEANUP_REQUIRED'); }
    else { caseCounts[caseId] = (caseCounts[caseId] || 0) + 1; assert.ok(caseCounts[caseId] <= V1_CASE_CONTROL_LIMITS[caseId], 'V1_CASE_RPC_BOUND'); }
    const operationId = `${fixture.gatewayRunId}:${caseId}:${++sequence}`; assert.equal(attempted.has(operationId), false); attempted.add(operationId);
    const body = JSON.stringify({ schemaVersion: 1, capability, caseId, operationId, runId: fixture.gatewayRunId,
      registrationSha256: descriptor.registrationSha256, args }); assert.ok(Buffer.byteLength(body) <= 16384, 'V1_CONTROL_ARGUMENT_BOUND');
    let response;
    try {
      const remaining = deadline - io.now(); assert.ok(remaining > 0, 'V1_CONTROL_COMPLETION_BOUND');
      response = await io.fetch(new URL(V1_CONTROL_PROTOCOL.pathname, origin), { method: 'POST', redirect: 'error', signal: AbortSignal.timeout(Math.min(V1_CONTROL_PROTOCOL.perReadMs, remaining)),
        headers: { 'Content-Type': 'application/json', 'X-CaseOps-Automated-Test': 'no-paid-providers', 'X-CaseOps-V1-Control': authority }, body });
    } catch { throw Error(writeCapabilities.has(capability) ? 'V1_CONTROL_OUTCOME_UNKNOWN_NO_REPLAY' : 'V1_CONTROL_READ_FAILED'); }
    assert.equal(response.status, 200, 'V1_CONTROL_RESPONSE_STATUS_REQUIRED');
    const value = await boundedResponse(response, V1_CONTROL_PROTOCOL.responseBytes);
    assert.equal(value.observed, true); assert.equal(value.sourceSha, descriptor.sourceSha); assert.equal(value.runId, descriptor.runId);
    assert.equal(value.operationId, operationId); assert.equal(value.caseId, caseId); assert.equal(value.capability, capability);
    assert.equal(value.noPaidMarker, 'no-paid-providers'); assert.equal(value.directDatabaseWrites, false); assert.equal(value.nativeMutationsForwardedByControls, false);
    return value;
  };
  // One receipt read follows observed UI Unknown; no hidden20-poll expansion.
  const methods = Object.fromEntries(V1_CONTROL_CAPABILITIES.map(capability => [capability,(args,options={})=>call(capability,args,options.deadline??io.now()+V1_CONTROL_PROTOCOL.perReadMs)]));
  return { ...methods, dispose() { authority = undefined; disposed = true; },
    publicState: () => ({ attemptedOperations: attempted.size, caseCounts: { ...caseCounts }, finalCleanup, disposed, authorityPrinted: false, registrationSha256: descriptor.registrationSha256,
      argumentIdentity: v1Hash(Buffer.from(descriptor.registrationSha256)) }) };
}
