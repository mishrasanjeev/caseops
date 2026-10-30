import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createHash, X509Certificate } from 'node:crypto';
import { execFileSync, spawn } from 'node:child_process';
import http from 'node:http';
import https from 'node:https';
import fs from 'node:fs';
import tls from 'node:tls';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';
import { binaryHash, byTestId, Journal, localJson, localUrl, MARKER, MARKER_HEADER, reconcileInventory, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { scenarios } from '../../apps/mobile/e2e/core.mjs';
import { createGateway } from './no-paid-gateway.mjs';
import { authenticate, authorizationIdentity, browserLogin, browserOrigin, loginCredentials } from '../../apps/mobile/e2e/browser-handoff.mjs';
import { resolveFirefoxEntry, validateFirefoxRecipe } from '../../apps/mobile/e2e/firefox-handoff.mjs';
import { CONSENT_MFA_VERIFIED, fixtureMfaCode, mfaStage, totp, validateAuthorizationTraffic } from '../../apps/mobile/e2e/mfa.mjs';
import { admitApplication, FixtureUnavailable, ownerControl, SEARCH_KINDS, validateBuildReceipt, validateCoreFixture, verifiedFile } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { delta, discard, noNotePostRetried, prepareScenario, readOnlyTraffic, scenarios as datedScenarios, selectMatterActivity, signedOutResumeTraffic, verifySavedNote } from '../../apps/mobile/e2e/journeys.mjs';
import { backgroundAndResume, click, find, input, nativeAction, read, selector, visible } from '../../apps/mobile/e2e/native-ui.mjs';
import { collect, harnessFingerprint, inventory as datedInventory, receiptInventory } from '../../apps/mobile/e2e/suite.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { androidSessionTransport, inspectLocalPlan, prepareLocalPlan, validateAndroidTransport, verifyAndroidSessionTransport } from '../../apps/mobile/e2e/local-run.mjs';
import { configuredSessionDeleteAdmission, MAX_SESSION_ADMISSION_EVENTS, proveCurrentSessionDeletion } from '../../apps/mobile/e2e/session-admission.mjs';
import { browserStep } from '../../apps/mobile/e2e/browser-progress.mjs';
import { appiumSessionEvent, authenticationGate, configureNativeDriver, needsFailedCallRecovery, recoverFailedCall } from '../../apps/mobile/e2e/run-state.mjs';
import { attestAndroidBinary } from '../../apps/mobile/e2e/installed-android.mjs';
import { prepareHostNodeTrust, reviewHostNodeRoots, reviewHostNodeBuildConfiguration, reviewHostNodeWindowsAclProof, reviewHostNodeWindowsAclPhase, DENIED_HOST_CA } from './host-node-trust.mjs';
import { localCertificates } from './host-node-trust-fixture.mjs';
import { readIosHostInput, referenceIosHostInput, neutralIosEnvironment, composeIosHostCommand, validateIosHostArguments, reviewIosPodBuildPaths, validatePodsCurlArguments, validateIosCurlArguments, projectIosGitArguments, admitIosGitRepository, iosHostCommandProjection, IOS_PODS_SOURCE_SHA256, runIosSimulatorBuild, runIosLocalQaCommand, openIosCurlTransport, reviewIosHostHome, reviewProjectNpm, renderIosHostBuildEntry, validateIosReadonlyGitArguments } from './ios-host-launch.mjs';

const installedHash = 'a'.repeat(64);
const installedPath = '/data/app/~~owned==/ai.caseops.mobile.dev-test==/base.apk';
const installedFixture = { appId: 'ai.caseops.mobile.dev', udid: 'emulator-5580', appPath: path.resolve('acceptance.apk') };
// Model the raw protocol endpoint separately from element lookup/refetch. The
// existing state-machine callbacks are the synthetic endpoint's server effects.
function nativeProtocolDouble(driver) {
  const query = driver.$$.bind(driver), callbacks = new Map();
  let sequence = 0;
  driver.$$ = async (...args) => {
    const matches = await query(...args);
    for (const element of matches) if (typeof element.click === 'function') {
      element.elementId ??= `unit-native-${++sequence}`;
      callbacks.set(element.elementId, element.click.bind(element));
    }
    return matches;
  };
  driver.elementClick = async id => {
    assert.ok(callbacks.has(id), 'UNIT_RESOLVED_NATIVE_ID_REQUIRED');
    await callbacks.get(id)();
  };
  return driver;
}

test('scoped native Activity tap preserves a lost or stale acknowledgement without refinding or replaying', async () => {
  for (const message of ['stale element reference', 'native click acknowledgement lost']) {
    const failure = new Error(message), events = [], dispatches = [];
    let scopeReads = 0, buttonReads = 0, fallbackClicks = 0;
    const button = { elementId: 'resolved-activity-original', isDisplayed: async () => true, isEnabled: async () => true,
      getAttribute: async key => ({ type: 'XCUIElementTypeButton', label: 'Activity' })[key],
      click: async () => { fallbackClicks++; } };
    const picker = { isDisplayed: async () => true,
      getAttribute: async key => ({ type: 'XCUIElementTypeSegmentedControl', label: 'Matter view' })[key],
      $$: async query => { buttonReads++; assert.equal(buttonReads, 1); assert.match(query, /label == "Activity"/); return [button]; } };
    const context = { platform: 'ios', record: event => events.push(event), driver: {
      waitUntil: async callback => assert.ok(await callback()),
      $$: async query => { scopeReads++; assert.equal(scopeReads, 1); assert.match(query, /label == "Matter view"/); return [picker]; },
      elementClick: async id => { dispatches.push(id); throw failure; },
    } };
    await assert.rejects(selectMatterActivity(context), error => error === failure);
    assert.deepEqual(dispatches, ['resolved-activity-original']);
    assert.deepEqual({ scopeReads, buttonReads, fallbackClicks }, { scopeReads: 1, buttonReads: 1, fallbackClicks: 0 });
    assert.deepEqual(events.filter(({ action }) => action === 'click'), [{ type: 'native_ui_action', action: 'click' }]);
  }
});

function androidCommandDouble({ install = 'Performing Streamed Install\nSuccess', paths = `package:${installedPath}`,
  digest = `${installedHash}  ${installedPath}`, initialDigest = digest, initialPaths = paths } = {}) {
  const calls = [];
  let replaced = false;
  return { calls, command: (binary, args, options) => {
    assert.equal(binary, 'adb'); assert.deepEqual(args.slice(0, 2), ['-s', 'emulator-5580']);
    assert.equal(options.shell, false); assert.equal(options.windowsHide, true); assert.ok(options.timeout <= 120000);
    calls.push(args.slice(2));
    if (args[2] === 'install') { replaced = true; return install; }
    if (args[3] === 'pm' && args[4] === 'list') return (replaced ? paths : initialPaths) ? `package:${installedFixture.appId}` : '';
    return args[3] === 'pm' ? replaced ? paths : initialPaths : replaced ? digest : initialDigest;
  } };
}
test('Android preflight explicitly replaces the APK without clearing data and attests installed bytes', () => {
  const stub = androidCommandDouble({ initialDigest: `${'b'.repeat(64)}  ${installedPath}` });
  const proof = attestAndroidBinary(installedFixture, installedHash, { ...stub, install: true });
  assert.equal(proof.explicitReplaceInstall, true); assert.equal(proof.appDataCleared, false);
  assert.deepEqual(stub.calls, [['shell', 'pm', 'list', 'packages', installedFixture.appId], ['shell', 'pm', 'path', installedFixture.appId], ['shell', 'sha256sum', installedPath],
    ['install', '-r', installedFixture.appPath], ['shell', 'pm', 'list', 'packages', installedFixture.appId], ['shell', 'pm', 'path', installedFixture.appId], ['shell', 'sha256sum', installedPath]]);
});
test('Android per-case and final attestations never reinstall or clear session data', () => {
  const stub = androidCommandDouble();
  assert.equal(attestAndroidBinary(installedFixture, installedHash, stub).explicitReplaceInstall, false);
  assert.equal(stub.calls.length, 3); assert.ok(stub.calls.every(args => args[0] === 'shell'));
});
test('Android stale same-version installed APK cannot pass a source-bound run', () => {
  const stub = androidCommandDouble({ digest: `${'b'.repeat(64)}  ${installedPath}` });
  assert.throws(() => attestAndroidBinary(installedFixture, installedHash, stub), /INSTALLED_ANDROID_APK_HASH_MISMATCH/);
});
test('Android failed install cannot fall through to an older installed APK', () => {
  const stub = androidCommandDouble({ install: 'Failure [INSTALL_FAILED]', initialDigest: `${'b'.repeat(64)}  ${installedPath}` });
  assert.throws(() => attestAndroidBinary(installedFixture, installedHash, { ...stub, install: true }), /EXACT_ANDROID_APK_INSTALL_FAILED/);
  assert.equal(stub.calls.length, 4);
});

test('Android preflight reuses only byte-identical installed APKs without a redundant replacement', () => {
  const stub = androidCommandDouble();
  const proof = attestAndroidBinary(installedFixture, installedHash, { ...stub, install: true });
  assert.equal(proof.installedApkSha256, installedHash);
  assert.equal(proof.explicitReplaceInstall, false);
  assert.deepEqual(stub.calls, [['shell', 'pm', 'list', 'packages', installedFixture.appId], ['shell', 'pm', 'path', installedFixture.appId], ['shell', 'sha256sum', installedPath]]);
});

test('Android missing owned APK installs once and verifies the actual resulting bytes', () => {
  const stub = androidCommandDouble({ initialPaths: '' });
  assert.equal(attestAndroidBinary(installedFixture, installedHash, { ...stub, install: true }).explicitReplaceInstall, true);
  assert.equal(stub.calls.filter(args => args[0] === 'install').length, 1);
  assert.equal(stub.calls.length, 5);
});

test('Android package-manager errors are not reinterpreted as an absent package or authorized install', () => {
  const calls = [];
  const error = Object.assign(new Error('UNIT_PACKAGE_MANAGER_FAILURE'), { status: 1, stdout: '', stderr: '' });
  assert.throws(() => attestAndroidBinary(installedFixture, installedHash, { install: true,
    command: (_binary, args) => { calls.push(args); throw error; } }), /UNIT_PACKAGE_MANAGER_FAILURE/);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].slice(2), ['shell', 'pm', 'list', 'packages', installedFixture.appId]);
});

test('Android malformed digest output cannot authorize either reuse or an install', () => {
  for (const digest of [installedHash, `${installedHash}  /another/base.apk`, `invalid  ${installedPath}`]) {
    const stub = androidCommandDouble({ digest });
    assert.throws(() => attestAndroidBinary(installedFixture, installedHash, { ...stub, install: true }), /EXACT_INSTALLED_APK_DIGEST_REQUIRED/);
    assert.equal(stub.calls.some(args => args[0] === 'install'), false);
  }
});
test('Android split APK and unsafe package paths fail closed', () => {
  for (const paths of [`package:${installedPath}\npackage:/data/app/split.apk`, 'package:/data/app/../base.apk', 'package:/sdcard/base.apk'])
    assert.throws(() => attestAndroidBinary(installedFixture, installedHash, androidCommandDouble({ paths })));
});
test('Android install rejects non-owned application and ambiguous device identity before any command', () => {
  for (const fixture of [{ ...installedFixture, appId: 'another.app' }, { ...installedFixture, udid: '-s other-device' }])
    assert.throws(() => attestAndroidBinary(fixture, installedHash, { command: () => assert.fail('must not execute') }));
});
test('canonical Android runner attests device bytes before preflight success, every case and postflight success', () => {
  const runner = readFileSync(new URL('./run-native.mjs', import.meta.url), 'utf8');
  assert.equal((runner.match(/attestAndroidBinary\(fixture, selectedBinaryHash/g) || []).length, 3);
  assert.ok(runner.indexOf('{ install: true }') < runner.indexOf("type: 'preflight_result', status: 'passed'"));
});

const inventory = JSON.parse(readFileSync(new URL('../../apps/mobile/e2e/inventory.json', import.meta.url), 'utf8'));
test('core discovered inventory exactly matches canonical identities on both platforms', () => {
  for (const platform of inventory.platforms) reconcileInventory(
    inventory.cases.map((item) => `${platform}:${item.id}`), scenarios.map((item) => `${platform}:${item.id}`));
  assert.ok(inventory.cases.findIndex((item) => item.id === 'CORE-06') < inventory.cases.findIndex((item) => item.id === 'CORE-05'), 'EVIDENCE_BEFORE_LOGOUT');
});
test('missing, reordered, duplicate and empty inventories fail closed', () => {
  for (const [wanted, actual] of [[['A', 'B'], ['A']], [['A', 'B'], ['B', 'A']], [['A', 'A'], ['A', 'A']], [[], []]]) {
    assert.throws(() => reconcileInventory(wanted, actual));
  }
});
test('loopback fence rejects external origins, credentials and query-bearing origins', () => {
  for (const url of ['https://caseops.ai', 'http://127.0.0.1.evil.test', 'http://user:secret@127.0.0.1', 'file:///tmp/a', 'http://127.0.0.1?x=y']) {
    assert.throws(() => localUrl(url));
  }
  assert.equal(localUrl('http://127.0.0.1:8191').port, '8191');
});
function events(status = 'passed') {
  return [
    { type: 'run_started', intended: ['android:A'], discovered: ['android:A'] },
    { type: 'preflight_result', status: 'passed' },
    ...['setup', 'call', 'teardown'].flatMap((phase) => [
      { type: 'phase_started', id: 'android:A', phase },
      { type: 'phase_result', id: 'android:A', phase, status },
    ]),
    { type: 'postflight_result', status: 'passed' },
    { type: 'run_completed' },
  ];
}
test('complete passing phases reconcile; failures never become a pass', () => {
  assert.equal(reconcileResults(events(), ['android:A']).status, 'passed');
  assert.equal(reconcileResults(events('failed'), ['android:A']).failedPhases, 3);
});
test('an interrupted journal is incomplete even when all recorded phases pass', () => {
  assert.throws(() => reconcileResults(events().slice(0, -1), ['android:A']), /COMPLETION/);
});
test('missing phase, duplicate phase, unknown phase and post-completion data reject', () => {
  const rows = events();
  for (const altered of [rows.filter((row) => row.phase !== 'teardown'), [...rows.slice(0, -1), rows[3], rows.at(-1)],
    [...rows.slice(0, -1), { type: 'phase_result', id: 'android:B', phase: 'call', status: 'passed' }, rows.at(-1)],
    [...rows, { type: 'extra' }]]) {
    assert.throws(() => reconcileResults(altered, ['android:A']));
  }
});
test('not-run call is explicit incomplete evidence, not a skip/pass', () => {
  const rows = events();
  rows.find((row) => row.type === 'phase_result' && row.phase === 'call').status = 'not-run';
  const result = reconcileResults(rows, ['android:A']);
  assert.equal(result.unexecutedCalls, 1);
  assert.equal(result.status, 'incomplete-or-failed');
});
test('phase results cannot precede their started event', () => {
  const rows = events();
  [rows[2], rows[3]] = [rows[3], rows[2]];
  assert.throws(() => reconcileResults(rows, ['android:A']), /BEFORE_START/);
});
test('failed or absent source postflight cannot be certified by passing calls', () => {
  const rows = events();
  rows.find((row) => row.type === 'postflight_result').status = 'failed';
  assert.equal(reconcileResults(rows, ['android:A']).status, 'incomplete-or-failed');
  assert.throws(() => reconcileResults(rows.filter((row) => row.type !== 'postflight_result'), ['android:A']), /POSTFLIGHT/);
});
test('journal is durably readable before completion and refuses overwrite', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'co-mobile-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'events.jsonl');
  const journal = new Journal(file);
  journal.write({ type: 'phase_started', id: 'android:A', phase: 'setup' });
  assert.equal(JSON.parse(readFileSync(file, 'utf8')).phase, 'setup');
  assert.throws(() => new Journal(file), /EEXIST/);
  journal.close();
});
test('APK hash is the actual file SHA-256', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'co-mobile-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'synthetic.apk');
  writeFileSync(file, 'hash test only, not a native binary');
  assert.equal(binaryHash(file), createHash('sha256').update(readFileSync(file)).digest('hex'));
});
test('testID uses React Native Android resource id and iOS accessibility id', async () => {
  for (const [platform, expected] of [['android', 'id=note-save'], ['ios', '~note-save']]) {
    const driver = { $: async (selector) => { assert.equal(selector, expected); return { waitForDisplayed: async () => {} }; } };
    await byTestId(driver, platform, 'note-save');
  }
});
test('failure reasons never copy token-bearing or private error text', () => {
  assert.equal(safeFailure(new Error('WRONG_PRINCIPAL'), 'FAILED'), 'WRONG_PRINCIPAL');
  assert.equal(safeFailure(new Error('request body password=secret'), 'FAILED'), 'FAILED');
});

async function listen(server) {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return `http://127.0.0.1:${server.address().port}`;
}
test('gateway rejects missing marker and unadmitted route without any upstream call', async (t) => {
  let upstreamCalls = 0;
  const upstream = http.createServer((request, response) => { upstreamCalls++; response.end('{}'); });
  t.after(() => upstream.close());
  const target = await listen(upstream);
  const gateway = createGateway({ upstream: target, routes: ['GET /api/build'], runId: 'unit' });
  t.after(() => gateway.close());
  const origin = await listen(gateway);
  assert.equal((await fetch(`${origin}/api/build`)).status, 403);
  assert.equal((await fetch(`${origin}/api/paid-provider`, { headers: { [MARKER_HEADER]: MARKER } })).status, 403);
  assert.equal(upstreamCalls, 0);
  const state = await localJson(`${origin}/__caseops_e2e/status`);
  assert.equal(state.markerRejected, 1);
  assert.equal(state.routeRejected, 1);
});
test('gateway preserves marker, auth, mutation bytes and query without retry or redirect', async (t) => {
  let calls = 0;
  const upstream = http.createServer((request, response) => {
    calls++;
    assert.equal(request.headers[MARKER_HEADER.toLowerCase()], MARKER);
    assert.equal(request.headers.authorization, 'Bearer synthetic-unit-only');
    assert.equal(request.url, '/api/matters/unit/notes?encoded=%2F');
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      assert.equal(Buffer.concat(chunks).toString(), '{"text":"unit"}');
      response.writeHead(201, { 'content-type': 'application/json' });
      response.end('{"saved":true}');
    });
  });
  t.after(() => upstream.close());
  const gateway = createGateway({ upstream: await listen(upstream), routes: ['POST /api/matters/unit/notes'], runId: 'unit' });
  t.after(() => gateway.close());
  const origin = await listen(gateway);
  const response = await fetch(`${origin}/api/matters/unit/notes?encoded=%2F`, { method: 'POST',
    headers: { [MARKER_HEADER]: MARKER, authorization: 'Bearer synthetic-unit-only' }, body: '{"text":"unit"}' });
  assert.equal(response.status, 201);
  assert.equal((await response.json()).saved, true);
  assert.equal(calls, 1);
  const state = await localJson(`${origin}/__caseops_e2e/status`);
  assert.equal(state.requests[0].status, 201);
  assert.equal(JSON.stringify(state).includes('synthetic-unit-only'), false);
});
test('upstream redirect cannot escape loopback or leak credentials', async (t) => {
  const upstream = http.createServer((request, response) => { response.writeHead(302, { location: 'https://example.com' }); response.end(); });
  t.after(() => upstream.close());
  const gateway = createGateway({ upstream: await listen(upstream), routes: ['GET /api/build'], runId: 'unit' });
  t.after(() => gateway.close());
  const origin = await listen(gateway);
  const response = await fetch(`${origin}/api/build`, { headers: { [MARKER_HEADER]: MARKER }, redirect: 'error' });
  assert.equal(response.status, 502);
  assert.equal(response.headers.get('location'), null);
});
test('gateway cannot start with a wildcard or external upstream', () => {
  assert.throws(() => createGateway({ upstream: 'https://caseops.ai', routes: ['GET /api/build'], runId: 'unit' }));
  assert.throws(() => createGateway({ upstream: 'http://127.0.0.1', routes: ['GET /api/*'], runId: 'unit' }));
});

test('gateway rejects absolute and authority-like targets before any upstream request', async (t) => {
  let trustedCalls = 0, otherCalls = 0;
  const trusted = http.createServer((_request, response) => { trustedCalls++; response.end('{"ok":true}'); });
  const other = http.createServer((_request, response) => { otherCalls++; response.end('{}'); });
  t.after(() => trusted.close());
  t.after(() => other.close());
  const gateway = createGateway({ upstream: await listen(trusted), routes: ['GET /api/build'], runId: 'target-unit' });
  t.after(() => gateway.close());
  const origin = new URL(await listen(gateway));
  const otherOrigin = await listen(other);
  const raw = (target) => new Promise((resolve, reject) => {
    const request = http.request({ hostname: origin.hostname, port: origin.port, path: target,
      headers: { [MARKER_HEADER]: MARKER }, timeout: 2000 }, response => {
      response.resume(); response.on('end', () => resolve(response.statusCode));
    });
    request.on('error', reject); request.on('timeout', () => request.destroy(new Error('Synthetic request deadline'))); request.end();
  });
  for (const target of [`${otherOrigin}/api/build`, `//${new URL(otherOrigin).host}/api/build`, '/\\other.invalid/api/build']) {
    assert.equal(await raw(target), 403);
  }
  assert.equal(trustedCalls, 0);
  assert.equal(otherCalls, 0);
  assert.equal(await raw('/api/build?value=%2F'), 200);
  assert.equal(trustedCalls, 1);
  assert.equal(otherCalls, 0);
});

// Deterministic harness doubles only; these are not Android/iOS acceptance.
function matterDriver(platform, initialDepth, backAvailable = true) {
  let depth = initialDepth;
  const actions = [];
  const fixture = { matter: { id: 'unit', search: 'unit-search', identityLabel: 'unit-code' },
    ids: { searchSubmit: 'matter-search-submit', matterIdentity: 'matter-code' } };
  const driver = { $: async (selector) => {
    const id = selector.replace(platform === 'android' ? /^id=/ : /^~/, '');
    const visible = () => id === 'tab-matters' || (id === 'back' && depth > 0 && backAvailable)
      || (['matter-search', 'matter-search-submit', 'matter-row-unit'].includes(id) && depth === 0)
      || (id === 'matter-code' && depth === 1);
    return {
      isDisplayed: async () => visible(),
      waitForDisplayed: async () => assert.ok(visible(), `NOT_VISIBLE_${id}`),
      click: async () => { assert.ok(visible()); actions.push(id); if (id === 'back') depth--; if (id === 'matter-row-unit') depth = 1; },
      setValue: async (value) => { assert.ok(visible()); actions.push(`search:${value}`); },
      getText: async () => fixture.matter.identityLabel,
    };
  } };
  return { context: { driver, fixture, platform }, actions };
}
test('Matter search unwinds a retained tab detail stack on Android and iOS', async () => {
  for (const platform of ['android', 'ios']) {
    const fake = matterDriver(platform, 2);
    await scenarios.find((item) => item.id === 'CORE-03').run(fake.context);
    assert.deepEqual(fake.actions, ['tab-matters', 'back', 'back', 'search:unit-search', 'matter-search-submit', 'matter-row-unit']);
  }
});
test('Matter search rejects a deeper stack at the strict four-back bound', async () => {
  const fake = matterDriver('android', 10);
  await assert.rejects(() => scenarios.find((item) => item.id === 'CORE-03').run(fake.context), /MATTER_SEARCH_UNREACHABLE/);
  assert.equal(fake.actions.filter((action) => action === 'back').length, 4);
  assert.equal(fake.actions.some((action) => action.startsWith('search:')), false);
});
test('Matter search fails closed when no usable Back control exists', async () => {
  const fake = matterDriver('ios', 1, false);
  await assert.rejects(() => scenarios.find((item) => item.id === 'CORE-03').run(fake.context), /MATTER_SEARCH_BACK_UNAVAILABLE/);
  assert.equal(fake.actions.some((action) => action.startsWith('search:')), false);
});
test('request evidence case uses retained traffic without touching authenticated tabs', async (t) => {
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/__caseops_e2e/status');
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ accepted: 2, markerRejected: 0, routeRejected: 0, overflow: false,
      requests: [{ method: 'GET', route: '/api/build' }, { method: 'GET', route: '/api/me/today' }] }));
  });
  t.after(() => server.close());
  const gatewayUrl = await listen(server);
  const driver = new Proxy({}, { get: () => { throw new Error('EVIDENCE_CASE_MUST_NOT_TOUCH_UI'); } });
  await scenarios.find((item) => item.id === 'CORE-06').run({ fixture: { gatewayUrl }, driver, platform: 'android' });
});

const EXPECTED_DATED = ['NATIVE-01', 'NATIVE-02', 'NATIVE-03', 'NATIVE-04', 'NATIVE-05', 'NATIVE-06',
  'NATIVE-07', 'NATIVE-08', 'NATIVE-09', 'NATIVE-10', 'NATIVE-11', 'NATIVE-12', 'NATIVE-13', 'NATIVE-14',
  'NATIVE-15', 'NATIVE-16', 'NATIVE-17', 'NATIVE-18', 'NATIVE-19', 'NATIVE-20', 'NATIVE-21', 'NATIVE-22', 'NATIVE-23'];
test('dated intended and executable inventories equal the independent literal 23-case contract', () => {
  assert.deepEqual(datedInventory.cases.map(({ id }) => id), EXPECTED_DATED);
  assert.deepEqual(datedScenarios.map(({ id }) => id), EXPECTED_DATED);
  assert.deepEqual(SEARCH_KINDS, ['matter_code', 'case_number', 'filing_number', 'cnr_number', 'temporary_e_case_number']);
  for (const platform of ['android', 'ios']) {
    const result = collect(platform);
    assert.deepEqual(result.discovered, EXPECTED_DATED.map((id) => `${platform}:${id}`));
    assert.deepEqual(result.intended, result.discovered);
  }
});

test('both collection CLIs discover all 23 without opening Appium or requiring a fixture', () => {
  for (const platform of ['android', 'ios']) {
    const result = JSON.parse(execFileSync(process.execPath, [fileURLToPath(new URL('./run-native.mjs', import.meta.url)), platform, '--collect'], { encoding: 'utf8' }));
    assert.equal(result.inventoryId, 'native-core-2026-10-25');
    assert.deepEqual(result.discovered, EXPECTED_DATED.map((id) => `${platform}:${id}`));
  }
});

const signedOutResume = datedScenarios.find(({ id }) => id === 'NATIVE-23');
function resumeDriver(platform, options = {}) {
  const actions = [], records = [];
  const appId = platform === 'android' ? 'ai.caseops.mobile.dev.localacceptance' : 'ai.caseops.mobile.dev.simulatoracceptance';
  let phase = 'initial';
  const driver = {
    queryAppState: async (id) => {
      assert.equal(id, appId);
      return phase === 'background' ? options.backgroundState ?? 3 : phase === 'resumed' ? options.resumeState ?? 4 : 4;
    },
    getCurrentPackage: async () => phase === 'background' && !options.homeKeepsPackage ? 'unit.launcher'
      : phase === 'resumed' && options.wrongResumePackage ? 'org.mozilla.firefox' : appId,
    pressKeyCode: async (key) => { assert.equal(key, 3); actions.push('android-home'); phase = 'background'; },
    execute: async (command, arguments_) => {
      assert.equal(command, 'mobile: pressButton'); assert.deepEqual(arguments_, { name: 'home' });
      actions.push('ios-home'); phase = 'background';
    },
    activateApp: async (id) => { assert.equal(id, appId); actions.push('activate-bound-app'); phase = 'resumed'; },
    switchContext: async (name) => { assert.equal(name, 'NATIVE_APP'); actions.push('native-context'); },
    waitUntil: async (predicate, { timeoutMsg }) => assert.equal(await predicate(), true, timeoutMsg),
    $$: async (query) => {
      const usable = !(phase === 'resumed' && options.privacyCover);
      const isSignIn = query === selector(platform, 'id', 'sign-in');
      if (usable && (isSignIn || query === selector(platform, 'id', 'signed-out'))
        || options.privateId && query === selector(platform, 'id', options.privateId)) {
        return [{ isDisplayed: async () => true, isEnabled: async () => !options.disabledSignIn,
          click: async () => { throw new Error('REGRESSION_MUST_NOT_CLICK_SIGN_IN'); } }];
      }
      return [];
    },
  };
  return { context: { driver: nativeProtocolDouble(driver), platform, fixture: { appId, principalLabel: 'unit-principal', workspaceLabel: 'unit-workspace',
    matter: { title: 'unit-private-title', identityLabel: 'unit-code' } }, record: (event) => records.push(event) }, actions, records };
}

test('post-logout regression has an independent signed-out prerequisite after NATIVE-22', () => {
  assert.equal(datedInventory.cases.at(-1).id, 'NATIVE-23');
  assert.equal(datedInventory.cases.at(-1).signedOutAfter, 'NATIVE-22');
  assert.equal(signedOutResume.signedOutAfter, 'NATIVE-22');
  assert.equal(signedOutResume.authenticateInCall, undefined);
});

test('post-logout setup blocks without a fully completed logout and never tries login', async () => {
  const driver = new Proxy({}, { get: () => { throw new Error('NO_DEVICE_OR_AUTH_WITHOUT_LOGOUT_PREREQUISITE'); } });
  await assert.rejects(() => prepareScenario({ driver }, signedOutResume, new Set()), /PREREQUISITE_SCENARIO_NOT_PASSED/);
  for (const platform of ['android', 'ios']) {
    const fake = resumeDriver(platform);
    await prepareScenario(fake.context, signedOutResume, new Set(['NATIVE-22']));
    assert.deepEqual(fake.actions, []);
  }
});

test('Home/resume uses actual platform Home, observes background and activates without process termination', async () => {
  for (const [platform, backgroundState] of [['android', 3], ['ios', 3], ['ios', 2]]) {
    const fake = resumeDriver(platform, { backgroundState });
    await backgroundAndResume(fake.context);
    assert.deepEqual(fake.actions, [`${platform}-home`, 'activate-bound-app', 'native-context']);
    assert.deepEqual(fake.records, [{ type: 'native_home_observed', platform, leftApp: true, backgroundState }]);
  }
});

test('Android Home must positively leave the exact app package before activation', async () => {
  const fake = resumeDriver('android', { homeKeepsPackage: true });
  await assert.rejects(() => backgroundAndResume(fake.context), /HOME_DID_NOT_BACKGROUND_RUNNING_APP/);
  assert.deepEqual(fake.actions, ['android-home']);
});

test('a terminated or unobserved Home transition cannot masquerade as warm background', async () => {
  for (const platform of ['android', 'ios']) for (const backgroundState of [0, 1, 4]) {
    const fake = resumeDriver(platform, { backgroundState });
    await assert.rejects(() => backgroundAndResume(fake.context), /HOME_DID_NOT_BACKGROUND_RUNNING_APP/);
    assert.deepEqual(fake.actions, [`${platform}-home`]);
  }
});

test('activation must restore foreground state and the exact Android package', async () => {
  for (const [platform, options] of [['android', { resumeState: 3 }], ['ios', { resumeState: 2 }], ['android', { wrongResumePackage: true }]]) {
    const fake = resumeDriver(platform, options);
    await assert.rejects(() => backgroundAndResume(fake.context), /HOME_RESUME_DID_NOT_FOREGROUND_EXACT_APP/);
  }
});

test('post-logout setup rejects disabled sign-in and retained private surfaces', async () => {
  for (const platform of ['android', 'ios']) {
    await assert.rejects(() => prepareScenario(resumeDriver(platform, { disabledSignIn: true }).context,
      signedOutResume, new Set(['NATIVE-22'])), /SIGNED_OUT_SIGN_IN_NOT_USABLE/);
    for (const privateId of ['account-open', 'account-screen', 'matter-code', 'note-input', 'screen-today', 'tab-work']) {
      await assert.rejects(() => prepareScenario(resumeDriver(platform, { privateId }).context,
        signedOutResume, new Set(['NATIVE-22'])), /PRIVATE_OR_FORBIDDEN_SURFACE_VISIBLE/);
    }
  }
});

test('signed-out resume rejects refresh, token exchange, authorization or any other auth attempt, including pending requests', () => {
  signedOutResumeTraffic([]);
  signedOutResumeTraffic([{ method: 'GET', route: '/api/build', status: 200 }]);
  for (const route of ['/api/auth/native/refresh', '/api/auth/native/token', '/api/auth/native/authorize', '/api/auth/login', '/api/auth/me']) {
    for (const status of [null, 200, 401]) assert.throws(() => signedOutResumeTraffic([{ method: 'POST', route, status }]), /SIGNED_OUT_RESUME_ATTEMPTED_AUTHENTICATION/);
  }
});

test('NATIVE-23 orchestration restores signed-out controls and rejects the reported persistent privacy cover (unit doubles only)', async (t) => {
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/__caseops_e2e/status');
    assert.equal(request.headers[MARKER_HEADER.toLowerCase()], MARKER);
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ runId: 'unit-resume', lastSequence: 0, overflow: false, markerRejected: 0, routeRejected: 0, requests: [] }));
  });
  t.after(() => server.close());
  const gatewayUrl = await listen(server);
  for (const platform of ['android', 'ios']) {
    for (const privacyCover of [false, true]) {
      const fake = resumeDriver(platform, { privacyCover });
      Object.assign(fake.context.fixture, { gatewayUrl, gatewayRunId: 'unit-resume' });
      await prepareScenario(fake.context, signedOutResume, new Set(['NATIVE-22']));
      if (privacyCover) await assert.rejects(() => signedOutResume.run(fake.context), /NATIVE_CONTROL_NOT_VISIBLE/);
      else await signedOutResume.run(fake.context);
      assert.deepEqual(fake.actions, [`${platform}-home`, 'activate-bound-app', 'native-context']);
    }
  }
});

test('historical six are immutable and cannot be relabelled as expanded core receipts', () => {
  assert.deepEqual(inventory.cases.map(({ id }) => id), ['CORE-01', 'CORE-02', 'CORE-03', 'CORE-04', 'CORE-06', 'CORE-05']);
  assert.equal(receiptInventory({ platform: 'android', scope: inventory.scope }, 'android').schemaVersion, 1);
  assert.equal(receiptInventory({ platform: 'ios', inventoryId: datedInventory.inventoryId }, 'ios').schemaVersion, 2);
  assert.throws(() => receiptInventory({ platform: 'android', inventoryId: 'invented' }, 'android'), /UNKNOWN_NATIVE/);
  assert.throws(() => receiptInventory({ platform: 'android', scope: 'renamed old green' }, 'android'), /HISTORICAL_SCOPE/);
  assert.throws(() => receiptInventory({ platform: 'android', inventoryId: datedInventory.inventoryId }, 'ios'), /PLATFORM_MISMATCH/);
});

test('native harness fingerprint is stable and source-bound rather than only a Git SHA', () => {
  assert.match(harnessFingerprint(), /^[a-f0-9]{64}$/);
  assert.equal(harnessFingerprint(), harnessFingerprint());
});

function strictEvents() {
  const rows = events();
  Object.assign(rows[0], { platform: 'android', inventoryId: datedInventory.inventoryId, harnessFingerprint: 'a'.repeat(64) });
  Object.assign(rows.at(-1), { platform: 'android', intendedCount: 1 });
  return rows;
}
test('dated reconciliation admits complete exact phases and explicitly blocks missing capability', () => {
  assert.equal(reconcileResults(strictEvents(), ['android:A']).status, 'passed');
  const rows = strictEvents();
  rows.find((row) => row.type === 'phase_result' && row.phase === 'setup').status = 'blocked';
  rows.find((row) => row.type === 'phase_result' && row.phase === 'call').status = 'not-run';
  const result = reconcileResults(rows, ['android:A']);
  assert.equal(result.status, 'incomplete-or-failed');
  assert.equal(result.unexecutedCalls, 1);
  assert.equal(result.blockedScenarios, 1);
  assert.equal(result.nativeCallsPassed, 0);
});
test('dated reconciliation rejects a passed call after failed setup or preflight', () => {
  for (const phase of ['setup', 'preflight']) {
    const rows = strictEvents();
    rows.find((row) => phase === 'preflight' ? row.type === 'preflight_result' : row.type === 'phase_result' && row.phase === phase).status = 'failed';
    if (phase === 'preflight') rows.splice(rows.findIndex((row) => row.type === 'postflight_result'), 1);
    assert.throws(() => reconcileResults(rows, ['android:A']), /AFTER_FAILED/);
  }
});
test('dated reconciliation rejects mismatched completion, foreign phase starts and interrupted completion', () => {
  for (const mutate of [
    (rows) => { rows.at(-1).intendedCount = 0; },
    (rows) => { rows.at(-1).platform = 'ios'; },
    (rows) => { rows[0].harnessFingerprint = undefined; },
    (rows) => { rows.splice(-1, 0, { type: 'phase_started', id: 'android:wrong', phase: 'call' }); },
    (rows) => { rows.splice(-1, 0, { type: 'run_interrupted' }); },
  ]) {
    const rows = strictEvents(); mutate(rows);
    assert.throws(() => reconcileResults(rows, ['android:A']));
  }
});
test('dated phase order cannot be permuted even when every phase has a matching start', () => {
  const rows = strictEvents();
  [rows[2], rows[4]] = [rows[4], rows[2]];
  [rows[3], rows[5]] = [rows[5], rows[3]];
  assert.throws(() => reconcileResults(rows, ['android:A']), /EXECUTION_ORDER/);
});

const authUrl = (origin = 'https://10.0.2.2:3443') => `${origin}/native/sign-in?${new URLSearchParams({
  code_challenge: 'a'.repeat(43), state: 'b'.repeat(64), platform: 'android', redirect_uri: 'caseops://oauth/callback',
})}`;
test('browser auth admits only actual isolated TLS origins and native sign-in return', () => {
  const origin = 'https://10.0.2.2:3443';
  const expected = authorizationIdentity(authUrl(), origin, 'android');
  assert.equal(expected.redirect_uri, 'caseops://oauth/callback');
  assert.deepEqual(authorizationIdentity(`${origin}/sign-in?${new URLSearchParams({ next: new URL(authUrl()).pathname + new URL(authUrl()).search })}`, origin, 'android'), expected);
  for (const value of ['http://10.0.2.2:3443', 'https://caseops.ai', 'https://10.0.2.2.evil.test', 'https://user:secret@localhost', 'https://localhost/path']) assert.throws(() => browserOrigin(value));
});
test('PKCE inspection rejects duplicate/missing/state/redirect/platform/origin mutations before form use', () => {
  const origin = 'https://10.0.2.2:3443';
  for (const mutate of [
    (url) => url.searchParams.append('state', 'c'.repeat(64)),
    (url) => url.searchParams.delete('code_challenge'),
    (url) => url.searchParams.set('state', 'short'),
    (url) => url.searchParams.set('redirect_uri', 'https://example.com'),
    (url) => url.searchParams.set('platform', 'ios'),
    (url) => { url.pathname = '/native/authorize'; },
    (url) => { url.hostname = 'example.com'; },
    (url) => { url.hash = 'secret'; },
  ]) { const url = new URL(authUrl()); mutate(url); assert.throws(() => authorizationIdentity(url.href, origin, 'android')); }
});
test('browser credentials come only from bounded named environment values, never fixture password fields', () => {
  const auth = { companySlug: 'unit', emailEnv: 'CASEOPS_MOBILE_UNIT_EMAIL', passwordEnv: 'CASEOPS_MOBILE_UNIT_PASSWORD' };
  assert.deepEqual(loginCredentials(auth, { CASEOPS_MOBILE_UNIT_EMAIL: 'unit@example.invalid', CASEOPS_MOBILE_UNIT_PASSWORD: 'unit-only' }),
    { companySlug: 'unit', email: 'unit@example.invalid', password: 'unit-only' });
  assert.throws(() => loginCredentials({ ...auth, password: 'in-file' }, {}), /CREDENTIALS_MISSING/);
  assert.throws(() => loginCredentials({ ...auth, passwordEnv: 'PATH' }, { PATH: 'private' }), /ENV_NAME/);
});

function domBrowserDouble({ wrongPrincipal = false, changedHandoff = false, externalOrigin = false, duplicatePassword = false,
  mfa = false, consent = false, platform = 'android', wrongAfterMfa = false, changedAfterMfa = false, autoConnect = false,
  noConsentChallenge = false, verifyRefused = false, appOpenMissing = false, appOpenDisabled = false, wrongAppOpenLabel = false,
  initiallyAuthenticated = false } = {}) {
  let stage = initiallyAuthenticated ? 'complete' : 'app', native = true, verified = false;
  const writes = [], clicks = [], records = [], requests = [];
  const request = (method, route, status) => requests.push({ sequence: requests.length + 1, method, route, status, nativeMarker: true });
  const url = () => {
    if (externalOrigin) return authUrl('https://example.com');
    const value = new URL(authUrl('https://127.0.0.1:3443'));
    value.searchParams.set('platform', platform);
    if (stage === 'connect' && changedHandoff || verified && changedAfterMfa) value.searchParams.set('state', 'c'.repeat(64));
    return ['login', 'mfa'].includes(stage) ? `${value.origin}/sign-in?${new URLSearchParams({ next: value.pathname + value.search })}` : value.href;
  };
  const element = (key, text = '') => ({
    isDisplayed: async () => true, isEnabled: async () => key !== 'app-open' || !appOpenDisabled, getText: async () => text,
    setValue: async (value) => { writes.push([key, value]); },
    click: async () => { clicks.push(key); if (key === 'sign-in') stage = 'landing'; if (key === 'link') stage = 'login';
      if (key === 'account') stage = 'account'; if (key === 'back') stage = 'complete';
      if (key === 'sign-out') { request('POST', '/api/auth/native/logout', 204); stage = 'app'; }
      if (key === 'submit') stage = mfa ? 'mfa' : 'connect'; if (key === 'mfa-submit') stage = 'connect';
      if (key === 'connect') {
        request('POST', '/api/auth/native/authorize', consent && !verified ? 403 : 200);
        stage = consent && !verified ? noConsentChallenge ? 'connect' : 'consent-mfa' : 'grant';
      }
      if (key === 'app-open') { request('POST', '/api/auth/native/token', 200); stage = 'complete'; }
      if (key === 'consent-verify' && !verifyRefused) {
        request('POST', '/api/auth/mfa/step-up', 200); request('GET', '/api/auth/me', 200);
        verified = true; stage = autoConnect ? 'complete' : 'connect';
      } },
  });
  const driver = {
    switchContext: async (name) => { native = name === 'NATIVE_APP'; },
    execute: async (command, args) => {
      assert.equal(platform, 'ios', 'IOS_BROWSER_METADATA_COMMAND_REQUIRED');
      if (typeof command === 'function') {
        assert.equal(native, false, 'IOS_FOREGROUND_PROOF_REQUIRES_WEB_CONTEXT');
        return { visibilityState: 'visible', hasFocus: true };
      }
      assert.equal(command, 'mobile: getContexts');
      assert.deepEqual(args, { waitForWebviewMs: 0 });
      return [{ id: 'NATIVE_APP' }, ...(stage === 'app' ? [] : [{ id: 'WEBVIEW_browser', url: url(),
        title: 'Synthetic browser unit', bundleId: 'com.apple.SafariViewService' }])];
    },
    getContexts: async () => { assert.equal(platform, 'android'); return ['NATIVE_APP', 'WEBVIEW_browser']; },
    getUrl: async () => url(),
    getWindowHandle: async () => { assert.equal(native, false); return 'browser-window'; },
    getWindowHandles: async () => { assert.equal(platform, 'android'); return ['browser-window']; },
    switchToWindow: async () => { assert.equal(platform, 'android'); },
    waitUntil: async (callback) => assert.ok(await callback(), 'UNIT_WAIT_UNSATISFIED'),
    $$: async (query) => {
      if (native) {
        if (platform === 'ios' && query === '-ios predicate string:type == "XCUIElementTypeButton" AND (label == "Cancel" OR name == "Cancel")'
          && stage !== 'app') return [element('cancel')];
        if (query === selector(platform, 'id', 'sign-in') && stage === 'app') return [element('sign-in')];
        if (query === selector(platform, 'id', 'account-open') && stage === 'complete') return [element('account')];
        if (query === selector(platform, 'id', 'signed-out') && stage === 'app') return [element('signed-out')];
        if (stage === 'account') {
          if (query === selector(platform, 'id', 'sign-out')) return [element('sign-out')];
          if (query === selector(platform, 'id', 'account-principal')) return [element('principal', 'Unit Person')];
          if (query === selector(platform, 'id', 'account-workspace')) return [element('workspace', 'Unit Workspace')];
          if (query === selector(platform, 'id', 'back')) return [element('back')];
        }
        return [];
      }
      if (query === 'a[href^="/sign-in?next="]' && stage === 'landing') return [element('link')];
      if (['#company-slug', 'form[aria-label="Sign in"] #company-slug', '#email', '#password'].includes(query) && stage === 'login') return Array.from({ length: query === '#password' && duplicatePassword ? 2 : 1 }, () => element(query === 'form[aria-label="Sign in"] #company-slug' ? '#company-slug' : query));
      if (query === 'form[aria-label="Sign in"] button[type="submit"]' && stage === 'login') return [element('submit')];
      if (query === '#mfa-code' && stage === 'mfa') return [element('#mfa-code')];
      if (query === 'form[aria-label="MFA challenge"] button[type="submit"]' && stage === 'mfa') return [element('mfa-submit')];
      if (query === '#native-mfa-code' && stage === 'consent-mfa') return [element('native-mfa-code')];
      if (query === 'form:has(#native-mfa-code) button[type="submit"]' && stage === 'consent-mfa') return [element('consent-verify', 'Verify code')];
      if (query === 'main [role="status"]' && verified && stage === 'connect') return [element('consent-notice', CONSENT_MFA_VERIFIED)];
      if (query === 'main dl dd' && stage === 'connect') return [element('principal', `${wrongPrincipal || verified && wrongAfterMfa ? 'Wrong' : 'Unit Person'} unit@example.invalid`), element('workspace', 'Unit Workspace / unit')];
      if (query === 'main button' && stage === 'connect') return [element('connect', 'Connect app')];
      if (query === '#native-app-open' && stage === 'grant' && !appOpenMissing) return [element('app-open', wrongAppOpenLabel ? 'Wrong button' : 'Open CaseOps')];
      return [];
    },
  };
  return { context: { driver: nativeProtocolDouble(driver), platform, fixture: { principalLabel: 'Unit Person', workspaceLabel: 'Unit Workspace',
    auth: { mode: 'web-context', webOrigin: 'https://127.0.0.1:3443', companySlug: 'unit', emailEnv: 'CASEOPS_MOBILE_UNIT_EMAIL', passwordEnv: 'CASEOPS_MOBILE_UNIT_PASSWORD' } }, record: (row) => records.push(row) },
  writes, clicks, records, requests, isNative: () => native };
}
function browserEnvironment(t) {
  for (const [key, value] of Object.entries({ CASEOPS_MOBILE_UNIT_EMAIL: 'unit@example.invalid', CASEOPS_MOBILE_UNIT_PASSWORD: 'unit-only-password', CASEOPS_MOBILE_UNIT_TOTP: 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ' })) {
    const previous = process.env[key]; process.env[key] = value;
    t.after(() => { if (previous === undefined) delete process.env[key]; else process.env[key] = previous; });
  }
}
test('browser UI orchestration fills the actual three fields and submits/connects once without exposing secrets', async (t) => {
  browserEnvironment(t);
  const fake = domBrowserDouble();
  await browserLogin(fake.context);
  assert.deepEqual(fake.writes.map(([key]) => key), ['#company-slug', '#email', '#password']);
  assert.equal(fake.clicks.filter((key) => key === 'submit').length, 1);
  assert.equal(fake.clicks.filter((key) => key === 'connect').length, 1);
  assert.equal(fake.isNative(), true);
  assert.equal(JSON.stringify(fake.records).includes('unit-only-password'), false);
  assert.equal(JSON.stringify(fake.records).includes('code_challenge'), false);
});
test('wrong browser principal or changed handoff prevents Connect and restores native context', async (t) => {
  browserEnvironment(t);
  for (const options of [{ wrongPrincipal: true }, { changedHandoff: true }, { duplicatePassword: true }]) {
    const fake = domBrowserDouble(options);
    await assert.rejects(() => browserLogin(fake.context));
    assert.equal(fake.clicks.includes('connect'), false);
    assert.equal(fake.isNative(), true);
    assert.ok(fake.clicks.filter((key) => key === 'submit').length <= 1);
  }
});
test('foreign browser page receives no credentials or Connect action', async (t) => {
  browserEnvironment(t);
  const fake = domBrowserDouble({ externalOrigin: true });
  await assert.rejects(() => browserLogin(fake.context));
  assert.deepEqual(fake.writes, []);
  assert.equal(fake.clicks.includes('connect'), false);
  assert.equal(fake.isNative(), true);
});

test('native locators escape exact text and reject XPath, unknown platforms and ambiguous visible controls', async () => {
  assert.equal(selector('android', 'text', 'A "quoted" title'), 'android=new UiSelector().text("A \\"quoted\\" title")');
  assert.throws(() => selector('android', 'xpath', '//button'), /LOCATOR_KIND/);
  assert.throws(() => selector('browser', 'id', 'note-save'), /PLATFORM/);
  const shown = { isDisplayed: async () => true }, hidden = { isDisplayed: async () => false };
  assert.equal(await visible({ $$: async () => [hidden, shown] }, 'unit'), shown);
  await assert.rejects(() => visible({ $$: async () => [shown, shown] }, 'unit'), /AMBIGUOUS/);
});
test('native scroll search is bounded and never clicks while a control is absent', async () => {
  let gestures = 0;
  const context = { platform: 'android', driver: { $$: async () => [], waitUntil: async (callback) => { assert.ok(await callback()); },
    getWindowRect: async () => ({ width: 400, height: 800 }), performActions: async () => { gestures++; }, releaseActions: async () => {} } };
  await assert.rejects(() => find(context, 'id', 'missing', { scroll: true }), /NOT_VISIBLE/);
  assert.equal(gestures, 9);
});
test('read-only Work rejects generation, approval and other mutations while allowing rotating auth', () => {
  readOnlyTraffic([{ method: 'GET', route: '/api/read' }, { method: 'POST', route: '/api/auth/native/refresh' }]);
  for (const route of ['/api/drafts/generate', '/api/drafts/approve', '/api/matters/unit/notes']) {
    assert.throws(() => readOnlyTraffic([{ method: 'GET' }, { method: 'POST', route }]), /MUTATION/);
  }
});

function discardDriver(platform, captions = {}) {
  const appId = 'ai.caseops.mobile.dev.localacceptance', clicks = [], records = [];
  let open = false;
  const controls = platform === 'android'
    ? [[`${appId}:id/alert_title`, captions.title ?? 'Discard unsaved note?'], ['android:id/button2', captions.stay ?? 'STAY'],
      ['android:id/button1', captions.leave ?? 'LEAVE EDITOR']]
    : [['Discard unsaved note?', 'Discard unsaved note?'], ['Stay', 'Stay'], ['Leave editor', 'Leave editor']];
  const driver = {
    waitUntil: async (predicate) => assert.ok(await predicate(), 'UNIT_CONTROL_NOT_VISIBLE'),
    $$: async (query) => {
      const back = query === selector(platform, 'id', 'back');
      const entry = open && controls.find(([id]) => selector(platform, platform === 'android' ? 'id' : 'text', id) === query);
      if (!back && !entry) return [];
      return [{ isDisplayed: async () => true, getText: async () => entry[1], click: async () => {
        clicks.push(back ? 'back' : entry[0]); open = back;
      } }];
    },
  };
  return { context: { driver: nativeProtocolDouble(driver), platform, fixture: { appId }, record: (event) => records.push(event) }, clicks, records };
}

test('Android discard validates observed title and exact uppercase canonical button IDs for Stay and Leave', async () => {
  for (const [action, expected] of [['stay', 'android:id/button2'], ['leave', 'android:id/button1']]) {
    const fake = discardDriver('android');
    await discard(fake.context, action);
    assert.deepEqual(fake.clicks, ['back', expected]);
    assert.ok(fake.records.some(({ action, controlId }) => action === 'read' && controlId.endsWith(':id/alert_title')));
  }
  for (const captions of [{ title: 'Save outcome unknown' }, { stay: 'Stay' }, { leave: 'Leave editor' }]) {
    const fake = discardDriver('android', captions);
    await assert.rejects(() => discard(fake.context), /WRONG_NOTE_DISCARD/);
    assert.deepEqual(fake.clicks, ['back']);
  }
});

test('iOS discard orchestration retains exact source TitleCase labels without claiming an observed Mac run', async () => {
  for (const [action, expected] of [['stay', 'Stay'], ['leave', 'Leave editor']]) {
    const fake = discardDriver('ios');
    await discard(fake.context, action);
    assert.deepEqual(fake.clicks, ['back', expected]);
  }
});

test('native ID locator admits exact qualified Android resource IDs but no guessed paths or iOS resource prefixes', () => {
  assert.equal(selector('android', 'id', 'android:id/button2'), 'id=android:id/button2');
  for (const id of ['some/path', 'android:id/button2/child', '/android:id/button2', 'android:id/button 2']) {
    assert.throws(() => selector('android', 'id', id), /INVALID_TEST_ID/);
  }
  assert.throws(() => selector('ios', 'id', 'android:id/button2'), /INVALID_TEST_ID/);
});

test('native UI action stages retain IDs only, never text selectors, read bodies or input values', async () => {
  const records = [], secret = 'unit-private-note-content';
  const context = { platform: 'android', record: (event) => records.push(event), driver: {
    waitUntil: async (predicate) => assert.ok(await predicate()),
    $$: async () => [{ isDisplayed: async () => true, setValue: async () => {}, getText: async () => secret, click: async () => {} }],
  } };
  nativeProtocolDouble(context.driver);
  await input(context, 'id', 'note-input', secret);
  assert.equal(await read(context, 'id', 'note-body-unit'), secret);
  await click(context, 'id', 'android:id/button1');
  await find(context, 'text', secret);
  assert.equal(JSON.stringify(records).includes(secret), false);
  assert.ok(records.some(({ action, controlId }) => action === 'input' && controlId === 'note-input'));
  for (const event of records) assert.ok(Object.keys(event).every((key) => ['type', 'action', 'controlId'].includes(key)));
  assert.throws(() => nativeAction(context, 'unit-secret-action'), /SAFE_NATIVE_ACTION_REQUIRED/);
});

test('phase-two fresh auth and whole-run three-cycle expectation match independent intended metadata', () => {
  assert.deepEqual(datedInventory.cases.filter(({ freshAuthenticationInSetup }) => freshAuthenticationInSetup).map(({ id }) => id), ['NATIVE-13']);
  assert.deepEqual(datedScenarios.filter(({ freshAuthenticationInSetup }) => freshAuthenticationInSetup).map(({ id }) => id), ['NATIVE-13']);
  assert.equal(datedInventory.cases.find(({ id }) => id === 'NATIVE-21').expectedAuthenticationCycles, 3);
  assert.equal(datedScenarios.find(({ id }) => id === 'NATIVE-21').expectedAuthenticationCycles, 3);
  const cycle = [{ method: 'POST', route: '/api/auth/native/authorize', status: 403 },
    { method: 'POST', route: '/api/auth/mfa/step-up', status: 200 }, { method: 'GET', route: '/api/auth/me', status: 200 },
    { method: 'POST', route: '/api/auth/native/authorize', status: 200 }, { method: 'POST', route: '/api/auth/native/token', status: 200 }];
  const auth = { mfaRequired: true, mfaStage: 'consent' };
  validateAuthorizationTraffic(Array.from({ length: 3 }, () => structuredClone(cycle)).flat(), auth, { cycles: 3 });
  for (const count of [1, 2, 4]) assert.throws(() => validateAuthorizationTraffic(
    Array.from({ length: count }, () => structuredClone(cycle)).flat(), auth, { cycles: 3 }), /CYCLE_COUNT_MISMATCH/);
});

test('NATIVE-13 setup runs actual auth orchestration fresh with logout, password, MFA, consent and app-open (unit double only)', async (t) => {
  browserEnvironment(t);
  const fake = domBrowserDouble({ consent: true, initiallyAuthenticated: true });
  Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/__caseops_e2e/status');
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ runId: 'unit-phase-two', lastSequence: fake.requests.length, overflow: false, markerRejected: 0,
      routeRejected: 0, requests: fake.requests }));
  });
  t.after(() => server.close());
  Object.assign(fake.context.fixture, { gatewayUrl: await listen(server), gatewayRunId: 'unit-phase-two' });
  await prepareScenario(fake.context, datedScenarios.find(({ id }) => id === 'NATIVE-13'), new Set());
  assert.deepEqual(fake.clicks, ['account', 'sign-out', 'sign-in', 'link', 'submit', 'connect', 'consent-verify', 'connect', 'app-open', 'account', 'back']);
  assert.deepEqual(fake.records.filter(({ type }) => type === 'native_authentication_boundary').map(({ state }) => state), ['started', 'passed']);
  assert.equal(fake.requests.filter(({ method, route }) => method === 'POST' && route === '/api/auth/native/logout').length, 1);
  assert.equal(fake.requests.filter(({ method, route }) => method === 'POST' && route === '/api/auth/native/token').length, 1);
});

test('failed-call recovery restarts only the bound app and never retries an operation or alters NATIVE-23 Home semantics', async () => {
  const calls = [], records = [], appId = 'ai.caseops.mobile.dev.localacceptance';
  const context = { platform: 'android', fixture: { appId }, record: (event) => records.push(event), driver: {
    terminateApp: async (id) => calls.push(['terminate', id]), activateApp: async (id) => calls.push(['activate', id]),
    switchContext: async (name) => calls.push(['context', name]),
  } };
  const previous = { id: 'NATIVE-13', failedCall: true };
  await recoverFailedCall(context, { id: 'NATIVE-14' }, previous);
  assert.deepEqual(calls, [['terminate', appId], ['activate', appId], ['context', 'NATIVE_APP']]);
  assert.ok(records.some(({ type, mutationReplay }) => type === 'native_case_recovery' && mutationReplay === false));
  calls.length = 0;
  assert.equal(needsFailedCallRecovery({ id: 'NATIVE-14' }, { id: 'NATIVE-13', failedCall: false }), false);
  await recoverFailedCall(context, { id: 'NATIVE-14' }, { id: 'NATIVE-13', failedCall: false });
  await recoverFailedCall(context, signedOutResume, { id: 'NATIVE-22', failedCall: true });
  assert.deepEqual(calls, []);
});

test('recovery rejects note POST activity including unknown outcomes without deleting or replaying retained notes', () => {
  noNotePostRetried([{ method: 'GET', route: '/api/matters/unit/notes' }, { method: 'POST', route: '/api/auth/native/refresh' }]);
  for (const id of ['primary', 'lifecycle', 'access']) for (const status of [null, 200, 201, 500]) {
    assert.throws(() => noNotePostRetried([{ method: 'POST', route: `/api/matters/${id}/notes`, status }]), /NOTE_POST_DURING_CASE_RECOVERY/);
  }
});

function savedNoteDriver(platform, options = {}) {
  const savedId = 'unit-acknowledged-id', body = 'Unit exact note body with release-scoped run identity', queries = [];
  const texts = { 'matter-code': options.wrongMatter ? 'OTHER-MATTER' : 'UNIT-MATTER',
    [`note-body-${savedId}`]: options.wrongBody ? 'Another saved body' : body };
  const driver = {
    waitUntil: async (predicate) => assert.ok(await predicate(), 'UNIT_NOTE_CONTROL_MISSING'),
    getWindowRect: async () => ({ width: 400, height: 800 }), performActions: async () => {}, releaseActions: async () => {},
    $$: async (query) => {
      queries.push(query);
      const id = query.replace(platform === 'android' ? /^id=/ : /^~/, '');
      const exists = id === 'matter-code' || id === `note-${savedId}` && !options.markerMissing
        || id === `note-body-${savedId}` && !options.bodyMissing || id === 'note-input' && options.editorVisible;
      if (!exists) return [];
      const element = { isDisplayed: async () => true, getText: async () => texts[id] ?? '',
        $$: async () => { throw new Error('FLATTENED_MARKER_HAS_NO_BODY_CHILDREN'); } };
      return id === `note-body-${savedId}` && options.duplicateBodyId ? [element, element] : [element];
    },
  };
  return { context: { driver: nativeProtocolDouble(driver), platform, fixture: { matter: { identityLabel: 'UNIT-MATTER' } }, noteText: body }, savedId, queries };
}

test('N9 exact acknowledged body ID proves ack/restart persistence despite a flattened leaf row marker (unit double)', async () => {
  for (const platform of ['android', 'ios']) for (const phase of ['ack', 'restart']) {
    const fake = savedNoteDriver(platform);
    await verifySavedNote(fake.context, fake.savedId, phase);
    assert.ok(fake.queries.includes(selector(platform, 'id', `note-${fake.savedId}`)));
    assert.ok(fake.queries.includes(selector(platform, 'id', `note-body-${fake.savedId}`)));
    assert.equal(fake.queries.some((query) => query.includes(fake.context.noteText)), false);
    assert.equal(fake.queries.some((query) => query.includes('note-latest-body')), false);
  }
});

test('N9 exact note binding rejects wrong body/Matter, editor text, missing marker/body and duplicate IDs without global fallback', async () => {
  for (const options of [{ wrongBody: true }, { wrongMatter: true }, { editorVisible: true },
    { markerMissing: true }, { bodyMissing: true }, { duplicateBodyId: true }]) {
    const fake = savedNoteDriver('android', options);
    await assert.rejects(() => verifySavedNote(fake.context, fake.savedId, 'restart'));
    assert.equal(fake.queries.some((query) => query.includes(fake.context.noteText)), false);
  }
});

test('canonical N9 uses the acknowledged ID at both checkpoints and retains one-POST/read evidence; six-case mapping stays historical', () => {
  const source = readFileSync(new URL('../../apps/mobile/e2e/journeys.mjs', import.meta.url), 'utf8');
  assert.ok(source.includes("await verifySavedNote(context, savedId, 'ack')"));
  assert.ok(source.includes("await verifySavedNote(context, savedId, 'restart')"));
  assert.equal(source.includes('note-latest-body'), false);
  assert.ok(source.includes("'NOTE_NOT_SUBMITTED_EXACTLY_ONCE'"));
  assert.ok(source.includes('successfulRead(requests, context.fixture.matterReloadRoute)'));
  const historical = JSON.parse(readFileSync(new URL('../../apps/mobile/e2e/testids.json', import.meta.url), 'utf8'));
  assert.equal(historical.ids?.savedNote ?? historical.savedNote, 'note-latest-body');
});

async function calendarDriver(t, { omitReloadRead = false, wrongEventId = false } = {}) {
  const requests = [], clicks = [], waits = [];
  const event = { hearingId: 'unit-hearing', eventId: 'hearing:unit-hearing', day: '2026-10-25', dayLabel: '25 Oct 2026', title: 'Unit recorded hearing', metaLabel: 'Unit hearing value',
    matter: { id: 'unit-matter', identityLabel: 'UNIT-MATTER', title: 'Unit source matter' }, nextHearingLabel: '25 Oct 2026 next hearing' };
  let page = 'calendar', draftDay = '', invalid = false;
  const appendRead = () => requests.push({ sequence: requests.length + 1, method: 'GET', route: '/api/calendar/events', status: 200, nativeMarker: true });
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/__caseops_e2e/status');
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ runId: 'unit-calendar', lastSequence: requests.length, overflow: false,
      markerRejected: 0, routeRejected: 0, requests }));
  });
  t.after(() => server.close());
  const driver = {
    waitUntil: async (predicate, options) => { waits.push(options); if (!await predicate()) throw new Error(options.timeoutMsg); },
    getWindowRect: async () => ({ width: 400, height: 800 }), performActions: async () => {}, releaseActions: async () => {},
    $$: async (query) => {
      const ids = ['tab-calendar', ...(page === 'calendar' ? ['screen-calendar', 'calendar-go-date', 'reload',
        `event-${wrongEventId ? 'another-hearing' : event.eventId}`] : ['matter-code'])];
      const id = ids.find((id) => query === selector('android', 'id', id));
      const dateInput = page === 'calendar' && query === selector('android', 'id', 'calendar-date-input');
      const texts = page === 'calendar' ? [event.dayLabel, event.title, event.metaLabel,
        ...(invalid ? ['Enter a valid date as YYYY-MM-DD.'] : [])] : [event.matter.title, event.nextHearingLabel];
      const text = texts.find((text) => query === selector('android', 'text', text));
      if (!id && !dateInput && !text) return [];
      return [{ isDisplayed: async () => true, getText: async () => id === 'matter-code' ? event.matter.identityLabel : text ?? '',
        setValue: async (value) => { assert.ok(dateInput); draftDay = value; }, click: async () => {
          clicks.push(id ?? 'text-leaf');
          if (id === 'tab-calendar') page = 'calendar';
          if (id === 'calendar-go-date') { invalid = draftDay !== event.day; if (!invalid) appendRead(); }
          if (id === 'reload' && !omitReloadRead) appendRead();
          if (id === `event-${event.eventId}`) page = 'matter';
          if (text) throw new Error('CALENDAR_TEXT_LEAF_IS_NOT_AN_ACTION_CONTROL');
        } }];
    },
  };
  return { context: { driver: nativeProtocolDouble(driver), platform: 'android', fixture: { calendar: event, gatewayRunId: 'unit-calendar', gatewayUrl: await listen(server) } },
    requests, clicks, waits };
}

test('N10/N11 use actual date/reload IDs and retain exact event/source values plus invalid-date zero-read boundary (unit double)', async (t) => {
  const positive = await calendarDriver(t);
  await datedScenarios.find(({ id }) => id === 'NATIVE-10').run(positive.context);
  assert.deepEqual(positive.clicks, ['tab-calendar', 'calendar-go-date', 'reload', 'event-hearing:unit-hearing']);
  assert.equal(positive.requests.length, 2);
  assert.ok(positive.waits.some(({ timeout, interval, timeoutMsg }) => timeout === 10000 && interval === 200 && timeoutMsg === 'AGENDA_REREAD_MISSING'));
  const invalid = await calendarDriver(t);
  await datedScenarios.find(({ id }) => id === 'NATIVE-11').run(invalid.context);
  assert.deepEqual(invalid.clicks, ['tab-calendar', 'calendar-go-date', 'calendar-go-date']);
  assert.equal(invalid.requests.length, 1);
});

test('N10 missing authoritative reload GET still fails without clicking twice or extending the read deadline', async (t) => {
  const fake = await calendarDriver(t, { omitReloadRead: true });
  await assert.rejects(() => datedScenarios.find(({ id }) => id === 'NATIVE-10').run(fake.context), /AGENDA_REREAD_MISSING/);
  assert.equal(fake.clicks.filter((id) => id === 'reload').length, 1);
  assert.equal(fake.requests.length, 1);
  assert.equal(fake.waits.filter(({ timeoutMsg }) => timeoutMsg === 'AGENDA_REREAD_MISSING').length, 1);
});

test('N10 rejects a different event ID even if its visible title/date/meta values match, without a title-click fallback', async (t) => {
  const fake = await calendarDriver(t, { wrongEventId: true });
  await assert.rejects(() => datedScenarios.find(({ id }) => id === 'NATIVE-10').run(fake.context), /NATIVE_CONTROL_NOT_VISIBLE/);
  assert.deepEqual(fake.clicks, ['tab-calendar', 'calendar-go-date', 'reload']);
});

test('N10 preserves an opaque Calendar event identity instead of deriving it from the hearing primary key', async (t) => {
  const fake = await calendarDriver(t);
  fake.context.fixture.calendar.eventId = 'opaque:v3-event-42';
  await datedScenarios.find(({ id }) => id === 'NATIVE-10').run(fake.context);
  assert.deepEqual(fake.clicks, ['tab-calendar', 'calendar-go-date', 'reload', 'event-opaque:v3-event-42']);
  assert.ok(!fake.clicks.includes('event-unit-hearing'));
});

test('N10 missing server-owned Calendar event identity cannot fall back to a hearing ID', async (t) => {
  const fake = await calendarDriver(t);
  delete fake.context.fixture.calendar.eventId;
  await assert.rejects(() => datedScenarios.find(({ id }) => id === 'NATIVE-10').run(fake.context), /SEEDED_CALENDAR_EVENT_ID_REQUIRED/);
  assert.deepEqual(fake.clicks, ['tab-calendar', 'calendar-go-date', 'reload']);
});

test('N20 clicks only the fixed server-current revoke ID while retaining cancel, confirmation, exact DELETE204 and admission proof (unit double)', async (t) => {
  const { plan, policy } = dynamicSessionPlan(t);
  const fixture = inspectLocalPlan(plan, 'android', unitCredentials).fixture;
  const state = sessionDeletionLedger(policy).before, clicks = [], records = [];
  let page = 'home';
  const append = (method, route, status) => {
    const sequence = ++state.lastSequence;
    const request = { sequence, requestId: sequence.toString(16).padStart(16, '0'), method, route, status, nativeMarker: true, browserHandoff: false };
    state.requests.push(request); state.accepted++;
    return request;
  };
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/__caseops_e2e/status');
    response.setHeader('content-type', 'application/json'); response.end(JSON.stringify(state));
  });
  t.after(() => server.close());
  fixture.gatewayUrl = await listen(server);
  const driver = {
    waitUntil: async (predicate) => assert.ok(await predicate()),
    getWindowRect: async () => ({ width: 400, height: 800 }), performActions: async () => {}, releaseActions: async () => {},
    terminateApp: async (id) => assert.equal(id, fixture.appId), activateApp: async (id) => assert.equal(id, fixture.appId),
    switchContext: async (name) => assert.equal(name, 'NATIVE_APP'),
    $$: async (query) => {
      const ids = page === 'home' ? ['account-open'] : page === 'account' ? ['account-session-current', 'account-session-current-revoke']
        : page === 'confirmation' ? ['account-session-confirmation', 'account-session-cancel', 'account-session-confirm'] : ['signed-out'];
      const id = ids.find((id) => query === selector('android', 'id', id));
      if (!id) return [];
      return [{ isDisplayed: async () => true, click: async () => {
        clicks.push(id);
        if (id === 'account-open') {
          page = 'account';
          const source = append('GET', '/api/auth/native/sessions', 200);
          state.sessionDeleteAdmissions.push({ type: 'session-delete-admitted', route: 'DELETE /api/auth/native/sessions/unit-current', sourceRequestId: source.requestId });
        }
        if (id === 'account-session-current-revoke') page = 'confirmation';
        if (id === 'account-session-cancel') page = 'account';
        if (id === 'account-session-confirm') {
          append('DELETE', '/api/auth/native/sessions/unit-current', 204);
          append('POST', '/api/auth/native/logout', 204);
          page = 'signed-out';
        }
      } }];
    },
  };
  await datedScenarios.find(({ id }) => id === 'NATIVE-20').run({ driver: nativeProtocolDouble(driver), fixture, platform: 'android', record: (event) => records.push(event) });
  assert.deepEqual(clicks, ['account-open', 'account-session-current-revoke', 'account-session-cancel',
    'account-session-current-revoke', 'account-session-confirm']);
  assert.equal(state.requests.filter(({ method }) => method === 'DELETE').length, 1);
  assert.ok(records.some(({ boundary, sourceRequestId, currentSessionId }) => boundary === 'current-native-session-delete-admission'
    && sourceRequestId === state.sessionDeleteAdmissions[0].sourceRequestId && currentSessionId === 'unit-current'));
});
test('request deltas reject changed run, truncation and same-sized history substitution', () => {
  const before = { runId: 'unit', lastSequence: 1, requests: [{ sequence: 1, method: 'GET', route: '/api/read', status: null }] };
  const after = { runId: 'unit', lastSequence: 2, requests: [{ ...before.requests[0], status: 200 }, { sequence: 2, method: 'POST', route: '/api/notes', status: 201 }] };
  assert.equal(delta(before, after).length, 1);
  assert.throws(() => delta(before, { ...after, runId: 'other' }), /RUN_CHANGED/);
  assert.throws(() => delta(before, { ...after, lastSequence: 0 }), /LEDGER_RESET/);
  assert.throws(() => delta(before, { ...after, requests: [{ sequence: 1, method: 'GET', route: '/api/other' }] }), /HISTORY_CHANGED/);
});

function ownedFile(t, body, name = 'receipt.json') {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'co-native-unit-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, name), bytes = Buffer.from(typeof body === 'string' ? body : JSON.stringify(body));
  writeFileSync(file, bytes);
  return { path: file, sha256: createHash('sha256').update(bytes).digest('hex') };
}
function coreFixture(t) {
  const matter = { id: 'unit-matter', identityLabel: 'UNIT-CODE', title: 'Synthetic unit matter', searches: SEARCH_KINDS.map((kind, index) => ({ kind, value: `unit-${index}` })) };
  const task = { id: 'unit-task', kind: 'task', title: 'Synthetic task', metaLabel: 'task 25 Oct 2026 todo', dueOn: '2026-10-25', dateLabel: '25 Oct 2026', status: 'todo', matter };
  const fixture = { environment: 'docker-integration', syntheticDataOnly: true, coreInventory: datedInventory.inventoryId,
    backendSha: 'a'.repeat(40), backendRevision: 'unit-api', webSha: 'a'.repeat(40), webRevision: 'unit-web', gatewayRunId: 'unit-run',
    browserApiMarkerVerified: true, matter, today: task, work: { task, draft: { ...task, id: 'unit-draft', kind: 'draft', entry: 'matter-work', revisionLabel: 'Revision 1', body: 'Synthetic draft', statusLabel: 'review Read-only', citations: ['Synthetic citation'], verifiedCitationCountLabel: '0 server-marked verified citations. This is not certification of legal accuracy.' } },
    calendar: { eventId: 'hearing:unit-hearing', matter, day: '2026-10-25', dayLabel: '25 Oct 2026', title: 'Synthetic hearing', metaLabel: 'hearing', nextHearingLabel: '25 Oct 2026' },
    auth: { mode: 'web-context', webOrigin: 'https://127.0.0.1:3443', companySlug: 'unit', emailEnv: 'CASEOPS_MOBILE_UNIT_EMAIL', passwordEnv: 'CASEOPS_MOBILE_UNIT_PASSWORD' } };
  fixture.isolationEvidence = ownedFile(t, { ...Object.fromEntries(['backendSha', 'backendRevision', 'gatewayRunId'].map((key) => [key, fixture[key]])),
    environment: 'docker-integration', syntheticDataOnly: true, project: 'unit-project',
    webIdentity: { service: 'web', release_sha: fixture.webSha, revision: fixture.webRevision },
    metroLaunched: false, productionAccessed: false, webAcceptanceMarkerBuild: true,
    containers: ['api', 'web', 'postgres'].map((service) => ({ name: `/unit-project-${service}-1`, project: 'unit-project', image: `sha256:${'a'.repeat(64)}`, networks: ['unit-project-private'] })) });
  return fixture;
}
const unitCredentials = { CASEOPS_MOBILE_UNIT_EMAIL: 'unit@example.invalid', CASEOPS_MOBILE_UNIT_PASSWORD: 'unit-only' };
test('dated fixture requires genuine Docker/TLS/release/marker/seed evidence and all supported searches', (t) => {
  const fixture = coreFixture(t);
  assert.equal(validateCoreFixture(fixture, unitCredentials), fixture);
  for (const mutate of [
    (copy) => { copy.environment = 'deterministic-simulator'; },
    (copy) => { copy.matter.searches.pop(); },
    (copy) => { copy.today.title = ''; },
    (copy) => { delete copy.work.draft.citations; },
    (copy) => { copy.browserApiMarkerVerified = false; },
    (copy) => { copy.backendRevision = 'different'; },
    (copy) => { copy.auth.webOrigin = 'http://127.0.0.1:3443'; },
  ]) { const copy = structuredClone(fixture); mutate(copy); assert.throws(() => validateCoreFixture(copy, unitCredentials)); }
});
test('fixture evidence hash changes and unbounded/relative files fail closed', (t) => {
  const receipt = ownedFile(t, 'unit evidence');
  assert.equal(verifiedFile(receipt.path, receipt.sha256).toString(), 'unit evidence');
  assert.throws(() => verifiedFile(receipt.path, '0'.repeat(64)), /CHANGED/);
  assert.throws(() => verifiedFile('relative.json', receipt.sha256), /ABSOLUTE/);
  assert.throws(() => verifiedFile(receipt.path, receipt.sha256, 1), /BOUNDED/);
});
test('owner capability absence is explicit unavailable and never an E2E pass', async () => {
  await assert.rejects(() => ownerControl({ owner: null }, 'disposeMatter', 'unit'), FixtureUnavailable);
});
test('owner controls refuse positive and wrong-purpose targets without invoking privileged work', async () => {
  let calls = 0;
  const context = { fixture: { environment: 'docker-integration', lifecycleMatter: { id: 'lifecycle' }, accessMatter: { id: 'access' } },
    owner: { capabilities: ['disposeMatter'], control: async () => { calls++; } } };
  for (const id of ['positive-matter', 'access']) await assert.rejects(() => ownerControl(context, 'disposeMatter', id), /UNOWNED/);
  assert.equal(calls, 0);
});
test('an uncertain owner command poisons the shared adapter and cannot be replayed by the next scenario', async () => {
  let calls = 0;
  const context = { fixture: { environment: 'docker-integration', lifecycleMatter: { id: 'lifecycle' } },
    owner: { capabilities: ['disposeMatter'], control: async () => { calls++; throw new Error('UNIT_TRANSPORT_LOST'); } } };
  await assert.rejects(() => ownerControl(context, 'disposeMatter', 'lifecycle'), /TRANSPORT_LOST/);
  await assert.rejects(() => ownerControl({ ...context }, 'disposeMatter', 'lifecycle'), /PREVIOUSLY_UNCERTAIN/);
  assert.equal(calls, 1);
});

function firefoxRecipe(t, { consent = false, androidBack = false, prepare = [], afterConnect = [], entryLocators = {} } = {}) {
  const locators = Object.fromEntries(['urlOpen', 'urlValue', 'urlClose', 'companySlug', 'email', 'password', 'submit', 'principal', 'emailFact', 'workspace', 'connect', 'signInLink']
    .map((key) => [key, { kind: 'id', value: `unit-${key}` }]));
  locators.appOpen = { kind: 'id', value: 'native-app-open' };
  locators.fullBrowser = { kind: 'id', value: 'ADDRESSBAR_TABS_COUNTER' };
  Object.assign(locators, entryLocators);
  if (consent) Object.assign(locators, { mfaCode: { kind: 'id', value: 'native-mfa-code' }, mfaSubmit: { kind: 'buttonText', value: 'Verify code' },
    mfaVerified: { kind: 'text', value: CONSENT_MFA_VERIFIED } });
  const urlCloseMode = androidBack ? 'android-back' : 'locator';
  const evidence = ownedFile(t, { kind: 'observed-native-firefox-locators', packageName: 'org.mozilla.firefox', version: '158.0.2', locators, urlCloseMode, prepare, afterConnect });
  return { ...(consent ? { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' } : {}),
    firefoxUi: { status: 'complete', packageName: 'org.mozilla.firefox', version: '158.0.2', signerSha256: 'A78B62A5165B4494B2FEAD9E76A280D22D937FEE6251AECE599446B2EA319B04',
    caTrustedThroughSettings: true, locatorEvidencePath: evidence.path, locatorEvidenceSha256: evidence.sha256, locators, urlCloseMode, prepare, afterConnect } };
}
test('Firefox native automation requires observed exact locators, trusted CA and reviewed package signer', (t) => {
  const auth = firefoxRecipe(t);
  assert.equal(validateFirefoxRecipe(auth), auth.firefoxUi);
  for (const mutate of [
    (copy) => { copy.firefoxUi.caTrustedThroughSettings = false; },
    (copy) => { copy.firefoxUi.signerSha256 = '0'.repeat(64); },
    (copy) => { copy.firefoxUi.locators.password = { kind: 'xpath', value: '//input[3]' }; },
    (copy) => { copy.firefoxUi.locatorEvidenceSha256 = '0'.repeat(64); },
    (copy) => { copy.firefoxUi.packageName = 'foreign.browser'; },
  ]) { const copy = structuredClone(auth); mutate(copy); assert.throws(() => validateFirefoxRecipe(copy)); }
});

test('Firefox app-open admission requires the exact new locator in both the recipe and hashed observed evidence', (t) => {
  const old = firefoxRecipe(t);
  delete old.firefoxUi.locators.appOpen;
  const oldEvidence = ownedFile(t, { kind: 'observed-native-firefox-locators', packageName: old.firefoxUi.packageName,
    version: old.firefoxUi.version, locators: old.firefoxUi.locators, urlCloseMode: old.firefoxUi.urlCloseMode });
  Object.assign(old.firefoxUi, { locatorEvidencePath: oldEvidence.path, locatorEvidenceSha256: oldEvidence.sha256 });
  assert.throws(() => validateFirefoxRecipe(old), /OBSERVED_LOCATORS_REQUIRED/);
  const substituted = firefoxRecipe(t);
  substituted.firefoxUi.locators.appOpen = { kind: 'text', value: 'Open CaseOps' };
  assert.throws(() => validateFirefoxRecipe(substituted), /LOCATOR_IDENTITY_MISMATCH/);
  const wrong = firefoxRecipe(t);
  wrong.firefoxUi.locators.appOpen = { kind: 'id', value: 'invented-open-control' };
  const evidence = ownedFile(t, { kind: 'observed-native-firefox-locators', packageName: wrong.firefoxUi.packageName,
    version: wrong.firefoxUi.version, locators: wrong.firefoxUi.locators, urlCloseMode: wrong.firefoxUi.urlCloseMode });
  Object.assign(wrong.firefoxUi, { locatorEvidencePath: evidence.path, locatorEvidenceSha256: evidence.sha256 });
  assert.throws(() => validateFirefoxRecipe(wrong), /EXACT_NATIVE_APP_OPEN_CONTROL_REQUIRED/);
});

test('Firefox consent recipes require hash-bound exact challenge, Verify code and verified notice locators', (t) => {
  for (const key of ['mfaCode', 'mfaSubmit', 'mfaVerified']) {
    const auth = firefoxRecipe(t, { consent: true });
    auth.firefoxUi.locators[key] = { kind: 'text', value: 'Wrong control' };
    const recipe = auth.firefoxUi;
    const evidence = ownedFile(t, { kind: 'observed-native-firefox-locators', packageName: recipe.packageName,
      version: recipe.version, locators: recipe.locators, prepare: recipe.prepare, urlCloseMode: recipe.urlCloseMode });
    Object.assign(recipe, { locatorEvidencePath: evidence.path, locatorEvidenceSha256: evidence.sha256 });
    assert.throws(() => validateFirefoxRecipe(auth), /EXACT_NATIVE/);
  }
});

test('MFA codes match independent RFC 4226/6238 SHA-1 six-digit vectors', () => {
  const secret = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';
  assert.equal(totp(secret, 0), '755224');
  assert.equal(totp(secret, 59000), '287082');
  assert.equal(totp(secret, 1111111109000), '081804');
  assert.equal(totp(secret, 2000000000000), '279037');
});
test('MFA helper fails closed for missing secret, arbitrary environment key and invalid clock', () => {
  assert.throws(() => fixtureMfaCode({ totpSecretEnv: 'PATH' }, { PATH: 'private' }), /ENV_NAME/);
  assert.throws(() => fixtureMfaCode({ totpSecretEnv: 'CASEOPS_MOBILE_TOTP' }, {}), /SECRET_REQUIRED/);
  assert.throws(() => totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', -1), /CLOCK/);
});
test('an empty but explicitly reported draft citation list is valid, not fabricated authority', (t) => {
  const fixture = coreFixture(t);
  fixture.work.draft.citations = [];
  assert.equal(validateCoreFixture(fixture, unitCredentials), fixture);
});
test('dated journal can retain a blocked call but never count it as a native pass', () => {
  const rows = strictEvents();
  rows.find((row) => row.type === 'phase_result' && row.phase === 'call').status = 'blocked';
  const result = reconcileResults(rows, ['android:A']);
  assert.equal(result.blockedCalls, 1);
  assert.equal(result.nativeCallsPassed, 0);
  assert.equal(result.status, 'incomplete-or-failed');
});

test('only exact platform-owned standalone IDs are admitted under isolated synthetic fixture', () => {
  for (const platform of ['android', 'ios']) {
    const appId = platform === 'android' ? 'ai.caseops.mobile.dev.localacceptance' : 'ai.caseops.mobile.dev.simulatoracceptance';
    const fixture = { appId, environment: 'docker-integration', syntheticDataOnly: true, coreInventory: datedInventory.inventoryId };
    assert.equal(admitApplication(fixture, platform), appId);
    assert.throws(() => admitApplication(fixture, platform === 'android' ? 'ios' : 'android'), /APP_REQUIRED/);
    for (const bad of ['ai.caseops.mobile.qa', 'ai.caseops.mobile.dev.evil', `${appId}.evil`, 'ai.caseops.mobile']) assert.throws(() => admitApplication({ ...fixture, appId: bad }, platform));
    assert.throws(() => admitApplication({ ...fixture, environment: 'production' }, platform), /ISOLATED_DOCKER/);
    assert.throws(() => admitApplication({ ...fixture, syntheticDataOnly: false }, platform), /SYNTHETIC/);
  }
});
function acceptanceReceipt(t, platform) {
  const binary = ownedFile(t, 'unit artifact only, never native E2E', 'synthetic.apk');
  const ca = ownedFile(t, 'unit public CA evidence');
  const fixture = { appId: platform === 'android' ? 'ai.caseops.mobile.dev.localacceptance' : 'ai.caseops.mobile.dev.simulatoracceptance',
    environment: 'docker-integration', syntheticDataOnly: true, coreInventory: datedInventory.inventoryId,
    binarySourceSha: 'a'.repeat(40), binarySourceFingerprint: 'b'.repeat(64), appPath: binary.path,
    apiOrigin: 'https://10.0.2.2:8443', auth: { webOrigin: 'https://10.0.2.2:3443' }, publicCa: ca };
  const proof = { platform, profile: platform === 'android' ? 'android-local-acceptance' : 'ios-simulator-acceptance',
    appId: fixture.appId, sourceSha: fixture.binarySourceSha, sourceFingerprint: fixture.binarySourceFingerprint,
    automatedTest: true, devEnabled: false, apiOrigin: fixture.apiOrigin, webOrigin: fixture.auth.webOrigin,
    artifact: fixture.appPath, binaryHash: binary.sha256, publicCaSha256: ca.sha256 };
  if (platform === 'ios') {
    const applicationIdentifier = `XCODETEAM1.${fixture.appId}`;
    proof.iosSigning = { kind: 'ios-simulator-ad-hoc-signing', appId: fixture.appId, strictVerified: true,
      signingIdentity: '-', distributionSigning: false, nativeExecution: 'not-run-by-signing-verifier',
      artifactSha256: binary.sha256, entitlementsLocation: 'Mach-O __TEXT,__entitlements',
      applicationIdentifier, keychainAccessGroups: [applicationIdentifier],
      slices: [{ architecture: 'arm64', applicationIdentifier, keychainAccessGroups: [applicationIdentifier] }],
      evidence: [ownedFile(t, 'Synthetic unit signing evidence; not actual Mac code signing.')] };
  }
  fixture.buildReceipt = ownedFile(t, proof);
  return { fixture, proof, hash: binary.sha256 };
}
test('standalone build receipts bind platform, source, artifact hash, origins and Android CA without loosening base fences', (t) => {
  for (const platform of ['android', 'ios']) {
    const { fixture, proof, hash } = acceptanceReceipt(t, platform);
    validateBuildReceipt(fixture, platform, hash);
    assert.throws(() => validateBuildReceipt({ ...fixture, buildReceipt: undefined }, platform, hash));
    assert.throws(() => validateBuildReceipt(fixture, platform, '0'.repeat(64)), /HASH_MISMATCH/);
    if (platform === 'ios') {
      const unsigned = { ...proof };
      delete unsigned.iosSigning;
      assert.throws(() => validateBuildReceipt({ ...fixture, buildReceipt: ownedFile(t, unsigned) }, platform, hash), /IOS_SIMULATOR_SIGNING_PROOF_REQUIRED/);
    }
  }
});
test('standalone receipt field substitution never authorizes another build or a debug/markerless binary', (t) => {
  const { fixture, proof, hash } = acceptanceReceipt(t, 'android');
  for (const patch of [{ sourceSha: 'c'.repeat(40) }, { sourceFingerprint: 'd'.repeat(64) }, { appId: 'ai.caseops.mobile.qa' },
    { automatedTest: false }, { devEnabled: true }, { apiOrigin: 'https://example.com' }, { publicCaSha256: '0'.repeat(64) }, { platform: 'ios' }]) {
    const copy = { ...fixture, buildReceipt: ownedFile(t, { ...proof, ...patch }) };
    assert.throws(() => validateBuildReceipt(copy, 'android', hash));
  }
});
test('dated documentation separates the passed Android core from incomplete full mobile and iOS acceptance', () => {
  const doc = readFileSync(new URL('../../docs/mobile/ANDROID_CORE_INVENTORY_2026-10-25.md', import.meta.url), 'utf8');
  assert.deepEqual([...doc.matchAll(/^\| (MOB-\d{2}) \|/gm)].map((match) => match[1]), Array.from({ length: 40 }, (_, index) => `MOB-${String(index + 1).padStart(2, '0')}`));
  assert.deepEqual([...doc.matchAll(/^\| (NATIVE-\d{2}) \|/gm)].map((match) => match[1]), EXPECTED_DATED);
  assert.ok(doc.includes('Android dated core: **23/23 passed**'));
  assert.ok(doc.includes('full mobile release remains **NO-GO**, not complete MOB-01..40 acceptance.'));
  assert.ok(doc.includes('iOS23 remain NOT RUN'));
  assert.ok(doc.includes('Historical attempts retained:'));
});

test('actual MFA-form orchestration submits one entered code and never logs its seed', async (t) => {
  browserEnvironment(t);
  const fake = domBrowserDouble({ mfa: true });
  Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: 'login', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
  await browserLogin(fake.context);
  assert.equal(fake.clicks.filter((key) => key === 'mfa-submit').length, 1);
  assert.match(fake.writes.find(([key]) => key === '#mfa-code')[1], /^\d{6}$/);
  assert.equal(JSON.stringify(fake.records).includes(process.env.CASEOPS_MOBILE_UNIT_TOTP), false);
});

test('required MFA has an explicit login or consent stage; enrollment never guesses the stage', () => {
  assert.equal(mfaStage({}), 'none');
  for (const stage of ['login', 'consent']) assert.equal(mfaStage({ mfaRequired: true, mfaStage: stage }), stage);
  for (const auth of [{ mfaRequired: true }, { mfaRequired: true, mfaStage: 'auto' },
    { mfaRequired: false, mfaStage: 'consent' }, { mfaRequired: 'true', mfaStage: 'login' }]) assert.throws(() => mfaStage(auth));
});

test('browser refuses missing MFA stage before any sign-in or credential entry', async (t) => {
  browserEnvironment(t);
  const fake = domBrowserDouble();
  fake.context.fixture.auth.mfaRequired = true;
  await assert.rejects(() => browserLogin(fake.context), /EXPLICIT_MFA_STAGE_REQUIRED/);
  assert.deepEqual(fake.clicks, []);
  assert.deepEqual(fake.writes, []);
});

test('consent MFA browser orchestration has two explicit Connect clicks around one real code submission on Android and iOS', async (t) => {
  browserEnvironment(t);
  for (const platform of ['android', 'ios']) {
    const fake = domBrowserDouble({ consent: true, platform });
    Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
    await browserLogin(fake.context);
    assert.deepEqual(fake.clicks, ['sign-in', 'link', 'submit', 'connect', 'consent-verify', 'connect', 'app-open']);
    assert.deepEqual(fake.writes.map(([key]) => key), ['#company-slug', '#email', '#password', 'native-mfa-code']);
    assert.match(fake.writes.at(-1)[1], /^\d{6}$/);
    assert.equal(JSON.stringify(fake.records).includes(process.env.CASEOPS_MOBILE_UNIT_TOTP), false);
    assert.equal(fake.isNative(), true);
  }
});

test('consent MFA refuses generic errors, failed verification, account/PKCE changes or automatic Connect without replay', async (t) => {
  browserEnvironment(t);
  for (const options of [{ noConsentChallenge: true }, { verifyRefused: true }, { wrongAfterMfa: true }, { changedAfterMfa: true }, { autoConnect: true }]) {
    const fake = domBrowserDouble({ consent: true, ...options });
    Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
    await assert.rejects(() => browserLogin(fake.context));
    assert.equal(fake.clicks.filter((key) => key === 'connect').length, 1);
    assert.ok(fake.clicks.filter((key) => key === 'consent-verify').length <= 1);
    assert.equal(fake.isNative(), true);
  }
});

test('login-stage and consent-stage MFA challenges cannot silently substitute for each other', async (t) => {
  browserEnvironment(t);
  for (const [options, stage] of [[{}, 'login'], [{ mfa: true }, 'consent']]) {
    const fake = domBrowserDouble(options);
    Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: stage, totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
    await assert.rejects(() => browserLogin(fake.context), /BROWSER_LOGIN_MFA_STAGE_MISMATCH/);
    assert.equal(fake.clicks.includes('connect'), false);
    assert.equal(fake.writes.some(([key]) => key.includes('mfa-code')), false);
  }
});

test('authorization receipts distinguish the consent 403 attempt from the sole successful grant and token exchange', () => {
  const authorize = (status) => ({ method: 'POST', route: '/api/auth/native/authorize', status });
  const token = (status = 200) => ({ method: 'POST', route: '/api/auth/native/token', status });
  const consent = { mfaRequired: true, mfaStage: 'consent' };
  const verification = { method: 'POST', route: '/api/auth/mfa/step-up', status: 200 };
  const identity = { method: 'GET', route: '/api/auth/me', status: 200 };
  const success = [authorize(403), verification, identity, authorize(200), token()];
  validateAuthorizationTraffic(success, consent, { single: true });
  validateAuthorizationTraffic([...success, ...structuredClone(success)], consent);
  validateAuthorizationTraffic([authorize(200), token()], { mfaRequired: true, mfaStage: 'login' }, { single: true });
  for (const rows of [[], [authorize(403)], [authorize(200), token()], [authorize(403), authorize(403), authorize(200), token()],
    [authorize(403), token(), authorize(200)], [authorize(403), authorize(200), token(401)],
    [authorize(403), authorize(200), token(), token()], [authorize(401), authorize(200), token()],
    [authorize(403), authorize(200), { ...token(), status: null }]]) {
    assert.throws(() => validateAuthorizationTraffic(rows, consent));
  }
  assert.throws(() => validateAuthorizationTraffic([...success, ...success], consent, { single: true }));
  assert.throws(() => validateAuthorizationTraffic(success, {}));
  for (const window of [[], [verification], [identity, verification], [verification, verification, identity],
    [{ ...verification, status: 403 }, identity], [verification, { ...identity, status: 401 }]]) {
    assert.throws(() => validateAuthorizationTraffic([authorize(403), ...window, authorize(200), token()], consent));
  }
});

// These deterministic accessibility doubles test Firefox orchestration only.
// Their recipe is deliberately synthetic and is never a native observation.
function firefoxDouble(t, foreign = false, options = {}) {
  const auth = firefoxRecipe(t, options);
  let stage = 'app', editing = false, verified = false, backCount = 0, consentCodeEntered = false;
  let fullBrowser = !options.prepare?.length || options.fullBrowserInitially === true;
  let clock = 0, connectedAt = 0, verifiedAt = 0, grantAt = 0, promptAt = 0, noticeCleared = false, promptCleared = false, lastLookup, promptIndex = 0;
  const writes = [], clicks = [], records = [], swipes = [], waits = [], refreshes = [];
  const values = auth.firefoxUi.locators;
  const fixture = { appId: 'ai.caseops.mobile.dev.localacceptance', principalLabel: 'Unit Person', workspaceLabel: 'Unit Workspace',
    auth: { ...auth, mode: 'native-firefox', webOrigin: 'https://10.0.2.2:3443', companySlug: 'unit', emailEnv: 'CASEOPS_MOBILE_UNIT_EMAIL', passwordEnv: 'CASEOPS_MOBILE_UNIT_PASSWORD' } };
  const driver = {
    switchContext: async (name) => assert.equal(name, 'NATIVE_APP'),
    getCurrentPackage: async () => stage === 'complete' ? fixture.appId : 'org.mozilla.firefox',
    pressKeyCode: async (code) => {
      assert.equal(code, 4); assert.equal(editing, true, 'BACK_MUST_NOT_NAVIGATE_WHEN_EDITOR_CLOSED');
      clicks.push('android-back'); if (++backCount >= (options.backPressesRequired || 1)) editing = false;
    },
    waitUntil: async (callback, settings = {}) => {
      if (options.chromeDelayMs === undefined && options.connectDelayMs === undefined && options.verifiedNoticeDelayMs === undefined && options.appOpenDelayMs === undefined && options.promptDelaysMs === undefined && options.entryDelayMs === undefined && !options.lowerFieldsNeedScroll) {
        return assert.ok(await callback(), 'UNIT_WAIT_UNSATISFIED');
      }
      const start = clock, timeout = settings.timeout ?? 10000, interval = settings.interval ?? 150;
      const wait = { key: undefined, timeout, start };
      waits.push(wait);
      for (;;) {
        const satisfied = await callback();
        wait.key ??= lastLookup;
        if (satisfied) return;
        if (clock - start >= timeout) throw new Error(settings.timeoutMsg || 'UNIT_WAIT_UNSATISFIED');
        clock += Math.min(interval, timeout - (clock - start));
      }
    },
    getWindowRect: async () => ({ width: 400, height: 800 }),
    performActions: async () => {
      swipes.push('scroll');
      if (options.connectDelayMs !== undefined && stage === 'connect' && clock - connectedAt < options.connectDelayMs) {
        stage = 'login';
        refreshes.push('GET /sign-in');
      }
      if (options.verifiedNoticeDelayMs !== undefined && verified) {
        noticeCleared = true;
        refreshes.push('GET /api/auth/me');
      }
      if (options.promptDelaysMs && stage === 'prompt') {
        promptCleared = true;
        refreshes.push('GET /api/auth/me');
      }
    },
    releaseActions: async () => {},
    $$: async (query) => {
      const preparationIndex = auth.firefoxUi.prepare.findIndex((locator) => query === selector('android', locator.kind, locator.value));
      const afterConnectIndex = auth.firefoxUi.afterConnect.findIndex((locator) => query === selector('android', locator.kind, locator.value));
      const key = query === 'id=sign-in' ? 'sign-in' : query === 'id=account-open' ? 'account-open'
        : Object.keys(values).find((name) => query === selector('android', values[name].kind, values[name].value))
          || (preparationIndex >= 0 ? `prepare-${preparationIndex}` : afterConnectIndex >= 0 ? `prompt-${afterConnectIndex}` : undefined);
      lastLookup = key;
      const shown = key === 'sign-in' ? stage === 'app' : key === 'account-open' ? stage === 'complete'
        : key === 'fullBrowser' ? fullBrowser && stage !== 'app' && stage !== 'complete' && !editing && clock >= (options.chromeDelayMs ?? 0)
        : key === 'urlOpen' ? (fullBrowser || options.customTabUrlShared) && stage !== 'app' && stage !== 'complete' && !editing && clock >= (options.chromeDelayMs ?? 0)
        : ['urlValue', 'urlClose'].includes(key) ? editing
        : key === 'signInLink' ? stage === 'landing' && !editing && clock >= (options.entryDelayMs ?? 0)
        : ['companySlug', 'email', 'password', 'submit'].includes(key) ? stage === 'login' && !editing
          && (key === 'companySlug' || !options.lowerFieldsNeedScroll || swipes.length > 0)
        : ['principal', 'emailFact', 'workspace', 'connect'].includes(key) ? stage === 'connect' && !editing
          && clock - connectedAt >= (options.connectDelayMs ?? 0)
        : ['mfaCode', 'mfaSubmit'].includes(key) ? stage === 'consent-mfa' && !editing
          && (key !== 'mfaSubmit' || !options.submitHiddenUntilCode || consentCodeEntered)
        : key === 'mfaVerified' ? verified && stage === 'connect' && !editing && !noticeCleared
          && clock - verifiedAt >= (options.verifiedNoticeDelayMs ?? 0)
        : key === 'appOpen' ? stage === 'grant' && !editing && !options.appOpenMissing && clock - grantAt >= (options.appOpenDelayMs ?? 0)
        : key && key.startsWith('prompt-') ? stage === 'prompt' && key === `prompt-${promptIndex}` && !promptCleared
          && clock - promptAt >= (options.promptDelaysMs?.[promptIndex] ?? 0)
        : key && key.startsWith('prepare-') ? stage === 'landing' && clock >= (options.chromeDelayMs ?? 0) : false;
      if (!shown) return [];
      return [{ isDisplayed: async () => true, isEnabled: async () => key !== 'appOpen' || !options.appOpenDisabled,
        setValue: async (value) => { writes.push([key, value]); if (key === 'mfaCode') consentCodeEntered = /^\d{6}$/.test(value); },
        getText: async () => {
          if (key === 'urlValue') {
            const target = new URL(authUrl(foreign ? 'https://example.com' : fixture.auth.webOrigin));
            if (verified && options.changedAfterMfa) target.searchParams.set('state', 'c'.repeat(64));
            return stage === 'login' ? `${target.origin}/sign-in?${new URLSearchParams({ next: target.pathname + target.search })}` : target.href;
          }
          return { principal: verified && options.wrongAfterMfa ? 'Wrong' : fixture.principalLabel, emailFact: 'unit@example.invalid',
            workspace: 'Unit Workspace / unit', connect: 'Connect app', mfaSubmit: 'Verify code', mfaVerified: CONSENT_MFA_VERIFIED,
            appOpen: options.wrongAppOpenLabel ? 'Wrong button' : 'Open CaseOps' }[key] || '';
        },
        click: async () => {
          clicks.push(key);
          if (key === 'sign-in') stage = options.directForm ? 'login' : 'landing';
          if (key === `prepare-${auth.firefoxUi.prepare.length - 1}` && !options.neverFullBrowser) fullBrowser = true;
          if (key === 'urlOpen') { editing = true; backCount = 0; }
          if (key === 'urlClose') editing = false;
          if (key === 'signInLink') stage = 'login';
          if (key === 'submit') { stage = 'connect'; connectedAt = clock; }
          if (key === 'connect') {
            stage = options.consent && !verified ? options.noConsentChallenge ? 'connect' : 'consent-mfa' : 'grant';
            if (stage === 'grant') grantAt = clock;
          }
          if (key === 'appOpen') { stage = auth.firefoxUi.afterConnect.length ? 'prompt' : 'complete'; promptAt = clock; }
          if (key?.startsWith('prompt-')) {
            promptAt = clock;
            if (++promptIndex === auth.firefoxUi.afterConnect.length) stage = 'complete';
          }
          if (key === 'mfaSubmit' && !options.verifyRefused) { verified = true; verifiedAt = clock; stage = options.autoConnect ? 'complete' : 'connect'; }
        } }];
    },
  };
  return { context: { driver: nativeProtocolDouble(driver), fixture, platform: 'android', record: (row) => records.push(row) }, writes, clicks, records, swipes, waits, refreshes,
    elapsed: () => clock };
}

test('Firefox waits for a delayed observed entry before any credential write without scrolling or replay', async t => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { entryDelayMs: 4011 });
  t.mock.method(Date, 'now', () => fake.elapsed());
  await browserLogin(fake.context);
  assert.equal(fake.clicks.filter(key => key === 'signInLink').length, 1);
  assert.equal(fake.clicks.filter(key => key === 'submit').length, 1);
  assert.equal(fake.swipes.length, 0);
  assert.deepEqual(fake.writes.slice(0, 3).map(([key]) => key), ['companySlug', 'email', 'password']);
  assert.ok(fake.elapsed() >= 4011 && fake.elapsed() <= 20000);
});

function firefoxEntryDouble(t, state, { dispatchFailure, lostAcknowledgement = false, readFailure } = {}) {
  const recipe = validateFirefoxRecipe(firefoxRecipe(t, { entryLocators: { useAnotherAccount: { kind: 'label', value: 'Use another account' } } }));
  let clock = 0, polling = false, wrapperClicks = 0, swallowed = 0;
  const attempts = [], acknowledged = [], queries = [], waits = [], records = [];
  const driver = {
    getCurrentPackage: async () => recipe.packageName,
    $$: async query => {
      if (readFailure) throw readFailure;
      const key = Object.keys(recipe.locators).find(name => query === selector('android', recipe.locators[name].kind, recipe.locators[name].value));
      queries.push(key);
      const count = state({ key, clock, acknowledged, attempts }) ?? 0;
      return Array.from({ length: typeof count === 'number' ? count : 1 }, (_, index) => ({ elementId: `${key}-original-${index}`,
        isDisplayed: async () => true, isEnabled: async () => count !== 'disabled',
        click: async () => { wrapperClicks++; assert.fail('ENTRY_ELEMENT_CLICK_MUST_NOT_BE_CALLED'); } }));
    },
    elementClick: async id => {
      assert.equal(polling, false, 'ENTRY_CLICK_MUST_BE_OUTSIDE_POLL'); attempts.push({ id, clock, queries: queries.length });
      if (!dispatchFailure || lostAcknowledgement) acknowledged.push({ id, clock });
      if (dispatchFailure) throw dispatchFailure;
    },
    waitUntil: async (callback, settings) => {
      const start = clock; waits.push({ start, ...settings });
      for (;;) {
        polling = true;
        try { if (await callback()) return; } catch { swallowed++; }
        finally { polling = false; }
        if (clock - start >= settings.timeout) throw Error(settings.timeoutMsg);
        clock += Math.min(settings.interval, settings.timeout - (clock - start));
      }
    },
  };
  t.mock.method(Date, 'now', () => clock);
  return { recipe, context: { driver, platform: 'android', record: event => records.push(event) }, attempts, acknowledged, queries, waits,
    elapsed: () => clock, wrapperClicks: () => wrapperClicks, swallowed: () => swallowed, records };
}

test('Firefox direct form anchor retains normal lower-field scrolling without an entry navigation', async t => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { directForm: true, lowerFieldsNeedScroll: true });
  t.mock.method(Date, 'now', () => fake.elapsed());
  await browserLogin(fake.context);
  assert.equal(fake.clicks.filter(key => key === 'signInLink').length, 0);
  assert.equal(fake.swipes.length, 1);
  assert.deepEqual(fake.writes.slice(0, 3).map(([key]) => key), ['companySlug', 'email', 'password']);
  assert.equal(fake.clicks.filter(key => key === 'submit').length, 1);
});

test('Firefox acknowledged entry lingering while the form loads waits without a second dispatch', async t => {
  const fake = firefoxEntryDouble(t, ({ key, clock, acknowledged }) => !acknowledged.length ? Number(key === 'useAnotherAccount')
    : Number(clock < 4500 ? key === 'useAnotherAccount' : key === 'companySlug'));
  await resolveFirefoxEntry(fake.context, fake.recipe);
  assert.equal(fake.attempts.length, 1); assert.equal(fake.attempts[0].id, 'useAnotherAccount-original-0');
  assert.equal(fake.elapsed(), 4500); assert.equal(fake.wrapperClicks(), 0); assert.equal(fake.swallowed(), 0);
  assert.ok(fake.waits[1].timeout <= 20000);
});

test('Firefox unknown or disabled entry states exhaust one 20 second bound without credentials or gestures', async t => {
  for (const state of [() => 0, ({ key }) => key === 'useAnotherAccount' ? 'disabled' : 0]) {
    const fake = firefoxEntryDouble(t, state);
    await assert.rejects(resolveFirefoxEntry(fake.context, fake.recipe), /FIREFOX_ENTRY_NOT_READY/);
    assert.equal(fake.elapsed(), 20000); assert.equal(fake.attempts.length, 0); assert.equal(fake.wrapperClicks(), 0);
  }
});

test('Firefox entry ambiguity and read transport failures remain terminal rather than waitUntil-swallowed', async t => {
  for (const state of [({ key }) => key === 'companySlug' ? 2 : 0,
    ({ key }) => Number(['useAnotherAccount', 'signInLink'].includes(key)),
    ({ key }) => Number(['companySlug', 'useAnotherAccount'].includes(key))]) {
    const fake = firefoxEntryDouble(t, state);
    await assert.rejects(resolveFirefoxEntry(fake.context, fake.recipe), /AMBIGUOUS/);
    assert.equal(fake.elapsed(), 0); assert.equal(fake.attempts.length, 0); assert.equal(fake.swallowed(), 0);
  }
  const failure = Error('UNIT_ENTRY_TRANSPORT_CLOSED'), fake = firefoxEntryDouble(t, () => 0, { readFailure: failure });
  await assert.rejects(resolveFirefoxEntry(fake.context, fake.recipe), error => error === failure);
  assert.equal(fake.elapsed(), 0); assert.equal(fake.swallowed(), 0); assert.equal(fake.attempts.length, 0);
});

test('Firefox entry stale and lost acknowledgements dispatch original ID once without refetch or wrapper replay', async t => {
  for (const lostAcknowledgement of [false, true]) {
    const failure = Error(lostAcknowledgement ? 'UNIT_ENTRY_ACK_UNKNOWN' : 'UNIT_ENTRY_STALE');
    const fake = firefoxEntryDouble(t, ({ key }) => Number(key === 'useAnotherAccount'), { dispatchFailure: failure, lostAcknowledgement });
    await assert.rejects(resolveFirefoxEntry(fake.context, fake.recipe), error => error === failure);
    assert.equal(fake.attempts.length, 1); assert.equal(fake.attempts[0].id, 'useAnotherAccount-original-0');
    assert.equal(fake.queries.length, fake.attempts[0].queries); assert.equal(fake.wrapperClicks(), 0); assert.equal(fake.elapsed(), 0);
    assert.equal(fake.acknowledged.length, lostAcknowledgement ? 1 : 0);
  }
});

test('Firefox optional transitions share the original deadline instead of starting another 20 seconds', async t => {
  const fake = firefoxEntryDouble(t, ({ key, clock, acknowledged }) => {
    if (clock < 12000) return 0;
    if (!acknowledged.length) return Number(key === 'useAnotherAccount');
    if (clock < 18000) return Number(key === 'useAnotherAccount');
    if (acknowledged.length === 1) return Number(key === 'signInLink');
    return Number(key === 'signInLink');
  });
  await assert.rejects(resolveFirefoxEntry(fake.context, fake.recipe), /FIREFOX_ENTRY_NOT_READY/);
  assert.equal(fake.elapsed(), 20000); assert.equal(fake.attempts.length, 2);
  assert.deepEqual(fake.attempts.map(row => row.id), ['useAnotherAccount-original-0', 'signInLink-original-0']);
  assert.ok(fake.waits[1].timeout <= 8000 && fake.waits[2].timeout <= 2000); assert.equal(fake.wrapperClicks(), 0);
});

test('actual Android Firefox wrapper dispatches resolved submit, consent, MFA and app-open IDs once after stale/lost acknowledgements', async t => {
  browserEnvironment(t);
  for (const key of ['submit', 'connect', 'mfaSubmit', 'appOpen']) for (const lostAcknowledgement of [false, true]) {
    const fake = firefoxDouble(t, false, { consent: true }), { driver } = fake.context;
    const locator = fake.context.fixture.auth.firefoxUi.locators[key], query = selector('android', locator.kind, locator.value);
    const lookup = driver.$$.bind(driver), rawClick = driver.elementClick.bind(driver);
    let resolvedId, lookups = 0, lookupsAtFailure, wrapperClicks = 0;
    const dispatched = [], failure = new Error(lostAcknowledgement ? 'UNIT_NATIVE_CLICK_ACK_UNKNOWN' : 'UNIT_STALE_NATIVE_ELEMENT');
    driver.$$ = async value => {
      lookups++;
      const controls = await lookup(value);
      if (value === query) for (const element of controls) {
        resolvedId = element.elementId;
        element.click = async () => { wrapperClicks++; throw new Error('ELEMENT_CLICK_WRAPPER_MUST_NOT_BE_CALLED'); };
      }
      return controls;
    };
    driver.elementClick = async id => {
      dispatched.push(id);
      if (id !== resolvedId) return rawClick(id);
      if (lostAcknowledgement) await rawClick(id);
      lookupsAtFailure = lookups;
      throw failure;
    };
    await assert.rejects(browserLogin(fake.context), error => error === failure);
    assert.equal(wrapperClicks, 0); assert.equal(dispatched.filter(id => id === resolvedId).length, 1);
    assert.equal(lookups, lookupsAtFailure, 'FAILED_NATIVE_CLICK_MUST_NOT_REFETCH');
    assert.equal(fake.clicks.filter(value => value === key).length, lostAcknowledgement ? 1 : 0);
    assert.equal(fake.records.some(event => event.type === 'browser_step' && event.key === 'native-return'), false);
    assert.ok(!JSON.stringify(fake.records).includes('unit-only'));
  }
});

test('current Android Firefox and Files wrappers contain no refetching element click calls', () => {
  for (const file of ['firefox-handoff.mjs', 'files-20261025.mjs']) {
    const source = readFileSync(new URL(`../../apps/mobile/e2e/${file}`, import.meta.url), 'utf8');
    assert.equal(/\.click\s*\(/.test(source), false, file);
    assert.ok(source.includes('dispatchNativeClick('), file);
  }
});

test('Firefox already-full browser skips Custom Tab menu conversion but retains MFA, PKCE and one explicit grant', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, androidBack: true, fullBrowserInitially: true,
    prepare: [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }] });
  await browserLogin(fake.context);
  assert.deepEqual(fake.clicks.filter(key => key.startsWith('prepare-')), []);
  assert.equal(fake.clicks.filter(key => key === 'mfaSubmit').length, 1);
  assert.equal(fake.clicks.filter(key => key === 'connect').length, 2);
  assert.equal(fake.clicks.filter(key => key === 'appOpen').length, 1);
});

test('Firefox Custom Tab sharing the URL box still requires observed full-browser conversion', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, customTabUrlShared: true,
    prepare: [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }] });
  await browserLogin(fake.context);
  assert.deepEqual(fake.clicks.filter(key => key.startsWith('prepare-')), ['prepare-0', 'prepare-1']);
  assert.ok(fake.records.some(({ key, action }) => key === 'fullBrowser' && action === 'find'));
  assert.deepEqual(fake.swipes, []);
});

test('Firefox conversion without the full-browser marker fails before entering credentials', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, customTabUrlShared: true, neverFullBrowser: true,
    prepare: [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }] });
  await assert.rejects(() => browserLogin(fake.context), /NATIVE_CONTROL_NOT_VISIBLE/);
  assert.deepEqual(fake.writes, []);
  assert.deepEqual(fake.clicks.filter(key => ['submit', 'connect', 'mfaSubmit', 'appOpen'].includes(key)), []);
  assert.deepEqual(fake.swipes, []);
});

test('Firefox already-full browser still rejects an external origin before entering credentials', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, true, { androidBack: true, fullBrowserInitially: true,
    prepare: [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }] });
  await assert.rejects(browserLogin(fake.context), /UNSAFE_BROWSER_ORIGIN/);
  assert.deepEqual(fake.writes, []);
  assert.deepEqual(fake.clicks.filter(key => key.startsWith('prepare-')), []);
});

test('Firefox cold chrome settles without scrolling before the observed Custom Tab menu actions', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, chromeDelayMs: 4011,
    prepare: [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }] });
  await browserLogin(fake.context);
  assert.ok(fake.elapsed() >= 4011 && fake.elapsed() <= 10000);
  assert.deepEqual(fake.clicks.filter(key => key.startsWith('prepare-')), ['prepare-0', 'prepare-1']);
  assert.deepEqual(fake.swipes, []);
});

test('Firefox unavailable chrome fails before credentials, scrolling or menu actions at its 10s bound', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, chromeDelayMs: 10001,
    prepare: [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }] });
  await assert.rejects(() => browserLogin(fake.context), /FIREFOX_BROWSER_CHROME_NOT_READY/);
  assert.equal(fake.elapsed(), 10000);
  assert.deepEqual(fake.writes, []);
  assert.deepEqual(fake.clicks, ['sign-in']);
  assert.deepEqual(fake.swipes, []);
});

test('Firefox native UI orchestration inspects location, fills labelled controls and connects exactly once', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t);
  await browserLogin(fake.context);
  assert.deepEqual(fake.writes.map(([key]) => key), ['companySlug', 'email', 'password']);
  assert.equal(fake.clicks.filter((key) => key === 'submit').length, 1);
  assert.equal(fake.clicks.filter((key) => key === 'connect').length, 1);
  assert.equal(fake.clicks.filter((key) => key === 'urlValue').length, 0);
  assert.equal(JSON.stringify(fake.records).includes('unit-only-password'), false);
});
test('Firefox native UI refuses an external address before entering any credential', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, true);
  await assert.rejects(() => browserLogin(fake.context), /UNSAFE_BROWSER_ORIGIN/);
  assert.deepEqual(fake.writes, []);
  assert.equal(fake.clicks.includes('connect'), false);
});

test('Firefox consent MFA submits one code between exactly two explicit Connect actions (unit accessibility double)', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true });
  await browserLogin(fake.context);
  assert.deepEqual(fake.writes.map(([key]) => key), ['companySlug', 'email', 'password', 'mfaCode']);
  assert.deepEqual(fake.clicks.filter((key) => ['connect', 'mfaSubmit'].includes(key)), ['connect', 'mfaSubmit', 'connect']);
  assert.equal(JSON.stringify(fake.records).includes(process.env.CASEOPS_MOBILE_UNIT_TOTP), false);
});

test('Firefox explicitly opens the granted app callback once before its observed normal browser prompt', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, afterConnect: [{ kind: 'label', value: 'Open in App' }] });
  await browserLogin(fake.context);
  assert.deepEqual(fake.clicks.filter((key) => ['connect', 'mfaSubmit', 'appOpen', 'prompt-0'].includes(key)),
    ['connect', 'mfaSubmit', 'connect', 'appOpen', 'prompt-0']);
  assert.equal(fake.records.filter(({ type, key, action }) => type === 'browser_step' && key === 'appOpen' && action === 'click').length, 1);
});

test('both bounded afterConnect prompt keys wait 10s without gestures when their observed controls arrive asynchronously', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, promptDelaysMs: [4011, 2300],
    afterConnect: [{ kind: 'label', value: 'Unit prompt one' }, { kind: 'label', value: 'Unit prompt two' }] });
  await browserLogin(fake.context);
  for (const key of ['prompt-0', 'prompt-1']) assert.ok(fake.waits.some((wait) => wait.key === key && wait.timeout === 10000));
  assert.deepEqual(fake.swipes, []);
  assert.deepEqual(fake.refreshes, []);
  assert.deepEqual(fake.clicks.filter((key) => ['connect', 'mfaSubmit', 'appOpen', 'prompt-0', 'prompt-1'].includes(key)),
    ['connect', 'mfaSubmit', 'connect', 'appOpen', 'prompt-0', 'prompt-1']);
  assert.ok(fake.elapsed() >= 6311 && fake.elapsed() < 20000);
});

test('either missing afterConnect prompt fails at its one 10s bound without scrolling, callback replay or another grant', async (t) => {
  browserEnvironment(t);
  for (const missing of [0, 1]) {
    const delays = [0, 0]; delays[missing] = 10001;
    const fake = firefoxDouble(t, false, { consent: true, promptDelaysMs: delays,
      afterConnect: [{ kind: 'label', value: 'Unit prompt one' }, { kind: 'label', value: 'Unit prompt two' }] });
    await assert.rejects(() => browserLogin(fake.context), /NATIVE_CONTROL_NOT_VISIBLE/);
    assert.equal(fake.elapsed(), 10000);
    assert.deepEqual(fake.swipes, []);
    assert.deepEqual(fake.refreshes, []);
    assert.equal(fake.clicks.filter((key) => key === 'appOpen').length, 1);
    assert.equal(fake.clicks.filter((key) => key === 'connect').length, 2);
    assert.equal(fake.clicks.filter((key) => key.startsWith('prompt-')).length, missing);
    assert.equal(fake.records.filter(({ type }) => type === 'browser_step').at(-1).key, `afterConnect-${missing}`);
  }
});

test('Firefox waits for a delayed grant-backed Open CaseOps button without refreshing or reauthorizing', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, appOpenDelayMs: 4011 });
  await browserLogin(fake.context);
  assert.ok(fake.waits.some(({ key, timeout }) => key === 'appOpen' && timeout === 10000));
  assert.deepEqual(fake.swipes, []);
  assert.deepEqual(fake.refreshes, []);
  assert.equal(fake.clicks.filter((key) => key === 'connect').length, 2);
  assert.equal(fake.clicks.filter((key) => key === 'appOpen').length, 1);
});

test('Firefox missing, disabled/expired or wrongly labelled app-open control cannot retry Connect or fabricate a native return', async (t) => {
  browserEnvironment(t);
  for (const options of [{ appOpenMissing: true }, { appOpenDisabled: true }, { wrongAppOpenLabel: true }]) {
    const fake = firefoxDouble(t, false, { consent: true, ...options });
    await assert.rejects(() => browserLogin(fake.context));
    assert.equal(fake.clicks.filter((key) => key === 'connect').length, 2);
    assert.equal(fake.clicks.filter((key) => key === 'mfaSubmit').length, 1);
    assert.equal(fake.clicks.filter((key) => key === 'appOpen').length, 0);
    assert.deepEqual(fake.swipes, []);
  }
});

test('Android/iOS web-context flow clicks fixed app-open control once after the final explicit Connect', async (t) => {
  browserEnvironment(t);
  for (const platform of ['android', 'ios']) {
    const fake = domBrowserDouble({ consent: true, platform });
    Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
    await browserLogin(fake.context);
    assert.deepEqual(fake.clicks.filter((key) => ['connect', 'consent-verify', 'app-open'].includes(key)),
      ['connect', 'consent-verify', 'connect', 'app-open']);
    assert.equal(fake.records.filter(({ type, key, action }) => type === 'browser_step' && key === 'appOpen' && action === 'click').length, 1);
  }
});

test('web-context missing or disabled app-open button fails without renewing a grant or clicking the expired callback', async (t) => {
  browserEnvironment(t);
  for (const options of [{ appOpenMissing: true }, { appOpenDisabled: true }, { wrongAppOpenLabel: true }]) {
    const fake = domBrowserDouble({ consent: true, ...options });
    Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
    await assert.rejects(() => browserLogin(fake.context));
    assert.equal(fake.clicks.filter((key) => key === 'connect').length, 2);
    assert.equal(fake.clicks.filter((key) => key === 'app-open').length, 0);
    assert.equal(fake.isNative(), true);
  }
});

test('Firefox consent fills six digits before looking up Verify code hidden from Gecko accessibility while disabled', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, submitHiddenUntilCode: true });
  await browserLogin(fake.context);
  assert.match(fake.writes.find(([key]) => key === 'mfaCode')[1], /^\d{6}$/);
  assert.deepEqual(fake.clicks.filter((key) => ['connect', 'mfaSubmit'].includes(key)), ['connect', 'mfaSubmit', 'connect']);
  assert.deepEqual(fake.swipes, []);
});

test('Firefox waits for post-login consent without a pull-to-refresh that cancels navigation', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, connectDelayMs: 4011 });
  await browserLogin(fake.context);
  assert.ok(fake.elapsed() >= 4011 && fake.elapsed() <= 10000);
  assert.ok(fake.waits.some(({ key, timeout }) => key === 'connect' && timeout === 10000));
  assert.deepEqual(fake.swipes, []);
  assert.deepEqual(fake.refreshes, []);
  assert.deepEqual(fake.clicks.filter(key => ['submit', 'connect', 'mfaSubmit', 'appOpen'].includes(key)),
    ['submit', 'connect', 'mfaSubmit', 'connect', 'appOpen']);
});

test('Firefox absent post-login consent fails at 10s without scrolling, another login or authorization', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, connectDelayMs: 10001 });
  await assert.rejects(() => browserLogin(fake.context), /NATIVE_CONTROL_NOT_VISIBLE/);
  assert.equal(fake.elapsed(), 10000);
  assert.deepEqual(fake.swipes, []);
  assert.deepEqual(fake.refreshes, []);
  assert.deepEqual(fake.clicks.filter(key => ['submit', 'connect', 'mfaSubmit', 'appOpen'].includes(key)), ['submit']);
});

test('Firefox waits without scrolling for the exact MFA verified notice arriving after 4011ms, retaining explicit second Connect', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, submitHiddenUntilCode: true, verifiedNoticeDelayMs: 4011 });
  await browserLogin(fake.context);
  assert.ok(fake.elapsed() >= 4011 && fake.elapsed() <= 10000);
  assert.ok(fake.waits.some(({ key, timeout }) => key === 'mfaVerified' && timeout === 10000));
  assert.deepEqual(fake.swipes, []);
  assert.deepEqual(fake.refreshes, []);
  assert.deepEqual(fake.clicks.filter((key) => ['connect', 'mfaSubmit'].includes(key)), ['connect', 'mfaSubmit', 'connect']);
  assert.equal(fake.records.filter(({ type, key, action }) => type === 'browser_step' && key === 'mfaVerified' && action === 'find').length, 1);
});

test('Firefox missing MFA verified notice fails at the bounded 10s wait without refresh, replay or second Connect', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, submitHiddenUntilCode: true, verifiedNoticeDelayMs: 10001 });
  await assert.rejects(() => browserLogin(fake.context), /NATIVE_CONTROL_NOT_VISIBLE/);
  assert.equal(fake.elapsed(), 10000);
  assert.deepEqual(fake.swipes, []);
  assert.deepEqual(fake.refreshes, []);
  assert.deepEqual(fake.clicks.filter((key) => ['connect', 'mfaSubmit'].includes(key)), ['connect', 'mfaSubmit']);
  assert.equal(fake.records.filter(({ type }) => type === 'browser_step').at(-1).key, 'mfaVerified');
});

test('runner configures and verifies real UiAutomator2 ID settings before UI commands, not an ignored capability', () => {
  const source = readFileSync(new URL('./run-native.mjs', import.meta.url), 'utf8');
  assert.equal(/appium:disableIdLocatorAutocompletion/.test(source), false, 'UNRECOGNIZED_ID_CAPABILITY_MUST_BE_ABSENT');
  const configure = source.indexOf('await configureNativeDriver(');
  assert.ok(configure > source.indexOf('appiumSessionEvent(driver.sessionId'));
  assert.ok(configure < source.indexOf('const contexts = await driver.getContexts()'));
  assert.equal(/allowInvisibleElements|mapTestTagToResourceId/.test(source), false);
  assert.ok(source.indexOf('authGate.assertSetup()') < source.indexOf('driver = await remote('));
  assert.ok(source.includes("authGate.failInitial(scenario, 'call')"));
});

test('browser-step journals accept only fixed action/key names and never arbitrary URL, selector or credential values', () => {
  const records = [], context = { record: (event) => records.push(event) };
  browserStep(context, 'password', 'fill');
  assert.deepEqual(records, [{ type: 'browser_step', key: 'password', action: 'fill' }]);
  for (const [key, action] of [['https://unit.invalid/?code=unit-secret', 'read'], ['unit@example.invalid', 'fill'],
    ['unit-only-password', 'fill'], ['mfaCode', '123456'], ['mfaCode', { value: 'unit-secret' }]]) {
    assert.throws(() => browserStep(context, key, action), /SAFE_BROWSER_STEP_NAME_REQUIRED/);
  }
  assert.equal(records.length, 1);
});

test('Firefox journals each recipe action before execution and fills MFA before any submit lookup without secret values', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, submitHiddenUntilCode: true, androidBack: true,
    prepare: [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }] });
  await browserLogin(fake.context);
  const steps = fake.records.filter(({ type }) => type === 'browser_step');
  const fill = steps.findIndex(({ key, action }) => key === 'mfaCode' && action === 'fill');
  const submit = steps.findIndex(({ key, action }) => key === 'mfaSubmit' && action === 'find');
  assert.ok(fill >= 0 && submit > fill);
  for (const key of ['prepare-0', 'prepare-1', 'urlOpen', 'urlValue', 'urlEditor', 'companySlug', 'email', 'password', 'submit',
    'principal', 'emailFact', 'workspace', 'connect', 'mfaCode', 'mfaSubmit', 'mfaVerified', 'appOpen', 'native-return']) {
    assert.ok(steps.some((step) => step.key === key), key);
  }
  assert.equal(steps.filter(({ key, action }) => key === 'connect' && action === 'click').length, 2);
  for (const step of steps) assert.deepEqual(Object.keys(step), ['type', 'key', 'action']);
  const serialized = JSON.stringify(steps);
  for (const value of [fake.context.fixture.auth.webOrigin, 'unit@example.invalid', 'unit-only-password',
    process.env.CASEOPS_MOBILE_UNIT_TOTP, fake.writes.find(([key]) => key === 'mfaCode')[1], 'More options', 'native-mfa-code']) {
    assert.equal(serialized.includes(value), false);
  }
});

test('a Firefox locator failure retains the exact last nonsecret recipe stage rather than a generic final-only error', async (t) => {
  browserEnvironment(t);
  const fake = firefoxDouble(t, false, { consent: true, noConsentChallenge: true });
  await assert.rejects(() => browserLogin(fake.context), /NATIVE_CONTROL_NOT_VISIBLE/);
  assert.deepEqual(fake.records.filter(({ type }) => type === 'browser_step').at(-1), { type: 'browser_step', key: 'mfaCode', action: 'find' });
  assert.equal(fake.writes.some(([key]) => key === 'mfaCode'), false);
  assert.equal(fake.clicks.filter((key) => key === 'connect').length, 1);
});

test('web-context consent journals fill-before-submit and two explicit Connect actions without browser contents', async (t) => {
  browserEnvironment(t);
  const fake = domBrowserDouble({ consent: true });
  Object.assign(fake.context.fixture.auth, { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' });
  await browserLogin(fake.context);
  const steps = fake.records.filter(({ type }) => type === 'browser_step');
  assert.ok(steps.findIndex(({ key, action }) => key === 'mfaCode' && action === 'fill')
    < steps.findIndex(({ key, action }) => key === 'mfaSubmit' && action === 'find'));
  assert.equal(steps.filter(({ key, action }) => key === 'connect' && action === 'click').length, 2);
  assert.equal(JSON.stringify(steps).includes('unit-only-password'), false);
  assert.equal(JSON.stringify(steps).includes('code_challenge'), false);
});

test('owned Appium UUID creation and cleanup states can be flushed before completion without auth data', (t) => {
  const marker = ownedFile(t, 'unit parent marker');
  const file = path.join(path.dirname(marker.path), 'owned-session.jsonl'), journal = new Journal(file);
  const sessionId = '11111111-2222-3333-4444-555555555555';
  journal.write(appiumSessionEvent(sessionId, 'created'));
  assert.equal(JSON.parse(readFileSync(file, 'utf8')).sessionId, sessionId);
  journal.write(appiumSessionEvent(sessionId, 'cleanup-failed'));
  journal.close();
  assert.deepEqual(readFileSync(file, 'utf8').trim().split('\n').map((line) => JSON.parse(line).state), ['created', 'cleanup-failed']);
  assert.deepEqual(appiumSessionEvent(sessionId, 'deleted'), { type: 'appium_session', sessionId, state: 'deleted' });
  for (const value of ['cnat_unit_secret', 'Bearer unit-only', 'https://unit.invalid/callback?code=unit', undefined]) {
    assert.throws(() => appiumSessionEvent(value, 'created'), /APPIUM_SESSION_UUID_REQUIRED/);
  }
});

test('Android explicitly updates then reads ID-autocompletion setting and exposes exact unprefixed IDs deterministically', async () => {
  const calls = [], records = [];
  let enabled = false;
  const control = { isDisplayed: async () => true };
  const driver = {
    updateSettings: async (settings) => { calls.push('update'); assert.deepEqual(settings,
      { disableIdLocatorAutocompletion: true, waitForIdleTimeout: 500, waitForSelectorTimeout: 0 }); enabled = true; },
    getSettings: async () => { calls.push('read'); return { disableIdLocatorAutocompletion: enabled,
      waitForIdleTimeout: 500, waitForSelectorTimeout: 0, privateUnrelatedSetting: 'unit-secret' }; },
    $$: async (query) => { calls.push('lookup'); assert.equal(query, 'id=native-mfa-code'); return enabled ? [control] : []; },
  };
  await configureNativeDriver(driver, 'android', (event) => records.push(event));
  assert.equal(await visible(driver, selector('android', 'id', 'native-mfa-code')), control);
  assert.deepEqual(calls, ['update', 'read', 'lookup']);
  assert.deepEqual(records, [{ type: 'native_driver_settings', disableIdLocatorAutocompletion: true,
    waitForIdleTimeout: 500, waitForSelectorTimeout: 0 }]);
});

test('false, missing or nonboolean ID-setting readback fails closed before UI and journals only the bounded boolean', async () => {
  for (const value of [false, undefined, 'true', 'unit-secret']) {
    const calls = [], records = [];
    const driver = {
      updateSettings: async () => calls.push('update'),
      getSettings: async () => { calls.push('read'); return { disableIdLocatorAutocompletion: value }; },
      getContexts: async () => { throw new Error('UI_MUST_NOT_BE_REACHED'); },
    };
    await assert.rejects(async () => { await configureNativeDriver(driver, 'android', (event) => records.push(event)); await driver.getContexts(); },
      /EXACT_ANDROID_RESOURCE_ID_SETTING_REQUIRED/);
    assert.deepEqual(calls, ['update', 'read']);
    assert.deepEqual(records, [{ type: 'native_driver_settings', disableIdLocatorAutocompletion: value === false ? false : null,
      waitForIdleTimeout: null, waitForSelectorTimeout: null }]);
  }
  const noAndroidCalls = new Proxy({}, { get: () => { throw new Error('NO_ANDROID_SETTINGS_ON_IOS'); } });
  await configureNativeDriver(noAndroidCalls, 'ios', () => { throw new Error('NO_FAKE_IOS_SETTINGS_PROOF'); });
});

test('Android refuses missing or silently ignored nested-wait settings before any UI work', async () => {
  for (const settings of [{}, { waitForIdleTimeout: 10000, waitForSelectorTimeout: 0 },
    { waitForIdleTimeout: 500, waitForSelectorTimeout: 10000 },
    { waitForIdleTimeout: '500', waitForSelectorTimeout: 0 }]) {
    let ui = false;
    const driver = { updateSettings: async () => {}, getSettings: async () => ({ disableIdLocatorAutocompletion: true, ...settings }) };
    await assert.rejects(async () => { await configureNativeDriver(driver, 'android', () => {}); ui = true; },
      /EXACT_ANDROID_(IDLE|SELECTOR)_WAIT_SETTING_REQUIRED/);
    assert.equal(ui, false);
  }
});

test('initial auth failure blocks all remaining 22 setups before another session while preserving exact failed/not-run evidence', () => {
  for (const platform of ['android', 'ios']) for (const failurePhase of ['setup', 'call']) {
    const collection = collect(platform), rows = [{ type: 'run_started', ...collection, harnessFingerprint: 'a'.repeat(64) },
      { type: 'preflight_result', status: 'passed' }];
    const gate = authenticationGate((event) => rows.push(event));
    let sessions = 0;
    for (const scenario of datedScenarios) {
      const id = `${platform}:${scenario.id}`;
      let setupPassed = false;
      rows.push({ type: 'phase_started', id, phase: 'setup' });
      try {
        gate.assertSetup(); sessions++;
        if (scenario.id === 'NATIVE-01' && failurePhase === 'setup') throw new Error('NATIVE_CONTROL_NOT_VISIBLE');
        setupPassed = true;
        rows.push({ type: 'phase_result', id, phase: 'setup', status: 'passed' });
      } catch (error) {
        gate.failInitial(scenario, 'setup');
        rows.push({ type: 'phase_result', id, phase: 'setup', status: error instanceof FixtureUnavailable ? 'blocked' : 'failed',
          reason: safeFailure(error, 'UNIT_FAILURE') });
      }
      rows.push({ type: 'phase_started', id, phase: 'call' });
      if (!setupPassed) rows.push({ type: 'phase_result', id, phase: 'call', status: 'not-run', reason: 'SETUP_FAILED' });
      else {
        assert.equal(scenario.id, 'NATIVE-01'); gate.failInitial(scenario, 'call');
        rows.push({ type: 'phase_result', id, phase: 'call', status: 'failed', reason: 'NATIVE_CONTROL_NOT_VISIBLE' });
      }
      rows.push({ type: 'phase_started', id, phase: 'teardown' }, { type: 'phase_result', id, phase: 'teardown', status: 'passed' });
    }
    rows.push({ type: 'postflight_result', status: 'passed' }, { type: 'run_completed', platform, intendedCount: 23 });
    const result = reconcileResults(rows, collection.intended);
    assert.equal(sessions, 1);
    assert.equal(result.nativeCallsPassed, 0);
    assert.equal(result.failedPhases, 1);
    assert.equal(result.blockedScenarios, 22);
    assert.equal(result.unexecutedCalls, failurePhase === 'setup' ? 23 : 22);
    assert.equal(result.status, 'incomplete-or-failed');
    assert.equal(rows.filter(({ type }) => type === 'auth_prerequisite_failed').length, 1);
    assert.ok(rows.some(({ status, reason }) => status === 'failed' && reason === 'NATIVE_CONTROL_NOT_VISIBLE'));
  }
});

test('a noninitial journey assertion failure does not silently poison the initial-auth prerequisite', () => {
  const records = [], gate = authenticationGate((event) => records.push(event));
  gate.failInitial({ id: 'NATIVE-09' }, 'call');
  gate.assertSetup();
  assert.deepEqual(records, []);
});

test('Firefox consent MFA refuses missing challenge, failed verification and changed identity/PKCE without reconnecting', async (t) => {
  browserEnvironment(t);
  for (const options of [{ noConsentChallenge: true }, { verifyRefused: true }, { wrongAfterMfa: true }, { changedAfterMfa: true }, { autoConnect: true }]) {
    const fake = firefoxDouble(t, false, { consent: true, ...options });
    await assert.rejects(() => browserLogin(fake.context));
    assert.equal(fake.clicks.filter((key) => key === 'connect').length, 1);
    assert.ok(fake.clicks.filter((key) => key === 'mfaSubmit').length <= 1);
  }
});

test('Firefox URL editor Back dismissal stops when closed, supports keyboard plus editor, and never issues a blind extra Back', async (t) => {
  browserEnvironment(t);
  const prepare = [{ kind: 'label', value: 'More options' }, { kind: 'label', value: 'Open in Firefox' }];
  for (const backPressesRequired of [1, 2]) {
    const fake = firefoxDouble(t, false, { androidBack: true, backPressesRequired, prepare });
    await browserLogin(fake.context);
    assert.deepEqual(fake.clicks.filter((key) => key.startsWith('prepare-')), ['prepare-0', 'prepare-1']);
    assert.equal(fake.clicks.filter((key) => key === 'android-back').length,
      fake.clicks.filter((key) => key === 'urlOpen').length * backPressesRequired);
  }
  const stuck = firefoxDouble(t, false, { androidBack: true, backPressesRequired: 3 });
  await assert.rejects(() => browserLogin(stuck.context), /FIREFOX_URL_EDITOR_NOT_DISMISSED/);
  assert.equal(stuck.clicks.filter((key) => key === 'android-back').length, 2);
  assert.deepEqual(stuck.writes, []);
});

function setupTraffic() {
  const state = { runId: 'unit-gateway', lastSequence: 1, accepted: 1, markerRejected: 1, routeRejected: 1,
    implementationSha256: 'a'.repeat(64), overflow: false,
    requests: [{ sequence: 1, method: 'GET', route: '/api/build', status: 200, nativeMarker: false, browserHandoff: false }] };
  const receipt = { gatewayRunId: state.runId, gatewayImplementationSha256: state.implementationSha256,
    tlsProof: { gatewayNegativeControls: [{ status: 403, code: 'AUTOMATED_MARKER_REQUIRED' }, { status: 403, code: 'ROUTE_NOT_ADMITTED' }] } };
  return { state, receipt };
}
test('native traffic baseline preserves and accounts for exact retained TLS negative controls', () => {
  const { state, receipt } = setupTraffic();
  const baseline = gatewayBaseline(state, receipt);
  assert.equal(baseline.lastSequence, 1);
  assert.equal(validateTraffic(state, baseline), state);
  assert.equal(baseline.markerRejected, 1);
  assert.equal(baseline.routeRejected, 1);
  assert.throws(() => gatewayBaseline({ ...state, markerRejected: 2 }, receipt), /UNRECONCILED/);
});
test('only admitted browser OPTIONS may lack an API marker; ordinary API calls still fail closed', () => {
  const { state, receipt } = setupTraffic(), baseline = gatewayBaseline(state, receipt);
  const after = { ...state, lastSequence: 2, accepted: 2,
    requests: [...state.requests, { sequence: 2, method: 'OPTIONS', route: '/api/auth/login', status: 200, nativeMarker: false, browserHandoff: true }] };
  validateTraffic(after, baseline);
  for (const patch of [{ method: 'POST' }, { browserHandoff: false }, { route: '/api/case-tracking/search' }]) {
    const copy = structuredClone(after); Object.assign(copy.requests[1], patch);
    assert.throws(() => validateTraffic(copy, baseline), /MARKER_NOT_PRESENT/);
  }
});
test('native request fence rejects new rejections, implementation changes and rewritten baseline history', () => {
  const { state, receipt } = setupTraffic(), baseline = gatewayBaseline(state, receipt);
  for (const patch of [{ markerRejected: 2 }, { routeRejected: 2 }, { implementationSha256: 'b'.repeat(64) }, { lastSequence: 0, requests: [] }]) {
    assert.throws(() => validateTraffic({ ...state, ...patch }, baseline));
  }
  const copy = structuredClone(state); copy.requests[0].status = 201;
  assert.throws(() => validateTraffic(copy, baseline), /HISTORY_CHANGED/);
});
test('partial Firefox recipes are blocked even when the normal TLS page and input IDs were really observed', (t) => {
  const recipe = firefoxRecipe(t);
  recipe.firefoxUi.status = 'partial';
  assert.throws(() => validateFirefoxRecipe(recipe), /RECIPE_INCOMPLETE/);
  assert.equal(selector('android', 'buttonText', 'Sign in'), 'android=new UiSelector().className("android.widget.Button").text("Sign in")');
  assert.throws(() => selector('ios', 'buttonText', 'Sign in'), /ANDROID_BUTTON/);
});

function localPlan(t) {
  const fixture = coreFixture(t), acceptance = acceptanceReceipt(t, 'android');
  const receipt = JSON.parse(readFileSync(fixture.isolationEvidence.path, 'utf8'));
  Object.assign(receipt, { gatewayUrl: 'https://127.0.0.1:8443', gatewayRunId: 'unit-run', webGatewayUrl: 'https://127.0.0.1:3443',
    apiOrigin: acceptance.fixture.apiOrigin, webOrigin: acceptance.fixture.auth.webOrigin,
    webMarkerTransportSourcePresent: true, source: { api: { dirty: false }, web: { dirty: false } } });
  const matter = { ...fixture.matter, search: fixture.matter.identityLabel };
  matter.searches[0].value = matter.identityLabel;
  const seed = { environment: 'docker-integration', syntheticDataOnly: true,
    principalLabel: 'Unit Person', workspaceLabel: 'Unit Workspace', companyId: 'unit-company', membershipId: 'unit-membership',
    matter, taskId: fixture.today.id, draftId: fixture.work.draft.id, hearingId: 'unit-hearing', calendarDate: fixture.calendar.day, calendar: { eventId: fixture.calendar.eventId },
    otherMatterId: 'unit-foreign', mfaEnrolled: false };
  const module = ownedFile(t, 'export async function control() { throw new Error("UNIT_ONLY_NOT_A_REAL_OWNER"); }', 'owner-unit.mjs');
  const output = ownedFile(t, 'output parent marker');
  return { schemaVersion: 1, dockerReceipt: ownedFile(t, receipt), seed: ownedFile(t, seed),
    gatewayRoutes: ownedFile(t, { routes: ['GET /api/auth/native/sessions', 'DELETE /api/auth/native/sessions/unit-current'] }),
    buildReceipt: acceptance.fixture.buildReceipt, publicCa: acceptance.fixture.publicCa,
    appId: acceptance.fixture.appId, binaryVersion: 'unit', binaryBuild: '1',
    device: { udid: 'unit-device', deviceName: 'unit-device', platformVersion: '17' },
    auth: { mode: 'web-context', companySlug: 'unit', emailEnv: 'CASEOPS_MOBILE_UNIT_EMAIL', passwordEnv: 'CASEOPS_MOBILE_UNIT_PASSWORD' },
    expectations: { matter, today: fixture.today, work: fixture.work, calendar: fixture.calendar,
      foreignMatter: { id: seed.otherMatterId, title: 'Foreign unit matter', identityLabel: 'FOREIGN-UNIT', search: 'FOREIGN-UNIT' },
      lifecycleMatter: { id: 'unit-lifecycle', title: 'Lifecycle unit', identityLabel: 'UNIT-LIFECYCLE', search: 'UNIT-LIFECYCLE' },
      accessMatter: { id: 'unit-access', title: 'Access unit', identityLabel: 'UNIT-ACCESS', search: 'UNIT-ACCESS' } },
    ownerControls: { modulePath: module.path, sha256: module.sha256, capabilities: ['disposeMatter', 'readMatterState', 'revokeMatterAccess', 'readNoteState'] },
    outputFixture: path.join(path.dirname(output.path), 'native-fixture.json') };
}

function macTransportPlan(t) {
  const plan = localPlan(t), receipt = JSON.parse(readFileSync(plan.buildReceipt.path, 'utf8'));
  plan.device.udid = 'emulator-5584';
  plan.androidTransport = { adbPort: 5038, appiumUrl: 'http://127.0.0.1:4725', systemPort: 8202 };
  const directory = path.dirname(receipt.artifact);
  const save = (name, value) => {
    const file = path.join(directory, name), bytes = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
    writeFileSync(file, bytes, { flag: 'wx' });
    return { path: file, sha256: createHash('sha256').update(bytes).digest('hex') };
  };
  const inputs = ['build.gradle', 'settings.gradle', 'gradle.properties', 'app/build.gradle', 'gradle/wrapper/gradle-wrapper.properties']
    .map(relativePath => { const bytes = `explicit synthetic generated input ${relativePath}`;
      const ref = save(relativePath.replaceAll('/', '-'), bytes);
      return { relativePath, sha256: ref.sha256, sizeBytes: Buffer.byteLength(bytes) }; });
  const proof = { schemaVersion: 1, kind: 'android-local-arm64-signature-proof', appId: plan.appId, artifactSha256: receipt.binaryHash,
    versionCode: 1, versionName: 'unit', architecture: 'arm64-v8a', signatureVerified: true, signatureSchemeV2: true,
    certificateSha256: '3'.repeat(64), intendedDeviceSerial: plan.device.udid, distributionSigning: false, nativeExecution: 'not-run-by-build-wrapper',
    evidence: [save('apk-badging.log', `package: name='${plan.appId}' versionCode='1' versionName='unit'\nnative-code: 'arm64-v8a'\n`),
      save('apk-signing.log', `Verifies\nVerified using v2 scheme (APK Signature Scheme v2): true\nNumber of signers: 1\nV2 Signer: certificate SHA-256 digest: ${'3'.repeat(64)}\n`),
      save('apk-abi.json', { schemaVersion: 1, abis: ['arm64-v8a'], nativeLibraryCount: 4, elfClass: 64, elfMachine: 183 }),
      save('generated-android-inputs.json', { schemaVersion: 1, files: inputs }),
      save('java21.log', 'Temurin-21.0.12.1+1 explicit synthetic fixture'), save('java17.log', 'Temurin-17.0.20.1+1 explicit synthetic fixture')] };
  receipt.androidSecurity = { kind: 'compiled-android-acceptance-security', apkSha256: receipt.binaryHash,
    nativeArtifactEvidence: save('android-native-proof.json', proof) };
  plan.buildReceipt = ownedFile(t, receipt);
  return plan;
}

const androidTransportEnvironment = { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5038', ANDROID_ADB_SERVER_PORT: '5038',
  ANDROID_SERIAL: 'emulator-5584', CASEOPS_MOBILE_APPIUM_URL: 'http://127.0.0.1:4725' };
function returnedAndroidCapabilities(fixture, prefixed = false) {
  return { platformName: 'Android', ...Object.fromEntries(Object.entries({ automationName: 'UiAutomator2', udid: fixture.udid,
    appPackage: fixture.appId, platformVersion: fixture.platformVersion, adbPort: 5038, systemPort: 8202 })
    .map(([key, value]) => [prefixed ? `appium:${key}` : key, value])) };
}

test('generated Mac plan preserves isolated transport through prepared fixture, requested capabilities and actual session readback', (t) => {
  const plan = macTransportPlan(t), prepared = prepareLocalPlan(plan, 'android', unitCredentials);
  assert.deepEqual(prepared.readiness.blockers, []);
  const fixture = JSON.parse(readFileSync(prepared.readiness.fixturePath, 'utf8'));
  assert.deepEqual(fixture.androidTransport, plan.androidTransport);
  const requested = androidSessionTransport(fixture, 'android', androidTransportEnvironment);
  assert.equal(requested.appiumUrl.href, 'http://127.0.0.1:4725/');
  assert.deepEqual(requested.capabilities, { 'appium:adbPort': 5038, 'appium:systemPort': 8202 });
  for (const prefixed of [false, true]) {
    const proof = verifyAndroidSessionTransport(fixture, 'android', returnedAndroidCapabilities(fixture, prefixed));
    assert.deepEqual(proof, { type: 'android_transport_verified', source: 'new-session-response', udid: 'emulator-5584',
      appId: fixture.appId, appiumUrl: 'http://127.0.0.1:4725', adbPort: 5038, systemPort: 8202 });
  }
});

test('Mac proof plans reject absent, malformed, wrong-port, wrong-URL and wrong-device transport before fixture output', (t) => {
  for (const edit of [plan => { delete plan.androidTransport; }, plan => { plan.androidTransport = null; },
    plan => { plan.androidTransport.adbPort = 5037; }, plan => { plan.androidTransport.adbPort = '5038'; },
    plan => { plan.androidTransport.systemPort = 8200; }, plan => { plan.androidTransport.appiumUrl = 'http://127.0.0.1:4723'; },
    plan => { plan.androidTransport.appiumUrl = 'http://127.0.0.1:4725/?unsafe=1'; }, plan => { plan.device.udid = 'emulator-5554'; },
    plan => { plan.androidTransport.unreviewedFallback = 5037; }]) {
    const plan = macTransportPlan(t); edit(plan);
    assert.throws(() => prepareLocalPlan(plan, 'android', unitCredentials), /MAC_ANDROID_TRANSPORT_REQUIRED|ANDROID_TRANSPORT_/);
    assert.throws(() => readFileSync(plan.outputFixture), /ENOENT/);
  }
});

test('plain-adb socket and runner endpoint cannot disagree with the bound Mac transport before creating a session', (t) => {
  const fixture = inspectLocalPlan(macTransportPlan(t), 'android', unitCredentials).fixture;
  for (const patch of [{ ADB_SERVER_SOCKET: undefined }, { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5037' },
    { ANDROID_ADB_SERVER_PORT: '5037' }, { ANDROID_SERIAL: 'emulator-5554' },
    { CASEOPS_MOBILE_APPIUM_URL: 'http://127.0.0.1:4723' }]) {
    let sessions = 0;
    assert.throws(() => { androidSessionTransport(fixture, 'android', { ...androidTransportEnvironment, ...patch }); sessions++; }, /ANDROID_TRANSPORT_/);
    assert.equal(sessions, 0);
  }
  const explicitPlanUrl = androidSessionTransport(fixture, 'android', { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5038' });
  assert.equal(explicitPlanUrl.appiumUrl.port, '4725');
});

test('omitted, mismatched or conflicting returned capability aliases prevent native actions and retain one owned cleanup', async (t) => {
  const fixture = inspectLocalPlan(macTransportPlan(t), 'android', unitCredentials).fixture;
  for (const edit of [caps => { delete caps.adbPort; }, caps => { caps.adbPort = 5037; }, caps => { delete caps.systemPort; },
    caps => { caps.systemPort = 8200; }, caps => { delete caps.udid; }, caps => { caps.udid = 'emulator-5554'; },
    caps => { caps.appPackage = 'foreign.app'; }, caps => { caps.platformVersion = 'guessed'; },
    caps => { caps['appium:adbPort'] = 5037; }, caps => { caps.platformName = 'iOS'; }]) {
    const driver = { capabilities: returnedAndroidCapabilities(fixture), async deleteSession() { cleanups++; } };
    let nativeActions = 0, cleanups = 0; edit(driver.capabilities);
    await assert.rejects(async () => {
      try { verifyAndroidSessionTransport(fixture, 'android', driver.capabilities); nativeActions++; }
      finally { await driver.deleteSession(); }
    }, /ANDROID_SESSION_/);
    assert.equal(nativeActions, 0); assert.equal(cleanups, 1);
  }
});

test('historical Windows plans without Mac proof or transport retain their existing endpoint and capability behavior', (t) => {
  const plan = localPlan(t), result = inspectLocalPlan(plan, 'android', unitCredentials);
  assert.deepEqual(result.readiness.blockers, []); assert.equal(Object.hasOwn(result.fixture, 'androidTransport'), false);
  assert.equal(validateAndroidTransport(result.fixture, 'android'), null);
  assert.deepEqual(androidSessionTransport(result.fixture, 'android', {}).capabilities, {});
  assert.equal(androidSessionTransport(result.fixture, 'android', {}).appiumUrl.href, 'http://127.0.0.1:4723/');
  assert.equal(verifyAndroidSessionTransport(result.fixture, 'android', undefined), null);
});

test('actual runner binds transport before preflight device work and checks returned capabilities before every native action', () => {
  const source = readFileSync(new URL('./run-native.mjs', import.meta.url), 'utf8');
  assert.ok(source.indexOf('const sessionTransport = androidSessionTransport(') < source.indexOf('owner = await loadOwnerControls('));
  assert.ok(source.indexOf('...sessionTransport.capabilities') < source.indexOf('driver = await remote('));
  const check = source.indexOf('verifyAndroidSessionTransport(fixture, platform, driver.capabilities)');
  assert.ok(check > source.indexOf('ownedSessionId = sessionCreated.sessionId'));
  assert.ok(check < source.indexOf('await configureNativeDriver('));
  assert.ok(check < source.indexOf("boundary: 'case-setup'"));
  assert.ok(check < source.indexOf('const contexts = await driver.getContexts()'));
  assert.ok(source.indexOf("assert.equal(androidTransportRejected, false, 'ANDROID_TRANSPORT_PREVIOUSLY_REFUSED')") < source.indexOf('driver = await remote('));
  assert.ok(source.includes('androidTransportRejected = true; throw error;'));
  assert.equal(source.match(/if \(driver\) await driver\.deleteSession\(\)/g)?.length, 1);
});

function dynamicSessionPlan(t) {
  const plan = localPlan(t), receipt = JSON.parse(readFileSync(plan.dockerReceipt.path, 'utf8'));
  const source = fileURLToPath(new URL('./local-gateway.py', import.meta.url));
  const implementationSha256 = createHash('sha256').update(readFileSync(source)).digest('hex');
  receipt.gatewayImplementationSha256 = implementationSha256;
  plan.dockerReceipt = ownedFile(t, receipt);
  const status = { runId: receipt.gatewayRunId, implementationSha256, accepted: 0, markerRejected: 0,
    routeRejected: 0, lastSequence: 0, overflow: false, requests: [], sessionDeleteAdmissions: [] };
  const policy = { kind: 'native-current-session-delete-v1', sourceRoute: 'GET /api/auth/native/sessions', sourceListLimit: 50,
    maxLiveIds: 1, maxAdmissionEvents: 64, nativeBearerOnly: true, cookiesAllowed: false, currentOnly: true, unrevokedOnly: true, consumeOnAttempt: true,
    gatewayRunId: receipt.gatewayRunId, implementationSha256, implementationEvidence: { path: source, sha256: implementationSha256 },
    statusEvidence: ownedFile(t, status), isolationEvidence: plan.dockerReceipt,
    requestEvidenceLink: 'sessionDeleteAdmissions[].sourceRequestId -> requests[].requestId', liveExecutionProofRequiredAt: 'NATIVE-20' };
  const descriptor = { schemaVersion: 2, routes: ['GET /api/auth/native/sessions'],
    dynamicAdmissions: { nativeCurrentSessionDelete: policy } };
  plan.gatewayRoutes = ownedFile(t, descriptor);
  return { plan, descriptor, policy, status };
}

test('dynamic session admission policy replaces an unknowable future static ID only with pinned source/status/isolation proof', (t) => {
  const { plan, policy } = dynamicSessionPlan(t);
  const result = inspectLocalPlan(plan, 'android', unitCredentials);
  assert.equal(result.readiness.status, 'ready-for-native-preflight', JSON.stringify(result.readiness.blockers));
  assert.deepEqual(result.fixture.nativeSessionDeleteAdmission, { mode: 'dynamic', routeEvidence: plan.gatewayRoutes, policy });
  assert.deepEqual(configuredSessionDeleteAdmission(result.fixture), result.fixture.nativeSessionDeleteAdmission);
});

test('missing dynamic proof or static wildcard still blocks preparation without fabricating a session ID', (t) => {
  for (const dynamic of [false, true]) for (const route of [undefined, 'DELETE /api/auth/native/sessions/*', 'DELETE /api/auth/native/sessions/']) {
    const { plan, descriptor } = dynamicSessionPlan(t);
    if (!dynamic) delete descriptor.dynamicAdmissions;
    if (route) descriptor.routes.push(route);
    plan.gatewayRoutes = ownedFile(t, descriptor);
    const result = prepareLocalPlan(plan, 'android', unitCredentials);
    assert.equal(result.readiness.status, dynamic && !route ? 'ready-for-native-preflight' : 'incomplete');
    if (result.readiness.status === 'incomplete') assert.throws(() => readFileSync(plan.outputFixture), /ENOENT/);
  }
});

test('dynamic policy rejects weakened invariants, changed reference hashes and wrong source/run identities', (t) => {
  for (const [key, value] of Object.entries({ kind: 'invented', sourceRoute: 'GET /api/auth/me', sourceListLimit: 500,
    maxLiveIds: 2, maxAdmissionEvents: 24, nativeBearerOnly: false, cookiesAllowed: true, currentOnly: false, unrevokedOnly: false,
    consumeOnAttempt: false, gatewayRunId: 'other-run', implementationSha256: '0'.repeat(64),
    requestEvidenceLink: 'unlinked', liveExecutionProofRequiredAt: 'never',
    implementationEvidence: { path: 'wrong.py', sha256: '0'.repeat(64) },
    isolationEvidence: { path: 'wrong.json', sha256: '0'.repeat(64) },
    statusEvidence: { path: 'wrong.json', sha256: '0'.repeat(64) } })) {
    const { plan, descriptor, policy } = dynamicSessionPlan(t);
    policy[key] = value; plan.gatewayRoutes = ownedFile(t, descriptor);
    const result = inspectLocalPlan(plan, 'android', unitCredentials);
    assert.equal(result.readiness.status, 'incomplete', key);
    assert.ok(result.readiness.blockers.some(({ fields }) => fields.includes('gatewayRoutes')), key);
  }
  const { plan, descriptor } = dynamicSessionPlan(t);
  descriptor.schemaVersion = 1; plan.gatewayRoutes = ownedFile(t, descriptor);
  assert.equal(inspectLocalPlan(plan, 'android', unitCredentials).readiness.status, 'incomplete');
});

test('dynamic policy rejects stale, overflowed, unsettled, unlinked or rejected runtime status evidence', (t) => {
  for (const patch of [{ runId: 'other' }, { implementationSha256: '0'.repeat(64) }, { markerRejected: 1 }, { routeRejected: 1 },
    { overflow: true }, { sessionDeleteAdmissions: undefined },
    { sessionDeleteAdmissions: [{ type: 'session-delete-admitted', route: 'DELETE /api/auth/native/sessions/unit', sourceRequestId: 'a'.repeat(16) }] },
    { lastSequence: 1, requests: [{ sequence: 1, requestId: 'a'.repeat(16), method: 'GET', route: '/api/build', status: null }] }]) {
    const { plan, descriptor, policy, status } = dynamicSessionPlan(t);
    policy.statusEvidence = ownedFile(t, { ...status, ...patch }); plan.gatewayRoutes = ownedFile(t, descriptor);
    assert.equal(inspectLocalPlan(plan, 'android', unitCredentials).readiness.status, 'incomplete');
  }
});

function sessionDeletionLedger(policy, count = 1) {
  const request = (sequence, method, route, status) => ({ sequence, requestId: sequence.toString(16).padStart(16, '0'), method, route, status,
    nativeMarker: true, browserHandoff: false });
  const before = { runId: policy.gatewayRunId, implementationSha256: policy.implementationSha256, accepted: 1,
    markerRejected: 0, routeRejected: 0, lastSequence: 1, overflow: false,
    requests: [request(1, 'GET', '/api/build', 200)], sessionDeleteAdmissions: [] };
  const after = structuredClone(before);
  for (let index = 0; index < count; index++) {
    const source = request(index + 2, 'GET', '/api/auth/native/sessions', 200);
    after.requests.push(source);
    after.sessionDeleteAdmissions.push({ type: 'session-delete-admitted', route: `DELETE /api/auth/native/sessions/current-${index}`,
      sourceRequestId: source.requestId });
  }
  after.requests.push(request(count + 2, 'DELETE', `/api/auth/native/sessions/current-${count - 1}`, 204));
  after.lastSequence = after.accepted = after.requests.length;
  return { before, after };
}

test('NATIVE-20 proves the latest real current-session admission and records only safe request/session IDs', (t) => {
  const { plan, policy } = dynamicSessionPlan(t);
  const { fixture } = inspectLocalPlan(plan, 'android', unitCredentials);
  const admission = configuredSessionDeleteAdmission(fixture);
  const { before, after } = sessionDeletionLedger(policy, 2);
  const proof = proveCurrentSessionDeletion(before, after, admission);
  assert.equal(proof.sourceRequestId, after.requests[2].requestId);
  assert.equal(proof.deleteRequestId, after.requests[3].requestId);
  assert.equal(proof.currentSessionId, 'current-1');
  assert.equal(proof.sourceSequence, 3);
  assert.equal(proof.deleteSequence, 4);
  assert.equal(JSON.stringify(proof).includes('Bearer'), false);
});

test('NATIVE-20 rejects wrong targets, stale sources, cookie/browser reads, unmarked/failed reads, duplicate deletes and altered history', (t) => {
  const { plan, policy } = dynamicSessionPlan(t);
  const admission = inspectLocalPlan(plan, 'android', unitCredentials).fixture.nativeSessionDeleteAdmission;
  for (const mutate of [
    ({ after }) => { after.sessionDeleteAdmissions = []; },
    ({ after }) => { after.requests.at(-1).route = '/api/auth/native/sessions/not-current'; },
    ({ after }) => { after.requests[1].status = 403; },
    ({ after }) => { after.requests[1].nativeMarker = false; },
    ({ after }) => { after.requests[1].browserHandoff = true; },
    ({ after }) => { after.requests[1].route = '/api/auth/me'; },
    ({ after }) => { after.sessionDeleteAdmissions[0].sourceRequestId = 'a'.repeat(16); },
    ({ after }) => { after.requests.at(-1).status = 200; },
    ({ after }) => { after.requests.at(-1).nativeMarker = false; },
    ({ after }) => { after.requests.at(-1).browserHandoff = true; },
    ({ after }) => { after.implementationSha256 = '0'.repeat(64); },
    ({ after }) => { after.runId = 'other'; },
    ({ after }) => { after.requests[0].requestId = 'f'.repeat(16); },
    ({ after }) => { after.requests[1].requestId = after.requests[0].requestId; },
    ({ after }) => { after.requests.push({ ...after.requests.at(-1), sequence: 4, requestId: 'f'.repeat(16) }); after.lastSequence = 4; },
    ({ before, after }) => { before.requests.push(structuredClone(after.requests[1])); before.lastSequence = 2;
      before.sessionDeleteAdmissions = structuredClone(after.sessionDeleteAdmissions); },
  ]) {
    const state = sessionDeletionLedger(policy); mutate(state);
    assert.throws(() => proveCurrentSessionDeletion(state.before, state.after, admission));
  }
  const newer = sessionDeletionLedger(policy, 2);
  newer.after.requests.at(-1).route = '/api/auth/native/sessions/current-0';
  assert.throws(() => proveCurrentSessionDeletion(newer.before, newer.after, admission), /DELETE_TARGET_NOT_LATEST_CURRENT_SESSION/);
});

test('64 complete admission events are retained; event 65 and request 501 reject without dropping history', (t) => {
  assert.equal(MAX_SESSION_ADMISSION_EVENTS, 64);
  const { plan, policy } = dynamicSessionPlan(t);
  const admission = inspectLocalPlan(plan, 'android', unitCredentials).fixture.nativeSessionDeleteAdmission;
  const complete = sessionDeletionLedger(policy, 64);
  assert.equal(proveCurrentSessionDeletion(complete.before, complete.after, admission).currentSessionId, 'current-63');
  assert.equal(complete.after.sessionDeleteAdmissions.length, 64);
  const overflow = sessionDeletionLedger(policy, 65);
  assert.throws(() => proveCurrentSessionDeletion(overflow.before, overflow.after, admission), /BOUNDED_SESSION_ADMISSION_LEDGER_REQUIRED/);
  assert.equal(overflow.after.sessionDeleteAdmissions.length, 65);
  const requests = sessionDeletionLedger(policy, 1);
  while (requests.after.requests.length < 501) {
    const sequence = requests.after.requests.length + 1;
    requests.after.requests.push({ sequence, requestId: sequence.toString(16).padStart(16, '0'), method: 'GET', route: '/api/build', status: 200 });
  }
  requests.after.lastSequence = 501;
  assert.throws(() => proveCurrentSessionDeletion(requests.before, requests.after, admission), /BOUNDED_REQUEST_LEDGER_REQUIRED/);
  assert.equal(requests.after.requests.length, 501);
});
test('offline local preparation maps exact Docker and seed metadata without loading a device or credential file', (t) => {
  const plan = localPlan(t);
  const result = inspectLocalPlan(plan, 'android', unitCredentials);
  assert.equal(result.readiness.status, 'ready-for-native-preflight');
  assert.equal(result.readiness.nativeExecution, 'not-run');
  assert.equal(result.readiness.credentialFilesRead, false);
  assert.equal(result.fixture.matter.id, plan.expectations.matter.id);
  assert.equal(result.fixture.appId, 'ai.caseops.mobile.dev.localacceptance');
  assert.equal(result.readiness.intended.length, 23);
  assert.equal(result.fixture.auth.webOrigin, 'https://10.0.2.2:3443');
});

test('offline preparation retains enrolled MFA as required but blocks unspecified stage instead of guessing login', (t) => {
  const plan = localPlan(t), seed = JSON.parse(readFileSync(plan.seed.path, 'utf8'));
  seed.mfaEnrolled = true; plan.seed = ownedFile(t, seed);
  const environment = { ...unitCredentials, CASEOPS_MOBILE_UNIT_TOTP: 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ' };
  plan.auth.totpSecretEnv = 'CASEOPS_MOBILE_UNIT_TOTP';
  const blocked = prepareLocalPlan(plan, 'android', environment);
  assert.equal(blocked.fixture.auth.mfaRequired, true);
  assert.equal(blocked.fixture.auth.mfaStage, undefined);
  assert.ok(blocked.readiness.blockers.some(({ code }) => code === 'EXPLICIT_MFA_STAGE_REQUIRED'));
  assert.throws(() => readFileSync(plan.outputFixture), /ENOENT/);
  plan.auth.mfaStage = 'consent';
  const ready = inspectLocalPlan(plan, 'android', environment);
  assert.equal(ready.readiness.status, 'ready-for-native-preflight');
  assert.equal(ready.fixture.auth.mfaStage, 'consent');
});
test('dirty web identity and incomplete seed retain the complete inventory and refuse fixture creation', (t) => {
  const plan = localPlan(t), receipt = JSON.parse(readFileSync(plan.dockerReceipt.path, 'utf8'));
  receipt.webIdentity.release_sha = 'unavailable'; receipt.source.web.dirty = true;
  plan.dockerReceipt = ownedFile(t, receipt); plan.expectations = {};
  const result = prepareLocalPlan(plan, 'android', unitCredentials);
  const codes = result.readiness.blockers.map(({ code }) => code);
  assert.ok(codes.includes('EXACT_SERVING_SHA_UNAVAILABLE'));
  assert.ok(codes.includes('SERVING_SOURCE_NOT_FROZEN'));
  assert.equal(result.readiness.intended.length, 23);
  assert.equal(result.readiness.status, 'incomplete');
  assert.equal(result.fixture.matter.searches[0].value, 'UNIT-CODE');
  assert.equal(result.readiness.blockers.filter(({ code }) => code === 'EXACT_SEARCH_IDENTIFIER_EXPECTATION_MISSING').length, 4);
  assert.throws(() => readFileSync(plan.outputFixture), /ENOENT/);
});
test('prepared fixture is secret-free and exclusive; a second preparation cannot overwrite it', (t) => {
  const plan = localPlan(t);
  const result = prepareLocalPlan(plan, 'android', unitCredentials);
  assert.equal(result.readiness.fixturePath, plan.outputFixture);
  const body = readFileSync(plan.outputFixture, 'utf8');
  assert.equal(body.includes(unitCredentials.CASEOPS_MOBILE_UNIT_PASSWORD), false);
  assert.throws(() => prepareLocalPlan(plan, 'android', unitCredentials), /EEXIST/);
  assert.equal(readFileSync(plan.outputFixture, 'utf8'), body);
});
test('local run plans reject embedded credential values and conflicting seed identities before assembly', (t) => {
  const plan = localPlan(t);
  assert.throws(() => inspectLocalPlan({ ...plan, password: 'UNIT_VALUE_MUST_NOT_APPEAR' }, 'android', unitCredentials), /SECRET_VALUE/);
  plan.expectations.matter.searches[0].value = 'wrong';
  assert.throws(() => inspectLocalPlan(plan, 'android', unitCredentials), /PRIMARY_SEARCH/);
});

// Offline driver/clock regression only; the existing browser doubles own the full PKCE/MFA journey.
const browserBoundary = 'OFFLINE_BROWSER_ADMISSION_BOUNDARY';

function readinessDouble({ initial = 'restoring', restoreAt = Infinity, logoutReadyAfter = 0 } = {}) {
  let time = 0, screen = initial, logoutAt;
  const clicks = [], reads = [], waits = [], records = [], browserAdmissions = [], gestures = [];
  const phase = () => {
    if (screen === 'restoring' && time >= restoreAt) screen = 'home';
    return screen;
  };
  const signInEnabled = () => phase() === 'signed-out' && time >= logoutAt + logoutReadyAfter;
  const element = (id, text = '') => ({
    isDisplayed: async () => true,
    isEnabled: async () => id !== 'sign-in' || signInEnabled(),
    getText: async () => { reads.push({ id, time }); return text; },
    click: async () => {
      clicks.push({ id, time });
      if (id === 'sign-in') {
        if (!signInEnabled()) throw new Error('OFFLINE_DISABLED_SIGNIN_CLICK');
        throw new Error(browserBoundary);
      }
      if (id === 'account-open') { assert.equal(phase(), 'home'); screen = 'account'; }
      else if (id === 'sign-out') { assert.equal(phase(), 'account'); screen = 'signed-out'; logoutAt = time; }
      else if (id === 'back') { assert.equal(phase(), 'account'); screen = 'home'; }
      else assert.fail(`UNEXPECTED_OFFLINE_CLICK:${id}`);
    },
  });
  if (initial === 'signed-out') logoutAt = 0;
  const driver = {
    switchContext: async name => assert.equal(name, 'NATIVE_APP', 'NO_REAL_BROWSER_CONTEXT_ALLOWED'),
    waitUntil: async (callback, options) => {
      const startedAt = time, deadline = time + options.timeout;
      const row = { startedAt, timeout: options.timeout, interval: options.interval, timeoutMsg: options.timeoutMsg };
      waits.push(row);
      while (true) {
        if (await callback()) { row.endedAt = time; row.result = 'ready'; return; }
        if (time >= deadline) { row.endedAt = time; row.result = 'timeout'; throw new Error(options.timeoutMsg); }
        time = Math.min(deadline, time + options.interval);
      }
    },
    $$: async query => {
      assert.ok(query.startsWith('id='), 'ONLY_OFFLINE_NATIVE_IDS_ALLOWED');
      const id = query.slice(3), current = phase();
      if (id === 'account-open' && current === 'home') return [element(id)];
      if (id === 'session-loading' && (current === 'restoring' || current === 'signed-out' && !signInEnabled())) return [element(id)];
      if (id === 'sign-in' && ['restoring', 'signed-out'].includes(current)) return [element(id)];
      // This deliberately keeps the logout acknowledgement visible before its button is usable.
      if (id === 'signed-out' && current === 'signed-out') return [element(id)];
      if (current === 'account') {
        if (id === 'account-principal') return [element(id, 'Synthetic Restart Principal')];
        if (id === 'account-workspace') return [element(id, 'Synthetic Restart Workspace')];
        if (['sign-out', 'back'].includes(id)) return [element(id)];
      }
      return [];
    },
    performActions: async () => { gestures.push(time); assert.fail('NO_GESTURE_DURING_OFFLINE_READINESS'); },
  };
  const context = { driver: nativeProtocolDouble(driver), platform: 'android', fixture: {
    principalLabel: 'Synthetic Restart Principal', workspaceLabel: 'Synthetic Restart Workspace',
    auth: { mode: 'web-context', webOrigin: 'https://127.0.0.1:3443', companySlug: 'synthetic-restart',
      mfaRequired: true, mfaStage: 'consent', emailEnv: 'CASEOPS_MOBILE_UNIT_EMAIL', passwordEnv: 'CASEOPS_MOBILE_UNIT_PASSWORD' },
  }, record: row => {
    records.push(row);
    if (row.type === 'browser_step' && row.key === 'sign-in' && row.action === 'click') browserAdmissions.push(time);
  } };
  return { context, clicks, reads, waits, records, browserAdmissions, gestures, now: () => time };
}

async function observeReadiness(fake, options) {
  let error;
  try { await authenticate(fake.context, options); } catch (cause) { error = cause.message; }
  return { error: error ?? null, elapsedVirtualMs: fake.now(), clicks: fake.clicks, reads: fake.reads,
    waits: fake.waits, browserAdmissions: fake.browserAdmissions, gestures: fake.gestures, records: fake.records };
}

test('restart waits past disabled visible sign-in for restored account identity without browser auth', async t => {
  browserEnvironment(t);
  const fake = readinessDouble({ restoreAt: 4011 });
  const actual = await observeReadiness(fake);
  assert.equal(actual.error, null);
  assert.ok(actual.elapsedVirtualMs >= 4011 && actual.elapsedVirtualMs <= 20000);
  assert.deepEqual(actual.clicks.map(row => row.id), ['account-open', 'back']);
  assert.deepEqual(actual.reads.map(row => row.id), ['account-principal', 'account-workspace']);
  assert.deepEqual(actual.browserAdmissions, []);
  assert.deepEqual(actual.gestures, []);
});

test('permanently disabled visible sign-in times out at 20s without clicks or browser auth', async t => {
  browserEnvironment(t);
  const fake = readinessDouble();
  const actual = await observeReadiness(fake);
  assert.equal(actual.error, 'NATIVE_SESSION_NOT_READY');
  assert.equal(actual.elapsedVirtualMs, 20000);
  assert.deepEqual(actual.clicks, []);
  assert.deepEqual(actual.reads, []);
  assert.deepEqual(actual.browserAdmissions, []);
  assert.deepEqual(actual.gestures, []);
});

test('fresh logout waits for enabled sign-in after signed-out acknowledgement before browser auth', async t => {
  browserEnvironment(t);
  const fake = readinessDouble({ initial: 'home', logoutReadyAfter: 4011 });
  const actual = await observeReadiness(fake, { fresh: true });
  assert.equal(actual.error, browserBoundary);
  assert.ok(actual.elapsedVirtualMs >= 4011 && actual.elapsedVirtualMs <= 20000);
  assert.deepEqual(actual.clicks.map(row => row.id), ['account-open', 'sign-out', 'sign-in']);
  assert.equal(actual.browserAdmissions.length, 1);
  assert.ok(actual.browserAdmissions[0] >= 4011);
  assert.deepEqual(actual.gestures, []);
});

test('fresh logout with permanently disabled sign-in times out at 20s without browser auth', async t => {
  browserEnvironment(t);
  const fake = readinessDouble({ initial: 'home', logoutReadyAfter: Infinity });
  const actual = await observeReadiness(fake, { fresh: true });
  assert.equal(actual.error, 'NATIVE_SESSION_NOT_READY');
  assert.equal(actual.elapsedVirtualMs, 20000);
  assert.deepEqual(actual.clicks.map(row => row.id), ['account-open', 'sign-out']);
  assert.deepEqual(actual.browserAdmissions, []);
  assert.deepEqual(actual.gestures, []);
});

test('already restored account control still reads both exact identities and returns without browser auth', async t => {
  browserEnvironment(t);
  const fake = readinessDouble({ initial: 'home' });
  const actual = await observeReadiness(fake);
  assert.equal(actual.error, null);
  assert.equal(actual.elapsedVirtualMs, 0);
  assert.deepEqual(actual.clicks.map(row => row.id), ['account-open', 'back']);
  assert.deepEqual(actual.reads.map(row => row.id), ['account-principal', 'account-workspace']);
  assert.deepEqual(actual.browserAdmissions, []);
});

test('already enabled signed-out control admits browser auth exactly once without extra wait', async t => {
  browserEnvironment(t);
  const fake = readinessDouble({ initial: 'signed-out' });
  const actual = await observeReadiness(fake);
  assert.equal(actual.error, browserBoundary);
  assert.equal(actual.elapsedVirtualMs, 0);
  assert.deepEqual(actual.clicks.map(row => row.id), ['sign-in']);
  assert.deepEqual(actual.browserAdmissions, [0]);
});

// These tests are local transport/source contracts, not native SDK acceptance.
const trustHelper = fileURLToPath(new URL('./host-node-trust.mjs', import.meta.url));
const trustFixture = fileURLToPath(new URL('./host-node-trust-fixture.mjs', import.meta.url));
const neutralTrustEnv = () => {
  const result = { ...process.env };
  for (const key of Object.keys(result)) if (/^(NODE_OPTIONS|NODE_EXTRA_CA_CERTS|NODE_USE_SYSTEM_CA|NODE_TLS_REJECT_UNAUTHORIZED|OPENSSL_CONF|OPENSSL_CONF_INCLUDE|SSL_CERT_FILE|SSL_CERT_DIR|CASEOPS_HOST_NODE_TRUST_POLICY_FILE|CASEOPS_HOST_NODE_TRUST_POLICY_SHA256)$/i.test(key)) delete result[key];
  return result;
};
const trustRoot = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-scoped-node-trust-')));
async function trustChild(args, environment) {
  const child = spawn(process.execPath, args, { env: environment, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  let stdout = '', stderr = '', exceeded = false;
  const consume = name => value => { if (stdout.length + stderr.length + value.length > 32768) { exceeded = true; child.kill(); } else if (name === 'stdout') stdout += value; else stderr += value; };
  child.stdout.on('data', consume('stdout')); child.stderr.on('data', consume('stderr'));
  const timer = setTimeout(() => child.kill(), 12000);
  try { const [code, signal] = await once(child, 'close'); return { code, signal, stdout, stderr, exceeded, pid: child.pid }; }
  finally { clearTimeout(timer); }
}
let tlsMaterials;
const materials = () => tlsMaterials ??= localCertificates();
function qaTrust(root) {
  const cert = materials().trusted.cert, file = path.join(root, 'isolated-ca.pem');
  fs.writeFileSync(file, cert, { mode: 0o600, flag: 'wx' });
  const reference = { path: file, sha256: createHash('sha256').update(cert).digest('hex'), certificateSha256: new X509Certificate(cert).fingerprint256.replaceAll(':', '').toLowerCase() };
  return { reference, prepared: prepareHostNodeTrust({ directory: path.join(root, 'policy'), role: 'native-qa', fixtureCA: reference, environment: neutralTrustEnv() }) };
}
async function localTls(material, callback) {
  let requests = 0;
  const server = https.createServer({ key: material.privateKey, cert: material.cert }, (request, response) => {
    assert.equal(request.headers['x-caseops-automated-test'], 'no-paid-providers'); requests++; response.end('local-only');
  });
  const sockets = new Set(); server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  try { return await callback(`https://127.0.0.1:${server.address().port}/`, () => requests); }
  finally { for (const socket of sockets) socket.destroy(); await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve())); }
}

test('host trust removes only the exact compromised DER and accepts the exact already-clean set', () => {
  const roots = reviewHostNodeRoots();
  assert.equal(roots.outputCount, 144); assert.equal(roots.removedCount, 1); assert.equal(roots.fingerprints.includes(DENIED_HOST_CA), false);
  const cleaned = roots.pem.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g);
  const again = reviewHostNodeRoots(cleaned);
  assert.equal(again.removedCount, 0); assert.equal(again.outputSetSha256, roots.outputSetSha256);
  assert.equal(again.pem, roots.pem);
});
test('host trust refuses duplicates, omitted unaffected roots, changed roots and unreviewed runtimes', () => {
  for (const values of [[...tls.rootCertificates, tls.rootCertificates[0]], tls.rootCertificates.slice(1), ['invalid', ...tls.rootCertificates.slice(1)]]) {
    assert.throws(() => reviewHostNodeRoots(values), /HOST_TRUST_/);
  }
  assert.throws(() => reviewHostNodeRoots(tls.rootCertificates, '24.15.1'), /HOST_TRUST_NODE_OR_ROOTS_UNREVIEWED/);
});
test('host trust preparation is exclusive, private and does not mutate the process environment or TLS defaults', () => {
  const root = trustRoot(), before = { ...process.env }, defaultBefore = tls.getCACertificates('default');
  try {
    const prepared = prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() });
    assert.equal(prepared.effectiveDefaultVerified, false); assert.equal(prepared.globalTrustChanges, 0);
    assert.equal(prepared.descriptor.runtimeSource.helper.sha256, createHash('sha256').update(fs.readFileSync(trustHelper)).digest('hex'));
    assert.ok(prepared.environment.NODE_OPTIONS.length < 24000);
    assert.equal(fs.readdirSync(prepared.descriptor.emptyDirectory).length, 0);
    if (process.platform !== 'win32') for (const name of ['policy.json', 'roots.pem']) assert.equal(fs.statSync(path.join(root, 'policy', name)).mode & 0o777, 0o600);
    assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() }), /EEXIST/);
    assert.equal(Object.keys(process.env).length === Object.keys(before).length && Object.keys(before).every(key => process.env[key] === before[key]), true); assert.deepEqual(tls.getCACertificates('default'), defaultBefore);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('actual inherited bootstrap activates the exact Node24 default store before the entry', async () => {
  const root = trustRoot();
  try {
    const prepared = prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() });
    const result = await trustChild([trustHelper, 'verify'], { ...neutralTrustEnv(), ...prepared.environment });
    assert.equal(result.code, 0, result.stderr); assert.equal(result.signal, null); assert.equal(result.exceeded, false);
    const report = JSON.parse(result.stdout); assert.equal(report.defaultEnumerationVerified, true); assert.equal(report.expectedDefaultCount, 144);
    assert.equal(report.expectedDefaultSetSha256, prepared.descriptor.outputSetSha256); assert.equal(report.globalTrustChanges, 0);
    const standalone = { ...neutralTrustEnv(), ...prepared.environment, CASEOPS_HOST_NODE_BOOTSTRAP_TEST: '1' };
    // A separate Node test controller must not inherit the parent's internal reporter context.
    delete standalone.NODE_TEST_CONTEXT;
    const forwarded = await trustChild(['--test', '--test-reporter=tap', trustFixture], standalone);
    assert.equal(forwarded.code, 0, forwarded.stderr || forwarded.stdout); assert.match(forwarded.stdout, /# tests 1\n/); assert.match(forwarded.stdout, /# pass 1\n/); assert.match(forwarded.stdout, /# fail 0\n/);
    if (process.env.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE) {
      const records = observerOuterRecords(process.pid).filter(row => row.event === 'child-spawned' && row.pid === forwarded.pid);
      assert.equal(records.length, 1); assert.equal(records[0].nestedDriver?.role, 'source-audited-nested-intrinsic-driver');
      assert.equal(records[0].nestedDriver.scriptCompleteClaim, false); assert.equal(records[0].nestedDriver.workerWitnessRequired, true);
      assert.deepEqual(records[0].nestedDriver.argv, [process.execPath, '--test', '--test-reporter=tap', trustFixture]);
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('native-QA default HTTPS and fetch preserve certificate and hostname rejection', async () => {
  const root = trustRoot();
  try {
    const { reference, prepared } = qaTrust(root), env = { ...neutralTrustEnv(), ...prepared.environment, CASEOPS_TEST_FIXTURE_CA: JSON.stringify(reference) };
    for (const [name, expected] of [['trusted', 'local-only'], ['untrusted', 'DEPTH_ZERO_SELF_SIGNED_CERT'], ['wrongHost', 'ERR_TLS_CERT_ALTNAME_INVALID']]) {
      await localTls(materials()[name], async (origin, requests) => {
        const result = await trustChild([trustFixture, 'probe', origin], env);
        assert.equal(result.code, 0, result.stderr); const report = JSON.parse(result.stdout);
        assert.deepEqual(report.output, [expected, expected]); assert.equal(report.expectedDefaultCount, 145); assert.equal(report.defaultEnumerationVerified, true);
        assert.equal(requests(), name === 'trusted' ? 2 : 0);
      });
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('normal Worker and subprocess inherit the activated fixture-bound default clients', async () => {
  const root = trustRoot();
  try {
    const { reference, prepared } = qaTrust(root);
    await localTls(materials().trusted, async (origin, requests) => {
      const result = await trustChild([trustFixture, 'descendants', origin], { ...neutralTrustEnv(), ...prepared.environment, CASEOPS_TEST_FIXTURE_CA: JSON.stringify(reference) });
      assert.equal(result.code, 0, result.stderr); const report = JSON.parse(result.stdout);
      assert.deepEqual(Object.keys(report).sort(), ['direct', 'subprocess', 'worker']);
      for (const value of Object.values(report)) { assert.equal(value.defaultEnumerationVerified, true); assert.equal(value.expectedDefaultCount, 145); assert.deepEqual(value.output, ['local-only', 'local-only']); }
      assert.equal(requests(), 6);
    });
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('base role never admits an isolated QA CA and explicit QA requires its exact public reference', () => {
  const root = trustRoot();
  try {
    const { reference } = qaTrust(root);
    assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'base'), fixtureCA: reference, environment: neutralTrustEnv() }), /HOST_TRUST_FIXTURE_ROLE/);
    assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'missing'), role: 'native-qa', environment: neutralTrustEnv() }), /HOST_TRUST_FIXTURE_ROLE/);
    assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'wrong'), role: 'native-qa', fixtureCA: { ...reference, sha256: '0'.repeat(64) }, environment: neutralTrustEnv() }), /HOST_TRUST_FIXTURE_CHANGED/);
    assert.equal(fs.existsSync(path.join(root, 'base')), false); assert.equal(fs.existsSync(path.join(root, 'missing')), false);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('competing trust, npm bypasses, additive CA and CLI overrides refuse before the entry', async () => {
  const root = trustRoot();
  try {
    const prepared = prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() }), base = { ...neutralTrustEnv(), ...prepared.environment };
    for (const override of [{ NODE_USE_SYSTEM_CA: '0' }, { OPENSSL_CONF: 'unexpected' }, { NODE_TLS_REJECT_UNAUTHORIZED: '0' }, { NODE_EXTRA_CA_CERTS: prepared.descriptor.bundle.path }, { npm_config_strict_ssl: 'false' }, { npm_config_ca: 'unexpected' }, { npm_config_cafile: prepared.descriptor.bundle.path }, { npm_config_node_options: '--use-bundled-ca' }, { NODE_OPTIONS: '--use-openssl-ca' }]) {
      const result = await trustChild(['-e', "console.log('ENTRY_RAN')"], { ...base, ...override });
      // Without the mandatory bootstrap Node itself can run; the explicit guard must refuse.
      if (override.NODE_OPTIONS) {
        const guarded = await trustChild([trustHelper, 'verify'], { ...base, ...override }); assert.notEqual(guarded.code, 0);
      } else { assert.notEqual(result.code, 0); assert.equal(result.stdout.includes('ENTRY_RAN'), false); }
    }
    for (const flag of ['--use-bundled-ca', '--no-use-openssl-ca', '--tls-min-v1.0', '--tls-cipher-list=DEFAULT@SECLEVEL=0']) {
      const result = await trustChild([flag, '-e', "console.log('ENTRY_RAN')"], base); assert.notEqual(result.code, 0); assert.equal(result.stdout.includes('ENTRY_RAN'), false);
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('changed policy/bundle and nonempty root directory refuse before the actual entry', async () => {
  const root = trustRoot();
  try {
    for (const variant of ['policy', 'bundle', 'empty']) {
      const prepared = prepareHostNodeTrust({ directory: path.join(root, variant), environment: neutralTrustEnv() });
      if (variant === 'policy') fs.appendFileSync(prepared.policyRef.path, '\n');
      else if (variant === 'bundle') fs.appendFileSync(prepared.descriptor.bundle.path, '\n');
      else fs.writeFileSync(path.join(prepared.descriptor.emptyDirectory, 'unadmitted.pem'), 'public synthetic');
      const result = await trustChild(['-e', "console.log('ENTRY_RAN')"], { ...neutralTrustEnv(), ...prepared.environment });
      assert.notEqual(result.code, 0); assert.equal(result.stdout, ''); assert.equal(result.stderr.includes('BEGIN CERTIFICATE'), false);
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('changed checked helper or bootstrap source refuses before any entry code', async () => {
  const root = trustRoot();
  try {
    for (const name of ['host-node-trust.mjs', 'host-node-trust-start.mjs']) {
      const copy = path.join(root, name === 'host-node-trust.mjs' ? 'helper' : 'bootstrap'); fs.mkdirSync(copy, { mode: 0o700 });
      for (const source of ['host-node-trust.mjs', 'host-node-trust-start.mjs', 'tooling.json']) fs.copyFileSync(path.join(path.dirname(trustHelper), source), path.join(copy, source));
      const outer = fs.readFileSync(new URL('./setup-open-source-tooling.ps1', import.meta.url), 'utf8').match(/\$prepare = @'\n([\s\S]+?)\n'@/);
      assert.ok(outer);
      const setup = await trustChild(['--input-type=module', '-e', outer[1], copy, path.join(copy, 'policy')], neutralTrustEnv());
      assert.equal(setup.code, 0, setup.stderr); const prepared = JSON.parse(setup.stdout).prepared;
      fs.appendFileSync(path.join(copy, name), '\nconsole.log("UNADMITTED_CODE");\n');
      const result = await trustChild(['-e', "console.log('ENTRY_RAN')"], { ...neutralTrustEnv(), ...prepared.environment });
      assert.notEqual(result.code, 0); assert.equal(result.stdout, '');
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('public fixture descriptor failures close the actual FD before any policy output', () => {
  for (const variant of ['read', 'stat', 'growth', 'replacement', 'parent-symlink']) {
    const root = trustRoot(), parent = path.join(root, 'source'); fs.mkdirSync(parent, { mode: 0o700 });
    const cert = materials().trusted.cert, file = path.join(parent, 'ca.pem'); fs.writeFileSync(file, cert, { mode: 0o600 });
    const reference = { path: file, sha256: createHash('sha256').update(cert).digest('hex'), certificateSha256: new X509Certificate(cert).fingerprint256.replaceAll(':', '').toLowerCase() };
    const original = { open: fs.openSync, stat: fs.fstatSync, read: fs.readSync, close: fs.closeSync }; let fd, closed = false, injected = false;
    fs.openSync = (name, ...args) => { const opened = original.open(name, ...args); if (name === file && fd === undefined) fd = opened; return opened; };
    fs.fstatSync = (value, ...args) => { if (value === fd && variant === 'stat') throw new Error('SYNTHETIC_STAT_FAILURE'); return original.stat(value, ...args); };
    fs.readSync = (value, ...args) => {
      if (value === fd && !injected) {
        injected = true;
        if (variant === 'read') throw new Error('SYNTHETIC_READ_FAILURE');
        if (variant === 'growth') fs.appendFileSync(file, 'x'.repeat(1024));
        if (variant === 'replacement') { fs.renameSync(file, file + '.held'); fs.writeFileSync(file, cert, { mode: 0o600 }); }
        if (variant === 'parent-symlink') { fs.renameSync(parent, parent + '.held'); fs.symlinkSync(parent + '.held', parent, process.platform === 'win32' ? 'junction' : 'dir'); }
      }
      return original.read(value, ...args);
    };
    fs.closeSync = value => { if (value === fd) closed = true; return original.close(value); };
    try {
      assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'policy'), role: 'native-qa', fixtureCA: reference, environment: neutralTrustEnv() }));
      assert.equal(closed, true); assert.throws(() => original.stat(fd), { code: 'EBADF' }); assert.equal(fs.existsSync(path.join(root, 'policy')), false);
    } finally { Object.assign(fs, { openSync: original.open, fstatSync: original.stat, readSync: original.read, closeSync: original.close }); fs.rmSync(root, { recursive: true, force: true }); }
  }
});
test('host trust exclusive writer refuses zero progress and leaves no falsely completed policy', () => {
  const root = trustRoot(), original = fs.writeSync; let writes = 0;
  fs.writeSync = () => { writes++; return 0; };
  try {
    assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() }), /HOST_TRUST_WRITE_PROGRESS/);
    assert.equal(writes, 1); assert.equal(fs.existsSync(path.join(root, 'policy', 'policy.json')), false);
  } finally { fs.writeSync = original; fs.rmSync(root, { recursive: true, force: true }); }
});
test('zero, oversize, hardlinked, shared-write and symlink CA inputs refuse before reading policy secrets or creating output', () => {
  for (const variant of ['zero', 'oversize', 'hardlink', 'shared-write', 'symlink']) {
    const root = trustRoot(), file = path.join(root, 'ca.pem');
    try {
      const cert = materials().trusted.cert;
      fs.writeFileSync(file, variant === 'zero' ? '' : variant === 'oversize' ? Buffer.alloc(65537) : cert, { mode: 0o600 });
      if (variant === 'hardlink') fs.linkSync(file, file + '.alias');
      if (variant === 'shared-write' && process.platform !== 'win32') fs.chmodSync(file, 0o666);
      if (variant === 'shared-write' && process.platform === 'win32') { fs.unlinkSync(file); fs.mkdirSync(file); }
      if (variant === 'symlink') { fs.renameSync(file, file + '.original'); if (process.platform === 'win32') { fs.mkdirSync(file + '.directory'); fs.symlinkSync(file + '.directory', file, 'junction'); } else fs.symlinkSync(file + '.original', file); }
      const reference = { path: file, sha256: createHash('sha256').update(cert).digest('hex'), certificateSha256: createHash('sha256').update(new X509Certificate(cert).raw).digest('hex') };
      assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'policy'), role: 'native-qa', fixtureCA: reference, environment: neutralTrustEnv() }));
      assert.equal(fs.existsSync(path.join(root, 'policy')), false);
    } finally { fs.rmSync(root, { recursive: true, force: true }); }
  }
});
test('provisioning pins exact accepted Node/npm and clean official Appium driver releases', () => {
  const pins = JSON.parse(fs.readFileSync(new URL('./tooling.json', import.meta.url), 'utf8'));
  assert.equal(pins.node, '24.15.0'); assert.equal(pins.npm, '11.12.1');
  assert.equal(pins.appium, '3.9.0'); assert.equal(pins.xcuitest, '12.22.2'); assert.equal(pins.uiautomator2, '8.7.3'); assert.equal(pins.webdriverio, '10.1.0');
  for (const [name, expected] of Object.entries(pins.hostNodeTrust)) {
    assert.match(expected, /^[a-f0-9]{64}$/);
    const source = fs.readFileSync(new URL(name === 'helperSha256' ? './host-node-trust.mjs' : './host-node-trust-start.mjs', import.meta.url));
    assert.equal(createHash('sha256').update(source).digest('hex'), expected);
  }
});
test('the actual provisioner outer executes only pinned held helper bytes before npm', async () => {
  const root = trustRoot(), script = fs.readFileSync(new URL('./setup-open-source-tooling.ps1', import.meta.url), 'utf8');
  const match = script.match(/\$prepare = @'\n([\s\S]+?)\n'@/); assert.ok(match);
  assert.ok(script.indexOf("Invoke-OwnedNode 'trust-prepare'") < script.indexOf("Invoke-OwnedNode 'npm-version'"));
  assert.ok(script.indexOf("Invoke-OwnedNode 'trust-verify'") < script.indexOf("Invoke-OwnedNode 'core-install'"));
  assert.doesNotMatch(script, /Invoke-WebRequest|\$env:APPIUM_HOME\s*=/);
  try {
    const valid = await trustChild(['--input-type=module', '-e', match[1], path.dirname(trustHelper), path.join(root, 'valid')], neutralTrustEnv());
    assert.equal(valid.code, 0, valid.stderr); const q = JSON.parse(valid.stdout);
    assert.equal(q.prepared.descriptor.nodeVersion, '24.15.0'); assert.equal(q.pins.appium, '3.9.0');
    const source = path.join(root, 'source'); fs.mkdirSync(source, { mode: 0o700 });
    for (const name of ['tooling.json', 'host-node-trust.mjs', 'host-node-trust-start.mjs']) fs.copyFileSync(path.join(path.dirname(trustHelper), name), path.join(source, name));
    fs.appendFileSync(path.join(source, 'host-node-trust.mjs'), '\nconsole.log("UNADMITTED_SOURCE_EXECUTED");\n');
    const invalid = await trustChild(['--input-type=module', '-e', match[1], source, path.join(root, 'invalid')], neutralTrustEnv());
    assert.notEqual(invalid.code, 0); assert.equal(invalid.stdout, ''); assert.equal(invalid.stderr.trim(), 'HOST_TRUST_PREPARATION_REFUSED');
    assert.equal(fs.existsSync(path.join(root, 'invalid')), false);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('Windows provisioner cleanup statically requires a started exact child and current parent identity', () => {
  const source = fs.readFileSync(new URL('./setup-open-source-tooling.ps1', import.meta.url), 'utf8');
  assert.match(source, /\$started = \$false/);
  assert.match(source, /if \(-not \$process\.Start\(\)\) \{ throw[^\n]+\}\n\s+\$started = \$true/);
  assert.ok(source.indexOf('$childIdentity = Get-ProcessSnapshot $process.Id') < source.indexOf('$process.StandardOutput.BaseStream'));
  const cleanup = source.slice(source.indexOf('    finally {'), source.indexOf('    # Successful native tools'));
  assert.match(cleanup, /if \(\$started\)\s*\{[\s\S]+if \(-not \$process\.HasExited\)/);
  assert.match(cleanup, /Test-ExactSnapshot \$childIdentity \$freshChild/);
  assert.match(cleanup, /Test-ExactSnapshot \$parentIdentity \$freshParent/);
  assert.match(cleanup, /\$freshChild\[1\] -eq \[string\]\$PID/);
  assert.match(cleanup, /StartTime\.ToUniversalTime\(\)\.ToString\('o'\) -eq \$created/);
  assert.match(source, /\$row\.CreationDate\.ToUniversalTime\(\)\.ToString\('o'\)/);
  assert.match(source, /\[string\]\$row\.CommandLine/); assert.match(source, /\$row\.ExecutablePath/);
  assert.doesNotMatch(cleanup, /\.Kill\(\$true\)|Stop-Process|\$failure\s*=/);
  assert.match(cleanup, /\$cleanupFailure = 'Owned cleanup identity unavailable; no further signal/);
});
test('compiled OpenSSL root paths refuse through the production build guard, with controlled build fixtures distinguished', () => {
  assert.deepEqual(reviewHostNodeBuildConfiguration(), { compiledSystemCaPathEmpty: true });
  assert.deepEqual(reviewHostNodeBuildConfiguration({ openssl_system_ca_path: '' }), { compiledSystemCaPathEmpty: true });
  for (const value of ['/etc/ssl/cert.pem', 'C:/unreviewed/store.pem', false, 0, null]) {
    assert.throws(() => reviewHostNodeBuildConfiguration({ openssl_system_ca_path: value }), /HOST_TRUST_COMPILED_CA_PATH_UNREVIEWED/);
  }
});
test('a forged hash-correct public policy cannot turn the approved bootstrap into arbitrary helper execution', async () => {
  const root = trustRoot();
  try {
    const prepared = prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() });
    const malicious = path.join(root, 'source'); fs.mkdirSync(malicious, { mode: 0o700 });
    const file = path.join(malicious, 'host-node-trust.mjs'), body = Buffer.from('console.log("UNADMITTED_HELPER_EXECUTED");export function activateHostNodeTrust(){}\n');
    fs.writeFileSync(file, body, { mode: 0o600, flag: 'wx' });
    const changed = { ...prepared.descriptor, runtimeSource: { ...prepared.descriptor.runtimeSource, helper: { path: file, sha256: createHash('sha256').update(body).digest('hex'), sizeBytes: body.length } } };
    const policy = Buffer.from(JSON.stringify(changed)); fs.writeFileSync(prepared.policyRef.path, policy);
    const result = await trustChild(['-e', 'console.log("ENTRY_RAN")'], { ...neutralTrustEnv(), ...prepared.environment, CASEOPS_HOST_NODE_TRUST_POLICY_SHA256: createHash('sha256').update(policy).digest('hex') });
    assert.notEqual(result.code, 0); assert.equal(result.stdout, ''); assert.equal(result.stderr.trim(), 'HOST_TRUST_BOOTSTRAP_REFUSED');
    const bootstrap = fs.readFileSync(new URL('./host-node-trust-start.mjs', import.meta.url), 'utf8');
    const pinned = bootstrap.match(/const APPROVED_HELPER_SHA256 = '([a-f0-9]{64})'/); assert.ok(pinned);
    assert.equal(pinned[1], prepared.descriptor.runtimeSource.helper.sha256);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('unknown and modified import URIs refuse before preload or application entry', async () => {
  const root = trustRoot();
  try {
    const prepared = prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() });
    const bootstrap = fs.readFileSync(new URL('./host-node-trust-start.mjs', import.meta.url));
    const unknown = Buffer.from('console.log("UNADMITTED_PRELOAD");\n');
    const modified = Buffer.concat([bootstrap, unknown]);
    for (const body of [unknown, modified]) {
      const option = '--import=data:text/javascript;base64,' + body.toString('base64');
      const result = await trustChild([option, '-e', 'console.log("ENTRY_RAN")'], { ...neutralTrustEnv(), ...prepared.environment });
      assert.notEqual(result.code, 0); assert.equal(result.stdout, '');
      assert.equal(result.stderr.includes('UNADMITTED_PRELOAD'), false);
      assert.equal(result.stderr.includes('HOST_TRUST_CLI_OVERRIDE_REFUSED'), true);
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});


import { createRequire as ciTrustCreateRequire, syncBuiltinESMExports } from 'node:module';
import { appendCITrustOutputs, prepareCIHostNodeTrust, prepareCIHostNodeTrustWindows, ciTrustFailureCode, reviewCIHostSourceAclOutput, reviewCICommandOwnerResult } from './host-node-trust-ci.mjs';
const ciTrustYaml = ciTrustCreateRequire(new URL('../../apps/mobile/package.json', import.meta.url))('js-yaml');
const ciTrustKeys = ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256', 'NPM_CONFIG_USERCONFIG', 'NPM_CONFIG_GLOBALCONFIG', 'NPM_CONFIG_STRICT_SSL', 'NPM_CONFIG_REGISTRY'];
const ciTrustValues = Object.fromEntries(ciTrustKeys.map(key => [key, 'public-fixture-' + key]));
function ciTrustFiles(callback) {
  const root = trustRoot(), file = path.join(root, 'commands');
  fs.writeFileSync(file, 'EARLIER=retained', { flag: 'wx', mode: 0o600 });
  fs.mkdirSync(path.join(root, 'workspace'), { mode: 0o700 });
  try { return callback({ root, file }); }
  finally { fs.rmSync(root, { recursive: true, force: true }); }
}
test('CI trust output append preserves prior bytes and writes only nine exact single-line outputs', () => ciTrustFiles(({ root, file }) => {
  const result = appendCITrustOutputs(file, root, ciTrustValues);
  const expected = 'EARLIER=retained\n' + ciTrustKeys.map(key => key + '=' + ciTrustValues[key] + '\n').join('');
  assert.equal(fs.readFileSync(file, 'utf8'), expected);
  assert.deepEqual(result, { appendedKeys: 9, previousBytes: 16, finalBytes: Buffer.byteLength(expected) });
}));
test('CI trust output refuses extra keys and multiline output injection before any write', () => ciTrustFiles(({ root, file }) => {
  const original = fs.readFileSync(file);
  for (const value of [{ ...ciTrustValues, PATH: 'unreviewed' }, { ...ciTrustValues, NODE_OPTIONS: 'one\nUNREVIEWED=two' }, { ...ciTrustValues, SSL_CERT_FILE: 'one\rtwo' }]) {
    assert.throws(() => appendCITrustOutputs(file, root, value));
    assert.deepEqual(fs.readFileSync(file), original);
  }
}));
test('CI trust output refuses an out-of-runner file without modifying it', () => ciTrustFiles(({ root }) => {
  const outside = trustRoot(), file = path.join(outside, 'commands'); fs.writeFileSync(file, 'unchanged', { mode: 0o600 });
  try { assert.throws(() => appendCITrustOutputs(file, root, ciTrustValues), /CI_TRUST_RUNNER_SCOPE/); assert.equal(fs.readFileSync(file, 'utf8'), 'unchanged'); }
  finally { fs.rmSync(outside, { recursive: true, force: true }); }
}));
test('CI trust output refuses hardlinked and oversized command files before mutation', () => ciTrustFiles(({ root, file }) => {
  const alias = path.join(root, 'alias'); fs.linkSync(file, alias);
  assert.throws(() => appendCITrustOutputs(file, root, ciTrustValues), /CI_TRUST_COMMAND_FILE/);
  assert.equal(fs.readFileSync(file, 'utf8'), 'EARLIER=retained'); fs.unlinkSync(alias);
  fs.writeFileSync(file, Buffer.alloc(1048577, 0x61));
  assert.throws(() => appendCITrustOutputs(file, root, ciTrustValues), /CI_TRUST_COMMAND_FILE/);
  assert.equal(fs.statSync(file).size, 1048577);
}));
test('CI trust output closes its retained descriptor and rejects a replacement pathname after write', () => ciTrustFiles(({ root, file }) => {
  const originalOpen = fs.openSync, originalWrite = fs.writeSync, selected = new Set(); let changed = false;
  fs.openSync = (name, ...args) => { const fd = originalOpen(name, ...args); if (name === file) selected.add(fd); return fd; };
  fs.writeSync = (fd, ...args) => {
    const count = originalWrite(fd, ...args);
    if (selected.has(fd) && !changed) { changed = true; fs.renameSync(file, path.join(root, 'retained-original')); fs.writeFileSync(file, 'replacement', { mode: 0o600, flag: 'wx' }); }
    return count;
  };
  try { assert.throws(() => appendCITrustOutputs(file, root, ciTrustValues), /CI_TRUST_NAMED_DESCRIPTOR_CHANGED/); }
  finally { fs.openSync = originalOpen; fs.writeSync = originalWrite; }
  assert.equal(changed, true); assert.equal(fs.readFileSync(file, 'utf8'), 'replacement');
  for (const fd of selected) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
}));
test('CI trust preparation requires explicit GitHub CI and never edits the global environment file', () => ciTrustFiles(({ root, file }) => {
  const global = path.join(root, 'global-env'); fs.writeFileSync(global, 'PYTHON_SCOPE=preserved', { mode: 0o600 });
  const environment = { ...neutralTrustEnv(), CI: 'true', GITHUB_ACTIONS: 'true', RUNNER_TEMP: root, CASEOPS_CI_WORKSPACE: path.join(root, 'workspace'), GITHUB_OUTPUT: file, GITHUB_ENV: global };
  for (const key of ['CI', 'GITHUB_ACTIONS']) assert.throws(() => prepareCIHostNodeTrust({ ...environment, [key]: 'false' }));
  const projectConfig = path.join(root, 'workspace', '.npmrc'); fs.writeFileSync(projectConfig, 'cafile=unreviewed-public-fixture\n', { mode: 0o600 });
  assert.throws(() => prepareCIHostNodeTrust(environment), /CI_TRUST_PROJECT_NPMRC_UNREVIEWED/); fs.unlinkSync(projectConfig);
  const result = prepareCIHostNodeTrust(environment);
  assert.equal(result.nodeVersion, process.versions.node); assert.equal(result.appendedKeys, 9);
  assert.equal(fs.readFileSync(global, 'utf8'), 'PYTHON_SCOPE=preserved');
  const rows = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).slice(1);
  assert.deepEqual(rows.map(row => row.slice(0, row.indexOf('='))), ciTrustKeys);
}));
test('CI trust output activates the actual Node child before its entry and leaves its parent environment unchanged', () => ciTrustFiles(({ root, file }) => {
  const before = Object.fromEntries(ciTrustKeys.map(key => [key, process.env[key]]));
  prepareCIHostNodeTrust({ ...neutralTrustEnv(), CI: 'true', GITHUB_ACTIONS: 'true', RUNNER_TEMP: root, CASEOPS_CI_WORKSPACE: path.join(root, 'workspace'), GITHUB_OUTPUT: file });
  const scoped = Object.fromEntries(fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).slice(1).map(row => { const i = row.indexOf('='); return [row.slice(0, i), row.slice(i + 1)]; }));
  const text = execFileSync(process.execPath, [trustHelper, 'verify'], { env: { ...neutralTrustEnv(), ...scoped }, timeout: 12000, maxBuffer: 16384, encoding: 'utf8' });
  const proof = JSON.parse(text); assert.equal(proof.selectedStoreVerified, true); assert.equal(proof.nodeVersion, process.versions.node);
  assert.ok(ciTrustKeys.every(key => process.env[key] === before[key]), 'CI_PARENT_ENVIRONMENT_UNCHANGED');
}));
test('CI preparation rejects a project config inserted during policy creation before issuing command outputs', () => ciTrustFiles(({ root, file }) => {
  const workspace = path.join(root, 'workspace'), config = path.join(workspace, '.npmrc');
  const original = fs.mkdtempSync; let inserted = false;
  fs.mkdtempSync = (...args) => {
    const created = original(...args);
    if (String(args[0]).startsWith(path.join(root, 'caseops-node-trust-'))) {
      fs.writeFileSync(config, 'cafile=unreviewed-public-fixture\n', { mode: 0o600, flag: 'wx' }); inserted = true;
    }
    return created;
  };
  try {
    assert.throws(() => prepareCIHostNodeTrust({ ...neutralTrustEnv(), CI: 'true', GITHUB_ACTIONS: 'true', RUNNER_TEMP: root, CASEOPS_CI_WORKSPACE: workspace, GITHUB_OUTPUT: file }), /CI_TRUST_PROJECT_(?:NPMRC_UNREVIEWED|CHANGED)/);
  } finally { fs.mkdtempSync = original; }
  assert.equal(inserted, true); assert.equal(fs.readFileSync(file, 'utf8'), 'EARLIER=retained');
}));
test('CI preparation refuses to complete when a project config appears during the output append', () => ciTrustFiles(({ root, file }) => {
  const workspace = path.join(root, 'workspace'), originalOpen = fs.openSync, originalWrite = fs.writeSync;
  let commandFD, inserted = false;
  fs.openSync = (name, ...args) => { const fd = originalOpen(name, ...args); if (name === file) commandFD = fd; return fd; };
  fs.writeSync = (fd, ...args) => {
    const count = originalWrite(fd, ...args);
    if (fd === commandFD && !inserted) { fs.writeFileSync(path.join(workspace, '.npmrc'), 'cafile=unreviewed-public-fixture\n', { mode: 0o600, flag: 'wx' }); inserted = true; }
    return count;
  };
  try {
    assert.throws(() => prepareCIHostNodeTrust({ ...neutralTrustEnv(), CI: 'true', GITHUB_ACTIONS: 'true', RUNNER_TEMP: root, CASEOPS_CI_WORKSPACE: workspace, GITHUB_OUTPUT: file }), /CI_TRUST_PROJECT_(?:NPMRC_UNREVIEWED|CHANGED)/);
  } finally { fs.openSync = originalOpen; fs.writeSync = originalWrite; }
  assert.equal(inserted, true); assert.ok(fs.readFileSync(file, 'utf8').length > 16, 'retain written output separately from failed completion');
  assert.throws(() => fs.fstatSync(commandFD), { code: 'EBADF' });
}));
test('CI workflows scope the nine trust outputs to Node commands and retain exact conditional setup admission', () => {
  let setupCount = 0, commandCount = 0;
  for (const name of ['ci.yml', 'mobile-source.yml', 'security.yml', 'release-verify.yml', 'prod-verify.yml']) {
    const workflow = ciTrustYaml.load(readFileSync(new URL('../../.github/workflows/' + name, import.meta.url), 'utf8'));
    assert.ok(ciTrustKeys.every(key => !Object.hasOwn(workflow.env ?? {}, key)));
    for (const job of Object.values(workflow.jobs)) {
      assert.ok(ciTrustKeys.every(key => !Object.hasOwn(job.env ?? {}, key)));
      let setup, trust;
      for (const step of job.steps ?? []) {
        if (step.uses === 'actions/setup-node@v4') { setup = step; trust = null; assert.ok(['22.23.4', '24.15.0'].includes(step.with['node-version'])); setupCount++; }
        if (step.uses === './.github/actions/node-trust') { assert.ok(setup && !trust); assert.equal(step.id, 'node_trust'); assert.equal(step.if, setup.if); trust = step; }
        const isNode = typeof step.run === 'string' && /\b(?:npm|npx|node)\s|bash\s+"\$RUNNER_TEMP\/caseops-prod-playwright"/.test(step.run);
        if (isNode) { assert.ok(trust, 'Node command requires prepared policy: ' + name); commandCount++; }
        for (const key of ciTrustKeys) {
          if (isNode) assert.equal(step.env?.[key], '${{ steps.node_trust.outputs.' + key + ' }}');
          else assert.equal(Object.hasOwn(step.env ?? {}, key), false, 'Non-Node step must keep its own runtime environment');
        }
      }
    }
  }
  assert.equal(setupCount, 15); assert.equal(commandCount, 106);
  const action = ciTrustYaml.load(readFileSync(new URL('../../.github/actions/node-trust/action.yml', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(action.outputs).sort(), [...ciTrustKeys].sort());
  for (const key of ciTrustKeys) assert.equal(action.outputs[key].value, '${{ steps.prepare.outputs.' + key + ' }}');
  assert.equal(action.runs.steps[0].id, 'prepare');
});


test('actual Next page-data Worker preserves inherited default HTTPS and fetch verification', async () => {
  const root = trustRoot();
  try {
    const { reference, prepared } = qaTrust(root);
    for (const [name, expected] of [['trusted', 'local-only'], ['untrusted', 'DEPTH_ZERO_SELF_SIGNED_CERT'], ['wrongHost', 'ERR_TLS_CERT_ALTNAME_INVALID']]) {
      await localTls(materials()[name], async (origin, requests) => {
        const result = await trustChild([trustFixture, 'next-worker', origin], { ...neutralTrustEnv(), ...prepared.environment, CASEOPS_TEST_FIXTURE_CA: JSON.stringify(reference) });
        assert.equal(result.code, 0, result.stderr); const report = JSON.parse(result.stdout);
        assert.equal(report.defaultEnumerationVerified, true); assert.equal(report.expectedDefaultCount, 145);
        assert.deepEqual(report.output, [expected, expected]); assert.equal(requests(), name === 'trusted' ? 2 : 0);
      });
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});


test('reviewed source-map inheritance keeps every extra preload and proxy override closed', async () => {
  const root = trustRoot();
  try {
    const prepared = prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() });
    const base = { ...neutralTrustEnv(), ...prepared.environment }, allowed = base.NODE_OPTIONS + ' --enable-source-maps';
    assert.ok(Buffer.byteLength(allowed) <= 8191, 'BOOTSTRAP_OPTIONS_MUST_REMAIN_WITHIN_WINDOWS_CMD_ENV_BOUND');
    const positive = await trustChild([trustHelper, 'verify'], { ...base, NODE_OPTIONS: allowed });
    assert.equal(positive.code, 0, positive.stderr); assert.equal(JSON.parse(positive.stdout).expectedDefaultCount, 144);
    for (const options of [allowed + ' --enable-source-maps', allowed + ' --import=data:text/javascript,console.log(%22UNADMITTED_PRELOAD_EXECUTED%22)', allowed + ' --use-env-proxy', allowed + ' --use-openssl-ca', '--enable-source-maps ' + base.NODE_OPTIONS]) {
      const result = await trustChild([trustHelper, 'verify'], { ...base, NODE_OPTIONS: options });
      assert.notEqual(result.code, 0); assert.doesNotMatch(result.stdout, /UNADMITTED_PRELOAD_EXECUTED/);
    }
    for (const key of ['NODE_USE_ENV_PROXY', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY']) {
      const result = await trustChild([trustHelper, 'verify'], { ...base, NODE_OPTIONS: allowed, [key]: 'unreviewed' });
      assert.notEqual(result.code, 0); assert.match(result.stderr, /HOST_TRUST_OVERRIDE_REFUSED/);
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('Windows ACL proof keeps current-owner and foreign-writer failures distinct and strict', () => {
  assert.deepEqual(reviewHostNodeWindowsAclProof({ ownerMatches: true, writeScopeSafe: true }), { ownerMatches: true, writeScopeSafe: true });
  assert.throws(() => reviewHostNodeWindowsAclProof({ ownerMatches: false, writeScopeSafe: true }), /HOST_TRUST_CURRENT_OWNER_REQUIRED/);
  for (const value of [false, 'true', 1, null]) assert.throws(() => reviewHostNodeWindowsAclProof({ ownerMatches: true, writeScopeSafe: value }), /HOST_TRUST_WINDOWS_WRITE_SCOPE_REQUIRED/);
  assert.throws(() => reviewHostNodeWindowsAclProof({ ownerMatches: true, writeScopeSafe: true, arbitrary: true }), /HOST_TRUST_SCHEMA/);
});

test('all Windows owner queries refuse an arbitrary token-default group with implied DACL authority', () => {
  const expected = "($o -eq $u -or ($o -eq $t -and $o -in @('S-1-5-18','S-1-5-32-544')))";
  for (const name of ['host-node-trust.mjs', 'host-node-trust-start.mjs', 'host-node-trust-ci.mjs']) {
    const source = fs.readFileSync(new URL(name, import.meta.url), 'utf8');
    const literal = source.match(/const code = ("[^\n]+");/);
    assert.ok(literal, name); const query = JSON.parse(literal[1]);
    const condition = query.match(/(?:\$ok=|ownerMatches=)(\([^;]+\));/);
    assert.ok(condition, name); assert.equal(condition[1], expected, name);
    // These literal identities are independent of the OS query. This source
    // contract does not claim that Windows ACLs were exercised on another OS.
    const trustedDefaultOwners = [...condition[1].matchAll(/'(S-[0-9-]+)'/g)].map(row => row[1]);
    assert.deepEqual(trustedDefaultOwners, ['S-1-5-18', 'S-1-5-32-544']);
    for (const [user, tokenOwner, owner, permitted] of [
      ['S-1-5-21-1000', 'S-1-5-21-9999', 'S-1-5-21-9999', false],
      ['S-1-5-21-1000', 'S-1-5-32-544', 'S-1-5-21-9999', false],
      ['S-1-5-21-1000', 'S-1-5-21-9999', 'S-1-5-21-1000', true],
      ['S-1-5-21-1000', 'S-1-5-32-544', 'S-1-5-32-544', true],
      ['S-1-5-21-1000', 'S-1-5-18', 'S-1-5-18', true],
      ['S-1-5-21-1000', 'S-1-5-21-9999', 'S-1-5-32-544', false],
    ]) assert.equal(owner === user || owner === tokenOwner && trustedDefaultOwners.includes(owner), permitted, name);
  }
});

test('Windows ownership refusal precedes descriptor bytes and closes every opened source', () => {
  // This is an actual filesystem/constructor composition with injected Windows
  // OS proof responses. It is not an actual Windows ACL acceptance claim on Mac.
  const require = ciTrustCreateRequire(import.meta.url), cp = require('node:child_process');
  const originalSpawn = cp.spawnSync, originalUid = Object.getOwnPropertyDescriptor(process, 'getuid'), originalPlatform = Object.getOwnPropertyDescriptor(process, 'platform');
  const originalSystemRoot = process.env.SystemRoot, originalOpen = fs.openSync, originalRead = fs.readSync;
  const root = trustRoot();
  try {
    process.env.SystemRoot = root; Object.defineProperty(process, 'getuid', { configurable: true, value: undefined }); Object.defineProperty(process, 'platform', { configurable: true, value: 'win32' });
    const completed = 'COPS_ACL0\nCOPS_ACL1\nCOPS_ACL2\nCOPS_ACL3\n';
    for (const [code, baseResult] of [
      ['HOST_TRUST_CURRENT_OWNER_REQUIRED', { status: 0, stdout: JSON.stringify({ ownerMatches: false, writeScopeSafe: true }) }],
      ['HOST_TRUST_WINDOWS_WRITE_SCOPE_REQUIRED', { status: 0, stdout: JSON.stringify({ ownerMatches: true, writeScopeSafe: false }) }],
      ['HOST_TRUST_WINDOWS_ACL_PROTOCOL', { status: 0, stdout: 'malformed' }],
      ...['NO_MARKER', 'SCRIPT_ENTERED', 'ACL_READ', 'IDENTITY_READ', 'RULES_READ'].map((phase, index) => [
        'HOST_TRUST_WINDOWS_ACL_TIMEOUT_' + phase,
        { status: null, error: { code: 'ETIMEDOUT' }, stdout: '', stderr: completed.split('\n').slice(0, index).join('\n') + (index ? '\n' : '') },
      ]),
    ]) {
      const result = { stderr: completed, ...baseResult };
      const fds = []; let reads = 0, commands = 0;
      fs.openSync = (...args) => { const fd = originalOpen(...args); fds.push(fd); return fd; };
      fs.readSync = (...args) => { reads++; return originalRead(...args); };
      cp.spawnSync = (executable, args, options) => { commands++; assert.equal(executable, path.join(root, 'System32/WindowsPowerShell/v1.0/powershell.exe')); assert.match(args.at(-1), /\$t=\$i\.Owner\.Value/); assert.equal(options.env.CASEOPS_TRUST_ACL_KIND, 'file'); assert.equal(options.timeout, 5000); return result; };
      syncBuiltinESMExports();
      assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'never-created'), environment: neutralTrustEnv() }), new RegExp(code));
      assert.equal(commands, 1); assert.equal(reads, 0); assert.ok(fds.length > 0); for (const fd of fds) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
    }
  } finally {
    fs.openSync = originalOpen; fs.readSync = originalRead; cp.spawnSync = originalSpawn; syncBuiltinESMExports();
    Object.defineProperty(process, 'getuid', originalUid); Object.defineProperty(process, 'platform', originalPlatform);
    if (originalSystemRoot === undefined) delete process.env.SystemRoot; else process.env.SystemRoot = originalSystemRoot;
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('CI preparation diagnostics reflect only reviewed fixed labels and no raw error data', () => {
  assert.equal(ciTrustFailureCode(new Error('HOST_TRUST_WINDOWS_ACL_TIMEOUT')), 'HOST_TRUST_WINDOWS_ACL_TIMEOUT');
  assert.equal(ciTrustFailureCode(new Error('CI_TRUST_COMMAND_OWNER\nPRIVATE_OWNER_VALUE')), 'CI_TRUST_COMMAND_OWNER');
  for (const value of [new Error('PRIVATE_PASSWORD'), new Error('https://private.invalid/owner'), { message: { private: true } }, null]) assert.equal(ciTrustFailureCode(value), 'CI_TRUST_PREPARATION_REFUSED');
  for (const phase of ['NO_MARKER', 'SCRIPT_ENTERED', 'ACL_READ', 'IDENTITY_READ', 'RULES_READ', 'UNCLASSIFIED']) assert.equal(ciTrustFailureCode(new Error('HOST_TRUST_WINDOWS_ACL_TIMEOUT_' + phase)), 'HOST_TRUST_WINDOWS_ACL_TIMEOUT_' + phase);
});

test('Windows ACL queries use only direct Framework metadata APIs with unchanged owner and complete ACE scope', () => {
  for (const name of ['host-node-trust.mjs', 'host-node-trust-start.mjs', 'host-node-trust-ci.mjs']) {
    const source = fs.readFileSync(new URL(name, import.meta.url), 'utf8'), match = source.match(/const code = ("[^\n]+");/);
    assert.ok(match, name); const query = JSON.parse(match[1]);
    assert.match(query, /\[IO\.File\]::GetAccessControl\(\$env:CASEOPS_TRUST_ACL_PATH,\$s\)/);
    assert.match(query, /\$s=\[Security\.AccessControl\.AccessControlSections\]'Access,Owner'/);
    assert.ok(query.includes('$a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])'));
    assert.ok(query.includes("$r.AccessControlType -eq 'Allow'")); assert.ok(query.includes('-band 852310'));
    assert.ok(query.includes("@($u,'S-1-5-18','S-1-5-32-544','S-1-3-0')"));
    assert.doesNotMatch(query, /\b(?:Get-Acl|Import-Module|ConvertTo-Json|Get-Content|Invoke-Expression|Start-Process)\b/i);
    for (let index = 0; index < 4; index++) assert.equal(query.split("WriteLine('COPS_ACL" + index + "')").length, 2);
    assert.ok(query.includes("catch{[Console]::Error.WriteLine('COPS_ACL_FAIL');exit 1}"));
    if (name === 'host-node-trust.mjs') assert.match(query, /\[IO\.Directory\]::GetAccessControl\(\$env:CASEOPS_TRUST_ACL_PATH,\$s\)/);
    else assert.doesNotMatch(query, /\[IO\.Directory\]/);
  }
});

test('Windows ACL milestone decoder accepts ordered fixed prefixes and never reflects an arbitrary diagnostic', () => {
  const markers = ['COPS_ACL0', 'COPS_ACL1', 'COPS_ACL2', 'COPS_ACL3'];
  for (const [index, expected] of ['NO_MARKER', 'SCRIPT_ENTERED', 'ACL_READ', 'IDENTITY_READ', 'RULES_READ'].entries())
    assert.equal(reviewHostNodeWindowsAclPhase(markers.slice(0, index).join('\r\n') + (index ? '\r\n' : '')), expected);
  for (const invalid of ['PRIVATE_OWNER_SID', 'COPS_ACL1\n', 'COPS_ACL0\nCOPS_ACL0\n', 'COPS_ACL0\nCOPS_ACL_FAIL\n', 'COPS_ACL0\nPRIVATE_PATH\n', 'x'.repeat(4097)]) assert.equal(reviewHostNodeWindowsAclPhase(invalid), 'UNCLASSIFIED');
});

test('CI Windows ACL completion markers are mandatory before writing even when SAFE was returned', () => ciTrustFiles(({ root, file }) => {
  const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), original = cp.spawnSync, uid = Object.getOwnPropertyDescriptor(process, 'getuid'), platform = Object.getOwnPropertyDescriptor(process, 'platform'), systemRoot = process.env.SystemRoot;
  const bytes = fs.readFileSync(file), completed = 'COPS_ACL0\r\nCOPS_ACL1\r\nCOPS_ACL2\r\nCOPS_ACL3\r\n'; let calls = 0;
  try {
    process.env.SystemRoot = root; Object.defineProperty(process, 'getuid', { configurable: true, value: undefined }); Object.defineProperty(process, 'platform', { configurable: true, value: 'win32' });
    for (const stderr of ['', 'COPS_ACL0\n', completed + 'PRIVATE_PATH\n']) {
      cp.spawnSync = (executable, args, options) => { calls++; assert.equal(options.timeout, 4000); assert.doesNotMatch(args.at(-1), /Get-Acl|ConvertTo-Json/); return { status: 0, stdout: 'SAFE', stderr }; }; syncBuiltinESMExports();
      assert.throws(() => appendCITrustOutputs(file, root, ciTrustValues), /CI_TRUST_COMMAND_OWNER/); assert.deepEqual(fs.readFileSync(file), bytes);
    }
    cp.spawnSync = () => { calls++; return { status: 0, stdout: 'SAFE', stderr: completed }; }; syncBuiltinESMExports();
    assert.equal(appendCITrustOutputs(file, root, ciTrustValues).appendedKeys, 9); assert.equal(calls, 4);
  } finally {
    cp.spawnSync = original; syncBuiltinESMExports(); Object.defineProperty(process, 'getuid', uid); Object.defineProperty(process, 'platform', platform);
    if (systemRoot === undefined) delete process.env.SystemRoot; else process.env.SystemRoot = systemRoot;
  }
}));
// iOS host launch tests are constructor/source contracts, not a native build.
function iosProjectionFixture() {
  const base = '/SYNTHETIC/owned-ios-host';
  const paths = Object.fromEntries(['home', 'empty', 'bin', 'cache', 'pods', 'repos', 'temporary', 'build', 'runtime'].map(k => [k, base + '/' + k]));
  const policy = { paths, podHome: '/SYNTHETIC/Cellar/pods/libexec', rubyGems: '/SYNTHETIC/Cellar/ruby/lib/ruby/gems/4.0.0', deadlineEpochMs: Date.now() + 60000,
    tools: { node: { path: '/SYNTHETIC/node24' }, ruby: { path: '/SYNTHETIC/ruby4' }, curl: { path: '/usr/bin/curl' }, git: { path: '/SYNTHETIC/git' } },
    shims: { node: { path: paths.bin + '/node' } }, bundle: { path: base + '/ruby188.pem', sha256: '1'.repeat(64), sizeBytes: 100 }, fixtureCA: null,
    nodeNpm: { user: { path: base + '/npm-user.npmrc' }, global: { path: base + '/npm-global.npmrc' }, cli: { path: '/SYNTHETIC/node24/lib/node_modules/npm/bin/npm-cli.js' } },
    source: { 'ios-host-pods.rb': { sha256: IOS_PODS_SOURCE_SHA256 } } };
  const environment = { NODE_OPTIONS: '--use-openssl-ca --import=data:text/javascript;base64,REVIEWED', SSL_CERT_FILE: base + '/node144.pem', SSL_CERT_DIR: base + '/node-empty',
    CASEOPS_HOST_NODE_TRUST_POLICY_FILE: base + '/node.json', CASEOPS_HOST_NODE_TRUST_POLICY_SHA256: '2'.repeat(64) };
  const admitted = { policy, node: { environment }, bundle: { bytes: Buffer.from('SYNTHETIC-PUBLIC-CA') },
    podsSource: Buffer.from('# SYNTHETIC CONTRACT SOURCE'), podEntry: Buffer.from('# SYNTHETIC POD ENTRY') };
  const ref = { path: base + '/policy.json', sha256: '3'.repeat(64), sizeBytes: 100 };
  return { policy, admitted, ref, environment };
}
function curlDownloaderArgs(output = '/SYNTHETIC/owned-ios-host/cache/package.tgz') {
  return ['-f', '-L', '-o', output, 'https://packages.contract-fixture.org/file.tgz', '--create-dirs', '--netrc-optional', '--retry', '2'];
}
test('iOS Node and Pods constructors use separate stores and owned HOME without global environment mutation', () => {
  const f = iosProjectionFixture(), input = { EXPO_PUBLIC_API_ORIGIN: 'https://api.contract-fixture.org' }, before = { ...input };
  const node = iosHostCommandProjection(f.admitted, f.ref, 'node', ['--print', '1'], input);
  const pod = iosHostCommandProjection(f.admitted, f.ref, 'pod', ['install', '--deployment', '--no-repo-update'], input);
  assert.equal(node.environment.SSL_CERT_FILE, '/SYNTHETIC/owned-ios-host/node144.pem');
  assert.equal(node.environment.NPM_CONFIG_USERCONFIG, f.policy.nodeNpm.user.path); assert.equal(node.environment.NPM_CONFIG_STRICT_SSL, 'true');
  assert.equal(pod.environment.SSL_CERT_FILE, '/SYNTHETIC/owned-ios-host/ruby188.pem');
  assert.equal(pod.environment.NODE_OPTIONS, undefined); assert.equal(pod.environment.NODE_EXTRA_CA_CERTS, undefined);
  assert.equal(pod.environment.NPM_CONFIG_USERCONFIG, undefined);
  assert.equal(pod.environment.HOME, '/SYNTHETIC/owned-ios-host/home'); assert.equal(pod.environment.GEM_PATH, '/SYNTHETIC/Cellar/pods/libexec:/SYNTHETIC/Cellar/ruby/lib/ruby/gems/4.0.0');
  assert.equal(pod.executable, '/SYNTHETIC/ruby4'); assert.deepEqual(pod.args, ['-', 'install', '--deployment', '--no-repo-update']);
  assert.equal(pod.input.toString(), '# SYNTHETIC CONTRACT SOURCE\nCaseopsIosPods.run\n'); pod.input.fill(0);
  assert.equal(pod.environment.NODE_BINARY, '/SYNTHETIC/owned-ios-host/bin/node'); assert.deepEqual(input, before);
});
test('iOS neutral Xcode and offline tools receive no Node or Ruby CA environment', () => {
  const f = iosProjectionFixture(), result = iosHostCommandProjection(f.admitted, f.ref, 'xcodebuild', ['build'], { ...f.environment, HOME: f.policy.paths.home });
  for (const key of ['SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_OPTIONS', 'NODE_EXTRA_CA_CERTS', 'GEM_HOME', 'GEM_PATH']) assert.equal(result.environment[key], undefined, key);
  assert.equal(result.environment.NODE_BINARY, f.policy.paths.bin + '/node');
  assert.equal(result.environment.LANG, 'en_US.UTF-8'); assert.equal(result.environment.LC_ALL, 'en_US.UTF-8');
});
test('iOS cross-role rebind permits only the exact admitted previous recipe and rejects foreign overrides', () => {
  for (const field of ['SSL_CERT_FILE', 'SSL_CERT_DIR', 'NODE_OPTIONS', 'NODE_EXTRA_CA_CERTS', 'GEM_HOME', 'HOME', 'RUBYOPT', 'HTTPS_PROXY', 'OPENSSL_CONF']) {
    const f = iosProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', ['-v'], { [field]: 'UNADMITTED' }), /IOS_HOST_CROSS_ROLE_OVERRIDE/);
  }
  assert.throws(() => neutralIosEnvironment({ PRIVATE_OPERATOR_TOKEN: 'SYNTHETIC_ONLY' }), /IOS_HOST_UNREVIEWED_ENVIRONMENT/);
  for (const name of ['CASEOPS_MOBILE_PASSWORD', 'CASEOPS_MOBILE_EMAIL', 'CASEOPS_STORE_BUILD_PRIVATE_KEY', 'CODE_SIGN_PASSWORD'])
    assert.throws(() => neutralIosEnvironment({ [name]: 'SYNTHETIC_UNADMITTED' }), /IOS_HOST_UNREVIEWED_ENVIRONMENT/);
  const f = iosProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { GIT_CONFIG_GLOBAL: '/operator/config' }), /IOS_HOST_OWNER_GIT_CONFIG_REFUSED/);
});
test('iOS actual Podfile flags survive the Pods to Node autolinking constructor with scoped trust and deadline', () => {
  const args = ['--no-warnings', '--eval', "require('expo/bin/autolinking')", 'expo-modules-autolinking', 'resolve', '--platform', 'apple', '--json'];
  for (let bits = 0; bits < 16; bits++) {
    const f = iosProjectionFixture(), deadline = String(Date.now() + 5000);
    f.policy.fixtureCA = { path: f.policy.paths.home + '/public-fixture.pem', sha256: '4'.repeat(64), certificateSha256: '5'.repeat(64) };
    f.environment.NODE_EXTRA_CA_CERTS = f.policy.fixtureCA.path;
    const flags = { EXPO_USE_PRECOMPILED_MODULES: String(bits & 1), EX_DEV_CLIENT_NETWORK_INSPECTOR: bits & 2 ? 'true' : 'false',
      RCT_USE_PREBUILT_RNCORE: String((bits >> 2) & 1), RCT_USE_RN_DEP: String((bits >> 3) & 1) };
    const pod = iosHostCommandProjection(f.admitted, f.ref, 'pod', ['install'], { CASEOPS_IOS_HOST_OUTER_DEADLINE: deadline });
    const inherited = { ...pod.environment, ...flags }, before = { ...inherited };
    const node = iosHostCommandProjection(f.admitted, f.ref, 'node', args, inherited);
    assert.deepEqual(node.args, args); assert.equal(node.executable, f.policy.tools.node.path);
    for (const [name, value] of Object.entries(flags)) assert.equal(node.environment[name], value, name);
    assert.equal(node.environment.NODE_OPTIONS, f.environment.NODE_OPTIONS);
    assert.equal(node.environment.SSL_CERT_FILE, f.environment.SSL_CERT_FILE); assert.equal(node.environment.SSL_CERT_DIR, f.environment.SSL_CERT_DIR);
    assert.equal(node.environment.NODE_EXTRA_CA_CERTS, f.policy.fixtureCA.path);
    assert.equal(node.environment.CASEOPS_HOST_NODE_TRUST_POLICY_FILE, f.environment.CASEOPS_HOST_NODE_TRUST_POLICY_FILE);
    assert.equal(node.environment.CASEOPS_HOST_NODE_TRUST_POLICY_SHA256, f.environment.CASEOPS_HOST_NODE_TRUST_POLICY_SHA256);
    assert.equal(node.environment.CASEOPS_IOS_HOST_OUTER_DEADLINE, deadline); assert.deepEqual(inherited, before);
    // CocoaPods downloaders and build helpers inherit the same public switches.
    for (const role of ['ruby', 'pod', 'curl', 'git', 'xcodebuild', 'neutral']) {
      const childFixture = iosProjectionFixture(); childFixture.policy.fixtureCA = f.policy.fixtureCA;
      childFixture.environment.NODE_EXTRA_CA_CERTS = f.policy.fixtureCA.path;
      const childArgs = role === 'curl' ? curlDownloaderArgs() : role === 'git' ? ['--version'] : [];
      const child = iosHostCommandProjection(childFixture.admitted, childFixture.ref, role, childArgs, inherited);
      for (const [name, value] of Object.entries(flags)) assert.equal(child.environment[name], value, role + ':' + name);
      child.input?.fill(0);
    }
    pod.input.fill(0);
  }
});
test('iOS Podfile flags reject other values names and trust overrides before child dispatch', () => {
  const valid = { EXPO_USE_PRECOMPILED_MODULES: '1', EX_DEV_CLIENT_NETWORK_INSPECTOR: 'true', RCT_USE_PREBUILT_RNCORE: '1', RCT_USE_RN_DEP: '1' };
  for (const name of Object.keys(valid)) {
    for (const value of ['', '2', '-1', 'TRUE', 'yes', '1 ', '0\n', 'SYNTHETIC_UNADMITTED']) {
      const f = iosProjectionFixture(); f.admitted.nodeBuildNames = [name];
      assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { ...valid, [name]: value }), /IOS_HOST_POD_BUILD_VALUE/);
    }
    const f = iosProjectionFixture();
    assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { ...valid, [name]: name === 'EX_DEV_CLIENT_NETWORK_INSPECTOR' ? '1' : 'true' }), /IOS_HOST_POD_BUILD_VALUE/);
    for (const value of [false, 1, null, {}, 'bad\0value']) assert.throws(() => neutralIosEnvironment({ [name]: value }), /IOS_HOST_ENVIRONMENT/);
  }
  for (const name of ['RCT_UNREVIEWED_FLAG', 'EXPO_USE_UNREVIEWED_MODULES', 'EX_DEV_CLIENT_UNREVIEWED', 'ex_dev_client_network_inspector']) {
    const f = iosProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { ...valid, [name]: '1' }), /IOS_HOST_UNREVIEWED_ENVIRONMENT/);
  }
  for (const name of ['NODE_TLS_REJECT_UNAUTHORIZED', 'NODE_EXTRA_CA_CERTS', 'SSL_CERT_FILE', 'HTTPS_PROXY', 'RUBYOPT', 'HOME']) {
    const f = iosProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { ...valid, [name]: 'SYNTHETIC_UNADMITTED' }), /IOS_HOST_CROSS_ROLE_OVERRIDE/);
  }
});
// IOS-ENV-03..06: J20/M22 source contracts, not native acceptance.
function iosRnProjectionFixture() {
  const f = iosProjectionFixture(), root = path.resolve('/SYNTHETIC/reviewed-rn-source');
  const mobile = path.join(root, 'apps/mobile'), ios = path.join(mobile, 'ios'), rn = path.join(mobile, 'node_modules/react-native');
  f.policy.helper = { path: path.join(root, 'scripts/mobile/ios-host-launch.mjs') };
  f.policy.paths.projectPods = path.join(ios, 'Pods');
  f.admitted.podBuildPaths = { sourceRoot: root, values: { APP_PATH: [ios + path.sep + '..'],
    REACT_NATIVE_PATH: [rn, f.policy.paths.projectPods + path.sep + path.relative(f.policy.paths.projectPods, rn)] } };
  return f;
}
test('IOS-ENV-03 RN source flags and paths survive Pods to every composed constructor with unchanged trust', () => {
  for (let bits = 0; bits < 64; bits++) {
    const f = iosRnProjectionFixture(), deadline = String(Date.now() + 5000);
    const flags = { RCT_SKIP_CODEGEN: String(bits & 1), RCT_REMOVE_LEGACY_ARCH: String((bits >> 1) & 1),
      RCT_REMOVE_LEGACY_MODULE_INTEROP: String((bits >> 2) & 1), RCT_REMOVE_LEGACY_COMPONENT_INTEROP: String((bits >> 3) & 1),
      RCT_HERMES_V1_ENABLED: String((bits >> 4) & 1), RCT_FABRIC_ENABLED: '1', RCT_AGGREGATE_PRIVACY_FILES: String((bits >> 5) & 1), RCT_NEW_ARCH_ENABLED: '1' };
    const paths = Object.fromEntries(Object.entries(f.admitted.podBuildPaths.values).map(([name, values]) => [name, values[0]]));
    const pod = iosHostCommandProjection(f.admitted, f.ref, 'pod', ['install'], { CASEOPS_IOS_HOST_OUTER_DEADLINE: deadline });
    const inherited = { ...pod.environment, ...flags, ...paths }, before = { ...inherited };
    for (const role of ['node', 'ruby', 'pod', 'curl', 'git', 'xcodebuild', 'neutral']) {
      const child = iosRnProjectionFixture(), args = role === 'node' ? ['./../node_modules/react-native/scripts/generate-codegen-artifacts.js', '-p', paths.APP_PATH, '-o', '/SYNTHETIC/reviewed-rn-source/apps/mobile/ios', '-t', 'ios'] : role === 'curl' ? curlDownloaderArgs() : role === 'git' ? ['--version'] : [];
      const result = iosHostCommandProjection(child.admitted, child.ref, role, args, inherited);
      for (const [name, value] of Object.entries({ ...flags, ...paths })) assert.equal(result.environment[name], value, role + ':' + name);
      assert.equal(result.environment.CASEOPS_IOS_HOST_OUTER_DEADLINE, deadline);
      if (role === 'node') { assert.deepEqual(result.args, args); assert.equal(result.environment.SSL_CERT_FILE, child.environment.SSL_CERT_FILE); assert.equal(result.environment.NODE_OPTIONS, child.environment.NODE_OPTIONS); assert.equal(result.environment.NPM_CONFIG_STRICT_SSL, 'true'); }
      else assert.equal(result.environment.NODE_OPTIONS, undefined);
      result.input?.fill(0); result.bundle?.fill(0);
    }
    assert.deepEqual(inherited, before); pod.input.fill(0);
  }
});
test('IOS-ENV-04 RN finite values and case aliases cannot bypass declared build names or trust fences', () => {
  const flags = ['RCT_SKIP_CODEGEN', 'RCT_REMOVE_LEGACY_ARCH', 'RCT_REMOVE_LEGACY_MODULE_INTEROP', 'RCT_REMOVE_LEGACY_COMPONENT_INTEROP', 'RCT_HERMES_V1_ENABLED', 'RCT_FABRIC_ENABLED', 'RCT_AGGREGATE_PRIVACY_FILES', 'RCT_NEW_ARCH_ENABLED'];
  for (const name of flags) {
    for (const value of ['', '2', '-1', 'true', 'TRUE', '1 ', '0\n', 'SYNTHETIC_UNADMITTED']) {
      const f = iosRnProjectionFixture(); f.admitted.nodeBuildNames = [name]; assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { [name]: value }), /IOS_HOST_POD_BUILD_VALUE/);
    }
    for (const value of [false, 1, null, {}, 'bad\0value']) assert.throws(() => neutralIosEnvironment({ [name]: value }), /IOS_HOST_ENVIRONMENT/);
    const f = iosRnProjectionFixture(), alias = name.toLowerCase(); f.admitted.nodeBuildNames = [alias]; assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { [alias]: '1' }), /IOS_HOST_UNREVIEWED_ENVIRONMENT/);
  }
  for (const name of ['RCT_FABRIC_ENABLED', 'RCT_NEW_ARCH_ENABLED']) { const f = iosRnProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { [name]: '0' }), /IOS_HOST_POD_BUILD_VALUE/); }
  for (const name of ['RCT_UNREVIEWED_FLAG', 'NODE_TLS_REJECT_UNAUTHORIZED', 'NODE_EXTRA_CA_CERTS', 'SSL_CERT_FILE', 'HTTPS_PROXY', 'RUBYOPT']) { const f = iosRnProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { RCT_NEW_ARCH_ENABLED: '1', [name]: 'SYNTHETIC_UNADMITTED' }), /IOS_HOST_(?:UNREVIEWED_ENVIRONMENT|CROSS_ROLE_OVERRIDE)/); }
});
test('IOS-ENV-05 SDK path values require reviewed policy root even when Xcode declares their names', () => {
  const f = iosRnProjectionFixture(), root = path.resolve('/SYNTHETIC/reviewed-rn-source');
  for (const name of ['APP_PATH', 'REACT_NATIVE_PATH']) {
    for (const value of ['/FOREIGN/source', root.toLowerCase() + '/apps/mobile', root + '/apps/mobile/ios/../../../private', '$' + '{PODS_ROOT}/../../node_modules/react-native', f.admitted.podBuildPaths.values[name][0] + '/']) {
      const c = iosRnProjectionFixture(); c.admitted.nodeBuildNames = [name]; assert.throws(() => iosHostCommandProjection(c.admitted, c.ref, 'node', [], { [name]: value }), /IOS_HOST_POD_SOURCE_PATH/);
    }
    const c = iosRnProjectionFixture(), alias = name.toLowerCase(); c.admitted.nodeBuildNames = [alias]; assert.throws(() => iosHostCommandProjection(c.admitted, c.ref, 'node', [], { [alias]: f.admitted.podBuildPaths.values[name][0] }), /IOS_HOST_UNREVIEWED_ENVIRONMENT/);
    const missing = iosProjectionFixture(); missing.admitted.nodeBuildNames = [name]; assert.throws(() => iosHostCommandProjection(missing.admitted, missing.ref, 'node', [], { [name]: f.admitted.podBuildPaths.values[name][0] }), /IOS_HOST_POD_SOURCE_PATH/);
  }
  assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { APP_PATH: root + '/apps/mobile' }), /IOS_HOST_POD_SOURCE_PATH/);
  const xcode = iosHostCommandProjection(f.admitted, f.ref, 'node', [], { REACT_NATIVE_PATH: f.admitted.podBuildPaths.values.REACT_NATIVE_PATH[1] }); assert.equal(xcode.environment.REACT_NATIVE_PATH, f.admitted.podBuildPaths.values.REACT_NATIVE_PATH[1]);
});
test('IOS-ENV-06 actual path review rejects symlinks and changed helper before composed command projection', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => reviewIosPodBuildPaths({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const root = trustRoot(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const mobile = path.join(root, 'apps/mobile'), ios = path.join(mobile, 'ios'), rn = path.join(mobile, 'node_modules/react-native'); const sourceFolder = path.join(root, 'scripts/mobile');
  for (const folder of [sourceFolder, ios, rn]) fs.mkdirSync(folder, { recursive: true, mode: 0o700 });
  const helperFile = path.join(sourceFolder, 'ios-host-launch.mjs'), source = fs.readFileSync(new URL('./ios-host-launch.mjs', import.meta.url)); fs.writeFileSync(helperFile, source, { mode: 0o600 }); const helper = referenceIosHostInput(helperFile, Date.now() + 20000, 131072);
  const f = iosProjectionFixture(); f.policy.helper = helper; f.policy.paths.projectPods = path.join(ios, 'Pods'); f.admitted.podBuildPaths = reviewIosPodBuildPaths(f.policy); assert.equal(fs.existsSync(f.policy.paths.projectPods), false);
  assert.deepEqual(f.admitted.podBuildPaths.values.APP_PATH, [ios + path.sep + '..']); assert.deepEqual(f.admitted.podBuildPaths.values.REACT_NATIVE_PATH, [rn]);
  const node = iosHostCommandProjection(f.admitted, f.ref, 'node', ['--print', '1'], { APP_PATH: ios + path.sep + '..', REACT_NATIVE_PATH: rn }); assert.equal(node.environment.REACT_NATIVE_PATH, rn); assert.equal(node.environment.SSL_CERT_FILE, f.environment.SSL_CERT_FILE);
  fs.mkdirSync(f.policy.paths.projectPods, { mode: 0o700 }); const withPods = reviewIosPodBuildPaths(f.policy); assert.equal(withPods.values.REACT_NATIVE_PATH[1], f.policy.paths.projectPods + path.sep + path.relative(f.policy.paths.projectPods, rn)); assert.equal(fs.realpathSync(withPods.values.REACT_NATIVE_PATH[1]), rn);
  for (const folder of [ios, rn]) { fs.renameSync(folder, folder + '-retained'); fs.symlinkSync(folder + '-retained', folder, 'dir'); assert.throws(() => reviewIosPodBuildPaths(f.policy), /IOS_HOST_DIRECTORY/); fs.unlinkSync(folder); fs.renameSync(folder + '-retained', folder); }
  const changed = Buffer.from(source); changed[0] ^= 1; fs.writeFileSync(helperFile, changed); assert.throws(() => reviewIosPodBuildPaths(f.policy), /IOS_HOST_HASH_CHANGED/); fs.writeFileSync(helperFile, source); assert.equal(reviewIosPodBuildPaths(f.policy).sourceRoot, root);
});

// IOS-ARGV-01..02: exact SDK code operands, not native acceptance.
test('IOS-ARGV-01 Node code operands preserve exact LF CRLF bytes and composed argv with unchanged trust', () => {
  const program = "require.resolve(\n    \"react-native\",\n    {paths: [process.argv[1]]},\n    )";
  for (const flag of ['-p', '--print', '-e', '--eval']) for (const code of [program, program.replaceAll('\n', '\r\n')]) {
    const args = [flag, code, '/SYNTHETIC/reviewed-rn-source/third-party-podspecs'], before = [...args];
    assert.equal(validateIosHostArguments('node', args), args);
    const f = iosRnProjectionFixture(), command = iosHostCommandProjection(f.admitted, f.ref, 'node', args, f.environment);
    assert.deepEqual(command.args, before); assert.deepEqual(args, before); assert.equal(command.environment.NODE_OPTIONS, f.environment.NODE_OPTIONS); assert.equal(command.environment.SSL_CERT_FILE, f.environment.SSL_CERT_FILE); assert.equal(command.environment.NPM_CONFIG_STRICT_SSL, 'true');
  }
  const literalTail = ['-p', program, '--', '--eval']; assert.equal(validateIosHostArguments('node', literalTail), literalTail);
  const byteBoundary = ['-e', ' '.repeat(8191) + '1']; assert.equal(validateIosHostArguments('node', byteBoundary), byteBoundary);
  const unicodeBoundary = ['--eval', 'é'.repeat(4096)]; assert.equal(validateIosHostArguments('node', unicodeBoundary), unicodeBoundary);
  const aggregateBoundary = Array.from({ length: 256 }, () => 'x'.repeat(8192)); assert.equal(validateIosHostArguments('node', aggregateBoundary), aggregateBoundary);
});
test('IOS-ARGV-02 CRLF paths flags env ambiguous code and original byte bounds refuse before policy reads', async t => {
  const cases = [
    ['node', ['-p']], ['node', ['-e', '']], ['node', ['-p', '--eval']], ['node', ['-p', '1', '-e', '2']], ['node', ['--eval', '1', '--print', '2']],
    ['node', ['--print\n', '1']], ['node', ['--eval\r', '1']], ['node', ['/SYNTHETIC/script\n.js']], ['node', ['-p', '1', '/SYNTHETIC/path\r\n']], ['node', ['/SYNTHETIC/codegen.js', '-p', 'source\npath']],
    ['node', ['--PRINT', '1\n']], ['node', ['-pe', '1\n']], ['node', ['-e', '1\0']], ['node', ['-e', 'x'.repeat(8193)]], ['node', ['-p', '😀'.repeat(2049)]], ['node', Array(257).fill('x')], ['node', ['-e', null]],
    ...['npm', 'ruby', 'pod', 'curl', 'git', 'xcodebuild', 'neutral'].map(role => [role, ['-e', '1\n']]),
  ];
  let reads = 0; const opened = t.mock.method(fs, 'openSync', () => { reads++; throw Error('POLICY_READ_REACHED'); });
  for (const [role, args] of cases) {
    const before = [...args]; assert.throws(() => validateIosHostArguments(role, args), /IOS_HOST_COMMAND_DOMAIN/);
    const promise = composeIosHostCommand({}, role, args); assert.ok(promise instanceof Promise); await assert.rejects(promise, /IOS_HOST_COMMAND_DOMAIN/); assert.deepEqual(args, before);
  }
  assert.equal(reads, 0); opened.mock.restore();
  for (const [name, code] of [['RCT_SKIP_CODEGEN', 'IOS_HOST_POD_BUILD_VALUE'], ['APP_PATH', 'IOS_HOST_POD_SOURCE_PATH'], ['NODE_OPTIONS', 'IOS_HOST_CROSS_ROLE_OVERRIDE']]) {
    const f = iosRnProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { ...f.environment, [name]: 'value\n' }), new RegExp(code));
  }
});

test('CocoaPods curl constructor preserves exact payload and headers while using held CA FD and required marker', () => {
  const f = iosProjectionFixture(), input = [...curlDownloaderArgs(), "-A 'CocoaPods/1.17.0 cocoapods-downloader/2.1'", '-H', 'If-None-Match: SYNTHETIC-ETAG'];
  const result = iosHostCommandProjection(f.admitted, f.ref, 'curl', input, {});
  assert.deepEqual(result.args.slice(0, 7), ['--disable', '--cacert', '/dev/fd/3', '--proto', '=https', '--proto-redir', '=https']);
  assert.deepEqual(result.args.slice(7, 7 + input.length), input);
  assert.deepEqual(result.args.slice(-2), ['-H', 'X-CaseOps-Automated-Test: no-paid-providers']);
  assert.equal(result.environment.CURL_SSL_BACKEND, 'secure-transport'); assert.equal(result.environment.SSL_CERT_FILE, undefined);
  assert.equal(result.environment.CURL_HOME, '/SYNTHETIC/owned-ios-host/home'); assert.equal(result.bundle.toString(), 'SYNTHETIC-PUBLIC-CA');
  result.bundle.fill(0);
});
test('CocoaPods curl allowlist rejects abbreviations next config proxy and later trust escapes', () => {
  for (const option of ['--next', '--config', '-K', '--cacert', '--ca-native', '--capath', '--proxy', '-k', '--insecure', '--url', '--head', '--max-time'])
    assert.throws(() => validatePodsCurlArguments([...curlDownloaderArgs(), option, 'SYNTHETIC']), /IOS_HOST_CURL_OPTION_REFUSED/);
  for (const option of ['--fail', '--location']) { const args = curlDownloaderArgs(); args[0] = option; assert.throws(() => validatePodsCurlArguments(args), /IOS_HOST_EXACT_DOWNLOADER_FORM/); }
});
test('CocoaPods curl authority rejects non HTTPS credential URLs fragments foreign output and malformed headers', () => {
  for (const url of ['http://packages.contract-fixture.org/a', 'https://user:pass@packages.contract-fixture.org/a', 'https://packages.contract-fixture.org/a#']) {
    const args = curlDownloaderArgs(); args[4] = url; assert.throws(() => validatePodsCurlArguments(args), /IOS_HOST_HTTPS_DOWNLOAD/);
  }
  for (const header of ['X-A: bad\r\nInjected: yes', 'X-CaseOps-Automated-Test: 1']) assert.throws(() => validatePodsCurlArguments([...curlDownloaderArgs(), '-H', header]), /IOS_HOST_/);
  const f = iosProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'curl', curlDownloaderArgs('/SYNTHETIC/owner/file'), {}), /IOS_HOST_CURL_OWNED_OUTPUT/);
});
test('iOS public input reader retains exact held bytes and closes its real descriptor', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readIosHostInput({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const file = path.join(base, 'input'), bytes = Buffer.from('PUBLIC SYNTHETIC INPUT'); fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 });
  const ref = { path: file, sha256: createHash('sha256').update(bytes).digest('hex'), sizeBytes: bytes.length };
  const original = fs.openSync; let fd;
  fs.openSync = (...args) => { const result = original(...args); if (args[0] === file) fd = result; return result; };
  try { const actual = readIosHostInput(ref); assert.deepEqual(actual.bytes, bytes); actual.bytes.fill(0); } finally { fs.openSync = original; }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('iOS public input reader refuses actual growth before returning and closes the held FD', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readIosHostInput({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true })); const file = path.join(base, 'input'); fs.writeFileSync(file, 'PUBLIC', { mode: 0o600 });
  const ref = { path: file, sha256: createHash('sha256').update('PUBLIC').digest('hex'), sizeBytes: 6 }, original = fs.readSync; let fd, once = false;
  fs.readSync = (value, ...args) => { fd = value; if (!once) { once = true; fs.appendFileSync(file, 'GROWTH'); } return original(value, ...args); };
  try { assert.throws(() => readIosHostInput(ref), /IOS_HOST_INPUT_CHANGED/); } finally { fs.readSync = original; }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('iOS public input catches late parent rename to same-leaf symlink and closes FD', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readIosHostInput({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true })); const dir = path.join(base, 'owned'); fs.mkdirSync(dir, { mode: 0o700 }); const file = path.join(dir, 'input'); fs.writeFileSync(file, 'PUBLIC', { mode: 0o600 });
  const ref = { path: file, sha256: createHash('sha256').update('PUBLIC').digest('hex'), sizeBytes: 6 }, original = fs.readSync; let fd, once = false;
  fs.readSync = (value, ...args) => { fd = value; const result = original(value, ...args); if (!once) { once = true; fs.renameSync(dir, dir + '-moved'); fs.symlinkSync(dir + '-moved', dir, process.platform === 'win32' ? 'junction' : 'dir'); } return result; };
  try { assert.throws(() => readIosHostInput(ref), /IOS_HOST_INPUT_CHANGED/); } finally { fs.readSync = original; }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('iOS input read failure zero size oversize hardlink and wrong hash refuse without leaked descriptors', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readIosHostInput({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true })); const file = path.join(base, 'input'); fs.writeFileSync(file, 'PUBLIC', { mode: 0o600 });
  const ref = { path: file, sha256: createHash('sha256').update('PUBLIC').digest('hex'), sizeBytes: 6 }, original = fs.readSync; let fd;
  fs.readSync = value => { fd = value; throw new Error('SYNTHETIC_IO_REFUSAL'); };
  try { assert.throws(() => readIosHostInput(ref), /SYNTHETIC_IO_REFUSAL/); } finally { fs.readSync = original; }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
  assert.throws(() => readIosHostInput({ ...ref, sizeBytes: 0 }), /IOS_HOST_REFERENCE/);
  assert.throws(() => readIosHostInput(ref, { maxBytes: 5 }), /IOS_HOST_REFERENCE/);
  assert.throws(() => readIosHostInput({ ...ref, sha256: '0'.repeat(64) }), /IOS_HOST_HASH_CHANGED/);
  fs.linkSync(file, file + '-linked'); assert.throws(() => readIosHostInput(ref), /IOS_HOST_FILE_IDENTITY/);
});
function iosReferenceFixture(t) {
  if (typeof process.getuid !== 'function') {
    assert.throws(() => referenceIosHostInput('/SYNTHETIC/input', Date.now() + 1000), /IOS_HOST_POSIX_OWNER_REQUIRED/); return null;
  }
  const root = trustRoot(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const dir = path.join(root, 'source'); fs.mkdirSync(dir, { mode: 0o700 });
  const file = path.join(dir, 'input'); fs.writeFileSync(file, 'PUBLIC', { flag: 'wx', mode: 0o600 });
  return { root, dir, file };
}
test('iOS public reference opens before pathname metadata and verifies both bounded observations', t => {
  const f = iosReferenceFixture(t); if (!f) return;
  const open = fs.openSync, lstat = fs.lstatSync, read = fs.readSync, events = [], descriptors = [], buffers = []; let consumed = 0;
  fs.openSync = (...args) => { if (args[0] === f.file) events.push('open'); const fd = open(...args); if (args[0] === f.file) descriptors.push(fd); return fd; };
  fs.lstatSync = (...args) => { if (args[0] === f.file) events.push('lstat'); return lstat(...args); };
  fs.readSync = (...args) => { buffers.push(args[1]); const n = read(...args); consumed += n; return n; };
  let ref;
  try { ref = referenceIosHostInput(f.file, Date.now() + 20000, 6); }
  finally { fs.openSync = open; fs.lstatSync = lstat; fs.readSync = read; }
  assert.equal(events[0], 'open'); assert.equal(descriptors.length, 2); assert.equal(consumed, 12);
  assert.deepEqual(ref, { path: f.file, sha256: createHash('sha256').update('PUBLIC').digest('hex'), sizeBytes: 6 });
  for (const buffer of buffers) assert.equal(buffer.every(b => b === 0), true);
  for (const fd of descriptors) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('iOS public reference refuses descriptor extent before reading and closes its FD', t => {
  const f = iosReferenceFixture(t); if (!f) return;
  const open = fs.openSync, read = fs.readSync; let descriptor, reads = 0;
  fs.openSync = (...args) => { const fd = open(...args); if (args[0] === f.file) descriptor = fd; return fd; };
  fs.readSync = (...args) => { reads++; return read(...args); };
  try { assert.throws(() => referenceIosHostInput(f.file, Date.now() + 20000, 5), /IOS_HOST_FILE_IDENTITY/); }
  finally { fs.openSync = open; fs.readSync = read; }
  assert.equal(reads, 0); assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
  for (const max of [0, NaN, 1.5, 256 * 1024 * 1024 + 1]) assert.throws(() => referenceIosHostInput(f.file, Date.now() + 20000, max), /IOS_HOST_REFERENCE/);
});
test('iOS public reference refuses an actual regular to FIFO swap without blocking or reading', t => {
  const f = iosReferenceFixture(t); if (!f) return;
  const open = fs.openSync, read = fs.readSync; let descriptor, replaced = false, reads = 0;
  fs.openSync = (...args) => {
    if (args[0] === f.file && !replaced) {
      assert.ok((args[1] & fs.constants.O_NONBLOCK) !== 0, 'REFERENCE_NONBLOCK_REQUIRED');
      fs.renameSync(f.file, f.file + '.retained');
      execFileSync('/usr/bin/mkfifo', [f.file], { env: { PATH: '/usr/bin:/bin' }, timeout: 1000, maxBuffer: 1024 }); replaced = true;
    }
    const fd = open(...args); if (args[0] === f.file) descriptor = fd; return fd;
  };
  fs.readSync = (...args) => { reads++; return read(...args); };
  try { assert.throws(() => referenceIosHostInput(f.file, Date.now() + 20000), /IOS_HOST_FILE_IDENTITY/); }
  finally { fs.openSync = open; fs.readSync = read; }
  assert.equal(replaced, true); assert.equal(fs.lstatSync(f.file).isFIFO(), true); assert.equal(fs.existsSync(f.file + '.retained'), true);
  assert.equal(reads, 0); assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
});
test('iOS public reference refuses growth within its fixed read extent and wipes its buffer', t => {
  const f = iosReferenceFixture(t); if (!f) return;
  const read = fs.readSync; let descriptor, buffer, consumed = 0, grew = false;
  fs.readSync = (...args) => { descriptor = args[0]; buffer = args[1]; if (!grew) { grew = true; fs.appendFileSync(f.file, 'GROWTH'); } const n = read(...args); consumed += n; return n; };
  try { assert.throws(() => referenceIosHostInput(f.file, Date.now() + 20000), /IOS_HOST_INPUT_CHANGED/); }
  finally { fs.readSync = read; }
  assert.equal(consumed, 7); assert.equal(buffer.length, 7); assert.equal(buffer.every(b => b === 0), true);
  assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
});
test('iOS public reference retains the read error identity and closes and wipes on refusal', t => {
  const f = iosReferenceFixture(t); if (!f) return;
  const read = fs.readSync, expected = new Error('SYNTHETIC_REFERENCE_READ_REFUSAL'); let descriptor, buffer;
  fs.readSync = (...args) => { descriptor = args[0]; buffer = args[1]; throw expected; };
  try { assert.throws(() => referenceIosHostInput(f.file, Date.now() + 20000), error => error === expected); }
  finally { fs.readSync = read; }
  assert.equal(buffer.every(b => b === 0), true); assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
});
test('iOS public reference rejects a replaced parent namespace after its descriptor read', t => {
  const f = iosReferenceFixture(t); if (!f) return;
  const read = fs.readSync; let descriptor, replaced = false;
  fs.readSync = (...args) => { descriptor = args[0]; const n = read(...args); if (!replaced) { replaced = true; fs.renameSync(f.dir, f.dir + '.retained'); fs.symlinkSync(f.dir + '.retained', f.dir); } return n; };
  try { assert.throws(() => referenceIosHostInput(f.file, Date.now() + 20000), /IOS_HOST_INPUT_CHANGED|IOS_HOST_NAMESPACE/); }
  finally { fs.readSync = read; }
  assert.equal(replaced, true); assert.equal(fs.lstatSync(f.dir).isSymbolicLink(), true);
  assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
});
test('iOS selected Pods preload and build body retain exact approved bytes and independent guard contracts', () => {
  const bytes = fs.readFileSync(new URL('./ios-host-pods.rb', import.meta.url)); assert.equal(createHash('sha256').update(bytes).digest('hex'), IOS_PODS_SOURCE_SHA256);
  const source = bytes.toString(); assert.match(source, /ssl_verifypeer => true/); assert.match(source, /ssl_verifyhost => 2/); assert.match(source, /'X-CaseOps-Automated-Test' => MARKER/);
  assert.match(source, /:cainfo => @policy.fetch\('bundle'\)/); assert.match(source, /options.merge\(expected\)/); assert.match(source, /:netrc\] == :optional/);
  const shell = fs.readFileSync(new URL('./build-ios-simulator-acceptance.sh', import.meta.url), 'utf8'); assert.match(shell, /IOS_HOST_REVIEWED_ENTRY/); assert.doesNotMatch(shell, /pod install|prebuild|xcodebuild/);
});
test('iOS simulator launch is unarmed before any policy read or synthetic transport entry', async () => {
  let calls = 0;
  await assert.rejects(runIosSimulatorBuild({ path: '/NEVER_READ', sha256: '0'.repeat(64), sizeBytes: 1 }, {}, { transport: () => { calls++; } }), /IOS_HOST_SIMULATOR_NOT_ARMED/);
  assert.equal(calls, 0);
});
function iosDescriptorFixture(t) {
  if (typeof process.getuid !== 'function') return { role: 'curl', bundle: Buffer.from('SYNTHETIC'), policy: { paths: {} } };
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  for (const p of ['home', 'temporary']) fs.mkdirSync(path.join(base, p), { mode: 0o700 });
  return { role: 'curl', bundle: Buffer.from('PUBLIC SYNTHETIC CA BYTES'), policy: { paths: { home: path.join(base, 'home'), temporary: path.join(base, 'temporary') } }, homeObservation: reviewIosHostHome(path.join(base, 'home')) };
}
test('iOS CA transport passes a real same regular FD with exact retained bytes and closes its owned copy', t => {
  const command = iosDescriptorFixture(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => openIosCurlTransport(command), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const transport = openIosCurlTransport(command), actual = Buffer.alloc(command.bundle.length + 1);
  const n = fs.readSync(transport.fd, actual, 0, actual.length, 0); assert.equal(n, command.bundle.length); assert.deepEqual(actual.subarray(0, n), command.bundle);
  assert.equal(fs.fstatSync(transport.fd).isFile(), true); transport.finish(); assert.equal(fs.existsSync(transport.file), false);
  assert.throws(() => fs.fstatSync(transport.fd), { code: 'EBADF' }); command.bundle.fill(0);
});
test('iOS CA transport refuses zero progress with FD closure and no false completed descriptor', t => {
  const command = iosDescriptorFixture(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => openIosCurlTransport(command), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const original = fs.writeSync; let fd;
  fs.writeSync = value => { fd = value; return 0; };
  try { assert.throws(() => openIosCurlTransport(command), /IOS_HOST_WRITE_PROGRESS/); } finally { fs.writeSync = original; }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' }); command.bundle.fill(0);
});
test('iOS CA transport detects actual parent rename to same-inode alias and preserves foreign namespace', t => {
  const command = iosDescriptorFixture(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => openIosCurlTransport(command), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const transport = openIosCurlTransport(command), dir = command.policy.paths.temporary;
  fs.renameSync(dir, dir + '-moved'); fs.symlinkSync(dir + '-moved', dir, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => transport.finish(), /IOS_HOST_TRANSPORT_CHANGED|IOS_HOST_TRANSPORT_NAMESPACE_CHANGED|IOS_HOST_NAMESPACE/);
  assert.throws(() => fs.fstatSync(transport.fd), { code: 'EBADF' }); assert.equal(fs.existsSync(path.join(dir + '-moved', path.basename(transport.file))), true); command.bundle.fill(0);
});
test('iOS CA transport refuses a netrc insertion or removed-late insertion using the owned HOME frame', t => {
  const command = iosDescriptorFixture(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => openIosCurlTransport(command), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const transport = openIosCurlTransport(command), file = path.join(command.policy.paths.home, '.netrc'); fs.writeFileSync(file, 'SYNTHETIC ONLY', { mode: 0o600 });
  assert.throws(() => reviewIosHostHome(command.policy.paths.home), /IOS_HOST_OWNER_CONFIG_REFUSED/); fs.unlinkSync(file);
  assert.throws(() => transport.finish(), /IOS_HOST_HOME_CHANGED/); assert.throws(() => fs.fstatSync(transport.fd), { code: 'EBADF' }); command.bundle.fill(0);
});
test('iOS public input refuses a controlled foreign-owner metadata frame before any body read', t => {
  if (typeof process.getuid !== 'function') { assert.equal(process.platform, 'win32'); return; }
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true })); const file = path.join(base, 'input'); fs.writeFileSync(file, 'PUBLIC', { mode: 0o600 });
  const ref = { path: file, sha256: createHash('sha256').update('PUBLIC').digest('hex'), sizeBytes: 6 }, actualStat = fs.fstatSync, actualRead = fs.readSync; let reads = 0, fd;
  fs.fstatSync = (value, options) => { fd = value; const real = actualStat(value, options); return new Proxy(real, { get(target, key) { return key === 'uid' ? target.uid + 1n : typeof target[key] === 'function' ? target[key].bind(target) : target[key]; } }); };
  fs.readSync = (...args) => { reads++; return actualRead(...args); };
  try { assert.throws(() => readIosHostInput(ref), /IOS_HOST_FILE_IDENTITY/); } finally { fs.fstatSync = actualStat; fs.readSync = actualRead; }
  assert.equal(reads, 0); assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('iOS Git shim permits exact local source inventory reads and refuses all transport or option escapes', () => {
  for (const args of [['--version'], ['check-ignore', '-z', '--stdin'], ['rev-parse', 'HEAD'], ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'apps/mobile', 'scripts/mobile/ios-host-pods.rb'], ['status', '--porcelain', '--untracked-files=all', '--', 'apps/mobile']])
    assert.deepEqual(validateIosReadonlyGitArguments(args), ['-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', ...args]);
  for (const args of [['clone', 'https://public.contract-fixture.org/repo'], ['fetch'], ['-c', 'http.sslVerify=false', 'status'], ['status', '--porcelain', '--untracked-files=all', '--', '../outside'], ['rev-parse', 'HEAD', '--show-toplevel']])
    assert.throws(() => validateIosReadonlyGitArguments(args), /IOS_HOST_GIT_TLS_UNPROVEN/);
});
test('real source inventory pathspecs retain the256 bound separately from the16-argument Git mutation bound', () => {
  const f = iosProjectionFixture(), paths = Array.from({ length: 32 }, (_, i) => 'scripts/mobile/source-' + i + '.mjs');
  for (const prefix of [['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--'], ['status', '--porcelain', '--untracked-files=all', '--']]) {
    const args = [...prefix, ...paths], row = projectIosGitArguments(args, f.policy.paths);
    assert.equal(row.family, 'local-source-inventory'); assert.deepEqual(row.args.slice(-args.length), args);
  }
  assert.throws(() => projectIosGitArguments(['clone', ...Array(16).fill('public')], f.policy.paths), /IOS_HOST_GIT_MUTATION_ARGUMENT_BOUND/);
  assert.throws(() => projectIosGitArguments(Array(257).fill('public'), f.policy.paths), /IOS_HOST_GIT_ARGUMENTS/);
  assert.throws(() => validateIosReadonlyGitArguments(['check-ignore', '-z', '--stdin', '--no-index']), /IOS_HOST_GIT_TLS_UNPROVEN/);
});
test('iOS build entry pins the complete actual helper bytes and executes only its retained buffer', () => {
  const file = fileURLToPath(new URL('./ios-host-launch.mjs', import.meta.url)), bytes = fs.readFileSync(file), ref = { path: file, sha256: createHash('sha256').update(bytes).digest('hex'), sizeBytes: bytes.length };
  const expected = renderIosHostBuildEntry(ref), actual = fs.readFileSync(new URL('./build-ios-simulator-acceptance.sh', import.meta.url), 'utf8');
  assert.equal(actual, expected); assert.match(actual, /fs\.openSync\(file/); assert.match(actual, /O_NONBLOCK/); assert.match(actual, /sha256/); assert.match(actual, /await import/); assert.match(actual, /data:text\/javascript;base64,/);
  assert.doesNotMatch(actual, /exec "\$CASEOPS_IOS_HOST_NODE" "\$repo\/scripts/);
});
test('iOS retained entry refuses a same-sized replaced helper before any sentinel execution', t => {
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const helper = fs.readFileSync(new URL('./ios-host-launch.mjs', import.meta.url)), root = path.join(base, 'source'), folder = path.join(root, 'scripts/mobile'); fs.mkdirSync(folder, { recursive: true, mode: 0o700 });
  const sentinel = path.join(base, 'UNADMITTED_HELPER'), file = path.join(folder, 'ios-host-launch.mjs'), entry = path.join(folder, 'build-ios-simulator-acceptance.sh');
  let fake = `import fs from 'node:fs';fs.writeFileSync(${JSON.stringify(sentinel)},'SYNTHETIC');export async function iosHostCli(){return 0};`;
  fake = fake.padEnd(helper.length, ' '); assert.equal(Buffer.byteLength(fake), helper.length); fs.writeFileSync(file, fake, { mode: 0o600 });
  fs.writeFileSync(entry, renderIosHostBuildEntry({ path: file, sha256: createHash('sha256').update(helper).digest('hex'), sizeBytes: helper.length }), { mode: 0o700 });
  if (process.platform === 'win32') { assert.equal(fs.existsSync(sentinel), false); return; }
  const child = spawnSyncForIosEntry(entry, { PATH: '/usr/bin:/bin', CASEOPS_IOS_HOST_NODE: process.execPath, CASEOPS_IOS_HOST_POLICY_FILE: '/NEVER_READ', CASEOPS_IOS_HOST_POLICY_SHA256: '0'.repeat(64), CASEOPS_IOS_HOST_POLICY_SIZE: '1', CASEOPS_IOS_SIMULATOR_BUILD_GO: 'EXPLICIT_REVIEWED_LOCAL_SIMULATOR_BUILD' });
  assert.equal(child.status, 1); assert.equal(fs.existsSync(sentinel), false);
  if (process.platform === 'darwin') assert.match(child.stderr, /IOS_HOST_SHIM_SOURCE_REFUSED/); else assert.match(child.stderr, /actual Mac/);
});
function spawnSyncForIosEntry(file, env) {
  try { const stdout = execFileSync('/bin/bash', [file], { env, timeout: 5000, maxBuffer: 8192, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }); return { status: 0, stdout, stderr: '' }; }
  catch (error) { return { status: error.status, stdout: String(error.stdout || ''), stderr: String(error.stderr || '') }; }
}
test('iOS Node build names are pinned to actual retained phase evidence without owner or TLS override fields', () => {
  const raw = fs.readFileSync(new URL('./ios-node-build-env.json', import.meta.url)), spec = JSON.parse(raw);
  assert.equal(createHash('sha256').update(raw).digest('hex'), '050bd27cab9480e208d17141e5df2d5f98d8f7cdbadc73c31b085ff3be5f0ba6');
  assert.equal(spec.provenance.namesEvidenceSha256, '6670f54a23ed98e6c33ec02e43339bb56e5fa4abebc3a7dc7850fea51319f257');
  assert.equal(spec.provenance.sdkVersion, '27.1'); assert.equal(spec.provenance.simulatorRuntime, '27.0'); assert.equal(spec.names.length, 586); assert.equal(new Set(spec.names).size, 586);
  assert.equal(spec.names.includes('LD_RUNPATH_SEARCH_PATHS'), true); assert.equal(spec.names.includes('BUILT_PRODUCTS_DIR'), true);
  for (const key of ['HOME', 'USER', 'UID', 'PATH', 'NODE_OPTIONS', 'LD_PRELOAD', 'DYLD_INSERT_LIBRARIES', 'HTTPS_PROXY']) assert.equal(spec.names.includes(key), false, key);
});
test('iOS Node accepts only source-admitted typed derived build names while rebinding trust and preserving the parent', () => {
  const f = iosProjectionFixture(); f.admitted.nodeBuildNames = ['BUILT_PRODUCTS_DIR', 'CONFIGURATION', 'LD_RUNPATH_SEARCH_PATHS'];
  const supplied = { BUILT_PRODUCTS_DIR: '/SYNTHETIC/Release-iphonesimulator', CONFIGURATION: 'Release', LD_RUNPATH_SEARCH_PATHS: '@executable_path/Frameworks' }, before = { ...supplied };
  const row = iosHostCommandProjection(f.admitted, f.ref, 'node', ['--print', '1'], supplied);
  assert.equal(row.environment.BUILT_PRODUCTS_DIR, supplied.BUILT_PRODUCTS_DIR); assert.equal(row.environment.CONFIGURATION, 'Release');
  assert.equal(row.environment.SSL_CERT_FILE, f.environment.SSL_CERT_FILE); assert.deepEqual(supplied, before);
  for (const key of ['DYLD_INSERT_LIBRARIES', 'LD_PRELOAD', 'HTTPS_PROXY']) assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { [key]: 'SYNTHETIC' }), /IOS_HOST_CROSS_ROLE_OVERRIDE/);
  assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', [], { UNOBSERVED_OWNER_TOKEN: 'SYNTHETIC' }), /IOS_HOST_UNREVIEWED_ENVIRONMENT/);
});
test('iOS derived build values reject nonstrings NUL field extent and aggregate overflow before dispatch', () => {
  for (const value of [false, 1, {}, 'bad\0value', 'x'.repeat(32769)]) assert.throws(() => neutralIosEnvironment({ CONFIGURATION: value }, { buildNames: ['CONFIGURATION'] }), /IOS_HOST_ENVIRONMENT/);
  const names = Array.from({ length: 9 }, (_, i) => 'SOURCE_FIELD_' + i), values = Object.fromEntries(names.map(n => [n, 'x'.repeat(32768)]));
  assert.throws(() => neutralIosEnvironment(values, { buildNames: names }), /IOS_HOST_ENVIRONMENT_BOUND/);
});
test('iOS generated CoreFoundation encoding metadata is typed current-user metadata and never forwarded', () => {
  for (const value of ['foreign:0:0', '0xFFFFFFFF:0:0', '0:0', '0:../../owner:0']) assert.throws(() => neutralIosEnvironment({ __CF_USER_TEXT_ENCODING: value }), /IOS_HOST_MACOS_TEXT_ENCODING/);
  if (typeof process.getuid === 'function') assert.deepEqual(neutralIosEnvironment({ __CF_USER_TEXT_ENCODING: '0x' + process.getuid().toString(16) + ':0x0:0x0' }), {});
});
test('iOS public preparation CLI rejects unknown fields before policy or tool admission', async t => {
  const { iosHostCli } = await import('./ios-host-launch.mjs'), root = trustRoot(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const bytes = Buffer.from(JSON.stringify({ directory: path.join(root, 'NEVER_CREATED'), nodePolicy: null, rubyBundle: null, tools: null, unknownField: 'PUBLIC SYNTHETIC FIELD' })), file = path.join(root, 'input.json'); fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 });
  if (typeof process.getuid !== 'function') { await assert.rejects(iosHostCli(['prepare', file, createHash('sha256').update(bytes).digest('hex'), String(bytes.length)]), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  await assert.rejects(iosHostCli(['prepare', file, createHash('sha256').update(bytes).digest('hex'), String(bytes.length)]), /IOS_HOST_PREPARE_KEYS/);
  assert.equal(fs.existsSync(path.join(root, 'NEVER_CREATED')), false);
});
test('actual RN archive redirect HEAD and SHA1 curl forms preserve arguments with exact marker and selected descriptor', () => {
  const f = iosProjectionFixture(), url = 'https://packages.contract-fixture.org/rn.tgz', target = f.policy.paths.pods + '/ReactNativeCore-artifacts/reactnative-core.download';
  const forms = [
    ['-A', 'react-native-0.88.0', url, '-Lo', target],
    ['-Ls', '-o', '/dev/null', '-w', '%{url_effective}', url],
    ['-o', '/dev/null', '--silent', '-Iw', '%{http_code}', '-L', url],
    ['-sL', url + '.sha1'],
  ];
  for (const args of forms) {
    const row = iosHostCommandProjection(f.admitted, f.ref, 'curl', args, {});
    assert.deepEqual(row.args.slice(7, -2), args); assert.deepEqual(row.args.slice(-2), ['-H', 'X-CaseOps-Automated-Test: no-paid-providers']);
    assert.equal(row.args[2], '/dev/fd/3');
    // Every projection owns its retained copy; restore the synthetic admitted buffer.
    f.admitted.bundle = { bytes: Buffer.from('SYNTHETIC-PUBLIC-CA') }; row.bundle.fill(0);
  }
});
test('RN curl variants reject arbitrary options URL authority and unrelated sidecars', () => {
  const url = 'https://packages.contract-fixture.org/rn.tgz';
  for (const args of [
    ['-A', 'arbitrary-user-agent', url, '-Lo', '/owned/file'],
    ['-A', 'react-native-0.88.0', url, '-Lo', '/owned/file', '--insecure'],
    ['-Ls', '-o', '/dev/null', '-w', '%{url_effective}', url, '--next'],
    ['-o', '/dev/null', '--silent', '-Iw', '%{http_code}', '-L', 'http://untrusted.invalid'],
    ['-sL', url], ['-sL', 'https://user:pass@packages.contract-fixture.org/a.sha1'],
  ]) assert.throws(() => validateIosCurlArguments(args), /IOS_HOST_/);
});
test('Git typed public downloader forms retain operands and bind every transport to selected CA and marker', () => {
  const f = iosProjectionFixture(), repo = f.policy.paths.temporary + '/clone', url = 'https://packages.contract-fixture.org/repo.git';
  for (const args of [['ls-remote', '--', url, 'main'], ['ls-remote', url, 'main'], ['clone', url, repo, '--template=', '--single-branch', '--depth', '1', '--branch', 'main'],
    ['-C', repo, 'fetch', 'origin', '--progress'], ['-C', repo, 'pull', '--ff-only'], ['-C', repo, 'submodule', 'update', '--init', '--recursive']]) {
    const row = projectIosGitArguments(args, f.policy.paths);
    assert.equal(row.network, true); assert.deepEqual(row.args.slice(-args.length), args);
    for (const setting of ['http.sslVerify=true', 'http.sslCAInfo=/dev/fd/3', 'http.sslCAPath=' + f.policy.paths.empty, 'http.extraHeader=X-CaseOps-Automated-Test: no-paid-providers', 'credential.helper=', 'protocol.allow=never', 'protocol.https.allow=always']) assert.ok(row.args.includes(setting), setting);
  }
  const git = iosHostCommandProjection(f.admitted, f.ref, 'git', ['ls-remote', '--', url], {});
  assert.equal(git.executable, '/SYNTHETIC/git'); assert.equal(git.environment.NODE_OPTIONS, undefined); assert.ok(Buffer.isBuffer(git.bundle));
  assert.equal(git.cwd, f.policy.paths.empty); assert.equal(git.environment.GIT_CEILING_DIRECTORIES, f.policy.paths.empty); git.bundle.fill(0);
});
test('Git constructor refuses credentials protocols arbitrary flags foreign targets and unreviewed revisions', () => {
  const f = iosProjectionFixture(), repo = f.policy.paths.repos + '/public', url = 'https://packages.contract-fixture.org/repo.git';
  for (const args of [['ls-remote', '--', 'ssh://packages.contract-fixture.org/repo'], ['ls-remote', '--', 'https://user:pass@packages.contract-fixture.org/repo'],
    ['clone', url, '/SYNTHETIC/source-worktree', '--template='], ['clone', url, repo, '--template=/operator/template'], ['clone', url, repo, '--template=', '-c', 'http.sslVerify=false'],
    ['-C', repo, 'config', 'credential.helper', 'UNADMITTED'], ['-C', repo, 'checkout', '--', '../outside'], ['-C', repo, 'reset', '--hard', '../main'],
    ['-C', repo, 'fetch', 'file:///operator/source'], ['-c', 'http.sslVerify=false', 'ls-remote', url]]) assert.throws(() => projectIosGitArguments(args, f.policy.paths), /IOS_HOST_/);
});
function iosGitFilesystemFixture(t) {
  const base = trustRoot(); t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const paths = Object.fromEntries(['home', 'cache', 'temporary', 'pods', 'repos'].map(k => [k, path.join(base, k)]));
  for (const p of Object.values(paths)) fs.mkdirSync(p, { mode: 0o700 });
  const repository = path.join(paths.repos, 'public'); fs.mkdirSync(repository, { mode: 0o700 }); fs.mkdirSync(path.join(repository, '.git'), { mode: 0o700 });
  const config = path.join(repository, '.git/config');
  fs.writeFileSync(config, '[core]\n\trepositoryformatversion = 0\n\tbare = false\n[remote "origin"]\n\turl = https://packages.contract-fixture.org/public.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n', { mode: 0o600 });
  return { paths, repository, config, command: { policy: { paths }, git: { repository, clone: false, family: 'fetch' } } };
}
test('Git real owned repository admission accepts canonical public config and refuses later symlink replacement', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => admitIosGitRepository({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const f = iosGitFilesystemFixture(t), before = admitIosGitRepository(f.command);
  assert.equal(before.repositoryIdentity.length, 5); assert.equal(before.root, f.paths.repos);
  fs.renameSync(f.repository, f.repository + '-moved'); fs.symlinkSync(f.repository + '-moved', f.repository, 'dir');
  assert.throws(() => admitIosGitRepository(f.command), /IOS_HOST_MUTATION_NAMESPACE/);
});
test('Git real config includes helper URL rewrites bypass flags and external object aliases refuse before a child', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => admitIosGitRepository({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const f = iosGitFilesystemFixture(t), original = fs.readFileSync(f.config);
  for (const row of ['[include]\n path = /operator/config', '[credential]\n helper = shell', '[http]\n sslVerify = false', '[url "https://unadmitted.invalid/"]\n insteadOf = https://packages.contract-fixture.org/']) {
    fs.writeFileSync(f.config, Buffer.concat([original, Buffer.from(row + '\n')]));
    assert.throws(() => admitIosGitRepository(f.command), /IOS_HOST_GIT_CONFIG/);
  }
  fs.writeFileSync(f.config, original); fs.writeFileSync(path.join(f.repository, '.git/commondir'), '/operator/repo');
  assert.throws(() => admitIosGitRepository(f.command), /IOS_HOST_GIT_EXTERNAL_OBJECTS/);
});
test('Git new clone target must be empty owned and canonical without following an existing symlink', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => admitIosGitRepository({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const f = iosGitFilesystemFixture(t), target = path.join(f.paths.temporary, 'new-clone'), command = { policy: { paths: f.paths }, git: { repository: target, clone: true, family: 'clone' } };
  assert.equal(admitIosGitRepository(command).repositoryIdentity, null); fs.mkdirSync(target, { mode: 0o700 });
  assert.equal(admitIosGitRepository(command).repositoryIdentity.length, 5); fs.writeFileSync(path.join(target, 'retained'), 'PUBLIC');
  assert.throws(() => admitIosGitRepository(command), /IOS_HOST_GIT_NEW_TARGET/);
});
test('Git selected-file copy retains a real descriptor and refuses permission drift without removing changed evidence', t => {
  const command = iosDescriptorFixture(t); command.role = 'git';
  if (typeof process.getuid !== 'function') { assert.throws(() => openIosCurlTransport(command), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const transport = openIosCurlTransport(command);
  assert.equal(fs.fstatSync(transport.fd).mode & 0o777, 0o400);
  fs.fchmodSync(transport.fd, 0o600);
  assert.throws(() => transport.finish(), /IOS_HOST_TRANSPORT_CHANGED/);
  assert.throws(() => fs.fstatSync(transport.fd), { code: 'EBADF' }); assert.equal(fs.existsSync(transport.file), true); command.bundle.fill(0);
});
test('Git selected-file final check refuses a same-leaf symlink substitution and closes the original held descriptor', t => {
  const command = iosDescriptorFixture(t); command.role = 'git';
  if (typeof process.getuid !== 'function') { assert.throws(() => openIosCurlTransport(command), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const transport = openIosCurlTransport(command), retained = transport.file + '-retained'; fs.renameSync(transport.file, retained); fs.symlinkSync(retained, transport.file);
  assert.throws(() => transport.finish(), /IOS_HOST_TRANSPORT_CHANGED/);
  assert.throws(() => fs.fstatSync(transport.fd), { code: 'EBADF' }); assert.equal(fs.lstatSync(transport.file).isSymbolicLink(), true); command.bundle.fill(0);
});
test('public local QA entry rejects store signing and nonmetadata Pod modes before any policy or transport read', async () => {
  const ref = { path: '/NEVER_READ', sha256: '0'.repeat(64), sizeBytes: 1 }; let calls = 0;
  for (const role of ['store', 'signing', 'xcodebuild']) await assert.rejects(runIosLocalQaCommand(ref, role, [], { transport: () => { calls++; } }), /IOS_HOST_LOCAL_QA_COMMAND/);
  await assert.rejects(runIosLocalQaCommand(ref, 'pod', ['install'], { transport: () => { calls++; } }), /IOS_HOST_LOCAL_QA_METADATA_ONLY/);
  assert.equal(calls, 0);
});
test('actual generated project Pods root is separately bound from CP_HOME with owned0755 parents and no broad checkout mutation', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => admitIosGitRepository({}), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  const f = iosGitFilesystemFixture(t), source = path.join(f.paths.home, 'source'), projectPods = path.join(source, 'apps/mobile/ios/Pods');
  fs.mkdirSync(projectPods, { recursive: true, mode: 0o755 });
  const paths = { ...f.paths, projectPods }, command = { policy: { paths }, git: { repository: path.join(projectPods, 'PublicPod'), clone: true, family: 'clone' } };
  const row = admitIosGitRepository(command); assert.equal(row.root, projectPods);
  const parent = path.dirname(projectPods); fs.chmodSync(parent, 0o777);
  assert.throws(() => admitIosGitRepository(command), /IOS_HOST_PROJECT_PODS_NAMESPACE/); fs.chmodSync(parent, 0o755);
  const foreign = { ...command, git: { ...command.git, repository: path.join(source, 'unrelated') } };
  assert.throws(() => admitIosGitRepository(foreign), /IOS_HOST_OWNED_MUTATION_PATH/);
});
test('iOS Node and npm metadata use the exact anonymous4 layer without leaking it to Ruby curl or Xcode', () => {
  const f = iosProjectionFixture(), original = {};
  const node = iosHostCommandProjection(f.admitted, f.ref, 'node', ['-v'], original);
  assert.deepEqual(Object.fromEntries(Object.entries(node.environment).filter(([k]) => k.startsWith('NPM_CONFIG_'))), {
    NPM_CONFIG_USERCONFIG: f.policy.nodeNpm.user.path, NPM_CONFIG_GLOBALCONFIG: f.policy.nodeNpm.global.path,
    NPM_CONFIG_STRICT_SSL: 'true', NPM_CONFIG_REGISTRY: 'https://registry.npmjs.org/' });
  const npm = iosHostCommandProjection(f.admitted, f.ref, 'npm', ['--version'], {});
  assert.equal(npm.executable, f.policy.tools.node.path); assert.equal(npm.args[0], '--input-type=module');
  assert.deepEqual(npm.args.slice(-2), ['--', '--version']);
  assert.match(npm.args[2], /createRequire\(entry\)\('\.\.\/lib\/cli\.js'\)\(process\)/);
  assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'npm', ['publish'], {}), /IOS_HOST_NPM_METADATA_ONLY/);
  for (const role of ['ruby', 'xcodebuild']) assert.equal(iosHostCommandProjection(f.admitted, f.ref, role, [], {}).environment.NPM_CONFIG_USERCONFIG, undefined);
  assert.deepEqual(original, {});
});
test('iOS npm recipes reject lowercase conflicting registry CA proxy and credential overrides before payload', () => {
  for (const environment of [{ npm_config_userconfig: '/operator/npmrc' }, { NPM_CONFIG_USERCONFIG: '/operator/npmrc' },
    { NPM_CONFIG_GLOBALCONFIG: '/operator/npmrc' }, { NPM_CONFIG_REGISTRY: 'https://unadmitted.invalid/' }, { NPM_CONFIG_STRICT_SSL: 'false' },
    { NPM_CONFIG_CAFILE: '/operator/extra.pem' }, { NPM_CONFIG_PROXY: 'http://127.0.0.1:1' }, { NPM_CONFIG__AUTH: 'SYNTHETIC_UNADMITTED' }]) {
    const f = iosProjectionFixture(); assert.throws(() => iosHostCommandProjection(f.admitted, f.ref, 'node', ['-v'], environment), /IOS_HOST_CROSS_ROLE_OVERRIDE/);
  }
});
test('iOS project npmrc absence fence catches late file or symlink creation without reading either payload', t => {
  const root = trustRoot(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'apps/mobile'), { recursive: true, mode: 0o700 }); fs.mkdirSync(path.join(root, 'scripts/mobile'), { recursive: true, mode: 0o700 });
  const p = { helper: { path: path.join(root, 'scripts/mobile/ios-host-launch.mjs') } };
  assert.equal(reviewProjectNpm(p).length, 2);
  const npmrc = path.join(root, 'apps/mobile/.npmrc'), target = path.join(root, 'UNREAD_CONFIG'); fs.writeFileSync(target, 'SYNTHETIC_UNREAD_PRIVATE_CONFIG');
  const actual = fs.readSync; let reads = 0; fs.readSync = (...args) => { reads++; return actual(...args); };
  try { fs.writeFileSync(npmrc, 'SYNTHETIC_UNREAD_PRIVATE_CONFIG'); assert.throws(() => reviewProjectNpm(p), /IOS_HOST_PROJECT_NPMRC_REFUSED/); fs.unlinkSync(npmrc);
    fs.symlinkSync(target, npmrc); assert.throws(() => reviewProjectNpm(p), /IOS_HOST_PROJECT_NPMRC_REFUSED/); }
  finally { fs.readSync = actual; }
  assert.equal(reads, 0);
});
test('iOS public preparation CLI refuses malformed UTF8 without normalizing hashed input bytes', async t => {
  const { iosHostCli } = await import('./ios-host-launch.mjs'), root = trustRoot(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, 'input.json'), bytes = Buffer.from([0x7b, 0x22, 0x78, 0x22, 0x3a, 0x22, 0xff, 0x22, 0x7d]); fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 });
  if (typeof process.getuid !== 'function') { await assert.rejects(iosHostCli(['prepare', file, createHash('sha256').update(bytes).digest('hex'), String(bytes.length)]), /IOS_HOST_POSIX_OWNER_REQUIRED/); return; }
  await assert.rejects(iosHostCli(['prepare', file, createHash('sha256').update(bytes).digest('hex'), String(bytes.length)]), { code: 'ERR_ENCODING_INVALID_ENCODED_DATA' });
  assert.deepEqual(fs.readFileSync(file), bytes);
});
test('iOS retained Pods source uses existing bounded stdin instead of exceeding the unchanged argv contract', () => {
  const f = iosProjectionFixture(); f.admitted.podsSource = fs.readFileSync(new URL('./ios-host-pods.rb', import.meta.url));
  const row = iosHostCommandProjection(f.admitted, f.ref, 'pod', ['install', '--deployment', '--no-repo-update'], {});
  assert.ok(f.admitted.podsSource.length > 8192); assert.ok(row.args.every(value => value.length <= 8192));
  assert.ok(row.input.length <= 1048576); assert.deepEqual(row.input, Buffer.concat([f.admitted.podsSource, Buffer.from('\nCaseopsIosPods.run\n')])); row.input.fill(0);
});
test('iOS role projection drops only the typed pinned-worker status descriptor marker', () => {
  assert.deepEqual(neutralIosEnvironment({ CASEOPS_STORE_CHILD_STATUS_FD: '6' }), {});
  for (const value of ['-1', '0', '2', '3.0', 'true', '2147483648', 'SYNTHETIC']) assert.throws(() => neutralIosEnvironment({ CASEOPS_STORE_CHILD_STATUS_FD: value }), /IOS_HOST_INTERNAL_STATUS_FD/);
  const source = fs.readFileSync(new URL('./ios-host-pods.rb', import.meta.url), 'utf8'); assert.doesNotMatch(source, /\$PROGRAM_NAME\s*=/);
});

test('offline iOS Git inventory bootstrap and source closure are pinned without importing Node trust', () => {
  const root = new URL('./', import.meta.url), helper = fs.readFileSync(new URL('ios-host-launch.mjs', root), 'utf8');
  assert.ok(helper.includes("const NODE_HELPER = '4dcca216db4071bee09d939142c5ea92bfb120b0bffa152ebefcf0b9acab1a18'"));
  assert.ok(helper.includes("const NODE_BOOTSTRAP = '2fb386b772aecfcc5c18aacf5d6c77aa934fa90d895adf2adf8baf42a9b6d6a5'"));
  const input = fs.readFileSync(new URL('ios-git-readonly.py', root));
  const pin = createHash('sha256').update(input).digest('hex');
  assert.ok(helper.includes("'ios-git-readonly.py': '" + pin + "'"));
  const fast = helper.slice(helper.indexOf('const GIT_READONLY_BOOTSTRAP ='), helper.indexOf('export function renderIosHostBuildEntry'));
  assert.match(fast, /exec\(compile\(bytes\(b\),ref\['path'\],'exec'\),scope\)/);
  assert.match(fast, /case "\$\{1-\}" in --version\|rev-parse\|ls-files\|status\|check-ignore/);
  assert.match(fast, /\/usr\/bin\/env -i PATH=\/usr\/bin:\/bin/);
  assert.doesNotMatch(fast.slice(0, fast.indexOf('function shimBytes')), /nodeRecipe|NODE_OPTIONS|SSL_CERT_FILE/);
  const snapshot = fs.readFileSync(new URL('source-snapshot.mjs', root), 'utf8');
  assert.ok(snapshot.includes("'scripts/mobile/ios-git-readonly.py'"));
  assert.ok(fs.readFileSync(new URL('../../.gitattributes', root), 'utf8').includes('scripts/mobile/ios-git-readonly.py text eol=lf'));
});

test('Windows owner refusal exposes only fixed existing-source classes before any payload read', () => {
  const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), originalSpawn = cp.spawnSync;
  const uid = Object.getOwnPropertyDescriptor(process, 'getuid'), platform = Object.getOwnPropertyDescriptor(process, 'platform');
  const systemRoot = process.env.SystemRoot, open = fs.openSync, read = fs.readSync, root = trustRoot();
  try {
    process.env.SystemRoot = root; Object.defineProperty(process, 'getuid', { configurable: true, value: undefined }); Object.defineProperty(process, 'platform', { configurable: true, value: 'win32' });
    const rows = [
      [{ ownerClass: 'ADMINISTRATORS', tokenOwnerClass: 'CURRENT_USER', writeScopeSafe: true }, 'HOST_TRUST_CURRENT_OWNER_REQUIRED_SOURCE_HELPER_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_WRITE_SAFE'],
      [{ ownerClass: 'SYSTEM', tokenOwnerClass: 'ADMINISTRATORS', writeScopeSafe: false }, 'HOST_TRUST_CURRENT_OWNER_REQUIRED_SOURCE_HELPER_OWNER_SYSTEM_TOKEN_ADMINISTRATORS_WRITE_UNSAFE'],
      [{ ownerClass: 'TOKEN_OTHER', tokenOwnerClass: 'OTHER', writeScopeSafe: true }, 'HOST_TRUST_CURRENT_OWNER_REQUIRED_SOURCE_HELPER_OWNER_TOKEN_OTHER_TOKEN_OTHER_WRITE_SAFE'],
      [{ ownerClass: 'S-1-5-21-PRIVATE', tokenOwnerClass: 'CURRENT_USER', writeScopeSafe: true }, 'HOST_TRUST_WINDOWS_ACL_PROTOCOL'],
      [{ ownerClass: 'OTHER', tokenOwnerClass: root, writeScopeSafe: true }, 'HOST_TRUST_WINDOWS_ACL_PROTOCOL'],
      [{ ownerClass: 'CURRENT_USER', tokenOwnerClass: 'CURRENT_USER', writeScopeSafe: true }, 'HOST_TRUST_WINDOWS_ACL_PROTOCOL'],
    ];
    for (const [detail, expected] of rows) {
      const fds = []; let reads = 0;
      fs.openSync = (...args) => { const fd = open(...args); fds.push(fd); return fd; }; fs.readSync = (...args) => { reads++; return read(...args); };
      cp.spawnSync = (_exe, _args, options) => {
        assert.equal(options.timeout, 5000); assert.equal(path.basename(options.env.CASEOPS_TRUST_ACL_PATH), 'host-node-trust.mjs');
        return { status: 0, stdout: JSON.stringify({ ownerMatches: false, ...detail }), stderr: 'COPS_ACL0\nCOPS_ACL1\nCOPS_ACL2\nCOPS_ACL3\n' };
      }; syncBuiltinESMExports();
      assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'uncreated'), environment: neutralTrustEnv() }), error => {
        assert.equal(error.message, expected); assert.ok(!error.message.includes(root) && !error.message.includes('S-1-5-21-PRIVATE')); assert.equal(ciTrustFailureCode(error), expected); return true;
      });
      assert.equal(reads, 0); assert.equal(fs.existsSync(path.join(root, 'uncreated')), false); assert.ok(fds.length > 0);
      for (const fd of fds) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
    }
  } finally {
    fs.openSync = open; fs.readSync = read; cp.spawnSync = originalSpawn; syncBuiltinESMExports();
    Object.defineProperty(process, 'getuid', uid); Object.defineProperty(process, 'platform', platform);
    if (systemRoot === undefined) delete process.env.SystemRoot; else process.env.SystemRoot = systemRoot;
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('Windows parent-directory owner refusal stays distinct from existing code and creates no policy objects', () => {
  const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), original = cp.spawnSync;
  const uid = Object.getOwnPropertyDescriptor(process, 'getuid'), platform = Object.getOwnPropertyDescriptor(process, 'platform');
  const systemRoot = process.env.SystemRoot, open = fs.openSync, root = trustRoot(), fds = []; let sawCode = false, directories = 0;
  try {
    process.env.SystemRoot = root; Object.defineProperty(process, 'getuid', { configurable: true, value: undefined }); Object.defineProperty(process, 'platform', { configurable: true, value: 'win32' });
    fs.openSync = (...args) => { const fd = open(...args); fds.push(fd); return fd; };
    cp.spawnSync = (_exe, _args, options) => {
      const directory = options.env.CASEOPS_TRUST_ACL_KIND === 'directory';
      if (directory) { directories++; assert.equal(options.env.CASEOPS_TRUST_ACL_PATH, root); } else sawCode = true;
      return { status: 0, stdout: JSON.stringify(directory ? { ownerMatches: false, writeScopeSafe: true, ownerClass: 'SYSTEM', tokenOwnerClass: 'CURRENT_USER' } : { ownerMatches: true, writeScopeSafe: true }), stderr: 'COPS_ACL0\nCOPS_ACL1\nCOPS_ACL2\nCOPS_ACL3\n' };
    }; syncBuiltinESMExports();
    assert.throws(() => prepareHostNodeTrust({ directory: path.join(root, 'policy'), environment: neutralTrustEnv() }), { message: 'HOST_TRUST_CURRENT_OWNER_REQUIRED_PARENT_DIRECTORY_OWNER_SYSTEM_TOKEN_CURRENT_USER_WRITE_SAFE' });
    assert.equal(sawCode, true); assert.equal(directories, 1); assert.equal(fs.existsSync(path.join(root, 'policy')), false);
    for (const fd of fds) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
  } finally {
    fs.openSync = open; cp.spawnSync = original; syncBuiltinESMExports(); Object.defineProperty(process, 'getuid', uid); Object.defineProperty(process, 'platform', platform);
    if (systemRoot === undefined) delete process.env.SystemRoot; else process.env.SystemRoot = systemRoot;
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('CI owner diagnostics reject arbitrary roles and private detail instead of reflecting it', () => {
  for (const message of [
    'HOST_TRUST_CURRENT_OWNER_REQUIRED_PRIVATE_PATH_OWNER_SYSTEM_TOKEN_CURRENT_USER_WRITE_SAFE',
    'HOST_TRUST_CURRENT_OWNER_REQUIRED_SOURCE_HELPER_OWNER_S-1-5-21-PRIVATE_TOKEN_CURRENT_USER_WRITE_SAFE',
    'HOST_TRUST_CURRENT_OWNER_REQUIRED_SOURCE_HELPER_OWNER_SYSTEM_TOKEN_OTHER_WRITE_SAFE_TRAILING',
    'HOST_TRUST_CURRENT_OWNER_REQUIRED_SOURCE_HELPER_OWNER_CURRENT_USER_TOKEN_CURRENT_USER_WRITE_SAFE',
  ]) assert.equal(ciTrustFailureCode(new Error(message)), 'CI_TRUST_PREPARATION_REFUSED');
  assert.equal(ciTrustFailureCode(new Error('HOST_TRUST_CURRENT_OWNER_REQUIRED_ROOTS_OUTPUT_OWNER_OTHER_TOKEN_OTHER_WRITE_UNSAFE\nPRIVATE_PATH')), 'HOST_TRUST_CURRENT_OWNER_REQUIRED_ROOTS_OUTPUT_OWNER_OTHER_TOKEN_OTHER_WRITE_UNSAFE');
});

function ciSourceCheck() {
  const deadline = performance.now() + 30000, check = () => assert.ok(performance.now() < deadline);
  Object.defineProperty(check, 'deadline', { value: deadline }); return check;
}
async function ciSourceFixture(callback) {
  const root = trustRoot(), source = path.join(root, 'source'), parent = path.join(root, 'new-parent');
  fs.mkdirSync(source, { mode: 0o700 }); fs.mkdirSync(parent, { mode: 0o700 });
  for (const name of ['host-node-trust-ci.mjs', 'host-node-trust.mjs', 'host-node-trust-start.mjs']) fs.writeFileSync(path.join(source, name), fs.readFileSync(new URL(name, import.meta.url)), { flag: 'wx', mode: 0o600 });
  try { const api = await import(pathToFileURL(path.join(source, 'host-node-trust-ci.mjs')).href); return await callback({ root, source, parent, api }); }
  finally { fs.rmSync(root, { recursive: true, force: true }); }
}
function ciSourceTrace() {
  const open = fs.openSync, read = fs.readSync, write = fs.writeSync, descriptors = new Map(); let reads = 0, writes = 0;
  fs.openSync = (name, ...args) => { const fd = open(name, ...args); descriptors.set(fd, String(name)); return fd; };
  fs.readSync = (...args) => { reads++; return read(...args); }; fs.writeSync = (...args) => { writes++; return write(...args); };
  return { descriptors, read, write, get reads() { return reads; }, get writes() { return writes; }, restore() { fs.openSync = open; fs.readSync = read; fs.writeSync = write; }, closed() { for (const fd of descriptors.keys()) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' }); } };
}
function ciSourceWindowsProofs(change) {
  const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), spawn = cp.spawnSync;
  const uid = Object.getOwnPropertyDescriptor(process, 'getuid'), platform = Object.getOwnPropertyDescriptor(process, 'platform'), systemRoot = process.env.SystemRoot;
  let calls = 0;
  Object.defineProperty(process, 'getuid', { configurable: true, value: undefined }); Object.defineProperty(process, 'platform', { configurable: true, value: 'win32' }); process.env.SystemRoot = '/owned-public-windows-system';
  cp.spawnSync = (_exe, args, options) => {
    calls++; assert.ok(options.timeout > 0 && options.timeout <= 5000 && Number.isInteger(options.timeout)); assert.equal(options.maxBuffer, 4096); assert.doesNotMatch(args.at(-1), /Get-Acl|ConvertTo-Json|ConvertFrom-Json|SetAccessControl|SetOwner/);
    const rows = Array.from({ length: 6 }, (_, index) => ({ runtimeOwner: index >= 2, reviewedAdminSource: index < 2, writeScopeSafe: true, tokenUserPresent: true, aclSha256: 'a'.repeat(64) }));
    change?.(rows, calls, options); return { status: 0, stdout: JSON.stringify(rows), stderr: '' };
  }; syncBuiltinESMExports();
  return { get calls() { return calls; }, restore() { cp.spawnSync = spawn; syncBuiltinESMExports(); Object.defineProperty(process, 'getuid', uid); Object.defineProperty(process, 'platform', platform); if (systemRoot === undefined) delete process.env.SystemRoot; else process.env.SystemRoot = systemRoot; } };
}

test('CI runtime copies retain exact reviewed Git blobs with independent readonly owned files', async () => ciSourceFixture(async ({ source, parent, api }) => {
  const check = ciSourceCheck(), staged = api.stageCIHostNodeRuntimeSources(parent, check);
  const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
  const identity = value => fields.map(key => value[key]);
  const namedMatches = (named, descriptor) => {
    for (const key of fields) {
      if (key === 'dev' && process.platform === 'win32' && named.dev === 0n) continue;
      assert.equal(named[key], descriptor[key]);
    }
  };
  const namespace = file => {
    check(); assert.ok(path.isAbsolute(file)); assert.equal(path.resolve(file), file); assert.equal(fs.realpathSync.native(file), file);
    const rows = []; let directory = path.dirname(file);
    while (true) {
      check(); assert.ok(rows.length < 128);
      const value = fs.lstatSync(directory, { bigint: true });
      assert.ok(value.isDirectory() && !value.isSymbolicLink()); assert.equal(fs.realpathSync.native(directory), directory);
      rows.push([directory, value.dev, value.ino, value.mode, value.uid, value.gid]);
      if (path.dirname(directory) === directory) return rows;
      directory = path.dirname(directory);
    }
  };
  const read = (fd, expected) => {
    const bytes = Buffer.alloc(Number(expected) + 1); let used = 0;
    while (used < bytes.length) {
      check(); const count = fs.readSync(fd, bytes, used, bytes.length - used, null);
      if (!count) break;
      used += count;
    }
    assert.equal(used, Number(expected)); return bytes.subarray(0, used);
  };
  try {
    assert.deepEqual(staged.provenance.map(row => [row.gitMode, row.gitBlobSha1]), [['100644', 'b659d65faca119a0cc78ab12c8d41a224bf6d112'], ['100644', '4c18c81d7c0ed28e7188c4335f0922eb024d6dff']]);
    for (const [role, name, expected] of [['helper', 'host-node-trust.mjs', 29741n], ['bootstrap', 'host-node-trust-start.mjs', 6068n]]) {
      const input = path.join(source, name), output = staged.sourceRefs[role].path;
      const flags = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0);
      let inputFd, outputFd, originalFailure; let bodyFailed = false; const closeFailures = [];
      try {
        inputFd = fs.openSync(input, flags); outputFd = fs.openSync(output, flags);
        const inputOpened = fs.fstatSync(inputFd, { bigint: true }), outputOpened = fs.fstatSync(outputFd, { bigint: true });
        for (const value of [inputOpened, outputOpened]) {
          assert.ok(value.isFile()); assert.equal(value.nlink, 1n); assert.equal(value.size, expected);
          if (typeof process.getuid === 'function') assert.equal(value.uid, BigInt(process.getuid()));
        }
        assert.notEqual(inputOpened.ino, outputOpened.ino); assert.equal(outputOpened.mode & 0o777n, 0o400n); assert.equal(inputOpened.mode & 0o777n, 0o600n);
        const inputNamespace = namespace(input), outputNamespace = namespace(output);
        const inputNamed = fs.lstatSync(input, { bigint: true }), outputNamed = fs.lstatSync(output, { bigint: true });
        assert.ok(inputNamed.isFile() && !inputNamed.isSymbolicLink()); assert.ok(outputNamed.isFile() && !outputNamed.isSymbolicLink());
        namedMatches(inputNamed, inputOpened); namedMatches(outputNamed, outputOpened);
        const inputBytes = read(inputFd, expected), outputBytes = read(outputFd, expected);
        assert.deepEqual(inputBytes, outputBytes); if (role === 'helper') assert.deepEqual(staged.retainedHelper, inputBytes);
        assert.deepEqual(inputNamespace, namespace(input)); assert.deepEqual(outputNamespace, namespace(output));
        assert.deepEqual(identity(inputOpened), identity(fs.fstatSync(inputFd, { bigint: true }))); assert.deepEqual(identity(outputOpened), identity(fs.fstatSync(outputFd, { bigint: true })));
        assert.deepEqual(identity(inputNamed), identity(fs.lstatSync(input, { bigint: true }))); assert.deepEqual(identity(outputNamed), identity(fs.lstatSync(output, { bigint: true })));
      } catch (error) { bodyFailed = true; originalFailure = error; }
      finally {
        for (const fd of [outputFd, inputFd]) if (fd !== undefined) {
          try { fs.closeSync(fd); } catch (error) { closeFailures.push(error); }
        }
      }
      if (bodyFailed) throw originalFailure;
      if (closeFailures.length) throw new AggregateError(closeFailures, 'CI source pair descriptor close failed');
    }
  } finally { staged.retainedHelper.fill(0); }
}));

test('CI observed Administrators source is admitted only as pinned public data while new objects stay strict', async () => ciSourceFixture(async ({ parent, api }) => {
  const proof = ciSourceWindowsProofs(), trace = ciSourceTrace(); let staged;
  try { staged = api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()); assert.equal(proof.calls, 2); assert.ok(staged.provenance.every(row => row.originalAcl.runtimeOwner === false && row.originalAcl.reviewedAdminSource && row.copiedAcl.runtimeOwner)); }
  finally { trace.restore(); proof.restore(); staged?.retainedHelper.fill(0); }
  trace.closed();
}));

test('CI source data exception cannot admit a foreign new copy owner or unsafe ACL before payload', async () => ciSourceFixture(async ({ parent, api }) => {
  const proof = ciSourceWindowsProofs(rows => { rows[4].runtimeOwner = false; rows[4].reviewedAdminSource = true; }), trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_OWNER_HELPER_COPY/); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); }
  finally { trace.restore(); proof.restore(); }
  trace.closed();
}));

test('CI source hardlink refuses before bytes and closes its original descriptor', async () => ciSourceFixture(async ({ root, source, parent, api }) => {
  fs.linkSync(path.join(source, 'host-node-trust.mjs'), path.join(root, 'alias')); const trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_INPUT/); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); }
  finally { trace.restore(); } trace.closed();
}));

test('CI source changed reviewed bytes never become copy payload and all four descriptors close', async () => ciSourceFixture(async ({ source, parent, api }) => {
  const file = path.join(source, 'host-node-trust.mjs'), bytes = fs.readFileSync(file); bytes[0] ^= 1; fs.writeFileSync(file, bytes);
  const trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_REVIEWED_BYTES/); assert.equal(trace.writes, 0); assert.equal(trace.descriptors.size, 4); }
  finally { trace.restore(); } trace.closed();
}));

test('CI source replacement during the first ACL observation gives zero payload reads', async () => ciSourceFixture(async ({ root, source, parent, api }) => {
  const file = path.join(source, 'host-node-trust.mjs'); let changed = false;
  const proof = ciSourceWindowsProofs((_rows, call) => { if (call === 1) { fs.renameSync(file, path.join(root, 'retained-original')); fs.copyFileSync(path.join(root, 'retained-original'), file); changed = true; } }), trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_CHANGED_BEFORE_READ/); assert.equal(changed, true); assert.equal(trace.reads, 0); }
  finally { trace.restore(); proof.restore(); } trace.closed();
}));

test('CI source copy replacement changes no existing replacement mode and closes all descriptors', async () => ciSourceFixture(async ({ root, parent, api }) => {
  const trace = ciSourceTrace(); let replacement, changed = false;
  fs.writeSync = (fd, ...args) => {
    const n = trace.write(fd, ...args), name = trace.descriptors.get(fd);
    if (!changed && name?.endsWith('runtime-source/host-node-trust.mjs')) { changed = true; fs.renameSync(name, path.join(root, 'retained-created-copy')); fs.writeFileSync(name, 'existing replacement', { flag: 'wx', mode: 0o600 }); replacement = name; }
    return n;
  };
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_NAMED_DESCRIPTOR_CHANGED/); assert.equal(changed, true); assert.equal(fs.readFileSync(replacement, 'utf8'), 'existing replacement'); assert.equal(fs.statSync(replacement).mode & 0o777, 0o600); }
  finally { trace.restore(); } trace.closed();
}));

test('CI source partial writes progress fully and zero writes refuse without losing descriptors', async () => ciSourceFixture(async ({ root, parent, api }) => {
  const trace = ciSourceTrace(); let staged;
  fs.writeSync = (fd, data, offset, length, position) => trace.write(fd, data, offset, Math.min(length, 7), position);
  try { staged = api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()); assert.equal(staged.retainedHelper.length, 29741); }
  finally { staged?.retainedHelper.fill(0); trace.restore(); } trace.closed();
  const second = path.join(root, 'second-parent'); fs.mkdirSync(second, { mode: 0o700 }); const refused = ciSourceTrace(); fs.writeSync = () => 0;
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(second, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_WRITE_PROGRESS/); }
  finally { refused.restore(); } refused.closed();
}));

test('CI source late ACL drift is refused after owned-copy writes', async () => ciSourceFixture(async ({ parent, api }) => {
  const proof = ciSourceWindowsProofs((rows, call, options) => { if (call === 2) { rows[0].aclSha256 = 'b'.repeat(64); } }), trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_ACL_CHANGED/); }
  finally { trace.restore(); proof.restore(); } trace.closed();
}));

test('CI explicit Windows preparation imports copied bytes and scopes child policy while Unix stays original', async () => {
  const root = trustRoot(), file = path.join(root, 'commands'), workspace = path.join(root, 'workspace'); fs.mkdirSync(workspace, { mode: 0o700 }); fs.writeFileSync(file, 'EARLIER=retained', { flag: 'wx', mode: 0o600 });
  const environment = { ...neutralTrustEnv(), CI: 'true', GITHUB_ACTIONS: 'true', RUNNER_TEMP: root, CASEOPS_CI_WORKSPACE: workspace, GITHUB_OUTPUT: file };
  try {
    const result = await prepareCIHostNodeTrustWindows(environment); assert.equal(result.appendedKeys, 9); assert.equal(result.runtimeSourceCopies.length, 2);
    const scoped = Object.fromEntries(fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).slice(1).map(row => { const i = row.indexOf('='); return [row.slice(0, i), row.slice(i + 1)]; }));
    const policy = JSON.parse(fs.readFileSync(scoped.CASEOPS_HOST_NODE_TRUST_POLICY_FILE));
    assert.ok(policy.runtimeSource.helper.path.startsWith(root + path.sep)); assert.match(policy.runtimeSource.helper.path, /runtime-source[/\\]host-node-trust\.mjs$/); assert.equal(policy.runtimeSource.helper.sha256, '4dcca216db4071bee09d939142c5ea92bfb120b0bffa152ebefcf0b9acab1a18');
    const text = execFileSync(process.execPath, ['--input-type=module', '-e', 'import tls from "node:tls"; console.log(JSON.stringify({count:tls.getCACertificates("default").length}));'], { env: { ...neutralTrustEnv(), ...scoped }, timeout: 12000, encoding: 'utf8', maxBuffer: 16384 }); assert.equal(JSON.parse(text).count, 144);
    const unixFile = path.join(root, 'unix-commands'); fs.writeFileSync(unixFile, '', { flag: 'wx', mode: 0o600 }); prepareCIHostNodeTrust({ ...environment, GITHUB_OUTPUT: unixFile });
    const rows = Object.fromEntries(fs.readFileSync(unixFile, 'utf8').trim().split('\n').map(row => { const i = row.indexOf('='); return [row.slice(0, i), row.slice(i + 1)]; }));
    assert.equal(JSON.parse(fs.readFileSync(rows.CASEOPS_HOST_NODE_TRUST_POLICY_FILE)).runtimeSource.helper.path, trustHelper);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});


test('CI source late extra namespace entry is independently refused with unchanged ACL proof', async () => ciSourceFixture(async ({ parent, api }) => {
  const proof = ciSourceWindowsProofs((_rows, call, options) => { if (call === 2) fs.writeFileSync(path.join(path.dirname(options.env.CASEOPS_SOURCE_4), 'late'), 'new', { flag: 'wx', mode: 0o600 }); }), trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_COMPLETE_NAMES/); assert.equal(proof.calls, 2); }
  finally { trace.restore(); proof.restore(); } trace.closed();
}));

test('CI pinned input exception rejects foreign input owner missing user and unsafe copied writer before payload', async () => {
  for (const change of [rows => { rows[0].reviewedAdminSource = false; }, rows => { rows[0].tokenUserPresent = false; }, rows => { rows[5].writeScopeSafe = false; }]) {
    await ciSourceFixture(async ({ parent, api }) => {
      const proof = ciSourceWindowsProofs(change), trace = ciSourceTrace();
      try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_(?:OWNER_HELPER_INPUT|ACL_PROTOCOL)/); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); }
      finally { trace.restore(); proof.restore(); } trace.closed();
    });
  }
});

test('CI source closed deadline refuses before creating runtime namespace or opening payload', async () => ciSourceFixture(async ({ parent, api }) => {
  const check = () => assert.fail('expired callback must not run'); Object.defineProperty(check, 'deadline', { value: performance.now() - 1 });
  const trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, check), /CI_TRUST_RUNTIME_SOURCE_DEADLINE/); assert.equal(trace.descriptors.size, 0); assert.equal(fs.existsSync(path.join(parent, 'runtime-source')), false); }
  finally { trace.restore(); }
}));

test('CI source parent alias refuses before source payload and never changes existing target', async () => ciSourceFixture(async ({ root, parent, api }) => {
  const alias = path.join(root, 'alias'); fs.symlinkSync(parent, alias, 'dir'); const trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(alias, ciSourceCheck()), /CI_TRUST_RUNTIME_SOURCE_NAMESPACE/); assert.equal(trace.reads, 0); assert.equal(fs.existsSync(path.join(parent, 'runtime-source')), false); }
  finally { trace.restore(); }
}));

test('CI Windows entry executes only copied bytes when exact public inputs have nonexclusive writer observations', async () => ciSourceFixture(async ({ root, source }) => {
  const workspace = path.join(root, 'workspace'), commands = path.join(root, 'commands'); fs.mkdirSync(workspace, { mode: 0o700 }); fs.writeFileSync(commands, '', { flag: 'wx', mode: 0o600 });
  const script = `import fs from 'node:fs'; import { createRequire, registerHooks, syncBuiltinESMExports } from 'node:module'; import { pathToFileURL } from 'node:url';
    const root=process.env.OWNED_FIXTURE_ROOT, source=process.env.OWNED_FIXTURE_SOURCE; let originalLoads=0, batches=0;
    registerHooks({load(url,context,next){if(url===pathToFileURL(source+'/host-node-trust.mjs').href){originalLoads++;throw Error('ORIGINAL_H_FILE_IMPORT_REFUSED')}return next(url,context)}});
    Object.defineProperty(process,'platform',{value:'win32'}); Object.defineProperty(process,'getuid',{value:undefined}); process.env.SystemRoot='/owned-public-windows-system';
    const cp=createRequire(import.meta.url)('node:child_process'); cp.spawnSync=(_exe,args,options)=>{
      if(options.env.CASEOPS_PARENT_CREATED_PATH){const p=options.env.CASEOPS_PARENT_CREATED_PATH;fs.mkdirSync(p,{mode:0o700});const f=fs.lstatSync(p,{bigint:true});return{status:0,stdout:JSON.stringify({created:true,ownerCurrent:true,protected:true,writersExact:true,ino:String(f.ino),volume:String(f.dev),birthtimeNs:String(f.birthtimeNs)}),stderr:[0,1,2,3,4].map(n=>'COPS_PARENT'+n).join(String.fromCharCode(10))+String.fromCharCode(10)}};
      if(options.env.CASEOPS_SOURCE_0){batches++;return {status:0,stdout:JSON.stringify(Array.from({length:6},(_,i)=>({runtimeOwner:i>=2,reviewedAdminSource:i<2,writeScopeSafe:i>=2,tokenUserPresent:true,aclSha256:'a'.repeat(64)}))),stderr:''}};
      if(args.at(-1).includes("[Console]::Out.Write('SAFE')"))return{status:0,stdout:'SAFE',stderr:'COPS_ACL0\\nCOPS_ACL1\\nCOPS_ACL2\\nCOPS_ACL3\\n'.replaceAll('\\\\n','\\n')};
      return{status:0,stdout:'{"ownerMatches":true,"writeScopeSafe":true}',stderr:'COPS_ACL0\\nCOPS_ACL1\\nCOPS_ACL2\\nCOPS_ACL3\\n'.replaceAll('\\\\n','\\n')};
    }; syncBuiltinESMExports();
    const api=await import(pathToFileURL(source+'/host-node-trust-ci.mjs')); const result=await api.prepareCIHostNodeTrustWindows();
    console.log(JSON.stringify({originalLoads,batches,roots:result.approvedRoots,copies:result.runtimeSourceCopies.length,keys:result.appendedKeys}));`;
  const environment = { ...neutralTrustEnv(), CI: 'true', GITHUB_ACTIONS: 'true', RUNNER_TEMP: root, CASEOPS_CI_WORKSPACE: workspace, GITHUB_OUTPUT: commands, OWNED_FIXTURE_ROOT: root, OWNED_FIXTURE_SOURCE: source };
  const output = execFileSync(process.execPath, ['--input-type=module', '--eval', script], { env: environment, timeout: 30000, encoding: 'utf8', maxBuffer: 16384 });
  assert.deepEqual(JSON.parse(output), { originalLoads: 0, batches: 2, roots: 144, copies: 2, keys: 9 });
}));


test('CI source cleanup retains original failure and attempts all four descriptor closures', async () => ciSourceFixture(async ({ source, parent, api }) => {
  const file = path.join(source, 'host-node-trust.mjs'), bytes = fs.readFileSync(file); bytes[0] ^= 1; fs.writeFileSync(file, bytes);
  const trace = ciSourceTrace(), close = fs.closeSync, stderr = process.stderr.write, closed = [], diagnostics = []; let first = true;
  process.stderr.write = value => { diagnostics.push(value); return true; };
  fs.closeSync = fd => { closed.push(fd); close(fd); if (first) { first = false; throw new Error('synthetic close acknowledgement failure'); } };
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), error => error.message === 'CI_TRUST_RUNTIME_SOURCE_REVIEWED_BYTES'); assert.equal(closed.length, 4); assert.deepEqual(diagnostics, ['CI_TRUST_RUNTIME_SOURCE_CLOSE\n']); }
  finally { process.stderr.write = stderr; fs.closeSync = close; trace.restore(); } trace.closed();
}));


async function ciOriginalFaultAndCloseFailure(original) {
  return ciSourceFixture(async ({ parent, api }) => {
    const trace = ciSourceTrace(), close = fs.closeSync, stderr = process.stderr.write, closed = [], diagnostics = []; let first = true, caught = false;
    fs.writeSync = () => { throw original; }; fs.closeSync = fd => { closed.push(fd); close(fd); if (first) { first = false; throw new Error('synthetic close acknowledgement failure'); } };
    process.stderr.write = value => { diagnostics.push(value); return true; };
    try { try { api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()); } catch (error) { caught = true; assert.equal(error, original); } assert.equal(caught, true); assert.equal(closed.length, 4); assert.deepEqual(diagnostics, ['CI_TRUST_RUNTIME_SOURCE_CLOSE\n']); }
    finally { process.stderr.write = stderr; fs.closeSync = close; trace.restore(); } trace.closed();
  });
}
test('CI source cleanup preserves a frozen original Error identity and reports only the fixed close refusal', async () => {
  const original = Object.freeze(new Error('synthetic retained body failure')); await ciOriginalFaultAndCloseFailure(original); assert.equal(Object.hasOwn(original, 'runtimeSourceCleanupError'), false);
});
test('CI source cleanup preserves falsy and primitive original throws while every descriptor closes', async () => {
  for (const original of [undefined, null, false, 0, 'synthetic primitive fault']) await ciOriginalFaultAndCloseFailure(original);
});
test('CI source successful body with a close failure returns no retained source and never retries the close', async () => ciSourceFixture(async ({ parent, api }) => {
  const trace = ciSourceTrace(), close = fs.closeSync, stderr = process.stderr.write, diagnostics = [], closed = []; let first = true;
  fs.closeSync = fd => { closed.push(fd); close(fd); if (first) { first = false; throw undefined; } }; process.stderr.write = value => { diagnostics.push(value); return true; };
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), { message: 'CI_TRUST_RUNTIME_SOURCE_CLOSE' }); assert.equal(closed.length, 4); assert.equal(new Set(closed).size, 4); assert.deepEqual(diagnostics, ['CI_TRUST_RUNTIME_SOURCE_CLOSE\n']); }
  finally { process.stderr.write = stderr; fs.closeSync = close; trace.restore(); } trace.closed();
}));

const ciAclProtocolRoles = ['HELPER_INPUT', 'BOOTSTRAP_INPUT', 'PARENT_DIRECTORY', 'RUNTIME_DIRECTORY', 'HELPER_COPY', 'BOOTSTRAP_COPY'];
const ciAclProtocolRows = () => Array.from({ length: 6 }, (_, index) => ({ runtimeOwner: index >= 2, reviewedAdminSource: index < 2, writeScopeSafe: true, tokenUserPresent: true, aclSha256: 'a'.repeat(64) }));
test('CI six-object ACL decoder preserves the exact valid response and does not promote source ownership', () => {
  const rows = ciAclProtocolRows(), parsed = reviewCIHostSourceAclOutput(JSON.stringify(rows)); assert.deepEqual(parsed, rows);
  assert.equal(parsed[0].runtimeOwner, false); assert.equal(parsed[0].reviewedAdminSource, true); assert.ok(parsed.slice(2).every(row => row.runtimeOwner));
});
test('CI ACL protocol diagnostics distinguish bounded output and array shapes without reflecting raw values', () => {
  for (const [value, reason] of [[undefined, 'JSON_TYPE'], ['', 'JSON_EMPTY'], ['  \r\n', 'JSON_EMPTY'], ['x'.repeat(4097), 'JSON_SIZE'], ['界'.repeat(1400), 'JSON_SIZE'], ['S-1-5-21-SYNTHETIC_PRIVATE_PATH', 'JSON_INVALID'], ['\ufeff[]', 'JSON_INVALID'], ['null', 'ARRAY_TYPE'], ['{}', 'ARRAY_TYPE'], ['[]', 'ARRAY_COUNT'], [JSON.stringify(ciAclProtocolRows().slice(0, 5)), 'ARRAY_COUNT'], [JSON.stringify([...ciAclProtocolRows(), {}]), 'ARRAY_COUNT']]) {
    const expected = 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_OUTPUT_' + reason;
    assert.throws(() => reviewCIHostSourceAclOutput(value), error => { assert.equal(error.message, expected); assert.equal(ciTrustFailureCode(error), expected); assert.ok(!error.message.includes('SYNTHETIC_PRIVATE')); return true; });
  }
});
test('CI ACL decoder identifies only the fixed object role and failing field class for every row', () => {
  const changes = [
    [row => null, 'ROW_TYPE'], [row => [], 'ROW_TYPE'], [row => 'SYNTHETIC_PRIVATE', 'ROW_TYPE'],
    [row => ({ ...row, SYNTHETIC_PRIVATE: 'S-1-5-21-SYNTHETIC' }), 'FIELDS'],
    [row => ({ ...row, runtimeOwner: 'SYNTHETIC_PRIVATE' }), 'OWNER_TYPE'],
    [row => ({ ...row, reviewedAdminSource: 1 }), 'ADMIN_TYPE'],
    [row => ({ ...row, writeScopeSafe: 'true' }), 'WRITE_TYPE'], [row => ({ ...row, writeScopeSafe: false }), 'WRITE_UNSAFE'],
    [row => ({ ...row, tokenUserPresent: 'SYNTHETIC_PRIVATE' }), 'USER_TYPE'], [row => ({ ...row, tokenUserPresent: false }), 'USER_MISSING'],
    [row => ({ ...row, aclSha256: null }), 'HASH_TYPE'], [row => ({ ...row, aclSha256: 'SYNTHETIC_PRIVATE' }), 'HASH_FORMAT'],
  ];
  for (let index = 0; index < 6; index++) for (const [change, reason] of changes) {
    const rows = ciAclProtocolRows(); rows[index] = change(rows[index]); const expected = 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_' + ciAclProtocolRoles[index] + '_' + reason;
    assert.throws(() => reviewCIHostSourceAclOutput(JSON.stringify(rows)), error => { assert.equal(error.message, expected); assert.equal(ciTrustFailureCode(error), expected); assert.ok(!error.message.includes('SYNTHETIC_PRIVATE')); return true; });
  }
});
test('CI actual staged-source strict runtime writers and every token-user refusal read zero payload', async () => {
  for (let index = 0; index < 6; index++) for (const [key, reason] of (index < 2 ? [['tokenUserPresent', 'USER_MISSING']] : [['writeScopeSafe', 'WRITE_UNSAFE'], ['tokenUserPresent', 'USER_MISSING']])) await ciSourceFixture(async ({ parent, api }) => {
    const proof = ciSourceWindowsProofs(rows => { rows[index][key] = false; }), trace = ciSourceTrace();
    try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), { message: 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_' + ciAclProtocolRoles[index] + '_' + reason }); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); assert.equal(proof.calls, 1); }
    finally { trace.restore(); proof.restore(); } trace.closed();
  });
});
test('CI late malformed ACL hash refuses the staged result and purges all retained source buffers', async () => ciSourceFixture(async ({ parent, api }) => {
  const proof = ciSourceWindowsProofs((rows, call) => { if (call === 2) rows[5].aclSha256 = 'SYNTHETIC_PRIVATE'; }), trace = ciSourceTrace(), buffers = new Set();
  fs.readSync = (...args) => { buffers.add(args[1]); return trace.read(...args); };
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), { message: 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_BOOTSTRAP_COPY_HASH_FORMAT' }); assert.equal(proof.calls, 2); assert.ok(buffers.size >= 4); assert.ok([...buffers].every(buffer => buffer.every(value => value === 0))); }
  finally { trace.restore(); proof.restore(); } trace.closed();
}));
test('CI ACL protocol diagnostics reject forged roles reasons and appended private detail', () => {
  for (const value of ['CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_SYNTHETIC_PRIVATE_WRITE_UNSAFE', 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_HELPER_INPUT_SYNTHETIC_PRIVATE', 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_HELPER_INPUT_HASH_FORMAT_S-1-5-21-SYNTHETIC', 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_OUTPUT_JSON_INVALID'.repeat(5)]) assert.equal(ciTrustFailureCode(new Error(value)), 'CI_TRUST_PREPARATION_REFUSED');
  assert.equal(ciTrustFailureCode(new Error('CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_HELPER_COPY_WRITE_UNSAFE\nSYNTHETIC_PRIVATE')), 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_HELPER_COPY_WRITE_UNSAFE');
});


async function ciFreshParentFixture(callback, setup = null) {
  const root = trustRoot(), workspace = path.join(root, 'workspace'), output = path.join(root, 'commands'); fs.mkdirSync(workspace, { mode: 0o700 }); fs.writeFileSync(output, 'EARLIER=retained\n', { flag: 'wx', mode: 0o600 });
  const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), originalSpawn = cp.spawnSync, uid = Object.getOwnPropertyDescriptor(process, 'getuid'), platform = Object.getOwnPropertyDescriptor(process, 'platform'), systemRoot = process.env.SystemRoot;
  const environment = { ...neutralTrustEnv(), CI: 'true', GITHUB_ACTIONS: 'true', RUNNER_TEMP: root, CASEOPS_CI_WORKSPACE: workspace, GITHUB_OUTPUT: output, CASEOPS_PARENT_CREATED_PATH: path.join(root, 'UNADMITTED') }, calls = [];
  Object.defineProperty(process, 'getuid', { configurable: true, value: undefined }); Object.defineProperty(process, 'platform', { configurable: true, value: 'win32' }); process.env.SystemRoot = '/owned-public-windows-system';
  const parentResult = parent => {
    assert.equal(fs.existsSync(parent), false, 'native creation must receive an absent leaf'); fs.mkdirSync(parent, { mode: 0o700 }); const state = fs.lstatSync(parent, { bigint: true });
    return { status: 0, stdout: JSON.stringify({ created: true, ownerCurrent: true, protected: true, writersExact: true, ino: String(state.ino), volume: String(state.dev), birthtimeNs: String(state.birthtimeNs) }), stderr: [0, 1, 2, 3, 4].map(n => 'COPS_PARENT' + n).join('\n') + '\n' };
  };
  cp.spawnSync = (_exe, args, options) => {
    if (options.env.CASEOPS_PARENT_CREATED_PATH) { calls.push({ kind: 'setup', args, options }); return setup ? setup(options, args.at(-1), () => parentResult(options.env.CASEOPS_PARENT_CREATED_PATH)) : parentResult(options.env.CASEOPS_PARENT_CREATED_PATH); }
    if (options.env.CASEOPS_SOURCE_0) { calls.push({ kind: 'source', args, options }); return { status: 0, stdout: JSON.stringify(ciAclProtocolRows().map(row => ({ ...row, runtimeOwner: true, reviewedAdminSource: false }))), stderr: '' }; }
    calls.push({ kind: 'strict-owner', args, options });
    const stderr = [0, 1, 2, 3].map(n => 'COPS_ACL' + n).join('\n') + '\n';
    return args.at(-1).includes("[Console]::Out.Write('SAFE')") ? { status: 0, stdout: 'SAFE', stderr } : { status: 0, stdout: '{"ownerMatches":true,"writeScopeSafe":true}', stderr };
  }; syncBuiltinESMExports();
  try { return await callback({ root, workspace, output, environment, calls }); }
  finally { cp.spawnSync = originalSpawn; syncBuiltinESMExports(); Object.defineProperty(process, 'getuid', uid); Object.defineProperty(process, 'platform', platform); if (systemRoot === undefined) delete process.env.SystemRoot; else process.env.SystemRoot = systemRoot; fs.rmSync(root, { recursive: true, force: true }); }
}
test('CI fresh-parent setup precedes every staged child and payload without using an environment-selected path', async () => {
  let observed = false;
  await ciFreshParentFixture(async ({ environment, calls }) => {
    const result = await prepareCIHostNodeTrustWindows(environment); assert.equal(observed, true); assert.equal(calls[0].kind, 'setup'); assert.equal(calls.filter(row => row.kind === 'setup').length, 1); assert.equal(calls.filter(row => row.kind === 'source').length, 2);
    assert.deepEqual(result.privateParentSetup, { kind: 'windows-protected-new-parent', owner: 'current-user', writers: ['current-user', 'system', 'administrators'], protected: true, identityBound: true, childrenCreatedAfterSetup: true, creation: 'exclusive-native-security-descriptor' });
  }, (options, code, create) => {
    const parent = options.env.CASEOPS_PARENT_CREATED_PATH; assert.equal(fs.existsSync(parent), false); const success = create(); observed = true; assert.match(path.basename(parent), /^caseops-node-trust-[a-f0-9-]{36}$/); assert.ok(!parent.endsWith('UNADMITTED'));
    const iterator = fs.opendirSync(parent, { bufferSize: 1 }); try { assert.equal(iterator.readSync(), null); } finally { iterator.closeSync(); }
    assert.ok(Number.isInteger(options.timeout) && options.timeout > 0 && options.timeout <= 5000); assert.equal(options.maxBuffer, 4096); assert.deepEqual(Object.keys(options.env).sort(), ['CASEOPS_PARENT_CREATED_PATH', 'SystemRoot', 'WINDIR']);
    assert.doesNotMatch(code, /Get-Acl|Set-Acl|Add-Type|ConvertTo-Json|New-Object/); assert.match(code, /SetAccessRuleProtection\(\$true,\$false\)/); assert.match(code, /SetOwner\(\$u\)/); assert.doesNotMatch(code, /SetAccessControl|SetSecurityInfo|Directory\]::CreateDirectory/); assert.match(code, /if\(!\$native::CreateDirectoryW\(\$p,\$sa\)\)\{throw 'EXCLUSIVE_CREATION_REQUIRED'\}/); assert.match(code, /GetSecurityInfo\(\$handle,1,5/); assert.match(code, /CloseHandle\(\$handle\)/); return success;
  });
});
test('CI fresh-parent failed empty unknown or timed-out setup never admits source payload or policy output', async () => {
  for (const [failure, reason] of [[{ status: 0, stdout: '', stderr: '' }, 'PROTOCOL_NO_MARKER'], [{ status: 0, stdout: 'SYNTHETIC_PRIVATE', stderr: '' }, 'PROTOCOL_NO_MARKER'], [{ status: 1, stdout: '', stderr: 'COPS_PARENT_REFUSED\n' }, 'REFUSED_NO_MARKER'], [{ status: null, stdout: '', stderr: '', error: { code: 'ETIMEDOUT' } }, 'TIMEOUT_NO_MARKER']]) await ciFreshParentFixture(async ({ environment, output, calls }) => {
    const trace = ciSourceTrace();
    try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), { message: 'CI_TRUST_PRIVATE_PARENT_SETUP_' + reason }); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); assert.equal(calls.length, 1); assert.equal(calls[0].kind, 'setup'); assert.equal(fs.readFileSync(output, 'utf8'), 'EARLIER=retained\n'); }
    finally { trace.restore(); } trace.closed();
  }, () => failure);
});
test('CI private-parent exclusive creation refuses a collision without touching an existing directory or its contents', async () => {
  const crypto = ciTrustCreateRequire(import.meta.url)('node:crypto'), random = crypto.randomUUID, fixed = '01234567-89ab-cdef-0123-456789abcdef';
  try {
    crypto.randomUUID = () => fixed; syncBuiltinESMExports();
    await ciFreshParentFixture(async ({ root, environment, calls }) => {
      const existing = path.join(root, 'caseops-node-trust-' + fixed); fs.mkdirSync(existing, { mode: 0o700 }); const file = path.join(existing, 'retained'), data = 'SYNTHETIC_EXISTING_CONTENT'; fs.writeFileSync(file, data, { flag: 'wx', mode: 0o600 }); const before = fs.lstatSync(existing, { bigint: true });
      await assert.rejects(prepareCIHostNodeTrustWindows(environment), { code: 'EEXIST' }); assert.equal(calls.length, 0); assert.equal(fs.readFileSync(file, 'utf8'), data); const after = fs.lstatSync(existing, { bigint: true });
      for (const key of ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs']) assert.equal(after[key], before[key]);
    });
  } finally { crypto.randomUUID = random; syncBuiltinESMExports(); }
});
test('CI changed or aliased fresh parent refuses after setup acknowledgement and before any staged source', async () => {
  for (const alias of [false, true]) await ciFreshParentFixture(async ({ root, environment, calls }) => {
    const trace = ciSourceTrace(); try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), /CI_TRUST_PRIVATE_PARENT_CHANGED/); assert.equal(trace.reads, 0); assert.equal(calls.length, 1); }
    finally { trace.restore(); } trace.closed();
  }, (options, _code, create) => {
    const success = create(), parent = options.env.CASEOPS_PARENT_CREATED_PATH, saved = parent + '-retained'; fs.renameSync(parent, saved); if (alias) fs.symlinkSync(saved, parent, 'dir'); else fs.mkdirSync(parent, { mode: 0o700 }); return success;
  });
});
test('CI late fresh-parent entry is refused rather than accepted as an empty setup success', async () => ciFreshParentFixture(async ({ environment, calls }) => {
  const trace = ciSourceTrace(); try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), /CI_TRUST_PRIVATE_PARENT_CHANGED|CI_TRUST_PRIVATE_PARENT_NOT_EMPTY/); assert.equal(trace.reads, 0); assert.equal(calls.length, 1); }
  finally { trace.restore(); } trace.closed();
}, (options, _code, create) => { const success = create(); fs.writeFileSync(path.join(options.env.CASEOPS_PARENT_CREATED_PATH, 'late'), 'owned synthetic entry', { flag: 'wx', mode: 0o600 }); return success; }));
test('CI atomic-parent readback binds inode birth type and namespace before unchanged full-frame admission', async () => {
  const lstat = fs.lstatSync; let parent = null;
  fs.lstatSync = (name, ...args) => { const state = lstat(name, ...args); return String(name) === parent && args[0]?.bigint ? new Proxy(state, { get(value, key) { return key === 'ctimeNs' ? value.ctimeNs + 100n : Reflect.get(value, key); } }) : state; };
  try { await ciFreshParentFixture(async ({ environment }) => { const result = await prepareCIHostNodeTrustWindows(environment); assert.equal(result.privateParentSetup.identityBound, true); }, (options, _code, create) => { parent = options.env.CASEOPS_PARENT_CREATED_PATH; return create(); }); }
  finally { fs.lstatSync = lstat; }
});
test('CI parent-setup refusals retain only fixed diagnostics and never reflect subprocess details', async () => ciFreshParentFixture(async ({ environment }) => {
  await assert.rejects(prepareCIHostNodeTrustWindows(environment), error => { assert.equal(ciTrustFailureCode(error), 'CI_TRUST_PRIVATE_PARENT_SETUP_REFUSED_UNCLASSIFIED'); assert.ok(!error.message.includes('SYNTHETIC_PRIVATE')); return true; });
}, () => ({ status: 1, stdout: 'S-1-5-21-SYNTHETIC_PRIVATE', stderr: '/SYNTHETIC_PRIVATE/PATH', error: { message: 'SYNTHETIC_PRIVATE' } })));


test('CI atomic creation collision after absence admission never changes the existing directory or stages bytes', async () => {
  let trace, fixtureReads = 0, fixtureWrites = 0;
  await ciFreshParentFixture(async ({ environment, calls }) => {
    trace = ciSourceTrace(); try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), { message: 'CI_TRUST_PRIVATE_PARENT_SETUP_REFUSED_STAGE_1' }); assert.equal(trace.reads, fixtureReads); assert.equal(trace.writes, fixtureWrites); assert.equal(calls.length, 1); }
    finally { trace.restore(); } trace.closed();
  }, (options, code) => {
    const parent = options.env.CASEOPS_PARENT_CREATED_PATH; assert.equal(fs.existsSync(parent), false); fs.mkdirSync(parent, { mode: 0o755 }); const retained = path.join(parent, 'existing'); fs.writeFileSync(retained, 'SYNTHETIC_EXISTING', { flag: 'wx', mode: 0o600 }); const before = fs.lstatSync(parent, { bigint: true });
    assert.doesNotMatch(code, /SetAccessControl|SetSecurityInfo/); assert.ok(code.indexOf("throw 'EXCLUSIVE_CREATION_REQUIRED'") < code.indexOf('$handle=$native::CreateFileW'));
    const after = fs.lstatSync(parent, { bigint: true }); for (const key of ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs']) assert.equal(after[key], before[key]); assert.equal(fs.readFileSync(retained, 'utf8'), 'SYNTHETIC_EXISTING');
    fixtureReads = trace.reads; fixtureWrites = trace.writes;
    return { status: 1, stdout: '', stderr: 'COPS_PARENT0\nCOPS_PARENT1\nCOPS_PARENT_REFUSED\n' };
  });
});

test('CI atomic handle identity and qualified Windows volume bind before any source byte read', async () => {
  for (const [key, value] of [['ino', '0'], ['ino', '18446744073709551616'], ['volume', '4294967296'], ['volume', '1'], ['birthtimeNs', '1']]) await ciFreshParentFixture(async ({ environment }) => {
    const trace = ciSourceTrace(); try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), /CI_TRUST_PRIVATE_PARENT_SETUP_PROTOCOL_STAGE_4|CI_TRUST_PRIVATE_PARENT_CHANGED/); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); }
    finally { trace.restore(); } trace.closed();
  }, (_options, _code, create) => { const result = create(), row = JSON.parse(result.stdout); row[key] = value; return { ...result, stdout: JSON.stringify(row) }; });
});
test('CI atomic readback rejects false protection owner writers creation and malformed protocol without reflecting output', async () => {
  for (const change of [row => ({ ...row, created: false }), row => ({ ...row, ownerCurrent: false }), row => ({ ...row, protected: false }), row => ({ ...row, writersExact: false }), row => ({ ...row, unknown: 'SYNTHETIC_PRIVATE' }), row => ({ ...row, ino: 1 }), () => []]) await ciFreshParentFixture(async ({ environment }) => {
    const trace = ciSourceTrace(); try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), error => error.message === 'CI_TRUST_PRIVATE_PARENT_SETUP_PROTOCOL_STAGE_4' && !error.message.includes('SYNTHETIC_PRIVATE')); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); }
    finally { trace.restore(); } trace.closed();
  }, (_options, _code, create) => { const result = create(); return { ...result, stdout: JSON.stringify(change(JSON.parse(result.stdout))) }; });
});


const ciCommandMarkers = 'COPS_ACL0\nCOPS_ACL1\nCOPS_ACL2\nCOPS_ACL3\n';
const ciCommandFalse = (change = {}) => ({ status: 0, stderr: ciCommandMarkers, stdout: JSON.stringify({ ownerMatches: false, writeScopeSafe: true, ownerClass: 'ADMINISTRATORS', tokenOwnerClass: 'CURRENT_USER', ...change }) });
test('CI command-owner decoder retains SAFE and the exact three internal object roles', () => {
  for (const role of ['GITHUB_OUTPUT', 'NPM_USER_CONFIG', 'NPM_GLOBAL_CONFIG']) assert.deepEqual(reviewCICommandOwnerResult({ status: 0, stdout: 'SAFE', stderr: ciCommandMarkers }, role), { ownerMatches: true, writeScopeSafe: true });
  assert.throws(() => reviewCICommandOwnerResult({ status: 0, stdout: 'SAFE', stderr: ciCommandMarkers }, 'SYNTHETIC_PRIVATE'), { message: 'CI_TRUST_COMMAND_OWNER_PROTOCOL' });
});
test('CI command-owner decoder separates bounded timeout command and protocol phases without reflecting output', () => {
  for (const [result, expected] of [[{ error: { code: 'ETIMEDOUT', message: 'SYNTHETIC_PRIVATE' }, status: null, stdout: '', stderr: 'COPS_ACL0\nCOPS_ACL1\n' }, 'TIMEOUT_ACL_READ'], [{ status: 1, stdout: 'SYNTHETIC_PRIVATE', stderr: 'COPS_ACL0\nCOPS_ACL_FAIL\n' }, 'COMMAND_FAILED_SCRIPT_ENTERED'], [{ status: 0, stdout: 'SAFE', stderr: 'COPS_ACL0\n' }, 'PROTOCOL_SCRIPT_ENTERED'], [{ status: 0, stdout: 'SYNTHETIC_PRIVATE', stderr: ciCommandMarkers }, 'PROTOCOL_RULES_READ'], [{ status: 0, stdout: 'SAFE', stderr: 'SYNTHETIC_PRIVATE' }, 'PROTOCOL_UNCLASSIFIED']]) {
    const message = 'CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_' + expected; assert.throws(() => reviewCICommandOwnerResult(result, 'GITHUB_OUTPUT'), error => error.message === message && ciTrustFailureCode(error) === message && !error.message.includes('SYNTHETIC_PRIVATE'));
  }
});
test('CI command-owner negative classifications remain refusal and reject malformed or forged predicate fields', () => {
  for (const [change, suffix] of [[{}, 'OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_SAFE'], [{ ownerMatches: true, writeScopeSafe: false, ownerClass: 'CURRENT_USER' }, 'OWNER_CURRENT_USER_TOKEN_CURRENT_USER_MATCH_YES_WRITE_UNSAFE'], [{ ownerClass: 'OTHER', tokenOwnerClass: 'OTHER', writeScopeSafe: false }, 'OWNER_OTHER_TOKEN_OTHER_MATCH_NO_WRITE_UNSAFE']]) {
    const message = 'CI_TRUST_COMMAND_OWNER_NPM_USER_CONFIG_' + suffix; assert.throws(() => reviewCICommandOwnerResult(ciCommandFalse(change), 'NPM_USER_CONFIG'), error => error.message === message && ciTrustFailureCode(error) === message);
  }
  for (const change of [{ ownerMatches: true }, { ownerMatches: 0 }, { writeScopeSafe: 1 }, { ownerClass: 'S-1-5-21-SYNTHETIC_PRIVATE' }, { tokenOwnerClass: 'SYNTHETIC_PRIVATE' }, { unknown: 'SYNTHETIC_PRIVATE' }]) assert.throws(() => reviewCICommandOwnerResult(ciCommandFalse(change), 'NPM_GLOBAL_CONFIG'), { message: 'CI_TRUST_COMMAND_OWNER_NPM_GLOBAL_CONFIG_PROTOCOL_RULES_READ' });
  for (const text of ['CI_TRUST_COMMAND_OWNER_PRIVATE_TIMEOUT_NO_MARKER', 'CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_OWNER_PRIVATE_TOKEN_OTHER_MATCH_NO_WRITE_SAFE', 'CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_TIMEOUT_NO_MARKER' + 'SYNTHETIC_PRIVATE']) assert.equal(ciTrustFailureCode(new Error(text)), 'CI_TRUST_PREPARATION_REFUSED');
});
test('actual retained command-file append identifies GITHUB_OUTPUT refusal before bytes and closes its descriptor', async () => ciFreshParentFixture(async ({ root, output }) => {
  const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), original = cp.spawnSync, trace = ciSourceTrace(); let observed = 0;
  cp.spawnSync = (_exe, args, options) => { observed++; assert.equal(options.timeout, 4000); assert.equal(options.maxBuffer, 4096); assert.equal(options.env.CASEOPS_TRUST_ACL_PATH, output); assert.doesNotMatch(args.at(-1), /Get-Acl|SetAccessControl|SetOwner|Add-Type/); return ciCommandFalse(); }; syncBuiltinESMExports();
  try { assert.throws(() => appendCITrustOutputs(output, root, Object.fromEntries(ciTrustKeys.map(key => [key, key === 'NPM_CONFIG_STRICT_SSL' ? 'true' : 'synthetic-public']))), { message: 'CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_SAFE' }); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); assert.equal(observed, 1); }
  finally { cp.spawnSync = original; syncBuiltinESMExports(); trace.restore(); } trace.closed(); assert.equal(fs.readFileSync(output, 'utf8'), 'EARLIER=retained\n');
}));
async function ciCommandConfigRefusal(name, role) {
  await ciFreshParentFixture(async ({ environment, output }) => {
    const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), original = cp.spawnSync, trace = ciSourceTrace(); let observed = null;
    cp.spawnSync = (exe, args, options) => { if (options.env.CASEOPS_TRUST_ACL_PATH?.endsWith('/' + name)) { observed = options.env.CASEOPS_TRUST_ACL_PATH; return ciCommandFalse(); } return original(exe, args, options); }; syncBuiltinESMExports();
    try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), { message: 'CI_TRUST_COMMAND_OWNER_' + role + '_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_SAFE' }); }
    finally { cp.spawnSync = original; syncBuiltinESMExports(); trace.restore(); } trace.closed();
    assert.ok(observed); assert.equal(fs.lstatSync(observed).size, 0); assert.equal(fs.readFileSync(output, 'utf8'), 'EARLIER=retained\n');
    if (name === 'user.npmrc') assert.equal(fs.existsSync(path.join(path.dirname(observed), 'global.npmrc')), false);
    else assert.equal(fs.readFileSync(path.join(path.dirname(observed), 'user.npmrc'), 'utf8'), '; CaseOps isolated public npm configuration.\n');
  });
}
test('actual Windows-entry composition distinguishes new NPM_USER_CONFIG before its first write', () => ciCommandConfigRefusal('user.npmrc', 'NPM_USER_CONFIG'));
test('actual Windows-entry composition distinguishes new NPM_GLOBAL_CONFIG and retains earlier anonymous config', () => ciCommandConfigRefusal('global.npmrc', 'NPM_GLOBAL_CONFIG'));


test('CI exact reviewed public inputs retain nonexclusive ACL observations while only strict copied bytes execute', async () => ciSourceFixture(async ({ source, parent, api }) => {
  const proof = ciSourceWindowsProofs(rows => { rows[0].writeScopeSafe = false; rows[1].writeScopeSafe = false; }), trace = ciSourceTrace(); let staged;
  try {
    staged = api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()); assert.equal(proof.calls, 2); assert.equal(staged.provenance.length, 2);
    for (const row of staged.provenance) { assert.equal(row.originalAcl.writeScopeSafe, false); assert.equal(row.originalWriteScope, 'nonexclusive-public-input-data'); assert.equal(row.inputAuthority, 'literal-sha256-gitblob-extent-retained-bytes'); assert.equal(row.copiedAcl.writeScopeSafe, true); assert.equal(row.copiedAcl.runtimeOwner, true); const original = fs.readFileSync(path.join(source, row.name)); assert.equal(createHash('sha256').update(original).digest('hex'), row.originalSha256); assert.equal(createHash('sha256').update(fs.readFileSync(row.copied.path)).digest('hex'), row.originalSha256); if (row.name === 'host-node-trust.mjs') assert.deepEqual(staged.retainedHelper, original); }
  } finally { trace.restore(); proof.restore(); staged?.retainedHelper.fill(0); } trace.closed();
}));
test('CI public-input admission token cannot be forged through the exported strict decoder', () => {
  const rows = ciAclProtocolRows(); rows[0].writeScopeSafe = false;
  for (const attempted of [undefined, true, 1, 'literal-reviewed-public-input-data', {}, { reviewed: true }, Symbol('literal-reviewed-public-input-data')]) assert.throws(() => reviewCIHostSourceAclOutput(JSON.stringify(rows), attempted), { message: 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_HELPER_INPUT_WRITE_UNSAFE' });
});
test('CI nonexclusive public inputs still require the original reviewed owner admission before all payload reads', async () => ciSourceFixture(async ({ parent, api }) => {
  const proof = ciSourceWindowsProofs(rows => { rows[0].writeScopeSafe = false; rows[0].runtimeOwner = false; rows[0].reviewedAdminSource = false; }), trace = ciSourceTrace();
  try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), { message: 'CI_TRUST_RUNTIME_SOURCE_OWNER_HELPER_INPUT' }); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); }
  finally { trace.restore(); proof.restore(); } trace.closed();
}));
test('CI corrupt nonexclusive helper or bootstrap inputs cannot write either staging payload', async () => {
  for (const name of ['host-node-trust.mjs', 'host-node-trust-start.mjs']) await ciSourceFixture(async ({ source, parent, api }) => {
    const file = path.join(source, name), data = fs.readFileSync(file); data[0] ^= 1; fs.writeFileSync(file, data);
    const proof = ciSourceWindowsProofs(rows => { rows[0].writeScopeSafe = false; rows[1].writeScopeSafe = false; }), trace = ciSourceTrace(), buffers = new Set();
    fs.readSync = (...args) => { buffers.add(args[1]); return trace.read(...args); };
    try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), { message: 'CI_TRUST_RUNTIME_SOURCE_REVIEWED_BYTES' }); assert.equal(trace.writes, 0); }
    finally { trace.restore(); proof.restore(); } trace.closed(); assert.ok([...buffers].every(buffer => buffer.every(value => value === 0)));
  });
});
test('CI both input full frames reconcile after immutable byte verification before the first staging write', async () => {
  for (const name of ['host-node-trust.mjs', 'host-node-trust-start.mjs']) await ciSourceFixture(async ({ source, parent, api }) => {
    const proof = ciSourceWindowsProofs(rows => { rows[0].writeScopeSafe = false; rows[1].writeScopeSafe = false; }), trace = ciSourceTrace(), read = fs.readSync, write = fs.writeSync; let changed = false, stagingWrites = 0;
    fs.readSync = (fd, ...args) => { const n = read(fd, ...args); if (!changed && n === 0 && trace.descriptors.get(fd) === path.join(source, 'host-node-trust-start.mjs')) { changed = true; fs.appendFileSync(path.join(source, name), ' '); } return n; };
    fs.writeSync = (fd, ...args) => { if (trace.descriptors.get(fd)?.includes('/runtime-source/')) stagingWrites++; return write(fd, ...args); };
    try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), { message: 'CI_TRUST_RUNTIME_SOURCE_CHANGED_BEFORE_WRITE' }); assert.equal(changed, true); assert.equal(stagingWrites, 0); }
    finally { trace.restore(); proof.restore(); } trace.closed();
  });
});
test('CI public-data writer admission never extends to parent runtime directory or either copied executable', async () => {
  for (let index = 2; index < 6; index++) await ciSourceFixture(async ({ parent, api }) => {
    const proof = ciSourceWindowsProofs(rows => { rows[0].writeScopeSafe = false; rows[1].writeScopeSafe = false; rows[index].writeScopeSafe = false; }), trace = ciSourceTrace();
    try { assert.throws(() => api.stageCIHostNodeRuntimeSources(parent, ciSourceCheck()), { message: 'CI_TRUST_RUNTIME_SOURCE_ACL_PROTOCOL_' + ciAclProtocolRoles[index] + '_WRITE_UNSAFE' }); assert.equal(trace.reads, 0); assert.equal(trace.writes, 0); }
    finally { trace.restore(); proof.restore(); } trace.closed();
  });
});


const ciRunnerOutputName = 'set_output_01234567-89ab-cdef-0123-456789abcdef';
async function ciNativeRunnerFixture(callback, { name = ciRunnerOutputName, nested = false, alias = false, proof = () => ciCommandFalse() } = {}) {
  await ciFreshParentFixture(async f => {
    const directory = path.join(f.root, '_runner_file_commands'); fs.mkdirSync(directory, { mode: 0o700 });
    if (alias) { const retained = path.join(f.root, 'retained-runner-directory'); fs.renameSync(directory, retained); fs.symlinkSync(retained, directory, 'dir'); }
    const destination = nested ? path.join(directory, 'nested') : directory; if (nested) fs.mkdirSync(destination, { mode: 0o700 });
    const command = path.join(destination, name); fs.writeFileSync(command, 'EARLIER=retained\n', { flag: 'wx', mode: 0o600 }); f.environment.GITHUB_OUTPUT = command;
    const cp = ciTrustCreateRequire(import.meta.url)('node:child_process'), original = cp.spawnSync; let calls = 0;
    cp.spawnSync = (exe, args, options) => { if (options.env.CASEOPS_TRUST_ACL_PATH === command) { calls++; return proof({ ...f, directory, command }, args, options); } return original(exe, args, options); }; syncBuiltinESMExports();
    try { await callback({ ...f, directory, command, get commandCalls() { return calls; } }); }
    finally { cp.spawnSync = original; syncBuiltinESMExports(); }
  });
}
test('CI native runner output admits only its observed safe Administrators owner and preserves distinct authority', async () => ciNativeRunnerFixture(async ({ environment, command }) => {
  const result = await prepareCIHostNodeTrustWindows(environment); assert.equal(result.commandFileAuthority, 'native-runner-command-safe-administrators-owner'); assert.equal(result.appendedKeys, 9); assert.equal(result.runtimeSourceCopies.length, 2);
  const rows = fs.readFileSync(command, 'utf8').split('\n'); assert.equal(rows.shift(), 'EARLIER=retained'); assert.equal(rows.pop(), ''); assert.deepEqual(rows.map(row => row.slice(0, row.indexOf('='))), ciTrustKeys);
  assert.ok(result.runtimeSourceCopies.every(row => row.copiedAcl.runtimeOwner && row.copiedAcl.writeScopeSafe));
}));
test('CI exported append and result decoder cannot forge native runner command authority', async () => ciNativeRunnerFixture(async ({ root, environment, command }) => {
  const trace = ciSourceTrace();
  try {
    for (const context of [undefined, {}, { token: Symbol('native-ci-preparation'), file: command, root, environment }]) assert.throws(() => appendCITrustOutputs(command, root, ciTrustValues, context), { message: 'CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_SAFE' });
    for (const token of [undefined, true, {}, Symbol('native-runner-output-command')]) assert.throws(() => reviewCICommandOwnerResult(ciCommandFalse(), 'GITHUB_OUTPUT', token), { message: 'CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_SAFE' });
    assert.equal(trace.reads, 0); assert.equal(trace.writes, 0);
  } finally { trace.restore(); } trace.closed(); assert.equal(fs.readFileSync(command, 'utf8'), 'EARLIER=retained\n');
}));
test('CI native runner class refuses unrelated command prefixes malformed UUID nested paths and parent aliases', async () => {
  for (const options of [{ name: 'set_env_01234567-89ab-cdef-0123-456789abcdef' }, { name: 'set_output_01234567-89ab-cdef-0123-456789abcdef-extra' }, { name: 'set_output_0123456789abcdef0123456789abcdef' }, { nested: true }, { alias: true }]) await ciNativeRunnerFixture(async ({ environment, command }) => {
    await assert.rejects(prepareCIHostNodeTrustWindows(environment), /CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_SAFE|CI_TRUST_CANONICAL_PATH/); assert.equal(fs.readFileSync(command, 'utf8'), 'EARLIER=retained\n');
  }, options);
});
test('CI native runner class cannot admit another owner token or any unsafe writer and keeps timeout refusal', async () => {
  for (const [result, expected] of [[ciCommandFalse({ ownerClass: 'OTHER' }), 'OWNER_OTHER_TOKEN_CURRENT_USER_MATCH_NO_WRITE_SAFE'], [ciCommandFalse({ tokenOwnerClass: 'OTHER' }), 'OWNER_ADMINISTRATORS_TOKEN_OTHER_MATCH_NO_WRITE_SAFE'], [ciCommandFalse({ writeScopeSafe: false }), 'OWNER_ADMINISTRATORS_TOKEN_CURRENT_USER_MATCH_NO_WRITE_UNSAFE'], [{ status: null, error: { code: 'ETIMEDOUT' }, stdout: '', stderr: 'COPS_ACL0\n' }, 'TIMEOUT_SCRIPT_ENTERED']]) await ciNativeRunnerFixture(async ({ environment, command }) => {
    await assert.rejects(prepareCIHostNodeTrustWindows(environment), { message: 'CI_TRUST_COMMAND_OWNER_GITHUB_OUTPUT_' + expected }); assert.equal(fs.readFileSync(command, 'utf8'), 'EARLIER=retained\n');
  }, { proof: () => result });
});
test('CI native runner held command-file replacement during ACL read refuses before appending any bytes', async () => {
  let commandWrites = 0, injectedWrites = 0, trace;
  await ciNativeRunnerFixture(async ({ environment, command, directory }) => {
    trace = ciSourceTrace(); const write = fs.writeSync; fs.writeSync = (fd, ...args) => { if (trace.descriptors.get(fd) === command) commandWrites++; return write(fd, ...args); };
    try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), /CI_TRUST_NAMED_DESCRIPTOR_CHANGED|CI_TRUST_RUNNER_COMMAND_CHANGED/); assert.equal(commandWrites, injectedWrites); }
    finally { trace.restore(); } trace.closed(); assert.equal(fs.readFileSync(command, 'utf8'), 'REPLACEMENT=retained\n'); assert.equal(fs.readFileSync(path.join(directory, 'original-command'), 'utf8'), 'EARLIER=retained\n');
  }, { proof: ({ command, directory }) => { fs.renameSync(command, path.join(directory, 'original-command')); fs.writeFileSync(command, 'REPLACEMENT=retained\n', { flag: 'wx', mode: 0o600 }); injectedWrites = commandWrites; return ciCommandFalse(); } });
});
test('CI native runner late directory insertion refuses with unchanged command bytes and closes descriptors', async () => {
  let trace, commandWrites = 0;
  await ciNativeRunnerFixture(async ({ environment, command }) => {
    trace = ciSourceTrace(); const write = fs.writeSync; fs.writeSync = (fd, ...args) => { if (trace.descriptors.get(fd) === command) commandWrites++; return write(fd, ...args); };
    try { await assert.rejects(prepareCIHostNodeTrustWindows(environment), { message: 'CI_TRUST_RUNNER_COMMAND_CHANGED' }); assert.equal(commandWrites, 0); }
    finally { trace.restore(); } trace.closed(); assert.equal(fs.readFileSync(command, 'utf8'), 'EARLIER=retained\n');
  }, { proof: ({ directory }) => { fs.writeFileSync(path.join(directory, 'late'), 'owned synthetic entry', { flag: 'wx', mode: 0o600 }); return ciCommandFalse(); } });
});

test('CI runner final callback refuses a same-inode edit after verified payload readback', async t => {
  await ciNativeRunnerFixture(async f => {
    const trace = ciSourceTrace(), read = fs.readSync, write = fs.writeSync, native = fs.realpathSync.native, lstat = fs.lstatSync;
    // Qualified capability simulation: only this owned command leaf's named
    // Windows dev field is zero; real inode/type/owner and other frames stay.
    fs.lstatSync = (file, ...args) => { const state = lstat(file, ...args); return file === f.command && args[0]?.bigint ? new Proxy(state, { get(value, key) { return key === 'dev' ? 0n : Reflect.get(value, key); } }) : state; };
    let written = false, readback = false, changed = false, observedError, verifiedEditedByte; const original = fs.lstatSync(f.command, { bigint: true }), inode = original.ino;
    fs.writeSync = (fd, ...args) => { if (trace.descriptors.get(fd) === f.command) written = true; return write(fd, ...args); };
    fs.readSync = (fd, ...args) => { const count = read(fd, ...args); if (written && count === 0 && trace.descriptors.get(fd) === f.command) readback = true; return count; };
    fs.realpathSync.native = (file, ...args) => { const result = native(file, ...args); if (!changed && readback && file === f.command) { changed = true; const matches = [...trace.descriptors].filter(([, name]) => name === file); assert.equal(matches.length, 1); const fd = matches[0][0]; assert.equal(fs.fstatSync(fd, { bigint: true }).ino, inode); trace.write(fd, Buffer.from('X'), 0, 1, 0);
      const frame = value => ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'].map(key => value[key]), end = performance.now() + 5000;
      const namespace = () => { const rows = []; for (let parent = path.dirname(file);;) { assert.ok(performance.now() < end && rows.length < 64); const state = fs.lstatSync(parent, { bigint: true }); assert.ok(state.isDirectory() && !state.isSymbolicLink()); rows.push([parent, ...['dev', 'ino', 'uid', 'gid', 'mode'].map(key => state[key])]); if (parent === path.dirname(parent)) return rows; parent = path.dirname(parent); } }; const parents = namespace();
      const edited = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true }); assert.ok(edited.isFile() && edited.nlink === 1n && edited.uid === original.uid && edited.ino === inode && edited.size > 0n && edited.size <= 1048576n); assert.ok(named.isFile() && !named.isSymbolicLink()); for (const key of ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs']) if (!(process.platform === 'win32' && key === 'dev' && named.dev === 0n)) assert.equal(edited[key], named[key]);
      const bytes = Buffer.alloc(Number(edited.size) + 1); let length = 0;
      try { while (length < bytes.length) { assert.ok(performance.now() < end); const width = trace.read(fd, bytes, length, bytes.length - length, length); if (!width) break; length += width; } assert.equal(BigInt(length), edited.size); assert.deepEqual(frame(fs.fstatSync(fd, { bigint: true })), frame(edited)); assert.deepEqual(frame(fs.lstatSync(file, { bigint: true })), frame(named)); assert.deepEqual(namespace(), parents); verifiedEditedByte = bytes[0]; }
      finally { bytes.fill(0); } } return result; };
    try { try { await prepareCIHostNodeTrustWindows(f.environment); } catch (error) { observedError = error; } }
    finally { fs.realpathSync.native = native; fs.lstatSync = lstat; trace.restore(); } trace.closed();
    const sameInode = fs.lstatSync(f.command, { bigint: true }).ino === inode;
    t.diagnostic(JSON.stringify({ injectedAfterReadback: changed && readback, sameInode, commandQueries: f.commandCalls, outcome: observedError ? 'refused' : 'returned', verifiedEditedByte, namedDevZeroSimulation: true }));
    assert.equal(changed && readback && sameInode, true); assert.equal(f.commandCalls, 1); assert.equal(verifiedEditedByte, 88); assert.equal(observedError?.message, 'CI_TRUST_RUNNER_COMMAND_CHANGED');
  });
});

// Optional source-gate observer contracts. These never authorize native actions.
import { createObserverSink, selectCompactInvocation, nativeActionEntry, SOURCE_GATE_WORKER_PATHS, reviewNestedDriverEvidence, reviewCapturedBasePolicy } from './source-gate-observer.mjs';
const observerNow = () => new Date().getTime();
const observerRoot = path.resolve(fileURLToPath(new URL('../..', import.meta.url)));
const observerNames = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const observerHash = value => createHash('sha256').update(value).digest('hex');
const observerFrame = value => observerNames.map(key => String(value[key]));
function observerRead(file, maximum = 65536) {
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const first = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    assert.equal(first.isFile() && named.isFile() && !named.isSymbolicLink() && first.nlink === 1n, true);
    assert.equal(first.uid, BigInt(process.getuid())); assert.ok(first.size > 0n && first.size <= BigInt(maximum));
    assert.deepEqual(observerFrame(first), observerFrame(named)); assert.equal(fs.realpathSync(file), file);
    const bytes = Buffer.alloc(Number(first.size) + 1); let count = 0;
    while (count < bytes.length) { const n = fs.readSync(fd, bytes, count, Math.min(65536, bytes.length - count), null); if (!n) break; count += n; }
    assert.equal(count, Number(first.size)); assert.deepEqual(observerFrame(first), observerFrame(fs.fstatSync(fd, { bigint: true })));
    assert.deepEqual(observerFrame(named), observerFrame(fs.lstatSync(file, { bigint: true })));
    return Buffer.from(bytes.subarray(0, count));
  } finally { fs.closeSync(fd); }
}
const observerRef = (file, max) => { const bytes = observerRead(file, max); return { path: file, sha256: observerHash(bytes), sizeBytes: bytes.length }; };
let observerBinary;
const observerBinaryRef = () => observerBinary ??= observerRef(process.execPath, 134217728);
function observerSave(file, value) {
  const bytes = Buffer.from(JSON.stringify(value) + '\n'); fs.writeFileSync(file, bytes, { mode: 0o600, flag: 'wx' });
  return { path: file, sha256: observerHash(bytes), sizeBytes: bytes.length };
}
async function withObserverFixture(callback) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-observer-contract-')));
  fs.chmodSync(root, 0o700);
  try {
    for (const name of ['home', 'tmp', 'mode', 'output', 'coverage']) fs.mkdirSync(path.join(root, name), { mode: 0o700 });
    const base = { PATH: `${path.dirname(process.execPath)}${path.delimiter}/usr/bin${path.delimiter}/bin`, HOME: path.join(root, 'home'), TMPDIR: path.join(root, 'tmp'), LANG: 'C', LC_ALL: 'C', TZ: 'UTC' };
    const H = observerRef(path.join(observerRoot, 'scripts/mobile/host-node-trust.mjs'));
    const B = observerRef(path.join(observerRoot, 'scripts/mobile/host-node-trust-start.mjs'));
    const A = observerRef(path.join(observerRoot, 'scripts/mobile/source-gate-observer.mjs'));
    const observerTrust = await import('data:text/javascript;base64,' + observerRead(H.path).toString('base64'));
    const prepared = observerTrust.prepareHostNodeTrust({ directory: path.join(root, 'policy'), sourceRefs: { helper: H, bootstrap: B }, environment: base });
    const selection = { schemaVersion: 1, kind: 'caseops-source-gate-selection', workerCwd: observerRoot,
      workerTargets: [observerRef(path.join(observerRoot, 'apps/mobile/e2e/evidence.test.mjs'))], expoConfigTarget: null, nestedDriver: null };
    const stat = fs.lstatSync(path.join(root, 'output'), { bigint: true });
    const manifest = { schemaVersion: 1, kind: 'caseops-source-gate-observer', role: 'source-gate-only', runId: 'c'.repeat(32),
      source: { repo: observerRoot, sha: 'a'.repeat(40), tree: 'b'.repeat(40) }, phase: 'node33', primaryNode: observerBinaryRef(),
      knownFallbackNodes: [], recorder: A, selection: null, output: { path: path.join(root, 'output'), identity: observerNames.slice(0, 5).map(key => String(stat[key])) }, deadlineEpochMs: observerNow() + 60000 };
    const inheritedCoverage = process.env.NODE_V8_COVERAGE;
    const outerMode = process.env.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE && process.env.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256
      ? { CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE: process.env.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE,
        CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256: process.env.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256 } : null;
    let invocation = 0;
    const run = async ({ args = ['-e', 'console.log("ENTRY_RAN")'], change = () => {}, environment = {}, mode = true, context = false, useOuterMode = false } = {}) => {
      const current = JSON.parse(JSON.stringify(manifest)), selected = JSON.parse(JSON.stringify(selection));
      const dir = path.join(root, `mode-${++invocation}`); fs.mkdirSync(dir, { mode: 0o700 });
      const selectedFile = path.join(dir, 'selection.json'); change(current, selected, dir);
      current.selection = observerSave(selectedFile, selected);
      if (environment.selectionBytes) { fs.writeFileSync(selectedFile, environment.selectionBytes); current.selection.sha256 = observerHash(environment.selectionBytes); current.selection.sizeBytes = environment.selectionBytes.length; }
      const descriptor = observerSave(path.join(dir, 'manifest.json'), current);
      if (environment.manifestBytes) { const raw = typeof environment.manifestBytes === 'function' ? environment.manifestBytes(current) : environment.manifestBytes; fs.writeFileSync(descriptor.path, raw); descriptor.sha256 = observerHash(raw); }
      const env = { ...base, ...prepared.environment, NODE_V8_COVERAGE: inheritedCoverage ?? path.join(root, 'coverage'),
        ...(useOuterMode && outerMode ? outerMode : mode ? { CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE: descriptor.path, CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256: descriptor.sha256 } : {}),
        ...(context ? { NODE_TEST_CONTEXT: 'child-v8' } : {}), ...environment };
      delete env.selectionBytes; delete env.manifestBytes;
      return await new Promise((resolve, reject) => {
        const child = spawn(process.execPath, args, { cwd: observerRoot, env, stdio: ['ignore', 'pipe', 'pipe'] });
        let stdout = Buffer.alloc(0), stderr = Buffer.alloc(0), overflow = false;
        const consume = stream => data => { if (stdout.length + stderr.length + data.length > 1048576) { overflow = true; child.kill(); } else if (stream === 'out') stdout = Buffer.concat([stdout, data]); else stderr = Buffer.concat([stderr, data]); };
        child.stdout.on('data', consume('out')); child.stderr.on('data', consume('err'));
        const timer = setTimeout(() => child.kill(), 10000);
        child.once('error', error => { clearTimeout(timer); reject(error); });
        child.once('close', (code, signal) => { clearTimeout(timer); resolve({ code, signal, stdout, stderr, overflow, descriptor, current, pid: child.pid, coverageDirectory: inheritedCoverage ?? path.join(root, 'coverage'), outerMode: useOuterMode ? outerMode : null }); });
      });
    };
    return await callback({ root, base, prepared, A, B, H, manifest, selection, run, observerTrust });
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
}
function observerFiles(directory) {
  const files = [], seen = new Set(), opened = fs.opendirSync(directory), end = performance.now() + 5000;
  try { while (true) {
    assert.ok(performance.now() < end); const entry = opened.readSync(); if (!entry) break;
    assert.ok(files.length < 128 && !seen.has(entry.name)); seen.add(entry.name); files.push(entry.name);
  } } finally { opened.closeSync(); }
  return files;
}
function observerOuterRecords(pid) {
  const file = process.env.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE, raw = observerRead(file, 16384);
  assert.equal(observerHash(raw), process.env.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256);
  const directory = JSON.parse(raw).output.path, files = observerFiles(directory).filter(name => name.startsWith(`compact-${pid}-0-`));
  assert.equal(files.length, 1);
  return observerRead(path.join(directory, files[0]), 2097152).toString('utf8').trim().split('\n').map(line => JSON.parse(line));
}
function observerRefused(result) {
  assert.equal(result.code, 1); assert.equal(result.signal, null); assert.equal(result.overflow, false);
  assert.equal(result.stdout.length, 0); assert.match(result.stderr.toString(), /^(?:SOURCE_GATE|HOST_TRUST)_[A-Z_]+\n$/);
}
function observerSinkFixture(callback) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-observer-sink-'))); fs.chmodSync(root, 0o700);
  const directory = path.join(root, 'output'); fs.mkdirSync(directory, { mode: 0o700 });
  const stat = fs.lstatSync(directory, { bigint: true }), output = { path: directory, identity: observerNames.slice(0, 5).map(key => String(stat[key])) };
  const io = Object.fromEntries(['openSync', 'closeSync', 'readSync', 'writeSync', 'fstatSync', 'lstatSync', 'realpathSync'].map(key => [key, fs[key].bind(fs)]));
  try { return callback({ root, output, io }); } finally { fs.rmSync(root, { recursive: true, force: true }); }
}

test('source observer import is inert and the worker allowlist is literal and unique', () => {
  assert.equal(SOURCE_GATE_WORKER_PATHS.length, 33); assert.equal(new Set(SOURCE_GATE_WORKER_PATHS).size, 33);
  assert.ok(SOURCE_GATE_WORKER_PATHS.every(name => !name.includes('..') && name.endsWith('.test.mjs')));
});
test('source observer absent mode preserves BASE144 and creates no compact witness', async () => {
  await withObserverFixture(async ({ root, run }) => {
    const result = await run({ mode: false, args: ['-e', 'console.log(require("node:tls").getCACertificates("default").length)'] });
    assert.equal(result.code, 0, result.stderr.toString()); assert.equal(result.stdout.toString(), '144\n'); assert.equal(result.stderr.length, 0);
    assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []);
  });
});
test('source observer unselected eval retains detailed fallback and zero Session output', async () => {
  await withObserverFixture(async ({ root, A, run }) => {
    const uri = 'data:text/javascript;base64,' + observerRead(A.path).toString('base64');
    const result = await run({ args: ['-e', `import(${JSON.stringify(uri)}).then(m=>console.log(JSON.stringify(m.sourceGateObserverStatus())))`] });
    assert.equal(result.code, 0, result.stderr.toString()); assert.equal(result.stderr.length, 0);
    assert.equal(JSON.parse(result.stdout).mode, 'unchanged-detailed-fallback'); assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []);
    assert.ok(observerFiles(result.coverageDirectory).some(name => name.startsWith(`coverage-${result.pid}-`) && name.endsWith('.json')));
  });
});
for (const [name, environment] of [
  ['missing SHA', { CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256: undefined }],
  ['unknown reserved key', { CASEOPS_SOURCE_GATE_OBSERVER_OTHER: '1' }],
  ['case-folded reserved key', { caseops_source_gate_observer_manifest_file: '/unadmitted' }],
]) test(`source observer refuses ${name} before the application`, async () => {
  await withObserverFixture(async ({ run }) => observerRefused(await run({ environment })));
});
for (const [name, change] of [
  ['non-source role', m => { m.role = 'native-qa'; }],
  ['expired descriptor', m => { m.deadlineEpochMs = observerNow() - 1; }],
  ['extended deadline', m => { m.deadlineEpochMs = observerNow() + 600000; }],
  ['unknown descriptor key', m => { m.extra = true; }],
  ['recorder digest redirect', m => { m.recorder.sha256 = '0'.repeat(64); }],
  ['recorder extent redirect', m => { m.recorder.sizeBytes++; }],
  ['duplicate target', (_m, s) => { s.workerTargets.push(s.workerTargets[0]); }],
  ['unreviewed target', (_m, s) => { s.workerTargets[0].path = path.join(observerRoot, 'scripts/mobile/host-node-trust.mjs'); }],
  ['unreviewed working directory', (_m, s) => { s.workerCwd = path.dirname(observerRoot); }],
]) test(`source observer refuses ${name} with no application or compact output`, async () => {
  await withObserverFixture(async ({ root, run }) => {
    observerRefused(await run({ change })); assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []);
  });
});
test('source observer refuses noncanonical duplicate-key JSON and oversized selection before application', async () => {
  await withObserverFixture(async ({ root, run, manifest }) => {
    const duplicate = current => Buffer.from(JSON.stringify(current).replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1') + '\n');
    observerRefused(await run({ environment: { manifestBytes: duplicate } }));
    observerRefused(await run({ environment: { selectionBytes: Buffer.alloc(65537, 32) } }));
    assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []);
  });
});
test('source observer forged hash-correct recorder never executes its sentinel', async () => {
  await withObserverFixture(async ({ root, run }) => {
    const foreign = path.join(root, 'source'); fs.mkdirSync(foreign, { mode: 0o700 });
    fs.mkdirSync(path.join(foreign, 'scripts'), { mode: 0o700 }); fs.mkdirSync(path.join(foreign, 'scripts/mobile'), { mode: 0o700 });
    const file = path.join(foreign, 'scripts/mobile/source-gate-observer.mjs'), sentinel = path.join(root, 'SENTINEL');
    const bytes = Buffer.from(`import fs from 'node:fs';fs.writeFileSync(${JSON.stringify(sentinel)},'executed');export function activateSourceGateObserver(){}\n`);
    fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 });
    const result = await run({ change: m => { m.source.repo = foreign; m.recorder = { path: file, sha256: observerHash(bytes), sizeBytes: bytes.length }; } });
    observerRefused(result); assert.equal(fs.existsSync(sentinel), false);
  });
});
for (const [name, args] of [
  ['core', ['scripts/mobile/run-native.mjs', 'ios']], ['iOS Files', ['scripts/mobile/run-ios-files.mjs']],
  ['Android Files', ['scripts/mobile/run-android-files.mjs']], ['V1', ['scripts/mobile/run-v1-workflows.mjs', 'ios', '--request', '/NEVER_READ_PRIVATE_REQUEST']],
  ['queue/privacy', ['scripts/mobile/run-queue-privacy.mjs', 'ios', '--request', '/NEVER_READ_PRIVATE_REQUEST']],
  ['client extensions', ['scripts/mobile/run-client-extensions.mjs', 'ios', '--request', '/NEVER_READ_PRIVATE_REQUEST']],
  ['store execution', ['scripts/mobile/run-store-packaging.mjs', '--execute', '/NEVER_READ_PRIVATE_REQUEST']],
]) test(`source observer valid mode refuses ${name} before its actual entry`, async () => {
  await withObserverFixture(async ({ root, run }) => {
    const result = await run({ args: [path.join(observerRoot, args[0]), ...args.slice(1)] }); observerRefused(result);
    assert.equal(result.stderr.toString(), 'SOURCE_GATE_OBSERVER_NATIVE_REFUSED\n'); assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []);
  });
});
test('source observer native recipe rejects the pair and pure inventory forms remain non-native', () => {
  assert.throws(() => neutralIosEnvironment({ CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE: '/not-read', CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256: 'a'.repeat(64) }), /IOS_HOST_/);
  for (const args of [['scripts/mobile/run-native.mjs', '--collect'], ['scripts/mobile/run-v1-workflows.mjs', '--collect'], ['scripts/mobile/run-store-packaging.mjs', '--plan']])
    assert.equal(nativeActionEntry(observerRoot, [process.execPath, path.join(observerRoot, args[0]), ...args.slice(1)]), false);
});
test('source observer exact selector keeps Node22, Worker, unknown argv and changed source in rich fallback', () => {
  const ref = { path: '/approved/test.mjs', sha256: 'a'.repeat(64), sizeBytes: 3 };
  const admitted = { admissionComplete: true, primaryNode: { path: '/node24', version: '24.15.0' }, workerCwd: '/approved', workerTargets: [ref], startupFlags: ['--use-openssl-ca'], expoConfigTarget: null };
  const actual = { isMainThread: true, executable: '/node24', nodeVersion: '24.15.0', execArgv: ['--use-openssl-ca'], argv: ['/node24', ref.path], cwd: '/approved', testContext: 'child-v8', entryReference: ref };
  assert.equal(selectCompactInvocation(actual, admitted).mode, 'compact');
  for (const delta of [{ isMainThread: false }, { executable: '/node22', nodeVersion: '22.14.0' }, { argv: ['/node24', ref.path, 'extra'] }, { entryReference: { ...ref, sha256: 'b'.repeat(64) } }, { execArgv: ['--inspect'] }])
    assert.deepEqual(selectCompactInvocation({ ...actual, ...delta }, admitted).sessionAllowed, false);
});
test('source observer sink uses its one FD, exact partial writes and same-FD readback', t => observerSinkFixture(({ output, io }) => {
  t.mock.method(Date, 'now', () => 0); assert.equal(Date.now(), 0); assert.ok(observerNow() > 1000000000000);
  let opens = 0, closes = 0; const originalOpen = io.openSync, originalClose = io.closeSync, originalWrite = io.writeSync;
  io.openSync = (...args) => { opens++; return originalOpen(...args); }; io.closeSync = fd => { closes++; return originalClose(fd); };
  io.writeSync = (fd, bytes, offset, length, position) => originalWrite(fd, bytes, offset, Math.min(7, length), position);
  const sink = createObserverSink(output, observerNow() + 5000, io); sink.emit({ event: 'unit', value: 'partial'.repeat(8) }); sink.close();
  const bytes = fs.readFileSync(sink.file); assert.equal(JSON.parse(bytes).value, 'partial'.repeat(8)); assert.equal(bytes.length, sink.bytes); assert.equal(sink.readbackBytes, sink.bytes);
  assert.equal(opens, 1); assert.equal(closes, 1);
}));
for (const [name, kind] of [['zero write', 'zero'], ['partial then EIO', 'partial'], ['readback failure', 'read']])
  test(`source observer sink closes after ${name} and preserves its actual successful extent`, () => observerSinkFixture(({ output, io }) => {
    let closes = 0, writes = 0; const close = io.closeSync, write = io.writeSync;
    io.closeSync = fd => { closes++; return close(fd); };
    if (kind === 'read') io.readSync = () => { throw Object.assign(new Error('synthetic read error'), { code: 'EIO' }); };
    else io.writeSync = (fd, bytes, offset, length, position) => { if (kind === 'zero') return 0; if (writes++) throw Object.assign(new Error('synthetic write error'), { code: 'EIO' }); return write(fd, bytes, offset, Math.min(5, length), position); };
    const sink = createObserverSink(output, observerNow() + 5000, io); let failure;
    try { sink.emit({ event: 'unit' }); } catch (error) { failure = error; } finally { sink.close(); }
    assert.ok(failure); assert.equal(closes, 1); assert.equal(fs.statSync(sink.file).size, sink.bytes);
    assert.equal(sink.bytes, kind === 'zero' ? 0 : kind === 'partial' ? 5 : Buffer.byteLength('{"ordinal":0,"event":"unit"}\n'));
  }));
test('source observer sink refuses late parent rename to a symlink to the same leaf inode', () => observerSinkFixture(({ root, output, io }) => {
  const sink = createObserverSink(output, observerNow() + 5000, io), moved = path.join(root, 'moved');
  fs.renameSync(output.path, moved); fs.symlinkSync(moved, output.path, 'dir');
  try { assert.throws(() => sink.emit({ event: 'unit' }), /SOURCE_GATE_/); assert.equal(sink.bytes, 0); }
  finally { sink.close(); }
}));
test('source observer real selected worker retains exact engine hashes and the unfiltered native exit diagnostic', async () => {
  await withObserverFixture(async ({ root, run }) => {
    const result = await run({ args: [path.join(observerRoot, 'apps/mobile/e2e/evidence.test.mjs')], context: true, useOuterMode: true });
    assert.equal(result.code, 0, result.stderr.toString()); assert.equal(result.signal, null); assert.equal(result.overflow, false);
    assert.equal(result.stderr.toString(), 'Failed to get \'result\' from coverage profile response:\n{"id":4,"error":{"code":-32000,"message":"Precise coverage has not been started."}}\n');
    let directory = path.join(root, 'output');
    if (result.outerMode) {
      const raw = observerRead(result.outerMode.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_FILE, 16384);
      assert.equal(observerHash(raw), result.outerMode.CASEOPS_SOURCE_GATE_OBSERVER_MANIFEST_SHA256);
      directory = JSON.parse(raw).output.path;
    }
    const files = observerFiles(directory).filter(name => name.startsWith(`compact-${result.pid}-0-`)); assert.equal(files.length, 1);
    const rows = observerRead(path.join(directory, files[0]), 2097152).toString('utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.equal(rows[0].event, 'header'); assert.equal(rows[0].selection, 'exact-declared-test-worker');
    assert.ok(rows.some(row => row.event === 'live')); assert.ok(rows.some(row => row.event === 'detailed-coverage-stopped'));
    const entry = pathToFileURL(path.join(observerRoot, 'apps/mobile/e2e/evidence.test.mjs')).href;
    const script = rows.find(row => row.event === 'script' && row.url === entry); assert.ok(script);
    assert.equal(script.engineSha256, observerHash(fs.readFileSync(new URL(entry))));
    assert.ok(rows.some(row => row.event === 'exit-marker' && row.code === 0)); assert.ok(fs.statSync(path.join(directory, files[0])).size < 2097152);
    assert.deepEqual(observerFiles(result.coverageDirectory).filter(name => name.startsWith(`coverage-${result.pid}-`)), []);
  });
});
for (const [label, extra, compactCount] of [
  ['captured Node24 defaults', [], 1],
  ['changed stack trace default', ['--stack-trace-limit=11'], 0],
]) test(`source observer actual intrinsic CLI ${label} preserves all evidence cases`, async () => {
  await withObserverFixture(async ({ root, run }) => {
    // Exercise Node's real controller-to-worker argv serialization. A synthetic
    // NODE_TEST_CONTEXT with direct entry execution does not reproduce it.
    const result = await run({ args: [...extra, '--test', '--test-reporter=tap', path.join(observerRoot, 'apps/mobile/e2e/evidence.test.mjs')] });
    assert.equal(result.code, 0, result.stderr.toString()); assert.equal(result.signal, null); assert.equal(result.overflow, false);
    const output = result.stdout.toString();
    for (const [name, value] of [['tests', 12], ['pass', 12], ['fail', 0], ['cancelled', 0], ['skipped', 0], ['todo', 0]])
      assert.match(output, new RegExp(`^# ${name} ${value}$`, 'm'));
    const directory = path.join(root, 'output'), files = observerFiles(directory);
    assert.equal(files.length, compactCount);
    if (compactCount) {
      const rows = observerRead(path.join(directory, files[0]), 2097152).toString('utf8').trim().split('\n').map(line => JSON.parse(line));
      assert.equal(rows[0].event, 'header'); assert.equal(rows[0].selection, 'exact-declared-test-worker');
      assert.ok(rows.some(row => row.event === 'live'));
      assert.ok(rows.some(row => row.event === 'exit-marker' && row.code === 0));
      const entry = pathToFileURL(path.join(observerRoot, 'apps/mobile/e2e/evidence.test.mjs')).href;
      assert.equal(rows.find(row => row.event === 'script' && row.url === entry)?.engineSha256,
        observerHash(fs.readFileSync(new URL(entry))));
    } else {
      assert.ok(observerFiles(result.coverageDirectory).some(name => name.startsWith('coverage-')));
    }
  });
});
test('source observer inherited normal ESM Worker remains rich without a Session or exit diagnostic', async () => {
  await withObserverFixture(async ({ root, A, run }) => {
    const uri = 'data:text/javascript;base64,' + observerRead(A.path).toString('base64');
    const worker = `import{parentPort}from'node:worker_threads';import tls from'node:tls';const m=await import(${JSON.stringify(uri)});parentPort.postMessage({status:m.sourceGateObserverStatus(),roots:tls.getCACertificates('default').length})`;
    const code = `const{Worker}=require('node:worker_threads');const w=new Worker(new URL(${JSON.stringify('data:text/javascript;base64,')}+Buffer.from(${JSON.stringify(worker)}).toString('base64')));w.once('message',r=>console.log(JSON.stringify(r)));w.once('exit',c=>{if(c)process.exitCode=c})`;
    const result = await run({ args: ['-e', code] }); assert.equal(result.code, 0, result.stderr.toString()); assert.equal(result.stderr.length, 0);
    const report = JSON.parse(result.stdout); assert.equal(report.roots, 144, JSON.stringify(report)); assert.equal(report.status.reason, 'worker-thread');
    assert.equal(report.status.sessionAllowed, false); assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []);
    assert.ok(observerFiles(result.coverageDirectory).filter(name => name.startsWith(`coverage-${result.pid}-`)).length >= 2);
  });
});
test('source observer async and synchronous unselected children retain their exact output and detailed fallback', async () => {
  await withObserverFixture(async ({ root, run }) => {
    const code = `const{spawn,spawnSync}=require('node:child_process');const args=['-e','console.log(require("node:tls").getCACertificates("default").length)'];const c=spawn(process.execPath,args,{stdio:['ignore','pipe','pipe']});let o='',e='';c.stdout.on('data',b=>o+=b);c.stderr.on('data',b=>e+=b);c.once('close',n=>{const s=spawnSync(process.execPath,args,{encoding:'utf8'});console.log(JSON.stringify({async:{code:n,stdout:o,stderr:e,pid:c.pid},sync:{code:s.status,stdout:s.stdout,stderr:s.stderr,pid:s.pid}}))})`;
    const result = await run({ args: ['-e', code] }); assert.equal(result.code, 0, result.stderr.toString()); assert.equal(result.stderr.length, 0);
    const report = JSON.parse(result.stdout); for (const value of Object.values(report)) { const { pid, ...output } = value; assert.ok(Number.isSafeInteger(pid) && pid > 0); assert.deepEqual(output, { code: 0, stdout: '144\n', stderr: '' }); }
    assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []); for (const pid of [result.pid, report.async.pid, report.sync.pid]) assert.equal(observerFiles(result.coverageDirectory).filter(name => name.startsWith(`coverage-${pid}-`)).length, 1);
  });
});
test('source observer Expo selector requires the exact pinned public or introspect argv and current ref', () => {
  const ref = { path: '/approved/apps/mobile/node_modules/expo/bin/cli', sha256: 'a'.repeat(64), sizeBytes: 43 };
  const target = { entry: ref, cwd: '/approved/apps/mobile', argvSuffixes: [['config', '--type', 'public', '--json'], ['config', '--type', 'introspect', '--json']] };
  const admitted = { admissionComplete: true, primaryNode: { path: '/node24', version: '24.15.0' }, workerCwd: '/approved', workerTargets: [], startupFlags: [], expoConfigTarget: target };
  const actual = { isMainThread: true, executable: '/node24', nodeVersion: '24.15.0', execArgv: [], argv: ['/node24', ref.path, ...target.argvSuffixes[0]], cwd: target.cwd, entryReference: ref };
  assert.equal(selectCompactInvocation(actual, admitted).reason, 'exact-pinned-expo-config');
  assert.equal(selectCompactInvocation({ ...actual, argv: ['/node24', ref.path, ...target.argvSuffixes[1]] }, admitted).mode, 'compact');
  for (const delta of [{ argv: [...actual.argv, '--unsafe'] }, { cwd: '/approved' }, { entryReference: { ...ref, sha256: 'b'.repeat(64) } }, { argv: ['/node24', ref.path, 'start'] }])
    assert.equal(selectCompactInvocation({ ...actual, ...delta }, admitted).sessionAllowed, false);
});
function observerNestedEvidence() {
  const ref = path => ({ path, sha256: 'a'.repeat(64), sizeBytes: 10 });
  const rule = { constructorSource: ref('/owned/Q/scripts/mobile/tooling.test.mjs'), fixture: ref('/owned/Q/scripts/mobile/host-node-trust-fixture.mjs'), cwd: '/owned/Q' };
  const environment = { HOME: '/owned/home', NODE_OPTIONS: 'held-B', SSL_CERT_FILE: '/owned/roots.pem', SSL_CERT_DIR: '/owned/empty',
    CASEOPS_HOST_NODE_TRUST_POLICY_FILE: '/owned/policy.json', CASEOPS_HOST_NODE_TRUST_POLICY_SHA256: 'b'.repeat(64) };
  const start = { file: '/node24', args: ['/node24', '--test', '--test-reporter=tap', rule.fixture.path], cwd: rule.cwd,
    options: { detached: false, windowsHide: true, windowsVerbatimArguments: false },
    stdio: [{ type: 'ignore' }, { type: 'pipe', readable: false, writable: true }, { type: 'pipe', readable: false, writable: true }],
    envPairs: Object.entries({ ...environment, CASEOPS_HOST_NODE_BOOTSTRAP_TEST: '1' }).map(([k, v]) => `${k}=${v}`) };
  return { actual: { start, end: JSON.parse(JSON.stringify(start)), pid: 123, parentEntryReference: rule.constructorSource },
    manifest: { primaryNode: { path: '/node24' } }, selection: { nestedDriver: rule }, context: {
      initialEnvironment: { ...environment, NODE_TEST_CONTEXT: 'child-v8' }, nodeEnvironmentKeys: ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256'],
      bootstrapReference: ref('/owned/B.mjs'), reviewNestedEnvironment: () => ({ scopedPolicyVerified: true, childEffectiveDefaultClaim: false, expectedDefaultCount: 144, policyRef: ref('/owned/policy.json') }) } };
}
test('source observer nested evidence keeps the intrinsic role distinct from a worker witness', () => {
  const { actual, manifest, selection, context } = observerNestedEvidence(), result = reviewNestedDriverEvidence(actual, manifest, selection, context);
  assert.equal(result.scriptCompleteClaim, false); assert.equal(result.workerWitnessRequired, true); assert.deepEqual(result.argv, actual.start.args);
  assert.deepEqual(result.environment.NODE_OPTIONS.exactHeldBootstrap, context.bootstrapReference);
});
for (const [name, change] of [
  ['missing PID', a => { a.pid = undefined; }], ['wrong constructor source', a => { a.parentEntryReference.sha256 = 'c'.repeat(64); }],
  ['changed snapshot', a => { a.end.cwd = '/changed'; }], ['wrong cwd', a => { a.start.cwd = a.end.cwd = '/changed'; }],
  ['detached group', a => { a.start.options.detached = a.end.options.detached = true; }],
  ['custom reporter', a => { a.start.args[2] = a.end.args[2] = '--test-reporter=custom'; }],
  ['unknown environment', a => { a.start.envPairs.push('UNKNOWN_PRIVATE=unretained'); a.end.envPairs.push('UNKNOWN_PRIVATE=unretained'); }],
  ['duplicate environment', a => { a.start.envPairs.push(a.start.envPairs[0]); a.end.envPairs.push(a.end.envPairs[0]); }],
  ['missing curated environment', a => { a.start.envPairs.shift(); a.end.envPairs.shift(); }],
]) test(`source observer nested evidence refuses ${name} without transferring a workload claim`, () => {
  const { actual, manifest, selection, context } = observerNestedEvidence();
  actual.parentEntryReference = { ...actual.parentEntryReference }; change(actual);
  assert.throws(() => reviewNestedDriverEvidence(actual, manifest, selection, context), /SOURCE_GATE_NESTED_/);
});
for (const [label, emptyExecArgv] of [['default', false], ['explicit empty execArgv', true]])
  test(`source observer classic CJS eval Worker ${label} preserves pre-existing startup and no observer Session`, async () => {
    await withObserverFixture(async ({ root, A, run }) => {
      const uri = 'data:text/javascript;base64,' + observerRead(A.path).toString('base64');
      const worker = `import(${JSON.stringify(uri)}).then(m=>require('node:worker_threads').parentPort.postMessage({status:m.sourceGateObserverStatus(),roots:require('node:tls').getCACertificates('default').length}))`;
      const code = `const{Worker}=require('node:worker_threads');const w=new Worker(${JSON.stringify(worker)},{eval:true${emptyExecArgv ? ',execArgv:[]' : ''}});w.once('message',r=>console.log(JSON.stringify({mainRoots:require('node:tls').getCACertificates('default').length,worker:r})));w.once('exit',c=>{if(c)process.exitCode=c})`;
      const baseline = await run({ args: ['-e', code], mode: false }), observed = await run({ args: ['-e', code] });
      for (const result of [baseline, observed]) {
        assert.equal(result.code, 0, result.stderr.toString()); assert.equal(result.signal, null); assert.equal(result.stderr.length, 0);
        // This enumeration is a constructor fact, not an HTTPS or TLS-clean verdict.
        assert.deepEqual(JSON.parse(result.stdout), { mainRoots: 144, worker: { status: { mode: 'not-activated' }, roots: 0 } });
        assert.ok(observerFiles(result.coverageDirectory).filter(name => name.startsWith(`coverage-${result.pid}-`)).length >= 2);
      }
      assert.deepEqual(JSON.parse(observed.stdout), JSON.parse(baseline.stdout)); assert.deepEqual(fs.readdirSync(path.join(root, 'output')), []);
    });
  });
async function observerChildPolicy(callback) {
  return await withObserverFixture(async fixture => {
    const child = fixture.observerTrust.prepareHostNodeTrust({ directory: path.join(fixture.root, 'child-policy'), environment: fixture.base, sourceRefs: { helper: fixture.H, bootstrap: fixture.B } });
    const environment = { ...child.environment }, descriptor = JSON.parse(fs.readFileSync(child.policyRef.path));
    const commit = () => { const raw = Buffer.from(JSON.stringify(descriptor, null, 2) + '\n'); fs.writeFileSync(child.policyRef.path, raw); environment.CASEOPS_HOST_NODE_TRUST_POLICY_SHA256 = observerHash(raw); };
    const context = { parentPolicy: fixture.prepared.descriptor, parentReport: { defaultEnumerationVerified: true, expectedDefaultCount: 144 },
      sourceRepo: observerRoot, bootstrapBytes: observerRead(fixture.B.path), deadlineEpochMs: observerNow() + 5000 };
    // This helper supplies an explicit parent-admission double. The runtime B
    // must obtain that admission from H's actual CURRENT process; this unit is
    // a real-FS public-policy contract, not another process's TLS proof.
    return callback({ ...fixture, child, environment, descriptor, commit, context });
  });
}
test('source observer captured child BASE policy matches the retained approved PEM and never claims its TLS default', async () => {
  await observerChildPolicy(({ environment, context, child }) => {
    const result = reviewCapturedBasePolicy(environment, context);
    assert.equal(result.scopedPolicyVerified, true); assert.equal(result.childEffectiveDefaultClaim, false);
    assert.equal(result.policyRef.path, child.policyRef.path); assert.equal(result.parentApprovedBundleSha256, context.parentPolicy.bundle.sha256);
  });
});
for (const [name, change] of [
  ['root fields', f => { f.descriptor.outputSetSha256 = '0'.repeat(64); f.commit(); }],
  ['helper source path', f => { f.descriptor.runtimeSource.helper.path = path.join(f.root, 'foreign-helper.mjs'); f.commit(); }],
  ['bootstrap source hash', f => { f.descriptor.runtimeSource.bootstrap.sha256 = '0'.repeat(64); f.commit(); }],
  ['policy extra field', f => { f.descriptor.unknown = true; f.commit(); }],
  ['native-QA role', f => { f.descriptor.role = 'native-qa'; f.commit(); }],
  ['bundle bytes', f => { const b = Buffer.from('different public bundle\n'); fs.writeFileSync(f.descriptor.bundle.path, b); f.descriptor.bundle.sha256 = observerHash(b); f.descriptor.bundle.sizeBytes = b.length; f.commit(); }],
  ['Node options', f => { f.environment.NODE_OPTIONS += ' --require=unreviewed'; }],
  ['additional CA', f => { f.environment.NODE_EXTRA_CA_CERTS = '/not-read'; }],
  ['proxy', f => { f.environment.HTTPS_PROXY = 'https://not-read.invalid'; }],
  ['case-folded tuple', f => { f.environment.ssl_cert_file = f.environment.SSL_CERT_FILE; }],
  ['nonempty private directory', f => { fs.writeFileSync(f.descriptor.emptyDirectory + '/late', 'x', { flag: 'wx', mode: 0o600 }); }],
]) test(`source observer captured child policy refuses changed ${name}`, async () => {
  await observerChildPolicy(fixture => { change(fixture); assert.throws(() => reviewCapturedBasePolicy(fixture.environment, fixture.context), /SOURCE_GATE_/); });
});

import { rebuildHostNodeBootstrap, readBootstrapGeneratorInput } from './rebuild-host-node-bootstrap.mjs';
test('source observer bootstrap generator preserves exact tokens and AST within the original Windows bound', t => {
  const folder = path.dirname(trustHelper), input = readBootstrapGeneratorInput(path.join(folder, 'host-node-trust-start.source.mjs'));
  const actual = readBootstrapGeneratorInput(path.join(folder, 'host-node-trust-start.mjs'));
  const declared = JSON.parse(readBootstrapGeneratorInput(path.join(folder, 'host-node-trust-start.provenance.json')));
  const pins = JSON.parse(fs.readFileSync(path.join(folder, 'tooling.json'))).sourceGateObserver;
  assert.deepEqual(Object.keys(pins).sort(), ['bootstrapReadable', 'generator', 'provenance', 'recorder']);
  for (const ref of Object.values(pins)) {
    const raw = observerRead(path.join(folder, ref.file), 65536);
    assert.equal(raw.length, ref.sizeBytes); assert.equal(observerHash(raw), ref.sha256);
  }
  const first = rebuildHostNodeBootstrap(input), second = rebuildHostNodeBootstrap(input);
  assert.ok(first.bytes.equals(actual) && second.bytes.equals(actual)); assert.deepEqual(first.provenance, declared);
  assert.equal(first.provenance.exactAstEqual, true); assert.ok(first.provenance.optionWithSourceMapsBytes <= 8191);
  assert.throws(() => rebuildHostNodeBootstrap(Buffer.alloc(16385)), /BOOTSTRAP_GENERATOR_INPUT/);
  assert.throws(() => rebuildHostNodeBootstrap(Buffer.from([0xff])), /encoded data|UTF-8/);
  const root = trustRoot(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const alias = path.join(root, 'alias'); fs.symlinkSync(path.join(folder, 'host-node-trust-start.source.mjs'), alias);
  assert.throws(() => readBootstrapGeneratorInput(alias), /BOOTSTRAP_GENERATOR_PATH/);
  const file = path.join(root, 'input'); fs.writeFileSync(file, input, { flag: 'wx', mode: 0o600 });
  const open = fs.openSync, read = fs.readSync; let descriptor;
  fs.openSync = (...args) => { descriptor = open(...args); return descriptor; };
  fs.readSync = () => { throw new Error('SYNTHETIC_GENERATOR_READ'); };
  try { assert.throws(() => readBootstrapGeneratorInput(file), /SYNTHETIC_GENERATOR_READ/); }
  finally { fs.openSync = open; fs.readSync = read; }
  assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
});
