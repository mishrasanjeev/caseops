import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync } from 'node:fs';
import path from 'node:path';

const MAX_BYTES = 16384;
const nativeIo = { closeSync, fstatSync, lstatSync, openSync, readSync, realpathSync };
const codes = new Set([
  'V1_MEMBER_FILE_REQUIRED', 'V1_MEMBER_FILE_CHANGED', 'V1_MEMBER_JSON_REQUIRED',
  'V1_MEMBER_READ_FAILED', 'V1_MEMBER_CLOSE_FAILED',
]);
const fail = code => { throw new Error(code); };

function same(left, right, namedPath = false) {
  return ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs', 'mode', 'uid', 'gid', 'nlink']
    .every(key => key === 'dev' && namedPath && process.platform === 'win32'
      || left[key] === right[key]);
}

function privateRegular(value) {
  const mode = value.mode & 0o7777n;
  return value.isFile() && !value.isSymbolicLink() && value.nlink === 1n
    && (mode === 0o400n || mode === 0o600n)
    && (typeof process.getuid !== 'function' || value.uid === BigInt(process.getuid()));
}

/**
 * Read an admitted local member descriptor once, without exposing parse or IO
 * diagnostics. This is file admission only; callers must first admit the actual
 * source, binary, device and backend. POSIX modes do not prove Windows ACLs.
 * The second argument is the small synchronous IO seam used by offline tests.
 */
export function readV1Member(file, io = nativeIo) {
  let fd;
  let result;
  let failure;
  let buffer;
  try {
    if (typeof file !== 'string' || !path.isAbsolute(file) || path.normalize(file) !== file) {
      fail('V1_MEMBER_FILE_REQUIRED');
    }
    const named = io.lstatSync(file, { bigint: true });
    if (!privateRegular(named) || named.size <= 0n || named.size > BigInt(MAX_BYTES)
      || io.realpathSync(file) !== file) fail('V1_MEMBER_FILE_REQUIRED');
    fd = io.openSync(file, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
    const opened = io.fstatSync(fd, { bigint: true });
    if (!privateRegular(opened) || opened.size <= 0n || opened.size > BigInt(MAX_BYTES)) {
      fail('V1_MEMBER_FILE_REQUIRED');
    }
    if (!same(opened, named, true)) fail('V1_MEMBER_FILE_CHANGED');
    buffer = Buffer.alloc(MAX_BYTES + 1);
    let size = 0;
    while (size < buffer.length) {
      const remaining = buffer.length - size;
      const count = io.readSync(fd, buffer, size, remaining, null);
      if (!Number.isSafeInteger(count) || count < 0 || count > remaining) fail('V1_MEMBER_READ_FAILED');
      if (count === 0) break;
      size += count;
    }
    const after = io.fstatSync(fd, { bigint: true });
    const finalNamed = io.lstatSync(file, { bigint: true });
    if (size > MAX_BYTES || size !== Number(opened.size) || !same(opened, after)
      || !privateRegular(finalNamed) || !same(opened, finalNamed, true)
      || io.realpathSync(file) !== file) fail('V1_MEMBER_FILE_CHANGED');
    const bytes = Buffer.from(buffer.subarray(0, size));
    let value;
    try {
      value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    } catch {
      fail('V1_MEMBER_JSON_REQUIRED');
    }
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail('V1_MEMBER_JSON_REQUIRED');
    result = { bytes, value, sha256: createHash('sha256').update(bytes).digest('hex'), uid: Number(opened.uid) };
  } catch (error) {
    failure = new Error(codes.has(error?.message) ? error.message : 'V1_MEMBER_READ_FAILED');
  } finally {
    if (fd !== undefined) {
      try { io.closeSync(fd); }
      catch { failure ??= new Error('V1_MEMBER_CLOSE_FAILED'); }
    }
    buffer?.fill(0);
  }
  if (failure) throw failure;
  return result;
}
