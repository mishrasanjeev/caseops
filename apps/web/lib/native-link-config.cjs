'use strict';
// Server/build-only: never import this descriptor reader in a client bundle.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { validateNativeLinkConfig, nativeLinkProjections } = require('./native-link-policy.cjs');
function readNativeLinkConfig(env, { allowSynthetic = false } = {}) {
  const file = env.CASEOPS_NATIVE_LINK_CONFIG_FILE, expected = env.CASEOPS_NATIVE_LINK_CONFIG_SHA256;
  if (typeof file !== 'string' || !path.isAbsolute(file) || !/^[a-f0-9]{64}$/.test(expected || '')) throw new Error('IMMUTABLE_NATIVE_LINK_CONFIG_REQUIRED');
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0));
  try {
    const opened = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    if (!opened.isFile() || opened.size < 1n || opened.size > 16384n || !named.isFile() || named.isSymbolicLink()
      || named.ino !== opened.ino || (process.platform !== 'win32' && named.dev !== opened.dev)) throw new Error('NATIVE_LINK_CONFIG_FILE_IDENTITY_REQUIRED');
    const bytes = fs.readFileSync(fd), after = fs.fstatSync(fd, { bigint: true });
    if (opened.size !== after.size || opened.mtimeNs !== after.mtimeNs || opened.ctimeNs !== after.ctimeNs || BigInt(bytes.length) !== opened.size) throw new Error('NATIVE_LINK_CONFIG_CHANGED');
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
