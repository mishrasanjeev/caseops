import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { ANDROID_FILES_SCAN_LIMITS, attestAndroidFilesContainers, snapshotAndroidFilesPrivacy, stageAndroidFilesAssets, snapshotAndroidCameraPrivacy } from './android-files-privacy.mjs';
import { assertCameraCopiesRemoved, CAMERA_PRIVACY_LIMITS } from './camera-files-privacy.mjs';

const APP = 'ai.caseops.mobile.dev.localacceptance', SERIAL = 'emulator-5584';
const PRIVATE = `/data/user/0/${APP}`, PUBLIC = '/storage/emulated/0/Download';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const environment = { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5038', PATH: '/unit/bin',
  CASEOPS_MOBILE_CORE_PASSWORD: 'SYNTHETIC_PRIVATE_VALUE_MUST_NOT_REACH_ADB' };

// Explicit protocol/filesystem doubles only. No adb, VM, appdata, root command
// or production operation is invoked by these source-contract tests.
function fixture(t, selectedProfile = null) {
  const profile = selectedProfile ?? { udid: 'emulator-5584', adbPort: 5038, appiumUrl: 'http://127.0.0.1:4725', systemPort: 8202, avdName: 'CaseOps_Pixel9_API36_arm64' };
  const SERIAL = profile.udid;
  const selectedEnvironment = { ...environment, ADB_SERVER_SOCKET: `tcp:127.0.0.1:${profile.adbPort}` };
  const root = mkdtempSync(path.join(os.tmpdir(), 'caseops-android-files-fs-unit-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const nodes = new Map(), calls = []; let inode = 10;
  const add = (file, bytes = null, uid = file.startsWith(PRIVATE) ? 10087 : 1023) => {
    const data = bytes === null ? null : Buffer.from(bytes);
    nodes.set(file, { kind: bytes === null ? 'directory' : 'file', uid, device: '10', inode: String(++inode),
      sizeBytes: data?.length || 0, modified: '2026-10-26 00:00:00.123456789 +0000', changed: '2026-10-26 00:00:00.123456789 +0000', bytes: data });
    return nodes.get(file);
  };
  add(PRIVATE); add(PUBLIC); add(`${PRIVATE}/cache`);
  const line = node => [node.kind === 'directory' ? 'directory' : 'regular file', node.uid, node.device, node.inode,
    node.sizeBytes, node.modified, node.changed].join('|');
  const state = { uid: '0', bootId: '11111111-2222-4333-8444-555555555555', avd: profile.avdName, brokenRead: false, listCalls: 0 };
  const command = (binary, args, options) => {
    assert.equal(binary, 'adb'); assert.deepEqual(args.slice(0, 2), ['-s', SERIAL]);
    assert.equal(options.shell, false); assert.ok(options.timeout > 0 && options.timeout <= 15000);
    assert.equal(options.env.ADB_SERVER_SOCKET, `tcp:127.0.0.1:${profile.adbPort}`);
    assert.equal(Object.hasOwn(options.env, 'CASEOPS_MOBILE_CORE_PASSWORD'), false);
    const argv = args.slice(2); calls.push(argv);
    let value;
    if (argv[0] === 'get-state') value = 'device';
    else if (argv.join(' ') === 'shell id -u') value = state.uid;
    else if (argv.join(' ') === 'shell am get-current-user') value = '0';
    else if (argv.join(' ') === 'shell getprop ro.build.version.sdk') value = '36';
    else if (argv.join(' ') === 'shell getprop ro.product.cpu.abi') value = 'arm64-v8a';
    else if (argv.join(' ') === 'emu avd name') value = `${state.avd}\nOK\n`;
    else if (argv.join(' ') === 'shell cat /proc/sys/kernel/random/boot_id') value = state.bootId;
    else if (argv.slice(0, 6).join(' ') === 'shell cmd package list packages -U') value = `package:${APP} uid:10087`;
    else if (argv[0] === 'shell' && argv[1] === 'readlink') value = argv.at(-1) === '/sdcard/Download' ? PUBLIC : argv.at(-1);
    else if (argv[0] === 'shell' && argv[1] === '-T') {
      assert.equal(argv.length, 3, 'ONE_QUOTED_REMOTE_SHELL_COMMAND_REQUIRED');
      const script = argv[2], file = /'([^']*)'$/.exec(script)?.[1];
      if (script.includes('CASEOPS_ANDROID_STAT_V1')) value = nodes.has(file) ? nodes.get(file).symlink ? 'SYMLINK' : line(nodes.get(file)) : 'ABSENT';
      else if (script.includes('CASEOPS_ANDROID_LIST_V1')) {
        state.listCalls++;
        let selected = [...nodes.keys()].filter(name => name === file || name.startsWith(`${file}/`));
        if (state.listMode === 'missing-root') selected = selected.filter(name => name !== file);
        if (state.listMode === 'duplicate') selected.push(file);
        value = state.listMode === 'empty' ? Buffer.alloc(0) : Buffer.from(selected.join('\0') + '\0');
        if (state.listCalls === 1 && state.lateBytes) add(`${PRIVATE}/cache/late-known-copy`, state.lateBytes);
        if (state.listCalls === 1 && state.cameraLateBytes) add(`${file}/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.png`, state.cameraLateBytes);
      }
      else if (script.includes('CASEOPS_ANDROID_READ_FD_V1')) {
        const node = nodes.get(file);
        if (state.replacementBeforeRead) node[state.replacementBeforeRead] = state.replacementBeforeRead === 'inode' ? '999999' : 10088;
        const header = line(state.readOwner ? { ...node, uid: state.readOwner } : node);
        const admitted = /'([^']*)' '[^']*'$/.exec(script)?.[1];
        assert.ok(script.includes('"$expected" ] || exit 37') && admitted, 'ADMITTED_METADATA_PRE_READ_REQUIRED');
        if (header.split('|').slice(1).join('|') !== admitted) throw Error('synthetic pre-read metadata refusal');
        assert.ok(script.includes('head -c ') && !script.includes('cat <&3'), 'ACTUAL_DEVICE_READ_MUST_BE_BOUNDED');
        assert.ok(script.includes('trap') && script.includes('readlink -f'), 'DESCRIPTOR_CLOSE_AND_NAMESPACE_REQUIRED');
        if (script.includes('stat -Lc %h') && node.links === 2) throw Error('synthetic remote single-link refusal');
        state.bodyReads = (state.bodyReads || 0) + 1;
        const body = state.corruptSecondCameraRead && file.endsWith('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.png') ? Buffer.from('yy') : node.bytes;
        value = Buffer.concat([Buffer.from(`${header}\n`), body, Buffer.from(`\n${state.brokenRead ? header + '-changed' : header}\n`)]);
        if (state.afterReadBytes) { node.bytes = state.afterReadBytes; node.sizeBytes = node.bytes.length;
          node.modified = '2026-10-26 00:00:01.123456789 +0000'; }
      } else if (script.includes('CASEOPS_ANDROID_WRITE_ASSET_V1')) {
        const tail = /'([^']*)' '([^']*)' '([^']*)'$/.exec(script);
        assert.ok(tail); const [, directory, filename, expectedIdentity] = tail, parent = nodes.get(directory);
        assert.equal(`${parent.device}:${parent.inode}`, expectedIdentity);
        const destination = `${directory}/${filename}`;
        assert.equal(nodes.has(destination), false, 'UNIT_EXCLUSIVE_REMOTE_ASSET_CREATE');
        assert.ok(Buffer.isBuffer(options.input), 'VERIFIED_DESCRIPTOR_BUFFER_REQUIRED');
        add(destination, options.input, 0); value = '';
      } else assert.fail('UNRECOGNIZED_OFFLINE_DEVICE_SCRIPT');
    } else if (argv[0] === 'shell' && argv[1] === 'mkdir') {
      assert.equal(nodes.has(argv.at(-1)), false, 'UNIT_EXCLUSIVE_PROVIDER_FOLDER'); add(argv.at(-1), null, 0); value = '';
    } else if (argv[0] === 'push') { add(argv[2], readFileSync(argv[1]), 0); value = '1 file pushed'; }
    else if (argv[0] === 'shell' && argv[1] === 'chmod') value = '';
    else if (argv[0] === 'shell' && argv[1] === 'sha256sum') value = `${sha(nodes.get(argv[2]).bytes)}  ${argv[2]}`;
    else assert.fail(`UNEXPECTED_OFFLINE_DEVICE_COMMAND: ${argv[0]}`);
    return options.encoding === 'utf8' ? Buffer.isBuffer(value) ? value.toString() : value : Buffer.from(value);
  };
  const options = { udid: SERIAL, appId: APP, command, environment: selectedEnvironment };
  const save = (name, value) => {
    const file = path.join(root, name), bytes = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
    writeFileSync(file, bytes); return { path: file, sha256: sha(bytes) };
  };
  const manifest = nonce => {
    const assets = ['txt', 'pdf'].map(id => {
      const filename = `CaseOps-android-files-${nonce}-${id}.${id}`, marker = `SYNTHETIC-${nonce}-${id}`;
      const ref = save(filename, `${marker}\nNo legal authority or customer data.\n`);
      return { id, filename, path: ref.path, sha256: ref.sha256, sizeBytes: readFileSync(ref.path).length, marker };
    });
    return save(`manifest-${nonce}.json`, { schemaVersion: 1, kind: 'android-files-synthetic-fixtures', platform: 'android', syntheticDataOnly: true, assets });
  };
  const containers = attestAndroidFilesContainers(options), manifestEvidence = manifest('012345abcdef');
  const stage = (suffix = 'first', selectedManifest = manifestEvidence) => stageAndroidFilesAssets({ ...options, containers,
    manifestEvidence: selectedManifest, runId: `unit-run-${suffix}`, output: path.join(root, `provider-${suffix}.json`) });
  const snapshot = (stagingEvidence, extra = {}) => snapshotAndroidFilesPrivacy({ ...options, containers, stagingEvidence, verifyProviderBytes: true,
    output: path.join(root, `snapshot-${Math.random().toString(16).slice(2)}.json`), ...extra });
  const camera = () => snapshotAndroidCameraPrivacy({ ...options, containers, output: path.join(root, `camera-${Math.random().toString(16).slice(2)}.json`) });
  return { root, nodes, calls, add, state, command, options, save, manifest, manifestEvidence, containers, stage, snapshot, camera };
}

test('actual attestation contract binds isolated AVD boot/API/ABI/root/package UID and canonical private/provider roots without mutation', t => {
  const f = fixture(t);
  assert.equal(f.containers.rootUid, 0); assert.equal(f.containers.packageUid, 10087);
  assert.equal(f.containers.appData.path, PRIVATE); assert.equal(f.containers.provider.path, PUBLIC);
  assert.equal(f.calls.some(args => ['root', 'push', 'install', 'rm'].includes(args[0])), false);
});

test('missing root, foreign AVD, changed boot or private directory owner refuse rather than guessing run-as access', t => {
  for (const edit of [f => { f.state.uid = '2000'; }, f => { f.state.avd = 'other-avd'; },
    f => { f.state.bootId = 'not-a-boot-id'; }, f => { f.nodes.get(PRIVATE).uid = 10088; }]) {
    const f = fixture(t); edit(f);
    assert.throws(() => attestAndroidFilesContainers(f.options), /ANDROID_FILES_|OWNED_ANDROID_AVD_REQUIRED/);
    assert.equal(f.calls.some(args => args[0] === 'root' || args[0] === 'push'), false);
  }
});

test('staging copies only exact public manifest assets to one exclusive provider folder and rechecks bytes/hash', t => {
  const f = fixture(t), result = f.stage();
  assert.equal(result.receipt.folderName, 'CaseOpsFiles-unit-run-first');
  assert.equal(result.receipt.assets.length, 2); assert.equal(result.receipt.originalsDeleted, false);
  assert.equal(f.calls.filter(args => args.some(value => value.includes('CASEOPS_ANDROID_WRITE_ASSET_V1'))).length, 2);
  assert.throws(() => f.stage(), /ANDROID_FILES_OUTPUT_EXISTS/);
  assert.equal(f.calls.filter(args => args.some(value => value.includes('CASEOPS_ANDROID_WRITE_ASSET_V1'))).length, 2);
  assert.equal(f.calls.some(args => args.includes('rm') || args.includes('delete')), false);
});

test('verified-buffer provider transfer never runs a provider byte read before picker journeys', t => {
  const f = fixture(t), result = f.stage();
  assert.equal(f.calls.filter(args => args[0] === 'shell' && args[1] === 'sha256sum').length, 0);
  assert.equal(result.receipt.providerOriginalsRead, false);
  assert.ok(result.receipt.assets.every(asset => asset.transferSha256 === asset.sha256 && asset.providerMetadata.kind === 'file'));
});
test('deferred cleanup checks provider metadata without hashes or descriptor payload reads', t => {
  const f = fixture(t), result = f.stage(); f.calls.length = 0;
  const current = f.snapshot(result.evidence, { verifyProviderBytes: false });
  assert.equal(f.calls.filter(args => args[0] === 'shell' && args[1] === 'sha256sum').length, 0);
  assert.equal(f.calls.filter(args => args.some(value => value.includes('CASEOPS_ANDROID_READ_FD_V1'))).length, 0);
  assert.equal(current.snapshot.complete, true); assert.equal(current.snapshot.providerOriginalsRead, false);
  assert.equal(current.snapshot.providerOriginalsPreserved, null); assert.equal(current.snapshot.providerMetadataPreserved, true);
});
test('final original verification uses bounded admitted descriptors and rejects same-byte inode replacement', t => {
  const f = fixture(t), staged = f.stage(), cold = f.snapshot(staged.evidence, { verifyProviderBytes: false });
  assert.equal(cold.snapshot.providerOriginalsPreserved, null);
  const final = f.snapshot(staged.evidence);
  assert.equal(final.snapshot.complete, true); assert.equal(final.snapshot.providerOriginalsRead, true); assert.equal(final.snapshot.providerOriginalsPreserved, true);
  assert.equal(final.snapshot.providerBytesRead, staged.receipt.assets.reduce((sum, row) => sum + row.sizeBytes, 0));
  assert.equal(f.calls.some(args => args[0] === 'shell' && args[1] === 'sha256sum'), false);
  f.nodes.get(staged.receipt.assets[0].devicePath).inode = '999999';
  const replaced = f.snapshot(staged.evidence);
  assert.equal(replaced.snapshot.complete, false); assert.equal(replaced.snapshot.providerMetadataPreserved, false); assert.equal(replaced.snapshot.providerOriginalsPreserved, false);
});
test('final provider metadata is reconciled after private scanning, including a cold checkpoint', t => {
  for (const verifyProviderBytes of [false, true]) {
    const f = fixture(t), staged = f.stage(), privateFile = `${PRIVATE}/cache/unrelated`;
    f.add(privateFile, 'unrelated private cache content'); const command = f.options.command; let changed = false;
    f.options.command = (binary, args, options) => { const value = command(binary, args, options);
      if (!changed && args.some(arg => arg.includes('CASEOPS_ANDROID_READ_FD_V1') && arg.includes(privateFile))) {
        changed = true; f.nodes.get(staged.receipt.assets[0].devicePath).modified = '2026-10-26 00:00:01.123456789 +0000';
      } return value;
    };
    const result = f.snapshot(staged.evidence, { verifyProviderBytes });
    assert.equal(changed, true); assert.equal(result.snapshot.complete, false); assert.equal(result.snapshot.providerMetadataPreserved, false);
    assert.equal(result.snapshot.providerOriginalsPreserved, verifyProviderBytes ? false : null);
    if (!verifyProviderBytes) assert.equal(result.snapshot.providerOriginalsRead, false);
    assert.ok(result.snapshot.issues.some(row => row.reason === 'provider-original-final-metadata-changed'));
  }
});

test('staging rejects mismatched local bytes, credential-named inputs and another platform before creating a provider folder', t => {
  for (const edit of [value => { value.platform = 'ios'; }, value => { value.assets[0].filename = 'credentials.json'; },
    value => { value.assets[0].sha256 = 'a'.repeat(64); }, value => { value.assets[0].sizeBytes++; }]) {
    const f = fixture(t), value = JSON.parse(readFileSync(f.manifestEvidence.path)); edit(value);
    const manifest = f.save('invalid-manifest.json', value);
    assert.throws(() => f.stage('invalid', manifest), /ANDROID_FILES_|FIXTURE_EVIDENCE_CHANGED/);
    assert.equal(f.calls.some(args => args[0] === 'push' || args[1] === 'mkdir'), false);
  }
});

test('uncertain provider write retains its exclusive attempt and never replays or deletes the partially staged original', t => {
  const f = fixture(t), command = f.options.command, failure = new Error('UNIT_PUSH_ACK_UNKNOWN'); let pushes = 0;
  f.options.command = (binary, args, options) => {
    const value = command(binary, args, options);
    if (args.some(value => value.includes('CASEOPS_ANDROID_WRITE_ASSET_V1'))) { pushes++; throw failure; }
    return value;
  };
  assert.throws(() => f.stage(), error => error === failure);
  const attempt = JSON.parse(readFileSync(path.join(f.root, 'provider-first.json.attempt.json')));
  assert.equal(attempt.automaticReplayAllowed, false); assert.equal(pushes, 1);
  assert.throws(() => f.stage(), /ANDROID_FILES_OUTPUT_EXISTS/); assert.equal(pushes, 1);
  assert.equal(f.calls.some(args => args.includes('rm')), false);
});

test('public provider transfer uses verified descriptor bytes even if the source pathname is replaced immediately before dispatch', t => {
  const f = fixture(t), asset = JSON.parse(readFileSync(f.manifestEvidence.path)).assets[0], command = f.options.command;
  const original = readFileSync(asset.path); let replaced = false;
  f.options.command = (binary, args, options) => {
    if (!replaced && args.some(value => value.includes('CASEOPS_ANDROID_WRITE_ASSET_V1'))) {
      replaced = true; writeFileSync(asset.path, 'UNEXPECTED_REPLACEMENT_MUST_NEVER_REACH_PUBLIC_PROVIDER');
    }
    return command(binary, args, options);
  };
  assert.throws(() => f.stage(), /FIXTURE_EVIDENCE_CHANGED/);
  const destination = `${PUBLIC}/CaseOpsFiles-unit-run-first/${asset.filename}`;
  assert.deepEqual(f.nodes.get(destination).bytes, original);
  assert.equal(sha(f.nodes.get(destination).bytes), asset.sha256);
  assert.equal(f.calls.some(args => args[0] === 'push'), false);
});

test('clean private appdata scan preserves every provider original and reports measured zero findings with no deletion', t => {
  const f = fixture(t), stage = f.stage(), result = f.snapshot(stage.evidence);
  assert.equal(result.snapshot.complete, true); assert.equal(result.snapshot.providerOriginalsPreserved, true);
  assert.equal(result.snapshot.providerOriginals.length, 2);
  assert.equal(result.snapshot.counts.privateAssetMatchCount, 0); assert.equal(result.snapshot.counts.ownedStagingFiles, 0);
  assert.equal(result.snapshot.fileContentsRetained, false); assert.equal(result.snapshot.deviceFilesDeleted, false);
});

test('known original bytes and cached workspace filename/SHA metadata are findings without retaining contents', t => {
  const f = fixture(t), stage = f.stage(), asset = stage.receipt.assets[0];
  const content = readFileSync(JSON.parse(readFileSync(f.manifestEvidence.path)).assets[0].path);
  f.add(`${PRIVATE}/cache/opaque-copy`, content);
  f.add(`${PRIVATE}/cache/workspace.json`, JSON.stringify({ filename: asset.filename, sourceHash: asset.sha256 }));
  const result = f.snapshot(stage.evidence), findings = result.snapshot.findings;
  assert.equal(result.snapshot.counts.privateAssetMatchCount, 2);
  assert.ok(findings.some(value => value.matches.some(match => match.reasons.includes('exact-content-sha256'))));
  assert.ok(findings.some(value => value.matches.some(match => match.reasons.includes('synthetic-sha256-metadata') && match.reasons.includes('synthetic-filename'))));
  assert.ok(findings.every(value => value.relativePath.startsWith('app-data/cache/')));
  assert.equal(JSON.stringify(result.snapshot).includes(asset.marker), false);
  assert.equal(JSON.stringify(result.snapshot).includes('No legal authority or customer data.'), false);
});

test('prior cohorts and base TXT remain scanning oracles while all provider originals are independently preserved', t => {
  const f = fixture(t), old = f.stage(), fresh = f.stage('second', f.manifest('abcdef012345'));
  const text = 'Synthetic CaseOps mobile source. No legal authority or customer data.\n';
  const seeded = { id: 'seeded-txt', filename: 'mobile-source.txt', sizeBytes: Buffer.byteLength(text), sha256: sha(text), marker: text.trim() };
  f.add(`${PRIVATE}/cache/old-workspace.json`, `${old.receipt.assets[0].filename}\n${seeded.sha256}`);
  const result = f.snapshot(fresh.evidence, { priorStagingEvidence: [old.evidence], knownSources: [seeded] });
  assert.equal(result.snapshot.providerOriginals.length, 4); assert.equal(result.snapshot.providerOriginalsPreserved, true);
  assert.equal(result.snapshot.counts.privateAssetMatchCount, 1);
  assert.equal(result.snapshot.findings[0].matches.length, 2);
});

test('private staging files count independently of whether their bytes match any synthetic original', t => {
  const f = fixture(t), stage = f.stage();
  f.add(`${PRIVATE}/cache/caseops-matter-files-v1`);
  f.add(`${PRIVATE}/cache/caseops-matter-files-v1/opaque`, 'unmatched synthetic staging control');
  const result = f.snapshot(stage.evidence);
  assert.equal(result.snapshot.counts.ownedStagingFiles, 1); assert.equal(result.snapshot.counts.privateAssetMatchCount, 0);
});

test('descriptor-framing change or a scan bound stays incomplete and cannot become zero-copy privacy proof', t => {
  for (const kind of ['changed-read', 'oversize', 'depth', 'mount']) {
    const f = fixture(t), stage = f.stage();
    const target = `${PRIVATE}/cache/${kind === 'depth' ? `${'nested/'.repeat(17)}file` : 'copy'}`;
    const metadata = f.add(target, 'synthetic-control');
    if (kind === 'changed-read') f.state.brokenRead = true;
    if (kind === 'oversize') metadata.sizeBytes = ANDROID_FILES_SCAN_LIMITS.fileBytes + 1;
    if (kind === 'mount') metadata.device = '99999';
    const result = f.snapshot(stage.evidence);
    assert.equal(result.snapshot.complete, false); assert.ok(result.snapshot.issues.length > 0);
  }
});

test('changed provider originals are reported and boot identity changes refuse before scanning another runtime', t => {
  const f = fixture(t), stage = f.stage(), asset = stage.receipt.assets[0];
  f.nodes.get(asset.devicePath).bytes = Buffer.from('changed-original');
  const result = f.snapshot(stage.evidence);
  assert.equal(result.snapshot.providerOriginalsPreserved, false); assert.equal(result.snapshot.complete, false);
  f.state.bootId = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
  assert.throws(() => f.snapshot(stage.evidence), /ANDROID_FILES_CONTAINER_IDENTITY_CHANGED/);
});

test('reviewed limits cannot be enlarged and wrong ADB socket refuses before any device command', t => {
  const f = fixture(t), stage = f.stage();
  assert.throws(() => f.snapshot(stage.evidence, { limits: { ...ANDROID_FILES_SCAN_LIMITS, fileBytes: 999999999 } }), /ANDROID_FILES_REVIEWED_SCAN_LIMITS_REQUIRED/);
  const before = f.calls.length;
  assert.throws(() => attestAndroidFilesContainers({ ...f.options, environment: { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5037' } }), /ISOLATED_ANDROID_FILES_ADB_REQUIRED/);
  assert.equal(f.calls.length, before);
});

test('a newly created or replaced external private root cannot be omitted from a stale zero-copy scan', t => {
  const f = fixture(t), stage = f.stage(), external = `/storage/emulated/0/Android/data/${APP}`;
  f.add(external); f.add(`${external}/cache`);
  f.add(`${external}/cache/known-copy`, readFileSync(JSON.parse(readFileSync(f.manifestEvidence.path)).assets[0].path));
  assert.throws(() => f.snapshot(stage.evidence), /ANDROID_FILES_EXTERNAL_ROOT_CHANGED/);
  const actual = attestAndroidFilesContainers(f.options);
  const observed = f.snapshot(stage.evidence, { containers: actual });
  assert.equal(observed.snapshot.complete, true); assert.equal(observed.snapshot.counts.privateAssetMatchCount, 1);
  f.nodes.get(external).inode = '99999';
  assert.throws(() => f.snapshot(stage.evidence, { containers: actual }), /ANDROID_FILES_EXTERNAL_ROOT_CHANGED/);
});

test('empty, duplicate or root-omitting directory listings remain incomplete rather than proving measured zero files', t => {
  for (const listMode of ['empty', 'missing-root', 'duplicate']) {
    const f = fixture(t), stage = f.stage(); f.state.listMode = listMode;
    const result = f.snapshot(stage.evidence);
    assert.equal(result.snapshot.complete, false);
    assert.ok(result.snapshot.issues.some(value => value.reason === 'incomplete-initial-directory-inventory'));
  }
  const charged = fixture(t), stage = charged.stage();
  for (let index = 0; index < 4095; index++) charged.add(`${PRIVATE}/cache/directory-${index}`);
  const overflow = charged.snapshot(stage.evidence);
  assert.equal(overflow.snapshot.complete, false);
  assert.ok(overflow.snapshot.counts.entries > ANDROID_FILES_SCAN_LIMITS.entries);
  assert.ok(overflow.snapshot.issues.some(value => value.reason === 'incomplete-final-directory-inventory'));
});

test('a known private copy created after the initial listing changes the final charged inventory and cannot be clean', t => {
  const f = fixture(t), stage = f.stage(), local = JSON.parse(readFileSync(f.manifestEvidence.path)).assets[0].path;
  f.state.lateBytes = readFileSync(local);
  const result = f.snapshot(stage.evidence);
  assert.equal(result.snapshot.complete, false);
  assert.ok(result.snapshot.issues.some(value => value.reason === 'directory-inventory-changed'));
  assert.equal(result.snapshot.inventories[0].stable, false);
  assert.ok(result.snapshot.counts.entries >= 5, 'BOTH_DIRECTORY_OBSERVATIONS_MUST_BE_CHARGED');
  assert.ok(result.snapshot.counts.observationBytes <= ANDROID_FILES_SCAN_LIMITS.totalBytes);
});

test('a file replaced with known bytes after its descriptor read fails the final metadata reconciliation', t => {
  const f = fixture(t), stage = f.stage(), asset = JSON.parse(readFileSync(f.manifestEvidence.path)).assets[0];
  f.add(`${PRIVATE}/cache/opaque`, Buffer.alloc(asset.sizeBytes, 88));
  f.state.afterReadBytes = readFileSync(asset.path);
  const result = f.snapshot(stage.evidence);
  assert.equal(result.snapshot.complete, false);
  assert.ok(result.snapshot.issues.some(value => value.reason === 'directory-or-file-metadata-changed'));
});

test('camera zero-copy scope distinguishes absent and empty exact SDK directory without opening provider assets', t => {
  for (const present of [false, true]) {
    const f = fixture(t);
    if (present) f.add(`${PRIVATE}/cache/ImagePicker`);
    const value = f.camera().observation;
    assert.equal(value.complete, true); assert.equal(value.directoryPresent, present); assert.equal(value.counts.copies, 0);
    assert.equal(assertCameraCopiesRemoved(value).status, 'passed');
    assert.equal(f.calls.some(args => args.includes('sha256sum')), false);
    assert.equal(value.providerOriginalsRead, false);
  }
});

test('unknown camera bytes are separate from legacy Files counts and have bounded UID-verified descriptor evidence', t => {
  const f = fixture(t), stage = f.stage(), sdk = `${PRIVATE}/cache/ImagePicker`;
  f.add(sdk); f.add(`${sdk}/11111111-2222-4333-8444-555555555555.jpg`, 'UNKNOWN_SYNTHETIC_CAMERA_MEDIA');
  assert.equal(f.snapshot(stage.evidence).snapshot.counts.privateAssetMatchCount, 0);
  f.state.listCalls = 0;
  const value = f.camera().observation;
  assert.equal(value.complete, true); assert.equal(value.counts.copies, 1); assert.equal(value.copies.length, 1);
  assert.equal(value.legacyKnownFixtureCountsIncluded, false); assert.equal(value.packageUid, 10087);
  assert.equal(JSON.stringify(value).includes('UNKNOWN_SYNTHETIC_CAMERA_MEDIA'), false);
  assert.throws(() => assertCameraCopiesRemoved(value), /OWNED_CAMERA_SDK_COPY_REMAINS/);
  assert.ok(f.calls.some(args => args.at(-1)?.includes(`head -c ${CAMERA_PRIVACY_LIMITS.fileBytes + 1}`)));
});

test('camera malformed names, nesting, foreign UID/device, hardlinks and oversized copies remain incomplete', t => {
  for (const kind of ['name', 'nested', 'uid', 'mount', 'hardlink', 'oversize']) {
    const f = fixture(t), sdk = `${PRIVATE}/cache/ImagePicker`; f.add(sdk);
    const target = `${sdk}/${kind === 'name' ? 'unreviewed-private-name' : kind === 'nested' ? 'nested/copy.jpg' : '11111111-2222-4333-8444-555555555555.jpg'}`;
    const node = f.add(target, 'synthetic');
    if (kind === 'uid') node.uid = 10088;
    if (kind === 'mount') node.device = '99999';
    if (kind === 'hardlink') node.links = 2;
    if (kind === 'oversize') node.sizeBytes = CAMERA_PRIVACY_LIMITS.fileBytes + 1;
    const value = f.camera().observation;
    assert.equal(value.complete, false, kind); assert.equal(value.copies.length, 0, kind);
    assert.equal(JSON.stringify(value).includes('unreviewed-private-name'), false);
  }
});

test('camera owner change in the opened descriptor and late copy insertion are never clean', t => {
  for (const kind of ['read-owner', 'late-copy']) {
    const f = fixture(t), sdk = `${PRIVATE}/cache/ImagePicker`; f.add(sdk);
    f.add(`${sdk}/11111111-2222-4333-8444-555555555555.jpg`, 'synthetic');
    if (kind === 'read-owner') f.state.readOwner = 10088;
    else f.state.cameraLateBytes = 'late-camera-copy';
    const value = f.camera().observation;
    assert.equal(value.complete, false); assert.ok(value.issues.length > 0);
    assert.throws(() => assertCameraCopiesRemoved(value), /COMPLETE_CAMERA_SDK_OBSERVATION_REQUIRED/);
  }
});

test('camera directory owner or boot mismatch refuses instead of scanning another identity', t => {
  for (const kind of ['owner', 'boot']) {
    const f = fixture(t), sdk = `${PRIVATE}/cache/ImagePicker`; const node = f.add(sdk);
    if (kind === 'owner') node.uid = 10088;
    else f.state.bootId = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
    assert.throws(() => f.camera(), kind === 'owner' ? /CAMERA_DIRECTORY_OWNER_REQUIRED/ : /ANDROID_FILES_CONTAINER_IDENTITY_CHANGED/);
    assert.equal(f.calls.some(args => args.at(-1)?.includes('CASEOPS_ANDROID_READ_FD_V1')), false);
  }
});

test('changed camera inode or UID is refused by admitted descriptor metadata before any media body read', t => {
  for (const field of ['inode', 'uid']) {
    const f = fixture(t), sdk = `${PRIVATE}/cache/ImagePicker`; f.add(sdk);
    f.add(`${sdk}/11111111-2222-4333-8444-555555555555.jpg`, 'REPLACEMENT_MEDIA_MUST_NOT_BE_READ');
    f.state.replacementBeforeRead = field;
    const value = f.camera().observation;
    assert.equal(value.complete, false); assert.equal(value.readBytesComplete, false);
    assert.equal(f.state.bodyReads || 0, 0); assert.equal(value.counts.bytesRead, 0);
  }
});

test('camera body budget shrinks after earlier copies and an uncertain body read stops all later copies', t => {
  const f = fixture(t), sdk = `${PRIVATE}/cache/ImagePicker`; f.add(sdk);
  f.add(`${sdk}/11111111-2222-4333-8444-555555555555.jpg`, Buffer.alloc(17 * 1024 * 1024 + 17));
  f.add(`${sdk}/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.png`, 'y');
  f.add(`${sdk}/bbbbbbbb-cccc-4ddd-8eee-ffffffffffff.jpg`, 'MUST_NOT_READ_THIRD_COPY');
  f.state.corruptSecondCameraRead = true;
  const value = f.camera().observation;
  assert.equal(value.complete, false); assert.equal(value.readBytesComplete, false); assert.equal(f.state.bodyReads, 2);
  const reads = f.calls.map(args => args.at(-1)).filter(value => value?.includes('CASEOPS_ANDROID_READ_FD_V1'));
  assert.equal(reads.length, 2);
  const first = Number(/head -c (\d+)/.exec(reads[0])[1]), second = Number(/head -c (\d+)/.exec(reads[1])[1]);
  assert.ok(second < first && second <= CAMERA_PRIVACY_LIMITS.totalBytes - value.counts.bytesRead + 1);
});


test('owned 16K Files attestation binds actual AVD and uses only its exact isolated device/ADB tuple', t => {
  const f = fixture(t, { udid: 'emulator-5580', adbPort: 5040, appiumUrl: 'http://127.0.0.1:4727', systemPort: 8204, avdName: 'CaseOps_PR558_16K_20261028_03' });
  assert.equal(f.containers.udid, 'emulator-5580'); assert.equal(f.containers.avdName, 'CaseOps_PR558_16K_20261028_03');
  assert.equal(f.containers.bootId, '11111111-2222-4333-8444-555555555555'); assert.equal(f.containers.packageUid, 10087);
  assert.ok(f.calls.length > 0); assert.equal(f.calls.some(args => ['root', 'install', 'push', 'rm'].includes(args[0])), false);
});

test('owned 16K Files constructor refuses mixed ADB/serial before command and old AVD after read-only identity', t => {
  const f = fixture(t, { udid: 'emulator-5580', adbPort: 5040, appiumUrl: 'http://127.0.0.1:4727', systemPort: 8204, avdName: 'CaseOps_PR558_16K_20261028_03' });
  for (const patch of [{ ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5038' }, { ADB_SERVER_SOCKET: 'tcp:127.0.0.1:5037' },
    { ANDROID_ADB_SERVER_PORT: '5038' }, { ANDROID_SERIAL: 'emulator-5584' }]) {
    let calls = 0;
    assert.throws(() => attestAndroidFilesContainers({ ...f.options, environment: { ...f.options.environment, ...patch }, command: () => { calls++; } }), /ISOLATED_ANDROID_FILES_ADB_REQUIRED|DEDICATED_ANDROID_FILES_DEVICE_REQUIRED/);
    assert.equal(calls, 0);
  }
  f.state.avd = 'CaseOps_Pixel9_API36_arm64';
  assert.throws(() => attestAndroidFilesContainers(f.options), /OWNED_ANDROID_AVD_REQUIRED/);
});
