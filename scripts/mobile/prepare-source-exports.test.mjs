import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import { createHash, X509Certificate } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { rootCertificates } from 'node:tls';
import { main, prepareSourceExportCa } from './prepare-source-exports.mjs';

const now = Date.now();
const certificate = rootCertificates.find(pem => {
  const value = new X509Certificate(pem);
  return value.ca && value.checkIssued(value) && value.verify(value.publicKey)
    && Date.parse(value.validFrom) <= now && now < Date.parse(value.validTo);
});
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const require = createRequire(import.meta.url);

function fixture(t) {
  const temp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-source-export-unit-')));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));
  return { temp, environment: { CI: 'true', CASEOPS_MOBILE_SOURCE_EXPORT: '1', RUNNER_TEMP: temp } };
}
function create(value, extra = {}) {
  return prepareSourceExportCa({ environment: value.environment, certificates: [certificate], now, ...extra });
}
function mutateStat(value, key) {
  return new Proxy(value, { get(target, property) { return property === key ? value[key] + 1n : Reflect.get(target, property); } });
}
function pem(bytes) { return `-----BEGIN CERTIFICATE-----\n${bytes.toString('base64').match(/.{1,64}/g).join('\n')}\n-----END CERTIFICATE-----\n`; }
function derNode(bytes, start) {
  let offset = start + 2, length = bytes[start + 1];
  if (length & 128) { const size = length & 127; length = 0; for (let i = 0; i < size; i++) length = length * 256 + bytes[offset++]; }
  return { start, value: offset, end: offset + length };
}

test('source export preparation requires explicit CI and separate exact opt-in', t => {
  const value = fixture(t);
  for (const CI of [undefined, false, true, 'false', '1']) assert.throws(() => create(value,
    { environment: { ...value.environment, CI } }), /SOURCE_EXPORT_CI_REQUIRED/);
  for (const flag of [undefined, true, 'true', '0']) assert.throws(() => create(value,
    { environment: { ...value.environment, CASEOPS_MOBILE_SOURCE_EXPORT: flag } }), /SOURCE_EXPORT_OPT_IN_REQUIRED/);
  assert.deepEqual(fs.readdirSync(value.temp), []);
});

test('RUNNER_TEMP is absolute, canonical, directory-owned and free of environment-line injection', t => {
  const value = fixture(t), link = path.join(value.temp, 'alias'); fs.symlinkSync(value.temp, link);
  for (const RUNNER_TEMP of [undefined, 'relative', value.temp + '/.', value.temp + '\nINJECT=1', link]) {
    assert.throws(() => create(value, { environment: { ...value.environment, RUNNER_TEMP } }), /SOURCE_EXPORT_TEMP_REQUIRED/);
  }
  for (const name of ['GIT_DIR', 'GIT_WORK_TREE']) assert.throws(() => create(value,
    { environment: { ...value.environment, [name]: value.temp } }), /SOURCE_EXPORT_TEMP_REQUIRED/);
  if (typeof process.getuid === 'function') {
    const io = { ...fs, lstatSync(file, options) {
      const stat = fs.lstatSync(file, options);
      return file === value.temp ? mutateStat(stat, 'uid') : stat;
    } };
    assert.throws(() => create(value, { io }), /SOURCE_EXPORT_TEMP_REQUIRED/);
  }
});

test('an ancestor .git directory or worktree file refuses without invoking a Git command', t => {
  const value = fixture(t), nested = path.join(value.temp, 'nested'); fs.mkdirSync(nested);
  const marker = path.join(value.temp, '.git'); fs.mkdirSync(marker);
  assert.throws(() => create(value, { environment: { ...value.environment, RUNNER_TEMP: nested } }), /SOURCE_EXPORT_OUTSIDE_GIT_REQUIRED/);
  fs.rmdirSync(marker); fs.writeFileSync(marker, 'gitdir: synthetic-public-marker\n');
  assert.throws(() => create(value), /SOURCE_EXPORT_OUTSIDE_GIT_REQUIRED/);
  assert.deepEqual(fs.readdirSync(value.temp).sort(), ['.git', 'nested']);
});

test('missing, malformed, wrong-type and oversized public root inputs create no output', t => {
  const value = fixture(t);
  for (const certificates of [[], ['not a certificate'], [certificate + 'PRIVATE_SYNTHETIC_MARKER'],
    [' '.repeat(16385) + certificate + 'x'], [certificate.repeat(20)]]) {
    assert.throws(() => create(value, { certificates }), /SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED/);
  }
  for (const certificates of [null, 'certificate', [Buffer.from(certificate)], [null]]) {
    assert.throws(() => create(value, { certificates }), /SOURCE_EXPORT_PUBLIC_ROOTS_REQUIRED/);
  }
  assert.deepEqual(fs.readdirSync(value.temp), []);
});

test('expired roots and nonfinite test clocks cannot be selected', t => {
  const value = fixture(t), ca = new X509Certificate(certificate);
  assert.throws(() => create(value, { now: Date.parse(ca.validTo) }), /SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED/);
  assert.throws(() => create(value, { now: Date.parse(ca.validFrom) - 1 }), /SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED/);
  for (const clock of [NaN, Infinity, 'now']) assert.throws(() => create(value, { now: clock }), /SOURCE_EXPORT_PUBLIC_ROOTS_REQUIRED/);
  assert.deepEqual(fs.readdirSync(value.temp), []);
});

test('a valid single public CA larger than 16 KiB is refused before creating an output directory', t => {
  const value = fixture(t);
  const oversized = certificate + '\n'.repeat(16385);
  assert.ok(Buffer.byteLength(oversized) > 16384);
  const parsed = new X509Certificate(oversized);
  assert.equal(parsed.ca && parsed.verify(parsed.publicKey), true, 'positive parser control on oversized public input');
  assert.throws(() => create(value, { certificates: [oversized] }), /SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED/);
  assert.deepEqual(fs.readdirSync(value.temp), []);
});

test('a real public certificate with corrupted self-signature is refused without key generation', t => {
  const value = fixture(t), bytes = Buffer.from(new X509Certificate(certificate).raw);
  bytes[bytes.length - 1] ^= 1;
  const corrupted = pem(bytes), ca = new X509Certificate(corrupted);
  assert.equal(ca.ca, true); assert.equal(ca.verify(ca.publicKey), false);
  assert.throws(() => create(value, { certificates: [corrupted] }), /SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED/);
});

test('a non-self-issued certificate is refused using only altered public DER issuer bytes', t => {
  const value = fixture(t), bytes = Buffer.from(new X509Certificate(certificate).raw);
  const root = derNode(bytes, 0), tbs = derNode(bytes, root.value); let child = derNode(bytes, tbs.value);
  if (bytes[child.start] === 0xa0) child = derNode(bytes, child.end);
  child = derNode(bytes, child.end); const issuer = derNode(bytes, child.end);
  let index = issuer.end - 1;
  while (index >= issuer.value && !/[a-z]/i.test(String.fromCharCode(bytes[index]))) index--;
  assert.ok(index >= issuer.value); bytes[index] = bytes[index] === 65 ? 66 : 65;
  const altered = pem(bytes), ca = new X509Certificate(altered);
  assert.notEqual(ca.issuer, ca.subject); assert.equal(ca.checkIssued(ca), false);
  assert.throws(() => create(value, { certificates: [altered] }), /SOURCE_EXPORT_CURRENT_PUBLIC_CA_REQUIRED/);
});

test('positive writes one current public PEM exclusively into a fresh owned readonly folder', t => {
  const value = fixture(t), first = create(value), second = create(value);
  assert.notEqual(path.dirname(first.file), path.dirname(second.file));
  const bytes = fs.readFileSync(first.file), ca = new X509Certificate(bytes);
  assert.equal(bytes.length <= 16384, true); assert.equal(first.sha256, sha(bytes));
  assert.equal(ca.ca, true); assert.equal(ca.verify(ca.publicKey), true);
  assert.deepEqual(fs.readdirSync(path.dirname(first.file)), ['public-ca.pem']);
  const stat = fs.lstatSync(first.file), folder = fs.lstatSync(path.dirname(first.file));
  assert.equal(stat.isFile() && !stat.isSymbolicLink() && stat.nlink === 1, true);
  assert.equal(stat.mode & 0o7777, 0o444); assert.equal(folder.mode & 0o077, 0);
  if (typeof process.getuid === 'function') assert.equal(stat.uid, process.getuid());
  assert.equal(bytes.includes(Buffer.from('PRIVATE KEY')), false);
});

test('exclusive descriptor writes, same-FD bounded readback and closure are actual operations', t => {
  const value = fixture(t), opened = [], closed = [], reads = [];
  const io = { ...fs, openSync(file, flags, mode) {
    assert.equal(flags & fs.constants.O_EXCL, fs.constants.O_EXCL);
    assert.equal(mode, 0o444); const fd = fs.openSync(file, flags, mode); opened.push(fd); return fd;
  }, readSync(fd, buffer, offset, length, position) {
    reads.push({ fd, length }); assert.ok(length <= 16385); return fs.readSync(fd, buffer, offset, length, position);
  }, closeSync(fd) { closed.push(fd); fs.closeSync(fd); } };
  const result = create(value, { io });
  assert.equal(opened.length, 1); assert.deepEqual(closed, opened);
  assert.ok(reads.length > 0 && reads.every(read => read.fd === opened[0]));
  assert.equal(result.sha256, sha(fs.readFileSync(result.file)));
});

test('descriptor-close failures stay fixed and never return an environment value', t => {
  const value = fixture(t); let closed = 0;
  const io = { ...fs, closeSync(fd) { fs.closeSync(fd); closed++; throw new Error('synthetic-private-path'); } };
  assert.throws(() => create(value, { io }), /^Error: SOURCE_EXPORT_PREPARATION_FAILED$/);
  assert.equal(closed, 1);
});

test('file metadata drift refuses and closes the descriptor before returning an environment value', t => {
  const value = fixture(t);
  for (const key of ['ino', 'size', 'uid', 'gid', 'mode', 'nlink', 'mtimeNs', 'ctimeNs', 'dev']) {
    let count = 0, closes = 0;
    const io = { ...fs, fstatSync(fd, options) {
      const stat = fs.fstatSync(fd, options); return ++count === 2 ? mutateStat(stat, key) : stat;
    }, closeSync(fd) { closes++; fs.closeSync(fd); } };
    assert.throws(() => create(value, { io }), /SOURCE_EXPORT_FILE_CHANGED/, key); assert.equal(closes, 1);
    let named = 0, namedCloses = 0;
    const namedIo = { ...fs, lstatSync(file, options) {
      const stat = fs.lstatSync(file, options);
      return path.basename(file) === 'public-ca.pem' && ++named === 2 ? mutateStat(stat, key) : stat;
    }, closeSync(fd) { namedCloses++; fs.closeSync(fd); } };
    assert.throws(() => create(value, { io: namedIo }), /SOURCE_EXPORT_FILE_CHANGED/);
    assert.equal(namedCloses, 1);
  }
});

test('source export Windows dev-zero portability refuses nonzero mismatches before readback and retains independent frames', t => {
  const value = fixture(t), platform = Object.getOwnPropertyDescriptor(process, 'platform');
  for (const change of ['zero', 'same', 'nonzero', 'inode', 'owner', 'directory', 'symlink', 'fd-drift', 'named-drift', 'darwin']) {
    let fd, reads = 0;
    Object.defineProperty(process, 'platform', { ...platform, value: change === 'darwin' ? 'darwin' : 'win32' });
    const io = { ...fs, openSync(...args) { fd = fs.openSync(...args); return fd; },
      fstatSync(...args) { const stat = fs.fstatSync(...args); return change === 'fd-drift' && reads > 0 ? mutateStat(stat, 'dev') : stat; },
      lstatSync(name, options) {
        const stat = fs.lstatSync(name, options); if (path.basename(name) !== 'public-ca.pem') return stat;
        const device = change === 'same' || change === 'named-drift' && reads > 0 ? stat.dev : change === 'nonzero' ? stat.dev + 1n : 0n;
        return new Proxy(stat, { get(target, key) {
          if (key === 'dev') return device;
          if (key === 'ino' && change === 'inode') return stat.ino + 1n;
          if (key === 'uid' && change === 'owner') return stat.uid + 1n;
          if (key === 'isFile' && change === 'directory') return () => false;
          if (key === 'isSymbolicLink' && change === 'symlink') return () => true;
          return Reflect.get(target, key);
        } });
      }, readSync(...args) { reads++; return fs.readSync(...args); } };
    try {
      if (['zero', 'same'].includes(change)) assert.match(create(value, { io }).sha256, /^[a-f0-9]{64}$/);
      else assert.throws(() => create(value, { io }), /SOURCE_EXPORT_FILE_CHANGED/, change);
      if (!['zero', 'same', 'fd-drift', 'named-drift'].includes(change)) assert.equal(reads, 0, `${change}: refuse before readback`);
      assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
    } finally { Object.defineProperty(process, 'platform', platform); }
  }
});

test('parent namespace replacement is refused before a public file is opened', t => {
  const value = fixture(t); let opened = 0;
  const io = { ...fs, mkdtempSync(prefix) {
    const child = fs.mkdtempSync(prefix); fs.renameSync(value.temp, value.temp + '-retained');
    fs.mkdirSync(value.temp, { mode: 0o700 }); fs.mkdirSync(child, { mode: 0o700 });
    t.after(() => fs.rmSync(value.temp + '-retained', { recursive: true, force: true }));
    return child;
  }, openSync(...args) { opened++; return fs.openSync(...args); } };
  assert.throws(() => create(value, { io }), /SOURCE_EXPORT_DIRECTORY_CHANGED/);
  assert.equal(opened, 0);
});

test('an extra child entry cannot pass a complete unique-directory observation', t => {
  const value = fixture(t);
  const io = { ...fs, readdirSync(directory, options) {
    fs.writeFileSync(path.join(directory, 'unexpected-public-file'), 'synthetic');
    return fs.readdirSync(directory, options);
  } };
  assert.throws(() => create(value, { io }), /SOURCE_EXPORT_DIRECTORY_CHANGED/);
});

test('main emits only the two public environment lines, with no certificate or diagnostics', t => {
  const value = fixture(t), lines = [];
  const result = main(value.environment, line => lines.push(line));
  assert.deepEqual(lines, [`CASEOPS_MOBILE_SOURCE_EXPORT_CA_FILE=${result.file}`,
    `CASEOPS_MOBILE_SOURCE_EXPORT_CA_SHA256=${result.sha256}`]);
  assert.equal(lines.join('\n').includes('BEGIN CERTIFICATE'), false);
  const refusedLines = [];
  assert.throws(() => main({ ...value.environment, CI: 'false' }, line => refusedLines.push(line)), /SOURCE_EXPORT_CI_REQUIRED/);
  assert.deepEqual(refusedLines, []);
});

test('actual acceptanceSettings accepts Android QA and rejects an Android CA on iOS, without host commands', t => {
  const value = fixture(t), ca = create(value);
  const pluginPath = require.resolve('../../apps/mobile/plugins/with-local-acceptance.cjs');
  const saved = childProcess.spawnSync; let commands = 0;
  delete require.cache[pluginPath];
  childProcess.spawnSync = (command, args) => {
    assert.equal(command, 'git'); assert.deepEqual(args, ['rev-parse', '--is-inside-work-tree']);
    commands++; return { status: 128, stderr: 'fatal: not a git repository', stdout: '' };
  };
  let plugin;
  try { plugin = require(pluginPath); }
  finally { childProcess.spawnSync = saved; delete require.cache[pluginPath]; }
  const shared = { CASEOPS_MOBILE_AUTOMATED_TEST: '1', CASEOPS_MOBILE_RELEASE_SHA: 'a'.repeat(40) };
  const android = plugin.acceptanceSettings({ ...shared, CASEOPS_MOBILE_BUILD_PROFILE: 'android-local-acceptance',
    EXPO_PUBLIC_API_ORIGIN: 'https://10.0.2.2:8453', EXPO_PUBLIC_WEB_ORIGIN: 'https://10.0.2.2:3453',
    CASEOPS_MOBILE_ANDROID_CA_FILE: ca.file, CASEOPS_MOBILE_ANDROID_CA_SHA256: ca.sha256 });
  assert.equal(android.platform, 'android'); assert.equal(android.ca.sha256, ca.sha256); assert.equal(commands, 1);
  const ios = { ...shared, CASEOPS_MOBILE_BUILD_PROFILE: 'ios-simulator-acceptance',
    EXPO_PUBLIC_API_ORIGIN: 'https://127.0.0.1:8443', EXPO_PUBLIC_WEB_ORIGIN: 'https://127.0.0.1:3443' };
  assert.equal(plugin.acceptanceSettings(ios).ca, null);
  assert.throws(() => plugin.acceptanceSettings({ ...ios, CASEOPS_MOBILE_ANDROID_CA_FILE: ca.file,
    CASEOPS_MOBILE_ANDROID_CA_SHA256: ca.sha256 }), /ANDROID_CA_FORBIDDEN_ON_IOS/);
});
