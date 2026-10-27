import { createHash, X509Certificate } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { rootCertificates } from 'node:tls';
import { fileURLToPath } from 'node:url';

const MAX_CA_BYTES = 16384;
const FILE_FIELDS = ['dev', 'ino', 'size', 'mode', 'uid', 'gid', 'nlink', 'mtimeNs', 'ctimeNs'];
const DIRECTORY_FIELDS = ['dev', 'ino', 'mode', 'uid', 'gid'];
const CODES = new Set(['SOURCE_EXPORT_CI_REQUIRED', 'SOURCE_EXPORT_OPT_IN_REQUIRED',
  'SOURCE_EXPORT_TEMP_REQUIRED', 'SOURCE_EXPORT_OUTSIDE_GIT_REQUIRED', 'SOURCE_EXPORT_PUBLIC_ROOTS_REQUIRED',
  'SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED', 'SOURCE_EXPORT_DIRECTORY_CHANGED', 'SOURCE_EXPORT_FILE_CHANGED',
  'SOURCE_EXPORT_PREPARATION_FAILED']);
const fail = code => { throw new Error(code); };
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const same = (left, right, fields, named = false) => fields.every(key =>
  key === 'dev' && named && process.platform === 'win32' || left[key] === right[key]);
const owned = value => typeof process.getuid !== 'function' || value.uid === BigInt(process.getuid());
const directory = value => value.isDirectory() && !value.isSymbolicLink() && owned(value);

function outsideGit(io, temp) {
  for (let current = temp; ; current = path.dirname(current)) {
    try { io.lstatSync(path.join(current, '.git')); fail('SOURCE_EXPORT_OUTSIDE_GIT_REQUIRED'); }
    catch (error) { if (error?.code !== 'ENOENT') throw error; }
    if (path.dirname(current) === current) break;
  }
}

function publicCa(certificates, now) {
  if (!Array.isArray(certificates) || certificates.length > 1024
    || certificates.some(value => typeof value !== 'string') || !Number.isFinite(now)) {
    fail('SOURCE_EXPORT_PUBLIC_ROOTS_REQUIRED');
  }
  for (const candidate of certificates) {
    if (candidate.length > MAX_CA_BYTES) continue;
    const pem = candidate.trim().replace(/\r\n/g, '\n') + '\n';
    const bytes = Buffer.from(pem);
    if (bytes.length > MAX_CA_BYTES
      || !/^-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]+\n-----END CERTIFICATE-----\n$/.test(pem)) continue;
    try {
      const certificate = new X509Certificate(bytes);
      if (certificate.ca && certificate.checkIssued(certificate) && certificate.verify(certificate.publicKey)
        && Date.parse(certificate.validFrom) <= now && now < Date.parse(certificate.validTo)) return bytes;
    } catch { /* A malformed or unsuitable public root is never emitted. */ }
  }
  fail('SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED');
}

/** CI source-export preparation only; this does not generate a local TLS key. */
export function prepareSourceExportCa({ environment = process.env, certificates = rootCertificates,
  now = Date.now(), io = fs } = {}) {
  let fd;
  try {
    if (environment.CI !== 'true') fail('SOURCE_EXPORT_CI_REQUIRED');
    if (environment.CASEOPS_MOBILE_SOURCE_EXPORT !== '1') fail('SOURCE_EXPORT_OPT_IN_REQUIRED');
    const temp = environment.RUNNER_TEMP;
    if (typeof temp !== 'string' || !path.isAbsolute(temp) || path.normalize(temp) !== temp
      || /[\x00-\x1f\x7f]/.test(temp) || environment.GIT_DIR || environment.GIT_WORK_TREE) {
      fail('SOURCE_EXPORT_TEMP_REQUIRED');
    }
    const parent = io.lstatSync(temp, { bigint: true });
    if (!directory(parent) || io.realpathSync(temp) !== temp) fail('SOURCE_EXPORT_TEMP_REQUIRED');
    outsideGit(io, temp);
    const bytes = publicCa(certificates, now);
    if (!same(parent, io.lstatSync(temp, { bigint: true }), DIRECTORY_FIELDS)) fail('SOURCE_EXPORT_DIRECTORY_CHANGED');
    const output = io.mkdtempSync(path.join(temp, 'caseops-source-export-'));
    io.chmodSync(output, 0o700);
    const created = io.lstatSync(output, { bigint: true });
    if (!directory(created) || (created.mode & 0o077n) !== 0n || io.realpathSync(output) !== output
      || !same(parent, io.lstatSync(temp, { bigint: true }), DIRECTORY_FIELDS)) fail('SOURCE_EXPORT_DIRECTORY_CHANGED');
    const file = path.join(output, 'public-ca.pem');
    fd = io.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL
      | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0), 0o444);
    let written = 0;
    while (written < bytes.length) {
      const count = io.writeSync(fd, bytes, written, bytes.length - written, null);
      if (!Number.isSafeInteger(count) || count <= 0 || count > bytes.length - written) fail('SOURCE_EXPORT_FILE_CHANGED');
      written += count;
    }
    io.fchmodSync(fd, 0o444);
    io.fsyncSync(fd);
    const opened = io.fstatSync(fd, { bigint: true });
    const named = io.lstatSync(file, { bigint: true });
    if (!opened.isFile() || !named.isFile() || named.isSymbolicLink() || !owned(opened)
      || opened.nlink !== 1n || (opened.mode & 0o7777n) !== 0o444n
      || opened.size !== BigInt(bytes.length) || !same(opened, named, FILE_FIELDS, true)) fail('SOURCE_EXPORT_FILE_CHANGED');
    const retained = Buffer.alloc(MAX_CA_BYTES + 1);
    let size = 0;
    while (size < retained.length) {
      const count = io.readSync(fd, retained, size, retained.length - size, size);
      if (!Number.isSafeInteger(count) || count < 0 || count > retained.length - size) fail('SOURCE_EXPORT_FILE_CHANGED');
      if (count === 0) break;
      size += count;
    }
    if (size !== bytes.length || !retained.subarray(0, size).equals(bytes)
      || !same(opened, io.fstatSync(fd, { bigint: true }), FILE_FIELDS)
      || !same(opened, io.lstatSync(file, { bigint: true }), FILE_FIELDS, true)) fail('SOURCE_EXPORT_FILE_CHANGED');
    const entries = io.readdirSync(output, { withFileTypes: true });
    if (entries.length !== 1 || entries[0].name !== 'public-ca.pem' || !entries[0].isFile()
      || entries[0].isSymbolicLink() || !same(created, io.lstatSync(output, { bigint: true }), DIRECTORY_FIELDS)
      || !same(parent, io.lstatSync(temp, { bigint: true }), DIRECTORY_FIELDS)
      || io.realpathSync(file) !== file) fail('SOURCE_EXPORT_DIRECTORY_CHANGED');
    return { file, sha256: sha(bytes) };
  } catch (error) {
    throw new Error(CODES.has(error?.message) ? error.message : 'SOURCE_EXPORT_PREPARATION_FAILED');
  } finally {
    if (fd !== undefined) {
      try { io.closeSync(fd); }
      catch { fail('SOURCE_EXPORT_PREPARATION_FAILED'); }
    }
  }
}

export function main(environment = process.env, print = console.log) {
  const result = prepareSourceExportCa({ environment });
  print(`CASEOPS_MOBILE_SOURCE_EXPORT_CA_FILE=${result.file}`);
  print(`CASEOPS_MOBILE_SOURCE_EXPORT_CA_SHA256=${result.sha256}`);
  return result;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); }
  catch (error) { console.error(CODES.has(error?.message) ? error.message : 'SOURCE_EXPORT_PREPARATION_FAILED'); process.exitCode = 1; }
}
