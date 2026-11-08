import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { once } from 'node:events';
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const epoch = 'v1-' + 'a'.repeat(16);
const docket = '01000000-0000-4000-8000-000000000001';
const other = '01000000-0000-4000-8000-000000000002';
const proposal = '01000000-0000-4000-8000-000000000003';
const prefix = '/api/ip/dockets/' + docket;
const writeRoutes = [prefix + '/deadlines', '/api/ip/deadlines/' + proposal + '/confirm',
  prefix + '/access/preview', prefix + '/access/apply'];
const readRoute = prefix + '/deadline-workspace';
const auth = 'Bearer synthetic-calendar-owner';
const marker = 'no-paid-providers';
const permitHeader = 'X-CaseOps-QA-Producer-Permit';
const receiptHeader = 'x-caseops-qa-producer-permit-consumed';
const hash = value => createHash('sha256').update(value).digest('hex');
const body = Buffer.from('{\n  "reason": "Synthetic QA लेख", "preview_token": "private-fixture-preview"\n}\n');

async function fixture(t) {
  const cache = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'calendar-gateway-')));
  t.after(() => rmSync(cache, { recursive: true, force: true }));
  const baseline = Buffer.from('{"routes":["POST /api/matters/"]}\n');
  const routeFile = path.join(cache, 'gateway-routes.json');
  writeFileSync(routeFile, baseline, { mode: 0o600 });
  const permits = path.join(cache, 'producer-permits-' + hash(epoch));
  mkdirSync(permits, { mode: 0o700 });
  const seen = [];
  const upstream = http.createServer(async (request, response) => {
    const parts = [];
    for await (const chunk of request) parts.push(chunk);
    seen.push({ method: request.method, route: request.url, body: Buffer.concat(parts), headers: request.headers });
    response.writeHead(200, { 'Content-Type': 'application/json', [receiptHeader]: 'upstream-spoof' });
    response.end('{}');
  });
  upstream.listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  t.after(() => upstream.close());
  const key = path.join(cache, 'fixture.key'), cert = path.join(cache, 'fixture.crt');
  execFileSync('/usr/bin/openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
    '-keyout', key, '-out', cert, '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'],
  { timeout: 10000, stdio: 'ignore' });
  const gateway = fileURLToPath(new URL('./local-gateway.py', import.meta.url));
  const code = [
    'import runpy,ssl,sys',
    'from http.server import ThreadingHTTPServer',
    'from pathlib import Path',
    'g=runpy.run_path(sys.argv[1]); cls=g["Gateway"]',
    'cls.handler.__globals__["upstream_destination"]=lambda web: ("127.0.0.1",int(sys.argv[5]))',
    'instance=cls(Path(sys.argv[2])); server=ThreadingHTTPServer(("127.0.0.1",0),instance.handler())',
    'context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(sys.argv[3],sys.argv[4])',
    'server.socket=context.wrap_socket(server.socket,server_side=True)',
    'print(server.server_address[1],flush=True)',
    'server.serve_forever()',
  ].join('\n');
  const child = spawn(process.env.CASEOPS_MOBILE_PRODUCER_PYTHON || 'python3',
    ['-I', '-c', code, gateway, cache, cert, key, String(upstream.address().port)],
    { env: { PATH: process.env.PATH, CASEOPS_ENV: 'local', CASEOPS_MOBILE_RUN_ID: epoch }, stdio: ['ignore', 'pipe', 'pipe'] });
  const exited = once(child, 'exit');
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill('SIGTERM');
      await exited;
    }
  });
  const [ready] = await Promise.race([
    once(child.stdout, 'data', { signal: AbortSignal.timeout(5000) }),
    exited.then(([status, signal]) => { throw new Error('Isolated gateway exited before readiness: ' + (signal ?? status)); }),
  ]);
  const port = Number(String(ready).trim()), ca = readFileSync(cert);
  assert.ok(port >= 1024 && port <= 65535);

  const probe = (method, route, { token, payload, bearer = auth, headers = {} } = {}) => new Promise((resolve, reject) => {
    const request = https.request({ hostname: '127.0.0.1', port, path: route, ca, rejectUnauthorized: true, method, agent: false,
      headers: { 'X-CaseOps-Automated-Test': marker, Authorization: bearer, ...(token ? { [permitHeader]: token } : {}),
        ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': String(payload.length) } : {}), ...headers },
    }, response => {
      const parts = [];
      response.on('data', chunk => parts.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, receipt: response.headers[receiptHeader], body: Buffer.concat(parts) }));
      response.on('error', reject);
    });
    request.setTimeout(2000, () => request.destroy(new Error('Gateway probe timed out')));
    request.on('error', reject);
    request.end(payload);
  });
  const issue = (method, route, payload, override = {}) => {
    const token = randomBytes(32).toString('hex');
    const bytes = Buffer.from(JSON.stringify({ epoch, route: method + ' ' + route, bearerSha256: hash(auth),
      expires: Date.now() + 9000, creatorAckSha256: hash('synthetic-creator-ack'),
      ...(payload ? { bodySha256: hash(payload) } : {}), ...override }) + '\n');
    const identity = hash(token);
    writeFileSync(path.join(permits, identity + '.json'), bytes, { mode: 0o600, flag: 'wx' });
    return { token, receipt: hash(bytes), identity };
  };
  const spent = () => readdirSync(permits).filter(name => name.endsWith('.spent')).sort();
  return { cache, routeFile, baseline, seen, probe, issue, spent };
}

test('calendar one-use permit framing and hashes reach the real isolated TLS gateway', async t => {
  const { cache, routeFile, baseline, seen, probe, issue, spent } = await fixture(t);
  const bare = await probe('POST', writeRoutes[0], { payload: body });
  assert.equal(bare.status, 403);
  assert.deepEqual(seen, []);

  const write = issue('POST', writeRoutes[0], body);
  const wrongBody = Buffer.from(body.toString().replace('Synthetic QA', 'Different QA'));
  const negatives = [
    ['POST', writeRoutes[0], { payload: wrongBody }, 403],
    ['POST', writeRoutes[0], { payload: body, bearer: 'Bearer another-owner' }, 403],
    ['POST', writeRoutes[0], { payload: body, bearer: 'Bearer cnat_native' }, 403],
    ['POST', writeRoutes[0], { payload: body, headers: { Cookie: 'session=fixture' } }, 403],
    ['POST', writeRoutes[0].replace(docket, other), { payload: body }, 403],
    ['POST', writeRoutes[0] + '?', { payload: body }, 403],
    ['POST', writeRoutes[0] + '?cursor=opaque', { payload: body }, 403],
    ['POST', writeRoutes[0], { payload: body, headers: { 'Content-Length': '+' + body.length } }, 400],
    ['POST', writeRoutes[0], { payload: body, headers: { 'Content-Length': '1048577' } }, 413],
    ['POST', writeRoutes[0], { payload: body, headers: { 'Transfer-Encoding': 'chunked' } }, 400],
    ['POST', writeRoutes[0], {}, 403],
  ];
  for (const [method, route, options, expected] of negatives) {
    const result = await probe(method, route, { token: write.token, ...options });
    assert.equal(result.status, expected);
    assert.equal(result.receipt, undefined);
  }
  const oldWrite = issue('POST', writeRoutes[0]);
  assert.equal((await probe('POST', writeRoutes[0], { token: oldWrite.token, payload: body })).status, 403);
  const expired = issue('POST', writeRoutes[0], body, { expires: Date.now() - 100 });
  assert.equal((await probe('POST', writeRoutes[0], { token: expired.token, payload: body })).status, 403);
  const wrongRoute = prefix + '/deadlines/override';
  const wrongPermit = issue('POST', wrongRoute, body);
  assert.equal((await probe('POST', wrongRoute, { token: wrongPermit.token, payload: body })).status, 403);
  assert.deepEqual(spent(), []);
  assert.deepEqual(seen, []);

  const receipts = [write];
  const race = await Promise.all([1, 2].map(() => probe('POST', writeRoutes[0], { token: write.token, payload: body })));
  assert.deepEqual(race.map(result => result.status).sort(), [200, 403]);
  assert.equal(race.find(result => result.status === 200).receipt, write.receipt);
  assert.equal(race.find(result => result.status === 403).receipt, undefined);
  for (const route of writeRoutes.slice(1)) {
    const permit = issue('POST', route, body);
    receipts.push(permit);
    const result = await probe('POST', route, { token: permit.token, payload: body });
    assert.equal(result.status, 200);
    assert.equal(result.receipt, permit.receipt);
    assert.equal((await probe('POST', route, { token: permit.token, payload: body })).status, 403);
  }

  const read = issue('GET', readRoute);
  receipts.push(read);
  for (const route of [readRoute + '?', readRoute + '?cursor=opaque']) {
    assert.equal((await probe('GET', route, { token: read.token })).status, 403);
  }
  assert.equal((await probe('GET', readRoute, { token: read.token, payload: body })).status, 403);
  const readWithHash = issue('GET', readRoute, body);
  assert.equal((await probe('GET', readRoute, { token: readWithHash.token })).status, 403);
  const readAck = await probe('GET', readRoute, { token: read.token });
  assert.equal(readAck.status, 200);
  assert.equal(readAck.receipt, read.receipt);

  const oldRoute = '/api/contracts/' + other + '/obligations';
  const legacy = issue('GET', oldRoute);
  const legacyAck = await probe('GET', oldRoute + '?cursor=a%2Bb', { token: legacy.token });
  assert.equal(legacyAck.status, 200);
  assert.equal(legacyAck.receipt, legacy.receipt);
  receipts.push(legacy);
  assert.deepEqual(spent(), receipts.map(item => item.identity + '.spent').sort());
  assert.deepEqual(seen.map(({ route }) => route), [...writeRoutes, readRoute, oldRoute + '?cursor=a%2Bb']);
  assert.deepEqual(seen.map(({ body: bytes }) => bytes), [...writeRoutes.map(() => body), Buffer.alloc(0), Buffer.alloc(0)]);
  for (const request of seen) {
    assert.equal(request.headers[permitHeader.toLowerCase()], undefined);
    assert.equal(request.headers['x-caseops-automated-test'], marker);
  }
  const status = await probe('GET', '/__caseops_e2e/status');
  const observed = JSON.parse(status.body);
  assert.deepEqual(observed.requests.map(row => row.producerPermitSha256), receipts.map(item => item.receipt));
  const journal = readFileSync(path.join(cache, readdirSync(cache).find(name => name.startsWith('gateway-events-'))));
  for (const privateValue of [...receipts.map(item => item.token), auth, 'private-fixture-preview', 'cursor=']) {
    assert.equal(journal.includes(privateValue), false);
    assert.equal(status.body.includes(privateValue), false);
  }
  assert.deepEqual(readFileSync(routeFile), baseline);
});
