import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { binaryHash } from '../../apps/mobile/e2e/support.mjs';
import { checkBuildConfig, decodeIosSimulatorEntitlements, finishBuild, parseIosSimulatorEntitlements, verifyIosSimulatorSigning } from './build-acceptance.mjs';
import { validateIosSigningReceipt } from '../../apps/mobile/e2e/fixture-contract.mjs';

const appId = 'ai.caseops.mobile.dev.simulatoracceptance';
const applicationIdentifier = `XCODETEAM1.${appId}`;
const info = { CFBundleIdentifier: appId, DTPlatformName: 'iphonesimulator', CFBundleSupportedPlatforms: ['iPhoneSimulator'] };
const entitlements = { 'application-identifier': applicationIdentifier, 'keychain-access-groups': [applicationIdentifier] };
const metadata = `Identifier=${appId}\nCodeDirectory v=20400 flags=0x2(adhoc)\nSignature=adhoc\nInfo.plist entries=33\nSealed Resources version=2 rules=10 files=22\n`;
function section(xml) {
  const bytes = Buffer.from(xml);
  const rows = [];
  for (let offset = 0; offset < bytes.length; offset += 16) {
    rows.push(`0x${(0x1000 + offset).toString(16)}: ${[...bytes.subarray(offset, offset + 16)].map((byte) => byte.toString(16).padStart(2, '0')).join(' ')} `);
  }
  return `synthetic-unit-binary [arm64]:\n(__TEXT,__entitlements) section:\n${rows.join('\n')}\n`;
}

test('Simulator signing proof requires Xcode-generated application identity and its exact private Keychain group', () => {
  assert.deepEqual(verifyIosSimulatorSigning(appId, info, entitlements, metadata), {
    applicationIdentifier, keychainAccessGroups: [applicationIdentifier], keychainGroupSource: 'explicit-private-group',
  });
});

test('the observed linker-only signature cannot certify a Keychain-capable Simulator app', () => {
  const original = 'Identifier=CaseOps\nCodeDirectory v=20400 flags=0x20002(adhoc,linker-signed)\nSignature=adhoc\nInfo.plist=not bound\nSealed Resources=none\n';
  assert.throws(() => verifyIosSimulatorSigning(appId, info, {}, original));
  for (const patch of [metadata.replace('flags=0x2(adhoc)', 'flags=0x20002(adhoc,linker-signed)'),
    metadata.replace('Info.plist entries=33', 'Info.plist=not bound'),
    metadata.replace('Sealed Resources version=2 rules=10 files=22', 'Sealed Resources=none'),
    metadata.replace('Signature=adhoc', 'Signature=untrusted'), metadata.replace(`Identifier=${appId}`, 'Identifier=other.app')]) {
    assert.throws(() => verifyIosSimulatorSigning(appId, info, entitlements, patch));
  }
});

test('Xcode app-identifier-only entitlements use the documented private default without inventing a group', () => {
  for (const observed of [{ 'application-identifier': applicationIdentifier },
    { 'application-identifier': applicationIdentifier, 'keychain-access-groups': [] }]) {
    assert.deepEqual(verifyIosSimulatorSigning(appId, info, observed, metadata), {
      applicationIdentifier, keychainAccessGroups: [applicationIdentifier], keychainGroupSource: 'application-identifier-default',
    });
  }
});

test('device bundles, wrong bundle IDs, missing entitlements and shared/wildcard Keychain groups fail closed', () => {
  for (const altered of [{ ...info, CFBundleIdentifier: 'other.app' }, { ...info, DTPlatformName: 'iphoneos' },
    { ...info, CFBundleSupportedPlatforms: ['iPhoneOS'] }]) {
    assert.throws(() => verifyIosSimulatorSigning(appId, altered, entitlements, metadata));
  }
  for (const altered of [{}, { ...entitlements, 'application-identifier': `*.${appId}` },
    { ...entitlements, 'application-identifier': 'XCODETEAM1.other.app' },
    { ...entitlements, 'keychain-access-groups': null }, { ...entitlements, 'keychain-access-groups': 'malformed' },
    { ...entitlements, 'keychain-access-groups': ['*'] },
    { ...entitlements, 'keychain-access-groups': [applicationIdentifier, 'XCODETEAM1.shared'] },
    { ...entitlements, 'com.apple.security.application-groups': ['group.shared'] }]) {
    assert.throws(() => verifyIosSimulatorSigning(appId, info, altered, metadata));
  }
});

test('actual Mach-O Simulator entitlement bytes are decoded without creating entitlement values', () => {
  const xml = '<?xml version="1.0"?><plist version="1.0"><dict><key>application-identifier</key><string>observed-only</string></dict></plist>\n';
  assert.equal(decodeIosSimulatorEntitlements(section(xml)), xml);
  const parsed = parseIosSimulatorEntitlements(section(xml));
  assert.equal(parsed.xml, xml);
  assert.deepEqual(Object.keys(parsed.entitlements), ['application-identifier']);
  assert.equal(parsed.entitlements['application-identifier'], 'observed-only');
});

test('native iOS preflight rejects unsigned historical receipts, mismatched signing hashes and changed evidence', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'caseops-ios-signature-evidence-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'explicit-unit-signing-evidence.txt'), bytes = 'synthetic unit evidence, not actual code signing';
  writeFileSync(file, bytes);
  const proof = { kind: 'ios-simulator-ad-hoc-signing', appId, strictVerified: true, signingIdentity: '-', distributionSigning: false,
    nativeExecution: 'not-run-by-signing-verifier', artifactSha256: 'a'.repeat(64), entitlementsLocation: 'Mach-O __TEXT,__entitlements',
    applicationIdentifier, keychainAccessGroups: [applicationIdentifier],
    slices: [{ architecture: 'arm64', applicationIdentifier, keychainAccessGroups: [applicationIdentifier] }],
    evidence: [{ path: file, sha256: createHash('sha256').update(bytes).digest('hex') }] };
  validateIosSigningReceipt(proof, appId, 'a'.repeat(64));
  assert.throws(() => validateIosSigningReceipt(undefined, appId, 'a'.repeat(64)), /IOS_SIMULATOR_SIGNING_PROOF_REQUIRED/);
  for (const altered of [{ ...proof, strictVerified: false }, { ...proof, artifactSha256: 'b'.repeat(64) },
    { ...proof, keychainAccessGroups: ['*'] }, { ...proof, evidence: [] },
    { ...proof, slices: [{ ...proof.slices[0], keychainAccessGroups: ['unrelated'] }] }]) {
    assert.throws(() => validateIosSigningReceipt(altered, appId, 'a'.repeat(64)));
  }
  writeFileSync(file, 'modified after receipt');
  assert.throws(() => validateIosSigningReceipt(proof, appId, 'a'.repeat(64)), /FIXTURE_EVIDENCE_CHANGED/);
});

test('missing, duplicated, discontinuous, malformed and oversized Simulator sections cannot become proof', () => {
  const valid = section('<?xml version="1.0"?><plist version="1.0"><dict/></plist>');
  for (const dump of ['', 'binary [arm64]:\n', valid.replace('0x1010:', '0x1020:'), valid.replace('0x1000: 3c', '0x1000: ZZ'),
    `${valid}\n(__TEXT,__entitlements) section:\n`, section('not an entitlement plist'),
    section('<?xml version="1.0"?>\0bad'), section(`<?xml version="1.0"?>${'x'.repeat(65536)}`)]) {
    assert.throws(() => decodeIosSimulatorEntitlements(dump));
  }
});

test('iOS receipt finishing requires strict signing proof bound to the final canonical artifact hash', (t) => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'caseops-ios-signing-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const artifact = path.join(directory, 'synthetic-unit-app');
  writeFileSync(artifact, 'unit artifact, not native execution');
  const values = { CASEOPS_MOBILE_BUILD_PROFILE: 'ios-simulator-acceptance', CASEOPS_MOBILE_AUTOMATED_TEST: '1',
    CASEOPS_MOBILE_RELEASE_SHA: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    EXPO_PUBLIC_API_ORIGIN: 'https://127.0.0.1:8443', EXPO_PUBLIC_WEB_ORIGIN: 'https://127.0.0.1:3443',
    CASEOPS_MOBILE_ANDROID_CA_FILE: undefined, CASEOPS_MOBILE_ANDROID_CA_SHA256: undefined,
    SKIP_BUNDLING: undefined, EX_UPDATES_NATIVE_DEBUG: undefined };
  const previous = Object.fromEntries(Object.keys(values).map((key) => [key, process.env[key]]));
  try {
    for (const [key, value] of Object.entries(values)) if (value === undefined) delete process.env[key]; else process.env[key] = value;
    const before = checkBuildConfig('ios');
    const config = { extra: { automatedTest: true, apiOrigin: before.apiOrigin, webOrigin: before.webOrigin, releaseSha: before.sourceSha },
      ios: { bundleIdentifier: appId } };
    assert.throws(() => finishBuild('ios', before, artifact, config), /IOS_SIMULATOR_SIGNING_PROOF_REQUIRED/);
    const proof = { kind: 'ios-simulator-ad-hoc-signing', appId, strictVerified: true, artifactSha256: binaryHash(artifact) };
    assert.throws(() => finishBuild('ios', before, artifact, config, { ...proof, strictVerified: false }), /STRICT_SIMULATOR_SIGNATURE_REQUIRED/);
    assert.throws(() => finishBuild('ios', before, artifact, config, { ...proof, appId: 'other' }), /SIGNED_SIMULATOR_BUNDLE_ID_MISMATCH/);
    assert.throws(() => finishBuild('ios', before, artifact, config, { ...proof, artifactSha256: '0'.repeat(64) }), /IOS_SIGNING_ARTIFACT_MISMATCH/);
    assert.deepEqual(finishBuild('ios', before, artifact, config, proof).iosSigning, proof);
    writeFileSync(artifact, 'changed after signing inspection');
    assert.throws(() => finishBuild('ios', before, artifact, config, proof), /IOS_SIGNING_ARTIFACT_MISMATCH/);
  } finally {
    for (const [key, value] of Object.entries(previous)) if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
});
