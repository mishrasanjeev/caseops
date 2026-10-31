import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { npmRegistryEntry, npmRegistryBootstrap } from './npm-registry.mjs';

// This is a distinct local dependency rebundle. npm's own CLI remains 11.12.1.
export const NPM_ARTIFACT = Object.freeze({ sha256: 'fcfa9290ee0acca362be71768de3dcc591f6af00622270529e70fbb25b831052',
  sizeBytes: 4043346, tarBytes: 17643520, members: 2149,
  relative: 'apps/mobile/vendor/npm-11.12.1-caseops-security/npm-11.12.1-caseops-security.tgz' });
const fields = ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs', 'uid', 'gid', 'mode', 'nlink'];
const directoryFields = ['dev', 'ino', 'mode', 'uid', 'gid'];
const frame = (s, keys = fields) => keys.map(k => String(s[k]));
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const digest = b => createHash('sha256').update(b).digest('hex');
const check = end => assert.ok(performance.now() < end, 'NPM_TOOLING_PREPARATION_DEADLINE');
const canonical = p => (fs.realpathSync.native ?? fs.realpathSync)(p);
function namedFile(named, opened) {
  assert.ok(named.isFile() && !named.isSymbolicLink(), 'NPM_TOOLING_REGULAR_FILE_REQUIRED');
  for (const key of fields) if (!(process.platform === 'win32' && key === 'dev' && named.dev === 0n))
    assert.equal(named[key], opened[key], 'NPM_TOOLING_NAMED_DESCRIPTOR_CHANGED');
}
function parents(file, end, scopeRoot = null) {
  const rows = [];
  if (scopeRoot) {
    assert.ok(file === scopeRoot || file.startsWith(scopeRoot + path.sep), 'NPM_TOOLING_NAMESPACE_SCOPE');
    if (file === scopeRoot) return rows;
  }
  for (let p = path.dirname(file); ; p = path.dirname(p)) {
    check(end); assert.ok(rows.length < 128, 'NPM_TOOLING_NAMESPACE_BOUND');
    const s = fs.lstatSync(p, { bigint: true });
    assert.ok(s.isDirectory() && !s.isSymbolicLink() && canonical(p) === p, 'NPM_TOOLING_NAMESPACE_CHANGED');
    rows.push([p, ...frame(s, directoryFields)]);
    if (p === scopeRoot || p === path.dirname(p)) return rows;
  }
}
// Windows ownership is an ACL fact, not its synthetic stat.uid. Only the pinned
// public archive may use a safe Administrators-owned checkout source. Executed
// copies require the current token's normal owner and a private write scope.
/** Decode only fixed ownership facts; never include SID/path/ACL bytes in errors. */
export function reviewNpmWindowsOwnerOutput(output, publicPinnedData = false) {
  assert.equal(typeof publicPinnedData, 'boolean', 'NPM_TOOLING_WINDOWS_OWNER_ADMISSION');
  assert.ok(typeof output === 'string' && output.length > 0 && output.length <= 4096
    && Buffer.byteLength(output) <= 4096, 'NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_BOUND');
  let value;
  try { value = JSON.parse(output); } catch { assert.fail('NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_JSON'); }
  assert.ok(value && typeof value === 'object' && !Array.isArray(value)
    && equal(Object.keys(value).sort(), ['aclSha256', 'reviewedAdminSource', 'runtimeOwner', 'tokenUserPresent', 'writeScopeSafe']),
  'NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_FIELDS');
  for (const key of ['runtimeOwner', 'reviewedAdminSource', 'writeScopeSafe', 'tokenUserPresent'])
    assert.equal(typeof value[key], 'boolean', 'NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_BOOLEAN');
  assert.ok(typeof value.aclSha256 === 'string' && /^[a-f0-9]{64}$/.test(value.aclSha256), 'NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_HASH');
  assert.ok(value.tokenUserPresent, 'NPM_TOOLING_WINDOWS_OWNER_TOKEN_REQUIRED');
  assert.ok(value.writeScopeSafe, 'NPM_TOOLING_WINDOWS_OWNER_WRITE_SCOPE_REFUSED');
  assert.ok(value.runtimeOwner || publicPinnedData && value.reviewedAdminSource, 'NPM_TOOLING_WINDOWS_OWNER_SID_REFUSED');
  return value.aclSha256;
}
function windowsOwner(file, kind, publicPinnedData, end) {
  if (process.platform !== 'win32') return;
  assert.ok(path.isAbsolute(process.env.SystemRoot || ''), 'NPM_TOOLING_WINDOWS_OWNER_REQUIRED');
  assert.ok(kind === 'file' || kind === 'directory', 'NPM_TOOLING_WINDOWS_OWNER_KIND');
  const code = "$ErrorActionPreference='Stop';try{$p=$env:CASEOPS_NPM_ACL_PATH;$sections=[Security.AccessControl.AccessControlSections]'Access,Owner';if($env:CASEOPS_NPM_ACL_KIND -eq 'file'){$a=[IO.File]::GetAccessControl($p,$sections)}elseif($env:CASEOPS_NPM_ACL_KIND -eq 'directory'){$a=[IO.Directory]::GetAccessControl($p,$sections)}else{throw 'NPM_ACL_KIND'};$i=[Security.Principal.WindowsIdentity]::GetCurrent();$u=$i.User.Value;$t=$i.Owner.Value;$present=![string]::IsNullOrEmpty($u);$o=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;$owner=($o -eq $u -or ($o -eq $t -and $o -in @('S-1-5-18','S-1-5-32-544')));$public=($present -and $o -eq 'S-1-5-32-544' -and $t -eq $u);$safe=$true;foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($r.AccessControlType -eq 'Allow' -and ([int]$r.FileSystemRights -band 852310) -ne 0 -and $r.IdentityReference.Value -notin @($u,'S-1-5-18','S-1-5-32-544','S-1-3-0')){$safe=$false}};$hash=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($a.GetSecurityDescriptorBinaryForm())).Replace('-','').ToLowerInvariant();[Console]::Out.Write('{\"runtimeOwner\":'+$owner.ToString().ToLowerInvariant()+',\"reviewedAdminSource\":'+$public.ToString().ToLowerInvariant()+',\"writeScopeSafe\":'+$safe.ToString().ToLowerInvariant()+',\"tokenUserPresent\":'+$present.ToString().ToLowerInvariant()+',\"aclSha256\":\"'+$hash+'\"}')}catch{[Console]::Error.WriteLine('NPM_TOOLING_WINDOWS_ACL_QUERY_FAILED');exit 1}";
  const result = spawnSync(path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe'),
    ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', code], { encoding: 'utf8', windowsHide: true,
      timeout: Math.max(1, Math.min(5000, Math.floor(end - performance.now()))), maxBuffer: 4096,
      env: { SystemRoot: process.env.SystemRoot, WINDIR: process.env.SystemRoot, CASEOPS_NPM_ACL_PATH: file, CASEOPS_NPM_ACL_KIND: kind } });
  check(end); assert.ok(!result.error && result.status === 0 && result.signal === null
    && result.stderr === '', 'NPM_TOOLING_WINDOWS_OWNER_COMMAND_REFUSED');
  return reviewNpmWindowsOwnerOutput(result.stdout, publicPinnedData);
}
export function readPinnedArchive(file, end = performance.now() + 30000) {
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const before = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    namedFile(named, before);
    assert.ok(before.isFile() && before.nlink === 1n && before.size === BigInt(NPM_ARTIFACT.sizeBytes), 'NPM_TOOLING_ARCHIVE_EXTENT');
    if (process.getuid) assert.equal(before.uid, BigInt(process.getuid()), 'NPM_TOOLING_ARCHIVE_OWNER');
    const location = canonical(file), ns = parents(location, end), acl = windowsOwner(file, 'file', true, end);
    const bytes = Buffer.alloc(NPM_ARTIFACT.sizeBytes + 1); let n = 0;
    while (n < bytes.length) { check(end); const width = fs.readSync(fd, bytes, n, Math.min(65536, bytes.length - n), n); if (!width) break; n += width; }
    assert.equal(n, NPM_ARTIFACT.sizeBytes, 'NPM_TOOLING_ARCHIVE_EXTENT');
    assert.ok(equal(frame(before), frame(fs.fstatSync(fd, { bigint: true })))
      && equal(frame(named), frame(fs.lstatSync(file, { bigint: true }))) && location === canonical(file)
      && equal(ns, parents(location, end)) && acl === windowsOwner(file, 'file', true, end), 'NPM_TOOLING_ARCHIVE_CHANGED');
    const kept = bytes.subarray(0, n); assert.equal(digest(kept), NPM_ARTIFACT.sha256, 'NPM_TOOLING_ARCHIVE_DIGEST');
    return kept;
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
function text(block, start, width) {
  const raw = block.subarray(start, start + width), zero = raw.indexOf(0), end = zero < 0 ? raw.length : zero;
  assert.ok(raw.subarray(end).every(b => b === 0) && raw.subarray(0, end).every(b => b >= 32 && b <= 126), 'NPM_TOOLING_TAR_TEXT');
  return raw.subarray(0, end).toString('ascii');
}
function octal(block, start, width) {
  const raw = block.subarray(start, start + width).toString('ascii');
  assert.match(raw, /^[0-7]+[\0 ]*$/, 'NPM_TOOLING_TAR_OCTAL');
  const value = Number.parseInt(raw, 8); assert.ok(Number.isSafeInteger(value), 'NPM_TOOLING_TAR_NUMBER'); return value;
}
/** Deliberately supports the reviewed archive's regular-only USTAR format. */
export function regularTarMembers(tar, end = performance.now() + 30000) {
  assert.ok(Buffer.isBuffer(tar) && tar.length > 1024 && tar.length <= 33554432 && tar.length % 512 === 0, 'NPM_TOOLING_TAR_BOUND');
  const rows = [], names = new Set(), portableNames = new Set(); let offset = 0, total = 0;
  while (offset + 512 <= tar.length) {
    check(end); const h = tar.subarray(offset, offset + 512);
    if (h.every(b => b === 0)) {
      assert.ok(tar.length - offset >= 1024 && tar.subarray(offset).every(b => b === 0), 'NPM_TOOLING_TAR_END');
      return rows;
    }
    assert.ok(rows.length < 4096, 'NPM_TOOLING_TAR_MEMBER_BOUND');
    let sum = 0; for (let i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? 32 : h[i];
    assert.equal(octal(h, 148, 8), sum, 'NPM_TOOLING_TAR_CHECKSUM');
    assert.ok(h[156] === 48 && text(h, 157, 100) === '' && text(h, 345, 155) === ''
      && text(h, 257, 6) === 'ustar' && h.subarray(263, 265).toString() === '00', 'NPM_TOOLING_TAR_REGULAR_ONLY');
    const name = text(h, 0, 100), parts = name.split('/');
    assert.ok(parts.length >= 2 && parts[0] === 'package' && parts.every(p => p && p !== '.' && p !== '..'
      && /^[A-Za-z0-9_@.+-]+$/.test(p) && !/[. ]$/.test(p)) && !names.has(name)
      && !portableNames.has(name.toLowerCase()), 'NPM_TOOLING_TAR_PATH'); names.add(name); portableNames.add(name.toLowerCase());
    const mode = octal(h, 100, 8), size = octal(h, 124, 12);
    assert.ok([0o644, 0o755].includes(mode) && size <= 8388608, 'NPM_TOOLING_TAR_MODE_EXTENT');
    total += size; assert.ok(total <= 33554432 && offset + 512 + size <= tar.length, 'NPM_TOOLING_TAR_PAYLOAD_BOUND');
    const bytes = tar.subarray(offset + 512, offset + 512 + size);
    rows.push({ path: name, mode, bytes, sha256: digest(bytes) });
    const next = offset + 512 + Math.ceil(size / 512) * 512;
    assert.ok(tar.subarray(offset + 512 + size, next).every(b => b === 0), 'NPM_TOOLING_TAR_PADDING'); offset = next;
  }
  assert.fail('NPM_TOOLING_TAR_END');
}
function writeMember(file, row, end, uid, root) {
  const ns = parents(file, end, root); let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), row.mode);
    const initial = fs.fstatSync(fd, { bigint: true });
    assert.ok(initial.isFile() && initial.nlink === 1n && initial.size === 0n && initial.uid === uid, 'NPM_TOOLING_EXCLUSIVE_FILE');
    let n = 0; while (n < row.bytes.length) { check(end); const w = fs.writeSync(fd, row.bytes, n, Math.min(65536, row.bytes.length - n), n); assert.ok(w > 0); n += w; }
    // This one-invocation runtime is verified by same-FD readback and complete paired payload scans.
    fs.fchmodSync(fd, row.mode);
    const final = fs.fstatSync(fd, { bigint: true }); namedFile(fs.lstatSync(file, { bigint: true }), final);
    assert.equal(final.size, BigInt(row.bytes.length));
    for (const key of ['dev', 'ino', 'uid', 'gid', 'nlink']) assert.equal(initial[key], final[key], 'NPM_TOOLING_WRITTEN_IDENTITY');
    const readback = Buffer.alloc(row.bytes.length + 1); n = 0;
    while (n < readback.length) { check(end); const w = fs.readSync(fd, readback, n, Math.min(65536, readback.length - n), n); if (!w) break; n += w; }
    assert.ok(n === row.bytes.length && readback.subarray(0, n).equals(row.bytes)
      && equal(frame(final), frame(fs.fstatSync(fd, { bigint: true }))) && equal(ns, parents(file, end, root)), 'NPM_TOOLING_SAME_DESCRIPTOR_WRITE');
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
export function verifyInstalledNpm(root, rows, directories, end, uid) {
  const files = new Map(rows.map(row => [path.join(root, ...row.path.split('/')), row]));
  const expected = new Set([...directories, ...files.keys()]), outerNamespace = parents(root, end); let observations = 0, bytesRead = 0;
  const observe = () => {
    const result = new Map(), pending = [root];
    while (pending.length) {
      check(end); const file = pending.pop(); assert.ok(++observations <= 8192, 'NPM_TOOLING_INSTALLED_INVENTORY_BOUND');
      assert.ok(!result.has(file) && expected.has(file), 'NPM_TOOLING_UNEXPECTED_INSTALLED_FILE');
      if (directories.has(file)) {
        const state = fs.lstatSync(file, { bigint: true }), ns = parents(file, end, root);
        assert.ok(state.isDirectory() && !state.isSymbolicLink() && state.uid === uid, 'NPM_TOOLING_INSTALLED_OWNER');
        const children = fs.readdirSync(file).sort();
        assert.equal(new Set(children).size, children.length);
        for (const child of children) pending.push(path.join(file, child));
        result.set(file, { metadata: frame(state), namespace: ns, children });
      } else {
        const row = files.get(file); let fd;
        try {
          assert.ok(row, 'NPM_TOOLING_INSTALLED_REGULAR_FILE');
          fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
          const opened = fs.fstatSync(fd, { bigint: true }), state = fs.lstatSync(file, { bigint: true }), ns = parents(file, end, root);
          assert.ok(!state.isSymbolicLink() && state.uid === uid, 'NPM_TOOLING_INSTALLED_OWNER');
          namedFile(state, opened);
          assert.ok(opened.isFile() && opened.nlink === 1n, 'NPM_TOOLING_INSTALLED_REGULAR_FILE');
          assert.equal(opened.size, BigInt(row.bytes.length));
          if (process.platform !== 'win32') assert.equal(Number(opened.mode & 0o7777n), row.mode);
          const hash = createHash('sha256'), block = Buffer.alloc(65536); let offset = 0;
          while (offset <= row.bytes.length) {
            check(end); const n = fs.readSync(fd, block, 0, Math.min(block.length, row.bytes.length + 1 - offset), offset);
            if (!n) break; offset += n; bytesRead += n;
            assert.ok(offset <= row.bytes.length && bytesRead <= 67108864, 'NPM_TOOLING_INSTALLED_PAYLOAD_BOUND'); hash.update(block.subarray(0, n));
          }
          assert.equal(offset, row.bytes.length); assert.equal(hash.digest('hex'), row.sha256, 'NPM_TOOLING_INSTALLED_PAYLOAD_CHANGED');
          assert.ok(equal(frame(opened), frame(fs.fstatSync(fd, { bigint: true })))
            && equal(frame(state), frame(fs.lstatSync(file, { bigint: true }))) && equal(ns, parents(file, end, root)), 'NPM_TOOLING_INSTALLED_FILE_CHANGED');
          result.set(file, { metadata: frame(state), namespace: ns, sha256: row.sha256 });
        } finally { if (fd !== undefined) fs.closeSync(fd); }
      }
    }
    assert.ok(result.size === expected.size && [...expected].every(p => result.has(p)), 'NPM_TOOLING_COMPLETE_INSTALLED_INVENTORY');
    return result;
  };
  const before = observe(), after = observe();
  for (const [file, row] of before) assert.ok(equal(row, after.get(file)), 'NPM_TOOLING_INSTALLED_PAIR_CHANGED');
  // Reconcile every final file and then every directory after all discovery.
  for (const [file, row] of [...after].sort((a, b) => b[0].length - a[0].length)) {
    check(end); assert.ok(++observations <= 8192, 'NPM_TOOLING_INSTALLED_INVENTORY_BOUND');
    assert.ok(equal(row.metadata, frame(fs.lstatSync(file, { bigint: true })))
      && equal(row.namespace, parents(file, end, root)), 'NPM_TOOLING_FINAL_METADATA_CHANGED');
    if (row.children) assert.ok(equal(row.children, fs.readdirSync(file).sort()), 'NPM_TOOLING_FINAL_DIRECTORY_CHANGED');
  }
  assert.ok(equal(outerNamespace, parents(root, end)), 'NPM_TOOLING_RUNTIME_NAMESPACE_CHANGED');
  return { entries: after.size, observations, bytesRead };
}
export function prepareNpm({ parent = os.tmpdir(), archive = fileURLToPath(new URL('../../' + NPM_ARTIFACT.relative, import.meta.url)) } = {}) {
  assert.ok(['22.23.4', '24.15.0'].includes(process.versions.node), 'NPM_TOOLING_PINNED_NODE_REQUIRED');
  const end = performance.now() + 30000;
  const kept = readPinnedArchive(archive, end), tar = gunzipSync(kept, { maxOutputLength: 33554432 });
  assert.equal(tar.length, NPM_ARTIFACT.tarBytes, 'NPM_TOOLING_TAR_EXTENT');
  const rows = regularTarMembers(tar, end); assert.equal(rows.length, NPM_ARTIFACT.members, 'NPM_TOOLING_EXACT_MEMBERS');
  // npm scripts may invoke npm or npx again. Keep those children on this exact
  // CLI and Node as well; the distribution's launchers expect a global layout.
  const shimRows = ['npm', 'npx'].map(name => {
    const bytes = Buffer.from(process.platform === 'win32'
      ? '@ECHO off\r\n"%CASEOPS_PINNED_NPM_NODE%" --input-type=module --eval "%CASEOPS_PINNED_NPM_BOOTSTRAP%" -- ' + name + ' %*\r\n'
      : '#!/bin/sh\nexec "$CASEOPS_PINNED_NPM_NODE" --input-type=module --eval "$CASEOPS_PINNED_NPM_BOOTSTRAP" -- ' + name + ' "$@"\n');
    return { path: 'bin/' + name + (process.platform === 'win32' ? '.cmd' : ''), mode: 0o755, bytes, sha256: digest(bytes) };
  });
  const entryBytes = Buffer.from(npmRegistryEntry), entrySha256 = digest(entryBytes);
  const entryRow = { path: 'caseops-entry.mjs', mode: 0o644, bytes: entryBytes, sha256: entrySha256 };
  const stagedRows = [...rows, ...shimRows, entryRow];
  const root = fs.mkdtempSync(path.join(canonical(parent), 'caseops-npm-')); fs.chmodSync(root, 0o700);
  const initial = fs.lstatSync(root, { bigint: true }), ns = parents(root, end), acl = windowsOwner(root, 'directory', false, end);
  assert.ok(initial.isDirectory() && !initial.isSymbolicLink(), 'NPM_TOOLING_OWNED_ROOT');
  if (process.getuid) assert.equal(initial.uid, BigInt(process.getuid()));
  const logDirectory = path.join(root, 'transport'); fs.mkdirSync(logDirectory, { mode: 0o700 });
  const directories = new Set([root, logDirectory]);
  for (const row of stagedRows) {
    check(end); const file = path.join(root, ...row.path.split('/')), components = row.path.split('/').slice(0, -1); let p = root;
    for (const part of components) { p = path.join(p, part); if (!directories.has(p)) { fs.mkdirSync(p, { mode: 0o700 }); directories.add(p); } }
    writeMember(file, row, end, initial.uid, root);
  }
  const inventory = verifyInstalledNpm(root, stagedRows, directories, end, initial.uid);
  if (process.platform !== 'win32') for (const name of ['npm', 'npx']) {
    try { fs.accessSync(path.join(root, 'bin', name), fs.constants.X_OK); }
    catch { assert.fail('NPM_TOOLING_EXECUTABLE_SHIM_REQUIRED'); }
    check(end);
  }
  assert.ok(equal(frame(initial, directoryFields), frame(fs.lstatSync(root, { bigint: true }), directoryFields))
    && equal(ns, parents(root, end)) && acl === windowsOwner(root, 'directory', false, end), 'NPM_TOOLING_RUNTIME_NAMESPACE_CHANGED');
  const inheritedPath = Object.keys(process.env).find(key => key.toUpperCase() === 'PATH');
  const bootstrap = npmRegistryBootstrap(entrySha256);
  const environment = { CASEOPS_PINNED_NPM_NODE: process.execPath, CASEOPS_PINNED_NPM_ROOT: root,
    CASEOPS_PINNED_NPM_ENTRY: path.join(root, 'caseops-entry.mjs'), CASEOPS_PINNED_NPM_BOOTSTRAP: bootstrap,
    CASEOPS_PINNED_NPM_CLI_SHA256: rows.find(row => row.path === 'package/bin/npm-cli.js').sha256,
    CASEOPS_PINNED_NPX_CLI_SHA256: rows.find(row => row.path === 'package/bin/npx-cli.js').sha256,
    CASEOPS_PINNED_NPM_DEADLINE: String(Date.now() + 1800000),
    CASEOPS_PINNED_NPM_CLI: path.join(root, 'package/bin/npm-cli.js'), CASEOPS_PINNED_NPX_CLI: path.join(root, 'package/bin/npx-cli.js'),
    PATH: [path.join(root, 'bin'), path.dirname(process.execPath), inheritedPath ? process.env[inheritedPath] : ''].join(path.delimiter) };
  const advisoryInventory = npmAdvisoryInventory(rows);
  check(end); return { root, cli: environment.CASEOPS_PINNED_NPM_CLI, npx: environment.CASEOPS_PINNED_NPX_CLI, files: rows.length, inventory, advisoryInventory, environment };
}
export function npmAdvisoryInventory(rows) {
  const manifests = rows.filter(r => /(^|\/)package\.json$/.test(r.path)), identities = [], markers = [];
  for (const row of manifests) {
    const value = JSON.parse(row.bytes.toString('utf8'));
    assert.ok(value && !Array.isArray(value) && typeof value === 'object', 'NPM_TOOLING_MANIFEST_REQUIRED');
    if (typeof value.name === 'string' && typeof value.version === 'string')
      identities.push({ path: row.path, sha256: row.sha256, name: value.name, version: value.version, role: 'installed' });
    else {
      const diffMarker = ['package/node_modules/diff/libcjs/package.json', 'package/node_modules/diff/libesm/package.json'].includes(row.path);
      assert.ok((equal(Object.keys(value).sort(), ['type']) || diffMarker && equal(Object.keys(value).sort(), ['sideEffects', 'type']) && value.sideEffects === false)
        && ['module', 'commonjs'].includes(value.type), 'NPM_TOOLING_UNCLASSIFIED_MANIFEST'); markers.push(row);
    }
  }
  const roots = new Set(identities.map(r => path.posix.dirname(r.path)));
  for (const row of markers) {
    let owner = path.posix.dirname(path.posix.dirname(row.path));
    while (owner !== '.' && !roots.has(owner)) owner = path.posix.dirname(owner);
    assert.ok(roots.has(owner), 'NPM_TOOLING_ORPHAN_MODULE_MARKER');
  }
  assert.ok(identities.length === 146 && markers.length === 42 && manifests.length === 188, 'NPM_TOOLING_EXACT_MANIFEST_CLASSIFICATION');
  const provenance = rows.find(r => r.path === 'package/node_modules/glob/CASEOPS-BUNDLE-SOURCES.json');
  assert.ok(provenance, 'NPM_TOOLING_BUNDLED_PROVENANCE_REQUIRED'); const bundle = JSON.parse(provenance.bytes.toString('utf8'));
  assert.ok(bundle.originalVersion === '14.0.2' && bundle.localVersion === '14.0.2-caseops.1'
    && bundle.sourceArchives.length === 8, 'NPM_TOOLING_BUNDLED_PROVENANCE_REQUIRED');
  const embedded = bundle.sourceArchives.map(row => ({ name: row.name, version: row.version, sha256: row.reference.sha256,
    role: row.name === 'glob' ? 'explicit-upstream-mapping' : 'embedded-default-bundle' }));
  assert.equal(new Set(embedded.map(row => row.name)).size, 8);
  const all = [...identities, ...embedded], graph = {};
  for (const row of all) {
    assert.match(row.name, /^(?:@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/i); assert.match(row.version, /^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$/i);
    (graph[row.name] ??= new Set()).add(row.version);
  }
  return { rows: all, logicalPackages: identities.length, ownedModuleMarkers: markers.length,
    names: Object.keys(graph).length, graph: Object.fromEntries(Object.entries(graph).sort().map(([name, versions]) => [name, [...versions].sort()])) };
}
export async function auditNpmInventory(inventory, request = globalThis.fetch) {
  assert.notEqual(process.env.NODE_TLS_REJECT_UNAUTHORIZED, '0', 'NPM_TOOLING_TLS_VERIFICATION_REQUIRED');
  const response = await request('https://registry.npmjs.org/-/npm/v1/security/advisories/bulk', { method: 'POST', redirect: 'error',
    headers: { 'Content-Type': 'application/json', 'X-CaseOps-Automated-Test': 'no-paid-providers' },
    body: JSON.stringify(inventory.graph), signal: AbortSignal.timeout(30000) });
  assert.equal(response.status, 200, 'NPM_TOOLING_ADVISORY_HTTP_STATUS');
  const reader = response.body.getReader(), chunks = []; let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      length += value.length; assert.ok(length <= 4194304, 'NPM_TOOLING_ADVISORY_RESPONSE_BOUND'); chunks.push(Buffer.from(value));
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
  const raw = Buffer.concat(chunks, length), advisories = JSON.parse(raw.toString('utf8'));
  assert.ok(advisories && typeof advisories === 'object' && !Array.isArray(advisories), 'NPM_TOOLING_ADVISORY_PROTOCOL');
  assert.deepEqual(Object.keys(advisories), [], 'NPM_TOOLING_ADVISORIES_FOUND');
  return { platform: process.platform, node: process.versions.node, artifactSha256: NPM_ARTIFACT.sha256,
    observedAt: new Date().toISOString(), inventory, advisoryResponseSha256: digest(raw), advisories };
}
export async function runNpm(args, options = {}) {
  const installed = prepareNpm(options), isNpx = args[0] === '--npx';
  if (args[0] === '--audit-cli') { assert.equal(args.length, 1); console.log(JSON.stringify(await auditNpmInventory(installed.advisoryInventory), null, 2)); return 0; }
  const ordinaryArgs = args[0] === '--cli-health' ? ['ls', '--all', '--omit=dev', '--json', '--prefix', path.join(installed.root, 'package')] : isNpx ? args.slice(1) : args;
  const environment = { ...process.env }; for (const key of Object.keys(environment)) if (key.toUpperCase() === 'PATH') delete environment[key]; Object.assign(environment, installed.environment);
  const child = spawn(process.execPath, ['--input-type=module', '--eval', installed.environment.CASEOPS_PINNED_NPM_BOOTSTRAP, '--', isNpx ? 'npx' : 'npm', ...ordinaryArgs], { stdio: 'inherit', env: environment, windowsHide: true });
  return await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', (status, signal) => signal ? reject(new Error('NPM_TOOLING_CHILD_SIGNAL')) : resolve(status)); });
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { process.exitCode = await runNpm(process.argv.slice(2)); }
  catch (error) { const label = /^NPM_TOOLING_[A-Z_]+$/.test(error?.message || '') ? error.message : 'NPM_TOOLING_REFUSED'; console.error(label); process.exitCode = 1; }
}
