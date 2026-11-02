'use strict';
// Build-only public descriptor. Never import this file into the native bundle.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const fail = name => { throw new Error(name); };
const same = (a, b, named = false) => fields.every(key => key === 'dev' && named && process.platform === 'win32' || a[key] === b[key]);
function namespace(file) {
  if (fs.realpathSync(file) !== file) fail('PRIVACY_POLICY_CANONICAL_NAMESPACE_REQUIRED');
  const rows = [];
  for (let parent = path.dirname(file); ; parent = path.dirname(parent)) {
    const s = fs.lstatSync(parent, { bigint: true });
    if (!s.isDirectory() || s.isSymbolicLink()) fail('PRIVACY_POLICY_CANONICAL_NAMESPACE_REQUIRED');
    rows.push([parent, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(s[key]))]);
    if (parent === path.dirname(parent)) break;
  }
  return JSON.stringify(rows);
}
function readPolicyBytes(file, expected) {
  if (typeof file !== 'string' || !path.isAbsolute(file) || path.resolve(file) !== file
    || typeof expected !== 'string' || !/^[a-f0-9]{64}$/.test(expected)) fail('IMMUTABLE_PRIVACY_POLICY_REFERENCE_REQUIRED');
  const deadline = performance.now() + 2000;
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0));
    const before = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    if (!before.isFile() || !named.isFile() || named.isSymbolicLink() || !same(before, named, true)
      || before.size < 1n || before.size > 16384n || before.nlink !== 1n
      || process.platform !== 'win32' && before.uid !== BigInt(process.getuid())) fail('PRIVACY_POLICY_OWNED_REGULAR_INPUT_REQUIRED');
    const parents = namespace(file), buffer = Buffer.alloc(16385);
    let count = 0;
    while (count < buffer.length) {
      if (performance.now() >= deadline) fail('PRIVACY_POLICY_READ_DEADLINE');
      const n = fs.readSync(fd, buffer, count, buffer.length - count, null);
      if (!n) break;
      count += n;
    }
    const final = fs.fstatSync(fd, { bigint: true }), finalNamed = fs.lstatSync(file, { bigint: true });
    if (count > 16384 || BigInt(count) !== before.size || !same(before, final)
      || !finalNamed.isFile() || finalNamed.isSymbolicLink() || !same(named, finalNamed)
      || !same(final, finalNamed, true) || namespace(file) !== parents || performance.now() >= deadline) fail('PRIVACY_POLICY_INPUT_CHANGED');
    const bytes = buffer.subarray(0, count);
    if (createHash('sha256').update(bytes).digest('hex') !== expected) fail('PRIVACY_POLICY_HASH_MISMATCH');
    return bytes;
  } catch (error) {
    if (typeof error.message === 'string' && /^(PRIVACY_POLICY_[A-Z_]+)$/.test(error.message)) throw error;
    fail('PRIVACY_POLICY_INPUT_UNAVAILABLE');
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
function exact(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
}
function policyUrl(value, origin) {
  try {
    if (typeof value !== 'string' || value.length > 2048 || !/^[\x21-\x7e]+$/.test(value) || value.includes('\\') || value.includes('?') || value.includes('#')) return false;
    const u = new URL(value), base = new URL(origin);
    return u.protocol === 'https:' && !u.port && !u.username && !u.password && !u.search && !u.hash
      && u.href === value && u.origin === origin && base.origin === origin && base.href === origin + '/';
  } catch { return false; }
}
function validatePrivacyPolicy(value, { links, webOrigin, sha256 }) {
  let approvedOrigin;
  try { approvedOrigin = new URL(links?.config?.redirectUri).origin; } catch { fail('EXACT_APPROVED_PRIVACY_POLICY_REQUIRED'); }
  if (!exact(value, ['schemaVersion', 'kind', 'nativeLinkConfigSha256', 'url', 'version'])
    || value.schemaVersion !== 1 || value.kind !== 'caseops-mobile-privacy-policy'
    || !links || value.nativeLinkConfigSha256 !== links.sha256
    || approvedOrigin !== webOrigin
    || !policyUrl(value.url, webOrigin) || typeof value.version !== 'string'
    || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value.version)
    || !/^[a-f0-9]{64}$/.test(sha256)) fail('EXACT_APPROVED_PRIVACY_POLICY_REQUIRED');
  return Object.freeze({ url: value.url, version: value.version, sha256 });
}
function parsePolicy(bytes) {
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes), value = JSON.parse(text), keys = new Set();
    // Flat descriptor only. Reject duplicate keys before assigning JSON meaning.
    let depth = 0, key = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') {
        const start = i++;
        while (i < text.length && text[i] !== '"') { if (text[i] === '\\') i++; i++; }
        if (depth === 1 && key) { const name = JSON.parse(text.slice(start, i + 1)); if (keys.has(name)) throw Error(); keys.add(name); key = false; }
      } else if (c === '{' || c === '[') { depth++; if (depth === 1) key = true; }
      else if (c === '}' || c === ']') depth--;
      else if (c === ',' && depth === 1) key = true;
    }
    return value;
  } catch { fail('PRIVACY_POLICY_JSON_REQUIRED'); }
}
function readPrivacyPolicySettings(env, { links, webOrigin, required = false }) {
  const file = env.CASEOPS_MOBILE_PRIVACY_POLICY_FILE, sha256 = env.CASEOPS_MOBILE_PRIVACY_POLICY_SHA256;
  if (file === undefined && sha256 === undefined) {
    if (required) fail('IMMUTABLE_PRIVACY_POLICY_REFERENCE_REQUIRED');
    return null;
  }
  return validatePrivacyPolicy(parsePolicy(readPolicyBytes(file, sha256)), { links, webOrigin, sha256 });
}
module.exports = { readPolicyBytes, policyUrl, validatePrivacyPolicy, readPrivacyPolicySettings };
