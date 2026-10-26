import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, lstatSync, openSync, readFileSync } from 'node:fs';
import path from 'node:path';

export function verifiedFile(file, expected, maxBytes = 1048576) {
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_FIXTURE_EVIDENCE_REQUIRED');
  assert.match(expected || '', /^[a-f0-9]{64}$/, 'FIXTURE_EVIDENCE_SHA_REQUIRED');
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0, 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
  const fd = openSync(file, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  let bytes;
  try {
    const opened = fstatSync(fd, { bigint: true });
    assert.ok(opened.isFile() && opened.size > 0n && opened.size <= BigInt(maxBytes), 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
    // Windows does not expose O_NOFOLLOW. Bind its pathname check to the
    // already-opened file, and read only that descriptor on every platform.
    const named = lstatSync(file, { bigint: true });
    assert.ok(named.isFile() && !named.isSymbolicLink() && named.ino === opened.ino
      && (process.platform === 'win32' || named.dev === opened.dev), 'FIXTURE_EVIDENCE_REPLACED');
    bytes = readFileSync(fd);
    const after = fstatSync(fd, { bigint: true });
    assert.ok(opened.size === after.size && opened.mtimeNs === after.mtimeNs && opened.ctimeNs === after.ctimeNs
      && BigInt(bytes.length) === opened.size, 'FIXTURE_EVIDENCE_CHANGED');
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expected, 'FIXTURE_EVIDENCE_CHANGED');
  } finally { closeSync(fd); }
  return bytes;
}
