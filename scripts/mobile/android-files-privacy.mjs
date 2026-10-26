import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, realpathSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';

const APP = 'ai.caseops.mobile.dev.localacceptance', SERIAL = 'emulator-5584';
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
function device({ udid, appId, environment = process.env, command = execFileSync, deadline = Date.now() + 30000, budget }) {
  assert.equal(udid, SERIAL, 'DEDICATED_ANDROID_FILES_DEVICE_REQUIRED');
  assert.equal(appId, APP, 'DEDICATED_ANDROID_FILES_APP_REQUIRED');
  assert.equal(environment.ADB_SERVER_SOCKET, 'tcp:127.0.0.1:5038', 'ISOLATED_ANDROID_FILES_ADB_REQUIRED');
  const env = Object.fromEntries(['PATH', 'HOME', 'ANDROID_USER_HOME', 'LANG', 'LC_ALL', 'TMPDIR']
    .filter(key => typeof environment[key] === 'string').map(key => [key, environment[key]]));
  Object.assign(env, { ADB_SERVER_SOCKET: environment.ADB_SERVER_SOCKET, ANDROID_ADB_SERVER_PORT: '5038' });
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
  const script = (label, source, args = [], options = {}) => run(['shell', '-T',
    ['sh', '-c', `# ${label}\n${source}`, '--', ...args].map(quote).join(' ')], options);
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
  return { text, script, stat, run };
}
function identity(containers) {
  assert.equal(containers?.schemaVersion, 1, 'ATTESTED_ANDROID_FILES_CONTAINERS_REQUIRED');
  assert.equal(containers.kind, 'android-files-containers', 'ATTESTED_ANDROID_FILES_CONTAINERS_REQUIRED');
  assert.equal(containers.platform, 'android', 'ATTESTED_ANDROID_FILES_PLATFORM_REQUIRED');
  assert.equal(containers.udid, SERIAL, 'DEDICATED_ANDROID_FILES_DEVICE_REQUIRED');
  assert.equal(containers.appId, APP, 'DEDICATED_ANDROID_FILES_APP_REQUIRED');
  assert.equal(containers.rootUid, 0, 'ANDROID_FILES_ROOT_ACCESS_REQUIRED');
  assert.match(containers.bootId || '', UUID, 'ANDROID_FILES_BOOT_ID_REQUIRED');
  assert.equal(containers.avdName, 'CaseOps_Pixel9_API36_arm64', 'OWNED_ANDROID_AVD_REQUIRED');
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
  assert.equal(io.text(['shell', 'id', '-u']), '0', 'ANDROID_FILES_ROOT_ACCESS_REQUIRED');
  assert.equal(io.text(['shell', 'am', 'get-current-user']), '0', 'ANDROID_FILES_USER_ZERO_REQUIRED');
  assert.equal(io.text(['shell', 'getprop', 'ro.build.version.sdk']), '36', 'ANDROID_FILES_API36_REQUIRED');
  assert.equal(io.text(['shell', 'getprop', 'ro.product.cpu.abi']), 'arm64-v8a', 'ANDROID_FILES_ARM64_REQUIRED');
  const avd = io.text(['emu', 'avd', 'name']).split(/\r?\n/);
  assert.deepEqual(avd, ['CaseOps_Pixel9_API36_arm64', 'OK'], 'OWNED_ANDROID_AVD_REQUIRED');
  const bootId = io.text(['shell', 'cat', '/proc/sys/kernel/random/boot_id']); assert.match(bootId, UUID, 'ANDROID_FILES_BOOT_ID_REQUIRED');
  const packageLine = io.text(['shell', 'cmd', 'package', 'list', 'packages', '-U', APP]);
  const match = new RegExp(`^package:${APP.replaceAll('.', '\\.')} uid:(\\d+)$`).exec(packageLine);
  assert.ok(match && Number(match[1]) >= 10000, 'ANDROID_FILES_EXACT_PACKAGE_UID_REQUIRED');
  const appPath = io.text(['shell', 'readlink', '-f', `/data/user/0/${APP}`]);
  assert.equal(appPath, `/data/user/0/${APP}`, 'ANDROID_FILES_PRIVATE_ROOT_REQUIRED');
  const providerPath = io.text(['shell', 'readlink', '-f', '/sdcard/Download']);
  assert.equal(providerPath, '/storage/emulated/0/Download', 'ANDROID_FILES_PROVIDER_ROOT_REQUIRED');
  const appData = { path: appPath, metadata: io.stat(appPath) }, provider = { path: providerPath, metadata: io.stat(providerPath) };
  assert.equal(appData.metadata?.kind, 'directory', 'ANDROID_FILES_PRIVATE_DIRECTORY_REQUIRED');
  assert.equal(appData.metadata.uid, Number(match[1]), 'ANDROID_FILES_PRIVATE_OWNER_MISMATCH');
  assert.equal(provider.metadata?.kind, 'directory', 'ANDROID_FILES_PROVIDER_DIRECTORY_REQUIRED');
  const externalPath = `/storage/emulated/0/Android/data/${APP}`, externalMetadata = io.stat(externalPath);
  if (externalMetadata) assert.equal(externalMetadata.kind, 'directory', 'ANDROID_FILES_EXTERNAL_DIRECTORY_REQUIRED');
  const result = { schemaVersion: 1, kind: 'android-files-containers', observed: true, platform: 'android',
    udid: SERIAL, appId: APP, rootUid: 0, packageUid: Number(match[1]), bootId, avdName: avd[0],
    appData, provider, externalAppData: externalMetadata ? { path: externalPath, metadata: externalMetadata } : null };
  identity(result); return result;
}
function current(containers, options) {
  identity(containers);
  const actual = attestAndroidFilesContainers({ ...options, udid: containers.udid, appId: containers.appId });
  for (const key of ['udid', 'appId', 'rootUid', 'packageUid', 'bootId', 'avdName']) assert.equal(actual[key], containers[key], 'ANDROID_FILES_CONTAINER_IDENTITY_CHANGED');
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
  return device({ ...options, udid: containers.udid, appId: containers.appId });
}
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
function providerHash(io, file) {
  const output = io.text(['shell', 'sha256sum', file]);
  assert.ok(SHA.test(output.slice(0, 64)) && output.slice(64) === `  ${file}`, 'ANDROID_FILES_EXACT_PROVIDER_HASH_REQUIRED');
  return output.slice(0, 64);
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
    udid: containers.udid, appId: containers.appId, bootId: containers.bootId, manifestEvidence,
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
    assert.equal(providerHash(io, devicePath), asset.sha256, 'ANDROID_FILES_PROVIDER_HASH_MISMATCH');
    verifiedFile(asset.path, asset.sha256, 262144);
    observed.push({ ...knownSource(asset), devicePath, observedProviderHash: asset.sha256 });
  }
  current(containers, options);
  const receipt = { schemaVersion: 1, kind: 'android-files-provider-assets', observed: true, platform: 'android',
    udid: containers.udid, appId: containers.appId, bootId: containers.bootId, avdName: containers.avdName,
    manifestEvidence, attemptEvidence, folderName, deviceFolderPath, provider: containers.provider,
    appData: containers.appData, assets: observed, originalsDeleted: false };
  return { receipt, evidence: save(output, receipt) };
}

function openedBytes(io, file, expected, maxBytes) {
  const source = 'p=$1; [ ! -L "$p" ] && [ -f "$p" ] || exit 41; exec 3<"$p" || exit 42; '
    + 'before=$(stat -Lc "%F|%u|%d|%i|%s|%y|%z" /proc/$$/fd/3) || exit 43; '
    + 'named=$(stat -c "%F|%u|%d|%i|%s|%y|%z" "$p") || exit 44; [ "$before" = "$named" ] || exit 45; '
    + 'printf "%s\\n" "$before"; cat <&3 || exit 46; '
    + 'after=$(stat -Lc "%F|%u|%d|%i|%s|%y|%z" /proc/$$/fd/3) || exit 47; '
    + 'named=$(stat -c "%F|%u|%d|%i|%s|%y|%z" "$p") || exit 48; exec 3<&-; '
    + '[ "$before" = "$after" ] && [ "$before" = "$named" ] || exit 49; printf "\\n%s\\n" "$after"';
  const result = Buffer.from(io.script('CASEOPS_ANDROID_READ_FD_V1', source, [file], { maxBuffer: maxBytes + 2048 }));
  const line = result.indexOf(10); assert.ok(line > 0 && line <= 1024, 'ANDROID_FILES_READ_FRAME_REQUIRED');
  const header = result.subarray(0, line).toString('utf8'), fields = header.split('|');
  assert.ok(fields.length === 7 && ['regular file', 'regular empty file'].includes(fields[0]) && /^\d+$/.test(fields[4]), 'ANDROID_FILES_READ_FRAME_REQUIRED');
  assert.equal(Number(fields[4]), expected.sizeBytes, 'ANDROID_FILES_FILE_CHANGED');
  assert.equal(fields[2], expected.device, 'ANDROID_FILES_FILE_CHANGED'); assert.equal(fields[3], expected.inode, 'ANDROID_FILES_FILE_CHANGED');
  assert.equal(fields[5], expected.modified, 'ANDROID_FILES_FILE_CHANGED'); assert.equal(fields[6], expected.changed, 'ANDROID_FILES_FILE_CHANGED');
  const bytes = result.subarray(line + 1, line + 1 + expected.sizeBytes);
  assert.equal(bytes.length, expected.sizeBytes, 'ANDROID_FILES_FILE_CHANGED');
  assert.equal(result.subarray(line + 1 + expected.sizeBytes).toString('utf8'), `\n${header}\n`, 'ANDROID_FILES_FILE_CHANGED');
  return bytes;
}

export function snapshotAndroidFilesPrivacy({ containers, stagingEvidence, priorStagingEvidence = [], knownSources = [], output,
  limits = ANDROID_FILES_SCAN_LIMITS, ...options }) {
  absoluteOutput(output); assert.deepEqual(limits, ANDROID_FILES_SCAN_LIMITS, 'ANDROID_FILES_REVIEWED_SCAN_LIMITS_REQUIRED');
  const deadline = Date.now() + 30000, budget = { bytes: 0, limit: limits.totalBytes }, scanOptions = { ...options, deadline, budget };
  const io = current(containers, scanOptions);
  assert.ok(Array.isArray(priorStagingEvidence) && priorStagingEvidence.length <= 4, 'ANDROID_FILES_PRIOR_COHORT_BOUND');
  const cohorts = [stagingEvidence, ...priorStagingEvidence].map(ref => ({ reference: ref, value: read(ref) }));
  assert.equal(new Set(cohorts.map(({ value }) => value.deviceFolderPath)).size, cohorts.length, 'ANDROID_FILES_DUPLICATE_PROVIDER_COHORT');
  const sources = [], originals = [], issues = [], findings = [];
  for (const { value } of cohorts) {
    for (const [key, expected] of Object.entries({ schemaVersion: 1, kind: 'android-files-provider-assets', observed: true,
      platform: 'android', udid: containers.udid, appId: containers.appId, bootId: containers.bootId })) assert.equal(value[key], expected, 'ANDROID_FILES_STAGING_IDENTITY_MISMATCH');
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
      const metadata = io.stat(asset.devicePath), actualHash = metadata?.kind === 'file' && metadata.sizeBytes === asset.sizeBytes ? providerHash(io, asset.devicePath) : null;
      const preserved = metadata?.sizeBytes === asset.sizeBytes && actualHash === asset.sha256;
      originals.push({ filename: asset.filename, sha256: asset.sha256, sizeBytes: asset.sizeBytes, preserved });
      if (!preserved) issues.push({ reason: 'provider-original-changed', filename: asset.filename });
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
  for (const root of roots) {
    let paths;
    try { paths = inventory(root); }
    catch { issues.push({ reason: 'incomplete-initial-directory-inventory', relativePath: root.name }); continue; }
    for (const file of paths) {
      if (Date.now() > deadline) { issues.push({ reason: 'time-bound', relativePath: root.name }); break; }
      const relative = file.slice(root.path.length).replace(/^\//, ''), relativePath = `${root.name}/${relative || '.'}`;
      let metadata;
      try { metadata = io.stat(file); } catch { issues.push({ reason: 'metadata-unavailable-or-link', relativePath }); continue; }
      if (!metadata) { issues.push({ reason: 'entry-disappeared', relativePath }); continue; }
      metadataByPath.set(file, metadata);
      if (metadata.device !== root.metadata.device) { issues.push({ reason: 'unreviewed-filesystem-boundary', relativePath }); continue; }
      if (metadata.kind === 'directory') continue;
      if (relative.startsWith('cache/caseops-matter-files-v1/')) ownedStagingFiles++;
      if (++files > limits.files || metadata.sizeBytes > limits.fileBytes || bytesRead + metadata.sizeBytes > limits.totalBytes) {
        issues.push({ reason: 'byte-or-file-bound', relativePath }); continue;
      }
      let bytes;
      try { bytes = openedBytes(io, file, metadata, limits.fileBytes); } catch { issues.push({ reason: 'opened-file-read-failed-or-changed', relativePath }); continue; }
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
    catch { issues.push({ reason: 'incomplete-final-directory-inventory', relativePath: root.name }); continue; }
    const stable = JSON.stringify(paths) === JSON.stringify(finalPaths);
    inventories.push({ root: root.name, initialCount: paths.length, finalCount: finalPaths.length,
      initialSha256: hash(Buffer.from(JSON.stringify(paths))), finalSha256: hash(Buffer.from(JSON.stringify(finalPaths))), stable });
    if (!stable) { issues.push({ reason: 'directory-inventory-changed', relativePath: root.name }); continue; }
    for (const file of finalPaths) {
      const relativePath = `${root.name}/${file.slice(root.path.length).replace(/^\//, '') || '.'}`;
      try { assert.deepEqual(io.stat(file), metadataByPath.get(file)); }
      catch { issues.push({ reason: 'directory-or-file-metadata-changed', relativePath }); }
    }
  }
  current(containers, scanOptions);
  const snapshot = { schemaVersion: 1, kind: 'android-files-privacy-snapshot', observed: true, platform: 'android',
    udid: containers.udid, appId: containers.appId, bootId: containers.bootId, ownedAppScopeOnly: true,
    providerOriginalsPreserved: originals.every(value => value.preserved), providerOriginals: originals,
    complete: issues.length === 0, limits, knownSources: unique.map(({ marker, ...metadata }) => metadata), stagingEvidence, priorStagingEvidence,
    counts: { entries, files, bytesRead, observationBytes: budget.bytes, ownedStagingFiles, privateAssetMatchCount: findings.length }, inventories, findings, issues,
    fileContentsRetained: false, credentialValuesPrinted: false, deviceFilesDeleted: false };
  return { snapshot, evidence: save(output, snapshot) };
}
