const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { createHash, X509Certificate } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const observer = require('./qa-observer.cjs');
const { withAppBuildGradle, withDangerousMod } = require('@expo/config-plugins');

const ANDROID_PROFILE = 'android-local-acceptance';
const IOS_PROFILE = 'ios-simulator-acceptance';
const ANDROID_APP_ID = 'ai.caseops.mobile.dev.localacceptance';
const IOS_BUNDLE_ID = 'ai.caseops.mobile.dev.simulatoracceptance';
const START = '// BEGIN CaseOps generated local acceptance';
const END = '// END CaseOps generated local acceptance';
const GENERATED_FILES = [
  'AndroidManifest.xml',
  'res/raw/caseops_local_acceptance_ca.pem',
  'res/xml/caseops_local_acceptance_network.xml',
  'res/values/caseops_local_acceptance.xml',
];

function localOrigin(value, platform) {
  assert.equal(typeof value, 'string', 'EXPLICIT_ACCEPTANCE_ORIGINS_REQUIRED');
  const url = new URL(value);
  const hosts = platform === 'android'
    ? ['10.0.2.2', '127.0.0.1', 'localhost'] : ['127.0.0.1', 'localhost'];
  assert.ok(url.protocol === 'https:' && hosts.includes(url.hostname)
    && value === url.origin && !url.username && !url.password
    && Number(url.port) >= 1024 && Number(url.port) <= 65535, 'LOCAL_HTTPS_ORIGIN_REQUIRED');
  return url;
}

function readPublicCa(file, expectedSha256, now = Date.now()) {
  assert.ok(file && path.isAbsolute(file), 'EXTERNAL_PUBLIC_CA_FILE_REQUIRED');
  assert.match(expectedSha256 || '', /^[a-f0-9]{64}$/, 'PUBLIC_CA_SHA256_REQUIRED');
  const resolved = fs.realpathSync(file);
  const fd = fs.openSync(resolved, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
  try {
    const opened = fs.fstatSync(fd, { bigint: true });
    assert.ok(opened.isFile() && opened.size > 0n && opened.size <= 16384n, 'PUBLIC_CA_SIZE_BOUND');
    const named = fs.lstatSync(resolved, { bigint: true });
    // Windows lstat reports dev=0 while fstat supplies a volume identity.
    assert.ok(named.isFile() && !named.isSymbolicLink() && named.ino === opened.ino
      && (process.platform === 'win32' || named.dev === opened.dev), 'PUBLIC_CA_FILE_REPLACED');
    const git = spawnSync('git', ['rev-parse', '--is-inside-work-tree'], {
      cwd: path.dirname(resolved), encoding: 'utf8', windowsHide: true,
      env: { ...process.env, LC_ALL: 'C', LANG: 'C' },
    });
    assert.ok(!git.error && git.status === 128 && /not a git repository/.test(git.stderr), 'PUBLIC_CA_MUST_BE_OUTSIDE_GIT');
    const pem = fs.readFileSync(fd, 'utf8');
    const after = fs.fstatSync(fd, { bigint: true });
    assert.ok(opened.size === after.size && opened.mtimeNs === after.mtimeNs && opened.ctimeNs === after.ctimeNs
      && BigInt(Buffer.byteLength(pem)) === opened.size, 'PUBLIC_CA_FILE_CHANGED');
    assert.match(pem, /^-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+\r?\n-----END CERTIFICATE-----\r?\n?$/, 'ONE_PUBLIC_CERTIFICATE_ONLY');
    const sha256 = createHash('sha256').update(pem).digest('hex');
    assert.equal(sha256, expectedSha256, 'PUBLIC_CA_HASH_MISMATCH');
    const cert = new X509Certificate(pem);
    assert.ok(cert.ca && cert.checkIssued(cert) && cert.verify(cert.publicKey), 'SELF_SIGNED_CA_REQUIRED');
    assert.ok(Date.parse(cert.validFrom) <= now && now < Date.parse(cert.validTo), 'PUBLIC_CA_NOT_CURRENT');
    return { pem, sha256, fingerprint256: cert.fingerprint256 };
  } finally { fs.closeSync(fd); }
}

function acceptanceSettings(env) {
  const profile = env.CASEOPS_MOBILE_BUILD_PROFILE;
  const observerSettings = observer.settings(env, profile);
  const hasCa = Boolean(env.CASEOPS_MOBILE_ANDROID_CA_FILE || env.CASEOPS_MOBILE_ANDROID_CA_SHA256);
  if (!profile) {
    assert.ok(!hasCa, 'CA_REQUIRES_ANDROID_ACCEPTANCE_PROFILE');
    return null;
  }
  assert.ok([ANDROID_PROFILE, IOS_PROFILE].includes(profile), 'UNKNOWN_MOBILE_BUILD_PROFILE');
  assert.equal(env.CASEOPS_MOBILE_AUTOMATED_TEST, '1', 'AUTOMATED_MARKER_REQUIRED');
  assert.match(env.CASEOPS_MOBILE_RELEASE_SHA || '', /^[a-f0-9]{40}$/, 'EXACT_SOURCE_SHA_REQUIRED');
  assert.ok(!env.EX_UPDATES_NATIVE_DEBUG && !env.SKIP_BUNDLING, 'STANDALONE_BUNDLING_REQUIRED');
  const platform = profile === ANDROID_PROFILE ? 'android' : 'ios';
  const api = localOrigin(env.EXPO_PUBLIC_API_ORIGIN, platform);
  const web = localOrigin(env.EXPO_PUBLIC_WEB_ORIGIN, platform);
  if (platform === 'ios') assert.ok(!hasCa, 'ANDROID_CA_FORBIDDEN_ON_IOS');
  const ca = platform === 'android'
    ? readPublicCa(env.CASEOPS_MOBILE_ANDROID_CA_FILE, env.CASEOPS_MOBILE_ANDROID_CA_SHA256) : null;
  return { profile, platform, apiOrigin: api.origin, webOrigin: web.origin,
    hosts: [...new Set([api.hostname, web.hostname])], ca,
    releaseSha: env.CASEOPS_MOBILE_RELEASE_SHA,
    ...(observerSettings ? { observer: { ...observerSettings, sourceRoot: path.resolve(__dirname, '../../..'), helperSha256: createHash('sha256').update(observer.held(path.resolve(__dirname, '../../../scripts/mobile/android-observer-manifest.py'), 65536)).digest('hex') } } : {}),
    androidAppId: ANDROID_APP_ID,
    iosBundleIdentifier: platform === 'ios' ? IOS_BUNDLE_ID : undefined };
}

function networkSecurityXml(settings) {
  const otherLoopbacks = ['localhost', 'ip6-localhost', '127.0.0.1', '[::1]']
    .filter((host) => !settings.hosts.includes(host));
  return `<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false">
    <trust-anchors><certificates src="system" /></trust-anchors>
  </base-config>
  <!-- Override Android 17's implicit cleartext localhost allowance without adding QA trust. -->
  <domain-config cleartextTrafficPermitted="false">
${otherLoopbacks.map((host) => `    <domain includeSubdomains="false">${host}</domain>`).join('\n')}
    <trust-anchors><certificates src="system" /></trust-anchors>
  </domain-config>
  <domain-config cleartextTrafficPermitted="false">
${settings.hosts.map((host) => `    <domain includeSubdomains="false">${host}</domain>`).join('\n')}
    <trust-anchors><certificates src="@raw/caseops_local_acceptance_ca" /></trust-anchors>
  </domain-config>
</network-security-config>
`;
}

function gradleBlock(settings) {
  // This is a standard non-debug build type: RN bundles it, dependencies fall back to release.
  return `${START}
def caseopsAcceptanceExpected = ${JSON.stringify({
    CASEOPS_MOBILE_BUILD_PROFILE: ANDROID_PROFILE,
    CASEOPS_MOBILE_AUTOMATED_TEST: '1',
    CASEOPS_MOBILE_RELEASE_SHA: settings.releaseSha,
    EXPO_PUBLIC_API_ORIGIN: settings.apiOrigin,
    EXPO_PUBLIC_WEB_ORIGIN: settings.webOrigin,
    CASEOPS_MOBILE_ANDROID_CA_SHA256: settings.ca.sha256,
  }).replace(/^\{/, '[').replace(/\}$/, ']')}
caseopsAcceptanceExpected.each { key, expected ->
    if (System.getenv(key) != expected) throw new GradleException("Acceptance configuration changed; rerun the acceptance prebuild: " + key)
}
if (System.getenv('EX_UPDATES_NATIVE_DEBUG') || System.getenv('SKIP_BUNDLING') ||
    findProperty('expo.devlauncher.configureInRelease') == 'true') {
    throw new GradleException('Standalone acceptance cannot enable development launcher or skip bundling')
}
def caseopsCaBytes = file('src/localAcceptance/res/raw/caseops_local_acceptance_ca.pem').bytes
if (java.security.MessageDigest.getInstance('SHA-256').digest(caseopsCaBytes).encodeHex().toString() != caseopsAcceptanceExpected.CASEOPS_MOBILE_ANDROID_CA_SHA256) {
    throw new GradleException('Acceptance public CA changed; rerun prebuild')
}
android {
    buildTypes {
        localAcceptance {
            initWith release
            debuggable false
            applicationIdSuffix '.localacceptance'
            matchingFallbacks = ['release']
            signingConfig signingConfigs.debug
        }
    }
}
// A QA-configured generated project may never package that config as the default app.
androidComponents {
    beforeVariants(selector().all()) { variant ->
        if (variant.buildType != 'localAcceptance') variant.enable = false
    }
}
if (extensions.getByType(com.facebook.react.ReactExtension).debuggableVariants.get().any { it.equalsIgnoreCase('localAcceptance') }) {
    throw new GradleException('Acceptance must use the supported non-debug bundling path')
}
${settings.observer ? observer.gradle(settings.observer, settings.observer.sourceRoot, settings.releaseSha, settings.observer.helperSha256) : ''}
${END}`;
}

function updateGradle(contents, settings) {
  const start = contents.indexOf(START);
  const end = contents.indexOf(END);
  assert.ok((start === -1 && end === -1) || (start >= 0 && end > start
    && contents.indexOf(START, start + START.length) === -1
    && contents.indexOf(END, end + END.length) === -1), 'GENERATED_GRADLE_MARKERS_INVALID');
  if (start >= 0) assert.equal(contents[start - 1], '\n', 'GENERATED_GRADLE_MARKERS_INVALID');
  const clean = start < 0 ? contents : contents.slice(0, start - 1) + contents.slice(end + END.length).replace(/^\n/, '');
  if (!settings || settings.platform !== 'android') return clean;
  return `${clean}\n${gradleBlock(settings)}\n`;
}

function writeAndroidOverlay(androidRoot, settings) {
  const root = path.join(androidRoot, 'app/src/localAcceptance');
  // Only touch the four files this plugin owns, never recursively remove a native tree.
  const files = settings?.platform === 'android' ? {
    'AndroidManifest.xml': `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" xmlns:tools="http://schemas.android.com/tools">
  <application android:networkSecurityConfig="@xml/caseops_local_acceptance_network" android:usesCleartextTraffic="false" tools:replace="android:usesCleartextTraffic" />
</manifest>
`,
    'res/raw/caseops_local_acceptance_ca.pem': settings.ca.pem,
    'res/xml/caseops_local_acceptance_network.xml': networkSecurityXml(settings),
    'res/values/caseops_local_acceptance.xml': '<?xml version="1.0" encoding="utf-8"?>\n<resources><string name="app_name">CaseOps Local Acceptance</string></resources>\n',
  } : {};
  for (const relative of GENERATED_FILES) {
    const target = path.join(root, relative);
    if (relative in files) {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, files[relative]);
    } else if (fs.existsSync(target)) fs.unlinkSync(target);
  }
}

// Pin the reviewed runtime for both production and local Android projects.
function pinGradleWrapper(androidRoot) {
  const file = path.join(androidRoot, 'gradle/wrapper/gradle-wrapper.properties');
  const fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_NOFOLLOW);
  try {
    const before = fs.fstatSync(fd, { bigint: true });
    const frame = value => ['ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs', ...(process.platform === 'win32' ? [] : ['dev'])].map(key => String(value[key]));
    assert.ok(before.isFile() && before.nlink === 1n && before.uid === BigInt(process.getuid?.() ?? 0) && before.size > 0n && before.size <= 32768n, 'GRADLE_WRAPPER_OWNED_REGULAR_INPUT');
    assert.deepEqual(frame(fs.lstatSync(file, { bigint: true })), frame(before));
    const input = fs.readFileSync(fd, 'utf8');
    assert.equal(BigInt(Buffer.byteLength(input)), before.size);
    assert.deepEqual(frame(fs.fstatSync(fd, { bigint: true })), frame(before));
    assert.deepEqual(frame(fs.lstatSync(file, { bigint: true })), frame(before));
    const keys = new Set();
    for (const line of input.split('\n')) {
      if (line === '' || /^\s*[#!]/.test(line)) continue;
      const row = /^(distributionBase|distributionPath|distributionUrl|zipStoreBase|zipStorePath|networkTimeout|validateDistributionUrl|distributionSha256Sum)=([^\r\n\0]*)$/.exec(line);
      assert.ok(row && !row[2].endsWith('\\') && !keys.has(row[1]), 'CANONICAL_UNAMBIGUOUS_GRADLE_WRAPPER_PROPERTIES');
      keys.add(row[1]);
    }
    const urls = [...input.matchAll(/^distributionUrl=(.*)$/gm)];
    const sums = [...input.matchAll(/^distributionSha256Sum=(.*)$/gm)];
    assert.equal(urls.length, 1, 'EXACT_GRADLE_WRAPPER_URL');
    assert.ok(sums.length <= 1, 'EXACT_GRADLE_WRAPPER_CHECKSUM');
    const oldUrl = 'https\\://services.gradle.org/distributions/gradle-9.4.1-bin.zip';
    const newUrl = 'https\\://services.gradle.org/distributions/gradle-9.9.2-bin.zip';
    const oldSha = '2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb';
    const newSha = '971fcd7150ca4ba04852c0b2ca0d2d0ab9468e14b03473eab19528809914c76b';
    assert.ok(urls[0][1] === oldUrl || urls[0][1] === newUrl, 'REVIEWED_GRADLE_WRAPPER_SOURCE');
    if (urls[0][1] === newUrl) assert.equal(sums[0]?.[1], newSha, 'PINNED_GRADLE_CHECKSUM_REQUIRED');
    else if (sums.length) assert.equal(sums[0][1], oldSha, 'REVIEWED_GRADLE_TEMPLATE_CHECKSUM');
    let output = input.replace(urls[0][0], 'distributionUrl=' + newUrl);
    output = sums.length ? output.replace(sums[0][0], 'distributionSha256Sum=' + newSha) : output + (output.endsWith('\n') ? '' : '\n') + 'distributionSha256Sum=' + newSha + '\n';
    assert.ok(Buffer.byteLength(output) <= 32768, 'GRADLE_WRAPPER_OUTPUT_BOUND');
    if (output !== input) {
      const bytes = Buffer.from(output);
      let written = 0;
      while (written < bytes.length) written += fs.writeSync(fd, bytes, written, bytes.length - written, written);
      fs.ftruncateSync(fd, bytes.length);
    }
    const after = fs.fstatSync(fd, { bigint: true });
    assert.equal(after.ino, before.ino);
    const verified = Buffer.alloc(Buffer.byteLength(output) + 1);
    assert.equal(fs.readSync(fd, verified, 0, verified.length, 0), Buffer.byteLength(output));
    assert.equal(verified.subarray(0, Buffer.byteLength(output)).toString('utf8'), output);
    assert.deepEqual(frame(fs.fstatSync(fd, { bigint: true })), frame(after));
    assert.deepEqual(frame(fs.lstatSync(file, { bigint: true })), frame(after));
  } finally { fs.closeSync(fd); }
}

function withLocalAcceptance(config) {
  const settings = acceptanceSettings(process.env);
  config = withAppBuildGradle(config, (mod) => {
    assert.equal(mod.modResults.language, 'groovy', 'GROOVY_EXPO_TEMPLATE_REQUIRED');
    mod.modResults.contents = updateGradle(mod.modResults.contents, settings);
    return mod;
  });
  config = withDangerousMod(config, ['android', (mod) => {
    assert.ok(!settings || settings.platform === 'android', 'IOS_ACCEPTANCE_CANNOT_PREBUILD_ANDROID');
    pinGradleWrapper(mod.modRequest.platformProjectRoot);
    writeAndroidOverlay(mod.modRequest.platformProjectRoot, settings);
    observer.overlay(mod.modRequest.platformProjectRoot, path.resolve(mod.modRequest.projectRoot, '../..'), settings?.observer ?? null, settings?.releaseSha);
    return mod;
  }]);
  return withDangerousMod(config, ['ios', (mod) => {
    assert.ok(!settings || settings.platform === 'ios', 'ANDROID_ACCEPTANCE_CANNOT_PREBUILD_IOS');
    return mod;
  }]);
}

module.exports = withLocalAcceptance;
Object.assign(module.exports, { acceptanceSettings, localOrigin, readPublicCa,
  networkSecurityXml, updateGradle, writeAndroidOverlay,
  pinGradleWrapper, ANDROID_PROFILE, IOS_PROFILE, ANDROID_APP_ID, IOS_BUNDLE_ID });
