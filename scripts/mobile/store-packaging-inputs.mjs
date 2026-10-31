// Internal host inputs, never imported by an application/web bundle.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const identity = fields.slice(0, 5);
const same = (a, b, keys = fields) => keys.every(k => a[k] === b[k]);
export const namedMatchesStoreDescriptor = (opened, named, platform = process.platform) =>
  fields.every(k => (k === 'dev' && platform === 'win32' && named.dev === 0n) || opened[k] === named[k]);
export const digest = data => createHash('sha256').update(data).digest('hex');
export function objectKeys(value, keys, code) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), code);
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort(), code);
}
export function checkDeadline(deadline) {
  assert.ok(deadline === undefined || (Number.isFinite(deadline) && Date.now() < deadline), 'STORE_TOTAL_DEADLINE');
}
export function namespace(file, deadline) {
  const rows = [];
  for (let p = path.dirname(file); ; p = path.dirname(p)) {
    checkDeadline(deadline); const stat = fs.lstatSync(p, { bigint: true });
    assert.ok(stat.isDirectory() && !stat.isSymbolicLink(), 'STORE_NAMESPACE_REQUIRED');
    rows.push({ path: p, stat });
    if (p === path.dirname(p)) return rows;
  }
}
function readOwnedBuffer(file, { maxBytes = 1048576, privateFile = false, systemTool = false, deadline, allowEmpty = false } = {}) {
  checkDeadline(deadline);
  assert.ok(path.isAbsolute(file || '') && path.resolve(file) === file, 'STORE_ABSOLUTE_INPUT_REQUIRED');
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 512 * 1024 * 1024, 'STORE_INPUT_BOUND');
  const allocations = []; let body;
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
  try {
    const a = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    const uid = process.getuid?.();
    assert.ok(a.isFile() && a.nlink === 1n && a.size >= (allowEmpty ? 0n : 1n) && a.size <= BigInt(maxBytes)
      && !named.isSymbolicLink() && namedMatchesStoreDescriptor(a, named)
      && (uid === undefined || a.uid === BigInt(uid) || (systemTool && a.uid === 0n))
      && (!privateFile || [0o400n, 0o600n].includes(a.mode & 0o7777n))
      && (!systemTool || (a.mode & 0o022n) === 0n), 'STORE_INPUT_IDENTITY_REQUIRED');
    const canonical = fs.realpathSync(file), parents = namespace(canonical, deadline);
    assert.ok(namedMatchesStoreDescriptor(a, fs.lstatSync(canonical, { bigint: true })), 'STORE_INPUT_NAMESPACE_CHANGED');
    const limit = Number(a.size) + 1, chunks = [];
    let bytes = 0;
    while (bytes < limit) {
      checkDeadline(deadline); const chunk = Buffer.alloc(Math.min(65536, limit - bytes)); allocations.push(chunk);
      const count = fs.readSync(fd, chunk, 0, chunk.length, bytes);
      if (!count) break;
      chunks.push(chunk.subarray(0, count)); bytes += count;
    }
    checkDeadline(deadline);
    assert.ok(BigInt(bytes) === a.size && bytes <= maxBytes && same(a, fs.fstatSync(fd, { bigint: true }))
      && same(named, fs.lstatSync(file, { bigint: true })) && fs.realpathSync(file) === canonical
      && namedMatchesStoreDescriptor(a, fs.lstatSync(canonical, { bigint: true })), 'STORE_INPUT_CHANGED');
    const finalParents = namespace(canonical, deadline);
    assert.ok(parents.length === finalParents.length && parents.every((row, i) => row.path === finalParents[i].path
      && same(row.stat, finalParents[i].stat, identity)), 'STORE_INPUT_NAMESPACE_CHANGED');
    body = Buffer.concat(chunks, bytes);
    return { bytes: body, metadata: Object.fromEntries(fields.map(k => [k, String(a[k])])), canonical };
  } finally { for (const allocation of allocations) allocation.fill(0); try { fs.closeSync(fd); } catch (error) { body?.fill(0); throw error; } }
}
export function readInput(file, { sha256, ...options } = {}) {
  if (sha256 !== undefined) assert.match(sha256, /^[a-f0-9]{64}$/, 'STORE_HASH_REQUIRED');
  const read = readOwnedBuffer(file, options);
  try {
    const actual = digest(read.bytes);
    if (sha256 !== undefined) assert.equal(actual, sha256, 'STORE_INPUT_HASH_MISMATCH');
    return { ...read, sha256: actual };
  } catch (error) { read.bytes.fill(0); throw error; }
}
// Password-pair input is not a public evidence reference. Never hash its
// contents or return a digest/raw buffer for persistence. Ownership/namespace
// and the actual keystore certificate provide the relevant local boundaries.
export function readPrivateCredentials(input, { deadline } = {}) {
  objectKeys(input, ['path'], 'STORE_PRIVATE_CREDENTIAL_PATH_REQUIRED');
  let read, value, transferred = false;
  try {
    read = readOwnedBuffer(input.path, { maxBytes: 16384, privateFile: true, deadline });
    value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(read.bytes));
    objectKeys(value, ['storePassword', 'keyPassword'], 'STORE_PASSWORD_FIELDS_REQUIRED');
    assert.ok(Object.values(value).every(v => typeof v === 'string' && v.length > 0 && v.length <= 1024 && !v.includes('\0')), 'STORE_PASSWORD_VALUES_REQUIRED');
    transferred = true;
    return { value, metadata: read.metadata, canonical: read.canonical };
  } catch { throw new Error('STORE_PRIVATE_CREDENTIALS_REFUSED'); }
  finally {
    read?.bytes.fill(0);
    if (!transferred && value && typeof value === 'object') for (const key of Object.keys(value)) value[key] = undefined;
  }
}
export function jsonInput(ref, options = {}) {
  objectKeys(ref, ['path', 'sha256'], 'STORE_REFERENCE_REQUIRED');
  const read = readInput(ref.path, { ...options, sha256: ref.sha256 });
  try { return { ...read, value: JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(read.bytes)) }; }
  catch { read.bytes.fill(0); throw new Error('STORE_INPUT_JSON_REQUIRED'); }
}
export function privateDirectory(directory, { existing = true, deadline } = {}) {
  checkDeadline(deadline);
  assert.ok(path.isAbsolute(directory || '') && path.resolve(directory) === directory, 'STORE_PRIVATE_DIRECTORY_REQUIRED');
  if (!existing) {
    assert.equal(fs.existsSync(directory), false, 'STORE_NEW_OUTPUT_REQUIRED');
    privateDirectory(path.dirname(directory), { deadline }); fs.mkdirSync(directory, { mode: 0o700 });
  }
  const a = fs.lstatSync(directory);
  assert.ok(a.isDirectory() && !a.isSymbolicLink() && fs.realpathSync(directory) === directory
    && (process.getuid === undefined || (a.uid === process.getuid() && (a.mode & 0o077) === 0)), 'STORE_PRIVATE_DIRECTORY_REQUIRED');
  return directory;
}
export function writePrivate(file, bytes, { deadline } = {}) {
  checkDeadline(deadline); privateDirectory(path.dirname(file), { deadline });
  const fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
  try {
    let count = 0;
    while (count < bytes.length) {
      checkDeadline(deadline); const n = fs.writeSync(fd, bytes, count, bytes.length - count); assert.ok(n > 0, 'STORE_OUTPUT_NO_PROGRESS'); count += n;
    }
    fs.fsyncSync(fd);
  } finally { fs.closeSync(fd); }
  return { path: file, sha256: digest(bytes) };
}

// Generated project directories are public source (normally 0755), unlike
// secret/output directories. Do not relax writePrivate for this one public copy.
export function writePublicLock(file, bytes, { deadline } = {}) {
  checkDeadline(deadline);
  assert.ok(path.isAbsolute(file || '') && path.resolve(file) === file
    && Buffer.isBuffer(bytes) && bytes.length > 0 && bytes.length <= 1048576, 'STORE_PUBLIC_LOCK_INPUT_REQUIRED');
  const parent = path.dirname(file), uid = process.getuid?.(), before = namespace(file, deadline);
  const parentAllowed = stat => stat.isDirectory() && !stat.isSymbolicLink()
    && (uid === undefined || stat.uid === BigInt(uid)) && (stat.mode & 0o022n) === 0n;
  assert.ok(parentAllowed(before[0].stat) && fs.realpathSync(parent) === parent, 'STORE_PUBLIC_LOCK_PARENT_REQUIRED');
  const reconcileParents = () => {
    const after = namespace(file, deadline);
    assert.ok(before.length === after.length && before.every((row, i) => row.path === after[i].path
      && same(row.stat, after[i].stat, identity)) && parentAllowed(after[0].stat)
      && fs.realpathSync(parent) === parent, 'STORE_PUBLIC_LOCK_NAMESPACE_CHANGED');
  };
  checkDeadline(deadline);
  const fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL
    | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
  try {
    const opened = fs.fstatSync(fd, { bigint: true });
    assert.ok(opened.isFile() && opened.nlink === 1n && opened.size === 0n
      && (uid === undefined || opened.uid === BigInt(uid)) && (opened.mode & 0o7777n) === 0o600n
      && namedMatchesStoreDescriptor(opened, fs.lstatSync(file, { bigint: true }))
      && fs.realpathSync(file) === file, 'STORE_PUBLIC_LOCK_IDENTITY_REQUIRED');
    reconcileParents();
    let count = 0;
    while (count < bytes.length) {
      checkDeadline(deadline);
      const n = fs.writeSync(fd, bytes, count, Math.min(65536, bytes.length - count), count);
      assert.ok(n > 0 && n <= Math.min(65536, bytes.length - count), 'STORE_OUTPUT_NO_PROGRESS'); count += n;
    }
    checkDeadline(deadline); fs.fsyncSync(fd); checkDeadline(deadline);
    const written = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    assert.ok(same(opened, written, fields.slice(0, 6)) && written.size === BigInt(bytes.length)
      && namedMatchesStoreDescriptor(written, named), 'STORE_PUBLIC_LOCK_CHANGED');
    const retained = Buffer.alloc(bytes.length + 1); let read = 0;
    while (read < retained.length) {
      checkDeadline(deadline);
      const n = fs.readSync(fd, retained, read, Math.min(65536, retained.length - read), read);
      if (!n) break;
      read += n;
    }
    checkDeadline(deadline);
    assert.ok(read === bytes.length && retained.subarray(0, read).equals(bytes)
      && same(written, fs.fstatSync(fd, { bigint: true })) && same(named, fs.lstatSync(file, { bigint: true }))
      && fs.realpathSync(file) === file, 'STORE_PUBLIC_LOCK_CHANGED');
    reconcileParents();
    return { path: file, sha256: digest(retained.subarray(0, read)) };
  } finally { fs.closeSync(fd); }
}

// Complete Git-tracked file contents and root/file metadata, not a full filesystem
// directory inventory or installed runtime/import-closure audit.
// Both observations are charged to one supplied entry/byte/deadline ledger.
export function gitSource(root, git, budget) {
  const charge = () => assert.ok(Date.now() < budget.deadline && ++budget.entries <= 20000, 'STORE_SOURCE_BOUND');
  const metadata = s => Object.fromEntries(fields.map(k => [k, String(s[k])]));
  charge(); const rootStat = fs.lstatSync(root, { bigint: true });
  assert.ok(rootStat.isDirectory() && !rootStat.isSymbolicLink() && fs.realpathSync(root) === root, 'STORE_SOURCE_ROOT_REQUIRED');
  assert.ok(fs.lstatSync(path.join(root, '.git')).isDirectory() && !fs.lstatSync(path.join(root, '.git')).isSymbolicLink()
    && !fs.existsSync(path.join(root, '.git/objects/info/alternates')), 'STORE_INDEPENDENT_GIT_CLONE_REQUIRED');
  const env = { PATH: '/usr/bin:/bin', HOME: process.env.HOME, GIT_OPTIONAL_LOCKS: '0', GIT_TERMINAL_PROMPT: '0', LC_ALL: 'C' };
  const call = args => { checkDeadline(budget.deadline); return execFileSync(git, args, { cwd: root, env, encoding: 'utf8', timeout: Math.max(1, Math.min(5000, budget.deadline - Date.now())), maxBuffer: 4 * 1024 * 1024 }); };
  assert.equal(call(['status', '--porcelain=v1', '--untracked-files=all']), '', 'STORE_CLEAN_SOURCE_REQUIRED');
  const sourceSha = call(['rev-parse', 'HEAD']).trim(), tree = call(['rev-parse', 'HEAD^{tree}']).trim();
  const gitInputs = ['HEAD', 'index'].map(name => {
    charge(); const read = readInput(path.join(root, '.git', name), { maxBytes: 4 * 1024 * 1024, deadline: budget.deadline }); budget.bytes += read.bytes.length;
    return { name, sha256: read.sha256, metadata: read.metadata };
  });
  const rows = call(['ls-tree', '-r', '-z', 'HEAD']).split('\0').filter(Boolean), names = new Set(), files = [];
  const hash = createHash('sha256');
  for (const row of rows) {
    charge();
    const m = /^(100644|100755) blob ([a-f0-9]{40})\t(.+)$/.exec(row);
    assert.ok(m && !names.has(m[3]) && !m[3].split('/').includes('..'), 'STORE_SOURCE_REGULAR_UNIQUE_REQUIRED'); names.add(m[3]);
    const file = path.join(root, m[3]), read = readInput(file, { maxBytes: 64 * 1024 * 1024, deadline: budget.deadline, allowEmpty: true });
    assert.equal(Boolean(Number(read.metadata.mode) & 0o111), m[1] === '100755', 'STORE_SOURCE_EXECUTABLE_MODE_MISMATCH');
    budget.bytes += read.bytes.length; assert.ok(budget.bytes <= 1024 * 1024 * 1024, 'STORE_SOURCE_BOUND');
    assert.equal(createHash('sha1').update('blob ' + read.bytes.length + '\0').update(read.bytes).digest('hex'), m[2], 'STORE_SOURCE_GIT_BYTES_MISMATCH');
    hash.update(m[3] + '\0' + read.sha256 + '\0');
    files.push({ path: m[3], gitBlob: m[2], sha256: read.sha256, metadata: read.metadata });
  }
  assert.equal(call(['status', '--porcelain=v1', '--untracked-files=all']), '', 'STORE_CLEAN_SOURCE_REQUIRED');
  assert.equal(call(['rev-parse', 'HEAD']).trim(), sourceSha, 'STORE_SOURCE_MOVED');
  for (const row of files) {
    charge(); const file = path.join(root, row.path);
    assert.deepEqual(metadata(fs.lstatSync(file, { bigint: true })), row.metadata, 'STORE_FINAL_SOURCE_METADATA_CHANGED');
    assert.equal(fs.realpathSync(file), file, 'STORE_FINAL_SOURCE_NAMESPACE_CHANGED');
  }
  for (const row of gitInputs) {
    charge(); assert.deepEqual(metadata(fs.lstatSync(path.join(root, '.git', row.name), { bigint: true })), row.metadata, 'STORE_GIT_INPUT_CHANGED');
  }
  charge(); assert.deepEqual(metadata(fs.lstatSync(root, { bigint: true })), metadata(rootStat), 'STORE_SOURCE_ROOT_CHANGED');
  assert.ok(budget.bytes <= 1024 * 1024 * 1024, 'STORE_SOURCE_BOUND');
  return { sourceSha, tree, sourceFileCount: files.length, fullSourceFingerprint: hash.digest('hex'), rootMetadata: metadata(rootStat), gitInputs, files };
}
