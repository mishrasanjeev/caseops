import assert from 'node:assert/strict';
import path from 'node:path';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { createProducerStore } from './native-producer-host.mjs';

const root = path.resolve(fileURLToPath(new URL('../..', import.meta.url)));
const sha256 = /^[0-9a-f]{64}$/;
const sha40 = /^[0-9a-f]{40}$/;
const imageId = /^sha256:[0-9a-f]{64}$/;
const services = ['api', 'gateway', 'migrate', 'postgres', 'scanner', 'valkey', 'web'];
const proofNames = ['claim', 'before', 'creation', 'after', 'apiDatabase', 'postgresDatabase', 'serving'];
const pgImage = 'pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f';
const marker = 'no-paid-providers';
const maxLaunchMs = 15 * 60_000;
const maxEvidenceAgeMs = 60_000;

function exact(value, keys, code) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), code);
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort(), code);
}

function timestamp(value) {
  assert.ok(Number.isSafeInteger(value) && value > 0, 'V1_LAUNCH_TIMESTAMP_REQUIRED');
  return value;
}

function loopback(origin) {
  const url = new URL(origin);
  assert.ok(origin === url.origin && url.protocol === 'https:' && url.hostname === '127.0.0.1'
    && Number(url.port) >= 1024, 'V1_LAUNCH_LOOPBACK_TLS_REQUIRED');
}

function canonicalAbsolute(value) {
  return typeof value === 'string' && path.isAbsolute(value) && path.normalize(value) === value
    && value.length <= 1000 && !/[\r\n\0]/.test(value);
}

function daemonIdentity(value) {
  exact(value, ['id', 'socket'], 'V1_LAUNCH_DAEMON_REQUIRED');
  assert.match(value.id, /^[a-zA-Z0-9:-]{16,128}$/);
  exact(value.socket, ['path', 'device', 'inode', 'uid'], 'V1_LAUNCH_SOCKET_IDENTITY_REQUIRED');
  assert.ok(canonicalAbsolute(value.socket.path) && value.socket.path.endsWith('/docker.sock'), 'V1_LAUNCH_OWNED_SOCKET_REQUIRED');
  for (const key of ['device', 'inode', 'uid']) assert.match(value.socket[key], /^\d{1,24}$/);
}

function claimIdentity(claim, now) {
  exact(claim, ['schemaVersion', 'kind', 'runId', 'project', 'slug', 'sourceSha', 'claimedAtMs', 'expiresAtMs',
    'daemon', 'profile', 'backendRevision', 'webRevision', 'databaseRevision'], 'V1_LAUNCH_CLAIM_REQUIRED');
  assert.equal(claim.schemaVersion, 1);
  assert.equal(claim.kind, 'exclusive-v1-owned-launch-claim');
  assert.match(claim.runId, /^v1-[0-9a-f]{16,48}$/);
  assert.equal(claim.project, 'caseops-mobile-' + claim.runId);
  assert.equal(claim.slug, 'mobile-' + claim.runId);
  assert.match(claim.sourceSha, sha40);
  assert.ok(timestamp(claim.claimedAtMs) <= now && now < timestamp(claim.expiresAtMs)
    && claim.expiresAtMs - claim.claimedAtMs <= maxLaunchMs, 'V1_LAUNCH_CLAIM_STALE');
  daemonIdentity(claim.daemon);
  exact(claim.profile, ['name', 'repoRoot', 'cache', 'composeSha256', 'overlaySha256', 'projectedSha256'], 'V1_LAUNCH_PROFILE_REQUIRED');
  assert.equal(claim.profile.name, 'v1-governed-catalogue');
  assert.ok(canonicalAbsolute(claim.profile.repoRoot) && canonicalAbsolute(claim.profile.cache)
    && claim.profile.cache !== claim.profile.repoRoot
    && !claim.profile.cache.startsWith(claim.profile.repoRoot + path.sep), 'V1_LAUNCH_PROFILE_PATHS_REQUIRED');
  for (const key of ['composeSha256', 'overlaySha256', 'projectedSha256']) assert.match(claim.profile[key], sha256);
  for (const [field, service] of [['backendRevision', 'api'], ['webRevision', 'web']]) {
    assert.ok(typeof claim[field] === 'string' && claim[field].startsWith(claim.project + '-' + service + '-')
      && /^[a-z0-9-]{24,140}$/.test(claim[field]), 'V1_LAUNCH_LOCAL_REVISION_REQUIRED');
  }
  assert.match(claim.databaseRevision, /^\d{8}_\d{4}$/);
}

function checkCreation(claim, before, creation, digests, now) {
  exact(before, ['kind', 'claimSha256', 'daemon', 'project', 'observedAtMs', 'scope', 'containers',
    'volumes', 'networks'], 'V1_LAUNCH_BEFORE_PROOF_REQUIRED');
  assert.equal(before.kind, 'observed-v1-docker-before');
  assert.equal(before.claimSha256, digests.claim);
  assert.deepEqual(before.daemon, claim.daemon, 'V1_LAUNCH_DAEMON_CHANGED');
  assert.equal(before.project, claim.project);
  assert.equal(before.scope, 'exact-project-label-and-literal-resource-names');
  for (const key of ['containers', 'volumes', 'networks']) assert.deepEqual(before[key], [], 'V1_LAUNCH_PREEXISTING_RESOURCE');
  exact(creation, ['kind', 'claimSha256', 'beforeSha256', 'daemon', 'project', 'profile', 'startedAtMs',
    'completedAtMs', 'action', 'exitCode', 'containerIds', 'containerConfigHashes', 'volumeNames', 'networkIds', 'createEvents'], 'V1_LAUNCH_CREATION_EVIDENCE_REQUIRED');
  assert.equal(creation.kind, 'observed-v1-owned-compose-creation');
  assert.equal(creation.action, 'create-new-project-without-import');
  assert.equal(creation.exitCode, 0, 'V1_LAUNCH_CREATION_NOT_ACKNOWLEDGED');
  assert.equal(creation.claimSha256, digests.claim);
  assert.equal(creation.beforeSha256, digests.before, 'V1_LAUNCH_CREATION_ABSENCE_PROOF_CHANGED');
  assert.deepEqual(creation.daemon, claim.daemon, 'V1_LAUNCH_DAEMON_CHANGED');
  assert.equal(creation.project, claim.project);
  assert.deepEqual(creation.profile, claim.profile, 'V1_LAUNCH_PROFILE_CHANGED');
  assert.ok(claim.claimedAtMs <= timestamp(before.observedAtMs) && before.observedAtMs < timestamp(creation.startedAtMs)
    && creation.startedAtMs < timestamp(creation.completedAtMs) && creation.completedAtMs <= now, 'V1_LAUNCH_CREATION_ORDER_REFUSED');
  exact(creation.containerIds, services, 'V1_LAUNCH_CONTAINER_INVENTORY_REQUIRED');
  exact(creation.containerConfigHashes, services, 'V1_LAUNCH_CONTAINER_INVENTORY_REQUIRED');
  for (const hash of Object.values(creation.containerConfigHashes)) assert.match(hash, sha256);
  for (const id of Object.values(creation.containerIds)) assert.match(id, sha256);
  assert.equal(new Set(Object.values(creation.containerIds)).size, services.length);
  assert.deepEqual(creation.volumeNames, [claim.project + '_documents', claim.project + '_postgres']);
  exact(creation.networkIds, ['default', 'ingress'], 'V1_LAUNCH_NETWORK_INVENTORY_REQUIRED');
  for (const id of Object.values(creation.networkIds)) assert.match(id, sha256);
  assert.notEqual(creation.networkIds.default, creation.networkIds.ingress);
  const expected = new Set([
    ...Object.values(creation.containerIds).map(id => 'container:' + id),
    ...creation.volumeNames.map(name => 'volume:' + name),
    ...Object.values(creation.networkIds).map(id => 'network:' + id),
  ]);
  assert.ok(Array.isArray(creation.createEvents) && creation.createEvents.length === expected.size, 'V1_LAUNCH_CREATE_EVENTS_REQUIRED');
  for (const event of creation.createEvents) {
    exact(event, ['type', 'action', 'id', 'observedAtMs'], 'V1_LAUNCH_CREATE_EVENT_REQUIRED');
    assert.equal(event.action, 'create', 'V1_LAUNCH_CREATE_EVENT_REQUIRED');
    assert.ok(creation.startedAtMs <= timestamp(event.observedAtMs) && event.observedAtMs <= creation.completedAtMs,
      'V1_LAUNCH_CREATE_EVENT_OUTSIDE_ATTEMPT');
    assert.ok(expected.delete(event.type + ':' + event.id), 'V1_LAUNCH_CREATE_EVENT_IDENTITY_CHANGED');
  }
}

function checkDocker(claim, creation, after, digests, now) {
  exact(after, ['kind', 'creationSha256', 'daemon', 'project', 'profile', 'observedAtMs', 'containers', 'volumes',
    'networks', 'criticalBindMounts', 'postgresVolumeConsumers', 'apiEnvironment', 'unadmittedEnvironmentNames'], 'V1_LAUNCH_DOCKER_PROOF_REQUIRED');
  assert.equal(after.kind, 'observed-v1-docker-after');
  assert.equal(after.creationSha256, digests.creation);
  assert.deepEqual(after.daemon, claim.daemon, 'V1_LAUNCH_DAEMON_CHANGED');
  assert.equal(after.project, claim.project);
  assert.deepEqual(after.profile, claim.profile, 'V1_LAUNCH_PROFILE_CHANGED');
  assert.ok(creation.completedAtMs <= timestamp(after.observedAtMs) && after.observedAtMs <= now
    && now - after.observedAtMs <= maxEvidenceAgeMs, 'V1_LAUNCH_DOCKER_OBSERVATION_STALE');
  exact(after.containers, services, 'V1_LAUNCH_CONTAINER_INVENTORY_REQUIRED');
  for (const service of services) {
    const container = after.containers[service];
    exact(container, ['id', 'imageId', 'configuredImage', 'project', 'service', 'configHash', 'status', 'exitCode', 'networkIds',
      'publishedPorts'], 'V1_LAUNCH_CONTAINER_PROOF_REQUIRED');
    assert.equal(container.id, creation.containerIds[service], 'V1_LAUNCH_CONTAINER_CHANGED');
    assert.match(container.imageId, imageId);
    assert.ok(typeof container.configuredImage === 'string' && /^[a-zA-Z0-9_./:@-]{1,240}$/.test(container.configuredImage));
    if (service === 'postgres') assert.equal(container.configuredImage, pgImage, 'V1_LAUNCH_DB_IMAGE_REFUSED');
    assert.equal(container.project, claim.project);
    assert.equal(container.service, service);
    assert.equal(container.configHash, creation.containerConfigHashes[service], 'V1_LAUNCH_CONTAINER_CONFIGURATION_CHANGED');
    assert.equal(container.status, service === 'migrate' ? 'exited' : 'running');
    assert.equal(container.exitCode, 0);
    assert.deepEqual(container.networkIds, service === 'gateway'
      ? [creation.networkIds.default, creation.networkIds.ingress].sort()
      : [creation.networkIds.default], 'V1_LAUNCH_NETWORK_SCOPE_CHANGED');
    if (service !== 'gateway') assert.deepEqual(container.publishedPorts, [], 'V1_LAUNCH_PRIVATE_SERVICE_PUBLISHED');
  }
  exact(after.networks, ['default', 'ingress'], 'V1_LAUNCH_NETWORK_INVENTORY_REQUIRED');
  for (const network of ['default', 'ingress']) {
    assert.deepEqual(after.networks[network], { id: creation.networkIds[network], project: claim.project,
      name: claim.project + '_' + network, internal: network === 'default' }, 'V1_LAUNCH_NETWORK_SCOPE_CHANGED');
  }
  exact(after.volumes, ['documents', 'postgres'], 'V1_LAUNCH_VOLUME_INVENTORY_REQUIRED');
  for (const name of ['documents', 'postgres']) {
    const volume = after.volumes[name];
    exact(volume, ['name', 'project', 'serviceVolume', 'driver', 'scope', 'createdAtMs', 'options', 'attachedTo',
      'destination', 'readWrite', 'volumeMountpoint', 'containerMountSource'], 'V1_LAUNCH_VOLUME_PROOF_REQUIRED');
    assert.equal(volume.name, claim.project + '_' + name);
    assert.equal(volume.project, claim.project);
    assert.equal(volume.serviceVolume, name);
    assert.equal(volume.driver, 'local');
    assert.equal(volume.scope, 'local');
    assert.deepEqual(volume.options, {}, 'V1_LAUNCH_VOLUME_OPTIONS_REFUSED');
    assert.ok(Math.floor(creation.startedAtMs / 1000) * 1000 <= timestamp(volume.createdAtMs)
      && volume.createdAtMs <= creation.completedAtMs, 'V1_LAUNCH_VOLUME_STALE');
    assert.equal(volume.attachedTo, creation.containerIds[name === 'postgres' ? 'postgres' : 'api']);
    assert.equal(volume.destination, name === 'postgres' ? '/var/lib/postgresql/data' : '/app/storage');
    assert.equal(volume.readWrite, true);
    assert.ok(canonicalAbsolute(volume.volumeMountpoint)
      && volume.volumeMountpoint.endsWith('/' + volume.name + '/_data'), 'V1_LAUNCH_VOLUME_MOUNTPOINT_REQUIRED');
    assert.equal(volume.containerMountSource, volume.volumeMountpoint, 'V1_LAUNCH_VOLUME_MOUNT_CHANGED');
  }
  const fixtureMounts = [
    { source: claim.profile.cache, destination: '/fixture-state', readWrite: true },
    { source: path.join(claim.profile.repoRoot, 'scripts/mobile'), destination: '/mobile-fixture', readWrite: false },
  ];
  assert.deepEqual(after.criticalBindMounts, {
    api: fixtureMounts,
    gateway: fixtureMounts,
    postgres: [{ source: path.join(claim.profile.repoRoot, 'infra/postgres/init/00-extensions.sql'),
      destination: '/docker-entrypoint-initdb.d/00-extensions.sql', readWrite: false }],
  }, 'V1_LAUNCH_CRITICAL_MOUNTS_CHANGED');
  assert.deepEqual(after.postgresVolumeConsumers, [creation.containerIds.postgres], 'V1_LAUNCH_POSTGRES_VOLUME_SHARED');
  assert.deepEqual(after.unadmittedEnvironmentNames, [], 'V1_LAUNCH_ENVIRONMENT_REFUSED');
  const environment = after.apiEnvironment;
  exact(environment, ['caseopsEnv', 'releaseSha', 'revision', 'workspaceEnabled', 'governanceEnabled',
    'workspaceExpiresAtMs', 'governanceExpiresAtMs', 'blockedCompanySlugs'], 'V1_LAUNCH_PROJECTED_ENV_REQUIRED');
  assert.equal(environment.caseopsEnv, 'local');
  assert.equal(environment.releaseSha, claim.sourceSha);
  assert.equal(environment.revision, claim.backendRevision);
  assert.equal(environment.workspaceEnabled, true);
  assert.equal(environment.governanceEnabled, true);
  for (const expiry of [environment.workspaceExpiresAtMs, environment.governanceExpiresAtMs]) {
    assert.ok(now < timestamp(expiry) && expiry <= claim.expiresAtMs, 'V1_LAUNCH_LOCAL_ROLLOUT_EXPIRED');
  }
  assert.deepEqual(environment.blockedCompanySlugs, [claim.slug, 'test-legal', 'test-mobile-other'].sort(), 'V1_LAUNCH_NO_PAID_TENANT_REQUIRED');
}

function checkDatabases(claim, creation, after, api, postgres) {
  for (const [proof, service] of [[api, 'api'], [postgres, 'postgres']]) {
    exact(proof, ['kind', 'probeId', 'containerId', 'targetContainerId', 'observedAtMs', 'database',
      'databaseRevision', 'systemIdentifier', 'postmasterStartedAtMs', 'transactionReadOnly', 'serverVersionNum',
      'postgresImageId'], 'V1_LAUNCH_DB_PROOF_REQUIRED');
    assert.equal(proof.kind, 'observed-read-only-v1-db-' + service);
    assert.match(proof.probeId, sha256);
    assert.equal(proof.containerId, creation.containerIds[service], 'V1_LAUNCH_DB_OBSERVER_CHANGED');
    assert.equal(proof.targetContainerId, creation.containerIds.postgres, 'V1_LAUNCH_DB_TARGET_CHANGED');
    assert.ok(creation.completedAtMs <= timestamp(proof.observedAtMs) && proof.observedAtMs <= after.observedAtMs
      && after.observedAtMs - proof.observedAtMs <= maxEvidenceAgeMs, 'V1_LAUNCH_DB_OBSERVATION_STALE');
    assert.equal(proof.transactionReadOnly, true, 'V1_LAUNCH_DB_PROBE_NOT_READ_ONLY');
    assert.equal(proof.database, 'caseops_mobile', 'V1_LAUNCH_DB_NAME_REFUSED');
    assert.equal(proof.databaseRevision, claim.databaseRevision, 'V1_LAUNCH_DB_REVISION_CHANGED');
    assert.equal(proof.postgresImageId, after.containers.postgres.imageId, 'V1_LAUNCH_DB_IMAGE_REFUSED');
    assert.ok(Number.isSafeInteger(proof.serverVersionNum) && proof.serverVersionNum >= 170000
      && proof.serverVersionNum < 180000, 'V1_LAUNCH_DB_VERSION_REFUSED');
    assert.match(proof.systemIdentifier, /^\d{17,19}$/, 'V1_LAUNCH_DB_SYSTEM_ID_REQUIRED');
    // PostgreSQL 17 BootStrapXLOG encodes the initdb epoch seconds in the upper 32 bits.
    // A fresh Docker volume and matching new postmaster do not detect a physical clone.
    const initializedAtMs = Number(BigInt(proof.systemIdentifier) >> 32n) * 1000;
    assert.ok(Math.floor(after.volumes.postgres.createdAtMs / 1000) * 1000 <= initializedAtMs
      && initializedAtMs <= timestamp(proof.postmasterStartedAtMs)
      && proof.postmasterStartedAtMs <= proof.observedAtMs, 'V1_LAUNCH_DB_CLONED_OR_STALE');
  }
  assert.notEqual(api.probeId, postgres.probeId, 'V1_LAUNCH_DB_INDEPENDENT_PROOFS_REQUIRED');
  for (const key of ['systemIdentifier', 'postmasterStartedAtMs', 'database', 'databaseRevision', 'serverVersionNum']) {
    assert.equal(api[key], postgres[key], 'V1_LAUNCH_DB_PEER_MISMATCH');
  }
}

function checkServing(claim, creation, after, serving) {
  exact(serving, ['kind', 'gatewayContainerId', 'runId', 'observedAtMs', 'marker', 'strictTLS', 'api', 'web'],
    'V1_LAUNCH_SERVING_PROOF_REQUIRED');
  assert.equal(serving.kind, 'observed-marked-v1-serving');
  assert.equal(serving.gatewayContainerId, creation.containerIds.gateway);
  assert.equal(serving.runId, claim.runId);
  assert.equal(serving.marker, marker);
  assert.equal(serving.strictTLS, true);
  assert.ok(creation.completedAtMs <= timestamp(serving.observedAtMs) && serving.observedAtMs <= after.observedAtMs
    && after.observedAtMs - serving.observedAtMs <= maxEvidenceAgeMs, 'V1_LAUNCH_SERVING_OBSERVATION_STALE');
  for (const [proof, route, revision] of [[serving.api, '/api/build', claim.backendRevision],
    [serving.web, '/api/release-identity', claim.webRevision]]) {
    exact(proof, ['origin', 'route', 'status', 'sourceSha', 'revision'], 'V1_LAUNCH_SERVING_IDENTITY_REQUIRED');
    loopback(proof.origin);
    assert.equal(proof.route, route);
    assert.equal(proof.status, 200);
    assert.equal(proof.sourceSha, claim.sourceSha);
    assert.equal(proof.revision, revision, 'V1_LAUNCH_SERVING_REVISION_CHANGED');
  }
  assert.notEqual(serving.api.origin, serving.web.origin, 'V1_LAUNCH_DISTINCT_SERVING_ORIGINS_REQUIRED');
  assert.deepEqual(after.containers.gateway.publishedPorts, {
    '8443/tcp': [{ hostIp: '127.0.0.1', hostPort: Number(new URL(serving.api.origin).port) }],
    '3443/tcp': [{ hostIp: '127.0.0.1', hostPort: Number(new URL(serving.web.origin).port) }],
  }, 'V1_LAUNCH_GATEWAY_PORTS_CHANGED');
}

export function reconcileV1LaunchEvidence(input, digests, now = Date.now()) {
  exact(input, proofNames, 'V1_LAUNCH_COMPLETE_EVIDENCE_REQUIRED');
  exact(digests, proofNames, 'V1_LAUNCH_EVIDENCE_DIGESTS_REQUIRED');
  for (const hash of Object.values(digests)) assert.match(hash, sha256);
  assert.equal(new Set(Object.values(digests)).size, proofNames.length, 'V1_LAUNCH_DISTINCT_EVIDENCE_REQUIRED');
  const { claim, before, creation, after, apiDatabase, postgresDatabase, serving } = input;
  claimIdentity(claim, timestamp(now));
  checkCreation(claim, before, creation, digests, now);
  checkDocker(claim, creation, after, digests, now);
  checkDatabases(claim, creation, after, apiDatabase, postgresDatabase);
  checkServing(claim, creation, after, serving);
  return { schemaVersion: 1, kind: 'non-authorizing-v1-launch-evidence-review', readyForLive: false,
    authorizesDatabaseWrites: false, realRuntimeVerified: false, evidenceReconciled: true, project: claim.project,
    runId: claim.runId, sourceSha: claim.sourceSha, evidenceSha256: { ...digests } };
}

export function reviewV1LaunchEvidence(cache, manifest, manifestSha256, now = Date.now()) {
  assert.ok(path.isAbsolute(cache) && realpathSync(cache) === cache && cache !== root
    && !cache.startsWith(root + path.sep), 'V1_LAUNCH_PRIVATE_EXTERNAL_CACHE_REQUIRED');
  const store = createProducerStore(cache);
  const read = (name, sha) => {
    assert.match(name, /^[a-zA-Z0-9][a-zA-Z0-9.-]{0,120}\.json$/);
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(verifiedFile(path.join(cache, name), sha, 131072)));
  };
  const refs = read(manifest, manifestSha256);
  exact(refs, proofNames, 'V1_LAUNCH_COMPLETE_EVIDENCE_REQUIRED');
  const input = {}, digests = {}, names = new Set([manifest]);
  for (const key of proofNames) {
    const ref = refs[key];
    exact(ref, ['name', 'sha256'], 'V1_LAUNCH_EVIDENCE_REFERENCE_REQUIRED');
    assert.ok(!names.has(ref.name), 'V1_LAUNCH_DISTINCT_EVIDENCE_REQUIRED');
    names.add(ref.name);
    digests[key] = ref.sha256;
    input[key] = read(ref.name, ref.sha256);
  }
  return store.write('v1-launch-evidence-review.json', {
    ...reconcileV1LaunchEvidence(input, digests, now), manifestSha256,
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    assert.equal(process.argv.length, 5);
    console.log(JSON.stringify(reviewV1LaunchEvidence(process.argv[2], process.argv[3], process.argv[4])));
  } catch {
    console.error('V1_LAUNCH_EVIDENCE_REVIEW_REFUSED');
    process.exitCode = 1;
  }
}
