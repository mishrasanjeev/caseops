import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { reconcileV1LaunchEvidence, reviewV1LaunchEvidence } from './v1-launch-attestor.mjs';

const start = Date.parse('2026-11-08T12:00:00Z');
const now = start + 36_000;
const services = ['api', 'gateway', 'migrate', 'postgres', 'scanner', 'valkey', 'web'];
const pg = 'pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const systemId = time => ((BigInt(Math.floor(time / 1000)) << 32n) + 1234n).toString();

function fixture() {
  const runId = 'v1-' + 'a'.repeat(20), project = 'caseops-mobile-' + runId, slug = 'mobile-' + runId;
  const sourceSha = 'a'.repeat(40), backendRevision = project + '-api-sha', webRevision = project + '-web-sha';
  const daemon = { id: 'example-local-daemon-1234', socket: { path: '/tmp/fixture/docker.sock', device: '4', inode: '54', uid: '501' } };
  const profile = { name: 'v1-governed-catalogue', repoRoot: '/tmp/fixture/source', cache: '/tmp/fixture/cache', composeSha256: hash('compose'), overlaySha256: hash('overlay'),
    projectedSha256: hash('projection') };
  const containerIds = Object.fromEntries(services.map(name => [name, hash('container-' + name)]));
  const containerConfigHashes = Object.fromEntries(services.map(name => [name, hash('config-' + name)]));
  const networkIds = { default: hash('private'), ingress: hash('ingress') };
  const volumeNames = [project + '_documents', project + '_postgres'];
  const digests = Object.fromEntries(['claim', 'before', 'creation', 'after', 'apiDatabase', 'postgresDatabase', 'serving']
    .map(key => [key, hash(key)]));
  const claim = { schemaVersion: 1, kind: 'exclusive-v1-owned-launch-claim', runId, project, slug, sourceSha,
    claimedAtMs: start, expiresAtMs: start + 120_000, daemon, profile, backendRevision, webRevision, databaseRevision: '20261108_0003' };
  const before = { kind: 'observed-v1-docker-before', claimSha256: digests.claim, daemon, project,
    observedAtMs: start + 1000, scope: 'exact-project-label-and-literal-resource-names', containers: [], volumes: [], networks: [] };
  const creation = { kind: 'observed-v1-owned-compose-creation', claimSha256: digests.claim, beforeSha256: digests.before,
    daemon, project, profile, startedAtMs: start + 2000, completedAtMs: start + 30_000,
    action: 'create-new-project-without-import', exitCode: 0, containerIds, containerConfigHashes, volumeNames, networkIds,
    createEvents: [['container', Object.values(containerIds)], ['volume', volumeNames], ['network', Object.values(networkIds)]]
      .flatMap(([type, ids]) => ids.map(id => ({ type, id, action: 'create', observedAtMs: start + 3000 }))) };
  const fixtureMounts = () => [
    { source: profile.cache, destination: '/fixture-state', readWrite: true },
    { source: profile.repoRoot + '/scripts/mobile', destination: '/mobile-fixture', readWrite: false },
  ];
  const after = { kind: 'observed-v1-docker-after', creationSha256: digests.creation, daemon, project, profile, observedAtMs: start + 35_000,
    containers: Object.fromEntries(services.map(service => [service, {
      id: containerIds[service], imageId: 'sha256:' + hash('image-' + service), configuredImage: service === 'postgres' ? pg : 'fixture:local',
      project, service, configHash: containerConfigHashes[service], status: service === 'migrate' ? 'exited' : 'running', exitCode: 0,
      networkIds: service === 'gateway' ? Object.values(networkIds).sort() : [networkIds.default],
      publishedPorts: service === 'gateway' ? { '8443/tcp': [{ hostIp: '127.0.0.1', hostPort: 8443 }],
        '3443/tcp': [{ hostIp: '127.0.0.1', hostPort: 3443 }] } : [],
    }])),
    volumes: Object.fromEntries(['postgres', 'documents'].map(name => [name, {
      name: project + '_' + name, project, serviceVolume: name, driver: 'local', scope: 'local', createdAtMs: start + 3000,
      options: {}, attachedTo: containerIds[name === 'postgres' ? 'postgres' : 'api'],
      destination: name === 'postgres' ? '/var/lib/postgresql/data' : '/app/storage', readWrite: true,
      volumeMountpoint: '/var/lib/docker/volumes/' + project + '_' + name + '/_data',
      containerMountSource: '/var/lib/docker/volumes/' + project + '_' + name + '/_data',
    }])),
    networks: Object.fromEntries(['default', 'ingress'].map(name => [name, {
      id: networkIds[name], project, name: project + '_' + name, internal: name === 'default',
    }])),
    criticalBindMounts: { api: fixtureMounts(), gateway: fixtureMounts(), postgres: [{
      source: profile.repoRoot + '/infra/postgres/init/00-extensions.sql',
      destination: '/docker-entrypoint-initdb.d/00-extensions.sql', readWrite: false,
    }] },
    postgresVolumeConsumers: [containerIds.postgres], unadmittedEnvironmentNames: [],
    apiEnvironment: { caseopsEnv: 'local', releaseSha: sourceSha, revision: backendRevision, workspaceEnabled: true,
      governanceEnabled: true, workspaceExpiresAtMs: start + 120_000, governanceExpiresAtMs: start + 120_000,
      blockedCompanySlugs: [slug, 'test-legal', 'test-mobile-other'].sort() },
  };
  const database = service => ({ kind: 'observed-read-only-v1-db-' + service, probeId: hash('probe-' + service),
    containerId: containerIds[service], targetContainerId: containerIds.postgres, observedAtMs: start + 33_000, database: 'caseops_mobile',
    databaseRevision: claim.databaseRevision, systemIdentifier: systemId(start + 5000), postmasterStartedAtMs: start + 10_000,
    transactionReadOnly: true, serverVersionNum: 170011, postgresImageId: after.containers.postgres.imageId });
  const serving = { kind: 'observed-marked-v1-serving', gatewayContainerId: containerIds.gateway, runId,
    observedAtMs: start + 34_000, marker: 'no-paid-providers', strictTLS: true,
    api: { origin: 'https://127.0.0.1:8443', route: '/api/build', status: 200, sourceSha, revision: backendRevision },
    web: { origin: 'https://127.0.0.1:3443', route: '/api/release-identity', status: 200, sourceSha, revision: webRevision } };
  return { input: structuredClone({ claim, before, creation, after, apiDatabase: database('api'),
    postgresDatabase: database('postgres'), serving }), digests };
}

test('reconciled modeled evidence always yields a non-authorizing offline receipt', () => {
  const { input, digests } = fixture();
  const result = reconcileV1LaunchEvidence(input, digests, now);
  assert.equal(result.evidenceReconciled, true);
  assert.equal(result.authorizesDatabaseWrites, false);
  assert.equal(result.readyForLive, false);
  assert.equal(result.realRuntimeVerified, false);
  assert.deepEqual(result.evidenceSha256, digests);
});

const rejected = [
  ['preexisting named volume', (i) => { i.before.volumes.push(i.creation.volumeNames[1]); }, /PREEXISTING_RESOURCE/],
  ['missing actual creation record', (i) => { i.creation = null; }, /CREATION_EVIDENCE_REQUIRED/],
  ['missing daemon create event', (i) => { i.creation.createEvents.pop(); }, /CREATE_EVENTS_REQUIRED/],
  ['replayed daemon create event', (i) => { i.creation.createEvents[1] = i.creation.createEvents[0]; }, /CREATE_EVENT_IDENTITY_CHANGED/],
  ['stale daemon create event', (i) => { i.creation.createEvents[0].observedAtMs = start; }, /CREATE_EVENT_OUTSIDE_ATTEMPT/],
  ['unbound creation record', (i) => { i.creation.beforeSha256 = hash('another sample'); }, /CREATION_ABSENCE_PROOF_CHANGED/],
  ['creation before absence observation', (i) => { i.creation.startedAtMs = i.before.observedAtMs; }, /CREATION_ORDER_REFUSED/],
  ['changed daemon socket', (i) => { i.after.daemon = { ...i.after.daemon, socket: { ...i.after.daemon.socket, inode: '99' } }; }, /DAEMON_CHANGED/],
  ['wrong Compose profile', (i) => { i.after.profile = { ...i.after.profile, overlaySha256: hash('foreign-overlay') }; }, /PROFILE_CHANGED/],
  ['changed container configuration', (i) => { i.after.containers.api.configHash = hash('unbound-config'); }, /CONTAINER_CONFIGURATION_CHANGED/],
  ['different Docker volume mount', (i) => { i.after.volumes.postgres.containerMountSource = '/tmp/another-data'; }, /VOLUME_MOUNT_CHANGED/],
  ['unexpected PostgreSQL initialization mount', (i) => {
    i.after.criticalBindMounts.postgres[0].readWrite = true;
  }, /CRITICAL_MOUNTS_CHANGED/],
  ['retained Docker volume', (i) => { i.after.volumes.postgres.createdAtMs = start - 1000; }, /VOLUME_STALE/],
  ['foreign stopped volume attachment', (i) => { i.after.postgresVolumeConsumers.push(hash('other-stopped-container')); }, /POSTGRES_VOLUME_SHARED/],
  ['old data cloned into the new Docker volume', (i) => {
    i.apiDatabase.systemIdentifier = systemId(start - 24 * 60 * 60_000);
    i.postgresDatabase.systemIdentifier = i.apiDatabase.systemIdentifier;
  }, /DB_CLONED_OR_STALE/],
  ['stale DB observation', (i) => { i.apiDatabase.observedAtMs = start + 1000; }, /DB_OBSERVATION_STALE/],
  ['wrong database name', (i) => { i.apiDatabase.database = 'postgres'; }, /DB_NAME_REFUSED/],
  ['wrong database identity', (i) => { i.apiDatabase.targetContainerId = hash('foreign-db'); }, /DB_TARGET_CHANGED/],
  ['wrong database image', (i) => { i.after.containers.postgres.configuredImage = 'postgres:17'; }, /DB_IMAGE_REFUSED/],
  ['wrong database revision', (i) => { i.apiDatabase.databaseRevision = '20261108_0002'; }, /DB_REVISION_CHANGED/],
  ['conflicting live system identifiers', (i) => { i.apiDatabase.systemIdentifier = systemId(start + 6000); }, /DB_PEER_MISMATCH/],
  ['duplicated database observation', (i) => { i.apiDatabase.probeId = i.postgresDatabase.probeId; }, /DB_INDEPENDENT_PROOFS_REQUIRED/],
  ['read-write database probe', (i) => { i.apiDatabase.transactionReadOnly = false; }, /DB_PROBE_NOT_READ_ONLY/],
  ['expired local rollout', (i) => { i.after.apiEnvironment.governanceExpiresAtMs = now; }, /LOCAL_ROLLOUT_EXPIRED/],
  ['missing no-paid tenant fence', (i) => { i.after.apiEnvironment.blockedCompanySlugs.shift(); }, /NO_PAID_TENANT_REQUIRED/],
  ['unexpected cloud/provider setting', (i) => { i.after.unadmittedEnvironmentNames.push('K_SERVICE'); }, /ENVIRONMENT_REFUSED/],
  ['off-host gateway port', (i) => { i.after.containers.gateway.publishedPorts['8443/tcp'][0].hostIp = '0.0.0.0'; }, /GATEWAY_PORTS_CHANGED/],
  ['wrong backend serving revision', (i) => { i.serving.api.revision = 'foreign'; }, /SERVING_REVISION_CHANGED/],
];
for (const [name, mutate, diagnostic] of rejected) {
  test('rejects ' + name, () => {
    const { input, digests } = fixture();
    mutate(input);
    assert.throws(() => reconcileV1LaunchEvidence(input, digests, now), diagnostic);
  });
}

test('refuses a stale otherwise internally consistent claim', () => {
  const { input, digests } = fixture();
  assert.throws(() => reconcileV1LaunchEvidence(input, digests, start + 121_000), /CLAIM_STALE/);
});

test('reads descriptor-verified distinct inputs and publishes only an exclusive review file', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'v1-launch-test-'));
  const cache = realpathSync(directory);
  try {
    const { input, digests } = fixture();
    const write = (key, value) => {
      const name = key + '.json', bytes = Buffer.from(JSON.stringify(value));
      writeFileSync(path.join(cache, name), bytes, { mode: 0o600 });
      return { name, sha256: hash(bytes) };
    };
    const refs = {};
    refs.claim = write('claim', input.claim);
    input.before.claimSha256 = refs.claim.sha256;
    refs.before = write('before', input.before);
    input.creation.claimSha256 = refs.claim.sha256;
    input.creation.beforeSha256 = refs.before.sha256;
    refs.creation = write('creation', input.creation);
    input.after.creationSha256 = refs.creation.sha256;
    for (const key of Object.keys(digests).slice(3)) refs[key] = write(key, input[key]);
    const manifest = write('manifest', refs);
    assert.throws(() => reviewV1LaunchEvidence(cache, manifest.name, hash('wrong-manifest'), now), /EVIDENCE_CHANGED/);
    const review = reviewV1LaunchEvidence(cache, manifest.name, manifest.sha256, now);
    const receipt = JSON.parse(readFileSync(review.path));
    assert.equal(receipt.authorizesDatabaseWrites, false);
    assert.equal(receipt.manifestSha256, manifest.sha256);
    assert.equal(receipt.evidenceSha256.creation, refs.creation.sha256);
    assert.throws(() => reviewV1LaunchEvidence(cache, manifest.name, manifest.sha256, now), /EEXIST/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
