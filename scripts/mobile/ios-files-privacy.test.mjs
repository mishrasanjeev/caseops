import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import fs from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import { assertProviderPreserved, attestIosFilesContainers, stageIosFilesAssets, snapshotIosFilesPrivacy, assertIosFilesPrivacy, snapshotIosCameraPrivacy } from './ios-files-privacy.mjs';
const require = createRequire(new URL('../../apps/mobile/package.json', import.meta.url));
const plist = require('@expo/plist').default;
const sha = (data) => createHash('sha256').update(data).digest('hex');
const ref = (file) => ({ path: file, sha256: sha(readFileSync(file)) });
const APP = 'ai.caseops.mobile.dev.simulatoracceptance';
const UDID = '27246D16-6C92-4FE1-9178-B89416E2A3E1';
const GROUP = 'group.com.apple.FileProvider.LocalStorage';
const META = '.com.apple.mobile_container_manager.metadata.plist';

function fixture(t) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-files-privacy-')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const devicesRoot = path.join(root, 'Devices'), data = path.join(devicesRoot, UDID, 'data');
  const app = path.join(data, 'Containers/Data/Application/11111111-1111-1111-1111-111111111111');
  const group = path.join(data, 'Containers/Shared/AppGroup/22222222-2222-2222-2222-222222222222');
  for (const folder of [app, path.join(group, 'File Provider Storage'), path.join(app, 'Documents/Inbox'), path.join(app, 'tmp')]) mkdirSync(folder, { recursive: true });
  writeFileSync(path.join(app, META), plist.build({ MCMMetadataIdentifier: APP }));
  writeFileSync(path.join(group, META), plist.build({ MCMMetadataIdentifier: GROUP }));
  const commands = [], run = (binary, args) => {
    commands.push({ binary, args });
    if (args[1] === 'list') return JSON.stringify({ devices: { 'com.apple.CoreSimulator.SimRuntime.iOS-26-5': [{ udid: UDID, state: 'Booted', name: 'Dedicated unit simulator', isAvailable: true }] } });
    if (args.at(-1) === 'data') return app;
    if (args.at(-1) === 'groups') return `${GROUP}\t${group}`;
    throw new Error('Unexpected command');
  };
  const containers = attestIosFilesContainers({ udid: UDID, devicesRoot, run });
  const source = path.join(root, 'public-assets'); mkdirSync(source);
  const assets = ['txt-one', 'txt-two'].map((id) => {
    const marker = `CaseOpsPublicSyntheticMarker-${id}-1234567890`, filename = `${id}.txt`, file = path.join(source, filename);
    const bytes = Buffer.from(`Public synthetic fixture ${marker}\n`); writeFileSync(file, bytes);
    return { id, filename, path: file, sha256: sha(bytes), sizeBytes: bytes.length, marker };
  });
  const manifest = path.join(root, 'manifest.json');
  writeFileSync(manifest, JSON.stringify({ schemaVersion: 1, kind: 'ios-files-synthetic-fixtures', platform: 'ios', syntheticDataOnly: true, assets }));
  const options = { containers, manifestEvidence: ref(manifest), runId: 'unit-run-1234', output: path.join(root, 'staging-receipt.json'), settleMs: 0 };
  const snapshot = (stagingEvidence, name, extra = {}) => snapshotIosFilesPrivacy({ containers, stagingEvidence, verifyProviderBytes: true, output: path.join(root, name), ...extra });
  return { root, app, group, commands, run, devicesRoot, containers, assets, manifest, options, snapshot };
}

test('attestation binds exact read-only simctl mapping to actual app/provider metadata and rejects an unrelated group', (t) => {
  const f = fixture(t);
  assert.equal(f.containers.provider.storagePath, path.join(f.group, 'File Provider Storage'));
  assert.equal(f.commands.length, 3);
  assert.ok(f.commands.every(({ args }) => args[0] === 'simctl' && ['list', 'get_app_container'].includes(args[1])));
  writeFileSync(path.join(f.group, META), plist.build({ MCMMetadataIdentifier: 'foreign.group' }));
  assert.throws(() => attestIosFilesContainers({ udid: UDID, devicesRoot: f.devicesRoot, run: f.run }), /CONTAINER_METADATA_IDENTITY_MISMATCH/);
});

test('staging records provider metadata only after a settle window and allows only ctime to move meanwhile', async (t) => {
  const f = fixture(t);
  // Simulate the provider daemon's post-write ingestion: an attribute write
  // moves only ctime shortly after the file appears.
  const { spawn } = await import('node:child_process');
  const touch = spawn(process.execPath, ['-e', `setTimeout(() => { const fs = require('fs'); for (const name of fs.readdirSync(process.argv[1])) for (const dir of [require('path').join(process.argv[1], name)]) if (fs.statSync(dir).isDirectory()) for (const file of fs.readdirSync(dir)) fs.chmodSync(require('path').join(dir, file), 0o600); }, 300);`, f.containers.provider.storagePath]);
  const result = stageIosFilesAssets({ ...f.options, settleMs: 1200 });
  await new Promise((resolve) => touch.on('exit', resolve));
  assert.equal(result.staging.providerSettleMs, 1200);
  for (const asset of result.staging.assets) {
    const now = fs.statSync(asset.path, { bigint: true });
    assert.equal(asset.providerMetadata.ctimeNs, String(now.ctimeNs), 'SETTLED_CTIME_RECORDED');
    assert.ok(BigInt(asset.providerMetadata.ctimeNs) > BigInt(asset.writeCtimeNs), 'INGESTION_CTIME_MOVE_OBSERVED');
  }
});

test('a provider original may gain only the OS last-used attribute, which moves ctime alone', async (t) => {
  const f = fixture(t), staged = stageIosFilesAssets(f.options).staging.assets[0];
  await new Promise((resolve) => setTimeout(resolve, 20));
  // Mutate through one descriptor so the test's own checks cannot race the path.
  const fd = fs.openSync(staged.path, 'r+');
  try {
    fs.fchmodSync(fd, 0o600); // an attribute-only change: ctime moves, nothing else
    assert.notEqual(String(fs.fstatSync(fd, { bigint: true }).ctimeNs), staged.providerMetadata.ctimeNs);
    assertProviderPreserved(staged, () => ['com.apple.provenance', 'com.apple.lastuseddate#PS']);
    assert.throws(() => assertProviderPreserved(staged, () => ['com.apple.lastuseddate#PS', 'com.example.app-wrote-this']), /PROVIDER_ORIGINAL_METADATA_CHANGED/);
    assert.throws(() => assertProviderPreserved(staged, () => { throw new Error('xattr unavailable'); }), /xattr unavailable/);
    fs.writeSync(fd, 'x', Number(fs.fstatSync(fd).size));
  } finally { fs.closeSync(fd); }
  assert.throws(() => assertProviderPreserved(staged, () => []), /PROVIDER_ORIGINAL_METADATA_CHANGED/);
});

test('staging refuses a provider original whose size changes while settling', async (t) => {
  const f = fixture(t);
  const { spawn } = await import('node:child_process');
  const grow = spawn(process.execPath, ['-e', `setTimeout(() => { const fs = require('fs'), path = require('path'); for (const name of fs.readdirSync(process.argv[1])) { const dir = path.join(process.argv[1], name); if (fs.statSync(dir).isDirectory()) { const file = fs.readdirSync(dir)[0]; fs.appendFileSync(path.join(dir, file), 'x'); } } }, 300);`, f.containers.provider.storagePath]);
  assert.throws(() => stageIosFilesAssets({ ...f.options, settleMs: 1200 }), /PROVIDER_ORIGINAL_CHANGED_WHILE_SETTLING/);
  await new Promise((resolve) => grow.on('exit', resolve));
  assert.throws(() => stageIosFilesAssets({ ...f.options, output: path.join(f.root, 'unbounded.json'), runId: 'unit-run-5678', settleMs: 60000 }), /BOUNDED_PROVIDER_SETTLE_REQUIRED/);
});

test('staging creates one exclusive provider folder with exact assets and immutable receipt, without app sharing changes', (t) => {
  const f = fixture(t), result = stageIosFilesAssets(f.options);
  assert.equal(result.staging.folderName, 'CaseOpsFiles-unit-run-1234');
  assert.equal(result.staging.appSharingFlagsChanged, false); assert.equal(result.staging.nativeUiExecuted, false);
  for (const asset of result.staging.assets) assert.equal(sha(readFileSync(asset.path)), asset.sha256);
  assert.equal(result.staging.appPrivateImportRoots[0].path, path.join(f.app, 'Documents/Inbox'));
  const before = readFileSync(result.stagingEvidence.path);
  assert.throws(() => stageIosFilesAssets(f.options), /FILES_RECEIPT_ALREADY_EXISTS/);
  assert.deepEqual(readFileSync(result.stagingEvidence.path), before);
  assert.throws(() => stageIosFilesAssets({ ...f.options, output: path.join(f.root, 'second.json') }), /EEXIST/);
});

test('staging and deferred private cleanup never consume provider bytes before picker journeys', t => {
  const f = fixture(t), open = fs.openSync, read = fs.readSync, close = fs.closeSync, descriptors = new Set(); let providerBytes = 0;
  fs.openSync = (file, ...args) => { const fd = open(file, ...args); if (String(file).startsWith(f.containers.provider.storagePath + path.sep)) descriptors.add(fd); return fd; };
  fs.readSync = (fd, ...args) => { const count = read(fd, ...args); if (descriptors.has(fd)) providerBytes += count; return count; };
  fs.closeSync = fd => { descriptors.delete(fd); return close(fd); }; syncBuiltinESMExports();
  let stage, snapshot;
  try { stage = stageIosFilesAssets(f.options); snapshot = f.snapshot(stage.stagingEvidence, 'deferred-cold.json', { verifyProviderBytes: false }).snapshot; }
  finally { fs.openSync = open; fs.readSync = read; fs.closeSync = close; syncBuiltinESMExports(); }
  assert.equal(providerBytes, 0); assert.equal(descriptors.size, 0);
  assert.equal(stage.staging.providerOriginalsRead, false); assert.equal(snapshot.providerOriginalsRead, false);
  assert.equal(snapshot.providerOriginalsPreserved, null); assert.equal(snapshot.providerMetadataPreserved, true);
});
test('explicit final verification proves original bytes and refuses metadata replacement or provider aliases before staging', t => {
  const f = fixture(t), staged = stageIosFilesAssets(f.options), cold = f.snapshot(staged.stagingEvidence, 'cold-before-final.json', { verifyProviderBytes: false }).snapshot;
  assert.equal(cold.providerOriginalsPreserved, null); assert.equal(cold.providerOriginalsRead, false);
  const final = f.snapshot(staged.stagingEvidence, 'final-originals.json').snapshot;
  assert.equal(final.complete, true); assert.equal(final.providerOriginalsRead, true); assert.equal(final.providerOriginalsPreserved, true);
  assert.equal(final.providerBytesRead, f.assets.reduce((sum, row) => sum + row.sizeBytes, 0));
  const file = staged.staging.assets[0].path, retained = file + '.retained'; fs.renameSync(file, retained); fs.copyFileSync(retained, file); fs.chmodSync(file, 0o600);
  const replaced = f.snapshot(staged.stagingEvidence, 'replaced-original.json').snapshot;
  assert.equal(replaced.complete, false); assert.equal(replaced.providerMetadataPreserved, false); assert.equal(replaced.providerOriginalsPreserved, false);
  const manifest = JSON.parse(readFileSync(f.manifest)); manifest.assets[0].path = staged.staging.assets[1].path;
  writeFileSync(f.manifest, JSON.stringify(manifest));
  assert.throws(() => stageIosFilesAssets({ ...f.options, manifestEvidence: ref(f.manifest), runId: 'alias-run-1234', output: path.join(f.root, 'alias-stage.json') }), /HOST_FIXTURE_MUST_NOT_READ_DEVICE_PROVIDER/);
});
test('final metadata fence catches a provider change during the private scan without reading a provider hardlink', t => {
  const f = fixture(t), staged = stageIosFilesAssets(f.options), original = staged.staging.assets[0].path;
  const read = fs.readSync, open = fs.openSync, descriptors = new Map(); let changed = false;
  fs.openSync = (file, ...args) => { const fd = open(file, ...args); descriptors.set(fd, String(file)); return fd; };
  fs.readSync = (fd, ...args) => { const count = read(fd, ...args); if (!changed && descriptors.get(fd) === path.join(f.app, META)) { changed = true; fs.appendFileSync(original, 'late'); } return count; }; syncBuiltinESMExports();
  let result; try { result = f.snapshot(staged.stagingEvidence, 'late-final-provider.json').snapshot; }
  finally { fs.openSync = open; fs.readSync = read; syncBuiltinESMExports(); }
  assert.equal(changed, true); assert.equal(result.complete, false); assert.equal(result.providerOriginalsPreserved, false);
  assert.ok(result.issues.some(row => row.reason === 'provider-original-final-metadata-changed'));
  fs.linkSync(staged.staging.assets[1].path, path.join(f.app, 'tmp/provider-hardlink'));
  const cold = f.snapshot(staged.stagingEvidence, 'hardlink-cold.json', { verifyProviderBytes: false }).snapshot;
  assert.equal(cold.complete, false); assert.equal(cold.providerOriginalsRead, false); assert.equal(cold.providerBytesRead, 0);
});
test('private scan binds two complete root-present inventories and catches insertion after either directory traversal', t => {
  for (const traversal of [1, 2]) {
    const f = fixture(t), staged = stageIosFilesAssets(f.options), open = fs.opendirSync, named = fs.lstatSync;
    let closed = 0, lastClosed, inserted = false;
    fs.opendirSync = (file, ...args) => { const dir = open(file, ...args), close = dir.closeSync.bind(dir);
      dir.closeSync = () => { close(); closed++; lastClosed = String(file); }; return dir; };
    fs.lstatSync = (file, ...args) => { const result = named(file, ...args);
      if (!inserted && closed === traversal * 4 && String(file) === lastClosed) {
        inserted = true; writeFileSync(path.join(lastClosed, 'late-private-copy'), f.assets[0].marker);
      } return result;
    }; syncBuiltinESMExports();
    let snapshot; try { snapshot = f.snapshot(staged.stagingEvidence, `late-private-${traversal}.json`, { verifyProviderBytes: false }).snapshot; }
    finally { fs.opendirSync = open; fs.lstatSync = named; syncBuiltinESMExports(); }
    assert.equal(inserted, true); assert.equal(snapshot.complete, false); assert.equal(snapshot.providerOriginalsRead, false);
    assert.ok(snapshot.issues.some(row => /inventory/.test(row.reason)));
  }
});
test('private directory discovery charges before retention, closes at the unchanged cap and never reads a rejected payload', t => {
  const f = fixture(t), staged = stageIosFilesAssets(f.options);
  for (let i = 0; i < 40; i++) writeFileSync(path.join(f.app, 'tmp', `wide-${i}`), 'unrelated');
  const open = fs.opendirSync, read = fs.readSync; let yielded = 0, closed = 0, privateReads = 0;
  fs.opendirSync = (...args) => { const dir = open(...args), next = dir.readSync.bind(dir), close = dir.closeSync.bind(dir);
    dir.readSync = () => { const item = next(); if (item) yielded++; return item; }; dir.closeSync = () => { closed++; return close(); }; return dir; };
  fs.readSync = (...args) => { privateReads++; return read(...args); }; syncBuiltinESMExports();
  let snapshot; try { snapshot = f.snapshot(staged.stagingEvidence, 'bounded-private.json', { verifyProviderBytes: false, limits: { entries: 8 } }).snapshot; }
  finally { fs.opendirSync = open; fs.readSync = read; syncBuiltinESMExports(); }
  assert.equal(snapshot.complete, false); assert.ok(yielded <= 8); assert.ok(closed > 0);
  assert.equal(snapshot.privateInventory.initialCount, null); assert.equal(snapshot.privateInventory.observations, 0);
  // Metadata/receipt readers may run; no body scanning occurs after discovery refusal.
  assert.equal(snapshot.counts.files, 0); assert.equal(snapshot.counts.bytesRead, 0); assert.ok(privateReads > 0);
});

test('a copy inserted during final leaf reconciliation cannot pass a complete zero-copy privacy scan', t => {
  const f = fixture(t), staged = stageIosFilesAssets(f.options);
  const open = fs.opendirSync, named = fs.lstatSync, canonical = fs.realpathSync;
  let rootCloses = 0, rootFinalStats = 0, rootReconciled = false, inserted = false;
  const late = path.join(f.app, 'late-private-copy'), leaf = path.join(f.app, META);
  fs.opendirSync = (file, ...args) => {
    const directory = open(file, ...args), close = directory.closeSync.bind(directory);
    directory.closeSync = () => { const result = close(); if (String(file) === f.app) rootCloses++; return result; };
    return directory;
  };
  fs.lstatSync = (file, ...args) => {
    const result = named(file, ...args);
    if (String(file) === f.app && rootCloses === 2 && ++rootFinalStats === 2) rootReconciled = true;
    return result;
  };
  fs.realpathSync = (file, ...args) => {
    const result = canonical(file, ...args);
    if (!inserted && rootReconciled && String(file) === leaf) {
      writeFileSync(late, f.assets[0].marker); inserted = true;
    }
    return result;
  };
  syncBuiltinESMExports();
  let snapshot;
  try { snapshot = f.snapshot(staged.stagingEvidence, 'late-final-leaf.json', { verifyProviderBytes: false }).snapshot; }
  finally { fs.opendirSync = open; fs.lstatSync = named; fs.realpathSync = canonical; syncBuiltinESMExports(); }
  assert.equal(inserted, true); assert.equal(rootCloses, 2);
  assert.equal(snapshot.counts.privateAssetMatchCount, 0);
  assert.equal(snapshot.providerOriginalsRead, false);
  assert.equal(snapshot.complete, false);
  assert.ok(snapshot.issues.some(row => row.reason === 'incomplete-or-changed-final-directory-inventory'));
  assert.throws(() => assertIosFilesPrivacy(snapshot, { boundary: 'clear' }), /COMPLETE_FILES_PRIVACY_SCAN_REQUIRED/);
});
test('exclusive retained-buffer provider write closes after zero progress and cannot replay its partial folder', t => {
  const f = fixture(t), open = fs.openSync, write = fs.writeSync, close = fs.closeSync, fds = new Set(); let providerFd;
  fs.openSync = (file, ...args) => { const fd = open(file, ...args); if (String(file).startsWith(f.containers.provider.storagePath + path.sep)) { fds.add(fd); providerFd = fd; } return fd; };
  fs.writeSync = (fd, ...args) => fds.has(fd) ? 0 : write(fd, ...args);
  fs.closeSync = fd => { fds.delete(fd); return close(fd); }; syncBuiltinESMExports();
  try { assert.throws(() => stageIosFilesAssets(f.options), /PROVIDER_WRITE_NO_PROGRESS/); }
  finally { fs.openSync = open; fs.writeSync = write; fs.closeSync = close; syncBuiltinESMExports(); }
  assert.equal(fds.size, 0); assert.throws(() => fs.fstatSync(providerFd), { code: 'EBADF' }); assert.equal(existsSync(f.options.output), false);
  assert.throws(() => stageIosFilesAssets({ ...f.options, output: path.join(f.root, 'no-replay.json') }), /EEXIST/);
});

test('wrong asset hashes, duplicate names, private manifests and symlink assets are refused before provider staging', (t) => {
  for (const alteration of ['hash', 'duplicate', 'private', 'symlink']) {
    const f = fixture(t), manifest = JSON.parse(readFileSync(f.manifest));
    if (alteration === 'hash') manifest.assets[0].sha256 = '0'.repeat(64);
    if (alteration === 'duplicate') manifest.assets[1].filename = manifest.assets[0].filename;
    if (alteration === 'private') manifest.syntheticDataOnly = false;
    if (alteration === 'symlink') { const link = path.join(f.root, 'linked.txt'); symlinkSync(manifest.assets[0].path, link); manifest.assets[0].path = link; }
    writeFileSync(f.manifest, JSON.stringify(manifest));
    assert.throws(() => stageIosFilesAssets({ ...f.options, manifestEvidence: ref(f.manifest) }));
    assert.equal(existsSync(path.join(f.containers.provider.storagePath, 'CaseOpsFiles-unit-run-1234')), false);
  }
});

test('container metadata changed after attestation cannot authorize a write or receipt inside the device', (t) => {
  const f = fixture(t);
  assert.throws(() => stageIosFilesAssets({ ...f.options, output: path.join(f.app, 'receipt.json') }), /FILES_RECEIPT_MUST_STAY_OUTSIDE_REPOSITORY_AND_DEVICE/);
  writeFileSync(path.join(f.app, META), plist.build({ MCMMetadataIdentifier: 'other.app' }));
  assert.throws(() => stageIosFilesAssets(f.options), /FILES_ASSET_HASH_MISMATCH/);
});

test('clean app-data scan proves scoped absence while provider originals remain unchanged', (t) => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options);
  const result = f.snapshot(stagingEvidence, 'clean.json');
  assert.equal(result.snapshot.complete, true); assert.equal(result.snapshot.counts.ownedStagingFiles, 0);
  assert.equal(result.snapshot.counts.privateAssetMatchCount, 0); assert.equal(result.snapshot.providerOriginalsPreserved, true);
  assert.equal(assertIosFilesPrivacy(result.snapshotEvidence, { boundary: 'upload' }).status, 'passed');
  const raw = readFileSync(result.snapshotEvidence.path, 'utf8');
  assert.ok(!raw.includes(f.assets[0].marker)); assert.ok(!raw.includes('Public synthetic fixture'));
});

test('camera SDK copies have separate attested-container evidence from legacy Files fixture counts', t => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options);
  const sdk = path.join(f.app, 'Library/Caches/ImagePicker'); mkdirSync(sdk, { recursive: true });
  const body = 'CAMERA_BYTES_UNKNOWN_TO_SYNTHETIC_FILES';
  writeFileSync(path.join(sdk, '11111111-2222-4333-8444-555555555555.jpg'), body);
  const legacy = f.snapshot(stagingEvidence, 'legacy-camera.json');
  assert.equal(legacy.snapshot.counts.privateAssetMatchCount, 0);
  const current = snapshotIosCameraPrivacy({ containers: f.containers, output: path.join(f.root, 'camera.json') });
  assert.equal(current.observation.complete, true); assert.equal(current.observation.counts.copies, 1);
  assert.equal(current.observation.udid, UDID); assert.equal(current.observation.appId, APP);
  assert.equal(current.observation.providerOriginalsRead, false);
  assert.equal(readFileSync(current.evidence.path, 'utf8').includes(body), false);
  for (const asset of f.assets) assert.equal(sha(readFileSync(asset.path)), asset.sha256);
});

test('OS Inbox/tmp copies and marker-only renderer cache remnants are detected separately from provider originals', (t) => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options);
  writeFileSync(path.join(f.app, 'Documents/Inbox', f.assets[0].filename), readFileSync(f.assets[0].path));
  writeFileSync(path.join(f.app, 'tmp/import-copy.bin'), readFileSync(f.assets[1].path));
  mkdirSync(path.join(f.app, 'Library/WebKit'), { recursive: true });
  writeFileSync(path.join(f.app, 'Library/WebKit/cache.bin'), `wrapper ${f.assets[0].marker} suffix`);
  const { snapshot } = f.snapshot(stagingEvidence, 'imports.json');
  assert.equal(snapshot.counts.osPrivateImportCopies, 2); assert.equal(snapshot.counts.privateAssetMatchCount, 3);
  assert.equal(snapshot.providerOriginalsPreserved, true);
  assert.throws(() => assertIosFilesPrivacy(snapshot, { boundary: 'logout' }), /PRIVATE_PICKED_ASSET_COPY_REMAINS/);
});

test('cached workspace metadata with only a known full filename or SHA fails privacy without recording cache contents', (t) => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options);
  const cache = path.join(f.app, 'Library/Caches/workspaces'); mkdirSync(cache, { recursive: true });
  const unrelated = 'PRIVATE-CACHE-CONTENT-MUST-NOT-BE-RECORDED';
  writeFileSync(path.join(cache, 'workspace.json'), JSON.stringify({ attachments: [{ original_filename: f.assets[0].filename }], unrelated }));
  writeFileSync(path.join(cache, 'metadata.sqlite'), Buffer.concat([Buffer.from('SQLite format 3\0'), Buffer.from(f.assets[1].sha256), Buffer.from(`\0${unrelated}`)]));
  writeFileSync(path.join(cache, 'unrelated.json'), JSON.stringify({ original_filename: 'other-public.txt', sha256_hex: '0'.repeat(64) }));
  const { snapshot, snapshotEvidence } = f.snapshot(stagingEvidence, 'cached-metadata.json');
  assert.equal(snapshot.complete, true); assert.equal(snapshot.providerOriginalsPreserved, true);
  assert.equal(snapshot.counts.privateAssetMatchCount, 2); assert.equal(snapshot.counts.osPrivateImportCopies, 0);
  assert.deepEqual(snapshot.findings.map(({ relativePath, matches }) => ({ relativePath, matches })), [
    { relativePath: 'Library/Caches/workspaces/metadata.sqlite', matches: [{ id: f.assets[1].id, reasons: ['known-asset-sha256-metadata'] }] },
    { relativePath: 'Library/Caches/workspaces/workspace.json', matches: [{ id: f.assets[0].id, reasons: ['known-asset-filename-metadata'] }] },
  ]);
  assert.throws(() => assertIosFilesPrivacy(snapshot, { boundary: 'logout' }), /PRIVATE_PICKED_ASSET_COPY_REMAINS/);
  const raw = readFileSync(snapshotEvidence.path, 'utf8');
  assert.ok(!raw.includes(unrelated)); assert.ok(!raw.includes('original_filename')); assert.ok(!raw.includes(f.assets[0].marker));
});

test('unknown owned staging files fail cleanup even without an exact known-asset match', (t) => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options), owned = path.join(f.app, 'Library/Caches/caseops-matter-files-v1');
  mkdirSync(owned, { recursive: true }); writeFileSync(path.join(owned, 'unknown.tmp'), 'opaque bytes');
  const { snapshot } = f.snapshot(stagingEvidence, 'owned.json');
  assert.equal(snapshot.counts.ownedStagingFiles, 1); assert.equal(snapshot.counts.privateAssetMatchCount, 0);
  assert.throws(() => assertIosFilesPrivacy(snapshot, { boundary: 'clear' }), /OWNED_UPLOAD_STAGING_REMAINS/);
});

test('additional seeded-reader sources are scanned without joining or changing provider originals', (t) => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options);
  const marker = 'Synthetic seeded source fixture marker. No customer data.', data = Buffer.from(marker);
  writeFileSync(path.join(f.app, 'tmp/seeded-reader-cache'), data);
  const { snapshot } = f.snapshot(stagingEvidence, 'seeded-reader.json', { knownSources: [{ id: 'seeded-txt', filename: 'mobile-source.txt',
    sha256: sha(data), sizeBytes: data.length, marker }] });
  assert.equal(snapshot.providerOriginals.length, 2); assert.equal(snapshot.providerOriginalsPreserved, true);
  assert.equal(snapshot.counts.privateAssetMatchCount, 1); assert.equal(snapshot.findings[0].matches[0].id, 'seeded-txt');
  assert.throws(() => assertIosFilesPrivacy(snapshot, { boundary: 'logout' }), /PRIVATE_PICKED_ASSET_COPY_REMAINS/);
  assert.ok(!JSON.stringify(snapshot).includes(marker));
});

test('privacy independently includes all five prior cohorts and charges current assets at the combined sixty-source bound', (t) => {
  const f = fixture(t), manifest = JSON.parse(readFileSync(f.manifest));
  for (let index = 2; index < 7; index++) {
    const filename = `current-${index}.txt`, file = path.join(f.root, 'public-assets', filename), data = Buffer.from(`Synthetic current asset ${index}.`);
    writeFileSync(file, data);
    manifest.assets.push({ id: `current-${index}`, filename, path: file, sha256: sha(data), sizeBytes: data.length });
  }
  writeFileSync(f.manifest, JSON.stringify(manifest));
  const { stagingEvidence } = stageIosFilesAssets({ ...f.options, manifestEvidence: ref(f.manifest) });
  const source = index => ({ id: `known-${index}`, filename: `known-${index}.txt`, sha256: sha(`Synthetic known asset ${index}.`), sizeBytes: 24 });
  const fiveCohortsAndSeed = Array.from({ length: 36 }, (_, index) => source(index));
  const cohort = f.snapshot(stagingEvidence, 'five-cohorts.json', { knownSources: fiveCohortsAndSeed }).snapshot;
  assert.equal(cohort.knownSources.length, 36); assert.equal(cohort.providerOriginals.length, 7);
  assert.equal(cohort.providerOriginalsPreserved, true); assert.equal(cohort.complete, true);
  const sixty = Array.from({ length: 53 }, (_, index) => source(index));
  const accepted = f.snapshot(stagingEvidence, 'sixty.json', { knownSources: sixty }).snapshot;
  assert.equal(accepted.knownSources.length + accepted.providerOriginals.length, 60);
  assert.deepEqual(accepted.limits, { files: 4096, entries: 8192, depth: 16, fileBytes: 8388608, totalBytes: 67108864 });
  assert.throws(() => f.snapshot(stagingEvidence, 'sixty-one.json', { knownSources: [...sixty, source(53)] }), /BOUNDED_KNOWN_SOURCE_INVENTORY_REQUIRED/);
  assert.equal(existsSync(path.join(f.root, 'sixty-one.json')), false);
});

test('missing or changed provider originals cannot be reported as successful app cleanup', (t) => {
  const f = fixture(t), { stagingEvidence, staging } = stageIosFilesAssets(f.options);
  rmSync(staging.assets[0].path);
  const { snapshot } = f.snapshot(stagingEvidence, 'provider-missing.json');
  assert.equal(snapshot.providerOriginalsPreserved, false);
  assert.throws(() => assertIosFilesPrivacy(snapshot, { boundary: 'background' }), /PROVIDER_ORIGINALS_MUST_BE_PRESERVED/);
});

test('a replacement app-data container cannot hide retained prior-container data from a reinstall claim', (t) => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options);
  const replacement = path.join(path.dirname(f.app), '33333333-3333-3333-3333-333333333333');
  mkdirSync(replacement); writeFileSync(path.join(replacement, META), plist.build({ MCMMetadataIdentifier: APP }));
  const containers = { ...f.containers, appData: { path: replacement, metadataEvidence: ref(path.join(replacement, META)) } };
  const retained = f.snapshot(stagingEvidence, 'old-container-retained.json', { containers });
  assert.equal(retained.snapshot.complete, false);
  assert.throws(() => assertIosFilesPrivacy(retained.snapshot, { boundary: 'reinstall' }), /COMPLETE_FILES_PRIVACY_SCAN_REQUIRED/);
  rmSync(f.app, { recursive: true });
  const removed = f.snapshot(stagingEvidence, 'old-container-removed.json', { containers });
  assert.equal(removed.snapshot.priorAppData.status, 'absent-after-container-change');
  assert.equal(assertIosFilesPrivacy(removed.snapshot, { boundary: 'reinstall' }).status, 'passed');
});

test('scan limits and symlink escape make absence incomplete, with no content from outside app-data', (t) => {
  const f = fixture(t), { stagingEvidence } = stageIosFilesAssets(f.options), outside = path.join(f.root, 'never-scan.txt');
  writeFileSync(outside, f.assets[0].marker); symlinkSync(outside, path.join(f.app, 'escape'));
  const { snapshot } = f.snapshot(stagingEvidence, 'symlink.json');
  assert.equal(snapshot.complete, false); assert.equal(snapshot.findings.length, 0);
  assert.throws(() => assertIosFilesPrivacy(snapshot, { boundary: 'restart' }), /COMPLETE_FILES_PRIVACY_SCAN_REQUIRED/);
  assert.throws(() => f.snapshot(stagingEvidence, 'raised.json', { limits: { files: 4097 } }), /PRIVACY_SCAN_BOUND_CANNOT_BE_RAISED/);
  rmSync(path.join(f.app, 'escape')); writeFileSync(path.join(f.app, 'large.bin'), Buffer.alloc(32));
  const bounded = f.snapshot(stagingEvidence, 'bounded.json', { limits: { fileBytes: 16 } });
  assert.equal(bounded.snapshot.complete, false);
});
