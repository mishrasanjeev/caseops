import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { generateKeyPairSync } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
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

test('installed Expo dependency uses the official node-forge 1.4.1 release', () => {
  const version = require('node-forge/package.json').version;
  assert.equal(version, '1.4.1');
});
test('every locked and installed node-forge identity is the reviewed release', () => {
  const lock = JSON.parse(readFileSync(path.join(app, 'package-lock.json'), 'utf8'));
  const copies = Object.entries(lock.packages).filter(([name]) => name.endsWith('/node-forge'));
  assert.equal(copies.length > 0, true);
  for (const [name, record] of copies) {
    assert.equal(record.version, '1.4.1');
    assert.equal(record.resolved, 'https://registry.npmjs.org/node-forge/-/node-forge-1.4.1.tgz');
    assert.equal(record.integrity, 'sha512-w5/MfWaeMrpR/5ba6fZyAUTLSuE6aYz7H/3cYrqwZEmf5eQS3IaaLgJt4MBv7HglGFWmV22K8h4U18RJQmw/ow==');
    const installed = JSON.parse(readFileSync(path.join(app, name, 'package.json'), 'utf8'));
    assert.equal(installed.name, 'node-forge');
    assert.equal(installed.version, record.version);
    assert.equal(installed.license, '(BSD-3-Clause OR GPL-2.0)');
  }
});
test('retained build-tool notice includes the exact installed upstream licence', () => {
  const licence = readFileSync(require.resolve('node-forge/LICENSE'), 'utf8');
  const notice = readFileSync(path.join(app, 'BUILD_TOOL_NOTICES.txt'), 'utf8');
  assert.equal(notice.includes('node-forge 1.4.1'), true);
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
