// Draft preparation only. This file never starts Xcode, Gradle, signing or upload.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { sourceSnapshot } from './source-snapshot.mjs';
const require = createRequire(import.meta.url);
const { readNativeLinkConfig } = require('../../apps/web/lib/native-link-config.cjs');
const { readJson, reference, readStoreBuildSettings } = require('../../apps/mobile/plugins/store-build.cjs');
const keys = (value, wanted, message) => {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), message);
  assert.deepEqual(Object.keys(value).sort(), [...wanted].sort(), message);
};
const absolute = (value) => assert.ok(typeof value === 'string' && path.isAbsolute(value) && path.resolve(value) === value && !/[\r\n\0]/.test(value), 'EXPLICIT_CANONICAL_PATH_REQUIRED');
const digest = (value) => assert.match(value, /^[a-f0-9]{64}$/, 'EXPLICIT_SHA256_REQUIRED');
const xml = (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&apos;');
function httpsOrigin(value) {
  const url = new URL(value);
  assert.ok(url.protocol === 'https:' && url.origin === value && !url.port && !url.username && !url.password
    && !/(^|\.)(localhost|invalid|test|example)$/.test(url.hostname)
    && !/(?:^|\.)example\.(?:com|net|org)$/.test(url.hostname)
    && !/^[\d.:\[\]]+$/.test(url.hostname), 'FINAL_HTTPS_ORIGIN_REQUIRED');
}
export function packagingPlan(request, { root, output, links, settings, source, allowSynthetic = false }) {
  keys(request, ['schemaVersion', 'kind', 'preparedOnly', 'syntheticDataOnly', 'platform', 'source', 'nativeLinks', 'storeBuild', 'apiOrigin', 'webOrigin', 'signing'], 'STORE_RECIPE_REQUEST_REQUIRED');
  assert.equal(request.schemaVersion, 1); assert.equal(request.kind, 'caseops-store-packaging-request');
  assert.equal(request.preparedOnly, true, 'PREPARATION_ONLY_REQUIRED');
  assert.equal(typeof request.syntheticDataOnly, 'boolean');
  assert.equal(request.syntheticDataOnly, links.config.syntheticDataOnly);
  assert.ok(!request.syntheticDataOnly || allowSynthetic, 'SYNTHETIC_STORE_RECIPE_FORBIDDEN');
  assert.ok(['ios', 'android'].includes(request.platform), 'EXACT_STORE_PLATFORM_REQUIRED');
  reference(request.nativeLinks); reference(request.storeBuild);
  assert.equal(request.nativeLinks.sha256, links.sha256, 'RECIPE_LINK_CONFIG_MISMATCH');
  assert.deepEqual(request.storeBuild, settings.ref, 'RECIPE_BUILD_CONFIG_MISMATCH');
  keys(request.source, ['sourceSha', 'sourceFingerprint', 'inputFileCount'], 'SOURCE_BINDING_REQUIRED');
  assert.deepEqual(request.source, { sourceSha: source.sourceSha, sourceFingerprint: source.sourceFingerprint, inputFileCount: source.inputFileCount }, 'RECIPE_ACTUAL_SOURCE_MISMATCH');
  assert.match(source.sourceSha, /^[a-f0-9]{40}$/); digest(source.sourceFingerprint);
  assert.ok(Number.isSafeInteger(source.inputFileCount) && source.inputFileCount > 0);
  assert.ok(!source.sourceDirty || (allowSynthetic && request.syntheticDataOnly), 'CLEAN_COMMITTED_STORE_SOURCE_REQUIRED');
  absolute(root); absolute(output);
  assert.ok(output !== root && !output.startsWith(root + path.sep), 'STORE_OUTPUT_MUST_BE_OUTSIDE_SOURCE');
  httpsOrigin(request.apiOrigin); httpsOrigin(request.webOrigin);
  assert.equal(request.webOrigin, new URL(links.config.redirectUri).origin, 'WEB_ORIGIN_MUST_OWN_EXACT_CALLBACK');
  const mobile = path.join(root, 'apps/mobile');
  const environment = {
    NODE_ENV: 'production', __EXPO_CONFIG_MODE: 'production', EXPO_NO_DOTENV: '1', CI: '1',
    CASEOPS_NATIVE_LINK_CONFIG_FILE: request.nativeLinks.path, CASEOPS_NATIVE_LINK_CONFIG_SHA256: request.nativeLinks.sha256,
    CASEOPS_STORE_BUILD_FILE: request.storeBuild.path, CASEOPS_STORE_BUILD_SHA256: request.storeBuild.sha256,
    CASEOPS_MOBILE_RELEASE_SHA: source.sourceSha, EXPO_PUBLIC_API_ORIGIN: request.apiOrigin, EXPO_PUBLIC_WEB_ORIGIN: request.webOrigin,
    CASEOPS_MOBILE_AUTOMATED_TEST: '0', EXPO_NO_TELEMETRY: '1',
  };
  const commands = [
    { cwd: root, executable: 'node', args: ['scripts/mobile/prepare-viewer-assets.mjs', '--check'], timeoutMs: 60000 },
    { cwd: mobile, executable: 'node', args: ['node_modules/expo/bin/cli', 'prebuild', '--platform', request.platform, '--no-install'], timeoutMs: 120000 },
  ];
  const outputs = {};
  if (request.platform === 'ios') {
    const s = request.signing;
    keys(s, ['teamId', 'applicationIdentifierPrefix', 'certificateSha1', 'certificateSha256', 'provisioningProfileUuid', 'provisioningProfileEvidence', 'developerDirectory', 'podfileLockEvidence'], 'EXPLICIT_IOS_DISTRIBUTION_INPUTS_REQUIRED');
    assert.match(s.teamId, /^[A-Z0-9]{10}$/); assert.match(s.applicationIdentifierPrefix, /^[A-Z0-9]{10}$/);
    assert.equal(s.applicationIdentifierPrefix, links.config.ios.applicationIdentifierPrefix, 'IOS_APPLICATION_PREFIX_MISMATCH');
    // The Team ID and application-identifier prefix are deliberately distinct.
    assert.match(s.certificateSha1, /^[a-f0-9]{40}$/); digest(s.certificateSha256);
    assert.match(s.provisioningProfileUuid, /^[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}$/);
    reference(s.provisioningProfileEvidence); reference(s.podfileLockEvidence); absolute(s.developerDirectory);
    environment.DEVELOPER_DIR = s.developerDirectory;
    const archive = path.join(output, 'CaseOps.xcarchive');
    commands.push(
      { cwd: path.join(mobile, 'ios'), executable: 'pod', args: ['install', '--deployment', '--no-repo-update'], timeoutMs: 180000 },
      { cwd: mobile, executable: 'xcodebuild', args: ['-workspace', 'ios/CaseOps.xcworkspace', '-scheme', 'CaseOps', '-configuration', 'Release', '-sdk', 'iphoneos', '-destination', 'generic/platform=iOS', '-archivePath', archive, '-derivedDataPath', path.join(output, 'DerivedData'), '-jobs', '4', 'CODE_SIGN_STYLE=Manual', 'CODE_SIGNING_ALLOWED=YES', 'CODE_SIGNING_REQUIRED=YES', 'DEVELOPMENT_TEAM=' + s.teamId, 'PRODUCT_BUNDLE_IDENTIFIER=' + links.config.ios.bundleIdentifier, 'CODE_SIGN_IDENTITY=' + s.certificateSha1, 'PROVISIONING_PROFILE_SPECIFIER=' + s.provisioningProfileUuid, 'CURRENT_PROJECT_VERSION=' + settings.iosBuildNumber, 'MARKETING_VERSION=' + settings.version, 'archive'], timeoutMs: 1800000 },
      { cwd: mobile, executable: 'xcodebuild', args: ['-exportArchive', '-archivePath', archive, '-exportPath', path.join(output, 'export'), '-exportOptionsPlist', path.join(output, 'ExportOptions.plist')], timeoutMs: 300000 },
    );
    outputs['ExportOptions.plist'] = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>method</key><string>app-store-connect</string><key>destination</key><string>export</string><key>signingStyle</key><string>manual</string><key>teamID</key><string>' + xml(s.teamId) + '</string><key>signingCertificate</key><string>' + xml(s.certificateSha1) + '</string><key>provisioningProfiles</key><dict><key>' + xml(links.config.ios.bundleIdentifier) + '</key><string>' + xml(s.provisioningProfileUuid) + '</string></dict><key>manageAppVersionAndBuildNumber</key><false/><key>uploadSymbols</key><false/></dict></plist>\n';
  } else {
    const s = request.signing;
    keys(s, ['uploadKeystoreEvidence', 'uploadKeyAlias', 'uploadCertificateSha256', 'appSigningCertificateSha256', 'androidSdkRoot', 'javaHome', 'java17Home', 'gradleUserHome'], 'EXPLICIT_ANDROID_DISTRIBUTION_INPUTS_REQUIRED');
    reference(s.uploadKeystoreEvidence); digest(s.uploadCertificateSha256); digest(s.appSigningCertificateSha256);
    assert.ok(links.config.android.signingCertificateSha256.includes(s.appSigningCertificateSha256), 'ANDROID_APP_SIGNING_LINK_CERTIFICATE_MISMATCH');
    assert.ok(typeof s.uploadKeyAlias === 'string' && /^[A-Za-z0-9._-]{1,100}$/.test(s.uploadKeyAlias), 'EXPLICIT_UPLOAD_KEY_ALIAS_REQUIRED');
    for (const key of ['androidSdkRoot', 'javaHome', 'java17Home', 'gradleUserHome']) absolute(s[key]);
    Object.assign(environment, { ANDROID_HOME: s.androidSdkRoot, ANDROID_SDK_ROOT: s.androidSdkRoot, JAVA_HOME: s.javaHome, GRADLE_USER_HOME: s.gradleUserHome, CASEOPS_UPLOAD_KEYSTORE: s.uploadKeystoreEvidence.path, CASEOPS_UPLOAD_KEY_ALIAS: s.uploadKeyAlias });
    commands.push({ cwd: path.join(mobile, 'android'), executable: './gradlew', args: [':app:bundleRelease', '--offline', '--no-daemon', '--max-workers=2', '--console=plain', '-I', path.join(output, 'store-signing.init.gradle'), '-Pandroid.builder.sdkDownload=false', '-Dorg.gradle.java.installations.auto-download=false', '-Dorg.gradle.java.installations.paths=' + s.java17Home + ',' + s.javaHome], timeoutMs: 1800000 });
    outputs['store-signing.init.gradle'] = "// Draft AGP9 release signing injection; native projection remains unverified.\ngradle.beforeProject { p ->\n p.pluginManager.withPlugin('com.android.application') {\n  p.extensions.getByName('androidComponents').finalizeDsl { android ->\n   if (p.path != ':app') throw new GradleException('EXACT_APP_MODULE_REQUIRED')\n   def env = System.getenv()\n   ['CASEOPS_UPLOAD_KEYSTORE','CASEOPS_UPLOAD_KEY_ALIAS','CASEOPS_UPLOAD_STORE_PASSWORD','CASEOPS_UPLOAD_KEY_PASSWORD'].each { if (!env[it]) throw new GradleException('EXPLICIT_UPLOAD_SIGNING_INPUT_REQUIRED') }\n   def signing = android.signingConfigs.create('caseopsStoreUpload')\n   signing.storeFile = p.file(env.CASEOPS_UPLOAD_KEYSTORE)\n   signing.storePassword = env.CASEOPS_UPLOAD_STORE_PASSWORD\n   signing.keyAlias = env.CASEOPS_UPLOAD_KEY_ALIAS\n   signing.keyPassword = env.CASEOPS_UPLOAD_KEY_PASSWORD\n   def release = android.buildTypes.getByName('release')\n   release.signingConfig = signing\n   release.debuggable = false\n  }\n }\n}\n";
  }
  return { schemaVersion: 1, kind: 'caseops-store-packaging-plan', preparedOnly: true, readyForBuild: false, executionEnabled: false,
    syntheticDataOnly: request.syntheticDataOnly, platform: request.platform, source,
    identities: settings.build.value.identities, version: settings.version, iosBuildNumber: settings.iosBuildNumber, androidVersionCode: settings.androidVersionCode,
    baselineScope: settings.baselineScope, independentlyVerifiedStoreMaximum: false,
    environment, requiredSecretEnvironmentNames: request.platform === 'android' ? ['CASEOPS_UPLOAD_STORE_PASSWORD', 'CASEOPS_UPLOAD_KEY_PASSWORD'] : [],
    commands, outputs,
    requiredBeforeExecution: [
      'fresh independent store/version history and one exclusive shared build-number reservation',
      'accepted exact executable/tool versions and hashes; clean committed complete source and dependency inventory; required security gates',
      'same-FD signing material verification; current certificate/private-key possession and certificate identity',
      request.platform === 'ios' ? 'CMS-decoded App Store profile UUID, expiry, distribution type, TeamIdentifier and application-identifier prefix, entitlements/certificate binding, exact installed profile and pinned Podfile.lock' : 'actual upload-keystore certificate identity via protected input; reviewed Gradle final release signing projection; pinned Gradle/wrapper/JDK/SDK graph with downloads disabled',
      'artifact postflight: exact version/build/IDs/source/policy digest, release signature, archive/AAB contents, runtime/dependency/privacy/license inventory',
      'actual independently bound production HTTPS associations and current native acceptance; production archive/store readiness is unverified',
    ] };
}
export function prepare(requestRef, output, { allowSynthetic = false, root = path.resolve(fileURLToPath(new URL('../../', import.meta.url))) } = {}) {
  assert.equal(process.versions.node, '24.15.0', 'PINNED_NODE_24_15_REQUIRED');
  const requestInput = readJson(reference(requestRef));
  const request = requestInput.value;
  const links = readNativeLinkConfig({ CASEOPS_NATIVE_LINK_CONFIG_FILE: request.nativeLinks?.path, CASEOPS_NATIVE_LINK_CONFIG_SHA256: request.nativeLinks?.sha256 }, { allowSynthetic });
  const settings = readStoreBuildSettings({ CASEOPS_STORE_BUILD_FILE: request.storeBuild?.path, CASEOPS_STORE_BUILD_SHA256: request.storeBuild?.sha256 }, links, { allowSynthetic });
  absolute(output); assert.equal(fs.existsSync(output), false, 'NEW_OUTPUT_DIRECTORY_REQUIRED');
  let parent = path.dirname(output); assert.equal(fs.realpathSync(parent), parent, 'CANONICAL_OUTPUT_PARENT_REQUIRED');
  const plan = packagingPlan(request, { root, output, links, settings, source: sourceSnapshot(root), allowSynthetic });
  fs.mkdirSync(output, { mode: 0o700 });
  for (const [name, bytes] of Object.entries({ 'request-evidence.json': requestInput.bytes, 'store-build-evidence.json': settings.build.bytes,
    'declared-baseline-evidence.json': settings.baseline.bytes, 'native-links-evidence.json': links.bytes, ...plan.outputs })) {
    fs.writeFileSync(path.join(output, name), bytes, { flag: 'wx', mode: 0o600 });
  }
  fs.writeFileSync(path.join(output, 'command-plan.json'), JSON.stringify(plan, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  return { preparedOnly: true, readyForBuild: false, path: path.join(output, 'command-plan.json'), sha256: createHash('sha256').update(fs.readFileSync(path.join(output, 'command-plan.json'))).digest('hex') };
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const args = process.argv.slice(2);
    assert.ok(args.length === 7 || args.length === 8, 'PREPARE_ONLY_CLI_REQUIRED');
    assert.equal(args[0], '--plan'); assert.equal(args[1], '--request'); assert.equal(args[3], '--sha256'); assert.equal(args[5], '--output');
    assert.ok(args.length === 7 || args[7] === '--synthetic', 'PREPARE_ONLY_CLI_REQUIRED');
    console.log(JSON.stringify(prepare({ path: args[2], sha256: args[4] }, args[6], { allowSynthetic: args[7] === '--synthetic' })));
  } catch { console.error('STORE_PACKAGING_PREPARATION_REFUSED'); process.exitCode = 1; }
}
