import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { readBuildInput } from './build-acceptance.mjs';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const app = path.join(repo, 'apps/mobile');
const vendor = path.join(app, 'vendor/deepmerge-4.3.1-caseops.1');
const require = createRequire(path.join(app, 'package.json'));
const scope = process.env.CASEOPS_MOBILE_DEPENDENCY_SCOPE ?? 'root-and-mobile';
assert.ok(scope === 'mobile-only' || scope === 'root-and-mobile', 'EXACT_INSTALLED_DEPENDENCY_SCOPE_REQUIRED');
const graphRoots = scope === 'mobile-only' ? [app] : [repo, app];
const bytes = file => readBuildInput(file, 1048576);
const json = file => JSON.parse(bytes(file).toString('utf8'));
const sha = body => createHash('sha256').update(body).digest('hex');
const provenance = json(path.join(vendor, 'provenance.json'));
const archiveSpec = 'file:vendor/deepmerge-4.3.1-caseops.1/deepmerge-4.3.1-caseops.1.tgz';

function physicalCopies() {
  const copies = new Set(), visited = new Set();
  let charged = 0;
  function packageDirectory(directory) {
    assert.ok(++charged <= 20000, 'COMPLETE_INSTALLED_DISCOVERY_BOUND');
    const metadata = fs.lstatSync(directory);
    if (metadata.isSymbolicLink()) {
      assert.equal(directory, path.join(repo, 'node_modules/@caseops/web'));
      assert.equal(fs.realpathSync(directory), path.join(repo, 'apps/web'));
      return;
    }
    assert.equal(metadata.isDirectory(), true);
    const identity = json(path.join(directory, 'package.json'));
    if (identity.name === 'deepmerge') copies.add(directory);
    nodeModules(path.join(directory, 'node_modules'));
  }
  function nodeModules(directory) {
    assert.ok(++charged <= 20000, 'COMPLETE_INSTALLED_DISCOVERY_BOUND');
    let metadata;
    try { metadata = fs.lstatSync(directory); }
    catch (error) { if (error.code === 'ENOENT') return; throw error; }
    assert.equal(metadata.isSymbolicLink(), false);
    assert.equal(metadata.isDirectory(), true);
    assert.equal(visited.has(directory), false);
    visited.add(directory);
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      const child = path.join(directory, entry.name);
      if (entry.name.startsWith('@')) {
        assert.equal(entry.isDirectory(), true);
        for (const name of fs.readdirSync(child)) packageDirectory(path.join(child, name));
      } else packageDirectory(child);
    }
  }
  const roots = graphRoots.map(base => path.join(base, 'node_modules'));
  if (scope === 'root-and-mobile') roots.push(path.join(repo, 'apps/web/node_modules'));
  for (const directory of roots) {
    nodeModules(directory);
  }
  return [...copies].sort();
}

function packageFiles(directory) {
  const names = [];
  function walk(current) {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const file = path.join(current, entry.name);
      assert.equal(entry.isSymbolicLink(), false);
      if (entry.isDirectory()) walk(file);
      else { assert.equal(entry.isFile(), true); names.push(path.relative(directory, file).split(path.sep).join('/')); }
      assert.ok(names.length <= 64);
    }
  }
  walk(directory);
  return names.sort();
}

test('every locked hidden-lock and physically installed deepmerge copy is the reviewed private archive', () => {
  const declared = json(path.join(app, 'package.json'));
  assert.equal(declared.devDependencies.deepmerge, archiveSpec);
  assert.equal(declared.overrides.deepmerge, '$deepmerge');
  const expected = [];
  for (const base of graphRoots) {
    const lock = json(path.join(base, 'package-lock.json'));
    const hidden = json(path.join(base, 'node_modules/.package-lock.json'));
    const locked = Object.entries(lock.packages).filter(([name]) => name.endsWith('/deepmerge'));
    const installed = Object.entries(hidden.packages).filter(([name]) => name.endsWith('/deepmerge'));
    assert.deepEqual(locked.map(([name]) => name).sort(), installed.map(([name]) => name).sort());
    for (const [name, record] of locked) {
      const directory = path.join(base, name), actual = json(path.join(directory, 'package.json'));
      expected.push(directory);
      assert.equal(record.version, '4.3.1-caseops.1');
      assert.equal(record.resolved, archiveSpec);
      assert.equal(record.integrity, provenance.tarball.integrity);
      for (const field of ['version', 'resolved', 'integrity']) assert.equal(hidden.packages[name][field], record[field]);
      assert.equal(actual.name, 'deepmerge');
      assert.equal(actual.version, record.version);
      assert.equal(actual.private, true);
      assert.equal(actual.license, 'MIT');
      assert.equal(actual.caseopsCompatibilityBackport.upstreamFixedRelease, false);
      assert.deepEqual(packageFiles(directory), Object.keys(provenance.packageFiles).sort());
      for (const [member, digest] of Object.entries(provenance.packageFiles)) assert.equal(sha(bytes(path.join(directory, member))), digest);
    }
  }
  assert.deepEqual(expected, [path.join(app, 'node_modules/deepmerge')]);
  assert.deepEqual(physicalCopies(), expected);
  const archive = bytes(path.join(vendor, provenance.tarball.filename));
  assert.equal(sha(archive), provenance.tarball.sha256);
  assert.equal('sha512-' + createHash('sha512').update(archive).digest('base64'), provenance.tarball.integrity);
});

test('actual installed Expo consumer resolves the protected runtime with unchanged SDK identity and retained MIT', () => {
  assert.equal(json(require.resolve('expo/package.json')).version, '58.0.21');
  assert.equal(json(require.resolve('@expo/config/package.json')).version, '58.0.9');
  const consumer = createRequire(require.resolve('@expo/config'));
  const resolved = consumer.resolve('deepmerge');
  assert.equal(resolved, path.join(app, 'node_modules/deepmerge/dist/cjs.js'));
  assert.equal(sha(bytes(resolved)), provenance.packageFiles['dist/cjs.js']);
  const merge = consumer('deepmerge');
  const result = merge({ session: null }, JSON.parse('{"session":{"__proto__":{"caseopsSyntheticAdmin":true}}}'));
  assert.equal(Object.getPrototypeOf(result.session), Object.prototype);
  assert.equal(result.session.caseopsSyntheticAdmin, undefined);
  assert.equal(Object.hasOwn(result.session, '__proto__'), true);
  assert.equal(Object.prototype.caseopsSyntheticAdmin, undefined);
  const licence = bytes(path.join(app, 'node_modules/deepmerge/license.txt'));
  assert.equal(sha(licence), provenance.originalFiles['license.txt']);
  assert.equal(bytes(path.join(app, 'BUILD_TOOL_NOTICES.txt')).toString('utf8').includes(licence.toString('utf8')), true);
  assert.equal(provenance.originalAuditAffectedNodes, 7);
  assert.equal(provenance.auditExceptionAdded, false);
});
