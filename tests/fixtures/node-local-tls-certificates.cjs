'use strict';

// Fixed synthetic loopback certificates for offline runtime tests only.
// No dependency, network, supplied subject, production key or external CA.
// Certificate layout: RFC5280. Signing and parsing use the pinned Node runtime.
const { createHash, generateKeyPairSync, randomBytes, sign, X509Certificate } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

function der(tag, ...parts) {
  const value = Buffer.concat(parts);
  if (value.length >= 65536) throw Error('DER_BOUND');
  const length = value.length < 128 ? [value.length]
    : value.length < 256 ? [0x81, value.length] : [0x82, value.length >> 8, value.length & 255];
  return Buffer.concat([Buffer.from([tag, ...length]), value]);
}
const sequence = (...parts) => der(0x30, ...parts);
const oid = hex => der(0x06, Buffer.from(hex, 'hex'));
const algorithm = sequence(oid('2a8648ce3d040302')); // ecdsa-with-SHA256
const extension = (hex, value, critical = false) => sequence(oid(hex),
  ...(critical ? [der(0x01, Buffer.from([255]))] : []), der(0x04, value));
const name = text => sequence(der(0x31, sequence(oid('550403'), der(0x0c, Buffer.from(text)))));
function date(value) {
  const text = value.toISOString().replace(/[-:T]/g, '').replace(/\.\d{3}Z$/, 'Z');
  return value.getUTCFullYear() < 2050 ? der(0x17, Buffer.from(text.slice(2))) : der(0x18, Buffer.from(text));
}
function pem(label, bytes) {
  return '-----BEGIN ' + label + '-----\n' + bytes.toString('base64').match(/.{1,64}/g).join('\n')
    + '\n-----END ' + label + '-----\n';
}
function material(label, now, issuer) {
  const keys = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  const subject = name('CaseOps local-only ' + label + ' TLS fixture');
  const publicDer = keys.publicKey.export({ type: 'spki', format: 'der' });
  const identifier = createHash('sha256').update(publicDer).digest();
  const serial = randomBytes(16);
  serial[0] = (serial[0] & 127) || 1;
  const ca = !issuer;
  const extensions = [
    extension('551d13', sequence(...(ca ? [der(0x01, Buffer.from([255]))] : [])), true),
    extension('551d0f', der(0x03, Buffer.from(ca ? [1, 0x86] : [7, 0x80])), true),
    extension('551d0e', der(0x04, identifier)),
    extension('551d23', sequence(der(0x80, issuer ? issuer.identifier : identifier))),
    extension('551d11', sequence(issuer ? der(0x82, Buffer.from('wrong.invalid'))
      : der(0x87, Buffer.from([127, 0, 0, 1])))),
    ...(ca ? [] : [extension('551d25', sequence(oid('2b06010505070301')))]),
  ];
  const tbs = sequence(der(0xa0, der(0x02, Buffer.from([2]))), der(0x02, serial), algorithm,
    issuer ? issuer.subject : subject, sequence(date(new Date(now - 60000)), date(new Date(now + 2 * 86400000))),
    subject, publicDer, der(0xa3, sequence(...extensions)));
  const signature = sign('sha256', tbs, issuer ? issuer.keys.privateKey : keys.privateKey);
  const raw = sequence(tbs, algorithm, der(0x03, Buffer.from([0]), signature));
  const parsed = new X509Certificate(raw);
  if (!parsed.verify(issuer ? issuer.keys.publicKey : keys.publicKey)) throw Error('SIGNATURE');
  return { keys, subject, identifier, certificate: pem('CERTIFICATE', raw) };
}

try {
  if (process.versions.node !== '22.23.5' || process.argv.length !== 3) throw Error('RUNTIME_OR_ARGUMENTS');
  const requested = process.argv[2];
  if (!path.isAbsolute(requested) || fs.realpathSync(requested) !== requested) throw Error('ROOT');
  const parent = path.dirname(requested);
  if (path.basename(requested) !== 'tls' || !/^caseops-node-trust-[A-Za-z0-9]+$/.test(path.basename(parent))
      || path.dirname(parent) !== fs.realpathSync(os.tmpdir())) throw Error('SCOPE');
  for (const dir of [requested, parent]) {
    const stat = fs.lstatSync(dir);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw Error('DIRECTORY');
  }
  if (fs.readdirSync(requested).length !== 0) throw Error('NONEMPTY');
  const end = performance.now() + 5000;
  const check = () => { if (performance.now() >= end) throw Error('DEADLINE'); };
  const now = new Date().getTime();
  const trusted = material('trusted', now);
  check();
  const untrusted = material('untrusted', now);
  check();
  const wrongHost = material('wrong-host', now, trusted);
  const rows = [['trusted', trusted], ['untrusted', untrusted], ['wrong-host', wrongHost]];
  for (const [label, value] of rows) {
    check();
    fs.writeFileSync(path.join(requested, label + '.pem'), value.certificate, { flag: 'wx', mode: 0o600 });
    fs.writeFileSync(path.join(requested, label + '.key'),
      value.keys.privateKey.export({ type: 'pkcs8', format: 'pem' }), { flag: 'wx', mode: 0o600 });
  }
  check();
  console.log(JSON.stringify({ version: 1, names: rows.map(([label]) => label), files: 6, algorithm: 'P-256/SHA-256' }));
} catch {
  console.error('CASEOPS_SYNTHETIC_TLS_FIXTURE_REFUSED');
  process.exitCode = 1;
}
