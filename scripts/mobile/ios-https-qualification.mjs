import assert from 'node:assert/strict';
import path from 'node:path';
import { CX_BUDGETS } from '../../apps/mobile/e2e/client-extensions-inventory.mjs';

const observations = new WeakSet(), leases = new WeakMap(), observationStates = new WeakMap();
const unavailableErrors = new WeakSet(), runtimeRefusals = new WeakSet();
const SHA = /^[a-f0-9]{64}$/, COMMIT = /^[a-f0-9]{40}$/;
const CASE = 'CX28-LINK-05';
const fail = code => { const error = new Error(code); unavailableErrors.add(error); throw error; };
// Classification uses only private identity, never caller-controlled error getters.
export const iosQualificationFailure = error => ({ unavailable: unavailableErrors.has(error), captureRequiresProcessExit: runtimeRefusals.has(error) });
export function iosQualificationDeadlines(caseStartedAt, leaseDeadlineMs) {
  assert.ok(Number.isSafeInteger(caseStartedAt) && Number.isSafeInteger(leaseDeadlineMs));
  const deadline = Math.min(caseStartedAt + CX_BUDGETS.perCaseMs, leaseDeadlineMs - 120000);
  assert.ok(deadline > caseStartedAt, 'QUAL_IOS_MAIN_WINDOW_REQUIRED');
  return { deadline, cleanupDeadline: Math.min(deadline + CX_BUDGETS.finalCleanupMs, leaseDeadlineMs) };
}
const object = value => assert.ok(value && typeof value === 'object' && !Array.isArray(value), 'QUAL_IOS_OBJECT_REQUIRED');
function keys(value, expected) { object(value); assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), 'QUAL_IOS_EXACT_FIELDS_REQUIRED'); }
function reference(value) {
  keys(value, ['path', 'sha256']);
  assert.ok(path.isAbsolute(value.path) && path.resolve(value.path) === value.path, 'QUAL_IOS_ABSOLUTE_CANONICAL_REFERENCE_REQUIRED');
  assert.ok(!/(credential|secret|\.(key|p12|keystore)$)/i.test(path.basename(value.path)), 'QUAL_IOS_PUBLIC_REFERENCE_REQUIRED');
  assert.match(value.sha256, SHA);
}
function productionBundle(value) {
  assert.match(value, /^[a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9-]+){2,}$/);
  assert.ok(!/(?:^|\.)(?:dev|localacceptance|simulatoracceptance)(?:\.|$)/i.test(value), 'QUAL_IOS_PRODUCTION_BUNDLE_REQUIRED');
}
export function validateIosQualificationDeclaration(q, expectedSource) {
  keys(q, ['schemaVersion', 'kind', 'platform', 'caseId', 'source', 'udid', 'appId', 'artifact', 'nativeLinks',
    'installedArtifactEvidence', 'signing', 'aasa', 'origin', 'url', 'subject', 'normalApiEvidence', 'sender', 'child']);
  assert.equal(q.schemaVersion, 1); assert.equal(q.kind, 'caseops-ios-https-qualification');
  assert.equal(q.platform, 'ios'); assert.equal(q.caseId, CASE);
  keys(q.source, ['sourceSha', 'sourceFingerprint', 'sourceDirty', 'inputFileCount']);
  assert.match(q.source.sourceSha, COMMIT); assert.match(q.source.sourceFingerprint, SHA);
  assert.equal(q.source.sourceDirty, false); assert.ok(Number.isSafeInteger(q.source.inputFileCount) && q.source.inputFileCount > 0);
  assert.deepEqual(q.source, expectedSource, 'QUAL_IOS_CURRENT_SOURCE_REQUIRED');
  // Physical identifiers, never a Simulator UUID or a descriptive label.
  assert.match(q.udid, /^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{8}-[a-fA-F0-9]{16})$/, 'QUAL_IOS_PHYSICAL_DEVICE_REQUIRED');
  productionBundle(q.appId);
  for (const name of ['artifact', 'nativeLinks', 'installedArtifactEvidence', 'aasa', 'normalApiEvidence']) reference(q[name]);
  assert.ok(q.artifact.path.endsWith('.ipa'), 'QUAL_IOS_IPA_REFERENCE_REQUIRED');
  keys(q.signing, ['teamId', 'applicationIdentifierPrefix', 'certificateSha256', 'profile', 'artifactPlatform', 'minimumOS']);
  for (const key of ['teamId', 'applicationIdentifierPrefix']) {
    assert.match(q.signing[key], /^[A-Z0-9]{10}$/);
    assert.ok(!/^(.)\1+$/.test(q.signing[key]) && !['ABCDE12345', 'FAKETEAMID', 'TEAMID12345'].includes(q.signing[key]), 'QUAL_IOS_REAL_SIGNING_IDENTITY_REQUIRED');
  }
  assert.match(q.signing.certificateSha256, SHA); reference(q.signing.profile);
  assert.equal(q.signing.artifactPlatform, 'iphoneos', 'QUAL_IOS_DEVICE_ARTIFACT_REQUIRED');
  assert.match(q.signing.minimumOS, /^\d+\.\d+(?:\.\d+)?$/);
  const [major, minor] = q.signing.minimumOS.split('.').map(Number);
  assert.ok(major > 17 || major === 17 && minor >= 4, 'QUAL_IOS_HTTPS_MINIMUM_REQUIRED');
  const origin = new URL(q.origin);
  assert.ok(origin.protocol === 'https:' && origin.origin === q.origin && !origin.port && !origin.username && !origin.password
    && !/^(?:localhost|\d+\.)/.test(origin.hostname) && !/(?:^|\.)(?:invalid|test|example|local)$/.test(origin.hostname) && !/(?:^|\.)example\.(?:com|net|org)$/.test(origin.hostname), 'QUAL_IOS_PUBLIC_HTTPS_REQUIRED');
  keys(q.subject, ['companyId', 'userId', 'membershipId', 'principalLabel', 'workspaceLabel', 'matter']);
  for (const key of ['companyId', 'userId', 'membershipId']) assert.match(q.subject[key], /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/);
  keys(q.subject.matter, ['id', 'code']);
  assert.match(q.subject.matter.id, /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/);
  for (const value of [q.subject.principalLabel, q.subject.workspaceLabel, q.subject.matter.code]) assert.ok(typeof value === 'string' && value.trim() && value.length <= 200 && !/[\x00-\x1f\x7f]/.test(value));
  assert.equal(q.url, `${q.origin}/native/open/workspaces/${q.subject.companyId}/matters/${q.subject.matter.id}`, 'QUAL_IOS_EXACT_AUTHORIZED_URL_REQUIRED');
  keys(q.sender, ['appId', 'artifact']); productionBundle(q.sender.appId); assert.notEqual(q.sender.appId, q.appId); reference(q.sender.artifact);
  keys(q.child, ['appiumUrl', 'wdaPort', 'appiumInventoryEvidence']);
  const appium = new URL(q.child.appiumUrl);
  assert.ok(appium.protocol === 'http:' && appium.hostname === '127.0.0.1' && appium.port && appium.pathname === '/' && !appium.username && !appium.password && !appium.search && !appium.hash, 'QUAL_IOS_OWNED_CHILD_SERVER_REQUIRED');
  assert.ok(Number.isSafeInteger(q.child.wdaPort) && q.child.wdaPort >= 1024 && q.child.wdaPort <= 65535); reference(q.child.appiumInventoryEvidence);
  return q;
}

/** Public declarations never supply actual authority. A production attestor must
 * independently measure signed and installed bytes, public AASA and OS delivery.
 * There is currently no reviewed supported physical installed-bundle attestor.
 * Refuse before creating a child; install ACK/version are deliberately insufficient.
 * Synthetic providers are only available to explicit contract-only unit callers.
 */
export function observeIosHttpsQualification(q, base, syntheticProvider) {
  validateIosQualificationDeclaration(q, base.source);
  if (base.contractOnly !== true) fail('QUAL_IOS_REAL_INSTALLED_ARTIFACT_ATTESTOR_UNAVAILABLE');
  assert.ok(syntheticProvider && syntheticProvider.contractOnly === true, 'QUAL_IOS_SYNTHETIC_PROVIDER_REQUIRED');
  for (const key of ['createChild', 'deleteChild', 'knownSessionAbsent', 'allSessions', 'verify', 'identify', 'dispatch', 'record', 'verifyParent']) assert.equal(typeof syntheticProvider[key], 'function');
  assert.equal(typeof base.now, 'function'); assert.equal(typeof base.charge, 'function'); assert.equal(typeof base.cleanupCharge, 'function');
  assert.ok(Number.isFinite(base.deadline) && Number.isFinite(base.cleanupDeadline) && base.now() < base.deadline && base.cleanupDeadline >= base.deadline && base.cleanupDeadline <= base.deadline + CX_BUDGETS.finalCleanupMs);
  const freeze = value => { if (value && typeof value === 'object') { for (const child of Object.values(value)) freeze(child); Object.freeze(value); } return value; };
  const result = Object.freeze({ q: freeze(structuredClone(q)), base: Object.freeze({ ...base }), io: Object.freeze({ ...syntheticProvider }), contractOnly: true });
  observations.add(result); observationStates.set(result, { timeoutUncertain: false }); return result;
}
function failureWithCleanup(original, bodyFailed, errors) {
  if (bodyFailed && errors.length) return new AggregateError([original, ...errors], 'QUAL_IOS_BODY_AND_CLEANUP_FAILED', { cause: original });
  if (bodyFailed) return original;
  return errors.length === 1 ? errors[0] : new AggregateError(errors, 'QUAL_IOS_CLEANUP_FAILED');
}
async function bounded(observed, operation, cleanup = false) {
  const { base } = observed, end = cleanup ? base.cleanupDeadline : base.deadline;
  const check = () => assert.ok(base.now() < end, cleanup ? 'QUAL_IOS_CLEANUP_DEADLINE' : 'QUAL_IOS_DEADLINE');
  check(); (cleanup ? base.cleanupCharge : base.charge)(); check();
  const remaining = Math.min(CX_BUDGETS.nativeReadMs, end - base.now());
  assert.ok(remaining > 0); let timer;
  try {
    const result = await Promise.race([Promise.resolve().then(() => { check(); return operation(); }),
      new Promise((_, reject) => { timer = setTimeout(() => { observationStates.get(observed).timeoutUncertain = true; reject(new Error(cleanup ? 'QUAL_IOS_CLEANUP_DEADLINE' : 'QUAL_IOS_DEADLINE')); }, remaining); })]);
    check(); return result;
  } finally { clearTimeout(timer); }
}
function lease(context) {
  const value = leases.get(context);
  assert.ok(value && context.platform === 'ios' && context.caseId === CASE && context.driver === value.driver
    && context.fixture.udid === value.observed.q.udid && context.binaryHash === value.observed.q.artifact.sha256, 'CX_ACTUAL_VERIFIED_HTTPS_ARTIFACT_REQUIRED');
  return value;
}
export async function terminateIosQualifiedApp(context) {
  const value = lease(context); await bounded(value.observed, () => value.driver.terminateApp(value.observed.q.appId));
}
export async function assertIosQualifiedColdState(context) {
  const value = lease(context); assert.equal(await bounded(value.observed, () => value.driver.queryAppState(value.observed.q.appId)), 1, 'QUAL_IOS_ACTUAL_COLD_STATE_REQUIRED');
}
export async function dispatchIosQualifiedHttpsLink(context, url) {
  const value = lease(context), { observed } = value;
  assert.equal(url, observed.q.url, 'QUAL_IOS_EXACT_AUTHORIZED_URL_REQUIRED'); assert.ok(value.opens < 2, 'QUAL_IOS_EXACT_COLD_WARM_ONLY');
  await bounded(observed, () => observed.io.verify(observed.q, 'before-dispatch'));
  if (value.opens === 1) assert.equal(await bounded(observed, () => value.driver.queryAppState(observed.q.appId)), 4, 'QUAL_IOS_ACTUAL_WARM_STATE_REQUIRED');
  // Provider must observe sender transition without killing the already warm app.
  // Empty URL-open options: no target CaseOps bundle and no universalLinksOnly.
  value.opens++;
  await bounded(observed, () => observed.io.dispatch(value.driver, { url, sender: observed.q.sender, options: {}, targetBundleId: null, warm: value.opens === 2 }));
  await bounded(observed, () => observed.io.identify(value.driver, observed.q, 'receiver'));
}

export async function withIosHttpsQualification(context, observer, action) {
  assert.equal(context.platform, 'ios'); assert.equal(context.caseId, CASE);
  const observed = await observer(); assert.ok(observations.has(observed), 'QUAL_IOS_PRIVATE_OBSERVATION_REQUIRED'); observations.delete(observed);
  // Canonical runner never supplies contractOnly. A synthetic lease must never
  // be converted into observed native acceptance or promotion evidence.
  assert.equal(context.contractOnly, true, 'QUAL_IOS_SYNTHETIC_LEASE_CANNOT_ENTER_NATIVE_RUN');
  const old = Object.fromEntries(['driver', 'fixture', 'binaryHash', 'workflowDomain', 'checkBudget'].map(key => [key, context[key]]));
  let driver, creationAttempted = false, creationAcknowledged = false, bodyFailed = false, childCleanupUncertain = false, original;
  const errors = [];
  try {
    await bounded(observed, () => observed.io.verify(observed.q, 'before-create'));
    creationAttempted = true;
    await bounded(observed, async () => {
      driver = await observed.io.createChild(observed.q);
      creationAcknowledged = !!(driver && typeof driver.sessionId === 'string' && driver.sessionId);
      assert.ok(creationAcknowledged, 'QUAL_IOS_ACKNOWLEDGED_CHILD_REQUIRED');
    });
    assert.notEqual(driver, old.driver, 'QUAL_IOS_SEPARATE_PHYSICAL_CHILD_REQUIRED');
    context.driver = driver; context.binaryHash = observed.q.artifact.sha256; context.workflowDomain = 'contract-only';
    context.fixture = { udid: observed.q.udid, appId: observed.q.appId, ...observed.q.subject,
      cx: { links: { https: observed.q.url, matter: observed.q.subject.matter, verifiedAssociation: {
        observed: false, binaryHash: observed.q.artifact.sha256, udid: observed.q.udid, mode: 'production', origin: observed.q.origin } } } };
    context.checkBudget = needed => { assert.ok(observed.base.now() + (needed ?? 0) <= observed.base.deadline, 'QUAL_IOS_DEADLINE'); old.checkBudget?.(needed); };
    await bounded(observed, () => observed.io.identify(driver, observed.q, 'principal-and-workspace'));
    leases.set(context, { observed, driver, opens: 0 });
    await action(context);
    assert.equal(leases.get(context).opens, 2, 'QUAL_IOS_BOTH_OPENS_REQUIRED');
    await bounded(observed, () => observed.io.verify(observed.q, 'finish'));
  } catch (error) { bodyFailed = true; original = error; }
  finally {
    leases.delete(context);
    if (creationAcknowledged) {
      try { await bounded(observed, () => driver.terminateApp(observed.q.appId), true); } catch (error) { errors.push(error); }
      try { await bounded(observed, () => observed.io.deleteChild(driver.sessionId), true); } catch (error) { childCleanupUncertain = true; errors.push(error); }
      try { assert.deepEqual(await bounded(observed, () => observed.io.knownSessionAbsent(driver.sessionId), true), { sessionId: driver.sessionId, status: 404, error: 'invalid session id' }, 'QUAL_IOS_CHILD_ABSENCE_REQUIRED'); } catch (error) { childCleanupUncertain = true; errors.push(error); }
      try { assert.deepEqual(await bounded(observed, () => observed.io.allSessions(), true), [], 'QUAL_IOS_FULL_CHILD_INVENTORY_REQUIRED'); } catch (error) { childCleanupUncertain = true; errors.push(error); }
    } else if (creationAttempted) {
      const uncertain = new Error('QUAL_IOS_CHILD_CREATE_UNKNOWN_NO_REPLAY'); childCleanupUncertain = true; errors.push(uncertain);
    }
    for (const [key, value] of Object.entries(old)) context[key] = value;
    try { await bounded(observed, () => observed.io.verifyParent(old.driver, old.fixture), true); } catch (error) { errors.push(error); }
  }
  if (bodyFailed || errors.length) {
    const error = failureWithCleanup(original, bodyFailed, errors);
    if (childCleanupUncertain || observationStates.get(observed).timeoutUncertain) {
      // An unknown creation cannot be hidden by primitive/frozen primary errors.
      const refusal = new AggregateError(bodyFailed ? [original, ...errors] : errors, 'QUAL_IOS_OWNED_CHILD_CLEANUP_UNCERTAIN', { cause: bodyFailed ? original : errors[0] });
      refusal.captureRequiresProcessExit = true; runtimeRefusals.add(refusal); throw refusal;
    }
    throw error;
  }
  const checkPublication = () => assert.ok(observed.base.now() < observed.base.cleanupDeadline, 'QUAL_IOS_CLEANUP_DEADLINE');
  checkPublication();
  let publicationFailed = false, publicationError;
  const publicationFailures = [];
  try { observed.io.record({ type: 'ios_https_qualification_contract_completed', observed: false, contractOnly: true,
    submissionAllowed: false, nativeCaseCredit: 0, parentSessionId: old.driver.sessionId, childSessionId: driver.sessionId, caseId: CASE }); }
  catch (error) { publicationFailed = true; publicationError = error; }
  try { checkPublication(); } catch (error) { publicationFailures.push(error); }
  if (publicationFailed || publicationFailures.length) throw failureWithCleanup(publicationError, publicationFailed, publicationFailures);
}
