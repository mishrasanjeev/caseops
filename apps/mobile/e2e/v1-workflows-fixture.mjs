import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
import { totp } from './mfa.mjs';
import { v1Hash, v1Identity, v1Reference, v1PrivateReference, v1Lifecycle, collectV1OracleIdentities, v1OracleIdentityEvidence, validateV1OracleIdentityEvidence, readV1Reference, readV1Bytes } from './v1-workflows-contract.mjs';
import { fileURLToPath } from 'node:url';
import { v1Inventory } from './v1-workflows-inventory.mjs';

export const V1_PRODUCER_LIMITS = Object.freeze({ totalMs: 180000, perRequestMs: 10000, requests: 96, writes: 64, responseBytes: 1048576 });
const CREATE = [
  /^\/api\/clients\/$/, /^\/api\/contracts\/$/, /^\/api\/matters\/$/,
  /^\/api\/ip\/patents\/families$/, /^\/api\/ip\/specialist\/records$/,
  /^\/api\/ip\/trademark-applications\/manual$/, /^\/api\/ip\/operational-deadlines$/,
  /^\/api\/matters\/[a-f0-9-]{36}\/(?:tasks|hearings)$/,
  /^\/api\/matters\/[a-f0-9-]{36}\/access\/(?:restricted|grants)$/,
  /^\/api\/ip\/dockets\/[a-f0-9-]{36}\/matter-links$/,
];
const READ = [
  /^\/api\/build$/, /^\/api\/ip\/(?:readiness|domains)$/,
  /^\/api\/contracts\/(?:[a-f0-9-]{36})?$/,
  /^\/api\/matters\/[a-f0-9-]{36}(?:\/workspace)?$/,
  /^\/api\/ip\/dockets\/[a-f0-9-]{36}\/summary$/,
  /^\/api\/ip\/patents\/families\/[a-f0-9-]{36}(?:\/versions\/1)?$/,
  /^\/api\/ip\/specialist\/records\/[a-f0-9-]{36}(?:\/versions\/1)?$/,
  /^\/api\/ip\/trademark-applications\/[a-f0-9-]{36}$/,
  /^\/api\/calendar\/events$/,
  /^\/api\/matters\/[a-f0-9-]{36}\/access$/,
  /^\/api\/ip\/dockets\/[a-f0-9-]{36}\/(?:access|matter-links)$/,
];
const READTHROUGH_CREATE = [/^\/api\/contracts\/[a-f0-9-]{36}\/obligations$/, /^\/api\/outside-counsel\/(?:profiles|assignments|spend-records)$/];
const READTHROUGH_READ = [/^\/api\/contracts\/[a-f0-9-]{36}\/obligations$/, /^\/api\/outside-counsel\/matters\/[a-f0-9-]{36}\/context$/];
function noSecrets(value) {
  if (Array.isArray(value)) { for (const item of value) noSecrets(item); return; }
  if (!value || typeof value !== 'object') return;
  for (const [key, item] of Object.entries(value)) {
    assert.ok(!/(password|totp|secret|access_token|refresh_token|authorization|cookie)/i.test(key), 'PRODUCER_PUBLIC_PLAN_MUST_NOT_EMBED_CREDENTIALS');
    noSecrets(item);
  }
}
export function requireV1ProducerPlan(plan) {
  assert.equal(plan?.schemaVersion, 1); assert.equal(plan.readyForLive, true, 'V1_PRODUCER_PENDING_MUST_NOT_RUN');
  assert.equal(plan.preparedOnly, false, 'V1_PRODUCER_PENDING_MUST_NOT_RUN');
  assert.equal(plan.environment, 'docker-integration'); assert.equal(plan.syntheticDataOnly, true);
  assert.match(plan.sourceSha || '', /^[a-f0-9]{40}$/); assert.match(plan.runId || '', /^v1-[a-f0-9-]{16,80}$/);
  assert.equal(plan.noPaidMarker, 'no-paid-providers'); assert.equal(plan.directDatabaseWrites, false);
  assert.ok(['base', 'readthrough'].includes(plan.phase), 'EXACT_FIXED_FIXTURE_PHASE_REQUIRED');
  v1Identity(plan.companyId); v1Identity(plan.membershipId);
  v1Identity(plan.ownerMembershipId);
  v1Reference(plan.catalogueEvidence); v1Reference(plan.emptyNotificationPlanEvidence);
  if (plan.phase === 'readthrough') for (const key of ['baseDatasetEvidence', 'baseProducerEvidence', 'viewerEvidence', 'inboxEvidence']) v1Reference(plan[key]);
  assert.ok(Array.isArray(plan.steps) && plan.steps.length > 0 && plan.steps.length <= V1_PRODUCER_LIMITS.requests);
  assert.equal(new Set(plan.steps.map(step => step.key)).size, plan.steps.length, 'UNIQUE_PRODUCER_STEP_KEYS_REQUIRED');
  assert.ok(plan.steps.every(step => /^[a-z][a-z0-9-]{1,80}$/.test(step.key)));
  if (plan.phase === 'base') {
    assert.ok(plan.secondaryOwner && typeof plan.secondaryOwner.companySlug === 'string' && typeof plan.secondaryOwner.companyName === 'string'
      && typeof plan.secondaryOwner.fullName === 'string' && typeof plan.secondaryOwner.email === 'string', 'NORMAL_SECOND_COMPANY_OWNER_PLAN_REQUIRED');
    assert.ok(plan.steps.length <= V1_PRODUCER_LIMITS.requests - 4, 'BASE_REQUESTS_MUST_RESERVE_FOUR_SECOND_COMPANY_CALLS');
    assert.ok(plan.steps.filter(step => step.method === 'POST').length <= V1_PRODUCER_LIMITS.writes - 3);
    assert.ok(plan.steps.every(step => !step.key.startsWith('secondary-')));
    assert.equal(plan.steps.filter(step => step.purpose === 'contract-create').length, 26, 'TWENTY_SIX_REAL_CONTRACT_CREATES_REQUIRED');
    assert.deepEqual(plan.steps.filter(step => step.purpose === 'ip-create').map(step => step.family).sort(), ['design', 'patent', 'trademark']);
    assert.equal(plan.steps.filter(step => step.purpose === 'work-parent-create').length, 8, 'SIX_PRIMARY_CONFLICT_AND_REVOKED_PARENTS_REQUIRED');
    assert.equal(plan.steps.filter(step => step.purpose === 'wall-matter-link').length, 1, 'ACTUAL_IP_OPERATIONAL_LINK_REQUIRED');
    assert.equal(plan.steps.filter(step => step.purpose === 'revoked-restricted').length, 1, 'ACTUAL_RESTRICTED_PARENT_REQUIRED');
    assert.equal(plan.steps.filter(step => step.purpose === 'revoked-grant').length, 1, 'ACTUAL_NATIVE_MEMBER_GRANT_REQUIRED');
  } else {
    assert.equal(plan.steps.length, 54, 'EXACT_READTHROUGH_HTTP_INVENTORY_REQUIRED');
    const roles = { 'obligation-create': 11, 'counsel-profile': 1, 'counsel-assignment': 11, 'counsel-spend': 26, 'obligation-page': 2, 'counsel-page': 3 };
    assert.deepEqual(Object.fromEntries(Object.entries(roles).map(([role]) => [role, plan.steps.filter(step => step.purpose === role).length])), roles);
    assert.ok(plan.steps.every(step => Object.hasOwn(roles, step.purpose)));
    assert.equal(plan.steps.filter(step => step.method === 'POST').length, 49);
    assert.ok(plan.steps.every(step => step.method === (step.purpose.endsWith('page') ? 'GET' : 'POST')));
  }
  for (const step of plan.steps) {
    assert.ok(['GET', 'POST'].includes(step.method));
    assert.ok(Array.isArray(step.expectedStatuses) && step.expectedStatuses.length > 0 && step.expectedStatuses.every(status => Number.isInteger(status) && status >= 200 && status < 300));
    if (step.purpose === 'contract-create') assert.ok(step.method === 'POST' && step.route === '/api/contracts/', 'CONTRACT_ROLE_REQUIRES_CONTRACT_API');
    if (step.purpose === 'work-parent-create') assert.ok(step.method === 'POST' && step.route === '/api/matters/', 'WORK_PARENT_ROLE_REQUIRES_MATTER_API');
    if (step.purpose === 'wall-matter-link') { assert.equal(step.method, 'POST'); assert.ok(step.route.endsWith('/matter-links')); assert.equal(step.body?.relation_role, 'operational');
      assert.ok(step.body.expected_docket_updated_at && typeof step.body.reason === 'string' && step.body.reason.length >= 8); }
    if (step.purpose === 'revoked-restricted') { assert.equal(step.method, 'POST'); assert.ok(step.route.endsWith('/access/restricted')); assert.equal(step.body?.restricted, true); }
    if (step.purpose === 'revoked-grant') { assert.equal(step.method, 'POST'); assert.ok(step.route.endsWith('/access/grants')); assert.equal(step.body?.membership_id, plan.membershipId); }
    if (step.purpose === 'ip-create') {
      assert.equal(step.method, 'POST'); assert.equal(step.idempotent, true, 'IP_IDEMPOTENCY_KEY_REQUIRED');
      assert.equal(step.route, { patent: '/api/ip/patents/families', design: '/api/ip/specialist/records', trademark: '/api/ip/trademark-applications/manual' }[step.family], 'ACTUAL_NORMAL_IP_CREATOR_REQUIRED');
      if (step.family === 'design') assert.equal(step.body?.details?.domain, 'design', 'ACTUAL_DESIGN_INTAKE_REQUIRED');
    }
    if (step.method === 'POST' && step.route.endsWith('/hearings')) {
      assert.deepEqual(step.body?.reminder_channels, [], 'SEED_HEARING_MUST_EXPLICITLY_SUPPRESS_CHANNELS');
      assert.deepEqual(step.body?.reminder_recipient_membership_ids, [], 'SEED_HEARING_MUST_NOT_ASSIGN_RECIPIENTS');
      assert.equal(step.body?.notification_critical, false, 'SEED_HEARING_MUST_NOT_BE_CRITICAL');
    }
  }
  noSecrets(plan); return plan;
}
function lookup(observed, reference) {
  assert.ok(typeof reference === 'string' && /^[a-z][a-z0-9-]{1,80}(?:\.[A-Za-z_][A-Za-z0-9_]*|\.[0-9]+)*$/.test(reference), 'SAFE_RESPONSE_REFERENCE_REQUIRED');
  const [name, ...parts] = reference.split('.'); let value = observed.get(name);
  assert.ok(value !== undefined, 'EARLIER_REAL_RESPONSE_REQUIRED');
  for (const part of parts) {
    assert.ok(!['__proto__', 'prototype', 'constructor'].includes(part) && value !== null && typeof value === 'object' && Object.hasOwn(value, part), 'RESPONSE_FIELD_REQUIRED');
    value = value[part];
  }
  return structuredClone(value);
}
export function resolveV1ResponseReferences(value, observed) {
  if (Array.isArray(value)) return value.map(item => resolveV1ResponseReferences(item, observed));
  if (!value || typeof value !== 'object') return value;
  if (Object.keys(value).length === 1 && Object.hasOwn(value, '$response')) return lookup(observed, value.$response);
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, resolveV1ResponseReferences(item, observed)]));
}
function routeFor(step, observed) {
  let route = step.route;
  assert.ok(typeof route === 'string' && route.length <= 500, 'BOUNDED_PRODUCER_ROUTE_REQUIRED');
  for (const [key, ref] of Object.entries(step.routeIds || {})) route = route.replace(`{${key}}`, v1Identity(lookup(observed, ref)));
  assert.ok(!/[{}*?#]/.test(route), 'EXACT_NORMAL_API_ROUTE_REQUIRED');
  const routes = step.phase === 'readthrough' ? step.method === 'POST' ? READTHROUGH_CREATE : READTHROUGH_READ : step.method === 'POST' ? CREATE : READ;
  assert.ok(routes.some(pattern => pattern.test(route)), 'REVIEWED_NORMAL_API_ROUTE_REQUIRED');
  return route;
}
/**
 * The owner actor supplies its normal authenticated API transport after its
 * public/source/private-file admission. This function never creates a token,
 * writes a database row directly, or retries an API command. The caller must
 * persist every event outside Git; a stopped producer is never resumed.
 */
export async function produceV1Dataset(plan, { request, catalogue, persistPrivate, persist, claim, aggregate, planEvidence, admit, readEvidence = readV1Reference, now = Date.now }) {
  requireV1ProducerPlan(plan); assert.equal(typeof request, 'function'); assert.equal(typeof persist, 'function');
  assert.deepEqual(catalogue, readEvidence(plan.catalogueEvidence), 'HASH_BOUND_ACTUAL_CATALOGUE_REQUIRED');
  assert.equal(catalogue.sourceSha, plan.sourceSha, 'ACTUAL_CATALOGUE_SOURCE_REQUIRED');
  assert.equal(catalogue.syntheticDataOnly, true); assert.equal(catalogue.designIntakeRegistered, true, 'REAL_DESIGN_REGISTRATION_REQUIRED');
  assert.equal(catalogue.patentFamilyAvailable, true, 'REAL_PATENT_FAMILY_CONTRACT_REQUIRED');
  assert.equal(catalogue.trademarkManualAvailable, true, 'REAL_TRADEMARK_MANUAL_CONTRACT_REQUIRED');
  assert.ok(aggregate && typeof aggregate.begin === 'function' && typeof aggregate.request === 'function'); v1Reference(planEvidence);
  assert.equal(aggregate.publicState().runId, plan.runId, 'EXACT_FIXTURE_RUN_REQUIRED'); assert.equal(aggregate.publicState().sourceSha, plan.sourceSha, 'EXACT_FIXTURE_SOURCE_REQUIRED');
  aggregate.begin(plan.phase, planEvidence);
  assert.equal(typeof admit, 'function', 'BEFORE_AFTER_ACTUAL_OWNER_ADMISSION_REQUIRED');
  const before = await admit(plan, { boundary: 'before', remaining: () => aggregate.remaining(plan.phase), charge: value => aggregate.request(plan.phase, { ...value, admission: true }) });
  assert.equal(before.beforeMemberRead, true); assert.equal(before.sourceSha, plan.sourceSha); assert.equal(before.apiSourceSha, plan.sourceSha); assert.equal(before.webSourceSha, plan.sourceSha);
  assert.equal(before.companyId, plan.companyId); assert.equal(before.membershipId, plan.ownerMembershipId); assert.equal(before.role, 'owner');
  assert.equal(typeof claim, 'function', 'PERSISTENT_EXCLUSIVE_PRODUCER_CLAIM_REQUIRED');
  const planSha256 = v1Hash(Buffer.from(JSON.stringify(plan))); claim(planSha256);
  const start = now(), deadline = start + V1_PRODUCER_LIMITS.totalMs, observed = new Map(), attempted = new Set();
  const oracleIds = new Set([plan.companyId, plan.membershipId, plan.ownerMembershipId]);
  if (plan.phase === 'readthrough') {
    const base = readEvidence(plan.baseDatasetEvidence), prior = readEvidence(plan.baseProducerEvidence), viewer = readEvidence(plan.viewerEvidence), inbox = readEvidence(plan.inboxEvidence);
    assert.equal(prior.kind, 'actual-normal-api-v1-base-fixture');
    for (const receipt of [prior, viewer, inbox]) { assert.equal(receipt.observed, true); assert.equal(receipt.sourceSha, plan.sourceSha); assert.equal(receipt.automaticRetry, false); assert.equal(receipt.mutationUncertain, false); }
    for (const receipt of [prior, viewer, inbox]) for (const id of validateV1OracleIdentityEvidence(receipt.oracleIdentityEvidence).identities) oracleIds.add(id);
    assert.equal(viewer.kind, 'actual-normal-api-v1-viewer'); assert.equal(viewer.role, 'viewer'); assert.equal(viewer.capabilities.includes('matters:write'), false);
    assert.equal(inbox.kind, 'actual-canonical-in-app-fixture'); assert.equal(inbox.externalCalls, 0); assert.equal(inbox.manualReceiptInsertion, false);
    observed.set('base', structuredClone(base)); observed.set('viewer', structuredClone(viewer)); observed.set('inbox', structuredClone(inbox));
  }
  const events = []; let writes = 0, uncertain = false;
  const record = value => { events.push(value); persist(structuredClone(value)); };
  record({ type: 'v1_producer_started', sourceSha: plan.sourceSha, runId: plan.runId, planSha256, limits: V1_PRODUCER_LIMITS, automaticRetry: false });
  try {
    if (plan.phase === 'base') {
      assert.equal(typeof persistPrivate, 'function', 'CANONICAL_PRIVATE_SECOND_OWNER_WRITER_REQUIRED');
      const identity = plan.secondaryOwner, credentials = { full_name: identity.fullName, email: identity.email, company_slug: identity.companySlug, password: 'Aa1!' + randomBytes(32).toString('base64url') };
      let token = '', enrollment;
      try {
        let file = await persistPrivate(credentials, { kind: 'canonical-local-fixture-private-json', createExclusive: true, mode: 0o600 });
        v1PrivateReference(file.evidence); assert.equal(file.evidence.uid, file.identity.uid); assert.equal(file.mode, 0o600); assert.equal(file.canonicalWriter, 'local-fixture.py');
        const inode = file.identity; assert.ok(inode && typeof inode.ino === 'string' && typeof inode.dev === 'string');
        const secondary = async (key, method, route, body) => {
          assert.equal(attempted.has(key), false); attempted.add(key); aggregate.request('base', { key, method, route });
          if (method === 'POST') { assert.ok(++writes <= V1_PRODUCER_LIMITS.writes); uncertain = true; }
          record({ type: 'v1_producer_request_started', key, method, route, privateBodyOmitted: true, mutationUncertain: uncertain });
          const response = await request({ actor: 'secondary-owner', method, route, body, accessTokenFromNormalBootstrap: token || undefined,
            headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' }, timeoutMs: Math.min(10000, aggregate.remaining('base')), maxResponseBytes: 1048576, automaticRetry: false });
          assert.equal(response.status, 200); assert.equal(response.releaseSha, plan.sourceSha); uncertain = false;
          collectV1OracleIdentities(response.value).forEach(id => oracleIds.add(id));
          record({ type: 'v1_producer_response', key, status: 200, requestId: response.requestId, privateResponseOmitted: true, mutationUncertain: false }); return response.value;
        };
        const owner = await secondary('secondary-bootstrap', 'POST', '/api/bootstrap/company', { company_name: identity.companyName, company_slug: identity.companySlug,
          company_type: 'law_firm', owner_full_name: identity.fullName, owner_email: identity.email, owner_password: credentials.password });
        v1Identity(owner.company.id); v1Identity(owner.membership.id); assert.notEqual(owner.company.id, plan.companyId);
        assert.equal(owner.company.slug, identity.companySlug); assert.equal(owner.membership.role, 'owner'); assert.equal(owner.user.full_name, identity.fullName);
        assert.ok(owner.capabilities.includes('company:manage_users')); assert.ok(typeof owner.access_token === 'string' && owner.access_token);
        token = owner.access_token; owner.access_token = '';
        enrollment = await secondary('secondary-enroll', 'POST', '/api/auth/mfa/enroll', {}); assert.match(enrollment.secret || '', /^[A-Z2-7]{16,128}$/);
        credentials.totp_secret = enrollment.secret;
        const privatePath = file.evidence.path;
        file = await persistPrivate(credentials, { kind: 'canonical-local-fixture-private-json', createExclusive: false, mode: 0o600, expectedEvidence: file.evidence, sameOwnedDescriptor: true });
        assert.equal(file.evidence.path, privatePath); assert.equal(file.mode, 0o600); assert.equal(file.ownedNoFollowSingleLink, true); assert.deepEqual(file.identity, inode); v1PrivateReference(file.evidence); assert.equal(file.evidence.uid, file.identity.uid);
        const verified = await secondary('secondary-enroll-verify', 'POST', '/api/auth/mfa/enroll/verify', { code: totp(enrollment.secret, now()) }); assert.equal(verified.status, 'enrolled');
        const security = await secondary('secondary-security', 'GET', '/api/auth/security'); assert.equal(security.mfa_status, 'enrolled');
        observed.set('secondary-owner', { companyId: owner.company.id, membershipId: owner.membership.id, role: 'owner', mfaEnrolled: true,
          credentialEvidence: file.evidence, companySlug: identity.companySlug, fullName: identity.fullName });
      } finally { token = ''; for (const key of Object.keys(credentials)) credentials[key] = ''; if (enrollment) enrollment.secret = ''; }
    }
    for (const step of plan.steps) {
      assert.ok(now() < deadline, 'V1_PRODUCER_TOTAL_DEADLINE');
      assert.ok(['GET', 'POST'].includes(step.method), 'EXACT_PRODUCER_METHOD_REQUIRED');
      assert.equal(attempted.has(step.key), false, 'PRODUCER_STEP_REPLAY_REFUSED'); attempted.add(step.key);
      const route = routeFor({ ...step, phase: plan.phase }, observed), body = resolveV1ResponseReferences(step.body, observed); noSecrets(body);
      if (step.method === 'POST') { assert.ok(++writes <= V1_PRODUCER_LIMITS.writes, 'V1_PRODUCER_WRITE_BOUND'); uncertain = true; }
      const headers = { 'X-CaseOps-Automated-Test': 'no-paid-providers', ...(step.method === 'POST' ? { 'Content-Type': 'application/json' } : {}),
        ...(step.idempotent ? { 'Idempotency-Key': `${plan.runId}-${step.key}-${randomUUID()}` } : {}) };
      record({ type: 'v1_producer_request_started', key: step.key, method: step.method, route,
        bodySha256: body === undefined ? null : v1Hash(Buffer.from(JSON.stringify(body))), mutationUncertain: uncertain });
      aggregate.request(plan.phase, { key: step.key, method: step.method, route });
      const response = await request({ method: step.method, route, query: resolveV1ResponseReferences(step.query, observed), body, headers,
        timeoutMs: Math.min(V1_PRODUCER_LIMITS.perRequestMs, deadline - now(), aggregate.remaining(plan.phase)), maxResponseBytes: V1_PRODUCER_LIMITS.responseBytes, automaticRetry: false });
      assert.ok(Number.isInteger(response.status) && step.expectedStatuses.includes(response.status), 'V1_PRODUCER_API_STATUS_REQUIRED');
      assert.equal(response.releaseSha, plan.sourceSha, 'V1_PRODUCER_SERVING_SOURCE_CHANGED');
      assert.ok(response.value && typeof response.value === 'object' && !Array.isArray(response.value), 'ACTUAL_PRODUCER_RESPONSE_REQUIRED');
      noSecrets(response.value);
      collectV1OracleIdentities(response.value).forEach(id => oracleIds.add(id));
      if (step.companyPath) assert.equal(lookup(new Map([['current', response.value]]), `current.${step.companyPath}`), plan.companyId, 'PRODUCER_RESPONSE_COMPANY_MISMATCH');
      if (step.identityPath) v1Identity(lookup(new Map([['current', response.value]]), `current.${step.identityPath}`));
      observed.set(step.key, structuredClone(response.value)); uncertain = false;
      record({ type: 'v1_producer_response', key: step.key, status: response.status, requestId: response.requestId,
        responseSha256: v1Hash(Buffer.from(JSON.stringify(response.value))), value: structuredClone(response.value), mutationUncertain: false });
    }
    const fixture = resolveV1ResponseReferences(plan.fixtureProjection, observed);
    assert.equal(fixture.companyId, plan.companyId); assert.equal(fixture.membershipId, plan.membershipId);
    const known = new Set([plan.companyId, plan.membershipId]);
    const ids = value => { if (Array.isArray(value)) value.forEach(ids); else if (value && typeof value === 'object') Object.values(value).forEach(ids); else if (typeof value === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value)) known.add(value); };
    for (const value of observed.values()) ids(value);
    const verifyIds = value => { if (Array.isArray(value)) value.forEach(verifyIds); else if (value && typeof value === 'object') Object.values(value).forEach(verifyIds); else if (typeof value === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value)) assert.ok(known.has(value), 'DATASET_ID_MUST_COME_FROM_ACTUAL_RESPONSE'); };
    verifyIds(fixture.v1.records); fixture.v1.readyForLive = false; fixture.v1.preparedOnly = true;
    const after = await admit(plan, { boundary: 'after', remaining: () => aggregate.remaining(plan.phase), charge: value => aggregate.request(plan.phase, { ...value, admission: true }) });
    assert.equal(after.apiSourceSha, plan.sourceSha); assert.equal(after.webSourceSha, plan.sourceSha);
    const receipt = { schemaVersion: 1, kind: plan.phase === 'base' ? 'actual-normal-api-v1-base-fixture' : 'actual-normal-api-v1-fixture', observed: true, nativeReady: false,
      phase: plan.phase, environment: 'docker-integration', syntheticDataOnly: true,
      sourceSha: plan.sourceSha, runId: plan.runId, companyId: plan.companyId, membershipId: plan.membershipId, ownerMembershipId: plan.ownerMembershipId,
      requests: events.filter(e => e.type === 'v1_producer_request_started').length, writes, directDatabaseWrites: false,
      noPaidMarker: 'no-paid-providers', automaticRetry: false, mutationUncertain: false, catalogueEvidence: plan.catalogueEvidence,
      oracleIdentityEvidence: v1OracleIdentityEvidence([...oracleIds]),
      emptyNotificationPlanEvidence: plan.emptyNotificationPlanEvidence, observations: [...observed].map(([key, value]) => ({ key, sha256: v1Hash(Buffer.from(JSON.stringify(value))) })) };
    if (plan.phase === 'base') receipt.secondaryOwner = observed.get('secondary-owner');
    if (plan.phase === 'readthrough') { receipt.viewerEvidence = plan.viewerEvidence; receipt.baseDatasetEvidence = plan.baseDatasetEvidence; receipt.baseProducerEvidence = plan.baseProducerEvidence; receipt.inboxEvidence = plan.inboxEvidence; }
    record({ type: 'v1_producer_completed', ...receipt }); return { fixture, receipt, events };
  } catch (error) {
    record({ type: 'v1_producer_stopped', observed: false, mutationUncertain: uncertain, attempted: [...attempted],
      reason: 'V1_FIXTURE_PRODUCTION_INCOMPLETE', automaticRetry: false });
    throw error;
  }
}
export function pendingV1ProducerPlan() {
  return { schemaVersion: 1, inventoryId: v1Inventory.inventoryId, preparedOnly: true, readyForLive: false,
    environment: 'docker-integration', syntheticDataOnly: true, noPaidMarker: 'no-paid-providers', directDatabaseWrites: false,
    sourceSha: 'FUTURE_CANONICAL_SOURCE_PENDING', runId: 'FUTURE_OWNED_RUN_PENDING', platform: 'PENDING', companyId: 'PENDING', membershipId: 'PENDING', ownerMembershipId: 'PENDING',
    phase: 'base', secondaryOwner: null, catalogueEvidence: null, emptyNotificationPlanEvidence: null, viewerEvidence: null, baseDatasetEvidence: null, baseProducerEvidence: null, inboxEvidence: null, steps: [], fixtureProjection: null,
    pending: ['actual-current-catalogue-and-design-registration', 'normal-authenticated-owner-transport', 'actual-two-company-members', 'eight-operational-parents',
      '26-contract-creates-and-two-real-cursor-pages', 'three-normal-ip-creates-and-calendar-events', 'revoked-wall-foreign-controls',
      'reviewed-one-shot-gateway-barrier-and-response-loss-controls', 'observed-native-selectors', 'actual-source-artifact-device-backend-auth'] };
}

export function pendingV1InboxPlan() {
  return { schemaVersion: 1, readyForLive: false, preparedOnly: true, environment: 'docker-integration', syntheticDataOnly: true,
    sourceSha: 'FUTURE_SOURCE_PENDING', runId: 'PENDING', noPaidMarker: 'no-paid-providers', companyId: 'PENDING', membershipId: 'PENDING', matterId: 'PENDING',
    workerEvidence: null, managerEvidence: null, postgresEvidence: null, workerReceiptOutput: null };
}

/** Four normal member HTTP operations and one separately enabled canonical
 * worker. Its ninety-second aggregate deadline includes actor admission, the
 * real due wait, lock/query/body work, readback and final serving checks. */
export async function produceV1Inbox(plan, { aggregate, planEvidence, admit, request, executeWorker, persistWorkerRequest, persist, readEvidence = readV1Reference, readCode = readV1Bytes, now = Date.now }) {
  assert.equal(plan?.readyForLive, true, 'INBOX_FIXTURE_PENDING_MUST_NOT_RUN'); assert.equal(plan.preparedOnly, false);
  assert.equal(plan.environment, 'docker-integration'); assert.equal(plan.syntheticDataOnly, true); assert.equal(plan.noPaidMarker, 'no-paid-providers');
  for (const key of ['companyId', 'membershipId', 'matterId']) v1Identity(plan[key]);
  for (const key of ['workerEvidence', 'managerEvidence', 'postgresEvidence']) v1Reference(plan[key]);
  assert.equal(plan.workerEvidence.path, fileURLToPath(new URL('../../../scripts/mobile/local-v1-inbox.py', import.meta.url)));
  assert.equal(plan.managerEvidence.path, fileURLToPath(new URL('../../../scripts/mobile/local-v1-controls.py', import.meta.url)));
  readCode(plan.workerEvidence); readCode(plan.managerEvidence);
  const postgres = readEvidence(plan.postgresEvidence); assert.equal(postgres.observed, true); assert.equal(postgres.readOnly, true); assert.equal(postgres.database, 'caseops_mobile');
  assert.equal(aggregate.publicState().runId, plan.runId, 'EXACT_FIXTURE_RUN_REQUIRED'); assert.equal(aggregate.publicState().sourceSha, plan.sourceSha, 'EXACT_FIXTURE_SOURCE_REQUIRED');
  aggregate.begin('inbox', planEvidence); const started = aggregate.publicState().stages.find(stage => stage.stage === 'inbox').started;
  const admitted = await admit(plan, { boundary: 'before', remaining: () => aggregate.remaining('inbox'), charge: value => aggregate.request('inbox', { ...value, admission: true }) });
  assert.equal(admitted.beforeMemberRead, true); assert.equal(admitted.sourceSha, plan.sourceSha); assert.equal(admitted.apiSourceSha, plan.sourceSha); assert.equal(admitted.webSourceSha, plan.sourceSha);
  assert.equal(admitted.membershipId, plan.membershipId); assert.equal(admitted.companyId, plan.companyId); assert.equal(admitted.role, 'member'); assert.ok(admitted.capabilities.includes('matters:write'));
  let uncertain = false, requests = 0; const calls = [];
  const oracleIds = new Set([plan.companyId, plan.membershipId, plan.matterId]);
  const call = async (key, method, route, body) => {
    aggregate.request('inbox', { key, method, route }); requests++; uncertain = method === 'POST';
    persist({ type: 'v1_inbox_http_started', key, method, route, mutationUncertain: uncertain });
    const response = await request({ key, method, route, body, headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' }, timeoutMs: Math.min(10000, aggregate.remaining('inbox')), maxResponseBytes: 1048576, automaticRetry: false });
    assert.equal(response.status, 200); assert.equal(response.releaseSha, plan.sourceSha); uncertain = false;
    collectV1OracleIdentities(response.value).forEach(id => oracleIds.add(id));
    calls.push({ key, method, route, status: response.status, requestId: response.requestId }); persist({ type: 'v1_inbox_http_ack', ...calls.at(-1) }); return response;
  };
  try {
    const workspace = (await call('inbox-current-parent', 'GET', `/api/matters/${plan.matterId}/workspace`)).value;
    assert.equal(workspace.matter.id, plan.matterId); assert.equal(workspace.matter.company_id, plan.companyId); assert.equal(workspace.matter.is_disposed, false);
    v1Lifecycle(workspace.matter.lifecycle_version);
    const due = now() + 45000; assert.ok(due <= started + 70000, 'INBOX_REAL_DUE_MUST_FIT_SHARED_PHASE');
    const when = new Date(due + 3600000).toISOString(), body = { hearing_on: when.slice(0, 10), hearing_time: when.slice(11, 19), timezone: 'UTC', time_status: 'exact',
      forum_name: 'Synthetic V1 inbox forum', purpose: 'Synthetic V1 due in_app hearing', expected_lifecycle_version: workspace.matter.lifecycle_version,
      reminder_offsets_hours: [1], reminder_channels: ['in_app'], reminder_recipient_membership_ids: [plan.membershipId], notification_critical: false };
    const acknowledgement = await call('inbox-normal-hearing-create', 'POST', `/api/matters/${plan.matterId}/hearings`, body), hearing = acknowledgement.value;
    v1Identity(hearing.id); assert.equal(hearing.matter_id, plan.matterId); assert.deepEqual(hearing.reminder_policy.channels, ['in_app']); assert.equal(hearing.reminder_policy.critical, false);
    const reload = (await call('inbox-hearing-readback', 'GET', `/api/matters/${plan.matterId}/workspace`)).value;
    assert.deepEqual(reload.hearings.filter(record => record.id === hearing.id), [hearing]);
    const workerRequest = { schemaVersion: 1, preparedOnly: false, readyForLive: true, environment: 'docker-integration', syntheticDataOnly: true,
      noPaidMarker: 'no-paid-providers', manualReceiptInsertion: false, sourceSha: plan.sourceSha, runId: plan.runId, companyId: plan.companyId,
      membershipId: plan.membershipId, matterId: plan.matterId, hearingId: hearing.id, phaseStartedMilliseconds: started,
      managerEvidence: { ...plan.managerEvidence, path: '/mobile-fixture/local-v1-controls.py' }, postgresIdentity: postgres,
      hearingAcknowledgement: { method: 'POST', route: `/api/matters/${plan.matterId}/hearings`, status: 200, requestId: acknowledgement.requestId, body, value: hearing } };
    const workerRequestEvidence = await persistWorkerRequest(workerRequest); v1Reference(workerRequestEvidence);
    aggregate.worker('inbox'); uncertain = true;
    let observed = 0;
    const worker = await executeWorker({ requestEvidence: workerRequestEvidence, sourceEvidence: plan.workerEvidence, timeoutMs: aggregate.remaining('inbox'), automaticRetry: false,
      onObserverStatement: sequence => { assert.equal(sequence, ++observed); aggregate.observer('inbox'); } });
    assert.equal(worker.kind, 'actual-canonical-in-app-worker'); assert.equal(worker.observed, true); assert.equal(worker.runId, plan.runId); assert.equal(worker.sourceSha, plan.sourceSha);
    assert.equal(worker.companyId, plan.companyId); assert.equal(worker.membershipId, plan.membershipId); assert.equal(worker.hearingId, hearing.id);
    assert.equal(worker.externalCalls, 0); assert.equal(worker.manualReceiptInsertion, false); assert.equal(worker.workerExecutions, 1); assert.equal(worker.observerStatements, observed); assert.ok(observed > 0);
    collectV1OracleIdentities(worker).forEach(id => oracleIds.add(id));
    uncertain = false;
    const inbox = (await call('inbox-actual-recipient-readback', 'GET', '/api/recipient-inbox?view=active&limit=25')).value;
    assert.equal(inbox.scope, 'delivered_hearing_and_ip_renewal'); const matches = inbox.items.filter(item => item.id === worker.notificationId); assert.equal(matches.length, 1);
    const notification = matches[0]; assert.equal(notification.status, 'unread'); assert.deepEqual(notification.target, { kind: 'matter', id: plan.matterId });
    const after = await admit(plan, { boundary: 'after', remaining: () => aggregate.remaining('inbox'), charge: value => aggregate.request('inbox', { ...value, admission: true }) });
    assert.equal(after.apiSourceSha, plan.sourceSha); assert.equal(after.webSourceSha, plan.sourceSha);
    return { schemaVersion: 1, phase: 'inbox', kind: 'actual-canonical-in-app-fixture', observed: true, sourceSha: plan.sourceSha, runId: plan.runId,
      companyId: plan.companyId, membershipId: plan.membershipId, requests, writes: 1, notification, matter: { ...workspace.matter, identityLabel: workspace.matter.matter_code, search: workspace.matter.matter_code },
      workerRequestEvidence, workerEvidence: plan.workerEvidence, worker, observations: calls, oracleIdentityEvidence: v1OracleIdentityEvidence([...oracleIds]),
      externalCalls: 0, manualReceiptInsertion: false, automaticRetry: false, mutationUncertain: false };
  } catch {
    persist({ type: 'v1_inbox_fixture_stopped', observed: false, mutationUncertain: uncertain, requests, automaticRetry: false });
    throw Error('V1_INBOX_FIXTURE_INCOMPLETE_NO_REPLAY');
  }
}
