import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash, randomUUID, X509Certificate } from 'node:crypto';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { androidFilesInventory as inventory, androidFilesScenarios as scenarios, collectAndroidFiles,
  validateAndroidFileAsset, validateAndroidFilesContext, validateAndroidPicker, validateAndroidSourceSeed } from '../../apps/mobile/e2e/android-files.mjs';
import { authenticate } from '../../apps/mobile/e2e/browser-handoff.mjs';
import { FixtureUnavailable, validateBuildReceipt, validateCoreFixture } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { attestAndroidBinary } from '../../apps/mobile/e2e/installed-android.mjs';
import { androidSessionTransport, verifyAndroidSessionTransport } from '../../apps/mobile/e2e/local-run.mjs';
import { restart } from '../../apps/mobile/e2e/native-ui.mjs';
import { appiumSessionEvent, configureNativeDriver } from '../../apps/mobile/e2e/run-state.mjs';
import { binaryHash, Journal, localJson, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';
import { attestAndroidFilesContainers, snapshotAndroidFilesPrivacy } from './android-files-privacy.mjs';

export function captureAndroidFilesPrivacy(options, phase, snapshot = snapshotAndroidFilesPrivacy) {
  assert.ok(['preflight', 'checkpoint', 'postflight'].includes(phase), 'ANDROID_FILES_PRIVACY_PHASE_REQUIRED');
  const result = snapshot({ ...options, verifyProviderBytes: phase === 'postflight' }), value = result.snapshot;
  assert.equal(value.schemaVersion, 2, 'ANDROID_FILES_COLD_PRIVACY_SCHEMA_REQUIRED');
  assert.equal(value.complete, true, 'ANDROID_FILES_COMPLETE_PRIVACY_SCAN_REQUIRED');
  assert.equal(value.providerMetadataPreserved, true, 'ANDROID_FILES_PROVIDER_METADATA_CHANGED');
  assert.equal(value.providerByteVerification, phase === 'postflight' ? 'postflight' : 'deferred-until-postflight', 'ANDROID_FILES_PROVIDER_VERIFICATION_PHASE_MISMATCH');
  assert.equal(value.providerOriginalsRead, phase === 'postflight', 'ANDROID_FILES_PROVIDER_READ_PHASE_MISMATCH');
  assert.equal(value.providerOriginalsPreserved, phase === 'postflight' ? true : null, 'ANDROID_FILES_PROVIDER_ORIGINALS_CHANGED');
  assert.equal(value.counts.ownedStagingFiles, 0, 'ANDROID_FILES_OWNED_STAGING_REMAINS');
  assert.equal(value.counts.privateAssetMatchCount, 0, 'ANDROID_FILES_PRIVATE_COPY_REMAINS');
  return result;
}

const root = fileURLToPath(new URL('../../', import.meta.url));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const readRef = ref => JSON.parse(verifiedFile(ref?.path, ref?.sha256));
const ref = file => ({ path: file, sha256: hash(readFileSync(file)) });
const KINDS = ['txt', 'pdf', 'png', 'jpeg', 'docx'];
function newJson(file, value) { writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, { flag: 'wx', mode: 0o600 }); return ref(file); }

export function assembleAndroidFilesFixture({ coreFixture, manifestEvidence, providerEvidence, pickerEvidence, filesCache,
  priorStagingEvidence = [], priorManifestEvidence = [] }) {
  const manifest = readRef(manifestEvidence), staged = readRef(providerEvidence), picker = readRef(pickerEvidence);
  assert.equal(manifest.kind, 'android-files-synthetic-fixtures', 'ANDROID_FILES_MANIFEST_REQUIRED');
  assert.equal(manifest.platform, 'android', 'ANDROID_FILES_MANIFEST_PLATFORM_REQUIRED');
  assert.equal(manifest.syntheticDataOnly, true, 'ANDROID_FILES_SYNTHETIC_MANIFEST_REQUIRED');
  assert.equal(manifest.backendSha, coreFixture.backendSha, 'ANDROID_FILES_MANIFEST_BACKEND_MISMATCH');
  assert.equal(manifest.backendRevision, coreFixture.backendRevision, 'ANDROID_FILES_MANIFEST_REVISION_MISMATCH');
  const isolation = readRef(coreFixture.isolationEvidence), original = readRef(manifest.isolationReceipt);
  assert.equal(original.platform, 'android', 'ANDROID_FILES_ORIGINAL_ISOLATION_PLATFORM_REQUIRED');
  for (const key of ['project', 'backendSha', 'backendRevision', 'webSha']) assert.equal(original[key], isolation[key], 'ANDROID_FILES_MANIFEST_ISOLATION_MISMATCH');
  assert.equal(manifest.companyId, coreFixture.companyId, 'ANDROID_FILES_MANIFEST_TENANT_MISMATCH');
  assert.equal(manifest.matter?.id, coreFixture.matter?.id, 'ANDROID_FILES_MANIFEST_MATTER_MISMATCH');
  assert.equal(manifest.source?.matterId, coreFixture.matter?.id, 'ANDROID_FILES_MANIFEST_SOURCE_REQUIRED');
  assert.equal(staged.kind, 'android-files-provider-assets', 'ANDROID_FILES_PROVIDER_RECEIPT_REQUIRED');
  for (const [key, expected] of Object.entries({ schemaVersion: 2, observed: true, platform: 'android', providerOriginalsRead: false }))
    assert.equal(staged[key], expected, 'ANDROID_FILES_OBSERVED_PROVIDER_RECEIPT_REQUIRED');
  for (const key of ['udid', 'appId']) assert.equal(staged[key], coreFixture[key], 'ANDROID_FILES_PROVIDER_DEVICE_MISMATCH');
  assert.deepEqual(staged.manifestEvidence, manifestEvidence, 'ANDROID_FILES_PROVIDER_MANIFEST_MISMATCH');
  const metadata = assets => assets.map(({ id, filename, sha256, sizeBytes }) => ({ id, filename, sha256, sizeBytes }))
    .sort((left, right) => left.filename.localeCompare(right.filename));
  assert.deepEqual(metadata(staged.assets), metadata(manifest.assets), 'ANDROID_FILES_COMPLETE_PROVIDER_COHORT_REQUIRED');
  assert.equal(picker.folderName, staged.folderName, 'ANDROID_FILES_OBSERVED_FOLDER_MISMATCH');
  assert.ok(path.isAbsolute(filesCache || ''), 'ANDROID_FILES_ABSOLUTE_CACHE_REQUIRED');
  assert.ok(Array.isArray(priorStagingEvidence) && priorStagingEvidence.length <= 4 && Array.isArray(priorManifestEvidence)
    && priorManifestEvidence.length <= 4, 'ANDROID_FILES_PRIOR_COHORT_BOUND');
  assert.equal(priorStagingEvidence.length, priorManifestEvidence.length, 'ANDROID_FILES_PAIRED_PRIOR_COHORTS_REQUIRED');
  const manifestRefs = [manifestEvidence, ...priorManifestEvidence], stageRefs = [providerEvidence, ...priorStagingEvidence];
  for (const references of [manifestRefs, stageRefs]) {
    assert.equal(new Set(references.map(value => value.path)).size, references.length, 'ANDROID_FILES_UNIQUE_COHORT_REFERENCES_REQUIRED');
    assert.equal(new Set(references.map(value => value.sha256)).size, references.length, 'ANDROID_FILES_UNIQUE_COHORT_REFERENCES_REQUIRED');
  }
  const folders = new Set([staged.folderName]);
  for (const [index, reference] of priorStagingEvidence.entries()) {
    const previous = readRef(reference), previousManifest = readRef(priorManifestEvidence[index]);
    assert.deepEqual(previous.manifestEvidence, priorManifestEvidence[index], 'ANDROID_FILES_PAIRED_PRIOR_MANIFEST_MISMATCH');
    for (const [key, expected] of Object.entries({ schemaVersion: 2, kind: 'android-files-provider-assets', observed: true, providerOriginalsRead: false,
      platform: 'android', udid: coreFixture.udid, appId: coreFixture.appId })) assert.equal(previous[key], expected, 'ANDROID_FILES_PRIOR_PROVIDER_IDENTITY_MISMATCH');
    assert.equal(previousManifest.kind, 'android-files-synthetic-fixtures', 'ANDROID_FILES_PRIOR_MANIFEST_REQUIRED');
    assert.equal(previousManifest.platform, 'android', 'ANDROID_FILES_PRIOR_MANIFEST_REQUIRED');
    assert.equal(previousManifest.syntheticDataOnly, true, 'ANDROID_FILES_PRIOR_MANIFEST_REQUIRED');
    assert.deepEqual(metadata(previous.assets), metadata(previousManifest.assets), 'ANDROID_FILES_COMPLETE_PROVIDER_COHORT_REQUIRED');
    assert.equal(folders.has(previous.folderName), false, 'ANDROID_FILES_UNIQUE_PROVIDER_COHORT_REQUIRED'); folders.add(previous.folderName);
  }
  const uploads = Object.fromEntries(KINDS.map(kind => {
    const selected = manifest.assets.filter(value => value.id === kind);
    assert.equal(selected.length, 1, 'ANDROID_FILES_EXACT_CLEAN_ASSET_INVENTORY_REQUIRED');
    const asset = { ...selected[0], ...(kind === 'txt' ? { text: verifiedFile(selected[0].path, selected[0].sha256, 262144).toString('utf8') } : {}),
      ...(kind === 'pdf' ? { pages: selected[0].expected?.pages } : {}) };
    return [kind, asset];
  }));
  const fixture = { ...structuredClone(coreFixture), filesInventory: inventory.inventoryId, filesCache,
    files: { manifestEvidence, providerEvidence, pickerEvidence, priorStagingEvidence, priorManifestEvidence,
      source: manifest.source, uploads, provider: { folderName: staged.folderName, evidence: pickerEvidence } } };
  validateAndroidSourceSeed(fixture, manifest.source);
  const context = { fixture, assets: fixture.files, provider: fixture.files.provider };
  for (const kind of KINDS) validateAndroidPicker(context, validateAndroidFileAsset(context, kind));
  return fixture;
}

export function androidFilesHarnessFingerprint() {
  const files = ['scripts/mobile/run-android-files.mjs', 'scripts/mobile/android-files-privacy.mjs', 'scripts/mobile/source-snapshot.mjs',
    'scripts/mobile/prepare-android-files-fixture.py', 'scripts/mobile/admit-android-file-source.py',
    ...readdirSync(path.join(root, 'apps/mobile/e2e')).filter(file => file.endsWith('.mjs')).map(file => `apps/mobile/e2e/${file}`)];
  const digest = createHash('sha256');
  for (const file of files.sort()) digest.update(`${file}\0${hash(readFileSync(path.join(root, file)))}\0`);
  return digest.digest('hex');
}
export function assertStrictAndroidFilesEnvironment(fixture, environment = process.env) {
  assert.notEqual(environment.NODE_TLS_REJECT_UNAUTHORIZED, '0', 'ANDROID_FILES_STRICT_TLS_REQUIRED');
  assert.equal(environment.NODE_EXTRA_CA_CERTS, fixture.publicCa?.path, 'ANDROID_FILES_EXACT_PUBLIC_CA_REQUIRED');
  const certificate = new X509Certificate(verifiedFile(fixture.publicCa?.path, fixture.publicCa?.sha256, 131072));
  assert.equal(certificate.ca, true, 'ANDROID_FILES_PUBLIC_CA_REQUIRED');
  assert.ok(Date.parse(certificate.validFrom) < Date.now() && Date.now() < Date.parse(certificate.validTo), 'ANDROID_FILES_CURRENT_CA_REQUIRED');
  const receipt = readRef(fixture.isolationEvidence);
  assert.equal(receipt.platform, 'android', 'ANDROID_FILES_ANDROID_ISOLATION_REQUIRED');
  assert.equal(receipt.publicCA, fixture.publicCa.path, 'ANDROID_FILES_CA_ISOLATION_MISMATCH');
  assert.equal(receipt.tlsProof?.strictDefaultTLS, true, 'ANDROID_FILES_STRICT_TLS_PROOF_REQUIRED');
  assert.equal(receipt.tlsProof?.verificationDisabled, false, 'ANDROID_FILES_STRICT_TLS_PROOF_REQUIRED'); return receipt;
}
export function validateAndroidFilesContainers(receipt, observed) {
  assert.ok(Array.isArray(receipt.containers) && receipt.containers.length >= 3 && receipt.containers.length <= 16, 'ANDROID_FILES_OWNED_CONTAINER_INVENTORY_REQUIRED');
  assert.equal(observed.length, receipt.containers.length, 'ANDROID_FILES_CONTAINER_INVENTORY_CHANGED');
  for (const expected of receipt.containers) {
    const selected = observed.filter(value => value.Id === expected.id); assert.equal(selected.length, 1, 'ANDROID_FILES_CONTAINER_ID_CHANGED');
    const actual = selected[0]; assert.equal(actual.Image, expected.image, 'ANDROID_FILES_CONTAINER_IMAGE_CHANGED');
    assert.equal(actual.Name, expected.name, 'ANDROID_FILES_CONTAINER_NAME_CHANGED');
    if (actual.Service === 'migrate' && expected.name === `/${receipt.project}-migrate-1`) {
      assert.equal(actual.Running, false, 'ANDROID_FILES_MIGRATION_NOT_COMPLETED');
      assert.equal(actual.Status, 'exited', 'ANDROID_FILES_MIGRATION_NOT_COMPLETED');
      assert.equal(actual.ExitCode, 0, 'ANDROID_FILES_MIGRATION_FAILED');
    } else {
      assert.equal(actual.Running, true, 'ANDROID_FILES_CONTAINER_STOPPED');
      assert.equal(actual.Status, 'running', 'ANDROID_FILES_CONTAINER_NOT_RUNNING');
    }
    assert.equal(actual.Project, receipt.project, 'ANDROID_FILES_FOREIGN_CONTAINER');
    assert.deepEqual([...actual.Networks].sort(), [...expected.networks].sort(), 'ANDROID_FILES_CONTAINER_NETWORK_CHANGED');
  }
  return observed;
}
export function bindAndroidFilesPrivateRoots(previous, actual) {
  for (const key of ['udid', 'appId', 'bootId', 'avdName', 'rootUid', 'packageUid']) assert.equal(actual[key], previous[key], 'ANDROID_FILES_PRIVATE_RUNTIME_CHANGED');
  for (const key of ['appData', 'provider', ...(previous.externalAppData ? ['externalAppData'] : [])]) {
    assert.equal(actual[key]?.path, previous[key].path, 'ANDROID_FILES_PRIVATE_ROOT_CHANGED');
    for (const field of ['kind', 'uid', 'device', 'inode']) assert.equal(actual[key]?.metadata[field], previous[key].metadata[field], 'ANDROID_FILES_PRIVATE_ROOT_CHANGED');
  }
  // A newly created, freshly attested external root is included before scanning.
  // Once observed, its identity must remain stable like the internal root.
  return actual;
}
function observeContainers(receipt) {
  const format = '{"Id":{{json .Id}},"Image":{{json .Image}},"Name":{{json .Name}},"Running":{{json .State.Running}},"Status":{{json .State.Status}},"ExitCode":{{json .State.ExitCode}},"Service":{{json (index .Config.Labels "com.docker.compose.service")}},"Project":{{json (index .Config.Labels "com.docker.compose.project")}},"Networks":{{json .NetworkSettings.Networks}}}';
  const text = execFileSync('docker', ['inspect', '--format', format, ...receipt.containers.map(value => value.id)],
    { encoding: 'utf8', timeout: 10000, maxBuffer: 65536, stdio: ['ignore', 'pipe', 'pipe'] });
  const observations = text.trim().split(/\r?\n/).map(line => { const value = JSON.parse(line); return { ...value, Networks: Object.keys(value.Networks) }; });
  return validateAndroidFilesContainers(receipt, observations);
}
export function androidFilesKnownSources(assets) {
  const previous = assets.priorManifestEvidence || [];
  assert.ok(Array.isArray(previous) && previous.length <= 4, 'ANDROID_FILES_PRIOR_COHORT_BOUND');
  return [{ id: 'seeded-txt', ...assets.source, marker: assets.source.text?.trim() }, ...previous.flatMap((reference, index) => {
    const manifest = readRef(reference);
    assert.equal(manifest.kind, 'android-files-synthetic-fixtures', 'ANDROID_FILES_PRIOR_MANIFEST_REQUIRED');
    assert.equal(manifest.platform, 'android', 'ANDROID_FILES_PRIOR_PLATFORM_REQUIRED'); assert.equal(manifest.syntheticDataOnly, true, 'ANDROID_FILES_SYNTHETIC_PRIOR_ASSETS_REQUIRED');
    assert.ok(Array.isArray(manifest.assets) && manifest.assets.length <= 12, 'ANDROID_FILES_PRIOR_ASSET_BOUND');
    return manifest.assets.map(value => ({ ...value, id: `prior-${index}-${value.id}` }));
  })];
}
export async function captureAndroidFilesFailure(context, output) {
  assert.equal(context.fixture.syntheticDataOnly, true, 'ANDROID_FILES_SYNTHETIC_FAILURE_ONLY');
  assert.equal(context.fixture.environment, 'docker-integration', 'ANDROID_FILES_ISOLATED_FAILURE_ONLY');
  assert.equal(await context.driver.getCurrentPackage(), context.fixture.appId, 'ANDROID_FILES_FAILURE_APP_NOT_FOREGROUND');
  await context.driver.switchContext('NATIVE_APP');
  assert.equal((await context.driver.$$('android=new UiSelector().password(true)')).length, 0, 'ANDROID_FILES_CREDENTIAL_CAPTURE_REFUSED');
  const source = await context.driver.getPageSource();
  assert.ok(typeof source === 'string' && Buffer.byteLength(source) <= 524288 && !/\bpassword\s*=\s*["']true["']/i.test(source), 'ANDROID_FILES_CREDENTIAL_OR_OVERSIZE_CAPTURE_REFUSED');
  writeFileSync(output, source, { flag: 'wx', mode: 0o600 }); return ref(output);
}

// Session/phase controller only; injected doubles never constitute native
// acceptance. The actual CLI supplies all source/TLS/binary/runtime fences.
export async function executeAndroidFilesCases({ cases = scenarios, createDriver, beforeCase, createContext, prepareAuthentication = authenticate,
  record, filesState, onCallFailure = async () => {} }) {
  const completed = new Set(); let unavailable = false, recovery;
  for (const [index, scenario] of cases.entries()) {
    const id = `android:${scenario.id}`; let driver, context, sessionId, requested = false, setup = false, called = false;
    record({ type: 'phase_started', id, phase: 'setup' });
    try {
      if (unavailable) throw new FixtureUnavailable('ANDROID_FILES_PRIOR_SESSION_OR_AUTH_UNCERTAIN');
      if (filesState.mutationUncertain) throw new FixtureUnavailable('ANDROID_FILES_UPLOAD_UNCERTAIN_NO_REPLAY');
      for (const dependency of scenario.requires || []) if (!completed.has(dependency)) throw new FixtureUnavailable('ANDROID_FILES_CASE_DEPENDENCY_UNVERIFIED');
      await beforeCase(scenario); requested = true; driver = await createDriver(scenario);
      sessionId = driver.sessionId; record({ ...appiumSessionEvent(sessionId, 'created'), id });
      context = await createContext(driver, scenario, id);
      if (index === 0 || recovery && !scenario.requiresSignedOut) await restart(context);
      recovery = undefined;
      if (!scenario.requiresSignedOut) {
        try { await prepareAuthentication(context, { fresh: index === 0 || scenario.freshAuthentication === true }); }
        catch (error) { unavailable = true; throw error; }
      }
      setup = true; record({ type: 'phase_result', id, phase: 'setup', status: 'passed' });
    } catch (error) {
      if (requested) unavailable = true;
      if (!requested && !(error instanceof FixtureUnavailable)) unavailable = true;
      record({ type: 'phase_result', id, phase: 'setup', status: error instanceof FixtureUnavailable ? 'blocked' : 'failed', reason: safeFailure(error, 'ANDROID_FILES_SETUP_FAILED') });
    }
    record({ type: 'phase_started', id, phase: 'call' });
    if (!setup) record({ type: 'phase_result', id, phase: 'call', status: 'not-run', reason: 'SETUP_FAILED' });
    else {
      try { await scenario.run(context); called = true; record({ type: 'phase_result', id, phase: 'call', status: 'passed' }); }
      catch (error) {
        try { await onCallFailure(context, scenario, id); } catch { record({ type: 'native_call_failure_capture_unavailable', id }); }
        recovery = scenario.id;
        record({ type: 'phase_result', id, phase: 'call', status: error instanceof FixtureUnavailable ? 'blocked' : 'failed', reason: safeFailure(error, 'ANDROID_FILES_ASSERTION_FAILED') });
      }
    }
    record({ type: 'phase_started', id, phase: 'teardown' });
    try {
      assert.ok(!requested || driver, 'ANDROID_FILES_SESSION_CREATION_UNCERTAIN');
      if (driver) await driver.deleteSession();
      if (sessionId) record({ ...appiumSessionEvent(sessionId, 'deleted'), id });
      record({ type: 'phase_result', id, phase: 'teardown', status: 'passed' }); if (setup && called) completed.add(scenario.id);
    } catch { unavailable = true; record({ type: 'phase_result', id, phase: 'teardown', status: 'failed', reason: 'ANDROID_FILES_SESSION_CLEANUP_UNCERTAIN' }); }
  }
  return { completed: [...completed], unavailable };
}

export async function runAndroidFiles() {
  const collection = collectAndroidFiles(), reportRoot = process.env.CASEOPS_MOBILE_REPORT_ROOT || path.join(os.homedir(), '.cache/caseops-mobile/android-files-reports');
  mkdirSync(reportRoot, { recursive: true, mode: 0o700 });
  const runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-android-files-${randomUUID().slice(0, 8)}`, report = path.join(reportRoot, runId);
  mkdirSync(report, { mode: 0o700 }); const journal = new Journal(path.join(report, 'events.jsonl'));
  let completed = false, preflight = false, fixture, assets, baseline, isolation, binary, frozen;
  const interrupted = code => { if (!completed) { journal.write({ type: 'run_interrupted', reason: 'PROCESS_EXIT_BEFORE_COMPLETION', exitCode: code }); journal.close(); process.exitCode = code || 1; } };
  process.once('exit', interrupted);
  const deadline = setTimeout(() => { journal.write({ type: 'run_interrupted', reason: 'THIRTY_MINUTE_SERIAL_INVENTORY_BOUND' }); journal.close(); process.removeListener('exit', interrupted); process.exit(124); }, 30 * 60 * 1000); deadline.unref();
  journal.write({ type: 'run_started', ...collection, harnessFingerprint: androidFilesHarnessFingerprint(), ...sourceSnapshot(root) });
  let runtimeFence, containers, transport, remote;
  try {
    assert.ok(path.isAbsolute(process.env.CASEOPS_MOBILE_FIXTURE || ''), 'ABSOLUTE_ANDROID_FILES_FIXTURE_REQUIRED');
    fixture = JSON.parse(readFileSync(process.env.CASEOPS_MOBILE_FIXTURE)); assets = fixture.files;
    assert.equal(fixture.filesInventory, inventory.inventoryId, 'EXACT_ANDROID_FILES_INVENTORY_REQUIRED');
    validateCoreFixture(fixture); isolation = assertStrictAndroidFilesEnvironment(fixture);
    binary = binaryHash(fixture.appPath); validateBuildReceipt(fixture, 'android', binary);
    transport = androidSessionTransport(fixture, 'android');
    assert.ok(Object.hasOwn(fixture, 'androidTransport'), 'ANDROID_FILES_BOUND_TRANSPORT_REQUIRED');
    const assembled = assembleAndroidFilesFixture({ coreFixture: fixture, manifestEvidence: assets.manifestEvidence, providerEvidence: assets.providerEvidence,
      pickerEvidence: assets.pickerEvidence, filesCache: fixture.filesCache, priorStagingEvidence: assets.priorStagingEvidence, priorManifestEvidence: assets.priorManifestEvidence });
    assert.deepEqual(assembled.files, assets, 'ANDROID_FILES_DERIVED_ASSETS_CHANGED');
    frozen = androidFilesHarnessFingerprint();
    runtimeFence = async () => {
      assert.equal(androidFilesHarnessFingerprint(), frozen, 'ANDROID_FILES_HARNESS_CHANGED');
      const source = sourceSnapshot(root);
      assert.equal(source.sourceDirty, false, 'ANDROID_FILES_CLEAN_SOURCE_REQUIRED'); assert.equal(source.sourceSha, fixture.binarySourceSha, 'ANDROID_FILES_SOURCE_COMMIT_CHANGED');
      assert.equal(source.sourceFingerprint, fixture.binarySourceFingerprint, 'ANDROID_FILES_SOURCE_CHANGED');
      assertStrictAndroidFilesEnvironment(fixture); assert.equal(binaryHash(fixture.appPath), binary, 'ANDROID_FILES_BINARY_CHANGED');
      attestAndroidBinary(fixture, binary); observeContainers(isolation);
      for (const [url, sha, revision] of [[`${fixture.gatewayUrl}/api/build`, fixture.backendSha, fixture.backendRevision],
        [`${fixture.webGatewayUrl}/api/release-identity`, fixture.webSha, fixture.webRevision]]) {
        const identity = await localJson(url); assert.equal(identity.release_sha, sha, 'ANDROID_FILES_SERVING_SHA_CHANGED'); assert.equal(identity.revision, revision, 'ANDROID_FILES_SERVING_REVISION_CHANGED');
      }
    };
    await runtimeFence(); baseline = gatewayBaseline(await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`), isolation);
    containers = attestAndroidFilesContainers({ udid: fixture.udid, appId: fixture.appId });
    const before = captureAndroidFilesPrivacy({ containers, stagingEvidence: assets.providerEvidence,
      priorStagingEvidence: assets.priorStagingEvidence, knownSources: androidFilesKnownSources(assets), output: path.join(report, 'preflight-filesystem.json') }, 'preflight');
    assert.equal(before.snapshot.complete, true, 'ANDROID_FILES_COMPLETE_PREFLIGHT_SCAN_REQUIRED');
    assert.equal(before.snapshot.providerMetadataPreserved, true, 'ANDROID_FILES_PROVIDER_ORIGINALS_CHANGED');
    assert.equal(before.snapshot.counts.privateAssetMatchCount, 0, 'ANDROID_FILES_PREFLIGHT_PRIVATE_COPY_RETAINS');
    assert.equal(before.snapshot.counts.ownedStagingFiles, 0, 'ANDROID_FILES_PREFLIGHT_STAGING_RETAINS');
    const tooling = process.env.CASEOPS_MOBILE_TOOLING_HOME || path.join(os.homedir(), '.cache/caseops-mobile/tooling');
    remote = createRequire(path.join(tooling, 'package.json'))('webdriverio').remote;
    assert.equal((await localJson(new URL('/status', transport.appiumUrl).href)).value.ready, true, 'ANDROID_FILES_APPIUM_NOT_READY');
    preflight = true; journal.write({ type: 'preflight_result', status: 'passed', binaryHash: binary, isolationEvidence: fixture.isolationEvidence, filesystemEvidence: before.evidence });
  } catch (error) { journal.write({ type: 'preflight_result', status: 'failed', reason: safeFailure(error, 'ANDROID_FILES_PREFLIGHT_FAILED') }); }
  const filesState = { uploads: {} };
  await executeAndroidFilesCases({ filesState, record: event => journal.write(event),
    beforeCase: async () => { assert.equal(preflight, true, 'ANDROID_FILES_PREFLIGHT_FAILED'); await runtimeFence(); },
    createDriver: () => remote({ hostname: transport.appiumUrl.hostname, port: Number(transport.appiumUrl.port), path: '/', protocol: 'http',
      logLevel: 'silent', connectionRetryCount: 0, connectionRetryTimeout: 60000, capabilities: { platformName: 'Android',
        'appium:automationName': 'UiAutomator2', 'appium:deviceName': fixture.deviceName, 'appium:platformVersion': fixture.platformVersion,
        'appium:udid': fixture.udid, 'appium:appPackage': fixture.appId, 'appium:noReset': true, 'appium:dontStopAppOnReset': true,
        'appium:newCommandTimeout': 60, ...transport.capabilities } }),
    createContext: async (driver, scenario, id) => {
      journal.write({ ...verifyAndroidSessionTransport(fixture, 'android', driver.capabilities), id });
      attestAndroidBinary(fixture, binary);
      await configureNativeDriver(driver, 'android', event => journal.write({ ...event, id }));
      assert.ok((await driver.getContexts()).includes('NATIVE_APP'), 'ANDROID_FILES_NATIVE_CONTEXT_REQUIRED');
      await driver.switchContext('NATIVE_APP');
      const context = { driver, fixture, platform: 'android', runId, gatewayBaseline: baseline, assets, source: assets.source,
        provider: assets.provider, filesState, record: event => journal.write({ ...event, id }),
        observeFilesystem: async (boundary, knownHashes) => {
          assert.match(boundary, /^[a-z0-9-]{1,80}$/); const manifest = readRef(assets.manifestEvidence);
          assert.ok(knownHashes.every(hash => hash === assets.source.sha256 || manifest.assets.some(asset => asset.sha256 === hash)), 'ANDROID_FILES_UNOWNED_PRIVACY_HASH');
          await runtimeFence();
          containers = bindAndroidFilesPrivateRoots(containers, attestAndroidFilesContainers({ udid: fixture.udid, appId: fixture.appId }));
          const output = path.join(report, `${scenario.id}-${boundary}-${randomUUID().slice(0, 8)}.json`);
          const { snapshot, evidence } = captureAndroidFilesPrivacy({ containers, stagingEvidence: assets.providerEvidence,
            priorStagingEvidence: assets.priorStagingEvidence, knownSources: androidFilesKnownSources(assets), output }, 'checkpoint');
          assert.equal(snapshot.complete, true, 'ANDROID_FILES_COMPLETE_PRIVACY_SCAN_REQUIRED');
          const normalized = newJson(`${output}.assertion.json`, { schemaVersion: 2, observed: snapshot.observed, platform: snapshot.platform,
            udid: snapshot.udid, appId: snapshot.appId, boundary, ownedAppScopeOnly: snapshot.ownedAppScopeOnly,
            providerOriginalsUnchanged: snapshot.providerOriginalsPreserved, providerMetadataUnchanged: snapshot.providerMetadataPreserved,
            providerOriginalsRead: snapshot.providerOriginalsRead, providerByteVerification: snapshot.providerByteVerification, stagedFileCount: snapshot.counts.ownedStagingFiles,
            privateByteMatchCount: snapshot.counts.privateAssetMatchCount, rawEvidence: evidence });
          journal.write({ type: 'filesystem_observation', id, boundary, evidence: normalized, rawEvidence: evidence }); return normalized;
        },
        admitUploadedFileRead: async (anchor, ack) => {
          await runtimeFence(); const manifest = readRef(assets.manifestEvidence), selected = manifest.assets.filter(asset => asset.filename === anchor.filename && asset.sha256 === anchor.sha256 && asset.sizeBytes === anchor.sizeBytes);
          assert.equal(selected.length, 1, 'ANDROID_FILES_EXACT_ACKNOWLEDGED_ASSET_REQUIRED');
          const output = path.join(report, `${scenario.id}-source-admission-${randomUUID().slice(0, 8)}.json`);
          const result = spawnSync(process.env.PYTHON || 'python3', [path.join(root, 'scripts/mobile/admit-android-file-source.py'), '--cache', fixture.filesCache,
            '--receipt', fixture.isolationEvidence.path, '--manifest', assets.manifestEvidence.path, '--manifest-sha256', assets.manifestEvidence.sha256,
            '--asset-id', selected[0].id, '--attachment-id', anchor.attachmentId, '--sha256', anchor.sha256, '--size-bytes', String(anchor.sizeBytes),
            '--filename', anchor.filename, '--ack-request-id', ack.requestId, '--output', output], { cwd: root, encoding: 'utf8', timeout: 80000, maxBuffer: 65536 });
          assert.equal(result.status, 0, 'ANDROID_FILES_SOURCE_ADMISSION_FAILED'); const receipt = JSON.parse(result.stdout.trim());
          journal.write({ type: 'source_admission', id, ...receipt }); return receipt;
        } };
      validateAndroidFilesContext(context); return context;
    }, onCallFailure: async (context, scenario, id) => journal.write({ type: 'native_call_failure_evidence', id,
      evidence: await captureAndroidFilesFailure(context, path.join(report, `${scenario.id}-failure-native.xml`)) }) });
  if (preflight) {
    let after;
    try { after = await localJson(`${fixture.gatewayUrl}/__caseops_e2e/status`); newJson(path.join(report, 'gateway-after.json'), after); }
    catch { journal.write({ type: 'gateway_capture_failed', reason: 'ANDROID_FILES_POSTFLIGHT_LEDGER_UNAVAILABLE' }); }
    try {
      const originals = captureAndroidFilesPrivacy({ containers: bindAndroidFilesPrivateRoots(containers, attestAndroidFilesContainers({ udid: fixture.udid, appId: fixture.appId })),
        stagingEvidence: assets.providerEvidence, priorStagingEvidence: assets.priorStagingEvidence, knownSources: androidFilesKnownSources(assets),
        output: path.join(report, 'postflight-filesystem.json') }, 'postflight');
      journal.write({ type: 'provider_originals_postflight', evidence: originals.evidence, status: 'passed' });
      await runtimeFence(); assert.ok(after, 'ANDROID_FILES_POSTFLIGHT_LEDGER_UNAVAILABLE'); validateTraffic(after, baseline);
      for (const id of collection.intended) {
        const sessions = journal.events.filter(event => event.type === 'appium_session' && event.id === id);
        if (sessions.length) { assert.deepEqual(sessions.map(value => value.state), ['created', 'deleted'], 'ANDROID_FILES_EXACT_SESSION_LIFECYCLE_REQUIRED'); assert.equal(sessions[0].sessionId, sessions[1].sessionId, 'ANDROID_FILES_SESSION_ID_CHANGED'); }
      }
      journal.write({ type: 'postflight_result', status: 'passed' });
    } catch (error) { journal.write({ type: 'postflight_result', status: 'failed', reason: safeFailure(error, 'ANDROID_FILES_POSTFLIGHT_FAILED') }); }
  }
  journal.write({ type: 'run_completed', platform: 'android', intendedCount: collection.intended.length });
  const result = reconcileResults(journal.events, collection.intended), nativeSessionCount = journal.events.filter(event => event.type === 'appium_session' && event.state === 'created').length;
  newJson(path.join(report, 'result.json'), { ...collection, ...result,
    nativeExecution: nativeSessionCount ? 'observed-Appium-sessions' : 'not-run', nativeSessionCount, report });
  completed = true; clearTimeout(deadline); process.removeListener('exit', interrupted); journal.close();
  return { ...result, report };
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length === 3 && process.argv[2] === '--collect') console.log(JSON.stringify(collectAndroidFiles(), null, 2));
  else if (process.argv.length === 2) { const result = await runAndroidFiles(); console.log(JSON.stringify(result)); if (result.status !== 'passed') process.exitCode = 1; }
  else throw new Error('Usage: node scripts/mobile/run-android-files.mjs [--collect]');
}
