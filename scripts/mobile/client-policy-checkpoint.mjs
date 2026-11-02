/** Publish a policy checkpoint only from an actual separately owned transition.
 * This consumer never changes settings, restarts services or resets a ledger.
 * The normal canonical Compose operator owns that separately admitted action.
 */
import assert from 'node:assert/strict';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { readClientPublicInput, writeClientProjection } from './client-extension-public-input.mjs';
import { localJson } from '../../apps/mobile/e2e/support.mjs';
import { parseClientCompatibility } from '../../apps/mobile/e2e/client-extensions-contract.mjs';

const ROOT=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
const read = ref => readClientPublicInput(ref.path, { expectedSha256: ref.sha256 }).value;
export async function verifyClientPolicyCheckpoint(q, dependencies = {}) {
  const io = { read, getJson: localJson, environment: process.env, ...dependencies };
  assert.equal(q.kind, 'complete-native-client-policy-checkpoint');
  assert.ok(path.isAbsolute(q.requestEvidence.path)&&q.requestEvidence.path!==ROOT&&!q.requestEvidence.path.startsWith(ROOT+path.sep));
  assert.equal(q.readyForLive, true); assert.equal(q.preparedOnly, false);
  const request = io.read(q.requestEvidence), prior = io.read(q.previousServingEvidence);
  const serving = io.read(q.servingEvidence), controls = io.read(q.controlsEvidence);
  const receipt = io.read(q.receiptEvidence), previousReceipt = io.read(q.previousReceiptEvidence);
  assert.notEqual(q.receiptEvidence.sha256,q.previousReceiptEvidence.sha256);
  assert.deepEqual(serving.receiptEvidence,q.receiptEvidence);assert.deepEqual(prior.receiptEvidence,q.previousReceiptEvidence);
  assert.equal(receipt.gatewayRunId,serving.gatewayRunId);assert.equal(previousReceipt.gatewayRunId,request.binding.runId);
  for(const value of [receipt,previousReceipt]){assert.equal(value.backendSha,request.binding.sourceSha);assert.equal(value.webSha,request.binding.sourceSha);assert.equal(value.productionAccessed,false);}
  const ledger=io.read(serving.previousLedgerEvidence);assert.deepEqual(serving.previousLedgerEvidence,prior.gatewayLedgerEvidence);assert.equal(ledger.runId,request.binding.runId);assert.equal(ledger.overflow,false);assert.ok(Array.isArray(ledger.requests)&&ledger.requests.length<=500);
  const registration = io.read(controls.registrationEvidence), config = io.read(q.configurationEvidence);
  assert.equal(request.kind, 'native-client-extension-owner-checkpoint');
  assert.equal(request.operation, 'policyCheckpoint'); assert.equal(request.noReplay, true);
  assert.ok(['floor', 'rollback', 'exit-floor', 'final-rollback'].includes(request.args.phase));
  assert.equal(request.caseId, ({floor:'CX28-VERSION-02',rollback:'CX28-VERSION-03','exit-floor':'CX28-VERSION-04','final-rollback':'CX28-VERSION-04'})[request.args.phase]);
  assert.equal(serving.kind, 'actual-client-policy-configuration-transition');
  assert.equal(serving.observed, true); assert.equal(serving.complete, true);
  assert.equal(serving.productionAccessed, false); assert.equal(serving.noPaidMarker, 'no-paid-providers');
  assert.equal(serving.databaseAndSecurityIdentityPreserved, true);
  assert.deepEqual(serving.previousServingEvidence, q.previousServingEvidence);
  assert.deepEqual(serving.protectedIdentityEvidence, prior.protectedIdentityEvidence);
  // This is typed physical/container/private-metadata preservation, not a DB dump claim.
  const preserved = io.read(serving.protectedIdentityEvidence);
  assert.equal(preserved.observed, true); assert.deepEqual(preserved.before, preserved.after);
  assert.equal(preserved.scope, 'owned-postgres-mount-and-private-metadata-identities');
  assert.equal(serving.backendSha, request.binding.sourceSha); assert.equal(serving.webSha, request.binding.sourceSha);
  assert.notEqual(serving.gatewayRunId, request.binding.runId);
  assert.deepEqual(serving.currentContainerIdentities.map(x => x.role).sort(), ['api', 'gateway', 'migrate', 'postgres', 'scanner', 'valkey', 'web']);
  assert.equal(new Set(serving.currentContainerIdentities.map(x => x.id)).size, 7);
  assert.equal(controls.profile, 'native-client-extensions-v1');
  assert.equal(controls.sourceSha, request.binding.sourceSha); assert.equal(controls.binaryHash, request.binding.binaryHash);
  assert.equal(controls.runId, serving.gatewayRunId); assert.deepEqual(controls.servingEvidence, q.servingEvidence);
  assert.equal(registration.runId, serving.gatewayRunId);
  assert.deepEqual(registration.priorNativeIdentityEvidence, request.args.priorNativeIdentityEvidence);
  const native = io.read(request.args.priorNativeIdentityEvidence);
  assert.equal(native.kind, 'actual-native-session-identity'); assert.equal(native.observed, true);
  assert.equal(native.sourceSha, request.binding.sourceSha); assert.equal(native.binaryHash, request.binding.binaryHash);
  assert.equal(native.runId, request.binding.runId); assert.deepEqual(registration.priorNativeIdentity, native.identity);
  assert.deepEqual(serving.configurationEvidence, q.configurationEvidence);
  const platform = registration.platform, minimum = config['CASEOPS_NATIVE_MINIMUM_' + platform.toUpperCase() + '_VERSION'];
  assert.equal(minimum, ['floor','exit-floor'].includes(request.args.phase) ? q.floorVersion : null);
  assert.equal(io.environment.NODE_EXTRA_CA_CERTS, serving.publicCA);
  assert.notEqual(io.environment.NODE_TLS_REJECT_UNAUTHORIZED, '0');
  for (const url of [serving.gatewayUrl, serving.webGatewayUrl]) {
    const parsed = new URL(url); assert.equal(parsed.protocol, 'https:');
    assert.ok(['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname));
  }
  const api = await io.getJson(serving.gatewayUrl + '/api/build');
  const web = await io.getJson(serving.webGatewayUrl + '/api/release-identity');
  assert.equal(api.release_sha, request.binding.sourceSha); assert.equal(api.revision, serving.backendRevision);
  assert.equal(web.release_sha, request.binding.sourceSha); assert.equal(web.revision, serving.webRevision);
  const policy = parseClientCompatibility(await io.getJson(serving.gatewayUrl + '/api/auth/native/compatibility?' + new URLSearchParams({ platform, client_version: registration.clientVersion })), { platform, version: registration.clientVersion });
  assert.equal(policy.minimum_supported_version, minimum);
  assert.equal(policy.status, ['floor','exit-floor'].includes(request.args.phase) ? 'update_required' : 'supported');
  const status = await io.getJson(serving.gatewayUrl + '/__caseops_e2e/status');
  assert.equal(status.runId, serving.gatewayRunId); assert.equal(status.v1ControlProfile, controls.profile);
  assert.equal(status.v1RegistrationSha256, controls.registrationEvidence.sha256); assert.equal(status.overflow, false);
  return { kind: 'native-client-extension-owner-ack', requestEvidence: q.requestEvidence,
    operation: request.operation, caseId: request.caseId, binding: request.binding,
    observed: true, acknowledged: true, noPaidMarker: 'no-paid-providers', mutationUncertain: false, replayed: false,
    value: { observed: true, operation: request.args.phase, configurationReplayed: false, originalLedgerPreserved: true,
      databaseAndSecurityIdentityPreserved: true, receiptEvidence: q.receiptEvidence,
      previousReceiptEvidence: q.previousReceiptEvidence, controlsEvidence: q.controlsEvidence,
      servingEvidence: q.servingEvidence, configurationEvidence: q.configurationEvidence } };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) try {
  const [file, hash, output] = process.argv.slice(2); assert.equal(process.argv.length, 5);
  const q = readClientPublicInput(file, { maxBytes: 16384, expectedSha256: hash }).value;
  const value = await verifyClientPolicyCheckpoint(q);
  assert.equal(path.dirname(output), path.dirname(q.requestEvidence.path));
  assert.equal(output, q.requestEvidence.path.replace(/\.request\.json$/, '.result.json'));
  const bytes = Buffer.from(JSON.stringify(value, null, 2) + '\n');
  writeClientProjection(output,bytes);
  console.log(JSON.stringify({ path: output, sha256: createHash('sha256').update(bytes).digest('hex') }));
} catch { console.error('NATIVE_CLIENT_POLICY_CHECKPOINT_REFUSED'); process.exitCode = 1; }
