// Real WebdriverIO transport regression. Requires the separately pinned existing
// Appium tooling, never an SDK, device, browser, provider or live Appium server.
import assert from 'node:assert/strict';
import http from 'node:http';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { MARKER, MARKER_HEADER } from '../../../apps/mobile/e2e/support.mjs';
import { NATIVE_WEBDRIVER_SITES, nativeConstructorInventory, nativeConstructorOptions } from './native-webdriver-constructor.mjs';

const tooling = process.env.CASEOPS_MOBILE_TOOLING_HOME;
assert.ok(tooling && path.isAbsolute(tooling), 'EXPLICIT_PINNED_APPIUM_TOOLING_REQUIRED');
const requireTooling = createRequire(path.join(tooling, 'package.json'));
assert.equal(JSON.parse(readFileSync(path.join(tooling, 'node_modules/webdriverio/package.json'), 'utf8')).version, '10.1.0', 'ACTUAL_LOCKED_WEBDRIVERIO_REQUIRED');
const { remote } = requireTooling('webdriverio');
nativeConstructorInventory();

async function peer(t, mode) {
  const requests = [], sockets = new Set(), errors = [];
  const server = http.createServer((request, response) => {
    const chunks = []; let bytes = 0;
    request.on('data', chunk => { bytes += chunk.length; if (bytes > 65536) request.destroy(); else chunks.push(chunk); });
    request.on('error', () => {});
    request.on('end', () => {
      try {
        const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null;
        requests.push({ method: request.method, route: request.url, marker: request.headers[MARKER_HEADER.toLowerCase()],
          markerOccurrences: request.rawHeaders.filter((value, index) => index % 2 === 0 && value.toLowerCase() === MARKER_HEADER.toLowerCase()).length, body });
        if (request.method === 'POST' && request.url === '/session' && mode === 'lost-ack') { request.socket.destroy(); return; }
        if (request.method === 'POST' && request.url === '/session' && mode === 'http-error') {
          response.writeHead(500, { 'Content-Type': 'application/json' });
          response.end(JSON.stringify({ value: { error: 'session not created', message: 'Controlled owned-peer failure', stacktrace: '' } })); return;
        }
        response.writeHead(200, { 'Content-Type': 'application/json' });
        if (request.method === 'POST' && request.url === '/session') {
          response.end(JSON.stringify({ value: { sessionId: 'owned-transport-session', capabilities: body.capabilities.alwaysMatch } }));
        } else if (request.method === 'GET' && request.url === '/session/owned-transport-session/timeouts') {
          response.end(JSON.stringify({ value: { script: 30000, pageLoad: 300000, implicit: 0 } }));
        } else if (request.method === 'DELETE' && request.url === '/session/owned-transport-session') response.end('{"value":null}');
        else { errors.push('UNEXPECTED_WEBDRIVER_REQUEST'); response.end('{"value":null}'); }
      } catch (error) { errors.push(error); response.destroy(); }
    });
  });
  server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
  const close = async () => {
    const end = performance.now() + 1000;
    const closed = [...sockets].map(socket => new Promise(resolve => socket.once('close', resolve)));
    for (const socket of sockets) socket.destroy();
    if (server.listening) closed.push(new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve())));
    let timer;
    try {
      await Promise.race([Promise.all(closed), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('OWNED_HTTP_PEER_CLOSE_DEADLINE')), Math.max(1, end - performance.now()));
      })]);
    } finally { clearTimeout(timer); }
    assert.ok(performance.now() < end, 'OWNED_HTTP_PEER_CLOSE_DEADLINE');
    assert.equal(server.listening, false); assert.equal(sockets.size, 0);
  };
  // Register ownership before waiting for acknowledgement of the listener.
  t.after(close); t.signal.addEventListener('abort', () => { for (const socket of sockets) socket.destroy(); server.close(); }, { once: true });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const address = server.address(); assert.equal(address.address, '127.0.0.1');
  return { endpoint: `http://127.0.0.1:${address.port}/`, requests, errors };
}

for (const site of NATIVE_WEBDRIVER_SITES) for (const platform of site.platforms) {
  const label = `native WebDriver ${site.family} ${platform}`;
  test(`${label} marks create, read and delete on the received HTTP requests`, { timeout: 10000 }, async t => {
    const p = await peer(t, 'success'), { options } = nativeConstructorOptions(site, platform, p.endpoint);
    let driver; const failures = [];
    try { driver = await remote(options); assert.deepEqual(await driver.getTimeouts(), { script: 30000, pageLoad: 300000, implicit: 0 }); }
    catch (error) { failures.push(error); }
    finally { if (driver) try { await driver.deleteSession(); } catch (error) { failures.push(error); } }
    if (failures.length === 1) throw failures[0];
    if (failures.length > 1) throw new AggregateError(failures, 'OWNED_TRANSPORT_BODY_AND_CLEANUP_FAILED');
    assert.deepEqual(p.errors, []); assert.deepEqual(p.requests.map(({ method, route }) => [method, route]),
      [['POST', '/session'], ['GET', '/session/owned-transport-session/timeouts'], ['DELETE', '/session/owned-transport-session']]);
    for (const request of p.requests) { assert.equal(request.marker, MARKER); assert.equal(request.markerOccurrences, 1); }
    assert.deepEqual(p.requests[0].body.capabilities.alwaysMatch, JSON.parse(JSON.stringify(options.capabilities)));
  });
  for (const mode of ['http-error', 'lost-ack']) test(`${label} marks ${mode} create without replay`, { timeout: 10000 }, async t => {
    const p = await peer(t, mode), { options } = nativeConstructorOptions(site, platform, p.endpoint);
    await assert.rejects(remote(options));
    assert.deepEqual(p.errors, []); assert.equal(p.requests.length, 1);
    assert.deepEqual([p.requests[0].method, p.requests[0].route], ['POST', '/session']);
    assert.equal(p.requests[0].marker, MARKER); assert.equal(p.requests[0].markerOccurrences, 1);
  });
}
