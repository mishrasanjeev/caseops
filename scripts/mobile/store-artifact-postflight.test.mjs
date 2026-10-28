import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { rootCertificates } from 'node:tls';
import { X509Certificate } from 'node:crypto';
import { deflateRawSync } from 'node:zlib';
import { inspectStoreZip, safeMember, certificateIdentity, elfLoadAlignments,
  verifyIosDistribution, verifyAndroidDistribution } from './store-artifact-postflight.mjs';
import { digest, jsonInput, namedMatchesStoreDescriptor, readInput, writePrivate } from './store-packaging-inputs.mjs';

function crc(b) { let n = 0xffffffff; for (const v of b) { n ^= v; for (let i = 0; i < 8; i++) n = (n >>> 1) ^ ((n & 1) ? 0xedb88320 : 0); } return (n ^ 0xffffffff) >>> 0; }
function zip(rows) {
  const locals = [], directories = []; let offset = 0;
  for (const row of rows) {
    const name = Buffer.from(row.name), data = Buffer.from(row.body || ''), method = row.deflate ? 8 : 0;
    const packed = method ? deflateRawSync(data) : data, sum = crc(data), local = Buffer.alloc(30), central = Buffer.alloc(46);
    local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20, 4); local.writeUInt16LE(method, 8); local.writeUInt32LE(sum, 14);
    local.writeUInt32LE(packed.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(name.length, 26);
    central.writeUInt32LE(0x02014b50); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(method, 10);
    central.writeUInt32LE(sum, 16); central.writeUInt32LE(packed.length, 20); central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(name.length, 28); central.writeUInt32LE(((row.mode ?? 0o100644) * 65536) >>> 0, 38); central.writeUInt32LE(offset, 42);
    const bytes = Buffer.concat([local, name, packed]); locals.push(bytes); directories.push(Buffer.concat([central, name])); offset += bytes.length;
  }
  const cd = Buffer.concat(directories), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(rows.length, 8); end.writeUInt16LE(rows.length, 10);
  end.writeUInt32LE(cd.length, 12); end.writeUInt32LE(offset, 16); return Buffer.concat([...locals, cd, end]);
}
function fixture(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-store-postflight-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { root, file: path.join(root, 'input.bin') };
}
const attestation = { source: { sourceSha: '1'.repeat(40), sourceFingerprint: digest('fp') },
  nativeLinks: { sha256: digest('links') }, storeBuild: { sha256: digest('build') }, notices: [{ name: 'LICENSE', sha256: digest('notice') }] };
const privacyPolicy = { url: 'https://auth.contract-fixture.org/app-privacy', version: 'synthetic', sha256: digest('privacy') };
function ios() {
  const expected = { appId: 'org.contract.app', version: '1.2.3', iosBuildNumber: '8', now: Date.UTC(2026, 9, 28), iosArchitectures: ['arm64'],
    signing: { certificateSha1: 'a'.repeat(40), certificateSha256: 'b'.repeat(64), teamId: 'TEAM123456', applicationIdentifierPrefix: 'PREF123456', provisioningProfileUuid: 'uuid' },
    associatedDomains: ['applinks:auth.contract-fixture.org'], privacyPolicy, attestation };
  const observed = { strictSignatureExit: 0, certificate: { sha1: expected.signing.certificateSha1, sha256: expected.signing.certificateSha256 }, architectures: ['arm64'],
    info: { CFBundleIdentifier: expected.appId, CFBundleShortVersionString: '1.2.3', CFBundleVersion: '8', DTPlatformName: 'iphoneos', CFBundleSupportedPlatforms: ['iPhoneOS'], MinimumOSVersion: '17.4',
      CaseOpsPrivacyPolicyURL: privacyPolicy.url, CaseOpsPrivacyPolicyVersion: privacyPolicy.version, CaseOpsPrivacyPolicySHA256: privacyPolicy.sha256 },
    entitlements: { 'application-identifier': 'PREF123456.org.contract.app', 'com.apple.developer.team-identifier': 'TEAM123456', 'get-task-allow': false,
      'com.apple.developer.associated-domains': expected.associatedDomains, 'keychain-access-groups': ['PREF123456.org.contract.app'] },
    profile: { UUID: 'uuid', TeamIdentifier: ['TEAM123456'], ApplicationIdentifierPrefix: ['PREF123456'], ExpirationDate: '2027-01-01T00:00:00Z',
      Entitlements: { 'application-identifier': 'PREF123456.org.contract.app', 'get-task-allow': false } }, profileCertificateSha256: ['b'.repeat(64)], attestation };
  return { expected, observed };
}
test('actual retained ZIP bytes validate stored and deflated member CRCs without pathname reopen', t => {
  const f = fixture(t), archive = zip([{ name: 'base/assets/a.txt', body: 'one' }, { name: 'base/assets/b.txt', body: 'two'.repeat(100), deflate: true }]);
  writePrivate(f.file, archive); const read = readInput(f.file, { sha256: digest(archive), maxBytes: archive.length }); const seen = [];
  const got = inspectStoreZip(read.bytes, (row, data) => seen.push([row.name, data.toString()]));
  assert.equal(got.entries.length, 2); assert.equal(got.expandedBytes, 303); assert.equal(got.archiveSha256, digest(archive));
  assert.deepEqual(seen, [['base/assets/a.txt', 'one'], ['base/assets/b.txt', 'two'.repeat(100)]]);
});
test('archive traversal absolute drive backslash empty and dot segments are refused', () => {
  for (const name of ['../x', '/x', 'C:x', 'a\\b', 'a//b', 'a/./b', 'a/../b']) assert.throws(() => inspectStoreZip(zip([{ name, body: 'x' }])), /STORE_ZIP_PATH_REFUSED/);
  assert.equal(safeMember('Payload/CaseOps.app/Info.plist'), 'Payload/CaseOps.app/Info.plist');
});
test('duplicate and symlink archive entries are refused before consumers can treat them as valid', () => {
  assert.throws(() => inspectStoreZip(zip([{ name: 'a', body: 'x' }, { name: 'a', body: 'x' }])), /DUPLICATE/);
  assert.throws(() => inspectStoreZip(zip([{ name: 'a', body: '../target', mode: 0o120777 }])), /MEMBER_REFUSED/);
});
test('real ZIP corruption and local central extent disagreement are rejected', () => {
  const badCrc = zip([{ name: 'a', body: 'x' }]); badCrc[31] ^= 1; assert.throws(() => inspectStoreZip(badCrc), /CONTENT_REFUSED/);
  const badLength = zip([{ name: 'a', body: 'x' }]); badLength.writeUInt32LE(999, 22); assert.throws(() => inspectStoreZip(badLength), /LOCAL_EXTENT/);
});
test('truncation multi-disk ZIP64 and encryption are explicitly unsupported', () => {
  const b = zip([{ name: 'a', body: 'x' }]); assert.throws(() => inspectStoreZip(b.subarray(0, -1)), /DIRECTORY/);
  const disk = Buffer.from(b); disk.writeUInt16LE(1, disk.length - 18); assert.throws(() => inspectStoreZip(disk), /DIRECTORY/);
  const wide = Buffer.from(b); wide.writeUInt16LE(65535, wide.length - 12); assert.throws(() => inspectStoreZip(wide), /DIRECTORY/);
  const encrypted = Buffer.from(b); encrypted.writeUInt16LE(1, 6); encrypted.writeUInt16LE(1, 31 + 1 + 8); assert.throws(() => inspectStoreZip(encrypted));
});
test('declared decompression expansion over the member bound is refused before inflation', () => {
  const b = zip([{ name: 'a', body: 'small', deflate: true }]); const cd = b.indexOf(Buffer.from([0x50, 0x4b, 0x01, 0x02]));
  b.writeUInt32LE(128 * 1024 * 1024 + 1, cd + 24); assert.throws(() => inspectStoreZip(b), /MEMBER_REFUSED/);
});
test('same descriptor growth consumes no more than original extent plus one and closes', t => {
  const f = fixture(t); writePrivate(f.file, Buffer.from('one')); const read = fs.readSync, close = fs.closeSync; let grew = false, bytes = 0, fd;
  fs.readSync = function (handle, buffer, ...args) { if (!grew) { grew = true; fs.appendFileSync(f.file, Buffer.alloc(1000)); } const n = read.call(this, handle, buffer, ...args); bytes += n; return n; };
  fs.closeSync = function (handle) { fd = handle; return close.call(this, handle); };
  try { assert.throws(() => readInput(f.file, { maxBytes: 20 }), /STORE_INPUT_CHANGED/); } finally { fs.readSync = read; fs.closeSync = close; }
  assert.equal(bytes, 4); assert.throws(() => fs.fstatSync(fd), /EBADF/);
});
test('real late parent symlink to the same held inode is refused and descriptor closes', t => {
  const f = fixture(t), parent = path.join(f.root, 'original'); fs.mkdirSync(parent, { mode: 0o700 }); const file = path.join(parent, 'data'); writePrivate(file, Buffer.from('same'));
  const originalInode = fs.statSync(file).ino;
  const read = fs.readSync, close = fs.closeSync; let moved = false, fd;
  fs.readSync = function (...args) { if (!moved) { moved = true; fs.renameSync(parent, parent + '-moved'); fs.symlinkSync(parent + '-moved', parent, 'dir'); } return read.apply(this, args); };
  fs.closeSync = function (handle) { fd = handle; return close.call(this, handle); };
  try { assert.throws(() => readInput(file), error => ['STORE_INPUT_CHANGED', 'STORE_INPUT_NAMESPACE_CHANGED'].includes(error.message)); }
  finally { fs.readSync = read; fs.closeSync = close; }
  assert.equal(fs.statSync(path.join(parent + '-moved', 'data')).ino, originalInode);
  assert.throws(() => fs.fstatSync(fd), /EBADF/);
});
test('zero oversized hardlinked malformed UTF8 and private-mode inputs are refused', t => {
  const f = fixture(t); fs.writeFileSync(f.file, ''); assert.throws(() => readInput(f.file)); fs.writeFileSync(f.file, 'four');
  assert.throws(() => readInput(f.file, { maxBytes: 3 })); fs.linkSync(f.file, f.file + '-link'); assert.throws(() => readInput(f.file)); fs.unlinkSync(f.file + '-link');
  fs.chmodSync(f.file, 0o644); assert.throws(() => readInput(f.file, { privateFile: true }));
  fs.writeFileSync(f.file, Buffer.from([255, 0])); assert.throws(() => jsonInput({ path: f.file, sha256: digest(Buffer.from([255, 0])) }), /STORE_INPUT_JSON_REQUIRED/);
});
test('existing canonical OS aliases work and simulated Windows dev0 changes only cross-API device comparison', t => {
  const f = fixture(t); writePrivate(f.file, Buffer.from('alias')); const alias = f.root + '-alias'; fs.symlinkSync(f.root, alias, 'dir');
  t.after(() => fs.unlinkSync(alias)); assert.equal(readInput(path.join(alias, 'input.bin')).bytes.toString(), 'alias');
  const a = { dev: 1n, ino: 2n, mode: 3n, uid: 4n, gid: 5n, nlink: 1n, size: 6n, mtimeNs: 7n, ctimeNs: 8n };
  assert.equal(namedMatchesStoreDescriptor(a, { ...a, dev: 0n }, 'win32'), true);
  assert.equal(namedMatchesStoreDescriptor(a, { ...a, dev: 0n }, 'darwin'), false);
  assert.equal(namedMatchesStoreDescriptor(a, { ...a, dev: 0n, ino: 99n }, 'win32'), false);
});
test('actual read and initial fstat failures always close the originally opened descriptor', t => {
  const f = fixture(t); writePrivate(f.file, Buffer.from('failure'));
  for (const method of ['readSync', 'fstatSync']) {
    const original = fs[method], close = fs.closeSync; let closed;
    fs[method] = () => { throw new Error('SYNTHETIC_IO_FAILURE'); };
    fs.closeSync = handle => { closed = handle; return close(handle); };
    try { assert.throws(() => readInput(f.file), /SYNTHETIC_IO_FAILURE/); }
    finally { fs[method] = original; fs.closeSync = close; }
    assert.equal(typeof closed, 'number'); assert.throws(() => fs.fstatSync(closed), /EBADF/);
  }
});
test('private output handles real partial writes and refuses zero progress with closed descriptor', t => {
  const f = fixture(t), original = fs.writeSync, close = fs.closeSync; let closed;
  fs.writeSync = (fd, bytes, offset) => original(fd, bytes, offset, 1);
  try { writePrivate(f.file, Buffer.from('partial')); } finally { fs.writeSync = original; }
  assert.equal(fs.readFileSync(f.file, 'utf8'), 'partial');
  fs.writeSync = () => 0; fs.closeSync = fd => { closed = fd; return close(fd); };
  try { assert.throws(() => writePrivate(f.file + '-zero', Buffer.from('refuse')), /NO_PROGRESS/); }
  finally { fs.writeSync = original; fs.closeSync = close; }
  assert.throws(() => fs.fstatSync(closed), /EBADF/);
});
test('public certificate parser validates actual DER and expiry without signing or reading a private key', () => {
  const cert = rootCertificates.map(v => new X509Certificate(v)).find(c => Date.parse(c.validFrom) < Date.now() && Date.parse(c.validTo) > Date.now());
  assert.ok(cert); assert.match(certificateIdentity(cert.raw).sha256, /^[a-f0-9]{64}$/);
  assert.throws(() => certificateIdentity(cert.raw, Date.UTC(2200, 0, 1)), /EXPIRED/); assert.throws(() => certificateIdentity(Buffer.from('not certificate')));
});
test('typed iOS device distribution contract keeps Team and prefix separate and exact attestation bytes', () => {
  const f = ios(); const got = verifyIosDistribution(f.observed, f.expected); assert.equal(got.linkSha256, digest('links'));
  delete f.observed.entitlements['keychain-access-groups']; verifyIosDistribution(f.observed, f.expected);
  assert.notEqual(f.expected.signing.teamId, f.expected.signing.applicationIdentifierPrefix);
});
test('iOS simulator debug profile wrong cert origin version and undeclared source all fail closed', () => {
  for (const mutate of [f => { f.observed.info.DTPlatformName = 'iphonesimulator'; }, f => { f.observed.entitlements['get-task-allow'] = true; },
    f => { f.observed.profile.ProvisionedDevices = ['synthetic-device']; }, f => { f.observed.certificate.sha256 = 'c'.repeat(64); },
    f => { f.observed.entitlements['com.apple.developer.associated-domains'] = ['applinks:wrong.invalid']; }, f => { f.observed.info.CFBundleVersion = '7'; },
    f => { f.observed.attestation = { ...attestation, source: { ...attestation.source, sourceSha: '2'.repeat(40) } }; }]) {
    const f = ios(); mutate(f); assert.throws(() => verifyIosDistribution(f.observed, f.expected));
  }
});
test('actual ELF program headers establish every load alignment and reject truncation', () => {
  const b = Buffer.alloc(120); Buffer.from([127, 69, 76, 70, 2, 1]).copy(b); b.writeBigUInt64LE(64n, 32); b.writeUInt16LE(56, 54); b.writeUInt16LE(1, 56); b.writeUInt32LE(1, 64); b.writeBigUInt64LE(16384n, 112);
  assert.deepEqual(elfLoadAlignments(b), [16384]); assert.throws(() => elfLoadAlignments(b.subarray(0, 100)), /PROGRAM_HEADERS/);
});
test('AAB contract distinguishes upload certificate from Play key and enforces all64-bit16K libraries', () => {
  const expected = { appId: 'org.contract.app', version: '1.2.3', androidVersionCode: 10, signing: { uploadCertificateSha256: 'a'.repeat(64), appSigningCertificateSha256: 'b'.repeat(64) }, androidAbis: ['arm64-v8a'], privacyPolicy, attestation };
  const observed = { bundletoolValidationExit: 0, jarSignatureExit: 0, signerCount: 1, certificate: { sha256: 'a'.repeat(64) }, packageName: expected.appId,
    versionName: '1.2.3', versionCode: 10, targetSdk: 36, debuggable: false, cleartextPermitted: false, allowBackup: false, networkSecurityConfigurationAbsent: true,
    nativeLibraries: [{ abi: 'arm64-v8a', loadAlignments: [16384, 65536] }], privacyPolicy, attestation };
  verifyAndroidDistribution(observed, expected);
  for (const patch of [{ jarSignatureExit: 37 }, { certificate: { sha256: 'b'.repeat(64) } }, { targetSdk: 35 }, { signerCount: 2 }, { debuggable: true },
    { nativeLibraries: [{ abi: 'arm64-v8a', loadAlignments: [4096] }] }, { networkSecurityConfigurationAbsent: false }]) assert.throws(() => verifyAndroidDistribution({ ...observed, ...patch }, expected));
});

test('one invocation deadline refuses before open and during bounded chunks with FD closure', t => {
  const f = fixture(t); writePrivate(f.file, Buffer.alloc(70000));
  const open = fs.openSync, read = fs.readSync, close = fs.closeSync, now = Date.now;
  let opens = 0, closed, clock = 100;
  fs.openSync = (...args) => { opens++; return open(...args); };
  Date.now = () => clock;
  try {
    assert.throws(() => readInput(f.file, { deadline: 99 }), /STORE_TOTAL_DEADLINE/);
    assert.equal(opens, 0);
    fs.readSync = (...args) => { const count = read(...args); clock = 201; return count; };
    fs.closeSync = fd => { closed = fd; return close(fd); };
    assert.throws(() => readInput(f.file, { deadline: 200 }), /STORE_TOTAL_DEADLINE/);
  } finally { fs.openSync = open; fs.readSync = read; fs.closeSync = close; Date.now = now; }
  assert.equal(opens, 1); assert.throws(() => fs.fstatSync(closed), /EBADF/);
});
