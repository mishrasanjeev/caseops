import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { closeSync, existsSync, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import https from 'node:https';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { validateSessionDeletePolicy } from '../../apps/mobile/e2e/session-admission.mjs';
import { safeFailure } from '../../apps/mobile/e2e/support.mjs';

const REPO = fileURLToPath(new URL('../../', import.meta.url));
const SOURCE = fileURLToPath(new URL('./local-gateway.py', import.meta.url));
// Reviewed with the actual Python Gateway regressions, including the 64-event boundary.
// A changed implementation requires another review; runtime hashes alone cannot admit it.
export const REVIEWED_GATEWAY_IMPLEMENTATION_SHA256 = '9cfe00aa49b016fb1e50f1ca4d5c613e77160466e86ee743bc3220ed34e293de';
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const inside = (root, file) => {
  const relative = path.relative(root, file);
  return relative && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
};

export function gatewayEvidenceReference(file, maxBytes = 1048576) {
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_FIXTURE_EVIDENCE_REQUIRED');
  const before = lstatSync(file);
  assert.ok(before.isFile() && !before.isSymbolicLink(), 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
  const fd = openSync(file, 'r');
  let bytes;
  try {
    const opened = fstatSync(fd);
    assert.ok(opened.isFile() && opened.size > 0 && opened.size <= maxBytes, 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
    assert.ok(before.dev === opened.dev && before.ino === opened.ino, 'FIXTURE_EVIDENCE_REPLACED');
    bytes = readFileSync(fd);
    const after = fstatSync(fd);
    assert.ok(opened.size === after.size && opened.mtimeMs === after.mtimeMs && bytes.length === opened.size, 'FIXTURE_EVIDENCE_CHANGED');
  } finally { closeSync(fd); }
  return { path: file, sha256: sha256(bytes) };
}

function cacheDirectory(cache) {
  assert.ok(path.isAbsolute(cache || ''), 'ABSOLUTE_FIXTURE_CACHE_REQUIRED');
  const root = realpathSync(cache);
  assert.ok(lstatSync(root).isDirectory() && root !== path.resolve(REPO) && !inside(path.resolve(REPO), root), 'FIXTURE_CACHE_MUST_STAY_OUTSIDE_REPOSITORY');
  return root;
}

function outputPath(cache, output) {
  assert.ok(path.isAbsolute(output || ''), 'OUTPUT_MUST_STAY_INSIDE_FIXTURE_CACHE');
  let ancestor = path.resolve(output);
  const suffix = [];
  while (!existsSync(ancestor)) {
    suffix.unshift(path.basename(ancestor));
    ancestor = path.dirname(ancestor);
  }
  const target = path.join(realpathSync(ancestor), ...suffix);
  assert.ok(inside(cache, target), 'OUTPUT_MUST_STAY_INSIDE_FIXTURE_CACHE');
  mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
  assert.ok(realpathSync(path.dirname(target)) === cache || inside(cache, realpathSync(path.dirname(target))), 'OUTPUT_MUST_STAY_INSIDE_FIXTURE_CACHE');
  return target;
}

function isolationReceipt(reference, cache) {
  assert.ok(inside(cache, realpathSync(reference?.path || '')), 'ISOLATION_RECEIPT_MUST_STAY_INSIDE_FIXTURE_CACHE');
  const receipt = JSON.parse(verifiedFile(reference.path, reference.sha256));
  assert.equal(receipt.environment, 'docker-integration', 'REAL_DOCKER_FIXTURE_REQUIRED');
  assert.equal(receipt.syntheticDataOnly, true, 'NO_PRIVATE_FIXTURES');
  for (const key of ['noPaidProviderKeysInAPIOrWeb', 'apiWebPostgresScannerNetworkInternal', 'webAcceptanceMarkerBuild', 'webMarkerTransportSourcePresent']) {
    assert.equal(receipt[key], true, 'ISOLATED_MARKED_DOCKER_FIXTURE_REQUIRED');
  }
  assert.equal(receipt.productionAccessed, false, 'PRODUCTION_ACCESS_FORBIDDEN');
  assert.equal(receipt.tlsProof?.strictDefaultTLS, true, 'STRICT_FIXTURE_TLS_REQUIRED');
  assert.equal(receipt.tlsProof?.verificationDisabled, false, 'STRICT_FIXTURE_TLS_REQUIRED');
  for (const key of ['unknownCARejected', 'wrongHostnameRejected']) assert.equal(receipt.tlsProof?.[key], true, 'STRICT_FIXTURE_TLS_REQUIRED');
  assert.ok(typeof receipt.gatewayRunId === 'string' && receipt.gatewayRunId.length > 0 && receipt.gatewayRunId.length <= 200, 'GATEWAY_RUN_REQUIRED');
  const origin = new URL(receipt.gatewayUrl);
  assert.ok(origin.protocol === 'https:' && origin.hostname === '127.0.0.1' && Number(origin.port) >= 1024
    && Number(origin.port) <= 65535 && origin.pathname === '/' && !origin.username && !origin.password
    && !origin.search && !origin.hash, 'EXACT_LOOPBACK_HTTPS_GATEWAY_REQUIRED');
  return receipt;
}

export function prepareGatewayRoutes({ cache, dockerReceipt, statusEvidence, output }) {
  cache = cacheDirectory(cache);
  output = outputPath(cache, output);
  const receipt = isolationReceipt(dockerReceipt, cache);
  const implementationEvidence = gatewayEvidenceReference(SOURCE);
  assert.equal(implementationEvidence.sha256, REVIEWED_GATEWAY_IMPLEMENTATION_SHA256, 'GATEWAY_IMPLEMENTATION_REVIEW_REQUIRED');
  assert.equal(receipt.gatewayImplementationSha256, implementationEvidence.sha256, 'DYNAMIC_SESSION_IMPLEMENTATION_MISMATCH');
  assert.equal(receipt.fixtureSourceHashes?.['scripts/mobile/local-gateway.py'], implementationEvidence.sha256, 'ISOLATION_GATEWAY_SOURCE_MISMATCH');
  const routeInventorySourceEvidence = gatewayEvidenceReference(path.join(cache, 'gateway-routes.json'));
  const routeInventoryBytes = verifiedFile(routeInventorySourceEvidence.path, routeInventorySourceEvidence.sha256);
  const { routes } = JSON.parse(routeInventoryBytes);
  assert.ok(Array.isArray(routes) && routes.length > 0 && routes.length <= 500, 'GATEWAY_ROUTE_INVENTORY_REQUIRED');
  assert.ok(routes.every((route) => typeof route === 'string' && route.length <= 400
    && /^(GET|POST|PATCH|DELETE|OPTIONS) \/api\/[^\s?#*{}<>]*$/.test(route)), 'EXACT_GATEWAY_ROUTES_REQUIRED');
  assert.equal(new Set(routes).size, routes.length, 'DUPLICATE_GATEWAY_ROUTE');
  assert.ok(!routes.some((route) => route.startsWith('DELETE /api/auth/native/sessions')), 'FUTURE_SESSION_DELETE_ID_FORBIDDEN');
  assert.ok(inside(cache, realpathSync(statusEvidence?.path || '')), 'STATUS_EVIDENCE_MUST_STAY_INSIDE_FIXTURE_CACHE');
  const status = JSON.parse(verifiedFile(statusEvidence.path, statusEvidence.sha256));
  assert.equal(status.accepted, status.lastSequence, 'GATEWAY_ACCEPTED_COUNT_MISMATCH');
  const policy = { kind: 'native-current-session-delete-v1', sourceRoute: 'GET /api/auth/native/sessions', sourceListLimit: 50,
    maxLiveIds: 1, maxAdmissionEvents: 64, nativeBearerOnly: true, cookiesAllowed: false, currentOnly: true, unrevokedOnly: true,
    consumeOnAttempt: true, gatewayRunId: receipt.gatewayRunId, implementationSha256: implementationEvidence.sha256,
    implementationEvidence, isolationEvidence: dockerReceipt, statusEvidence,
    requestEvidenceLink: 'sessionDeleteAdmissions[].sourceRequestId -> requests[].requestId', liveExecutionProofRequiredAt: 'NATIVE-20' };
  const routeInventoryEvidence = { path: `${output}.routes.json`, sha256: sha256(routeInventoryBytes) };
  // The admission source changes when a later fixture is extended. Preserve the
  // exact bytes for this run; source provenance must not become a live dependency.
  for (const reference of [dockerReceipt, statusEvidence, implementationEvidence, routeInventorySourceEvidence]) verifiedFile(reference.path, reference.sha256);
  if (existsSync(output) || existsSync(routeInventoryEvidence.path)) {
    throw Object.assign(new Error('OUTPUT_ALREADY_EXISTS'), { code: 'EEXIST' });
  }
  writeFileSync(routeInventoryEvidence.path, routeInventoryBytes, { flag: 'wx', mode: 0o600 });
  const descriptor = { schemaVersion: 2, routes, routeInventoryEvidence, routeInventorySourceEvidence,
    dynamicAdmissions: { nativeCurrentSessionDelete: policy } };
  const bytes = Buffer.from(`${JSON.stringify(descriptor, null, 2)}\n`);
  const gatewayRoutes = { path: output, sha256: sha256(bytes) };
  validateSessionDeletePolicy(descriptor, gatewayRoutes, dockerReceipt, receipt);
  for (const reference of [dockerReceipt, statusEvidence, implementationEvidence, routeInventoryEvidence]) verifiedFile(reference.path, reference.sha256);
  writeFileSync(output, bytes, { flag: 'wx', mode: 0o600 });
  return { gatewayRoutes, statusEvidence, isolationEvidence: dockerReceipt, routeInventoryEvidence, routeInventorySourceEvidence,
    gatewayRunId: receipt.gatewayRunId, implementationSha256: implementationEvidence.sha256,
    nativeExecution: 'not-run', servicesChanged: false, credentialFilesRead: false };
}

async function readGatewayStatus(receipt, publicCa) {
  const ca = verifiedFile(publicCa.path, publicCa.sha256, 131072);
  const url = new URL('/__caseops_e2e/status', receipt.gatewayUrl);
  return new Promise((resolve, reject) => {
    const request = https.request(url, { method: 'GET', ca, rejectUnauthorized: true, agent: false,
      headers: { Accept: 'application/json', 'X-CaseOps-Automated-Test': 'no-paid-providers' } }, (response) => {
      const chunks = [];
      let size = 0;
      if (response.statusCode !== 200) return request.destroy(new Error('GATEWAY_STATUS_REQUEST_FAILED'));
      response.on('data', (chunk) => {
        size += chunk.length;
        if (size > 1048576) request.destroy(new Error('GATEWAY_STATUS_RESPONSE_BOUND'));
        else chunks.push(chunk);
      });
      response.on('error', reject);
      response.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch (error) { reject(error); }
      });
    });
    const deadline = setTimeout(() => request.destroy(new Error('GATEWAY_STATUS_DEADLINE')), 10000);
    request.on('error', reject);
    request.on('close', () => clearTimeout(deadline));
    request.end();
  });
}

export async function captureGatewayRoutes({ cache, dockerReceipt, output }) {
  cache = cacheDirectory(cache);
  output = outputPath(cache, output);
  const receipt = isolationReceipt(dockerReceipt, cache);
  assert.ok(inside(cache, realpathSync(receipt.publicCA || '')), 'PUBLIC_CA_MUST_STAY_INSIDE_FIXTURE_CACHE');
  const publicCa = gatewayEvidenceReference(receipt.publicCA, 131072);
  const status = await readGatewayStatus(receipt, publicCa);
  const statusPath = `${output}.status.json`;
  writeFileSync(statusPath, `${JSON.stringify(status, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
  const statusEvidence = gatewayEvidenceReference(statusPath);
  return { ...prepareGatewayRoutes({ cache, dockerReceipt, statusEvidence, output }), publicCa };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const { values } = parseArgs({ options: { cache: { type: 'string' }, receipt: { type: 'string' }, output: { type: 'string' } } });
    assert.ok(values.cache && values.receipt && values.output, 'USAGE_CACHE_RECEIPT_OUTPUT_REQUIRED');
    const result = await captureGatewayRoutes({ cache: values.cache, dockerReceipt: gatewayEvidenceReference(values.receipt), output: values.output });
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    console.error(error.code === 'EEXIST' ? 'OUTPUT_ALREADY_EXISTS' : safeFailure(error, 'GATEWAY_ROUTE_EXPORT_FAILED'));
    process.exitCode = 1;
  }
}
