import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from 'node:fs';
import path from 'node:path';

const fileFields = ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs', 'uid', 'gid', 'mode', 'nlink'];
// Shared ancestors may legitimately acquire siblings while evidence is read.
// Their identity, ownership and permissions must remain the same.
const directoryFields = ['dev', 'ino', 'uid', 'gid', 'mode'];
const same = (left, right, fields) => fields.every(key => left[key] === right[key]);
const systemIo = () => ({ closeSync, fstatSync, lstatSync, openSync, readSync, realpathSync,
  platform: process.platform, uid: process.getuid?.() });

function namedMatchesOpened(named, opened, platform) {
  return named.isFile() && !named.isSymbolicLink()
    && fileFields.every(key => (key === 'dev' && platform === 'win32' && named.dev === 0n) || named[key] === opened[key]);
}
function namespace(file, io) {
  const result = [];
  for (let directory = path.dirname(file); ; directory = path.dirname(directory)) {
    const stat = io.lstatSync(directory, { bigint: true });
    assert.ok(stat.isDirectory() && !stat.isSymbolicLink(), 'FIXTURE_EVIDENCE_NAMESPACE_CHANGED');
    result.push({ directory, stat });
    if (path.dirname(directory) === directory) return result;
  }
}

// The optional I/O adapter is for filesystem regressions only. Runtime callers
// use the three-argument verifiedFile API; no fixture supplies this adapter.
export function verifiedFileWithIo(file, expected, maxBytes = 1048576, adapter = {}) {
  const io = { ...systemIo(), ...adapter };
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_FIXTURE_EVIDENCE_REQUIRED');
  assert.match(expected || '', /^[a-f0-9]{64}$/, 'FIXTURE_EVIDENCE_SHA_REQUIRED');
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0, 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
  const fd = io.openSync(file, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  try {
    const opened = io.fstatSync(fd, { bigint: true });
    assert.ok(opened.isFile() && opened.size > 0n && opened.size <= BigInt(maxBytes), 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
    assert.ok(opened.nlink === 1n && opened.uid >= 0n
      && (io.uid === undefined ? io.platform === 'win32' : opened.uid === BigInt(io.uid)), 'FIXTURE_EVIDENCE_OWNER_REQUIRED');
    const named = io.lstatSync(file, { bigint: true });
    assert.ok(namedMatchesOpened(named, opened, io.platform), 'FIXTURE_EVIDENCE_REPLACED');
    // Resolve after opening: an existing OS alias such as /var is supported,
    // while any subsequent change to that mapping or its canonical parents is refused.
    const canonical = io.realpathSync(file);
    const parents = namespace(canonical, io);
    const canonicalNamed = io.lstatSync(canonical, { bigint: true });
    assert.ok(namedMatchesOpened(canonicalNamed, opened, io.platform), 'FIXTURE_EVIDENCE_REPLACED');
    const limit = Math.min(Number(opened.size) + 1, maxBytes + 1);
    const chunks = [];
    let length = 0;
    while (length < limit) {
      const chunk = Buffer.alloc(Math.min(65536, limit - length));
      const count = io.readSync(fd, chunk, 0, chunk.length, length);
      assert.ok(Number.isSafeInteger(count) && count >= 0 && count <= chunk.length, 'FIXTURE_EVIDENCE_READ_REFUSED');
      if (count === 0) break;
      chunks.push(chunk.subarray(0, count));
      length += count;
    }
    assert.ok(length <= maxBytes && BigInt(length) === opened.size, 'FIXTURE_EVIDENCE_CHANGED');
    const after = io.fstatSync(fd, { bigint: true });
    const namedAfter = io.lstatSync(file, { bigint: true });
    const canonicalAfter = io.lstatSync(canonical, { bigint: true });
    assert.ok(same(opened, after, fileFields), 'FIXTURE_EVIDENCE_CHANGED');
    assert.ok(same(named, namedAfter, fileFields) && same(canonicalNamed, canonicalAfter, fileFields)
      && namedMatchesOpened(namedAfter, after, io.platform) && namedMatchesOpened(canonicalAfter, after, io.platform), 'FIXTURE_EVIDENCE_REPLACED');
    assert.equal(io.realpathSync(file), canonical, 'FIXTURE_EVIDENCE_NAMESPACE_CHANGED');
    const finalParents = namespace(canonical, io);
    assert.ok(parents.length === finalParents.length && parents.every((row, index) => row.directory === finalParents[index].directory
      && same(row.stat, finalParents[index].stat, directoryFields)), 'FIXTURE_EVIDENCE_NAMESPACE_CHANGED');
    const bytes = Buffer.concat(chunks, length);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expected, 'FIXTURE_EVIDENCE_CHANGED');
    return bytes;
  } finally { io.closeSync(fd); }
}

export function verifiedFile(file, expected, maxBytes = 1048576) {
  return verifiedFileWithIo(file, expected, maxBytes);
}
