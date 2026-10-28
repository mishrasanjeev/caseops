import assert from 'node:assert/strict';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { constants, openSync, closeSync, fstatSync, lstatSync, readSync } from 'node:fs';
import { v1Inventory, V1_BUDGETS } from './v1-workflows-inventory.mjs';

const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
const AWARE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/;
export const V1_CONTROL_CAPABILITIES = Object.freeze([
  'readSource', 'readWorkspace', 'readCurrentActor', 'readNotificationState', 'readObligations', 'readCounsel', 'readInbox',
  'readNativeRequest', 'applyIpPolicy', 'armSourceFault', 'armWorkBarrier',
  'releaseWorkBarrier', 'changeMatterLifecycle', 'changeChild', 'changeMatterAccess',
  'armUnknownResponse', 'readControlReceipt', 'closeCaseControls', 'closeRunControls',
]);
export const v1Hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
export const V1_NATIVE_CREATION_RESERVE = Object.freeze([
  Object.freeze({ caseId: 'WORK-01', kind: 'task', acknowledgement: 'native-post' }),
  Object.freeze({ caseId: 'WORK-03', kind: 'hearing', acknowledgement: 'native-post' }),
  Object.freeze({ caseId: 'WORK-04', kind: 'follow-up-task', acknowledgement: 'workspace-after-native-patch' }),
  Object.freeze({ caseId: 'WORK-06', kind: 'unknown-save-task', acknowledgement: 'gateway-upstream-post' }),
]);
export function collectV1OracleIdentities(...values) {
  const identities = new Set(), seen = new Set(), stack = [...values];
  while (stack.length) {
    const value = stack.pop();
    if (typeof value === 'string' && UUID.test(value)) identities.add(value);
    else if (value && typeof value === 'object' && !seen.has(value)) { seen.add(value); for (const [key, item] of Object.entries(value))
      if (!/password|totp|secret|token|authorization|cookie/i.test(key)) stack.push(item); }
  }
  return [...identities].sort();
}
export function v1OracleIdentityEvidence(...values) {
  const identities = collectV1OracleIdentities(...values);
  return { identities, sha256: v1Hash(Buffer.from(JSON.stringify(identities))) };
}
export function validateV1OracleIdentityEvidence(value) {
  assert.ok(value && Array.isArray(value.identities)); value.identities.forEach(identity => v1Identity(identity));
  assert.deepEqual(value.identities, [...new Set(value.identities)].sort(), 'COMPLETE_UNIQUE_ORACLE_IDENTITIES_REQUIRED');
  assert.equal(value.sha256, v1Hash(Buffer.from(JSON.stringify(value.identities))), 'ORACLE_IDENTITY_HASH_REQUIRED'); return value;
}
export function requiredV1ControlIdentities(records, registration) {
  const ids = new Set();
  for (const route of [...registration.exactRoutes, ...registration.ownerExactRoutes])
    for (const id of route.match(/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}/g) || []) ids.add(id);
  for (const id of collectV1OracleIdentities(registration.actors, registration.ownerRecipes,
    records.access.wall.subjectMembershipId, records.policy.revokedWork.grantId, records.policy.revokedWork.subjectMembershipId,
    records.policy.readOnly.matter.id, records.policy.readOnly.task.id, records.policy.readOnly.hearing.id,
    records.obligations.pages[0].next_after, records.counsel.pages[0].assignment_next_after, records.counsel.pages[0].spend_next_after)) ids.add(id);
  return [...ids].sort();
}
export function validateV1ControlIdentityCapacity(identities) {
  assert.ok(Array.isArray(identities)); identities.forEach(identity => v1Identity(identity));
  assert.equal(new Set(identities).size, identities.length, 'UNIQUE_REGISTERED_CONTROL_IDENTITIES_REQUIRED');
  assert.ok(identities.length > 0 && identities.length + V1_NATIVE_CREATION_RESERVE.length <= 96, 'V1_FOUR_NATIVE_IDENTITIES_MUST_BE_RESERVED');
  return { registeredCount: identities.length, nativeCreationReserve: V1_NATIVE_CREATION_RESERVE, maximumKnownCount: identities.length + 4, unusedHeadroom: 96 - identities.length - 4 };
}
export function reconcileV1ControlIdentities(records, registration, oracleEvidence) {
  validateV1OracleIdentityEvidence(oracleEvidence);
  assert.deepEqual(registration.exactRoutes, strictV1Routes(records), 'COMPLETE_EXACT_NATIVE_ROUTES_REQUIRED');
  const ownerRoutes = [...new Set(registration.ownerRecipes.flatMap(recipe => recipe.requests.map(request => `${request.method} ${request.route}`)))].sort();
  assert.deepEqual([...registration.ownerExactRoutes].sort(), ownerRoutes, 'EXACT_OWNER_RECIPE_ROUTES_REQUIRED');
  const expected = requiredV1ControlIdentities(records, registration), registered = [...registration.syntheticIds].sort();
  assert.deepEqual(registered, expected, 'EXACT_COMPLETE_CONTROL_AUTHORITY_SET_REQUIRED');
  const capacity = validateV1ControlIdentityCapacity(registered);
  for (const id of [...expected, ...collectV1OracleIdentities(records)]) assert.ok(oracleEvidence.identities.includes(id), 'ALL_CONTROL_AND_PAYLOAD_ORACLES_MUST_BE_RETAINED');
  return { ...capacity, controlIdentities: registered, oracleIdentitySha256: oracleEvidence.sha256, oracleCount: oracleEvidence.identities.length,
    payloadOnlyCount: oracleEvidence.identities.filter(id => !expected.includes(id)).length };
}
export const V1_FIXTURE_ENVELOPE = Object.freeze({
  stages: Object.freeze({
    base: Object.freeze({ requests: 96, posts: 64, milliseconds: 180000 }),
    viewer: Object.freeze({ requests: 10, posts: 7, milliseconds: 60000 }),
    inbox: Object.freeze({ requests: 4, posts: 1, milliseconds: 90000, workerExecutions: 1, observerStatements: 20 }),
    readthrough: Object.freeze({ requests: 54, posts: 49, milliseconds: 180000 }),
  }),
  // Each stage: API+web before and after, normal admitted actor login/MFA/current me.
  admissionPerStage: Object.freeze({ requests: 7, posts: 2 }),
  productionRequests: 164, productionPosts: 121, admissionRequests: 28, admissionPosts: 8,
  combinedRequests: 192, combinedPosts: 129, milliseconds: 510000,
});
export const V1_FIXTURE_ADMISSION_HTTP = Object.freeze({
  'api-before': Object.freeze({ method: 'GET', route: '/api/build' }),
  'web-before': Object.freeze({ method: 'GET', route: '/api/release-identity' }),
  'actor-login': Object.freeze({ method: 'POST', route: '/api/auth/login' }),
  'actor-mfa': Object.freeze({ method: 'POST', route: '/api/auth/mfa/step-up' }),
  'actor-identity': Object.freeze({ method: 'GET', route: '/api/auth/me' }),
  'api-after': Object.freeze({ method: 'GET', route: '/api/build' }),
  'web-after': Object.freeze({ method: 'GET', route: '/api/release-identity' }),
});
/** One externally claimed run and four consumed-before-effect stage claims.
 * The caller must persist this ledger and every original phase receipt. No
 * failed/unknown phase can be resumed or replaced by a renamed stage. */
export function createV1FixtureAggregate({ runId, sourceSha, claim, persist, now = Date.now }) {
  assert.match(runId || '', /^v1-[a-f0-9-]{16,80}$/); assert.match(sourceSha || '', /^[a-f0-9]{40}$/);
  assert.equal(typeof claim, 'function'); assert.equal(typeof persist, 'function');
  claim(`fixture-run:${runId}`); const started = now(), phases = new Map(), keys = new Set();
  const publicState = () => ({ runId, sourceSha, elapsedMilliseconds: now() - started, stages: [...phases].map(([stage, value]) => ({ stage, ...value })) });
  const live = stage => { const value = phases.get(stage); assert.ok(value && !value.completed, 'UNFINISHED_CLAIMED_FIXTURE_STAGE_REQUIRED');
    assert.ok(now() - started <= V1_FIXTURE_ENVELOPE.milliseconds && now() - value.started <= V1_FIXTURE_ENVELOPE.stages[stage].milliseconds, 'V1_WHOLE_FIXTURE_DEADLINE'); return value; };
  return {
    begin(stage, planEvidence) {
      assert.ok(Object.hasOwn(V1_FIXTURE_ENVELOPE.stages, stage)); v1Reference(planEvidence);
      assert.equal(phases.has(stage), false, 'FIXTURE_STAGE_UNKNOWN_OR_COMPLETED_MUST_NOT_REPLAY');
      assert.equal(phases.size, ['base', 'viewer', 'inbox', 'readthrough'].indexOf(stage), 'EXACT_FIXTURE_STAGE_ORDER_REQUIRED');
      assert.ok([...phases.values()].every(phase => phase.completed), 'EARLIER_ORIGINAL_STAGE_RECEIPT_REQUIRED');
      claim(`fixture-stage:${runId}:${stage}`);
      phases.set(stage, { started: now(), requests: 0, posts: 0, admissionRequests: 0, admissionPosts: 0, observerStatements: 0, workerExecutions: 0, completed: false, planEvidence });
      persist({ type: 'v1_fixture_stage_claimed', stage, runId, sourceSha, planEvidence });
    },
    request(stage, { key, method, route, admission = false }) {
      const value = live(stage); assert.ok(typeof key === 'string' && key.length <= 160 && !keys.has(`${stage}:${key}`), 'FIXTURE_HTTP_REPLAY_REFUSED');
      assert.ok(['GET', 'POST'].includes(method)); keys.add(`${stage}:${key}`);
      if (admission) assert.deepEqual({ method, route }, V1_FIXTURE_ADMISSION_HTTP[key], 'EXACT_ADMISSION_HTTP_INVENTORY_REQUIRED');
      const limits = admission ? V1_FIXTURE_ENVELOPE.admissionPerStage : V1_FIXTURE_ENVELOPE.stages[stage];
      const count = admission ? 'admissionRequests' : 'requests', posts = admission ? 'admissionPosts' : 'posts';
      assert.ok(++value[count] <= limits.requests, 'FIXTURE_STAGE_HTTP_BOUND'); if (method === 'POST') assert.ok(++value[posts] <= limits.posts, 'FIXTURE_STAGE_POST_BOUND');
      const all = [...phases.values()]; assert.ok(all.reduce((sum, phase) => sum + phase.requests + phase.admissionRequests, 0) <= V1_FIXTURE_ENVELOPE.combinedRequests);
      assert.ok(all.reduce((sum, phase) => sum + phase.posts + phase.admissionPosts, 0) <= V1_FIXTURE_ENVELOPE.combinedPosts);
      persist({ type: 'v1_fixture_http_charged', stage, key, method, route, admission, runId });
    },
    observer(stage) { const value = live(stage); assert.equal(stage, 'inbox'); assert.ok(++value.observerStatements <= 20, 'INBOX_OBSERVER_STATEMENT_BOUND'); },
    worker(stage) { const value = live(stage); assert.equal(stage, 'inbox'); assert.ok(++value.workerExecutions <= 1, 'INBOX_WORKER_REPLAY_REFUSED'); claim(`fixture-worker:${runId}:inbox`); },
    complete(stage, receiptEvidence) { const value = live(stage); v1Reference(receiptEvidence); value.completed = true; value.receiptEvidence = receiptEvidence;
      persist({ type: 'v1_fixture_stage_completed', stage, runId, receiptEvidence, counters: { ...value } }); },
    finish() {
      assert.ok(now() - started <= V1_FIXTURE_ENVELOPE.milliseconds, 'V1_WHOLE_FIXTURE_DEADLINE');
      assert.deepEqual([...phases.keys()], ['base', 'viewer', 'inbox', 'readthrough']); assert.ok([...phases.values()].every(phase => phase.completed), 'ALL_ORIGINAL_FIXTURE_RECEIPTS_REQUIRED');
      for (const [stage, phase] of phases) {
        assert.equal(phase.admissionRequests, 7, 'ALL_STAGE_ADMISSION_HTTP_MUST_BE_CHARGED'); assert.equal(phase.admissionPosts, 2);
        assert.ok(Object.keys(V1_FIXTURE_ADMISSION_HTTP).every(key => keys.has(`${stage}:${key}`)), 'EXACT_ADMISSION_HTTP_INVENTORY_REQUIRED');
        if (stage !== 'base') { assert.equal(phase.requests, V1_FIXTURE_ENVELOPE.stages[stage].requests); assert.equal(phase.posts, V1_FIXTURE_ENVELOPE.stages[stage].posts); }
        if (stage === 'inbox') { assert.equal(phase.workerExecutions, 1); assert.ok(phase.observerStatements > 0 && phase.observerStatements <= 20); }
      }
      const states = publicState(); return { schemaVersion: 1, kind: 'actual-complete-v1-fixture-aggregate', observed: true, ...states, envelope: V1_FIXTURE_ENVELOPE, automaticRetry: false };
    },
    remaining(stage) { const phase = live(stage); return Math.min(V1_FIXTURE_ENVELOPE.milliseconds - (now() - started), V1_FIXTURE_ENVELOPE.stages[stage].milliseconds - (now() - phase.started)); },
    publicState,
  };
}
export function v1Reference(value, code = 'HASH_BOUND_V1_REFERENCE_REQUIRED') {
  assert.ok(value && path.isAbsolute(value.path || '') && path.resolve(value.path) === value.path && SHA.test(value.sha256 || ''), code);
  return value;
}
export function v1PrivateReference(value) {
  v1Reference(value);
  assert.deepEqual(Object.keys(value).sort(), ['path', 'sha256', 'uid'], 'EXACT_PRIVATE_DESCRIPTOR_REFERENCE_REQUIRED');
  assert.ok(Number.isSafeInteger(value.uid) && value.uid >= 0, 'ACTUAL_PRIVATE_DESCRIPTOR_UID_REQUIRED');
  return value;
}
export function validateV1FixtureAggregate(value, sourceSha, load = readV1Reference) {
  assert.equal(value.kind, 'actual-complete-v1-fixture-aggregate'); assert.equal(value.observed, true); assert.equal(value.sourceSha, sourceSha);
  assert.deepEqual(value.envelope, V1_FIXTURE_ENVELOPE); assert.equal(value.automaticRetry, false);
  assert.deepEqual(value.stages.map(stage => stage.stage), ['base', 'viewer', 'inbox', 'readthrough']);
  assert.ok(Number.isFinite(value.elapsedMilliseconds) && value.elapsedMilliseconds >= 0 && value.elapsedMilliseconds <= V1_FIXTURE_ENVELOPE.milliseconds);
  let requests = 0, posts = 0; const oracleIdentities = new Set(); let finalOracleEvidence;
  const kinds = { base: 'actual-normal-api-v1-base-fixture', viewer: 'actual-normal-api-v1-viewer', inbox: 'actual-canonical-in-app-fixture', readthrough: 'actual-normal-api-v1-fixture' };
  for (const stage of value.stages) {
    const limits = V1_FIXTURE_ENVELOPE.stages[stage.stage]; assert.equal(stage.completed, true);
    v1Reference(stage.planEvidence); const plan = load(stage.planEvidence); assert.equal(plan.sourceSha, sourceSha); assert.equal(plan.runId, value.runId);
    assert.equal(plan.readyForLive, true); assert.equal(plan.preparedOnly, false); v1Reference(stage.receiptEvidence);
    const receipt = load(stage.receiptEvidence); assert.equal(receipt.kind, kinds[stage.stage]); assert.equal(receipt.sourceSha, sourceSha); assert.equal(receipt.runId, value.runId);
    assert.equal(receipt.observed, true); assert.equal(receipt.automaticRetry, false); assert.equal(receipt.mutationUncertain, false);
    validateV1OracleIdentityEvidence(receipt.oracleIdentityEvidence);
    for (const id of receipt.oracleIdentityEvidence.identities) oracleIdentities.add(id);
    if (stage.stage === 'readthrough') finalOracleEvidence = receipt.oracleIdentityEvidence;
    assert.equal(receipt.requests, stage.requests); assert.equal(receipt.writes, stage.posts);
    for (const key of ['requests', 'posts', 'admissionRequests', 'admissionPosts']) assert.ok(Number.isSafeInteger(stage[key]) && stage[key] >= 0);
    assert.ok(stage.requests <= limits.requests && stage.posts <= limits.posts); assert.equal(stage.admissionRequests, 7); assert.equal(stage.admissionPosts, 2);
    if (stage.stage !== 'base') { assert.equal(stage.requests, limits.requests); assert.equal(stage.posts, limits.posts); }
    if (stage.stage === 'inbox') { assert.equal(stage.workerExecutions, 1); assert.ok(Number.isSafeInteger(stage.observerStatements) && stage.observerStatements > 0 && stage.observerStatements <= 20); }
    requests += stage.requests + stage.admissionRequests; posts += stage.posts + stage.admissionPosts;
  }
  assert.ok(requests <= V1_FIXTURE_ENVELOPE.combinedRequests && posts <= V1_FIXTURE_ENVELOPE.combinedPosts);
  assert.deepEqual(finalOracleEvidence, v1OracleIdentityEvidence([...oracleIdentities]), 'ALL_FOUR_PHASE_PAYLOAD_ORACLES_REQUIRED');
  return value;
}
export function readV1Bytes(value, maximum = 1048576) {
  v1Reference(value);
  assert.ok(Number.isSafeInteger(maximum) && maximum > 0 && maximum <= 4194304, 'BOUNDED_V1_EVIDENCE_REQUIRED');
  const fd = openSync(value.path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | constants.O_NONBLOCK);
  let bytes;
  try {
    const a = fstatSync(fd, { bigint: true }), named = lstatSync(value.path, { bigint: true });
    const regular = s => s.isFile() && !s.isSymbolicLink() && s.size > 0n && s.size <= BigInt(maximum);
    const same = (x, y, namedPath) => ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs', 'uid', 'gid', 'mode', 'nlink']
      .every(key => (namedPath && process.platform === 'win32' && key === 'dev' && y.dev === 0n) || x[key] === y[key]);
    assert.ok(regular(a) && regular(named) && same(a, named, true), 'V1_EVIDENCE_IDENTITY_CHANGED');
    const buffer = Buffer.alloc(maximum + 1); let length = 0;
    while (length < buffer.length) { const n = readSync(fd, buffer, length, buffer.length - length, null); if (!n) break; length += n; }
    const after = fstatSync(fd, { bigint: true }), final = lstatSync(value.path, { bigint: true });
    assert.ok(length <= maximum && BigInt(length) === a.size && regular(final)
      && same(a, after, false) && same(a, final, true) && same(named, final, false), 'V1_EVIDENCE_CHANGED_OR_OVERBOUND');
    bytes = buffer.subarray(0, length); assert.equal(v1Hash(bytes), value.sha256, 'V1_EVIDENCE_HASH_MISMATCH');
  } finally { closeSync(fd); }
  return Buffer.from(bytes);
}
export function readV1Reference(value, maximum = 1048576) {
  const bytes = readV1Bytes(value, maximum);
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw Error('V1_EVIDENCE_JSON_REQUIRED'); }
}
export function v1Identity(value, code = 'EXACT_V1_IDENTITY_REQUIRED') {
  assert.match(value || '', UUID, code); return value;
}
export function v1Version(value, kind) {
  if (kind === 'task') assert.ok(AWARE.test(value || '') && Number.isFinite(Date.parse(value)), 'AWARE_TASK_VERSION_REQUIRED');
  else assert.match(value || '', /^mhv1:[a-f0-9]{64}$/, 'CURRENT_HEARING_HMAC_REQUIRED');
  return value;
}
export function v1Lifecycle(value) {
  assert.ok(Number.isSafeInteger(value) && value >= 0, 'STRICT_PARENT_LIFECYCLE_REQUIRED'); return value;
}
export function requirePreparedV1(config) {
  assert.equal(config?.schemaVersion, 1, 'V1_REQUEST_VERSION_REQUIRED');
  assert.equal(config.readyForLive, true, 'V1_PREPARED_ONLY_MUST_NOT_RUN');
  assert.equal(config.preparedOnly, false, 'V1_PREPARED_ONLY_MUST_NOT_RUN');
  assert.equal(config.inventoryId, v1Inventory.inventoryId, 'EXACT_V1_REQUEST_INVENTORY_REQUIRED');
  assert.ok(v1Inventory.platforms.includes(config.platform), 'SUPPORTED_V1_PLATFORM_REQUIRED');
  assert.match(config.expectedSourceSha || '', /^[a-f0-9]{40}$/, 'FUTURE_V1_SOURCE_REQUIRED');
  assert.match(config.expectedSourceFingerprint || '', SHA, 'FUTURE_V1_INPUTS_REQUIRED');
  assert.ok(Number.isSafeInteger(config.expectedInputFileCount) && config.expectedInputFileCount > 0, 'EXACT_V1_INPUT_COUNT_REQUIRED');
  assert.match(config.expectedBinaryHash || '', SHA, 'ACTUAL_V1_BINARY_REQUIRED');
  for (const key of ['fixtureEvidence', 'buildReceipt', 'dockerReceipt', 'deviceEvidence', 'installedEvidence',
    'authObservation', 'producerEvidence', 'viewerEvidence', 'inboxEvidence', 'aggregateFixtureEvidence', 'controlsEvidence', 'gatewayEvidence', 'codeClosure']) v1Reference(config[key]);
  assert.ok(Array.isArray(config.members) && config.members.length === 2, 'TWO_NORMAL_COMPANY_MEMBERS_REQUIRED');
  for (const member of config.members) { v1PrivateReference(member.credentialEvidence); v1Reference(member.fixtureEvidence); v1Reference(member.authObservation); }
  assert.ok(path.isAbsolute(config.reportRoot || '') && path.isAbsolute(config.repoRoot || ''), 'ABSOLUTE_V1_OWNED_PATHS_REQUIRED');
  return config;
}
export function validateV1BaseFixture(fixture, platform) {
  const v = fixture?.v1;
  assert.equal(v?.inventoryId, v1Inventory.inventoryId, 'EXACT_V1_SUPPLEMENT_REQUIRED');
  assert.equal(fixture.environment, 'docker-integration', 'ISOLATED_V1_FIXTURE_REQUIRED');
  assert.equal(fixture.syntheticDataOnly, true, 'SYNTHETIC_V1_FIXTURE_REQUIRED');
  assert.equal(v.platform, platform, 'INDEPENDENT_V1_PLATFORM_REQUIRED');
  assert.equal(v.readyForLive, true, 'PREPARED_V1_FIXTURE_MUST_NOT_RUN');
  assert.equal(v.preparedOnly, false, 'PREPARED_V1_FIXTURE_MUST_NOT_RUN');
  for (const key of ['companyId', 'membershipId']) v1Identity(fixture[key]);
  assert.equal(v.records.companyId, fixture.companyId, 'V1_RECORD_COMPANY_MISMATCH');
  const records = v.records;
  assert.equal(records.calendar.sources.length, 3, 'THREE_ACTUAL_IP_SOURCE_TYPES_REQUIRED');
  assert.deepEqual(records.calendar.sources.map(x => x.family).sort(), ['design', 'patent', 'trademark']);
  for (const source of records.calendar.sources) {
    v1Identity(source.docket.id); assert.equal(source.docket.company_id, fixture.companyId);
    assert.equal(source.event.ip_docket_id, source.docket.id, 'CALENDAR_DOCKET_IDENTITY_REQUIRED');
    assert.ok(typeof source.docket.record_type === 'string' && source.docket.record_type.length > 1, 'ACTUAL_GENERIC_RECORD_TYPE_REQUIRED');
    assert.equal(source.docket.id, source.expected.sourceId);
    assert.equal(source.docket.record_type, { patent: 'patent_family', design: 'design_intake', trademark: 'trademark' }[source.family], 'ACTUAL_IP_FAMILY_TYPE_REQUIRED');
  }
  assert.equal(records.contracts.pages.length, 2, 'TWO_REAL_CONTRACT_PAGES_REQUIRED');
  assert.equal(records.contracts.pages[0].contracts.length, 25, 'REAL_FIRST_CONTRACT_PAGE_REQUIRED');
  assert.ok(records.contracts.pages[0].next_cursor && records.contracts.pages[1].contracts.length > 0, 'REAL_CURSOR_CONTINUATION_REQUIRED');
  const ids = records.contracts.pages.flatMap(page => page.contracts.map(row => {
    v1Identity(row.id); assert.equal(row.company_id, fixture.companyId); return row.id;
  }));
  assert.equal(new Set(ids).size, ids.length, 'UNIQUE_CONTRACT_PAGE_MEMBERSHIP_REQUIRED');
  for (const row of [records.contracts.nullable, records.contracts.minorUnit]) {
    v1Identity(row.id); assert.equal(row.company_id, fixture.companyId); assert.ok(ids.includes(row.id));
  }
  assert.equal(records.contracts.nullable.effective_on, null);
  assert.equal(records.contracts.nullable.expires_on, null);
  assert.equal(records.contracts.nullable.total_value_minor, null);
  assert.equal(records.contracts.minorUnit.total_value_minor, 1, 'INDEPENDENT_ONE_MINOR_UNIT_REQUIRED');
  assert.equal(records.contracts.minorUnit.currency, 'INR');
  assert.equal(records.contracts.minorUnitExpectedLabel, 'INR 1 minor unit', 'LITERAL_MINOR_UNIT_DISPLAY_REQUIRED');
  assert.ok(Array.isArray(records.work.targets) && records.work.targets.length === 6, 'SIX_INDEPENDENT_WORK_TARGETS_REQUIRED');
  const parents = records.work.targets.map(target => { v1Identity(target.matter.id); v1Lifecycle(target.matter.lifecycle_version); return target.matter.id; });
  assert.equal(new Set(parents).size, 6, 'INDEPENDENT_WORK_PARENTS_REQUIRED');
  for (const target of records.work.targets) {
    assert.equal(target.matter.company_id, fixture.companyId); assert.equal(target.matter.is_disposed, false);
    if (target.task) { v1Identity(target.task.id); assert.equal(target.task.matter_id, target.matter.id); v1Version(target.task.updated_at, 'task'); assert.equal(target.task.immutable_lifecycle_history, false); }
    if (target.hearing) { v1Identity(target.hearing.id); assert.equal(target.hearing.matter_id, target.matter.id); v1Version(target.hearing.record_version, 'hearing'); assert.equal(target.hearing.immutable_lifecycle_history, false); }
  }
  assert.equal(v.notificationPolicy.explicitEmptyChannelsBackendVerified, true, 'REAL_EMPTY_CHANNEL_BACKEND_PROOF_REQUIRED');
  v1Reference(v.notificationPolicy.evidence);
  assert.equal(v.notificationPolicy.channels.length, 0); assert.equal(v.notificationPolicy.critical, false);
  v1Reference(v.controls.evidence); assert.deepEqual(v.controls.capabilities, V1_CONTROL_CAPABILITIES);
  assert.equal(v.controls.mutationsUseNormalApis, true); assert.equal(v.controls.directDatabaseWrites, false);
  assert.equal(v.controls.noPaidMarker, 'no-paid-providers');
  assert.deepEqual(records.access.faults.map(x => x.mode), ['readiness-revoked', 'grant-revoked', 'missing', 'offline', 'malformed'], 'ALL_SOURCE_FAILURE_BOUNDARIES_REQUIRED');
  assert.deepEqual(records.work.targets[4].races.map(x => x.kind), ['parent', 'child'], 'BOTH_STALE_WORK_RACES_REQUIRED');
  const wall = records.access.wall;
  v1Identity(wall.docket.id); assert.equal(wall.docket.company_id, fixture.companyId); v1Identity(wall.linkedMatter.id);
  assert.equal(wall.docket.matter_id, wall.linkedMatter.id, 'ACTUAL_WALL_LINK_LINEAGE_REQUIRED');
  assert.equal(wall.subjectMembershipId, fixture.membershipId); v1Reference(wall.initialPolicyEvidence);
  const policy = records.policy;
  v1Reference(policy.viewerEvidence); v1Reference(policy.readOnlyMemberFixture);
  assert.equal(policy.readOnly.expectedRole, 'viewer'); assert.equal(policy.readOnly.expectedCanWrite, false);
  v1Identity(policy.readOnly.matter.id); v1Identity(policy.readOnly.task.id); v1Identity(policy.readOnly.hearing.id);
  assert.equal(policy.readOnly.task.matter_id, policy.readOnly.matter.id); assert.equal(policy.readOnly.hearing.matter_id, policy.readOnly.matter.id);
  assert.notEqual(policy.readOnly.matter.company_id, fixture.companyId, 'INDEPENDENT_VIEWER_COMPANY_REQUIRED');
  v1Lifecycle(policy.readOnly.matter.lifecycle_version); assert.equal(policy.readOnly.matter.is_disposed, false);
  v1Version(policy.readOnly.task.updated_at, 'task'); v1Version(policy.readOnly.hearing.record_version, 'hearing');
  assert.equal(policy.readOnly.task.immutable_lifecycle_history, false); assert.equal(policy.readOnly.hearing.immutable_lifecycle_history, false);
  const revoked = policy.revokedWork;
  v1Identity(revoked.matter.id); assert.equal(revoked.matter.company_id, fixture.companyId); v1Identity(revoked.task.id);
  assert.equal(revoked.task.matter_id, revoked.matter.id); v1Identity(revoked.grantId);
  assert.equal(revoked.subjectMembershipId, fixture.membershipId); assert.equal(revoked.matter.restricted_access, true);
  assert.ok(!parents.includes(revoked.matter.id), 'INDEPENDENT_REVOKED_WORK_PARENT_REQUIRED');
  assert.equal(wall.linkedMatter.company_id, fixture.companyId);
  return fixture;
}
export function validateV1Fixture(fixture, platform) {
  validateV1BaseFixture(fixture, platform);
  const records = fixture.v1.records, obligations = records.obligations, counsel = records.counsel, inbox = records.inbox;
  assert.ok(records.contracts.pages.flatMap(page => page.contracts).some(record => record.id === obligations.contractId), 'ACTUAL_OBLIGATION_PARENT_REQUIRED');
  assert.equal(obligations.companyId, fixture.companyId); assert.equal(obligations.pages.length, 2);
  assert.equal(obligations.pages[0].limit, 10); assert.equal(obligations.pages[0].obligations.length, 10);
  assert.equal(obligations.pages[1].limit, 10); assert.equal(obligations.pages[1].obligations.length, 1);
  const children = obligations.pages.flatMap(page => page.obligations);
  assert.deepEqual(children.map(record => record.id), children.map(record => record.id).toSorted());
  assert.equal(new Set(children.map(record => record.id)).size, 11);
  for (const page of obligations.pages) {
    assert.equal(page.company_id, fixture.companyId); assert.equal(page.contract_id, obligations.contractId); assert.equal(page.ordering, 'id_ascending');
    for (const record of page.obligations) { v1Identity(record.id); assert.equal(record.contract_id, obligations.contractId); }
  }
  assert.equal(obligations.pages[0].next_after, obligations.pages[0].obligations.at(-1).id); assert.equal(obligations.pages[1].next_after, null);
  assert.ok(children.some(record => record.due_on === null && record.owner_membership_id === null && record.owner_name === null), 'ACTUAL_NULL_OBLIGATION_REQUIRED');
  assert.ok(children.some(record => typeof record.due_on === 'string' && record.owner_membership_id === fixture.membershipId && typeof record.owner_name === 'string'), 'ACTUAL_ASSIGNED_DATED_OBLIGATION_REQUIRED');
  const preview = obligations.retainedPreview;
  assert.ok(preview === null || preview && preview.observed === true && preview.record.description_truncated === true);
  if (preview) { v1Reference(preview.evidence); assert.deepEqual(preview.record, children.find(record => record.id === preview.record.id), 'ACTUAL_RETAINED_PREVIEW_ROW_REQUIRED'); }
  v1Identity(counsel.matter.id); assert.equal(counsel.matter.company_id, fixture.companyId);
  assert.equal(counsel.pages.length, 3); const [initial, assignmentPage, spendPage] = counsel.pages;
  for (const page of counsel.pages) {
    assert.equal(page.matter_id, counsel.matter.id); assert.equal(page.assignment_limit, 10); assert.equal(page.spend_limit, 25); assert.equal(page.totals_scope, 'page');
    for (const record of [...page.assignments, ...page.spend_records]) { v1Identity(record.id); assert.equal(record.matter_id, counsel.matter.id); assert.equal(record.company_id, fixture.companyId); }
  }
  assert.equal(initial.assignments.length, 10); assert.equal(initial.spend_records.length, 25);
  for (const values of [[...initial.assignments, ...assignmentPage.assignments], [...initial.spend_records, ...spendPage.spend_records]]) {
    const identities = values.map(record => record.id); assert.equal(new Set(identities).size, identities.length); assert.deepEqual(identities, identities.toSorted());
  }
  assert.equal(initial.assignment_next_after, initial.assignments.at(-1).id); assert.equal(initial.spend_next_after, initial.spend_records.at(-1).id);
  assert.equal(assignmentPage.assignments.length, 1); assert.equal(assignmentPage.assignment_next_after, null);
  assert.deepEqual(assignmentPage.spend_records, initial.spend_records);
  assert.deepEqual(spendPage.assignments, assignmentPage.assignments); assert.equal(spendPage.spend_records.length, 1); assert.equal(spendPage.spend_next_after, null);
  assert.ok(counsel.moneyFacts.some(fact => fact.recordId === spendPage.assignments[0].id && fact.fieldId === 'counsel-assignment-budget' && fact.currency === 'INR'
    && fact.minorUnits === 1 && spendPage.assignments[0].budget_amount_minor === 1 && fact.expectedLabel === 'INR 0.01 (1 paisa)'), 'INDEPENDENT_COUNSEL_PAISA_ORACLE_REQUIRED');
  assert.ok(spendPage.currencies.length > 0, 'ACTUAL_COUNSEL_PAGE_CURRENCIES_REQUIRED');
  v1Reference(inbox.deliveryEvidence); assert.equal(inbox.membershipId, fixture.membershipId); assert.equal(inbox.companyId, fixture.companyId);
  v1Identity(inbox.notification.id); assert.equal(inbox.notification.status, 'unread'); assert.equal(inbox.notification.target.kind, 'matter');
  assert.equal(inbox.notification.target.id, inbox.matter.id); assert.equal(inbox.matter.company_id, fixture.companyId);
  assert.deepEqual(inbox.transitions, ['read', 'dismissed', 'unread']);
  assert.equal(inbox.externalCalls, 0); assert.equal(inbox.manualReceiptInsertion, false);
  return fixture;
}
export function validateV1ExecutionFixture(fixture, platform) {
  validateV1Fixture(fixture, platform);
  const { records, nativeSelectors } = fixture.v1;
  const text = value => assert.ok(typeof value === 'string' && value.length > 0 && value.length <= 4000, 'COMPLETE_PUBLIC_V1_EXECUTION_FACT_REQUIRED');
  const fields = value => { assert.ok(value && typeof value === 'object' && !Array.isArray(value)); for (const item of Object.values(value)) assert.equal(typeof item, 'string'); };
  assert.equal(nativeSelectors?.observed, true); assert.equal(nativeSelectors.platform, platform);
  assert.equal(nativeSelectors.udid, fixture.udid); assert.deepEqual(nativeSelectors.buildReceipt, fixture.buildReceipt);
  assert.ok(nativeSelectors.segments && typeof nativeSelectors.segments === 'object');
  for (const key of ['day', 'dayLabel', 'nextWeekLabel']) text(records.calendar[key]);
  assert.match(records.calendar.day, /^\d{4}-\d{2}-\d{2}$/);
  for (const source of records.calendar.sources) {
    v1Identity(source.event.id); text(source.docket.status); v1Version(source.docket.updated_at, 'task');
    assert.ok(Array.isArray(source.rowFields) && source.rowFields.length === 3); source.rowFields.forEach(text);
  }
  const contracts = records.contracts.pages.flatMap(page => page.contracts);
  assert.deepEqual(records.contracts.rows.map(row => row.id).sort(), contracts.map(row => row.id).sort());
  for (const row of records.contracts.rows) { assert.equal(row.fields.length, 3); row.fields.forEach(text); }
  for (const contract of contracts) { text(contract.contract_code); text(contract.status); v1Version(contract.updated_at, 'task'); }
  v1Reference(records.secondCompany.fixtureEvidence);
  assert.ok(contracts.some(record => record.id === records.access.contract.id));
  assert.ok(records.calendar.sources.some(source => source.docket.id === records.access.ip.docket.id));
  for (const fault of records.access.faults) {
    assert.ok(['source-unavailable', 'source-error'].includes(fault.expectedRoot)); text(fault.expectedTitle);
    if (['missing', 'offline', 'malformed'].includes(fault.mode)) assert.equal(fault.route, `/api/contracts/${records.access.contract.id}`);
  }
  for (const index of [0, 2, 5]) { fields(records.work.targets[index].create.fields); assert.ok(records.work.targets[index].create.body); }
  const hearing = records.work.targets[2].create.body;
  assert.deepEqual(hearing.reminder_channels, []); assert.deepEqual(hearing.reminder_recipient_membership_ids, []); assert.equal(hearing.notification_critical, false);
  assert.ok(records.work.targets[1].task); assert.ok(records.work.targets[3].hearing);
  const transitions = records.work.targets[3].transitions;
  assert.equal(transitions.length, 2); assert.equal(transitions[1].body.status, 'completed');
  assert.equal(typeof transitions[1].body.create_follow_up, 'boolean');
  for (const transition of transitions) { fields(transition.fields); assert.ok(transition.body && transition.expected && transition.rowFacts); }
  for (const race of records.work.targets[4].races) {
    v1Identity(race.matter.id); assert.equal(race.matter.company_id, fixture.companyId); v1Identity(race.task.id);
    assert.equal(race.task.matter_id, race.matter.id); v1Version(race.task.updated_at, 'task');
    assert.equal(race.expectedCanStartNewRequest, race.kind === 'child'); text(race.attemptedTitle); assert.ok(race.change && race.rowFacts);
  }
  fields(records.policy.revokedWork.fields); assert.ok(records.policy.revokedWork.body && typeof records.policy.revokedWork.body === 'object');
  assert.equal(records.policy.revokedWork.task.immutable_lifecycle_history, false); v1Version(records.policy.revokedWork.task.updated_at, 'task');
  assert.ok(records.policy.revokedWork.rowFacts); assert.ok(records.policy.readOnly.rowFacts);
  const wall = records.access.wall;
  v1Identity(wall.event.id); assert.equal(wall.event.ip_docket_id, wall.docket.id);
  assert.equal(wall.rowFields.length, 3); wall.rowFields.forEach(text);
  for (const target of [...records.work.targets.flatMap(value => [value, ...(value.races || []).filter(race => race.matter)]), records.policy.readOnly, records.policy.revokedWork]) {
    text(target.matter.search); text(target.matter.identityLabel); text(target.matter.title);
  }
  for (const [kind, record] of [['task', records.policy.readOnly.task], ['hearing', records.policy.readOnly.hearing], ['task', records.policy.revokedWork.task]]) {
    const target = record.id === records.policy.revokedWork.task.id ? records.policy.revokedWork : records.policy.readOnly;
    assert.equal(target.rowFacts[kind][record.id].length, 3); target.rowFacts[kind][record.id].forEach(text);
  }
  const obligations = records.obligations, children = obligations.pages.flatMap(page => page.obligations);
  for (const record of children) {
    assert.equal(obligations.rowFacts[record.id].length, 3); obligations.rowFacts[record.id].forEach(text);
    fields(obligations.detailFacts[record.id]); assert.equal(obligations.detailFacts[record.id]['obligation-id'], record.id);
  }
  for (const key of ['nullable', 'assigned']) assert.deepEqual(obligations[key], children.find(record => record.id === obligations[key].id));
  assert.equal(obligations.detailFacts[obligations.nullable.id]['obligation-due'], 'Not recorded');
  assert.equal(obligations.detailFacts[obligations.nullable.id]['obligation-owner-name'], 'Not recorded');
  assert.equal(obligations.detailFacts[obligations.nullable.id]['obligation-owner-id'], 'Not recorded');
  text(obligations.detailFacts[obligations.assigned.id]['obligation-due']);
  assert.equal(obligations.detailFacts[obligations.assigned.id]['obligation-owner-id'], fixture.membershipId);
  assert.equal(obligations.detailFacts[obligations.assigned.id]['obligation-owner-name'], obligations.assigned.owner_name);
  const counsel = records.counsel, current = counsel.pages[2];
  for (const key of ['search', 'identityLabel', 'title']) text(counsel.matter[key]);
  for (const [kind, list] of [['assignment', current.assignments], ['spend', current.spend_records]]) for (const record of list) {
    assert.equal(counsel.rowFacts[kind][record.id].length, 3); counsel.rowFacts[kind][record.id].forEach(text);
    fields(counsel.detailFacts[kind][record.id]); assert.equal(counsel.detailFacts[kind][record.id][`counsel-${kind}-id`], record.id);
  }
  for (const currency of current.currencies) { assert.equal(counsel.currencyRows[currency.currency].length, 3); counsel.currencyRows[currency.currency].forEach(text); fields(counsel.totalFacts[currency.currency]); }
  const inbox = records.inbox; for (const state of ['unread', 'read', 'dismissed']) text(inbox.statusRows[state]);
  for (const key of ['search', 'identityLabel', 'title']) text(inbox.matter[key]);
  assert.ok(nativeSelectors.scopedActionPatterns?.recipientInbox?.observed === true, 'ACTUAL_INBOX_NATIVE_PRIMITIVE_PATTERN_REQUIRED');
  return fixture;
}
export function validateMutationTrace(rows, { method, route, body, expectedStatus, requestId }) {
  assert.ok(['POST', 'PATCH'].includes(method), 'EXPLICIT_WORK_MUTATION_REQUIRED');
  assert.match(route, /^\/api\/matters\/[a-f0-9-]{36}\/(?:tasks|hearings)(?:\/[a-f0-9-]{36})?$/);
  const writes = rows.filter(row => row.method === method && row.route === route);
  assert.equal(writes.length, 1, 'NATIVE_WORK_NOT_EXACTLY_ONCE');
  const row = writes[0]; assert.ok(expectedStatus.includes(row.status), 'NATIVE_WORK_STATUS_MISMATCH');
  if (requestId) assert.equal(row.requestId, requestId);
  assert.deepEqual(row.bodyObservation?.keys, Object.keys(body).sort(), 'ACTUAL_DIRTY_KEYS_REQUIRED');
  assert.equal(row.bodyObservation?.canonicalSha256, v1Hash(Buffer.from(JSON.stringify(Object.fromEntries(Object.entries(body).sort(([a], [b]) => a.localeCompare(b)))))), 'ACTUAL_WORK_BODY_HASH_MISMATCH');
  assert.ok(rows.every(other => other === row || ['GET', 'HEAD', 'OPTIONS'].includes(other.method)
    || other.method === 'POST' && ['/api/auth/native/refresh'].includes(other.route)), 'UNEXPECTED_WORK_JOURNEY_MUTATION');
  return row;
}
export function validateV1MutationEvidence(observed, completeJourney, expected) {
  const row = validateMutationTrace(observed, expected);
  const writes = completeJourney.filter(item => !['GET', 'HEAD', 'OPTIONS'].includes(item.method)
    && !(item.method === 'POST' && item.route === '/api/auth/native/refresh'));
  assert.equal(writes.length, 1, 'ONE_MUTATION_ACROSS_COMPLETE_NATIVE_JOURNEY_REQUIRED');
  for (const key of ['method', 'route', 'status', 'requestId', 'sequence']) assert.equal(writes[0][key], row[key], 'CONTROL_AND_GATEWAY_ACK_MUST_AGREE');
  return row;
}
export function validateV1InboxMutationEvidence(observed, completeJourney, { id, body, target }) {
  v1Identity(id); v1Identity(target.id); assert.ok(['matter', 'ip_docket'].includes(target.kind));
  assert.deepEqual(Object.keys(body).sort(), ['expected_status', 'status']);
  for (const value of Object.values(body)) assert.ok(['read', 'unread', 'dismissed'].includes(value));
  const route = `/api/recipient-inbox/${id}`;
  const writes = completeJourney.filter(item => !['GET', 'HEAD', 'OPTIONS'].includes(item.method) && !(item.method === 'POST' && item.route === '/api/auth/native/refresh'));
  assert.equal(writes.length, 1, 'ONE_NATIVE_INBOX_TRANSITION_REQUIRED'); assert.equal(observed.length, 1);
  const row = observed[0];
  for (const [key, expected] of Object.entries({ method: 'PATCH', route, status: 200 })) assert.equal(row[key], expected);
  for (const key of ['method', 'route', 'status', 'requestId', 'sequence']) assert.equal(row[key], writes[0][key], 'INBOX_CONTROL_ACK_MISMATCH');
  assert.deepEqual(row.bodyObservation.keys, ['expected_status', 'status']);
  assert.equal(row.bodyObservation.canonicalSha256, v1Hash(Buffer.from(JSON.stringify(Object.fromEntries(Object.entries(body).sort(([a], [b]) => a.localeCompare(b)))))));
  assert.deepEqual(row.responseObservation, { id, status: body.status, target });
  return row;
}
export function strictV1Routes(records) {
  const routes = new Set(['GET /api/build', 'GET /api/health', 'GET /api/ip/readiness', 'GET /api/contracts/', 'GET /api/ip/portfolio', 'GET /api/calendar/events', 'GET /api/matters/']);
  for (const source of records.calendar.sources) routes.add(`GET /api/ip/dockets/${v1Identity(source.docket.id)}/summary`);
  routes.add(`GET /api/ip/dockets/${v1Identity(records.access.wall.docket.id)}/summary`);
  for (const row of records.contracts.pages.flatMap(x => x.contracts)) routes.add(`GET /api/contracts/${v1Identity(row.id)}`);
  const targets = [...records.work.targets.flatMap(target => [target, ...(target.races || []).filter(race => race.matter)]),
    records.policy.readOnly, records.policy.revokedWork];
  routes.add(`GET /api/matters/${v1Identity(records.access.wall.linkedMatter.id)}/workspace`);
  routes.add(`GET /api/contracts/${v1Identity(records.obligations.contractId)}/obligations`);
  routes.add(`GET /api/outside-counsel/matters/${v1Identity(records.counsel.matter.id)}/context`);
  routes.add('GET /api/recipient-inbox');
  routes.add(`PATCH /api/recipient-inbox/${v1Identity(records.inbox.notification.id)}`);
  routes.add(`GET /api/matters/${v1Identity(records.inbox.matter.id)}/workspace`);
  for (const { matter, task, hearing } of targets) {
    const prefix = `/api/matters/${v1Identity(matter.id)}`;
    routes.add(`GET ${prefix}/workspace`);
    if (matter.id !== records.policy.readOnly.matter.id) {
      for (const kind of ['tasks', 'hearings']) routes.add(`POST ${prefix}/${kind}`);
      for (const [kind, record] of [['tasks', task], ['hearings', hearing]]) if (record) routes.add(`PATCH ${prefix}/${kind}/${v1Identity(record.id)}`);
    }
  }
  assert.ok([...routes].every(row => !/[?*{}]/.test(row)), 'EXACT_NONWILDCARD_V1_ROUTES_REQUIRED');
  return [...routes].sort();
}
export function createV1CaseBudget() {
  const counts = { controls: 0, reads: 0, ownerCalls: 0 };
  return { counts, control() { assert.ok(++counts.controls <= V1_BUDGETS.maxControlsPerCase, 'V1_NATIVE_ACTION_BOUND'); },
    read() { assert.ok(++counts.reads <= V1_BUDGETS.maxAuthoritativeReadsPerCase, 'V1_AUTHORITATIVE_READ_BOUND'); },
    owner() { assert.ok(++counts.ownerCalls <= V1_BUDGETS.maxControlCallsPerCase, 'V1_CONTROL_CALL_BOUND'); } };
}
export function reconcileV1Sessions(events, { requireComplete = false } = {}) {
  const rows = events.filter(row => row.type === 'appium_session');
  const created = rows.filter(row => row.state === 'created'), deleted = rows.filter(row => row.state === 'deleted');
  assert.equal(new Set(created.map(row => row.sessionId)).size, created.length, 'DISTINCT_V1_NATIVE_SESSIONS_REQUIRED');
  assert.equal(new Set(created.map(row => row.id)).size, created.length, 'ONE_V1_SESSION_PER_CASE_REQUIRED');
  assert.ok(new Set(created.map(row => row.id.split(':')[0])).size <= 1, 'INDEPENDENT_V1_PLATFORM_SESSIONS_REQUIRED');
  for (const row of rows) {
    v1Identity(row.sessionId); assert.ok(['created', 'deleted', 'cleanup-failed'].includes(row.state));
    assert.ok(v1Inventory.platforms.some(platform => v1Inventory.cases.some(item => row.id === `${platform}:${item.id}`)));
    if (row.state !== 'created') {
      const admitted = created.filter(item => item.sessionId === row.sessionId && item.id === row.id);
      assert.equal(admitted.length, 1, 'V1_CLEANUP_REQUIRES_ADMITTED_SESSION');
      assert.ok(events.indexOf(admitted[0]) < events.indexOf(row), 'V1_DELETE_BEFORE_CREATION');
    }
  }
  assert.equal(new Set(deleted.map(row => row.sessionId)).size, deleted.length, 'V1_SESSION_DELETE_MUST_NOT_REPLAY');
  const paired = created.every(row => deleted.some(item => item.sessionId === row.sessionId && item.id === row.id));
  if (requireComplete) {
    assert.equal(created.length, 17); assert.equal(deleted.length, 17); assert.equal(paired, true);
    assert.deepEqual(created.map(row => row.id), v1Inventory.cases.map(row => `${created[0].id.split(':')[0]}:${row.id}`));
  }
  return { createdSessions: created.length, deletedSessions: deleted.length, allCreatedSessionsClosed: paired,
    nativeExecution: created.length ? 'actual' : 'not-started' };
}
