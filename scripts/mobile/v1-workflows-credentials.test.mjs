import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { readV1Member } from '../../apps/mobile/e2e/v1-workflows-credentials.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const SYNTHETIC = Buffer.from('{"synthetic":true,"member":"public-unit-fixture"}\n');

function fixture(t, bytes = SYNTHETIC, mode = 0o600) {
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-v1-member-')));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'synthetic-member.json');
  fs.writeFileSync(file, bytes, { mode, flag: 'wx' });
  fs.chmodSync(file, mode);
  return { dir, file, bytes };
}

function observedIo(overrides = {}) {
  const opened = [], closed = [], reads = [], flags = [];
  const io = {
    lstatSync: fs.lstatSync,
    realpathSync: fs.realpathSync,
    fstatSync: fs.fstatSync,
    openSync(file, value) {
      flags.push(value);
      const fd = fs.openSync(file, value); opened.push(fd); return fd;
    },
    readSync(fd, buffer, offset, length, position) {
      reads.push({ fd, length }); return fs.readSync(fd, buffer, offset, length, position);
    },
    closeSync(fd) { closed.push(fd); fs.closeSync(fd); },
    ...overrides,
  };
  return { io, opened, closed, reads, flags };
}

function changed(stat, updates) {
  return new Proxy(stat, { get(target, key) {
    return Object.hasOwn(updates, key) ? updates[key] : Reflect.get(target, key);
  } });
}

function refuses(file, observed, code) {
  assert.throws(() => readV1Member(file, observed.io), error => error.message === code);
  assert.deepEqual(observed.closed, observed.opened, 'every actually opened descriptor closes once');
}

test('private regular member returns retained exact bytes/value/hash through one checked descriptor', t => {
  const value = fixture(t), observed = observedIo();
  const result = readV1Member(value.file, observed.io);
  assert.deepEqual(result, { bytes: SYNTHETIC, value: JSON.parse(SYNTHETIC), sha256: sha(SYNTHETIC), uid: process.getuid() });
  assert.equal(observed.opened.length, 1);
  assert.deepEqual(observed.closed, observed.opened);
  assert.ok(observed.reads.length > 0 && observed.reads.every(read => read.fd === observed.opened[0]));
  assert.equal(observed.flags[0], fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
  fs.writeFileSync(value.file, '{"replacedAfterReturn":true}');
  assert.deepEqual(result.bytes, SYNTHETIC);
});

test('owner-read-only mode is admitted; group/other/execute or special permissions are refused', t => {
  const value = fixture(t, SYNTHETIC, 0o400);
  assert.equal(readV1Member(value.file).sha256, sha(SYNTHETIC));
  for (const mode of [0o644, 0o640, 0o620, 0o700, 0o4600]) {
    fs.chmodSync(value.file, mode);
    const observed = observedIo(); refuses(value.file, observed, 'V1_MEMBER_FILE_REQUIRED');
    assert.equal(observed.reads.length, 0);
  }
});

test('the exact 16 KiB JSON boundary is retained without reading past the single-byte sentinel', t => {
  const bytes = Buffer.from(JSON.stringify({ pad: 'x'.repeat(16384 - Buffer.byteLength('{"pad":""}')) }));
  assert.equal(bytes.length, 16384);
  const value = fixture(t, bytes), observed = observedIo();
  const result = readV1Member(value.file, observed.io);
  assert.deepEqual(result.bytes, bytes); assert.equal(result.sha256, sha(bytes));
  assert.ok(observed.reads.every(read => read.length <= 16385));
  assert.deepEqual(observed.closed, observed.opened);
});

test('relative/noncanonical paths and symlink aliases refuse before opening or reading', t => {
  const value = fixture(t);
  const alias = path.join(value.dir, 'alias'); fs.symlinkSync(value.file, alias);
  const parentAlias = path.join(value.dir, 'parent-alias'); fs.symlinkSync(value.dir, parentAlias);
  for (const file of ['relative-member.json', `${value.dir}/./synthetic-member.json`, alias,
    path.join(parentAlias, 'synthetic-member.json')]) {
    const observed = observedIo(); refuses(file, observed, 'V1_MEMBER_FILE_REQUIRED');
    assert.equal(observed.opened.length, 0); assert.equal(observed.reads.length, 0);
  }
});

test('directory, empty, oversized and multiple-linked files refuse without consuming bytes', t => {
  const value = fixture(t);
  const hardlink = path.join(value.dir, 'hardlink'); fs.linkSync(value.file, hardlink);
  let observed = observedIo(); refuses(value.file, observed, 'V1_MEMBER_FILE_REQUIRED');
  assert.equal(observed.reads.length, 0); fs.unlinkSync(hardlink);
  for (const bytes of [Buffer.alloc(0), Buffer.alloc(16385, 0x20)]) {
    fs.writeFileSync(value.file, bytes); observed = observedIo();
    refuses(value.file, observed, 'V1_MEMBER_FILE_REQUIRED'); assert.equal(observed.reads.length, 0);
  }
  observed = observedIo(); refuses(value.dir, observed, 'V1_MEMBER_FILE_REQUIRED');
});

test('foreign UID metadata refuses before any credential bytes are read', t => {
  const value = fixture(t);
  const observed = observedIo({ lstatSync(file, options) {
    const stat = fs.lstatSync(file, options); return changed(stat, { uid: stat.uid + 1n });
  } });
  if (typeof process.getuid === 'function') {
    refuses(value.file, observed, 'V1_MEMBER_FILE_REQUIRED');
    assert.equal(observed.reads.length, 0);
  } else {
    // This metadata control does not claim an independently verified Windows ACL.
    refuses(value.file, observed, 'V1_MEMBER_FILE_CHANGED');
  }
});

test('growth after accepted fstat consumes at most 16 KiB+1, refuses and closes the same descriptor', t => {
  const value = fixture(t); let stats = 0;
  const observed = observedIo({ fstatSync(fd, options) {
    const stat = fs.fstatSync(fd, options);
    if (++stats === 1) fs.appendFileSync(value.file, Buffer.alloc(131072, 0x20));
    return stat;
  } });
  refuses(value.file, observed, 'V1_MEMBER_FILE_CHANGED');
  assert.equal(observed.opened.length, 1);
  assert.equal(observed.reads.reduce((sum, read) => sum + read.length, 0), 16385);
  assert.equal(fs.statSync(value.file).size, SYNTHETIC.length + 131072);
});

test('path replacement between named check and open refuses before read, with descriptor closure', t => {
  const value = fixture(t); const replacement = path.join(value.dir, 'replacement');
  fs.writeFileSync(replacement, SYNTHETIC, { mode: 0o600 });
  const observed = observedIo(); const open = observed.io.openSync;
  observed.io.openSync = (file, flags) => { fs.renameSync(replacement, file); return open(file, flags); };
  refuses(value.file, observed, 'V1_MEMBER_FILE_CHANGED');
  assert.equal(observed.opened.length, 1); assert.equal(observed.reads.length, 0);
});

test('replacement after reading cannot substitute a different final namespace identity', t => {
  const value = fixture(t); const replacement = path.join(value.dir, 'replacement');
  fs.writeFileSync(replacement, SYNTHETIC, { mode: 0o600 }); let named = 0;
  const observed = observedIo({ lstatSync(file, options) {
    if (++named === 2) fs.renameSync(replacement, file);
    return fs.lstatSync(file, options);
  } });
  refuses(value.file, observed, 'V1_MEMBER_FILE_CHANGED');
  assert.equal(observed.opened.length, 1);
});

test('final descriptor and named metadata include UID/GID/mode/link/time/inode/size/device checks', t => {
  const value = fixture(t);
  for (const key of ['uid', 'gid', 'mode', 'nlink', 'mtimeNs', 'ctimeNs', 'ino', 'size', 'dev']) {
    let stats = 0;
    const observed = observedIo({ fstatSync(fd, options) {
      const stat = fs.fstatSync(fd, options);
      return ++stats === 2 ? changed(stat, { [key]: stat[key] + 1n }) : stat;
    } });
    refuses(value.file, observed, 'V1_MEMBER_FILE_CHANGED');
    let named = 0;
    const namedObserved = observedIo({ lstatSync(file, options) {
      const stat = fs.lstatSync(file, options);
      return ++named === 2 ? changed(stat, { [key]: stat[key] + 1n }) : stat;
    } });
    refuses(value.file, namedObserved, 'V1_MEMBER_FILE_CHANGED');
  }
});

test('Windows named dev normalization preserves exact descriptor dev/inode and every other metadata field', t => {
  const value = fixture(t), descriptor = Object.getOwnPropertyDescriptor(process, 'platform');
  Object.defineProperty(process, 'platform', { ...descriptor, value: 'win32' });
  try {
    const observed = observedIo({ lstatSync(file, options) {
      return changed(fs.lstatSync(file, options), { dev: 0n });
    } });
    assert.equal(readV1Member(value.file, observed.io).sha256, sha(SYNTHETIC));
    assert.deepEqual(observed.closed, observed.opened);
    let stats = 0;
    const drift = observedIo({
      lstatSync(file, options) { return changed(fs.lstatSync(file, options), { dev: 0n }); },
      fstatSync(fd, options) {
        const stat = fs.fstatSync(fd, options);
        return ++stats === 2 ? changed(stat, { dev: stat.dev + 1n }) : stat;
      },
    });
    refuses(value.file, drift, 'V1_MEMBER_FILE_CHANGED');
  } finally { Object.defineProperty(process, 'platform', descriptor); }
});

test('read/metadata/final-path failures close once and expose only a fixed safe code', t => {
  const value = fixture(t);
  for (const stage of ['fstatSync', 'readSync', 'final-lstat', 'final-realpath']) {
    const observed = observedIo(); let calls = 0;
    const method = stage === 'final-lstat' ? 'lstatSync' : stage === 'final-realpath' ? 'realpathSync' : stage;
    const original = observed.io[method];
    observed.io[method] = (...args) => {
      if (++calls === (stage.startsWith('final-') ? 2 : 1)) throw new Error('PRIVATE_SYNTHETIC_ERROR_MARKER');
      return original(...args);
    };
    refuses(value.file, observed, 'V1_MEMBER_READ_FAILED');
    assert.equal(observed.opened.length, 1);
  }
});

test('malformed JSON, invalid UTF8 and non-object roots never reflect submitted bytes', t => {
  for (const bytes of [Buffer.from('{"PRIVATE_SYNTHETIC_MARKER":broken}'), Buffer.from([0xff]),
    Buffer.from('null'), Buffer.from('[]'), Buffer.from('"PRIVATE_SYNTHETIC_MARKER"')]) {
    const value = fixture(t, bytes), observed = observedIo();
    refuses(value.file, observed, 'V1_MEMBER_JSON_REQUIRED');
  }
});

test('a close error rejects admission after one close attempt, without leaking IO details', t => {
  const value = fixture(t), observed = observedIo(); const close = observed.io.closeSync;
  observed.io.closeSync = fd => { close(fd); throw new Error('PRIVATE_CLOSE_DETAIL'); };
  refuses(value.file, observed, 'V1_MEMBER_CLOSE_FAILED');
  assert.equal(observed.closed.length, 1);
});

test('short descriptor reads assemble all bytes; malformed read counts cannot loop or overrun', t => {
  const value = fixture(t); const observed = observedIo(); const read = observed.io.readSync;
  observed.io.readSync = (fd, buffer, offset, length, position) => read(fd, buffer, offset, Math.min(3, length), position);
  assert.deepEqual(readV1Member(value.file, observed.io).bytes, SYNTHETIC);
  assert.deepEqual(observed.closed, observed.opened);
  for (const count of [-1, 0.5, 16386, NaN]) {
    const invalid = observedIo({ readSync() { return count; } });
    refuses(value.file, invalid, 'V1_MEMBER_READ_FAILED');
  }
});
