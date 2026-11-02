import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { validateAndroidNativeProof } from '../../apps/mobile/e2e/android-native-proof.mjs';
import { validateBuildReceipt } from '../../apps/mobile/e2e/fixture-contract.mjs';

const hash = (value) => createHash('sha256').update(value).digest('hex');
const APP = 'ai.caseops.mobile.dev.localacceptance';
const SERIAL = 'emulator-5580';
// Independent producer inventory: changing the consumer list cannot drop proof.
const REPORTS = ['apk-badging.log', 'apk-signing.log', 'apk-abi.json',
  'generated-android-inputs.json', 'java21.log', 'java17.log'];
const INPUTS = ['build.gradle', 'settings.gradle', 'gradle.properties', 'app/build.gradle',
  'gradle/wrapper/gradle-wrapper.properties'];
// Captured with pinned SDK37/apksigner0.9 from Mozilla's official158.0.2 ARM64
// APK (SHA25646a588b9f33c261e8cda9549426fc0118fde517cb87087633c11000d3e8099d5).
// These are public certificate fingerprints, never a signing/private key.
const SDK37_REPORT = `Verifies
Verified using v1 scheme (JAR signing): false
Verified using v2 scheme (APK Signature Scheme v2): true
Verified using v3 scheme (APK Signature Scheme v3): false
Verified using v3.1 scheme (APK Signature Scheme v3.1): false
Verified using v3.2 scheme (APK Signature Scheme v3.2): false
Verified using v4 scheme (APK Signature Scheme v4): false
Verified for SourceStamp: false
Number of signers: 1
V2 Signer: certificate DN: CN=Release Engineering, OU=Release Engineering, O=Mozilla Corporation, L=Mountain View, ST=California, C=US
V2 Signer: certificate SHA-256 digest: a78b62a5165b4494b2fead9e76a280d22d937fee6251aece599446b2ea319b04
V2 Signer: certificate SHA-1 digest: 920f4876a6a57b4a6a2f4ccaf65f7d29ce26ff2c
V2 Signer: certificate MD5 digest: b1e1bcee2733025ece9456e419a814a3
V2 Signer: key algorithm: RSA
V2 Signer: key size (bits): 2048
V2 Signer: public key SHA-256 digest: aac36655156876c894b09d512e74a0c7bb3301a1c871f200820d099ef1520ae1
V2 Signer: public key SHA-1 digest: 3d4fff78408b159058428bff8d07589a4c18aa8b
V2 Signer: public key MD5 digest: fe669db38a1eae305b8573293e5c35d8
`;
const MOZILLA_CERT = 'a78b62a5165b4494b2fead9e76a280d22d937fee6251aece599446b2ea319b04';

function fixture(t) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-android-native-proof-')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const write = (name, value) => {
    const data = typeof value === 'string' ? value : JSON.stringify(value);
    writeFileSync(path.join(root, name), data);
    return { path: path.join(root, name), sha256: hash(data) };
  };
  const inputs = INPUTS.map(relativePath => {
    const data = `synthetic generated build input: ${relativePath}\n`;
    write(relativePath.replaceAll('/', '-'), data);
    return { relativePath, sha256: hash(data), sizeBytes: Buffer.byteLength(data) };
  });
  const contents = [
    `package: name='${APP}' versionCode='1' versionName='0.1.0' platformBuildVersionName='17'\nnative-code: 'arm64-v8a'\n`,
    `Verifies\nVerified using v1 scheme (JAR signing): false\nVerified using v2 scheme (APK Signature Scheme v2): true\nNumber of signers: 1\nSigner #1 certificate SHA-256 digest: ${'3'.repeat(64)}\n`,
    { schemaVersion: 1, abis: ['arm64-v8a'], nativeLibraryCount: 4, elfClass: 64, elfMachine: 183 },
    { schemaVersion: 1, files: inputs },
    'OpenJDK Runtime Environment Temurin-21.0.12.1+1 (synthetic unit fixture)\n',
    'OpenJDK Runtime Environment Temurin-17.0.20.1+1 (synthetic unit fixture)\n',
  ];
  const actualHash = hash('synthetic APK identity; no native execution is claimed by this test');
  const proof = { schemaVersion: 1, kind: 'android-local-arm64-signature-proof', appId: APP,
    artifactSha256: actualHash, versionCode: 1, versionName: '0.1.0', architecture: 'arm64-v8a',
    signatureVerified: true, signatureSchemeV2: true, certificateSha256: '3'.repeat(64), intendedDeviceSerial: SERIAL,
    evidence: REPORTS.map((name, index) => write(name, contents[index])),
    distributionSigning: false, nativeExecution: 'not-run-by-build-wrapper' };
  const receipt = { platform: 'android', profile: 'android-local-acceptance', appId: APP, binaryHash: actualHash,
    androidSecurity: { kind: 'compiled-android-acceptance-security', apkSha256: actualHash } };
  const save = () => { receipt.androidSecurity.nativeArtifactEvidence = write('android-native-proof.json', proof); };
  save();
  return { root, write, proof, receipt, actualHash, save,
    target: { appId: APP, udid: SERIAL },
    check() { return validateAndroidNativeProof(this.target, receipt, actualHash); },
    report(name, value) {
      const index = REPORTS.indexOf(name); assert.ok(index >= 0);
      proof.evidence[index] = write(name, value); save();
    } };
}

test('historical receipts without the optional extension remain valid and gain no ARM64/signature claim', () => {
  for (const receipt of [{}, { androidSecurity: null }, { androidSecurity: { kind: 'historical-windows' } }]) {
    const before = structuredClone(receipt);
    assert.equal(validateAndroidNativeProof({}, receipt, undefined), null);
    assert.deepEqual(receipt, before);
  }
});

test('all exact producer reports and copied inputs bind one APK, signer and selected serial', (t) => {
  const f = fixture(t), result = f.check();
  assert.equal(result.appId, APP); assert.equal(result.artifactSha256, f.actualHash);
  assert.equal(result.intendedDeviceSerial, SERIAL); assert.equal(result.certificateSha256, '3'.repeat(64));
  assert.equal(result.signatureVerified, true); assert.equal(result.signatureSchemeV2, true);
  assert.equal(result.distributionSigning, false); assert.equal(result.nativeExecution, 'not-run-by-build-wrapper');
  assert.deepEqual(result.evidence.map(item => path.basename(item.path)), REPORTS);
});

test('captured official Firefox SDK37 single V2 Signer report binds the exact reviewed public certificate', (t) => {
  assert.equal(hash(SDK37_REPORT), 'f5fc366fe25fab7fe128592e8ae2acd0287095f9ae05a0558681fb0332a88253');
  const f = fixture(t); f.proof.certificateSha256 = MOZILLA_CERT; f.report('apk-signing.log', SDK37_REPORT);
  assert.equal(f.check().certificateSha256, MOZILLA_CERT);
});

test('SDK37 V1-only, duplicate and mixed signer labels cannot claim one verified V2 identity', (t) => {
  const line = `V2 Signer: certificate SHA-256 digest: ${MOZILLA_CERT}\n`;
  for (const text of [SDK37_REPORT.replace('v2): true', 'v2): false'),
    SDK37_REPORT.replaceAll('V2 Signer:', 'V1 Signer:'), SDK37_REPORT + line,
    SDK37_REPORT + `Signer #1 certificate SHA-256 digest: ${MOZILLA_CERT}\n`,
    SDK37_REPORT + `V2 Signer: certificate SHA-256 digest: ${'4'.repeat(64)}\n`,
    SDK37_REPORT + 'Number of signers: 1\n']) {
    const f = fixture(t); f.proof.certificateSha256 = MOZILLA_CERT; f.report('apk-signing.log', text);
    assert.throws(() => f.check(), /ANDROID_NATIVE_(ONE_SIGNER|APKSIGNER_V2)_REQUIRED/);
  }
});

test('public build-receipt admission consumes the extension and refuses tampered, null and false-signature proof', (t) => {
  const f = fixture(t);
  const artifact = f.write('synthetic.apk', 'synthetic APK identity; no native execution is claimed by this test');
  const ca = f.write('public-ca.pem', 'synthetic public CA input; no TLS execution in this unit test');
  Object.assign(f.target, { environment: 'docker-integration', syntheticDataOnly: true,
    coreInventory: 'native-core-2026-10-25', appPath: artifact.path,
    binarySourceSha: 'a'.repeat(40), binarySourceFingerprint: 'b'.repeat(64),
    apiOrigin: 'https://10.0.2.2:8443', auth: { webOrigin: 'https://10.0.2.2:3443' }, publicCa: ca });
  Object.assign(f.receipt, { sourceSha: f.target.binarySourceSha, sourceFingerprint: f.target.binarySourceFingerprint,
    automatedTest: true, devEnabled: false, artifact: artifact.path,
    apiOrigin: f.target.apiOrigin, webOrigin: f.target.auth.webOrigin, publicCaSha256: ca.sha256 });
  const seal = () => { f.target.buildReceipt = f.write('complete-build-receipt.json', f.receipt); };
  seal();
  validateBuildReceipt(f.target, 'android', f.actualHash);
  writeFileSync(f.receipt.androidSecurity.nativeArtifactEvidence.path, '{}');
  assert.throws(() => validateBuildReceipt(f.target, 'android', f.actualHash), /FIXTURE_EVIDENCE_CHANGED/);
  f.receipt.androidSecurity.nativeArtifactEvidence = null; seal();
  assert.throws(() => validateBuildReceipt(f.target, 'android', f.actualHash), /ANDROID_NATIVE/);
  f.proof.signatureSchemeV2 = false; f.save(); seal();
  assert.throws(() => validateBuildReceipt(f.target, 'android', f.actualHash), /ANDROID_NATIVE_V2_SIGNATURE_REQUIRED/);
});

test('present null, malformed or wrong-hash proof cannot fall back to historical behavior', (t) => {
  for (const value of [null, undefined, false, {}, [], { path: 'relative.json', sha256: 'a'.repeat(64) }]) {
    const f = fixture(t); f.receipt.androidSecurity.nativeArtifactEvidence = value;
    assert.throws(() => f.check(), /ANDROID_NATIVE/);
  }
  const f = fixture(t); f.receipt.androidSecurity.nativeArtifactEvidence.sha256 = '0'.repeat(64);
  assert.throws(() => f.check(), /FIXTURE_EVIDENCE_CHANGED/);
});

test('schema, exact identity, selected serial, strict booleans, version and artifact mismatches reject', (t) => {
  for (const [key, value] of [['schemaVersion', 2], ['kind', 'android-proof'], ['appId', 'ai.caseops.mobile.dev'],
    ['artifactSha256', 'a'.repeat(64)], ['intendedDeviceSerial', 'emulator-other'], ['architecture', 'x86_64'],
    ['signatureVerified', false], ['signatureVerified', 'true'], ['signatureSchemeV2', false], ['signatureSchemeV2', 1],
    ['distributionSigning', true], ['nativeExecution', 'native-passed'], ['certificateSha256', 'not-a-digest'],
    ['versionCode', 0], ['versionCode', '1'], ['versionName', '']]) {
    const f = fixture(t); f.proof[key] = value; f.save();
    assert.throws(() => f.check(), /ANDROID_NATIVE/, `field ${key} must reject`);
  }
  for (const mutate of [f => { f.target.udid = 'another-serial'; }, f => { f.receipt.binaryHash = 'a'.repeat(64); },
    f => { f.receipt.androidSecurity.apkSha256 = 'b'.repeat(64); }, f => { f.receipt.platform = 'ios'; }]) {
    const f = fixture(t); mutate(f); assert.throws(() => f.check(), /ANDROID_NATIVE/);
  }
});

test('every one of the six report files is hash-verified before parsed assertions can succeed', (t) => {
  for (const name of REPORTS) {
    const f = fixture(t); writeFileSync(path.join(f.root, name), 'tampered report');
    assert.throws(() => f.check(), /FIXTURE_EVIDENCE_CHANGED/, `${name} must be read through its bound digest`);
  }
});

test('missing/duplicate reports, path traversal and same-name evidence outside the proof directory reject', (t) => {
  for (const mutate of [f => f.proof.evidence.pop(), f => { f.proof.evidence[1] = f.proof.evidence[0]; },
    f => { f.proof.evidence[0].path = path.join(f.root, 'nested') + '/../apk-badging.log'; },
    f => { f.proof.evidence[0].path = path.join(path.dirname(f.root), 'apk-badging.log'); }]) {
    const f = fixture(t); mutate(f); f.save(); assert.throws(() => f.check(), /ANDROID_NATIVE/);
  }
});

test('rehashed AAPT identity/version/ABI/debuggable ambiguity cannot be hidden behind proof fields', (t) => {
  const original = `package: name='${APP}' versionCode='1' versionName='0.1.0'\nnative-code: 'arm64-v8a'\n`;
  for (const text of [original.replace(APP, 'another.app'), original.replace("versionCode='1'", "versionCode='2'"),
    original.replace("versionName='0.1.0'", "versionName='2.0.0'"), original.replace("'arm64-v8a'", "'x86_64'"),
    original + 'application-debuggable\n', original + original.split('\n')[0] + '\n', original + "native-code: 'x86_64'\n"]) {
    const f = fixture(t); f.report('apk-badging.log', text); assert.throws(() => f.check(), /ANDROID_NATIVE/);
  }
});

test('rehashed signer output must independently verify v2, one signer and the exact certificate', (t) => {
  const f0 = fixture(t), original = readFileSync(path.join(f0.root, 'apk-signing.log'), 'utf8');
  for (const text of [original.replace('Verifies\n', 'DOES NOT VERIFY\n'), original.replace('v2): true', 'v2): false'),
    original.replace('Number of signers: 1', 'Number of signers: 2'), original.replace('3'.repeat(64), '4'.repeat(64)),
    original + `Signer #2 certificate SHA-256 digest: ${'5'.repeat(64)}\n`,
    original + 'Verified using v2 scheme (APK Signature Scheme v2): false\n']) {
    const f = fixture(t); f.report('apk-signing.log', text); assert.throws(() => f.check(), /ANDROID_NATIVE/);
  }
});

test('rehashed ABI JSON must attest bounded nonempty AArch64 ELF libraries only', (t) => {
  for (const changes of [{ abis: ['arm64-v8a', 'x86_64'] }, { elfClass: 32 }, { elfMachine: 62 },
    { nativeLibraryCount: 0 }, { nativeLibraryCount: '4' }, { nativeLibraryCount: 257 }, { schemaVersion: 2 }]) {
    const f = fixture(t), abi = JSON.parse(readFileSync(path.join(f.root, 'apk-abi.json')));
    f.report('apk-abi.json', { ...abi, ...changes }); assert.throws(() => f.check(), /ANDROID_NATIVE/);
  }
});

test('generated build inputs cannot point outside their exact inventory or differ from retained copied bytes', (t) => {
  for (const mutate of [manifest => { manifest.files[0].relativePath = '../outside'; },
    manifest => { manifest.files[1] = manifest.files[0]; }, manifest => { manifest.files[0].sizeBytes++; }]) {
    const f = fixture(t), manifest = JSON.parse(readFileSync(path.join(f.root, 'generated-android-inputs.json')));
    mutate(manifest); f.report('generated-android-inputs.json', manifest); assert.throws(() => f.check(), /ANDROID_NATIVE/);
  }
  const f = fixture(t); writeFileSync(path.join(f.root, 'app-build.gradle'), 'different generated input');
  assert.throws(() => f.check(), /FIXTURE_EVIDENCE_CHANGED/);
});

test('rehashed JDK reports must retain the two exact pinned versions', (t) => {
  for (const [name, content] of [['java21.log', 'Temurin-21.0.1+1\n'], ['java17.log', 'Temurin-17.0.20.1+1\nTemurin-21.0.12.1+1\n']]) {
    const f = fixture(t); f.report(name, content); assert.throws(() => f.check(), /ANDROID_NATIVE_JDK_VERSION_MISMATCH/);
  }
});
