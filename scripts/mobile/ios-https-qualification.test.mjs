import test from 'node:test';
import assert from 'node:assert/strict';
import { validateIosQualificationDeclaration, observeIosHttpsQualification, withIosHttpsQualification, iosQualificationDeadlines, iosQualificationFailure } from './ios-https-qualification.mjs';
import { dispatchQualifiedHttpsLink, terminateQualifiedApp, assertQualifiedColdState } from './https-qualification-lease.mjs';
import { recordLink } from '../../apps/mobile/e2e/client-extensions-ui.mjs';

const ref = name => ({ path: '/synthetic-ios/' + name, sha256: 'b'.repeat(64) });
function fixture() {
  let clock = 0, state = 4, charges = 0, cleanupCharges = 0;
  const events = [], calls = [];
  const source = { sourceSha: 'a'.repeat(40), sourceFingerprint: 'b'.repeat(64), sourceDirty: false, inputFileCount: 255 };
  const subject = { companyId: '11111111-1111-4111-8111-111111111111', userId: '22222222-2222-4222-8222-222222222222', membershipId: '33333333-3333-4333-8333-333333333333', principalLabel: 'Synthetic Member', workspaceLabel: 'Synthetic Workspace', matter: { id: '44444444-4444-4444-8444-444444444444', code: 'SYNTHETIC' } };
  const q = { schemaVersion: 1, kind: 'caseops-ios-https-qualification', platform: 'ios', caseId: 'CX28-LINK-05', source,
    udid: '00008101-0012345678901234', appId: 'ai.caseops.mobile', artifact: ref('artifact.ipa'), nativeLinks: ref('native-links.json'), installedArtifactEvidence: ref('installed.json'),
    signing: { teamId: 'AB12CD34EF', applicationIdentifierPrefix: 'GH12IJ34KL', certificateSha256: 'c'.repeat(64), profile: ref('profile.mobileprovision'), artifactPlatform: 'iphoneos', minimumOS: '17.4' },
    aasa: ref('public-aasa.json'), origin: 'https://caseops.ai', url: 'https://caseops.ai/native/open/workspaces/' + subject.companyId + '/matters/' + subject.matter.id,
    subject, normalApiEvidence: ref('normal-api.json'), sender: { appId: 'ai.caseops.ownedlinksender', artifact: ref('sender.ipa') },
    child: { appiumUrl: 'http://127.0.0.1:4727', wdaPort: 8103, appiumInventoryEvidence: ref('appium.json') } };
  const parent = { sessionId: 'synthetic-parent' }, oldFixture = { appId: 'ai.caseops.mobile.dev.simulatoracceptance', udid: 'synthetic-simulator' };
  const child = { sessionId: 'synthetic-child', async terminateApp(app) { calls.push(['terminate', app]); state = 1; }, async queryAppState(app) { calls.push(['state', app]); return state; } };
  const c = { platform: 'ios', caseId: q.caseId, contractOnly: true, driver: parent, fixture: oldFixture, binaryHash: 'd'.repeat(64), workflowDomain: 'simulator', nativeOperations: 0,
    checkBudget() {}, record: row => events.push(row) };
  const base = { source, contractOnly: true, now: () => clock, deadline: 100, cleanupDeadline: 190,
    charge() { charges++; }, cleanupCharge() { cleanupCharges++; } };
  const io = { contractOnly: true, async createChild() { calls.push(['create']); return child; }, async deleteChild(id) { calls.push(['delete', id]); },
    async knownSessionAbsent(id) { calls.push(['absence', id]); return { sessionId: id, status: 404, error: 'invalid session id' }; }, async allSessions() { calls.push(['inventory']); return []; },
    async verify(_q, phase) { calls.push(['verify', phase]); }, async identify(_driver, _q, phase) { calls.push(['identity', phase]); },
    async dispatch(_driver, request) { calls.push(['dispatch', request]); state = 4; }, record: row => events.push(row), async verifyParent(driver, f) { calls.push(['parent']); assert.equal(driver, parent); assert.equal(f, oldFixture); } };
  const observe = () => observeIosHttpsQualification(q, base, io);
  const action = async () => { await terminateQualifiedApp(c); await assertQualifiedColdState(c); await dispatchQualifiedHttpsLink(c, q.url); await dispatchQualifiedHttpsLink(c, q.url); };
  return { q, source, c, parent, oldFixture, child, base, io, events, calls, observe, action,
    now: value => { clock = value; }, state: value => { state = value; }, counts: () => ({ charges, cleanupCharges }) };
}
test('iOS qualification refuses actual authority before any physical child is created', () => {
  const f = fixture(); f.base.contractOnly = false; let children = 0; f.io.createChild = () => { children++; };
  assert.throws(() => observeIosHttpsQualification(f.q, f.base, f.io), /REAL_INSTALLED_ARTIFACT_ATTESTOR_UNAVAILABLE/); assert.equal(children, 0);
});
test('iOS declaration binds source, device, signing, public origin and exact authorized record', () => {
  const f = fixture(); assert.equal(validateIosQualificationDeclaration(f.q, f.source), f.q);
  const changes = [q => { q.source.sourceFingerprint = 'c'.repeat(64); }, q => { q.udid = '11111111-1111-4111-8111-111111111111'; }, q => { q.signing.artifactPlatform = 'iphonesimulator'; }, q => { q.signing.minimumOS = '17.3'; }, q => { q.signing.teamId = 'FAKETEAMID'; }, q => { q.appId += '.dev.simulatoracceptance'; }, q => { q.origin = 'https://127.0.0.1'; }, q => { q.url += '?redirect=other'; }, q => { q.url = q.url.replace(q.subject.matter.id, q.subject.userId); }, q => { q.child.appiumUrl = 'http://remote.example:4727'; }, q => { q.observed = true; }];
  for (const change of changes) { const q = structuredClone(f.q); change(q); assert.throws(() => validateIosQualificationDeclaration(q, f.source)); }
});
test('JSON observed flags and a forged observation cannot mint an iOS private lease', async () => {
  const f = fixture(); f.c.fixture.cx = { links: { verifiedAssociation: { observed: true, binaryHash: f.c.binaryHash, udid: f.oldFixture.udid, mode: 'production', origin: f.q.origin } } };
  await assert.rejects(recordLink(f.c, f.q.url, { verifiedHttps: true }), /ACTUAL_VERIFIED_HTTPS_ARTIFACT_REQUIRED/);
  await assert.rejects(withIosHttpsQualification(f.c, () => ({ q: f.q, contractOnly: false }), f.action), /PRIVATE_OBSERVATION_REQUIRED/); assert.equal(f.calls.length, 0);
});
test('a synthetic private observation cannot enter the canonical native runner context', async () => {
  const f = fixture(); delete f.c.contractOnly;
  await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), /SYNTHETIC_LEASE_CANNOT_ENTER_NATIVE_RUN/); assert.equal(f.calls.length, 0);
});
test('contract-only physical child performs cold and warm unforced opens and restores the Simulator parent', async () => {
  const f = fixture(); await withIosHttpsQualification(f.c, f.observe, f.action);
  assert.equal(f.c.driver, f.parent); assert.equal(f.c.fixture, f.oldFixture); assert.equal(f.c.binaryHash, 'd'.repeat(64)); assert.equal(f.c.workflowDomain, 'simulator');
  const requests = f.calls.filter(row => row[0] === 'dispatch').map(row => row[1]); assert.equal(requests.length, 2);
  for (const request of requests) { assert.deepEqual(request.options, {}); assert.equal(request.targetBundleId, null); assert.equal(request.url, f.q.url); }
  assert.deepEqual(requests.map(row => row.warm), [false, true]);
  assert.deepEqual(f.calls.filter(row => ['delete', 'absence', 'inventory', 'parent'].includes(row[0])).map(row => row[0]), ['delete', 'absence', 'inventory', 'parent']);
  assert.equal(f.events.length, 1); assert.equal(f.events[0].observed, false); assert.equal(f.events[0].nativeCaseCredit, 0); assert.equal(f.events[0].submissionAllowed, false);
  assert.ok(f.counts().charges > 0 && f.counts().cleanupCharges >= 5);
  await assert.rejects(dispatchQualifiedHttpsLink(f.c, f.q.url), /ACTUAL_VERIFIED_HTTPS_ARTIFACT_REQUIRED/);
});
test('cold and warm state refusals stop before an unverified URL dispatch', async () => {
  for (const cold of [true, false]) {
    const f = fixture();
    await assert.rejects(withIosHttpsQualification(f.c, f.observe, async () => {
      await terminateQualifiedApp(f.c); if (cold) { f.state(4); await assertQualifiedColdState(f.c); }
      else { await assertQualifiedColdState(f.c); await dispatchQualifiedHttpsLink(f.c, f.q.url); f.state(1); await dispatchQualifiedHttpsLink(f.c, f.q.url); }
    }), cold ? /ACTUAL_COLD_STATE_REQUIRED/ : /ACTUAL_WARM_STATE_REQUIRED/);
    assert.equal(f.calls.filter(row => row[0] === 'dispatch').length, cold ? 0 : 1);
  }
});
test('unknown URL acknowledgement is never silently replayed and still closes its known child', async () => {
  const f = fixture(), original = Object.freeze(new Error('SYNTHETIC_OPEN_ACK_UNKNOWN')); let opens = 0;
  f.io.dispatch = async () => { opens++; throw original; };
  await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), value => value === original);
  assert.equal(opens, 1); assert.equal(f.calls.filter(row => row[0] === 'delete').length, 1); assert.equal(f.c.driver, f.parent);
});
test('falsy and frozen body failures retain independent cleanup errors without overwriting the original', async () => {
  for (const original of [undefined, null, false, 0, '', Object.freeze(new Error('SYNTHETIC_BODY'))]) {
    const f = fixture(), secondary = new Error('SYNTHETIC_DELETE'); f.io.deleteChild = async () => { throw secondary; };
    await assert.rejects(withIosHttpsQualification(f.c, f.observe, async () => { throw original; }), error => error instanceof AggregateError && error.cause === original && error.errors[0] === original && error.errors[1] === secondary);
    assert.equal(f.c.driver, f.parent); assert.ok(f.calls.some(row => row[0] === 'absence')); assert.ok(f.calls.some(row => row[0] === 'inventory'));
  }
});
test('falsy body failure propagates unchanged when child cleanup succeeds', async () => {
  const f = fixture(); let caught = false;
  try { await withIosHttpsQualification(f.c, f.observe, async () => { throw undefined; }); } catch (error) { caught = true; assert.equal(error, undefined); }
  assert.equal(caught, true);
});
test('acknowledged child creation crossing the main deadline is cleaned under the separate reserve', async () => {
  const f = fixture(); f.io.createChild = async () => { f.now(100); return f.child; };
  await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), /QUAL_IOS_DEADLINE/);
  assert.ok(f.calls.some(row => row[0] === 'delete')); assert.equal(f.c.driver, f.parent); assert.equal(f.events.length, 0);
});
test('unknown child creation retains uncertainty and cannot become complete from an empty inventory', async () => {
  const f = fixture(), original = new Error('SYNTHETIC_CREATE_TRANSPORT'); f.io.createChild = async () => { throw original; };
  await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), error => error.captureRequiresProcessExit === true && error.cause === original && error.errors.includes(original));
  assert.equal(f.calls.filter(row => row[0] === 'create').length, 0); assert.equal(f.calls.filter(row => row[0] === 'delete').length, 0); assert.equal(f.c.driver, f.parent); assert.equal(f.events.length, 0);
});
test('slow charge and deferred microtask cannot dispatch work after the main deadline', async () => {
  for (const deferred of [false, true]) {
    const f = fixture(); f.base.charge = () => { if (deferred) queueMicrotask(() => f.now(100)); else f.now(100); };
    await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), /QUAL_IOS_DEADLINE/);
    assert.equal(f.calls.filter(row => row[0] === 'verify' || row[0] === 'create' || row[0] === 'dispatch').length, 0);
  }
});
test('late successful reads cannot issue the next native dispatch', async () => {
  const f = fixture(); f.io.verify = async (_q, phase) => { if (phase === 'before-dispatch') f.now(100); };
  await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), /QUAL_IOS_DEADLINE/); assert.equal(f.calls.filter(row => row[0] === 'dispatch').length, 0);
});
test('nonempty or unknown child-session absence refuses completion after acknowledged deletion', async () => {
  for (const wrong of ['known', 'all']) {
    const f = fixture(); if (wrong === 'known') f.io.knownSessionAbsent = async () => ({ sessionId: f.child.sessionId, status: 500, error: 'unknown' }); else f.io.allSessions = async () => [{ id: f.child.sessionId }];
    await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), error => error.captureRequiresProcessExit === true && error.errors.some(item => item.message.includes(wrong === 'known' ? 'CHILD_ABSENCE_REQUIRED' : 'FULL_CHILD_INVENTORY_REQUIRED'))); assert.equal(f.c.driver, f.parent);
  }
});
test('parent restoration failure remains a failure and does not replay the physical workflow', async () => {
  const f = fixture(), original = new Error('SYNTHETIC_PARENT_UNVERIFIED'); f.io.verifyParent = async () => { throw original; };
  await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), value => value === original);
  assert.equal(f.calls.filter(row => row[0] === 'dispatch').length, 2); assert.equal(f.c.driver, f.parent);
});

test('private observations are single-use and retain an immutable declaration', async () => {
  const f = fixture(), observation = f.observe();
  assert.equal(Object.isFrozen(observation.q.subject.matter), true);
  f.q.subject.matter.code = 'MUTATED'; assert.equal(observation.q.subject.matter.code, 'SYNTHETIC');
  await withIosHttpsQualification(f.c, () => observation, f.action);
  await assert.rejects(withIosHttpsQualification(f.c, () => observation, f.action), /PRIVATE_OBSERVATION_REQUIRED/);
  assert.equal(f.calls.filter(row => row[0] === 'create').length, 1);
});
test('late successful child absence cannot publish completion beyond cleanup reserve', async () => {
  const f = fixture(); f.io.knownSessionAbsent = async id => { f.now(190); return { sessionId: id, status: 404, error: 'invalid session id' }; };
  await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), error => error.captureRequiresProcessExit === true && error.errors.some(value => value.message === 'QUAL_IOS_CLEANUP_DEADLINE'));
  assert.equal(f.events.length, 0); assert.equal(f.c.driver, f.parent); assert.equal(f.calls.filter(row => row[0] === 'inventory').length, 0);
});

test('cleanup timeout uncertainty survives falsy and frozen body errors despite later empty session proof', async () => {
  for (const original of [false, Object.freeze(new Error('SYNTHETIC_FROZEN_BODY'))]) {
    const f = fixture(); f.base.deadline = 1; f.base.cleanupDeadline = 2;
    let acknowledge; const deferred = new Promise(resolve => { acknowledge = resolve; });
    f.child.terminateApp = () => deferred;
    await assert.rejects(withIosHttpsQualification(f.c, f.observe, async () => { throw original; }), error => error.captureRequiresProcessExit === true && error.cause === original && error.errors[0] === original && error.errors.some(value => value instanceof Error && value.message === 'QUAL_IOS_CLEANUP_DEADLINE'));
    assert.ok(f.calls.some(row => row[0] === 'absence')); assert.ok(f.calls.some(row => row[0] === 'inventory')); assert.equal(f.events.length, 0); acknowledge();
  }
});
test('slow final completion recording cannot finish successfully past cleanup reserve', async () => {
  for (const throws of [false, true]) {
    const f = fixture(); f.io.record = () => { f.now(190); if (throws) throw 0; };
    await assert.rejects(withIosHttpsQualification(f.c, f.observe, f.action), error => throws ? error instanceof AggregateError && error.cause === 0 && error.errors[0] === 0 && error.errors.some(value => value instanceof Error && value.message === 'QUAL_IOS_CLEANUP_DEADLINE') : error.message === 'QUAL_IOS_CLEANUP_DEADLINE');
    assert.equal(f.c.driver, f.parent); assert.ok(f.calls.some(row => row[0] === 'inventory'));
  }
});

test('iOS cleanup reserve is bounded from the actual case or suite limited main deadline', () => {
  assert.deepEqual(iosQualificationDeadlines(0, 1000000), { deadline: 300000, cleanupDeadline: 390000 });
  assert.deepEqual(iosQualificationDeadlines(0, 200000), { deadline: 80000, cleanupDeadline: 170000 });
  assert.throws(() => iosQualificationDeadlines(0, 120000), /MAIN_WINDOW_REQUIRED/);
});
test('iOS failure classification never evaluates arbitrary getters or changes primitive exceptions', async () => {
  let reads = 0;
  const original = Object.freeze(Object.defineProperties({}, { message: { get() { reads++; throw new Error('GETTER'); } }, captureRequiresProcessExit: { get() { reads++; throw new Error('GETTER'); } } }));
  for (const value of [original, undefined, null, false, 0, '']) assert.deepEqual(iosQualificationFailure(value), { unavailable: false, captureRequiresProcessExit: false });
  assert.equal(reads, 0);
  const f = fixture(); f.base.contractOnly = false;
  let unavailable;
  try { f.observe(); } catch (error) { unavailable = error; }
  assert.deepEqual(iosQualificationFailure(unavailable), { unavailable: true, captureRequiresProcessExit: false });
  const g = fixture(); g.io.createChild = async () => { throw original; };
  await assert.rejects(withIosHttpsQualification(g.c, g.observe, g.action), error => error.cause === original && iosQualificationFailure(error).captureRequiresProcessExit === true);
  assert.equal(reads, 0);
});

test('canonical iOS record-link scenario remains explicitly unavailable before creating any physical child', async () => {
  const { clientExtensionScenarios } = await import('../../apps/mobile/e2e/client-extensions-20261028.mjs');
  const { ClientExtensionUnavailable } = await import('../../apps/mobile/e2e/client-extensions-ui.mjs');
  const f = fixture(); delete f.c.contractOnly; f.base.contractOnly = false;
  f.c.withHttpsQualification = async action => {
    try { return await withIosHttpsQualification(f.c, f.observe, action); }
    catch (error) { if (iosQualificationFailure(error).unavailable) throw new ClientExtensionUnavailable('QUAL_IOS_REAL_INSTALLED_ARTIFACT_ATTESTOR_UNAVAILABLE'); throw error; }
  };
  const scenario = clientExtensionScenarios.find(row => row.id === 'CX28-LINK-05');
  await assert.rejects(scenario.run(f.c), error => error instanceof ClientExtensionUnavailable && error.message === 'QUAL_IOS_REAL_INSTALLED_ARTIFACT_ATTESTOR_UNAVAILABLE');
  assert.equal(f.calls.length, 0); assert.equal(f.events.length, 0); assert.equal(f.c.driver, f.parent); assert.equal(f.c.fixture, f.oldFixture); assert.equal(f.c.binaryHash, 'd'.repeat(64));
});
