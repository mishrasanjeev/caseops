import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createProducerStore } from '../../../scripts/mobile/native-producer-host.mjs';
import { produceV1CounselPrerequisite, readV1CounselPrerequisite, V1_COUNSEL_PREREQUISITE_LIMITS,
  V1_COUNSEL_PROFILE_ROUTE, V1_COUNSEL_WORKSPACE_ROUTE } from './v1-counsel-prerequisite.mjs';
import { V1_FIXTURE_ADMISSION_HTTP, V1_FIXTURE_ENVELOPE, v1OracleIdentityEvidence, readV1Reference } from './v1-workflows-contract.mjs';
import { pendingV1ProducerPlan, produceV1Dataset } from './v1-workflows-fixture.mjs';

const uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const ref = name => ({ path: `/unit/${name}.json`, sha256: 'a'.repeat(64) });
const binding = {
  runId: 'v1-1234567890abcdef', sourceSha: 'b'.repeat(40), sourceFingerprint: 'c'.repeat(64), backendRevision: 'api-test',
  webRevision: 'web-test', dockerReceipt: ref('docker'), companyId: uuid(1), ownerMembershipId: uuid(2), ownerUserId: uuid(3),
};
const admitted = {
  companyId: binding.companyId, membershipId: binding.ownerMembershipId, userId: binding.ownerUserId, role: 'owner',
  membershipActive: true, userActive: true, capabilities: ['outside_counsel:manage'],
};
const version = '2026-10-27T00:00:00Z';
const profile = (body, id) => ({
  id, company_id: binding.companyId, name: body.name, panel_status: body.panel_status, primary_contact_name: null,
  primary_contact_email: null, primary_contact_phone: null, firm_city: null, jurisdictions: [], practice_areas: [],
  internal_notes: null, total_matters_count: 0, active_matters_count: 0, total_spend_minor: 0, approved_spend_minor: 0,
  created_at: version, updated_at: version,
});
const workspace = profiles => ({
  summary: { company_id: binding.companyId, profile_count: profiles.length, total_counsel_count: profiles.length },
  profiles, assignments: [], spend_records: [], matter_summaries: [],
});
function harness() {
  const calls = [], writes = [], events = [], claims = new Set();
  let time = 1000;
  const dependencies = {
    now: () => time,
    claim: name => { assert.ok(!claims.has(name), 'SYNTHETIC_EXCLUSIVE_CLAIM_REFUSED'); claims.add(name); },
    persist: event => events.push(event),
    admit: async (boundary, { remaining, charge }) => {
      assert.ok(remaining() > 0);
      const entries = Object.entries(V1_FIXTURE_ADMISSION_HTTP);
      for (const [key, observed] of (boundary === 'before' ? entries.slice(0, 5) : entries.slice(5))) charge({ key, ...observed });
      return admitted;
    },
    request: async input => {
      calls.push(input); time += 10;
      assert.equal(input.automaticRetry, false);
      assert.deepEqual(input.headers, { 'X-CaseOps-Automated-Test': 'no-paid-providers' });
      assert.ok(input.timeoutMs <= V1_COUNSEL_PREREQUISITE_LIMITS.perRequestMs);
      let value;
      if (input.method === 'POST') {
        assert.equal(input.route, V1_COUNSEL_PROFILE_ROUTE);
        value = profile(input.body, uuid(100 + writes.length)); writes.push(value);
      } else {
        assert.equal(input.route, V1_COUNSEL_WORKSPACE_ROUTE);
        assert.equal(input.body, undefined);
        value = workspace([...writes].reverse());
      }
      return { status: 200, releaseSha: binding.sourceSha, requestId: `synthetic-ack-${calls.length}`, value };
    },
  };
  return { dependencies, calls, writes, events, advance: ms => { time += ms; } };
}
function evidenceStore(t) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-v1-counsel-')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return createProducerStore(root);
}

test('ten exact normal creates reconcile an empty before and ACK-equal full workspace in a separate ledger', async t => {
  const model = harness(), store = evidenceStore(t);
  const receipt = await produceV1CounselPrerequisite(binding, model.dependencies);
  const evidence = store.write('counsel-prerequisite-receipt.json', receipt);
  assert.deepEqual(readV1CounselPrerequisite(evidence, binding), model.writes.map(row => row.id));
  assert.equal(receipt.requests, 12); assert.equal(receipt.posts, 10); assert.equal(receipt.admission.length, 7);
  assert.deepEqual(model.calls.map(call => call.method), ['GET', ...Array(10).fill('POST'), 'GET']);
  assert.equal(new Set(model.writes.map(row => row.name)).size, 10);
  assert.equal(V1_FIXTURE_ENVELOPE.stages.base.posts, 64);
  assert.equal(V1_FIXTURE_ENVELOPE.stages.readthrough.requests, 54);
  assert.equal(V1_FIXTURE_ENVELOPE.stages.readthrough.posts, 49);
  assert.equal(V1_FIXTURE_ENVELOPE.milliseconds, 510000);
  assert.throws(() => readV1CounselPrerequisite({ ...evidence, sha256: 'f'.repeat(64) }, binding));
  for (const changed of [
    { runId: 'v1-abcdef1234567890' }, { ownerUserId: uuid(4) }, { companyId: uuid(4) }, { sourceSha: 'e'.repeat(40) },
    { backendRevision: 'other-api' }, { dockerReceipt: ref('different-docker') },
  ]) assert.throws(() => readV1CounselPrerequisite(evidence, { ...binding, ...changed }), /COUNSEL_PREREQUISITE_BINDING_CHANGED/);
  await assert.rejects(produceV1CounselPrerequisite(binding, model.dependencies), /SYNTHETIC_EXCLUSIVE_CLAIM_REFUSED/);
  assert.equal(model.calls.length, 12);
});

test('preexisting workspace data stops before any create, and duplicate and foreign ACKs stop after one attempt', async () => {
  for (const [scenario, expectedCalls, pattern] of [
    ['preexisting', 1, /COUNSEL_WORKSPACE_PROFILE_COUNT_CHANGED/],
    ['duplicate', 3, /DISTINCT_COUNSEL_PROFILE_ACK_REQUIRED/],
    ['foreign', 2, /COUNSEL_PROFILE_ACK_COMPANY_CHANGED/],
    ['readback-drift', 12, /COUNSEL_PROFILE_READBACK_DIFFERS_FROM_ACK/],
  ]) {
    const model = harness(), request = model.dependencies.request;
    model.dependencies.request = async input => {
      const result = await request(input);
      if (scenario === 'preexisting' && model.calls.length === 1) result.value = workspace([profile({ name: 'Retained profile', panel_status: 'active' }, uuid(800))]);
      if (scenario === 'duplicate' && model.calls.length === 3) result.value = { ...result.value, id: model.writes[0].id };
      if (scenario === 'foreign' && model.calls.length === 2) result.value = { ...result.value, company_id: uuid(9) };
      if (scenario === 'readback-drift' && model.calls.length === 12) result.value.profiles[0] = { ...result.value.profiles[0], updated_at: '2026-10-28T00:00:00Z' };
      return result;
    };
    await assert.rejects(produceV1CounselPrerequisite(binding, model.dependencies), pattern);
    assert.equal(model.calls.length, expectedCalls);
    assert.equal(model.events.at(-1).observed, false);
  }
});

test('unknown create outcome or deadline earns no completion receipt and leaves no retry path', async () => {
  const model = harness(), request = model.dependencies.request;
  model.dependencies.request = async input => {
    const response = await request(input);
    if (input.method === 'POST') throw Error('SYNTHETIC_LOST_ACK');
    return response;
  };
  await assert.rejects(produceV1CounselPrerequisite(binding, model.dependencies), /SYNTHETIC_LOST_ACK/);
  assert.equal(model.calls.length, 2);
  assert.deepEqual(model.events.at(-1), { type: 'v1_counsel_prerequisite_stopped', observed: false, automaticRetry: false,
    mutationUncertain: true, requests: 2, posts: 1 });
  await assert.rejects(produceV1CounselPrerequisite(binding, model.dependencies), /SYNTHETIC_EXCLUSIVE_CLAIM_REFUSED/);
  assert.equal(model.calls.length, 2);

  const timed = harness(), timedRequest = timed.dependencies.request;
  timed.dependencies.request = async input => {
    const response = await timedRequest(input);
    timed.advance(V1_COUNSEL_PREREQUISITE_LIMITS.milliseconds);
    return response;
  };
  await assert.rejects(produceV1CounselPrerequisite(binding, timed.dependencies), /COUNSEL_PREREQUISITE_DEADLINE/);
  assert.equal(timed.calls.length, 1);
});

test('original 54-request readthrough consumes only verified prior profile IDs and one current ACK', async t => {
  const model = harness(), store = evidenceStore(t), priorReceipt = await produceV1CounselPrerequisite(binding, model.dependencies);
  const evidence = store.write('counsel-prerequisite-receipt.json', priorReceipt);
  const response = value => ({ $response: value });
  const matterId = uuid(20), contractId = uuid(21), memberId = uuid(22), currentProfileId = uuid(200);
  const plan = Object.assign(pendingV1ProducerPlan(), {
    readyForLive: true, preparedOnly: false, phase: 'readthrough', runId: binding.runId, sourceSha: binding.sourceSha,
    companyId: binding.companyId, membershipId: memberId, ownerMembershipId: binding.ownerMembershipId, catalogueEvidence: ref('catalogue'),
    emptyNotificationPlanEvidence: ref('notification'), baseDatasetEvidence: ref('base-dataset'), baseProducerEvidence: ref('base-producer'),
    viewerEvidence: ref('viewer'), inboxEvidence: ref('inbox'), counselPrerequisiteEvidence: evidence,
    fixtureProjection: { companyId: binding.companyId, membershipId: memberId, v1: { records: {
      counsel: { matter: response('base.v1.records.counsel.matter'), profileIds: response('counsel-prerequisite.counselProfileIds') },
    } } },
  });
  const step = (purpose, index, method, route, body, routeIds) => ({ key: `${purpose}-${index}`, purpose, method, route, body, routeIds, expectedStatuses: [200] });
  const stages = (count, callback) => Array.from({ length: count }, (_, index) => callback(index));
  const obligationRoute = '/api/contracts/{contract}/obligations', obligationIds = { contract: 'base.v1.records.contracts.nullable.id' };
  const contextRoute = '/api/outside-counsel/matters/{matter}/context', matterIds = { matter: 'base.v1.records.counsel.matter.id' };
  const assignmentRoute = '/api/outside-counsel/assignments';
  plan.steps = [
    ...stages(11, i => step('obligation-create', i, 'POST', obligationRoute, { title: `Synthetic obligation ${i}` }, obligationIds)),
    step('counsel-profile', 0, 'POST', V1_COUNSEL_PROFILE_ROUTE, { name: 'Synthetic current profile' }),
    ...stages(11, i => step('counsel-assignment', i, 'POST', assignmentRoute, {
      matter_id: response('base.v1.records.counsel.matter.id'), budget_amount_minor: 1, currency: 'INR',
      counsel_id: response(i < 10 ? `counsel-prerequisite.counselProfileIds.${i}` : 'counsel-profile-0.id'),
    })),
    ...stages(26, i => step('counsel-spend', i, 'POST', '/api/outside-counsel/spend-records', { amount_minor: i + 1 })),
    ...stages(2, i => step('obligation-page', i, 'GET', obligationRoute, undefined, obligationIds)),
    ...stages(3, i => step('counsel-page', i, 'GET', contextRoute, undefined, matterIds)),
  ];
  const catalogue = { sourceSha: binding.sourceSha, syntheticDataOnly: true, designIntakeRegistered: true, patentFamilyAvailable: true, trademarkManualAvailable: true };
  const receipt = { observed: true, sourceSha: binding.sourceSha, automaticRetry: false, mutationUncertain: false, oracleIdentityEvidence: v1OracleIdentityEvidence([matterId, contractId]) };
  const synthetic = new Map([
    [plan.catalogueEvidence.path, catalogue],
    [plan.baseDatasetEvidence.path, { v1: { records: { counsel: { matter: { id: matterId } }, contracts: { nullable: { id: contractId } } } } }],
    [plan.baseProducerEvidence.path, { ...receipt, kind: 'actual-normal-api-v1-base-fixture' }],
    [plan.viewerEvidence.path, { ...receipt, kind: 'actual-normal-api-v1-viewer', role: 'viewer', capabilities: [] }],
    [plan.inboxEvidence.path, { ...receipt, kind: 'actual-canonical-in-app-fixture', externalCalls: 0, manualReceiptInsertion: false }],
  ]);
  const calls = [], before = { beforeMemberRead: true, sourceSha: binding.sourceSha, apiSourceSha: binding.sourceSha, webSourceSha: binding.sourceSha,
    companyId: binding.companyId, membershipId: binding.ownerMembershipId, role: 'owner' };
  const dependencies = {
    catalogue, counselPrerequisiteBinding: binding, planEvidence: ref('readthrough-plan'), claim() {}, persist() {},
    aggregate: { begin() {}, request() {}, remaining: () => 180000, publicState: () => ({ runId: binding.runId, sourceSha: binding.sourceSha }) },
    admit: async () => before,
    readEvidence: observed => synthetic.get(observed.path) ?? readV1Reference(observed),
    request: async input => {
      calls.push(input);
      return { status: 200, releaseSha: binding.sourceSha, requestId: `synthetic-readthrough-${calls.length}`,
        value: { id: input.route === V1_COUNSEL_PROFILE_ROUTE ? currentProfileId : uuid(300 + calls.length), company_id: binding.companyId,
          ...(input.route === assignmentRoute ? { matter_id: input.body.matter_id, counsel_id: input.body.counsel_id } : {}) } };
    },
  };
  const result = await produceV1Dataset(plan, dependencies);
  const assignments = calls.filter(call => call.route === assignmentRoute);
  assert.deepEqual(assignments.map(call => call.body.counsel_id), [...model.writes.map(row => row.id), currentProfileId]);
  assert.ok(assignments.every(call => call.body.matter_id === matterId && call.body.budget_amount_minor === 1));
  assert.equal(result.receipt.requests, 54); assert.equal(result.receipt.writes, 49);
  assert.deepEqual(result.receipt.counselPrerequisiteEvidence, evidence);
  for (const invalidCounsel of [uuid(100), uuid(999)]) {
    const invalid = structuredClone(plan);
    invalid.steps.find(item => item.key === 'counsel-assignment-1').body.counsel_id = invalidCounsel;
    calls.length = 0;
    await assert.rejects(produceV1Dataset(invalid, dependencies), /FRESH_DISTINCT_COUNSEL_PROFILE_ACK_REQUIRED/);
    assert.equal(calls.filter(call => call.route === assignmentRoute).length, 1);
  }
  calls.length = 0;
  await assert.rejects(produceV1Dataset({ ...plan, counselPrerequisiteEvidence: { ...evidence, sha256: 'e'.repeat(64) } }, dependencies));
  assert.equal(calls.length, 0);
});
