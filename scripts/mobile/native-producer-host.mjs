import assert from 'node:assert/strict';
import https from 'node:https';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { openSync, closeSync, writeSync, fsyncSync, lstatSync, realpathSync } from 'node:fs';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { readV1Member } from '../../apps/mobile/e2e/v1-workflows-credentials.mjs';
import { totp } from '../../apps/mobile/e2e/mfa.mjs';

export const producerHash = bytes => createHash('sha256').update(bytes).digest('hex');
export function producerTimeout(remaining,maximum=10000) { assert.ok(Number.isFinite(remaining)&&remaining>=1,'PRODUCER_DEADLINE_EXPIRED');return Math.floor(Math.min(remaining,maximum)); }
export function readProducerReference(ref, maxBytes = 1048576) {
  assert.ok(ref && path.isAbsolute(ref.path) && path.normalize(ref.path) === ref.path, 'PRODUCER_REFERENCE_REQUIRED');
  return JSON.parse(verifiedFile(ref.path, ref.sha256, maxBytes));
}
export function readProducerActor(ref) {
  assert.deepEqual(Object.keys(ref).sort(), ['path', 'sha256', 'uid']);
  const held = readV1Member(ref.path);
  try {
    assert.equal(held.sha256, ref.sha256, 'PRODUCER_PRIVATE_DIGEST_CHANGED');
    assert.equal(held.uid, ref.uid, 'PRODUCER_PRIVATE_OWNER_CHANGED');
    return held.value;
  } finally { held.bytes.fill(0); }
}
export function createProducerStore(root) {
  assert.ok(path.isAbsolute(root) && realpathSync(root) === root, 'PRODUCER_CANONICAL_OUTPUT_REQUIRED');
  const initial = lstatSync(root, { bigint: true });
  assert.ok(initial.isDirectory() && !initial.isSymbolicLink() && initial.uid === BigInt(process.getuid()) && (initial.mode & 0o077n) === 0n, 'PRODUCER_PRIVATE_OUTPUT_REQUIRED');
  const check = () => { const now = lstatSync(root, { bigint: true }); assert.ok(realpathSync(root) === root && ['dev','ino','uid','mode'].every(k => initial[k] === now[k]), 'PRODUCER_OUTPUT_CHANGED'); };
  const write = (name, value) => {
    check(); assert.match(name, /^[a-zA-Z0-9][a-zA-Z0-9.-]{0,180}$/);
    const file = path.join(root, name), bytes = Buffer.from(JSON.stringify(value, null, 2) + '\n');
    assert.ok(bytes.length <= 1048576, 'PRODUCER_OUTPUT_BOUND');
    const fd = openSync(file, 'wx', 0o600);
    try { check(); let offset = 0; while (offset < bytes.length) { const n = writeSync(fd, bytes, offset); assert.ok(n > 0); offset += n; } fsyncSync(fd); check(); }
    finally { closeSync(fd); }
    const ref = { path: file, sha256: producerHash(bytes) }; verifiedFile(file, ref.sha256); return ref;
  };
  let sequence = 0;
  return { write, claim: key => write('claim-' + producerHash(Buffer.from(key)) + '.json', { key, noReplay: true }),
    persist: event => write('event-' + String(++sequence).padStart(5,'0') + '.json', event) };
}
function origin(value) {
  const url = new URL(value);
  assert.ok(url.origin === value && url.protocol === 'https:' && ['127.0.0.1','localhost','[::1]'].includes(url.hostname)
    && !url.username && !url.password && !url.search && !url.hash, 'PRODUCER_LOCAL_TLS_REQUIRED');
  return url;
}
/** Ordinary Bearer tokens come only from this host's real normal login/bootstrap
 * responses. releaseSha is admission provenance, not an invented HTTP header. */
export function createProducerHttp({ apiOrigin, webOrigin, sourceSha, publicCa, deadlineMs, persist, now = Date.now }) {
  const api = origin(apiOrigin), web = origin(webOrigin), ca = verifiedFile(publicCa.path, publicCa.sha256, 65536);
  assert.match(sourceSha, /^[a-f0-9]{40}$/); assert.ok(Number.isFinite(deadlineMs) && deadlineMs > now() && deadlineMs - now() <= 510000);
  assert.equal(typeof persist, 'function');
  const tokens = new Map(), identities = new Map(); let sequence = 0, poisoned = false;
  const request = async ({ actor = 'owner', method, route, body, query, headers = {}, timeoutMs = 10000, maxResponseBytes = 1048576, signal,
    web: useWeb = false, automaticRetry = false, accessTokenFromNormalBootstrap, deadlineMs:callDeadlineMs=deadlineMs }) => {
    assert.equal(poisoned, false, 'PRODUCER_TRANSPORT_OUTCOME_UNCERTAIN');
    assert.equal(automaticRetry, false, 'PRODUCER_RETRY_REFUSED');
    assert.ok(['GET','POST','PATCH','DELETE'].includes(method) && typeof actor === 'string' && /^[a-z][a-z-]{0,40}$/.test(actor));
    assert.ok(typeof route === 'string' && route.startsWith('/api/') && !route.startsWith('//') && !/[#\\\r\n]/.test(route));
    const base = useWeb ? web : api, url = new URL(route, base);
    assert.equal(url.origin, base.origin, 'PRODUCER_ROUTE_ORIGIN_CHANGED');
    if(useWeb)assert.ok(method==='GET'&&route==='/api/release-identity'&&body===undefined&&query===undefined,'PRODUCER_PUBLIC_WEB_IDENTITY_ONLY');
    if (query !== undefined) { assert.ok(query && typeof query === 'object'); for (const [k,v] of Object.entries(query)) { assert.ok(['string','number','boolean'].includes(typeof v)); url.searchParams.set(k,String(v)); } }
    assert.ok(Number.isSafeInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 10000);
    assert.ok(Number.isSafeInteger(maxResponseBytes) && maxResponseBytes > 0 && maxResponseBytes <= 1048576);
    assert.ok(!signal?.aborted, 'PRODUCER_HTTP_DEADLINE');
    for (const [key,value] of Object.entries(headers)) { assert.ok(!/^(authorization|cookie|host|content-length|connection)$/i.test(key)); if (/^x-caseops-automated-test$/i.test(key)) assert.equal(value,'no-paid-providers'); }
    if (accessTokenFromNormalBootstrap !== undefined) assert.equal(accessTokenFromNormalBootstrap, tokens.get(actor), 'PRODUCER_TOKEN_NOT_FROM_NORMAL_RESPONSE');
    const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body)); assert.ok(!payload || payload.length <= 1048576);
    const safeHeaders = { ...headers, 'X-CaseOps-Automated-Test':'no-paid-providers', ...(!useWeb&&tokens.has(actor) ? { Authorization:'Bearer '+tokens.get(actor) } : {}),
      ...(payload ? { 'Content-Type':'application/json', 'Content-Length':String(payload.length) } : {}) };
    const id = ++sequence; persist({ type:'producer_http_started', sequence:id, actor, method, route:url.pathname, automaticRetry:false, mutationUncertain:method !== 'GET' });
    try {
      const remaining=producerTimeout(Math.min(timeoutMs,deadlineMs-now(),callDeadlineMs-now()));
      const result = await new Promise((resolve,reject) => {
        let settled = false, timer;
        const fail = () => { if (!settled) { settled = true; clearTimeout(timer); reject(new Error('PRODUCER_HTTP_INCOMPLETE_NO_REPLAY')); } };
        const req = https.request(url, { method, headers:safeHeaders, ca, rejectUnauthorized:true, agent:false, signal }, res => {
          const chunks = []; let size = 0;
          res.on('data', chunk => { size += chunk.length; if (size > maxResponseBytes) { res.destroy(); req.destroy(); fail(); } else chunks.push(chunk); });
          res.on('aborted', fail); res.on('error', fail);
          res.on('end', () => { if (settled) return; try {
            assert.ok(res.statusCode < 300 || res.statusCode >= 400, 'PRODUCER_REDIRECT_REFUSED');
            const bytes = Buffer.concat(chunks), value = bytes.length ? JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)) : null;
            const observedId = res.headers['x-request-id'];assert.ok((typeof observedId==='string'&&observedId.length>0&&observedId.length<=160)||(useWeb&&observedId===undefined),'PRODUCER_REQUEST_ID_REQUIRED');const requestId=observedId??null;
            settled = true; clearTimeout(timer); resolve({status:res.statusCode,value,requestId,releaseSha:sourceSha});
          } catch { req.destroy(); fail(); } });
        });
        timer = setTimeout(() => { req.destroy(); fail(); }, remaining); req.on('error',fail); req.end(payload);
      });
      if (method === 'POST' && ['/api/auth/login','/api/bootstrap/company'].includes(url.pathname) && result.status === 200) {
        assert.ok(typeof result.value.access_token === 'string' && result.value.access_token.length > 0, 'PRODUCER_NORMAL_TOKEN_REQUIRED');
        tokens.set(actor,result.value.access_token);
        identities.set(actor, structuredClone({user:result.value.user,membership:result.value.membership,company:result.value.company,capabilities:result.value.capabilities}));
      }
      persist({type:'producer_http_ack',sequence:id,status:result.status,requestId:result.requestId,releaseShaProvenance:'public-before-after-admission'});
      return result;
    } catch { poisoned = true; throw new Error('PRODUCER_HTTP_INCOMPLETE_NO_REPLAY'); }
  };
  const login = async (actor, ref, { charge, remaining, includeIdentity = true } = {}) => {
    producerTimeout(remaining());
    const credentials = readProducerActor(ref);
    const call = async (key,method,route,body) => { const budget=remaining();const timeoutMs=producerTimeout(budget);charge({key,method,route}); const response = await request({actor,method,route,body,timeoutMs,deadlineMs:now()+budget}); assert.equal(response.status,200,'PRODUCER_NORMAL_LOGIN_FAILED'); return response.value; };
    try {
      const session = await call('actor-login','POST','/api/auth/login',{email:credentials.email,password:credentials.password,company_slug:credentials.company_slug});
      assert.match(credentials.totp_secret || '', /^[A-Z2-7]{16,128}$/);
      const mfa = await call('actor-mfa','POST','/api/auth/mfa/step-up',{code:totp(credentials.totp_secret,now()),purpose:'step_up'}); assert.equal(mfa.status,'verified');
      return includeIdentity ? await call('actor-identity','GET','/api/auth/me') : {user:session.user,membership:session.membership,company:session.company,capabilities:session.capabilities};
    } finally { for (const key of Object.keys(credentials)) credentials[key] = undefined; }
  };
  return {request,login,getActorIdentity: actor => structuredClone(identities.get(actor)),clear() {tokens.clear();identities.clear();ca.fill(0);poisoned=true;} };
}
