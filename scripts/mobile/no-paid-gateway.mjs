import assert from 'node:assert/strict';
import http from 'node:http';
import https from 'node:https';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { localUrl, MARKER, MARKER_HEADER } from '../../apps/mobile/e2e/support.mjs';

// Admission is exact method + pathname, not a blanket GET or provider prefix.
export function createGateway({ upstream, routes, runId }) {
  const target = localUrl(upstream);
  assert.equal(target.pathname, '/', 'UPSTREAM_ORIGIN_REQUIRED');
  assert.ok(Array.isArray(routes) && routes.length > 0 && routes.length <= 100, 'EXACT_ROUTE_INVENTORY_REQUIRED');
  for (const route of routes) assert.match(route, /^(GET|POST|PATCH|PUT|DELETE) \/api\/[a-zA-Z0-9_./:-]+$/, 'INVALID_ADMITTED_ROUTE');
  assert.match(runId, /^[a-zA-Z0-9_-]{1,80}$/, 'SAFE_RUN_ID_REQUIRED');
  const allowed = new Set(routes);
  const state = { runId, accepted: 0, markerRejected: 0, routeRejected: 0, lastSequence: 0, overflow: false, requests: [] };
  return http.createServer((request, response) => {
    const reply = (code, body) => {
      response.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' });
      response.end(JSON.stringify(body));
    };
    if (request.headers[MARKER_HEADER.toLowerCase()] !== MARKER) {
      state.markerRejected++;
      return reply(403, { code: 'AUTOMATED_MARKER_REQUIRED' });
    }
    // HTTP origin-form is the only accepted request target. In particular,
    // an absolute or protocol-relative target cannot select another authority.
    if (typeof request.url !== 'string' || !request.url.startsWith('/')
      || request.url.startsWith('//') || /[\\\x00-\x20\x7f]/.test(request.url)) {
      state.routeRejected++;
      return reply(403, { code: 'ROUTE_NOT_ADMITTED' });
    }
    let url;
    try { url = new URL(request.url, 'http://127.0.0.1'); }
    catch {
      state.routeRejected++;
      return reply(403, { code: 'ROUTE_NOT_ADMITTED' });
    }
    if (url.pathname === '/__caseops_e2e/status' && request.method === 'GET') return reply(200, state);
    const route = `${request.method} ${url.pathname}`;
    if (!allowed.has(route)) {
      state.routeRejected++;
      return reply(403, { code: 'ROUTE_NOT_ADMITTED' });
    }
    if (state.requests.length >= 500) {
      state.overflow = true;
      return reply(503, { code: 'REQUEST_EVIDENCE_BOUND' });
    }
    const record = { sequence: ++state.lastSequence, method: request.method, route: url.pathname, status: null };
    state.requests.push(record);
    state.accepted++;
    const headers = { ...request.headers, host: target.host, [MARKER_HEADER]: MARKER };
    delete headers.connection;
    const transport = target.protocol === 'https:' ? https : http;
    const upstreamRequest = transport.request({
      protocol: target.protocol, hostname: target.hostname === '[::1]' ? '::1' : target.hostname, port: target.port,
      path: `${url.pathname}${url.search}`, method: request.method, headers, timeout: 15000,
      minVersion: 'TLSv1.2', rejectUnauthorized: true, agent: false,
    }, (upstreamResponse) => {
      record.status = upstreamResponse.statusCode;
      // Do not follow redirects or let a test client escape the marker fence.
      if (upstreamResponse.statusCode >= 300 && upstreamResponse.statusCode < 400) {
        upstreamResponse.resume();
        return reply(502, { code: 'UPSTREAM_REDIRECT_REQUIRES_REVIEW' });
      }
      response.writeHead(upstreamResponse.statusCode, { ...upstreamResponse.headers, 'cache-control': 'no-store' });
      upstreamResponse.pipe(response);
    });
    upstreamRequest.on('timeout', () => upstreamRequest.destroy());
    upstreamRequest.on('error', () => {
      record.status = 502;
      if (!response.headersSent) reply(502, { code: 'UPSTREAM_TRANSPORT_FAILED' });
      else response.destroy();
    });
    request.on('aborted', () => upstreamRequest.destroy());
    response.on('close', () => { if (!response.writableFinished) upstreamRequest.destroy(); });
    let received = 0;
    request.on('data', (chunk) => {
      received += chunk.length;
      if (received > 1048576) {
        upstreamRequest.destroy();
        request.destroy();
      }
    });
    request.pipe(upstreamRequest);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const config = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  assert.ok(Number.isInteger(config.port) && config.port >= 1024 && config.port <= 65535, 'EXPLICIT_UNPRIVILEGED_PORT_REQUIRED');
  const server = createGateway(config);
  server.requestTimeout = 20000;
  server.headersTimeout = 10000;
  server.listen(config.port, '127.0.0.1', () => console.log(JSON.stringify({ ready: true, port: config.port, runId: config.runId })));
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => server.close());
}
