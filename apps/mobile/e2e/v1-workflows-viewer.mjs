import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { totp } from './mfa.mjs';
import { v1Hash, v1Identity, v1Reference, v1PrivateReference, collectV1OracleIdentities, v1OracleIdentityEvidence } from './v1-workflows-contract.mjs';
import { readV1Reference } from './v1-workflows-contract.mjs';

export const V1_VIEWER_LIMITS = Object.freeze({ totalMs: 60000, requestMs: 10000, requests: 10, responseBytes: 1048576 });

/** The normal owner transport is acquired only after public source, installed
 * artifact and BOTH serving identities have been admitted. The transport owns
 * ordinary API cookies/tokens in memory; this helper never manufactures one.
 * persistPrivate must be the reviewed local-fixture.py private create/update
 * adapter. No private response or input is passed to the public event sink. */
export async function produceV1Viewer(plan, { admit, request, persistPrivate, persist, claim, aggregate, planEvidence, readEvidence = readV1Reference, now = Date.now, password = () => 'Aa1!' + randomBytes(32).toString('base64url') }) {
  assert.equal(plan?.readyForLive, true, 'V1_VIEWER_PENDING_MUST_NOT_RUN'); assert.equal(plan.preparedOnly, false);
  assert.equal(plan.environment, 'docker-integration'); assert.equal(plan.syntheticDataOnly, true);
  assert.equal(plan.noPaidMarker, 'no-paid-providers'); assert.equal(plan.directDatabaseWrites, false);
  assert.match(plan.sourceSha || '', /^[a-f0-9]{40}$/); v1Identity(plan.companyId);
  for (const key of ['buildReceipt', 'dockerReceipt', 'installedEvidence', 'codeClosure']) v1Reference(plan[key]);
  v1Reference(plan.ownerEvidence); v1Identity(plan.ownerMembershipId);
  const ownerReceipt = readEvidence(plan.ownerEvidence); assert.equal(ownerReceipt.kind, 'actual-normal-api-v1-base-fixture'); assert.equal(ownerReceipt.observed, true); assert.equal(ownerReceipt.sourceSha, plan.sourceSha);
  const owner = ownerReceipt.secondaryOwner; assert.equal(owner.companyId, plan.companyId); assert.equal(owner.membershipId, plan.ownerMembershipId); assert.equal(owner.mfaEnrolled, true); v1PrivateReference(owner.credentialEvidence);
  for (const value of [plan.fullName, plan.email, plan.companySlug]) assert.ok(typeof value === 'string' && value.length > 0 && value.length <= 255);
  assert.match(plan.runId || '', /^v1-[a-f0-9-]{16,80}$/); assert.equal(typeof claim, 'function');
  assert.equal(aggregate.publicState().runId, plan.runId, 'EXACT_FIXTURE_RUN_REQUIRED'); assert.equal(aggregate.publicState().sourceSha, plan.sourceSha, 'EXACT_FIXTURE_SOURCE_REQUIRED');
  assert.ok(aggregate && typeof aggregate.begin === 'function'); v1Reference(planEvidence); aggregate.begin('viewer', planEvidence);
  const admitted = await admit(plan, { boundary: 'before', remaining: () => aggregate.remaining('viewer'), charge: value => aggregate.request('viewer', { ...value, admission: true }) });
  assert.equal(admitted.beforeMemberRead, true); assert.equal(admitted.sourceSha, plan.sourceSha);
  assert.equal(admitted.apiSourceSha, plan.sourceSha); assert.equal(admitted.webSourceSha, plan.sourceSha);
  assert.deepEqual(admitted.buildReceipt, plan.buildReceipt); assert.deepEqual(admitted.dockerReceipt, plan.dockerReceipt);
  assert.deepEqual(admitted.installedEvidence, plan.installedEvidence); assert.match(admitted.binaryHash || '', /^[a-f0-9]{64}$/);
  assert.equal(admitted.companyId, plan.companyId); assert.equal(admitted.membershipId, plan.ownerMembershipId); assert.equal(admitted.role, 'owner'); assert.ok(admitted.capabilities.includes('company:manage_users'));
  assert.deepEqual(admitted.credentialEvidence, owner.credentialEvidence);
  claim(v1Hash(Buffer.from(JSON.stringify(plan))));
  const end = now() + V1_VIEWER_LIMITS.totalMs; let count = 0, uncertain = false;
  const records = [], attempted = new Set();
  const oracleIds = new Set([plan.companyId, plan.ownerMembershipId]);
  const call = async (key, actor, method, route, body, statuses = [200]) => {
    assert.ok(now() < end && ++count <= V1_VIEWER_LIMITS.requests, 'V1_VIEWER_REQUEST_BOUND');
    assert.equal(attempted.has(key), false, 'V1_VIEWER_REQUEST_REPLAY_REFUSED'); attempted.add(key);
    assert.ok(['owner', 'viewer'].includes(actor)); assert.ok(['GET', 'POST'].includes(method));
    assert.ok(['/api/companies/current/users', '/api/auth/login', '/api/auth/me', '/api/auth/security', '/api/auth/mfa/enroll', '/api/auth/mfa/enroll/verify', '/api/matters/'].includes(route)
      || /^\/api\/matters\/[a-f0-9-]{36}\/(?:tasks|hearings|workspace)$/.test(route), 'V1_VIEWER_NORMAL_API_REQUIRED');
    uncertain = method === 'POST'; persist({ type: 'v1_viewer_request_started', key, method, route, mutationUncertain: uncertain });
    aggregate.request('viewer', { key, method, route });
    const response = await request({ key, actor, method, route, body, headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' },
      timeoutMs: Math.min(V1_VIEWER_LIMITS.requestMs, end - now(), aggregate.remaining('viewer')), maxResponseBytes: V1_VIEWER_LIMITS.responseBytes, automaticRetry: false });
    assert.ok(statuses.includes(response.status), 'V1_VIEWER_API_STATUS_REQUIRED'); assert.equal(response.releaseSha, plan.sourceSha);
    assert.ok(response.value && typeof response.value === 'object' && !Array.isArray(response.value));
    collectV1OracleIdentities(response.value).forEach(id => oracleIds.add(id));
    uncertain = false; records.push({ key, method, route, status: response.status, requestId: response.requestId });
    persist({ type: 'v1_viewer_response', ...records.at(-1), mutationUncertain: false }); return response.value;
  };
  const credentials = { full_name: plan.fullName, email: plan.email, company_slug: plan.companySlug, password: password() };
  assert.ok(typeof credentials.password === 'string' && credentials.password.length >= 32);
  let enrollment, privateFile;
  const checkPrivate = value => {
    v1PrivateReference(value.evidence); assert.equal(value.evidence.uid, value.identity.uid); assert.equal(value.mode, 0o600); assert.equal(value.canonicalWriter, 'local-fixture.py');
    assert.ok(value.identity && typeof value.identity.dev === 'string' && typeof value.identity.ino === 'string');
  };
  try {
    // Preserve the initial setup identity even if the next one-shot API call
    // has an unknown outcome. This must be private from its first byte.
    privateFile = await persistPrivate(credentials, { kind: 'canonical-local-fixture-private-json', createExclusive: true, mode: 0o600 }); checkPrivate(privateFile);
    const initialIdentity = { ...privateFile.identity };
    persist({ type: 'v1_viewer_private_created', credentialPath: privateFile.evidence.path, mode: privateFile.mode });
    const created = await call('create-viewer', 'owner', 'POST', '/api/companies/current/users', { full_name: plan.fullName, email: plan.email, password: credentials.password, role: 'viewer' });
    v1Identity(created.membership_id); assert.equal(created.role, 'viewer');
    const login = await call('viewer-login', 'viewer', 'POST', '/api/auth/login', { email: plan.email, password: credentials.password, company_slug: plan.companySlug });
    assert.equal(login.company.id, plan.companyId); assert.equal(login.membership.id, created.membership_id);
    assert.equal(login.membership.role, 'viewer'); assert.equal(login.capabilities.includes('matters:write'), false);
    enrollment = await call('viewer-enroll', 'viewer', 'POST', '/api/auth/mfa/enroll', {});
    assert.match(enrollment.secret || '', /^[A-Z2-7]{16,128}$/);
    credentials.totp_secret = enrollment.secret;
    const privatePath = privateFile.evidence.path;
    privateFile = await persistPrivate(credentials, { kind: 'canonical-local-fixture-private-json', createExclusive: false, mode: 0o600,
      expectedEvidence: privateFile.evidence, sameOwnedDescriptor: true }); checkPrivate(privateFile);
    assert.equal(privateFile.evidence.path, privatePath, 'V1_VIEWER_MFA_PRIVATE_PATH_CHANGED');
    assert.deepEqual(privateFile.identity, initialIdentity, 'V1_VIEWER_MFA_PRIVATE_INODE_CHANGED');
    assert.equal(privateFile.ownedNoFollowSingleLink, true, 'V1_VIEWER_PRIVATE_UPDATE_ADMISSION_REQUIRED');
    const verified = await call('viewer-enroll-verify', 'viewer', 'POST', '/api/auth/mfa/enroll/verify', { code: totp(enrollment.secret, now()) }); assert.equal(verified.status, 'enrolled');
    const me = await call('viewer-current-identity', 'viewer', 'GET', '/api/auth/me');
    assert.equal(me.company.id, plan.companyId); assert.equal(me.membership.id, created.membership_id); assert.equal(me.membership.role, 'viewer');
    assert.equal(me.user.is_active, true); assert.equal(me.membership.is_active, true);
    assert.ok(Array.isArray(me.capabilities) && !me.capabilities.includes('matters:write'));
    const security = await call('viewer-security', 'viewer', 'GET', '/api/auth/security'); assert.equal(security.mfa_status, 'enrolled');
    assert.ok(plan.work?.matter && plan.work.task && plan.work.hearing && plan.work.rowFacts, 'READONLY_WORK_PLAN_REQUIRED');
    assert.deepEqual(plan.work.hearing.reminder_channels, []); assert.deepEqual(plan.work.hearing.reminder_recipient_membership_ids, []);
    assert.equal(plan.work.hearing.notification_critical, false);
    const matter = await call('readonly-matter', 'owner', 'POST', '/api/matters/', plan.work.matter);
    v1Identity(matter.id); assert.equal(matter.company_id, plan.companyId); assert.equal(matter.is_disposed, false);
    assert.ok(Number.isSafeInteger(matter.lifecycle_version) && matter.lifecycle_version >= 0);
    const task = await call('readonly-task', 'owner', 'POST', `/api/matters/${matter.id}/tasks`, { ...plan.work.task, expected_lifecycle_version: matter.lifecycle_version });
    const hearing = await call('readonly-hearing', 'owner', 'POST', `/api/matters/${matter.id}/hearings`, { ...plan.work.hearing, expected_lifecycle_version: matter.lifecycle_version });
    for (const record of [task, hearing]) { v1Identity(record.id); assert.equal(record.matter_id, matter.id); }
    assert.equal(task.owner_membership_id, null, 'READONLY_SYNTHETIC_TASK_MUST_BE_UNASSIGNED');
    const workspace = await call('readonly-workspace', 'viewer', 'GET', `/api/matters/${matter.id}/workspace`);
    assert.equal(workspace.matter.id, matter.id); assert.equal(workspace.matter.company_id, plan.companyId);
    assert.deepEqual(workspace.tasks.filter(record => record.id === task.id), [task]);
    assert.deepEqual(workspace.hearings.filter(record => record.id === hearing.id), [hearing]);
    for (const facts of [plan.work.rowFacts.task, plan.work.rowFacts.hearing]) assert.ok(Array.isArray(facts) && facts.length === 3 && facts.every(value => typeof value === 'string' && value));
    assert.equal(plan.work.rowFacts.task[0], task.title); assert.equal(plan.work.rowFacts.hearing[0], hearing.purpose || 'Hearing purpose not recorded');
    assert.ok(plan.work.rowFacts.task[2].endsWith(' · Read-only') && plan.work.rowFacts.hearing[2].endsWith(' · Read-only'));
    assert.ok(typeof workspace.matter.matter_code === 'string' && workspace.matter.matter_code && typeof workspace.matter.title === 'string' && workspace.matter.title);
    const readOnlyWork = { expectedRole: 'viewer', expectedCanWrite: false, matter: { ...workspace.matter, search: workspace.matter.matter_code, identityLabel: workspace.matter.matter_code }, task, hearing,
      rowFacts: { task: { [task.id]: plan.work.rowFacts.task }, hearing: { [hearing.id]: plan.work.rowFacts.hearing } } };
    const after = await admit(plan, { boundary: 'after', remaining: () => aggregate.remaining('viewer'), charge: value => aggregate.request('viewer', { ...value, admission: true }) });
    assert.equal(after.apiSourceSha, plan.sourceSha); assert.equal(after.webSourceSha, plan.sourceSha); assert.equal(after.binaryHash, admitted.binaryHash);
    const receipt = { schemaVersion: 1, kind: 'actual-normal-api-v1-viewer', phase: 'viewer', requests: count, writes: 7, observed: true, sourceSha: plan.sourceSha, runId: plan.runId,
      companyId: plan.companyId, membershipId: me.membership.id, role: 'viewer', capabilities: [...me.capabilities].sort(), mfaEnrolled: true,
      credentialEvidence: privateFile.evidence, buildReceipt: plan.buildReceipt, dockerReceipt: plan.dockerReceipt, installedEvidence: plan.installedEvidence,
      binaryHash: admitted.binaryHash, noPaidMarker: 'no-paid-providers', directDatabaseWrites: false, automaticRetry: false, mutationUncertain: false,
      oracleIdentityEvidence: v1OracleIdentityEvidence([...oracleIds]),
      readOnlyWork, observations: records };
    persist({ type: 'v1_viewer_completed', ...receipt }); return receipt;
  } catch {
    persist({ type: 'v1_viewer_stopped', observed: false, attempted: [...attempted], mutationUncertain: uncertain, automaticRetry: false });
    throw Error('V1_VIEWER_PRODUCTION_INCOMPLETE_NO_REPLAY');
  } finally { for (const key of Object.keys(credentials)) credentials[key] = ''; if (enrollment) enrollment.secret = ''; }
}

export function pendingV1ViewerPlan() {
  return { schemaVersion: 1, preparedOnly: true, readyForLive: false, environment: 'docker-integration', syntheticDataOnly: true,
    noPaidMarker: 'no-paid-providers', directDatabaseWrites: false, sourceSha: 'FUTURE_SOURCE_PENDING', companyId: 'PENDING', runId: 'PENDING',
    buildReceipt: null, dockerReceipt: null, installedEvidence: null, codeClosure: null, ownerEvidence: null, ownerMembershipId: 'PENDING', fullName: 'PENDING', email: 'PENDING', companySlug: 'PENDING', work: null };
}
