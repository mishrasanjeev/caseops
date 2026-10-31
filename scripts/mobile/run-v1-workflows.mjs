import { OBSERVER_SOURCE_INPUTS } from './android-qa-observer.mjs';
import { observerConfiguration } from './android-qa-observer.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { sourceSnapshot } from './source-snapshot.mjs';
import { OBSERVER_IDENTITY, attestAndroidFilesContainers } from './android-files-privacy.mjs';
import { androidLocalProfile } from '../../apps/mobile/e2e/android-local-profile.mjs';
import { attestAndroidBinary } from '../../apps/mobile/e2e/installed-android.mjs';
import { androidSessionTransport, verifyAndroidSessionTransport } from '../../apps/mobile/e2e/local-run.mjs';
import { validateBuildReceipt, validateCoreFixture, admitApplication } from '../../apps/mobile/e2e/fixture-contract.mjs';
import { binaryHash, localJson, Journal, reconcileResults, safeFailure } from '../../apps/mobile/e2e/support.mjs';
import { gatewayBaseline, validateTraffic } from '../../apps/mobile/e2e/traffic.mjs';
import { authenticate } from '../../apps/mobile/e2e/browser-handoff.mjs';
import { traffic, delta } from '../../apps/mobile/e2e/journeys.mjs';
import { find, visible, selector, dispatchNativeClick, restart } from '../../apps/mobile/e2e/native-ui.mjs';
import { appiumSessionEvent, configureNativeDriver } from '../../apps/mobile/e2e/run-state.mjs';
import { readV1Member } from '../../apps/mobile/e2e/v1-workflows-credentials.mjs';
import { requirePreparedV1, v1PrivateReference, readV1Reference, readV1Bytes, validateV1ExecutionFixture, validateV1FixtureAggregate, strictV1Routes, V1_CONTROL_CAPABILITIES, reconcileV1Sessions, reconcileV1ControlIdentities } from '../../apps/mobile/e2e/v1-workflows-contract.mjs';
import { V1_BUDGETS, V1_CASE_CONTROL_LIMITS } from '../../apps/mobile/e2e/v1-workflows-inventory.mjs';
import { collectV1Workflows, v1WorkflowScenarios, prepareV1Context } from '../../apps/mobile/e2e/v1-workflows.mjs';

const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
const INPUTS = [...OBSERVER_SOURCE_INPUTS, 'apps/mobile/e2e/v1-workflows-inventory.mjs', 'apps/mobile/e2e/v1-workflows-contract.mjs',
  'apps/mobile/e2e/v1-workflows.mjs', 'apps/mobile/e2e/v1-workflows-credentials.mjs', 'apps/mobile/e2e/v1-workflows-fixture.mjs',
  'apps/mobile/e2e/native-ui.mjs', 'apps/mobile/e2e/browser-handoff.mjs', 'apps/mobile/e2e/firefox-handoff.mjs',
  'apps/mobile/e2e/fixture-contract.mjs', 'apps/mobile/e2e/evidence.mjs', 'apps/mobile/e2e/support.mjs',
  'apps/mobile/e2e/traffic.mjs', 'apps/mobile/e2e/run-state.mjs', 'apps/mobile/e2e/installed-android.mjs',
  'apps/mobile/e2e/local-run.mjs', 'apps/mobile/e2e/journeys.mjs', 'scripts/mobile/run-v1-workflows.mjs',
  'scripts/mobile/source-snapshot.mjs', 'scripts/mobile/android-files-privacy.mjs', 'scripts/mobile/v1-workflows-controls.mjs',
  'scripts/mobile/prepare-v1-fixture.mjs', 'scripts/mobile/local-gateway.py', 'scripts/mobile/local-v1-controls.py', 'scripts/mobile/local-v1-inbox.py',
  'compose.mobile-local.yml'];
export function v1HarnessFingerprint(root = ROOT) {
  const allE2e = fs.readdirSync(path.join(root, 'apps/mobile/e2e')).filter(name => /\.(mjs|json)$/.test(name)).map(name => `apps/mobile/e2e/${name}`);
  const hash = createHash('sha256'); for (const name of [...new Set([...allE2e, ...INPUTS])].sort()) { hash.update(name); hash.update('\0'); hash.update(fs.readFileSync(path.join(root, name))); hash.update('\0'); } return hash.digest('hex');
}
const toolEnvironment = environment => Object.fromEntries(['PATH', 'HOME', 'USERPROFILE', 'DEVELOPER_DIR', 'SYSTEMROOT', 'TEMP', 'TMPDIR',
  'ANDROID_USER_HOME', 'ADB_SERVER_SOCKET', 'ANDROID_ADB_SERVER_PORT', 'ANDROID_SERIAL', 'CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE'].filter(k => typeof environment[k] === 'string').map(k => [k, environment[k]]));
export function observeInstalled(fixture, platform, expectedHash, environment) {
  const tools = toolEnvironment(environment);
  if (platform === 'android' && tools.CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE !== undefined) {
    assert.equal(tools.CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE, fixture.androidTransport?.transportMode ?? 'emulator', 'V1_ANDROID_TRANSPORT_MODE_MISMATCH');
  }
  const command = (file, args, options) => execFileSync(file, args, { ...options, env: tools });
  if (platform === 'android') {
    const installed = attestAndroidBinary(fixture, expectedHash, { install: false, command });
    const containers = attestAndroidFilesContainers({ udid: fixture.udid, appId: fixture.appId, androidTransportMode: fixture.androidTransport?.transportMode, privacyObserver: fixture.privacyObserverEvidence, command, environment: tools });
    let layout;
    if (containers.transportMode === 'usb-reverse') {
      const observe = args => {
        const raw = command('adb', ['-s', fixture.udid, 'shell', ...args], { shell: false, windowsHide: true,
          encoding: 'utf8', timeout: 5000, maxBuffer: 64, stdio: ['pipe', 'pipe', 'pipe'] });
        assert.ok(typeof raw === 'string' || Buffer.isBuffer(raw), 'ANDROID_LAYOUT_OUTPUT_REQUIRED');
        const bytes = Buffer.from(raw); assert.ok(bytes.length > 0 && bytes.length <= 64, 'ANDROID_LAYOUT_OUTPUT_BOUND');
        return { text: new TextDecoder('utf-8', { fatal: true }).decode(bytes), returnedBytes: bytes.length };
      };
      const beforeBoot = observe(['cat', '/proc/sys/kernel/random/boot_id']);
      assert.equal(beforeBoot.text.trim(), containers.bootId, 'ANDROID_LAYOUT_BOOT_CHANGED');
      const page = observe(['getconf', 'PAGESIZE']);
      assert.match(page.text, /^(4096|16384)\r?\n?$/, 'ANDROID_PHYSICAL_PAGE_SIZE_REQUIRED');
      const afterBoot = observe(['cat', '/proc/sys/kernel/random/boot_id']);
      assert.equal(afterBoot.text.trim(), containers.bootId, 'ANDROID_LAYOUT_BOOT_CHANGED');
      layout = { schemaVersion: 1, kind: 'android-physical-layout-observation', observed: true, platform: 'android',
        udid: fixture.udid, appId: fixture.appId, binaryHash: installed.installedApkSha256, bootId: containers.bootId,
        deviceKind: 'physical', transportMode: 'usb-reverse', pageSizeBytes: Number(page.text.trim()),
        physicalIdentity: Object.fromEntries((containers.access==='qa-observer-service' ? ['packageUid', ...OBSERVER_IDENTITY] : ['access', 'deviceKind', 'transportMode', 'shellUid', 'packageUid', 'runAsUid', 'usbDevPath', 'apiLevel', 'abi', 'qemuOff']).map(key => [key, containers[key]])),
        observationCommand: ['shell', 'getconf', 'PAGESIZE'], returnedOutputBytes: { beforeBoot: beforeBoot.returnedBytes, pageSize: page.returnedBytes, afterBoot: afterBoot.returnedBytes },
        acceptanceScope: 'physical-workflow-only', sixteenKEmulatorAcceptance: false };
    }
    return { platform, udid: fixture.udid, appId: fixture.appId, binaryHash: installed.installedApkSha256,
      bootId: containers.bootId, appDataPath: containers.appData.path,
      appDataIdentity: Object.fromEntries(['kind', 'uid', 'device', 'inode'].map(key => [key, containers.appData.metadata[key]])),
      ...(layout ? { pageSizeBytes: layout.pageSizeBytes, androidLayout: layout, physicalWorkflowOnly: true, sixteenKEmulatorAcceptance: false } : { pageSizeRequired: 16384 }),
      ...(containers.transportMode === 'usb-reverse' ? Object.fromEntries((containers.access==='qa-observer-service' ? ['packageUid', ...OBSERVER_IDENTITY] : ['access', 'deviceKind', 'transportMode', 'shellUid', 'packageUid', 'runAsUid', 'usbDevPath', 'apiLevel', 'abi', 'qemuOff'])
        .map(key => [key, containers[key]])) : {}) };
  }
  assert.equal(process.platform, 'darwin', 'IOS_NATIVE_OWNER_MAC_REQUIRED');
  const invoke = args => command('/usr/bin/xcrun', ['simctl', ...args], { encoding: 'utf8', timeout: 10000, maxBuffer: 1048576 }).trim();
  const inventory = JSON.parse(invoke(['list', 'devices', '--json']));
  const matches = Object.entries(inventory.devices).flatMap(([runtime, rows]) => rows.filter(row => row.udid === fixture.udid).map(row => ({ ...row, runtime })));
  assert.equal(matches.length, 1, 'EXACT_V1_SIMULATOR_REQUIRED'); const device = matches[0];
  assert.equal(device.state, 'Booted'); assert.equal(device.isAvailable, true);
  assert.match(device.deviceTypeIdentifier, /^com\.apple\.CoreSimulator\.SimDeviceType\.(iPhone|iPad)-[A-Za-z0-9-]+$/);
  const appPath = invoke(['get_app_container', fixture.udid, fixture.appId, 'app']);
  const appDataPath = invoke(['get_app_container', fixture.udid, fixture.appId, 'data']);
  const id = command('/usr/libexec/PlistBuddy', ['-c', 'Print :CFBundleIdentifier', path.join(appPath, 'Info.plist')], { encoding: 'utf8', timeout: 10000 }).trim();
  assert.equal(id, fixture.appId); const observedHash = binaryHash(appPath); assert.equal(observedHash, expectedHash);
  command('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath], { timeout: 20000, stdio: ['ignore', 'pipe', 'pipe'] });
  return { platform, udid: fixture.udid, appId: id, binaryHash: observedHash, appPath, appDataPath, deviceTypeIdentifier: device.deviceTypeIdentifier,
    runtime: device.runtime, state: device.state };
}
export function validateAndroidLayoutEvidence(fixture, actual, device, expectedInstalled) {
  const mode = fixture.androidTransport?.transportMode;
  if (mode !== 'usb-reverse') {
    for (const value of [actual, device, expectedInstalled]) {
      assert.notEqual(value.deviceKind, 'physical', 'ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR');
      assert.notEqual(value.transportMode, 'usb-reverse', 'ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR');
      assert.equal(value.androidLayout, undefined, 'ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR');
      assert.notEqual(value.physicalWorkflowOnly, true, 'ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR');
    }
    assert.equal(actual.bootId, device.bootId); assert.equal(device.pageSizeBytes, 16384);
    return null;
  }
  const profile = androidLocalProfile(fixture.udid, 'ANDROID_LAYOUT_PHYSICAL_PROFILE_REQUIRED', mode);
  assert.equal(fixture.appId, 'ai.caseops.mobile.dev.localacceptance', 'ANDROID_LAYOUT_QA_PACKAGE_REQUIRED');
  assert.equal(profile.deviceKind, 'physical', 'ANDROID_LAYOUT_PHYSICAL_PROFILE_REQUIRED');
  assert.deepEqual(Object.keys(fixture.androidTransport).sort(), ['adbPort', 'appiumUrl', 'systemPort', 'transportMode'], 'ANDROID_LAYOUT_PHYSICAL_PROFILE_REQUIRED');
  for (const key of ['adbPort', 'appiumUrl', 'systemPort', 'transportMode']) assert.equal(fixture.androidTransport[key], profile[key], 'ANDROID_LAYOUT_PHYSICAL_PROFILE_REQUIRED');
  const layout = actual.androidLayout;
  assert.ok(layout && layout.schemaVersion === 1 && layout.kind === 'android-physical-layout-observation' && layout.observed === true, 'ANDROID_LAYOUT_OBSERVATION_REQUIRED');
  assert.match(actual.binaryHash || '', /^[a-f0-9]{64}$/);
  assert.equal(layout.udid, fixture.udid, 'ANDROID_LAYOUT_DEVICE_IDENTITY_CHANGED'); assert.equal(layout.appId, fixture.appId, 'ANDROID_LAYOUT_DEVICE_IDENTITY_CHANGED');
  assert.equal(layout.binaryHash, actual.binaryHash, 'ANDROID_LAYOUT_BINARY_CHANGED');
  assert.equal(layout.platform, 'android'); assert.equal(layout.deviceKind, 'physical'); assert.equal(layout.transportMode, mode);
  assert.deepEqual(layout.observationCommand, ['shell', 'getconf', 'PAGESIZE']);
  assert.ok([4096, 16384].includes(layout.pageSizeBytes), 'ANDROID_PHYSICAL_PAGE_SIZE_REQUIRED');
  assert.equal(layout.acceptanceScope, 'physical-workflow-only'); assert.equal(layout.sixteenKEmulatorAcceptance, false);
  assert.match(layout.bootId || '', /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/);
  assert.deepEqual(Object.keys(layout.returnedOutputBytes || {}).sort(), ['afterBoot', 'beforeBoot', 'pageSize']);
  for (const bytes of Object.values(layout.returnedOutputBytes)) assert.ok(Number.isSafeInteger(bytes) && bytes > 0 && bytes <= 64, 'ANDROID_LAYOUT_OUTPUT_BOUND');
  const fields = actual.access==='qa-observer-service' ? ['packageUid', ...OBSERVER_IDENTITY] : ['access', 'deviceKind', 'transportMode', 'shellUid', 'packageUid', 'runAsUid', 'usbDevPath', 'apiLevel', 'abi', 'qemuOff'];
  for (const value of [actual, device, expectedInstalled]) {
    assert.equal(value.udid, fixture.udid, 'ANDROID_LAYOUT_DEVICE_IDENTITY_CHANGED'); assert.equal(value.appId, fixture.appId, 'ANDROID_LAYOUT_DEVICE_IDENTITY_CHANGED');
    assert.equal(value.binaryHash ?? value.installedApkSha256, actual.binaryHash, 'ANDROID_LAYOUT_BINARY_CHANGED');
    assert.equal(value.bootId, layout.bootId, 'ANDROID_LAYOUT_BOOT_CHANGED'); assert.equal(value.pageSizeBytes, layout.pageSizeBytes, 'ANDROID_LAYOUT_PAGE_CHANGED');
    assert.equal(value.pageSizeRequired, undefined, 'ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR');
    assert.ok(!Object.hasOwn(value, 'rootUid') && !Object.hasOwn(value, 'avdName'), 'ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR');
    assert.equal(value.access,actual.access);assert.ok(['run-as','qa-observer-service'].includes(value.access)); assert.equal(value.deviceKind, 'physical'); assert.equal(value.transportMode, mode); assert.equal(value.shellUid, 2000);
    assert.ok(Number.isSafeInteger(value.packageUid) && value.packageUid >= 10000); if(value.access==='qa-observer-service'){assert.ok(!Object.hasOwn(value,'runAsUid'));const d=observerConfiguration(value.observerInstallationEvidence,fixture.udid);assert.equal(d.targetApkSha256,actual.binaryHash);assert.equal(d.sourceSha,fixture.binarySourceSha);assert.deepEqual(value.observerInstallationEvidence,fixture.privacyObserverEvidence);assert.equal(d.packageUid,value.packageUid);for(const k of ['observerAppId','observerUid','targetApkSha256','observerApkSha256','sourceSha','signerSha256'])assert.equal(value[k],d[k]);assert.equal(value.observationDomain,d.domain);assert.equal(value.fullPackageForceStoppedStateCertified,false);}else assert.equal(value.runAsUid, value.packageUid);
    assert.match(value.usbDevPath || '', /^usb:[A-Za-z0-9.:_-]{1,128}$/); assert.equal(value.apiLevel, 36); assert.equal(value.abi, 'arm64-v8a'); assert.equal(value.qemuOff, true);
    assert.deepEqual(Object.fromEntries(fields.map(key => [key, value[key]])), layout.physicalIdentity, 'ANDROID_LAYOUT_PHYSICAL_IDENTITY_CHANGED');
    assert.deepEqual(value.androidLayout, layout, 'ANDROID_LAYOUT_RETAINED_OBSERVATION_CHANGED');
  }
  return layout;
}
export function androidLayoutSummary(installed) {
  if (installed === undefined) return {};
  if (installed.transportMode !== 'usb-reverse') {
    assert.equal(installed.androidLayout, undefined, 'ANDROID_LAYOUT_PHYSICAL_CANNOT_CERTIFY_EMULATOR'); return {};
  }
  const layout = installed.androidLayout;
  assert.ok(layout && layout.kind === 'android-physical-layout-observation' && layout.observed === true && [4096, 16384].includes(layout.pageSizeBytes), 'ANDROID_LAYOUT_OBSERVATION_REQUIRED');
  assert.equal(layout.acceptanceScope, 'physical-workflow-only'); assert.equal(layout.sixteenKEmulatorAcceptance, false);
  return { androidAcceptanceScope: 'physical-workflow-only', androidPageSizeBytes: layout.pageSizeBytes,
    sixteenKEmulatorAcceptance: false, sixteenKEmulator83Acceptance: 'required-separately' };
}
/** All public artifact, device and BOTH serving identities precede the reader. */
export async function admitV1BeforeMembers(config, dependencies = {}) {
  requirePreparedV1(config);
  const io = { read: readV1Reference, bytes: readV1Bytes, snapshot: sourceSnapshot, installed: observeInstalled, getJson: localJson,
    artifactHash: binaryHash, reader: readV1Member, environment: process.env, buildCheck: validateBuildReceipt,
    fixtureCheck: validateV1ExecutionFixture, coreCheck: validateCoreFixture, harness: v1HarnessFingerprint, ...dependencies };
  assert.equal(path.resolve(config.repoRoot), ROOT, 'EXACT_V1_CHECKOUT_REQUIRED');
  const fixture = io.read(config.fixtureEvidence), build = io.read(config.buildReceipt), isolation = io.read(config.dockerReceipt), device = io.read(config.deviceEvidence), expectedInstalled = io.read(config.installedEvidence);
  io.fixtureCheck(fixture, config.platform); admitApplication(fixture, config.platform);
  assert.deepEqual(fixture.buildReceipt, config.buildReceipt); assert.deepEqual(fixture.isolationEvidence, config.dockerReceipt);
  for (const key of ['backendSha', 'webSha', 'binarySourceSha']) assert.equal(fixture[key], config.expectedSourceSha);
  for (const key of ['backendSha', 'webSha']) assert.equal(isolation[key], config.expectedSourceSha);
  assert.equal(build.sourceSha, config.expectedSourceSha); assert.equal(build.sourceFingerprint, config.expectedSourceFingerprint);
  assert.equal(build.inputFileCount, config.expectedInputFileCount); assert.equal(build.sourceDirty, false);
  assert.equal(fixture.binarySourceFingerprint, config.expectedSourceFingerprint);
  assert.equal(io.artifactHash(build.artifact), config.expectedBinaryHash); io.buildCheck(fixture, config.platform, config.expectedBinaryHash);
  const source = io.snapshot(ROOT); assert.deepEqual(source, { sourceSha: config.expectedSourceSha, sourceFingerprint: config.expectedSourceFingerprint,
    sourceDirty: false, inputFileCount: config.expectedInputFileCount });
  assert.equal(config.expectedHarnessFingerprint, io.harness());
  const closure = io.read(config.codeClosure); for (const ref of closure.code) io.bytes(ref);
  const producer = io.read(config.producerEvidence); assert.equal(producer.observed, true); assert.equal(producer.sourceSha, config.expectedSourceSha);
  assert.equal(producer.kind, 'actual-normal-api-v1-fixture'); assert.equal(producer.phase, 'readthrough'); assert.equal(producer.nativeReady, false);
  assert.equal(producer.companyId, fixture.companyId); assert.equal(producer.directDatabaseWrites, false); assert.equal(producer.automaticRetry, false);
  const aggregate = validateV1FixtureAggregate(io.read(config.aggregateFixtureEvidence), config.expectedSourceSha, io.read);
  assert.deepEqual(aggregate.stages[3].receiptEvidence, config.producerEvidence); assert.deepEqual(aggregate.stages[1].receiptEvidence, config.viewerEvidence); assert.deepEqual(aggregate.stages[2].receiptEvidence, config.inboxEvidence);
  const inbox = io.read(config.inboxEvidence); assert.equal(inbox.kind, 'actual-canonical-in-app-fixture'); assert.equal(inbox.observed, true);
  assert.equal(inbox.companyId, fixture.companyId); assert.equal(inbox.membershipId, fixture.membershipId); assert.equal(inbox.externalCalls, 0); assert.equal(inbox.manualReceiptInsertion, false);
  assert.deepEqual(fixture.v1.records.inbox.deliveryEvidence, config.inboxEvidence); assert.deepEqual(fixture.v1.records.inbox.notification, inbox.notification);
  assert.deepEqual(fixture.v1.provenance.aggregateFixture, config.aggregateFixtureEvidence);
  assert.equal(inbox.workerEvidence.path, path.join(ROOT, 'scripts/mobile/local-v1-inbox.py')); io.bytes(inbox.workerEvidence);
  assert.ok(closure.code.some(ref => ref.path === inbox.workerEvidence.path && ref.sha256 === inbox.workerEvidence.sha256), 'INBOX_WORKER_SOURCE_CLOSURE_REQUIRED');
  assert.equal(inbox.worker.workerExecutions, 1); assert.equal(inbox.worker.observerStatements, aggregate.stages[2].observerStatements);
  const controls = io.read(config.controlsEvidence); assert.deepEqual(controls.capabilities, V1_CONTROL_CAPABILITIES); assert.equal(controls.sourceSha, config.expectedSourceSha);
  assert.equal(controls.nativeMutationsForwardedByControls, false); assert.equal(controls.directDatabaseWrites, false);
  assert.equal(controls.module.path, path.join(ROOT, 'scripts/mobile/v1-workflows-controls.mjs'), 'REGISTERED_V1_CONTROL_MODULE_REQUIRED');
  io.bytes(controls.module); assert.ok(closure.code.some(ref => ref.path === controls.module.path && ref.sha256 === controls.module.sha256), 'CONTROL_MODULE_COPY_CLOSURE_REQUIRED');
  assert.equal(controls.gatewayImplementationEvidence.path, path.join(ROOT, 'scripts/mobile/local-v1-controls.py'));
  io.bytes(controls.gatewayImplementationEvidence);
  assert.ok(closure.code.some(ref => ref.path === controls.gatewayImplementationEvidence.path && ref.sha256 === controls.gatewayImplementationEvidence.sha256), 'CONTROL_GATEWAY_COPY_CLOSURE_REQUIRED');
  const gateway = io.read(config.gatewayEvidence); assert.equal(gateway.observed, true); assert.equal(gateway.sourceSha, config.expectedSourceSha);
  assert.equal(gateway.gatewayRunId, isolation.gatewayRunId); assert.deepEqual(gateway.v1ExactRoutes, strictV1Routes(fixture.v1.records));
  assert.equal(gateway.nativeWorkBodyObservation, 'keys-and-canonical-sha256'); assert.equal(gateway.authorizationValuesRetained, false);
  assert.equal(controls.registrationSha256, gateway.v1Registration.sha256); const registered = io.read(gateway.v1Registration);
  assert.deepEqual(registered.caseControlLimits, V1_CASE_CONTROL_LIMITS);
  assert.deepEqual(registered.inboxNotifications, [{ id: inbox.notification.id, companyId: fixture.companyId, recipientMembershipId: fixture.membershipId,
    target: inbox.notification.target, deliveryEvidence: config.inboxEvidence }]);
  const identityAudit = reconcileV1ControlIdentities(fixture.v1.records, registered, producer.oracleIdentityEvidence);
  for (const actor of Object.values(registered.actors)) v1PrivateReference(actor.credentialEvidence);
  v1PrivateReference(registered.authorityEvidence);
  for (const [index, actor] of ['member', 'second-company'].entries()) assert.deepEqual(registered.actors[actor].credentialEvidence, config.members[index].credentialEvidence, 'EXACT_NATIVE_ACTOR_PRIVATE_MAPPING_REQUIRED');
  const auth = io.read(config.authObservation); assert.equal(auth.observed, true); assert.equal(auth.udid, fixture.udid); assert.equal(auth.bundleId, fixture.appId);
  assert.deepEqual(auth.buildReceipt, config.buildReceipt); assert.deepEqual(auth.dockerReceipt, config.dockerReceipt); assert.equal(auth.binaryHash, config.expectedBinaryHash);
  assert.equal(auth.membershipId, fixture.membershipId); assert.equal(auth.nativePrincipalVerified, true); assert.equal(auth.nativeWorkspaceVerified, true);
  assert.equal(auth.pkceUnchanged, true); assert.equal(auth.logoutAcknowledged, true); assert.equal(auth.sessionCleanup, 'passed');
  assert.deepEqual(auth.importedSource, { sourceSha: config.expectedSourceSha, sourceFingerprint: config.expectedSourceFingerprint,
    sourceDirty: false, inputFileCount: config.expectedInputFileCount });
  assert.deepEqual(config.authObservation, config.members[0].authObservation);
  assert.deepEqual(fixture.v1.records.secondCompany.fixtureEvidence, config.members[1].fixtureEvidence, 'EXACT_SECOND_COMPANY_FIXTURE_REQUIRED');
  assert.deepEqual(fixture.v1.records.policy.readOnlyMemberFixture, config.members[1].fixtureEvidence, 'EXACT_READONLY_NATIVE_MEMBER_REQUIRED');
  assert.deepEqual(fixture.v1.records.policy.viewerEvidence, config.viewerEvidence);
  const viewer = io.read(config.viewerEvidence);
  assert.equal(viewer.kind, 'actual-normal-api-v1-viewer'); assert.equal(viewer.observed, true); assert.equal(viewer.sourceSha, config.expectedSourceSha);
  assert.equal(viewer.directDatabaseWrites, false); assert.equal(viewer.automaticRetry, false); assert.equal(viewer.mutationUncertain, false);
  assert.equal(viewer.noPaidMarker, 'no-paid-providers'); assert.equal(viewer.role, 'viewer'); assert.equal(viewer.capabilities.includes('matters:write'), false);
  assert.deepEqual(viewer.credentialEvidence, config.members[1].credentialEvidence);
  assert.deepEqual(viewer.buildReceipt, config.buildReceipt); assert.deepEqual(viewer.dockerReceipt, config.dockerReceipt);
  assert.deepEqual(viewer.installedEvidence, config.installedEvidence); assert.equal(viewer.binaryHash, config.expectedBinaryHash);
  assert.notEqual(io.environment.NODE_TLS_REJECT_UNAUTHORIZED, '0'); assert.equal(io.environment.NODE_EXTRA_CA_CERTS, isolation.publicCA);
  const actual = io.installed(fixture, config.platform, config.expectedBinaryHash, io.environment); assert.equal(actual.udid, device.udid);
  assert.equal(actual.binaryHash, config.expectedBinaryHash); assert.equal(actual.appId, fixture.appId);
  assert.equal(device.observed, true); assert.equal(device.platform, config.platform); assert.equal(device.appId, fixture.appId); assert.deepEqual(device.buildReceipt, config.buildReceipt);
  assert.equal(expectedInstalled.udid, fixture.udid); assert.equal(expectedInstalled.appId, fixture.appId); assert.deepEqual(expectedInstalled.buildReceipt, config.buildReceipt);
  assert.equal(expectedInstalled.binaryHash ?? expectedInstalled.installedApkSha256, config.expectedBinaryHash);
  if (expectedInstalled.appDataPath) assert.equal(actual.appDataPath, expectedInstalled.appDataPath);
  if (config.platform === 'android') validateAndroidLayoutEvidence(fixture, actual, device, expectedInstalled);
  else assert.equal(actual.deviceTypeIdentifier, device.deviceTypeIdentifier);
  const api = await io.getJson(isolation.gatewayUrl + '/api/build'), web = await io.getJson(isolation.webGatewayUrl + '/api/release-identity');
  assert.equal(api.release_sha, config.expectedSourceSha); assert.equal(api.revision, isolation.backendRevision);
  assert.equal(web.release_sha, config.expectedSourceSha); assert.equal(web.revision, isolation.webRevision);
  const runtime = await io.getJson(isolation.gatewayUrl + '/__caseops_e2e/status');
  assert.equal(runtime.runId, isolation.gatewayRunId); assert.equal(runtime.v1ControlsEnabled, true, 'ACTUAL_V1_CONTROL_RUNTIME_REQUIRED_BEFORE_PRIVATE_READ');
  assert.equal(runtime.v1ControlsImplementationSha256, controls.gatewayImplementationEvidence.sha256);
  assert.equal(runtime.v1RegistrationSha256, controls.registrationSha256);
  assert.deepEqual(io.snapshot(ROOT), source); assert.deepEqual(io.installed(fixture, config.platform, config.expectedBinaryHash, io.environment), actual);
  const publicMembers = config.members.map(entry => {
    const memberFixture = io.read(entry.fixtureEvidence), observed = io.read(entry.authObservation);
    assert.equal(memberFixture.udid, fixture.udid); assert.deepEqual(memberFixture.buildReceipt, config.buildReceipt); assert.deepEqual(memberFixture.isolationEvidence, config.dockerReceipt);
    for (const key of ['binarySourceSha', 'backendSha', 'webSha']) assert.equal(memberFixture[key], config.expectedSourceSha);
    assert.equal(memberFixture.apiOrigin, isolation.apiOrigin); assert.equal(memberFixture.auth.webOrigin, isolation.webOrigin); assert.equal(memberFixture.auth.mfaRequired, true);
    assert.equal(observed.observed, true); assert.equal(observed.membershipId, memberFixture.membershipId); assert.equal(observed.udid, fixture.udid);
    assert.deepEqual(observed.buildReceipt, config.buildReceipt); assert.deepEqual(observed.dockerReceipt, config.dockerReceipt); assert.equal(observed.binaryHash, config.expectedBinaryHash);
    assert.equal(observed.nativePrincipalVerified, true); assert.equal(observed.nativeWorkspaceVerified, true); assert.equal(observed.pkceUnchanged, true); assert.equal(observed.sessionCleanup, 'passed');
    assert.equal(observed.mfaStage, memberFixture.auth.mfaStage); assert.equal(observed.iosConsent, memberFixture.auth.iosConsent);
    assert.equal(observed.logoutAcknowledged, true); assert.equal(observed.mode, memberFixture.auth.mode);
    assert.deepEqual(observed.importedSource, source);
    return { entry, fixture: memberFixture };
  });
  assert.notEqual(publicMembers[0].fixture.companyId, publicMembers[1].fixture.companyId);
  assert.equal(viewer.companyId, publicMembers[1].fixture.companyId); assert.equal(viewer.membershipId, publicMembers[1].fixture.membershipId);
  for (const [index, actor] of ['member', 'second-company'].entries()) {
    assert.equal(registered.actors[actor].companyId, publicMembers[index].fixture.companyId);
    assert.equal(registered.actors[actor].membershipId, publicMembers[index].fixture.membershipId);
  }
  assert.equal(viewer.mfaEnrolled, true); assert.equal(fixture.v1.records.policy.readOnly.matter.company_id, viewer.companyId);
  assert.deepEqual(viewer.readOnlyWork, fixture.v1.records.policy.readOnly);
  const envNames = publicMembers.flatMap(member => ['emailEnv', 'passwordEnv', 'totpSecretEnv'].map(key => member.fixture.auth[key]));
  assert.equal(new Set(envNames).size, 6, 'DISTINCT_TWO_COMPANY_PRIVATE_NAMES_REQUIRED');
  const members = [];
  for (const { entry, fixture: memberFixture } of publicMembers) {
    const loaded = io.reader(entry.credentialEvidence.path);
    try {
      assert.equal(loaded.sha256, entry.credentialEvidence.sha256); assert.equal(loaded.uid, entry.credentialEvidence.uid); const value = loaded.value;
      assert.equal(value.full_name, memberFixture.principalLabel); assert.equal(value.company_slug, memberFixture.auth.companySlug);
      const environment = { ...io.environment };
      for (const [key, field] of [['emailEnv', 'email'], ['passwordEnv', 'password'], ['totpSecretEnv', 'totp_secret']]) {
        assert.match(memberFixture.auth[key], /^CASEOPS_MOBILE_[A-Z0-9_]+$/); assert.ok(typeof value[field] === 'string' && value[field]); environment[memberFixture.auth[key]] = value[field];
      }
      io.coreCheck(memberFixture, environment); members.push({ fixture: memberFixture, value });
      for (const key of ['emailEnv', 'passwordEnv', 'totpSecretEnv']) delete environment[memberFixture.auth[key]];
    } finally { loaded.bytes.fill(0); }
  }
  assert.equal(members[0].fixture.membershipId, fixture.membershipId); assert.notEqual(members[0].fixture.companyId, members[1].fixture.companyId);
  return { fixture, build, isolation, source, installed: actual, members, controls,
    publicAdmission: { source, installed: actual, apiRevision: api.revision, webRevision: web.revision, artifactHash: config.expectedBinaryHash, identityAudit, beforeMemberRead: true } };
}
async function withMember(member, action) {
  const previous = new Map();
  try { for (const [key, field] of [['emailEnv', 'email'], ['passwordEnv', 'password'], ['totpSecretEnv', 'totp_secret']]) {
    const name = member.fixture.auth[key]; previous.set(name, process.env[name]); process.env[name] = member.value[field];
  } return await action(); }
  finally { for (const [name, value] of previous) { if (value === undefined) delete process.env[name]; else process.env[name] = value; } }
}
export async function logoutKnown(context, fixture) {
  const account = await find(context, 'id', 'account-open'); await dispatchNativeClick(context, account, 'id', 'account-open');
  assert.equal(await (await find(context, 'id', 'account-principal')).getText(), fixture.principalLabel);
  assert.equal(await (await find(context, 'id', 'account-workspace')).getText(), fixture.workspaceLabel);
  const before = await traffic(context);
  const button = await find(context, 'id', 'sign-out', { scroll: true }); await dispatchNativeClick(context, button, 'id', 'sign-out');
  await context.driver.waitUntil(async () => !!await visible(context.driver, selector(context.platform, 'id', 'signed-out'))
    && !await visible(context.driver, selector(context.platform, 'id', 'session-loading')), { timeout: 20000, interval: 200 });
  const requests = delta(before, await traffic(context));
  assert.equal(requests.filter(row => row.method === 'POST' && row.route === '/api/auth/native/logout' && row.status === 204).length, 1, 'ONE_NATIVE_LOGOUT_ACK_REQUIRED');
  assert.equal(requests.filter(row => !['GET', 'HEAD', 'OPTIONS'].includes(row.method) && row.route !== '/api/auth/native/refresh').length, 1, 'LOGOUT_MUST_NOT_REPLAY');
}
export async function runV1(config) {
  const admitted = await admitV1BeforeMembers(config), { fixture, isolation, source, members } = admitted;
  const collection = collectV1Workflows(config.platform), runId = `${new Date().toISOString().replace(/[:.]/g, '-')}-${config.platform}-v1-${randomUUID().slice(0, 8)}`;
  const report = path.join(config.reportRoot, runId); fs.mkdirSync(report, { recursive: false, mode: 0o700 });
  const journal = new Journal(path.join(report, 'events.jsonl')), frozen = v1HarnessFingerprint();
  journal.write({ type: 'run_started', ...collection, ...source, harnessFingerprint: frozen, publicAdmission: admitted.publicAdmission });
  let completed = false, preflightPassed = false, postflight;
  const deadline = setTimeout(() => { journal.write({ type: 'run_interrupted', reason: 'V1_THIRTY_MINUTE_SERIAL_BOUND' }); journal.close(); process.exit(124); }, V1_BUDGETS.serialInventoryMs); deadline.unref();
  let controls;
  try {
  const controlFile = admitted.controls.module; assert.ok(path.isAbsolute(controlFile.path) && controlFile.path.startsWith(ROOT + path.sep));
  readV1Bytes(controlFile);
  const controlModule = await import(pathToFileURL(controlFile.path)); controls = await controlModule.createControls({ fixture, descriptor: admitted.controls, admission: admitted.publicAdmission });
  for (const name of V1_CONTROL_CAPABILITIES) assert.equal(typeof controls[name], 'function', 'V1_CONTROL_IMPLEMENTATION_REQUIRED');
  const status = await localJson(isolation.gatewayUrl + '/__caseops_e2e/status'), baseline = gatewayBaseline(status, isolation);
  const tooling = process.env.CASEOPS_MOBILE_TOOLING_HOME || path.join(os.homedir(), '.cache/caseops-mobile/tooling');
  const remote = createRequire(path.join(tooling, 'package.json'))('webdriverio').remote;
  const transport = androidSessionTransport(fixture, config.platform), appium = transport.appiumUrl;
  journal.write({ type: 'preflight_result', status: 'passed', buildReceipt: config.buildReceipt, dockerReceipt: config.dockerReceipt, installed: admitted.installed, harnessFingerprint: frozen });
  preflightPassed = true;
  const state = { dispatched: new Set(), versions: [], activeFixture: fixture }; let cleanupUncertain = false, previousFailed = false;
    for (const scenario of v1WorkflowScenarios) {
      const id = `${config.platform}:${scenario.id}`; let driver, context, setupPassed = false, callPassed = false;
      journal.write({ type: 'phase_started', id, phase: 'setup' });
      try {
        assert.equal(cleanupUncertain, false, 'EARLIER_V1_CLEANUP_UNCERTAIN'); assert.equal(v1HarnessFingerprint(), frozen); assert.deepEqual(sourceSnapshot(ROOT), source);
        assert.deepEqual(observeInstalled(fixture, config.platform, config.expectedBinaryHash, process.env), admitted.installed);
        const capabilities = { platformName: config.platform === 'ios' ? 'iOS' : 'Android', 'appium:automationName': config.platform === 'ios' ? 'XCUITest' : 'UiAutomator2',
          'appium:udid': fixture.udid, 'appium:deviceName': fixture.deviceName, 'appium:platformVersion': fixture.platformVersion,
          'appium:noReset': true, 'appium:newCommandTimeout': 60, ...transport.capabilities,
          ...(config.platform === 'ios' ? { 'appium:bundleId': fixture.appId, 'appium:includeSafariInWebviews': true, 'appium:webviewConnectTimeout': 20000 }
            : { 'appium:appPackage': fixture.appId, 'appium:app': fixture.appPath, 'appium:dontStopAppOnReset': true, 'appium:ensureWebviewsHavePages': true, 'appium:enableWebviewDetailsCollection': true }) };
        driver = await remote({ hostname: appium.hostname, port: Number(appium.port) || 4723, protocol: appium.protocol.slice(0, -1), path: appium.pathname,
          logLevel: 'silent', connectionRetryCount: 0, connectionRetryTimeout: V1_BUDGETS.transportMs, capabilities });
        journal.write({ ...appiumSessionEvent(driver.sessionId, 'created'), id });
        if (config.platform === 'android') journal.write({ ...verifyAndroidSessionTransport(fixture, config.platform, driver.capabilities), id });
        await configureNativeDriver(driver, config.platform); await driver.switchContext('NATIVE_APP');
        context = prepareV1Context({ fixture, platform: config.platform, driver, gatewayBaseline: baseline, controls, state, caseId: scenario.id,
          record: value => journal.write({ ...value, id }), authenticate: async (wanted, options) => {
            const member = members.find(value => value.fixture.membershipId === wanted.membershipId); assert.ok(member, 'ADMITTED_NATIVE_MEMBER_REQUIRED');
            return withMember(member, () => authenticate({ ...context, fixture: wanted }, options));
          } });
        if (previousFailed) await restart(context);
        const wanted = scenario.actor === 'second-company' ? members[1].fixture : fixture;
        if (state.activeFixture.membershipId !== wanted.membershipId) await logoutKnown(context, state.activeFixture);
        await context.authenticate(wanted, { fresh: !!scenario.freshAuthentication });
        state.activeFixture = wanted;
        journal.write({ type: 'phase_result', id, phase: 'setup', status: 'passed' }); setupPassed = true;
      } catch (error) { cleanupUncertain = true; journal.write({ type: 'phase_result', id, phase: 'setup', status: 'failed', reason: safeFailure(error, 'V1_SETUP_FAILED') }); }
      journal.write({ type: 'phase_started', id, phase: 'call' });
      if (setupPassed) try { await scenario.run(context); callPassed = true; journal.write({ type: 'phase_result', id, phase: 'call', status: 'passed' }); }
      catch (error) { journal.write({ type: 'phase_result', id, phase: 'call', status: 'failed', reason: safeFailure(error, 'V1_CALL_FAILED') }); }
      else journal.write({ type: 'phase_result', id, phase: 'call', status: 'not-run', reason: 'V1_SETUP_REQUIRED' });
      journal.write({ type: 'phase_started', id, phase: 'teardown' }); let teardownPassed = true;
      try { const clean = await controls.closeCaseControls({ caseId: scenario.id }); assert.equal(clean.observed, true); assert.equal(clean.allOwnedControlsClosed, true); }
      catch { cleanupUncertain = true; teardownPassed = false; }
      if (driver) try {
        if (scenario.id === 'INBOX-01' && callPassed && teardownPassed) {
          await logoutKnown(context, state.activeFixture); state.signedOutAcknowledged = true;
          assert.equal((await driver.$$(selector(config.platform, 'id', 'quick-work-editor'))).length, 0);
          assert.equal((await driver.$$(selector(config.platform, 'id', 'source-detail'))).length, 0);
        }
        const sessionId = driver.sessionId; await driver.deleteSession(); journal.write({ ...appiumSessionEvent(sessionId, 'deleted'), id });
      }
      catch { cleanupUncertain = true; teardownPassed = false; }
      journal.write({ type: 'v1_case_budget_result', id, logical: context?.budget.counts || null, actualControlTransport: controls.publicState() });
      journal.write({ type: 'phase_result', id, phase: 'teardown', status: teardownPassed ? 'passed' : 'failed', ...(teardownPassed ? {} : { reason: 'V1_OWNED_CLEANUP_UNCERTAIN' }) });
      previousFailed = setupPassed && !callPassed;
    }
    assert.equal(cleanupUncertain, false); assert.equal(state.signedOutAcknowledged, true, 'FINAL_V1_SIGNED_OUT_ACK_REQUIRED'); assert.equal(v1HarnessFingerprint(), frozen); assert.deepEqual(sourceSnapshot(ROOT), source);
    reconcileV1Sessions(journal.events, { requireComplete: true });
    assert.deepEqual(observeInstalled(fixture, config.platform, config.expectedBinaryHash, process.env), admitted.installed);
    validateTraffic(await localJson(isolation.gatewayUrl + '/__caseops_e2e/status'), baseline);
    const api = await localJson(isolation.gatewayUrl + '/api/build'), web = await localJson(isolation.webGatewayUrl + '/api/release-identity');
    assert.equal(api.release_sha, source.sourceSha); assert.equal(api.revision, isolation.backendRevision);
    assert.equal(web.release_sha, source.sourceSha); assert.equal(web.revision, isolation.webRevision);
    postflight = { type: 'postflight_result', status: 'passed', harnessFingerprint: frozen, installed: admitted.installed };
  } catch (error) {
    if (preflightPassed) postflight = { type: 'postflight_result', status: 'failed', reason: safeFailure(error, 'V1_POSTFLIGHT_FAILED') };
    else {
      journal.write({ type: 'preflight_result', status: 'failed', reason: safeFailure(error, 'V1_CONTROL_PREFLIGHT_FAILED') });
      for (const id of collection.intended) for (const phase of ['setup', 'call', 'teardown']) {
        journal.write({ type: 'phase_started', id, phase });
        journal.write({ type: 'phase_result', id, phase, status: phase === 'setup' ? 'blocked' : phase === 'call' ? 'not-run' : 'passed', reason: 'V1_PREFLIGHT_REQUIRED_NO_NATIVE_SESSION' });
      }
    }
  }
  finally {
    completed = true; clearTimeout(deadline);
    try {
      if (controls) {
        const closed = await controls.closeRunControls({ caseId: 'INBOX-01' });
        assert.equal(closed.allOwnedControlsClosed, true); assert.equal(closed.authorityCleared, true); assert.equal(closed.journalClosed, true);
        const runtime = await localJson(isolation.gatewayUrl + '/__caseops_e2e/status');
        assert.equal(runtime.v1ControlsEnabled, false); assert.equal(runtime.v1ControlRunClosed, true);
      }
    }
    catch { if (preflightPassed) postflight = { type: 'postflight_result', status: 'failed', reason: 'V1_CONTROL_DISPOSAL_UNVERIFIED' }; }
    finally { controls?.dispose(); for (const member of members) member.value = undefined; }
  }
  if (postflight) journal.write(postflight);
  journal.write({ type: 'run_completed', platform: config.platform, intendedCount: 17 });
  const result = reconcileResults(journal.events, collection.intended); journal.close();
  const preview = journal.events.find(row => row.type === 'v1_assertion' && row.boundary === 'retained-long-obligation-preview');
  const summary = { ...collection, ...result, ...reconcileV1Sessions(journal.events), completed, harnessFingerprint: frozen, report, ...androidLayoutSummary(admitted.installed), core23PassedByThisRun: false, files17PassedByThisRun: false,
    retainedLongObligationPreview: preview?.observed === true ? 'passed' : 'unverified' };
  fs.writeFileSync(path.join(report, 'summary.json'), JSON.stringify(summary, null, 2) + '\n', { flag: 'wx', mode: 0o600 }); return summary;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [platform, mode, file, digest] = process.argv.slice(2);
    if (mode === '--collect') { assert.equal(process.argv.length, 4); console.log(JSON.stringify(collectV1Workflows(platform), null, 2)); }
    else {
      assert.equal(mode, '--request'); assert.equal(process.argv.length, 6); assert.equal(process.env.CASEOPS_NATIVE_V1_GO, 'FUTURE_CANONICAL_NATIVE_WINDOW_RELEASED');
      const config = readV1Reference({ path: file, sha256: digest }, 16384); assert.equal(config.platform, platform); requirePreparedV1(config);
      fs.mkdirSync(config.reportRoot, { recursive: true, mode: 0o700 });
      fs.writeFileSync(path.join(config.reportRoot, `${digest}.claim.json`), JSON.stringify({ request: { path: file, sha256: digest }, platform, at: new Date().toISOString(), noReplay: true }) + '\n', { flag: 'wx', mode: 0o600 });
      const result = await runV1(config); console.log(JSON.stringify(result)); if (result.status !== 'passed') process.exitCode = 1;
    }
  } catch { console.error('V1_NATIVE_REFUSED_OR_INCOMPLETE'); process.exitCode = 1; }
}
