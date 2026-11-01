import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync, gzipSync } from 'node:zlib';
import { auditNpmInventory } from './npm-tooling.mjs';

// Appium 3.9.0, UiAutomator2 8.7.3 and XCUITest 12.22.2 ship glob 13.0.6 and
// minimatch 10.2.6 (GHSA-3g3m-2fjr-6pw4, GHSA-g3hv-75wg-m249). The core graph is
// repaired by overrides; each driver bundles those copies, which an override
// cannot reach, so its bundle is rebuilt from the exact upstream archive.
const REPO = fileURLToPath(new URL('../../', import.meta.url));
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const sri = bytes => 'sha512-' + createHash('sha512').update(bytes).digest('base64');
const registry = (name, version) => `https://registry.npmjs.org/${name}/-/${name.split('/').pop()}-${version}.tgz`;

// One npm project holds appium, webdriverio and the driver, so the driver's
// appium peer resolves to the installed core and one lock covers the graph.
export const APPIUM_TOOLING_PROJECT = 'scripts/mobile/appium-tooling';
export const VENDORED_GLOB = Object.freeze({ name: 'glob', version: '14.0.2-caseops.1',
  relative: 'apps/mobile/vendor/glob-14.0.2-caseops.1/glob-14.0.2-caseops.1.tgz',
  sha256: '6a1eb71056c3c6138d30c06c4c9e0877b4a9bf79ee66c684a9405c6c4442ae25' });
// Each replacement directory must hold exactly the named old version (or be
// absent for a new dependency) before it is replaced.
const DRIVER_REPLACEMENTS = Object.freeze([
  Object.freeze({ into: 'node_modules/glob', name: 'glob', version: '14.0.2-caseops.1', replaces: '13.0.6', vendored: true, sha256: VENDORED_GLOB.sha256 }),
  Object.freeze({ into: 'node_modules/minimatch', name: 'minimatch', version: '11.0.1', replaces: '10.2.6',
    integrity: 'sha512-t+Vn6DX4wPCxS23y03C0uhF7S1jpi1GfqPrnlEipCJaA2ykiNbMkVlDutZtmvLfRcUN6R8AYVlzTsQrT4RZoLQ==' }),
  Object.freeze({ into: 'node_modules/@isaacs/nonrecursive-glob-match', name: '@isaacs/nonrecursive-glob-match', version: '1.0.3', replaces: null,
    integrity: 'sha512-SI7kyKHq4XXDRozw+r9GlRZkia1ZkFrpLW98r2IC2Bpr8YkFGE3fvjzmxCG0x78A++69HmDNrDvSMYBZmHGpKA==' }),
  // glob 14 requires path-scurry ^3; other bundled consumers keep 2.0.2.
  Object.freeze({ into: 'node_modules/glob/node_modules/path-scurry', name: 'path-scurry', version: '3.0.0', replaces: null,
    integrity: 'sha512-1pTbQqH1wIwMi/eleQ5leFTTCkzFsPcgXNjwOA8YGGW/W4/kHT3dssE7Z6NH+zuqNLOzOB0uaD61yl7cAcVhgg==' }),
]);
export const UIA2_REBUNDLE = Object.freeze({
  driver: 'uiautomator2',
  upstream: Object.freeze({ name: 'appium-uiautomator2-driver', version: '8.7.3',
    integrity: 'sha512-Aa+CPtxasGBVg30d62Lun45ike7p8QNpN8n7i1FrRv7V8A04cfPulPYFzl5t71VdICXADaU6bzP7hsLXE2ahFQ==' }),
  localVersion: '8.7.3-caseops.1',
  replacements: DRIVER_REPLACEMENTS,
  provenanceFile: 'CASEOPS-REBUNDLE.json',
  tarSha256: '4f55ebc09906251558b33f593664d34eb3ecd6c95fcd46dcdd65f70634a90c75',
  tgzIntegrity: 'sha512-OS9PpU9Eoyl7QmSpkO+eSoo/JcqsUyXO8lqHWaDUb0StsSv+WK3HLeME1XRkZJ52sFh0c2MAP5kSYU01YmpbvA==',
});
export const XCUITEST_REBUNDLE = Object.freeze({
  driver: 'xcuitest',
  upstream: Object.freeze({ name: 'appium-xcuitest-driver', version: '12.22.2',
    integrity: 'sha512-Zgtv+BBZ35QyONs3I972JjEz1d9cBlzHWIJNug33jslu6OcIUKyNKr79xwpiOb1Kpcs8Pzq0yctdzcwZ7FjBkQ==' }),
  localVersion: '12.22.2-caseops.1',
  replacements: DRIVER_REPLACEMENTS,
  provenanceFile: 'CASEOPS-REBUNDLE.json',
  tarSha256: 'b69fc94c1180820fa5864d2659a9f91e73d81e658a7dffbde934eb06df86bc14',
  tgzIntegrity: 'sha512-3L0NpmjThZZj7f+/8M0qik6kPn14q4uLKNfSv9lTMYqXzZTQ3sURMAf2i+c96QwysAmh/RjAUGsuLcbPKX2DLQ==',
});
export const DRIVER_REBUNDLES = Object.freeze([UIA2_REBUNDLE, XCUITEST_REBUNDLE]);

const MTIME = 499162500; // npm's fixed pack timestamp, 1985-10-26T08:15:00Z.
function text(block, start, width) {
  const raw = block.subarray(start, start + width), zero = raw.indexOf(0), end = zero < 0 ? raw.length : zero;
  assert.ok(raw.subarray(end).every(b => b === 0) && raw.subarray(0, end).every(b => b >= 32 && b <= 126), 'APPIUM_TOOLING_TAR_TEXT');
  return raw.subarray(0, end).toString('ascii');
}
function octal(block, start, width) {
  const raw = block.subarray(start, start + width).toString('ascii');
  assert.match(raw, /^[0-7]+[\0 ]*$/, 'APPIUM_TOOLING_TAR_OCTAL');
  const value = Number.parseInt(raw, 8); assert.ok(Number.isSafeInteger(value), 'APPIUM_TOOLING_TAR_NUMBER'); return value;
}
/** Regular-only USTAR members of an npm package archive, bounded for driver bundles. */
export function packageTarMembers(tgz, { maxMembers = 16384, maxBytes = 268435456 } = {}) {
  assert.ok(Buffer.isBuffer(tgz) && tgz.length > 0 && tgz.length <= maxBytes, 'APPIUM_TOOLING_ARCHIVE_BOUND');
  const tar = gunzipSync(tgz, { maxOutputLength: maxBytes + 1048576 });
  assert.ok(tar.length > 1024 && tar.length % 512 === 0, 'APPIUM_TOOLING_TAR_BOUND');
  const rows = [], names = new Set(), portable = new Set(); let offset = 0, total = 0;
  while (offset + 512 <= tar.length) {
    const h = tar.subarray(offset, offset + 512);
    if (h.every(b => b === 0)) {
      assert.ok(tar.length - offset >= 1024 && tar.subarray(offset).every(b => b === 0), 'APPIUM_TOOLING_TAR_END');
      return rows;
    }
    assert.ok(rows.length < maxMembers, 'APPIUM_TOOLING_TAR_MEMBER_BOUND');
    let sum = 0; for (let i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? 32 : h[i];
    assert.equal(octal(h, 148, 8), sum, 'APPIUM_TOOLING_TAR_CHECKSUM');
    // POSIX ustar may split long names into a prefix. The old GNU magic (used
    // by the vendored glob archive) has no prefix field there, so it must be empty.
    const magic = h.subarray(257, 265).toString('latin1'), gnu = magic === 'ustar  \0';
    assert.ok(h[156] === 48 && text(h, 157, 100) === '' && (magic === 'ustar\x0000' || gnu)
      && (!gnu || h.subarray(345, 500).every(b => b === 0)), 'APPIUM_TOOLING_TAR_REGULAR_ONLY');
    const prefix = gnu ? '' : text(h, 345, 155), name = (prefix ? prefix + '/' : '') + text(h, 0, 100), parts = name.split('/');
    // Upstream driver bundles retain a few editor undo files ending in '~'.
    assert.ok(parts.length >= 2 && parts[0] === 'package' && parts.every(p => p && p !== '.' && p !== '..'
      && /^[A-Za-z0-9_@.+~-]+$/.test(p) && !/[. ]$/.test(p)) && !names.has(name)
      && !portable.has(name.toLowerCase()), 'APPIUM_TOOLING_TAR_PATH'); names.add(name); portable.add(name.toLowerCase());
    const mode = octal(h, 100, 8), size = octal(h, 124, 12);
    assert.ok([0o644, 0o755].includes(mode), 'APPIUM_TOOLING_TAR_MODE');
    total += size; assert.ok(total <= maxBytes && offset + 512 + size <= tar.length, 'APPIUM_TOOLING_TAR_PAYLOAD_BOUND');
    const bytes = tar.subarray(offset + 512, offset + 512 + size);
    rows.push({ path: name, mode, bytes });
    const next = offset + 512 + Math.ceil(size / 512) * 512;
    assert.ok(tar.subarray(offset + 512 + size, next).every(b => b === 0), 'APPIUM_TOOLING_TAR_PADDING'); offset = next;
  }
  assert.fail('APPIUM_TOOLING_TAR_END');
}
function field(h, value, start, width) {
  const bytes = Buffer.from(value, 'ascii'); assert.ok(bytes.length <= width, 'APPIUM_TOOLING_TAR_FIELD'); bytes.copy(h, start);
}
/** Deterministic USTAR (sorted, fixed owner/time) of regular package rows. */
export function deterministicTar(rows) {
  const blocks = [];
  for (const row of [...rows].sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0)) {
    const h = Buffer.alloc(512); let name = row.path, prefix = '';
    if (name.length > 100) {
      const split = [...name.matchAll(/\//g)].map(m => m.index).find(i => i <= 155 && name.length - i - 1 <= 100);
      assert.ok(split !== undefined, 'APPIUM_TOOLING_TAR_PATH_LENGTH');
      prefix = name.slice(0, split); name = name.slice(split + 1);
    }
    field(h, name, 0, 100); field(h, row.mode.toString(8).padStart(7, '0') + '\0', 100, 8);
    field(h, '0000000\0', 108, 8); field(h, '0000000\0', 116, 8);
    field(h, row.bytes.length.toString(8).padStart(11, '0') + '\0', 124, 12);
    field(h, MTIME.toString(8).padStart(11, '0') + '\0', 136, 12); h.fill(32, 148, 156); h[156] = 48;
    field(h, 'ustar\0', 257, 6); field(h, '00', 263, 2); field(h, prefix, 345, 155);
    const sum = h.reduce((a, b) => a + b, 0); field(h, sum.toString(8).padStart(6, '0') + '\0 ', 148, 8);
    blocks.push(h, row.bytes, Buffer.alloc((512 - row.bytes.length % 512) % 512));
  }
  blocks.push(Buffer.alloc(1024)); return Buffer.concat(blocks);
}
/** The package's own top-level licence member, which must ship with it. */
function licenceFile(rows, prefix) {
  const matches = rows.filter(r => r.path.startsWith(prefix) && /^(licen[cs]e|copying)(\.(md|txt))?$/i.test(r.path.slice(prefix.length)));
  assert.equal(matches.length, 1, 'APPIUM_TOOLING_LICENCE_REQUIRED');
  return { path: matches[0].path.slice('package/'.length), sha256: sha256(matches[0].bytes) };
}
function manifestAt(rows, directory) {
  const row = rows.find(r => r.path === `package/${directory}/package.json`);
  return row ? JSON.parse(row.bytes.toString('utf8')) : null;
}
/**
 * Rebuild a driver bundle. `archives` holds the exact upstream driver archive
 * and one archive per replacement, keyed by package name.
 */
export function rebundleDriver(archives, spec) {
  assert.equal(sri(archives[spec.upstream.name]), spec.upstream.integrity, 'APPIUM_TOOLING_UPSTREAM_INTEGRITY');
  let rows = packageTarMembers(archives[spec.upstream.name]);
  const original = JSON.parse(rows.find(r => r.path === 'package/package.json').bytes.toString('utf8'));
  assert.ok(original.name === spec.upstream.name && original.version === spec.upstream.version, 'APPIUM_TOOLING_UPSTREAM_IDENTITY');
  const replaced = [];
  for (const item of spec.replacements) {
    const archive = archives[item.name];
    if (item.vendored) assert.equal(sha256(archive), item.sha256, 'APPIUM_TOOLING_VENDORED_DIGEST');
    else assert.equal(sri(archive), item.integrity, 'APPIUM_TOOLING_REPLACEMENT_INTEGRITY');
    const prior = manifestAt(rows, item.into);
    assert.equal(prior?.version ?? null, item.replaces, 'APPIUM_TOOLING_REPLACED_IDENTITY');
    // A nested node_modules owned by the replaced package goes with it.
    const prefix = `package/${item.into}/`, removed = rows.filter(r => r.path.startsWith(prefix));
    rows = rows.filter(r => !r.path.startsWith(prefix));
    const added = packageTarMembers(archive).map(r => ({ ...r, path: prefix + r.path.slice('package/'.length) }));
    const manifest = manifestAt(added, item.into);
    assert.ok(manifest?.name === item.name && manifest.version === item.version, 'APPIUM_TOOLING_REPLACEMENT_IDENTITY');
    rows.push(...added);
    replaced.push({ directory: item.into, name: item.name, from: item.replaces, to: item.version, license: manifest.license,
      licenseFile: licenceFile(added, prefix), archiveSha256: sha256(archive), removedFiles: removed.length, addedFiles: added.length });
  }
  const driverLicence = { package: `${original.name}@${original.version}`, license: original.license, licenseFile: licenceFile(rows, 'package/') };
  for (const name of ['glob', 'minimatch']) {
    const copies = rows.filter(r => r.path.endsWith('/package.json') && new RegExp(`/node_modules/${name}/package\\.json$`).test(r.path));
    assert.deepEqual(copies.map(r => r.path), [`package/node_modules/${name}/package.json`], 'APPIUM_TOOLING_SINGLE_FIXED_COPY');
  }
  // Bundled dependents still declare the replaced versions; npm ci rejects
  // that bundle as out of sync. Point those declarations at the fixed copies.
  const fixed = new Map(spec.replacements.filter(r => r.replaces).map(r => [r.name, r.version])), dependents = [];
  rows = rows.map(row => {
    if (!/^package\/node_modules\/.+\/package\.json$/.test(row.path) || fixed.has(JSON.parse(row.bytes.toString('utf8')).name)) return row;
    const manifest = JSON.parse(row.bytes.toString('utf8')); let changed = false;
    for (const field of ['dependencies', 'optionalDependencies'])
      for (const [name, version] of fixed) if (manifest[field]?.[name] !== undefined && manifest[field][name] !== version) {
        dependents.push({ package: `${manifest.name}@${manifest.version}`, field, name, from: manifest[field][name], to: version });
        manifest[field][name] = version; changed = true;
      }
    return changed ? { ...row, bytes: Buffer.from(JSON.stringify(manifest, null, 2) + '\n') } : row;
  });
  const provenance = { kind: 'caseops-appium-driver-rebundle-v1', name: spec.upstream.name,
    upstreamVersion: spec.upstream.version, localVersion: spec.localVersion, upstreamIntegrity: spec.upstream.integrity,
    advisories: ['GHSA-3g3m-2fjr-6pw4', 'GHSA-g3hv-75wg-m249'], driverLicence, replacements: replaced, dependentSpecs: dependents,
    unchanged: 'All other upstream members are byte-identical; the root package.json changes only version and files.' };
  const manifest = { ...original, version: spec.localVersion, files: [...original.files, spec.provenanceFile] };
  rows = rows.filter(r => r.path !== 'package/package.json');
  rows.push({ path: 'package/package.json', mode: 0o644, bytes: Buffer.from(JSON.stringify(manifest, null, 2) + '\n') },
    { path: `package/${spec.provenanceFile}`, mode: 0o644, bytes: Buffer.from(JSON.stringify(provenance, null, 2) + '\n') });
  const tar = deterministicTar(rows), tarSha256 = sha256(tar);
  if (spec.tarSha256) assert.equal(tarSha256, spec.tarSha256, 'APPIUM_TOOLING_REBUNDLE_DIGEST');
  // The lockfile pins this archive's integrity, so fix the gzip OS byte (unix)
  // rather than inherit the host's; the compressed stream is the pinned Node's.
  const tgz = gzipSync(tar, { level: 9 }); tgz[9] = 3;
  return { tgz, tarSha256, provenance, members: rows.length };
}

// One budget is charged by every listing, metadata observation and byte read,
// including the final reconciliation pass.
export const INVENTORY_LIMITS = Object.freeze({ entries: 100000, bytes: 67108864, milliseconds: 120000 });
function inventoryBudget(limits = INVENTORY_LIMITS) {
  const deadline = Date.now() + limits.milliseconds; let entries = 0, bytes = 0;
  const budget = {
    tick() { assert.ok(Date.now() <= deadline, 'APPIUM_TOOLING_INVENTORY_DEADLINE'); },
    entry(count = 1) { entries += count; assert.ok(entries <= limits.entries, 'APPIUM_TOOLING_INVENTORY_ENTRY_BOUND'); budget.tick(); },
    read(count) { bytes += count; assert.ok(bytes <= limits.bytes, 'APPIUM_TOOLING_INVENTORY_BYTE_BOUND'); budget.tick(); },
    totals: () => ({ entries, bytes }),
  };
  return budget;
}
const FRAME = ['dev', 'ino', 'mode', 'nlink', 'uid', 'gid', 'size', 'mtimeNs', 'ctimeNs'];
// Windows can report lstat dev 0 for a file whose descriptor has a device ID.
const frame = (stat, named = false) => FRAME.filter(key => !(process.platform === 'win32' && named && key === 'dev')).map(key => String(stat[key])).join(':');
function observe(file, budget) { budget.entry(); return fs.lstatSync(file, { bigint: true }); }
function directory(file, budget) {
  const stat = observe(file, budget);
  assert.ok(stat.isDirectory() && !stat.isSymbolicLink(), 'APPIUM_TOOLING_PHYSICAL_DIRECTORY'); return stat;
}
function listing(file, budget) { const names = fs.readdirSync(file).sort(); budget.entry(names.length); return names; }
/** Read a regular file through one descriptor whose identity matches its name throughout. */
function heldFile(file, maxBytes, budget) {
  const named = observe(file, budget);
  assert.ok(named.isFile() && !named.isSymbolicLink() && named.size <= BigInt(maxBytes), 'APPIUM_TOOLING_HELD_FILE');
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0));
  try {
    const held = fs.fstatSync(fd, { bigint: true });
    assert.ok(held.isFile() && frame(held, true) === frame(named, true), 'APPIUM_TOOLING_HELD_FILE');
    const bytes = Buffer.alloc(Number(held.size) + 1); let count = 0;
    while (count < bytes.length) { budget.tick(); const n = fs.readSync(fd, bytes, count, bytes.length - count, count); if (!n) break; count += n; }
    budget.read(count);
    assert.ok(count === Number(held.size) && frame(fs.fstatSync(fd, { bigint: true })) === frame(held), 'APPIUM_TOOLING_HELD_FILE');
    return { bytes: bytes.subarray(0, count), stat: named };
  } finally { fs.closeSync(fd); }
}
const heldJson = (file, maxBytes, budget) => JSON.parse(heldFile(file, maxBytes, budget).bytes.toString('utf8'));
const relativePath = (base, file) => path.relative(base, file).split(path.sep).join('/');

// Known npm/Appium metadata beside packages; every other dot entry refuses.
const APPIUM_CACHE_FILES = Object.freeze(['extensions.yaml', 'package.hash']);
function walkModules(state, owner, depth) {
  assert.ok(depth < 32, 'APPIUM_TOOLING_PACKAGE_DEPTH');
  const modules = path.join(owner, 'node_modules');
  state.directories.set(modules, frame(directory(modules, state.budget))); const names = listing(modules, state.budget);
  state.listings.set(modules, names);
  for (const name of names) {
    const entry = path.join(modules, name);
    if (name === '.bin') state.bins.push(modules);
    else if (name === '.package-lock.json' && depth === 0) {
      const held = heldFile(entry, 16777216, state.budget); state.files.set(entry, frame(held.stat, true));
      state.hidden = JSON.parse(held.bytes.toString('utf8'));
    } else if (name === '.cache' && depth === 0) {
      state.directories.set(entry, frame(directory(entry, state.budget)));
      const cache = listing(entry, state.budget); state.listings.set(entry, cache);
      assert.deepEqual(cache, ['appium'], 'APPIUM_TOOLING_UNKNOWN_METADATA');
      const appium = path.join(entry, 'appium'); state.directories.set(appium, frame(directory(appium, state.budget)));
      const files = listing(appium, state.budget); state.listings.set(appium, files);
      assert.ok(files.every(file => APPIUM_CACHE_FILES.includes(file)), 'APPIUM_TOOLING_UNKNOWN_METADATA');
      for (const file of files) state.files.set(path.join(appium, file), frame(heldFile(path.join(appium, file), 1048576, state.budget).stat, true));
    } else if (name.startsWith('.')) assert.fail('APPIUM_TOOLING_UNKNOWN_METADATA');
    else if (name.startsWith('@')) {
      state.directories.set(entry, frame(directory(entry, state.budget)));
      const scoped = listing(entry, state.budget); state.listings.set(entry, scoped);
      for (const child of scoped) { assert.ok(!child.startsWith('.'), 'APPIUM_TOOLING_UNKNOWN_METADATA'); walkPackage(state, path.join(entry, child), modules, depth); }
    } else walkPackage(state, entry, modules, depth);
  }
}
function walkPackage(state, location, modules, depth) {
  state.directories.set(location, frame(directory(location, state.budget)));
  const key = relativePath(state.root, location), manifestFile = path.join(location, 'package.json');
  if (!fs.existsSync(manifestFile)) {
    // npm leaves empty directories for some bundled optional packages; they
    // hold no code and must match an optional lock entry below.
    const names = listing(location, state.budget); state.listings.set(location, names);
    assert.deepEqual(names, [], 'APPIUM_TOOLING_UNMANIFESTED_PACKAGE');
    state.placeholders.push(key); return;
  }
  const held = heldFile(manifestFile, 1048576, state.budget), manifest = JSON.parse(held.bytes.toString('utf8'));
  state.files.set(manifestFile, frame(held.stat, true));
  state.packages.push({ path: key, name: manifest.name, version: manifest.version, location, modules, bin: manifest.bin });
  const bundle = path.join(location, 'CASEOPS-BUNDLE-SOURCES.json');
  if (fs.existsSync(bundle)) {
    const sources = heldFile(bundle, 1048576, state.budget); state.files.set(bundle, frame(sources.stat, true));
    for (const row of JSON.parse(sources.bytes.toString('utf8')).sourceArchives)
      state.embedded.push({ path: key + '#embedded', name: row.name, version: row.version });
  }
  if (fs.existsSync(path.join(location, 'node_modules'))) walkModules(state, location, depth + 1);
}
function declaredBins(row) {
  if (typeof row.bin === 'string') return { [row.name.split('/').pop()]: row.bin };
  return row.bin && typeof row.bin === 'object' ? row.bin : {};
}
/** Each .bin entry must be the link npm creates for a bin its sibling package declares. */
function verifyBins(state) {
  for (const modules of state.bins) {
    const bin = path.join(modules, '.bin'); state.directories.set(bin, frame(directory(bin, state.budget)));
    const names = listing(bin, state.budget); state.listings.set(bin, names);
    const declared = new Map();
    for (const row of state.packages.filter(p => p.modules === modules))
      for (const [name, target] of Object.entries(declaredBins(row))) declared.set(name, path.resolve(row.location, target));
    for (const name of names) {
      const entry = path.join(bin, name), stat = observe(entry, state.budget);
      if (process.platform === 'win32') {
        assert.ok(stat.isFile() && declared.has(name.replace(/\.(cmd|ps1)$/i, '')), 'APPIUM_TOOLING_UNDECLARED_BIN');
        state.files.set(entry, frame(stat, true)); continue;
      }
      assert.ok(stat.isSymbolicLink() && declared.get(name) === path.resolve(bin, fs.readlinkSync(entry)), 'APPIUM_TOOLING_UNDECLARED_BIN');
      const target = observe(declared.get(name), state.budget);
      assert.ok(target.isFile() && !target.isSymbolicLink(), 'APPIUM_TOOLING_UNDECLARED_BIN');
      state.links.set(entry, frame(stat, true));
    }
  }
}
function currentLibc() { return process.platform !== 'linux' ? null : process.report.getReport().header.glibcVersionRuntime ? 'glibc' : 'musl'; }
// npm's os/cpu/libc rule: a negated value excludes; otherwise positive entries must include it.
const mismatched = (list, value) => Array.isArray(list)
  && (list.includes('!' + value) || (list.some(item => !item.startsWith('!')) && !list.includes(value)));
export function platformExcluded(entry) {
  return mismatched(entry.os, process.platform) || mismatched(entry.cpu, process.arch)
    || (Array.isArray(entry.libc) && (currentLibc() === null || mismatched(entry.libc, currentLibc())));
}
/** Reconcile installed packages and placeholders with the lockfile and npm's hidden lock. */
function reconcileLock(state, lock) {
  const installed = new Map(state.packages.map(row => [row.path, row])), placeholders = new Set(state.placeholders), absentOptional = [];
  assert.equal(installed.size, state.packages.length, 'APPIUM_TOOLING_DUPLICATE_PACKAGE_PATH');
  for (const [key, entry] of Object.entries(lock.packages)) {
    if (!key) continue;
    const row = installed.get(key);
    if (row) {
      assert.ok(entry.version === row.version && (entry.name ?? key.split('node_modules/').pop()) === row.name, 'APPIUM_TOOLING_LOCK_IDENTITY_MISMATCH');
    } else if (placeholders.has(key)) assert.equal(entry.optional, true, 'APPIUM_TOOLING_PLACEHOLDER_NOT_OPTIONAL');
    else { assert.ok(entry.optional === true && platformExcluded(entry), 'APPIUM_TOOLING_LOCKED_PACKAGE_ABSENT'); absentOptional.push(key); }
  }
  for (const key of [...installed.keys(), ...placeholders]) assert.ok(Object.hasOwn(lock.packages, key), 'APPIUM_TOOLING_UNLOCKED_PACKAGE');
  if (state.hidden) {
    const hidden = Object.entries(state.hidden.packages).filter(([key]) => key);
    for (const [key, entry] of hidden) assert.ok(installed.get(key)?.version === entry.version || placeholders.has(key), 'APPIUM_TOOLING_HIDDEN_LOCK_MISMATCH');
    const listed = new Set(hidden.map(([key]) => key));
    for (const key of installed.keys()) assert.ok(listed.has(key), 'APPIUM_TOOLING_HIDDEN_LOCK_MISMATCH');
  }
  return absentOptional.sort();
}
/** Re-observe every discovered listing and identity; any insertion, removal or change refuses. */
function reconcileNamespace(state) {
  for (const [dir, names] of state.listings) assert.deepEqual(listing(dir, state.budget), names, 'APPIUM_TOOLING_PHYSICAL_DRIFT');
  for (const [dir, before] of state.directories) assert.equal(frame(directory(dir, state.budget)), before, 'APPIUM_TOOLING_PHYSICAL_DRIFT');
  for (const [file, before] of [...state.files, ...state.links]) assert.equal(frame(observe(file, state.budget), true), before, 'APPIUM_TOOLING_PHYSICAL_DRIFT');
}
/**
 * Complete physical inventory of a root-present install: nested, bundled and
 * embedded identities, reconciled with its lockfile and re-observed at the end.
 */
export function physicalAdvisoryInventory(root, { lockfile = path.join(root, 'package-lock.json'), limits = INVENTORY_LIMITS, afterDiscovery } = {}) {
  const budget = inventoryBudget(limits);
  assert.ok(path.isAbsolute(root) && fs.existsSync(root) && fs.existsSync(path.join(root, 'node_modules')), 'APPIUM_TOOLING_PHYSICAL_ROOT_REQUIRED');
  const state = { root, budget, directories: new Map(), listings: new Map(), files: new Map(), links: new Map(),
    packages: [], embedded: [], placeholders: [], bins: [], hidden: null };
  state.directories.set(root, frame(directory(root, budget)));
  const heldLock = heldFile(lockfile, 16777216, budget), lock = JSON.parse(heldLock.bytes.toString('utf8'));
  state.files.set(lockfile, frame(heldLock.stat, true));
  assert.equal(lock.lockfileVersion, 3, 'APPIUM_TOOLING_LOCKFILE_VERSION');
  walkModules(state, root, 0); verifyBins(state);
  const absentOptional = reconcileLock(state, lock);
  afterDiscovery?.();
  reconcileNamespace(state);
  const rows = [...state.packages.map(({ path: key, name, version }) => ({ path: key, name, version })), ...state.embedded];
  return { ...advisoryInventory(rows), emptyPlaceholders: state.placeholders.sort(), absentOptional,
    binLinks: state.links.size, observations: budget.totals() };
}
/** Every package identity recorded by an npm v3 lockfile. */
export function lockedAdvisoryInventory(lockfile, { limits = INVENTORY_LIMITS } = {}) {
  const lock = heldJson(lockfile, 16777216, inventoryBudget(limits));
  assert.equal(lock.lockfileVersion, 3, 'APPIUM_TOOLING_LOCKFILE_VERSION');
  return advisoryInventory(Object.entries(lock.packages).filter(([key]) => key)
    .map(([key, value]) => ({ path: key, name: value.name ?? key.split('node_modules/').pop(), version: value.version })));
}
export function advisoryInventory(rows) {
  const graph = {};
  for (const row of rows) {
    assert.match(row.name, /^(?:@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/i, 'APPIUM_TOOLING_PACKAGE_NAME');
    assert.match(row.version, /^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$/i, 'APPIUM_TOOLING_PACKAGE_VERSION');
    (graph[row.name] ??= new Set()).add(row.version);
  }
  return { rows, names: Object.keys(graph).length,
    graph: Object.fromEntries(Object.entries(graph).sort().map(([name, versions]) => [name, [...versions].sort()])) };
}

export const DOWNLOAD_LIMITS = Object.freeze({ archiveBytes: 67108864, totalBytes: 201326592, milliseconds: 600000 });
/** One deadline and byte budget shared by every official archive download. */
export function downloadSession(limits = DOWNLOAD_LIMITS, request = globalThis.fetch, { environment = {} } = {}) {
  const deadline = Date.now() + limits.milliseconds; let total = 0;
  return async function downloadOfficialArchive(url, integrity) {
    assert.notEqual(process.env.NODE_TLS_REJECT_UNAUTHORIZED, '0', 'APPIUM_TOOLING_TLS_VERIFICATION_REQUIRED');
    // A caller may impose an additional refusal, never replace the live guard.
    assert.notEqual(environment.NODE_TLS_REJECT_UNAUTHORIZED, '0', 'APPIUM_TOOLING_TLS_VERIFICATION_REQUIRED');
    assert.ok(url.startsWith('https://registry.npmjs.org/') && /^sha512-[A-Za-z0-9+/]{86}==$/.test(integrity), 'APPIUM_TOOLING_OFFICIAL_ARCHIVE_REQUIRED');
    const remaining = deadline - Date.now(); assert.ok(remaining > 0, 'APPIUM_TOOLING_DOWNLOAD_DEADLINE');
    const response = await request(url, { redirect: 'error', headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' },
      signal: AbortSignal.timeout(remaining) });
    if (response.status !== 200) { await response.body?.cancel().catch(() => {}); assert.fail('APPIUM_TOOLING_DOWNLOAD_STATUS'); }
    const declared = Number(response.headers.get('content-length') ?? NaN);
    const reader = response.body.getReader(), chunks = []; let length = 0;
    try {
      assert.ok(!(declared > limits.archiveBytes), 'APPIUM_TOOLING_DOWNLOAD_BOUND');
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        length += value.length; total += value.length;
        assert.ok(length <= limits.archiveBytes && total <= limits.totalBytes, 'APPIUM_TOOLING_DOWNLOAD_BOUND');
        assert.ok(Date.now() < deadline, 'APPIUM_TOOLING_DOWNLOAD_DEADLINE'); chunks.push(Buffer.from(value));
      }
    } catch (error) { await reader.cancel().catch(() => {}); throw error; }
    finally { reader.releaseLock(); }
    const bytes = Buffer.concat(chunks, length); assert.equal(sri(bytes), integrity, 'APPIUM_TOOLING_DOWNLOAD_INTEGRITY');
    return bytes;
  };
}
function run(command, args, options) {
  const child = spawn(command, args, { stdio: 'inherit', windowsHide: true, ...options });
  return new Promise((resolve, reject) => { child.once('error', reject);
    child.once('exit', (status, signal) => signal ? reject(new Error('APPIUM_TOOLING_CHILD_SIGNAL')) : resolve(status)); });
}
export const DRIVER_LIST_LIMITS = Object.freeze({ entries: 512, bytes: 1048576, milliseconds: 60000 });
/** Keep the child's original stdout descriptor until its JSON and name are reconciled. */
export async function readInstalledDrivers(runtime, { limits = DRIVER_LIST_LIMITS } = {}) {
  limits = Object.freeze({ entries: limits.entries, bytes: limits.bytes, milliseconds: limits.milliseconds });
  for (const key of Object.keys(DRIVER_LIST_LIMITS))
    assert.ok(Number.isSafeInteger(limits[key]) && limits[key] >= 0 && limits[key] <= DRIVER_LIST_LIMITS[key], 'APPIUM_TOOLING_DRIVER_LIST_LIMIT');
  const deadline = Date.now() + limits.milliseconds, budget = inventoryBudget(limits);
  const root = path.resolve(runtime), listed = path.join(root, 'driver-list.json');
  assert.equal(runtime, root, 'APPIUM_TOOLING_DRIVER_LIST_ROOT');
  const identity = stat => ['dev', 'ino', 'mode', 'nlink', 'uid', 'gid'].map(key => String(stat[key])).join(':');
  const directoryIdentity = stat => ['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(stat[key])).join(':');
  const ancestors = []; let current = root;
  while (true) {
    ancestors.push([current, directoryIdentity(directory(current, budget))]);
    const parent = path.dirname(current); if (parent === current) break; current = parent;
  }
  assert.equal(fs.realpathSync(root), root, 'APPIUM_TOOLING_DRIVER_LIST_ROOT');
  const list = fs.openSync(listed, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
  try {
    const original = fs.fstatSync(list, { bigint: true });
    const owner = process.getuid?.();
    assert.ok(original.isFile() && original.nlink === 1n && (owner === undefined || original.uid === BigInt(owner)) &&
      (process.platform === 'win32' || (original.mode & 0o777n) === 0o600n), 'APPIUM_TOOLING_DRIVER_LIST_FILE');
    const names = listing(root, budget);
    const reconcile = expected => {
      for (const [file, before] of ancestors)
        assert.equal(directoryIdentity(directory(file, budget)), before, 'APPIUM_TOOLING_DRIVER_LIST_NAMESPACE');
      assert.deepEqual(listing(root, budget), names, 'APPIUM_TOOLING_DRIVER_LIST_NAMESPACE');
      const named = observe(listed, budget), held = fs.fstatSync(list, { bigint: true });
      assert.ok(named.isFile() && !named.isSymbolicLink() && held.isFile() && held.nlink === 1n &&
        identity(held) === identity(original) && frame(named, true) === frame(held, true) &&
        (!expected || frame(held) === frame(expected)), 'APPIUM_TOOLING_DRIVER_LIST_CHANGED');
      return held;
    };
    reconcile(original);
    const remaining = deadline - Date.now(); assert.ok(remaining > 0, 'APPIUM_TOOLING_DRIVER_LIST_DEADLINE');
    const status = await run(process.execPath, [path.join(root, 'node_modules/appium/index.js'), 'driver', 'list', '--installed', '--json'],
      { cwd: root, env: { ...process.env, APPIUM_HOME: root }, stdio: ['ignore', list, 'inherit'], timeout: remaining, killSignal: 'SIGKILL' });
    assert.equal(status, 0, 'APPIUM_TOOLING_DRIVER_LIST');
    assert.ok(Date.now() < deadline, 'APPIUM_TOOLING_DRIVER_LIST_DEADLINE');
    const written = reconcile();
    assert.ok(written.size <= BigInt(limits.bytes), 'APPIUM_TOOLING_DRIVER_LIST_BOUND');
    const bytes = Buffer.alloc(Number(written.size) + 1); let count = 0;
    while (count < bytes.length) {
      budget.tick(); const read = fs.readSync(list, bytes, count, Math.min(65536, bytes.length - count), count);
      budget.read(read); if (!read) break; count += read;
    }
    assert.equal(count, Number(written.size), 'APPIUM_TOOLING_DRIVER_LIST_CHANGED');
    reconcile(written);
    const installed = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(0, count)));
    assert.ok(installed && typeof installed === 'object' && !Array.isArray(installed), 'APPIUM_TOOLING_DRIVER_IDENTITY');
    for (const spec of DRIVER_REBUNDLES)
      assert.ok(installed[spec.driver]?.installed === true && installed[spec.driver].version === spec.localVersion, 'APPIUM_TOOLING_DRIVER_IDENTITY');
    reconcile(written); budget.tick();
    return installed;
  } finally { fs.closeSync(list); }
}
/**
 * Install the repaired Appium project into a new runtime (also its APPIUM_HOME)
 * and audit its locked and physical graphs.
 */
export async function prepareAppiumTooling(runtime, { request = globalThis.fetch } = {}) {
  assert.equal(process.versions.node, '24.15.0', 'APPIUM_TOOLING_PINNED_NODE_REQUIRED');
  assert.ok(path.isAbsolute(runtime) && !fs.existsSync(runtime), 'APPIUM_TOOLING_NEW_RUNTIME_REQUIRED');
  const relative = path.relative(REPO, runtime);
  assert.ok(relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative), 'APPIUM_TOOLING_RUNTIME_OUTSIDE_REPOSITORY');
  const vendor = path.join(runtime, 'vendor'); fs.mkdirSync(vendor, { recursive: true, mode: 0o700 });
  const glob = fs.readFileSync(path.join(REPO, VENDORED_GLOB.relative)); assert.equal(sha256(glob), VENDORED_GLOB.sha256, 'APPIUM_TOOLING_VENDORED_DIGEST');
  fs.writeFileSync(path.join(vendor, path.basename(VENDORED_GLOB.relative)), glob, { flag: 'wx' });

  const archives = { [VENDORED_GLOB.name]: glob }, download = downloadSession(DOWNLOAD_LIMITS, request);
  for (const item of DRIVER_REPLACEMENTS.filter(r => !r.vendored)) archives[item.name] = await download(registry(item.name, item.version), item.integrity);
  const drivers = {};
  for (const spec of DRIVER_REBUNDLES) {
    archives[spec.upstream.name] = await download(registry(spec.upstream.name, spec.upstream.version), spec.upstream.integrity);
    const rebuilt = rebundleDriver(archives, spec), output = path.join(vendor, `${spec.upstream.name}-${spec.localVersion}.tgz`);
    assert.equal(sri(rebuilt.tgz), spec.tgzIntegrity, 'APPIUM_TOOLING_REBUNDLE_INTEGRITY');
    fs.writeFileSync(output, rebuilt.tgz, { flag: 'wx', mode: 0o600 });
    drivers[spec.driver] = { path: output, tgzSha256: sha256(rebuilt.tgz), tarSha256: rebuilt.tarSha256, members: rebuilt.members, provenance: rebuilt.provenance };
  }

  for (const name of ['package.json', 'package-lock.json'])
    fs.copyFileSync(path.join(REPO, APPIUM_TOOLING_PROJECT, name), path.join(runtime, name), fs.constants.COPYFILE_EXCL);
  const npm = [path.join(REPO, 'scripts/mobile/npm-tooling.mjs'), 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--fetch-timeout=60000', '--fetch-retries=1'];
  const installStatus = await run(process.execPath, npm, { cwd: runtime });
  assert.equal(installStatus, 0, 'APPIUM_TOOLING_INSTALL');
  await readInstalledDrivers(runtime);

  const inventories = { locked: lockedAdvisoryInventory(path.join(runtime, 'package-lock.json')), physical: physicalAdvisoryInventory(runtime) };
  const audits = {};
  for (const [key, inventory] of Object.entries(inventories)) {
    const result = await auditNpmInventory(inventory, request);
    audits[key] = { packages: inventory.rows.length, names: inventory.names, emptyPlaceholders: inventory.emptyPlaceholders,
      absentOptional: inventory.absentOptional, binLinks: inventory.binLinks, observations: inventory.observations,
      advisoryResponseSha256: result.advisoryResponseSha256, advisories: 0 };
  }
  const receipt = { kind: 'caseops-appium-tooling-v1', node: process.versions.node, runtime, appiumHome: runtime,
    drivers, audits, observedAt: new Date().toISOString(), nativeExecution: 'not-run' };
  fs.writeFileSync(path.join(runtime, 'receipt.json'), JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  return receipt;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    assert.ok(process.argv.length === 4 && process.argv[2] === 'prepare', 'Usage: node scripts/mobile/appium-tooling.mjs prepare /absolute/new-runtime');
    console.log(JSON.stringify(await prepareAppiumTooling(process.argv[3]), null, 2));
  } catch (error) {
    const label = /^(APPIUM_TOOLING|NPM_TOOLING)_[A-Z_]+$/.test(error?.message || '') ? error.message : 'APPIUM_TOOLING_REFUSED';
    console.error(label); process.exitCode = 1;
  }
}
