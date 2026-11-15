// Authorizes only unchanged candidate bytes after the full platform gate. No
// build, signing, upload, track edit, native case execution or public mutation.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readInput, jsonInput, objectKeys, privateDirectory, writePrivate, gitSource } from './store-packaging-inputs.mjs';
import { storeGatesFor } from './store-packaging-execution.mjs';
import { inventory as coreInventory, harnessFingerprint } from '../../apps/mobile/e2e/suite.mjs';
import { androidFilesInventory } from '../../apps/mobile/e2e/android-files.mjs';
import { QP } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
import { androidClientExtensions } from '../../apps/mobile/e2e/client-extensions-inventory.mjs';
import { validateV1EvidenceStreams } from '../../apps/mobile/e2e/v1-run-evidence.mjs';
import { reconcileV1Sessions } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { v1Inventory } from '../../apps/mobile/e2e/v1-workflows-inventory.mjs';
import { reconcileResults } from '../../apps/mobile/e2e/support.mjs';
import { androidFilesHarnessFingerprint } from './run-android-files.mjs';
import { qpHarnessFingerprint } from './run-queue-privacy.mjs';
import { clientHarnessFingerprint } from './client-extension-runtime.mjs';
import { v1HarnessFingerprint } from './run-v1-workflows.mjs';

const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
export function androidQualificationInventories() {
  const result = { core: coreInventory.cases.map(row => row.id), files: androidFilesInventory.cases.map(row => row.id),
    qp: [...QP.cases], client: androidClientExtensions.cases.map(row => row.id), v1: v1Inventory.cases.map(row => row.id) };
  assert.deepEqual(Object.values(result).map(rows => rows.length), [23, 17, 2, 24, 17]);
  assert.equal(new Set(Object.values(result).flat()).size, 83);
  return Object.fromEntries(Object.entries(result).map(([name, rows]) => [name, rows.map(id => 'android:' + id)]));
}
export function currentQualificationHarnesses(root = ROOT) {
  return { core: harnessFingerprint(), files: androidFilesHarnessFingerprint(root), qp: qpHarnessFingerprint(root),
    client: clientHarnessFingerprint(root), v1: v1HarnessFingerprint(root) };
}

export function validateQualificationNativeReports(reports, qualification, source, harnesses) {
  const inventories = androidQualificationInventories();
  objectKeys(reports, Object.keys(inventories), 'QUALIFICATION_COMPLETE_NATIVE_REPORTS_REQUIRED');
  for (const [name, intended] of Object.entries(inventories)) {
    const report = reports[name], events = report.events;
    assert.ok(Array.isArray(events) && events.length > 0 && events.length <= 4000, 'QUALIFICATION_NATIVE_JOURNAL_BOUND');
    const result = reconcileResults(events, intended);
    assert.equal(result.status, 'passed', 'QUALIFICATION_COMPLETE_NATIVE_PASS_REQUIRED');
    assert.equal(result.nativeCallsPassed, intended.length);
    assert.ok(report.summary && report.summary.status === 'passed', 'QUALIFICATION_FINAL_RUNNER_SUMMARY_REQUIRED');
    for (const key of Object.keys(result)) assert.deepEqual(report.summary[key], result[key], 'QUALIFICATION_SUMMARY_JOURNAL_MISMATCH');
    assert.deepEqual(report.summary.intended, intended); assert.deepEqual(report.summary.discovered, intended);
    if (name === 'qp') { assert.equal(report.summary.pairedSessions, true); assert.equal(report.summary.nativeExecution, 'actual'); }
    if (name === 'client') { assert.notEqual(report.summary.captureCleanupUncertain, true); assert.notEqual(report.summary.captureRequiresProcessExit, true); assert.equal(report.summary.actualNativeExecution, true); assert.equal(report.summary.nativeExecution, 'observed'); }
    if (name === 'files') { assert.equal(report.summary.nativeSessionCount, 17); assert.equal(report.summary.nativeExecution, 'observed-Appium-sessions'); }
    if (name === 'v1') {
      assert.equal(report.summary.completed, true, 'QUALIFICATION_COMPLETED_V1_REQUIRED');
      validateV1EvidenceStreams(report.summary.evidence, report.mainBytes, report.browserBytes);
      const actualSessions = reconcileV1Sessions(events, { requireComplete: true });
      for (const key of Object.keys(actualSessions)) assert.deepEqual(report.summary[key], actualSessions[key]);
      const cleanup = report.summary.sessionCleanup, absence = report.summary.sessionAbsence;
      assert.equal(cleanup.length, 17); assert.equal(absence.verified, true); assert.deepEqual(absence.completeSessionInventory, []);
      const created = events.filter(row => row.type === 'appium_session' && row.state === 'created').map(row => row.sessionId);
      assert.deepEqual(cleanup.map(row => row.id), created);
      assert.ok(cleanup.every(row => row.attempted === true && row.acknowledged === true));
      assert.deepEqual(absence.known, created.map(id => ({ id, status: 404, error: 'invalid session id' })));
    }
    const start = events[0], nativeSource = start.source ?? Object.fromEntries(['sourceSha', 'sourceFingerprint', 'sourceDirty', 'inputFileCount'].map(key => [key, start[key]]));
    assert.deepEqual(nativeSource, source, 'QUALIFICATION_NATIVE_SOURCE_MISMATCH');
    assert.equal(start.harnessFingerprint, harnesses[name], 'QUALIFICATION_NATIVE_HARNESS_MISMATCH');
    const preflight = events.find(row => row.type === 'preflight_result');
    assert.equal(preflight.binaryHash ?? preflight.installed?.binaryHash ?? start.binaryHash, report.binaryHash, 'QUALIFICATION_NATIVE_ARTIFACT_MISMATCH');
    const sessions = events.filter(row => row.type === 'appium_session');
    for (const id of intended) {
      const rows = sessions.filter(row => row.id === id);
      assert.deepEqual(rows.map(row => row.state), ['created', 'deleted'], 'QUALIFICATION_NATIVE_SESSION_CLEANUP_REQUIRED');
      assert.match(rows[0].sessionId, /^[a-f0-9-]{36}$/i);
      assert.equal(rows[0].sessionId, rows[1].sessionId);
    }
    assert.equal(sessions.length, intended.length * 2);
    assert.equal(new Set(sessions.filter(row => row.state === 'created').map(row => row.sessionId)).size, intended.length);
  }
  assert.equal(qualification.kind, 'actual-android-https-qualification');
  assert.equal(qualification.contractOnly, false); assert.equal(qualification.observed, true);
  assert.deepEqual(qualification.source, source); assert.equal(qualification.actualOsVerifiedHost, true);
  assert.equal(qualification.unforcedResolver, true); assert.equal(qualification.unforcedColdWarmDispatchCount, 2);
  assert.equal(qualification.sourceAndInstalledArtifactRechecked, true);
  const events = reports.client.events, id = 'android:CX28-LINK-05';
  const proof = events.filter(row => row.type === 'https_qualification_completed');
  assert.equal(proof.length, 1, 'QUALIFICATION_ONE_CASE_PROOF_REQUIRED');
  assert.equal(proof[0].id, id); assert.equal(proof[0].contractOnly, false);
  assert.deepEqual(proof[0].source, source); assert.equal(proof[0].udid, qualification.udid);
  const liveSession = events.find(row => row.type === 'appium_session' && row.state === 'created' && row.id === id);
  assert.equal(proof[0].sessionId, liveSession.sessionId, 'QUALIFICATION_OWNED_SESSION_REQUIRED');
  assert.equal(proof[0].binaryHash, qualification.binaryHash);
  assert.deepEqual(proof[0].qualificationEvidence, reports.client.qualificationEvidence);
  const began = events.findIndex(row => row.id === id && row.type === 'phase_started' && row.phase === 'call');
  const ended = events.findIndex(row => row.id === id && row.type === 'phase_result' && row.phase === 'call');
  assert.ok(began < events.indexOf(proof[0]) && events.indexOf(proof[0]) < ended, 'QUALIFICATION_PROOF_OUTSIDE_CASE');
  return { nativeCasesPassed: 83, exactPhasesPassed: 249, qualificationBinaryHash: qualification.binaryHash,
    acceptanceScope: 'Explicit QA artifact per suite plus the separately bound production HTTPS artifact for LINK05; no cross-artifact pass transfer' };
}

export function admitQualificationPromotionOutput(output, root = ROOT) {
  assert.ok(path.resolve(root) === root && path.isAbsolute(output) && path.resolve(output) === output && !output.startsWith(root + path.sep) && output !== root && !output.startsWith(ROOT + path.sep) && output !== ROOT, 'QUALIFICATION_OUTPUT_OUTSIDE_SOURCE_REQUIRED');
}
function readPromotionSource(root, git, deadline, sourceReader) {
  const verify = () => readInput(git.path, { sha256: git.sha256, maxBytes: git.sizeBytes, systemTool: true, deadline }).bytes.fill(0);
  // Each verification uses the canonical held-descriptor reader and the same
  // original deadline/declared byte bound. No source-read budget is reset.
  verify();
  let value, original, failed = false;
  try { value = sourceReader(root, git.path, { entries: 0, bytes: 0, deadline }); }
  catch (error) { failed = true; original = error; }
  try { verify(); }
  catch (error) { if (!failed) throw error; /* preserve the exact primary, including falsy/frozen throws */ }
  if (failed) throw original;
  return value;
}

export async function promoteAndroidQualification(requestRef, { root = ROOT, sourceReader = gitSource, harnesses } = {}) {
  const contractOnly = sourceReader !== gitSource || harnesses !== undefined;
  assert.ok(contractOnly || (root === ROOT && process.platform === 'darwin' && process.versions.node === '24.15.0'), 'QUALIFICATION_PINNED_HOST_REQUIRED');
  assert.ok(contractOnly || process.env.CASEOPS_ANDROID_QUALIFICATION_PROMOTE_GO === 'EXPLICIT_REVIEWED_ALL15_GATE_PROMOTION', 'QUALIFICATION_PROMOTION_NOT_ARMED');
  const deadline = Date.now() + 120000;
  const json = ref => jsonInput(ref, { deadline }).value;
  const q = json(requestRef);
  objectKeys(q, ['schemaVersion', 'kind', 'platform', 'candidate', 'gates', 'nativeReports', 'qualificationEvidence', 'storeHistory', 'output'], 'QUALIFICATION_PROMOTION_REQUEST_REQUIRED');
  assert.equal(q.schemaVersion, 1); assert.equal(q.kind, 'caseops-android-qualification-promotion'); assert.equal(q.platform, 'android');
  admitQualificationPromotionOutput(q.output, root);
  const gates = json(q.gates), candidate = json(q.candidate), expectedGates = storeGatesFor('android');
  assert.equal(gates.schemaVersion, 2); assert.equal(gates.kind, 'caseops-reviewed-store-gates'); assert.equal(gates.platform, 'android');
  objectKeys(gates.results, expectedGates, 'QUALIFICATION_ALL15_GATES_REQUIRED');
  assert.ok(expectedGates.every(name => gates.results[name] === 'passed'), 'QUALIFICATION_ALL15_GATES_REQUIRED');
  assert.ok(Date.parse(gates.reviewedAt) <= Date.now() && Date.now() - Date.parse(gates.reviewedAt) <= 86400000, 'QUALIFICATION_FRESH_GATES_REQUIRED');
  assert.ok(Array.isArray(gates.evidence) && gates.evidence.length >= 15 && gates.evidence.length <= 256);
  for (const ref of gates.evidence) json(ref);
  assert.equal(candidate.kind, 'caseops-android-qualification-result');
  for (const key of ['observed', 'qualificationOnly', 'distributionSigningVerified']) assert.equal(candidate[key], true, 'QUALIFICATION_REAL_CANDIDATE_REQUIRED');
  for (const key of ['contractOnly', 'storeAcceptance', 'uploaded', 'submissionAllowed']) assert.equal(candidate[key], false);
  assert.equal(candidate.cleanup.complete, true);
  assert.deepEqual(gates.inputBindings, candidate.inputBindings, 'QUALIFICATION_PROMOTION_BINDINGS_CHANGED');
  const recipe = json(candidate.recipe), tools = json(candidate.tools), settings = json(recipe.storeBuild), history = json(q.storeHistory);
  assert.equal(history.kind, 'caseops-reviewed-actual-store-history'); assert.deepEqual(history.identities, settings.identities);
  assert.ok(Date.parse(history.observedAt) <= Date.now() && Date.now() - Date.parse(history.observedAt) <= 86400000);
  assert.ok(Number.isSafeInteger(history.androidVersionCode) && history.androidVersionCode < settings.androidVersionCode, 'QUALIFICATION_FRESH_STORE_COUNTER_REQUIRED');
  for (const ref of history.evidence) json(ref);
  const git = tools.entries.git;
  const source = readPromotionSource(root, git, deadline, sourceReader);
  assert.equal(source.sourceSha, candidate.sourceSha); assert.equal(source.tree, candidate.tree);
  assert.equal(source.fullSourceFingerprint, candidate.fullSourceFingerprint);
  assert.equal(gates.sourceSha, source.sourceSha); assert.equal(gates.tree, source.tree);
  const nativeSource = { ...recipe.source, sourceDirty: false };
  assert.equal(gates.sourceFingerprint, nativeSource.sourceFingerprint); assert.equal(gates.inputFileCount, nativeSource.inputFileCount);
  const reports = {};
  objectKeys(q.nativeReports, Object.keys(androidQualificationInventories()), 'QUALIFICATION_COMPLETE_NATIVE_REPORTS_REQUIRED');
  let reportBytes = 0;
  for (const [name, report] of Object.entries(q.nativeReports)) {
    objectKeys(report, name === 'v1' ? ['events', 'artifact', 'summary', 'browserEvents'] : ['events', 'artifact', 'summary'], 'QUALIFICATION_NATIVE_REPORT_REQUIRED');
    assert.equal(path.dirname(report.summary.path), path.dirname(report.events.path), 'QUALIFICATION_CANONICAL_REPORT_DIRECTORY_REQUIRED');
    assert.equal(path.basename(report.events.path), 'events.jsonl');
    assert.equal(path.basename(report.summary.path), name === 'files' ? 'result.json' : 'summary.json');
    const held = readInput(report.events.path, { sha256: report.events.sha256, maxBytes: 2 * 1024 * 1024, deadline });
    let events, mainBytes;
    try { reportBytes += held.bytes.length; assert.ok(reportBytes <= 10 * 1024 * 1024); mainBytes = Buffer.from(held.bytes); const text = new TextDecoder('utf-8', { fatal: true }).decode(mainBytes); assert.ok(text.endsWith('\n')); events = text.slice(0, -1).split('\n').map(row => JSON.parse(row)); }
    finally { held.bytes.fill(0); }
    readInput(report.artifact.path, { sha256: report.artifact.sha256, maxBytes: 512 * 1024 * 1024, deadline }).bytes.fill(0);
    reports[name] = { events, summary: json(report.summary), binaryHash: report.artifact.sha256 };
    if (name === 'v1') {
      assert.equal(path.dirname(report.browserEvents.path), path.dirname(report.events.path)); assert.equal(path.basename(report.browserEvents.path), 'browser-events.jsonl');
      const browser = readInput(report.browserEvents.path, { sha256: report.browserEvents.sha256, maxBytes: 1048576, allowEmpty: true, deadline });
      reports[name].mainBytes = mainBytes; reports[name].browserBytes = browser.bytes;
    }
  }
  reports.client.qualificationEvidence = q.qualificationEvidence;
  const qualification = json(q.qualificationEvidence);
  const native = validateQualificationNativeReports(reports, qualification, nativeSource, harnesses ?? currentQualificationHarnesses(root));
  assert.deepEqual(candidate.qualificationApk.aab, candidate.artifact, 'QUALIFICATION_DERIVATION_AAB_MISMATCH');
  assert.equal(qualification.binaryHash, candidate.qualificationApk.artifact.sha256, 'QUALIFICATION_EXACT_TESTED_APK_REQUIRED');
  assert.deepEqual(qualification.qualificationBuild, q.candidate, 'QUALIFICATION_TESTED_CANDIDATE_REQUIRED');
  assert.deepEqual(qualification.storeBuild, recipe.storeBuild);
  assert.equal(candidate.postflight.artifactSha256, candidate.artifact.sha256);
  assert.equal(candidate.postflight.distributionSigningVerified, true);
  readInput(candidate.artifact.path, { sha256: candidate.artifact.sha256, maxBytes: 512 * 1024 * 1024, deadline }).bytes.fill(0);
  readInput(candidate.qualificationApk.artifact.path, { sha256: qualification.binaryHash, maxBytes: 128 * 1024 * 1024, deadline }).bytes.fill(0);
  assert.deepEqual(readPromotionSource(root, git, deadline, sourceReader), source, 'QUALIFICATION_SOURCE_CHANGED');
  admitQualificationPromotionOutput(q.output, root);
  privateDirectory(q.output, { existing: false, deadline });
  const result = { schemaVersion: 1, kind: 'caseops-android-qualified-artifact-promotion', contractOnly,
    sourceSha: source.sourceSha, tree: source.tree, fullSourceFingerprint: source.fullSourceFingerprint,
    candidate: q.candidate, gates: q.gates, nativeReports: q.nativeReports, qualificationEvidence: q.qualificationEvidence,
    artifact: candidate.artifact, qualifiedApk: candidate.qualificationApk.artifact, native,
    submissionAllowed: !contractOnly, storeAcceptance: false, uploaded: false, artifactRebuilt: false,
    hardwareAcceptance: 'Not certified by this promotion; retain the independent platform hardware review',
    playGeneratedApkAcceptance: 'Not certified by a standalone upload-key APK qualification' };
  return { ...result, evidence: writePrivate(path.join(q.output, 'promotion.json'), Buffer.from(JSON.stringify(result) + '\n'), { deadline }) };
}
