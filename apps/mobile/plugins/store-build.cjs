'use strict';
// Build-only public metadata. A declared baseline is not an independent store read.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const fail = (message) => { throw new Error(message); };
function shape(value, keys, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).sort().join('\0') !== [...keys].sort().join('\0')) fail(name);
}
function reference(value) {
  shape(value, ['path', 'sha256'], 'EXACT_STORE_REFERENCE_REQUIRED');
  if (typeof value.path !== 'string' || !path.isAbsolute(value.path) || path.resolve(value.path) !== value.path
    || !/^[a-f0-9]{64}$/.test(value.sha256)) fail('EXACT_STORE_REFERENCE_REQUIRED');
  return value;
}
function readHashed(referenceValue, maxBytes = 65536) {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 16 * 1024 * 1024) fail('STORE_INPUT_SIZE_BOUND');
  const ref = reference(referenceValue);
  const fd = fs.openSync(ref.path, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0));
  try {
    const before = fs.fstatSync(fd, { bigint: true });
    const named = fs.lstatSync(ref.path, { bigint: true });
    const same = (a, b, named = false) => ['ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'].every(key => a[key] === b[key])
      && (named && process.platform === 'win32' || a.dev === b.dev);
    if (!before.isFile() || before.size < 1n || before.size > BigInt(maxBytes) || !named.isFile() || named.isSymbolicLink()
      || (process.platform !== 'win32' && (before.uid !== BigInt(process.getuid()) || before.nlink !== 1n))
      || (process.platform === 'win32' && before.nlink > 1n)
      || !same(before, named, true) || fs.realpathSync(ref.path) !== ref.path) fail('REGULAR_CANONICAL_STORE_INPUT_REQUIRED');
    const buffer = Buffer.alloc(maxBytes + 1);
    let count = 0;
    while (count < buffer.length) {
      const length = fs.readSync(fd, buffer, count, buffer.length - count, null);
      if (!length) break;
      count += length;
    }
    if (count > maxBytes) fail('STORE_INPUT_SIZE_BOUND');
    const bytes = buffer.subarray(0, count);
    const after = fs.fstatSync(fd, { bigint: true });
    const finalName = fs.lstatSync(ref.path, { bigint: true });
    if (!after.isFile() || !finalName.isFile() || finalName.isSymbolicLink()
      || !same(before, after) || !same(after, finalName, true) || BigInt(bytes.length) !== before.size) fail('STORE_INPUT_CHANGED');
    if (createHash('sha256').update(bytes).digest('hex') !== ref.sha256) fail('STORE_INPUT_HASH_MISMATCH');
    return bytes;
  } finally { fs.closeSync(fd); }
}
function readJson(ref, maxBytes) {
  const bytes = readHashed(ref, maxBytes);
  let value;
  try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { fail('STORE_INPUT_JSON_REQUIRED'); }
  return { value, bytes };
}
function version(value) {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})$/.test(value)) fail('EXPLICIT_MARKETING_VERSION_REQUIRED');
  return value.split('.').map(Number);
}
function iosBuild(value, zero = false) {
  if (typeof value !== 'string' || !(zero ? /^(0|[1-9][0-9]{0,3})$/ : /^[1-9][0-9]{0,3}$/).test(value)) fail('EXPLICIT_IOS_BUILD_NUMBER_REQUIRED');
  return Number(value);
}
function androidBuild(value, zero = false) {
  if (!Number.isSafeInteger(value) || value < (zero ? 0 : 1) || value > 2100000000) fail('EXPLICIT_ANDROID_VERSION_CODE_REQUIRED');
  return value;
}
function identities(value, links) {
  shape(value, ['iosBundleIdentifier', 'androidPackageName'], 'STORE_IDENTITIES_REQUIRED');
  if (value.iosBundleIdentifier !== links.config.ios.bundleIdentifier || value.androidPackageName !== links.config.android.packageName) fail('STORE_LINK_IDENTITIES_MISMATCH');
}
function validateStoreBuild(build, baseline, links, { allowSynthetic = false } = {}) {
  shape(build, ['schemaVersion', 'kind', 'syntheticDataOnly', 'nativeLinkConfigSha256', 'identities', 'version', 'iosBuildNumber', 'androidVersionCode', 'baseline'], 'STORE_BUILD_SCHEMA_REQUIRED');
  shape(baseline, ['schemaVersion', 'kind', 'syntheticDataOnly', 'identities', 'marketingVersion', 'iosBuildNumber', 'androidVersionCode', 'scope'], 'DECLARED_BASELINE_SCHEMA_REQUIRED');
  if (build.schemaVersion !== 1 || build.kind !== 'caseops-store-build' || baseline.schemaVersion !== 1
    || baseline.kind !== 'caseops-declared-store-build-baseline' || baseline.scope !== 'operator-declared-not-store-verified') fail('DECLARED_BASELINE_REQUIRED');
  if (typeof build.syntheticDataOnly !== 'boolean' || build.syntheticDataOnly !== baseline.syntheticDataOnly
    || build.syntheticDataOnly !== links.config.syntheticDataOnly || (build.syntheticDataOnly && !allowSynthetic)) fail('REAL_STORE_INPUTS_REQUIRED');
  if (build.nativeLinkConfigSha256 !== links.sha256) fail('STORE_LINK_CONFIG_HASH_MISMATCH');
  identities(build.identities, links); identities(baseline.identities, links); reference(build.baseline);
  const nextVersion = version(build.version), priorVersion = version(baseline.marketingVersion);
  const compare = nextVersion.reduce((result, part, index) => result || Math.sign(part - priorVersion[index]), 0);
  if (compare < 0 || build.version === '0.0.0') fail('MARKETING_VERSION_ROLLBACK_FORBIDDEN');
  if (iosBuild(build.iosBuildNumber) <= iosBuild(baseline.iosBuildNumber, true)
    || androidBuild(build.androidVersionCode) <= androidBuild(baseline.androidVersionCode, true)) fail('DECLARED_STORE_BUILD_NUMBERS_MUST_INCREASE');
  return { version: build.version, iosBuildNumber: build.iosBuildNumber, androidVersionCode: build.androidVersionCode,
    baselineScope: baseline.scope, independentlyVerifiedStoreMaximum: false };
}
function readStoreBuildSettings(env, links, options) {
  const ref = reference({ path: env.CASEOPS_STORE_BUILD_FILE, sha256: env.CASEOPS_STORE_BUILD_SHA256 });
  const build = readJson(ref);
  const baseline = readJson(reference(build.value.baseline));
  return { ...validateStoreBuild(build.value, baseline.value, links, options), ref, build, baseline };
}
// Reserve before any future build or secret access. Partial reservations survive failure.
function reserveBuildNumbers(root, build, requestSha256) {
  iosBuild(build.iosBuildNumber); androidBuild(build.androidVersionCode);
  shape(build.identities, ['iosBundleIdentifier', 'androidPackageName'], 'STORE_IDENTITIES_REQUIRED');
  for (const value of Object.values(build.identities)) if (typeof value !== 'string' || !/^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9_-]+){2,}$/.test(value)) fail('STORE_IDENTITIES_REQUIRED');
  if (!path.isAbsolute(root) || fs.realpathSync(root) !== root || !/^[a-f0-9]{64}$/.test(requestSha256)) fail('EXPLICIT_CANONICAL_RESERVATION_ROOT_REQUIRED');
  const stat = fs.lstatSync(root);
  if (!stat.isDirectory() || stat.isSymbolicLink() || (process.platform !== 'win32' && ((stat.mode & 0o077) !== 0 || stat.uid !== process.getuid()))) fail('OWNED_PRIVATE_RESERVATION_ROOT_REQUIRED');
  for (const [platform, appId, value] of [['ios', build.identities.iosBundleIdentifier, build.iosBuildNumber], ['android', build.identities.androidPackageName, String(build.androidVersionCode)]]) {
    const identity = createHash('sha256').update(JSON.stringify([platform, appId])).digest('hex');
    fs.writeFileSync(path.join(root, identity + '-' + platform + '-' + value + '.json'), JSON.stringify({ requestSha256, platform, value }) + '\n', { flag: 'wx', mode: 0o600 });
  }
}
module.exports = { readHashed, readJson, reference, validateStoreBuild, readStoreBuildSettings, reserveBuildNumbers };
