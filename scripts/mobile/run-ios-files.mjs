import assert from 'node:assert/strict';
import { createHash, randomUUID, X509Certificate } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { iosFilesInventory as inventory, iosFilesScenarios as scenarios, collectIosFiles, validateIosFilesContext,
  validateSourceSeed, validatePickerProvider, validateAsset, validatePickerAsset } from '../../apps/mobile/e2e/ios-files.mjs';
import { authenticate } from '../../apps/mobile/e2e/browser-handoff.mjs';
import { restart } from '../../apps/mobile/e2e/native-ui.mjs';
import { FixtureUnavailable, validateBuildReceipt, validateCoreFixture } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { appiumSessionEvent } from '../../apps/mobile/e2e/run-state.mjs';
import { binaryHash, Journal, localJson, localUrl, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';
import { attestIosFilesContainers, snapshotIosFilesPrivacy } from './ios-files-privacy.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const readRef = (reference) => JSON.parse(verifiedFile(reference?.path, reference?.sha256));
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
const ref = (file) => ({ path: file, sha256: digest(readFileSync(file)) });
export function knownFileSources(assets) {
  const previous = assets.priorManifestEvidence || [];
  assert.ok(Array.isArray(previous) && previous.length <= 6, 'BOUNDED_PRIOR_FILES_COHORTS_REQUIRED');
  const current = readRef(assets.manifestEvidence);
  assert.equal(current.syntheticDataOnly, true, 'SYNTHETIC_CURRENT_FILES_REQUIRED');
  assert.equal(current.kind, 'ios-files-synthetic-fixtures', 'CURRENT_FILES_MANIFEST_REQUIRED');
  assert.ok(Array.isArray(current.assets) && current.assets.length > 0 && current.assets.length <= 16, 'BOUNDED_CURRENT_FILES_REQUIRED');
  const known = [{ id: 'seeded-txt', ...assets.source, marker: assets.source.text?.trim() },
    ...previous.flatMap((reference, index) => {
      const manifest = readRef(reference);
      assert.equal(manifest.syntheticDataOnly, true, 'SYNTHETIC_PRIOR_FILES_REQUIRED');
      assert.equal(manifest.kind, 'ios-files-synthetic-fixtures', 'PRIOR_FILES_MANIFEST_REQUIRED');
      assert.ok(Array.isArray(manifest.assets) && manifest.assets.length <= 12, 'BOUNDED_PRIOR_FILES_REQUIRED');
      return manifest.assets.map(asset => ({ ...asset, id: `prior-${index}-${asset.id}` }));
    })];
  assert.ok(known.length + current.assets.length <= 60, 'BOUNDED_TOTAL_FILES_SOURCES_REQUIRED');
  return known;
}
export function assertStrictIosFilesEnvironment(fixture, environment = process.env) {
  assert.notEqual(environment.NODE_TLS_REJECT_UNAUTHORIZED, '0', 'STRICT_FILES_TLS_REQUIRED');
  assert.equal(environment.NODE_EXTRA_CA_CERTS, fixture.publicCa?.path, 'EXACT_FILES_PUBLIC_CA_REQUIRED');
  const ca = new X509Certificate(verifiedFile(fixture.publicCa?.path, fixture.publicCa?.sha256, 131072));
  assert.equal(ca.ca, true, 'FILES_PUBLIC_CA_REQUIRED');
  assert.ok(Date.parse(ca.validFrom) < Date.now() && Date.now() < Date.parse(ca.validTo), 'CURRENT_FILES_PUBLIC_CA_REQUIRED');
  const receipt = readRef(fixture.isolationEvidence);
  assert.equal(receipt.publicCA, fixture.publicCa.path, 'FILES_CA_ISOLATION_MISMATCH');
  assert.equal(receipt.tlsProof?.strictDefaultTLS, true, 'STRICT_FILES_TLS_PROOF_REQUIRED');
  assert.equal(receipt.tlsProof?.verificationDisabled, false, 'STRICT_FILES_TLS_PROOF_REQUIRED');
  return receipt;
}
export async function captureIosFilesCallFailure(context, report, caseId) {
  assert.equal(context.fixture.environment, 'docker-integration', 'SYNTHETIC_NATIVE_FAILURE_ONLY');
  assert.equal(context.fixture.syntheticDataOnly, true, 'SYNTHETIC_NATIVE_FAILURE_ONLY');
  assert.match(caseId, /^ios:FILES-(0[1-9]|1[0-7])$/);
  assert.equal(await context.driver.queryAppState(context.fixture.appId), 4, 'FAILURE_APP_NOT_FOREGROUND');
  await context.driver.switchContext('NATIVE_APP');
  // Authentication runs in setup, never in these Files calls. Still refuse
  // any hierarchy containing a password control, including hidden controls.
  const passwords = await context.driver.$$('-ios predicate string:type == "XCUIElementTypeSecureTextField"');
  assert.equal(passwords.length, 0, 'CREDENTIAL_SURFACE_FAILURE_CAPTURE_REFUSED');
  const source = await context.driver.getPageSource();
  assert.ok(typeof source === 'string' && Buffer.byteLength(source) <= 524288, 'NATIVE_FAILURE_HIERARCHY_BOUND');
  assert.equal(source.includes('XCUIElementTypeSecureTextField'), false, 'CREDENTIAL_SURFACE_FAILURE_CAPTURE_REFUSED');
  const file = path.join(report, `${caseId.slice(4)}-failure-native.xml`);
  writeFileSync(file, source, { flag: 'wx', mode: 0o600 });
  return ref(file);
}
export function filesCaseRecovery() {
  let failedCase;
  return {
    observe({ id, setupPassed, callPassed }) {
      if (setupPassed && !callPassed) failedCase = id;
    },
    async prepare(context) {
      if (!failedCase) return;
      context.record?.({ type: 'native_case_recovery', previousCase: failedCase, action: 'restart-bound-app', mutationReplay: false });
      await restart(context);
      failedCase = undefined;
    },
  };
}
export function iosFilesHarnessFingerprint() {
  const files = ['scripts/mobile/run-ios-files.mjs', 'scripts/mobile/source-snapshot.mjs',
    'scripts/mobile/ios-files-privacy.mjs', 'scripts/mobile/prepare-ios-files-fixture.py', 'scripts/mobile/admit-ios-file-source.py',
    ...readdirSync(path.join(root, 'apps/mobile/e2e')).filter(name => name.endsWith('.mjs')).map(name => `apps/mobile/e2e/${name}`)];
  const hash = createHash('sha256');
  for (const file of files.sort()) hash.update(`${file}\0${digest(readFileSync(path.join(root, file)))}\0`);
  return hash.digest('hex');
}

export async function runIosFiles() {
  const collection = collectIosFiles();
  const reportRoot = process.env.CASEOPS_MOBILE_REPORT_ROOT || path.join(os.homedir(), '.cache/caseops-mobile/ios-files-reports');
  mkdirSync(reportRoot, { recursive: true, mode: 0o700 });
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-ios-files-${randomUUID().slice(0, 8)}`;
  const report = path.join(reportRoot, runId);
  mkdirSync(report, { mode: 0o700 });
  const journal = new Journal(path.join(report, 'events.jsonl'));
  const frozen = iosFilesHarnessFingerprint();
  journal.write({ type: 'run_started', ...collection, harnessFingerprint: frozen, ...sourceSnapshot(root) });
  let completed = false;
  const interrupted = (code) => {
    if (!completed) { journal.write({ type: 'run_interrupted', reason: 'PROCESS_EXIT_BEFORE_COMPLETION', exitCode: code }); journal.close(); process.exitCode = code || 1; }
  };
  process.once('exit', interrupted);
  const deadline = setTimeout(() => {
    journal.write({ type: 'run_interrupted', reason: 'THIRTY_MINUTE_SERIAL_INVENTORY_BOUND' });
    journal.close(); process.removeListener('exit', interrupted); process.exit(124);
  }, 30 * 60 * 1000);
  deadline.unref();
  let fixture, assets, containers, baseline, remote, artifactHash, appium, preflight = false;
  const uploaded = new Map(), filesState = { uploads: {} };
  try {
    assert.equal(process.platform, 'darwin', 'IOS_REQUIRES_OWNER_MACBOOK_XCODE');
    assert.ok(path.isAbsolute(process.env.CASEOPS_MOBILE_FIXTURE || ''), 'ABSOLUTE_FILES_FIXTURE_REQUIRED');
    fixture = JSON.parse(readFileSync(process.env.CASEOPS_MOBILE_FIXTURE));
    const isolation = assertStrictIosFilesEnvironment(fixture);
    validateCoreFixture(fixture);
    assert.equal(fixture.environment, 'docker-integration', 'ISOLATED_DOCKER_REQUIRED');
    assert.equal(fixture.syntheticDataOnly, true, 'SYNTHETIC_FIXTURE_REQUIRED');
    assert.equal(fixture.filesInventory, inventory.inventoryId, 'EXACT_FILES_INVENTORY_REQUIRED');
    assets = fixture.files;
    readRef(assets.manifestEvidence); readRef(assets.pickerEvidence);
    validateSourceSeed(fixture, assets.source);
    const fileInputs = { fixture, assets, source: assets.source, provider: assets.provider };
    validatePickerProvider(fileInputs);
    for (const kind of ['txt', 'pdf', 'png', 'jpeg', 'docx']) validatePickerAsset(fileInputs, validateAsset(fileInputs, kind));
    artifactHash = binaryHash(fixture.appPath);
    validateBuildReceipt(fixture, 'ios', artifactHash);
    const source = sourceSnapshot(root);
    assert.equal(source.sourceSha, fixture.binarySourceSha, 'BINARY_SOURCE_COMMIT_MISMATCH');
    assert.equal(source.sourceFingerprint, fixture.binarySourceFingerprint, 'BINARY_SOURCE_SNAPSHOT_MISMATCH');
    const installed = execFileSync('xcrun', ['simctl', 'get_app_container', fixture.udid, fixture.appId, 'app'], { encoding: 'utf8', timeout: 10000 }).trim();
    assert.equal(binaryHash(installed), artifactHash, 'INSTALLED_BINARY_MISMATCH');
    containers = attestIosFilesContainers({ udid: fixture.udid, appId: fixture.appId });
    const staged = readRef(assets.providerEvidence);
    assert.equal(staged.folderName, assets.provider.folderName, 'FILES_STAGED_PICKER_FOLDER_MISMATCH');
    assert.deepEqual(staged.manifestEvidence, assets.manifestEvidence, 'FILES_STAGED_MANIFEST_MISMATCH');
    const preflightPrivacy = snapshotIosFilesPrivacy({ containers, stagingEvidence: assets.providerEvidence,
      knownSources: knownFileSources(assets), output: path.join(report, 'preflight-filesystem.json') });
    assert.equal(preflightPrivacy.snapshot.complete, true, 'COMPLETE_FILES_PREFLIGHT_SCAN_REQUIRED');
    assert.equal(preflightPrivacy.snapshot.providerOriginalsPreserved, true, 'FILES_PROVIDER_ORIGINALS_CHANGED');
    assert.equal(preflightPrivacy.snapshot.counts.privateAssetMatchCount, 0, 'FILES_PREFLIGHT_PRIVATE_COPY_REMAINS');
    assert.equal(preflightPrivacy.snapshot.counts.ownedStagingFiles, 0, 'FILES_PREFLIGHT_STAGING_REMAINS');
    const status = await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`);
    baseline = gatewayBaseline(status, isolation);
    for (const [url, expected, revision] of [[`${fixture.gatewayUrl}/api/build`, fixture.backendSha, fixture.backendRevision],
      [`${fixture.webGatewayUrl}/api/release-identity`, fixture.webSha, fixture.webRevision]]) {
      const identity = await localJson(url);
      assert.equal(identity.release_sha, expected, 'SERVING_RELEASE_MISMATCH');
      assert.equal(identity.revision, revision, 'SERVING_REVISION_MISMATCH');
    }
    const tooling = process.env.CASEOPS_MOBILE_TOOLING_HOME || path.join(os.homedir(), '.cache/caseops-mobile/tooling');
    remote = createRequire(path.join(tooling, 'package.json'))('webdriverio').remote;
    appium = localUrl(process.env.CASEOPS_MOBILE_APPIUM_URL || 'http://127.0.0.1:4723');
    assert.equal((await localJson(new URL('/status', appium).href)).value.ready, true, 'APPIUM_NOT_READY');
    preflight = true;
    journal.write({ type: 'preflight_result', status: 'passed', binaryHash: artifactHash, buildReceipt: fixture.buildReceipt,
      backendSha: fixture.backendSha, backendRevision: fixture.backendRevision, webSha: fixture.webSha, webRevision: fixture.webRevision,
      gatewayBaseline: baseline, manifestEvidence: assets.manifestEvidence, pickerEvidence: assets.pickerEvidence,
      source: assets.source, udid: fixture.udid, appId: fixture.appId, harnessFingerprint: frozen,
      providerEvidence: assets.providerEvidence, filesystemEvidence: preflightPrivacy.snapshotEvidence });
  } catch (error) { journal.write({ type: 'preflight_result', status: 'failed', reason: safeFailure(error, 'IOS_FILES_PREFLIGHT_FAILED') }); }
  let cleanupUncertain = false, authFailed = false;
  const recovery = filesCaseRecovery();
  const completedCases = new Set();
  for (const [index, scenario] of scenarios.entries()) {
    const id = `ios:${scenario.id}`;
    let driver, sessionId, context, setupPassed = false, callPassed = false, sessionRequested = false;
    journal.write({ type: 'phase_started', id, phase: 'setup' });
    try {
      assert.equal(preflight, true, 'PREFLIGHT_FAILED');
      assert.equal(cleanupUncertain, false, 'PREVIOUS_SESSION_CLEANUP_UNCERTAIN');
      assert.equal(authFailed, false, 'AUTHENTICATION_PREREQUISITE_FAILED');
      for (const required of scenario.requires || []) if (!completedCases.has(required)) throw new FixtureUnavailable('REQUIRED_FILES_CASE_FAILED');
      const currentContainers = attestIosFilesContainers({ udid: fixture.udid, appId: fixture.appId });
      assert.equal(currentContainers.appData.path, containers.appData.path, 'FILES_APP_CONTAINER_CHANGED');
      const installed = execFileSync('xcrun', ['simctl', 'get_app_container', fixture.udid, fixture.appId, 'app'], { encoding: 'utf8', timeout: 10000 }).trim();
      assert.equal(binaryHash(installed), artifactHash, 'INSTALLED_BINARY_CHANGED');
      sessionRequested = true;
      driver = await remote({ hostname: appium.hostname, port: Number(appium.port) || 4723, protocol: appium.protocol.slice(0, -1),
        path: appium.pathname, logLevel: 'silent', connectionRetryCount: 0, connectionRetryTimeout: 60000,
        capabilities: { platformName: 'iOS', 'appium:automationName': 'XCUITest', 'appium:deviceName': fixture.deviceName,
          'appium:platformVersion': fixture.platformVersion, 'appium:udid': fixture.udid, 'appium:bundleId': fixture.appId,
          'appium:noReset': true, 'appium:newCommandTimeout': 60, 'appium:includeSafariInWebviews': true, 'appium:webviewConnectTimeout': 20000 } });
      sessionId = driver.sessionId;
      journal.write({ ...appiumSessionEvent(sessionId, 'created'), id });
      await driver.switchContext('NATIVE_APP');
      context = { fixture, driver, platform: 'ios', runId, gatewayBaseline: baseline, assets, source: assets.source, provider: assets.provider, uploaded, filesState,
        record: (event) => journal.write({ ...event, id }),
        observeFilesystem: async (boundary, knownAssetHashes = []) => {
          assert.match(boundary, /^[a-z0-9-]{1,80}$/);
          const output = path.join(report, `${scenario.id}-${boundary}-${randomUUID().slice(0, 8)}.json`);
          const manifest = readRef(assets.manifestEvidence);
          assert.ok(knownAssetHashes.every(hash => hash === assets.source.sha256 || manifest.assets.some(asset => asset.sha256 === hash)), 'UNOWNED_PRIVACY_ASSET');
          const currentContainers = attestIosFilesContainers({ udid: fixture.udid, appId: fixture.appId });
          assert.equal(currentContainers.appData.path, containers.appData.path, 'FILES_APP_CONTAINER_CHANGED');
          const { snapshot, snapshotEvidence } = snapshotIosFilesPrivacy({ containers: currentContainers, stagingEvidence: assets.providerEvidence,
            knownSources: knownFileSources(assets), output });
          assert.equal(snapshot.complete, true, 'COMPLETE_FILES_PRIVACY_SCAN_REQUIRED');
          assert.equal(snapshot.udid, fixture.udid, 'FILES_DEVICE_MISMATCH');
          assert.equal(snapshot.appId, fixture.appId, 'FILES_APP_MISMATCH');
          assert.equal(snapshot.appDataPath, containers.appData.path, 'FILES_APP_CONTAINER_MISMATCH');
          const assertionPath = `${output}.assertion.json`;
          writeFileSync(assertionPath, `${JSON.stringify({ schemaVersion: 1, observed: true, platform: 'ios', udid: snapshot.udid,
            bundleId: snapshot.appId, boundary, ownedAppScopeOnly: true,
            providerOriginalsUnchanged: snapshot.providerOriginalsPreserved, stagedFileCount: snapshot.counts.ownedStagingFiles,
            privateByteMatchCount: snapshot.counts.privateAssetMatchCount, rawEvidence: snapshotEvidence }, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
          const evidence = ref(assertionPath);
          journal.write({ type: 'filesystem_observation', id, boundary, evidence, rawEvidence: snapshotEvidence });
          return evidence;
        },
        admitUploadedFileRead: async (anchor, ack) => {
          assert.equal(anchor.matterId, fixture.matter.id, 'EXACT_UPLOAD_PARENT_REQUIRED');
          const manifest = readRef(assets.manifestEvidence);
          const matches = manifest.assets.filter(asset => asset.sha256 === anchor.sha256 && asset.filename === anchor.filename && asset.sizeBytes === anchor.sizeBytes);
          assert.equal(matches.length, 1, 'EXACT_ACKNOWLEDGED_ASSET_REQUIRED');
          const output = path.join(report, `${scenario.id}-source-admission-${randomUUID().slice(0, 8)}.json`);
          const result = spawnSync('python3', [path.join(root, 'scripts/mobile/admit-ios-file-source.py'),
            '--cache', fixture.filesCache, '--receipt', fixture.isolationEvidence.path, '--manifest', assets.manifestEvidence.path,
            '--manifest-sha256', assets.manifestEvidence.sha256, '--asset-id', matches[0].id,
            '--attachment-id', anchor.attachmentId, '--sha256', anchor.sha256, '--size-bytes', String(anchor.sizeBytes),
            // Two ten-second container inspections plus the helper's bounded
            // 55-second proof. This does not extend the 30-second upload wait.
            '--filename', anchor.filename, '--ack-request-id', ack.requestId, '--output', output], { cwd: root, encoding: 'utf8', timeout: 80000, maxBuffer: 65536 });
          assert.equal(result.status, 0, 'EXACT_UPLOADED_SOURCE_ADMISSION_FAILED');
          const admission = JSON.parse(result.stdout.trim());
          journal.write({ type: 'source_admission', id, ...admission });
          return admission;
        } };
      validateIosFilesContext(context);
      // A prior diagnostic or failed run may have left a system picker open.
      // Cold-start the exact bound app before the first browser/MFA setup.
      if (index === 0) await restart(context);
      await recovery.prepare(context);
      if (!scenario.requiresSignedOut) {
        const fresh = index === 0 || scenario.freshAuthentication === true;
        if (fresh) journal.write({ type: 'authentication_boundary', id, method: 'real-system-browser-pkce-and-mfa' });
        try { await authenticate(context, { fresh }); }
        catch (error) { authFailed = true; throw error; }
      }
      setupPassed = true;
      journal.write({ type: 'phase_result', id, phase: 'setup', status: 'passed' });
    } catch (error) {
      if (sessionRequested && !driver) cleanupUncertain = true;
      journal.write({ type: 'phase_result', id, phase: 'setup', status: error instanceof FixtureUnavailable ? 'blocked' : 'failed', reason: safeFailure(error, 'IOS_FILES_SETUP_FAILED') });
    }
    journal.write({ type: 'phase_started', id, phase: 'call' });
    if (!setupPassed) journal.write({ type: 'phase_result', id, phase: 'call', status: 'not-run', reason: 'SETUP_FAILED' });
    else {
      try { await scenario.run(context); callPassed = true; journal.write({ type: 'phase_result', id, phase: 'call', status: 'passed' }); }
      catch (error) {
        try { journal.write({ type: 'native_call_failure_evidence', id, evidence: await captureIosFilesCallFailure(context, report, id) }); }
        catch (captureError) { journal.write({ type: 'native_call_failure_capture_unavailable', id, reason: safeFailure(captureError, 'NATIVE_FAILURE_CAPTURE_UNAVAILABLE') }); }
        journal.write({ type: 'phase_result', id, phase: 'call', status: error instanceof FixtureUnavailable ? 'blocked' : 'failed', reason: safeFailure(error, 'IOS_FILES_ASSERTION_FAILED') });
      }
    }
    journal.write({ type: 'phase_started', id, phase: 'teardown' });
    try {
      assert.ok(!sessionRequested || driver, 'SESSION_CREATION_CLEANUP_UNCERTAIN');
      if (driver) await driver.deleteSession();
      if (sessionId) journal.write({ ...appiumSessionEvent(sessionId, 'deleted'), id });
      journal.write({ type: 'phase_result', id, phase: 'teardown', status: 'passed' });
      if (setupPassed && callPassed) completedCases.add(scenario.id);
    } catch { cleanupUncertain = true; journal.write({ type: 'phase_result', id, phase: 'teardown', status: 'failed', reason: 'NATIVE_SESSION_CLEANUP_FAILED' }); }
    recovery.observe({ id: scenario.id, setupPassed, callPassed });
  }
  if (preflight) {
    let after;
    // Preserve the actual ledger even when another postflight fence fails.
    try {
      after = await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`);
      writeFileSync(path.join(report, 'gateway-after.json'), `${JSON.stringify(after, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
    } catch { journal.write({ type: 'gateway_capture_failed', reason: 'FILES_POSTFLIGHT_LEDGER_UNAVAILABLE' }); }
    try {
      assert.equal(iosFilesHarnessFingerprint(), frozen, 'HARNESS_CHANGED_DURING_RUN');
      const source = sourceSnapshot(root);
      assert.equal(source.sourceSha, fixture.binarySourceSha, 'SOURCE_COMMIT_CHANGED_DURING_RUN');
      assert.equal(source.sourceFingerprint, fixture.binarySourceFingerprint, 'SOURCE_CHANGED_DURING_RUN');
      assertStrictIosFilesEnvironment(fixture);
      assert.equal(binaryHash(fixture.appPath), artifactHash, 'BINARY_CHANGED_DURING_RUN');
      const installed = execFileSync('xcrun', ['simctl', 'get_app_container', fixture.udid, fixture.appId, 'app'], { encoding: 'utf8', timeout: 10000 }).trim();
      assert.equal(binaryHash(installed), artifactHash, 'INSTALLED_BINARY_CHANGED');
      for (const [url, sha, revision] of [[`${fixture.gatewayUrl}/api/build`, fixture.backendSha, fixture.backendRevision],
        [`${fixture.webGatewayUrl}/api/release-identity`, fixture.webSha, fixture.webRevision]]) {
        const identity = await localJson(url);
        assert.equal(identity.release_sha, sha, 'SERVING_RELEASE_CHANGED');
        assert.equal(identity.revision, revision, 'SERVING_REVISION_CHANGED');
      }
      for (const id of collection.intended) {
        const sessions = journal.events.filter(event => event.type === 'appium_session' && event.id === id);
        assert.deepEqual(sessions.map(event => event.state), ['created', 'deleted'], 'EXACT_FILES_SESSION_LIFECYCLE_REQUIRED');
        assert.equal(sessions[0].sessionId, sessions[1].sessionId, 'FILES_SESSION_CLEANUP_IDENTITY_MISMATCH');
      }
      assert.ok(after, 'FILES_POSTFLIGHT_LEDGER_UNAVAILABLE');
      const verifiedAfter = await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`);
      validateTraffic(verifiedAfter, baseline);
      writeFileSync(path.join(report, 'gateway-after-verification.json'), `${JSON.stringify(verifiedAfter, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
      journal.write({ type: 'postflight_result', status: 'passed', requests: verifiedAfter.lastSequence - baseline.lastSequence });
    } catch (error) { journal.write({ type: 'postflight_result', status: 'failed', reason: safeFailure(error, 'IOS_FILES_POSTFLIGHT_FAILED') }); }
  }
  journal.write({ type: 'run_completed', platform: 'ios', intendedCount: collection.intended.length });
  completed = true; clearTimeout(deadline); process.removeListener('exit', interrupted);
  const result = reconcileResults(journal.events, collection.intended);
  journal.close();
  const summary = { schemaVersion: 1, ...collection, ...result, harnessFingerprint: frozen, evidenceDirectory: report };
  writeFileSync(path.join(report, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
  console.log(JSON.stringify(summary, null, 2));
  if (result.status !== 'passed') process.exitCode = 1;
  return summary;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  assert.ok(process.argv.length === 2 || process.argv.length === 3 && process.argv[2] === '--collect', 'UNKNOWN_IOS_FILES_RUN_ARGUMENT');
  if (process.argv[2] === '--collect') console.log(JSON.stringify(collectIosFiles(), null, 2));
  else await runIosFiles();
}
