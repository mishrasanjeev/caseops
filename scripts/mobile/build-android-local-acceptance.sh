#!/bin/bash
set -euo pipefail
umask 077

[[ $# = 0 ]] || { echo 'This wrapper takes explicit session environment only, no arguments.' >&2; exit 1; }
[[ "$(uname -s)" = Darwin && "$(uname -m)" = arm64 ]] || { echo 'An actual Apple Silicon Mac is required.' >&2; exit 1; }
: "${ANDROID_HOME:?Supply the owned, already-installed Android SDK}"
: "${ANDROID_SDK_ROOT:?Supply the same explicit Android SDK}"
: "${JAVA_HOME:?Supply the pinned Temurin 21 JDK home}"
: "${CASEOPS_ANDROID_JDK17_HOME:?Supply the pinned Temurin 17 toolchain home}"
: "${GRADLE_USER_HOME:?Supply an owned Gradle cache outside Git}"
: "${ANDROID_UDID:?Supply the explicitly selected dedicated target serial}"
: "${CASEOPS_MOBILE_ANDROID_CA_FILE:?Supply the isolated public CA file}"
: "${CASEOPS_MOBILE_ANDROID_CA_SHA256:?Supply its exact SHA256}"
: "${EXPO_PUBLIC_API_ORIGIN:?Supply the isolated Android HTTPS API origin}"
: "${EXPO_PUBLIC_WEB_ORIGIN:?Supply the isolated Android HTTPS web origin}"

repo="$(cd "$(dirname "$0")/../.." && pwd -P)"
build_root="${CASEOPS_ANDROID_BUILD_ROOT:-$HOME/.cache/caseops-mobile/android-builds}"
node - "$repo" "$build_root" <<'NODE'
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const [repo, output] = process.argv.slice(2);
assert.equal(process.versions.node, '24.15.0', 'PINNED_NODE_24_15_REQUIRED');
for (const value of [output, process.env.ANDROID_HOME, process.env.ANDROID_SDK_ROOT, process.env.JAVA_HOME,
  process.env.CASEOPS_ANDROID_JDK17_HOME, process.env.GRADLE_USER_HOME]) assert.ok(path.isAbsolute(value), 'ABSOLUTE_TOOL_AND_OUTPUT_PATHS_REQUIRED');
assert.equal(fs.realpathSync(process.env.ANDROID_HOME), fs.realpathSync(process.env.ANDROID_SDK_ROOT), 'ONE_EXPLICIT_ANDROID_SDK_REQUIRED');
for (const value of [output, process.env.GRADLE_USER_HOME]) {
  let ancestor = value; while (!fs.existsSync(ancestor)) ancestor = path.dirname(ancestor);
  const actual = path.resolve(fs.realpathSync(ancestor), path.relative(ancestor, value));
  assert.ok(actual !== repo && !actual.startsWith(repo + path.sep), 'BUILD_CACHE_MUST_REMAIN_OUTSIDE_REPOSITORY');
}
assert.match(process.env.ANDROID_UDID, /^[A-Za-z0-9._:-]{1,120}$/, 'EXPLICIT_DEDICATED_TARGET_SERIAL_REQUIRED');
assert.ok(fs.readFileSync(path.join(repo, 'scripts/mobile/source-snapshot.mjs'), 'utf8')
  .includes("'scripts/mobile/build-android-local-acceptance.sh'"), 'MAC_ANDROID_WRAPPER_MUST_BE_IN_SOURCE_SNAPSHOT');
// AGP9.2.1 libraries which omit buildToolsVersion retain its36.0.0 default;
// the root application separately pins37.0.0. Both are legitimate inputs.
for (const [relative, expected] of [['platforms/android-37.0/source.properties', '2'], ['build-tools/36.0.0/source.properties', '36.0.0'],
  ['build-tools/37.0.0/source.properties', '37.0.0'],
  ['ndk/27.1.12297006/source.properties', '27.1.12297006'], ['cmake/3.30.5/source.properties', '3.30.5']]) {
  assert.ok(fs.existsSync(path.join(process.env.ANDROID_HOME, relative)), `PINNED_ANDROID_SDK_PACKAGE_REQUIRED: ${relative}`);
  const body = fs.readFileSync(path.join(process.env.ANDROID_HOME, relative), 'utf8');
  assert.equal(/^Pkg\.Revision\s*=\s*(\S+)\s*$/m.exec(body)?.[1], expected, 'PINNED_ANDROID_SDK_PACKAGE_REQUIRED');
}
NODE
mkdir -p "$build_root"
run="$(mktemp -d "$build_root/android-arm64-XXXXXXXX")"
trap 'printf "Raw build evidence retained: %s\n" "$run"' EXIT

"$JAVA_HOME/bin/java" -version >"$run/java21.log" 2>&1
"$CASEOPS_ANDROID_JDK17_HOME/bin/java" -version >"$run/java17.log" 2>&1
node - "$run" <<'NODE'
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const root = process.argv[2];
assert.match(fs.readFileSync(path.join(root, 'java21.log'), 'utf8'), /Temurin-21\.0\.12\.1\+1\b/, 'PINNED_TEMURIN_21_REQUIRED');
assert.match(fs.readFileSync(path.join(root, 'java17.log'), 'utf8'), /Temurin-17\.0\.20\.1\+1\b/, 'PINNED_TEMURIN_17_REQUIRED');
NODE
export PATH="$JAVA_HOME/bin:$PATH"
export CASEOPS_MOBILE_BUILD_PROFILE=android-local-acceptance CASEOPS_MOBILE_AUTOMATED_TEST=1
export CASEOPS_MOBILE_RELEASE_SHA="$(git -C "$repo" rev-parse HEAD)"
export NODE_ENV=production EXPO_NO_DOTENV=1 CMAKE_BUILD_PARALLEL_LEVEL=2
proof="$repo/scripts/mobile/build-acceptance.mjs"
aapt="$ANDROID_HOME/build-tools/37.0.0/aapt2"
apksigner="$ANDROID_HOME/build-tools/37.0.0/apksigner"
[[ -x "$aapt" && -x "$apksigner" ]] || { echo 'Pinned AAPT2 and apksigner are required; no SDK installation is performed.' >&2; exit 1; }
cd "$repo/apps/mobile"
node "$proof" check android "$run/before.json" 2>&1 | tee "$run/check.log"
node ./node_modules/expo/bin/cli prebuild --platform android --no-install 2>&1 | tee "$run/prebuild.log"
node - "$PWD/android" "$run" <<'NODE'
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const [android, output] = process.argv.slice(2), file = path.join(android, 'gradle/wrapper/gradle-wrapper.properties');
let body = fs.readFileSync(file, 'utf8');
assert.equal(/^distributionUrl=(.+)$/m.exec(body)?.[1], 'https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip', 'PINNED_GRADLE_DISTRIBUTION_REQUIRED');
const digest = '2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb';
const existing = /^distributionSha256Sum=(.*)$/m.exec(body);
if (existing) assert.equal(existing[1], digest, 'PINNED_GRADLE_CHECKSUM_REQUIRED');
else { body += `\ndistributionSha256Sum=${digest}\n`; fs.writeFileSync(file, body); }
const inputs = ['build.gradle', 'settings.gradle', 'gradle.properties', 'app/build.gradle', 'gradle/wrapper/gradle-wrapper.properties'];
const files = inputs.map(relative => { const data = fs.readFileSync(path.join(android, relative));
  fs.writeFileSync(path.join(output, relative.replaceAll('/', '-')), data, { flag: 'wx' });
  return { relativePath: relative, sha256: crypto.createHash('sha256').update(data).digest('hex'), sizeBytes: data.length }; });
fs.writeFileSync(path.join(output, 'generated-android-inputs.json'), JSON.stringify({ schemaVersion: 1, files }, null, 2) + '\n', { flag: 'wx' });
NODE
(
  cd android
  ./gradlew :app:assembleLocalAcceptance -PreactNativeArchitectures=arm64-v8a \
    -Pandroid.compileSdkVersion=37 -Pandroid.buildToolsVersion=37.0.0 \
    -Pandroid.ndkVersion=27.1.12297006 -Pandroid.cmakeVersion=3.30.5 -Pandroid.builder.sdkDownload=false \
    "-Dorg.gradle.java.installations.paths=$CASEOPS_ANDROID_JDK17_HOME,$JAVA_HOME" \
    -Dorg.gradle.java.installations.auto-download=false --no-daemon --max-workers=2 --console=plain
) 2>&1 | tee "$run/gradle.log"
apk="$run/caseops-local-acceptance-arm64.apk"
cp android/app/build/outputs/apk/localAcceptance/app-localAcceptance.apk "$apk"
node - "$apk" "$run/apk-before-inspection.json" <<'NODE'
const fs = require('node:fs'), crypto = require('node:crypto');
const [apk, output] = process.argv.slice(2), sha256 = crypto.createHash('sha256').update(fs.readFileSync(apk)).digest('hex');
fs.writeFileSync(output, JSON.stringify({ sha256 }) + '\n', { flag: 'wx' });
NODE
"$aapt" dump badging "$apk" >"$run/apk-badging.log" 2>"$run/apk-badging.stderr"
"$apksigner" verify --verbose --print-certs "$apk" >"$run/apk-signing.log" 2>"$run/apk-signing.stderr"
node "$proof" android-resources "$run/before.json" "$apk" "$aapt" "$run" "$run/android-resources.json" 2>&1 | tee "$run/resources.log"
python3 - "$run" "$apk" <<'PY'
import hashlib,json,pathlib,re,sys,zipfile
root,apk=pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2])
assert 0 < apk.stat().st_size <= 512*1024*1024, 'APK_FILE_SIZE_BOUND'
plan=json.loads((root/'android-resources.json').read_text())
with zipfile.ZipFile(apk) as source:
    entries=source.infolist();assert 0 < len(entries) <= 30000, 'APK_ZIP_ENTRY_BOUND'
    names=[entry.filename for entry in entries];assert len(set(names))==len(names), 'DUPLICATE_APK_ZIP_ENTRY'
    assert sum(entry.file_size for entry in entries) <= 1024*1024*1024, 'APK_UNCOMPRESSED_SIZE_BOUND'
    for name in names:
        parts=pathlib.PurePosixPath(name).parts
        assert not name.startswith('/') and not any(part in ['.','..'] for part in parts) and not re.search(r'[\\:%\x00-\x1f\x7f]',name), 'UNSAFE_ZIP_PATH'
    libraries=[entry for entry in entries if entry.filename.startswith('lib/') and entry.filename.endswith('.so')]
    assert 0 < len(libraries) <= 256 and all(re.fullmatch(r'lib/[^/]+/[^/]+\.so',entry.filename) for entry in libraries), 'BOUNDED_NATIVE_LIBRARY_INVENTORY_REQUIRED'
    abis=sorted({entry.filename.split('/')[1] for entry in libraries})
    assert abis==['arm64-v8a'], 'ARM64_ONLY_NATIVE_LIBRARIES_REQUIRED'
    for entry in libraries:
        assert 64 <= entry.file_size <= 128*1024*1024, 'NATIVE_LIBRARY_SIZE_BOUND'
        with source.open(entry) as library:header=library.read(20)
        assert header[:6]==b'\x7fELF\x02\x01' and int.from_bytes(header[16:18],'little')==3 and int.from_bytes(header[18:20],'little')==183, 'AARCH64_SHARED_ELF_REQUIRED'
    for name,target,limit in [(plan['ca']['path'],'public-ca-from-apk.pem',16384),('assets/app.config','embedded-config.json',1048576)]:
        entry=source.getinfo(name);assert 0 < entry.file_size <= limit,'BOUNDED_APK_INPUT_REQUIRED'
        with (root/target).open('xb') as output:output.write(source.read(entry))
    with (root/'apk-zip-inventory.json').open('x') as output:json.dump([{'name':e.filename,'length':e.file_size} for e in entries],output)
    with (root/'apk-abi.json').open('x') as output:json.dump({'schemaVersion':1,'abis':abis,'nativeLibraryCount':len(libraries),'elfClass':64,'elfMachine':183},output)
PY
node "$proof" android-zip "$run/android-resources.json" "$run/apk-zip-inventory.json" "$run/public-ca-from-apk.pem" "$run/before.json" "$apk" "$run/android-security.json" 2>&1 | tee "$run/zip.log"
node - "$run" "$apk" <<'NODE'
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const [root, apk] = process.argv.slice(2), digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const badging = fs.readFileSync(path.join(root, 'apk-badging.log'), 'utf8'), signing = fs.readFileSync(path.join(root, 'apk-signing.log'), 'utf8');
assert.ok(Buffer.byteLength(badging) <= 1048576 && Buffer.byteLength(signing) <= 1048576, 'BOUNDED_SDK_IDENTITY_OUTPUT_REQUIRED');
const identity = /^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'/m.exec(badging);
assert.equal(identity?.[1], 'ai.caseops.mobile.dev.localacceptance', 'EXACT_QA_PACKAGE_REQUIRED');
assert.doesNotMatch(badging, /^application-debuggable/m, 'NON_DEBUGGABLE_APK_REQUIRED');
assert.equal(/^native-code: (.+)$/m.exec(badging)?.[1], "'arm64-v8a'", 'AAPT_ARM64_ONLY_REQUIRED');
const signingLines = signing.split(/\r?\n/);
assert.equal(signingLines.filter(line => line === 'Verifies').length, 1, 'APK_SIGNATURE_VERIFICATION_REQUIRED');
assert.ok(!signingLines.some(line => line.includes('DOES NOT VERIFY')), 'APK_SIGNATURE_VERIFICATION_REQUIRED');
assert.deepEqual(signingLines.filter(line => line.startsWith('Verified using v2 scheme')),
  ['Verified using v2 scheme (APK Signature Scheme v2): true'], 'APK_V2_SIGNATURE_REQUIRED');
assert.deepEqual(signingLines.filter(line => line.startsWith('Number of signers:')), ['Number of signers: 1'], 'ONE_APK_SIGNER_REQUIRED');
const certificates = signingLines.filter(line => line.includes('certificate SHA-256 digest:'));
assert.equal(certificates.length, 1, 'ONE_APK_SIGNER_REQUIRED');
const certificate = /^(?:Signer #1 certificate|V2 Signer: certificate) SHA-256 digest: ([a-fA-F0-9]{64})$/.exec(certificates[0]);
assert.ok(certificate, 'ONE_APK_SIGNER_REQUIRED');
const artifactSha256 = digest(fs.readFileSync(apk));
assert.equal(artifactSha256, JSON.parse(fs.readFileSync(path.join(root, 'apk-before-inspection.json'), 'utf8')).sha256, 'APK_CHANGED_DURING_SIGNING_OR_ABI_INSPECTION');
assert.ok(Number.isSafeInteger(Number(identity[2])) && Number(identity[2]) > 0, 'POSITIVE_APK_VERSION_CODE_REQUIRED');
const refs = ['apk-badging.log', 'apk-signing.log', 'apk-abi.json', 'generated-android-inputs.json', 'java21.log', 'java17.log']
  .map(name => ({ path: path.join(root, name), sha256: digest(fs.readFileSync(path.join(root, name))) }));
const proof = { schemaVersion: 1, kind: 'android-local-arm64-signature-proof', appId: identity[1], artifactSha256,
  versionCode: Number(identity[2]), versionName: identity[3], architecture: 'arm64-v8a', signatureVerified: true, signatureSchemeV2: true,
  certificateSha256: certificate[1].toLowerCase(), intendedDeviceSerial: process.env.ANDROID_UDID, evidence: refs,
  distributionSigning: false, nativeExecution: 'not-run-by-build-wrapper' };
const output = path.join(root, 'android-native-proof.json'), bytes = Buffer.from(JSON.stringify(proof, null, 2) + '\n');
fs.writeFileSync(output, bytes, { flag: 'wx' });
const security = JSON.parse(fs.readFileSync(path.join(root, 'android-security.json'), 'utf8'));
assert.equal(security.apkSha256, artifactSha256, 'ANDROID_NATIVE_PROOF_ARTIFACT_MISMATCH');
security.nativeArtifactEvidence = { path: output, sha256: digest(bytes) };
fs.writeFileSync(path.join(root, 'android-security-final.json'), JSON.stringify(security, null, 2) + '\n', { flag: 'wx' });
NODE
node "$proof" finish android "$run/before.json" "$apk" "$run/embedded-config.json" "$run/receipt.json" "$run/android-security-final.json" 2>&1 | tee "$run/finish.log"
printf 'Standalone local ARM64 APK and verified build receipt: %s\n' "$run/receipt.json"
printf 'Build only; owner separately installs the exact APK and runs Android native acceptance.\n'
