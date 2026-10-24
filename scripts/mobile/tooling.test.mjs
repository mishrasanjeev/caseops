import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createHash } from 'node:crypto';
import http from 'node:http';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { binaryHash, byTestId, Journal, localJson, localUrl, MARKER, MARKER_HEADER, reconcileInventory, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { scenarios } from '../../apps/mobile/e2e/core.mjs';
import { createGateway } from './no-paid-gateway.mjs';

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
