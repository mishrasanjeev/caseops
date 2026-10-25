import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash, X509Certificate } from 'node:crypto';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { rootCertificates } from 'node:tls';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const app = fileURLToPath(new URL('../../apps/mobile/', import.meta.url));
const repo = path.resolve(app, '../..');
const require = createRequire(path.join(app, 'package.json'));
const plugin = require(path.join(app, 'plugins/with-local-acceptance.cjs'));
const { compileModsAsync, XML } = require('@expo/config-plugins');
const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim();
const certificate = `${rootCertificates.find((pem) => {
  const cert = new X509Certificate(pem);
  return cert.ca && cert.checkIssued(cert) && cert.verify(cert.publicKey)
    && Date.parse(cert.validFrom) < Date.now() && Date.now() < Date.parse(cert.validTo);
}).trim()}\n`;
const digest = (value) => createHash('sha256').update(value).digest('hex');

test('Windows native staging is short, outside sources, module-isolated and part of build evidence', () => {
  const init = readFileSync(path.join(repo,'scripts/mobile/windows-native-paths.gradle'),'utf8');
  assert.match(init, /gradle\.beforeProject/);
  assert.match(init, /components\.finalizeDsl/);
  assert.match(init, /dsl\.externalNativeBuild\.cmake\.buildStagingDirectory = staging\.resolve\(module\)/);
  assert.match(init, /!staging\.startsWith\(owned\)/);
  assert.match(init, /substring\(0, 12\)/);
  assert.doesNotMatch(init, /delete\(|deleteDir|exec\(|debuggable|cleartext|LongPathsEnabled/);
  const wrapper=readFileSync(path.join(repo,'scripts/mobile/build-android-local-acceptance.ps1'),'utf8');
  assert.match(wrapper, /'--init-script', \(Join-Path \$PSScriptRoot 'windows-native-paths\.gradle'\)/);
  const snapshot=readFileSync(path.join(repo,'scripts/mobile/source-snapshot.mjs'),'utf8');
  for (const file of ['windows-native-paths.gradle','build-android-local-acceptance.ps1','build-ios-simulator-acceptance.sh']) assert.ok(snapshot.includes(file));
});

function fixture(t) {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'caseops-build-config-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'public-ca.pem');
  writeFileSync(file, certificate);
  return { dir, file, env: {
    CASEOPS_MOBILE_BUILD_PROFILE: plugin.ANDROID_PROFILE,
    CASEOPS_MOBILE_AUTOMATED_TEST: '1', CASEOPS_MOBILE_RELEASE_SHA: sha,
    CASEOPS_MOBILE_ANDROID_CA_FILE: file, CASEOPS_MOBILE_ANDROID_CA_SHA256: digest(certificate),
    EXPO_PUBLIC_API_ORIGIN: 'https://10.0.2.2:8443', EXPO_PUBLIC_WEB_ORIGIN: 'https://10.0.2.2:3443',
  } };
}

function cleanEnv(extra = {}) {
  return { ...Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/^(CASEOPS_MOBILE_|EXPO_PUBLIC_|EX_UPDATES_NATIVE_DEBUG$|SKIP_BUNDLING$)/.test(key))),
  EXPO_NO_DOTENV: '1', ...extra };
}
function expoConfig(env = {}) {
  return JSON.parse(execFileSync(process.execPath, ['./node_modules/expo/bin/cli', 'config', '--type', 'public', '--json'], {
    cwd: app, env: cleanEnv(env), encoding: 'utf8', timeout: 30000,
  }));
}
function withEnv(env, action) {
  const prior = process.env;
  process.env = cleanEnv(env);
  return Promise.resolve().then(action).finally(() => { process.env = prior; });
}

test('default Expo config retains production origins, native IDs and no QA trust metadata', () => {
  const config = expoConfig();
  assert.equal(config.android.package, 'ai.caseops.mobile.dev');
  assert.equal(config.ios.bundleIdentifier, 'ai.caseops.mobile.dev');
  assert.equal(config.extra.apiOrigin, 'https://caseops.ai');
  assert.equal(config.extra.webOrigin, 'https://caseops.ai');
  assert.equal(config.extra.automatedTest, false);
  assert.equal(config.updates.enabled, false);
  assert.equal(config.ios.infoPlist.NSAppTransportSecurity, undefined);
  assert.equal(config.android.networkSecurityConfig, undefined);
  assert.doesNotMatch(JSON.stringify(config), /BEGIN CERTIFICATE|public-ca\.pem|fingerprint256/);
});

test('Android public config is marker-enforced, exact-source and leaves iOS defaults intact', (t) => {
  const { env, file } = fixture(t);
  const config = expoConfig(env);
  assert.equal(config.extra.automatedTest, true);
  assert.equal(config.extra.apiOrigin, env.EXPO_PUBLIC_API_ORIGIN);
  assert.equal(config.extra.webOrigin, env.EXPO_PUBLIC_WEB_ORIGIN);
  assert.equal(config.extra.releaseSha, sha);
  assert.equal(config.android.package, 'ai.caseops.mobile.dev'); // suffix is build-type-owned, not namespace.
  assert.equal(config.ios.bundleIdentifier, 'ai.caseops.mobile.dev');
  assert.equal(config.ios.infoPlist.NSAppTransportSecurity, undefined);
  assert.ok(!JSON.stringify(config).includes(file));
  assert.doesNotMatch(JSON.stringify(config), /BEGIN CERTIFICATE/);
});

test('iOS simulator acceptance has a distinct ID, HTTPS, marker and no Android CA', () => {
  const config = expoConfig({ CASEOPS_MOBILE_BUILD_PROFILE: plugin.IOS_PROFILE,
    CASEOPS_MOBILE_AUTOMATED_TEST: '1', CASEOPS_MOBILE_RELEASE_SHA: sha,
    EXPO_PUBLIC_API_ORIGIN: 'https://127.0.0.1:8443', EXPO_PUBLIC_WEB_ORIGIN: 'https://127.0.0.1:3443' });
  assert.equal(config.ios.bundleIdentifier, plugin.IOS_BUNDLE_ID);
  assert.equal(config.extra.automatedTest, true);
  assert.equal(config.ios.infoPlist.NSAppTransportSecurity, undefined);
  assert.equal(config.android.package, 'ai.caseops.mobile.dev');
});

test('unknown profiles and CA variables without the Android profile fail closed', () => {
  assert.throws(() => plugin.acceptanceSettings({ CASEOPS_MOBILE_BUILD_PROFILE: 'production' }), /UNKNOWN_MOBILE_BUILD_PROFILE/);
  for (const name of ['CASEOPS_MOBILE_ANDROID_CA_FILE', 'CASEOPS_MOBILE_ANDROID_CA_SHA256']) {
    assert.throws(() => plugin.acceptanceSettings({ [name]: 'value' }), /CA_REQUIRES_ANDROID_ACCEPTANCE_PROFILE/);
  }
});

test('missing marker, partial source identity and bundling bypass flags are rejected', (t) => {
  const { env } = fixture(t);
  for (const marker of [undefined, '0', 'true']) {
    assert.throws(() => plugin.acceptanceSettings({ ...env, CASEOPS_MOBILE_AUTOMATED_TEST: marker }), /AUTOMATED_MARKER_REQUIRED/);
  }
  assert.throws(() => plugin.acceptanceSettings({ ...env, CASEOPS_MOBILE_RELEASE_SHA: sha.slice(0, 8) }), /EXACT_SOURCE_SHA_REQUIRED/);
  for (const name of ['EX_UPDATES_NATIVE_DEBUG', 'SKIP_BUNDLING']) {
    assert.throws(() => plugin.acceptanceSettings({ ...env, [name]: '1' }), /STANDALONE_BUNDLING_REQUIRED/);
  }
});

for (const origin of ['http://10.0.2.2:8443', 'https://caseops.ai:8443', 'https://10.0.2.2.evil.test:8443',
  'https://user:password@10.0.2.2:8443', 'https://10.0.2.2:8443/path', 'https://10.0.2.2:8443?x=1',
  'https://10.0.2.2:8443#fragment', 'https://10.0.2.2', 'https://10.0.2.2:8443/', 'https://192.168.1.2:8443']) {
  test(`Android acceptance rejects noncanonical or nonlocal origin: ${origin}`, () => {
    assert.throws(() => plugin.localOrigin(origin, 'android'), /LOCAL_HTTPS_ORIGIN_REQUIRED/);
  });
}

test('both origins are mandatory and iOS cannot borrow the emulator host or Android trust', (t) => {
  const { env } = fixture(t);
  assert.throws(() => plugin.acceptanceSettings({ ...env, EXPO_PUBLIC_WEB_ORIGIN: undefined }), /EXPLICIT_ACCEPTANCE_ORIGINS_REQUIRED/);
  assert.throws(() => plugin.localOrigin('https://10.0.2.2:8443', 'ios'), /LOCAL_HTTPS_ORIGIN_REQUIRED/);
  assert.throws(() => plugin.acceptanceSettings({ ...env, CASEOPS_MOBILE_BUILD_PROFILE: plugin.IOS_PROFILE,
    EXPO_PUBLIC_API_ORIGIN: 'https://127.0.0.1:8443', EXPO_PUBLIC_WEB_ORIGIN: 'https://127.0.0.1:3443' }), /ANDROID_CA_FORBIDDEN_ON_IOS/);
});

test('only one external current public root CA with the exact byte hash is admitted', (t) => {
  const { file } = fixture(t);
  assert.equal(plugin.readPublicCa(file, digest(certificate)).sha256, digest(certificate));
  assert.throws(() => plugin.readPublicCa(file, '0'.repeat(64)), /PUBLIC_CA_HASH_MISMATCH/);
  assert.throws(() => plugin.readPublicCa(file, digest(certificate), Date.parse(new X509Certificate(certificate).validTo)), /PUBLIC_CA_NOT_CURRENT/);
  assert.throws(() => plugin.readPublicCa('relative.pem', digest(certificate)), /EXTERNAL_PUBLIC_CA_FILE_REQUIRED/);
  assert.throws(() => plugin.readPublicCa(path.join(app, 'app.config.ts'), '0'.repeat(64)), /PUBLIC_CA_MUST_BE_OUTSIDE_GIT/);
  for (const pem of [certificate + certificate, certificate + '-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n']) {
    writeFileSync(file, pem);
    assert.throws(() => plugin.readPublicCa(file, digest(pem)), /ONE_PUBLIC_CERTIFICATE_ONLY/);
  }
});

test('network trust is exact-host CA-only, not a global or user-store trust override', async (t) => {
  const { env } = fixture(t);
  const settings = plugin.acceptanceSettings(env);
  const xml = plugin.networkSecurityXml(settings);
  assert.equal((xml.match(/<domain includeSubdomains="false">10.0.2.2<\/domain>/g) || []).length, 1);
  assert.doesNotMatch(xml, /includeSubdomains="true"|src="user"|debug-overrides|cleartextTrafficPermitted="true"/);
  assert.match(xml, /<domain includeSubdomains="false">localhost<\/domain>/);
  const domain = xml.slice(xml.lastIndexOf('<domain-config'));
  assert.doesNotMatch(domain, /src="system"/);
  assert.match(domain, /src="@raw\/caseops_local_acceptance_ca"/);
  assert.doesNotMatch(xml.slice(0, xml.indexOf('<domain-config')), /@raw/);
  const parsed = (await XML.parseXMLAsync(xml))['network-security-config'];
  assert.equal(parsed['base-config'][0].$.cleartextTrafficPermitted, 'false');
  const domains = parsed['domain-config'];
  assert.equal(domains.length, 2);
  assert.deepEqual(domains[1].domain.map((item) => item._), ['10.0.2.2']);
  assert.equal(domains[1]['trust-anchors'][0].certificates[0].$.src, '@raw/caseops_local_acceptance_ca');
});

test('release-derived Gradle generation is idempotent and default cleanup is byte-identical', (t) => {
  const { env } = fixture(t);
  const settings = plugin.acceptanceSettings(env);
  const template = "// Existing default build types and signing are untouched.\r\nandroid { buildTypes { release {} } }\r\n";
  const built = plugin.updateGradle(template, settings);
  assert.equal(plugin.updateGradle(built, settings), built);
  assert.equal(plugin.updateGradle(built, null), template);
  assert.match(built, /initWith release[\s\S]*debuggable false[\s\S]*applicationIdSuffix '\.localacceptance'[\s\S]*matchingFallbacks = \['release'\]/);
  assert.match(built, /variant\.buildType != 'localAcceptance'.*variant\.enable = false/);
  assert.match(built, /System\.getenv\(key\) != expected/);
  assert.match(built, /MessageDigest\.getInstance\('SHA-256'\)/);
  assert.match(built, /extensions\.getByType\(com\.facebook\.react\.ReactExtension\)\.debuggableVariants\.get\(\)/);
  assert.doesNotMatch(built, /if \(react\.debuggableVariants/);
  assert.doesNotMatch(built, /useDevSupport\s*=|getUseDeveloperSupport|debuggableVariants\s*=/);
  assert.throws(() => plugin.updateGradle(`${built}\n// BEGIN CaseOps generated local acceptance`, settings), /GENERATED_GRADLE_MARKERS_INVALID/);
});

test('overlay creation, replacement and cleanup never touch main, release or unowned files', (t) => {
  const { env, dir } = fixture(t);
  const root = path.join(dir, 'android');
  const main = path.join(root, 'app/src/main/AndroidManifest.xml');
  const unrelated = path.join(root, 'app/src/localAcceptance/unowned.txt');
  mkdirSync(path.dirname(main), { recursive: true });
  writeFileSync(main, '<manifest>production sentinel</manifest>');
  const settings = plugin.acceptanceSettings(env);
  plugin.writeAndroidOverlay(root, settings);
  writeFileSync(unrelated, 'retain');
  const ca = path.join(root, 'app/src/localAcceptance/res/raw/caseops_local_acceptance_ca.pem');
  assert.equal(readFileSync(ca, 'utf8'), certificate);
  plugin.writeAndroidOverlay(root, settings);
  assert.equal(readFileSync(ca, 'utf8'), certificate);
  plugin.writeAndroidOverlay(root, null);
  assert.equal(existsSync(ca), false);
  assert.equal(existsSync(path.join(root, 'app/src/localAcceptance/AndroidManifest.xml')), false);
  assert.equal(readFileSync(main, 'utf8'), '<manifest>production sentinel</manifest>');
  assert.equal(readFileSync(unrelated, 'utf8'), 'retain');
  assert.equal(existsSync(path.join(root, 'app/src/release')), false);
});

test('actual Expo Android mod compiler applies the plugin and removes QA output on default replay', async (t) => {
  const { env, dir } = fixture(t);
  const gradle = path.join(dir, 'android/app/build.gradle');
  mkdirSync(path.dirname(gradle), { recursive: true });
  writeFileSync(gradle, "apply plugin: 'com.android.application'\n");
  const run = (values) => withEnv(values, () => compileModsAsync(plugin({ name: 'CaseOps', slug: 'caseops-mobile' }), {
    projectRoot: dir, platforms: ['android'],
  }));
  await run(env);
  assert.match(readFileSync(gradle, 'utf8'), /localAcceptance/);
  assert.ok(existsSync(path.join(dir, 'android/app/src/localAcceptance/res/raw/caseops_local_acceptance_ca.pem')));
  await run({});
  assert.equal(readFileSync(gradle, 'utf8'), "apply plugin: 'com.android.application'\n");
  assert.equal(existsSync(path.join(dir, 'android/app/src/localAcceptance/res/raw/caseops_local_acceptance_ca.pem')), false);
});

test('installed RN and Expo use non-debug dev=false bundling and release launcher stubs', () => {
  const gradle = readFileSync(path.join(app, 'node_modules/@react-native/gradle-plugin/react-native-gradle-plugin/src/main/kotlin/com/facebook/react/TaskConfiguration.kt'), 'utf8');
  assert.match(gradle, /if \(!isDebuggableVariant\)/);
  assert.match(gradle, /task\.devEnabled\.set\(false\)/);
  const launcher = readFileSync(path.join(app, 'node_modules/expo-dev-launcher/android/build.gradle'), 'utf8');
  assert.match(launcher, /configureInRelease = findProperty\("expo.devlauncher.configureInRelease"\) == "true"/);
  assert.match(launcher, /java\.srcDir 'src\/disableInRelease\/java'/);
  const xcode = readFileSync(path.join(app, 'node_modules/expo/scripts/react-native-xcode.sh'), 'utf8');
  assert.match(xcode, /\*Debug\*\)[\s\S]*DEV=true[\s\S]*\*\)[\s\S]*DEV=false/);
});

test('build receipt binds exact current source and rejects a stale requested release', async (t) => {
  const { env } = fixture(t);
  const { checkBuildConfig, finishBuild } = await import('./build-acceptance.mjs');
  await withEnv(env, () => {
    const before = checkBuildConfig('android');
    assert.equal(before.appId, plugin.ANDROID_APP_ID);
    assert.equal(before.sourceSha, sha);
    assert.equal(before.devEnabled, false);
    const config = { extra: { automatedTest: true, apiOrigin: before.apiOrigin,
      webOrigin: before.webOrigin, releaseSha: sha } };
    assert.throws(() => finishBuild('android', { ...before, sourceFingerprint: 'changed' }, env.CASEOPS_MOBILE_ANDROID_CA_FILE, config), /SOURCE_OR_CONFIGURATION_CHANGED_DURING_BUILD/);
    assert.throws(() => finishBuild('android', before, env.CASEOPS_MOBILE_ANDROID_CA_FILE,
      { extra: { ...config.extra, automatedTest: false } }), /EMBEDDED_MARKER_REQUIRED/);
    const receipt = finishBuild('android', before, env.CASEOPS_MOBILE_ANDROID_CA_FILE, config);
    assert.equal(receipt.binaryHash, digest(certificate)); // synthetic file, not APK acceptance.
  });
  await withEnv({ ...env, CASEOPS_MOBILE_RELEASE_SHA: '0'.repeat(40) }, () => {
    assert.throws(() => checkBuildConfig('android'), /CURRENT_SOURCE_SHA_REQUIRED/);
  });
});

test('build wrappers never start Metro, use distinct standalone tasks and retain raw logs', () => {
  const android = readFileSync(new URL('./build-android-local-acceptance.ps1', import.meta.url), 'utf8');
  const ios = readFileSync(new URL('./build-ios-simulator-acceptance.sh', import.meta.url), 'utf8');
  assert.match(android, /:app:assembleLocalAcceptance/);
  assert.match(android, /& \$Command @Arguments/);
  assert.match(android, /GetEntry\('assets\/index.android.bundle'\)/);
  assert.match(android, /application-debuggable/);
  assert.match(ios, /-configuration Release/);
  assert.match(ios, /CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO/);
  assert.match(ios, /test -s "\$app\/main.jsbundle"/);
  for (const script of [android, ios]) {
    assert.doesNotMatch(script, /expo[^\n]* start |Set-ExecutionPolicy|ExecutionPolicy Bypass|--insecure|NODE_TLS_REJECT_UNAUTHORIZED|allowProvisioningUpdates/);
    assert.match(script, /Raw build evidence retained/);
  }
});

test('receipt writer creates UTF-8 JSON exclusively and refuses evidence overwrite', (t) => {
  const { dir, env } = fixture(t);
  const output = path.join(dir, 'before.json');
  const args = ['scripts/mobile/build-acceptance.mjs', 'check', 'android', output];
  execFileSync(process.execPath, args, { cwd: repo, env: cleanEnv(env), stdio: 'pipe' });
  assert.equal(JSON.parse(readFileSync(output, 'utf8')).automatedTest, true);
  const original = readFileSync(output);
  const again = spawnSync(process.execPath, args, { cwd: repo, env: cleanEnv(env), encoding: 'utf8' });
  assert.notEqual(again.status, 0);
  assert.match(again.stderr, /EEXIST/);
  assert.deepEqual(readFileSync(output), original);
});

for (const shell of ['powershell.exe', 'pwsh.exe']) {
  test(`Windows wrapper parses and forwards native drive-letter arguments in ${shell}`, { skip: process.platform !== 'win32' }, (t) => {
    const { dir } = fixture(t);
    const wrapper = fileURLToPath(new URL('./build-android-local-acceptance.ps1', import.meta.url));
    const quote = (value) => `'${value.replaceAll("'", "''")}'`;
    const argument = 'C:/explicit path/QA input/public-ca.pem';
    const script = `
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(${quote(wrapper)}, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'WRAPPER_PARSE_FAILED' }
$definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-BuildCommand' }, $true)
. ([scriptblock]::Create($definition.Extent.Text))
$run = ${quote(dir)}
$nativeArguments = @('-e', 'process.stdout.write(JSON.stringify(process.argv.slice(1)))', ${quote(argument)})
Invoke-BuildCommand ${quote(process.execPath)} $nativeArguments 'argv.log' | Out-Null
Invoke-BuildCommand ${quote(process.execPath)} @('-e', 'process.stderr.write(''SUCCESS_STDERR''); process.exit(0)') 'stderr.log' | Out-Null
$rejected = $false
try {
    Invoke-BuildCommand ${quote(process.execPath)} @('-e', 'process.stderr.write(''FAILED_STDERR''); process.exit(7)') 'failure.log' | Out-Null
} catch { $rejected = $true }
[pscustomobject]@{
    received = @((Get-Content -LiteralPath (Join-Path $run 'argv.log') -Raw | ConvertFrom-Json))
    stderrRetained = (Get-Content -LiteralPath (Join-Path $run 'stderr.log') -Raw).Contains('SUCCESS_STDERR')
    failureRetained = (Get-Content -LiteralPath (Join-Path $run 'failure.log') -Raw).Contains('FAILED_STDERR')
    failedExitRejected = $rejected
} | ConvertTo-Json
`;
    const stdout = execFileSync(shell, ['-NoProfile', '-NonInteractive', '-Command', script], {
      encoding: 'utf8', timeout: 15000, windowsHide: true,
    });
    assert.deepEqual(JSON.parse(stdout.trim()), { received: [argument], stderrRetained: true,
      failureRetained: true, failedExitRejected: true });
  });
}

test('cross-platform profile guards reject prebuilding the wrong native platform', async (t) => {
  const { env, dir } = fixture(t);
  await withEnv(env, async () => {
    const config = plugin({ name: 'CaseOps', slug: 'caseops-mobile' });
    await assert.rejects(() => config.mods.ios.dangerous({ ...config, modResults: {},
      modRequest: { projectRoot: dir, platformProjectRoot: path.join(dir, 'ios'), platform: 'ios', modName: 'dangerous' } }),
    /ANDROID_ACCEPTANCE_CANNOT_PREBUILD_IOS/);
  });
  await withEnv({ CASEOPS_MOBILE_BUILD_PROFILE: plugin.IOS_PROFILE,
    CASEOPS_MOBILE_AUTOMATED_TEST: '1', CASEOPS_MOBILE_RELEASE_SHA: sha,
    EXPO_PUBLIC_API_ORIGIN: 'https://127.0.0.1:8443', EXPO_PUBLIC_WEB_ORIGIN: 'https://127.0.0.1:3443' }, async () => {
    const config = plugin({ name: 'CaseOps', slug: 'caseops-mobile' });
    await assert.rejects(() => config.mods.android.dangerous({ ...config, modResults: {},
      modRequest: { projectRoot: dir, platformProjectRoot: path.join(dir, 'android'), platform: 'android', modName: 'dangerous' } }),
    /IOS_ACCEPTANCE_CANNOT_PREBUILD_ANDROID/);
  });
});
