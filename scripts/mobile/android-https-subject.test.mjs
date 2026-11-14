import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import https from 'node:https';
import tls from 'node:tls';
import { EventEmitter } from 'node:events';
import { createHash } from 'node:crypto';
import { prepareAndroidHttpsSubject, normalQualificationApi, admitHttpsSubjectOutput } from './android-https-subject.mjs';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
function fixture(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-subject-unit-'))); fs.chmodSync(root, 0o700); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const q = { schemaVersion: 1, kind: 'caseops-fresh-https-qualification-subject-request', api: { origin: 'https://api.caseops.ai', sourceSha: 'a'.repeat(40), revision: 'synthetic-api' }, workEmailDomain: 'orchestrum.in', output: path.join(root, 'subject') };
  const bytes = Buffer.from(JSON.stringify(q)); const request = path.join(root, 'request.json'); fs.writeFileSync(request, bytes, { mode: 0o600 });
  const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333', '44444444-4444-4444-8444-444444444444'];
  let auth, matter; const calls = [], state = { loseBootstrap: false, deniedCapabilities: false, late: false }, now = Date.now();
  const dependencies = { now: () => now + (state.late ? 180001 : 0), random: size => Buffer.alloc(size, 1),
    async api(options) {
      calls.push(options); let value;
      if (options.route === '/api/build') value = { release_sha: q.api.sourceSha, revision: q.api.revision };
      else if (options.route === '/api/bootstrap/company') { if (state.loseBootstrap) throw Error('SYNTHETIC_UNKNOWN_BOOTSTRAP');
        const p = options.body; auth = { access_token: 'SYNTHETIC_PRIVATE_TOKEN', token_type: 'bearer', company: { id: ids[0], is_active: true, slug: p.company_slug, name: p.company_name },
          user: { id: ids[1], is_active: true, email: p.owner_email, full_name: p.owner_full_name }, membership: { id: ids[2], is_active: true, role: 'owner' }, capabilities: state.deniedCapabilities ? [] : ['matters:create', 'matters:read'] }; value = auth; }
      else if (options.route === '/api/auth/mfa/enroll') value = { status: 'pending', secret: 'JBSWY3DPEHPK3PXP' };
      else if (options.route === '/api/auth/mfa/enroll/verify') { assert.match(options.body.code, /^\d{6}$/); value = { status: 'enrolled', recovery_codes: ['SYNTHETIC_PRIVATE_RECOVERY'] }; }
      else if (options.route === '/api/auth/security') value = { mfa_status: 'enrolled' };
      else if (options.route === '/api/auth/me') value = auth;
      else if (options.route === '/api/matters/') { matter = { id: ids[3], company_id: ids[0], matter_code: options.body.matter_code, is_active: true }; value = matter; }
      else if (options.route === '/api/matters/' + ids[3]) value = matter;
      else throw Error('UNDECLARED_NORMAL_API_ROUTE');
      return { status: 200, value, requestId: 'synthetic-request-' + calls.length };
    } };
  return { q, ref: { path: request, sha256: sha(bytes) }, state, calls, dependencies };
}
test('normal subject producer acknowledges fresh bootstrap, real capabilities, MFA and exact created matter before publication', async t => {
  const f = fixture(t), result = await prepareAndroidHttpsSubject(f.ref, f.dependencies);
  assert.deepEqual(f.calls.map(row => row.method + " " + row.route.replace(/\/api\/matters\/[a-f0-9-]{36}$/, "/api/matters/{owned}")), ["GET /api/build", "POST /api/bootstrap/company", "POST /api/auth/mfa/enroll", "POST /api/auth/mfa/enroll/verify", "GET /api/auth/security", "GET /api/auth/me", "POST /api/matters/", "GET /api/matters/{owned}", "GET /api/build"]); assert.equal(f.calls.filter(row => row.route === '/api/bootstrap/company').length, 1);
  assert.equal(result.contractOnly, true); assert.equal(result.observed, false); assert.equal(result.nativeAuthenticationVerified, false);
  assert.equal(result.mfaApiEnrollmentVerified, true); assert.equal(result.directDatabaseWrites, false); assert.equal(result.entitlementModified, false);
  const text = fs.readFileSync(result.evidence.path, 'utf8'); for (const secret of ['SYNTHETIC_PRIVATE_TOKEN', 'SYNTHETIC_PRIVATE_RECOVERY', 'JBSWY3DPEHPK3PXP', 'owner_password']) assert.equal(text.includes(secret), false);
  assert.equal(fs.statSync(path.join(f.q.output, 'private-account.json')).mode & 0o777, 0o600);
});
test('unknown bootstrap acknowledgement is retained without retry or guessed adoption', async t => {
  const f = fixture(t); f.state.loseBootstrap = true;
  await assert.rejects(prepareAndroidHttpsSubject(f.ref, f.dependencies), /SYNTHETIC_UNKNOWN_BOOTSTRAP/);
  assert.equal(f.calls.length, 2); assert.equal(f.calls.filter(row => row.route === '/api/bootstrap/company').length, 1);
  assert.equal(fs.existsSync(path.join(f.q.output, 'subject-evidence.json')), false); assert.equal(fs.existsSync(path.join(f.q.output, 'private-account.json')), true);
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.q.output, 'incomplete.json'))).unknownMutationsMustNotReplay, true);
});
test('missing real capability cannot be repaired by synthetic entitlements or reach matter mutation', async t => {
  const f = fixture(t); f.state.deniedCapabilities = true;
  await assert.rejects(prepareAndroidHttpsSubject(f.ref, f.dependencies), /HTTPS_SUBJECT_REAL_CAPABILITY_REQUIRED/);
  assert.equal(f.calls.some(row => row.route === '/api/matters/'), false); assert.equal(fs.existsSync(path.join(f.q.output, 'subject-evidence.json')), false);
});
test('a late successful bootstrap cannot start MFA or publish a subject', async t => {
  const f = fixture(t), original = f.dependencies.api;
  f.dependencies.api = async options => { const result = await original(options); if (options.route === '/api/bootstrap/company') f.state.late = true; return result; };
  await assert.rejects(prepareAndroidHttpsSubject(f.ref, f.dependencies), /HTTPS_SUBJECT_DEADLINE/);
  assert.equal(f.calls.length, 2); assert.equal(fs.existsSync(path.join(f.q.output, 'subject-evidence.json')), false);
});
test('actual normal API HTTP constructor preserves strict public TLS, no-paid marker, route/body and finite response', async () => {
  const original = https.request, calls = [];
  try {
    https.request = (url, options, callback) => { const request = new EventEmitter(); calls.push({ url, options }); request.write = body => { calls.at(-1).body = body.toString(); };
      request.destroy = error => { request.emit('error', error); request.emit('close'); };
      request.end = () => process.nextTick(() => { const response = new EventEmitter(); response.statusCode = 200; response.headers = { 'x-request-id': 'synthetic-id' }; response.destroy = () => {};
        callback(response); response.emit('data', Buffer.from('{"safe":true}')); response.emit('end'); request.emit('close'); }); return request; };
    const result = await normalQualificationApi({ origin: 'https://api.caseops.ai', method: 'POST', route: '/api/auth/mfa/enroll/verify', token: 'SYNTHETIC_TOKEN', body: { code: '123456' }, deadline: Date.now() + 1000 });
    assert.equal(result.status, 200); assert.equal(calls[0].options.rejectUnauthorized, true); assert.equal(calls[0].options.ca, tls.rootCertificates); assert.equal(calls[0].options.agent, false);
    assert.equal(calls[0].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers'); assert.equal(calls[0].body, '{"code":"123456"}');
    assert.throws(() => normalQualificationApi({ origin: 'https://localhost', method: 'GET', route: '/api/build', deadline: Date.now() + 1000 }));
  } finally { https.request = original; }
});

test('failed normal API POST constructors retain marker, TLS, auth and exact payload without retry', async () => {
  const original = https.request;
  try {
    for (const mode of ['status', 'unknown-post', 'oversize', 'malformed', 'timeout']) {
      const calls = [];
      https.request = (url, options, callback) => {
        const request = new EventEmitter(), row = { url, options }; calls.push(row);
        request.write = bytes => { row.body = bytes.toString(); };
        request.destroy = error => { request.emit('error', error); request.emit('close'); };
        request.end = () => { if (mode !== 'timeout') process.nextTick(() => {
          if (mode === 'unknown-post') { request.emit('error', Error('SYNTHETIC_POST_ACK_UNKNOWN')); request.emit('close'); return; }
          const response = new EventEmitter(); response.statusCode = mode === 'status' ? 403 : 200; response.headers = {};
          response.destroy = error => { if (error) response.emit('error', error); request.emit('close'); };
          callback(response);
          if (mode !== 'status') { response.emit('data', mode === 'oversize' ? Buffer.alloc(1048577) : Buffer.from([0xff])); if (mode !== 'oversize') response.emit('end'); request.emit('close'); }
        }); }; return request;
      };
      await assert.rejects(normalQualificationApi({ origin: 'https://api.caseops.ai', method: 'POST', route: '/api/auth/mfa/enroll/verify',
        token: 'SYNTHETIC_TOKEN', body: { code: '123456' }, deadline: Date.now() + (mode === 'timeout' ? 20 : 1000) }));
      assert.equal(calls.length, 1); assert.equal(calls[0].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
      assert.equal(calls[0].options.rejectUnauthorized, true); assert.equal(calls[0].options.ca, tls.rootCertificates); assert.equal(calls[0].options.agent, false);
      assert.equal(calls[0].options.headers.Authorization, 'Bearer SYNTHETIC_TOKEN'); assert.equal(calls[0].body, '{"code":"123456"}');
      assert.equal(calls[0].url.pathname, '/api/auth/mfa/enroll/verify');
    }
  } finally { https.request = original; }
});

test('subject output rejects normalized source root, children and alternate spellings before private creation', () => {
  const root = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
  for (const output of [root, root + '/', path.join(root, 'private-subject'), root + '/folder/../private-subject', root + '/../' + path.basename(root) + '/private-subject']) assert.throws(() => admitHttpsSubjectOutput(output), /HTTPS_SUBJECT_OUTPUT_OUTSIDE_SOURCE_REQUIRED/);
});
