// Creates only a fresh disposable production test workspace through normal APIs.
// Private tokens, password and TOTP secret never enter the public receipt.
import assert from 'node:assert/strict';
import path from 'node:path';
import https from 'node:https';
import tls from 'node:tls';
import { isIP } from 'node:net';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { jsonInput, privateDirectory, writePrivate, objectKeys, digest } from './store-packaging-inputs.mjs';
import { totp } from '../../apps/mobile/e2e/mfa.mjs';
const ROOT = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
function publicOrigin(origin) {
  const value = new URL(origin);
  assert.ok(value.protocol === 'https:' && value.origin === origin && !value.port && !value.username && !value.password
    && !isIP(value.hostname.replace(/^\[|\]$/g, '')) && value.hostname.includes('.')
    && !/(?:^|\.)(?:localhost|local|internal|test|invalid|example)$/.test(value.hostname), 'HTTPS_SUBJECT_PUBLIC_ORIGIN_REQUIRED');
}
export function normalQualificationApi({ origin, method, route, token, body, deadline }) {
  publicOrigin(origin); assert.ok(['GET', 'POST'].includes(method));
  assert.ok(/^\/api\/[A-Za-z0-9_./-]+$/.test(route) && !route.includes('..'));
  const remaining = Math.min(15000, deadline - Date.now()); assert.ok(remaining > 0, 'HTTPS_SUBJECT_DEADLINE');
  const bytes = body === undefined ? null : Buffer.from(JSON.stringify(body));
  assert.ok(!bytes || bytes.length <= 65536);
  return new Promise((resolve, reject) => {
    const headers = { 'X-CaseOps-Automated-Test': 'no-paid-providers', Accept: 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}),
      ...(bytes ? { 'Content-Type': 'application/json', 'Content-Length': String(bytes.length) } : {}) };
    const request = https.request(new URL(route, origin), { method, headers, agent: false, ca: tls.rootCertificates, rejectUnauthorized: true }, response => {
      if (response.statusCode !== 200) { response.destroy(); reject(Error('HTTPS_SUBJECT_NORMAL_API_REFUSED')); return; }
      const chunks = []; let size = 0;
      response.on('data', chunk => { size += chunk.length; if (size > 1048576) response.destroy(Error('HTTPS_SUBJECT_HTTP_BYTE_BOUND')); else chunks.push(chunk); });
      response.on('error', reject);
      response.on('end', () => { try { resolve({ status: response.statusCode, value: JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))),
        requestId: typeof response.headers['x-request-id'] === 'string' ? response.headers['x-request-id'] : null }); } catch { reject(Error('HTTPS_SUBJECT_JSON_REQUIRED')); } });
    });
    const timer = setTimeout(() => request.destroy(Error('HTTPS_SUBJECT_HTTP_DEADLINE')), remaining);
    request.on('error', reject); request.on('close', () => clearTimeout(timer));
    if (bytes) request.write(bytes); request.end();
  });
}
export function admitHttpsSubjectOutput(output) {
  assert.ok(path.isAbsolute(output) && path.resolve(output) === output && output !== ROOT && !output.startsWith(ROOT + path.sep), 'HTTPS_SUBJECT_OUTPUT_OUTSIDE_SOURCE_REQUIRED');
}
export async function prepareAndroidHttpsSubject(requestRef, dependencies = {}) {
  const contractOnly = Object.keys(dependencies).length > 0;
  assert.ok(contractOnly || process.env.CASEOPS_HTTPS_SUBJECT_CREATE_GO === 'EXPLICIT_FRESH_DISPOSABLE_NORMAL_API_SUBJECT', 'HTTPS_SUBJECT_MUTATION_NOT_ARMED');
  const io = { api: normalQualificationApi, now: Date.now, random: randomBytes, ...dependencies };
  const deadline = io.now() + 180000;
  const q = jsonInput(requestRef, { deadline }).value;
  objectKeys(q, ['schemaVersion', 'kind', 'api', 'workEmailDomain', 'output'], 'HTTPS_SUBJECT_REQUEST_REQUIRED');
  assert.equal(q.schemaVersion, 1); assert.equal(q.kind, 'caseops-fresh-https-qualification-subject-request');
  objectKeys(q.api, ['origin', 'sourceSha', 'revision'], 'HTTPS_SUBJECT_SERVING_IDENTITY_REQUIRED'); publicOrigin(q.api.origin);
  assert.match(q.api.sourceSha, /^[a-f0-9]{40}$/); assert.ok(typeof q.api.revision === 'string' && q.api.revision.length > 0 && q.api.revision.length < 200);
  // Restrict generated non-delivery test identities to the owner's domain.
  assert.equal(q.workEmailDomain, 'orchestrum.in', 'HTTPS_SUBJECT_COMPANY_DOMAIN_REQUIRED');
  admitHttpsSubjectOutput(q.output);
  privateDirectory(q.output, { existing: false, deadline });
  const nonce = io.random(12).toString('hex'); assert.match(nonce, /^[a-f0-9]{24}$/);
  const slug = 'test-native-https-' + nonce, label = 'Disposable HTTPS ' + nonce;
  const credentials = { email: 'native-https-' + nonce + '@' + q.workEmailDomain, password: 'Qa!' + io.random(32).toString('base64url') + '9', company_slug: slug };
  const acknowledgements = []; let token, created = false, completed = false, bodyFailed = false;
  const check = () => assert.ok(io.now() < deadline, 'HTTPS_SUBJECT_DEADLINE');
  const call = async (method, route, body) => {
    check(); assert.ok(acknowledgements.length < 12, 'HTTPS_SUBJECT_NORMAL_API_CALL_BOUND');
    const result = await io.api({ origin: q.api.origin, method, route, body, token, deadline }); check();
    assert.equal(result.status, 200, 'HTTPS_SUBJECT_NORMAL_API_ACK_REQUIRED');
    acknowledgements.push({ method, route: route.includes('/matters/') && route !== '/api/matters/' ? '/api/matters/{owned-matter}' : route,
      status: result.status, acknowledgedAt: new Date(io.now()).toISOString(), requestIdSha256: result.requestId ? digest(result.requestId) : null });
    return result.value;
  };
  // Persist the generated credentials BEFORE the only bootstrap request. An
  // unknown transport result is retained and never retried or adopted by slug.
  writePrivate(path.join(q.output, 'private-account.json'), Buffer.from(JSON.stringify(credentials) + '\n'), { deadline });
  try {
    const build = await call('GET', '/api/build');
    assert.equal(build.release_sha, q.api.sourceSha); assert.equal(build.revision, q.api.revision);
    const auth = await call('POST', '/api/bootstrap/company', { company_name: label, company_slug: slug, company_type: 'law_firm', owner_full_name: label,
      owner_email: credentials.email, owner_password: credentials.password });
    created = true; assert.equal(auth.token_type, 'bearer'); assert.ok(typeof auth.access_token === 'string' && auth.access_token.length > 0); token = auth.access_token;
    for (const key of ['company', 'user', 'membership']) { assert.match(auth[key].id, uuid); assert.equal(auth[key].is_active, true); }
    assert.equal(auth.company.slug, slug); assert.equal(auth.company.name, label); assert.equal(auth.user.email, credentials.email); assert.equal(auth.user.full_name, label);
    assert.equal(auth.membership.role, 'owner');
    assert.ok(['matters:create', 'matters:read'].every(capability => auth.capabilities.includes(capability)), 'HTTPS_SUBJECT_REAL_CAPABILITY_REQUIRED');
    const enrollment = await call('POST', '/api/auth/mfa/enroll'); assert.equal(enrollment.status, 'pending'); assert.match(enrollment.secret, /^[A-Z2-7]{16,128}$/);
    // API enrollment verification is not a rendered-QR acceptance claim.
    writePrivate(path.join(q.output, 'private-mfa.json'), Buffer.from(JSON.stringify({ totp_secret: enrollment.secret }) + '\n'), { deadline });
    const verified = await call('POST', '/api/auth/mfa/enroll/verify', { code: totp(enrollment.secret, io.now()) }); assert.equal(verified.status, 'enrolled');
    writePrivate(path.join(q.output, 'private-recovery.json'), Buffer.from(JSON.stringify({ recovery_codes: verified.recovery_codes }) + '\n'), { deadline });
    const security = await call('GET', '/api/auth/security'); assert.equal(security.mfa_status, 'enrolled');
    const me = await call('GET', '/api/auth/me');
    for (const key of ['company', 'user', 'membership']) assert.equal(me[key].id, auth[key].id);
    assert.ok(['matters:create', 'matters:read'].every(capability => me.capabilities.includes(capability)), 'HTTPS_SUBJECT_REAL_CAPABILITY_REQUIRED');
    const code = 'TEST-HTTPS-' + nonce.toUpperCase();
    const matter = await call('POST', '/api/matters/', { title: label, matter_code: code, practice_area: 'General', forum_level: 'advisory', status: 'active' });
    assert.match(matter.id, uuid); assert.equal(matter.company_id, auth.company.id); assert.equal(matter.matter_code, code); assert.equal(matter.is_active, true);
    const readback = await call('GET', '/api/matters/' + matter.id);
    assert.equal(readback.id, matter.id); assert.equal(readback.company_id, auth.company.id); assert.equal(readback.matter_code, code); assert.equal(readback.is_active, true);
    const finalBuild = await call('GET', '/api/build'); assert.deepEqual(finalBuild, build); check();
    const subject = { companyId: auth.company.id, companySlug: slug, userId: auth.user.id, membershipId: auth.membership.id,
      principalLabel: label, workspaceLabel: label, matter: { id: matter.id, code } };
    const result = { schemaVersion: 1, kind: contractOnly ? 'synthetic-normal-api-https-qualification-subject' : 'caseops-normal-api-https-qualification-subject',
      contractOnly, observed: !contractOnly, syntheticDataOnly: true, noPaidMarker: 'no-paid-providers', directDatabaseWrites: false,
      subject, apiOrigin: q.api.origin, backendRevision: q.api.revision, backendSourceSha: q.api.sourceSha, mfaApiEnrollmentVerified: true,
      nativeAuthenticationVerified: false, renderedQrVerified: false, entitlementModified: false, acknowledgements };
    const evidence = writePrivate(path.join(q.output, 'subject-evidence.json'), Buffer.from(JSON.stringify(result) + '\n'), { deadline }); completed = true;
    return { ...result, evidence };
  } catch (error) { bodyFailed = true; throw error; } finally {
    token = undefined; credentials.password = undefined;
    if (!completed) try { writePrivate(path.join(q.output, 'incomplete.json'), Buffer.from(JSON.stringify({ kind: 'incomplete-https-subject-preparation', createdAcknowledged: created,
      unknownMutationsMustNotReplay: true, observed: false, acknowledgements }) + '\n')); } catch (error) { if (!bodyFailed) throw error; }
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    assert.ok(process.argv.length === 5 && process.argv[2] === '--execute', 'HTTPS_SUBJECT_EXACT_ARGUMENTS_REQUIRED');
    const result = await prepareAndroidHttpsSubject({ path: process.argv[3], sha256: process.argv[4] });
    console.log(JSON.stringify({ kind: result.kind, observed: result.observed, nativeAuthenticationVerified: false }));
  } catch { console.error('HTTPS_SUBJECT_PREPARATION_INCOMPLETE_NO_REPLAY'); process.exitCode = 1; }
}
