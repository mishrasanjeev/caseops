import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { generateKeyPairSync } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Worker } from 'node:worker_threads';
import test from 'node:test';

const require = createRequire(new URL('../../apps/mobile/package.json', import.meta.url));
const forge = require('node-forge');
const app = fileURLToPath(new URL('../../apps/mobile/', import.meta.url));
// Ephemeral public test key; no private key material is written or retained.
const generated = generateKeyPairSync('rsa', { modulusLength: 2048, publicExponent: 3 });
const privateKey = forge.pki.privateKeyFromPem(generated.privateKey.export({ type: 'pkcs1', format: 'pem' }));
const publicKey = forge.pki.publicKeyFromPem(generated.publicKey.export({ type: 'pkcs1', format: 'pem' }));
const messageDigest = forge.md.sha256.create().update('CaseOps public dependency regression fixture');
const digest = messageDigest.digest().getBytes();
const { asn1 } = forge;
const oid = () => asn1.create(asn1.Class.UNIVERSAL, asn1.Type.OID, false, asn1.oidToDer(forge.pki.oids.sha256).getBytes());
const nullValue = (value = '') => asn1.create(asn1.Class.UNIVERSAL, asn1.Type.NULL, false, value);
const info = algorithm => asn1.toDer(asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, [
  asn1.create(asn1.Class.UNIVERSAL, asn1.Type.SEQUENCE, true, algorithm),
  asn1.create(asn1.Class.UNIVERSAL, asn1.Type.OCTETSTRING, false, digest),
])).getBytes();
function accepted(der) {
  const signature = privateKey.sign(der, 'NONE');
  try { return publicKey.verify(digest, signature) === true; }
  catch { return false; }
}

test('installed Expo dependency uses the official node-forge 1.4.3 release', () => {
  const version = require('node-forge/package.json').version;
  assert.equal(version, '1.4.3');
});
test('every locked and installed node-forge identity is the reviewed release', () => {
  const lock = JSON.parse(readFileSync(path.join(app, 'package-lock.json'), 'utf8'));
  const copies = Object.entries(lock.packages).filter(([name]) => name.endsWith('/node-forge'));
  assert.equal(copies.length > 0, true);
  for (const [name, record] of copies) {
    assert.equal(record.version, '1.4.3');
    assert.equal(record.resolved, 'https://registry.npmjs.org/node-forge/-/node-forge-1.4.3.tgz');
    assert.equal(record.integrity, 'sha512-P6wzfh6t70avmV8FrVEAd/36sOPJQ+hkaJVX1Laap9J/77m7M0eyozDvc8SwnDf4P7MP94gwbAAo0rg3YVXT+g==');
    const installed = JSON.parse(readFileSync(path.join(app, name, 'package.json'), 'utf8'));
    assert.equal(installed.name, 'node-forge');
    assert.equal(installed.version, record.version);
    assert.equal(installed.license, '(BSD-3-Clause OR GPL-2.0)');
  }
});
test('retained build-tool notice includes the exact installed upstream licence', () => {
  const licence = readFileSync(require.resolve('node-forge/LICENSE'), 'utf8');
  const notice = readFileSync(path.join(app, 'BUILD_TOOL_NOTICES.txt'), 'utf8');
  assert.equal(notice.includes('node-forge 1.4.3'), true);
  assert.equal(notice.includes(licence), true);
});
test('Git checkout preserves the exact stored build-tool notice bytes', () => {
  const repo = path.resolve(app, '../..');
  const file = 'apps/mobile/BUILD_TOOL_NOTICES.txt';
  const attributes = execFileSync('git', ['check-attr', 'eol', '--', file], { cwd: repo, encoding: 'utf8', timeout: 5000 });
  assert.equal(attributes.trim(), `${file}: eol: lf`);
  const stored = execFileSync('git', ['rev-parse', `:${file}`], { cwd: repo, encoding: 'utf8', timeout: 5000 }).trim();
  const actual = execFileSync('git', ['hash-object', '--no-filters', '--', file], { cwd: repo, encoding: 'utf8', timeout: 5000 }).trim();
  assert.equal(actual, stored);
});
test('canonical SHA-256 DigestInfo signatures with NULL parameters still verify', () => {
  const result = accepted(info([oid(), nullValue()]));
  assert.equal(result, true);
});
test('canonical SHA-256 DigestInfo signatures without parameters still verify', () => {
  const result = accepted(info([oid()]));
  assert.equal(result, true);
});
test('nested DigestAlgorithm garbage is rejected by the installed RSA parser', () => {
  const extra = asn1.create(asn1.Class.UNIVERSAL, asn1.Type.OCTETSTRING, false, 'public regression padding');
  const result = accepted(info([oid(), nullValue(), extra]));
  assert.equal(result, false);
});
test('nonempty NULL DigestAlgorithm parameters are rejected by the installed RSA parser', () => {
  const result = accepted(info([oid(), nullValue('\x00\x00')]));
  assert.equal(result, false);
});
test('nonminimal DigestInfo DER length is rejected by the installed RSA parser', () => {
  const canonical = info([oid(), nullValue()]);
  assert.equal(canonical.charCodeAt(1) < 128, true);
  const nonminimal = canonical[0] + '\x81' + canonical.slice(1);
  const result = accepted(nonminimal);
  assert.equal(result, false);
});

test('Forge rejects an Ed25519 identity-key forgery and still accepts a real signature', () => {
  const message = Buffer.from('CaseOps dependency signature regression');
  const identity = Buffer.alloc(32); identity[0] = 1;
  assert.equal(forge.pki.ed25519.verify({ message, publicKey: identity,
    signature: Buffer.concat([identity, Buffer.alloc(32)]) }), false);
  const keys = forge.pki.ed25519.generateKeyPair();
  const signature = forge.pki.ed25519.sign({ message, privateKey: keys.privateKey });
  assert.equal(forge.pki.ed25519.verify({ message, publicKey: keys.publicKey, signature }), true);
});

function tlsClient() {
  const errors = [];
  const connection = forge.tls.createConnection({ server: false, caStore: [],
    connected() {}, closed() {}, dataReady() {},
    tlsDataReady(c) { c.tlsData.clear(); }, error(_c, error) { errors.push(error); } });
  return { connection, errors };
}

test('Forge rejects an unoffered TLS compression method through its error callback', () => {
  const { connection, errors } = tlsClient();
  connection.handshake();
  const hello = Buffer.concat([Buffer.from([3, 1]), Buffer.alloc(32), Buffer.from([0, 0, 0x2f, 0xff])]);
  const handshake = Buffer.concat([Buffer.from([2, 0, 0, hello.length]), hello]);
  const record = Buffer.concat([Buffer.from([22, 3, 1, 0, handshake.length]), handshake]);
  assert.doesNotThrow(() => connection.process(record.toString('binary')));
  assert.equal(connection.fail, true);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].alert.description, forge.tls.Alert.Description.illegal_parameter);
});

for (const state of ['before-handshake', 'after-close', 'after-close-notify']) {
  test(`Forge ignores a sessionless TLS handshake ${state}`, () => {
    const { connection } = tlsClient();
    if (state !== 'before-handshake') connection.handshake();
    if (state === 'after-close') connection.close();
    if (state === 'after-close-notify') connection.process(Buffer.from([21, 3, 1, 0, 2, 1, 0]).toString('binary'));
    assert.equal(connection.session, null);
    assert.doesNotThrow(() => connection.process(Buffer.from([22, 3, 1, 0, 4, 2, 0, 0, 0]).toString('binary')));
    assert.equal(connection.session, null);
  });
}

test('Forge HTTP header and cookie trimming stay bounded on hostile whitespace', async () => {
  // Keep startup and parsing inside the original bound without starting another
  // operating-system process. Workers inherit the host trust bootstrap unchanged.
  let worker;
  let timer;
  try {
    await new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error('BOUNDED_FORGE_HEADER_AND_COOKIE_PARSE')), 1500);
      worker = new Worker(`
    const assert = require('node:assert/strict');
    const { workerData } = require('node:worker_threads');
    const forge = require(workerData.http);
    const util = require(workerData.util);
    const value = 'a' + '\\t '.repeat(80000) + 'X';
    const response = forge.createResponse();
    assert.equal(response.readHeader(util.createBuffer('HTTP/1.1 200 OK\\r\\nX-CaseOps: ' + value + '\\r\\nSet-Cookie: fixture=' + value + '\\r\\n\\r\\n')), true);
    assert.equal(response.getField('X-CaseOps'), value);
    assert.equal(response.getCookies()[0].value, value);
      `, { eval: true, workerData: { http: require.resolve('node-forge/lib/http'), util: require.resolve('node-forge/lib/util') } });
      worker.once('error', reject);
      worker.once('exit', code => code === 0 ? resolve() : reject(new Error(`FORGE_PARSER_WORKER_EXIT_${code}`)));
    });
  } finally {
    clearTimeout(timer);
    if (worker) await worker.terminate();
  }
});
