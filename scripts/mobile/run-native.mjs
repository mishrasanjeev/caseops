import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { delta, noNotePostRetried, prepareScenario, scenarios, traffic } from '../../apps/mobile/e2e/journeys.mjs';
import { admitApplication, FixtureUnavailable, loadOwnerControls, validateBuildReceipt, validateCoreFixture } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { collect, harnessFingerprint, inventory } from '../../apps/mobile/e2e/suite.mjs';
import { binaryHash, Journal, localJson, localUrl, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { inspectLocalPlan, prepareLocalPlan } from '../../apps/mobile/e2e/local-run.mjs';
import { appiumSessionEvent, authenticationGate, configureNativeDriver, needsFailedCallRecovery, recoverFailedCall } from '../../apps/mobile/e2e/run-state.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const platform = process.argv[2];
assert.ok(inventory.platforms.includes(platform), 'Usage: node scripts/mobile/run-native.mjs android|ios [--collect]');
const mode = process.argv[3];
assert.ok(!mode && process.argv.length === 3 || mode === '--collect' && process.argv.length === 4
  || ['--inspect-local', '--prepare-local'].includes(mode) && process.argv.length === 5, 'UNKNOWN_NATIVE_RUN_ARGUMENT');
const collection = collect(platform);
const { intended } = collection;
if (mode === '--collect') {
  console.log(JSON.stringify(collection, null, 2));
} else if (['--inspect-local', '--prepare-local'].includes(mode)) {
  try {
    assert.ok(path.isAbsolute(process.argv[4]), 'ABSOLUTE_LOCAL_RUN_PLAN_REQUIRED');
    const plan = JSON.parse(readFileSync(process.argv[4], 'utf8'));
    const { readiness } = (mode === '--prepare-local' ? prepareLocalPlan : inspectLocalPlan)(plan, platform);
    console.log(JSON.stringify(readiness, null, 2));
    if (readiness.status !== 'ready-for-native-preflight') process.exitCode = 1;
  } catch (error) {
    console.log(JSON.stringify({ status: 'incomplete', reason: safeFailure(error, 'LOCAL_PREPARATION_FAILED'),
      nativeExecution: 'not-run', servicesChanged: false }));
    process.exitCode = 1;
  }
} else {
  const reportRoot = process.env.CASEOPS_MOBILE_REPORT_ROOT || path.join(os.homedir(), '.cache/caseops-mobile/evidence');
  mkdirSync(reportRoot, { recursive: true });
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${platform}-${randomUUID().slice(0, 8)}`;
  const report = path.join(reportRoot, runId);
  mkdirSync(report);
  const journal = new Journal(path.join(report, 'events.jsonl'));
  let initialSnapshot;
  try { initialSnapshot = sourceSnapshot(root); } catch { initialSnapshot = { sourceIdentity: 'unavailable' }; }
  const deadline = setTimeout(() => {
    journal.write({ type: 'run_interrupted', reason: 'TWENTY_MINUTE_RUN_BOUND' });
    journal.close();
    process.exit(124);
  }, 20 * 60 * 1000);
  deadline.unref();
  const initialHarness = harnessFingerprint();
  journal.write({ type: 'run_started', ...collection, harnessFingerprint: initialHarness, ...initialSnapshot });
  let fixture, owner, remote, appiumUrl, capabilities, selectedBinaryHash, runGatewayBaseline, preflightFailed = false;
  try {
    if (platform === 'ios') assert.equal(process.platform, 'darwin', 'IOS_REQUIRES_OWNER_MACBOOK_XCODE');
    assert.ok(process.env.CASEOPS_MOBILE_FIXTURE, 'ISOLATED_FIXTURE_MISSING');
    fixture = JSON.parse(readFileSync(process.env.CASEOPS_MOBILE_FIXTURE, 'utf8'));
    validateCoreFixture(fixture);
    owner = await loadOwnerControls(fixture);
    assert.equal(fixture.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
    assert.match(fixture.backendSha, /^[0-9a-f]{40}$/, 'EXACT_BACKEND_SHA_REQUIRED');
    assert.match(fixture.binarySourceSha, /^[0-9a-f]{40}$/, 'EXACT_BINARY_SHA_REQUIRED');
    assert.ok(fixture.binaryVersion && fixture.binaryBuild && fixture.deviceName && fixture.platformVersion && fixture.udid && fixture.appId, 'BINARY_DEVICE_METADATA_REQUIRED');
    admitApplication(fixture, platform);
    assert.ok(path.isAbsolute(fixture.appPath), 'ABSOLUTE_NATIVE_BINARY_REQUIRED');
    assert.ok(existsSync(fixture.appPath), 'NATIVE_BINARY_MISSING');
    assert.ok(platform === 'android' ? statSync(fixture.appPath).isFile() && fixture.appPath.endsWith('.apk') : statSync(fixture.appPath).isDirectory() && fixture.appPath.endsWith('.app'), 'INSTALLABLE_NATIVE_BINARY_REQUIRED');
    assert.ok(fixture.principalLabel && fixture.workspaceLabel && fixture.matter?.id, 'NATIVE_AUTH_AND_EXPECTATIONS_REQUIRED');
    assert.equal(fixture.noteRoute, `/api/matters/${fixture.matter.id}/notes`, 'EXACT_NOTE_ROUTE_REQUIRED');
    assert.equal(fixture.matterReloadRoute, `/api/matters/${fixture.matter.id}/workspace`, 'EXACT_WORKSPACE_REREAD_REQUIRED');
    const gatewayUrl = localUrl(fixture.gatewayUrl);
    assert.equal(gatewayUrl.pathname, '/', 'GATEWAY_ORIGIN_REQUIRED');
    assert.equal(gatewayUrl.protocol, 'https:', 'REAL_TLS_API_REQUIRED');
    fixture.gatewayUrl = gatewayUrl.origin;
    const status = await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`);
    assert.equal(status.runId, fixture.gatewayRunId, 'WRONG_GATEWAY_RUN');
    assert.equal(status.overflow, false, 'GATEWAY_EVIDENCE_OVERFLOW');
    const isolation = JSON.parse(verifiedFile(fixture.isolationEvidence.path, fixture.isolationEvidence.sha256));
    runGatewayBaseline = gatewayBaseline(status, isolation);
    const backend = await localJson(`${fixture.gatewayUrl}/api/build`);
    assert.equal(backend.release_sha, fixture.backendSha, 'BACKEND_RELEASE_MISMATCH');
    assert.equal(backend.revision, fixture.backendRevision, 'BACKEND_REVISION_MISMATCH');
    const webGateway = localUrl(fixture.webGatewayUrl);
    assert.equal(webGateway.pathname, '/', 'WEB_GATEWAY_ORIGIN_REQUIRED');
    assert.equal(webGateway.protocol, 'https:', 'REAL_TLS_WEB_REQUIRED');
    fixture.webGatewayUrl = webGateway.origin;
    const web = await localJson(`${fixture.webGatewayUrl}/api/release-identity`);
    assert.equal(web.service, 'web', 'WEB_IDENTITY_REQUIRED');
    assert.equal(web.release_sha, fixture.webSha, 'WEB_RELEASE_MISMATCH');
    assert.equal(web.revision, fixture.webRevision, 'WEB_REVISION_MISMATCH');
    const snapshot = sourceSnapshot(root);
    assert.equal(fixture.binarySourceSha, snapshot.sourceSha, 'BINARY_SOURCE_MISMATCH');
    assert.equal(fixture.binarySourceFingerprint, snapshot.sourceFingerprint, 'BINARY_SOURCE_SNAPSHOT_MISMATCH');
    selectedBinaryHash = binaryHash(fixture.appPath);
    validateBuildReceipt(fixture, platform, selectedBinaryHash);
    const tooling = process.env.CASEOPS_MOBILE_TOOLING_HOME || path.join(os.homedir(), '.cache/caseops-mobile/tooling');
    remote = createRequire(path.join(tooling, 'package.json'))('webdriverio').remote;
    appiumUrl = localUrl(process.env.CASEOPS_MOBILE_APPIUM_URL || 'http://127.0.0.1:4723');
    const appium = await localJson(new URL('status', `${appiumUrl.href.replace(/\/$/, '')}/`).href);
    assert.equal(appium.value.ready, true, 'APPIUM_NOT_READY');
    capabilities = {
      platformName: platform === 'android' ? 'Android' : 'iOS',
      'appium:automationName': platform === 'android' ? 'UiAutomator2' : 'XCUITest',
      'appium:deviceName': fixture.deviceName,
      'appium:platformVersion': fixture.platformVersion,
      'appium:udid': fixture.udid,
      'appium:app': fixture.appPath,
      'appium:noReset': true,
      'appium:enforceAppInstall': true,
      'appium:newCommandTimeout': 60,
      ...(platform === 'android' ? { 'appium:appPackage': fixture.appId,
        'appium:dontStopAppOnReset': true, 'appium:ensureWebviewsHavePages': true,
        'appium:enableWebviewDetailsCollection': true } : { 'appium:bundleId': fixture.appId,
        'appium:includeSafariInWebviews': true, 'appium:webviewConnectTimeout': 20000 }),
    };
    journal.write({ type: 'preflight_result', status: 'passed', environment: fixture.environment, ...snapshot,
      binarySourceSha: fixture.binarySourceSha, binaryVersion: fixture.binaryVersion, binaryBuild: fixture.binaryBuild,
      binaryHash: selectedBinaryHash, binaryHashKind: 'sha256-file-or-canonical-bundle-tree',
      backendSha: backend.release_sha, backendRevision: backend.revision, device: fixture.deviceName,
      webSha: web.release_sha, webRevision: web.revision,
      platformVersion: fixture.platformVersion, gatewayRunId: status.runId,
      harnessFingerprint: initialHarness, browserMode: fixture.auth.mode, ownerCapabilities: owner?.capabilities || [],
      appId: fixture.appId, isolationEvidenceSha256: fixture.isolationEvidence.sha256,
      buildReceiptSha256: fixture.buildReceipt?.sha256 || null, gatewayBaseline: runGatewayBaseline });
  } catch (error) {
    preflightFailed = true;
    journal.write({ type: 'preflight_result', status: 'failed', reason: safeFailure(error, 'NATIVE_PREREQUISITE_MISSING_OR_MISMATCHED') });
  }
  const completedCases = new Set();
  const authGate = authenticationGate((event) => journal.write(event));
  let previousCase;
  for (const scenario of scenarios) {
    const id = `${platform}:${scenario.id}`;
    let driver, context, ownedSessionId, setupPassed = false, callPassed = false, callFailed = false, teardownPassed = false;
    journal.write({ type: 'phase_started', id, phase: 'setup' });
    try {
      assert.equal(preflightFailed, false, 'PREFLIGHT_FAILED');
      authGate.assertSetup();
      if (previousCase?.cleanupUncertain) throw new FixtureUnavailable('PREVIOUS_NATIVE_SESSION_CLEANUP_UNCERTAIN');
      assert.notEqual(owner?.poisoned, true, 'OWNER_CONTROL_PREVIOUSLY_UNCERTAIN');
      for (const capability of inventory.cases.find((item) => item.id === scenario.id).ownerCapabilities || []) {
        if (!owner?.capabilities.includes(capability)) throw new FixtureUnavailable('FIXTURE_OWNER_CAPABILITY_UNAVAILABLE');
      }
      driver = await remote({ hostname: appiumUrl.hostname, port: Number(appiumUrl.port) || 4723,
        protocol: appiumUrl.protocol.slice(0, -1), path: appiumUrl.pathname, capabilities,
        logLevel: 'silent', connectionRetryCount: 0, connectionRetryTimeout: 60000 });
      assert.ok(driver.sessionId, 'NATIVE_SESSION_MISSING');
      const sessionCreated = appiumSessionEvent(driver.sessionId, 'created');
      ownedSessionId = sessionCreated.sessionId;
      journal.write({ ...sessionCreated, id });
      await configureNativeDriver(driver, platform, (event) => journal.write({ ...event, id }));
      const contexts = await driver.getContexts();
      assert.ok(contexts.includes('NATIVE_APP'), 'NATIVE_CONTEXT_REQUIRED');
      await driver.switchContext('NATIVE_APP');
      context = { driver, fixture, platform, owner, runId, gatewayBaseline: runGatewayBaseline,
        record: (event) => journal.write({ ...event, id }), noteText: `CaseOps native QA ${runId} ${scenario.id}` };
      const recoveryBaseline = needsFailedCallRecovery(scenario, previousCase) ? await traffic(context) : undefined;
      await recoverFailedCall(context, scenario, previousCase);
      await prepareScenario(context, scenario, completedCases);
      if (recoveryBaseline) noNotePostRetried(delta(recoveryBaseline, await traffic(context)));
      setupPassed = true;
      journal.write({ type: 'phase_result', id, phase: 'setup', status: 'passed' });
    } catch (error) {
      if (!preflightFailed) authGate.failInitial(scenario, 'setup');
      journal.write({ type: 'phase_result', id, phase: 'setup', status: error instanceof FixtureUnavailable ? 'blocked' : 'failed',
        reason: safeFailure(error, 'NATIVE_SESSION_OR_AUTH_FAILED') });
    }
    journal.write({ type: 'phase_started', id, phase: 'call' });
    if (!setupPassed) journal.write({ type: 'phase_result', id, phase: 'call', status: 'not-run', reason: 'SETUP_FAILED' });
    else {
      try {
        await scenario.run(context);
        callPassed = true;
        journal.write({ type: 'phase_result', id, phase: 'call', status: 'passed' });
      } catch (error) {
        callFailed = !(error instanceof FixtureUnavailable);
        authGate.failInitial(scenario, 'call');
        journal.write({ type: 'phase_result', id, phase: 'call', status: error instanceof FixtureUnavailable ? 'blocked' : 'failed',
          reason: safeFailure(error, 'NATIVE_ASSERTION_FAILED') });
      }
    }
    journal.write({ type: 'phase_started', id, phase: 'teardown' });
    try {
      if (driver) await driver.deleteSession();
      if (ownedSessionId) journal.write({ ...appiumSessionEvent(ownedSessionId, 'deleted'), id });
      teardownPassed = true;
      journal.write({ type: 'phase_result', id, phase: 'teardown', status: 'passed' });
      if (setupPassed && callPassed) completedCases.add(scenario.id);
    } catch {
      if (ownedSessionId) journal.write({ ...appiumSessionEvent(ownedSessionId, 'cleanup-failed'), id });
      journal.write({ type: 'phase_result', id, phase: 'teardown', status: 'failed', reason: 'NATIVE_SESSION_CLEANUP_FAILED' });
    }
    previousCase = { id: scenario.id, failedCall: callFailed,
      cleanupUncertain: previousCase?.cleanupUncertain || !!driver && !teardownPassed };
  }
  if (!preflightFailed) {
    try {
      assert.equal(sourceSnapshot(root).sourceFingerprint, fixture.binarySourceFingerprint, 'SOURCE_CHANGED_DURING_RUN');
      assert.equal(harnessFingerprint(), initialHarness, 'HARNESS_CHANGED_DURING_RUN');
      assert.equal(binaryHash(fixture.appPath), selectedBinaryHash, 'BINARY_CHANGED_DURING_RUN');
      assert.notEqual(owner?.poisoned, true, 'OWNER_CONTROL_PREVIOUSLY_UNCERTAIN');
      const backend = await localJson(`${fixture.gatewayUrl}/api/build`);
      assert.equal(backend.release_sha, fixture.backendSha, 'BACKEND_RELEASE_CHANGED');
      assert.equal(backend.revision, fixture.backendRevision, 'BACKEND_REVISION_CHANGED');
      const web = await localJson(`${fixture.webGatewayUrl}/api/release-identity`);
      assert.equal(web.release_sha, fixture.webSha, 'WEB_RELEASE_CHANGED');
      assert.equal(web.revision, fixture.webRevision, 'WEB_REVISION_CHANGED');
      validateTraffic(await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`), runGatewayBaseline);
      journal.write({ type: 'postflight_result', status: 'passed' });
    } catch (error) {
      journal.write({ type: 'postflight_result', status: 'failed', reason: safeFailure(error, 'SOURCE_RECHECK_FAILED') });
    }
  }
  journal.write({ type: 'run_completed', platform, intendedCount: intended.length });
  const result = reconcileResults(journal.events, intended);
  clearTimeout(deadline);
  journal.close();
  const summary = { schemaVersion: 2, ...collection, harnessFingerprint: initialHarness, ...result, evidenceDirectory: report };
  writeFileSync(path.join(report, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`, { flag: 'wx' });
  console.log(JSON.stringify(summary, null, 2));
  if (result.status !== 'passed') process.exitCode = 1;
}
