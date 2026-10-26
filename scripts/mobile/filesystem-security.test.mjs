import assert from 'node:assert/strict';
import { createHash, X509Certificate } from 'node:crypto';
import fs from 'node:fs';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { rootCertificates } from 'node:tls';
import test from 'node:test';
import { verifiedFile } from '../../apps/mobile/e2e/evidence.mjs';
import { binaryHash, localJson, MARKER, MARKER_HEADER } from '../../apps/mobile/e2e/support.mjs';

const require = createRequire(import.meta.url);
const plugin = require('../../apps/mobile/plugins/with-local-acceptance.cjs');
const sha = (data) => createHash('sha256').update(data).digest('hex');
const certificate = rootCertificates.find((pem) => {
  const value = new X509Certificate(pem);
  return value.ca && value.checkIssued(value) && value.verify(value.publicKey)
    && Date.parse(value.validFrom) < Date.now() && Date.now() < Date.parse(value.validTo);
});

function fixture(t, data = 'owned synthetic evidence') {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-filesystem-security-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'input');
  fs.writeFileSync(file, data);
  return { dir, file, data, expected: sha(data) };
}
function withFs(overrides, run) {
  const prior = Object.fromEntries(Object.keys(overrides).map((key) => [key, fs[key]]));
  for (const [key, wrap] of Object.entries(overrides)) fs[key] = (...args) => wrap(prior[key], ...args);
  syncBuiltinESMExports();
  try { return run(); }
  finally {
    Object.assign(fs, prior);
    syncBuiltinESMExports();
  }
}
function descriptorProof(file, action, { failAt } = {}) {
  const opened = [], closed = [], reads = [], stages = [];
  let thrown;
  let result;
  withFs({
    openSync: (original, name, flags, ...rest) => {
      const fd = original(name, flags, ...rest);
      if (name === file) { opened.push(fd); stages.push('open'); }
      return fd;
    },
    fstatSync: (original, fd, ...rest) => {
      if (opened.includes(fd)) { stages.push('fstat'); if (failAt === 'fstat') throw new Error('UNIT_FSTAT_FAILURE'); }
      return original(fd, ...rest);
    },
    lstatSync: (original, name, ...rest) => {
      if (name === file) stages.push('lstat');
      return original(name, ...rest);
    },
    readFileSync: (original, argument, ...rest) => {
      if (argument === file || opened.includes(argument)) {
        reads.push(argument); stages.push('read');
        if (failAt === 'read') throw new Error('UNIT_READ_FAILURE');
      }
      return original(argument, ...rest);
    },
    closeSync: (original, fd) => { if (opened.includes(fd)) { closed.push(fd); stages.push('close'); } return original(fd); },
  }, () => {
    try { result = action(); } catch (error) { thrown = error; }
  });
  assert.equal(opened.length, 1);
  assert.deepEqual(closed, opened, 'DESCRIPTOR_CLOSED_ON_EVERY_BRANCH');
  assert.ok(reads.every((argument) => typeof argument === 'number' && argument === opened[0]), 'READ_ONLY_THE_CHECKED_DESCRIPTOR');
  return { result, thrown, reads, stages };
}

function windowsStatPolicy(file, platform, alteration, action) {
  const descriptor = Object.getOwnPropertyDescriptor(process, 'platform');
  Object.defineProperty(process, 'platform', { ...descriptor, value: platform });
  try {
    return withFs({ lstatSync: (original, name, options) => {
      const actual = original(name, options);
      if (name !== file || options?.bigint !== true) return actual;
      return new Proxy(actual, { get(target, key) {
        if (key === 'dev') return 0n;
        if (key === 'ino' && alteration === 'inode') return actual.ino + 1n;
        if (key === 'isSymbolicLink' && alteration === 'symlink') return () => true;
        if (key === 'isFile' && alteration === 'directory') return () => false;
        return Reflect.get(target, key);
      } });
    } }, action);
  } finally { Object.defineProperty(process, 'platform', descriptor); }
}

test('Windows lstat dev=0 cannot invalidate the same opened inode in any mobile file consumer', (t) => {
  const value = fixture(t, certificate);
  const actions = [() => verifiedFile(value.file, value.expected), () => binaryHash(value.file),
    () => plugin.readPublicCa(value.file, value.expected)];
  for (const action of actions) {
    const result = windowsStatPolicy(value.file, 'win32', null, action);
    assert.ok(result, 'SAME_WINDOWS_INODE_MUST_BE_READ');
  }
});

test('Windows volume normalization preserves inode/file/symlink refusals and other platforms still compare dev', (t) => {
  const value = fixture(t, certificate);
  const actions = [() => verifiedFile(value.file, value.expected), () => binaryHash(value.file),
    () => plugin.readPublicCa(value.file, value.expected)];
  for (const action of actions) {
    for (const alteration of ['inode', 'symlink', 'directory']) {
      assert.throws(() => windowsStatPolicy(value.file, 'win32', alteration, action), /REPLACED/);
    }
    assert.throws(() => windowsStatPolicy(value.file, 'darwin', null, action), /REPLACED/);
  }
});

test('evidence opens before path checks and checks/reads/closes one descriptor', (t) => {
  const value = fixture(t);
  const proof = descriptorProof(value.file, () => verifiedFile(value.file, value.expected));
  assert.equal(proof.thrown, undefined);
  assert.equal(proof.result.toString(), value.data);
  assert.equal(proof.stages[0], 'open');
  assert.equal(proof.reads.length, 1);
});

test('evidence descriptor closes on metadata, read, size and digest failures', (t) => {
  const value = fixture(t);
  for (const failAt of ['fstat', 'read']) {
    const proof = descriptorProof(value.file, () => verifiedFile(value.file, value.expected), { failAt });
    assert.match(proof.thrown.message, /UNIT_.*_FAILURE/);
  }
  for (const [expected, maximum, error] of [[value.expected, 1, /BOUNDED/], ['0'.repeat(64), 1048576, /CHANGED/]]) {
    const proof = descriptorProof(value.file, () => verifiedFile(value.file, expected, maximum));
    assert.match(proof.thrown.message, error);
  }
});

test('same-length in-place artifact mutation cannot pass by restoring mtime', (t) => {
  const value = fixture(t, 'original bytes');
  const before = fs.statSync(value.file);
  let changed = false, opened;
  withFs({
    fstatSync: (original, fd, ...args) => {
      const actual = original(fd, ...args);
      if (!opened) { opened = actual; return actual; }
      assert.notEqual(actual.ctimeNs, opened.ctimeNs, 'ACTUAL_MUTATION_MUST_CHANGE_CTIME');
      // Give the actor an exact mtime restoration, including submillisecond
      // precision. The descriptor's independently changed ctime must reject it.
      return new Proxy(actual, { get: (target, key) => key === 'mtimeNs' ? opened.mtimeNs : Reflect.get(target, key) });
    },
    readFileSync: (original, fd, ...args) => {
    if (typeof fd === 'number' && !changed) {
      changed = true;
      fs.writeFileSync(value.file, 'mutated! bytes');
      fs.utimesSync(value.file, before.atime, before.mtime);
    }
    return original(fd, ...args);
    },
  }, () => assert.throws(() => binaryHash(value.file), /BINARY_FILE_CHANGED/));
  assert.equal(changed, true);
});

test('APK hashing reads the descriptor and retains the actual SHA-256 format', (t) => {
  const value = fixture(t, 'synthetic APK bytes');
  const proof = descriptorProof(value.file, () => binaryHash(value.file));
  assert.equal(proof.thrown, undefined);
  assert.equal(proof.result, value.expected);
  assert.equal(proof.reads.length, 1);
});

test('a replacement at a path-read boundary cannot substitute unchecked APK bytes', (t) => {
  const value = fixture(t, 'original APK bytes');
  let pathReads = 0;
  const result = withFs({ readFileSync: (original, file, ...args) => {
    if (file === value.file) { pathReads++; fs.writeFileSync(file, 'unchecked foreign content'); }
    return original(file, ...args);
  } }, () => binaryHash(value.file));
  assert.equal(result, value.expected);
  assert.equal(pathReads, 0);
});

test('bundle tree digest keeps its existing sorted path/size/byte serialization including empty files', (t) => {
  const value = fixture(t);
  const bundle = path.join(value.dir, 'App.app');
  fs.mkdirSync(path.join(bundle, 'sub'), { recursive: true });
  fs.writeFileSync(path.join(bundle, 'z'), 'last');
  fs.writeFileSync(path.join(bundle, 'sub', 'a'), 'first');
  fs.writeFileSync(path.join(bundle, 'empty'), '');
  const expected = createHash('sha256').update('/empty\0' + '0\0').update('')
    .update('/sub/a\0' + '5\0').update('first').update('/z\0' + '4\0').update('last').digest('hex');
  assert.equal(binaryHash(bundle), expected);
});

test('bundle membership changing during enumeration is refused rather than silently omitted', (t) => {
  const value = fixture(t);
  const bundle = path.join(value.dir, 'App.app');
  fs.mkdirSync(bundle); fs.writeFileSync(path.join(bundle, 'original'), 'original');
  let added = false;
  withFs({ readdirSync: (original, file, ...args) => {
    const entries = original(file, ...args);
    if (file === bundle && !added) { added = true; fs.writeFileSync(path.join(bundle, 'new'), 'unreviewed'); }
    return entries;
  } }, () => assert.throws(() => binaryHash(bundle), /BINARY_DIRECTORY_CHANGED/));
});

test('binary descriptors close on a failed read; empty root and nonregular input stay unavailable', (t) => {
  const value = fixture(t);
  const proof = descriptorProof(value.file, () => binaryHash(value.file), { failAt: 'read' });
  assert.match(proof.thrown.message, /UNIT_READ_FAILURE/);
  fs.writeFileSync(value.file, '');
  assert.throws(() => binaryHash(value.file), /BINARY_BOUND_EXCEEDED/);
  assert.throws(() => verifiedFile(value.dir, value.expected), /BOUNDED|EISDIR|EACCES|EPERM/);
});

test('public CA provenance and bytes are checked through one closed descriptor', (t) => {
  assert.ok(certificate, 'CURRENT_NODE_PUBLIC_ROOT_REQUIRED');
  const value = fixture(t, certificate);
  const proof = descriptorProof(value.file, () => plugin.readPublicCa(value.file, value.expected));
  assert.equal(proof.thrown, undefined);
  assert.equal(proof.result.pem, certificate);
  assert.equal(proof.result.sha256, value.expected);
  assert.equal(proof.stages[0], 'open');
});

test('public CA descriptors close on read, metadata, wrong-digest and expiry refusals', (t) => {
  const value = fixture(t, certificate);
  for (const failAt of ['fstat', 'read']) {
    const proof = descriptorProof(value.file, () => plugin.readPublicCa(value.file, value.expected), { failAt });
    assert.match(proof.thrown.message, /UNIT_.*_FAILURE/);
  }
  let proof = descriptorProof(value.file, () => plugin.readPublicCa(value.file, '0'.repeat(64)));
  assert.match(proof.thrown.message, /PUBLIC_CA_HASH_MISMATCH/);
  proof = descriptorProof(value.file, () => plugin.readPublicCa(value.file, value.expected, Date.parse(new X509Certificate(certificate).validTo)));
  assert.match(proof.thrown.message, /PUBLIC_CA_NOT_CURRENT/);
});

test('local probes reconstruct only reviewed loopback GET endpoints with their constant marker', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    return Response.json({ observed: true });
  });
  for (const url of ['http://127.0.0.1:8191/api/build', 'https://localhost:8443/api/release-identity',
    'http://[::1]:4723/wd/hub/status', 'http://localhost:4723/status', 'https://127.0.0.1:8443/__caseops_e2e/status']) {
    assert.deepEqual(await localJson(url), { observed: true });
  }
  assert.equal(calls.length, 5);
  for (const { url, options } of calls) {
    assert.equal(typeof url, 'string');
    assert.equal(options.method, 'GET'); assert.equal(options.redirect, 'error');
    assert.deepEqual(options.headers, { [MARKER_HEADER]: MARKER });
    assert.equal(options.body, undefined); assert.ok(options.signal instanceof AbortSignal);
  }
});

test('arbitrary file-derived paths, options, origins and credentials are rejected before dispatch', async (t) => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return Response.json({}); });
  for (const url of ['https://example.com/status', 'http://127.0.0.1/upload/private-file-bytes',
    'http://user:private@127.0.0.1/status', 'http://127.0.0.1/status?private=value', 'http://127.0.0.1/status#private',
    'file:///private/status', 'http://127.0.0.1:0/status']) {
    await assert.rejects(() => localJson(url));
  }
  for (const options of [{ method: 'POST' }, { headers: { Referer: 'file data' } }, { body: 'file data' }]) {
    await assert.rejects(() => localJson('http://127.0.0.1:8191/status', options), /READ_ONLY_LOCAL_PROBE_REQUIRED/);
  }
  assert.equal(calls, 0);
});

test('a mutable URL value cannot change the authority between validation and fetch', async (t) => {
  let coercions = 0, dispatched;
  t.mock.method(globalThis, 'fetch', async (url) => { dispatched = url; return Response.json({ ok: true }); });
  const value = { toString: () => ++coercions === 1 ? 'http://127.0.0.1:8191/status' : 'https://example.com/private' };
  assert.deepEqual(await localJson(value), { ok: true });
  assert.equal(coercions, 1);
  assert.equal(dispatched, 'http://127.0.0.1:8191/status');
});

test('probe response bound still cancels an oversized response instead of parsing it', async (t) => {
  let cancelled = 0;
  t.mock.method(globalThis, 'fetch', async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(1048577)); },
    cancel() { cancelled++; },
  })));
  await assert.rejects(() => localJson('http://127.0.0.1:8191/status'), /RESPONSE_BOUND_EXCEEDED/);
  assert.equal(cancelled, 1);
});
