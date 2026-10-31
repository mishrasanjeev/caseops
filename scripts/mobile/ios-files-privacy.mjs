import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { closeSync, constants, existsSync, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync, opendirSync, readSync, realpathSync, writeFileSync, writeSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { observeIosCameraDirectory } from './camera-files-privacy.mjs';

const REPO = fileURLToPath(new URL('../../', import.meta.url));
const require = createRequire(new URL('../../apps/mobile/package.json', import.meta.url));
const binaryPlist = require('bplist-parser');
const xmlPlist = require('@expo/plist').default;
const META = '.com.apple.mobile_container_manager.metadata.plist';
const GROUP = 'group.com.apple.FileProvider.LocalStorage';
const APP = 'ai.caseops.mobile.dev.simulatoracceptance';
const DEFAULT_DEVICES = path.join(os.homedir(), 'Library/Developer/CoreSimulator/Devices');
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const ref = (file, bytes) => ({ path: file, sha256: sha(bytes) });
const inside = (root, file) => { const relative = path.relative(root, file); return relative && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative); };
const jsonRef = (value) => JSON.parse(verifiedFile(value?.path, value?.sha256));

function bytes(file, limit, expected, budget) {
  const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
  const identity = value => fields.map(key => String(value[key]));
  const namespace = () => {
    assert.ok(path.isAbsolute(file) && path.resolve(file) === file && realpathSync(file) === file, 'FILES_EVIDENCE_NAMESPACE');
    const values = []; let parent = path.dirname(file);
    while (true) {
      const stat = lstatSync(parent, { bigint: true });
      assert.ok(stat.isDirectory() && !stat.isSymbolicLink(), 'FILES_EVIDENCE_NAMESPACE');
      // Bind parent identities/canonical paths, not unrelated sibling-entry
      // timestamps. The opened file retains its complete nine-field fence.
      values.push([parent, ['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(stat[key]))]);
      if (path.dirname(parent) === parent) break;
      parent = path.dirname(parent);
    }
    return values;
  };
  const fd = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const opened = fstatSync(fd, { bigint: true });
    const ancestors = namespace(), before = lstatSync(file, { bigint: true });
    assert.ok(before.isFile() && !before.isSymbolicLink(), 'REGULAR_FILES_EVIDENCE_REQUIRED');
    assert.ok(opened.isFile() && opened.nlink === 1n && opened.uid === BigInt(process.getuid())
      && opened.size >= 0n && opened.size <= BigInt(limit), 'FILES_EVIDENCE_BYTE_BOUND');
    if (budget) assert.ok(opened.size <= BigInt(budget.limit - budget.bytes), 'FILES_EVIDENCE_TOTAL_BOUND');
    assert.deepEqual(identity(before), identity(opened), 'FILES_EVIDENCE_REPLACED');
    const buffer = Buffer.alloc(Math.min(limit + 1, budget ? budget.limit - budget.bytes + 1 : limit + 1)); let length = 0;
    while (length < buffer.length) {
      const count = readSync(fd, buffer, length, buffer.length - length, null);
      if (!count) break;
      length += count;
      if (budget) { budget.bytes += count; assert.ok(budget.bytes <= budget.limit, 'FILES_EVIDENCE_TOTAL_BOUND'); }
    }
    assert.ok(length <= limit && BigInt(length) === opened.size, 'FILES_EVIDENCE_BYTE_BOUND');
    const data = buffer.subarray(0, length);
    assert.deepEqual(identity(opened), identity(fstatSync(fd, { bigint: true })), 'FILES_EVIDENCE_CHANGED');
    assert.deepEqual(identity(opened), identity(lstatSync(file, { bigint: true })), 'FILES_EVIDENCE_CHANGED');
    assert.deepEqual(namespace(), ancestors, 'FILES_EVIDENCE_NAMESPACE');
    if (expected) assert.equal(sha(data), expected, 'FILES_ASSET_HASH_MISMATCH');
    return data;
  } finally { closeSync(fd); }
}
function directory(file) {
  assert.ok(path.isAbsolute(file) && lstatSync(file).isDirectory() && !lstatSync(file).isSymbolicLink()
    && realpathSync(file) === path.resolve(file), 'EXACT_CONTAINER_DIRECTORY_REQUIRED');
  return file;
}
function metadata(root, identifier, evidence) {
  const file = path.join(root, META), data = bytes(file, 131072, evidence?.sha256);
  if (evidence) assert.equal(evidence.path, file, 'CONTAINER_METADATA_PATH_MISMATCH');
  const value = data.subarray(0, 6).toString() === 'bplist' ? binaryPlist.parseBuffer(data)[0] : xmlPlist.parse(data.toString());
  assert.equal(value.MCMMetadataIdentifier, identifier, 'CONTAINER_METADATA_IDENTITY_MISMATCH');
  return ref(file, data);
}
function validateContainers(value) {
  assert.equal(value.kind, 'ios-files-containers', 'ATTESTED_IOS_FILES_CONTAINERS_REQUIRED');
  assert.equal(value.appId, APP, 'DEDICATED_IOS_APP_REQUIRED');
  assert.match(value.udid || '', /^[a-fA-F0-9-]{36}$/, 'EXACT_SIMULATOR_UDID_REQUIRED');
  assert.equal(path.basename(path.dirname(value.deviceDataPath)), value.udid, 'CONTAINER_DEVICE_SCOPE_MISMATCH');
  directory(value.deviceDataPath); directory(value.appData.path); directory(value.provider.groupPath); directory(value.provider.storagePath);
  assert.equal(path.dirname(value.appData.path), path.join(value.deviceDataPath, 'Containers/Data/Application'), 'APP_DATA_CONTAINER_SCOPE_MISMATCH');
  assert.equal(path.dirname(value.provider.groupPath), path.join(value.deviceDataPath, 'Containers/Shared/AppGroup'), 'PROVIDER_CONTAINER_SCOPE_MISMATCH');
  assert.equal(value.provider.groupId, GROUP, 'LOCAL_FILES_PROVIDER_REQUIRED');
  assert.equal(value.provider.storagePath, path.join(value.provider.groupPath, 'File Provider Storage'), 'LOCAL_PROVIDER_STORAGE_PATH_MISMATCH');
  metadata(value.appData.path, APP, value.appData.metadataEvidence);
  metadata(value.provider.groupPath, GROUP, value.provider.metadataEvidence);
  return value;
}
function outputPath(file, containers) {
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_FILES_RECEIPT_REQUIRED');
  let parent = path.dirname(file);
  while (!existsSync(parent)) parent = path.dirname(parent);
  const target = path.resolve(realpathSync(parent), path.relative(parent, file));
  assert.ok(target !== REPO && !inside(REPO, target) && !inside(containers.deviceDataPath, target), 'FILES_RECEIPT_MUST_STAY_OUTSIDE_REPOSITORY_AND_DEVICE');
  assert.ok(!existsSync(file), 'FILES_RECEIPT_ALREADY_EXISTS');
  return file;
}
function writeReceipt(file, value) {
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const data = Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
  writeFileSync(file, data, { flag: 'wx', mode: 0o600 }); return ref(file, data);
}

export function attestIosFilesContainers({ udid, appId = APP, devicesRoot = DEFAULT_DEVICES, run = execFileSync }) {
  assert.match(udid || '', /^[a-fA-F0-9-]{36}$/, 'EXACT_SIMULATOR_UDID_REQUIRED');
  assert.equal(appId, APP, 'DEDICATED_IOS_APP_REQUIRED');
  const command = (args) => run('/usr/bin/xcrun', ['simctl', ...args], { encoding: 'utf8', timeout: 10000, maxBuffer: 131072, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  const inventory = JSON.parse(command(['list', 'devices', 'available', '--json']));
  const matches = Object.entries(inventory.devices || {}).flatMap(([runtime, devices]) => devices.filter((device) => device.udid === udid).map((device) => ({ ...device, runtime })));
  assert.ok(matches.length === 1 && matches[0].isAvailable === true && matches[0].state === 'Booted'
    && /^com\.apple\.CoreSimulator\.SimRuntime\.iOS-/.test(matches[0].runtime), 'ONE_BOOTED_IOS_SIMULATOR_REQUIRED');
  const deviceDataPath = directory(path.join(realpathSync(devicesRoot), udid, 'data'));
  const appData = directory(command(['get_app_container', udid, appId, 'data']));
  const groups = command(['get_app_container', udid, 'com.apple.DocumentsApp', 'groups']).split(/\r?\n/)
    .map((line) => line.split('\t')).filter(([identifier]) => identifier === GROUP);
  assert.ok(groups.length === 1 && groups[0].length === 2, 'EXACT_LOCAL_FILES_GROUP_REQUIRED');
  const groupPath = directory(groups[0][1]);
  const value = { schemaVersion: 1, kind: 'ios-files-containers', udid, appId, deviceDataPath,
    device: { name: matches[0].name, runtime: matches[0].runtime, state: matches[0].state },
    appData: { path: appData, metadataEvidence: metadata(appData, appId) },
    provider: { hostAppId: 'com.apple.DocumentsApp', groupId: GROUP, groupPath,
      storagePath: directory(path.join(groupPath, 'File Provider Storage')), metadataEvidence: metadata(groupPath, GROUP) },
    nativeUiExecuted: false };
  return validateContainers(value);
}

function markers(asset) {
  const declared = [asset.expected?.segmentMarkers, asset.expected?.pageMarkers].filter((value) => value !== undefined);
  assert.ok(declared.every((value) => Array.isArray(value) && value.length <= 16), 'BOUNDED_PUBLIC_MARKERS_REQUIRED');
  const result = [...new Set([asset.marker, ...declared.flat()].filter((value) => value !== undefined))];
  assert.ok(result.length <= 32 && result.every((value) => typeof value === 'string' && Buffer.byteLength(value) >= 16
    && Buffer.byteLength(value) <= 256 && !value.includes('\0')), 'UNIQUE_PUBLIC_ASSET_MARKER_REQUIRED');
  return result;
}
function knownSource(asset) {
  assert.match(asset.id || '', /^[A-Za-z0-9_-]{1,80}$/, 'FILES_ASSET_ID_REQUIRED');
  assert.ok(typeof asset.filename === 'string' && asset.filename.length > 0 && asset.filename.length <= 160
    && path.basename(asset.filename) === asset.filename && !/[\x00-\x1f\x7f/\\]/.test(asset.filename)
    && !['.', '..'].includes(asset.filename) && !/(credential|secret|\.key$|\.pem$)/i.test(asset.filename), 'PUBLIC_ASSET_BASENAME_REQUIRED');
  assert.match(asset.sha256 || '', /^[a-f0-9]{64}$/, 'FILES_ASSET_SHA_REQUIRED');
  assert.ok(Number.isSafeInteger(asset.sizeBytes) && asset.sizeBytes > 0 && asset.sizeBytes <= 8388608, 'KNOWN_SOURCE_SIZE_BOUND');
  markers(asset); return asset;
}
function manifestAssets(evidence) {
  const manifest = jsonRef(evidence);
  assert.equal(manifest.schemaVersion, 1, 'FILES_MANIFEST_VERSION_REQUIRED');
  assert.equal(manifest.kind, 'ios-files-synthetic-fixtures', 'IOS_FILES_FIXTURE_MANIFEST_REQUIRED');
  assert.equal(manifest.platform, 'ios', 'IOS_FILES_FIXTURE_MANIFEST_REQUIRED');
  assert.equal(manifest.syntheticDataOnly, true, 'PUBLIC_SYNTHETIC_ASSETS_REQUIRED');
  assert.ok(Array.isArray(manifest.assets) && manifest.assets.length > 0 && manifest.assets.length <= 16, 'BOUNDED_FILES_ASSET_INVENTORY_REQUIRED');
  const names = new Set(), ids = new Set(); let total = 0;
  for (const asset of manifest.assets) {
    knownSource(asset);
    assert.ok(!ids.has(asset.id), 'DUPLICATE_FILES_ASSET'); ids.add(asset.id);
    assert.ok(typeof asset.filename === 'string' && asset.filename.length > 0 && asset.filename.length <= 160
      && path.basename(asset.filename) === asset.filename && !/[\x00-\x1f\x7f/\\]/.test(asset.filename)
      && !['.', '..'].includes(asset.filename) && !/(credential|secret|\.key$|\.pem$)/i.test(asset.filename), 'PUBLIC_ASSET_BASENAME_REQUIRED');
    assert.ok(!names.has(asset.filename), 'DUPLICATE_FILES_ASSET'); names.add(asset.filename);
    assert.ok(path.isAbsolute(asset.path || ''), 'ABSOLUTE_PUBLIC_ASSET_PATH_REQUIRED');
    assert.match(asset.sha256 || '', /^[a-f0-9]{64}$/, 'FILES_ASSET_SHA_REQUIRED');
    assert.ok(Number.isSafeInteger(asset.sizeBytes) && asset.sizeBytes > 0 && asset.sizeBytes <= 262144, 'PUBLIC_ASSET_SIZE_BOUND');
    total += asset.sizeBytes; assert.ok(total <= 1048576, 'PUBLIC_ASSET_TOTAL_BOUND');
  }
  return manifest.assets;
}

const PROVIDER_FIELDS = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
function providerMetadata(file) {
  const value = lstatSync(file, { bigint: true });
  assert.ok(value.isFile() && !value.isSymbolicLink() && value.uid === BigInt(process.getuid()) && value.nlink === 1n
    && (value.mode & 0o7777n) === 0o600n && realpathSync(file) === file, 'PROVIDER_ORIGINAL_METADATA_REQUIRED');
  return Object.fromEntries(PROVIDER_FIELDS.map(key => [key, String(value[key])]));
}
function writeProviderAsset(file, data, deadline) {
  const frame = value => PROVIDER_FIELDS.map(key => String(value[key]));
  const parents = () => {
    assert.equal(realpathSync(path.dirname(file)), path.dirname(file), 'PROVIDER_WRITE_NAMESPACE_CHANGED');
    const result = [];
    for (let p = path.dirname(file); ; p = path.dirname(p)) {
      assert.ok(Date.now() < deadline, 'PROVIDER_STAGING_DEADLINE');
      const value = lstatSync(p, { bigint: true }); assert.ok(value.isDirectory() && !value.isSymbolicLink());
      result.push([p, ...['dev','ino','mode','uid','gid'].map(key => String(value[key]))]);
      if (path.dirname(p) === p) return result;
    }
  };
  const before = parents();
  const fd = openSync(file, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW | constants.O_NONBLOCK, 0o600);
  try {
    const opened = fstatSync(fd, { bigint: true });
    assert.ok(opened.isFile() && opened.nlink === 1n && opened.uid === BigInt(process.getuid()) && opened.size === 0n
      && (opened.mode & 0o7777n) === 0o600n, 'PROVIDER_WRITE_IDENTITY_REQUIRED');
    assert.deepEqual(frame(opened), frame(lstatSync(file, { bigint: true })));
    let offset = 0;
    while (offset < data.length) {
      assert.ok(Date.now() < deadline, 'PROVIDER_STAGING_DEADLINE');
      const count = writeSync(fd, data, offset, Math.min(65536, data.length - offset));
      assert.ok(Number.isSafeInteger(count) && count > 0 && count <= Math.min(65536, data.length - offset), 'PROVIDER_WRITE_NO_PROGRESS'); offset += count;
    }
    fsyncSync(fd); assert.ok(Date.now() < deadline, 'PROVIDER_STAGING_DEADLINE');
    const finished = fstatSync(fd, { bigint: true });
    assert.deepEqual(frame(finished).slice(0, 6), frame(opened).slice(0, 6)); assert.equal(finished.size, BigInt(data.length));
    assert.deepEqual(frame(finished), frame(lstatSync(file, { bigint: true })));
    assert.deepEqual(parents(), before); assert.equal(realpathSync(file), file);
    assert.deepEqual(frame(fstatSync(fd, { bigint: true })), frame(finished));
    assert.deepEqual(frame(lstatSync(file, { bigint: true })), frame(finished));
    return Object.fromEntries(PROVIDER_FIELDS.map(key => [key, String(finished[key])]));
  } finally { closeSync(fd); }
}

export function stageIosFilesAssets({ containers, manifestEvidence, runId, output }) {
  const deadline = Date.now() + 30000;
  validateContainers(containers); outputPath(output, containers);
  assert.match(runId || '', /^[a-zA-Z0-9][a-zA-Z0-9-]{5,63}$/, 'UNIQUE_FILES_RUN_ID_REQUIRED');
  const assets = manifestAssets(manifestEvidence);
  const prepared = assets.map((asset) => {
    assert.ok(asset.path !== containers.deviceDataPath && !inside(containers.deviceDataPath, asset.path), 'HOST_FIXTURE_MUST_NOT_READ_DEVICE_PROVIDER');
    const data = bytes(asset.path, 262144, asset.sha256); assert.equal(data.length, asset.sizeBytes, 'FILES_ASSET_SIZE_MISMATCH'); return { asset, data };
  });
  const folderName = `CaseOpsFiles-${runId}`, folderPath = path.join(containers.provider.storagePath, folderName);
  mkdirSync(folderPath, { recursive: false, mode: 0o700 });
  const staged = prepared.map(({ asset, data }) => {
    const file = path.join(folderPath, asset.filename), metadata = writeProviderAsset(file, data, deadline);
    return { id: asset.id, filename: asset.filename, path: file, sha256: asset.sha256, sizeBytes: asset.sizeBytes,
      transferSha256: sha(data), transferMethod: 'verified-buffer-exclusive-descriptor-write', providerMetadata: metadata };
  });
  const receipt = { schemaVersion: 2, kind: 'ios-files-provider-assets', udid: containers.udid, appId: containers.appId,
    syntheticDataOnly: true, manifestEvidence, containers, folderName, folderPath, assets: staged,
    ownedStagingRoot: path.join(containers.appData.path, 'Library/Caches/caseops-matter-files-v1'),
    appPrivateImportRoots: ['Documents/Inbox', 'tmp', 'Library/Caches/DocumentPicker'].map((relativePath) => ({
      relativePath, path: path.join(containers.appData.path, relativePath), existsAtStaging: existsSync(path.join(containers.appData.path, relativePath)) })),
    providerOriginalsRead: false, providerOriginalsPreserved: null, originalByteVerification: 'deferred-until-postflight',
    nativeUiExecuted: false, appSharingFlagsChanged: false };
  return { stagingEvidence: writeReceipt(output, receipt), staging: receipt };
}

const DEFAULT_LIMITS = { files: 4096, entries: 8192, depth: 16, fileBytes: 8388608, totalBytes: 67108864 };
export function snapshotIosFilesPrivacy({ containers, stagingEvidence, output, knownSources = [], limits = {}, verifyProviderBytes = false }) {
  assert.equal(typeof verifyProviderBytes, 'boolean', 'EXPLICIT_PROVIDER_VERIFICATION_REQUIRED');
  validateContainers(containers); outputPath(output, containers);
  const bounds = { ...DEFAULT_LIMITS, ...limits };
  for (const [key, value] of Object.entries(bounds)) assert.ok(Object.hasOwn(DEFAULT_LIMITS, key) && Number.isSafeInteger(value)
    && value > 0 && value <= DEFAULT_LIMITS[key], 'PRIVACY_SCAN_BOUND_CANNOT_BE_RAISED');
  const byteBudget = { bytes: 0, limit: bounds.totalBytes };
  const staging = jsonRef(stagingEvidence);
  assert.equal(staging.schemaVersion, 2, 'COLD_PROVIDER_STAGING_PROVENANCE_REQUIRED');
  assert.equal(staging.providerOriginalsRead, false, 'COLD_PROVIDER_STAGING_PROVENANCE_REQUIRED');
  assert.equal(staging.kind, 'ios-files-provider-assets', 'STAGED_FILES_RECEIPT_REQUIRED');
  assert.equal(staging.udid, containers.udid, 'FILES_DEVICE_MISMATCH'); assert.equal(staging.appId, containers.appId, 'FILES_APP_MISMATCH');
  assert.equal(staging.containers.provider.groupPath, containers.provider.groupPath, 'FILES_PROVIDER_CONTAINER_CHANGED');
  assert.equal(staging.folderPath, path.join(containers.provider.storagePath, staging.folderName), 'STAGED_PROVIDER_FOLDER_SCOPE_MISMATCH');
  directory(staging.folderPath);
  const assets = manifestAssets(staging.manifestEvidence);
  assert.ok(Array.isArray(knownSources) && knownSources.length + assets.length <= 60, 'BOUNDED_KNOWN_SOURCE_INVENTORY_REQUIRED');
  const scannedSources = [...assets, ...knownSources.map(knownSource)];
  assert.equal(new Set(scannedSources.map(({ id }) => id)).size, scannedSources.length, 'DUPLICATE_KNOWN_SOURCE_ID');
  assert.deepEqual(staging.assets.map(({ id, filename, sha256, sizeBytes }) => ({ id, filename, sha256, sizeBytes })),
    assets.map(({ id, filename, sha256, sizeBytes }) => ({ id, filename, sha256, sizeBytes })), 'STAGED_ASSET_MANIFEST_MISMATCH');
  let providerBytesRead = 0;
  const providerOriginals = staging.assets.map((asset) => {
    assert.equal(asset.path, path.join(staging.folderPath, asset.filename), 'PROVIDER_ORIGINAL_SCOPE_MISMATCH');
    assert.equal(asset.transferSha256, asset.sha256, 'VERIFIED_PROVIDER_TRANSFER_REQUIRED');
    assert.equal(asset.transferMethod, 'verified-buffer-exclusive-descriptor-write', 'VERIFIED_PROVIDER_TRANSFER_REQUIRED');
    assert.deepEqual(Object.keys(asset.providerMetadata || {}).sort(), [...PROVIDER_FIELDS].sort(), 'PROVIDER_STAGING_METADATA_REQUIRED');
    try {
      const current = providerMetadata(asset.path); assert.deepEqual(current, asset.providerMetadata, 'PROVIDER_ORIGINAL_METADATA_CHANGED');
      if (!verifyProviderBytes) return { id: asset.id, metadataPreserved: true, preserved: null, byteVerification: 'deferred-until-postflight' };
      assert.ok(providerBytesRead + asset.sizeBytes <= bounds.totalBytes, 'PROVIDER_FINAL_BYTE_BOUND');
      const beforeRead = byteBudget.bytes; let data;
      try { data = bytes(asset.path, asset.sizeBytes, asset.sha256, byteBudget); }
      finally { providerBytesRead += byteBudget.bytes - beforeRead; }
      assert.deepEqual(providerMetadata(asset.path), asset.providerMetadata, 'PROVIDER_ORIGINAL_METADATA_CHANGED');
      return { id: asset.id, metadataPreserved: true, preserved: data.length === asset.sizeBytes, sha256: sha(data), sizeBytes: data.length };
    } catch { return { id: asset.id, metadataPreserved: false, preserved: verifyProviderBytes ? false : null }; }
  });
  const findings = [], issues = providerOriginals.filter(row => !row.metadataPreserved || verifyProviderBytes && !row.preserved)
    .map(row => ({ reason: 'provider-original-changed', relativePath: row.id }));
  let files = 0, entries = 0, ownedStagingFiles = 0;
  const scanDeadline = Date.now() + 30000;
  const frame = value => PROVIDER_FIELDS.map(key => String(value[key]));
  let inventoryAttempts = 0;
  const inventory = () => {
    inventoryAttempts++;
    const rows = new Map(), todo = [{ file: containers.appData.path, depth: 0 }], scheduled = new Set([containers.appData.path]);
    assert.ok(++entries <= bounds.entries, 'FILES_PRIVATE_ENTRY_BOUND');
    while (todo.length) {
      assert.ok(Date.now() < scanDeadline, 'FILES_PRIVATE_SCAN_DEADLINE');
      const { file, depth } = todo.pop(); assert.ok(depth <= bounds.depth, 'FILES_PRIVATE_DEPTH_BOUND');
      const stat = lstatSync(file, { bigint: true });
      if (!stat.isSymbolicLink()) assert.equal(realpathSync(file), file, 'FILES_PRIVATE_NAMESPACE_CHANGED');
      const row = { metadata: frame(stat), kind: stat.isDirectory() ? 'directory' : stat.isFile() ? 'file' : 'other' }; rows.set(file, row);
      if (stat.isDirectory()) {
        const names = new Set(); const directory = opendirSync(file, { bufferSize: 1 });
        try {
          for (;;) {
            assert.ok(Date.now() < scanDeadline, 'FILES_PRIVATE_SCAN_DEADLINE');
            const entry = directory.readSync(); if (!entry) break;
            assert.ok(++entries <= bounds.entries, 'FILES_PRIVATE_ENTRY_BOUND');
            assert.ok(entry.name !== '.' && entry.name !== '..' && !names.has(entry.name), 'FILES_PRIVATE_DUPLICATE_ENTRY'); names.add(entry.name);
            const child = path.join(file, entry.name); assert.ok(!scheduled.has(child), 'FILES_PRIVATE_DUPLICATE_ENTRY');
            scheduled.add(child); todo.push({ file: child, depth: depth + 1 });
          }
        } finally { directory.closeSync(); }
        assert.deepEqual(frame(lstatSync(file, { bigint: true })), row.metadata, 'FILES_PRIVATE_DIRECTORY_CHANGED');
      }
    }
    assert.ok(rows.has(containers.appData.path), 'FILES_PRIVATE_ROOT_REQUIRED'); return rows;
  };
  let initialInventory, finalInventory;
  try { initialInventory = inventory(); }
  catch { issues.push({ reason: 'incomplete-initial-directory-inventory', relativePath: '.' }); }
  const originalAppData = staging.containers.appData.path;
  const priorAppData = { path: originalAppData, status: originalAppData === containers.appData.path ? 'same-container'
    : existsSync(originalAppData) ? 'retained-after-container-change' : 'absent-after-container-change' };
  if (priorAppData.status === 'retained-after-container-change') issues.push({ reason: 'prior-app-data-container-remains', relativePath: '[prior-container]' });
  for (const [file, expected] of initialInventory ?? []) {
      if (file === containers.appData.path) continue;
      const name = path.basename(file), relativePath = path.relative(containers.appData.path, file);
      if (Date.now() >= scanDeadline) { issues.push({ reason: 'time-bound', relativePath }); break; }
      let stat;
      try { assert.deepEqual(frame(lstatSync(file, { bigint: true })), expected.metadata, 'FILES_PRIVATE_DISCOVERY_TO_READ_CHANGED'); stat = lstatSync(file); }
      catch { issues.push({ reason: 'entry-changed-or-unreadable', relativePath }); continue; }
      if (stat.isSymbolicLink()) { issues.push({ reason: 'unfollowed-symlink', relativePath }); continue; }
      if (stat.isDirectory()) continue;
      if (!stat.isFile()) { issues.push({ reason: 'non-regular-file', relativePath }); continue; }
      const owned = relativePath.split(path.sep).slice(0, 3).join('/') === 'Library/Caches/caseops-matter-files-v1';
      if (owned) ownedStagingFiles++;
      if (++files > bounds.files || stat.size > bounds.fileBytes || byteBudget.bytes + stat.size > bounds.totalBytes) { issues.push({ reason: 'byte-or-file-bound', relativePath }); continue; }
      let data;
      try { data = bytes(file, bounds.fileBytes, undefined, byteBudget); } catch { issues.push({ reason: 'file-changed-or-unreadable', relativePath }); continue; }
      const digest = sha(data);
      const matches = scannedSources.flatMap((asset) => {
        const reasons = [];
        if (digest === asset.sha256) reasons.push('exact-asset-hash');
        if (name.includes(asset.filename)) reasons.push('known-asset-name');
        if (data.includes(Buffer.from(asset.filename))) reasons.push('known-asset-filename-metadata');
        if (data.includes(Buffer.from(asset.sha256, 'ascii'))) reasons.push('known-asset-sha256-metadata');
        if (markers(asset).some((marker) => data.includes(Buffer.from(marker)))) reasons.push('known-synthetic-marker');
        return reasons.length ? [{ id: asset.id, reasons }] : [];
      });
      if (owned || matches.length) {
        const normalized = relativePath.split(path.sep).join('/');
        const classification = owned ? 'owned-upload-staging' : /^(tmp\/|Documents\/Inbox\/|Library\/Caches\/DocumentPicker\/)/.test(normalized)
          ? 'os-private-import-copy' : 'other-private-asset-copy';
        findings.push({ relativePath: normalized, sha256: digest, sizeBytes: data.length, classification, matches });
      }
  }
  try {
    assert.ok(initialInventory, 'FILES_PRIVATE_INITIAL_INVENTORY_REQUIRED');
    finalInventory = inventory();
    const serialize = rows => [...rows].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
    assert.deepEqual(serialize(finalInventory), serialize(initialInventory), 'FILES_PRIVATE_COMPLETE_INVENTORY_CHANGED');
    for (const [file, row] of finalInventory) {
      assert.ok(Date.now() < scanDeadline, 'FILES_PRIVATE_SCAN_DEADLINE');
      assert.deepEqual(frame(lstatSync(file, { bigint: true })), row.metadata, 'FILES_PRIVATE_FINAL_PATH_CHANGED');
      if (row.kind !== 'other') assert.equal(realpathSync(file), file, 'FILES_PRIVATE_NAMESPACE_CHANGED');
    }
  } catch { issues.push({ reason: 'incomplete-or-changed-final-directory-inventory', relativePath: '.' }); }
  // Do not accept an original changed while the private-container scan ran.
  // This final fence consumes metadata only, including for a cold checkpoint.
  for (const [index, asset] of staging.assets.entries()) {
    try { assert.deepEqual(providerMetadata(asset.path), asset.providerMetadata, 'PROVIDER_ORIGINAL_METADATA_CHANGED'); }
    catch {
      providerOriginals[index].metadataPreserved = false;
      if (verifyProviderBytes) providerOriginals[index].preserved = false;
      issues.push({ reason: 'provider-original-final-metadata-changed', relativePath: asset.id });
    }
  }
  // Leaf and provider reconciliation can run after a directory's first final
  // check. Recheck every unique directory, children first and root last, so a
  // late private copy cannot leave an apparently complete empty finding set.
  if (finalInventory) try {
    for (const [file, row] of [...finalInventory].reverse()) if (row.kind === 'directory') {
      assert.ok(Date.now() < scanDeadline, 'FILES_PRIVATE_SCAN_DEADLINE');
      assert.deepEqual(frame(lstatSync(file, { bigint: true })), row.metadata, 'FILES_PRIVATE_FINAL_DIRECTORY_CHANGED');
      assert.equal(realpathSync(file), file, 'FILES_PRIVATE_NAMESPACE_CHANGED');
    }
    assert.ok(Date.now() < scanDeadline, 'FILES_PRIVATE_SCAN_DEADLINE');
  } catch { issues.push({ reason: 'incomplete-or-changed-final-directory-inventory', relativePath: '.' }); }
  findings.sort((a, b) => a.relativePath.localeCompare(b.relativePath)); issues.sort((a, b) => a.relativePath.localeCompare(b.relativePath));
  const snapshot = { schemaVersion: 2, kind: 'ios-files-privacy-snapshot', observed: true, platform: 'ios',
    udid: containers.udid, appId: containers.appId, bundleId: containers.appId, ownedAppScopeOnly: true,
    appDataPath: containers.appData.path, priorAppData, containers, stagingEvidence, complete: issues.length === 0,
    counts: { files, entries, bytesRead: byteBudget.bytes, ownedStagingFiles,
      privateAssetMatchCount: findings.filter(({ matches }) => matches.length > 0).length,
      osPrivateImportCopies: findings.filter(({ classification }) => classification === 'os-private-import-copy').length }, limits: bounds,
    privateInventory: { rootPresent: Boolean(initialInventory?.has(containers.appData.path) && finalInventory?.has(containers.appData.path)),
      intendedObservations: 2, attemptedObservations: inventoryAttempts, observations: Number(Boolean(initialInventory)) + Number(Boolean(finalInventory)),
      initialCount: initialInventory?.size ?? null, finalCount: finalInventory?.size ?? null },
    searchMethods: ['exact-file-sha256', 'known-basename', 'literal-public-filename', 'literal-public-sha256', 'literal-public-marker'],
    knownSources: knownSources.map(({ id, filename, sha256, sizeBytes, ...asset }) => ({ id, filename, sha256, sizeBytes,
      markerSha256: markers(asset).map((marker) => sha(Buffer.from(marker))) })),
    findings, issues, providerOriginals, providerMetadataPreserved: providerOriginals.every(row => row.metadataPreserved),
    providerOriginalsRead: providerBytesRead > 0, providerBytesRead,
    providerByteVerification: verifyProviderBytes ? 'postflight' : 'deferred-until-postflight',
    providerOriginalsPreserved: verifyProviderBytes ? providerOriginals.every(({ preserved }) => preserved) : null,
    fileContentsRecorded: false, credentialValuesRecorded: false, nativeUiExecuted: false };
  return { snapshotEvidence: writeReceipt(output, snapshot), snapshot };
}

export function assertIosFilesPrivacy(snapshot, { boundary } = {}) {
  if (snapshot?.path) snapshot = jsonRef(snapshot);
  assert.match(boundary || '', /^(clear|upload|background|logout|restart|reinstall)$/);
  assert.equal(snapshot.kind, 'ios-files-privacy-snapshot', 'FILES_PRIVACY_SNAPSHOT_REQUIRED');
  assert.equal(snapshot.providerMetadataPreserved, true, 'PROVIDER_ORIGINALS_MUST_BE_PRESERVED');
  assert.equal(snapshot.providerOriginalsPreserved, snapshot.providerByteVerification === 'postflight' ? true : null, 'PROVIDER_ORIGINALS_MUST_BE_PRESERVED');
  assert.equal(snapshot.complete, true, 'COMPLETE_FILES_PRIVACY_SCAN_REQUIRED');
  assert.equal(snapshot.counts.ownedStagingFiles, 0, 'OWNED_UPLOAD_STAGING_REMAINS');
  assert.equal(snapshot.findings.filter(({ classification }) => classification !== 'owned-upload-staging').length, 0, 'PRIVATE_PICKED_ASSET_COPY_REMAINS');
  return { boundary, status: 'passed', providerOriginalsPreserved: snapshot.providerOriginalsPreserved,
    providerOriginalsRead: snapshot.providerOriginalsRead, providerByteVerification: snapshot.providerByteVerification, nativeUiExecuted: false };
}

// Separate scope: old Files snapshots/findings do not establish that arbitrary
// UUID-named camera images are gone. No provider asset is opened by this scan.
export function snapshotIosCameraPrivacy({ containers, output }, dependencies) {
  validateContainers(containers); outputPath(output, containers);
  const observation = { ...observeIosCameraDirectory(containers.appData.path, dependencies),
    udid: containers.udid, appId: containers.appId, appMetadataEvidence: containers.appData.metadataEvidence };
  return { observation, evidence: writeReceipt(output, observation) };
}
