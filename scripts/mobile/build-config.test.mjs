import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash, X509Certificate } from 'node:crypto';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { rootCertificates } from 'node:tls';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { sourceSnapshot } from './source-snapshot.mjs';

const app = fileURLToPath(new URL('../../apps/mobile/', import.meta.url));
const repo = path.resolve(app, '../..');
const require = createRequire(path.join(app, 'package.json'));
const plugin = require(path.join(app, 'plugins/with-local-acceptance.cjs'));
const linkPolicy = require(path.join(repo, 'apps/web/lib/native-link-policy.cjs'));
const { readNativeLinkConfig } = require(path.join(repo, 'apps/web/lib/native-link-config.cjs'));
const { compileModsAsync, XML } = require('@expo/config-plugins');
const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim();
const certificate = `${rootCertificates.find((pem) => {
  const cert = new X509Certificate(pem);
  return cert.ca && cert.checkIssued(cert) && cert.verify(cert.publicKey)
    && Date.parse(cert.validFrom) < Date.now() && Date.now() < Date.parse(cert.validTo);
}).trim()}\n`;
const digest = (value) => createHash('sha256').update(value).digest('hex');

test('mobile CI selects every tooling module and audits before either platform export', () => {
  const workflow = require('js-yaml').load(readFileSync(path.join(repo, '.github/workflows/mobile-source.yml'), 'utf8'));
  const steps = workflow.jobs.source.steps;
  const expected = ['scripts/mobile/build-config.test.mjs', 'scripts/mobile/tooling.test.mjs',
    'scripts/mobile/local-owner-controls.test.mjs', 'apps/mobile/e2e/files-20261025.test.mjs',
    'apps/mobile/e2e/ios-files.test.mjs', 'apps/mobile/e2e/android-files.test.mjs',
    'scripts/mobile/ios-browser-context.test.mjs', 'scripts/mobile/ios-native-locators.test.mjs',
    'scripts/mobile/ios-simulator-signing.test.mjs',
    'scripts/mobile/prepare-gateway-routes.test.mjs',
    'scripts/mobile/prepare-ios-local-run.test.mjs', 'scripts/mobile/ios-files-privacy.test.mjs',
    'scripts/mobile/run-ios-files.test.mjs',
    'scripts/mobile/filesystem-security.test.mjs', 'scripts/mobile/build-android-local-acceptance.test.mjs',
    'scripts/mobile/android-native-proof.test.mjs', 'scripts/mobile/prepare-android-local-run.test.mjs',
    'scripts/mobile/android-files-privacy.test.mjs', 'scripts/mobile/run-android-files.test.mjs'];
  const discovered = ['scripts/mobile', 'apps/mobile/e2e'].flatMap(directory => readdirSync(path.join(repo, directory))
    .filter(file => file.endsWith('.test.mjs')).map(file => `${directory}/${file}`));
  assert.deepEqual(discovered.sort(), [...expected].sort(), 'COMPLETE_TOOLING_FILE_INVENTORY_REQUIRED');
  const harness = steps.find(step => step.name === 'Verify the native evidence harness');
  assert.equal(harness.run, `node --test ${expected.join(' ')}`);
  const fixturePreparation = steps.find(step => step.name === 'Verify isolated fixture preparation and gateway');
  assert.equal(fixturePreparation?.run, 'python3 scripts/mobile/local-fixture.test.py');
  const filesFixtureCommands = [
    ['Verify synthetic iOS Files picker inputs', 'python3 scripts/mobile/prepare-ios-files-fixture.test.py'],
    ['Verify acknowledged iOS Files source admission', 'python3 scripts/mobile/admit-ios-file-source.test.py'],
    ['Verify synthetic Android Files picker inputs', 'python3 scripts/mobile/prepare-android-files-fixture.test.py'],
    ['Verify acknowledged Android Files source admission', 'python3 scripts/mobile/admit-android-file-source.test.py'],
  ];
  for (const [name, command] of filesFixtureCommands) {
    const matches = steps.filter(step => step.name === name);
    assert.equal(matches.length, 1, 'EXACT_FILES_FIXTURE_CI_STEP_REQUIRED');
    assert.equal(matches[0].run, command, 'FILES_FIXTURE_REGRESSION_CI_COMMAND_REQUIRED');
    assert.notEqual(matches[0]['continue-on-error'], true);
    assert.equal(matches[0].if, undefined, 'FILES_FIXTURE_CI_MUST_RUN_UNCONDITIONALLY');
    assert.ok(!matches[0]['working-directory'] || matches[0]['working-directory'] === '.', 'FILES_FIXTURE_CI_REPOSITORY_ROOT_REQUIRED');
    assert.ok(existsSync(path.join(repo, command.split(' ')[1])), 'FILES_FIXTURE_TEST_SOURCE_REQUIRED');
  }
  const audit = steps.findIndex(step => step.name === 'Enforce the unwaived high-severity dependency gate');
  assert.ok(audit >= 0);
  assert.equal(steps[audit].run, 'npm audit --audit-level=high');
  assert.notEqual(steps[audit]['continue-on-error'], true);
  for (const [, command] of filesFixtureCommands) {
    assert.ok(steps.findIndex(step => step.run === command) < audit, 'FILES_FIXTURE_REGRESSIONS_MUST_PRECEDE_PLATFORM_EXPORT_GATE');
  }
  for (const command of ['npm run export:android', 'npm run export:ios']) {
    const exporting = steps.findIndex(step => step.run === command);
    assert.ok(exporting > audit, 'DEPENDENCY_AUDIT_MUST_PRECEDE_PLATFORM_EXPORT');
  }
});

test('mobile source CI installs the renderer browser and both locked dependency graphs', () => {
  const workflow = require('js-yaml').load(readFileSync(path.join(repo, '.github/workflows/mobile-source.yml'), 'utf8'));
  const steps = workflow.jobs.source.steps;
  const isRoot = (step) => !step['working-directory'] || step['working-directory'] === '.';
  const rootInstall = steps.findIndex(step => isRoot(step) && step.run === 'npm ci --include=dev');
  const mobileInstall = steps.findIndex(step => step['working-directory'] === 'apps/mobile' && step.run === 'npm ci');
  const browserInstall = steps.findIndex(step => isRoot(step) && step.run === 'npx --no-install playwright install --with-deps chromium');
  const typecheck = steps.findIndex(step => step['working-directory'] === 'apps/mobile' && step.run === 'npm run typecheck');
  const tests = steps.findIndex(step => step['working-directory'] === 'apps/mobile' && step.run === 'npm test');
  assert.ok(rootInstall >= 0 && mobileInstall >= 0 && browserInstall >= 0);
  assert.ok(rootInstall < typecheck && mobileInstall < typecheck);
  assert.ok(rootInstall < browserInstall && browserInstall < tests);
  const nodeSetup = steps.find(step => step.uses === 'actions/setup-node@v4');
  assert.equal(nodeSetup.with['node-version'], '24.15.0', 'NATIVE_WRAPPER_RUNTIME_MUST_MATCH_SOURCE_CI');
  assert.deepEqual(nodeSetup.with['cache-dependency-path'].trim().split(/\s+/).sort(),
    ['apps/mobile/package-lock.json', 'package-lock.json']);
  for (const event of ['push', 'pull_request']) {
    for (const dependency of ['package.json', 'package-lock.json', 'apps/web/**', 'tests/e2e/support/**', 'playwright.mobile-handoff.config.ts', 'tsconfig.e2e.json'])
      assert.ok(workflow.on[event].paths.includes(dependency), `NATIVE_SHARED_INPUT_TRIGGER_REQUIRED:${event}:${dependency}`);
  }
  assert.deepEqual(workflow.jobs['browser-handoff'].env, {
    NEXT_PUBLIC_API_BASE_URL: 'http://127.0.0.1:8000',
    NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE: '1',
    NEXT_PUBLIC_APP_URL: 'https://127.0.0.1:3443',
  }, 'BUILT_BROWSER_MOCKS_REQUIRE_EXPLICIT_ISOLATED_POLICY_WITHOUT_PRODUCTION_CONFIG');
});

const resourceDump = `Package name=ai.caseops.mobile.dev.localacceptance id=7f
  type raw id=10 entryCount=1
    resource 0x7f100000 raw/caseops_local_acceptance_ca
      () (file) res/Ap.pem
  type xml id=14 entryCount=1
    resource 0x7f140000 xml/caseops_local_acceptance_network
      () (file) res/RM.xml type=XML
`;
const manifestDump = `N: android=http://schemas.android.com/apk/res/android (line=2)
  E: manifest (line=2)
    A: package="ai.caseops.mobile.dev.localacceptance" (Raw: "ai.caseops.mobile.dev.localacceptance")
      E: application (line=3)
        A: http://schemas.android.com/apk/res/android:allowBackup(0x01010280)=false
        A: http://schemas.android.com/apk/res/android:usesCleartextTraffic(0x010104ec)=false
        A: http://schemas.android.com/apk/res/android:networkSecurityConfig(0x01010527)=@0x7f140000
`;
const networkDump = `E: network-security-config (line=2)
    E: base-config (line=3)
      A: cleartextTrafficPermitted=false
        E: trust-anchors (line=4)
            E: certificates (line=4)
              A: src="system" (Raw: "system")
    E: domain-config (line=7)
      A: cleartextTrafficPermitted=false
        E: domain (line=8)
          A: includeSubdomains=false
            T: 'localhost'
        E: domain (line=9)
          A: includeSubdomains=false
            T: 'ip6-localhost'
        E: domain (line=10)
          A: includeSubdomains=false
            T: '127.0.0.1'
        E: domain (line=11)
          A: includeSubdomains=false
            T: '[::1]'
        E: trust-anchors (line=12)
            E: certificates (line=12)
              A: src="system" (Raw: "system")
    E: domain-config (line=14)
      A: cleartextTrafficPermitted=false
        E: domain (line=15)
          A: includeSubdomains=false
            T: '10.0.2.2'
        E: trust-anchors (line=16)
            E: certificates (line=16)
              A: src=@0x7f100000
`;
const zipInventory = [
  { name: 'AndroidManifest.xml', length: 1000 },
  { name: 'assets/index.android.bundle', length: 2000 },
  { name: 'assets/app.config', length: 1000 },
  { name: 'res/Ap.pem', length: Buffer.byteLength(certificate) },
  { name: 'res/RM.xml', length: 1000 },
];

test('optimized APK names resolve through SDK identities and compiled manifest/XML pointers', async () => {
  const build = await import('./build-acceptance.mjs');
  const resources = build.resolveAndroidAcceptanceResources(resourceDump);
  assert.deepEqual(resources.ca, { id: '0x7f100000', path: 'res/Ap.pem' });
  assert.deepEqual(resources.network, { id: '0x7f140000', path: 'res/RM.xml' });
  build.verifyAndroidCompiledSecurity(resources, manifestDump, networkDump, ['10.0.2.2']);
  assert.equal(build.verifyAndroidZipEvidence(resources, zipInventory, Buffer.from(certificate), digest(certificate)).publicCaSha256, digest(certificate));
  const renamed = resourceDump.replaceAll('res/Ap.pem', 'res/Another.pem').replaceAll('res/RM.xml', 'res/Another.xml')
    .replaceAll('0x7f100000', '0x7f210005').replaceAll('0x7f140000', '0x7f220007');
  const dynamic = build.resolveAndroidAcceptanceResources(renamed);
  build.verifyAndroidCompiledSecurity(dynamic, manifestDump.replaceAll('0x7f140000', '0x7f220007'),
    networkDump.replaceAll('0x7f100000', '0x7f210005'), ['10.0.2.2']);
});

for (const [label, altered] of [
  ['missing', resourceDump.replace('raw/caseops_local_acceptance_ca', 'raw/not_the_ca')],
  ['duplicate name', resourceDump + '    resource 0x7f100008 raw/caseops_local_acceptance_ca\n      () (file) res/other.pem\n'],
  ['duplicate ID', resourceDump + '    resource 0x7f100000 raw/other\n      () (file) res/other.pem\n'],
  ['qualified alternate', resourceDump.replace('() (file) res/Ap.pem', '() (file) res/Ap.pem\n      (v37) (file) res/other.pem')],
  ['traversal', resourceDump.replace('res/Ap.pem', 'res/../outside.pem')],
  ['absolute', resourceDump.replace('res/Ap.pem', '/res/Ap.pem')],
  ['backslash', resourceDump.replace('res/Ap.pem', 'res\\Ap.pem')],
  ['misleading suffix', resourceDump.replace('raw/caseops_local_acceptance_ca', 'raw/caseops_local_acceptance_ca_fake')],
  ['shared ZIP path', resourceDump.replace('res/RM.xml', 'res/Ap.pem')],
  ['malformed extra header', resourceDump + '    resource invalid raw/caseops_local_acceptance_ca\n'],
]) {
  test(`SDK resource lookup rejects ${label}`, async () => {
    const { resolveAndroidAcceptanceResources } = await import('./build-acceptance.mjs');
    assert.throws(() => resolveAndroidAcceptanceResources(altered), /RESOURCE|ZIP/);
  });
}

test('APK ZIP verification rejects missing/duplicate entries, traversal and wrong CA bytes or source hash', async () => {
  const build = await import('./build-acceptance.mjs');
  const resources = build.resolveAndroidAcceptanceResources(resourceDump);
  for (const inventory of [zipInventory.slice(0, -1), [...zipInventory, zipInventory[3]],
    [...zipInventory, { name: 'res/../evil', length: 1 }],
    [...zipInventory, { name: '/absolute', length: 1 }],
    [...zipInventory, { name: 'res\\evil', length: 1 }],
    zipInventory.map((entry) => entry.name === 'res/Ap.pem' ? { ...entry, length: 16385 } : entry)]) {
    assert.throws(() => build.verifyAndroidZipEvidence(resources, inventory, Buffer.from(certificate), digest(certificate)), /ZIP|APK/);
  }
  assert.throws(() => build.verifyAndroidZipEvidence(resources, zipInventory, Buffer.from(certificate), '0'.repeat(64)), /CA_HASH_MISMATCH/);
  assert.throws(() => build.verifyAndroidZipEvidence(resources, zipInventory, Buffer.from(certificate.replace('CERTIFICATE', 'NOT_CERTIFICATE')), digest(certificate)), /CA_HASH_MISMATCH/);
});

for (const [label, manifest, network] of [
  ['wrong manifest pointer', manifestDump.replace('@0x7f140000', '@0x7f140001'), networkDump],
  ['wrong CA pointer', manifestDump, networkDump.replace('@0x7f100000', '@0x7f100001')],
  ['duplicate manifest pointer', manifestDump + '        A: http://schemas.android.com/apk/res/android:networkSecurityConfig(0x01010527)=@0x7f140000\n', networkDump],
  ['cleartext', manifestDump, networkDump.replace('cleartextTrafficPermitted=false', 'cleartextTrafficPermitted=true')],
  ['user CA substitute', manifestDump, networkDump.replace('src=@0x7f100000', 'src="user" (Raw: "user")')],
  ['foreign CA host', manifestDump, networkDump.replace("T: '10.0.2.2'", "T: 'caseops.ai'")],
  ['wildcard host', manifestDump, networkDump.replace('includeSubdomains=false', 'includeSubdomains=true')],
  ['backup', manifestDump.replace('allowBackup(0x01010280)=false', 'allowBackup(0x01010280)=true'), networkDump],
  ['debuggable', manifestDump + '        A: http://schemas.android.com/apk/res/android:debuggable(0x0101000f)=true\n', networkDump],
  ['fake named CA string', manifestDump, networkDump.replace('src=@0x7f100000', 'src="@raw/caseops_local_acceptance_ca" (Raw: "@raw/caseops_local_acceptance_ca")')],
  ['wrong framework attribute ID', manifestDump.replace('networkSecurityConfig(0x01010527)', 'networkSecurityConfig(0x01010001)'), networkDump],
  ['extra trust source', manifestDump, networkDump + '            E: certificates (line=18)\n              A: src="system" (Raw: "system")\n'],
]) {
  test(`compiled security verification rejects ${label}`, async () => {
    const build = await import('./build-acceptance.mjs');
    assert.throws(() => build.verifyAndroidCompiledSecurity(build.resolveAndroidAcceptanceResources(resourceDump), manifest, network, ['10.0.2.2']),
      /SDK_XML|COMPILED|MANIFEST|NETWORK|BASE|SUBDOMAIN|TRUST|DOMAIN|CERTIFICATE|FRAMEWORK/);
  });
}

test('SDK resource and XML parsers enforce byte, line and structural bounds', async () => {
  const build = await import('./build-acceptance.mjs');
  assert.throws(() => build.resolveAndroidAcceptanceResources('x'.repeat(16 * 1024 * 1024 + 1)), /SDK_DUMP_SIZE_BOUND/);
  assert.throws(() => build.resolveAndroidAcceptanceResources('x'.repeat(8193)), /SDK_DUMP_LINE_BOUND/);
  assert.throws(() => build.verifyAndroidCompiledSecurity(build.resolveAndroidAcceptanceResources(resourceDump),
    manifestDump, networkDump + 'E: network-security-config (line=100)\n', ['10.0.2.2']), /ONE_COMPILED_XML_ROOT_REQUIRED/);
});

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
    !/^(CASEOPS_MOBILE_|CASEOPS_NATIVE_LINK_|EXPO_PUBLIC_|__EXPO_CONFIG_MODE$|EX_UPDATES_NATIVE_DEBUG$|SKIP_BUNDLING$)/.test(key))),
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
  assert.deepEqual(config.extra.nativeLinkPolicy, { mode: 'disabled' });
  assert.equal(config.ios.infoPlist.NSAppTransportSecurity, undefined);
  assert.equal(config.android.networkSecurityConfig, undefined);
  assert.doesNotMatch(JSON.stringify(config), /BEGIN CERTIFICATE|public-ca\.pem|fingerprint256/);
});

function publicLinkFixture(t, syntheticDataOnly = true) {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'caseops-native-links-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const config = { schemaVersion: 1, kind: 'caseops-native-links', syntheticDataOnly,
    redirectUri: syntheticDataOnly ? 'https://native.invalid/native/oauth/callback' : 'https://native.caseops.ai/native/oauth/callback',
    ios: { bundleIdentifier: 'ai.caseops.mobile', applicationIdentifierPrefix: 'X9Y8Z7W6V5' },
    android: { packageName: 'ai.caseops.mobile', signingCertificateSha256: [digest('public synthetic signing certificate test bytes')] } };
  const file = path.join(dir, 'links.json'), bytes = JSON.stringify(config) + '\n'; writeFileSync(file, bytes);
  return { dir, file, config, bytes, env: { CASEOPS_NATIVE_LINK_CONFIG_FILE: file, CASEOPS_NATIVE_LINK_CONFIG_SHA256: digest(bytes) } };
}
test('production Expo configuration refuses absent, partial, tampered and synthetic public link inputs', t => {
  assert.throws(() => expoConfig({ NODE_ENV: 'production', __EXPO_CONFIG_MODE: 'production' }), /IMMUTABLE_NATIVE_LINK_CONFIG_REQUIRED/);
  const f = publicLinkFixture(t);
  assert.throws(() => readNativeLinkConfig(f.env), /SYNTHETIC_NATIVE_LINK_CONFIG_FORBIDDEN/);
  assert.throws(() => readNativeLinkConfig({ CASEOPS_NATIVE_LINK_CONFIG_FILE: f.file }), /IMMUTABLE_NATIVE_LINK_CONFIG_REQUIRED/);
  writeFileSync(f.file, f.bytes + ' ');
  assert.throws(() => readNativeLinkConfig(f.env, { allowSynthetic: true }), /HASH_MISMATCH/);
});
test('complete immutable structural config projects exactly matching mobile, web, API and association identities without enabling auth', t => {
  const f = publicLinkFixture(t, false), loaded = readNativeLinkConfig(f.env);
  const config = expoConfig({ ...f.env, NODE_ENV: 'production' }), p = loaded.projections;
  assert.equal(config.scheme, undefined);
  assert.equal(config.ios.bundleIdentifier, f.config.ios.bundleIdentifier);
  assert.deepEqual(config.ios.associatedDomains, ['applinks:native.caseops.ai']);
  assert.deepEqual(config.android.intentFilters, p.mobile.android.intentFilters);
  assert.equal(config.android.package, f.config.android.packageName);
  assert.deepEqual(config.extra.nativeLinkPolicy, p.policy);
  assert.deepEqual(JSON.parse(p.apiEnvironment.CASEOPS_NATIVE_REDIRECT_URIS), [config.extra.nativeLinkPolicy.redirectUri]);
  assert.deepEqual(Object.keys(p.apiEnvironment), ['CASEOPS_NATIVE_REDIRECT_URIS']);
  assert.deepEqual(p.appleAppSiteAssociation.applinks.details[0].appIDs, ['X9Y8Z7W6V5.ai.caseops.mobile']);
  assert.equal(p.assetlinks[0].target.package_name, config.android.package);
  assert.deepEqual(p.assetlinks[0].target.sha256_cert_fingerprints, [f.config.android.signingCertificateSha256[0].toUpperCase().match(/../g).join(':')]);
  assert.equal(config.extra.nativeLinkPolicy.configSha256, digest(f.bytes));
});
test('production policy rejects reserved endpoints, scheme downgrade, QA identities and malformed or unknown fields', t => {
  const f = publicLinkFixture(t, false);
  for (const redirectUri of ['caseops://oauth/callback', 'http://native.caseops.ai/native/oauth/callback', 'https://native.invalid/native/oauth/callback', 'https://example.com/native/oauth/callback', 'https://native.caseops.ai/native/oauth/callback/extra', 'https://native.caseops.ai:8443/native/oauth/callback', 'https://native.caseops.ai/native/oauth/callback?x=1'])
    assert.throws(() => linkPolicy.validateNativeLinkConfig({ ...f.config, redirectUri }));
  assert.throws(() => linkPolicy.validateNativeLinkConfig({ ...f.config, arbitrary: true }));
  assert.throws(() => linkPolicy.validateNativeLinkConfig({ ...f.config, ios: { ...f.config.ios, bundleIdentifier: 'ai.caseops.mobile.dev' } }));
  assert.throws(() => linkPolicy.validateNativeLinkConfig({ ...f.config, ios: { ...f.config.ios, applicationIdentifierPrefix: 1234567890 } }));
  assert.throws(() => linkPolicy.validateNativeLinkConfig({ ...f.config, android: { ...f.config.android, signingCertificateSha256: ['a'.repeat(64)] } }));
});
test('native public config is read and hashed from the opened descriptor, with no parse-error content reflection', t => {
  const f = publicLinkFixture(t), fs = require('node:fs'), original = fs.readFileSync;
  let descriptorReads = 0;
  try {
    fs.readFileSync = function(file, ...args) {
      if (typeof file === 'number') { descriptorReads++; writeFileSync(f.file + '.replacement', '{}'); }
      return original.call(this, file, ...args);
    };
    const loaded = readNativeLinkConfig(f.env, { allowSynthetic: true });
    assert.equal(descriptorReads, 1); assert.equal(loaded.bytes.toString(), f.bytes);
  } finally { fs.readFileSync = original; }
  const malformed = 'PRIVATE_INVALID_INPUT_NOT_FOR_ERROR_MESSAGES'; writeFileSync(f.file, malformed);
  assert.throws(() => readNativeLinkConfig({ ...f.env, CASEOPS_NATIVE_LINK_CONFIG_SHA256: digest(malformed) }, { allowSynthetic: true }), error => {
    assert.equal(error.message, 'NATIVE_LINK_CONFIG_JSON_REQUIRED'); assert.ok(!error.message.includes(malformed)); return true;
  });
  const output = path.join(f.dir, 'malformed-output');
  const refused = spawnSync(process.execPath, [path.join(repo, 'scripts/mobile/prepare-native-links.mjs'),
    '--config', f.file, '--sha256', digest(malformed), '--output', output, '--synthetic'], {
    cwd: repo, encoding: 'utf8', timeout: 10000,
  });
  assert.equal(refused.status, 1);
  assert.equal(refused.stdout, '');
  assert.equal(refused.stderr.trim(), 'NATIVE_LINK_CONFIG_JSON_REQUIRED');
  assert.ok(!refused.stderr.includes(malformed));
  assert.equal(existsSync(output), false);
});
test('actual offline generator emits deterministic hash-bound public projections only into a fresh directory, preserves earlier snapshots', async t => {
  const { prepareNativeLinks } = await import('./prepare-native-links.mjs');
  const f = publicLinkFixture(t), first = path.join(f.dir, 'first'), second = path.join(f.dir, 'second');
  assert.throws(() => prepareNativeLinks({ file: f.file, sha256: digest(f.bytes), output: first }), /SYNTHETIC/);
  const a = prepareNativeLinks({ file: f.file, sha256: digest(f.bytes), output: first, synthetic: true });
  prepareNativeLinks({ file: f.file, sha256: digest(f.bytes), output: second, synthetic: true });
  for (const file of ['config-evidence.json', 'projections.json', 'apple-app-site-association', 'assetlinks.json', 'api-environment.json'])
    assert.deepEqual(readFileSync(path.join(first, file)), readFileSync(path.join(second, file)));
  assert.equal(a.productionEnabled, false); assert.equal(a.platformAssociationVerified, false);
  writeFileSync(f.file, '{}\n');
  assert.equal(readFileSync(a.configEvidence.path, 'utf8'), f.bytes);
  assert.throws(() => readNativeLinkConfig(f.env, { allowSynthetic: true }), /HASH_MISMATCH/);
  assert.throws(() => prepareNativeLinks({ file: a.configEvidence.path, sha256: a.configEvidence.sha256, output: first, synthetic: true }), /NEW_ABSOLUTE/);
});
test('native link runtime/generator imports are in the actual source snapshot and existing web builder closure', () => {
  const snapshot = readFileSync(path.join(repo, 'scripts/mobile/source-snapshot.mjs'), 'utf8');
  for (const file of ['apps/web/lib/native-link-policy.cjs', 'apps/web/lib/native-link-policy.d.cts', 'apps/web/lib/native-link-config.cjs', 'apps/web/lib/native-link-config.d.cts', 'scripts/mobile/prepare-native-links.mjs']) assert.ok(snapshot.includes(file));
  assert.match(readFileSync(path.join(repo, 'apps/web/Dockerfile'), 'utf8'), /COPY apps\/web \.\//);
  const metro = require(path.join(app, 'metro.config.js'));
  assert.ok(metro.watchFolders.includes(path.join(repo, 'apps/web/lib')), 'SHARED_PUBLIC_RUNTIME_POLICY_MUST_BE_VISIBLE_TO_METRO');
  assert.doesNotMatch(readFileSync(path.join(app, 'src/auth/handoff.ts'), 'utf8'), /native-link-config\.cjs|node:fs|node:crypto/);
});
test('actual source fingerprint and dirty fence include shared callback policy changes', t => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'caseops-link-snapshot-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  mkdirSync(path.join(dir, 'apps/mobile'), { recursive: true });
  mkdirSync(path.join(dir, 'apps/web/lib'), { recursive: true });
  writeFileSync(path.join(dir, 'apps/mobile/index.ts'), 'export {};\n');
  const policy = path.join(dir, 'apps/web/lib/native-link-policy.cjs');
  writeFileSync(policy, 'module.exports = { mode: "disabled" };\n');
  execFileSync('git', ['init', '--quiet'], { cwd: dir });
  execFileSync('git', ['add', '.'], { cwd: dir });
  execFileSync('git', ['-c', 'user.name=Offline fixture', '-c', 'user.email=offline@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Synthetic source snapshot'], { cwd: dir });
  const before = sourceSnapshot(dir); assert.equal(before.sourceDirty, false);
  writeFileSync(policy, 'module.exports = { mode: "changed" };\n');
  const after = sourceSnapshot(dir); assert.equal(after.sourceDirty, true);
  assert.notEqual(after.sourceFingerprint, before.sourceFingerprint);
  assert.equal(after.sourceSha, before.sourceSha);
});

test('Android public config is marker-enforced, exact-source and leaves iOS defaults intact', (t) => {
  const { env, file } = fixture(t);
  const config = expoConfig(env);
  assert.equal(config.extra.automatedTest, true);
  assert.deepEqual(config.extra.nativeLinkPolicy, { mode: 'local', redirectUri: 'caseops://oauth/callback' });
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
  assert.deepEqual(config.extra.nativeLinkPolicy, { mode: 'local', redirectUri: 'caseops://oauth/callback' });
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
  assert.match(ios, /CODE_SIGNING_ALLOWED=YES/);
  assert.match(ios, /CODE_SIGN_IDENTITY=-/);
  assert.match(ios, /CODE_SIGN_INJECT_BASE_ENTITLEMENTS=YES/);
  assert.doesNotMatch(ios, /CODE_SIGNING_ALLOWED=NO|CODE_SIGNING_REQUIRED=NO/);
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
