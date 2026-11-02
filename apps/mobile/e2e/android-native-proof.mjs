import assert from 'node:assert/strict';
import path from 'node:path';
import { verifiedFile } from './evidence.mjs';

const QA_ID = 'ai.caseops.mobile.dev.localacceptance';
const SHA = /^[a-f0-9]{64}$/;
const REPORTS = ['apk-badging.log', 'apk-signing.log', 'apk-abi.json',
  'generated-android-inputs.json', 'java21.log', 'java17.log'];
const INPUTS = ['build.gradle', 'settings.gradle', 'gradle.properties', 'app/build.gradle',
  'gradle/wrapper/gradle-wrapper.properties'];

function shape(value, fields, code) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), code);
  assert.ok(Object.keys(value).length === fields.length && fields.every(field => Object.hasOwn(value, field)), code);
}
function reference(value, name, directory) {
  shape(value, ['path', 'sha256'], 'ANDROID_NATIVE_EVIDENCE_REFERENCE_REQUIRED');
  assert.ok(typeof value.path === 'string' && path.isAbsolute(value.path)
    && path.normalize(value.path) === value.path && path.basename(value.path) === name,
  'ANDROID_NATIVE_EVIDENCE_PATH_REQUIRED');
  if (directory !== undefined) assert.equal(path.dirname(value.path), directory, 'ANDROID_NATIVE_EVIDENCE_DIRECTORY_MISMATCH');
  assert.match(value.sha256 || '', SHA, 'ANDROID_NATIVE_EVIDENCE_HASH_REQUIRED');
}
function oneLine(lines, prefix, expression, code) {
  const candidates = lines.filter(line => line.startsWith(prefix));
  assert.equal(candidates.length, 1, code);
  const match = expression.exec(candidates[0]);
  assert.ok(match, code);
  return match;
}
function jdk(text, expected) {
  const versions = [...text.matchAll(/Temurin-([0-9.]+\+[0-9]+)/g)].map(match => match[1]);
  assert.ok(versions.length > 0 && versions.length <= 4 && versions.every(version => version === expected),
    'ANDROID_NATIVE_JDK_VERSION_MISMATCH');
}

/** Optional Mac ARM64 build extension; absence makes no new native-proof claim. */
export function validateAndroidNativeProof(fixture, receipt, actualHash) {
  const security = receipt?.androidSecurity;
  if (security == null || !Object.hasOwn(security, 'nativeArtifactEvidence')) return null;
  assert.equal(receipt.platform, 'android', 'ANDROID_NATIVE_PLATFORM_MISMATCH');
  assert.equal(receipt.profile, 'android-local-acceptance', 'ANDROID_NATIVE_PROFILE_MISMATCH');
  assert.equal(security.kind, 'compiled-android-acceptance-security', 'ANDROID_NATIVE_COMPILED_SECURITY_REQUIRED');
  assert.match(actualHash || '', SHA, 'ANDROID_NATIVE_ARTIFACT_HASH_REQUIRED');
  assert.equal(receipt.binaryHash, actualHash, 'ANDROID_NATIVE_ARTIFACT_MISMATCH');
  assert.equal(security.apkSha256, actualHash, 'ANDROID_NATIVE_ARTIFACT_MISMATCH');
  const ref = security.nativeArtifactEvidence;
  reference(ref, 'android-native-proof.json');
  const directory = path.dirname(ref.path);
  const proof = JSON.parse(verifiedFile(ref.path, ref.sha256, 32768));
  shape(proof, ['schemaVersion', 'kind', 'appId', 'artifactSha256', 'versionCode', 'versionName',
    'architecture', 'signatureVerified', 'signatureSchemeV2', 'certificateSha256', 'intendedDeviceSerial',
    'evidence', 'distributionSigning', 'nativeExecution'], 'ANDROID_NATIVE_PROOF_SCHEMA_REQUIRED');
  assert.equal(proof.schemaVersion, 1, 'ANDROID_NATIVE_PROOF_SCHEMA_REQUIRED');
  assert.equal(proof.kind, 'android-local-arm64-signature-proof', 'ANDROID_NATIVE_PROOF_KIND_REQUIRED');
  assert.equal(proof.appId, QA_ID, 'ANDROID_NATIVE_QA_ID_REQUIRED');
  assert.equal(receipt.appId, proof.appId, 'ANDROID_NATIVE_QA_ID_REQUIRED');
  assert.equal(fixture.appId, proof.appId, 'ANDROID_NATIVE_QA_ID_REQUIRED');
  assert.equal(proof.artifactSha256, actualHash, 'ANDROID_NATIVE_ARTIFACT_MISMATCH');
  assert.match(proof.intendedDeviceSerial || '', /^[A-Za-z0-9._:-]{1,120}$/, 'ANDROID_NATIVE_SERIAL_REQUIRED');
  assert.equal(proof.intendedDeviceSerial, fixture.udid, 'ANDROID_NATIVE_DEVICE_SERIAL_MISMATCH');
  assert.equal(proof.architecture, 'arm64-v8a', 'ANDROID_NATIVE_ARM64_REQUIRED');
  assert.equal(proof.signatureVerified, true, 'ANDROID_NATIVE_SIGNATURE_REQUIRED');
  assert.equal(proof.signatureSchemeV2, true, 'ANDROID_NATIVE_V2_SIGNATURE_REQUIRED');
  assert.equal(proof.distributionSigning, false, 'ANDROID_NATIVE_DISTRIBUTION_CLAIM_FORBIDDEN');
  assert.equal(proof.nativeExecution, 'not-run-by-build-wrapper', 'ANDROID_NATIVE_EXECUTION_CLAIM_FORBIDDEN');
  assert.match(proof.certificateSha256 || '', SHA, 'ANDROID_NATIVE_CERTIFICATE_HASH_REQUIRED');
  assert.ok(Number.isSafeInteger(proof.versionCode) && proof.versionCode > 0, 'ANDROID_NATIVE_VERSION_CODE_REQUIRED');
  assert.ok(typeof proof.versionName === 'string' && proof.versionName.length > 0 && proof.versionName.length <= 100
    && !/[\x00-\x1f\x7f]/.test(proof.versionName), 'ANDROID_NATIVE_VERSION_NAME_REQUIRED');
  assert.ok(Array.isArray(proof.evidence) && proof.evidence.length === REPORTS.length, 'ANDROID_NATIVE_REPORT_INVENTORY_REQUIRED');
  const reports = {};
  for (let index = 0; index < REPORTS.length; index++) {
    const name = REPORTS[index], item = proof.evidence[index];
    reference(item, name, directory);
    reports[name] = verifiedFile(item.path, item.sha256, name.endsWith('.log') ? 1048576 : 262144).toString('utf8');
  }

  const badging = reports['apk-badging.log'].split(/\r?\n/);
  const identity = oneLine(badging, 'package:', /^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']+)'(?: |$)/,
    'ANDROID_NATIVE_AAPT_IDENTITY_REQUIRED');
  assert.equal(identity[1], proof.appId, 'ANDROID_NATIVE_AAPT_IDENTITY_MISMATCH');
  assert.equal(Number(identity[2]), proof.versionCode, 'ANDROID_NATIVE_AAPT_VERSION_MISMATCH');
  assert.equal(identity[3], proof.versionName, 'ANDROID_NATIVE_AAPT_VERSION_MISMATCH');
  assert.ok(!badging.some(line => line.startsWith('application-debuggable')), 'ANDROID_NATIVE_DEBUGGABLE_FORBIDDEN');
  oneLine(badging, 'native-code:', /^native-code: 'arm64-v8a'$/, 'ANDROID_NATIVE_AAPT_ARM64_REQUIRED');

  const signing = reports['apk-signing.log'].split(/\r?\n/);
  assert.equal(signing.filter(line => line === 'Verifies').length, 1, 'ANDROID_NATIVE_APKSIGNER_VERIFICATION_REQUIRED');
  assert.ok(!signing.some(line => /DOES NOT VERIFY/.test(line)), 'ANDROID_NATIVE_APKSIGNER_VERIFICATION_REQUIRED');
  oneLine(signing, 'Verified using v2 scheme', /^Verified using v2 scheme \(APK Signature Scheme v2\): true$/,
    'ANDROID_NATIVE_APKSIGNER_V2_REQUIRED');
  oneLine(signing, 'Number of signers:', /^Number of signers: 1$/, 'ANDROID_NATIVE_ONE_SIGNER_REQUIRED');
  // SDK37 labels its sole v2 signer differently from historical SDK reports.
  // Count every certificate digest first: duplicate or mixed labels may never
  // hide a second identity, even when both lines contain the same digest.
  const certificates = signing.filter(line => line.includes('certificate SHA-256 digest:'));
  assert.equal(certificates.length, 1, 'ANDROID_NATIVE_ONE_SIGNER_REQUIRED');
  const certificate = /^(?:Signer #1 certificate|V2 Signer: certificate) SHA-256 digest: ([a-fA-F0-9]{64})$/.exec(certificates[0]);
  assert.ok(certificate, 'ANDROID_NATIVE_ONE_SIGNER_REQUIRED');
  assert.equal(certificate[1].toLowerCase(), proof.certificateSha256, 'ANDROID_NATIVE_CERTIFICATE_MISMATCH');

  const abi = JSON.parse(reports['apk-abi.json']);
  shape(abi, ['schemaVersion', 'abis', 'nativeLibraryCount', 'elfClass', 'elfMachine'], 'ANDROID_NATIVE_ABI_REPORT_REQUIRED');
  assert.equal(abi.schemaVersion, 1, 'ANDROID_NATIVE_ABI_REPORT_REQUIRED');
  assert.deepEqual(abi.abis, ['arm64-v8a'], 'ANDROID_NATIVE_ARM64_REQUIRED');
  assert.ok(Number.isSafeInteger(abi.nativeLibraryCount) && abi.nativeLibraryCount > 0 && abi.nativeLibraryCount <= 256,
    'ANDROID_NATIVE_LIBRARY_COUNT_REQUIRED');
  assert.equal(abi.elfClass, 64, 'ANDROID_NATIVE_ELF64_REQUIRED');
  assert.equal(abi.elfMachine, 183, 'ANDROID_NATIVE_AARCH64_REQUIRED');

  const generated = JSON.parse(reports['generated-android-inputs.json']);
  shape(generated, ['schemaVersion', 'files'], 'ANDROID_NATIVE_GENERATED_INPUTS_REQUIRED');
  assert.equal(generated.schemaVersion, 1, 'ANDROID_NATIVE_GENERATED_INPUTS_REQUIRED');
  assert.ok(Array.isArray(generated.files) && generated.files.length === INPUTS.length, 'ANDROID_NATIVE_GENERATED_INPUTS_REQUIRED');
  for (let index = 0; index < INPUTS.length; index++) {
    const input = generated.files[index], relative = INPUTS[index];
    shape(input, ['relativePath', 'sha256', 'sizeBytes'], 'ANDROID_NATIVE_GENERATED_INPUTS_REQUIRED');
    assert.equal(input.relativePath, relative, 'ANDROID_NATIVE_GENERATED_INPUT_PATH_REQUIRED');
    assert.ok(Number.isSafeInteger(input.sizeBytes) && input.sizeBytes > 0 && input.sizeBytes <= 1048576,
      'ANDROID_NATIVE_GENERATED_INPUT_BOUND');
    const bytes = verifiedFile(path.join(directory, relative.replaceAll('/', '-')), input.sha256, 1048576);
    assert.equal(bytes.length, input.sizeBytes, 'ANDROID_NATIVE_GENERATED_INPUT_SIZE_MISMATCH');
  }
  jdk(reports['java21.log'], '21.0.12.1+1');
  jdk(reports['java17.log'], '17.0.20.1+1');
  return proof;
}
