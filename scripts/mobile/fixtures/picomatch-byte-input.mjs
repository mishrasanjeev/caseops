import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

// Keep matcher-only controls independent of Expo's installed SDK and runtime.
// Read these small, pinned fixture bytes through the checked descriptor.
export function readFixtureBytes(file, limit) {
  assert.ok(typeof file === 'string' && path.isAbsolute(file));
  assert.ok(Number.isSafeInteger(limit) && limit > 0 && limit <= 8388608);
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0));
  try {
    const before = fs.fstatSync(fd, { bigint: true });
    const named = fs.lstatSync(file, { bigint: true });
    const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs', 'birthtimeNs'];
    const frame = value => fields.map(key => String(value[key]));
    assert.ok(before.isFile() && named.isFile() && !named.isSymbolicLink() && before.nlink === 1n);
    for (const key of ['ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'birthtimeNs'])
      assert.equal(before[key], named[key]);
    if (!(process.platform === 'win32' && named.dev === 0n)) assert.equal(before.dev, named.dev);
    assert.ok(before.size >= 0n && before.size <= BigInt(limit));
    const bytes = Buffer.alloc(Number(before.size) + 1);
    let offset = 0;
    while (offset < bytes.length) {
      const count = fs.readSync(fd, bytes, offset, bytes.length - offset, offset);
      if (!count) break;
      offset += count;
    }
    assert.equal(offset, Number(before.size));
    assert.deepEqual(frame(fs.fstatSync(fd, { bigint: true })), frame(before));
    assert.deepEqual(frame(fs.lstatSync(file, { bigint: true })), frame(named));
    return bytes.subarray(0, offset);
  } finally { fs.closeSync(fd); }
}
