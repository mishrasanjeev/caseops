// Native qualification only. JSON declarations never mint a dispatch lease.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import https from 'node:https';
import tls from 'node:tls';
import { isIP } from 'node:net';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { readInput, jsonInput, writePrivate, privateDirectory, digest, objectKeys } from './store-packaging-inputs.mjs';
import { inspectStoreZip } from './store-artifact-postflight.mjs';
import { home, read, click } from '../../apps/mobile/e2e/native-ui.mjs';
import { sdkXmlTree, sdkValue } from './android-sdk-xml.mjs';

const require = createRequire(import.meta.url);
const { validateNativeLinkConfig } = require('../../apps/web/lib/native-link-policy.cjs');
const leases = new WeakMap();
const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
const ID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
function freeze(value) {
  if (value && typeof value === 'object') { for (const item of Object.values(value)) freeze(item); Object.freeze(value); }
  return value;
}
export const HTTPS_QUALIFICATION_CASE = 'CX28-LINK-05';

export function qualificationUrl(value, origin, subject) {
  const url = new URL(value);
  assert.equal(url.origin, origin, 'QUAL_LINK_ORIGIN');
  assert.equal(url.protocol, 'https:', 'QUAL_HTTPS_REQUIRED');
  assert.ok(!url.username && !url.password && !url.port && !url.search && !url.hash, 'QUAL_CANONICAL_URL_REQUIRED');
  assert.equal(url.pathname, `/native/open/workspaces/${subject.companyId}/matters/${subject.matter.id}`, 'QUAL_EXACT_SUBJECT_LINK');
  assert.equal(url.href, value, 'QUAL_CANONICAL_URL_REQUIRED');
  return url;
}

export function validateQualificationDeclaration(q, { source, udid, config, configSha256 }) {
  objectKeys(q, ['schemaVersion', 'kind', 'platform', 'caseId', 'source', 'udid', 'apk', 'qualificationBuild', 'nativeLinks',
    'certificateSha256', 'origin', 'url', 'subject', 'normalApiEvidence', 'api', 'web', 'tools', 'output'], 'QUAL_DECLARATION_REQUIRED');
  assert.equal(q.schemaVersion, 1); assert.equal(q.kind, 'caseops-android-https-qualification');
  assert.equal(q.platform, 'android'); assert.equal(q.caseId, HTTPS_QUALIFICATION_CASE);
  assert.deepEqual(q.source, source, 'QUAL_CURRENT_SOURCE_REQUIRED');
  assert.equal(q.source.sourceDirty, false); assert.equal(q.udid, udid, 'QUAL_OWNED_DEVICE_REQUIRED');
  assert.equal(config.syntheticDataOnly, false); assert.equal(q.nativeLinks.sha256, configSha256);
  assert.equal(q.origin, new URL(config.redirectUri).origin, 'QUAL_PUBLIC_LINK_POLICY_REQUIRED');
  assert.match(q.certificateSha256, SHA);
  assert.ok(config.android.signingCertificateSha256.includes(q.certificateSha256), 'QUAL_DECLARED_SIGNER_NOT_ASSOCIATED');
  assert.ok(path.isAbsolute(q.apk.path) && q.apk.path.endsWith('.apk')); assert.match(q.apk.sha256, SHA);
  objectKeys(q.subject, ['companyId', 'companySlug', 'userId', 'membershipId', 'principalLabel', 'workspaceLabel', 'matter'], 'QUAL_DISPOSABLE_SUBJECT_REQUIRED');
  for (const key of ['companyId', 'userId', 'membershipId']) assert.match(q.subject[key], ID);
  assert.match(q.subject.companySlug, /^test-native-https-[a-f0-9]{12,32}$/);
  assert.match(q.subject.matter.id, ID);
  for (const value of [q.subject.principalLabel, q.subject.workspaceLabel, q.subject.matter.code])
    assert.ok(typeof value === 'string' && value.length > 0 && value.length <= 200 && !/[\x00-\x1f\x7f]/.test(value));
  qualificationUrl(q.url, q.origin, q.subject);
  for (const value of [q.api, q.web]) {
    objectKeys(value, ['origin', 'sourceSha', 'revision'], 'QUAL_SERVING_IDENTITY_REQUIRED');
    const url = new URL(value.origin);
    assert.ok(url.protocol === 'https:' && url.origin === value.origin && !url.port && !url.username && !url.password, 'QUAL_REAL_HTTPS_SERVING_REQUIRED');
    assert.ok(!isIP(url.hostname.replace(/^\[|\]$/g, '')) && url.hostname.includes('.') && !/(?:^|\.)(?:localhost|local|internal|test|invalid)$/.test(url.hostname), 'QUAL_PUBLIC_SERVING_REQUIRED');
    assert.match(value.sourceSha, /^[a-f0-9]{40}$/); assert.ok(typeof value.revision === 'string' && value.revision.length > 0 && value.revision.length <= 200);
  }
  assert.equal(q.web.origin, q.origin);
  return config.android.packageName;
}

export function verifyQualificationApkFacts({ badging, signature, attestation }, q, appId, expected) {
  assert.ok(badging.startsWith(`package: name='${appId}' `), 'QUAL_ACTUAL_PACKAGE_REQUIRED');
  assert.match(badging.split('\n')[0], new RegExp(" versionCode='" + expected.androidVersionCode + "'(?: |$)"), 'QUAL_ACTUAL_VERSION_CODE_REQUIRED');
  assert.ok(badging.split('\n')[0].includes(" versionName='" + expected.version + "'"), 'QUAL_ACTUAL_VERSION_NAME_REQUIRED');
  assert.deepEqual(attestation.storeBuild, expected.storeBuild, 'QUAL_ACTUAL_STORE_BUILD_REQUIRED');
  const signers = [...signature.matchAll(/^(?:Signer #\d+|V2 Signer:|V3\.0 Signer:) certificate SHA-256 digest: ([a-f0-9]{64})$/gm)].map(m => m[1]);
  assert.equal(signature.split(/\r?\n/).filter(line => line.includes('certificate SHA-256 digest:')).length, signers.length, 'QUAL_UNRECOGNIZED_SIGNER_FORMAT');
  assert.ok(signers.length > 0 && signers.every(value => value === q.certificateSha256), 'QUAL_ACTUAL_SIGNER_REQUIRED');
  assert.match(signature, /^Verifies$/m);
  assert.equal(attestation.kind, 'caseops-store-artifact-source');
  assert.equal(attestation.qualificationOnly, true, 'QUAL_NON_SUBMITTABLE_ARTIFACT_REQUIRED');
  assert.equal(attestation.nativeAcceptanceClaimed, false);
  assert.equal(attestation.submissionAuthorization, 'separate-artifact-bound-promotion-required');
  assert.deepEqual(attestation.source, { sourceSha: q.source.sourceSha, sourceFingerprint: q.source.sourceFingerprint, inputFileCount: q.source.inputFileCount });
  assert.equal(attestation.nativeLinks.sha256, q.nativeLinks.sha256);
  assert.equal(attestation.apiOrigin, q.api.origin); assert.equal(attestation.webOrigin, q.web.origin);
}

export function verifyQualificationManifest(dump, origin) {
  const tree = sdkXmlTree(dump), ns = 'http://schemas.android.com/apk/res/android:';
  const attr = (node, key) => node.attrs.get(ns + key) ?? node.attrs.get('android:' + key);
  const value = (node, key) => sdkValue(attr(node, key));
  const boolean = (node, key, fallback) => {
    const actual = attr(node, key); if (!actual) return fallback;
    if (/^\(type 0x12\)0x(?:ffffffff|1)$/.test(actual.raw)) return true;
    if (/^\(type 0x12\)0x0$/.test(actual.raw)) return false;
    return sdkValue(actual);
  };
  assert.equal(tree.name, 'manifest');
  const apps = tree.children.filter(node => node.name === 'application'); assert.equal(apps.length, 1);
  const app = apps[0];
  assert.equal(boolean(app, 'debuggable', false), false, 'QUAL_NONDEBUGGABLE_REQUIRED');
  assert.equal(boolean(app, 'usesCleartextTraffic', false), false, 'QUAL_STRICT_TRANSPORT_REQUIRED');
  assert.equal(boolean(app, 'allowBackup', true), false, 'QUAL_NO_BACKUP_REQUIRED');
  assert.equal(attr(app, 'networkSecurityConfig'), undefined, 'QUAL_NO_QA_NETWORK_POLICY');
  const host = new URL(origin).hostname;
  const filters = app.children.filter(node => ['activity', 'activity-alias'].includes(node.name))
    .flatMap(activity => activity.children.filter(node => node.name === 'intent-filter')
      .filter(filter => boolean(filter, 'autoVerify', false) === true)
      .map(filter => ({ activity, filter })));
  const matches = filters.filter(({ activity, filter }) => {
    if (!boolean(activity, 'exported', false)) return false;
    const names = kind => filter.children.filter(node => node.name === kind).map(node => value(node, 'name'));
    if (!names('action').includes('android.intent.action.VIEW') || !['android.intent.category.BROWSABLE', 'android.intent.category.DEFAULT'].every(name => names('category').includes(name))) return false;
    const data = filter.children.filter(node => node.name === 'data');
    return data.length > 0 && data.every(node => value(node, 'scheme') === 'https' && value(node, 'host') === host)
      && data.some(node => attr(node, 'pathPrefix') && value(node, 'pathPrefix') === '/native/open/');
  });
  assert.equal(matches.length, 1, 'QUAL_COMPILED_AUTOVERIFY_FILTER_REQUIRED');
}

export function verifyQualificationAssociation({ dal, verified, resolver }, q, appId) {
  assert.ok(Array.isArray(dal) && dal.length > 0 && dal.length <= 16, 'QUAL_DAL_REQUIRED');
  const matches = dal.filter(row => row.target?.namespace === 'android_app' && row.target.package_name === appId
    && row.relation?.includes('delegate_permission/common.handle_all_urls')
    && row.target.sha256_cert_fingerprints?.some(value => value.replaceAll(':', '').toLowerCase() === q.certificateSha256));
  assert.equal(matches.length, 1, 'QUAL_EXACT_DAL_SIGNER_REQUIRED');
  const host = new URL(q.origin).hostname;
  assert.ok(verified.split(/\r?\n/).some(line => line.trim() === host + ': verified'), 'QUAL_OS_VERIFIED_HOST_REQUIRED');
  const components = resolver.trim().split(/\r?\n/).filter(line => /^[A-Za-z0-9_.]+\/[A-Za-z0-9_.$]+$/.test(line));
  assert.equal(components.length, 1, 'QUAL_UNAMBIGUOUS_DEFAULT_RESOLVER_REQUIRED');
  assert.ok(components[0].startsWith(appId + '/'), 'QUAL_UNFORCED_RESOLVER_REQUIRED');
  return components[0];
}

export function qualificationHttpsJson(url, deadline) {
  const target = new URL(url);
  assert.ok(target.protocol === 'https:' && !target.username && !target.password && !target.search && !target.hash);
  const remaining = Math.min(15000, deadline - Date.now()); assert.ok(remaining > 0, 'QUAL_DEADLINE');
  return new Promise((resolve, reject) => {
    const request = https.get(target, { rejectUnauthorized: true, ca: tls.rootCertificates, agent: false,
      headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' } }, response => {
      let size = 0; const chunks = [];
      if (response.statusCode !== 200) { response.destroy(); reject(Error('QUAL_HTTPS_STATUS_REQUIRED')); return; }
      response.on('data', chunk => { size += chunk.length; if (size > 16384) { response.destroy(Error('QUAL_HTTPS_BYTE_BOUND')); return; } chunks.push(chunk); });
      response.on('error', reject);
      response.on('end', () => { try { resolve(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)))); } catch { reject(Error('QUAL_HTTPS_JSON_REQUIRED')); } });
    });
    const timer = setTimeout(() => request.destroy(Error('QUAL_HTTPS_DEADLINE')), remaining);
    request.on('error', reject); request.on('close', () => clearTimeout(timer));
  });
}

// This factory is invoked by the admitted runner, never by a request's fields.
// Test dependencies are code-only and cannot be supplied by a JSON declaration.
export async function observeAndroidHttpsQualification(q, base, dependencies = {}) {
  q = freeze(structuredClone(q));
  const contractOnly = Object.keys(dependencies).length > 0;
  const io = { read: readInput, json: jsonInput, command: execFileSync, https: qualificationHttpsJson, now: Date.now, ...dependencies };
  assert.equal(base.platform, 'android'); assert.equal(base.caseId, HTTPS_QUALIFICATION_CASE);
  assert.ok(Number.isInteger(base.adbPort) && base.adbPort >= 1024 && base.adbPort <= 65535, 'QUAL_OWNED_ADB_TRANSPORT_REQUIRED');
  const deadline = Math.min(base.deadline, io.now() + 60000);
  const check = (needed = 0) => { assert.ok(io.now() + needed < deadline, 'QUAL_DEADLINE'); base.checkBudget?.(needed); };
  const cleanupDeadline = Math.min(base.cleanupDeadline ?? base.deadline, io.now() + 90000);
  const boundedNative = async (operation, cleanup = false) => {
    const end = cleanup ? cleanupDeadline : deadline;
    const remaining = () => Math.min(10000, end - io.now());
    assert.ok(remaining() > 0, cleanup ? 'QUAL_CLEANUP_DEADLINE' : 'QUAL_DEADLINE');
    if (cleanup) base.cleanupCharge?.(); else { check(); base.charge?.(); }
    let timer;
    try {
      const value = await Promise.race([Promise.resolve().then(() => {
        assert.ok(io.now() < end, cleanup ? 'QUAL_CLEANUP_DEADLINE' : 'QUAL_DEADLINE');
        if (!cleanup) check();
        return operation();
      }), new Promise((_, reject) => { timer = setTimeout(() => reject(Error(cleanup ? 'QUAL_CLEANUP_ACK_UNKNOWN' : 'QUAL_NATIVE_ACK_UNKNOWN')), remaining()); })]);
      assert.ok(io.now() < end, cleanup ? 'QUAL_CLEANUP_DEADLINE' : 'QUAL_DEADLINE');
      if (!cleanup) check();
      return value;
    } finally { clearTimeout(timer); }
  };
  assert.equal(q.nativeLinks.path, path.join(ROOT, 'apps/web/native-links/production.json'), 'QUAL_COMMITTED_LINK_CONFIG_REQUIRED');
  const links = io.json(q.nativeLinks, { deadline });
  const config = validateNativeLinkConfig(links.value);
  const appId = validateQualificationDeclaration(q, { source: base.source, udid: base.udid, config, configSha256: q.nativeLinks.sha256 });
  const actor = io.json(q.normalApiEvidence, { deadline }).value;
  assert.equal(actor.kind, 'caseops-normal-api-https-qualification-subject');
  assert.equal(actor.observed, true); assert.equal(actor.contractOnly, false); assert.equal(actor.mfaApiEnrollmentVerified, true);
  assert.equal(actor.entitlementModified, false); assert.equal(actor.backendSourceSha, q.api.sourceSha);
  assert.ok(Array.isArray(actor.acknowledgements) && actor.acknowledgements.length === 9 && actor.acknowledgements.every(row => row.status === 200), 'QUAL_NORMAL_API_ACKNOWLEDGEMENTS_REQUIRED');
  assert.deepEqual(actor.acknowledgements.map(row => row.method + ' ' + row.route), ['GET /api/build', 'POST /api/bootstrap/company', 'POST /api/auth/mfa/enroll', 'POST /api/auth/mfa/enroll/verify', 'GET /api/auth/security', 'GET /api/auth/me', 'POST /api/matters/', 'GET /api/matters/{owned-matter}', 'GET /api/build']);
  assert.equal(actor.noPaidMarker, 'no-paid-providers'); assert.equal(actor.directDatabaseWrites, false);
  assert.equal(actor.syntheticDataOnly, true); assert.deepEqual(actor.subject, q.subject);
  assert.equal(actor.apiOrigin, q.api.origin); assert.equal(actor.backendRevision, q.api.revision);
  const candidate = io.json(q.qualificationBuild, { deadline }).value;
  assert.equal(candidate.kind, 'caseops-android-qualification-result');
  for (const key of ['observed', 'qualificationOnly', 'distributionSigningVerified']) assert.equal(candidate[key], true, 'QUAL_ACTUAL_CANDIDATE_REQUIRED');
  for (const key of ['contractOnly', 'submissionAllowed', 'storeAcceptance', 'uploaded']) assert.equal(candidate[key], false, 'QUAL_NON_SUBMITTABLE_CANDIDATE_REQUIRED');
  assert.equal(candidate.cleanup.complete, true); assert.equal(candidate.sourceSha, q.source.sourceSha);
  assert.deepEqual(candidate.qualificationApk.artifact, q.apk, 'QUAL_EXACT_DERIVED_APK_REQUIRED');
  assert.equal(candidate.qualificationApk.kind, 'caseops-android-qualification-apk');
  assert.deepEqual(candidate.qualificationApk.aab, candidate.artifact, 'QUAL_EXACT_DERIVED_AAB_REQUIRED');
  assert.equal(candidate.qualificationApk.submissionAllowed, false); assert.equal(candidate.qualificationApk.installedAcceptance, false);
  assert.equal(candidate.postflight.artifactSha256, candidate.artifact.sha256);
  assert.equal(candidate.postflight.distributionSigningVerified, true);
  assert.deepEqual(candidate.phases.map(row => [row.name, row.status]), ['reservation', 'signing-admission', 'build', 'artifact-postflight', 'source-postflight'].map(name => [name, 'passed']));
  const recipe = io.json(candidate.recipe, { deadline }).value;
  const settings = io.json(recipe.storeBuild, { deadline }).value;
  assert.equal(recipe.kind, 'caseops-store-packaging-request'); assert.equal(recipe.platform, 'android');
  assert.deepEqual(recipe.source, { sourceSha: q.source.sourceSha, sourceFingerprint: q.source.sourceFingerprint, inputFileCount: q.source.inputFileCount });
  assert.deepEqual(recipe.nativeLinks, q.nativeLinks); assert.equal(recipe.apiOrigin, q.api.origin); assert.equal(recipe.webOrigin, q.web.origin);
  assert.equal(recipe.signing.uploadCertificateSha256, q.certificateSha256, 'QUAL_ACTUAL_UPLOAD_SIGNER_REQUIRED');
  assert.ok(Number.isSafeInteger(settings.androidVersionCode) && settings.androidVersionCode > 0);
  assert.match(settings.version, /^\d+\.\d+\.\d+$/);
  const expected = { version: settings.version, androidVersionCode: settings.androidVersionCode, storeBuild: recipe.storeBuild };
  objectKeys(q.tools, ['adb', 'apksigner', 'aapt2', 'java', 'runtimeInputs'], 'QUAL_PINNED_TOOLS_REQUIRED');
  assert.equal(base.acceptedTools.observed, true); assert.equal(base.acceptedTools.platform, 'android');
  for (const role of ['adb', 'apksigner', 'aapt2', 'java']) {
    const accepted = base.acceptedTools.executables.filter(row => row.role === role);
    assert.equal(accepted.length, 1, 'QUAL_ACCEPTED_SDK_TOOL_REQUIRED');
    assert.equal(q.tools[role].path, accepted[0].file.path, 'QUAL_ACCEPTED_SDK_TOOL_REQUIRED');
    assert.equal(q.tools[role].sha256, accepted[0].file.sha256, 'QUAL_ACCEPTED_SDK_TOOL_REQUIRED');
    assert.equal(q.tools[role].sizeBytes, accepted[0].file.extent, 'QUAL_ACCEPTED_SDK_TOOL_REQUIRED');
  }
  assert.ok(Array.isArray(q.tools.runtimeInputs) && q.tools.runtimeInputs.length > 0 && q.tools.runtimeInputs.length <= 256);
  assert.deepEqual(q.tools.runtimeInputs, base.acceptedTools.httpsRuntimeInputs, 'QUAL_ACCEPTED_SDK_CLOSURE_REQUIRED');
  const toolRefs = [q.tools.adb, q.tools.apksigner, q.tools.aapt2, q.tools.java, ...q.tools.runtimeInputs];
  let declaredBytes = 0;
  for (const tool of toolRefs) { assert.ok(Number.isSafeInteger(tool.sizeBytes) && tool.sizeBytes > 0); declaredBytes += tool.sizeBytes; }
  assert.ok(declaredBytes <= 256 * 1024 * 1024, 'QUAL_TOOL_CLOSURE_BYTE_BOUND');
  const verifyTools = () => { for (const tool of toolRefs) { const actual = io.read(tool.path, { sha256: tool.sha256, maxBytes: tool.sizeBytes, systemTool: true, deadline });
    try { assert.equal(actual.bytes.length, tool.sizeBytes); } finally { actual.bytes.fill(0); } } };
  verifyTools();
  assert.equal(path.dirname(q.output), base.outputRoot, 'QUAL_OWNED_REPORT_OUTPUT_REQUIRED');
  assert.equal(path.basename(q.output), 'https-qualification');
  assert.ok(path.isAbsolute(q.output) && path.resolve(q.output) === q.output && !q.output.startsWith(ROOT), 'QUAL_OUTPUT_OUTSIDE_SOURCE_REQUIRED');
  privateDirectory(q.output, { existing: false, deadline });
  const apk = io.read(q.apk.path, { sha256: q.apk.sha256, maxBytes: 128 * 1024 * 1024, deadline });
  let copy;
  try { copy = writePrivate(path.join(q.output, 'verified-input.apk'), apk.bytes, { deadline }); }
  finally { apk.bytes.fill(0); }
  const environment = { PATH: path.dirname(q.tools.java.path) + ':/usr/bin:/bin', JAVA_HOME: path.dirname(path.dirname(q.tools.java.path)),
    ADB_SERVER_SOCKET: `tcp:127.0.0.1:${base.adbPort}`, ANDROID_ADB_SERVER_PORT: String(base.adbPort) };
  const command = (tool, args, mutation = false) => {
    check(); verifyTools(); base.charge?.(); check();
    const result = io.command(q.tools[tool].path, args, { env: environment, encoding: 'utf8', maxBuffer: 1048576, timeout: Math.min(10000, deadline - io.now()) });
    check(); verifyTools();
    base.record?.({ type: 'https_qualification_transport', tool, argvSha256: digest(JSON.stringify(args)), mutation, outputSha256: digest(result) });
    return result;
  };
  const adb = args => command('adb', ['-P', String(base.adbPort), '-s', q.udid, ...args]);
  let installedObservations = 0;
  const verifyInstalled = () => {
    io.read(q.apk.path, { sha256: q.apk.sha256, maxBytes: 128 * 1024 * 1024, deadline }).bytes.fill(0);
    const installed = adb(['shell', 'pm', 'path', appId]).trim();
    assert.match(installed, /^package:\/data\/app\/[A-Za-z0-9_./+=~-]+\/base\.apk$/, 'QUAL_ONE_INSTALLED_APK_REQUIRED');
    const installedPath = path.join(q.output, `installed-${++installedObservations}.apk`);
    assert.equal(fs.existsSync(installedPath), false, 'QUAL_FRESH_DEVICE_COPY_REQUIRED');
    adb(['pull', installed.slice(8), installedPath]);
    io.read(installedPath, { sha256: q.apk.sha256, maxBytes: 128 * 1024 * 1024, deadline }).bytes.fill(0);
  };
  verifyInstalled();
  const badging = command('aapt2', ['dump', 'badging', copy.path]);
  const manifest = command('aapt2', ['dump', 'xmltree', '--file', 'AndroidManifest.xml', copy.path]);
  verifyQualificationManifest(manifest, q.origin);
  const signature = command('apksigner', ['verify', '--verbose', '--print-certs', copy.path]);
  const retained = io.read(copy.path, { sha256: q.apk.sha256, maxBytes: 128 * 1024 * 1024, deadline }); let attestation;
  try { inspectStoreZip(retained.bytes, (row, bytes) => { check(); if (row.name === 'assets/caseops-store-attestation.json') attestation = JSON.parse(bytes.toString('utf8')); }); }
  finally { retained.bytes.fill(0); }
  assert.ok(attestation, 'QUAL_EMBEDDED_SOURCE_REQUIRED');
  verifyQualificationApkFacts({ badging, signature, attestation }, q, appId, expected);
  const [dal, api, web] = await Promise.all([io.https(q.origin + '/.well-known/assetlinks.json', deadline),
    io.https(q.api.origin + '/api/build', deadline), io.https(q.web.origin + '/api/release-identity', deadline)]);
  for (const [actual, expected] of [[api, q.api], [web, q.web]]) {
    assert.equal(actual.release_sha, expected.sourceSha, 'QUAL_ACTUAL_SERVING_SOURCE_REQUIRED');
    assert.equal(actual.revision, expected.revision, 'QUAL_ACTUAL_SERVING_REVISION_REQUIRED');
  }
  const verified = adb(['shell', 'pm', 'get-app-links', appId]);
  const resolverArgs = ['shell', 'cmd', 'package', 'resolve-activity', '--brief', '-a', 'android.intent.action.VIEW', '-c', 'android.intent.category.BROWSABLE', '-d', q.url];
  const resolver = adb(resolverArgs);
  const component = verifyQualificationAssociation({ dal, verified, resolver }, q, appId); check();
  let opens = 0;
  return Object.freeze({ q, appId, component, deadline, contractOnly, check,
    native: operation => boundedNative(operation), cleanup: operation => boundedNative(operation, true),
    charge() { check(); base.charge?.(); },
    open(url) {
      qualificationUrl(url, q.origin, q.subject); check(); assert.ok(opens < 2, 'QUAL_EXACT_COLD_WARM_DISPATCH_ONLY');
      verifyInstalled();
      // Reobserve current OS verification/resolution before each single intent.
      verifyQualificationAssociation({ dal, verified: adb(['shell', 'pm', 'get-app-links', appId]), resolver: adb(resolverArgs) }, q, appId);
      opens++;
      const started = command('adb', ['-P', String(base.adbPort), '-s', q.udid, 'shell', 'am', 'start', '-W', '-a', 'android.intent.action.VIEW', '-c', 'android.intent.category.BROWSABLE', '-d', url], true);
      assert.match(started, /^Status: ok$/m, 'QUAL_INTENT_ACK_REQUIRED');
      assert.ok(started.split(/\r?\n/).some(line => line.trim().startsWith('Activity: ' + appId + '/')), 'QUAL_ACTUAL_INTENT_TARGET_REQUIRED');
    },
    async finish() {
      check(); assert.equal(opens, 2, 'QUAL_BOTH_OPENS_REQUIRED'); verifyInstalled();
      const [currentDal, currentApi, currentWeb] = await Promise.all([io.https(q.origin + '/.well-known/assetlinks.json', deadline),
        io.https(q.api.origin + '/api/build', deadline), io.https(q.web.origin + '/api/release-identity', deadline)]);
      for (const [actual, expected] of [[currentApi, q.api], [currentWeb, q.web]]) {
        assert.equal(actual.release_sha, expected.sourceSha, 'QUAL_ACTUAL_SERVING_SOURCE_REQUIRED');
        assert.equal(actual.revision, expected.revision, 'QUAL_ACTUAL_SERVING_REVISION_REQUIRED');
      }
      const currentComponent = verifyQualificationAssociation({ dal: currentDal,
        verified: adb(['shell', 'pm', 'get-app-links', appId]), resolver: adb(resolverArgs) }, q, appId);
      assert.equal(currentComponent, component, 'QUAL_RESOLVER_CHANGED'); check();
      io.read(q.nativeLinks.path, { sha256: q.nativeLinks.sha256, maxBytes: 16384, deadline }).bytes.fill(0);
      io.read(q.qualificationBuild.path, { sha256: q.qualificationBuild.sha256, maxBytes: 1048576, deadline }).bytes.fill(0);
      io.read(candidate.recipe.path, { sha256: candidate.recipe.sha256, maxBytes: 1048576, deadline }).bytes.fill(0);
      io.read(recipe.storeBuild.path, { sha256: recipe.storeBuild.sha256, maxBytes: 65536, deadline }).bytes.fill(0);
      verifyTools();
      const result = { schemaVersion: 1, kind: contractOnly ? 'synthetic-android-https-qualification' : 'actual-android-https-qualification', contractOnly, caseId: HTTPS_QUALIFICATION_CASE,
        source: q.source, udid: q.udid, appId, binaryHash: q.apk.sha256, certificateSha256: q.certificateSha256,
        origin: q.origin, nativeLinks: q.nativeLinks, urlSha256: digest(q.url), component, api: q.api, web: q.web,
        normalApiEvidence: q.normalApiEvidence, qualificationBuild: q.qualificationBuild, storeBuild: recipe.storeBuild, productionAccessed: true, sourceAndInstalledArtifactRechecked: true,
        actualOsVerifiedHost: true, unforcedResolver: true, unforcedColdWarmDispatchCount: opens,
        observed: !contractOnly, submissionAllowed: false, nativeCaseCredit: 0 };
      return writePrivate(path.join(q.output, 'qualification-observation.json'), Buffer.from(JSON.stringify(result) + '\n'), { deadline });
    },
  });
}

export async function withAndroidHttpsQualification(context, observer, action) {
  assert.equal(context.platform, 'android'); assert.equal(context.caseId, HTTPS_QUALIFICATION_CASE);
  assert.equal(typeof observer, 'function', 'QUAL_RUNNER_OBSERVER_REQUIRED');
  const observed = await observer();
  const oldFixture = context.fixture, oldBinary = context.binaryHash;
  const oldCheckBudget = context.checkBudget;
  let bodyError, bodyFailed = false;
  const cleanupErrors = [];
  try {
    await observed.native(() => context.driver.activateApp(observed.appId));
    context.fixture = { udid: oldFixture.udid, appId: observed.appId,
      companyId: observed.q.subject.companyId, userId: observed.q.subject.userId, membershipId: observed.q.subject.membershipId,
      principalLabel: observed.q.subject.principalLabel, workspaceLabel: observed.q.subject.workspaceLabel,
      cx: { links: { https: observed.q.url, matter: observed.q.subject.matter,
        verifiedAssociation: { observed: true, binaryHash: observed.q.apk.sha256, udid: observed.q.udid, mode: 'production', origin: observed.q.origin } } } };
    context.binaryHash = observed.q.apk.sha256;
    // Retain the runner's original operation budget and add the lease deadline
    // to every nested helper. Revoke it before independent finite cleanup.
    context.checkBudget = needed => { observed.check(needed ?? 0); oldCheckBudget?.(needed ?? 0); };
    observed.check(); await home(context, 'today'); observed.check();
    await click(context, 'id', 'account-open', { scroll: false }); observed.check();
    const principal = await read(context, 'id', 'account-principal'); observed.check();
    assert.equal(principal, observed.q.subject.principalLabel, 'QUAL_NATIVE_PRINCIPAL_REQUIRED');
    const workspace = await read(context, 'id', 'account-workspace'); observed.check();
    assert.equal(workspace, observed.q.subject.workspaceLabel, 'QUAL_NATIVE_WORKSPACE_REQUIRED');
    leases.set(context, { observed, opens: 0 });
    await action(context); observed.check();
    const evidence = await observed.finish(); observed.check();
    context.record({ type: 'https_qualification_completed', caseId: HTTPS_QUALIFICATION_CASE,
      contractOnly: observed.contractOnly, sessionId: context.driver.sessionId, udid: observed.q.udid,
      source: observed.q.source, binaryHash: observed.q.apk.sha256, qualificationEvidence: evidence,
      physicalAssociationProven: context.workflowDomain === 'physical' });
  } catch (error) { bodyFailed = true; bodyError = error; }
  finally {
    leases.delete(context); context.checkBudget = oldCheckBudget;
    // Each command is charged and gets the remaining original 90-second
    // cleanup reserve (at most 10 seconds per acknowledgement). Never replay.
    try { await observed.cleanup(() => context.driver.terminateApp(observed.appId)); }
    catch (error) { cleanupErrors.push(error); }
    context.fixture = oldFixture; context.binaryHash = oldBinary;
    try { await observed.cleanup(() => context.driver.activateApp(oldFixture.appId)); }
    catch (error) { cleanupErrors.push(error); }
    try { assert.equal(await observed.cleanup(() => context.driver.getCurrentPackage()), oldFixture.appId, 'QUAL_QA_CONTEXT_RESTORE_UNVERIFIED'); }
    catch (error) { cleanupErrors.push(error); }
    // Do not mutate original errors: they may be frozen, primitives or falsy.
    // Reporting is secondary and cannot replace either original failure.
    if (cleanupErrors.length) try { context.record({ type: 'https_qualification_cleanup_failed', failedCommands: cleanupErrors.length, bodyFailed }); } catch { /* original failures below */ }
  }
  if (bodyFailed) throw bodyError;
  if (cleanupErrors.length) throw cleanupErrors[0];
}

function qualificationLease(context) {
  const lease = leases.get(context);
  assert.ok(lease && context.caseId === HTTPS_QUALIFICATION_CASE && context.binaryHash === lease.observed.q.apk.sha256
    && context.fixture.appId === lease.observed.appId, 'CX_ACTUAL_VERIFIED_HTTPS_ARTIFACT_REQUIRED');
  return lease;
}
export async function terminateQualifiedApp(context) {
  const { observed } = qualificationLease(context);
  await observed.native(() => context.driver.terminateApp(observed.appId));
}
export async function assertQualifiedColdState(context) {
  const { observed } = qualificationLease(context);
  assert.equal(await observed.native(() => context.driver.queryAppState(observed.appId)), 1, 'QUAL_ACTUAL_COLD_STATE_REQUIRED');
}
export async function dispatchQualifiedHttpsLink(context, url) {
  const lease = qualificationLease(context), observed = lease.observed;
  if (lease.opens === 1) {
    assert.equal(await observed.native(() => context.driver.queryAppState(observed.appId)), 4, 'QUAL_ACTUAL_WARM_STATE_REQUIRED');
    assert.equal(await observed.native(() => context.driver.getCurrentPackage()), observed.appId, 'QUAL_ACTUAL_WARM_FOREGROUND_REQUIRED');
  }
  observed.check(); lease.opens++; // Lost acknowledgement cannot replay.
  observed.open(url);
  await context.driver.waitUntil(async () => {
    const current = await observed.native(() => context.driver.getCurrentPackage());
    const state = await observed.native(() => context.driver.queryAppState(observed.appId));
    return current === observed.appId && state === 4;
  }, { timeout: 20000, interval: 200, timeoutMsg: 'QUAL_ACTUAL_FOREGROUND_APP_REQUIRED' });
  observed.check();
}
