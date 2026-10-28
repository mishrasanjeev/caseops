import assert from 'node:assert/strict';
import { appendFileSync, closeSync, fstatSync, linkSync, mkdirSync, mkdtempSync, openSync, readSync, realpathSync,
  renameSync, rmSync, statSync, symlinkSync, truncateSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { spawnSync } from 'node:child_process';
import { assertCameraCopiesRemoved, CAMERA_PRIVACY_LIMITS, observeIosCameraDirectory } from './camera-files-privacy.mjs';

const NAME = '11111111-2222-4333-8444-555555555555.jpg';
const SECOND = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.png';
function fixture(t, present = true) {
  const base = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'camera-privacy-source-')));
  const app = path.join(base, 'app'), root = path.join(app, 'Library/Caches/ImagePicker');
  mkdirSync(present ? root : app, { recursive: true });
  t.after(() => rmSync(base, { force: true, recursive: true }));
  return { base, app, root, image: path.join(root, NAME) };
}

function descriptorProbe(t, mode) {
  const f = fixture(t); writeFileSync(f.image, 'stable-synthetic-copy');
  // A separate process keeps the builtin instrumentation local to this real
  // filesystem control; no shared ESM bindings or other tests are patched.
  const source = String.raw`
    import fs from 'node:fs';
    import { syncBuiltinESMExports } from 'node:module';
    const q = JSON.parse(fs.readFileSync(0, 'utf8'));
    const open = fs.openSync, lstat = fs.lstatSync, fstat = fs.fstatSync;
    let descriptor, changed = false, reads = 0; const events = [];
    fs.openSync = function(file, ...args) {
      const fd = open(file, ...args);
      if (file === q.image) { descriptor = fd; events.push('open'); }
      return fd;
    };
    fs.lstatSync = function(file, ...args) {
      if (file === q.image) events.push('named');
      return lstat(file, ...args);
    };
    fs.fstatSync = function(fd, ...args) {
      const value = fstat(fd, ...args);
      if (fd === descriptor) {
        events.push('descriptor');
        if (q.mode === 'replace' && !changed) {
          changed = true; fs.renameSync(q.image, q.saved);
          fs.writeFileSync(q.image, 'replacement-current-leaf');
        }
      }
      return value;
    };
    syncBuiltinESMExports();
    const { observeIosCameraDirectory } = await import(q.module);
    const value = observeIosCameraDirectory(q.app, { readChunk(fd, ...args) {
      events.push('body'); reads++; return fs.readSync(fd, ...args);
    } });
    let closed = false;
    try { fstat(descriptor); } catch (error) { closed = error.code === 'EBADF'; }
    process.stdout.write(JSON.stringify({ value, events, reads, changed, closed }));
  `;
  const child = spawnSync(process.execPath, ['--input-type=module', '-e', source], {
    input: JSON.stringify({ mode, app: f.app, image: f.image, saved: path.join(f.base, 'retained-copy'),
      module: new URL('./camera-files-privacy.mjs', import.meta.url).href }),
    encoding: 'utf8', timeout: 5000, maxBuffer: 65536,
  });
  assert.equal(child.error, undefined); assert.equal(child.status, 0); assert.equal(child.stderr, '');
  return JSON.parse(child.stdout);
}

test('the opened descriptor is admitted before its named camera leaf and body', t => {
  const value = descriptorProbe(t, 'stable');
  assert.deepEqual(value.events.slice(0, 3), ['open', 'descriptor', 'named']);
  assert.ok(value.events.indexOf('body') > value.events.indexOf('named'));
  assert.equal(value.value.complete, true); assert.equal(value.value.counts.copies, 1);
  assert.equal(value.value.counts.bytesRead, Buffer.byteLength('stable-synthetic-copy'));
  assert.equal(value.closed, true);
});

test('actual leaf replacement after descriptor opening refuses before any body read and closes it', t => {
  const value = descriptorProbe(t, 'replace');
  assert.equal(value.changed, true); assert.equal(value.reads, 0);
  assert.equal(value.value.counts.bytesRead, 0); assert.equal(value.value.complete, false);
  assert.equal(value.value.copies.length, 0); assert.equal(value.closed, true);
});

test('absent or empty exact SDK directory has its own charged zero-copy scope', t => {
  for (const present of [false, true]) {
    const f = fixture(t, present), value = observeIosCameraDirectory(f.app);
    assert.equal(value.complete, true); assert.equal(value.directoryPresent, present);
    assert.equal(value.counts.copies, 0); assert.ok(value.counts.entries > 0);
    assert.equal(value.providerOriginalsRead, false); assert.equal(value.legacyKnownFixtureCountsIncluded, false);
    assert.equal(assertCameraCopiesRemoved(value).status, 'passed');
  }
  assert.throws(() => assertCameraCopiesRemoved({ kind: 'ios-files-privacy-snapshot', complete: true, counts: { copies: 0 } }), /CAMERA_SDK_OBSERVATION_REQUIRED/);
});

test('previously unknown UUID camera bytes are counted independently without recording media or encoded metadata', t => {
  const f = fixture(t), body = 'SYNTHETIC_CAMERA_BODY_NOT_PUBLIC_IN_REPORT'; writeFileSync(f.image, body);
  const value = observeIosCameraDirectory(f.app);
  assert.equal(value.complete, true); assert.equal(value.counts.copies, 1); assert.equal(value.copies.length, 1);
  assert.equal(value.counts.bytesRead, Buffer.byteLength(body));
  assert.equal(value.copies[0].classification, 'owned-camera-sdk-copy');
  assert.equal(value.encodedMetadataInspected, false); assert.equal(value.physicalCameraAcceptance, false);
  assert.equal(JSON.stringify(value).includes(body), false); assert.equal(JSON.stringify(value).includes(NAME), false);
  assert.throws(() => assertCameraCopiesRemoved(value), /OWNED_CAMERA_SDK_COPY_REMAINS/);
});

test('unreviewed names, nested directories, symlinks and hard links cannot become a clean owned SDK result', t => {
  for (const kind of ['name', 'directory', 'symlink', 'hardlink']) {
    const f = fixture(t), outside = path.join(f.base, 'retained-original'); writeFileSync(outside, 'ORIGINAL_UNCHANGED');
    if (kind === 'name') writeFileSync(path.join(f.root, 'unreviewed-private-name'), 'unreviewed');
    if (kind === 'directory') mkdirSync(f.image);
    if (kind === 'symlink') symlinkSync(outside, f.image);
    if (kind === 'hardlink') linkSync(outside, f.image);
    const value = observeIosCameraDirectory(f.app);
    assert.equal(value.complete, false); assert.equal(value.counts.copies, 1); assert.equal(value.copies.length, 0);
    assert.equal(JSON.stringify(value).includes('unreviewed-private-name'), false);
    assert.throws(() => assertCameraCopiesRemoved(value), /COMPLETE_CAMERA_SDK_OBSERVATION_REQUIRED/);
  }
});

test('same-descriptor growth fails final identity and closes the admitted descriptor', t => {
  const f = fixture(t); writeFileSync(f.image, 'synthetic-before'); let descriptor, reads = 0;
  const value = observeIosCameraDirectory(f.app, { readChunk(fd, ...args) {
    descriptor = fd;
    if (++reads === 1) appendFileSync(f.image, 'late-growth');
    return readSync(fd, ...args);
  } });
  assert.equal(value.complete, false); assert.equal(value.copies.length, 0); assert.ok(reads > 0);
  assert.throws(() => fstatSync(descriptor), /EBADF/);
});

test('actual sparse growth after stat consumes at most the fixed limit plus one byte and closes the descriptor', t => {
  const f = fixture(t); writeFileSync(f.image, 'x'); let descriptor, consumed = 0, once = false;
  const value = observeIosCameraDirectory(f.app, { readChunk(fd, ...args) {
    descriptor = fd;
    if (!once) { once = true; truncateSync(f.image, CAMERA_PRIVACY_LIMITS.fileBytes + 4096); }
    const count = readSync(fd, ...args); consumed += count; return count;
  } });
  assert.equal(value.complete, false); assert.equal(value.copies.length, 0);
  assert.equal(consumed, CAMERA_PRIVACY_LIMITS.fileBytes + 1);
  assert.equal(value.counts.bytesRead, consumed); assert.throws(() => fstatSync(descriptor), /EBADF/);
});

test('later sparse growth is also bounded by aggregate room plus one byte with descriptor closure', t => {
  const f = fixture(t); writeFileSync(f.image, 'x'); truncateSync(f.image, 17 * 1024 * 1024 + 17);
  const second = path.join(f.root, SECOND); writeFileSync(second, 'y'); const secondInode = statSync(second).ino;
  let consumed = 0, grown = false, descriptor;
  const value = observeIosCameraDirectory(f.app, { readChunk(fd, ...args) {
    descriptor = fd;
    if (!grown && fstatSync(fd).ino === secondInode) { grown = true; truncateSync(second, CAMERA_PRIVACY_LIMITS.fileBytes + 4096); }
    const count = readSync(fd, ...args); consumed += count; return count;
  } });
  assert.equal(value.complete, false); assert.equal(value.counts.bytesRead, consumed);
  assert.equal(consumed, CAMERA_PRIVACY_LIMITS.totalBytes + 1);
  assert.throws(() => fstatSync(descriptor), /EBADF/);
});

test('late parent rename plus symlink to the same inode fails final canonical namespace', t => {
  const f = fixture(t); writeFileSync(f.image, 'synthetic'); let once = false, descriptor;
  const value = observeIosCameraDirectory(f.app, { readChunk(fd, ...args) {
    descriptor = fd;
    if (!once) { once = true; renameSync(f.root, `${f.root}-retained`); symlinkSync(`${f.root}-retained`, f.root); }
    return readSync(fd, ...args);
  } });
  assert.equal(value.complete, false); assert.ok(value.issues.some(item => item.reason === 'camera-final-namespace-changed'));
  assert.throws(() => fstatSync(descriptor), /EBADF/);
});

test('unrelated entries outside the owned app do not weaken canonical ancestor identity or invalidate its SDK inventory', t => {
  const f = fixture(t); writeFileSync(f.image, 'synthetic'); let once = false;
  const value = observeIosCameraDirectory(f.app, { readChunk(fd, ...args) {
    if (!once) { once = true; mkdirSync(path.join(f.base, 'unrelated-owned-test-sibling')); }
    return readSync(fd, ...args);
  } });
  assert.equal(value.complete, true); assert.equal(value.counts.copies, 1);
});

test('a copy inserted after the initial inventory is charged by the final observation and refuses absence', t => {
  const f = fixture(t); writeFileSync(f.image, 'synthetic'); let once = false;
  const value = observeIosCameraDirectory(f.app, { readChunk(fd, ...args) {
    if (!once) { once = true; writeFileSync(path.join(f.root, SECOND), 'late-copy'); }
    return readSync(fd, ...args);
  } });
  assert.equal(value.complete, false); assert.equal(value.inventory.initialCount, 1); assert.equal(value.inventory.finalCount, 2);
  assert.ok(value.counts.entries >= 3);
});

test('byte and directory bounds refuse before reading an oversized or excess camera copy', t => {
  const large = fixture(t), fd = openSync(large.image, 'w'); closeSync(fd);
  truncateSync(large.image, CAMERA_PRIVACY_LIMITS.fileBytes + 1);
  let reads = 0;
  const value = observeIosCameraDirectory(large.app, { readChunk() { reads++; throw Error('must not read'); } });
  assert.equal(value.complete, false); assert.equal(reads, 0); assert.equal(value.counts.bytesRead, 0);
  const many = fixture(t);
  for (let index = 0; index <= CAMERA_PRIVACY_LIMITS.copies; index++)
    writeFileSync(path.join(many.root, `${index.toString(16).padStart(8, '0')}-2222-4333-8444-555555555555.jpg`), 'x');
  assert.equal(observeIosCameraDirectory(many.app).complete, false);
});
