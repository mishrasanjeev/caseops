import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { packagingPlan, prepare } from './prepare-store-packaging.mjs';
import { sourceSnapshot } from './source-snapshot.mjs';
const require = createRequire(import.meta.url);
const { readHashed, readJson, validateStoreBuild, readStoreBuildSettings, reserveBuildNumbers } = require('../../apps/mobile/plugins/store-build.cjs');
const { readNativeLinkConfig } = require('../../apps/web/lib/native-link-config.cjs');
const repo = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
const digest = value => createHash('sha256').update(value).digest('hex');
function appConfig(extra = {}) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(CASEOPS_|EXPO_PUBLIC_|NODE_ENV$|__EXPO_CONFIG_MODE$|EX_UPDATES_NATIVE_DEBUG$|SKIP_BUNDLING$)/.test(key)));
  // Resolve through this checkout's already installed mobile graph.
  delete env.NODE_PATH;
  const script = "import {createRequire} from 'node:module'; import {pathToFileURL} from 'node:url'; const f=process.cwd()+'/apps/mobile/app.config.ts'; globalThis.require=createRequire(f); const {default:c}=await import(pathToFileURL(f)); console.log(JSON.stringify({version:c.version,ios:c.ios,android:c.android,extra:c.extra}));";
  return spawnSync(process.execPath, ['--experimental-strip-types', '--no-experimental-transform-types', '--input-type=module', '-e', script], { cwd: repo, env: { ...env, ...extra }, encoding: 'utf8', timeout: 5000 });
}
function fixture(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-store-contract-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  function save(name, value) { const data = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value)); const file = path.join(root, name); fs.writeFileSync(file, data, { mode: 0o600 }); return { path: file, sha256: digest(data) }; }
  // Synthetic fixture only; neither identifier nor certificate is publisher proof.
  const config = { schemaVersion: 1, kind: 'caseops-native-links', syntheticDataOnly: true,
    redirectUri: 'https://auth.contract-fixture.org/native/oauth/callback',
    ios: { bundleIdentifier: 'org.contract.fixtureapp', applicationIdentifierPrefix: 'ABC123DE45' },
    android: { packageName: 'org.contract.fixtureapp', signingCertificateSha256: [digest('synthetic-app-signing-certificate')] } };
  const linkRef = save('links.json', config);
  const links = readNativeLinkConfig({ CASEOPS_NATIVE_LINK_CONFIG_FILE: linkRef.path, CASEOPS_NATIVE_LINK_CONFIG_SHA256: linkRef.sha256 }, { allowSynthetic: true });
  const identities = { iosBundleIdentifier: config.ios.bundleIdentifier, androidPackageName: config.android.packageName };
  const baseline = { schemaVersion: 1, kind: 'caseops-declared-store-build-baseline', syntheticDataOnly: true, identities,
    marketingVersion: '0.9.0', iosBuildNumber: '7', androidVersionCode: 9, scope: 'operator-declared-not-store-verified' };
  const baselineRef = save('baseline.json', baseline);
  const build = { schemaVersion: 1, kind: 'caseops-store-build', syntheticDataOnly: true, nativeLinkConfigSha256: links.sha256,
    identities, version: '1.0.0', iosBuildNumber: '8', androidVersionCode: 10, baseline: baselineRef };
  const buildRef = save('build.json', build);
  const settings = readStoreBuildSettings({ CASEOPS_STORE_BUILD_FILE: buildRef.path, CASEOPS_STORE_BUILD_SHA256: buildRef.sha256 }, links, { allowSynthetic: true });
  const source = sourceSnapshot(repo);
  const request = { schemaVersion: 1, kind: 'caseops-store-packaging-request', preparedOnly: true, syntheticDataOnly: true, platform: 'ios',
    source: { sourceSha: source.sourceSha, sourceFingerprint: source.sourceFingerprint, inputFileCount: source.inputFileCount }, nativeLinks: linkRef, storeBuild: buildRef,
    apiOrigin: 'https://api.contract-fixture.org', webOrigin: 'https://auth.contract-fixture.org',
    signing: { teamId: 'TEAM123456', applicationIdentifierPrefix: config.ios.applicationIdentifierPrefix, certificateSha1: digest('certificate').slice(0, 40),
      certificateSha256: digest('certificate'), provisioningProfileUuid: '019b85b0-50bd-4c77-aa22-3da2e5009fe1', provisioningProfileEvidence: save('profile.fixture', 'PUBLIC SYNTHETIC PROFILE'), developerDirectory: '/Applications/Contract-Xcode.app/Contents/Developer', podfileLockEvidence: save('Podfile.lock', 'SYNTHETIC LOCK') } };
  const options = { root: repo, output: path.join(root, 'prepared'), links, settings, source, allowSynthetic: true };
  const android = () => ({ ...structuredClone(request), platform: 'android', signing: { uploadKeystoreEvidence: save('keystore.fixture', 'PUBLIC SYNTHETIC KEYSTORE'), uploadKeyAlias: 'contract-upload', uploadCertificateSha256: digest('synthetic-upload-certificate'),
    appSigningCertificateSha256: config.android.signingCertificateSha256[0], androidSdkRoot: '/owned/android-sdk', javaHome: '/owned/java21', java17Home: '/owned/java17', gradleUserHome: '/owned/gradle-cache' } });
  return { root, save, config, linkRef, links, baseline, build, buildRef, settings, request, options, android };
}
test('version admission is explicitly relative to the exact declared baseline, never store verification', t => {
  const f = fixture(t); const actual = validateStoreBuild(f.build, f.baseline, f.links, { allowSynthetic: true });
  assert.deepEqual(actual, { version: '1.0.0', iosBuildNumber: '8', androidVersionCode: 10, baselineScope: 'operator-declared-not-store-verified', independentlyVerifiedStoreMaximum: false });
});
for (const [field, value] of [['iosBuildNumber', '7'], ['androidVersionCode', 9], ['iosBuildNumber', '0'], ['androidVersionCode', 2100000001], ['version', '0.8.9']]) {
  test('rejects nonmonotonic or invalid version field ' + field + ':' + value, t => {
    const f = fixture(t); assert.throws(() => validateStoreBuild({ ...f.build, [field]: value }, f.baseline, f.links, { allowSynthetic: true }));
  });
}
test('all missing/extra fields, hash drift, wrong identity and synthetic production inputs fail closed', t => {
  const f = fixture(t);
  const missing = { ...f.build }; delete missing.baseline;
  for (const b of [missing, { ...f.build, password: 'synthetic-secret' }, { ...f.build, nativeLinkConfigSha256: '0'.repeat(64) }, { ...f.build, identities: { ...f.build.identities, androidPackageName: 'org.other.app' } }]) assert.throws(() => validateStoreBuild(b, f.baseline, f.links, { allowSynthetic: true }));
  assert.throws(() => validateStoreBuild(f.build, f.baseline, f.links), /REAL_STORE_INPUTS_REQUIRED/);
});
test('same-FD reads reject exact-hash tamper, symlink and malformed JSON without leaking contents', t => {
  const f = fixture(t); const ref = f.save('content.json', 'PRIVATE_SYNTHETIC_MARKER');
  assert.throws(() => readJson(ref), error => error.message === 'STORE_INPUT_JSON_REQUIRED');
  fs.writeFileSync(ref.path, 'CHANGED_SYNTHETIC_MARKER'); assert.throws(() => readHashed(ref), /HASH_MISMATCH/);
  const symlink = path.join(f.root, 'link.json'); fs.symlinkSync(f.linkRef.path, symlink);
  assert.throws(() => readHashed({ path: symlink, sha256: f.linkRef.sha256 }));
  assert.throws(() => readHashed({ path: f.root + '/sub/../links.json', sha256: f.linkRef.sha256 }), /EXACT_STORE_REFERENCE_REQUIRED/);
});
test('changed baseline bytes and a false verified-store scope are refused', t => {
  const f = fixture(t); fs.writeFileSync(f.build.baseline.path, JSON.stringify({ ...f.baseline, iosBuildNumber: '1' }));
  assert.throws(() => readStoreBuildSettings({ CASEOPS_STORE_BUILD_FILE: f.buildRef.path, CASEOPS_STORE_BUILD_SHA256: f.buildRef.sha256 }, f.links, { allowSynthetic: true }), /HASH_MISMATCH/);
  assert.throws(() => validateStoreBuild(f.build, { ...f.baseline, scope: 'store-verified' }, f.links, { allowSynthetic: true }), /DECLARED_BASELINE_REQUIRED/);
});
test('exclusive number reservation survives replay and identity-key ordering', t => {
  const f = fixture(t); const dir = path.join(f.root, 'reservations'); fs.mkdirSync(dir, { mode: 0o700 });
  reserveBuildNumbers(dir, f.build, digest('request1'));
  assert.equal(fs.readdirSync(dir).length, 2);
  assert.throws(() => reserveBuildNumbers(dir, { ...f.build, identities: { androidPackageName: f.build.identities.androidPackageName, iosBundleIdentifier: f.build.identities.iosBundleIdentifier } }, digest('request2')), /EEXIST/);
  assert.equal(fs.readdirSync(dir).length, 2);
  assert.throws(() => reserveBuildNumbers(dir, { ...f.build, iosBuildNumber: '../bad' }, digest('request3')), /IOS_BUILD_NUMBER/);
});
test('each platform reservation survives changes to the other platform identity', t => {
  const f = fixture(t);
  for (const other of ['androidPackageName', 'iosBundleIdentifier']) {
    const dir = path.join(f.root, other); fs.mkdirSync(dir, { mode: 0o700 });
    reserveBuildNumbers(dir, f.build, digest('first'));
    const changed = { ...f.build, identities: { ...f.build.identities, [other]: 'org.changed.application' } };
    assert.throws(() => reserveBuildNumbers(dir, changed, digest('second')), /EEXIST/);
    // A partially reserved new iOS counter is retained when Android collides.
    assert.equal(fs.readdirSync(dir).length, other === 'iosBundleIdentifier' ? 3 : 2);
  }
});
test('Xcode recipe archives actual device SDK and exports manually without upload/provisioning/version mutation', t => {
  const f = fixture(t); const plan = packagingPlan(f.request, f.options);
  assert.equal(plan.executionEnabled, false); assert.equal(plan.readyForBuild, false);
  assert.notEqual(f.request.signing.teamId, f.request.signing.applicationIdentifierPrefix);
  const archive = plan.commands.find(c => c.args.includes('archive'));
  assert.ok(archive.args.includes('iphoneos')); assert.ok(archive.args.includes('generic/platform=iOS'));
  assert.ok(archive.args.includes('CURRENT_PROJECT_VERSION=8')); assert.ok(archive.args.includes('CODE_SIGN_STYLE=Manual'));
  assert.ok(plan.commands.some(c => c.args.includes('-exportArchive')));
  assert.doesNotMatch(JSON.stringify(plan.commands), /allowProvisioning|upload|iphonesimulator|CODE_SIGNING_ALLOWED=NO/);
  assert.match(plan.outputs['ExportOptions.plist'], /<key>destination<\/key><string>export<\/string>/);
  assert.match(plan.outputs['ExportOptions.plist'], /<key>manageAppVersionAndBuildNumber<\/key><false\/>/);
});
test('Android AAB recipe binds actual app-signing cert separately from upload cert and never puts passwords in argv', t => {
  const f = fixture(t); const request = f.android(); const plan = packagingPlan(request, f.options);
  assert.notEqual(request.signing.uploadCertificateSha256, request.signing.appSigningCertificateSha256);
  assert.deepEqual(plan.requiredSecretEnvironmentNames, ['CASEOPS_UPLOAD_STORE_PASSWORD', 'CASEOPS_UPLOAD_KEY_PASSWORD']);
  const gradle = plan.commands.at(-1);
  assert.equal(gradle.executable, './gradlew'); assert.equal(gradle.args[0], ':app:bundleRelease');
  for (const flag of ['--offline', '--no-daemon', '-Pandroid.builder.sdkDownload=false', '-Dorg.gradle.java.installations.auto-download=false']) assert.ok(gradle.args.includes(flag));
  assert.doesNotMatch(JSON.stringify(gradle), /storePassword|keyPassword|generate|upload|assemble/);
  assert.match(plan.outputs['store-signing.init.gradle'], /finalizeDsl/);
  assert.match(plan.outputs['store-signing.init.gradle'], /release.signingConfig = signing/);
});
test('wrong prefix/app-signing certificate/unknown signing fields refuse before any compiler command', t => {
  const f = fixture(t);
  assert.throws(() => packagingPlan({ ...f.request, signing: { ...f.request.signing, applicationIdentifierPrefix: f.request.signing.teamId } }, f.options), /PREFIX_MISMATCH/);
  const a = f.android(); a.signing.appSigningCertificateSha256 = digest('wrong'); assert.throws(() => packagingPlan(a, f.options), /LINK_CERTIFICATE_MISMATCH/);
  assert.throws(() => packagingPlan({ ...f.request, signing: { ...f.request.signing, password: 'not-allowed' } }, f.options), /DISTRIBUTION_INPUTS_REQUIRED/);
});
test('wrong source, API/TLS, callback origin, production dirty tree and mixed build ref refuse', t => {
  const f = fixture(t);
  for (const r of [{ ...f.request, source: { ...f.request.source, inputFileCount: 1 } }, { ...f.request, apiOrigin: 'http://api.contract-fixture.org' }, { ...f.request, webOrigin: 'https://other.contract-fixture.org' }, { ...f.request, storeBuild: { ...f.buildRef, sha256: '0'.repeat(64) } }]) assert.throws(() => packagingPlan(r, f.options));
  assert.throws(() => packagingPlan(f.request, { ...f.options, allowSynthetic: false }), /SYNTHETIC_STORE_RECIPE_FORBIDDEN/);
});
test('reserved example API origins cannot be represented as final production endpoints', t => {
  const f = fixture(t);
  for (const host of ['example.com', 'api.example.net', 'www.example.org', 'localhost', 'native.invalid']) {
    assert.throws(() => packagingPlan({ ...f.request, apiOrigin: 'https://' + host }, f.options), /FINAL_HTTPS_ORIGIN_REQUIRED/);
  }
});
test('real preparation writes only evidence/projections, never reads signing material or invokes native tools', t => {
  const f = fixture(t); const request = f.android();
  // Deliberately nonexistent signing inputs: planning cannot imply possession/validation.
  request.signing.uploadKeystoreEvidence.path = path.join(f.root, 'not-present.keystore');
  const requestRef = f.save('request.json', request);
  const result = prepare(requestRef, f.options.output, { root: repo, allowSynthetic: true });
  assert.equal(result.readyForBuild, false);
  const plan = JSON.parse(fs.readFileSync(result.path)); assert.equal(plan.executionEnabled, false);
  assert.ok(plan.requiredBeforeExecution.some(s => s.includes('actual upload-keystore certificate')));
  assert.equal(fs.existsSync(request.signing.uploadKeystoreEvidence.path), false);
  assert.throws(() => prepare(requestRef, f.options.output, { root: repo, allowSynthetic: true }), /NEW_OUTPUT_DIRECTORY_REQUIRED/);
});
test('CLI run/unknown modes refuse before inputs and emit only a fixed secret-safe diagnostic', t => {
  const r = spawnSync(process.execPath, ['scripts/mobile/prepare-store-packaging.mjs', '--run', 'PRIVATE_SYNTHETIC_MARKER'], { cwd: repo, encoding: 'utf8', timeout: 5000 });
  assert.equal(r.status, 1); assert.equal(r.stdout, ''); assert.equal(r.stderr.trim(), 'STORE_PACKAGING_PREPARATION_REFUSED');
});
test('actual TypeScript config keeps local QA version defaults and rejects production store metadata mixing', t => {
  const f = fixture(t);
  const env = { NODE_ENV: 'production', CASEOPS_MOBILE_BUILD_PROFILE: 'ios-simulator-acceptance', CASEOPS_MOBILE_AUTOMATED_TEST: '1',
    CASEOPS_MOBILE_RELEASE_SHA: f.options.source.sourceSha, EXPO_PUBLIC_API_ORIGIN: 'https://127.0.0.1:8443', EXPO_PUBLIC_WEB_ORIGIN: 'https://127.0.0.1:3443' };
  const run = appConfig(env); assert.equal(run.status, 0, run.stderr); const config = JSON.parse(run.stdout);
  assert.equal(config.version, '0.1.0'); assert.equal(config.ios.buildNumber, undefined); assert.equal(config.android.versionCode, undefined);
  assert.equal(config.ios.deploymentTarget, undefined); assert.equal(config.ios.bundleIdentifier, 'ai.caseops.mobile.dev.simulatoracceptance');
  assert.equal(config.extra.nativeLinkPolicy.mode, 'local');
  const refused = appConfig({ ...env, CASEOPS_STORE_BUILD_FILE: f.buildRef.path, CASEOPS_STORE_BUILD_SHA256: f.buildRef.sha256 });
  assert.notEqual(refused.status, 0); assert.match(refused.stderr, /ACCEPTANCE_AND_STORE_BUILD_CONFIG_CANNOT_MIX/);
  const orphan = appConfig({ CASEOPS_STORE_BUILD_FILE: f.buildRef.path, CASEOPS_STORE_BUILD_SHA256: f.buildRef.sha256 });
  assert.notEqual(orphan.status, 0); assert.match(orphan.stderr, /STORE_BUILD_REQUIRES_NATIVE_LINK_CONFIG/);
});
test('actual production TypeScript config refuses absent numbering and projects exact declared values when complete', t => {
  const f = fixture(t);
  // Structural non-synthetic flag is exercised only in this offline unit; no publisher ownership is claimed.
  const config = { ...f.config, syntheticDataOnly: false }; const lr = f.save('structural-links.json', config);
  const baseline = { ...f.baseline, syntheticDataOnly: false }; const previous = f.save('structural-baseline.json', baseline);
  const br = f.save('structural-build.json', { ...f.build, syntheticDataOnly: false, nativeLinkConfigSha256: lr.sha256, baseline: previous });
  const privacy = f.save('structural-policy.json', { schemaVersion: 1, kind: 'caseops-mobile-privacy-policy', nativeLinkConfigSha256: lr.sha256,
    url: 'https://auth.contract-fixture.org/privacy-policy', version: 'synthetic-policy-v1' });
  const env = { NODE_ENV: 'production', CASEOPS_NATIVE_LINK_CONFIG_FILE: lr.path, CASEOPS_NATIVE_LINK_CONFIG_SHA256: lr.sha256,
    EXPO_PUBLIC_WEB_ORIGIN: 'https://auth.contract-fixture.org', CASEOPS_MOBILE_PRIVACY_POLICY_FILE: privacy.path, CASEOPS_MOBILE_PRIVACY_POLICY_SHA256: privacy.sha256 };
  const absent = appConfig(env); assert.notEqual(absent.status, 0); assert.match(absent.stderr, /EXACT_STORE_REFERENCE_REQUIRED/);
  const run = appConfig({ ...env, CASEOPS_STORE_BUILD_FILE: br.path, CASEOPS_STORE_BUILD_SHA256: br.sha256 });
  assert.equal(run.status, 0, run.stderr); const projected = JSON.parse(run.stdout);
  assert.equal(projected.version, '1.0.0'); assert.equal(projected.ios.buildNumber, '8'); assert.equal(projected.android.versionCode, 10);
  assert.equal(projected.ios.deploymentTarget, '17.4'); assert.equal(projected.extra.nativeLinkPolicy.mode, 'https');
  assert.deepEqual(projected.extra.privacyPolicy, { url: 'https://auth.contract-fixture.org/privacy-policy', version: 'synthetic-policy-v1', sha256: privacy.sha256 });
});
test('growth after initial fstat cannot cause more than limit-plus-one descriptor bytes to be consumed', t => {
  const f = fixture(t); const ref = f.save('growing.json', '{}');
  const originals = { readFileSync: fs.readFileSync, readSync: fs.readSync, closeSync: fs.closeSync };
  let grew = false, readFileBytes = 0, readSyncBytes = 0, closed;
  const grow = () => { if (!grew) { grew = true; fs.appendFileSync(ref.path, Buffer.alloc(8192)); } };
  fs.readFileSync = function (fd, ...rest) { if (typeof fd === 'number') { grow(); const bytes = originals.readFileSync.call(this, fd, ...rest); readFileBytes += bytes.length; return bytes; } return originals.readFileSync.call(this, fd, ...rest); };
  fs.readSync = function (fd, buffer, ...rest) { grow(); const count = originals.readSync.call(this, fd, buffer, ...rest); readSyncBytes += count; return count; };
  fs.closeSync = function (fd) { closed = fd; return originals.closeSync.call(this, fd); };
  try { assert.throws(() => readHashed(ref, 64)); }
  finally { Object.assign(fs, originals); }
  // readFileSync may itself call exported readSync; do not double-charge that observation.
  assert.ok(Math.max(readFileBytes, readSyncBytes) <= 65, 'UNBOUNDED_DESCRIPTOR_READ:' + Math.max(readFileBytes, readSyncBytes));
  assert.equal(grew, true); assert.equal(typeof closed, 'number');
  assert.throws(() => fs.fstatSync(closed), /EBADF/);
});
test('path replacement during descriptor read is refused and original descriptor is always closed', t => {
  const f = fixture(t); const ref = f.save('replaced.json', '{}');
  const originals = { readFileSync: fs.readFileSync, readSync: fs.readSync, closeSync: fs.closeSync };
  let replaced = false, closed;
  const replace = () => { if (!replaced) { replaced = true; fs.renameSync(ref.path, ref.path + '.old'); fs.writeFileSync(ref.path, '{}'); } };
  fs.readFileSync = function (fd, ...rest) { if (typeof fd === 'number') replace(); return originals.readFileSync.call(this, fd, ...rest); };
  fs.readSync = function (...args) { replace(); return originals.readSync.apply(this, args); };
  fs.closeSync = function (fd) { closed = fd; return originals.closeSync.call(this, fd); };
  try { assert.throws(() => readHashed(ref), /INPUT_CHANGED/); }
  finally { Object.assign(fs, originals); }
  assert.equal(replaced, true); assert.equal(typeof closed, 'number'); assert.throws(() => fs.fstatSync(closed), /EBADF/);
});
test('hard-linked and foreign-owner descriptor inputs refuse before reading and close on rejection', t => {
  const f = fixture(t); const ref = f.save('linked.json', '{}');
  fs.linkSync(ref.path, ref.path + '.second');
  assert.throws(() => readHashed(ref), /REGULAR_CANONICAL_STORE_INPUT_REQUIRED/);
  fs.unlinkSync(ref.path + '.second');
  if (process.platform !== 'win32') {
    const original = fs.fstatSync; let closed;
    const close = fs.closeSync;
    fs.fstatSync = function (...args) { const stat = original.apply(this, args); return Object.assign(Object.create(stat), { uid: stat.uid + 1n }); };
    fs.closeSync = function (fd) { closed = fd; return close.call(this, fd); };
    try { assert.throws(() => readHashed(ref), /REGULAR_CANONICAL_STORE_INPUT_REQUIRED/); }
    finally { fs.fstatSync = original; fs.closeSync = close; }
    assert.throws(() => fs.fstatSync(closed), /EBADF/);
  }
});

// Appendable source: uses the existing test/assert/fs/os/path/require/repo imports.
const { readNativeLinkConfig: readPublicNativeLinks } = require(path.join(repo, 'apps/web/lib/native-link-config.cjs'));
function publicReaderFixture(t, bytes) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-public-link-reader-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const config = { schemaVersion: 1, kind: 'caseops-native-links', syntheticDataOnly: true,
    redirectUri: 'https://n.invalid/native/oauth/callback', ios: { bundleIdentifier: 'a.b.c', applicationIdentifierPrefix: 'X9Y8Z7W6V5' },
    android: { packageName: 'a.b.c', signingCertificateSha256: ['a'.repeat(64)] } };
  const data = bytes || Buffer.from(JSON.stringify(config).padEnd(390, ' '));
  const file = path.join(dir, 'config.json'); fs.writeFileSync(file, data, { mode: 0o444 });
  return { dir, file, data, env: { CASEOPS_NATIVE_LINK_CONFIG_FILE: file, CASEOPS_NATIVE_LINK_CONFIG_SHA256: createHash('sha256').update(data).digest('hex') } };
}
function withPublicReaderHooks(fixture, action, invoke, mutateStat) {
  const originals = Object.fromEntries(['openSync', 'readSync', 'readFileSync', 'fstatSync', 'lstatSync', 'closeSync'].map(key => [key, fs[key]]));
  const state = { fd: undefined, triggered: false, readSyncBytes: 0, readFileBytes: 0, closes: 0 };
  const trigger = () => { if (!state.triggered) { state.triggered = true; action?.(); } };
  fs.openSync = function (name, flags, ...rest) {
    const fd = originals.openSync.call(this, name, flags, ...rest);
    if (name === fixture.file && typeof flags === 'number' && !(flags & (fs.constants.O_WRONLY | fs.constants.O_RDWR))) state.fd = fd;
    return fd;
  };
  fs.readSync = function (fd, ...rest) { if (fd === state.fd) trigger(); const n = originals.readSync.call(this, fd, ...rest); if (fd === state.fd) state.readSyncBytes += n; return n; };
  fs.readFileSync = function (fd, ...rest) { if (fd === state.fd) trigger(); const b = originals.readFileSync.call(this, fd, ...rest); if (fd === state.fd) state.readFileBytes += b.length; return b; };
  fs.fstatSync = function (fd, ...rest) { const s = originals.fstatSync.call(this, fd, ...rest); return fd === state.fd && mutateStat ? mutateStat(s, state, 'opened') : s; };
  fs.lstatSync = function (name, ...rest) { const s = originals.lstatSync.call(this, name, ...rest); return name === fixture.file && mutateStat ? mutateStat(s, state, 'named') : s; };
  fs.closeSync = function (fd) { if (fd === state.fd) state.closes++; return originals.closeSync.call(this, fd); };
  try { invoke(state); }
  finally { Object.assign(fs, originals); }
  assert.equal(state.closes, 1, 'PUBLIC_READER_DESCRIPTOR_MUST_CLOSE_ONCE');
  assert.throws(() => fs.fstatSync(state.fd), /EBADF/);
  return state;
}

test('public native link config growth after390B stat consumes at most16KiB plus one detection byte', t => {
  const f = publicReaderFixture(t); assert.equal(f.data.length, 390);
  fs.chmodSync(f.file, 0o600);
  const state = withPublicReaderHooks(f, () => fs.appendFileSync(f.file, Buffer.alloc(131072)), () => {
    assert.throws(() => readPublicNativeLinks(f.env, { allowSynthetic: true }));
  });
  const consumed = Math.max(state.readSyncBytes, state.readFileBytes); // avoid double-counting readFileSync's internal readSync.
  assert.ok(consumed <= 16385, 'PUBLIC_CONFIG_UNBOUNDED_READ:' + consumed);
  assert.equal(state.triggered, true);
});
test('public native link config rejects regular or symlink pathname replacement while retaining the opened FD', t => {
  for (const symlink of [false, true]) {
    const f = publicReaderFixture(t);
    withPublicReaderHooks(f, () => {
      fs.renameSync(f.file, f.file + '.old');
      if (symlink) fs.symlinkSync(f.file + '.old', f.file); else fs.writeFileSync(f.file, f.data);
    }, () => assert.throws(() => readPublicNativeLinks(f.env, { allowSynthetic: true }), /NATIVE_LINK_CONFIG_CHANGED/));
  }
});
test('public native link config UID and link-count drift reject even with unchanged inode size and timestamps', t => {
  for (const field of ['uid', 'nlink']) {
    const f = publicReaderFixture(t);
    withPublicReaderHooks(f, () => {}, () => assert.throws(() => readPublicNativeLinks(f.env, { allowSynthetic: true }), /NATIVE_LINK_CONFIG_CHANGED/),
      (s, state) => state.triggered ? Object.assign(Object.create(s), { [field]: s[field] + 1n }) : s);
  }
});
test('public native link config preserves an original descriptor-read error and closes exactly once', t => {
  const f = publicReaderFixture(t), error = new Error('SYNTHETIC_PUBLIC_CONFIG_READ_FAILURE');
  withPublicReaderHooks(f, () => { throw error; }, () => assert.throws(() => readPublicNativeLinks(f.env, { allowSynthetic: true }), actual => actual === error));
});
test('stable public deployment metadata admits read-only files without imposing current UID or single-link private-key policy', t => {
  const f = publicReaderFixture(t);
  const state = withPublicReaderHooks(f, () => {}, () => {
    const loaded = readPublicNativeLinks(f.env, { allowSynthetic: true }); assert.deepEqual(loaded.bytes, f.data);
  }, s => Object.assign(Object.create(s), { uid: 0n, nlink: 2n }));
  assert.equal(state.triggered, true); // simulated stable deployment UID/link metadata; not actual root/Windows execution proof.
});
test('public native link config closes on hash and UTF8 failures with fixed nonreflecting JSON error', t => {
  for (const kind of ['hash', 'utf8']) {
    const f = publicReaderFixture(t, kind === 'utf8' ? Buffer.from([0xff, 0xfe]) : undefined);
    if (kind === 'hash') f.env.CASEOPS_NATIVE_LINK_CONFIG_SHA256 = '0'.repeat(64);
    withPublicReaderHooks(f, () => {}, () => assert.throws(() => readPublicNativeLinks(f.env, { allowSynthetic: true }),
      error => error.message === (kind === 'hash' ? 'NATIVE_LINK_CONFIG_HASH_MISMATCH' : 'NATIVE_LINK_CONFIG_JSON_REQUIRED')));
  }
});
test('store config rejects owner, mode and link-count drift even if size and timestamps stay equal', t => {
  const f = fixture(t);
  for (const field of ['uid', 'gid', 'mode', 'nlink']) {
    const ref = f.save('drift-' + field + '.json', '{}');
    withPublicReaderHooks({ file: ref.path }, () => {}, () => assert.throws(() => readHashed(ref), /STORE_INPUT_CHANGED/),
      (s, state) => state.triggered ? Object.assign(Object.create(s), { [field]: s[field] + 1n }) : s);
  }
});
