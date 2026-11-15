// Verification fixture only: evaluate the actual six runner option expressions,
// without importing a runner or creating an SDK/device/backend session.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { MARKER, MARKER_HEADER } from '../../../apps/mobile/e2e/support.mjs';
import { V1_BUDGETS } from '../../../apps/mobile/e2e/v1-workflows-inventory.mjs';
import { IOS_FILE_FACT_RESPONSE_ATTRIBUTES } from '../../../apps/mobile/e2e/ios-files.mjs';

const ROOT = fileURLToPath(new URL('../../../', import.meta.url));
const ts = createRequire(path.join(ROOT, 'apps/mobile/package.json'))('typescript');
export const NATIVE_WEBDRIVER_SITES = Object.freeze([
  { file: 'run-native.mjs', family: 'Core', platforms: ['android', 'ios'], timeout: 60000 },
  { file: 'run-android-files.mjs', family: 'Files', platforms: ['android'], timeout: 60000 },
  { file: 'run-ios-files.mjs', family: 'Files', platforms: ['ios'], timeout: 60000 },
  { file: 'run-queue-privacy.mjs', family: 'Queue/privacy', platforms: ['android', 'ios'], timeout: 60000 },
  { file: 'run-client-extensions.mjs', family: 'Client extensions', platforms: ['android', 'ios'], timeout: 10000 },
  { file: 'run-v1-workflows.mjs', family: 'V1', platforms: ['android', 'ios'], timeout: V1_BUDGETS.transportMs },
]);

export function constructorCalls(source, file) {
  assert.equal(typeof source, 'string'); assert.ok(Buffer.byteLength(source) <= 1048576);
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  assert.equal(tree.parseDiagnostics.length, 0, 'ACTUAL_RUNNER_MUST_PARSE');
  const calls = [];
  const visit = node => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'remote') {
      assert.equal(node.arguments.length, 1, 'EXACT_NATIVE_REMOTE_ARGUMENT_REQUIRED');
      assert.ok(ts.isObjectLiteralExpression(node.arguments[0]), 'ACTUAL_NATIVE_OPTIONS_OBJECT_REQUIRED');
      calls.push({ expression: node.arguments[0].getText(tree), line: tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1 });
    }
    ts.forEachChild(node, visit);
  };
  visit(tree); return calls;
}

export function nativeConstructorInventory() {
  const directory = path.join(ROOT, 'scripts/mobile'), found = [];
  for (const file of readdirSync(directory).filter(name => /^run-.*\.mjs$/.test(name)).sort()) {
    for (const call of constructorCalls(readFileSync(path.join(directory, file), 'utf8'), file)) found.push({ file, ...call });
  }
  assert.deepEqual(found.map(({ file }) => file).sort(), NATIVE_WEBDRIVER_SITES.map(({ file }) => file).sort(),
    'COMPLETE_SIX_NATIVE_CONSTRUCTOR_INVENTORY_REQUIRED');
  return found;
}

export function nativeConstructorOptions(site, platform, endpoint) {
  assert.ok(NATIVE_WEBDRIVER_SITES.includes(site) && site.platforms.includes(platform));
  const destination = new URL(endpoint);
  assert.ok(destination.protocol === 'http:' && destination.hostname === '127.0.0.1' && Number(destination.port) >= 1024
    && destination.pathname === '/' && !destination.search && !destination.hash && !destination.username && !destination.password,
  'OWNED_LOOPBACK_WEBDRIVER_PEER_REQUIRED');
  const source = readFileSync(path.join(ROOT, 'scripts/mobile', site.file), 'utf8');
  const calls = constructorCalls(source, site.file); assert.equal(calls.length, 1);
  const fixture = { deviceName: 'owned-transport-fixture', platformVersion: platform === 'ios' ? '26' : '16',
    udid: 'owned-transport-fixture', appId: platform === 'ios' ? 'ai.caseops.mobile.localqa' : 'ai.caseops.mobile.dev.localacceptance' };
  const capabilities = { platformName: platform === 'ios' ? 'iOS' : 'Android',
    'appium:automationName': platform === 'ios' ? 'XCUITest' : 'UiAutomator2',
    'appium:udid': fixture.udid, 'appium:noReset': true, 'caseops:sourceWitness': 'retained' };
  const transportCapabilities = platform === 'android' ? { 'appium:adbPort': 5038, 'appium:systemPort': 8202 }
    : { 'appium:wdaLocalPort': 8101 };
  const context = { MARKER, MARKER_HEADER, URL, Number, appiumUrl: destination, appium: destination, url: destination,
    capabilities, fixture, f: fixture, q: { platform }, transport: { appiumUrl: destination, capabilities: transportCapabilities },
    V1_BUDGETS, IOS_FILE_FACT_RESPONSE_ATTRIBUTES };
  const options = runInNewContext(`(${calls[0].expression})`, context, { timeout: 1000 });
  assert.equal(options.hostname, '127.0.0.1'); assert.equal(options.port, Number(destination.port));
  assert.equal(options.protocol, 'http'); assert.equal(options.path, '/');
  return { options, fixture, capabilities, transportCapabilities, source, expression: calls[0].expression };
}
