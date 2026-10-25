import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { closeSync, fstatSync, lstatSync, openSync, readFileSync } from 'node:fs';
import path from 'node:path';

export function verifiedFile(file, expected, maxBytes = 1048576) {
  assert.ok(path.isAbsolute(file || ''), 'ABSOLUTE_FIXTURE_EVIDENCE_REQUIRED');
  assert.match(expected || '', /^[a-f0-9]{64}$/, 'FIXTURE_EVIDENCE_SHA_REQUIRED');
  const before = lstatSync(file);
  assert.ok(before.isFile() && !before.isSymbolicLink(), 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
  const fd = openSync(file, 'r');
  let bytes;
  try {
    const opened = fstatSync(fd);
    assert.ok(opened.isFile() && opened.size > 0 && opened.size <= maxBytes, 'BOUNDED_FIXTURE_EVIDENCE_REQUIRED');
    assert.ok(before.dev === opened.dev && before.ino === opened.ino, 'FIXTURE_EVIDENCE_REPLACED');
    bytes = readFileSync(fd);
    const after = fstatSync(fd);
    assert.ok(opened.size === after.size && opened.mtimeMs === after.mtimeMs && bytes.length === opened.size, 'FIXTURE_EVIDENCE_CHANGED');
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expected, 'FIXTURE_EVIDENCE_CHANGED');
  } finally { closeSync(fd); }
  return bytes;
}
