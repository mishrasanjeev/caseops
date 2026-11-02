import assert from 'node:assert/strict';
import { createHash, X509Certificate } from 'node:crypto';
import fs from 'node:fs';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
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
  let readFileDepth = 0;
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
      readFileDepth++;
      try { return original(argument, ...rest); }
      finally { readFileDepth--; }
    },
    readSync: (original, argument, ...rest) => {
      if (readFileDepth === 0 && opened.includes(argument)) {
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

test('binary Windows dev-zero portability retains pre-read identity and independent final FD and named frames', t => {
  const value = fixture(t), platform = Object.getOwnPropertyDescriptor(process, 'platform');
  for (const change of ['zero', 'same', 'nonzero', 'inode', 'owner', 'fd-dev', 'fd-owner', 'named-dev', 'named-owner', 'darwin']) {
    let reads = 0;
    Object.defineProperty(process, 'platform', { ...platform, value: change === 'darwin' ? 'darwin' : 'win32' });
    try {
      const proof = withFs({
        lstatSync(original, file, options) {
          const stat = original(file, options); if (file !== value.file || !options?.bigint) return stat;
          const dev = change === 'same' || change === 'named-dev' && reads > 0 ? stat.dev : change === 'nonzero' ? stat.dev + 1n : 0n;
          const patch = { dev, ...(change === 'inode' ? { ino: stat.ino + 1n } : {}),
            ...((change === 'owner' || change === 'named-owner' && reads > 0) ? { uid: stat.uid + 1n } : {}) };
          return new Proxy(stat, { get: (target, key) => Object.hasOwn(patch, key) ? patch[key] : Reflect.get(target, key) });
        },
        fstatSync(original, ...args) {
          const stat = original(...args), patch = reads > 0 ? change === 'fd-dev' ? { dev: stat.dev + 1n } : change === 'fd-owner' ? { uid: stat.uid + 1n } : {} : {};
          return new Proxy(stat, { get: (target, key) => Object.hasOwn(patch, key) ? patch[key] : Reflect.get(target, key) });
        },
        readFileSync(original, ...args) { reads++; return original(...args); },
        readSync(original, ...args) { reads++; return original(...args); },
      }, () => descriptorProof(value.file, () => binaryHash(value.file)));
      if (['zero', 'same'].includes(change)) assert.equal(proof.result, value.expected);
      else assert.match(proof.thrown?.message || '', /BINARY_FILE_(?:REPLACED|CHANGED)/, change);
      if (['nonzero', 'inode', 'owner', 'darwin'].includes(change)) assert.equal(proof.reads.length, 0, change);
    } finally { Object.defineProperty(process, 'platform', platform); }
  }
});

test('binary growth after descriptor admission consumes at most the opened extent plus one and closes on refusal', t => {
  const value = fixture(t, 'original'), originalLength = Buffer.byteLength(value.data);
  let fd, consumed = 0, changed = false, nested = 0;
  const grow = () => { if (!changed) { changed = true; fs.appendFileSync(value.file, ' replacement-growth'.repeat(100)); } };
  withFs({
    openSync(original, ...args) { fd = original(...args); return fd; },
    readFileSync(original, argument, ...args) {
      if (argument !== fd) return original(argument, ...args);
      grow(); nested++;
      try { const bytes = original(argument, ...args); consumed += bytes.length; return bytes; }
      finally { nested--; }
    },
    readSync(original, argument, ...args) {
      if (argument === fd) grow();
      const count = original(argument, ...args); if (argument === fd && !nested) consumed += count; return count;
    },
  }, () => assert.throws(() => binaryHash(value.file), /BINARY_FILE_CHANGED/));
  assert.equal(changed, true); assert.ok(consumed <= originalLength + 1, `${consumed} exceeds admitted detector extent`);
  assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' });
});

test('evidence opens before path checks and checks/reads/closes one descriptor', (t) => {
  const value = fixture(t);
  const proof = descriptorProof(value.file, () => verifiedFile(value.file, value.expected));
  assert.equal(proof.thrown, undefined);
  assert.equal(proof.result.toString(), value.data);
  assert.equal(proof.stages[0], 'open');
  assert.ok(proof.reads.length >= 1);
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
    readSync: (original, fd, ...args) => {
    if (!changed) {
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
  assert.equal(proof.reads.length, 2, 'payload read followed by one EOF/growth detector read');
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

test('bundle hash keeps sorted DFS order when a directory prefix and dotted sibling sort differently', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'); fs.mkdirSync(path.join(root, 'a'), { recursive: true });
  fs.writeFileSync(path.join(root, 'a', 'z'), 'first'); fs.writeFileSync(path.join(root, 'a.txt'), 'second');
  const expected = createHash('sha256').update('/a/z\0' + '5\0first/a.txt\0' + '6\0second').digest('hex');
  assert.equal(binaryHash(root), expected);
});

test('bundle census rejects a real insertion in an already visited nested directory', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'), early = path.join(root, 'a'), late = path.join(root, 'z');
  fs.mkdirSync(early, { recursive: true }); fs.mkdirSync(late); fs.writeFileSync(path.join(early, 'first'), 'first');
  const last = path.join(late, 'last'); fs.writeFileSync(last, 'last'); let selected, inserted = false;
  withFs({ openSync(original, name, ...args) { const fd = original(name, ...args); if (name === last) selected = fd; return fd; },
    readSync(original, fd, ...args) { if (fd === selected && !inserted) { inserted = true; fs.writeFileSync(path.join(early, 'missed'), 'new'); } return original(fd, ...args); },
  }, () => assert.throws(() => binaryHash(root), /BINARY_(?:CENSUS|DIRECTORY)_CHANGED/));
  assert.equal(inserted, true); assert.throws(() => fs.fstatSync(selected), { code: 'EBADF' });
});

test('bundle final reconciliation catches insertion after the second leaf metadata observation', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'); fs.mkdirSync(root); const file = path.join(root, 'file'); fs.writeFileSync(file, 'x');
  let inventories = 0, secondClosed = false, leafStats = 0, inserted = false;
  withFs({ opendirSync(original, name, ...args) { const dir = original(name, ...args); if (name !== root) return dir;
      const observation = ++inventories; return { readSync: () => dir.readSync(), closeSync() { dir.closeSync(); if (observation === 2) secondClosed = true; } }; },
    lstatSync(original, name, ...args) { const value = original(name, ...args); if (name === file && secondClosed && ++leafStats === 2) {
      inserted = true; fs.writeFileSync(path.join(root, 'late'), 'late'); } return value; },
  }, () => assert.throws(() => binaryHash(root), /BINARY_CENSUS_CHANGED/));
  assert.equal(inventories, 2); assert.equal(inserted, true);
});

test('bundle empty-root second census cannot return zero-copy success after a late insertion', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'); fs.mkdirSync(root); let observations = 0, inserted = false, closed = 0;
  withFs({ opendirSync(original, ...args) { const dir = original(...args), observation = ++observations;
    return { readSync: () => dir.readSync(), closeSync() { dir.closeSync(); closed++; if (observation === 2) { inserted = true; fs.writeFileSync(path.join(root, 'late'), 'late'); } } }; },
  }, () => assert.throws(() => binaryHash(root), /BINARY_DIRECTORY_CHANGED/));
  assert.equal(observations, 2); assert.equal(closed, 2); assert.equal(inserted, true);
});

test('bundle held-file parent replacement refuses before bytes and closes its actual descriptor', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'), dir = path.join(root, 'parent'), moved = path.join(root, 'moved'); fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'file'); fs.writeFileSync(file, 'x'); let selected, changed = false, reads = 0;
  withFs({ openSync(original, name, ...args) { const fd = original(name, ...args); if (name === file) selected = fd; return fd; },
    fstatSync(original, fd, ...args) { const value = original(fd, ...args); if (fd === selected && !changed) { changed = true; fs.renameSync(dir, moved); fs.symlinkSync(moved, dir); } return value; },
    readSync(original, fd, ...args) { if (fd === selected) reads++; return original(fd, ...args); },
  }, () => assert.throws(() => binaryHash(root), /BINARY_NAMESPACE_CHANGED/));
  assert.equal(changed, true); assert.equal(reads, 0); assert.throws(() => fs.fstatSync(selected), { code: 'EBADF' });
});

test('bundle two-observation entry cap includes root and EOF while duplicates refuse before retention', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'); fs.mkdirSync(root); fs.writeFileSync(path.join(root, 'file'), 'x');
  assert.match(binaryHash(root, { maxEntries: 4 }), /^[a-f0-9]{64}$/);
  let opened = 0, closed = 0;
  const tracked = (original, ...args) => { const dir = original(...args); opened++; return { readSync: () => dir.readSync(), closeSync() { dir.closeSync(); closed++; } }; };
  withFs({ opendirSync: tracked }, () => assert.throws(() => binaryHash(root, { maxEntries: 3 }), /BINARY_CENSUS_ENTRY_BOUND/));
  assert.equal(opened, 2); assert.equal(closed, opened);
  let reads = 0;
  withFs({ readdirSync: () => ['file', 'file'], opendirSync(original, ...args) { const dir = original(...args); let first;
    return { readSync() { reads++; if (first) return first; first = dir.readSync(); return first; }, closeSync() { dir.closeSync(); } }; },
  }, () => assert.throws(() => binaryHash(root), /BINARY_DUPLICATE_ENTRY/));
  assert.equal(reads, 2);
});

test('bundle census enforces depth and checks its shared deadline before and after iterator next', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'); fs.mkdirSync(root); fs.writeFileSync(path.join(root, 'file'), 'x');
  assert.throws(() => binaryHash(root, { maxDepth: 0 }), /BINARY_CENSUS_DEPTH_BOUND/);
  const descriptor = Object.getOwnPropertyDescriptor(performance, 'now');
  for (const point of ['before-next', 'after-next']) {
    let now = 0, reads = 0, closed = 0; Object.defineProperty(performance, 'now', { configurable: true, value: () => now });
    try { withFs({ opendirSync(original, ...args) { const dir = original(...args); if (point === 'before-next') now = 30000;
      return { readSync() { reads++; const value = dir.readSync(); now = 30000; return value; }, closeSync() { dir.closeSync(); closed++; } }; },
    }, () => assert.throws(() => binaryHash(root), /BINARY_CENSUS_DEADLINE/));
      assert.equal(reads, point === 'before-next' ? 0 : 1); assert.equal(closed, 1);
    } finally { if (descriptor) Object.defineProperty(performance, 'now', descriptor); else delete performance.now; }
  }
});

test('bundle declared aggregate and remaining descriptor extents refuse before payload', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'); fs.mkdirSync(root);
  const a = path.join(root, 'a'), b = path.join(root, 'b'); fs.writeFileSync(a, 'a'); fs.writeFileSync(b, 'b'); let reads = 0;
  withFs({ lstatSync(original, name, options) { const value = original(name, options);
    return [a, b].includes(name) && options?.bigint ? new Proxy(value, { get: (target, key) => key === 'size' ? 1610612736n : Reflect.get(target, key) }) : value; },
    readSync(original, ...args) { reads++; return original(...args); },
  }, () => assert.throws(() => binaryHash(root), /BINARY_BOUND_EXCEEDED/));
  assert.equal(reads, 0);
  let selected;
  withFs({ openSync(original, name, ...args) { const fd = original(name, ...args); if (name === a) selected = fd; return fd; },
    fstatSync(original, fd, ...args) { const value = original(fd, ...args); return fd === selected
      ? new Proxy(value, { get: (target, key) => key === 'size' ? 2147483649n : Reflect.get(target, key) }) : value; },
    readSync(original, ...args) { reads++; return original(...args); },
  }, () => assert.throws(() => binaryHash(root), /BINARY_BOUND_EXCEEDED/));
  assert.equal(reads, 0); assert.throws(() => fs.fstatSync(selected), { code: 'EBADF' });
});

test('bundle second complete census reads metadata only while legacy payload bytes are consumed once', t => {
  const f = fixture(t), root = path.join(f.dir, 'App.app'); fs.mkdirSync(root); const file = path.join(root, 'file'); fs.writeFileSync(file, 'payload');
  let observations = 0, consumed = 0, selected;
  withFs({ opendirSync(original, ...args) { observations++; return original(...args); },
    openSync(original, name, ...args) { const fd = original(name, ...args); if (name === file) selected = fd; return fd; },
    readSync(original, fd, ...args) { const count = original(fd, ...args); if (fd === selected) consumed += count; return count; },
  }, () => assert.match(binaryHash(root, { maxEntries: 4 }), /^[a-f0-9]{64}$/));
  assert.equal(observations, 2); assert.equal(consumed, 7); assert.throws(() => fs.fstatSync(selected), { code: 'EBADF' });
});

test('bundle membership changing during enumeration is refused rather than silently omitted', (t) => {
  const value = fixture(t);
  const bundle = path.join(value.dir, 'App.app');
  fs.mkdirSync(bundle); fs.writeFileSync(path.join(bundle, 'original'), 'original');
  let added = false;
  withFs({ opendirSync: (original, file, ...args) => {
    const directory = original(file, ...args);
    return { readSync() { const entry = directory.readSync();
      if (!entry && file === bundle && !added) { added = true; fs.writeFileSync(path.join(bundle, 'new'), 'unreviewed'); }
      return entry; }, closeSync: () => directory.closeSync() };
  } }, () => assert.throws(() => binaryHash(bundle), /BINARY_DIRECTORY_CHANGED/));
  assert.equal(added, true);
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
