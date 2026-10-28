import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { verifiedFile, verifiedFileWithIo } from './evidence.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function fixture(t, text = 'owned evidence') {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-evidence-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const parent = path.join(dir, 'parent'); fs.mkdirSync(parent);
  const file = path.join(parent, 'input'); fs.writeFileSync(file, text, { mode: 0o600 });
  return { dir, parent, file, text, expected: hash(text) };
}
function instrument(overrides = {}) {
  const state = { descriptors: [], closed: [], bytes: 0, reads: 0, requested: [] };
  const io = {
    openSync(...args) { const fd = fs.openSync(...args); state.descriptors.push(fd); return fd; },
    closeSync(fd) { state.closed.push(fd); fs.closeSync(fd); },
    readSync(fd, buffer, offset, length, position) {
      state.reads++; state.requested.push(length);
      const count = fs.readSync(fd, buffer, offset, length, position); state.bytes += count; return count;
    }, ...overrides,
  };
  return { state, io, closed() { assert.deepEqual(state.closed, state.descriptors); for (const fd of state.descriptors) assert.throws(() => fs.fstatSync(fd), { code: 'EBADF' }); } };
}
function proxy(stat, fields) { return new Proxy(stat, { get(target, key) { return key in fields ? fields[key] : Reflect.get(target, key); } }); }

test('verified evidence retains exact descriptor bytes and supports partial reads without pathname reopening', t => {
  const f = fixture(t), proof = instrument();
  proof.io.readSync = (fd, buffer, offset, length, position) => {
    proof.state.reads++; const count = fs.readSync(fd, buffer, offset, Math.min(length, 2), position); proof.state.bytes += count; return count;
  };
  const bytes = verifiedFileWithIo(f.file, f.expected, 1024, proof.io);
  assert.deepEqual(bytes, Buffer.from(f.text)); assert.equal(proof.state.bytes, bytes.length); assert.ok(proof.state.reads > 2); proof.closed();
  assert.deepEqual(verifiedFile(f.file, f.expected), bytes);
});

test('actual growth after initial fstat consumes at most the observed size plus one and closes', t => {
  const f = fixture(t, 'original'), maximum = 16, proof = instrument(); let grew = false;
  proof.io.readSync = (fd, buffer, offset, length, position) => {
    if (!grew) { grew = true; fs.appendFileSync(f.file, Buffer.alloc(65536)); }
    proof.state.requested.push(length); const count = fs.readSync(fd, buffer, offset, length, position); proof.state.bytes += count; return count;
  };
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, maximum, proof.io), /CHANGED/);
  assert.equal(proof.state.bytes, Buffer.byteLength(f.text) + 1); assert.ok(proof.state.bytes <= maximum + 1); proof.closed();
});

test('growth at the caller maximum consumes only maximum plus one', t => {
  const f = fixture(t, 'x'.repeat(65536)), proof = instrument(); let grew = false;
  proof.io.readSync = (fd, buffer, offset, length, position) => {
    if (!grew) { grew = true; fs.appendFileSync(f.file, Buffer.alloc(65536)); }
    const count = fs.readSync(fd, buffer, offset, length, position); proof.state.bytes += count; return count;
  };
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 65536, proof.io), /CHANGED/);
  assert.equal(proof.state.bytes, 65537); proof.closed();
});

test('late parent rename and symlink to the same held inode is refused with descriptor closure', t => {
  const f = fixture(t), moved = path.join(f.dir, 'moved'), proof = instrument(); let changed = false;
  proof.io.readSync = (...args) => {
    if (!changed) { changed = true; fs.renameSync(f.parent, moved); fs.symlinkSync(moved, f.parent, process.platform === 'win32' ? 'junction' : 'dir'); }
    return fs.readSync(...args);
  };
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, proof.io), /NAMESPACE_CHANGED/); proof.closed();
});

test('replacement pathname cannot substitute equal-hash bytes for the held descriptor', t => {
  const f = fixture(t), proof = instrument(); let changed = false;
  proof.io.readSync = (...args) => {
    if (!changed) { changed = true; fs.renameSync(f.file, f.file + '.old'); fs.writeFileSync(f.file, f.text); }
    return fs.readSync(...args);
  };
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, proof.io), /CHANGED|REPLACED/); proof.closed();
});

test('existing canonical OS aliases resolve after opening and remain accepted', t => {
  const f = fixture(t), alias = path.join(f.dir, 'existing-alias');
  fs.symlinkSync(f.parent, alias, process.platform === 'win32' ? 'junction' : 'dir');
  assert.deepEqual(verifiedFile(path.join(alias, 'input'), f.expected), Buffer.from(f.text));
  // macOS os.tmpdir commonly supplies /var -> /private/var; retain that actual spelling too.
  const uncanonical = path.join(os.tmpdir(), path.basename(f.dir), 'parent', 'input');
  assert.deepEqual(verifiedFile(uncanonical, f.expected), Buffer.from(f.text));
});

test('empty, oversized, directory and symlink evidence refuse before descriptor bytes', t => {
  const f = fixture(t);
  for (const [file, max] of [[f.file, 1], [f.parent, 1024]]) {
    const proof = instrument(); assert.throws(() => verifiedFileWithIo(file, f.expected, max, proof.io)); assert.equal(proof.state.bytes, 0); proof.closed();
  }
  fs.writeFileSync(f.file, ''); const empty = instrument();
  assert.throws(() => verifiedFileWithIo(f.file, hash(''), 1024, empty.io), /BOUNDED/); assert.equal(empty.state.bytes, 0); empty.closed();
  fs.symlinkSync(f.file, f.file + '.link'); const link = instrument();
  assert.throws(() => verifiedFileWithIo(f.file + '.link', f.expected, 1024, link.io)); assert.equal(link.state.bytes, 0); link.closed();
});

test('hard-linked or foreign-owned evidence refuses before any descriptor byte', t => {
  const f = fixture(t); fs.linkSync(f.file, f.file + '.hard'); const hard = instrument();
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, hard.io), /OWNER/); assert.equal(hard.state.bytes, 0); hard.closed();
  fs.unlinkSync(f.file + '.hard'); const foreign = instrument({ uid: Number(fs.statSync(f.file).uid) + 1 });
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, foreign.io), /OWNER/); assert.equal(foreign.state.bytes, 0); foreign.closed();
});

test('read failure and every metadata checkpoint failure close the opened descriptor', t => {
  const f = fixture(t);
  const failing = instrument({ readSync() { throw new Error('SYNTHETIC_READ_FAILURE'); } });
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, failing.io), /SYNTHETIC_READ_FAILURE/); failing.closed();
  for (const method of ['fstatSync', 'lstatSync', 'realpathSync']) {
    const proof = instrument({ [method]() { throw new Error('SYNTHETIC_METADATA_FAILURE'); } });
    assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, proof.io), /SYNTHETIC_METADATA_FAILURE/); proof.closed();
  }
  const digest = instrument(); assert.throws(() => verifiedFileWithIo(f.file, '0'.repeat(64), 1024, digest.io), /CHANGED/); digest.closed();
});

test('all nine descriptor fields and all nine named fields stay exact across observations', t => {
  const f = fixture(t);
  for (const method of ['fstatSync', 'lstatSync']) for (const field of ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs', 'uid', 'gid', 'mode', 'nlink']) {
    let reads = 0;
    const proof = instrument({ [method](name, options) {
      const stat = fs[method](name, options);
      const target = method === 'fstatSync' || name === f.file;
      if (target && ++reads > (method === 'fstatSync' ? 1 : 2)) return proxy(stat, { [field]: stat[field] + 1n });
      return stat;
    } });
    assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, proof.io), /CHANGED|REPLACED/); proof.closed();
  }
});

test('simulated Windows named dev zero is portable while descriptor drift and other device mismatches refuse', t => {
  const f = fixture(t);
  const windows = () => instrument({ platform: 'win32', lstatSync(name, options) { const stat = fs.lstatSync(name, options); return name === f.file ? proxy(stat, { dev: 0n }) : stat; } });
  const positive = windows(); assert.equal(verifiedFileWithIo(f.file, f.expected, 1024, positive.io).toString(), f.text); positive.closed();
  const wrongDevice = instrument({ platform: 'win32', lstatSync(name, options) { const stat = fs.lstatSync(name, options); return name === f.file ? proxy(stat, { dev: stat.dev + 1n }) : stat; } });
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, wrongDevice.io), /REPLACED/); wrongDevice.closed();
  const drift = windows(); let observations = 0;
  drift.io.fstatSync = (fd, options) => { const stat = fs.fstatSync(fd, options); return ++observations > 1 ? proxy(stat, { dev: stat.dev + 1n }) : stat; };
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, drift.io), /CHANGED/); drift.closed();
});

test('canonical ancestor identity changes refuse but unrelated sibling timestamp changes do not', t => {
  const f = fixture(t), proof = instrument(); let read = false;
  proof.io.readSync = (...args) => { read = true; fs.writeFileSync(path.join(f.dir, 'sibling'), 'unrelated'); return fs.readSync(...args); };
  assert.equal(verifiedFileWithIo(f.file, f.expected, 1024, proof.io).toString(), f.text); proof.closed();
  const changed = instrument({ lstatSync(name, options) { const stat = fs.lstatSync(name, options); return read && name === f.parent ? proxy(stat, { gid: stat.gid + 1n }) : stat; } });
  read = false; changed.io.readSync = (...args) => { read = true; return fs.readSync(...args); };
  assert.throws(() => verifiedFileWithIo(f.file, f.expected, 1024, changed.io), /NAMESPACE_CHANGED/); changed.closed();
});
