import assert from 'node:assert/strict';
import { observeQaPrivacy, observerConfiguration } from './android-qa-observer.mjs';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, realpathSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { CAMERA_COPY_NAME, CAMERA_PRIVACY_LIMITS } from './camera-files-privacy.mjs';
import { androidLocalProfile } from '../../apps/mobile/e2e/android-local-profile.mjs';

const APP = 'ai.caseops.mobile.dev.localacceptance';
const REPO = fileURLToPath(new URL('../../', import.meta.url));
const SHA = /^[a-f0-9]{64}$/, UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const read = ref => JSON.parse(verifiedFile(ref?.path, ref?.sha256));
const quote = value => `'${String(value).replaceAll("'", "'\"'\"'")}'`;
export const ANDROID_FILES_SCAN_LIMITS = Object.freeze({ files: 4096, entries: 8192, depth: 16,
  fileBytes: 8388608, totalBytes: 67108864 });
function absoluteOutput(file) {
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_ANDROID_FILES_OUTPUT_REQUIRED');
  let parent = path.dirname(file); while (!existsSync(parent)) parent = path.dirname(parent);
  const resolved = path.resolve(realpathSync(parent), path.relative(parent, file));
  assert.ok(!resolved.startsWith(realpathSync(REPO) + path.sep), 'ANDROID_FILES_OUTPUT_OUTSIDE_REPOSITORY_REQUIRED');
  assert.equal(existsSync(resolved), false, 'ANDROID_FILES_OUTPUT_EXISTS'); return resolved;
}
function save(file, value) {
  file = absoluteOutput(file); mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
  writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 }); return { path: file, sha256: hash(bytes) };
}
function selectedTransportMode({ androidTransportMode, environment = process.env }) {
  const configured = environment.CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE;
  if (androidTransportMode !== undefined && configured !== undefined) {
    assert.equal(androidTransportMode, configured, 'ANDROID_FILES_TRANSPORT_MODE_MISMATCH');
  }
  return androidTransportMode === undefined ? configured : androidTransportMode;
}
export const OBSERVER_IDENTITY = ['access', 'deviceKind', 'transportMode', 'shellUid', 'usbDevPath', 'apiLevel', 'abi', 'qemuOff', 'observerAppId', 'observerUid', 'targetApkSha256', 'observerApkSha256', 'sourceSha', 'signerSha256', 'observationDomain', 'fullPackageForceStoppedStateCertified', 'observerInstallationEvidence'];
function accessEvidence(containers) {
  if (containers.transportMode !== 'usb-reverse') return {};
  if (containers.access === 'qa-observer-service') return Object.fromEntries(OBSERVER_IDENTITY.map(key => [key, containers[key]]));
  return Object.fromEntries(['access', 'deviceKind', 'transportMode', 'shellUid', 'runAsUid', 'usbDevPath', 'apiLevel', 'abi', 'qemuOff']
    .map(key => [key, containers[key]]));
}
function device({ udid, appId, androidTransportMode, privacyObserver, environment = process.env, command = execFileSync, deadline = Date.now() + 30000, budget }) {
  const mode = selectedTransportMode({ androidTransportMode, environment });
  const profile = androidLocalProfile(udid, 'DEDICATED_ANDROID_FILES_DEVICE_REQUIRED', mode);
  const physical = mode === 'usb-reverse';
  if (physical) assert.ok(profile.transportMode === mode && profile.deviceKind === 'physical', 'ANDROID_FILES_PHYSICAL_PROFILE_REQUIRED');
  assert.equal(appId, APP, 'DEDICATED_ANDROID_FILES_APP_REQUIRED');
  assert.equal(environment.ADB_SERVER_SOCKET, `tcp:127.0.0.1:${profile.adbPort}`, 'ISOLATED_ANDROID_FILES_ADB_REQUIRED');
  if (environment.ANDROID_ADB_SERVER_PORT !== undefined) assert.equal(environment.ANDROID_ADB_SERVER_PORT, String(profile.adbPort), 'ISOLATED_ANDROID_FILES_ADB_REQUIRED');
  if (environment.ANDROID_SERIAL !== undefined) assert.equal(environment.ANDROID_SERIAL, udid, 'DEDICATED_ANDROID_FILES_DEVICE_REQUIRED');
  const env = Object.fromEntries(['PATH', 'HOME', 'ANDROID_USER_HOME', 'LANG', 'LC_ALL', 'TMPDIR']
    .filter(key => typeof environment[key] === 'string').map(key => [key, environment[key]]));
  Object.assign(env, { ADB_SERVER_SOCKET: environment.ADB_SERVER_SOCKET, ANDROID_ADB_SERVER_PORT: String(profile.adbPort) });
  const run = (args, options = {}) => {
    const remaining = deadline - Date.now(); assert.ok(remaining > 0, 'ANDROID_FILES_OBSERVATION_DEADLINE');
    const byteRoom = budget ? budget.limit - budget.bytes : Infinity;
    assert.ok(byteRoom > 0, 'ANDROID_FILES_OBSERVATION_BYTE_BOUND');
    const value = command('adb', ['-s', udid, ...args], { shell: false, windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'], env, ...options, maxBuffer: Math.min(options.maxBuffer ?? 1048576, byteRoom),
      timeout: Math.min(options.timeout ?? 5000, remaining) });
    if (budget) { budget.bytes += Buffer.byteLength(value); assert.ok(budget.bytes <= budget.limit, 'ANDROID_FILES_OBSERVATION_BYTE_BOUND'); }
    return value;
  };
  const text = args => run(args, { encoding: 'utf8' }).trim();
  // adb shell rejoins argv. Supply one complete quoted command and disable
  // its PTY so descriptor-framed binary reads retain their exact bytes.
  const privatePath = file => {
    assert.ok(typeof file === 'string' && path.posix.normalize(file) === file && !/[\x00-\x1f\x7f]/.test(file), 'ANDROID_FILES_CANONICAL_SCOPED_PATH_REQUIRED');
    const roots = [`/data/user/0/${APP}`, `/storage/emulated/0/Android/data/${APP}`];
    if (roots.some(root => file === root || file.startsWith(`${root}/`))) return true;
    const provider = '/storage/emulated/0/Download';
    assert.ok(file === provider || file.startsWith(`${provider}/`), 'ANDROID_FILES_OWNED_SCOPED_PATH_REQUIRED');
    return false;
  };
  const script = (label, source, args = [], options = {}) => {
    let runAs = false;
    if (physical) {
      assert.ok(['CASEOPS_ANDROID_STAT_V1', 'CASEOPS_ANDROID_LIST_V1', 'CASEOPS_ANDROID_READ_FD_V1', 'CASEOPS_ANDROID_WRITE_ASSET_V1'].includes(label), 'ANDROID_FILES_REVIEWED_SCRIPT_REQUIRED');
      const file = label === 'CASEOPS_ANDROID_READ_FD_V1' ? args[1] : args[0];
      runAs = privatePath(file);
      assert.ok(!runAs || !privacyObserver, 'QA_OBSERVER_PRIVATE_SHELL_REFUSED');
      if (label === 'CASEOPS_ANDROID_WRITE_ASSET_V1') assert.equal(runAs, false, 'ANDROID_FILES_PROVIDER_WRITE_SCOPE_REQUIRED');
    }
    return run(['shell', '-T', [...(runAs ? ['run-as', APP] : []), 'sh', '-c', `# ${label}\n${source}`, '--', ...args].map(quote).join(' ')], options);
  };
  const readlink = file => { assert.ok(!privacyObserver || file === '/sdcard/Download' || !privatePath(file), 'QA_OBSERVER_PRIVATE_SHELL_REFUSED'); return text(['shell', ...(physical && file !== '/sdcard/Download' && privatePath(file) ? ['run-as', APP] : []), 'readlink', '-f', file]); };
  const stat = file => {
    const raw = script('CASEOPS_ANDROID_STAT_V1', 'if [ -L "$1" ]; then printf SYMLINK; elif [ -e "$1" ]; then stat -c "%F|%u|%d|%i|%s|%y|%z" "$1"; else printf ABSENT; fi', [file], { encoding: 'utf8' }).trim();
    if (raw === 'ABSENT') return null;
    assert.notEqual(raw, 'SYMLINK', 'ANDROID_FILES_SYMLINK_REFUSED');
    const fields = raw.split('|');
    assert.ok(fields.length === 7 && ['regular file', 'regular empty file', 'directory'].includes(fields[0])
      && fields.slice(1, 5).every(value => /^\d+$/.test(value)), 'ANDROID_FILES_STAT_REQUIRED');
    return { kind: fields[0] === 'directory' ? 'directory' : 'file', uid: Number(fields[1]), device: fields[2], inode: fields[3],
      sizeBytes: Number(fields[4]), modified: fields[5], changed: fields[6] };
  };
  const physicalStat = file => {
    const runAs = privatePath(file);
    assert.ok(!runAs || !privacyObserver, 'QA_OBSERVER_PRIVATE_SHELL_REFUSED');
    let result;
    try {
      result = run(['shell', '-T', [...(runAs ? ['run-as', APP] : []), 'env', 'LC_ALL=C', '/system/bin/toybox', 'stat',
        '-c', '%F|%u|%d|%i|%s|%y|%z', '--', file].map(quote).join(' ')], { encoding: 'utf8' });
    } catch (error) {
      const valid = value => typeof value === 'string' || Buffer.isBuffer(value);
      const stdout = valid(error?.stdout) ? Buffer.from(error.stdout) : null;
      const stderr = valid(error?.stderr) ? Buffer.from(error.stderr) : null;
      if (budget) {
        budget.bytes += (stdout?.length || 0) + (stderr?.length || 0);
        if (budget.bytes > budget.limit) throw new AggregateError([error], 'ANDROID_FILES_OBSERVATION_BYTE_BOUND', { cause: error });
      }
      // These are complete reviewed toybox diagnostics, including the exact
      // requested path. Permission, I/O, transport and malformed failures keep
      // their original Error; absence is never inferred from test -e.
      const missing = [`stat: '${file}': No such file or directory\n`, `stat: ${file}: No such file or directory\n`];
      if (error?.status === 1 && error.signal === null && error.code === undefined && stdout?.length === 0
        && stderr && stderr.length <= 2048 && Date.now() <= deadline
        && missing.some(value => stderr.equals(Buffer.from(value)))) return null;
      throw error;
    }
    const raw = result.trim(), fields = raw.split('|');
    assert.notEqual(fields[0], 'symbolic link', 'ANDROID_FILES_SYMLINK_REFUSED');
    assert.ok(fields.length === 7 && ['regular file', 'regular empty file', 'directory'].includes(fields[0])
      && fields.slice(1, 5).every(value => /^\d+$/.test(value)), 'ANDROID_FILES_STAT_REQUIRED');
    return { kind: fields[0] === 'directory' ? 'directory' : 'file', uid: Number(fields[1]), device: fields[2], inode: fields[3],
      sizeBytes: Number(fields[4]), modified: fields[5], changed: fields[6] };
  };
  const physicalStatFailures = new Set();
  const observedStat = file => {
    try { return physicalStat(file); }
    catch (error) { physicalStatFailures.add(error); throw error; }
  };
  return { text, script, stat: physical ? observedStat : stat, run, profile, readlink, physical,
    rethrowStatFailure: error => { if (physicalStatFailures.has(error)) throw error; } };
}
function identity(containers) {
  assert.equal(containers?.schemaVersion, 1, 'ATTESTED_ANDROID_FILES_CONTAINERS_REQUIRED');
  assert.equal(containers.kind, 'android-files-containers', 'ATTESTED_ANDROID_FILES_CONTAINERS_REQUIRED');
  assert.equal(containers.platform, 'android', 'ATTESTED_ANDROID_FILES_PLATFORM_REQUIRED');
  const profile = androidLocalProfile(containers.udid, 'DEDICATED_ANDROID_FILES_DEVICE_REQUIRED', containers.transportMode);
  assert.equal(containers.appId, APP, 'DEDICATED_ANDROID_FILES_APP_REQUIRED');
  if (containers.transportMode === 'usb-reverse') {
    assert.equal(profile.deviceKind, 'physical', 'ANDROID_FILES_PHYSICAL_PROFILE_REQUIRED');
    assert.equal(containers.deviceKind, 'physical', 'ANDROID_FILES_PHYSICAL_PROFILE_REQUIRED');
    assert.ok(['run-as', 'qa-observer-service'].includes(containers.access), 'ANDROID_FILES_PHYSICAL_ACCESS_REQUIRED');
    assert.equal(containers.shellUid, 2000, 'ANDROID_FILES_SHELL_ACCESS_REQUIRED');
    if (containers.access === 'qa-observer-service') {
      assert.ok(!Object.hasOwn(containers, 'runAsUid'), 'QA_OBSERVER_RUN_AS_LABEL_FORBIDDEN');
      const d = observerConfiguration(containers.observerInstallationEvidence, containers.udid);
      for (const key of ['observerAppId', 'observerUid', 'targetApkSha256', 'observerApkSha256', 'sourceSha', 'signerSha256']) assert.equal(containers[key], d[key], 'QA_OBSERVER_INSTALLATION_CHANGED');
      assert.equal(containers.packageUid, d.packageUid); assert.equal(containers.observationDomain, d.domain); assert.equal(containers.fullPackageForceStoppedStateCertified, false);
    } else assert.equal(containers.runAsUid, containers.packageUid, 'ANDROID_FILES_RUN_AS_UID_REQUIRED');
    assert.match(containers.usbDevPath || '', /^usb:[A-Za-z0-9.:_-]{1,128}$/, 'ANDROID_FILES_USB_DEVICE_REQUIRED');
    assert.equal(containers.apiLevel, 36, 'ANDROID_FILES_API36_REQUIRED');
    assert.equal(containers.abi, 'arm64-v8a', 'ANDROID_FILES_ARM64_REQUIRED');
    assert.equal(containers.qemuOff, true, 'ANDROID_FILES_PHYSICAL_QEMU_OFF_REQUIRED');
    assert.ok(!Object.hasOwn(containers, 'rootUid') && !Object.hasOwn(containers, 'avdName'), 'ANDROID_FILES_PHYSICAL_ROOT_AVD_FIELDS_FORBIDDEN');
  } else {
    assert.equal(containers.transportMode, undefined, 'ANDROID_FILES_TRANSPORT_MODE_MISMATCH');
    assert.equal(containers.deviceKind, undefined, 'ANDROID_FILES_TRANSPORT_MODE_MISMATCH');
    assert.equal(containers.access, undefined, 'ANDROID_FILES_TRANSPORT_MODE_MISMATCH');
    assert.equal(containers.rootUid, 0, 'ANDROID_FILES_ROOT_ACCESS_REQUIRED');
    assert.equal(containers.avdName, profile.avdName, 'OWNED_ANDROID_AVD_REQUIRED');
  }
  assert.match(containers.bootId || '', UUID, 'ANDROID_FILES_BOOT_ID_REQUIRED');
  assert.equal(containers.appData.path, `/data/user/0/${APP}`, 'ANDROID_FILES_PRIVATE_ROOT_REQUIRED');
  assert.ok(Number.isSafeInteger(containers.packageUid) && containers.packageUid >= 10000, 'ANDROID_FILES_PACKAGE_UID_REQUIRED');
  assert.equal(containers.appData.metadata.uid, containers.packageUid, 'ANDROID_FILES_PRIVATE_OWNER_MISMATCH');
  assert.equal(containers.provider.path, '/storage/emulated/0/Download', 'ANDROID_FILES_PROVIDER_ROOT_REQUIRED');
}

// Read-only attestation. The caller separately authorizes any adb-root command;
// this helper never enables root, clears appdata or modifies a device setting.
export function attestAndroidFilesContainers(options) {
  const io = device(options);
  assert.equal(io.text(['get-state']), 'device', 'READY_ANDROID_FILES_DEVICE_REQUIRED');
  assert.equal(io.text(['shell', 'id', '-u']), io.physical ? '2000' : '0', io.physical ? 'ANDROID_FILES_SHELL_ACCESS_REQUIRED' : 'ANDROID_FILES_ROOT_ACCESS_REQUIRED');
  assert.equal(io.text(['shell', 'am', 'get-current-user']), '0', 'ANDROID_FILES_USER_ZERO_REQUIRED');
  assert.equal(io.text(['shell', 'getprop', 'ro.build.version.sdk']), '36', 'ANDROID_FILES_API36_REQUIRED');
  assert.equal(io.text(['shell', 'getprop', 'ro.product.cpu.abi']), 'arm64-v8a', 'ANDROID_FILES_ARM64_REQUIRED');
  let avd, usbDevPath;
  if (io.physical) {
    usbDevPath = io.text(['get-devpath']); assert.match(usbDevPath, /^usb:[A-Za-z0-9.:_-]{1,128}$/, 'ANDROID_FILES_USB_DEVICE_REQUIRED');
    assert.ok(['', '0'].includes(io.text(['shell', 'getprop', 'ro.kernel.qemu'])), 'ANDROID_FILES_PHYSICAL_QEMU_OFF_REQUIRED');
  } else {
    avd = io.text(['emu', 'avd', 'name']).split(/\r?\n/);
    assert.deepEqual(avd, [io.profile.avdName, 'OK'], 'OWNED_ANDROID_AVD_REQUIRED');
  }
  const bootId = io.text(['shell', 'cat', '/proc/sys/kernel/random/boot_id']); assert.match(bootId, UUID, 'ANDROID_FILES_BOOT_ID_REQUIRED');
  const packageLine = io.text(['shell', 'cmd', 'package', 'list', 'packages', '-U', APP]);
  const match = new RegExp(`^package:${APP.replaceAll('.', '\\.')} uid:(\\d+)$`).exec(packageLine);
  assert.ok(match && Number(match[1]) >= 10000, 'ANDROID_FILES_EXACT_PACKAGE_UID_REQUIRED');
  let native;
  if (io.physical && options.privacyObserver) native = observeQaPrivacy({ ...options, operation: 'attest' }, value => ({ metadata: value.metadata, epoch: observerEpoch(value) }));
  if (io.physical && !native) {
    assert.equal(io.text(['shell', 'run-as', APP, 'id', '-u']), match[1], 'ANDROID_FILES_RUN_AS_UID_REQUIRED');
    assert.equal(io.text(['shell', 'run-as', APP, 'pwd']), `/data/user/0/${APP}`, 'ANDROID_FILES_RUN_AS_PRIVATE_ROOT_REQUIRED');
  }
  const appPath = native ? native.metadata.appData.path : io.readlink(`/data/user/0/${APP}`);
  assert.equal(appPath, `/data/user/0/${APP}`, 'ANDROID_FILES_PRIVATE_ROOT_REQUIRED');
  const providerPath = io.readlink('/sdcard/Download');
  assert.equal(providerPath, '/storage/emulated/0/Download', 'ANDROID_FILES_PROVIDER_ROOT_REQUIRED');
  const appData = { path: appPath, metadata: native ? legacyMetadata(native.metadata.appData.frame) : io.stat(appPath) }, provider = { path: providerPath, metadata: io.stat(providerPath) };
  assert.equal(appData.metadata?.kind, 'directory', 'ANDROID_FILES_PRIVATE_DIRECTORY_REQUIRED');
  assert.equal(appData.metadata.uid, Number(match[1]), 'ANDROID_FILES_PRIVATE_OWNER_MISMATCH');
  assert.equal(provider.metadata?.kind, 'directory', 'ANDROID_FILES_PROVIDER_DIRECTORY_REQUIRED');
  const externalPath = `/storage/emulated/0/Android/data/${APP}`, externalMetadata = native ? (native.metadata.externalAppData ? legacyMetadata(native.metadata.externalAppData.frame) : null) : io.stat(externalPath);
  if (externalMetadata) {
    assert.equal(externalMetadata.kind, 'directory', 'ANDROID_FILES_EXTERNAL_DIRECTORY_REQUIRED');
    if (io.physical && !native) assert.equal(io.readlink(externalPath), externalPath, 'ANDROID_FILES_EXTERNAL_ROOT_REQUIRED');
  }
  const result = { schemaVersion: 1, kind: 'android-files-containers', observed: true, platform: 'android',
    udid: options.udid, appId: APP, packageUid: Number(match[1]), bootId,
    ...(io.physical ? { access: 'run-as', deviceKind: 'physical', transportMode: 'usb-reverse', shellUid: 2000,
      ...(native ? { access: 'qa-observer-service', ...Object.fromEntries(['observerAppId', 'observerUid', 'targetApkSha256', 'observerApkSha256', 'sourceSha', 'signerSha256'].map(key => [key, observerConfiguration(options.privacyObserver, options.udid)[key]])), observationDomain: 'qa-main-preserved-observer-running', fullPackageForceStoppedStateCertified: false, observerInstallationEvidence: options.privacyObserver, observationEpoch: native.epoch } : { runAsUid: Number(match[1]) }), usbDevPath, apiLevel: 36, abi: 'arm64-v8a', qemuOff: true } : { rootUid: 0, avdName: avd[0] }),
    appData, provider, externalAppData: externalMetadata ? { path: externalPath, metadata: externalMetadata } : null };
  identity(result); return result;
}
function current(containers, options) {
  identity(containers);
  const requested = selectedTransportMode(options);
  if (requested !== undefined) assert.equal(requested, containers.transportMode ?? 'emulator', 'ANDROID_FILES_TRANSPORT_MODE_MISMATCH');
  if (containers.access === 'qa-observer-service' && options.privacyObserver) assert.deepEqual(options.privacyObserver, containers.observerInstallationEvidence, 'QA_OBSERVER_INSTALLATION_CHANGED');
  const bound = { ...options, ...(containers.access === 'qa-observer-service' ? { privacyObserver: containers.observerInstallationEvidence } : {}), udid: containers.udid, appId: containers.appId, androidTransportMode: containers.transportMode };
  const actual = attestAndroidFilesContainers(bound);
  const fields = ['udid', 'appId', 'packageUid', 'bootId', ...(containers.transportMode === 'usb-reverse'
    ? (containers.access === 'qa-observer-service' ? OBSERVER_IDENTITY : ['access', 'deviceKind', 'transportMode', 'shellUid', 'runAsUid', 'usbDevPath', 'apiLevel', 'abi', 'qemuOff']) : ['rootUid', 'avdName'])];
  for (const key of fields) assert.deepEqual(actual[key], containers[key], 'ANDROID_FILES_CONTAINER_IDENTITY_CHANGED');
  for (const key of ['appData', 'provider']) {
    assert.equal(actual[key].path, containers[key].path, 'ANDROID_FILES_CONTAINER_IDENTITY_CHANGED');
    for (const field of ['kind', 'uid', 'device', 'inode']) assert.equal(actual[key].metadata[field], containers[key].metadata[field], 'ANDROID_FILES_CONTAINER_IDENTITY_CHANGED');
  }
  assert.equal(Boolean(actual.externalAppData), Boolean(containers.externalAppData), 'ANDROID_FILES_EXTERNAL_ROOT_CHANGED');
  if (containers.externalAppData) {
    assert.equal(actual.externalAppData.path, containers.externalAppData.path, 'ANDROID_FILES_EXTERNAL_ROOT_CHANGED');
    for (const field of ['kind', 'uid', 'device', 'inode']) assert.equal(actual.externalAppData.metadata[field],
      containers.externalAppData.metadata[field], 'ANDROID_FILES_EXTERNAL_ROOT_CHANGED');
  }
  return device(bound);
}

function legacyMetadata(f) { return { kind: (Number(f[2]) & 61440) === 16384 ? 'directory' : 'file', uid: Number(f[3]), device: f[0], inode: f[1], sizeBytes: Number(f[6]), modified: f[7], changed: f[8] }; }
function observerEpoch(value) { const m=value.metadata; return { schemaVersion: 1, access: value.access, domain: value.domain, packageUid: m.packageUid, callerUid: m.callerUid, callerPid: m.callerPid, observerPid: m.observerPid, mainBefore: m.mainBefore, mainAfter: m.mainAfter, lifecycleSequenceBefore: m.lifecycleSequenceBefore, lifecycleSequenceAfter: m.lifecycleSequenceAfter, packageStoppedBefore: value.packageStoppedBefore, packageStoppedAfter: value.packageStoppedAfter, deliberateQaFixtureUnstop: value.deliberateQaFixtureUnstop, fullPackageForceStoppedStateCertified: false, leaseClosed: value.leaseClosed, mainReactApplicationInitializedByObserver: false }; }

function knownSource(value) {
  assert.ok(typeof value?.id === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value.id), 'ANDROID_FILES_KNOWN_SOURCE_ID_REQUIRED');
  assert.ok(/^[A-Za-z0-9][A-Za-z0-9._-]{1,200}$/.test(value.filename || ''), 'ANDROID_FILES_KNOWN_FILENAME_REQUIRED');
  assert.match(value.sha256 || '', SHA, 'ANDROID_FILES_KNOWN_HASH_REQUIRED');
  assert.ok(Number.isSafeInteger(value.sizeBytes) && value.sizeBytes > 0 && value.sizeBytes <= 1048576, 'ANDROID_FILES_KNOWN_SIZE_REQUIRED');
  assert.ok(value.marker === undefined || typeof value.marker === 'string' && value.marker.length > 0 && value.marker.length <= 512,
    'ANDROID_FILES_KNOWN_MARKER_REQUIRED');
  return { id: value.id, filename: value.filename, sha256: value.sha256, sizeBytes: value.sizeBytes,
    ...(value.marker ? { marker: value.marker } : {}) };
}
export function stageAndroidFilesAssets({ containers, manifestEvidence, runId, output, ...options }) {
  absoluteOutput(output); const io = current(containers, options), manifest = read(manifestEvidence);
  assert.equal(manifest.schemaVersion, 1, 'ANDROID_FILES_MANIFEST_VERSION_REQUIRED');
  assert.equal(manifest.platform, 'android', 'ANDROID_FILES_MANIFEST_PLATFORM_REQUIRED');
  assert.equal(manifest.kind, 'android-files-synthetic-fixtures', 'ANDROID_FILES_MANIFEST_KIND_REQUIRED');
  assert.equal(manifest.syntheticDataOnly, true, 'ANDROID_FILES_SYNTHETIC_ASSETS_REQUIRED');
  assert.ok(Array.isArray(manifest.assets) && manifest.assets.length > 0 && manifest.assets.length <= 12, 'ANDROID_FILES_ASSET_COUNT_REQUIRED');
  assert.ok(/^[A-Za-z0-9][A-Za-z0-9-]{5,63}$/.test(runId || ''), 'ANDROID_FILES_UNIQUE_RUN_ID_REQUIRED');
  const assets = manifest.assets.map(asset => {
    const known = knownSource(asset);
    assert.match(asset.filename, /^CaseOps-android-files-[a-f0-9]{12}-(?:txt|pdf|png|jpeg|docx|eicar|unsupported)\.(?:txt|pdf|png|jpeg|jpg|docx|rtf)$/,
      'ANDROID_FILES_PUBLIC_PRODUCER_FILENAME_REQUIRED');
    assert.ok(path.isAbsolute(asset.path || '') && path.basename(asset.path) === asset.filename, 'ANDROID_FILES_ASSET_PATH_REQUIRED');
    const bytes = verifiedFile(asset.path, asset.sha256, 262144);
    assert.equal(bytes.length, asset.sizeBytes, 'ANDROID_FILES_ASSET_SIZE_MISMATCH');
    return { ...known, path: asset.path, bytes };
  });
  assert.equal(new Set(assets.map(asset => asset.filename)).size, assets.length, 'ANDROID_FILES_DUPLICATE_ASSET');
  assert.ok(assets.reduce((sum, asset) => sum + asset.sizeBytes, 0) <= 1048576, 'ANDROID_FILES_TOTAL_ASSET_BOUND');
  const folderName = `CaseOpsFiles-${runId}`, deviceFolderPath = `${containers.provider.path}/${folderName}`;
  const attemptEvidence = save(`${output}.attempt.json`, { schemaVersion: 1, kind: 'android-files-provider-stage-attempt',
    udid: containers.udid, appId: containers.appId, bootId: containers.bootId, ...accessEvidence(containers), manifestEvidence,
    folderName, deviceFolderPath, assets: assets.map(knownSource), automaticReplayAllowed: false });
  // mkdir without -p is the exclusive ownership admission. Never reuse/delete
  // a preexisting provider folder, and never retry an unknown push outcome.
  io.text(['shell', 'mkdir', '-m', '0755', deviceFolderPath]);
  const folderMetadata = io.stat(deviceFolderPath);
  assert.equal(folderMetadata?.kind, 'directory', 'ANDROID_FILES_EXCLUSIVE_PROVIDER_DIRECTORY_REQUIRED');
  const observed = [];
  for (const asset of assets) {
    const devicePath = `${deviceFolderPath}/${asset.filename}`;
    // Transfer the already verified descriptor bytes, never a pathname adb
    // could reopen after it was replaced. Bind cwd to the exclusive directory
    // inode before noclobber creation; no retry can overwrite an earlier file.
    io.script('CASEOPS_ANDROID_WRITE_ASSET_V1', 'cd -P "$1" || exit 41; '
      + '[ "$(stat -c "%d:%i" .)" = "$3" ] || exit 42; [ ! -L "$2" ] || exit 43; '
      + 'umask 022; set -C; cat >"$2" || exit 44', [deviceFolderPath, asset.filename,
      `${folderMetadata.device}:${folderMetadata.inode}`], { input: asset.bytes, encoding: 'utf8', timeout: 15000 });
    const metadata = io.stat(devicePath);
    assert.equal(metadata?.kind, 'file', 'ANDROID_FILES_PROVIDER_FILE_REQUIRED');
    assert.equal(metadata.sizeBytes, asset.sizeBytes, 'ANDROID_FILES_PROVIDER_SIZE_MISMATCH');
    verifiedFile(asset.path, asset.sha256, 262144);
    observed.push({ ...knownSource(asset), devicePath, transferSha256: hash(asset.bytes),
      transferMethod: 'verified-buffer-exclusive-device-write', providerMetadata: metadata });
  }
  current(containers, options);
  const receipt = { schemaVersion: 2, kind: 'android-files-provider-assets', observed: true, platform: 'android',
    udid: containers.udid, appId: containers.appId, bootId: containers.bootId, ...accessEvidence(containers),
    ...(Object.hasOwn(containers, 'avdName') ? { avdName: containers.avdName } : {}),
    manifestEvidence, attemptEvidence, folderName, deviceFolderPath, provider: containers.provider,
    appData: containers.appData, assets: observed, originalsDeleted: false, providerOriginalsRead: false,
    providerOriginalsPreserved: null, originalByteVerification: 'deferred-until-postflight' };
  return { receipt, evidence: save(output, receipt) };
}

function openedBytes(io, file, expected, maxBytes, singleLink = false) {
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0, 'ANDROID_FILES_READ_BOUND_REQUIRED');
  const admitted = [expected.uid, expected.device, expected.inode, expected.sizeBytes, expected.modified, expected.changed].join('|');
  const source = 'expected=$1; p=$2; [ ! -L "$p" ] && [ -f "$p" ] || exit 41; exec 3<"$p" || exit 42; '
    + 'trap \'exec 3<&-\' EXIT; [ "$(readlink -f "$p")" = "$p" ] || exit 40; '
    + 'before=$(stat -Lc "%F|%u|%d|%i|%s|%y|%z" /proc/$$/fd/3) || exit 43; '
    + 'case "$before" in "regular file|"*|"regular empty file|"*) ;; *) exit 38;; esac; '
    + '[ "$(stat -Lc "%u|%d|%i|%s|%y|%z" /proc/$$/fd/3)" = "$expected" ] || exit 37; '
    + 'named=$(stat -c "%F|%u|%d|%i|%s|%y|%z" "$p") || exit 44; [ "$before" = "$named" ] || exit 45; '
    + (singleLink ? '[ "$(stat -Lc %h /proc/$$/fd/3)" = 1 ] || exit 39; ' : '')
    + `size=$(stat -Lc %s /proc/$$/fd/3) || exit 43; [ "$size" -le ${maxBytes} ] || exit 46; `
    + `printf "%s\\n" "$before"; head -c ${maxBytes + 1} <&3 || exit 46; `
    + 'after=$(stat -Lc "%F|%u|%d|%i|%s|%y|%z" /proc/$$/fd/3) || exit 47; '
    + 'named=$(stat -c "%F|%u|%d|%i|%s|%y|%z" "$p") || exit 48; exec 3<&-; '
    + (singleLink ? '[ "$(stat -c %h "$p")" = 1 ] || exit 39; ' : '')
    + '[ "$(readlink -f "$p")" = "$p" ] || exit 40; '
    + '[ "$before" = "$after" ] && [ "$before" = "$named" ] || exit 49; printf "\\n%s\\n" "$after"';
  const result = Buffer.from(io.script('CASEOPS_ANDROID_READ_FD_V1', source, [admitted, file], { maxBuffer: maxBytes + 2048 }));
  const line = result.indexOf(10); assert.ok(line > 0 && line <= 1024, 'ANDROID_FILES_READ_FRAME_REQUIRED');
  const header = result.subarray(0, line).toString('utf8'), fields = header.split('|');
  assert.ok(fields.length === 7 && ['regular file', 'regular empty file'].includes(fields[0]) && /^\d+$/.test(fields[4]), 'ANDROID_FILES_READ_FRAME_REQUIRED');
  assert.equal(Number(fields[4]), expected.sizeBytes, 'ANDROID_FILES_FILE_CHANGED');
  assert.equal(Number(fields[1]), expected.uid, 'ANDROID_FILES_FILE_CHANGED');
  assert.equal(fields[2], expected.device, 'ANDROID_FILES_FILE_CHANGED'); assert.equal(fields[3], expected.inode, 'ANDROID_FILES_FILE_CHANGED');
  assert.equal(fields[5], expected.modified, 'ANDROID_FILES_FILE_CHANGED'); assert.equal(fields[6], expected.changed, 'ANDROID_FILES_FILE_CHANGED');
  const bytes = result.subarray(line + 1, line + 1 + expected.sizeBytes);
  assert.equal(bytes.length, expected.sizeBytes, 'ANDROID_FILES_FILE_CHANGED');
  assert.equal(result.subarray(line + 1 + expected.sizeBytes).toString('utf8'), `\n${header}\n`, 'ANDROID_FILES_FILE_CHANGED');
  return bytes;
}

export function snapshotAndroidFilesPrivacy({ containers, stagingEvidence, priorStagingEvidence = [], knownSources = [], output,
  limits = ANDROID_FILES_SCAN_LIMITS, verifyProviderBytes = false, ...options }) {
  assert.equal(typeof verifyProviderBytes, 'boolean', 'ANDROID_FILES_EXPLICIT_PROVIDER_VERIFICATION_REQUIRED');
  absoluteOutput(output); assert.deepEqual(limits, ANDROID_FILES_SCAN_LIMITS, 'ANDROID_FILES_REVIEWED_SCAN_LIMITS_REQUIRED');
  const deadline = Date.now() + 30000, budget = { bytes: 0, limit: limits.totalBytes }, scanOptions = { ...options, deadline, budget };
  const io = current(containers, scanOptions);
  assert.ok(Array.isArray(priorStagingEvidence) && priorStagingEvidence.length <= 4, 'ANDROID_FILES_PRIOR_COHORT_BOUND');
  const cohorts = [stagingEvidence, ...priorStagingEvidence].map(ref => ({ reference: ref, value: read(ref) }));
  assert.equal(new Set(cohorts.map(({ value }) => value.deviceFolderPath)).size, cohorts.length, 'ANDROID_FILES_DUPLICATE_PROVIDER_COHORT');
  const sources = [], originals = [], providerChecks = [], issues = [], findings = []; let providerBytesRead = 0;
  for (const { value } of cohorts) {
    for (const [key, expected] of Object.entries({ schemaVersion: 2, kind: 'android-files-provider-assets', observed: true, providerOriginalsRead: false,
      platform: 'android', udid: containers.udid, appId: containers.appId, bootId: containers.bootId })) assert.equal(value[key], expected, 'ANDROID_FILES_STAGING_IDENTITY_MISMATCH');
    for (const [key, expected] of Object.entries(accessEvidence(containers))) assert.deepEqual(value[key], expected, 'ANDROID_FILES_STAGING_ACCESS_MISMATCH');
    if (containers.transportMode === 'usb-reverse') assert.ok(!Object.hasOwn(value, 'rootUid') && !Object.hasOwn(value, 'avdName'), 'ANDROID_FILES_STAGING_ACCESS_MISMATCH');
    assert.ok(/^CaseOpsFiles-[A-Za-z0-9-]{6,64}$/.test(value.folderName || ''), 'ANDROID_FILES_OWNED_PROVIDER_FOLDER_REQUIRED');
    assert.equal(value.deviceFolderPath, `${containers.provider.path}/${value.folderName}`, 'ANDROID_FILES_PROVIDER_FOLDER_MISMATCH');
    assert.ok(Array.isArray(value.assets) && value.assets.length > 0 && value.assets.length <= 12, 'ANDROID_FILES_STAGED_ASSETS_REQUIRED');
    const manifest = read(value.manifestEvidence);
    assert.equal(manifest.kind, 'android-files-synthetic-fixtures', 'ANDROID_FILES_STAGING_MANIFEST_REQUIRED');
    assert.equal(manifest.platform, 'android', 'ANDROID_FILES_STAGING_MANIFEST_REQUIRED');
    assert.equal(manifest.syntheticDataOnly, true, 'ANDROID_FILES_STAGING_MANIFEST_REQUIRED');
    const metadata = assets => assets.map(({ id, filename, sha256, sizeBytes }) => ({ id, filename, sha256, sizeBytes }))
      .sort((left, right) => left.filename.localeCompare(right.filename));
    assert.deepEqual(metadata(value.assets), metadata(manifest.assets), 'ANDROID_FILES_COMPLETE_PROVIDER_COHORT_REQUIRED');
    for (const asset of value.assets) {
      sources.push(knownSource(asset)); assert.equal(asset.devicePath, `${value.deviceFolderPath}/${asset.filename}`, 'ANDROID_FILES_PROVIDER_ASSET_PATH_MISMATCH');
      assert.equal(asset.transferSha256, asset.sha256, 'ANDROID_FILES_VERIFIED_TRANSFER_REQUIRED');
      assert.equal(asset.transferMethod, 'verified-buffer-exclusive-device-write', 'ANDROID_FILES_VERIFIED_TRANSFER_REQUIRED');
      assert.deepEqual(Object.keys(asset.providerMetadata || {}).sort(), ['kind','uid','device','inode','sizeBytes','modified','changed'].sort(), 'ANDROID_FILES_STAGED_METADATA_REQUIRED');
      const metadata = io.stat(asset.devicePath);
      const metadataPreserved = ['kind','uid','device','inode','sizeBytes','modified','changed'].every(key => metadata?.[key] === asset.providerMetadata[key])
        && metadata?.kind === 'file' && metadata.sizeBytes === asset.sizeBytes;
      let actualHash = null;
      if (verifyProviderBytes && metadataPreserved) {
        try { const data = openedBytes(io, asset.devicePath, metadata, asset.sizeBytes, true); providerBytesRead += data.length;
          assert.deepEqual(io.stat(asset.devicePath), metadata, 'ANDROID_FILES_PROVIDER_METADATA_CHANGED'); actualHash = hash(data); }
        catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'provider-original-unreadable', filename: asset.filename }); }
      }
      const preserved = verifyProviderBytes ? metadataPreserved && actualHash === asset.sha256 : null;
      originals.push({ filename: asset.filename, sha256: asset.sha256, sizeBytes: asset.sizeBytes, metadataPreserved, preserved,
        ...(verifyProviderBytes ? { observedSha256: actualHash } : { byteVerification: 'deferred-until-postflight' }) });
      providerChecks.push({ path: asset.devicePath, metadata: asset.providerMetadata, row: originals.at(-1) });
      if (!metadataPreserved || verifyProviderBytes && !preserved) issues.push({ reason: 'provider-original-changed', filename: asset.filename });
    }
  }
  assert.ok(Array.isArray(knownSources) && knownSources.length <= 64, 'ANDROID_FILES_KNOWN_SOURCE_BOUND');
  sources.push(...knownSources.map(knownSource));
  const unique = [...new Map(sources.map(value => [`${value.filename}:${value.sha256}`, value])).values()];
  let files = 0, entries = 0, bytesRead = 0, ownedStagingFiles = 0;
  const inventories = [], metadataByPath = new Map();
  const roots = [{ name: 'app-data', ...containers.appData }, ...(containers.externalAppData ? [{ name: 'external-app-data', ...containers.externalAppData }] : [])];
  const inventory = root => {
    const raw = Buffer.from(io.script('CASEOPS_ANDROID_LIST_V1', 'find "$1" -xdev -maxdepth 17 -print0', [root.path], { maxBuffer: 1048576 }));
    assert.ok(raw.length > 0 && raw.at(-1) === 0, 'ANDROID_FILES_DIRECTORY_LIST_FRAME_REQUIRED');
    const paths = new TextDecoder('utf-8', { fatal: true }).decode(raw).split('\0'); paths.pop();
    entries += paths.length;
    assert.ok(entries <= limits.entries, 'ANDROID_FILES_DIRECTORY_ENTRY_BOUND');
    assert.ok(paths.length > 0 && paths.filter(file => file === root.path).length === 1
      && new Set(paths).size === paths.length, 'ANDROID_FILES_COMPLETE_UNIQUE_ROOT_LIST_REQUIRED');
    for (const file of paths) {
      assert.ok(file === root.path || file.startsWith(`${root.path}/`), 'ANDROID_FILES_FOREIGN_SCAN_PATH');
      const relative = file.slice(root.path.length).replace(/^\//, '');
      assert.ok(!relative.split('/').some(part => part === '..') && !/[\x00-\x1f\x7f]/.test(relative), 'ANDROID_FILES_UNSAFE_SCAN_PATH');
      assert.ok(!relative || relative.split('/').length <= limits.depth, 'ANDROID_FILES_DIRECTORY_DEPTH_BOUND');
    }
    return paths.sort();
  };
  let observationEpoch;
  if (containers.access === 'qa-observer-service') {
    observeQaPrivacy({ ...scanOptions, udid: containers.udid, androidTransportMode: containers.transportMode, privacyObserver: containers.observerInstallationEvidence, operation: 'files-snapshot' }, value => {
      observationEpoch=observerEpoch(value); entries=value.metadata.entries; files=value.files.length; bytesRead=value.metadata.privateBytesRead;
      for(const inventory of value.metadata.inventories) inventories.push({ root: inventory.name, initialCount: inventory.initial.length, finalCount: inventory.final.length, initialSha256: hash(JSON.stringify(inventory.initial)), finalSha256: hash(JSON.stringify(inventory.final)), stable: true });
      for(const file of value.files) {
        const root=value.metadata.inventories.find(i=>i.initial.includes(file.path)); const relative=file.path.slice(root.root.length).replace(/^\//,'');
        if(root.name==='app-data' && relative.startsWith('cache/caseops-matter-files-v1/')) ownedStagingFiles++;
        const matches=[]; for(const source of unique) { const reasons=[];
          if(file.sha256===source.sha256)reasons.push('exact-content-sha256');
          if(source.marker&&file.bytes.includes(Buffer.from(source.marker)))reasons.push('synthetic-marker');
          if(path.posix.basename(file.path)===source.filename||file.bytes.includes(Buffer.from(source.filename)))reasons.push('synthetic-filename');
          if(file.bytes.includes(Buffer.from(source.sha256)))reasons.push('synthetic-sha256-metadata');
          if(reasons.length)matches.push({id:source.id,reasons});
        }
        if(matches.length)findings.push({relativePathSha256:hash(`${root.name}/${relative}`),sha256:file.sha256,matches});
      }
    });
  } else {
  for (const root of roots) {
    let paths;
    try { paths = inventory(root); }
    catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'incomplete-initial-directory-inventory', relativePath: root.name }); continue; }
    for (const file of paths) {
      if (Date.now() > deadline) { issues.push({ reason: 'time-bound', relativePath: root.name }); break; }
      const relative = file.slice(root.path.length).replace(/^\//, ''), relativePath = `${root.name}/${relative || '.'}`;
      let metadata;
      try { metadata = io.stat(file); } catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'metadata-unavailable-or-link', relativePath }); continue; }
      if (!metadata) { issues.push({ reason: 'entry-disappeared', relativePath }); continue; }
      metadataByPath.set(file, metadata);
      if (metadata.device !== root.metadata.device) { issues.push({ reason: 'unreviewed-filesystem-boundary', relativePath }); continue; }
      if (metadata.kind === 'directory') continue;
      if (relative.startsWith('cache/caseops-matter-files-v1/')) ownedStagingFiles++;
      if (++files > limits.files || metadata.sizeBytes > limits.fileBytes || bytesRead + metadata.sizeBytes > limits.totalBytes) {
        issues.push({ reason: 'byte-or-file-bound', relativePath }); continue;
      }
      let bytes;
      try { bytes = openedBytes(io, file, metadata, limits.fileBytes); } catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'opened-file-read-failed-or-changed', relativePath }); continue; }
      bytesRead += bytes.length; const sha256 = hash(bytes), matches = [];
      for (const source of unique) {
        const reasons = [];
        if (sha256 === source.sha256) reasons.push('exact-content-sha256');
        if (source.marker && bytes.includes(Buffer.from(source.marker))) reasons.push('synthetic-marker');
        if (path.posix.basename(file) === source.filename || bytes.includes(Buffer.from(source.filename))) reasons.push('synthetic-filename');
        if (bytes.includes(Buffer.from(source.sha256))) reasons.push('synthetic-sha256-metadata');
        if (reasons.length) matches.push({ id: source.id, reasons });
      }
      if (matches.length) findings.push({ relativePath, sha256, matches });
    }
    let finalPaths;
    try { finalPaths = inventory(root); }
    catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'incomplete-final-directory-inventory', relativePath: root.name }); continue; }
    const stable = JSON.stringify(paths) === JSON.stringify(finalPaths);
    inventories.push({ root: root.name, initialCount: paths.length, finalCount: finalPaths.length,
      initialSha256: hash(Buffer.from(JSON.stringify(paths))), finalSha256: hash(Buffer.from(JSON.stringify(finalPaths))), stable });
    if (!stable) { issues.push({ reason: 'directory-inventory-changed', relativePath: root.name }); continue; }
    for (const file of finalPaths) {
      const relativePath = `${root.name}/${file.slice(root.path.length).replace(/^\//, '') || '.'}`;
      try { assert.deepEqual(io.stat(file), metadataByPath.get(file)); }
      catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'directory-or-file-metadata-changed', relativePath }); }
    }
  }
  }
  for (const expected of providerChecks) {
    try { assert.deepEqual(io.stat(expected.path), expected.metadata, 'ANDROID_FILES_PROVIDER_METADATA_CHANGED'); }
    catch (error) { io.rethrowStatFailure(error); expected.row.metadataPreserved = false; if (verifyProviderBytes) expected.row.preserved = false;
      issues.push({ reason: 'provider-original-final-metadata-changed', relativePath: expected.row.filename }); }
  }
  current(containers, scanOptions);
  const snapshot = { schemaVersion: 2, kind: 'android-files-privacy-snapshot', observed: true, platform: 'android',
    udid: containers.udid, appId: containers.appId, bootId: containers.bootId, ...accessEvidence(containers), ownedAppScopeOnly: true,
    providerOriginalsPreserved: verifyProviderBytes ? originals.every(value => value.preserved) : null,
    providerMetadataPreserved: originals.every(value => value.metadataPreserved), providerOriginalsRead: providerBytesRead > 0,
    providerBytesRead, providerByteVerification: verifyProviderBytes ? 'postflight' : 'deferred-until-postflight', providerOriginals: originals,
    ...(observationEpoch ? { observationEpoch } : {}), complete: issues.length === 0, limits, knownSources: unique.map(({ marker, ...metadata }) => metadata), stagingEvidence, priorStagingEvidence,
    counts: { entries, files, bytesRead, observationBytes: budget.bytes, ownedStagingFiles, privateAssetMatchCount: findings.length }, inventories, findings, issues,
    fileContentsRetained: false, credentialValuesPrinted: false, deviceFilesDeleted: false };
  return { snapshot, evidence: save(output, snapshot) };
}

// New, separately reported SDK scope. A legacy known-fixture match count of
// zero cannot certify cleanup of a camera image with previously unknown bytes.
export function snapshotAndroidCameraPrivacy({ containers, output, ...options }) {
  absoluteOutput(output);
  const limits = CAMERA_PRIVACY_LIMITS, deadline = Date.now() + limits.milliseconds;
  const budget = { bytes: 0, limit: limits.totalBytes }, scanOptions = { ...options, deadline, budget };
  const io = current(containers, scanOptions), root = `${containers.appData.path}/cache/ImagePicker`;
  if (containers.access === 'qa-observer-service') {
    const observation = observeQaPrivacy({ ...scanOptions, udid: containers.udid, androidTransportMode: containers.transportMode, privacyObserver: containers.observerInstallationEvidence, operation: 'camera-snapshot' }, value => ({
      schemaVersion: 1, kind: 'camera-sdk-private-copies', platform: 'android', udid: containers.udid, appId: containers.appId, bootId: containers.bootId, packageUid: containers.packageUid, ...accessEvidence(containers), root, complete: true,
      directoryPresent: value.metadata.inventories[0].initial.length > 0, limits, counts: { copies: value.files.length, bytesRead: value.metadata.privateBytesRead, observationBytes: budget.bytes, entries: value.metadata.entries }, readBytesComplete: true,
      copies: value.files.map(file => ({ nameSha256: hash(path.posix.basename(file.path)), sizeBytes: file.sizeBytes, sha256: file.sha256, classification: 'owned-camera-sdk-copy' })), issues: [],
      inventory: [value.metadata.inventories[0].initial,value.metadata.inventories[0].final].map(values => ({count: Math.max(0,values.length-1),sha256:hash(JSON.stringify(values.filter(p=>p!==root)))})), observationEpoch: observerEpoch(value),
      legacyKnownFixtureCountsIncluded: false, providerOriginalsRead: false, fileContentsRecorded: false, filesDeleted: false, encodedMetadataInspected: false, physicalCameraAcceptance: false
    }));
    current(containers, scanOptions); observation.counts.observationBytes=budget.bytes; return { observation, evidence: save(output,observation) };
  }
  const issues = [], copies = [], namespaces = [], pathsByObservation = [];
  let entries = 0, bytesRead = 0, paths = [], readBytesComplete = true;
  const namespace = () => [containers.appData.path, `${containers.appData.path}/cache`, root].map(file => {
    assert.ok(Date.now() <= deadline && ++entries <= limits.entries, 'CAMERA_OBSERVATION_BOUND');
    const metadata = io.stat(file);
    if (metadata) {
      assert.ok(metadata.kind === 'directory' && metadata.uid === containers.packageUid
        && metadata.device === containers.appData.metadata.device, 'CAMERA_DIRECTORY_OWNER_REQUIRED');
      assert.equal(io.readlink(file), file, 'CAMERA_DIRECTORY_NAMESPACE_REQUIRED');
    }
    return { path: file, metadata };
  });
  const initialNamespace = namespace(), present = initialNamespace.at(-1).metadata !== null;
  const inventory = () => {
    if (!present) return [];
    const raw = Buffer.from(io.script('CASEOPS_ANDROID_LIST_V1', 'find "$1" -xdev -maxdepth 2 -print0', [root], { maxBuffer: 65536 }));
    assert.ok(raw.length > 0 && raw.at(-1) === 0, 'CAMERA_DIRECTORY_LIST_FRAME_REQUIRED');
    const found = new TextDecoder('utf-8', { fatal: true }).decode(raw).split('\0'); found.pop(); entries += found.length;
    assert.ok(entries <= limits.entries && found.length <= limits.copies + 1
      && found.filter(file => file === root).length === 1 && new Set(found).size === found.length, 'CAMERA_DIRECTORY_ENTRY_BOUND');
    for (const file of found) assert.ok(file === root || file.startsWith(`${root}/`) && path.posix.dirname(file) === root,
      'CAMERA_DIRECT_CHILD_REQUIRED');
    return found.filter(file => file !== root).sort();
  };
  const observedMetadata = new Map();
  try {
    paths = inventory(); pathsByObservation.push(paths);
    for (const file of paths) {
      assert.ok(Date.now() <= deadline, 'CAMERA_OBSERVATION_BOUND');
      const name = path.posix.basename(file), metadata = io.stat(file);
      observedMetadata.set(file, metadata);
      if (!CAMERA_COPY_NAME.test(name)) { issues.push({ reason: 'unreviewed-camera-entry' }); continue; }
      if (metadata?.kind !== 'file' || metadata.uid !== containers.packageUid || metadata.device !== containers.appData.metadata.device) {
        issues.push({ reason: 'camera-copy-owner-or-kind' }); continue;
      }
      if (metadata.sizeBytes > limits.fileBytes || bytesRead + metadata.sizeBytes > limits.totalBytes) {
        issues.push({ reason: 'camera-copy-byte-bound' }); continue;
      }
      try {
        // Count successful body reads; reserve framing in the independently
        // charged device-output budget. After any uncertain read stop, so its
        // max+1 extent cannot be consumed again by another file.
        const remaining = Math.min(limits.fileBytes, limits.totalBytes - bytesRead, budget.limit - budget.bytes - 2048);
        assert.ok(remaining > 0 && metadata.sizeBytes <= remaining, 'CAMERA_OBSERVATION_BYTE_BOUND');
        const bytes = openedBytes(io, file, metadata, remaining, true); bytesRead += bytes.length;
        copies.push({ nameSha256: hash(name), sizeBytes: bytes.length, sha256: hash(bytes), classification: 'owned-camera-sdk-copy' });
      } catch (error) { io.rethrowStatFailure(error); readBytesComplete = false; issues.push({ reason: 'camera-copy-read-or-identity-failed' }); break; }
    }
    const finalPaths = inventory(); pathsByObservation.push(finalPaths);
    assert.deepEqual(finalPaths, paths, 'CAMERA_DIRECTORY_CHANGED');
    for (const file of finalPaths) assert.deepEqual(io.stat(file), observedMetadata.get(file), 'CAMERA_COPY_CHANGED');
  } catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'camera-directory-incomplete-or-changed' }); }
  try { namespaces.push(initialNamespace, namespace()); assert.deepEqual(namespaces[1], initialNamespace, 'CAMERA_NAMESPACE_CHANGED'); }
  catch (error) { io.rethrowStatFailure(error); issues.push({ reason: 'camera-final-namespace-changed' }); }
  current(containers, scanOptions);
  const observation = { schemaVersion: 1, kind: 'camera-sdk-private-copies', platform: 'android', udid: containers.udid,
    appId: containers.appId, bootId: containers.bootId, packageUid: containers.packageUid, ...accessEvidence(containers), root, complete: issues.length === 0,
    directoryPresent: present, limits, counts: { copies: paths.length, bytesRead, observationBytes: budget.bytes, entries }, readBytesComplete, copies, issues,
    inventory: pathsByObservation.map(values => ({ count: values.length, sha256: hash(JSON.stringify(values)) })),
    legacyKnownFixtureCountsIncluded: false, providerOriginalsRead: false, fileContentsRecorded: false,
    filesDeleted: false, encodedMetadataInspected: false, physicalCameraAcceptance: false };
  return { observation, evidence: save(output, observation) };
}
