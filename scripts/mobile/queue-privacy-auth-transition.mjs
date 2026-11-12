import assert from 'node:assert/strict';
import path from 'node:path';
import { QP } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
import { reference } from '../../apps/mobile/e2e/queue-privacy-contract.mjs';
import { checkLedger } from '../../apps/mobile/e2e/traffic.mjs';

const services = ['api', 'gateway', 'migrate', 'postgres', 'scanner', 'valkey', 'web'];
const activationKeys = ['CASEOPS_MOBILE_V1_CONTROLS', 'CASEOPS_MOBILE_V1_PROFILE',
  'CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256', 'CASEOPS_MOBILE_V1_REGISTRATION',
  'CASEOPS_MOBILE_V1_REGISTRATION_SHA256'];
function keys(value, expected, reason) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), reason);
  assert.deepEqual(Object.keys(value).sort(), [...expected].sort(), reason);
}
function runtime(value, receipt, source) {
  keys(value, ['kind', 'sourceSha', 'project', 'runId', 'containers'], 'QP_AUTH_RUNTIME_SHAPE_REQUIRED');
  assert.equal(value.kind, 'actual-qp-runtime-inventory');
  assert.equal(value.sourceSha, source.sourceSha);
  assert.equal(value.project, receipt.project); assert.equal(value.runId, receipt.gatewayRunId);
  assert.equal(value.containers.length, services.length, 'QP_AUTH_COMPLETE_RUNTIME_REQUIRED');
  const rows = value.containers.map(row => ({ ...row })).sort((a, b) => a.name.localeCompare(b.name));
  assert.deepEqual(rows.map(row => row.name), services.map(service => `/${receipt.project}-${service}-1`), 'QP_AUTH_EXACT_SERVICES_REQUIRED');
  assert.equal(new Set(rows.map(row => row.id)).size, services.length, 'QP_AUTH_UNIQUE_CONTAINERS_REQUIRED');
  for (const row of rows) {
    keys(row, ['id', 'name', 'image', 'networks', 'project', 'mounts'], 'QP_AUTH_CONTAINER_SHAPE_REQUIRED');
    assert.match(row.id, /^[a-f0-9]{64}$/); assert.match(row.image, /^sha256:[a-f0-9]{64}$/);
    assert.equal(row.project, receipt.project);
    assert.ok(Array.isArray(row.networks) && row.networks.length > 0 && row.networks.length <= 4);
    assert.equal(new Set(row.networks).size, row.networks.length);
    assert.ok(row.networks.every(name => typeof name === 'string' && name.startsWith(receipt.project + '_')));
    row.networks = [...row.networks].sort();
    assert.ok(Array.isArray(row.mounts) && row.mounts.length <= 16);
    row.mounts = [...row.mounts].sort((a, b) => a.destination.localeCompare(b.destination));
    assert.equal(new Set(row.mounts.map(mount => mount.destination)).size, row.mounts.length);
    for (const mount of row.mounts) {
      keys(mount, ['type', 'name', 'source', 'destination', 'readWrite'], 'QP_AUTH_MOUNT_SHAPE_REQUIRED');
      assert.ok(['bind', 'volume'].includes(mount.type) && typeof mount.readWrite === 'boolean');
      assert.ok(mount.name === null || typeof mount.name === 'string');
      for (const key of ['source', 'destination']) assert.ok(typeof mount[key] === 'string' && path.isAbsolute(mount[key]));
    }
  }
  const withoutMounts = rows.map(({ mounts, ...row }) => row);
  const declared = receipt.containers.map(row => ({ ...row, networks: [...row.networks].sort() })).sort((a, b) => a.name.localeCompare(b.name));
  assert.deepEqual(withoutMounts, declared, 'QP_AUTH_RUNTIME_RECEIPT_CHANGED');
  return rows;
}

/** A separately observed normal sign-in may precede the short control lease.
 * Its original receipt stays unchanged. Admit it only through the complete
 * source/runtime/configuration transition to this exact active registration.
 * This function opens only public evidence; it cannot refresh a lease, sign in,
 * read credentials, perform native input or change any running service.
 */
export function resolveQPAuthDockerReceipt(q, { read, source, isolation, controls }) {
  if (q.preRegistrationAuthEvidence === undefined || q.preRegistrationAuthEvidence === null) return q.dockerReceipt;
  reference(q.preRegistrationAuthEvidence);
  const transition = read(q.preRegistrationAuthEvidence);
  const fields = ['schemaVersion', 'kind', 'sourceSha', 'beforeDockerReceipt', 'afterDockerReceipt',
    'beforeRuntimeEvidence', 'afterRuntimeEvidence', 'beforeConfiguration', 'afterConfiguration',
    'beforeGatewayStatus', 'afterGatewayStatus', 'activationEvidence', 'authObservations'];
  keys(transition, fields, 'QP_AUTH_TRANSITION_SHAPE_REQUIRED');
  assert.equal(transition.schemaVersion, 1); assert.equal(transition.kind, 'actual-qp-auth-before-registration');
  assert.equal(transition.sourceSha, source.sourceSha);
  for (const key of fields.slice(3, -1)) reference(transition[key]);
  assert.deepEqual(transition.afterDockerReceipt, q.dockerReceipt, 'QP_AUTH_FINAL_RECEIPT_REQUIRED');
  assert.notDeepEqual(transition.beforeDockerReceipt, q.dockerReceipt, 'QP_AUTH_DISTINCT_PRIOR_RECEIPT_REQUIRED');
  assert.deepEqual(transition.authObservations, q.members.map(member => member.authObservation), 'QP_AUTH_EXACT_OBSERVATIONS_REQUIRED');
  const before = read(transition.beforeDockerReceipt), after = read(transition.afterDockerReceipt);
  assert.deepEqual(after, isolation, 'QP_AUTH_CURRENT_ISOLATION_REQUIRED');
  for (const receipt of [before, after]) {
    assert.equal(receipt.environment, 'docker-integration'); assert.equal(receipt.syntheticDataOnly, true);
    assert.equal(receipt.productionAccessed, false); assert.equal(receipt.metroLaunched, false);
    assert.equal(receipt.backendSha, source.sourceSha); assert.equal(receipt.webSha, source.sourceSha);
    assert.equal(receipt.tlsProof?.strictDefaultTLS, true); assert.equal(receipt.tlsProof?.verificationDisabled, false);
    assert.equal(receipt.apiWebPostgresScannerNetworkInternal, true);
  }
  for (const key of ['project', 'gatewayRunId', 'backendRevision', 'webRevision', 'source', 'apiOrigin', 'webOrigin',
    'gatewayUrl', 'webGatewayUrl', 'publicCA', 'composeSha256', 'fixtureSourceHashes', 'gatewayImplementationSha256']) {
    assert.ok(Object.hasOwn(before, key) && Object.hasOwn(after, key), 'QP_AUTH_SERVING_IDENTITY_REQUIRED');
    assert.deepEqual(before[key], after[key], 'QP_AUTH_SERVING_IDENTITY_CHANGED');
  }
  const earlier = runtime(read(transition.beforeRuntimeEvidence), before, source);
  const current = runtime(read(transition.afterRuntimeEvidence), after, source);
  for (let index = 0; index < earlier.length; index++) {
    const a = earlier[index], b = current[index];
    if (a.name === `/${after.project}-gateway-1`) {
      assert.notEqual(a.id, b.id, 'QP_AUTH_ACTIVATION_GATEWAY_REQUIRED');
      assert.deepEqual({ ...a, id: b.id }, b, 'QP_AUTH_GATEWAY_SCOPE_CHANGED');
    } else assert.deepEqual(a, b, 'QP_AUTH_PROTECTED_RUNTIME_CHANGED');
  }
  const oldConfig = read(transition.beforeConfiguration), newConfig = read(transition.afterConfiguration);
  assert.equal(oldConfig.CASEOPS_MOBILE_V1_CONTROLS, '0'); assert.equal(newConfig.CASEOPS_MOBILE_V1_CONTROLS, '1');
  assert.equal(newConfig.CASEOPS_MOBILE_V1_PROFILE, QP.profile);
  assert.equal(newConfig.CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256, controls.gatewayImplementationEvidence.sha256);
  assert.equal(newConfig.CASEOPS_MOBILE_V1_REGISTRATION_SHA256, controls.registrationEvidence.sha256);
  assert.equal(newConfig.CASEOPS_MOBILE_V1_REGISTRATION, '/fixture-state/' + path.basename(controls.registrationEvidence.path));
  const stable = value => Object.fromEntries(Object.entries(value).filter(([key]) => !activationKeys.includes(key)));
  assert.deepEqual(stable(oldConfig), stable(newConfig), 'QP_AUTH_CONFIGURATION_CHANGED');
  for (const config of [oldConfig, newConfig]) {
    assert.equal(config.CASEOPS_MOBILE_PROJECT, after.project); assert.equal(config.CASEOPS_MOBILE_GATEWAY_RUN_ID, after.gatewayRunId);
    assert.equal(config.CASEOPS_MOBILE_API_SHA, source.sourceSha); assert.equal(config.CASEOPS_MOBILE_WEB_SHA, source.sourceSha);
  }
  const oldStatus = read(transition.beforeGatewayStatus), newStatus = read(transition.afterGatewayStatus);
  for (const state of [oldStatus, newStatus]) {
    checkLedger(state); assert.equal(state.runId, after.gatewayRunId);
    assert.equal(state.markerRejected, 0); assert.equal(state.routeRejected, 0);
    assert.equal(state.implementationSha256, after.gatewayImplementationSha256);
  }
  assert.equal(oldStatus.v1ControlsEnabled, false); assert.equal(newStatus.v1ControlsEnabled, true);
  assert.equal(newStatus.v1ControlProfile, QP.profile);
  assert.equal(newStatus.v1ControlsImplementationSha256, controls.gatewayImplementationEvidence.sha256);
  assert.equal(newStatus.v1RegistrationSha256, controls.registrationEvidence.sha256);
  const activation = read(transition.activationEvidence);
  assert.equal(activation.sourceSha, source.sourceSha); assert.equal(activation.project, after.project); assert.equal(activation.runId, after.gatewayRunId);
  assert.deepEqual(activation.finalDockerReceipt, q.dockerReceipt); assert.deepEqual(activation.registrationEvidence, controls.registrationEvidence);
  assert.deepEqual(activation.controlsEvidence, q.controlsEvidence); assert.equal(activation.actualActiveGateway, true);
  assert.equal(activation.actualNativeAcceptance, false); assert.ok(Number.isInteger(activation.secondsRemaining) && activation.secondsRemaining > 0 && activation.secondsRemaining <= 479);
  return transition.beforeDockerReceipt;
}
