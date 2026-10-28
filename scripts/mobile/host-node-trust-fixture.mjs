// Local synthetic TLS contract only. No external service, enrollment or key is read.
import https from 'node:https';
import { createHash, generateKeyPairSync } from 'node:crypto';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Worker, isMainThread, parentPort, workerData } from 'node:worker_threads';
import { assertHostNodeTrust, HOST_NODE_TRUST_ENV } from './host-node-trust.mjs';

export function localCertificates() {
  const require = createRequire(new URL('../../apps/mobile/package.json', import.meta.url));
  const forge = require('node-forge');
  if (require('node-forge/package.json').version !== '1.4.1') throw new Error('HOST_TLS_FIXTURE_FORGE_VERSION');
  function material(name, issuer = null, wrongHost = false) {
    const generated = generateKeyPairSync('rsa', { modulusLength: 2048 });
    const key = forge.pki.privateKeyFromPem(generated.privateKey.export({ type: 'pkcs1', format: 'pem' }));
    const certificate = forge.pki.createCertificate();
    certificate.publicKey = forge.pki.publicKeyFromPem(generated.publicKey.export({ type: 'pkcs1', format: 'pem' }));
    certificate.serialNumber = createHash('sha256').update(name).digest('hex').slice(0, 20);
    // Other colocated UI contracts mock Date.now; TLS uses the real clock.
    const now = new Date().getTime();
    certificate.validity.notBefore = new Date(now - 60000);
    certificate.validity.notAfter = new Date(now + 86400000);
    certificate.setSubject([{ name: 'commonName', value: 'CaseOps local-only ' + name }]);
    certificate.setIssuer(issuer ? issuer.certificate.subject.attributes : certificate.subject.attributes);
    certificate.setExtensions([{ name: 'basicConstraints', cA: !issuer }, { name: 'keyUsage', keyCertSign: !issuer, digitalSignature: true, keyEncipherment: true }, { name: 'subjectAltName', altNames: wrongHost ? [{ type: 2, value: 'wrong.invalid' }] : [{ type: 7, ip: '127.0.0.1' }] }]);
    certificate.sign(issuer?.key ?? key, forge.md.sha256.create());
    return { certificate, key, cert: forge.pki.certificateToPem(certificate), privateKey: forge.pki.privateKeyToPem(key) };
  }
  const trusted = material('trusted');
  return { trusted, untrusted: material('untrusted'), wrongHost: material('wrong-host', trusted, true) };
}

export async function probe(raw, transportOnly = false) {
  const target = new URL(raw);
  if (target.protocol !== 'https:' || target.hostname !== '127.0.0.1' || !target.port || target.username || target.password || target.pathname !== '/' || raw.includes('?') || raw.includes('#')) throw new Error('HOST_TLS_FIXTURE_LOOPBACK_ONLY');
  const policyRef = { path: process.env[HOST_NODE_TRUST_ENV.file], sha256: process.env[HOST_NODE_TRUST_ENV.sha256] };
  const report = transportOnly ? { contractOnly: true, selectedSyntheticStoreTransport: true } : assertHostNodeTrust({ policyRef, role: process.env.CASEOPS_TEST_FIXTURE_CA ? 'native-qa' : 'base', expectedFixtureCA: process.env.CASEOPS_TEST_FIXTURE_CA ? JSON.parse(process.env.CASEOPS_TEST_FIXTURE_CA) : null });
  const output = [], signal = AbortSignal.timeout(5000), headers = { 'X-CaseOps-Automated-Test': 'no-paid-providers' };
  const body = async response => { let result = '', count = 0; for await (const chunk of response) { count += Buffer.byteLength(chunk); if (count > 4096) throw new Error('HOST_TLS_FIXTURE_BODY_BOUND'); result += Buffer.from(chunk).toString('utf8'); } return result; };
  try { const response = await fetch(target, { signal, headers }); output.push(await body(response.body)); }
  catch (error) { output.push(error.cause?.code ?? error.code ?? 'HOST_TLS_FIXTURE_FAILURE'); }
  try { output.push(await new Promise((resolve, reject) => {
    const request = https.get(target, { signal, timeout: 5000, headers }, response => { body(response).then(resolve, reject); });
    request.once('timeout', () => request.destroy(new Error('HOST_TLS_FIXTURE_DEADLINE'))); request.once('error', reject);
  })); } catch (error) { output.push(error.code ?? 'HOST_TLS_FIXTURE_FAILURE'); }
  return { ...report, output };
}
async function descendants(target) {
  const direct = await probe(target);
  const worker = new Worker(new URL(import.meta.url), { workerData: { target } });
  const exited = once(worker, 'exit');
  const timer = setTimeout(() => { void worker.terminate(); }, 8000);
  let workerReport;
  try { const received = await once(worker, 'message'); workerReport = received[0]; const [exit] = await exited; if (exit !== 0) throw new Error('HOST_TLS_FIXTURE_WORKER_EXIT'); }
  finally { clearTimeout(timer); }
  const child = spawn(process.execPath, [fileURLToPath(import.meta.url), 'probe', target], { env: process.env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  let stdout = '', stderr = ''; const bound = stream => data => { if (stdout.length + stderr.length + data.length > 16384) child.kill(); else if (stream === 'stdout') stdout += data; else stderr += data; };
  child.stdout.on('data', bound('stdout')); child.stderr.on('data', bound('stderr'));
  const childTimer = setTimeout(() => child.kill(), 8000);
  try { const [exit, signal] = await once(child, 'close'); if (exit !== 0 || signal || stderr) throw new Error('HOST_TLS_FIXTURE_CHILD_REFUSED'); return { direct, worker: workerReport, subprocess: JSON.parse(stdout) }; }
  finally { clearTimeout(childTimer); }
}
async function nextWorker(target) {
  const require = createRequire(new URL('../../package.json', import.meta.url));
  if (require('next/package.json').version !== '16.4.2') throw new Error('HOST_TLS_FIXTURE_NEXT_VERSION');
  const { Worker: NextWorker } = require('next/dist/lib/worker');
  const worker = new NextWorker(fileURLToPath(new URL('./host-node-trust-next-worker.cjs', import.meta.url)), {
    numWorkers: 1, enableSourceMaps: true, isolatedMemory: true, exposedMethods: ['probe'],
    enableWorkerThreads: false,
  });
  let timer;
  try {
    return await Promise.race([worker.probe(target), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('HOST_TLS_FIXTURE_NEXT_DEADLINE')), 8000);
    })]);
  } finally { clearTimeout(timer); await worker.end(); }
}
if (!isMainThread) {
  try { parentPort.postMessage(await probe(workerData.target)); }
  catch { parentPort.postMessage({ refused: true }); process.exitCode = 1; }
} else if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href && process.env.CASEOPS_HOST_NODE_BOOTSTRAP_TEST === '1') {
  const { default: test } = await import('node:test');
  test('forwarded-approved-bootstrap', () => {
    const report = assertHostNodeTrust({ policyRef: { path: process.env[HOST_NODE_TRUST_ENV.file], sha256: process.env[HOST_NODE_TRUST_ENV.sha256] } });
    if (!report.defaultEnumerationVerified || report.expectedDefaultCount !== 144) throw new Error('ROOTS_NOT_ACTIVATED');
  });
} else if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const mode = process.argv[2];
    if (!['probe', 'descendants', 'transport-only', 'next-worker'].includes(mode)) throw new Error('HOST_TLS_FIXTURE_MODE');
    console.log(JSON.stringify(mode === 'next-worker' ? await nextWorker(process.argv[3]) : mode === 'descendants' ? await descendants(process.argv[3]) : await probe(process.argv[3], mode === 'transport-only')));
  } catch (error) { console.error(/^HOST_[A-Z_]+$/.test(error.message) ? error.message : 'HOST_TLS_FIXTURE_REFUSED'); process.exitCode = 1; }
}
