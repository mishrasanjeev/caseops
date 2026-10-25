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
import { delta, prepareScenario, readOnlyTraffic, scenarios as datedScenarios, signedOutResumeTraffic } from '../../apps/mobile/e2e/journeys.mjs';
import { backgroundAndResume, find, selector, visible } from '../../apps/mobile/e2e/native-ui.mjs';
import { collect, harnessFingerprint, inventory as datedInventory, receiptInventory } from '../../apps/mobile/e2e/suite.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { inspectLocalPlan, prepareLocalPlan } from '../../apps/mobile/e2e/local-run.mjs';

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
  noConsentChallenge = false, verifyRefused = false } = {}) {
  let stage = 'app', native = true, verified = false;
  const writes = [], clicks = [], records = [];
  const url = () => {
    if (externalOrigin) return authUrl('https://example.com');
    const value = new URL(authUrl('https://127.0.0.1:3443'));
    value.searchParams.set('platform', platform);
    if (stage === 'connect' && changedHandoff || verified && changedAfterMfa) value.searchParams.set('state', 'c'.repeat(64));
    return ['login', 'mfa'].includes(stage) ? `${value.origin}/sign-in?${new URLSearchParams({ next: value.pathname + value.search })}` : value.href;
  };
  const element = (key, text = '') => ({
    isDisplayed: async () => true, isEnabled: async () => true, getText: async () => text,
    setValue: async (value) => { writes.push([key, value]); },
    click: async () => { clicks.push(key); if (key === 'sign-in') stage = 'landing'; if (key === 'link') stage = 'login';
      if (key === 'submit') stage = mfa ? 'mfa' : 'connect'; if (key === 'mfa-submit') stage = 'connect';
      if (key === 'connect') stage = consent && !verified ? noConsentChallenge ? 'connect' : 'consent-mfa' : 'complete';
      if (key === 'consent-verify' && !verifyRefused) { verified = true; stage = autoConnect ? 'complete' : 'connect'; } },
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
      return [];
    },
  };
  return { context: { driver, platform, fixture: { principalLabel: 'Unit Person', workspaceLabel: 'Unit Workspace',
    auth: { mode: 'web-context', webOrigin: 'https://127.0.0.1:3443', companySlug: 'unit', emailEnv: 'CASEOPS_MOBILE_UNIT_EMAIL', passwordEnv: 'CASEOPS_MOBILE_UNIT_PASSWORD' } }, record: (row) => records.push(row) },
  writes, clicks, records, isNative: () => native };
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

function firefoxRecipe(t, { consent = false, androidBack = false, prepare = [] } = {}) {
  const locators = Object.fromEntries(['urlOpen', 'urlValue', 'urlClose', 'companySlug', 'email', 'password', 'submit', 'principal', 'emailFact', 'workspace', 'connect', 'signInLink']
    .map((key) => [key, { kind: 'id', value: `unit-${key}` }]));
  if (consent) Object.assign(locators, { mfaCode: { kind: 'id', value: 'native-mfa-code' }, mfaSubmit: { kind: 'buttonText', value: 'Verify code' },
    mfaVerified: { kind: 'text', value: CONSENT_MFA_VERIFIED } });
  const urlCloseMode = androidBack ? 'android-back' : 'locator';
  const evidence = ownedFile(t, { kind: 'observed-native-firefox-locators', packageName: 'org.mozilla.firefox', version: '158.0.2', locators, urlCloseMode, prepare });
  return { ...(consent ? { mfaRequired: true, mfaStage: 'consent', totpSecretEnv: 'CASEOPS_MOBILE_UNIT_TOTP' } : {}),
    firefoxUi: { status: 'complete', packageName: 'org.mozilla.firefox', version: '158.0.2', signerSha256: 'A78B62A5165B4494B2FEAD9E76A280D22D937FEE6251AECE599446B2EA319B04',
    caTrustedThroughSettings: true, locatorEvidencePath: evidence.path, locatorEvidenceSha256: evidence.sha256, locators, urlCloseMode, prepare } };
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
  assert.ok(doc.includes('Native acceptance: **Not run**.'));
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
    assert.deepEqual(fake.clicks, ['sign-in', 'link', 'submit', 'connect', 'consent-verify', 'connect']);
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
  let stage = 'app', editing = false, verified = false, backCount = 0;
  const writes = [], clicks = [], records = [];
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
    waitUntil: async (callback) => assert.ok(await callback(), 'UNIT_WAIT_UNSATISFIED'),
    $$: async (query) => {
      const preparationIndex = auth.firefoxUi.prepare.findIndex((locator) => query === selector('android', locator.kind, locator.value));
      const key = query === 'id=sign-in' ? 'sign-in' : query === 'id=account-open' ? 'account-open'
        : Object.keys(values).find((name) => query === selector('android', values[name].kind, values[name].value))
          || (preparationIndex >= 0 ? `prepare-${preparationIndex}` : undefined);
      const shown = key === 'sign-in' ? stage === 'app' : key === 'account-open' ? stage === 'complete'
        : key === 'urlOpen' ? stage !== 'app' && stage !== 'complete' && !editing
        : ['urlValue', 'urlClose'].includes(key) ? editing
        : key === 'signInLink' ? stage === 'landing' && !editing
        : ['companySlug', 'email', 'password', 'submit'].includes(key) ? stage === 'login' && !editing
        : ['principal', 'emailFact', 'workspace', 'connect'].includes(key) ? stage === 'connect' && !editing
        : ['mfaCode', 'mfaSubmit'].includes(key) ? stage === 'consent-mfa' && !editing
        : key === 'mfaVerified' ? verified && stage === 'connect' && !editing
        : key && key.startsWith('prepare-') ? stage === 'landing' : false;
      if (!shown) return [];
      return [{ isDisplayed: async () => true,
        setValue: async (value) => { writes.push([key, value]); },
        getText: async () => {
          if (key === 'urlValue') {
            const target = new URL(authUrl(foreign ? 'https://example.com' : fixture.auth.webOrigin));
            if (verified && options.changedAfterMfa) target.searchParams.set('state', 'c'.repeat(64));
            return stage === 'login' ? `${target.origin}/sign-in?${new URLSearchParams({ next: target.pathname + target.search })}` : target.href;
          }
          return { principal: verified && options.wrongAfterMfa ? 'Wrong' : fixture.principalLabel, emailFact: 'unit@example.invalid',
            workspace: 'Unit Workspace / unit', connect: 'Connect app', mfaSubmit: 'Verify code', mfaVerified: CONSENT_MFA_VERIFIED }[key] || '';
        },
        click: async () => {
          clicks.push(key);
          if (key === 'sign-in') stage = 'landing';
          if (key === 'urlOpen') { editing = true; backCount = 0; }
          if (key === 'urlClose') editing = false;
          if (key === 'signInLink') stage = 'login';
          if (key === 'submit') stage = 'connect';
          if (key === 'connect') stage = options.consent && !verified ? options.noConsentChallenge ? 'connect' : 'consent-mfa' : 'complete';
          if (key === 'mfaSubmit' && !options.verifyRefused) { verified = true; stage = options.autoConnect ? 'complete' : 'connect'; }
        } }];
    },
  };
  return { context: { driver, fixture, platform: 'android', record: (row) => records.push(row) }, writes, clicks, records };
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
