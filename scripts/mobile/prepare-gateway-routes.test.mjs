import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { gatewayEvidenceReference, prepareGatewayRoutes, REVIEWED_GATEWAY_IMPLEMENTATION_SHA256 } from './prepare-gateway-routes.mjs';
import { validateSessionDeletePolicy } from '../../apps/mobile/e2e/session-admission.mjs';

const source = fileURLToPath(new URL('./local-gateway.py', import.meta.url));

test('gateway evidence Windows dev-zero portability preserves pre-read identity and both final metadata frames', (t) => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-gateway-portability-')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, 'public.json'); writeFileSync(file, '{"public":true}');
  const original = Object.fromEntries(['openSync', 'closeSync', 'fstatSync', 'lstatSync', 'readSync'].map(key => [key, fs[key]]));
  const platform = Object.getOwnPropertyDescriptor(process, 'platform');
  for (const change of ['zero', 'same', 'nonzero', 'inode', 'owner', 'directory', 'symlink', 'fd-drift', 'named-drift', 'darwin']) {
    let fd, reads = 0;
    Object.defineProperty(process, 'platform', { ...platform, value: change === 'darwin' ? 'darwin' : 'win32' });
    fs.openSync = (...args) => { fd = original.openSync(...args); return fd; };
    fs.fstatSync = (...args) => {
      const value = original.fstatSync(...args); return change === 'fd-drift' && reads > 0
        ? new Proxy(value, { get: (target, key) => key === 'dev' ? value.dev + 1n : Reflect.get(target, key) }) : value;
    };
    fs.lstatSync = (name, options) => {
      const value = original.lstatSync(name, options); if (name !== file) return value;
      const device = change === 'same' || change === 'named-drift' && reads > 0 ? value.dev : change === 'nonzero' ? value.dev + 1n : 0n;
      return new Proxy(value, { get(target, key) {
        if (key === 'dev') return device;
        if (key === 'ino' && change === 'inode') return value.ino + 1n;
        if (key === 'uid' && change === 'owner') return value.uid + 1n;
        if (key === 'isFile' && change === 'directory') return () => false;
        if (key === 'isSymbolicLink' && change === 'symlink') return () => true;
        return Reflect.get(target, key);
      } });
    };
    fs.readSync = (...args) => { reads++; return original.readSync(...args); };
    syncBuiltinESMExports();
    try {
      if (['zero', 'same'].includes(change)) assert.match(gatewayEvidenceReference(file).sha256, /^[a-f0-9]{64}$/);
      else assert.throws(() => gatewayEvidenceReference(file), /FIXTURE_EVIDENCE/, change);
      if (!['zero', 'same', 'fd-drift', 'named-drift'].includes(change)) assert.equal(reads, 0, `${change}: refuse before payload`);
      assert.throws(() => original.fstatSync(fd), { code: 'EBADF' });
    } finally {
      Object.assign(fs, original); syncBuiltinESMExports(); Object.defineProperty(process, 'platform', platform);
    }
  }
});
function input(t, { receiptPatch = {}, statusPatch = {}, routes = ['GET /api/build', 'GET /api/auth/native/sessions'] } = {}) {
  const cache = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-gateway-export-')));
  t.after(() => rmSync(cache, { recursive: true, force: true }));
  const write = (name, value) => {
    const file = path.join(cache, name);
    writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
    return gatewayEvidenceReference(file);
  };
  const implementationSha256 = createHash('sha256').update(readFileSync(source)).digest('hex');
  const receipt = { environment: 'docker-integration', syntheticDataOnly: true, noPaidProviderKeysInAPIOrWeb: true,
    apiWebPostgresScannerNetworkInternal: true, webAcceptanceMarkerBuild: true, webMarkerTransportSourcePresent: true,
    productionAccessed: false, tlsProof: { strictDefaultTLS: true, verificationDisabled: false, unknownCARejected: true, wrongHostnameRejected: true },
    gatewayRunId: 'actual-unit-run', gatewayUrl: 'https://127.0.0.1:18443', gatewayImplementationSha256: implementationSha256,
    fixtureSourceHashes: { 'scripts/mobile/local-gateway.py': implementationSha256 }, ...receiptPatch };
  const status = { runId: receipt.gatewayRunId, implementationSha256, accepted: 0, lastSequence: 0, markerRejected: 0,
    routeRejected: 0, overflow: false, requests: [], sessionDeleteAdmissions: [], ...statusPatch };
  write('gateway-routes.json', { routes });
  return { cache, dockerReceipt: write('receipt.json', receipt), statusEvidence: write('actual-status.json', status),
    output: path.join(cache, 'gateway-descriptor.json'), receipt, status, write };
}

test('export binds exact source, route inventory, runtime status and immutable isolation receipt without inventing a session ID', (t) => {
  const fixture = input(t), statusBefore = readFileSync(fixture.statusEvidence.path);
  const result = prepareGatewayRoutes(fixture);
  const descriptor = JSON.parse(readFileSync(result.gatewayRoutes.path));
  assert.equal(result.implementationSha256, REVIEWED_GATEWAY_IMPLEMENTATION_SHA256);
  assert.deepEqual(result.gatewayRoutes, gatewayEvidenceReference(fixture.output));
  assert.deepEqual(descriptor.routes, ['GET /api/build', 'GET /api/auth/native/sessions']);
  assert.deepEqual(descriptor.routeInventoryEvidence, gatewayEvidenceReference(`${fixture.output}.routes.json`));
  assert.deepEqual(descriptor.routeInventorySourceEvidence, gatewayEvidenceReference(path.join(fixture.cache, 'gateway-routes.json')));
  assert.deepEqual(readFileSync(descriptor.routeInventoryEvidence.path), readFileSync(descriptor.routeInventorySourceEvidence.path));
  assert.deepEqual(readFileSync(fixture.statusEvidence.path), statusBefore);
  const policy = descriptor.dynamicAdmissions.nativeCurrentSessionDelete;
  assert.deepEqual(policy.implementationEvidence, { path: source, sha256: REVIEWED_GATEWAY_IMPLEMENTATION_SHA256 });
  assert.deepEqual(policy.statusEvidence, fixture.statusEvidence);
  assert.deepEqual(policy.isolationEvidence, fixture.dockerReceipt);
  assert.equal(policy.maxAdmissionEvents, 64);
  assert.equal(policy.maxLiveIds, 1);
  assert.equal(policy.consumeOnAttempt, true);
  assert.equal(policy.nativeBearerOnly, true);
  assert.equal(policy.cookiesAllowed, false);
  assert.equal(policy.currentOnly, true);
  assert.equal(policy.unrevokedOnly, true);
  assert.equal(policy.liveExecutionProofRequiredAt, 'NATIVE-20');
  assert.ok(!JSON.stringify(descriptor).includes('currentSessionId'));
  assert.equal(validateSessionDeletePolicy(descriptor, result.gatewayRoutes, fixture.dockerReceipt, fixture.receipt).mode, 'dynamic');
  assert.equal(result.nativeExecution, 'not-run');
  assert.equal(result.servicesChanged, false);
  assert.equal(result.credentialFilesRead, false);
  if (process.platform !== 'win32') assert.equal(statSync(fixture.output).mode & 0o777, 0o600);
});

test('export refuses invented static DELETE IDs, wildcard routes, duplicate inventory and missing source route', (t) => {
  for (const routes of [
    ['GET /api/auth/native/sessions', 'DELETE /api/auth/native/sessions/guessed-future-id'],
    ['GET /api/auth/native/sessions', 'DELETE /api/auth/native/sessions/*'],
    ['GET /api/auth/native/sessions', 'GET /api/matters/{id}'],
    ['GET /api/auth/native/sessions', 'GET /api/matters/?q=private'],
    ['GET /api/auth/native/sessions', 'GET /api/auth/native/sessions'],
    ['GET /api/build'],
  ]) {
    const fixture = input(t, { routes });
    assert.throws(() => prepareGatewayRoutes(fixture));
    assert.equal(existsSync(fixture.output), false);
  }
});

test('export rejects source and run drift plus private, production, paid-key, network and TLS claims', (t) => {
  for (const receiptPatch of [
    { environment: 'unit' }, { syntheticDataOnly: false }, { productionAccessed: true },
    { noPaidProviderKeysInAPIOrWeb: false }, { apiWebPostgresScannerNetworkInternal: false },
    { webAcceptanceMarkerBuild: false }, { webMarkerTransportSourcePresent: false },
    { tlsProof: { strictDefaultTLS: true, verificationDisabled: true } },
    { gatewayImplementationSha256: '0'.repeat(64) }, { fixtureSourceHashes: {} },
    { gatewayUrl: 'https://caseops.ai' }, { gatewayUrl: 'http://127.0.0.1:18443' },
    { gatewayUrl: 'https://127.0.0.1:18443/path' }, { gatewayUrl: 'https://127.0.0.1:18443?q=x' },
  ]) {
    const fixture = input(t, { receiptPatch });
    assert.throws(() => prepareGatewayRoutes(fixture));
    assert.equal(existsSync(fixture.output), false);
  }
});

test('export rejects rejected, overflowed, unsettled, incomplete and unlinked runtime ledgers without changing evidence', (t) => {
  const sourceRequest = { sequence: 1, requestId: 'a'.repeat(16), method: 'GET', route: '/api/auth/native/sessions',
    status: 200, nativeMarker: true, browserHandoff: false };
  for (const statusPatch of [
    { runId: 'different-run' }, { implementationSha256: '0'.repeat(64) }, { markerRejected: 1 }, { routeRejected: 1 },
    { overflow: true }, { accepted: 1 }, { sessionDeleteAdmissions: undefined },
    { accepted: 1, lastSequence: 1, requests: [{ ...sourceRequest, status: null }] },
    { accepted: 2, lastSequence: 2, requests: [sourceRequest] },
    { sessionDeleteAdmissions: [{ type: 'session-delete-admitted', route: 'DELETE /api/auth/native/sessions/invented', sourceRequestId: 'a'.repeat(16) }] },
  ]) {
    const fixture = input(t, { statusPatch }), before = readFileSync(fixture.statusEvidence.path);
    assert.throws(() => prepareGatewayRoutes(fixture));
    assert.deepEqual(readFileSync(fixture.statusEvidence.path), before);
    assert.equal(existsSync(fixture.output), false);
  }
});

test('all 64 real admission events remain intact, while a 65th cannot be truncated into valid evidence', (t) => {
  const requests = Array.from({ length: 64 }, (_, index) => ({ sequence: index + 1, requestId: index.toString(16).padStart(16, '0'),
    method: 'GET', route: '/api/auth/native/sessions', status: 200, nativeMarker: true, browserHandoff: false }));
  const events = requests.map(({ requestId }) => ({ type: 'session-delete-admitted',
    route: 'DELETE /api/auth/native/sessions/response-derived-current', sourceRequestId: requestId }));
  const fixture = input(t, { statusPatch: { accepted: 64, lastSequence: 64, requests, sessionDeleteAdmissions: events } });
  const before = readFileSync(fixture.statusEvidence.path);
  prepareGatewayRoutes(fixture);
  assert.deepEqual(readFileSync(fixture.statusEvidence.path), before);
  const overflow = input(t, { statusPatch: { accepted: 64, lastSequence: 64, requests, sessionDeleteAdmissions: [...events, events[0]] } });
  assert.throws(() => prepareGatewayRoutes(overflow), /BOUNDED_SESSION_ADMISSION_LEDGER_REQUIRED/);
  assert.equal(JSON.parse(readFileSync(overflow.statusEvidence.path)).sessionDeleteAdmissions.length, 65);
  assert.equal(existsSync(overflow.output), false);
});

test('tampered evidence hashes and symlinks fail closed before writing the descriptor', (t) => {
  for (const kind of ['receipt', 'status']) {
    const fixture = input(t);
    const reference = kind === 'receipt' ? fixture.dockerReceipt : fixture.statusEvidence;
    writeFileSync(reference.path, '{}');
    assert.throws(() => prepareGatewayRoutes(fixture), /FIXTURE_EVIDENCE_CHANGED/);
    assert.equal(existsSync(fixture.output), false);
  }
  const fixture = input(t), link = path.join(fixture.cache, 'symlink.json');
  symlinkSync(fixture.statusEvidence.path, link);
  assert.throws(() => gatewayEvidenceReference(link), /BOUNDED_FIXTURE_EVIDENCE_REQUIRED/);
});

test('output cannot escape the fixture cache, overwrite an earlier descriptor or create repository artifacts', (t) => {
  const fixture = input(t), repoOutput = fileURLToPath(new URL('./export-must-not-exist.json', import.meta.url));
  for (const output of [repoOutput, path.join(fixture.cache, '..', 'gateway-must-not-exist.json'), 'relative.json']) {
    assert.throws(() => prepareGatewayRoutes({ ...fixture, output }), /OUTPUT_MUST_STAY_INSIDE_FIXTURE_CACHE/);
  }
  assert.equal(existsSync(repoOutput), false);
  prepareGatewayRoutes(fixture);
  const before = readFileSync(fixture.output), snapshotBefore = readFileSync(`${fixture.output}.routes.json`);
  assert.throws(() => prepareGatewayRoutes(fixture), { code: 'EEXIST' });
  assert.deepEqual(readFileSync(fixture.output), before);
  assert.deepEqual(readFileSync(`${fixture.output}.routes.json`), snapshotBefore);
});

test('later mutable route-source changes preserve prior run validation; altered immutable snapshots remain rejected', (t) => {
  const fixture = input(t), result = prepareGatewayRoutes(fixture);
  const descriptor = JSON.parse(readFileSync(result.gatewayRoutes.path));
  const inventory = path.join(fixture.cache, 'gateway-routes.json');
  const original = readFileSync(descriptor.routeInventoryEvidence.path);
  writeFileSync(inventory, JSON.stringify({ routes: [...descriptor.routes, 'POST /api/paid/unreviewed'] }));
  assert.equal(validateSessionDeletePolicy(descriptor, result.gatewayRoutes, fixture.dockerReceipt, fixture.receipt).mode, 'dynamic');
  assert.deepEqual(readFileSync(descriptor.routeInventoryEvidence.path), original);
  assert.equal(descriptor.routeInventorySourceEvidence.path, inventory);
  writeFileSync(descriptor.routeInventoryEvidence.path, readFileSync(inventory));
  assert.throws(() => validateSessionDeletePolicy(descriptor, result.gatewayRoutes, fixture.dockerReceipt, fixture.receipt), /FIXTURE_EVIDENCE_CHANGED/);
  descriptor.routeInventoryEvidence = gatewayEvidenceReference(descriptor.routeInventoryEvidence.path);
  assert.throws(() => validateSessionDeletePolicy(descriptor, result.gatewayRoutes, fixture.dockerReceipt, fixture.receipt), /GATEWAY_ROUTE_SOURCE_CHANGED/);
  delete descriptor.routeInventoryEvidence;
  assert.equal(validateSessionDeletePolicy(descriptor, result.gatewayRoutes, fixture.dockerReceipt, fixture.receipt).mode, 'dynamic');
});

test('output through a symlinked directory cannot create files outside the cache', (t) => {
  const fixture = input(t), other = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-gateway-outside-')));
  t.after(() => rmSync(other, { recursive: true, force: true }));
  symlinkSync(other, path.join(fixture.cache, 'outside'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => prepareGatewayRoutes({ ...fixture, output: path.join(fixture.cache, 'outside', 'new', 'descriptor.json') }), /OUTPUT_MUST_STAY_INSIDE_FIXTURE_CACHE/);
  assert.equal(existsSync(path.join(other, 'new')), false);
});
