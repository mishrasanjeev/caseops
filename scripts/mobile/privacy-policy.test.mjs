import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../apps/mobile/package.json', import.meta.url));
const { readPolicyBytes, readPrivacyPolicySettings, validatePrivacyPolicy } = require('./plugins/privacy-policy.cjs');
const { projectIosPrivacyPolicy, projectAndroidPrivacyPolicy } = require('./plugins/with-privacy-policy.cjs');
const withPrivacyPolicy = require('./plugins/with-privacy-policy.cjs');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const origin = 'https://publisher.contract-fixture.org';
const links = { sha256: 'a'.repeat(64), config: { redirectUri: origin + '/native/oauth/callback' } };
const descriptor = { schemaVersion: 1, kind: 'caseops-mobile-privacy-policy', nativeLinkConfigSha256: links.sha256, url: origin + '/privacy-policy', version: '2026-10-28' };
function fixture(t, value = descriptor) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-policy-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, 'policy.json'), bytes = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
  fs.writeFileSync(file, bytes, { mode: 0o600 });
  return { root, file, bytes, env: { CASEOPS_MOBILE_PRIVACY_POLICY_FILE: file, CASEOPS_MOBILE_PRIVACY_POLICY_SHA256: hash(bytes) } };
}
const options = { links, webOrigin: origin, required: true };
test('policy descriptor projects exactly URL version and byte digest without page approval', t => {
  const f = fixture(t); assert.deepEqual(readPrivacyPolicySettings(f.env, options), { url: descriptor.url, version: descriptor.version, sha256: hash(f.bytes) });
});
test('production policy is required while explicit development absence is null', () => {
  assert.equal(readPrivacyPolicySettings({}, { links: null, webOrigin: origin }), null);
  assert.throws(() => readPrivacyPolicySettings({}, options), /IMMUTABLE_PRIVACY_POLICY_REFERENCE_REQUIRED/);
  for (const env of [{ CASEOPS_MOBILE_PRIVACY_POLICY_FILE: '/synthetic/policy' }, { CASEOPS_MOBILE_PRIVACY_POLICY_SHA256: 'a'.repeat(64) }, { CASEOPS_MOBILE_PRIVACY_POLICY_FILE: '', CASEOPS_MOBILE_PRIVACY_POLICY_SHA256: '' }]) assert.throws(() => readPrivacyPolicySettings(env, options));
});
test('policy rejects foreign origins credentials query fragment normalization and downgrade', () => {
  for (const url of ['http://publisher.contract-fixture.org/privacy', 'https://foreign.contract-fixture.org/privacy', origin + '/privacy?account=synthetic', origin + '/privacy?', origin + '/privacy#', origin + '/privacy#secret', 'https://user:pass@publisher.contract-fixture.org/privacy', origin + ':443/privacy', origin + '/a/../privacy', origin + '/privacy\n']) assert.throws(() => validatePrivacyPolicy({ ...descriptor, url }, { ...options, sha256: 'b'.repeat(64) }), /EXACT_APPROVED_PRIVACY_POLICY_REQUIRED/);
  assert.throws(() => validatePrivacyPolicy(descriptor, { ...options, webOrigin: 'https://foreign.contract-fixture.org', sha256: 'b'.repeat(64) }));
});
test('policy binds approved links and rejects unknown fields and invalid versions', () => {
  for (const value of [{ ...descriptor, nativeLinkConfigSha256: 'b'.repeat(64) }, { ...descriptor, extra: true }, { ...descriptor, version: 1 }, { ...descriptor, version: 'x'.repeat(65) }, { ...descriptor, version: '../policy' }]) assert.throws(() => validatePrivacyPolicy(value, { ...options, sha256: 'b'.repeat(64) }));
});
test('policy malformed duplicate and non-UTF8 JSON never reflects content', t => {
  for (const raw of ['PRIVATE_SYNTHETIC_VALUE', JSON.stringify(descriptor).replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1')]) {
    const f = fixture(t, raw); assert.throws(() => readPrivacyPolicySettings(f.env, options), error => error.message === 'PRIVACY_POLICY_JSON_REQUIRED');
  }
  const f = fixture(t); const raw = Buffer.from([255]); fs.writeFileSync(f.file, raw); assert.throws(() => readPrivacyPolicySettings({ ...f.env, CASEOPS_MOBILE_PRIVACY_POLICY_SHA256: hash(raw) }, options), /PRIVACY_POLICY_JSON_REQUIRED/);
});
test('policy exact hash path symlink hardlink empty and oversized inputs fail closed', t => {
  const f = fixture(t); assert.throws(() => readPolicyBytes(f.file, 'b'.repeat(64)), /HASH_MISMATCH/);
  const alias = path.join(f.root, 'alias'); fs.symlinkSync(f.file, alias); assert.throws(() => readPolicyBytes(alias, hash(f.bytes)));
  fs.unlinkSync(alias); fs.linkSync(f.file, alias); assert.throws(() => readPolicyBytes(f.file, hash(f.bytes))); fs.unlinkSync(alias);
  for (const bytes of [Buffer.alloc(0), Buffer.alloc(16385)]) { fs.writeFileSync(f.file, bytes); assert.throws(() => readPolicyBytes(f.file, hash(bytes))); }
});
test('policy growth after admission consumes at most 16KiB plus one and closes the FD', t => {
  const f = fixture(t), realRead = fs.readSync, realOpen = fs.openSync; let fd, read = 0, grown = false;
  fs.openSync = (...args) => { const n = realOpen(...args); if (args[0] === f.file && fd === undefined) fd = n; return n; };
  fs.readSync = (...args) => { if (args[0] === fd && !grown) { grown = true; fs.appendFileSync(f.file, Buffer.alloc(65536)); } const n = realRead(...args); if (args[0] === fd) read += n; return n; };
  try { assert.throws(() => readPolicyBytes(f.file, hash(f.bytes)), /INPUT_CHANGED/); assert.equal(read, 16385); }
  finally { fs.openSync = realOpen; fs.readSync = realRead; }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('policy replacement between open and admission reads zero bytes and closes', t => {
  const f = fixture(t), realOpen = fs.openSync, realRead = fs.readSync; let fd, reads = 0;
  fs.openSync = (...args) => { const n = realOpen(...args); if (args[0] === f.file && fd === undefined) { fd = n; fs.renameSync(f.file, path.join(f.root, 'retained')); fs.writeFileSync(f.file, f.bytes); } return n; };
  fs.readSync = (...args) => { if (args[0] === fd) reads++; return realRead(...args); };
  try { assert.throws(() => readPolicyBytes(f.file, hash(f.bytes)), /OWNED_REGULAR_INPUT_REQUIRED/); assert.equal(reads, 0); }
  finally { fs.openSync = realOpen; fs.readSync = realRead; }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('policy final namespace rejects a moved parent symlink to the same held inode', t => {
  const f = fixture(t), realRead = fs.readSync; let fd, moved = false;
  fs.readSync = (...args) => { fd = args[0]; const n = realRead(...args); if (!moved) { moved = true; fs.renameSync(f.root, f.root + '-retained'); fs.symlinkSync(f.root + '-retained', f.root, process.platform === 'win32' ? 'junction' : 'dir'); } return n; };
  try { assert.throws(() => readPolicyBytes(f.file, hash(f.bytes)), /CANONICAL_NAMESPACE_REQUIRED/); }
  finally { fs.readSync = realRead; fs.unlinkSync(f.root); fs.renameSync(f.root + '-retained', f.root); }
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('policy native metadata uses exactly the admitted URL version digest on both platforms', t => {
  const f = fixture(t), p = readPrivacyPolicySettings(f.env, options);
  assert.deepEqual(projectIosPrivacyPolicy({ Existing: 'unchanged' }, p), { Existing: 'unchanged', CaseOpsPrivacyPolicyURL: p.url, CaseOpsPrivacyPolicyVersion: p.version, CaseOpsPrivacyPolicySHA256: p.sha256 });
  const manifest = { manifest: { application: [{ 'meta-data': [{ $: { 'android:name': 'other', 'android:value': 'keep' } }] }] } };
  projectAndroidPrivacyPolicy(manifest, p); const rows = manifest.manifest.application[0]['meta-data'];
  assert.equal(rows.length, 4); assert.deepEqual(rows.slice(1).map(x => x.$), ['URL', 'VERSION', 'SHA256'].map((suffix, i) => ({ 'android:name': 'ai.caseops.mobile.PRIVACY_POLICY_' + suffix, 'android:value': [p.url, p.version, p.sha256][i] })));
});
test('unconfigured QA native projection removes only policy-owned stale metadata', t => {
  const f = fixture(t), p = readPrivacyPolicySettings(f.env, options), info = projectIosPrivacyPolicy({ Existing: true }, p);
  assert.deepEqual(projectIosPrivacyPolicy(info, null), { Existing: true });
  const manifest = { manifest: { application: [{ 'meta-data': [{ $: { 'android:name': 'other', 'android:value': 'keep' } }] }] } }; projectAndroidPrivacyPolicy(manifest, p); projectAndroidPrivacyPolicy(manifest, null);
  assert.deepEqual(manifest.manifest.application[0]['meta-data'], [{ $: { 'android:name': 'other', 'android:value': 'keep' } }]);
});
test('invalid privacy projection mutates neither existing native document', () => {
  const info = { Existing: true }, manifest = { manifest: { application: [{}] } };
  assert.throws(() => projectIosPrivacyPolicy(info, { url: descriptor.url, version: 1, sha256: 'a'.repeat(64) })); assert.deepEqual(info, { Existing: true });
  assert.throws(() => projectAndroidPrivacyPolicy(manifest, { ...descriptor })); assert.deepEqual(manifest, { manifest: { application: [{}] } });
});
test('actual Expo plugin registers configured and unconfigured mods with explicit options', () => {
  for (const options of [{ configured: false }, { configured: true, policy: { url: descriptor.url, version: descriptor.version, sha256: 'a'.repeat(64) } }]) {
    const config = withPrivacyPolicy({ name: 'Synthetic policy test', slug: 'synthetic-policy-test' }, options);
    assert.equal(typeof config.mods.ios.infoPlist, 'function'); assert.equal(typeof config.mods.android.manifest, 'function');
  }
  assert.throws(() => withPrivacyPolicy({ name: 'Synthetic', slug: 'synthetic' }, {}), /PLUGIN_OPTIONS_REQUIRED/);
});
