'use strict';
// Server/build-only: never import this descriptor reader in a client bundle.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { validateNativeLinkConfig, nativeLinkProjections } = require('./native-link-policy.cjs');
const metadataKeys = ['ino', 'size', 'mode', 'uid', 'gid', 'nlink', 'mtimeNs', 'ctimeNs'];
function sameMetadata(a, b, named = false) {
  // Windows lstat.dev may be zero while fstat.dev identifies its volume. Keep
  // the inode and complete metadata checks; compare like descriptor stats fully.
  return metadataKeys.every(key => a[key] === b[key])
    && (named && process.platform === 'win32' || a.dev === b.dev);
}
function readNativeLinkConfig(env, { allowSynthetic = false } = {}) {
  const file = env.CASEOPS_NATIVE_LINK_CONFIG_FILE, expected = env.CASEOPS_NATIVE_LINK_CONFIG_SHA256;
  if (typeof file !== 'string' || !path.isAbsolute(file) || !/^[a-f0-9]{64}$/.test(expected || '')) throw new Error('IMMUTABLE_NATIVE_LINK_CONFIG_REQUIRED');
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0));
  try {
    const opened = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    if (!opened.isFile() || opened.size < 1n || opened.size > 16384n || !named.isFile() || named.isSymbolicLink()
      || !sameMetadata(opened, named, true)) throw new Error('NATIVE_LINK_CONFIG_FILE_IDENTITY_REQUIRED');
    // A size check before readFileSync does not bound allocation if the file
    // grows. Consume at most the existing 16 KiB limit plus one detection byte.
    const buffer = Buffer.alloc(16385);
    let count = 0;
    while (count < buffer.length) {
      const length = fs.readSync(fd, buffer, count, buffer.length - count, null);
      if (!length) break;
      count += length;
    }
    if (count > 16384) throw new Error('NATIVE_LINK_CONFIG_SIZE_BOUND');
    const bytes = buffer.subarray(0, count), after = fs.fstatSync(fd, { bigint: true });
    const finalNamed = fs.lstatSync(file, { bigint: true });
    if (!after.isFile() || !finalNamed.isFile() || finalNamed.isSymbolicLink()
      || !sameMetadata(opened, after) || !sameMetadata(named, finalNamed)
      || !sameMetadata(after, finalNamed, true) || BigInt(bytes.length) !== opened.size) throw new Error('NATIVE_LINK_CONFIG_CHANGED');
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    if (sha256 !== expected) throw new Error('NATIVE_LINK_CONFIG_HASH_MISMATCH');
    let decoded;
    try { decoded = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
    catch { throw new Error('NATIVE_LINK_CONFIG_JSON_REQUIRED'); }
    const config = validateNativeLinkConfig(decoded);
    if (config.syntheticDataOnly && !allowSynthetic) throw new Error('SYNTHETIC_NATIVE_LINK_CONFIG_FORBIDDEN');
    return { config, sha256, bytes, projections: nativeLinkProjections(config, sha256) };
  } finally { fs.closeSync(fd); }
}
module.exports = { readNativeLinkConfig };
