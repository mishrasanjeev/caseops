import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { androidQualificationInventories, validateQualificationNativeReports, promoteAndroidQualification, admitQualificationPromotionOutput } from './android-qualification-promotion.mjs';
import { storeGatesFor } from './store-packaging-execution.mjs';
import { reconcileResults } from '../../apps/mobile/e2e/support.mjs';
import { V1RunEvidence } from '../../apps/mobile/e2e/v1-run-evidence.mjs';
import { reconcileV1Sessions } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
// Synthetic contract fixtures retain actual descriptor-bound bytes; persistence
// fsync timing is covered by the unchanged canonical V1 evidence suite.
const fixtureIo = Object.fromEntries(['openSync', 'appendFileSync', 'closeSync', 'fstatSync', 'lstatSync', 'readSync'].map(key => [key, fs[key]])); fixtureIo.fsyncSync = () => {};
const hash = value => createHash('sha256').update(value).digest('hex');
const source = { sourceSha: 'a'.repeat(40), sourceFingerprint: 'b'.repeat(64), sourceDirty: false, inputFileCount: 260 };
function fixture(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-promotion-contract-'))); fs.chmodSync(root, 0o700);
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const save = (name, value) => { const file = path.join(root, name); fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
    const bytes = Buffer.isBuffer(value) ? value : Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
    fs.writeFileSync(file, bytes, { mode: 0o600, flag: 'wx' }); return { path: file, sha256: hash(bytes) }; };
  const qualificationEvidence = { path: path.join(root, 'qualification.json'), sha256: hash('qualification placeholder') };
  const qualification = { kind: 'actual-android-https-qualification', contractOnly: false, observed: true, source,
    actualOsVerifiedHost: true, unforcedResolver: true, unforcedColdWarmDispatchCount: 2, sourceAndInstalledArtifactRechecked: true,
    binaryHash: hash('qualified APK'), udid: 'emulator-5584' };
  const reports = {}, harnesses = {};
  let session = 0;
  for (const [name, intended] of Object.entries(androidQualificationInventories())) {
    const binaryHash = hash('QA APK ' + name); harnesses[name] = hash('harness ' + name);
    const events = [{ type: 'run_started', inventoryId: 'synthetic-' + name, platform: 'android', intended, discovered: intended,
      source, binaryHash, harnessFingerprint: harnesses[name] }, { type: 'preflight_result', status: 'passed', binaryHash }];
    for (const id of intended) {
      const sessionId = '00000000-0000-4000-8000-' + String(++session).padStart(12, '0');
      for (const phase of ['setup', 'call', 'teardown']) {
        events.push({ type: 'phase_started', id, phase });
        if (phase === 'setup') events.push({ type: 'appium_session', id, state: 'created', sessionId });
        if (phase === 'call' && id === 'android:CX28-LINK-05') events.push({ type: 'https_qualification_completed', id, contractOnly: false,
          binaryHash: qualification.binaryHash, qualificationEvidence, sessionId, source, udid: qualification.udid });
        if (phase === 'teardown') events.push({ type: 'appium_session', id, state: 'deleted', sessionId });
        events.push({ type: 'phase_result', id, phase, status: 'passed' });
      }
    }
    events.push({ type: 'postflight_result', status: 'passed' }, { type: 'run_completed', platform: 'android', intendedCount: intended.length });
    let summary = { ...reconcileResults(events, intended), intended, discovered: intended };
    const report = { events, binaryHash, summary, qualificationEvidence };
    if (name === 'qp') Object.assign(summary, { pairedSessions: true, nativeExecution: 'actual' });
    if (name === 'client') Object.assign(summary, { actualNativeExecution: true, nativeExecution: 'observed' });
    if (name === 'files') Object.assign(summary, { nativeSessionCount: 17, nativeExecution: 'observed-Appium-sessions' });
    if (name === 'v1') {
      const directory = path.join(root, 'v1'); fs.mkdirSync(directory, { mode: 0o700 }); const journal = new V1RunEvidence(directory, fixtureIo);
      for (const event of events) { journal.write(event); if (event.type === 'preflight_result') journal.write({ type: 'browser_step', step: 'synthetic-public-workflow' }); }
      summary.evidence = journal.close(); report.events = journal.events; report.mainBytes = fs.readFileSync(path.join(directory, 'events.jsonl'));
      report.browserBytes = fs.readFileSync(path.join(directory, 'browser-events.jsonl'));
      Object.assign(summary, reconcileV1Sessions(report.events, { requireComplete: true }), { completed: true });
      const ids = report.events.filter(row => row.type === 'appium_session' && row.state === 'created').map(row => row.sessionId);
      summary.sessionCleanup = ids.map(id => ({ id, attempted: true, acknowledged: true }));
      summary.sessionAbsence = { verified: true, known: ids.map(id => ({ id, status: 404, error: 'invalid session id' })), completeSessionInventory: [] };
    }
    reports[name] = report;
  }
  return { root, save, reports, qualification, qualificationEvidence, harnesses };
}
test('promotion inventory retains all 83 independent IDs and exactly 249 original phases', t => {
  const f = fixture(t); assert.deepEqual(Object.values(androidQualificationInventories()).map(rows => rows.length), [23, 17, 2, 24, 17]);
  assert.equal(validateQualificationNativeReports(f.reports, f.qualification, source, f.harnesses).nativeCasesPassed, 83);
});
test('passed rows cannot promote a missing, failed or mismatched canonical runner summary', t => {
  for (const name of Object.keys(androidQualificationInventories())) for (const change of [r => { delete r.summary; }, r => { r.summary.status = 'incomplete'; }, r => { r.summary.nativeCallsPassed--; }]) {
    const f = fixture(t); change(f.reports[name]); assert.throws(() => validateQualificationNativeReports(f.reports, f.qualification, source, f.harnesses));
  }
});
test('retained passing V1 main rows cannot upgrade failed final close, stream bytes or session absence', t => {
  for (const change of [r => { r.summary.completed = false; }, r => { r.summary.evidence.status = 'incomplete'; },
    r => { r.summary.evidence.failure = 'V1_EVIDENCE_CLOSE_FAILED'; }, r => { r.browserBytes = Buffer.alloc(0); },
    r => { r.browserBytes = Buffer.from('tampered'); }, r => { delete r.browserBytes; }, r => { r.summary.evidence.streams[1].fileBytesVerified = false; },
    r => { r.summary.sessionAbsence.verified = false; }, r => { r.summary.sessionAbsence.known.pop(); }, r => { r.summary.sessionCleanup[0].acknowledged = false; }]) {
    const f = fixture(t); change(f.reports.v1); assert.throws(() => validateQualificationNativeReports(f.reports, f.qualification, source, f.harnesses));
  }
});
test('native phase, source, harness, artifact, session and case-specific proof remain independently required', t => {
  for (const change of [f => { f.reports.core.events.find(r => r.type === 'phase_result').status = 'failed'; },
    f => { f.reports.core.events[0].source = { ...source, sourceSha: 'f'.repeat(40) }; }, f => { f.reports.files.events[0].harnessFingerprint = 'f'.repeat(64); },
    f => { f.reports.qp.binaryHash = 'f'.repeat(64); }, f => { f.reports.client.events.find(r => r.state === 'deleted').sessionId = 'f'.repeat(36); },
    f => { f.qualification.observed = false; }, f => { f.qualification.contractOnly = true; }, f => { f.qualification.unforcedResolver = false; },
    f => { f.reports.client.events.find(r => r.type === 'https_qualification_completed').binaryHash = 'f'.repeat(64); }]) {
    const f = fixture(t); change(f); assert.throws(() => validateQualificationNativeReports(f.reports, f.qualification, source, f.harnesses));
  }
});
function promotionFixture(t) {
  const f = fixture(t), { save } = f;
  const artifact = save('candidate.aab', 'SYNTHETIC SIGNED AAB'), apk = save('candidate.apk', 'SYNTHETIC QUALIFIED APK');
  f.qualification.binaryHash = apk.sha256; const proofEvent = f.reports.client.events.find(r => r.type === 'https_qualification_completed'); proofEvent.binaryHash = apk.sha256;
  const settings = save('settings.json', { version: '1.0.0', androidVersionCode: 4, identities: { androidPackageName: 'ai.caseops.mobile', iosBundleIdentifier: null } });
  const recipe = save('recipe.json', { source: Object.fromEntries(Object.entries(source).filter(([key]) => key !== 'sourceDirty')), storeBuild: settings });
  const git = save('git', 'SYNTHETIC GIT');
  const tools = save('tools.json', { entries: { git: { ...git, sizeBytes: fs.statSync(git.path).size } } });
  const candidateValue = { kind: 'caseops-android-qualification-result', observed: true, qualificationOnly: true, distributionSigningVerified: true,
    contractOnly: false, storeAcceptance: false, uploaded: false, submissionAllowed: false, cleanup: { complete: true }, inputBindings: { toolsSha256: tools.sha256 },
    recipe, tools, artifact, qualificationApk: { artifact: apk, aab: artifact }, postflight: { artifactSha256: artifact.sha256, distributionSigningVerified: true },
    sourceSha: source.sourceSha, tree: 'c'.repeat(40), fullSourceFingerprint: 'd'.repeat(64) };
  const candidate = save('candidate.json', candidateValue);
  Object.assign(f.qualification, { qualificationBuild: candidate, storeBuild: settings });
  const qualificationEvidence = save('actual-qualification.json', f.qualification); proofEvent.qualificationEvidence = qualificationEvidence;
  const nativeReports = {};
  for (const [name, r] of Object.entries(f.reports)) {
    const directory = 'reports/' + name + '/';
    nativeReports[name] = { events: save(directory + 'events.jsonl', name === 'v1' ? r.mainBytes : r.events.map(row => JSON.stringify(row) + '\n').join('')),
      summary: save(directory + (name === 'files' ? 'result.json' : 'summary.json'), r.summary), artifact: save(directory + 'qa.apk', 'SYNTHETIC QA ' + name) };
    // Bind the actual file digest to each synthetic report before serialization.
    r.binaryHash = nativeReports[name].artifact.sha256; r.events[0].binaryHash = r.binaryHash; r.events.find(row => row.type === 'preflight_result').binaryHash = r.binaryHash;
    if (name !== 'v1') { fs.unlinkSync(nativeReports[name].events.path); nativeReports[name].events = save(directory + 'events.jsonl', r.events.map(row => JSON.stringify(row) + '\n').join('')); }
    else {
      // V1's immutable byte manifest must reflect the same bound artifact.
      const journalDir = path.join(f.root, 'rebound-v1'); fs.mkdirSync(journalDir, { mode: 0o700 }); const journal = new V1RunEvidence(journalDir, fixtureIo);
      for (const row of r.events) { const { evidenceSequence, ...event } = row; journal.write(event); }
      r.summary.evidence = journal.close(); r.mainBytes = fs.readFileSync(path.join(journalDir, 'events.jsonl')); r.browserBytes = fs.readFileSync(path.join(journalDir, 'browser-events.jsonl'));
      fs.unlinkSync(nativeReports[name].events.path); nativeReports[name].events = save(directory + 'events.jsonl', r.mainBytes);
      fs.unlinkSync(nativeReports[name].summary.path); nativeReports[name].summary = save(directory + 'summary.json', r.summary);
      nativeReports[name].browserEvents = save(directory + 'browser-events.jsonl', r.browserBytes);
    }
  }
  const gateValue = { schemaVersion: 2, kind: 'caseops-reviewed-store-gates', platform: 'android', sourceSha: source.sourceSha, tree: candidateValue.tree,
    sourceFingerprint: source.sourceFingerprint, inputFileCount: source.inputFileCount, reviewedAt: new Date().toISOString(), inputBindings: candidateValue.inputBindings,
    results: Object.fromEntries(storeGatesFor('android').map(name => [name, 'passed'])), evidence: storeGatesFor('android').map((name, i) => save('gate-' + i + '.json', { syntheticContractOnly: true, name })) };
  const gates = save('gates.json', gateValue), storeHistory = save('history.json', { kind: 'caseops-reviewed-actual-store-history', identities: { androidPackageName: 'ai.caseops.mobile', iosBundleIdentifier: null },
    observedAt: new Date().toISOString(), androidVersionCode: 3, evidence: [save('history-proof.json', { syntheticContractOnly: true })] });
  const q = { schemaVersion: 1, kind: 'caseops-android-qualification-promotion', platform: 'android', candidate, gates, nativeReports, qualificationEvidence, storeHistory,
    output: path.join(f.root, 'promotion') };
  return { ...f, q, gateValue, candidateValue, sourceReader: () => ({ sourceSha: source.sourceSha, tree: candidateValue.tree, fullSourceFingerprint: candidateValue.fullSourceFingerprint }) };
}
test('unchanged-byte promotion is explicit all-15 and synthetic adapters never authorize submission', async t => {
  const f = promotionFixture(t), ref = f.save('request.json', f.q);
  const result = await promoteAndroidQualification(ref, { root: path.join(f.root, 'source'), sourceReader: f.sourceReader, harnesses: f.harnesses });
  assert.equal(result.native.nativeCasesPassed, 83); assert.equal(result.contractOnly, true); assert.equal(result.submissionAllowed, false);
  assert.equal(result.artifactRebuilt, false); assert.equal(result.uploaded, false); assert.deepEqual(result.artifact, f.candidateValue.artifact);
});
test('each of the final 15 gates blocks promotion before output or artifact processing', async t => {
  for (const gate of storeGatesFor('android')) {
    const f = promotionFixture(t); f.gateValue.results[gate] = 'failed'; f.q.gates = f.save('failed-gates.json', f.gateValue);
    await assert.rejects(promoteAndroidQualification(f.save('request.json', f.q), { root: path.join(f.root, 'source'), sourceReader: f.sourceReader, harnesses: f.harnesses }), /QUALIFICATION_ALL15_GATES_REQUIRED/);
    assert.equal(fs.existsSync(f.q.output), false);
  }
});
test('promotion refuses candidate, source, exact tested bytes and report completion drift', async t => {
  for (const change of [f => { f.candidateValue.cleanup.complete = false; }, f => { f.candidateValue.sourceSha = 'f'.repeat(40); },
    f => { f.candidateValue.qualificationApk.artifact.sha256 = 'f'.repeat(64); }, f => { f.candidateValue.postflight.artifactSha256 = 'f'.repeat(64); },
    f => { f.candidateValue.observed = false; }, f => { f.candidateValue.contractOnly = true; }]) {
    const f = promotionFixture(t); change(f); f.q.candidate = f.save('drifted-candidate.json', f.candidateValue);
    await assert.rejects(promoteAndroidQualification(f.save('request.json', f.q), { root: path.join(f.root, 'source'), sourceReader: f.sourceReader, harnesses: f.harnesses }));
    assert.equal(fs.existsSync(f.q.output), false);
  }
});

test('promotion output rejects current source root and children before publication', () => {
  const root = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
  for (const output of [root, root + '/', path.join(root, 'promotion'), root + '/folder/../promotion', root + '/../' + path.basename(root) + '/promotion']) assert.throws(() => admitQualificationPromotionOutput(output), /QUALIFICATION_OUTPUT_OUTSIDE_SOURCE_REQUIRED/);
});

test('Git replacement during either actual promotion source read cannot publish unchanged artifacts', async t => {
  for (const replaceAt of [1, 2]) {
    const f = promotionFixture(t), tools = JSON.parse(fs.readFileSync(f.candidateValue.tools.path)); let calls = 0;
    const sourceReader = (...args) => { const result = f.sourceReader(...args); if (++calls === replaceAt) fs.writeFileSync(tools.entries.git.path, 'CHANGED_EXECUTABLE_BYTES'); return result; };
    await assert.rejects(promoteAndroidQualification(f.save('request.json', f.q), { root: path.join(f.root, 'source'), sourceReader, harnesses: f.harnesses }), /STORE_INPUT_HASH_MISMATCH|STORE_INPUT_IDENTITY_REQUIRED/);
    assert.equal(calls, replaceAt); assert.equal(fs.existsSync(f.q.output), false);
  }
});

test('a failed source read preserves its exact falsy or frozen original even when the pinned Git recheck also fails', async t => {
  for (const failAt of [1, 2]) for (const original of [undefined, null, false, 0, '', Object.freeze(Error('SYNTHETIC_SOURCE_FAILURE'))]) {
    const f = promotionFixture(t), tools = JSON.parse(fs.readFileSync(f.candidateValue.tools.path)); let calls = 0, failed = false, gitReads = 0;
    const open = fs.openSync; fs.openSync = (file, ...args) => { if (file === tools.entries.git.path) gitReads++; return open(file, ...args); };
    const sourceReader = (...args) => { if (++calls === failAt) { fs.writeFileSync(tools.entries.git.path, 'CHANGED_EXECUTABLE_BYTES'); throw original; } return f.sourceReader(...args); };
    try { await promoteAndroidQualification(f.save('request.json', f.q), { root: path.join(f.root, 'source'), sourceReader, harnesses: f.harnesses }); }
    catch (error) { failed = true; assert.equal(error, original); }
    finally { fs.openSync = open; }
    assert.equal(gitReads, failAt * 2, 'both pre/post held-descriptor Git reads occurred');
    assert.equal(failed, true); assert.equal(calls, failAt); assert.equal(fs.existsSync(f.q.output), false);
  }
});
