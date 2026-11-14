import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import tls from 'node:tls';
import { EventEmitter } from 'node:events';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { recordLink } from '../../apps/mobile/e2e/client-extensions-ui.mjs';
import { clientExtensionScenarios } from '../../apps/mobile/e2e/client-extensions-20261028.mjs';
import { qualificationUrl, validateQualificationDeclaration, verifyQualificationApkFacts,
  verifyQualificationAssociation, verifyQualificationManifest, observeAndroidHttpsQualification,
  withAndroidHttpsQualification, qualificationHttpsJson } from './android-https-qualification.mjs';
import { deriveQualificationApk } from './android-qualification-apk.mjs';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const sha = value => createHash('sha256').update(value).digest('hex');
function zip(entries) {
  let offset = 0; const locals = [], directory = [];
  for (const [name, bytes] of Object.entries(entries)) {
    let crc = 0xffffffff;
    for (const byte of bytes) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0); }
    crc = (crc ^ 0xffffffff) >>> 0;
    const n = Buffer.from(name), local = Buffer.alloc(30), central = Buffer.alloc(46);
    local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20, 4); local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(bytes.length, 18); local.writeUInt32LE(bytes.length, 22); local.writeUInt16LE(n.length, 26);
    central.writeUInt32LE(0x02014b50); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6);
    central.writeUInt32LE(crc, 16); central.writeUInt32LE(bytes.length, 20); central.writeUInt32LE(bytes.length, 24);
    central.writeUInt16LE(n.length, 28); central.writeUInt32LE((0o100644 << 16) >>> 0, 38); central.writeUInt32LE(offset, 42);
    locals.push(local, n, bytes); directory.push(central, n); offset += local.length + n.length + bytes.length;
  }
  const table = Buffer.concat(directory), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50); end.writeUInt16LE(directory.length / 2, 8); end.writeUInt16LE(directory.length / 2, 10);
  end.writeUInt32LE(table.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, table, end]);
}
function manifest() {
  return `N: android=http://schemas.android.com/apk/res/android (line=1)
E: manifest (line=1)
  E: application (line=2)
    A: android:allowBackup=false
    A: android:usesCleartextTraffic=false
    E: activity (line=3)
      A: android:exported=true
      E: intent-filter (line=4)
        A: android:autoVerify=true
        E: action (line=5)
          A: android:name="android.intent.action.VIEW"
        E: category (line=6)
          A: android:name="android.intent.category.BROWSABLE"
        E: category (line=7)
          A: android:name="android.intent.category.DEFAULT"
        E: data (line=8)
          A: android:scheme="https"
          A: android:host="caseops.ai"
          A: android:pathPrefix="/native/open/"
`;
}
function fixture(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-https-contract-')));
  fs.chmodSync(root, 0o700); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const save = (name, value) => { const file = path.join(root, name), bytes = Buffer.isBuffer(value) ? value : Buffer.from(typeof value === 'string' ? value : JSON.stringify(value));
    fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 }); fs.writeFileSync(file, bytes, { flag: 'wx', mode: 0o600 }); return { path: file, sha256: sha(bytes) }; };
  const linkPath = path.join(ROOT, 'apps/web/native-links/production.json'), linkBytes = fs.readFileSync(linkPath), config = JSON.parse(linkBytes);
  const source = { sourceSha: 'a'.repeat(40), sourceFingerprint: 'b'.repeat(64), sourceDirty: false, inputFileCount: 250 };
  const subject = { companyId: '11111111-1111-4111-8111-111111111111', userId: '22222222-2222-4222-8222-222222222222',
    membershipId: '33333333-3333-4333-8333-333333333333', companySlug: 'test-native-https-0123456789ab',
    principalLabel: 'Disposable HTTPS verifier', workspaceLabel: 'Disposable HTTPS workspace',
    matter: { id: '44444444-4444-4444-8444-444444444444', code: 'TEST-HTTPS-0123456789ab' } };
  const nativeLinks = { path: linkPath, sha256: sha(linkBytes) }, certificateSha256 = config.android.signingCertificateSha256[0];
  const storeBuild = save('store-build.json', { version: '1.0.0', androidVersionCode: 4 });
  const expected = { version: '1.0.0', androidVersionCode: 4, storeBuild };
  const attestation = { storeBuild, kind: 'caseops-store-artifact-source', qualificationOnly: true, nativeAcceptanceClaimed: false,
    submissionAuthorization: 'separate-artifact-bound-promotion-required', source: { sourceSha: source.sourceSha, sourceFingerprint: source.sourceFingerprint, inputFileCount: source.inputFileCount },
    nativeLinks, apiOrigin: 'https://api.caseops.ai', webOrigin: 'https://caseops.ai' };
  const apkBytes = zip({ 'assets/caseops-store-attestation.json': Buffer.from(JSON.stringify(attestation)) });
  const apk = save('candidate.apk', apkBytes), api = { origin: attestation.apiOrigin, sourceSha: 'c'.repeat(40), revision: 'qualification-api' },
    web = { origin: attestation.webOrigin, sourceSha: 'd'.repeat(40), revision: 'qualification-web' };
  const normalApiEvidence = save('normal-api.json', { kind: 'caseops-normal-api-https-qualification-subject', noPaidMarker: 'no-paid-providers', directDatabaseWrites: false,
    syntheticDataOnly: true, observed: true, contractOnly: false, mfaApiEnrollmentVerified: true, entitlementModified: false, backendSourceSha: api.sourceSha,
    acknowledgements: ['GET /api/build', 'POST /api/bootstrap/company', 'POST /api/auth/mfa/enroll', 'POST /api/auth/mfa/enroll/verify', 'GET /api/auth/security', 'GET /api/auth/me', 'POST /api/matters/', 'GET /api/matters/{owned-matter}', 'GET /api/build'].map(row => ({ method: row.slice(0, row.indexOf(' ')), route: row.slice(row.indexOf(' ') + 1), status: 200 })),
    subject, apiOrigin: api.origin, backendRevision: api.revision });
  const aab = save('candidate.aab', 'SYNTHETIC_AAB');
  const recipe = save('recipe.json', { kind: 'caseops-store-packaging-request', platform: 'android', storeBuild, source: attestation.source, nativeLinks, apiOrigin: api.origin, webOrigin: web.origin, signing: { uploadCertificateSha256: certificateSha256 } });
  const qualificationBuild = save('candidate-result.json', { kind: 'caseops-android-qualification-result', observed: true, qualificationOnly: true,
    distributionSigningVerified: true, contractOnly: false, submissionAllowed: false, storeAcceptance: false, uploaded: false,
    cleanup: { complete: true }, sourceSha: source.sourceSha, recipe, artifact: aab, postflight: { artifactSha256: aab.sha256, distributionSigningVerified: true },
    phases: ['reservation', 'signing-admission', 'build', 'artifact-postflight', 'source-postflight'].map(name => ({ name, status: 'passed' })),
    qualificationApk: { kind: 'caseops-android-qualification-apk', artifact: apk, aab, submissionAllowed: false, installedAcceptance: false } });
  const tools = Object.fromEntries(['adb', 'apksigner', 'aapt2', 'java'].map(role => { const ref = save('tools/' + role, 'SYNTHETIC_' + role); fs.chmodSync(ref.path, 0o700); return [role, { ...ref, sizeBytes: fs.statSync(ref.path).size }]; }));
  const runtime = save('tools/runtime.jar', 'SYNTHETIC_RUNTIME'); tools.runtimeInputs = [{ ...runtime, sizeBytes: fs.statSync(runtime.path).size }];
  const q = { schemaVersion: 1, kind: 'caseops-android-https-qualification', platform: 'android', caseId: 'CX28-LINK-05', source, udid: 'emulator-5584',
    apk, qualificationBuild, nativeLinks, certificateSha256, origin: 'https://caseops.ai',
    url: `https://caseops.ai/native/open/workspaces/${subject.companyId}/matters/${subject.matter.id}`, subject, normalApiEvidence, api, web, tools,
    output: path.join(root, 'https-qualification') };
  const acceptedTools = { observed: true, platform: 'android', executables: ['adb', 'apksigner', 'aapt2', 'java'].map(role => ({ role, file: {
    path: tools[role].path, sha256: tools[role].sha256, extent: tools[role].sizeBytes } })), httpsRuntimeInputs: tools.runtimeInputs };
  const commands = [], requests = [], events = [], base = { platform: 'android', caseId: q.caseId, source: structuredClone(source), udid: q.udid, adbPort: 5038,
    acceptedTools, outputRoot: root, deadline: Date.now() + 300000, checkBudget() {}, charge() {}, record: row => events.push(row) };
  let currentPackage = 'ai.caseops.mobile.dev.localacceptance', appState = 4, pending = false;
  const state = { verified: 'caseops.ai: verified', resolver: 'ai.caseops.mobile/.MainActivity', badging: "package: name='ai.caseops.mobile' versionCode='4' versionName='1.0.0'", manifest: manifest(),
    signature: `Verifies\nSigner #1 certificate SHA-256 digest: ${certificateSha256}\n`, installedBytes: apkBytes, loseIntentAck: false, foregroundIntent: true };
  const dependencies = {
    command(executable, args, options) {
      const role = ['adb', 'apksigner', 'aapt2', 'java'].find(name => tools[name].path === executable); assert.ok(role); commands.push({ role, args, options });
      if (role === 'aapt2') return args.includes('xmltree') ? state.manifest : state.badging;
      if (role === 'apksigner') return state.signature;
      assert.equal(role, 'adb'); assert.deepEqual(args.slice(0, 4), ['-P', '5038', '-s', q.udid]);
      const a = args.slice(4);
      if (a[0] === 'pull') { fs.writeFileSync(a[2], state.installedBytes, { flag: 'wx', mode: 0o600 }); return ''; }
      if (a.slice(0, 3).join(' ') === 'shell pm path') return 'package:/data/app/owned/ai.caseops.mobile/base.apk\n';
      if (a.includes('get-app-links')) return state.verified;
      if (a.includes('resolve-activity')) return state.resolver;
      if (a.includes('start')) { if (state.loseIntentAck) throw Error('SYNTHETIC_INTENT_ACK_LOST');
        if (state.foregroundIntent) { currentPackage = 'ai.caseops.mobile'; appState = 4; pending = true; }
        return 'Status: ok\nActivity: ai.caseops.mobile/.MainActivity\n'; }
      throw Error('UNEXPECTED_FAKE_COMMAND');
    },
    async https(url) { requests.push(url); if (url.endsWith('/assetlinks.json')) return [{ relation: ['delegate_permission/common.handle_all_urls'], target: {
      namespace: 'android_app', package_name: 'ai.caseops.mobile', sha256_cert_fingerprints: [certificateSha256] } }];
      const serving = url.startsWith(api.origin) ? api : web; return { release_sha: serving.sourceSha, revision: serving.revision }; },
  };
  const oldFixture = { appId: currentPackage, udid: q.udid, cx: { links: { own: 'caseops://synthetic' } } };
  const context = { platform: 'android', caseId: q.caseId, fixture: oldFixture, binaryHash: 'e'.repeat(64), nativeOperations: 0,
    workflowDomain: 'emulator', record: row => events.push(row), checkBudget() {},
    driver: { async activateApp(app) { currentPackage = app; appState = 4; }, async terminateApp() { appState = 1; currentPackage = 'launcher'; },
      async getCurrentPackage() { return currentPackage; }, async queryAppState() { return appState; },
      async execute() { throw Error('PACKAGE_FORCED_APP_LINK_FORBIDDEN'); },
      async waitUntil(condition) { assert.equal(!!await condition(), true, 'SYNTHETIC_NATIVE_CONDITION_FAILED'); },
      async elementClick(id) { if (id === 'record-link-open') pending = false; },
      async $$(query) { const id = query.replace(/^id=/, ''); if (id === 'record-link-open' && !pending) return [];
        if (!['tab-today', 'screen-today', 'account-open', 'account-principal', 'account-workspace', 'record-link-open', 'matter-code'].includes(id)) return [];
        return [{ elementId: id, isDisplayed: async () => true, isEnabled: async () => true, getText: async () => id === 'account-principal' ? subject.principalLabel : id === 'account-workspace' ? subject.workspaceLabel : id === 'matter-code' ? subject.matter.code : '' }]; },
    } };
  context.withHttpsQualification = action => withAndroidHttpsQualification(context, () => observeAndroidHttpsQualification(q, base, dependencies), action);
  return { root, save, q, base, source, config, attestation, state, commands, requests, events, context, oldFixture, apkBytes, dependencies, expected,
    observe: () => observeAndroidHttpsQualification(q, base, dependencies), intentCommands: () => commands.filter(row => row.args.includes('start')) };
}

test('a caller-written observed association cannot authorize a production URL dispatch', async () => {
  let dispatched = 0;
  const context = { platform: 'android', caseId: 'CX28-LINK-05', binaryHash: 'b'.repeat(64), nativeOperations: 0,
    fixture: { udid: 'owned', appId: 'ai.caseops.mobile', cx: { links: {
      verifiedAssociation: { observed: true, binaryHash: 'b'.repeat(64), udid: 'owned', mode: 'production', origin: 'https://caseops.ai' },
    } } }, driver: { execute: async () => { dispatched++; } }, record() {}, checkBudget() {}, workflowDomain: 'emulator' };
  await assert.rejects(recordLink(context, 'https://caseops.ai/native/open/workspaces/test/matters/test', { verifiedHttps: true }), /CX_ACTUAL_VERIFIED_HTTPS_ARTIFACT_REQUIRED/);
  assert.equal(dispatched, 0);
});

test('qualification declaration rejects drift, local origins, another subject and extra authority flags', t => {
  const f = fixture(t), admit = q => validateQualificationDeclaration(q, { source: f.base.source, udid: f.base.udid, config: f.config, configSha256: f.q.nativeLinks.sha256 });
  assert.equal(admit(f.q), 'ai.caseops.mobile');
  for (const patch of [{ observed: true }, { caseId: 'CX28-LINK-04' }, { platform: 'ios' }, { udid: 'other' }, { origin: 'https://other.caseops.ai' }, { certificateSha256: 'f'.repeat(64) }]) assert.throws(() => admit({ ...f.q, ...patch }));
  for (const origin of ['https://localhost', 'https://127.0.0.1', 'https://[::1]', 'https://private.local', 'https://service.internal']) assert.throws(() => admit({ ...f.q, api: { ...f.q.api, origin } }), /QUAL_PUBLIC_SERVING_REQUIRED/);
  for (const suffix of ['?token=x', '#fragment', '/extra']) assert.throws(() => qualificationUrl(f.q.url + suffix, f.q.origin, f.q.subject));
  assert.throws(() => qualificationUrl(f.q.url.replace(f.q.subject.matter.id, '55555555-5555-4555-8555-555555555555'), f.q.origin, f.q.subject));
});
test('compiled HTTPS filter is one real tree with production transport settings', () => {
  verifyQualificationManifest(manifest(), 'https://caseops.ai');
  for (const [before, after] of [['android:autoVerify=true', 'android:autoVerify=false'], ['android:allowBackup=false', 'android:allowBackup=true'],
    ['android:usesCleartextTraffic=false', 'android:usesCleartextTraffic=true'], ['android:exported=true', 'android:exported=false'], ['"caseops.ai"', '"other.caseops.ai"'], ['"https"', '"caseops"']])
    assert.throws(() => verifyQualificationManifest(manifest().replace(before, after), 'https://caseops.ai'));
  assert.throws(() => verifyQualificationManifest(manifest().replace('    A: android:allowBackup=false', '    A: android:allowBackup=false\n    A: android:networkSecurityConfig=@0x7f010001'), 'https://caseops.ai'));
  assert.throws(() => verifyQualificationManifest(manifest() + '\0', 'https://caseops.ai'), /SDK_DUMP_SIZE_BOUND/);
  assert.throws(() => verifyQualificationManifest(manifest().replace('        A: android:autoVerify=true', '        A: android:autoVerify=true\n        A: android:autoVerify=true'), 'https://caseops.ai'), /DUPLICATE_SDK_XML_ATTRIBUTE/);
});
test('APK signer, package, source, non-submission and link-policy facts are independent', t => {
  const f = fixture(t), facts = { badging: f.state.badging, signature: f.state.signature, attestation: f.attestation };
  verifyQualificationApkFacts(facts, f.q, 'ai.caseops.mobile', f.expected);
  for (const patch of [{ badging: "package: name='ai.caseops.mobile.dev' " }, { signature: f.state.signature.replace(f.q.certificateSha256, 'f'.repeat(64)) },
    { attestation: { ...f.attestation, qualificationOnly: false } }, { attestation: { ...f.attestation, nativeAcceptanceClaimed: true } },
    { attestation: { ...f.attestation, source: { ...f.attestation.source, sourceSha: 'f'.repeat(40) } } }]) assert.throws(() => verifyQualificationApkFacts({ ...facts, ...patch }, f.q, 'ai.caseops.mobile', f.expected));
});
test('actual OS verified state and unforced default resolution cannot be replaced by DAL alone', t => {
  const f = fixture(t), facts = { dal: [{ relation: ['delegate_permission/common.handle_all_urls'], target: { namespace: 'android_app', package_name: 'ai.caseops.mobile', sha256_cert_fingerprints: [f.q.certificateSha256] } }], verified: f.state.verified, resolver: f.state.resolver };
  verifyQualificationAssociation(facts, f.q, 'ai.caseops.mobile', f.expected);
  for (const patch of [{ verified: 'caseops.ai: approved' }, { verified: 'other.caseops.ai: verified' }, { resolver: 'android/com.android.internal.app.ResolverActivity' }, { dal: [] }, { resolver: f.state.resolver + '\n' + f.state.resolver }])
    assert.throws(() => verifyQualificationAssociation({ ...facts, ...patch }, f.q, 'ai.caseops.mobile', f.expected));
});
test('the complete LINK05 callback dispatches cold/warm unforced once and restores QA identity', async t => {
  const f = fixture(t); await clientExtensionScenarios.find(row => row.id === 'CX28-LINK-05').run(f.context);
  assert.equal(f.intentCommands().length, 2);
  for (const row of f.intentCommands()) { assert.ok(!row.args.includes('-p') && !row.args.includes('-n')); assert.equal(row.options.env.ADB_SERVER_SOCKET, 'tcp:127.0.0.1:5038'); }
  assert.equal(f.context.fixture, f.oldFixture); assert.equal(f.context.binaryHash, 'e'.repeat(64)); assert.equal(await f.context.driver.getCurrentPackage(), f.oldFixture.appId);
  const proof = JSON.parse(fs.readFileSync(path.join(f.q.output, 'qualification-observation.json')));
  assert.equal(proof.contractOnly, true); assert.equal(proof.observed, false); assert.equal(proof.submissionAllowed, false); assert.equal(proof.nativeCaseCredit, 0);
  assert.equal(f.events.filter(row => row.boundary === 'actual-https-association-cold-and-warm').length, 1);
  await assert.rejects(recordLink(f.context, f.q.url, { verifiedHttps: true }));
});
test('failed or ambiguous SDK/OS witnesses cannot dispatch even one production intent', async t => {
  for (const patch of [{ signature: 'Verifies\nSigner #1 certificate SHA-256 digest: ' + 'f'.repeat(64) }, { verified: 'caseops.ai: none' }, { resolver: 'other.app/.Main' }, { manifest: manifest().replace('autoVerify=true', 'autoVerify=false') }]) {
    const f = fixture(t); Object.assign(f.state, patch); await assert.rejects(f.observe()); assert.equal(f.intentCommands().length, 0);
  }
});
test('a lost first intent acknowledgement is retained without replay and QA cleanup still runs', async t => {
  const f = fixture(t); f.state.loseIntentAck = true;
  await assert.rejects(clientExtensionScenarios.find(row => row.id === 'CX28-LINK-05').run(f.context), /SYNTHETIC_INTENT_ACK_LOST/);
  assert.equal(f.intentCommands().length, 1); assert.equal(f.context.fixture, f.oldFixture); assert.equal(await f.context.driver.getCurrentPackage(), f.oldFixture.appId);
  assert.equal(fs.existsSync(path.join(f.q.output, 'qualification-observation.json')), false);
});
test('installed-byte drift before the warm open refuses the second dispatch', async t => {
  const f = fixture(t), original = f.dependencies.command;
  f.dependencies.command = (binary, args, options) => { const result = original(binary, args, options); if (args.includes('start')) f.state.installedBytes = Buffer.from('CHANGED_INSTALLED_APK'); return result; };
  await assert.rejects(clientExtensionScenarios.find(row => row.id === 'CX28-LINK-05').run(f.context), /STORE_INPUT_HASH_MISMATCH/);
  assert.equal(f.intentCommands().length, 1); assert.equal(f.context.fixture, f.oldFixture);
});
test('a caller cannot substitute the accepted ADB or write outside this report', async t => {
  for (const mutate of [f => { f.q.tools.adb.sha256 = 'f'.repeat(64); }, f => { f.q.output = path.join(f.root, 'foreign', 'https-qualification'); }]) {
    const f = fixture(t); mutate(f); await assert.rejects(f.observe()); assert.equal(f.commands.length, 0);
  }
});
test('reporting failure after intent acknowledgement still restores the QA app', async t => {
  const f = fixture(t), original = Error('SYNTHETIC_REPORT_WRITE_FAILED');
  f.base.record = row => { if (row.mutation) throw original; };
  await assert.rejects(clientExtensionScenarios.find(row => row.id === 'CX28-LINK-05').run(f.context), error => error === original);
  assert.equal(f.intentCommands().length, 1); assert.equal(f.context.fixture, f.oldFixture); assert.equal(await f.context.driver.getCurrentPackage(), f.oldFixture.appId);
});
test('a late successful public read never mints a dispatch lease', async t => {
  const f = fixture(t); let now = Date.now(); f.base.deadline = now + 300000; f.dependencies.now = () => now;
  const original = f.dependencies.https; f.dependencies.https = async url => { const result = await original(url); now += 60001; return result; };
  await assert.rejects(f.observe(), /QUAL_DEADLINE/); assert.equal(f.intentCommands().length, 0);
});
test('every public HTTPS constructor uses bounded public roots, the no-paid marker and no redirects', async () => {
  const original = https.get; const calls = [];
  try {
    https.get = (url, options, callback) => { calls.push({ url, options }); const request = new EventEmitter(); request.destroy = error => { request.emit('error', error); request.emit('close'); };
      process.nextTick(() => { const response = new EventEmitter(); response.statusCode = 200; response.destroy = () => {};
        callback(response); response.emit('data', Buffer.from('{"safe":true}')); response.emit('end'); request.emit('close'); }); return request; };
    assert.deepEqual(await qualificationHttpsJson('https://caseops.ai/.well-known/assetlinks.json', Date.now() + 1000), { safe: true });
    assert.equal(calls.length, 1); assert.equal(calls[0].options.rejectUnauthorized, true); assert.equal(calls[0].options.agent, false);
    assert.equal(calls[0].options.ca, tls.rootCertificates); assert.equal(calls[0].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
    assert.throws(() => qualificationHttpsJson('https://caseops.ai/.well-known/assetlinks.json', Date.now() - 1), /QUAL_DEADLINE/);
  } finally { https.get = original; }
});
test('APK derivation consumes verified ZIP member bytes and cannot mark native acceptance', async t => {
  const f = fixture(t), output = path.join(f.root, 'derive'); fs.mkdirSync(output, { mode: 0o700 });
  const aab = f.save('input.aab', 'SYNTHETIC_AAB'), key = f.save('key.p12', 'SYNTHETIC_KEY_NOT_A_REAL_KEY'); let calls = 0;
  const tools = { ...f.q.tools, bundletool: f.save('tools/bundletool.jar', 'SYNTHETIC_BUNDLETOOL') };
  const result = await deriveQualificationApk({ aab, output, keystore: key, keyAlias: 'synthetic-upload', tools, deadline: Date.now() + 30000 }, async command => {
    calls++; assert.equal(command.role, 'qualification-apk'); assert.ok(command.args.includes('--mode=universal'));
    assert.ok(command.args.includes('--ks-pass=env:CASEOPS_UPLOAD_STORE_PASSWORD')); assert.ok(command.args.includes('--key-pass=env:CASEOPS_UPLOAD_KEY_PASSWORD'));
    const target = command.args.find(arg => arg.startsWith('--output=')).slice(9); fs.writeFileSync(target, zip({ 'universal.apk': f.apkBytes }), { flag: 'wx', mode: 0o600 });
  });
  assert.equal(calls, 1); assert.equal(result.artifact.sha256, f.q.apk.sha256); assert.equal(result.submissionAllowed, false); assert.equal(result.installedAcceptance, false); assert.equal(result.signatureClaimed, false);
});

test('falsy body and cleanup failures preserve the exact original value and still restore fixture', async t => {
  for (const original of [undefined, null, false, 0, '', Object.freeze(Error('FROZEN_BODY'))]) {
    const f = fixture(t), before = f.context.driver.terminateApp;
    f.context.driver.terminateApp = async () => { throw 0; };
    let failed = false;
    try { await withAndroidHttpsQualification(f.context, f.observe, async () => { throw original; }); }
    catch (error) { failed = true; assert.equal(error, original); }
    assert.equal(failed, true); assert.equal(f.context.fixture, f.oldFixture);
    assert.equal(await f.context.driver.getCurrentPackage(), f.oldFixture.appId);
    assert.equal(f.events.some(row => row.type === 'https_qualification_cleanup_failed' && row.bodyFailed), true);
    f.context.driver.terminateApp = before;
  }
});
test('falsy cleanup failure cannot turn a successful body into success', async t => {
  const f = fixture(t); let failure = false;
  const observed = await f.observe();
  const lease = { ...observed, async finish() { return { path: '/synthetic', sha256: 'f'.repeat(64) }; } };
  f.context.driver.terminateApp = async () => { throw undefined; };
  try { await withAndroidHttpsQualification(f.context, () => lease, async () => {}); }
  catch (error) { failure = true; assert.equal(error, undefined); }
  assert.equal(failure, true); assert.equal(f.context.fixture, f.oldFixture);
});
test('late native workspace read is refused before cold termination while independent cleanup restores QA', async t => {
  const f = fixture(t); let now = Date.now(), terminations = 0;
  f.dependencies.now = () => now;
  const find = f.context.driver.$$;
  f.context.driver.$$ = async query => (await find(query)).map(element => ({ ...element, async getText() {
    const value = await element.getText(); if (query === 'id=account-workspace') now += 60001; return value;
  } }));
  const terminate = f.context.driver.terminateApp;
  f.context.driver.terminateApp = async app => { terminations++; return terminate(app); };
  await assert.rejects(clientExtensionScenarios.find(row => row.id === 'CX28-LINK-05').run(f.context), /QUAL_DEADLINE/);
  assert.equal(terminations, 1); assert.equal(f.intentCommands().length, 0);
  assert.equal(f.context.fixture, f.oldFixture); assert.equal(await f.context.driver.getCurrentPackage(), f.oldFixture.appId);
});
test('a dead app or late warm-state observation cannot earn the second HTTPS dispatch', async t => {
  for (const late of [false, true]) {
    const f = fixture(t); let now = Date.now(), queries = 0;
    f.dependencies.now = () => now;
    const query = f.context.driver.queryAppState;
    f.context.driver.queryAppState = async app => {
      const result = await query(app); queries++;
      // cold, first foreground, then pre-second warm witness.
      if (queries === 3) { if (late) now += 60001; else return 1; }
      return result;
    };
    await assert.rejects(clientExtensionScenarios.find(row => row.id === 'CX28-LINK-05').run(f.context), late ? /QUAL_DEADLINE/ : /QUAL_ACTUAL_WARM_STATE_REQUIRED/);
    assert.equal(f.intentCommands().length, 1); assert.equal(f.context.fixture, f.oldFixture);
  }
});
test('late cleanup acknowledgement remains failed and never earns a restoration claim beyond its absolute reserve', async t => {
  const f = fixture(t); let now = Date.now(); f.dependencies.now = () => now;
  const observed = await f.observe(), cleanup = observed.cleanup;
  let calls = 0;
  const wrapped = { ...observed, async finish() { return { path: '/synthetic', sha256: 'f'.repeat(64) }; },
    cleanup: operation => cleanup(async () => { calls++; const result = await operation(); if (calls === 1) now += 90001; return result; }) };
  await assert.rejects(withAndroidHttpsQualification(f.context, () => wrapped, async () => {}), /QUAL_CLEANUP_DEADLINE/);
  assert.equal(f.context.fixture, f.oldFixture);
  assert.equal(f.events.some(row => row.type === 'https_qualification_cleanup_failed'), true);
});

test('the pinned SDK V2 and V3 signer forms retain exact signer inventory and reject mixed or unknown identities', t => {
  const f = fixture(t), facts = { badging: f.state.badging, attestation: f.attestation };
  for (const prefix of ['Signer #1', 'V2 Signer:', 'V3.0 Signer:']) {
    const signature = `Verifies\n${prefix} certificate SHA-256 digest: ${f.q.certificateSha256}\n`;
    verifyQualificationApkFacts({ ...facts, signature }, f.q, 'ai.caseops.mobile', f.expected);
    assert.throws(() => verifyQualificationApkFacts({ ...facts, signature: signature + `V2 Signer: certificate SHA-256 digest: ${'f'.repeat(64)}\n` }, f.q, 'ai.caseops.mobile', f.expected), /QUAL_ACTUAL_SIGNER_REQUIRED/);
  }
  assert.throws(() => verifyQualificationApkFacts({ ...facts, signature: `Verifies\nSigner #1 certificate SHA-256 digest: ${f.q.certificateSha256}\nUnknown signer certificate SHA-256 digest: ${f.q.certificateSha256}\n` }, f.q, 'ai.caseops.mobile', f.expected), /QUAL_UNRECOGNIZED_SIGNER_FORMAT/);
});

test('failed public metadata HTTP constructors retain strict TLS and the marker without retries', async () => {
  const original = https.get;
  try {
    for (const mode of ['status', 'tls', 'oversize', 'malformed', 'timeout']) {
      const calls = [];
      https.get = (url, options, callback) => {
        calls.push({ url, options }); const request = new EventEmitter();
        request.destroy = error => { request.emit('error', error); request.emit('close'); };
        if (mode !== 'timeout') process.nextTick(() => {
          if (mode === 'tls') { request.emit('error', Error('SYNTHETIC_TLS_REFUSED')); request.emit('close'); return; }
          const response = new EventEmitter(); response.statusCode = mode === 'status' ? 302 : 200;
          response.destroy = error => { if (error) response.emit('error', error); request.emit('close'); };
          callback(response);
          if (mode !== 'status') { response.emit('data', mode === 'oversize' ? Buffer.alloc(16385) : Buffer.from([0xff])); if (mode !== 'oversize') response.emit('end'); request.emit('close'); }
        });
        return request;
      };
      await assert.rejects(qualificationHttpsJson('https://caseops.ai/.well-known/assetlinks.json', Date.now() + (mode === 'timeout' ? 20 : 1000)));
      assert.equal(calls.length, 1); assert.equal(calls[0].options.rejectUnauthorized, true); assert.equal(calls[0].options.ca, tls.rootCertificates);
      assert.equal(calls[0].options.agent, false); assert.equal(calls[0].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
    }
  } finally { https.get = original; }
});

test('slow budget charging cannot dispatch a deferred native command beyond its active or cleanup deadline', async t => {
  for (const cleanup of [false, true]) {
    const f = fixture(t); let now = Date.now(); f.dependencies.now = () => now;
    const observed = await f.observe(); let dispatches = 0;
    if (cleanup) f.base.cleanupCharge = () => { now += 90001; };
    else f.base.charge = () => { now += 60001; };
    await assert.rejects(observed[cleanup ? 'cleanup' : 'native'](async () => { dispatches++; }), cleanup ? /QUAL_CLEANUP_DEADLINE/ : /QUAL_DEADLINE/);
    assert.equal(dispatches, 0);
  }
});

test('unobserved synthetic stale or incomplete normal API subject receipts cannot reach any SDK or production dispatch', async t => {
  for (const patch of [actor => { actor.observed = false; }, actor => { actor.contractOnly = true; },
    actor => { actor.backendSourceSha = 'f'.repeat(40); }, actor => { actor.mfaApiEnrollmentVerified = false; },
    actor => { actor.entitlementModified = true; }, actor => { actor.directDatabaseWrites = true; },
    actor => { actor.acknowledgements.pop(); }, actor => { actor.acknowledgements[1].status = 409; },
    actor => { actor.acknowledgements[1].route = '/api/auth/login'; }, actor => { actor.subject.companyId = '55555555-5555-4555-8555-555555555555'; }]) {
    const f = fixture(t), actor = JSON.parse(fs.readFileSync(f.q.normalApiEvidence.path)); patch(actor);
    f.q.normalApiEvidence = f.save('invalid-normal-api.json', actor);
    await assert.rejects(f.observe()); assert.equal(f.commands.length, 0); assert.equal(f.intentCommands().length, 0);
  }
});
