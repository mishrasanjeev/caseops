const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { createHash, X509Certificate } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
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
  const git = spawnSync('git', ['rev-parse', '--is-inside-work-tree'], {
    cwd: path.dirname(resolved), encoding: 'utf8', windowsHide: true,
    env: { ...process.env, LC_ALL: 'C', LANG: 'C' },
  });
  assert.ok(!git.error && git.status === 128 && /not a git repository/.test(git.stderr), 'PUBLIC_CA_MUST_BE_OUTSIDE_GIT');
  const size = fs.statSync(resolved).size;
  assert.ok(size > 0 && size <= 16384, 'PUBLIC_CA_SIZE_BOUND');
  const pem = fs.readFileSync(resolved, 'utf8');
  assert.match(pem, /^-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+\r?\n-----END CERTIFICATE-----\r?\n?$/, 'ONE_PUBLIC_CERTIFICATE_ONLY');
  const sha256 = createHash('sha256').update(pem).digest('hex');
  assert.equal(sha256, expectedSha256, 'PUBLIC_CA_HASH_MISMATCH');
  const cert = new X509Certificate(pem);
  assert.ok(cert.ca && cert.checkIssued(cert) && cert.verify(cert.publicKey), 'SELF_SIGNED_CA_REQUIRED');
  assert.ok(Date.parse(cert.validFrom) <= now && now < Date.parse(cert.validTo), 'PUBLIC_CA_NOT_CURRENT');
  return { pem, sha256, fingerprint256: cert.fingerprint256 };
}

function acceptanceSettings(env) {
  const profile = env.CASEOPS_MOBILE_BUILD_PROFILE;
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

function withLocalAcceptance(config) {
  const settings = acceptanceSettings(process.env);
  config = withAppBuildGradle(config, (mod) => {
    assert.equal(mod.modResults.language, 'groovy', 'GROOVY_EXPO_TEMPLATE_REQUIRED');
    mod.modResults.contents = updateGradle(mod.modResults.contents, settings);
    return mod;
  });
  config = withDangerousMod(config, ['android', (mod) => {
    assert.ok(!settings || settings.platform === 'android', 'IOS_ACCEPTANCE_CANNOT_PREBUILD_ANDROID');
    writeAndroidOverlay(mod.modRequest.platformProjectRoot, settings);
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
  ANDROID_PROFILE, IOS_PROFILE, ANDROID_APP_ID, IOS_BUNDLE_ID });
