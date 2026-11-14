import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { closeSync, constants, fsyncSync, fstatSync, lstatSync, mkdirSync, openSync, readSync,
  realpathSync, writeFileSync } from 'node:fs';
import https from 'node:https';
import path from 'node:path';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const exactRoute = /^(GET|POST|PATCH|DELETE|OPTIONS) \/api\/[a-zA-Z0-9_./-]{1,390}$/;
const calendarId = '[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}';
const calendarRead = new RegExp(`^GET /api/ip/dockets/${calendarId}/deadline-workspace$`);
const calendarWrite = new RegExp(`^POST /api/ip/(?:dockets/${calendarId}/(?:deadlines|access/(?:preview|apply))|deadlines/${calendarId}/confirm)$`);
const bound = 131072;
// Leave clock skew room below the gateway's independent 10-second ceiling.
const permitLifetimeMs = 9500;
const keyFields = ['dev', 'ino', 'uid', 'gid', 'mode'];
const fileFields = [...keyFields, 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const equal = (a, b, fields) => fields.every(field => field === 'dev' && process.platform === 'win32' && b.dev === 0n || a[field] === b[field]);

function readRoutes(file) {
  const fd = openSync(file, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  try {
    const opened = fstatSync(fd, { bigint: true }), named = lstatSync(file, { bigint: true });
    assert.ok(opened.isFile() && named.isFile() && !named.isSymbolicLink() && opened.nlink === 1n
      && (process.getuid === undefined || opened.uid === BigInt(process.getuid()) && (opened.mode & 0o077n) === 0n)
      && opened.size > 0n && opened.size <= BigInt(bound) && equal(opened, named, fileFields), 'PRODUCER_ROUTE_FILE_IDENTITY');
    const bytes = Buffer.alloc(Number(opened.size) + 1);
    let length = 0;
    while (length < bytes.length) {
      const count = readSync(fd, bytes, length, bytes.length - length, null);
      if (!count) break;
      length += count;
    }
    assert.ok(length === Number(opened.size) && equal(opened, fstatSync(fd, { bigint: true }), fileFields)
      && equal(named, lstatSync(file, { bigint: true }), fileFields), 'PRODUCER_ROUTE_FILE_CHANGED');
    return { bytes: bytes.subarray(0, length), named };
  } finally { closeSync(fd); }
}

// The canonical route file is read only. A dependent request gets one short-lived
// permit bound to its actual path and normal Bearer token. The gateway consumes
// it before forwarding and never adds the route to its general allowlist.
export function openProducerRouteFile({ cache, baseSha256, epoch, persist, requiredRoutes = [], now = Date.now }) {
  assert.ok(path.isAbsolute(cache) && realpathSync(cache) === cache, 'PRODUCER_GATEWAY_CACHE_REQUIRED');
  const identity = lstatSync(cache, { bigint: true });
  const checkDirectory = (name, expected) => {
    const current = lstatSync(name, { bigint: true });
    assert.ok(realpathSync(name) === name && current.isDirectory() && !current.isSymbolicLink()
      && (!expected || equal(expected, current, keyFields))
      && (process.getuid === undefined || current.uid === BigInt(process.getuid()) && (current.mode & 0o077n) === 0n), 'PRODUCER_GATEWAY_CACHE_CHANGED');
    return current;
  };
  checkDirectory(cache, identity);
  const file = path.join(cache, 'gateway-routes.json');
  const original = readRoutes(file);
  assert.equal(hash(original.bytes), baseSha256, 'PRODUCER_BASE_ROUTE_HASH_MISMATCH');
  const content = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(original.bytes));
  assert.deepEqual(Object.keys(content), ['routes']);
  const routes = new Set(content.routes);
  assert.ok(Array.isArray(content.routes) && content.routes.length > 0 && routes.size === content.routes.length
    && routes.size <= 500 && [...routes].every(r => typeof r === 'string' && exactRoute.test(r)), 'PRODUCER_EXACT_BASE_ROUTES_REQUIRED');
  assert.ok(requiredRoutes.every(route => routes.has(route)), 'PRODUCER_FIXED_ROUTE_INVENTORY_INCOMPLETE');
  assert.match(epoch, /^[a-z0-9-]{8,160}$/);
  const permitRoot = path.join(cache, 'producer-permits-' + hash(epoch));
  mkdirSync(permitRoot, { mode: 0o700 });
  const permitRootIdentity = checkDirectory(permitRoot);
  let busy = false, poisoned = false, closed = false, issued = 0;
  const consumed = [];
  const verify = () => {
    checkDirectory(cache, identity); checkDirectory(permitRoot, permitRootIdentity);
    const current = readRoutes(file);
    assert.ok(equal(original.named, current.named, fileFields) && original.bytes.equals(current.bytes), 'PRODUCER_ROUTE_WRITER_CONFLICT');
  };
  return {
    async dispatch(route, provenance, authorization, deadline, send, binding) {
      assert.ok(!busy && !poisoned && !closed && typeof send === 'function', 'PRODUCER_ROUTE_SCOPE_CLOSED');
      assert.match(route, exactRoute);
      busy = true;
      try {
        verify();
        const reviewedRead = calendarRead.test(route), reviewedWrite = calendarWrite.test(route);
        let bodySha256;
        if (reviewedRead || reviewedWrite) {
          assert.ok(!routes.has(route) && provenance?.calendarExact === true && binding?.queryPresent === false,
            'PRODUCER_CALENDAR_EXACT_ADMISSION_REQUIRED');
          const bytes = binding.bodyBytes;
          assert.ok(reviewedWrite ? Buffer.isBuffer(bytes) && bytes.length > 0 && bytes.length <= 1048576 : bytes === undefined,
            'PRODUCER_CALENDAR_BODY_REQUIRED');
          if (reviewedWrite) bodySha256 = hash(bytes);
        }
        if (routes.has(route)) return await send();
        assert.match(provenance?.requestDigest || '', /^[a-f0-9]{64}$/, 'PRODUCER_DEPENDENT_ROUTE_NOT_ADMITTED');
        assert.ok(typeof authorization === 'string' && authorization.startsWith('Bearer ') && !authorization.startsWith('Bearer cnat_')
          && authorization.length <= 16384, 'PRODUCER_NORMAL_BEARER_REQUIRED');
        const current = now(), expires = Math.min(deadline, current + permitLifetimeMs);
        assert.ok(Number.isSafeInteger(expires) && expires > current && ++issued <= 96, 'PRODUCER_PERMIT_BOUND');
        const proof = randomBytes(32).toString('hex'), proofSha256 = hash(proof);
        const permit = path.join(permitRoot, proofSha256 + '.json');
        const bytes = Buffer.from(JSON.stringify({ epoch, route, bearerSha256: hash(authorization), expires,
          creatorAckSha256: provenance.requestDigest, ...(bodySha256 === undefined ? {} : { bodySha256 }) }) + '\n');
        const fd = openSync(permit, 'wx', 0o600);
        try { writeFileSync(fd, bytes); fsyncSync(fd); } finally { closeSync(fd); }
        verify();
        persist({ type: 'producer_exact_route_permit', creatorAckSha256: provenance.requestDigest, baseSha256, permitSha256: hash(bytes), routeSha256: hash(route) });
        const result = await send(proof);
        assert.equal(result.permitReceipt, hash(bytes), 'PRODUCER_PERMIT_CONSUMPTION_NOT_ACKNOWLEDGED');
        consumed.push(result.permitReceipt);
        verify();
        persist({ type: 'producer_exact_route_consumed', permitSha256: hash(bytes) });
        return result;
      } catch (error) { poisoned = true; throw error; }
      finally { busy = false; }
    },
    verifyRestored() { assert.equal(busy, false); verify(); },
    seal() { this.verifyRestored(); closed = true; },
    consumed: () => [...consumed],
  };
}

function status(receipt, ca, remaining) {
  const origin = new URL(receipt.gatewayUrl);
  assert.ok(origin.origin === receipt.gatewayUrl && origin.protocol === 'https:' && origin.hostname === '127.0.0.1'
    && Number(origin.port) >= 1024, 'PRODUCER_GATEWAY_LOOPBACK_REQUIRED');
  const timeout = Math.min(5000, Math.floor(remaining()));
  assert.ok(timeout > 0, 'PRODUCER_ROUTE_DEADLINE');
  return new Promise((resolve, reject) => {
    const request = https.request(new URL('/__caseops_e2e/status', origin), { ca, rejectUnauthorized: true, agent: false,
      headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' } }, response => {
      let total = 0; const chunks = [];
      if (response.statusCode !== 200) return request.destroy(new Error('PRODUCER_GATEWAY_STATUS_REFUSED'));
      response.on('error', reject);
      response.on('aborted', () => reject(new Error('PRODUCER_GATEWAY_STATUS_INCOMPLETE')));
      response.on('data', chunk => {
        total += chunk.length;
        if (total > 1048576) request.destroy(new Error('PRODUCER_GATEWAY_STATUS_BOUND')); else chunks.push(chunk);
      });
      response.on('end', () => {
        try { resolve(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)))); }
        catch { reject(new Error('PRODUCER_GATEWAY_STATUS_MALFORMED')); }
      });
    });
    const timer = setTimeout(() => request.destroy(new Error('PRODUCER_GATEWAY_STATUS_DEADLINE')), timeout);
    request.on('error', reject); request.on('close', () => clearTimeout(timer)); request.end();
  });
}

// Producer activation must match the live gateway mount, not a nearby path
// chosen from the CLI. Keep Docker output projections free of environment data.
export async function admitProducerRouteFile({ receipt, docker, publicCa, baseSha256, root, remaining, persist, requiredRoutes, command = execFileSync }) {
  const cache = path.dirname(path.dirname(receipt.publicCA));
  assert.ok(cache !== root && !cache.startsWith(root + path.sep) && publicCa.path === path.join(cache, 'tls/ca.crt'), 'PRODUCER_GATEWAY_ROOT_REFUSED');
  assert.equal(receipt.productionAccessed, false);
  assert.equal(receipt.noPaidProviderKeysInAPIOrWeb, true);
  assert.equal(receipt.apiWebPostgresScannerNetworkInternal, true);
  assert.equal(receipt.tlsProof?.strictDefaultTLS, true);
  assert.equal(receipt.tlsProof?.verificationDisabled, false);
  assert.match(receipt.gatewayImplementationSha256, /^[a-f0-9]{64}$/);
  assert.equal(receipt.fixtureSourceHashes['scripts/mobile/local-gateway.py'], receipt.gatewayImplementationSha256);
  verifiedFile(path.join(root, 'scripts/mobile/local-gateway.py'), receipt.gatewayImplementationSha256, bound);
  verifiedFile(path.join(root, 'compose.mobile-local.yml'), receipt.composeSha256, bound);
  assert.match(receipt.project, /^caseops-mobile-[a-z0-9-]+$/);
  const rows = receipt.containers.filter(row => row.name === '/' + receipt.project + '-gateway-1');
  assert.equal(rows.length, 1); const [gateway] = rows;
  assert.match(gateway.id, /^[a-f0-9]{64}$/);
  assert.equal(gateway.project, receipt.project);
  verifiedFile(docker.path, docker.sha256, 134217728);
  const assertContainer = () => {
    const timeout = Math.min(5000, Math.floor(remaining()));
    assert.ok(timeout > 0, 'PRODUCER_ROUTE_DEADLINE');
    const format = '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},"running":{{json .State.Running}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"mounts":{{json .Mounts}}}';
    const current = JSON.parse(command(docker.path, ['inspect', '--format', format, gateway.id],
      { encoding: 'utf8', timeout, maxBuffer: 65536, stdio: ['ignore', 'pipe', 'pipe'] }));
    for (const k of ['id', 'name', 'image', 'project']) assert.equal(current[k], gateway[k], 'PRODUCER_GATEWAY_CONTAINER_CHANGED');
    assert.equal(current.running, true); assert.equal(current.service, 'gateway');
    for (const [source, destination, rw] of [[cache, '/fixture-state', true], [path.join(root, 'scripts/mobile'), '/mobile-fixture', false]]) {
      const matched = current.mounts.filter(item => item.Destination === destination);
      assert.ok(matched.length === 1 && matched[0].Type === 'bind' && matched[0].Source === source && matched[0].RW === rw, 'PRODUCER_GATEWAY_MOUNT_CHANGED');
    }
  };
  const ca = verifiedFile(publicCa.path, publicCa.sha256, 65536);
  try {
    assertContainer();
    const initial = await status(receipt, ca, remaining);
    const baseline = gatewayBaseline(initial, receipt);
    assert.equal(initial.v1ControlsEnabled, false, 'PRODUCER_REQUIRES_SEPARATE_GATEWAY_EPOCH');
    const file = openProducerRouteFile({ cache, baseSha256, epoch: receipt.gatewayRunId, persist, requiredRoutes });
    return {
      dispatch: file.dispatch,
      verifyRestored: file.verifyRestored,
      async finish() {
        file.seal();
        assertContainer();
        const current = validateTraffic(await status(receipt, ca, remaining), baseline);
        assert.equal(current.v1ControlsEnabled, false, 'PRODUCER_GATEWAY_CONTROL_STATE_CHANGED');
        assert.deepEqual(current.requests.slice(baseline.lastSequence).filter(row => row.producerPermitSha256 !== undefined)
          .map(row => row.producerPermitSha256), file.consumed(), 'PRODUCER_GATEWAY_PERMIT_LEDGER_MISMATCH');
        persist({ type: 'producer_route_epoch_closed', baseSha256, requests: current.lastSequence - baseline.lastSequence });
      },
      clear() { ca.fill(0); },
    };
  } catch (error) { ca.fill(0); throw error; }
}
