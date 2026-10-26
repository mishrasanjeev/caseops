import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash, X509Certificate } from 'node:crypto';
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { rootCertificates } from 'node:tls';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

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
  const files = ['scripts/mobile/build-android-local-acceptance.sh', 'scripts/mobile/build-acceptance.mjs', 'scripts/mobile/source-snapshot.mjs',
    'scripts/mobile/prepare-native-links.mjs', 'apps/mobile/metro.config.js',
    'apps/web/lib/native-link-policy.cjs', 'apps/web/lib/native-link-policy.d.cts',
    'apps/web/lib/native-link-config.cjs', 'apps/web/lib/native-link-config.d.cts',
    'scripts/mobile/prepare-viewer-assets.mjs', 'apps/mobile/src/viewer/renderer-runtime.ts',
    ...['LICENSES.txt', 'manifest.json', 'pdfjs-assets.ts', 'renderer-runtime-source.ts'].map(name => `apps/mobile/src/viewer/generated/${name}`),
    'apps/mobile/package.json', 'apps/mobile/app.config.ts', 'apps/mobile/plugins/with-local-acceptance.cjs', 'apps/mobile/e2e/support.mjs'];
  for (const name of files) { const destination = path.join(checkout, name); mkdirSync(path.dirname(destination), { recursive: true }); copyFileSync(path.join(repo, name), destination); }
  // Trace actual source capture in the temporary contract fixture, so an order
  // assertion cannot pass merely because the wrapper contains command strings.
  const snapshot = path.join(checkout, 'scripts/mobile/source-snapshot.mjs');
  writeFileSync(snapshot, readFileSync(snapshot, 'utf8')
    .replace("import { readFileSync } from 'node:fs';", "import { appendFileSync, readFileSync } from 'node:fs';")
    .replace('  const paths = [', "  appendFileSync(process.env.CASEOPS_TEST_TRACE, 'source-snapshot\\n');\n  const paths = ["));
  file('repo/package.json', '{"type":"module"}\n'); file('repo/.gitignore', 'node_modules/\napps/mobile/android/\n');
  mkdirSync(path.join(checkout, 'apps/mobile/node_modules'), { recursive: true });
  symlinkSync(path.join(repo, 'apps/mobile/node_modules/@expo'), path.join(checkout, 'apps/mobile/node_modules/@expo'), 'dir');
  for (const module of ['expo-secure-store', 'expo-web-browser', 'pdfjs-dist'])
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
  for (const input of ['scripts/mobile/prepare-native-links.mjs', 'apps/mobile/metro.config.js',
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
