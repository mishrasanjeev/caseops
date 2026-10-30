import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash, X509Certificate } from 'node:crypto';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { rootCertificates } from 'node:tls';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { androidGradleArguments, androidGradleExecutionArguments, androidSharedJavaOptions, assertAndroidNodePath, bindAndroidJavaHome, neutralAndroidGradleEnvironment, prepareAndroidGradleEnvironment, renderAndroidNodeShim, readAndroidHostInput, writeAndroidHostOutput } from './android-host-launch.mjs';
import { prepareHostNodeTrust } from './host-node-trust.mjs';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
// Actual public SDK37/apksigner0.9 report for Mozilla's official Firefox158.0.2
// ARM64 APK, retained verbatim independently of the producer/consumer parser.
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
const cert = rootCertificates.find(pem => { const c = new X509Certificate(pem);
  return c.ca && c.checkIssued(c) && c.verify(c.publicKey) && Date.parse(c.validFrom) < Date.now() && Date.now() < Date.parse(c.validTo); }).trim() + '\n';
const resources = `  resource 0x7f100000 raw/caseops_local_acceptance_ca
    () (file) res/Ap.pem
  resource 0x7f140000 xml/caseops_local_acceptance_network
    () (file) res/RM.xml type=XML
`;
const manifest = `E: manifest (line=1)
  A: package="ai.caseops.mobile.dev.localacceptance"
  E: application (line=2)
    A: http://schemas.android.com/apk/res/android:allowBackup(0x01010280)=false
    A: http://schemas.android.com/apk/res/android:usesCleartextTraffic(0x010104ec)=false
    A: http://schemas.android.com/apk/res/android:networkSecurityConfig(0x01010527)=@0x7f140000
`;
const network = `E: network-security-config (line=1)
  E: base-config (line=2)
    A: cleartextTrafficPermitted=false
    E: trust-anchors (line=3)
      E: certificates (line=4)
        A: src="system"
  E: domain-config (line=5)
    A: cleartextTrafficPermitted=false
${['localhost', 'ip6-localhost', '127.0.0.1', '[::1]'].map(host => `    E: domain (line=6)
      A: includeSubdomains=false
      T: '${host}'`).join('\n')}
    E: trust-anchors (line=7)
      E: certificates (line=8)
        A: src="system"
  E: domain-config (line=9)
    A: cleartextTrafficPermitted=false
    E: domain (line=10)
      A: includeSubdomains=false
      T: '10.0.2.2'
    E: trust-anchors (line=11)
      E: certificates (line=12)
        A: src=@0x7f100000
`;

function fixture(t, extra = {}) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-mac-android-wrapper-'))), checkout = path.join(root, 'repo');
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const file = (name, data, executable = false) => { const p = path.join(root, name); mkdirSync(path.dirname(p), { recursive: true });
    writeFileSync(p, data); if (executable) chmodSync(p, 0o700); return p; };
  const files = ['scripts/mobile/android-host-launch.mjs', 'scripts/mobile/android-no-paid.gradle',
    'scripts/mobile/host-platform-trust.py', 'scripts/mobile/fixtures/host-platform-trust/HostPlatformTrust.java',
    'scripts/mobile/host-node-trust.mjs', 'scripts/mobile/host-node-trust-start.mjs',
    'scripts/mobile/build-android-local-acceptance.sh', 'scripts/mobile/build-acceptance.mjs', 'scripts/mobile/source-snapshot.mjs',
    'scripts/mobile/prepare-native-links.mjs', 'scripts/mobile/prepare-store-packaging.mjs', 'apps/mobile/metro.config.js',
    'apps/web/lib/native-link-policy.cjs', 'apps/web/lib/native-link-policy.d.cts',
    'apps/web/lib/native-link-config.cjs', 'apps/web/lib/native-link-config.d.cts',
    'scripts/mobile/prepare-viewer-assets.mjs', 'apps/mobile/src/viewer/renderer-runtime.ts',
    ...['LICENSES.txt', 'manifest.json', 'pdfjs-assets.ts', 'renderer-runtime-source.ts'].map(name => `apps/mobile/src/viewer/generated/${name}`),
    'apps/mobile/package.json', 'apps/mobile/app.config.ts', 'apps/mobile/plugins/with-local-acceptance.cjs', 'apps/mobile/plugins/store-build.cjs',
    'apps/mobile/plugins/privacy-policy.cjs', 'apps/mobile/plugins/with-privacy-policy.cjs', 'apps/mobile/e2e/support.mjs'];
  for (const name of files) { const destination = path.join(checkout, name); mkdirSync(path.dirname(destination), { recursive: true }); copyFileSync(path.join(repo, name), destination); }
  // Trace actual source capture in the temporary contract fixture, so an order
  // assertion cannot pass merely because the wrapper contains command strings.
  const snapshot = path.join(checkout, 'scripts/mobile/source-snapshot.mjs');
  const snapshotSource = readFileSync(snapshot, 'utf8');
  assert.equal(snapshotSource.split('  const paths = [').length, 2, 'EXACT_SOURCE_TRACE_BOUNDARY_REQUIRED');
  writeFileSync(snapshot, "import { appendFileSync as appendCaseopsSnapshotTrace } from 'node:fs';\n" + snapshotSource
    .replace('  const paths = [', "  appendCaseopsSnapshotTrace(process.env.CASEOPS_TEST_TRACE, 'source-snapshot\\n');\n  const paths = ["));
  file('repo/package.json', '{"type":"module"}\n'); file('repo/.gitignore', 'node_modules/\napps/mobile/android/\n');
  mkdirSync(path.join(checkout, 'apps/mobile/node_modules'), { recursive: true });
  symlinkSync(path.join(repo, 'apps/mobile/node_modules/@expo'), path.join(checkout, 'apps/mobile/node_modules/@expo'), 'dir');
  for (const module of ['expo-secure-store', 'expo-web-browser', 'expo-image-picker', 'pdfjs-dist'])
    symlinkSync(path.join(repo, 'apps/mobile/node_modules', module), path.join(checkout, 'apps/mobile/node_modules', module), 'dir');
  file('repo/apps/mobile/node_modules/expo/package.json', '{"name":"expo","version":"58.0.19"}');
  file('repo/apps/mobile/node_modules/expo/bin/cli', `const fs=require('fs'),path=require('path');
fs.appendFileSync(process.env.CASEOPS_TEST_TRACE,'expo:'+JSON.stringify(process.argv.slice(2))+'\\n');
const root=path.join(process.cwd(),'android');fs.mkdirSync(path.join(root,'gradle/wrapper'),{recursive:true});fs.mkdirSync(path.join(root,'app'),{recursive:true});
for(const file of ['build.gradle','settings.gradle','gradle.properties','app/build.gradle'])fs.writeFileSync(path.join(root,file),'// synthetic offline native input\\n');
fs.writeFileSync(path.join(root,'gradle/wrapper/gradle-wrapper.properties'),'distributionUrl=https\\\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip\\n');
fs.copyFileSync(process.env.CASEOPS_TEST_GRADLE,path.join(root,'gradlew'));fs.chmodSync(path.join(root,'gradlew'),0o700);
`);
  file('tools/uname', '#!/bin/bash\nif [[ "$1" = -s ]]; then echo "${CASEOPS_TEST_OS:-Darwin}"; else echo arm64; fi\n', true);
  file('tools/node', `#!/bin/bash
if [[ "$1" = */scripts/mobile/prepare-viewer-assets.mjs ]]; then
  printf 'viewer-check:%s\\n' "$2" >> "$CASEOPS_TEST_TRACE"
  "$CASEOPS_TEST_NODE_REAL" "$@"
  result=$?
  printf 'viewer-check-result:%s\\n' "$result" >> "$CASEOPS_TEST_TRACE"
  exit "$result"
fi
exec "$CASEOPS_TEST_NODE_REAL" "$@"
`, true);
  for (const [name, version] of [['jdk21', '21.0.12.1+1'], ['jdk17', '17.0.20.1+1']])
    file(`${name}/bin/java`, `#!/bin/bash\necho 'OpenJDK Runtime Environment Temurin-${version} (synthetic version fixture)' >&2\n`, true);
  for (const [name, version] of [['platforms/android-37.0', '2'], ['build-tools/36.0.0', '36.0.0'], ['build-tools/37.0.0', '37.0.0'], ['ndk/27.1.12297006', '27.1.12297006'], ['cmake/3.30.5', '3.30.5']])
    file(`sdk/${name}/source.properties`, `Pkg.Revision=${version}\n`);
  file('responses.json', JSON.stringify({ resources, manifest, network }));
  file('aapt.py', `import sys,json,pathlib,os
args=sys.argv[1:];root=pathlib.Path(os.environ['CASEOPS_TEST_ROOT']);d=json.loads((root/'responses.json').read_text())
if args[:2]==['dump','badging']:print("package: name='ai.caseops.mobile.dev.localacceptance' versionCode='1' versionName='0.1.0'\\nnative-code: 'arm64-v8a'")
elif args[:2]==['dump','resources']:
 if os.environ.get('CASEOPS_TEST_MUTATE_APK'):
  with pathlib.Path(args[-1]).open('ab') as f:f.write(b'changed-after-signing')
 print(d['resources'],end='')
else:print(d['manifest'] if args[3]=='AndroidManifest.xml' else d['network'],end='')
`);
  file('sdk/build-tools/37.0.0/aapt2', '#!/bin/bash\nexec python3 "$CASEOPS_TEST_ROOT/aapt.py" "$@"\n', true);
  file('sdk/build-tools/37.0.0/apksigner', `#!/bin/bash
if [[ -n "\${CASEOPS_TEST_SIGNING_REPORT:-}" ]]; then
cat "$CASEOPS_TEST_SIGNING_REPORT"
else
echo Verifies
echo 'Verified using v2 scheme (APK Signature Scheme v2): true'
echo 'Number of signers: 1'
echo 'Signer #1 certificate SHA-256 digest: ${'3'.repeat(64)}'
fi
exit "\${CASEOPS_TEST_SIGNER_EXIT:-0}"
`, true);
  const gradle = file('fake-gradlew', `#!/bin/bash
printf 'gradle:%s\\n' "$*" >> "$CASEOPS_TEST_TRACE"
if [[ "\${CASEOPS_TEST_GRADLE_EXIT:-0}" != 0 ]]; then echo RETAINED_GRADLE_FAILURE >&2; exit "$CASEOPS_TEST_GRADLE_EXIT"; fi
python3 "$CASEOPS_TEST_ROOT/make-apk.py" "$PWD/app/build/outputs/apk/localAcceptance/app-localAcceptance.apk"
if [[ -n "\${CASEOPS_TEST_MUTATE_SOURCE:-}" ]]; then echo changed > ../source-changed.ts; fi
if [[ -n "\${CASEOPS_TEST_MUTATE_POLICY_HELPER:-}" ]]; then echo '// synthetic post-preflight helper change' >> "../plugins/$CASEOPS_TEST_MUTATE_POLICY_HELPER"; fi
`, true);
  file('make-apk.py', `import os,sys,json,pathlib,zipfile
p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True)
config={'extra':{'automatedTest':True,'apiOrigin':os.environ['EXPO_PUBLIC_API_ORIGIN'],'webOrigin':os.environ['EXPO_PUBLIC_WEB_ORIGIN'],'releaseSha':os.environ['CASEOPS_MOBILE_RELEASE_SHA']}}
elf=bytearray(64);elf[:6]=b'\\x7fELF\\x02\\x01';elf[16:18]=(3).to_bytes(2,'little');elf[18:20]=int(os.environ.get('CASEOPS_TEST_ELF_MACHINE','183')).to_bytes(2,'little')
with zipfile.ZipFile(p,'w') as z:
 for name,data in [('AndroidManifest.xml',b'synthetic compiled XML'),('assets/index.android.bundle',b'synthetic bundled JS'),('assets/app.config',json.dumps(config).encode()),('res/Ap.pem',pathlib.Path(os.environ['CASEOPS_MOBILE_ANDROID_CA_FILE']).read_bytes()),('res/RM.xml',b'synthetic compiled network XML'),('lib/'+os.environ.get('CASEOPS_TEST_ABI','arm64-v8a')+'/libfixture.so',elf)]:z.writestr(name,data)
`);
  const ca = file('ca.pem', cert), trace = file('trace.log', '');
  mkdirSync(path.join(root, 'gradle-cache')); mkdirSync(path.join(root, 'builds'));
  for (const args of [['init', '--quiet'], ['add', '.'], ['-c', 'user.name=Offline fixture', '-c', 'user.email=offline@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Offline fixture']])
    execFileSync('git', args, { cwd: checkout, stdio: 'pipe' });
  const env = { ...process.env, PATH: `${path.join(root, 'tools')}:${path.dirname(process.execPath)}:${process.env.PATH}`,
    ANDROID_HOME: path.join(root, 'sdk'), ANDROID_SDK_ROOT: path.join(root, 'sdk'), JAVA_HOME: path.join(root, 'jdk21'),
    CASEOPS_ANDROID_JDK17_HOME: path.join(root, 'jdk17'), GRADLE_USER_HOME: path.join(root, 'gradle-cache'), ANDROID_UDID: 'emulator-5582',
    CASEOPS_MOBILE_ANDROID_CA_FILE: ca, CASEOPS_MOBILE_ANDROID_CA_SHA256: hash(cert), EXPO_PUBLIC_API_ORIGIN: 'https://10.0.2.2:8443',
    EXPO_PUBLIC_WEB_ORIGIN: 'https://10.0.2.2:3443', CASEOPS_ANDROID_BUILD_ROOT: path.join(root, 'builds'),
    CASEOPS_TEST_ROOT: root, CASEOPS_TEST_GRADLE: gradle, CASEOPS_TEST_TRACE: trace, CASEOPS_TEST_NODE_REAL: process.execPath, ...extra };
  for (const key of ['EX_UPDATES_NATIVE_DEBUG', 'SKIP_BUNDLING']) delete env[key];
  const run = () => spawnSync('/bin/bash', [path.join(checkout, 'scripts/mobile/build-android-local-acceptance.sh')], { cwd: checkout, env, encoding: 'utf8', timeout: 45000, maxBuffer: 262144 });
  const outputs = () => readdirSync(path.join(root, 'builds')).map(name => path.join(root, 'builds', name));
  return { root, checkout, env, trace, run, outputs,
    signing(text) { const p = file('captured-signing-report.log', text); env.CASEOPS_TEST_SIGNING_REPORT = p; } };
}

test('actual shell orchestration binds portable source/CA receipt, ARM64 ELF and signature evidence without executing a device', t => {
  const f = fixture(t), result = f.run(); assert.equal(result.status, 0, result.stdout + result.stderr);
  const [output] = f.outputs(); assert.ok(output); const receipt = JSON.parse(readFileSync(path.join(output, 'receipt.json')));
  assert.equal(receipt.profile, 'android-local-acceptance'); assert.equal(receipt.devEnabled, false);
  assert.equal(receipt.binaryHash, hash(readFileSync(receipt.artifact))); assert.equal(receipt.publicCaSha256, hash(cert));
  const ref = receipt.androidSecurity.nativeArtifactEvidence, bytes = readFileSync(ref.path); assert.equal(hash(bytes), ref.sha256);
  const proof = JSON.parse(bytes); assert.equal(proof.artifactSha256, receipt.binaryHash); assert.equal(proof.architecture, 'arm64-v8a');
  assert.equal(proof.signatureVerified, true); assert.equal(proof.distributionSigning, false); assert.equal(proof.nativeExecution, 'not-run-by-build-wrapper');
  for (const evidence of proof.evidence) assert.equal(hash(readFileSync(evidence.path)), evidence.sha256);
  const trace = readFileSync(f.trace, 'utf8'); assert.match(trace, /prebuild.*--platform.*android.*--no-install/);
  assert.match(trace, /assembleLocalAcceptance.*reactNativeArchitectures=arm64-v8a/); assert.match(trace, /android.builder.sdkDownload=false/);
  assert.match(trace, /org.gradle.java.installations.auto-download=false/); assert.doesNotMatch(trace, /adb|emulator|--licenses|sdkmanager|expo.*start/);
  assert.match(readFileSync(path.join(output, 'gradle-wrapper-gradle-wrapper.properties'), 'utf8'), /distributionSha256Sum=2ab2958f/);
});

test('actual preflight order verifies generated public renderer bytes before source snapshots, prebuild and Gradle', t => {
  const f = fixture(t), result = f.run(); assert.equal(result.status, 0, result.stdout + result.stderr);
  for (const input of ['scripts/mobile/prepare-native-links.mjs', 'scripts/mobile/prepare-store-packaging.mjs',
    'apps/mobile/plugins/store-build.cjs', 'apps/mobile/plugins/privacy-policy.cjs', 'apps/mobile/plugins/with-privacy-policy.cjs', 'apps/mobile/metro.config.js',
    'apps/web/lib/native-link-policy.cjs', 'apps/web/lib/native-link-policy.d.cts',
    'apps/web/lib/native-link-config.cjs', 'apps/web/lib/native-link-config.d.cts'])
    assert.deepEqual(readFileSync(path.join(f.checkout, input)), readFileSync(path.join(repo, input)), 'EXACT_SHARED_NATIVE_LINK_INPUT_CLOSURE_REQUIRED');
  const stages = readFileSync(f.trace, 'utf8').trim().split('\n').map(line => line.split(':')[0]);
  assert.deepEqual(stages, ['viewer-check', 'viewer-check-result', 'source-snapshot', 'expo', 'gradle', 'source-snapshot']);
  assert.match(readFileSync(f.trace, 'utf8'), /^viewer-check:--check\nviewer-check-result:0\n/);
  const [output] = f.outputs();
  assert.match(readFileSync(path.join(output, 'viewer-assets-check.log'), 'utf8'), /PDF\.js 6\.4\.299: verified 4 deterministic public outputs/);
  assert.ok(existsSync(path.join(output, 'before.json')) && existsSync(path.join(output, 'receipt.json')));
});

test('stale generated public renderer is refused without rewriting it or capturing a build source snapshot', t => {
  const f = fixture(t), generated = path.join(f.checkout, 'apps/mobile/src/viewer/generated/renderer-runtime-source.ts');
  const stale = readFileSync(generated, 'utf8') + '// Deliberately stale public output in this offline fixture.\n';
  writeFileSync(generated, stale);
  // A clean committed stale output reproduces the gap that a source hash alone
  // cannot detect: the generated bytes must match their canonical program.
  execFileSync('git', ['add', 'apps/mobile/src/viewer/generated/renderer-runtime-source.ts'], { cwd: f.checkout, stdio: 'pipe' });
  execFileSync('git', ['-c', 'user.name=Offline fixture', '-c', 'user.email=offline@example.invalid', '-c', 'commit.gpgsign=false',
    'commit', '--quiet', '-m', 'Synthetic stale renderer control'], { cwd: f.checkout, stdio: 'pipe' });
  const result = f.run(); assert.notEqual(result.status, 0);
  assert.match(result.stdout + result.stderr, /Stale public asset: renderer-runtime-source\.ts/);
  assert.equal(readFileSync(generated, 'utf8'), stale, 'preflight must not silently regenerate reviewed inputs');
  assert.equal(readFileSync(f.trace, 'utf8'), 'viewer-check:--check\nviewer-check-result:1\n');
  const [output] = f.outputs();
  assert.match(readFileSync(path.join(output, 'viewer-assets-check.log'), 'utf8'), /Stale public asset: renderer-runtime-source\.ts/);
  for (const file of ['before.json', 'check.log', 'prebuild.log', 'gradle.log', 'caseops-local-acceptance-arm64.apk', 'receipt.json'])
    assert.equal(existsSync(path.join(output, file)), false, `${file} must not exist after failed renderer preflight`);
  assert.equal(existsSync(path.join(f.checkout, 'apps/mobile/android')), false);
});

test('actual wrapper orchestration accepts the verbatim SDK37 single V2 signer report', t => {
  assert.equal(hash(SDK37_REPORT), 'f5fc366fe25fab7fe128592e8ae2acd0287095f9ae05a0558681fb0332a88253');
  const f = fixture(t); f.signing(SDK37_REPORT); const result = f.run(); assert.equal(result.status, 0, result.stdout + result.stderr);
  const [output] = f.outputs(), proof = JSON.parse(readFileSync(path.join(output, 'android-native-proof.json')));
  assert.equal(proof.certificateSha256, 'a78b62a5165b4494b2fead9e76a280d22d937fee6251aece599446b2ea319b04');
});

test('actual wrapper rejects V1-only, duplicated and mixed SDK37 signer reports before receipt', t => {
  const certificate = 'a78b62a5165b4494b2fead9e76a280d22d937fee6251aece599446b2ea319b04';
  for (const text of [SDK37_REPORT.replace('v2): true', 'v2): false'),
    SDK37_REPORT.replaceAll('V2 Signer:', 'V1 Signer:'),
    SDK37_REPORT + `V2 Signer: certificate SHA-256 digest: ${certificate}\n`,
    SDK37_REPORT + `Signer #1 certificate SHA-256 digest: ${certificate}\n`]) {
    const f = fixture(t); f.signing(text); const result = f.run(); assert.notEqual(result.status, 0);
    assert.match(result.stdout + result.stderr, /APK_V2_SIGNATURE_REQUIRED|ONE_APK_SIGNER_REQUIRED/);
    const [output] = f.outputs(); assert.equal(existsSync(path.join(output, 'receipt.json')), false);
  }
});

test('nonzero Gradle diagnostics remain retained and cannot produce a receipt', t => {
  const f = fixture(t, { CASEOPS_TEST_GRADLE_EXIT: '7' }), result = f.run(); assert.equal(result.status, 7);
  const [output] = f.outputs(); assert.match(readFileSync(path.join(output, 'gradle.log'), 'utf8'), /RETAINED_GRADLE_FAILURE/);
  assert.equal(existsSync(path.join(output, 'receipt.json')), false);
});

for (const [label, extra, error] of [
  ['x86 library path despite claimed ARM64 badging', { CASEOPS_TEST_ABI: 'x86_64' }, /ARM64_ONLY_NATIVE_LIBRARIES_REQUIRED/],
  ['x86 ELF hidden in an ARM64 library path', { CASEOPS_TEST_ELF_MACHINE: '62' }, /AARCH64_SHARED_ELF_REQUIRED/],
  ['failed signature verifier despite successful-looking stdout', { CASEOPS_TEST_SIGNER_EXIT: '9' }, null],
  ['APK mutation after signature verification', { CASEOPS_TEST_MUTATE_APK: '1' }, /APK_CHANGED_DURING_SDK_INSPECTION/],
  ['source mutation after the actual preflight', { CASEOPS_TEST_MUTATE_SOURCE: '1' }, /SOURCE_OR_CONFIGURATION_CHANGED_DURING_BUILD/],
  ['policy reader mutation after the actual preflight', { CASEOPS_TEST_MUTATE_POLICY_HELPER: 'privacy-policy.cjs' }, /SOURCE_OR_CONFIGURATION_CHANGED_DURING_BUILD/],
  ['policy native plugin mutation after the actual preflight', { CASEOPS_TEST_MUTATE_POLICY_HELPER: 'with-privacy-policy.cjs' }, /SOURCE_OR_CONFIGURATION_CHANGED_DURING_BUILD/],
]) test(`orchestrator rejects ${label} and retains the failed candidate`, t => {
  const f = fixture(t, extra), result = f.run(); assert.notEqual(result.status, 0);
  if (error) assert.match(result.stdout + result.stderr, error);
  const [output] = f.outputs(); assert.ok(output); assert.equal(existsSync(path.join(output, 'receipt.json')), false);
  assert.ok(existsSync(path.join(output, 'caseops-local-acceptance-arm64.apk')));
});

test('non-Mac host and mismatched SDK pins fail before any prebuild or Gradle command', t => {
  const f = fixture(t, { CASEOPS_TEST_OS: 'Linux' }); assert.notEqual(f.run().status, 0); assert.equal(readFileSync(f.trace, 'utf8'), '');
  f.env.CASEOPS_TEST_OS = 'Darwin'; writeFileSync(path.join(f.root, 'sdk/ndk/27.1.12297006/source.properties'), 'Pkg.Revision=28.0.0\n');
  const failed = f.run(); assert.notEqual(failed.status, 0); assert.match(failed.stderr, /PINNED_ANDROID_SDK_PACKAGE_REQUIRED/);
  assert.equal(readFileSync(f.trace, 'utf8'), ''); assert.equal(f.outputs().length, 0);
});

test('missing transitive AGP Build Tools36 fails before prebuild despite root Build Tools37 being present', t => {
  const f = fixture(t); rmSync(path.join(f.root, 'sdk/build-tools/36.0.0/source.properties'));
  assert.equal(existsSync(path.join(f.root, 'sdk/build-tools/37.0.0/source.properties')), true);
  const failed = f.run(); assert.notEqual(failed.status, 0);
  assert.match(failed.stderr, /PINNED_ANDROID_SDK_PACKAGE_REQUIRED: build-tools\/36\.0\.0/);
  assert.equal(readFileSync(f.trace, 'utf8'), ''); assert.equal(f.outputs().length, 0);
});


function androidRoleInput(t) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'caseops-android-role-'))); chmodSync(root, 0o700); t.after(() => rmSync(root, { recursive: true, force: true }));
  const file = path.join(root, 'public-input'), data = Buffer.from('finite owned public role input'); writeFileSync(file, data, { flag: 'wx', mode: 0o600 });
  return { root, file, data, ref: { path: file, sha256: hash(data), sizeBytes: data.length } };
}
const androidNodeRecipe = () => ({ NODE_OPTIONS: '--use-openssl-ca --import=data:text/javascript;base64,REVIEWED', SSL_CERT_FILE: '/owned/node144/roots.pem', SSL_CERT_DIR: '/owned/node144/empty', CASEOPS_HOST_NODE_TRUST_POLICY_FILE: '/owned/node144/policy.json', CASEOPS_HOST_NODE_TRUST_POLICY_SHA256: 'a'.repeat(64) });
test('Android Gradle role keeps exact canonical argv and rejects alternate toolchain homes', () => {
  assert.deepEqual(androidGradleArguments(), ['./gradlew', ':app:assembleLocalAcceptance', '-PreactNativeArchitectures=arm64-v8a', '-Pandroid.compileSdkVersion=37', '-Pandroid.buildToolsVersion=37.0.0', '-Pandroid.ndkVersion=27.1.12297006', '-Pandroid.cmakeVersion=3.30.5', '-Pandroid.builder.sdkDownload=false', '-Dorg.gradle.java.installations.paths=/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-17.0.20.1+1/Contents/Home,/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-21.0.12.1+1/Contents/Home', '-Dorg.gradle.java.installations.auto-download=false', '--no-daemon', '--max-workers=2', '--console=plain']);
  assert.throws(() => androidGradleArguments('/unadmitted/JDK21'), /ANDROID_HOST_JAVA21/);
});
test('Android Java-neutral environment removes only the fully matched Node recipe before JDK admission', () => {
  const node = androidNodeRecipe(), original = { HOME: '/owned/home', PATH: '/owned/shim:/usr/bin:/bin', ...node, EXPO_PUBLIC_API_ORIGIN: 'https://10.0.2.2:9443' }, result = neutralAndroidGradleEnvironment(original, node);
  assert.deepEqual(result, { HOME: '/owned/home', PATH: '/owned/shim:/usr/bin:/bin', EXPO_PUBLIC_API_ORIGIN: 'https://10.0.2.2:9443' }); assert.equal(original.SSL_CERT_FILE, '/owned/node144/roots.pem');
});
test('Android role rebinding refuses mismatched missing lowercase additive Java proxy and CMake trust fields', () => {
  const node = androidNodeRecipe();
  for (const extra of [{ SSL_CERT_FILE: '/unadmitted/roots.pem' }, { NODE_OPTIONS: '--use-bundled-ca' }, { JAVA_TOOL_OPTIONS: '-Dunadmitted=true' }, { CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE: '/foreign/policy' }, { NODE_PATH: '/foreign/modules' }, { JAVA_OPTS: '-Dforeign=true' }, { GRADLE_OPTS: '-Dforeign=true' }, { CLASSPATH: '/foreign/code' }, { NODE_EXTRA_CA_CERTS: '/foreign/ca' }, { ssl_cert_file: '/foreign/ca' }, { HTTPS_PROXY: 'http://127.0.0.1:1' }, { CMAKE_TLS_VERIFY: '0' }, { CMAKE_TLS_CAINFO: '/foreign/ca' }, { CURL_SSL_BACKEND: 'foreign' }]) assert.throws(() => neutralAndroidGradleEnvironment({ ...node, ...extra }, node), /ANDROID_HOST_CROSS_ROLE_OVERRIDE/);
  const missing = { ...node }; delete missing.SSL_CERT_DIR; assert.throws(() => neutralAndroidGradleEnvironment(missing, node), /ANDROID_HOST_NODE_RECIPE_REQUIRED/);
});
test('Android role PATH binding rejects dropped shadowed duplicated and relative shim scopes', () => {
  const shim = '/owned/role/node', sourcePath = '/usr/bin:/bin';
  assertAndroidNodePath({ PATH: '/owned/role:/usr/bin:/bin' }, shim, sourcePath);
  for (const actual of ['/usr/bin:/bin', '/foreign:/owned/role:/usr/bin:/bin', '/owned/role:/usr/bin:/bin:/foreign']) assert.throws(() => assertAndroidNodePath({ PATH: actual }, shim, sourcePath), /ANDROID_HOST_NODE_SHIM_PATH_REQUIRED/);
  for (const invalid of ['/owned/role:/usr/bin', '.:/usr/bin', '/usr/bin::/bin', '/usr/bin\n/bin']) assert.throws(() => assertAndroidNodePath({ PATH: '/owned/role:' + invalid }, shim, invalid), /ANDROID_HOST_SOURCE_PATH/);
});
test('Android public role reader binds both reference shapes to the same owned descriptor and closes it', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  const open = fs.openSync, descriptors = []; fs.openSync = (...args) => { const fd = open(...args); descriptors.push(fd); return fd; };
  try { assert.deepEqual(readAndroidHostInput(f.ref), f.data); assert.deepEqual(readAndroidHostInput({ path: f.file, sha256: f.ref.sha256 }), f.data); }
  finally { fs.openSync = open; } for (const fd of descriptors) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
test('Android role reader rejects owned hardlinks and symlinks with zero payload reads', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  const read = fs.readSync, link = path.join(f.root, 'alias'); let reads = 0; fs.readSync = (...args) => { reads++; return read(...args); };
  try { fs.linkSync(f.file, link); assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_FILE/); fs.unlinkSync(link); fs.symlinkSync(f.file, link); assert.throws(() => readAndroidHostInput({ ...f.ref, path: link })); assert.equal(reads, 0); }
  finally { fs.readSync = read; }
});
test('Android role reader refuses same-owner replacement between opened and named admission before bytes', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  const fstat = fs.fstatSync, read = fs.readSync, open = fs.openSync; let changed = false, reads = 0, descriptor;
  fs.openSync = (...args) => descriptor = open(...args); fs.fstatSync = (...args) => { const state = fstat(...args); if (!changed) { changed = true; fs.renameSync(f.file, f.file + '-original'); writeFileSync(f.file, f.data, { flag: 'wx', mode: 0o600 }); } return state; }; fs.readSync = (...args) => { reads++; return read(...args); };
  try { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_FILE/); assert.equal(reads, 0); }
  finally { fs.fstatSync = fstat; fs.readSync = read; fs.openSync = open; } assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
});
test('Android role reader bounds a growing file at admitted size plus one and refuses changed content', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  const read = fs.readSync; let bytes = 0, changed = false;
  fs.readSync = (...args) => { if (!changed) { changed = true; fs.appendFileSync(f.file, Buffer.alloc(65536)); } const n = read(...args); bytes += n; return n; };
  try { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_INPUT_CHANGED/); assert.equal(bytes, f.data.length + 1); }
  finally { fs.readSync = read; }
});
test('Android role reader refuses a late parent link even when it still names the same inode and bytes', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  const child = path.join(f.root, 'child'), saved = path.join(f.root, 'saved'); mkdirSync(child, { mode: 0o700 }); fs.renameSync(f.file, path.join(child, 'input')); const reference = { ...f.ref, path: path.join(child, 'input') }, read = fs.readSync; let changed = false;
  fs.readSync = (...args) => { const n = read(...args); if (!changed) { changed = true; fs.renameSync(child, saved); fs.symlinkSync(saved, child, 'dir'); } return n; };
  try { assert.throws(() => readAndroidHostInput(reference), /ANDROID_HOST_INPUT_CHANGED/); }
  finally { fs.readSync = read; }
});
test('Android role input bounds and expired deadline refuse before reading payload', t => {
  const f = androidRoleInput(t), read = fs.readSync; let reads = 0; fs.readSync = (...args) => { reads++; return read(...args); };
  try { assert.throws(() => readAndroidHostInput(f.ref, { limit: 1 })); assert.throws(() => readAndroidHostInput(f.ref, { end: performance.now() - 1 })); assert.equal(reads, 0); }
  finally { fs.readSync = read; }
});
function actualAndroidNodeShim(t) {
  const f = androidRoleInput(t), prepared = prepareHostNodeTrust({ directory: path.join(f.root, 'node-policy'), environment: {} }), sharedRef = { path: path.join(f.root, 'shared-policy.json'), sha256: 'b'.repeat(64), sizeBytes: 1 }, javaOptions = '-Djavax.net.ssl.trustStore=/owned/shared117 -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=changeit -Duser.home=' + f.root, shim = path.join(f.root, 'node');
  writeFileSync(shim, renderAndroidNodeShim(process.execPath, prepared.environment, sharedRef, javaOptions), { flag: 'wx', mode: 0o500 });
  const environment = { HOME: f.root, TMPDIR: f.root, PATH: '/usr/bin:/bin', JAVA_TOOL_OPTIONS: javaOptions, CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE: sharedRef.path, CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256: sharedRef.sha256 };
  return { ...f, prepared, sharedRef, javaOptions, shim, environment };
}
function actualAndroidNodeEntries(f) {
  const bytes = readAndroidHostInput(f.prepared.descriptor.runtimeSource.helper), helper = 'data:text/javascript;base64,' + bytes.toString('base64'); bytes.fill(0);
  // Public fixture data travels as data, never as JSON interpolated into code.
  f.environment.CASEOPS_ANDROID_TEST_HELPER = helper;
  f.environment.CASEOPS_ANDROID_TEST_POLICY = JSON.stringify({ policyRef: f.prepared.policyRef, role: 'base' });
  const verification = "let verification;try{const value=assertHostNodeTrust(JSON.parse(process.env.CASEOPS_ANDROID_TEST_POLICY));verification={expected:value.expectedDefaultCount,verified:value.defaultEnumerationVerified};}catch(error){verification={refusal:error.message};}const facts={count:tls.getCACertificates('default').length,java:process.env.JAVA_TOOL_OPTIONS??null,...verification};";
  const report = "import tls from 'node:tls';const {assertHostNodeTrust}=await import(process.env.CASEOPS_ANDROID_TEST_HELPER);" + verification;
  writeFileSync(path.join(f.root, 'worker.mjs'), report + "import {parentPort} from 'node:worker_threads';parentPort.postMessage(facts);", { flag: 'wx', mode: 0o600 });
  writeFileSync(path.join(f.root, 'fork.mjs'), report + 'console.log(JSON.stringify(facts));', { flag: 'wx', mode: 0o600 });
  function cjsWorker(require) {
    const tls = require('node:tls'), { parentPort } = require('node:worker_threads');
    import(process.env.CASEOPS_ANDROID_TEST_HELPER).then(({ assertHostNodeTrust }) => {
      let verification;
      try {
        const value = assertHostNodeTrust(JSON.parse(process.env.CASEOPS_ANDROID_TEST_POLICY));
        verification = { expected: value.expectedDefaultCount, verified: value.defaultEnumerationVerified };
      } catch (error) { verification = { refusal: error.message }; }
      parentPort.postMessage({ count: tls.getCACertificates('default').length, java: process.env.JAVA_TOOL_OPTIONS ?? null, ...verification });
    }).catch(error => { throw error; });
  }
  // Only this fixed function body becomes code; both Worker forms share it.
  const cjs = '(' + cjsWorker.toString() + ')(require);';
  writeFileSync(path.join(f.root, 'worker.cjs'), cjs, { flag: 'wx', mode: 0o600 });
  const parent = report + `import {Worker} from 'node:worker_threads';import {spawnSync} from 'node:child_process';import {fileURLToPath} from 'node:url';const execute=(entry,options)=>new Promise((resolve,reject)=>{const w=new Worker(entry,options);w.once('message',resolve);w.once('error',reject)});const worker=await execute(new URL('./worker.mjs',import.meta.url),{});const fileEmpty=await execute(new URL('./worker.mjs',import.meta.url),{execArgv:[]});const cjsFile=await execute(new URL('./worker.cjs',import.meta.url),{eval:false});const evalMain=(${cjsWorker.toString()});const cjsEval=await execute('('+evalMain.toString()+')(require);',{eval:true,execArgv:[]});const child=spawnSync(process.execPath,[fileURLToPath(new URL('./fork.mjs',import.meta.url))],{encoding:'utf8',timeout:5000,maxBuffer:8192});if(child.status!==0)throw Error('FORK_REFUSED');console.log(JSON.stringify({...facts,worker,fileEmpty,cjsFile,cjsEval,fork:JSON.parse(child.stdout)}));`;
  const entry = path.join(f.root, 'parent.mjs'); writeFileSync(entry, parent, { flag: 'wx', mode: 0o600 }); return entry;
}
let androidWorkerComposition;
function actualAndroidWorkerFacts(t) {
  // One bounded actual composition exercises every named constructor once.
  // Retain public immutable facts for the distinct assertions, not live files.
  if (androidWorkerComposition) { if (Object.hasOwn(androidWorkerComposition, 'error')) throw androidWorkerComposition.error; return androidWorkerComposition.facts; }
  androidWorkerComposition = {};
  try {
    const f = actualAndroidNodeShim(t), entry = actualAndroidNodeEntries(f), result = spawnSync(f.shim, [entry], { env: f.environment, encoding: 'utf8', timeout: 15000, maxBuffer: 65536 }); assert.equal(result.status, 0, result.stderr);
    const facts = JSON.parse(result.stdout); for (const value of Object.values(facts)) if (value && typeof value === 'object') Object.freeze(value); Object.freeze(facts);
    androidWorkerComposition.facts = facts; return facts;
  } catch (error) { androidWorkerComposition.error = error; throw error; }
}
test('actual Android Node shim rebinds Node144 for Workers and process.execPath forks while removing Java fields', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput({ path: '/unread', sha256: 'a'.repeat(64), sizeBytes: 1 }), /ANDROID_HOST_REFERENCE/); return; }
  const result = actualAndroidWorkerFacts(t);
  const expected = { count: 144, java: null, expected: 144, verified: true };
  assert.deepEqual({ count: result.count, java: result.java, expected: result.expected, verified: result.verified, worker: result.worker, fork: result.fork }, { ...expected, worker: expected, fork: expected });
});
test('actual Android file Worker retains the effective Node144 default with empty execArgv', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput({ path: '/unread', sha256: 'a'.repeat(64), sizeBytes: 1 }), /ANDROID_HOST_REFERENCE/); return; }
  const result = actualAndroidWorkerFacts(t);
  const expected = { count: 144, java: null, expected: 144, verified: true };
  assert.deepEqual(result.fileEmpty, expected);
});
test('actual Android CJS file Worker retains the effective Node144 default with eval false', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput({ path: '/unread', sha256: 'a'.repeat(64), sizeBytes: 1 }), /ANDROID_HOST_REFERENCE/); return; }
  assert.deepEqual(actualAndroidWorkerFacts(t).cjsFile, { count: 144, java: null, expected: 144, verified: true });
});
test('actual Android CJS eval Worker with empty execArgv refuses the required effective Node144 default', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput({ path: '/unread', sha256: 'a'.repeat(64), sizeBytes: 1 }), /ANDROID_HOST_REFERENCE/); return; }
  // An empty OpenSSL enumeration is not a claim that TLS verification is off.
  // It fails this exact selected-default requirement before any HTTP request.
  assert.deepEqual(actualAndroidWorkerFacts(t).cjsEval, { count: 0, java: null, refusal: 'HOST_TRUST_EFFECTIVE_DEFAULT_MISMATCH' });
});
test('actual Android Node shim rejects conflicting Node Java CMake and extra CA state before target execution', t => {
  if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput({ path: '/unread', sha256: 'a'.repeat(64), sizeBytes: 1 }), /ANDROID_HOST_REFERENCE/); return; }
  const f = actualAndroidNodeShim(t), sentinel = path.join(f.root, 'unreached');
  for (const extra of [{ NODE_OPTIONS: '--use-bundled-ca' }, { JAVA_TOOL_OPTIONS: '-Dforeign=true' }, { JAVA_TOOL_OPTIONS: f.javaOptions.replace(' -Duser.home=' + f.root, '') }, { NODE_PATH: '/foreign/modules' }, { JAVA_OPTS: '-Dforeign=true' }, { GRADLE_OPTS: '-Dforeign=true' }, { CLASSPATH: '/foreign/code' }, { CMAKE_TLS_VERIFY: '0' }, { NODE_EXTRA_CA_CERTS: '/unadmitted/ca' }]) {
    const result = spawnSync(f.shim, ['--eval', `require('node:fs').writeFileSync(${JSON.stringify(sentinel)},'unexpected')`], { env: { ...f.environment, ...extra }, timeout: 5000, encoding: 'utf8', maxBuffer: 8192 }); assert.equal(result.status, 37); assert.equal(existsSync(sentinel), false);
  }
});
test('Android role helper and marked init inputs are in the actual wrapper source and fixture-copy closure', () => {
  const source = readFileSync(new URL('./source-snapshot.mjs', import.meta.url), 'utf8'), wrapper = readFileSync(new URL('./build-android-local-acceptance.sh', import.meta.url), 'utf8');
  for (const file of ['android-host-launch.mjs', 'android-no-paid.gradle', 'host-platform-trust.py', 'fixtures/host-platform-trust/HostPlatformTrust.java']) assert.ok(source.includes('scripts/mobile/' + file));
  assert.match(wrapper, /node "\$repo\/scripts\/mobile\/android-host-launch\.mjs" gradle -- "\$\{gradle_command\[@\]\}"/);
  assert.doesNotMatch(wrapper, /gradlew\.original|sed .*gradlew|mv .*gradlew/);
});


test('Android public reader preserves frozen and primitive body faults when close acknowledgement also fails', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  for (const original of [Object.freeze(new Error('synthetic body fault')), undefined]) {
    const read = fs.readSync, close = fs.closeSync, stderr = process.stderr.write; let closed = 0, seen = false; const diagnostics = [];
    fs.readSync = () => { throw original; }; fs.closeSync = fd => { closed++; close(fd); throw new Error('synthetic close acknowledgement failure'); }; process.stderr.write = text => { diagnostics.push(text); return true; };
    try { try { readAndroidHostInput(f.ref); } catch (error) { seen = true; assert.equal(error, original); } assert.equal(seen, true); assert.equal(closed, 1); assert.deepEqual(diagnostics, ['ANDROID_HOST_DESCRIPTOR_CLOSE\n']); }
    finally { fs.readSync = read; fs.closeSync = close; process.stderr.write = stderr; }
  }
});
test('Android role output binds the newly opened file and parent namespace before any payload write', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  const child = path.join(f.root, 'child'), moved = path.join(f.root, 'moved'); mkdirSync(child, { mode: 0o700 });
  const fstat = fs.fstatSync, write = fs.writeSync, open = fs.openSync; let changed = false, writes = 0, descriptor;
  fs.openSync = (...args) => descriptor = open(...args);
  fs.fstatSync = (...args) => { const value = fstat(...args); if (!changed) { changed = true; fs.renameSync(child, moved); fs.symlinkSync(moved, child, 'dir'); } return value; };
  fs.writeSync = (...args) => { writes++; return write(...args); };
  try { assert.throws(() => writeAndroidHostOutput(path.join(child, 'output'), f.data), /ANDROID_HOST_OUTPUT_PREWRITE_BINDING|ANDROID_HOST_OUTPUT_PREWRITE_NAMESPACE/); assert.equal(writes, 0); }
  finally { fs.fstatSync = fstat; fs.writeSync = write; fs.openSync = open; }
  assert.equal(changed, true); assert.equal(fs.lstatSync(path.join(moved, 'output')).size, 0); assert.throws(() => fs.fstatSync(descriptor), { code: 'EBADF' });
});
test('Android role output handles real partial writes and refuses same-descriptor readback corruption with closure', t => {
  const f = androidRoleInput(t); if (typeof process.getuid !== 'function') { assert.throws(() => readAndroidHostInput(f.ref), /ANDROID_HOST_REFERENCE/); return; }
  const write = fs.writeSync, read = fs.readSync, open = fs.openSync; const descriptors = []; let writes = 0;
  fs.openSync = (...args) => { const fd = open(...args); descriptors.push(fd); return fd; };
  fs.writeSync = (fd, data, offset, length, position) => { writes++; return write(fd, data, offset, Math.min(length, 2), position); };
  let reference;
  try { reference = writeAndroidHostOutput(path.join(f.root, 'partial'), f.data); }
  finally { fs.writeSync = write; fs.openSync = open; }
  assert.ok(writes > 1); assert.equal(reference.sha256, f.ref.sha256); assert.deepEqual(readAndroidHostInput(reference), f.data);
  fs.openSync = (...args) => { const fd = open(...args); descriptors.push(fd); return fd; }; let changed = false;
  fs.readSync = (fd, ...args) => { if (!changed) { changed = true; assert.ok(fs.fstatSync(fd).isFile()); write(fd, Buffer.from('X'), 0, 1, 0); } return read(fd, ...args); };
  try { assert.throws(() => writeAndroidHostOutput(path.join(f.root, 'corrupt'), f.data), /ANDROID_HOST_OUTPUT_CHANGED/); }
  finally { fs.openSync = open; fs.readSync = read; }
  assert.equal(changed, true); for (const fd of descriptors) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});
function androidJavaHomeBinding(t) {
  const f = androidRoleInput(t), sharedJavaOptions = '-Djavax.net.ssl.trustStore=/owned/shared117 -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=changeit';
  const temporaryParent = path.join(f.root, 'temporary-parent'), temporary = path.join(temporaryParent, 'tmp');
  fs.mkdirSync(temporaryParent, { mode: 0o700 }); fs.mkdirSync(temporary, { mode: 0o700 });
  const identityKeys = ['dev', 'ino', 'mode', 'uid', 'gid'], temporaryState = fs.lstatSync(temporary, { bigint: true }), parents = [];
  for (let parent = path.dirname(temporary);;) {
    const state = fs.lstatSync(parent, { bigint: true }); parents.push([parent, ...identityKeys.map(key => String(state[key]))]);
    if (parent === path.dirname(parent)) break; parent = path.dirname(parent);
  }
  const privateJavaTmp = { path: temporary, identity: identityKeys.map(key => String(temporaryState[key])), namespace: parents };
  const gradlePolicyReference = { path: path.join(f.root, 'policy.json'), sha256: 'a'.repeat(64), sizeBytes: 1 }, binding = { privateJavaHome: f.root, privateJavaTmp, sharedJavaOptions, javaOptions: sharedJavaOptions + ' -Djava.io.tmpdir=' + temporary + ' -Duser.home=' + f.root, gradlePolicyReference };
  const environment = { HOME: f.root, TMPDIR: temporary, JAVA_TOOL_OPTIONS: sharedJavaOptions, CASEOPS_HOST_PLATFORM_TRUST_POLICY_FILE: gradlePolicyReference.path, CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256: gradlePolicyReference.sha256 };
  return { ...f, binding, environment, temporary, temporaryParent };
}
test('Android Java home binding first requires the exact shared TLS3 recipe then adds only the owned property', t => {
  const f = androidJavaHomeBinding(t); if (typeof process.getuid !== 'function') { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding)); return; }
  const result = bindAndroidJavaHome(f.environment, f.binding);
  assert.deepEqual(result, { ...f.environment, JAVA_TOOL_OPTIONS: f.binding.sharedJavaOptions + ' -Djava.io.tmpdir=' + f.temporary + ' -Duser.home=' + f.root });
  assert.equal(f.environment.JAVA_TOOL_OPTIONS, f.binding.sharedJavaOptions); assert.equal(Object.keys(result).length, Object.keys(f.environment).length);
});
test('Android Java home binding refuses changed extra missing or previously home-extended shared TLS options', t => {
  const f = androidJavaHomeBinding(t); if (typeof process.getuid !== 'function') { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding)); return; }
  for (const options of [undefined, '', f.binding.javaOptions, f.binding.sharedJavaOptions + ' -Dforeign=true', f.binding.sharedJavaOptions.replace('PKCS12', 'JKS')]) assert.throws(() => bindAndroidJavaHome({ ...f.environment, JAVA_TOOL_OPTIONS: options }, f.binding), /ANDROID_GRADLE_JAVA117_RECIPE/);
  assert.throws(() => bindAndroidJavaHome(f.environment, { ...f.binding, javaOptions: f.binding.javaOptions + ' -Duser.home=/foreign' }), /ANDROID_HOST_BOUND_JAVA_OPTIONS/);
  assert.throws(() => bindAndroidJavaHome(f.environment, { ...f.binding, sharedJavaOptions: f.binding.sharedJavaOptions.replace('PKCS12', 'JKS') }), /ANDROID_HOST_SHARED_JAVA_OPTIONS/);
});
test('Android Java home binding refuses foreign HOME aliases cross-role fields and foreign policy recipes', t => {
  const f = androidJavaHomeBinding(t); if (typeof process.getuid !== 'function') { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding)); return; }
  assert.throws(() => bindAndroidJavaHome({ ...f.environment, HOME: path.dirname(f.root) }, f.binding), /ANDROID_HOST_PRIVATE_JAVA_HOME/);
  const alias = path.join(f.root, 'alias'); fs.symlinkSync(f.root, alias, 'dir'); assert.throws(() => bindAndroidJavaHome({ ...f.environment, HOME: alias }, { ...f.binding, privateJavaHome: alias, javaOptions: f.binding.sharedJavaOptions + ' -Djava.io.tmpdir=' + f.temporary + ' -Duser.home=' + alias }), /ANDROID_HOST_OWNED_DIRECTORY/);
  for (const extra of [{ SSL_CERT_FILE: '/foreign/roots' }, { NODE_OPTIONS: '--use-bundled-ca' }, { JAVA_OPTS: '-Dforeign=true' }, { java_tool_options: f.binding.sharedJavaOptions }]) assert.throws(() => bindAndroidJavaHome({ ...f.environment, ...extra }, f.binding), /ANDROID_HOST_CROSS_ROLE_OVERRIDE/);
  assert.throws(() => bindAndroidJavaHome({ ...f.environment, CASEOPS_HOST_PLATFORM_TRUST_POLICY_SHA256: 'b'.repeat(64) }, f.binding), /ANDROID_GRADLE_POLICY_RECIPE/);
});
test('Android prepare-only Gradle composition applies the strict policy reader before any output or JVM work', async t => {
  const f = androidRoleInput(t), open = fs.openSync, opened = []; fs.openSync = (...args) => { opened.push(args[0]); return open(...args); };
  try { await assert.rejects(prepareAndroidGradleEnvironment(f.ref)); }
  finally { fs.openSync = open; }
  assert.ok(opened.length <= 1 && opened.every(file => file === f.file)); assert.deepEqual(readdirSync(f.root), ['public-input']);
});
const sharedGradleDeclaration = () => ({ schemaVersion: 1, kind: 'caseops-host-gradle-jdks-trust-v1', runtimeScope: 'gradle-java21-java17', qaOnly: false, type: 'PKCS12', aliases: Object.fromEntries(Array.from({ length: 117 }, (_, i) => ['synthetic-root-' + i, i.toString(16).padStart(64, '0')])), store: { path: path.resolve(os.tmpdir(), 'owned-shared117.truststore'), sha256: 'a'.repeat(64), sizeBytes: 1000 } });
test('Android shared policy projection accepts the real DTO alias-map shape without claiming runtime admission', () => {
  const value = sharedGradleDeclaration();
  assert.equal(androidSharedJavaOptions(value), '-Djavax.net.ssl.trustStore=' + value.store.path + ' -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=changeit');
  assert.equal(Object.keys(value.aliases).length, 117); assert.equal(Object.hasOwn(value, 'runtimeVerification'), false);
});
test('Android shared policy projection refuses array aliases and malformed required production types', () => {
  const value = sharedGradleDeclaration();
  for (const aliases of [Object.values(value.aliases), null, true, Object.fromEntries(Object.entries(value.aliases).slice(1)), { ...value.aliases, 'synthetic-root-0': false }, { ...value.aliases, 'synthetic-root-0': value.aliases['synthetic-root-1'] }]) assert.throws(() => androidSharedJavaOptions({ ...value, aliases }), /ANDROID_HOST_PRODUCTION_JAVA117_ALIASES/);
  for (const extra of [{ schemaVersion: '1' }, { schemaVersion: true }, { qaOnly: 0 }, { qaOnly: true }, { runtimeScope: 'java21' }, { type: 'JKS' }]) assert.throws(() => androidSharedJavaOptions({ ...value, ...extra }), /ANDROID_HOST_PRODUCTION_JAVA117_REQUIRED/);
  for (const store of [{ ...value.store, sizeBytes: true }, { ...value.store, sha256: 1 }, { ...value.store, sha256: ['a'.repeat(64)] }, { ...value.store, path: '/unadmitted store' }]) assert.throws(() => androidSharedJavaOptions({ ...value, store }), /ANDROID_HOST_SHARED_STORE_REFERENCE/);
});

test('Android Java temporary binding rejects inherited TMPDIR drift and non-private or aliased directory', t => {
  const f = androidJavaHomeBinding(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding)); return; }
  for (const TMPDIR of [undefined, os.tmpdir(), f.root]) {
    assert.throws(() => bindAndroidJavaHome({ ...f.environment, TMPDIR }, f.binding), /ANDROID_HOST_BOUND_TMPDIR/);
  }
  fs.chmodSync(f.temporary, 0o755);
  try { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding), /ANDROID_HOST_OWNED_DIRECTORY/); }
  finally { fs.chmodSync(f.temporary, 0o700); }
  const alias = path.join(f.root, 'temporary-alias'); fs.symlinkSync(f.temporary, alias, 'dir');
  assert.throws(() => bindAndroidJavaHome({ ...f.environment, TMPDIR: alias }, { ...f.binding,
    privateJavaTmp: { ...f.binding.privateJavaTmp, path: alias } }), /ANDROID_HOST_OWNED_DIRECTORY/);
});
test('Android Java temporary binding rejects a replaced leaf inode and a replaced parent with the original leaf', t => {
  const f = androidJavaHomeBinding(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding)); return; }
  fs.renameSync(f.temporary, f.temporary + '-retained'); fs.mkdirSync(f.temporary, { mode: 0o700 });
  assert.throws(() => bindAndroidJavaHome(f.environment, f.binding), /ANDROID_HOST_PRIVATE_JAVA_TMP_IDENTITY/);
  const g = androidJavaHomeBinding(t), retainedParent = g.temporaryParent + '-retained';
  fs.renameSync(g.temporaryParent, retainedParent); fs.mkdirSync(g.temporaryParent, { mode: 0o700 });
  fs.renameSync(path.join(retainedParent, 'tmp'), g.temporary);
  assert.throws(() => bindAndroidJavaHome(g.environment, g.binding), /ANDROID_HOST_PRIVATE_JAVA_TMP_IDENTITY/);
});

test('Android Gradle execution preserves all user arguments and appends only the bound Kotlin JVM vector', t => {
  const f = androidJavaHomeBinding(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding)); return; }
  const env = { ...bindAndroidJavaHome(f.environment, f.binding), JAVA_HOME: '/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-21.0.12.1+1/Contents/Home',
    CASEOPS_ANDROID_JDK17_HOME: '/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-17.0.20.1+1/Contents/Home' };
  const args = androidGradleArguments(), before = [...args], actual = androidGradleExecutionArguments(args, f.binding, env);
  assert.deepEqual(args, before); assert.equal(actual.length, 14); assert.deepEqual(actual.slice(0, 13), before);
  assert.equal(actual[13], '-Pkotlin.daemon.jvmargs=' + f.binding.javaOptions);
  assert.equal(actual.filter(value => value.startsWith('-Pkotlin.daemon.jvmargs=')).length, 1);
});
test('Android Gradle execution rejects extra user JVM options and changed runtime options before projection', t => {
  const f = androidJavaHomeBinding(t);
  if (typeof process.getuid !== 'function') { assert.throws(() => bindAndroidJavaHome(f.environment, f.binding)); return; }
  const env = { ...bindAndroidJavaHome(f.environment, f.binding), JAVA_HOME: '/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-21.0.12.1+1/Contents/Home',
    CASEOPS_ANDROID_JDK17_HOME: '/Users/sanjeevkumar/.cache/caseops-mobile/android-mac-setup/jdks/jdk-17.0.20.1+1/Contents/Home' };
  for (const extra of ['-Pkotlin.daemon.jvmargs=-Dforeign=true', '-Pkotlin.compiler.execution.strategy=in-process', '--init-script=/foreign']) {
    assert.throws(() => androidGradleExecutionArguments([...androidGradleArguments(), extra], f.binding, env), /ANDROID_HOST_CANONICAL_GRADLE_ARGV/);
  }
  assert.throws(() => androidGradleExecutionArguments(androidGradleArguments(), f.binding, { ...env, JAVA_TOOL_OPTIONS: env.JAVA_TOOL_OPTIONS + ' -Dforeign=true' }), /ANDROID_HOST_BOUND_JAVA_OPTIONS/);
});
