import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { authenticate, scenarios } from '../../apps/mobile/e2e/core.mjs';
import { binaryHash, Journal, localJson, localUrl, reconcileInventory, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const inventory = JSON.parse(readFileSync(new URL('../../apps/mobile/e2e/inventory.json', import.meta.url), 'utf8'));
const platform = process.argv[2];
assert.ok(inventory.platforms.includes(platform), 'Usage: node scripts/mobile/run-native.mjs android|ios [--collect]');
const intended = inventory.cases.map((item) => `${platform}:${item.id}`);
reconcileInventory(intended, scenarios.map((item) => `${platform}:${item.id}`));
if (process.argv[3] === '--collect') {
  console.log(JSON.stringify({ platform, scope: inventory.scope, intended, discovered: intended }, null, 2));
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
  journal.write({ type: 'run_started', platform, intended, discovered: intended, scope: inventory.scope, ...initialSnapshot });
  let fixture, remote, appiumUrl, capabilities, preflightFailed = false;
  try {
    if (platform === 'ios') assert.equal(process.platform, 'darwin', 'IOS_REQUIRES_OWNER_MACBOOK_XCODE');
    assert.ok(process.env.CASEOPS_MOBILE_FIXTURE, 'ISOLATED_FIXTURE_MISSING');
    fixture = JSON.parse(readFileSync(process.env.CASEOPS_MOBILE_FIXTURE, 'utf8'));
    assert.ok(['deterministic-simulator', 'docker-integration'].includes(fixture.environment), 'ISOLATED_BACKEND_REQUIRED');
    assert.equal(fixture.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
    assert.match(fixture.backendSha, /^[0-9a-f]{40}$/, 'EXACT_BACKEND_SHA_REQUIRED');
    assert.match(fixture.binarySourceSha, /^[0-9a-f]{40}$/, 'EXACT_BINARY_SHA_REQUIRED');
    assert.ok(fixture.binaryVersion && fixture.binaryBuild && fixture.deviceName && fixture.platformVersion && fixture.udid && fixture.appId, 'BINARY_DEVICE_METADATA_REQUIRED');
    assert.equal(fixture.appId, 'ai.caseops.mobile.dev', 'DEDICATED_DEV_APP_REQUIRED');
    assert.ok(path.isAbsolute(fixture.appPath), 'ABSOLUTE_NATIVE_BINARY_REQUIRED');
    assert.ok(existsSync(fixture.appPath), 'NATIVE_BINARY_MISSING');
    assert.ok(platform === 'android' ? statSync(fixture.appPath).isFile() && fixture.appPath.endsWith('.apk') : statSync(fixture.appPath).isDirectory() && fixture.appPath.endsWith('.app'), 'INSTALLABLE_NATIVE_BINARY_REQUIRED');
    assert.ok(fixture.ids && fixture.ids.screens && fixture.principalLabel && fixture.workspaceLabel && fixture.matter?.id, 'NATIVE_AUTH_AND_EXPECTATIONS_REQUIRED');
    for (const id of ['principal', 'workspace', 'accountClose', 'matterIdentity', 'savedNote', 'signedOut', 'searchSubmit', 'noteAcknowledgement', 'noteReturn']) {
      assert.ok(typeof fixture.ids[id] === 'string' && fixture.ids[id].length > 0, 'NATIVE_TEST_IDS_REQUIRED');
    }
    for (const screen of ['today', 'matters', 'calendar', 'work']) assert.ok(fixture.ids.screens[screen], 'NATIVE_SCREEN_IDS_REQUIRED');
    assert.equal(fixture.noteRoute, `/api/matters/${fixture.matter.id}/notes`, 'EXACT_NOTE_ROUTE_REQUIRED');
    assert.equal(fixture.matterReloadRoute, `/api/matters/${fixture.matter.id}/workspace`, 'EXACT_WORKSPACE_REREAD_REQUIRED');
    const gatewayUrl = localUrl(fixture.gatewayUrl);
    assert.equal(gatewayUrl.pathname, '/', 'GATEWAY_ORIGIN_REQUIRED');
    fixture.gatewayUrl = gatewayUrl.origin;
    const status = await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`);
    assert.equal(status.runId, fixture.gatewayRunId, 'WRONG_GATEWAY_RUN');
    assert.equal(status.overflow, false, 'GATEWAY_EVIDENCE_OVERFLOW');
    const backend = await localJson(`${fixture.gatewayUrl}/api/build`);
    assert.equal(backend.release_sha, fixture.backendSha, 'BACKEND_RELEASE_MISMATCH');
    assert.equal(backend.revision, fixture.backendRevision, 'BACKEND_REVISION_MISMATCH');
    const snapshot = sourceSnapshot(root);
    assert.equal(fixture.binarySourceSha, snapshot.sourceSha, 'BINARY_SOURCE_MISMATCH');
    assert.equal(fixture.binarySourceFingerprint, snapshot.sourceFingerprint, 'BINARY_SOURCE_SNAPSHOT_MISMATCH');
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
      'appium:newCommandTimeout': 60,
      ...(platform === 'android' ? { 'appium:appPackage': fixture.appId, 'appium:disableIdLocatorAutocompletion': true } : { 'appium:bundleId': fixture.appId }),
    };
    journal.write({ type: 'preflight_result', status: 'passed', environment: fixture.environment, ...snapshot,
      binarySourceSha: fixture.binarySourceSha, binaryVersion: fixture.binaryVersion, binaryBuild: fixture.binaryBuild,
      binaryHash: binaryHash(fixture.appPath), binaryHashKind: 'sha256-file-or-canonical-bundle-tree',
      backendSha: backend.release_sha, backendRevision: backend.revision, device: fixture.deviceName,
      platformVersion: fixture.platformVersion, gatewayRunId: status.runId });
  } catch (error) {
    preflightFailed = true;
    journal.write({ type: 'preflight_result', status: 'failed', reason: safeFailure(error, 'NATIVE_PREREQUISITE_MISSING_OR_MISMATCHED') });
  }
  for (const scenario of scenarios) {
    const id = `${platform}:${scenario.id}`;
    let driver, context, setupPassed = false;
    journal.write({ type: 'phase_started', id, phase: 'setup' });
    try {
      assert.equal(preflightFailed, false, 'PREFLIGHT_FAILED');
      driver = await remote({ hostname: appiumUrl.hostname, port: Number(appiumUrl.port) || 4723,
        protocol: appiumUrl.protocol.slice(0, -1), path: appiumUrl.pathname, capabilities,
        logLevel: 'silent', connectionRetryCount: 0, connectionRetryTimeout: 60000 });
      assert.ok(driver.sessionId, 'NATIVE_SESSION_MISSING');
      const contexts = await driver.getContexts();
      assert.ok(contexts.includes('NATIVE_APP'), 'NATIVE_CONTEXT_REQUIRED');
      await driver.switchContext('NATIVE_APP');
      context = { driver, fixture, platform, noteText: `CaseOps native QA ${runId}` };
      await authenticate(context);
      setupPassed = true;
      journal.write({ type: 'phase_result', id, phase: 'setup', status: 'passed' });
    } catch (error) {
      journal.write({ type: 'phase_result', id, phase: 'setup', status: 'failed', reason: safeFailure(error, 'NATIVE_SESSION_OR_AUTH_FAILED') });
    }
    journal.write({ type: 'phase_started', id, phase: 'call' });
    if (!setupPassed) journal.write({ type: 'phase_result', id, phase: 'call', status: 'not-run', reason: 'SETUP_FAILED' });
    else {
      try {
        await scenario.run(context);
        journal.write({ type: 'phase_result', id, phase: 'call', status: 'passed' });
      } catch (error) {
        journal.write({ type: 'phase_result', id, phase: 'call', status: 'failed', reason: safeFailure(error, 'NATIVE_ASSERTION_FAILED') });
      }
    }
    journal.write({ type: 'phase_started', id, phase: 'teardown' });
    try {
      if (driver) await driver.deleteSession();
      journal.write({ type: 'phase_result', id, phase: 'teardown', status: 'passed' });
    } catch {
      journal.write({ type: 'phase_result', id, phase: 'teardown', status: 'failed', reason: 'NATIVE_SESSION_CLEANUP_FAILED' });
    }
  }
  if (!preflightFailed) {
    try {
      assert.equal(sourceSnapshot(root).sourceFingerprint, fixture.binarySourceFingerprint, 'SOURCE_CHANGED_DURING_RUN');
      journal.write({ type: 'postflight_result', status: 'passed' });
    } catch (error) {
      journal.write({ type: 'postflight_result', status: 'failed', reason: safeFailure(error, 'SOURCE_RECHECK_FAILED') });
    }
  }
  journal.write({ type: 'run_completed', platform, intendedCount: intended.length });
  const result = reconcileResults(journal.events, intended);
  clearTimeout(deadline);
  journal.close();
  const summary = { schemaVersion: 1, platform, scope: inventory.scope, ...result, evidenceDirectory: report };
  writeFileSync(path.join(report, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`, { flag: 'wx' });
  console.log(JSON.stringify(summary, null, 2));
  if (result.status !== 'passed') process.exitCode = 1;
}
