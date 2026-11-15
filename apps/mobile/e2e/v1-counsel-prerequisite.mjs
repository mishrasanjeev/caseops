import assert from 'node:assert/strict';
import { readV1Reference, v1Identity, v1Reference, V1_FIXTURE_ADMISSION_HTTP } from './v1-workflows-contract.mjs';

export const V1_COUNSEL_PROFILE_ROUTE = '/api/outside-counsel/profiles';
export const V1_COUNSEL_WORKSPACE_ROUTE = '/api/outside-counsel/workspace';
export const V1_COUNSEL_PREREQUISITE_LIMITS = Object.freeze({
  profiles: 10, requests: 12, posts: 10, admissionRequests: 7, admissionPosts: 2,
  milliseconds: 120000, perRequestMs: 10000, responseBytes: 1048576,
});
const limits = V1_COUNSEL_PREREQUISITE_LIMITS;
const BINDING_KEYS = ['backendRevision', 'companyId', 'dockerReceipt', 'ownerMembershipId', 'ownerUserId', 'runId', 'sourceFingerprint', 'sourceSha', 'webRevision'];
const RESPONSE_KEYS = ['releaseSha', 'requestId', 'status', 'value'];
const OBSERVATION_KEYS = ['key', 'method', 'route'];

function exactKeys(value, expected, error) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), error);
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), error);
}
function bindingFacts(binding) {
  exactKeys(binding, BINDING_KEYS, 'EXACT_COUNSEL_PREREQUISITE_BINDING_REQUIRED');
  assert.match(binding.runId, /^v1-[a-f0-9-]{16,80}$/);
  assert.match(binding.sourceSha, /^[a-f0-9]{40}$/);
  assert.match(binding.sourceFingerprint, /^[a-f0-9]{64}$/);
  for (const field of ['companyId', 'ownerMembershipId', 'ownerUserId']) v1Identity(binding[field]);
  for (const field of ['backendRevision', 'webRevision']) assert.match(binding[field], /^[A-Za-z0-9._:-]{1,160}$/);
  exactKeys(binding.dockerReceipt, ['path', 'sha256'], 'EXACT_DOCKER_REFERENCE_REQUIRED');
  v1Reference(binding.dockerReceipt);
}
function profileBody(binding, index) {
  return { name: `Synthetic V1 ${binding.runId} Counsel ${index + 1}`, panel_status: 'active' };
}
function checkedResponse(response, binding, requestIds) {
  exactKeys(response, RESPONSE_KEYS, 'EXACT_COUNSEL_HTTP_ACK_REQUIRED');
  assert.equal(response.status, 200, 'COUNSEL_PREREQUISITE_HTTP_STATUS_REQUIRED');
  assert.equal(response.releaseSha, binding.sourceSha, 'COUNSEL_PREREQUISITE_SERVING_SOURCE_CHANGED');
  assert.match(response.requestId, /^[A-Za-z0-9_.:-]{1,160}$/);
  assert.ok(!requestIds.has(response.requestId), 'DISTINCT_COUNSEL_REQUEST_ACK_REQUIRED');
  requestIds.add(response.requestId);
  assert.ok(response.value && typeof response.value === 'object' && !Array.isArray(response.value));
  return response.value;
}
function checkedWorkspace(value, companyId, profileCount) {
  exactKeys(value, ['summary', 'profiles', 'assignments', 'spend_records', 'matter_summaries'], 'EXACT_COUNSEL_WORKSPACE_REQUIRED');
  assert.equal(value.summary.company_id, companyId, 'COUNSEL_WORKSPACE_COMPANY_CHANGED');
  assert.equal(value.summary.profile_count, profileCount, 'COUNSEL_WORKSPACE_PROFILE_COUNT_CHANGED');
  assert.equal(value.summary.total_counsel_count, profileCount, 'COUNSEL_WORKSPACE_PROFILE_COUNT_CHANGED');
  assert.ok(Array.isArray(value.profiles) && value.profiles.length === profileCount, 'EXACT_COUNSEL_WORKSPACE_PROFILES_REQUIRED');
  for (const key of ['assignments', 'spend_records', 'matter_summaries']) assert.deepEqual(value[key], [], 'FRESH_COUNSEL_WORKSPACE_REQUIRED');
  return value.profiles;
}
function checkedProfile(value, binding, index, ids) {
  exactKeys(value, ['id', 'company_id', 'name', 'primary_contact_name', 'primary_contact_email', 'primary_contact_phone',
    'firm_city', 'jurisdictions', 'practice_areas', 'panel_status', 'internal_notes', 'total_matters_count',
    'active_matters_count', 'total_spend_minor', 'approved_spend_minor', 'created_at', 'updated_at'], 'EXACT_COUNSEL_PROFILE_ACK_REQUIRED');
  const id = v1Identity(value.id);
  assert.ok(!ids.has(id), 'DISTINCT_COUNSEL_PROFILE_ACK_REQUIRED');
  assert.equal(value.company_id, binding.companyId, 'COUNSEL_PROFILE_ACK_COMPANY_CHANGED');
  assert.equal(value.name, profileBody(binding, index).name, 'COUNSEL_PROFILE_ACK_NAME_CHANGED');
  assert.equal(value.panel_status, 'active');
  for (const field of ['primary_contact_name', 'primary_contact_email', 'primary_contact_phone', 'firm_city', 'internal_notes']) assert.equal(value[field], null);
  for (const field of ['jurisdictions', 'practice_areas']) assert.deepEqual(value[field], []);
  for (const field of ['total_matters_count', 'active_matters_count', 'total_spend_minor', 'approved_spend_minor']) assert.equal(value[field], 0);
  for (const field of ['created_at', 'updated_at']) assert.ok(Number.isFinite(Date.parse(value[field])));
  ids.add(id);
}
function checkedOwner(owner, binding) {
  exactKeys(owner, ['companyId', 'membershipId', 'userId', 'role', 'membershipActive', 'userActive', 'capabilities'], 'EXACT_COUNSEL_OWNER_EVIDENCE_REQUIRED');
  assert.deepEqual([owner.companyId, owner.membershipId, owner.userId], [binding.companyId, binding.ownerMembershipId, binding.ownerUserId], 'COUNSEL_PREREQUISITE_OWNER_CHANGED');
  assert.equal(owner.role, 'owner');
  assert.equal(owner.membershipActive, true);
  assert.equal(owner.userActive, true);
  assert.ok(Array.isArray(owner.capabilities) && owner.capabilities.includes('outside_counsel:manage'), 'COUNSEL_MANAGEMENT_CAPABILITY_REQUIRED');
}
const admissionOrder = Object.keys(V1_FIXTURE_ADMISSION_HTTP);
function checkAdmission(entry, index) {
  exactKeys(entry, OBSERVATION_KEYS, 'EXACT_COUNSEL_ADMISSION_CALL_REQUIRED');
  const key = admissionOrder[index];
  assert.deepEqual(entry, { key, ...V1_FIXTURE_ADMISSION_HTTP[key] }, 'EXACT_COUNSEL_ADMISSION_SEQUENCE_REQUIRED');
}

/** Consumer for the exclusive descriptor-verified receipt written by the host.
 * Reconciles the complete proof to the current run rather than accepting IDs
 * copied into the readthrough plan. No network or credential read occurs here.
 */
export function readV1CounselPrerequisite(evidence, binding, { read = readV1Reference } = {}) {
  bindingFacts(binding);
  exactKeys(evidence, ['path', 'sha256'], 'EXACT_COUNSEL_RECEIPT_REFERENCE_REQUIRED');
  v1Reference(evidence);
  return validateReceipt(read(evidence), binding);
}
function validateReceipt(receipt, binding) {
  exactKeys(receipt, ['schemaVersion', 'kind', 'binding', 'observed', 'automaticRetry', 'mutationUncertain', 'noPaidMarker',
    'directDatabaseWrites', 'admission', 'owner', 'requests', 'posts', 'elapsedMilliseconds', 'before', 'created', 'after'], 'EXACT_COUNSEL_RECEIPT_REQUIRED');
  assert.equal(receipt.schemaVersion, 1);
  assert.equal(receipt.kind, 'actual-v1-counsel-prerequisite');
  assert.deepEqual(receipt.binding, binding, 'COUNSEL_PREREQUISITE_BINDING_CHANGED');
  assert.equal(receipt.observed, true);
  assert.equal(receipt.automaticRetry, false);
  assert.equal(receipt.mutationUncertain, false);
  assert.equal(receipt.directDatabaseWrites, false);
  assert.equal(receipt.noPaidMarker, 'no-paid-providers');
  assert.equal(receipt.requests, limits.requests);
  assert.equal(receipt.posts, limits.posts);
  assert.ok(Number.isSafeInteger(receipt.elapsedMilliseconds) && receipt.elapsedMilliseconds >= 0 && receipt.elapsedMilliseconds <= limits.milliseconds);
  assert.ok(Array.isArray(receipt.admission) && receipt.admission.length === limits.admissionRequests);
  receipt.admission.forEach(checkAdmission);
  assert.equal(receipt.admission.filter(entry => entry.method === 'POST').length, limits.admissionPosts);
  checkedOwner(receipt.owner, binding);
  const requestIds = new Set(), profileIds = new Set();
  checkedWorkspace(checkedResponse(receipt.before, binding, requestIds), binding.companyId, 0);
  assert.ok(Array.isArray(receipt.created) && receipt.created.length === limits.profiles, 'TEN_COUNSEL_PROFILE_ACKS_REQUIRED');
  const acknowledged = receipt.created.map((response, index) => {
    const profile = checkedResponse(response, binding, requestIds);
    checkedProfile(profile, binding, index, profileIds);
    return profile;
  });
  const readback = checkedWorkspace(checkedResponse(receipt.after, binding, requestIds), binding.companyId, limits.profiles);
  const compare = (left, right) => left.id.localeCompare(right.id);
  assert.deepEqual(readback.toSorted(compare), acknowledged.toSorted(compare), 'COUNSEL_PROFILE_READBACK_DIFFERS_FROM_ACK');
  return [...profileIds];
}

/** Only the newly required profiles run here. Normal auth and source admission
 * are owned by the caller and charged to this separate finite clock. No
 * original V1 dataset work moves into this operation.
 */
export async function produceV1CounselPrerequisite(binding, { admit, request, claim, persist, now = Date.now, deadline = now() + limits.milliseconds }) {
  bindingFacts(binding);
  const started = deadline - limits.milliseconds, admission = [], requestIds = new Set(), profileIds = new Set();
  const remaining = () => {
    const left = deadline - now();
    assert.ok(left >= 1 && left <= limits.milliseconds, 'COUNSEL_PREREQUISITE_DEADLINE');
    return left;
  };
  const charge = entry => {
    remaining();
    checkAdmission(entry, admission.length);
    admission.push(structuredClone(entry));
    persist({ type: 'v1_counsel_prerequisite_admission', ...entry });
  };
  remaining();
  claim(`v1-counsel-prerequisite:${binding.runId}`);
  let requests = 0, posts = 0, mutationUncertain = false;
  const call = async (method, route, body) => {
    const timeoutMs = Math.min(limits.perRequestMs, remaining());
    assert.ok(++requests <= limits.requests);
    if (method === 'POST') { assert.ok(++posts <= limits.posts); mutationUncertain = true; }
    persist({ type: 'v1_counsel_prerequisite_http_started', method, route, sequence: requests, mutationUncertain });
    const { status, value, requestId, releaseSha } = await request({ method, route, body, timeoutMs,
      headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' }, maxResponseBytes: limits.responseBytes, automaticRetry: false });
    remaining();
    const response = { status, value, requestId, releaseSha };
    checkedResponse(response, binding, requestIds);
    persist({ type: 'v1_counsel_prerequisite_http_ack', method, route, sequence: requests, requestId });
    return response;
  };
  try {
    const owner = await admit('before', { remaining, charge });
    assert.equal(admission.length, 5);
    checkedOwner(owner, binding);
    const before = await call('GET', V1_COUNSEL_WORKSPACE_ROUTE);
    checkedWorkspace(before.value, binding.companyId, 0);
    const created = [];
    for (let index = 0; index < limits.profiles; index++) {
      const response = await call('POST', V1_COUNSEL_PROFILE_ROUTE, profileBody(binding, index));
      checkedProfile(response.value, binding, index, profileIds);
      created.push(response);
      mutationUncertain = false;
    }
    const after = await call('GET', V1_COUNSEL_WORKSPACE_ROUTE);
    assert.deepEqual(await admit('after', { remaining, charge }), owner, 'COUNSEL_PREREQUISITE_OWNER_CHANGED');
    remaining();
    const receipt = { schemaVersion: 1, kind: 'actual-v1-counsel-prerequisite', binding, observed: true,
      automaticRetry: false, mutationUncertain: false, directDatabaseWrites: false, noPaidMarker: 'no-paid-providers',
      admission, owner, requests, posts, elapsedMilliseconds: now() - started, before, created, after };
    // Both writer and reader must reconcile the exact fresh-workspace proof.
    validateReceipt(receipt, binding);
    return receipt;
  } catch (error) {
    persist({ type: 'v1_counsel_prerequisite_stopped', observed: false, automaticRetry: false, mutationUncertain, requests, posts });
    throw error;
  }
}
