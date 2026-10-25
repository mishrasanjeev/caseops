import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import http from 'node:http';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { binaryHash, byTestId, Journal, localJson, localUrl, MARKER, MARKER_HEADER, reconcileInventory, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { scenarios } from '../../apps/mobile/e2e/core.mjs';
import { createGateway } from './no-paid-gateway.mjs';
import { authorizationIdentity, browserLogin, browserOrigin, loginCredentials } from '../../apps/mobile/e2e/browser-handoff.mjs';
import { validateFirefoxRecipe } from '../../apps/mobile/e2e/firefox-handoff.mjs';
import { CONSENT_MFA_VERIFIED, fixtureMfaCode, mfaStage, totp, validateAuthorizationTraffic } from '../../apps/mobile/e2e/mfa.mjs';
import { admitApplication, FixtureUnavailable, ownerControl, SEARCH_KINDS, validateBuildReceipt, validateCoreFixture, verifiedFile } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { delta, discard, noNotePostRetried, prepareScenario, readOnlyTraffic, scenarios as datedScenarios, signedOutResumeTraffic, verifySavedNote } from '../../apps/mobile/e2e/journeys.mjs';
import { backgroundAndResume, click, find, input, nativeAction, read, selector, visible } from '../../apps/mobile/e2e/native-ui.mjs';
import { collect, harnessFingerprint, inventory as datedInventory, receiptInventory } from '../../apps/mobile/e2e/suite.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { inspectLocalPlan, prepareLocalPlan } from '../../apps/mobile/e2e/local-run.mjs';
import { configuredSessionDeleteAdmission, MAX_SESSION_ADMISSION_EVENTS, proveCurrentSessionDeletion } from '../../apps/mobile/e2e/session-admission.mjs';
import { browserStep } from '../../apps/mobile/e2e/browser-progress.mjs';
import { appiumSessionEvent, authenticationGate, configureNativeDriver, needsFailedCallRecovery, recoverFailedCall } from '../../apps/mobile/e2e/run-state.mjs';

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
  return { context: { driver, platform, fixture: { appId, principalLabel: 'unit-principal', workspaceLabel: 'unit-workspace',
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
    getContexts: async () => ['NATIVE_APP', 'WEBVIEW_browser'], getUrl: async () => url(),
    getWindowHandles: async () => ['browser-window'], switchToWindow: async () => {},
    waitUntil: async (callback) => assert.ok(await callback(), 'UNIT_WAIT_UNSATISFIED'),
    $$: async (query) => {
      if (native) {
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
      if (['#company-slug', '#email', '#password'].includes(query) && stage === 'login') return Array.from({ length: query === '#password' && duplicatePassword ? 2 : 1 }, () => element(query));
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
  return { context: { driver, platform, fixture: { principalLabel: 'Unit Person', workspaceLabel: 'Unit Workspace',
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
  return { context: { driver, platform, fixture: { appId }, record: (event) => records.push(event) }, clicks, records };
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
  return { context: { driver, platform, fixture: { matter: { identityLabel: 'UNIT-MATTER' } }, noteText: body }, savedId, queries };
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
  const event = { hearingId: 'unit-hearing', day: '2026-10-25', dayLabel: '25 Oct 2026', title: 'Unit recorded hearing', metaLabel: 'Unit hearing value',
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
        `event-${wrongEventId ? 'another-hearing' : event.hearingId}`] : ['matter-code'])];
      const id = ids.find((id) => query === selector('android', 'id', id));
      const dateInput = page === 'calendar' && query === selector('android', 'label', 'Agenda date, YYYY-MM-DD');
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
          if (id === `event-${event.hearingId}`) page = 'matter';
          if (text) throw new Error('CALENDAR_TEXT_LEAF_IS_NOT_AN_ACTION_CONTROL');
        } }];
    },
  };
  return { context: { driver, platform: 'android', fixture: { calendar: event, gatewayRunId: 'unit-calendar', gatewayUrl: await listen(server) } },
    requests, clicks, waits };
}

test('N10/N11 use actual date/reload IDs and retain exact event/source values plus invalid-date zero-read boundary (unit double)', async (t) => {
  const positive = await calendarDriver(t);
  await datedScenarios.find(({ id }) => id === 'NATIVE-10').run(positive.context);
  assert.deepEqual(positive.clicks, ['tab-calendar', 'calendar-go-date', 'reload', 'event-unit-hearing']);
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
  await datedScenarios.find(({ id }) => id === 'NATIVE-20').run({ driver, fixture, platform: 'android', record: (event) => records.push(event) });
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
    calendar: { matter, day: '2026-10-25', dayLabel: '25 Oct 2026', title: 'Synthetic hearing', metaLabel: 'hearing', nextHearingLabel: '25 Oct 2026' },
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

function firefoxRecipe(t, { consent = false, androidBack = false, prepare = [], afterConnect = [] } = {}) {
  const locators = Object.fromEntries(['urlOpen', 'urlValue', 'urlClose', 'companySlug', 'email', 'password', 'submit', 'principal', 'emailFact', 'workspace', 'connect', 'signInLink']
    .map((key) => [key, { kind: 'id', value: `unit-${key}` }]));
  locators.appOpen = { kind: 'id', value: 'native-app-open' };
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
  fixture.buildReceipt = ownedFile(t, proof);
  return { fixture, proof, hash: binary.sha256 };
}
test('standalone build receipts bind platform, source, artifact hash, origins and Android CA without loosening base fences', (t) => {
  for (const platform of ['android', 'ios']) {
    const { fixture, hash } = acceptanceReceipt(t, platform);
    validateBuildReceipt(fixture, platform, hash);
    assert.throws(() => validateBuildReceipt({ ...fixture, buildReceipt: undefined }, platform, hash));
    assert.throws(() => validateBuildReceipt(fixture, platform, '0'.repeat(64)), /HASH_MISMATCH/);
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
test('dated documentation retains all forty acceptance groups and all 23 executable cases without a passed claim', () => {
  const doc = readFileSync(new URL('../../docs/mobile/ANDROID_CORE_INVENTORY_2026-10-25.md', import.meta.url), 'utf8');
  assert.deepEqual([...doc.matchAll(/^\| (MOB-\d{2}) \|/gm)].map((match) => match[1]), Array.from({ length: 40 }, (_, index) => `MOB-${String(index + 1).padStart(2, '0')}`));
  assert.deepEqual([...doc.matchAll(/^\| (NATIVE-\d{2}) \|/gm)].map((match) => match[1]), EXPECTED_DATED);
  assert.ok(doc.includes('Native acceptance: **Incomplete**.'));
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
  let clock = 0, verifiedAt = 0, grantAt = 0, promptAt = 0, noticeCleared = false, promptCleared = false, lastLookup, promptIndex = 0;
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
      if (options.verifiedNoticeDelayMs === undefined && options.appOpenDelayMs === undefined && options.promptDelaysMs === undefined) {
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
        : key === 'urlOpen' ? stage !== 'app' && stage !== 'complete' && !editing
        : ['urlValue', 'urlClose'].includes(key) ? editing
        : key === 'signInLink' ? stage === 'landing' && !editing
        : ['companySlug', 'email', 'password', 'submit'].includes(key) ? stage === 'login' && !editing
        : ['principal', 'emailFact', 'workspace', 'connect'].includes(key) ? stage === 'connect' && !editing
        : ['mfaCode', 'mfaSubmit'].includes(key) ? stage === 'consent-mfa' && !editing
          && (key !== 'mfaSubmit' || !options.submitHiddenUntilCode || consentCodeEntered)
        : key === 'mfaVerified' ? verified && stage === 'connect' && !editing && !noticeCleared
          && clock - verifiedAt >= (options.verifiedNoticeDelayMs ?? 0)
        : key === 'appOpen' ? stage === 'grant' && !editing && !options.appOpenMissing && clock - grantAt >= (options.appOpenDelayMs ?? 0)
        : key && key.startsWith('prompt-') ? stage === 'prompt' && key === `prompt-${promptIndex}` && !promptCleared
          && clock - promptAt >= (options.promptDelaysMs?.[promptIndex] ?? 0)
        : key && key.startsWith('prepare-') ? stage === 'landing' : false;
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
          if (key === 'sign-in') stage = 'landing';
          if (key === 'urlOpen') { editing = true; backCount = 0; }
          if (key === 'urlClose') editing = false;
          if (key === 'signInLink') stage = 'login';
          if (key === 'submit') stage = 'connect';
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
  return { context: { driver, fixture, platform: 'android', record: (row) => records.push(row) }, writes, clicks, records, swipes, waits, refreshes,
    elapsed: () => clock };
}
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
    updateSettings: async (settings) => { calls.push('update'); assert.deepEqual(settings, { disableIdLocatorAutocompletion: true }); enabled = true; },
    getSettings: async () => { calls.push('read'); return { disableIdLocatorAutocompletion: enabled, privateUnrelatedSetting: 'unit-secret' }; },
    $$: async (query) => { calls.push('lookup'); assert.equal(query, 'id=native-mfa-code'); return enabled ? [control] : []; },
  };
  await configureNativeDriver(driver, 'android', (event) => records.push(event));
  assert.equal(await visible(driver, selector('android', 'id', 'native-mfa-code')), control);
  assert.deepEqual(calls, ['update', 'read', 'lookup']);
  assert.deepEqual(records, [{ type: 'native_driver_settings', disableIdLocatorAutocompletion: true }]);
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
    assert.deepEqual(records, [{ type: 'native_driver_settings', disableIdLocatorAutocompletion: value === false ? false : null }]);
  }
  const noAndroidCalls = new Proxy({}, { get: () => { throw new Error('NO_ANDROID_SETTINGS_ON_IOS'); } });
  await configureNativeDriver(noAndroidCalls, 'ios', () => { throw new Error('NO_FAKE_IOS_SETTINGS_PROOF'); });
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
    matter, taskId: fixture.today.id, draftId: fixture.work.draft.id, hearingId: 'unit-hearing', calendarDate: fixture.calendar.day,
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
