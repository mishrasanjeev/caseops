import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { createV1FixtureAggregate } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { createV1IpAccessGrant } from './v1-ip-access-grant.mjs';
import { grantV1IpMemberAccess } from './v1-ip-access-host.mjs';

const id = n => '11000000-0000-4000-8000-' + String(n).padStart(12, '0');
const hash = value => createHash('sha256').update(value).digest('hex');
const time = '2026-11-08T12:00:00.000000Z';
const previewToken = 'c'.repeat(64);
const reason = 'Synthetic native fixture: grant access to the current test member.';
const types = { patent: 'patent_family', design: 'design_intake' };
const creators = { patent: '/api/ip/patents/families', design: '/api/ip/specialist/records' };

export function ipAccessTestFixture(family = 'patent', options = {}) {
  const scope = options.scope ?? { sourceSha: 'a'.repeat(40), companyId: id(1), ownerMembershipId: id(2), memberMembershipId: id(3) };
  const { sourceSha, companyId, ownerMembershipId: owner, memberMembershipId: member } = scope;
  const [record, docket, matter, edge, initial, granted, operation] = options.identities ?? Array.from({ length: 7 }, (_, index) => id(index + 10));
  const prefix = '/api/ip/dockets/' + docket;
  const title = options.title ?? 'Restricted synthetic ' + family;
  const ack = (requestId, method, route, status, value, options = {}) => ({
    actor: { companyId, membershipId: options.member ? member : owner },
    request: { method, route, ...options.request },
    response: { status, releaseSha: sourceSha, requestId, value, serverDate: new Date(time).toUTCString() },
  });
  const grant = (id, subject_id, subject_label, reason) => ({ id, subject_type: 'membership', subject_id, subject_label,
    access_level: 'member', reason, effective_from: time, expires_at: null, revoked_at: null,
    granted_by_membership_id: owner, revoked_by_membership_id: null, record_version: 0, created_at: time });
  const before = grant(initial, owner, 'Synthetic owner', 'Initial restricted-record creator access.');
  const added = grant(granted, member, 'Synthetic member', reason);
  const panel = (version, grants) => ({ docket_id: docket, docket_title: title, restricted: true, access_policy_version: version,
    linked_matter_id: matter, grants, walls: [], active_internal_membership_count: grants.length, queued_delivery_count: 0,
    excluded_persistence: ['portal_grants', 'access_review_campaigns', 'emergency_access_sessions'] });
  const change = { action: 'grant', expected_access_policy_version: 1, subject_type: 'membership', subject_id: member, reason };
  const parents = {
    creator: ack('creator-01', 'POST', creators[family], 201, { id: record, docket_id: docket,
      ...(family === 'patent' ? { record_kind: types.patent, facts: { title } } : { facts: { title, details: { domain: family } } }) }),
    matter: ack('matter-01', 'POST', '/api/matters/', 200, { id: matter, company_id: companyId, is_active: true, status: 'active' }),
    link: ack('link-01', 'POST', prefix + '/matter-links', 201, { id: edge, company_id: companyId, docket_id: docket, matter_id: matter,
      relation_role: 'operational', source: 'manual', retired_at: null, created_by_membership_id: owner },
    { request: { body: { matter_id: matter, relation_role: 'operational' } } }),
    mfa: ack('mfa-01', 'POST', '/api/auth/mfa/step-up', 200, { status: 'verified', expires_at: '2026-11-08T12:15:00.000000Z' },
      { request: { purpose: 'step_up', verificationMethod: 'totp' } }),
    panel: ack('panel-01', 'GET', prefix + '/access', 200, panel(1, [before])),
  };
  const memberSummary = ack('summary-01', 'GET', prefix + '/summary', 200, { id: docket, company_id: companyId, matter_id: matter,
    record_type: types[family], title, primary_identifier: null, status: 'draft', is_active: true, lifecycle_version: 0,
    access_policy_version: 2, current_version: 1, updated_at: time }, { member: true });
  const preview = ack('preview-01', 'POST', prefix + '/access/preview', 200, { docket_id: docket, access_policy_version: 1,
    action: 'grant', preview_token: previewToken, affected_memberships: [{ membership_id: member, label: added.subject_label,
      before_visible: false, after_visible: true, linked_matter_visible: true }],
    visibility_gain_count: 1, visibility_loss_count: 0, queued_delivery_recheck_count: 0, document_count: 0,
    linked_matter_id: matter, linked_matter_mismatch: false, warnings: [], requires_step_up: true });
  const apply = ack('apply-01', 'POST', prefix + '/access/apply', 200, { action: 'grant', invalidation_operation_id: operation,
    visibility_gain_count: 1, visibility_loss_count: 0, queued_delivery_recheck_count: 0, panel: panel(2, [added, structuredClone(before)]) });
  let clock = Date.parse(time);
  const charges = [], calls = [], buffers = [];
  const ready = (overrides = {}) => createV1IpAccessGrant(scope, family, parents, {
    charge: value => charges.push(structuredClone(value)), remaining: () => 8000, now: () => clock,
    ...overrides,
  });
  function respond(request) {
    const previewRequest = request.route.endsWith('/preview');
    const envelope = previewRequest ? preview : apply;
    assert.equal(request.route, envelope.request.route);
    assert.equal(request.actor, 'owner');
    assert.equal(request.method, 'POST');
    assert.equal(request.timeoutMs, options.expectedTimeoutMs ?? 8000);
    assert.equal(request.automaticRetry, false);
    const digest = hash(request.bodyBytes);
    assert.deepEqual(request.provenance, { requestDigest: hash(previewRequest ? parents.panel.response.requestId : preview.response.requestId),
      bodySha256: digest });
    assert.deepEqual(JSON.parse(request.bodyBytes), previewRequest ? change : { ...change, preview_token: previewToken });
    buffers.push(request.bodyBytes);
    calls.push(request.route);
    return { ...envelope, request: { ...envelope.request, bodySha256: digest } };
  }
  return { scope, family, parents, memberSummary, preview, apply, ready, respond, charges, calls, buffers,
    expire: () => { clock = Date.parse(parents.mfa.response.value.expires_at) - 8000; } };
}
const fixture = ipAccessTestFixture;

for (const family of Object.keys(types)) {
  test('binds ' + family + ' owner panel and fresh MFA to an exact single durable member grant', async () => {
    const f = fixture(family);
    const execute = f.ready();
    const grant = await execute(f.respond);
    assert.equal(grant.receipt.grantId, id(15));
    assert.equal(grant.receipt.membershipId, f.scope.memberMembershipId);
    assert.equal(grant.receipt.accessPolicyVersion, 2);
    assert.equal(grant.receipt.memberSummaryAckSha256, undefined);
    const receipt = grant.acceptMemberSummary(f.memberSummary);
    assert.equal(receipt.memberSummaryAckSha256, hash(f.memberSummary.response.requestId));
    assert.deepEqual(f.charges, ['preview', 'apply'].map(operation => ({
      key: 'ip-' + family + '-grant-' + operation, method: 'POST', route: '/api/ip/dockets/' + id(11) + '/access/' + operation,
    })));
    assert.ok(f.buffers.every(bytes => bytes.every(byte => byte === 0)));
    assert.ok(!JSON.stringify([receipt, f.charges]).includes(previewToken));
    assert.ok(!JSON.stringify([receipt, f.charges]).includes('preview_token'));
    await assert.rejects(execute(f.respond), /PAIR_REPLAY_REFUSED/);
    assert.throws(() => grant.acceptMemberSummary(f.memberSummary), /MEMBER_READ_REPLAY_REFUSED/);

    const bridge = fixture(family);
    const { mfa, ...parents } = bridge.parents;
    const host = {
      getActorIdentity: () => ({ company: { id: bridge.scope.companyId }, membership: { id: bridge.scope.ownerMembershipId } }),
      getMfaAcknowledgement: () => mfa,
      requestIpAccess: async (input, chain) => {
        const claim = chain.claim({ stage: input.producerStage, actor: input.actor, company: bridge.scope.companyId,
          membership: bridge.scope.ownerMembershipId, method: input.method, requestTarget: input.route, bodyBytes: input.bodyBytes });
        assert.deepEqual(claim.provenance, input.provenance);
        const response = bridge.respond(input).response;
        const projection = claim.acceptResponse(response);
        assert.throws(() => claim.acceptResponse(response), /ACK_REPLAY_REFUSED/);
        assert.throws(() => chain.claim({}), /HOST_REPLAY_REFUSED/);
        return { projection };
      },
    };
    const bridged = await grantV1IpMemberAccess(host, bridge.scope, family, parents,
      { charge: value => bridge.charges.push(value), remaining: () => 8000, now: () => Date.parse(time) });
    assert.equal(bridged.acceptMemberSummary(bridge.memberSummary).grantId, id(15));
    assert.equal(bridge.calls.length, 2);
    assert.ok(bridge.buffers.every(bytes => bytes.every(byte => byte === 0)));
    await assert.rejects(grantV1IpMemberAccess({ ...host, getActorIdentity: () => ({}) }, bridge.scope, family, parents, {}), /HOST_ACTOR_REQUIRED/);
  });
}

for (const [name, change, error] of [
  ['foreign creator issuer', f => { f.parents.creator.actor.companyId = id(999); }, /ACK_ACTOR/],
  ['foreign linked Matter', f => { f.parents.link.response.value.matter_id = id(999); }, /LINK_LINEAGE/],
  ['stale panel version', f => { f.parents.panel.response.value.access_policy_version = 0; }, /PANEL_LINEAGE/],
  ['preexisting member access', f => { f.parents.panel.response.value.grants.push(f.apply.response.value.panel.grants[0]); }, /UNEXPECTED_PANEL_ACCESS/],
  ['foreign MFA actor', f => { f.parents.mfa.actor.membershipId = f.scope.memberMembershipId; }, /ACK_ACTOR/],
  ['non-TOTP MFA projection', f => { f.parents.mfa.request.verificationMethod = 'recovery_code'; }, /NORMAL_MFA_REQUIRED/],
]) {
  test('rejects ' + name + ' before dispatch', () => {
    const f = fixture();
    change(f);
    assert.throws(f.ready, error);
    assert.deepEqual(f.charges, []);
  });
}

for (const [name, change, error] of [
  ['wrong preview tenant', f => { f.preview.actor.companyId = id(999); }, /ACK_ACTOR/],
  ['wrong serving source', f => { f.preview.response.releaseSha = 'b'.repeat(40); }, /ACK_REQUIRED/],
  ['duplicate predecessor ACK', f => { f.preview.response.requestId = f.parents.panel.response.requestId; }, /ACK_REQUIRED/],
  ['unexpected preview member gain', f => { f.preview.response.value.affected_memberships[0].membership_id = id(999); }, /ONE_MEMBER_GAIN/],
  ['new linked-Matter mismatch', f => { f.preview.response.value.linked_matter_mismatch = true; }, /PREVIEW_EFFECT/],
  ['invalid preview token', f => { f.preview.response.value.preview_token = 'arbitrary'; }, /PREVIEW_LINEAGE/],
]) {
  test('stops before applying on ' + name, async () => {
    const f = fixture();
    change(f);
    await assert.rejects(f.ready()(f.respond), error);
    assert.equal(f.charges.length, 1);
  });
}

test('checks normal MFA again immediately before apply and never refreshes or replays it', async () => {
  const f = fixture();
  const execute = f.ready();
  await assert.rejects(execute(request => {
    const response = f.respond(request);
    f.expire();
    return response;
  }), /MFA_TOO_OLD/);
  assert.equal(f.charges.length, 1);
  await assert.rejects(execute(f.respond), /PAIR_REPLAY_REFUSED/);
  await assert.rejects(f.ready()(f.respond), /MFA_TOO_OLD/);
  assert.equal(f.charges.length, 1);
});

test('refuses a changed existing owner grant and requires a separate current member read', async () => {
  const f = fixture();
  f.apply.response.value.panel.grants[1].record_version += 1;
  await assert.rejects(f.ready()(f.respond), /OWNER_GRANT_CHANGED/);
  assert.equal(f.charges.length, 2);
  const complete = fixture();
  const proof = await complete.ready()(complete.respond);
  complete.memberSummary.response.value.access_policy_version = 1;
  assert.throws(() => proof.acceptMemberSummary(complete.memberSummary), /MEMBER_SUMMARY_LINEAGE/);
});

test('refuses altered exact request bytes or an unknown apply without exposing the token', async () => {
  const f = fixture();
  const execute = f.ready();
  await assert.rejects(execute(request => {
    const envelope = f.respond(request);
    if (request.route.endsWith('/apply')) throw new Error(previewToken);
    return envelope;
  }), error => error.message === 'V1_IP_ACL_TRANSPORT_INCOMPLETE_NO_REPLAY' && error.cause === undefined);
  assert.ok(f.buffers.every(bytes => bytes.every(byte => byte === 0)));
  await assert.rejects(execute(f.respond), /PAIR_REPLAY_REFUSED/);
  const changed = fixture();
  await assert.rejects(changed.ready()(request => {
    const response = changed.respond(request);
    response.request.bodySha256 = 'f'.repeat(64);
    return response;
  }), /ACK_REQUEST/);
  assert.equal(changed.charges.length, 1);
});

test('the existing base gate refuses a reconstructed pair after an uncertain dispatch', async () => {
  const f = fixture();
  const events = [];
  const aggregate = createV1FixtureAggregate({ runId: 'v1-' + 'f'.repeat(16), sourceSha: f.scope.sourceSha,
    claim: () => {}, persist: event => events.push(event), now: () => Date.parse(time) });
  aggregate.begin('base', { path: '/synthetic-owned-base-plan.json', sha256: 'e'.repeat(64) });
  const options = { charge: event => aggregate.request('base', event) };
  const first = f.ready(options);
  await assert.rejects(first(request => {
    const response = f.respond(request);
    if (request.route.endsWith('/apply')) throw new Error(previewToken);
    return response;
  }), /TRANSPORT_INCOMPLETE_NO_REPLAY/);
  await assert.rejects(f.ready(options)(f.respond), /FIXTURE_HTTP_REPLAY_REFUSED/);
  assert.equal(aggregate.publicState().stages[0].requests, 2);
  assert.equal(aggregate.publicState().stages[0].posts, 2);
  assert.equal(f.calls.length, 2);
  assert.ok(!JSON.stringify(events).includes(previewToken));
});

for (const family of ['patent', 'design']) {
  test(`granted ${family} access uses each response server second when the client clock is behind`, async () => {
    const f = fixture(family), epoch = Date.parse(time);
    Object.assign(f.apply.response.value.panel.grants[0], { effective_from: new Date(epoch + 15).toISOString(), created_at: new Date(epoch + 16).toISOString() });
    const proof = await f.ready({ now: () => epoch - 20 })(f.respond);
    assert.equal(proof.acceptMemberSummary(f.memberSummary).membershipId, f.scope.memberMembershipId);
    assert.equal(f.calls.length, 2); assert.ok(f.buffers.every(b => b.every(x => x === 0)));
  });
  test(`${family} grant timestamp second boundaries use the panel and apply observations independently`, async () => {
    const epoch = Date.parse(time);
    for (const which of ['owner', 'member']) for (const offset of [999, 1000]) {
      const f = fixture(family), row = which === 'owner' ? f.parents.panel.response.value.grants[0] : f.apply.response.value.panel.grants[0];
      Object.assign(row, { effective_from: new Date(epoch + offset).toISOString(), created_at: new Date(epoch + offset).toISOString() });
      if (which === 'owner') f.apply.response.value.panel.grants[1] = structuredClone(row);
      if (which === 'owner' && offset === 1000) { assert.throws(() => f.ready({ now: () => epoch + 5000 }), /GRANT_NOT_ACTIVE/); assert.equal(f.calls.length, 0); continue; }
      const run = f.ready({ now: () => epoch + 5000 });
      if (offset === 999) { const result = await run(f.respond); result.acceptMemberSummary(f.memberSummary); assert.equal(f.calls.length, 2); }
      else { await assert.rejects(run(f.respond), /GRANT_NOT_ACTIVE/); assert.equal(f.calls.length, which === 'owner' ? 0 : 2); }
    }
    const f = fixture(family);
    f.apply.response.serverDate = new Date(epoch + 1000).toUTCString();
    Object.assign(f.apply.response.value.panel.grants[0], { effective_from: new Date(epoch + 1000).toISOString(), created_at: new Date(epoch + 1001).toISOString() });
    const granted = await f.ready()(f.respond); granted.acceptMemberSummary(f.memberSummary); assert.equal(f.calls.length, 2);
  });
  test(`${family} access rejects missing or malformed corresponding response time without host fallback`, async () => {
    for (const which of ['panel', 'apply']) for (const date of [undefined, 'not-a-date', 'Sun, 08 Nov 2026 12:00:00 GMT trailing', 'Mon, 08 Nov 2026 12:00:00 GMT']) {
      const f = fixture(family), target = which === 'panel' ? f.parents.panel.response : f.apply.response;
      if (date === undefined) delete target.serverDate; else target.serverDate = date;
      if (which === 'panel') { assert.throws(f.ready, /SERVER_DATE/); assert.equal(f.calls.length, 0); }
      else { await assert.rejects(f.ready()(f.respond), /SERVER_DATE/); assert.equal(f.calls.length, 2); }
    }
  });
  test(`${family} server-clock grant validation still rejects expiry revocation and invalid timestamps`, async () => {
    for (const which of ['owner', 'member']) for (const change of [
      { expires_at: time }, { revoked_at: time }, { revoked_by_membership_id: id(999) },
      { effective_from: 'invalid' }, { created_at: 'invalid' },
    ]) {
      const f = fixture(family), row = which === 'owner' ? f.parents.panel.response.value.grants[0] : f.apply.response.value.panel.grants[0]; Object.assign(row, change);
      if (which === 'owner') { assert.throws(f.ready, /GRANT_NOT_ACTIVE/); assert.equal(f.calls.length, 0); }
      else { await assert.rejects(f.ready()(f.respond), /GRANT_NOT_ACTIVE/); assert.equal(f.calls.length, 2); }
    }
  });
}
