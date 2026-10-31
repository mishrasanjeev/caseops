import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
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


// The mobile-only glob backport shares this already selected installed-artifact
// module; the original deepmerge graph and every original assertion stay intact.
const globVendor = path.join(app, 'vendor/glob-14.0.2-caseops.1');
const globProvenance = json(path.join(globVendor, 'provenance.json'));
const globArchiveSpec = 'file:vendor/glob-14.0.2-caseops.1/glob-14.0.2-caseops.1.tgz';

function mobileMatcherCopies() {
  const found = { glob: [], minimatch: [] }, visited = new Set();
  let charged = 0;
  function nodeModules(directory) {
    assert.ok(++charged <= 20000, 'COMPLETE_MOBILE_MATCHER_DISCOVERY_BOUND');
    let metadata;
    try { metadata = fs.lstatSync(directory); }
    catch (error) { if (error.code === 'ENOENT') return; throw error; }
    assert.equal(metadata.isSymbolicLink(), false);
    assert.equal(metadata.isDirectory(), true);
    assert.equal(visited.has(directory), false);
    visited.add(directory);
    function member(child) {
      assert.ok(++charged <= 20000, 'COMPLETE_MOBILE_MATCHER_DISCOVERY_BOUND');
      const frame = fs.lstatSync(child);
      assert.equal(frame.isSymbolicLink(), false);
      assert.equal(frame.isDirectory(), true);
      const identity = json(path.join(child, 'package.json'));
      if (Object.hasOwn(found, identity.name)) found[identity.name].push(child);
      nodeModules(path.join(child, 'node_modules'));
    }
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.name.startsWith('.')) continue;
      const child = path.join(directory, entry.name);
      assert.equal(entry.isSymbolicLink(), false);
      assert.equal(entry.isDirectory(), true);
      if (entry.name.startsWith('@')) {
        for (const name of fs.readdirSync(child)) member(path.join(child, name));
      } else member(child);
    }
  }
  nodeModules(path.join(app, 'node_modules'));
  for (const copies of Object.values(found)) copies.sort();
  return found;
}
function globPackageFiles(directory) {
  const names = [];
  function walk(current) {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      if (current === directory && entry.name === 'node_modules') continue;
      const file = path.join(current, entry.name);
      assert.equal(entry.isSymbolicLink(), false);
      if (entry.isDirectory()) walk(file);
      else { assert.equal(entry.isFile(), true); names.push(path.relative(directory, file).split(path.sep).join('/')); }
      assert.ok(names.length <= 128, 'FINITE_GLOB_PACKAGE_FILES');
    }
  }
  walk(directory);
  return names.sort();
}

test('every mobile locked hidden-lock and physical glob or minimatch copy is the exact fixed artifact', () => {
  const declared = json(path.join(app, 'package.json'));
  assert.equal(declared.devDependencies.glob, globArchiveSpec);
  assert.equal(declared.overrides.glob, '$glob');
  assert.equal(declared.overrides.minimatch, '11.0.1');
  const lock = json(path.join(app, 'package-lock.json'));
  const hidden = json(path.join(app, 'node_modules/.package-lock.json'));
  const physical = mobileMatcherCopies();
  for (const name of ['glob', 'minimatch']) {
    const rows = Object.entries(lock.packages).filter(([file]) => file.endsWith('/' + name));
    assert.ok(rows.length > 0);
    assert.deepEqual(physical[name], rows.map(([file]) => path.join(app, file)).sort());
    assert.deepEqual(Object.keys(hidden.packages).filter(file => file.endsWith('/' + name)).sort(), rows.map(([file]) => file).sort());
    for (const [file, identity] of rows) {
      const directory = path.join(app, file);
      assert.equal(identity.version, name === 'glob' ? '14.0.2-caseops.1' : '11.0.1');
      const actual = json(path.join(directory, 'package.json'));
      assert.equal(actual.name, name);
      assert.equal(actual.version, identity.version);
      for (const field of ['version', 'resolved', 'integrity']) assert.equal(hidden.packages[file][field], identity[field]);
      if (name === 'glob') {
        assert.equal(identity.resolved, globArchiveSpec);
        assert.equal(identity.integrity, globProvenance.artifact.integrity);
        assert.deepEqual(globPackageFiles(directory), Object.keys(globProvenance.packageFiles).sort());
        for (const [member, digest] of Object.entries(globProvenance.packageFiles)) assert.equal(sha(bytes(path.join(directory, member))), digest);
      }
    }
  }
  const archive = bytes(path.join(globVendor, globProvenance.artifact.filename));
  assert.equal(sha(archive), '6a1eb71056c3c6138d30c06c4c9e0877b4a9bf79ee66c684a9405c6c4442ae25');
  assert.equal(sha(archive), globProvenance.artifact.sha256);
  assert.equal('sha512-' + createHash('sha512').update(archive).digest('base64'), globProvenance.artifact.integrity);
});

test('both installed default glob bundles contain fixed matcher source and actual method bounds', async () => {
  const directory = path.dirname(require.resolve('glob/package.json'));
  assert.equal(require.resolve('glob'), path.join(directory, 'dist/commonjs/index.min.js'));
  const manifest = json(path.join(directory, 'package.json'));
  assert.equal(manifest.exports['.'].import.default, './dist/esm/index.min.js');
  assert.equal(manifest.exports['.'].require.default, './dist/commonjs/index.min.js');
  const oldSources = new Set(['624aa1c8da8c65303c7577450fc608ced3309906401546dfeaeee3a7c2100362', '6c8a59770ce01698ea22b1e6d1b4df403017c5af1b17c155f42578058781c16c', 'fb8314de5dd6c29ad1cb44c8822077aa1baf1ac514eaae2cc4d9b9c5414de13c']);
  for (const format of ['commonjs', 'esm']) {
    const file = path.join(directory, 'dist', format, 'index.min.js');
    const code = bytes(file).toString('utf8');
    assert.equal(sha(bytes(file)), globProvenance.packageFiles['dist/' + format + '/index.min.js']);
    assert.match(code, /braceExpandMax/);
    assert.match(code, /secondPhasePreProcess\([^)]*\)\{[^{}]{0,200}(?:1000|1e3)/);
    const map = json(file + '.map');
    let fixedMinimatch = false, fixedMatcher = false;
    for (let i = 0; i < map.sources.length; i++) {
      if (map.sourcesContent[i] === null) continue;
      const digest = sha(Buffer.from(map.sourcesContent[i]));
      assert.equal(oldSources.has(digest), false);
      if (map.sources[i].endsWith('/minimatch/src/index.ts')) {
        assert.equal(digest, 'eff2f23257708f4bd102cf94d746c8f26f5887e993e6de0f3c139bdae924c37b'); fixedMinimatch = true;
      }
      if (map.sources[i].endsWith('/@isaacs/nonrecursive-glob-match/src/index.ts')) fixedMatcher = true;
    }
    assert.equal(fixedMinimatch, true);
    assert.equal(fixedMatcher, true);
  }
  const cjs = require('glob');
  const esm = await import(pathToFileURL(path.join(directory, 'dist/esm/index.min.js')).href);
  for (const api of [cjs, esm]) for (const name of ['glob', 'globSync', 'globStream', 'globIterate', 'Glob', 'hasMagic', 'escape', 'unescape']) assert.equal(typeof api[name], 'function');
});

test('fixed mobile glob keeps actual Expo consumers ordinary matching and bounded cancellation', async () => {
  const os = await import('node:os');
  const directory = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'caseops-fixed-glob-'));
  try {
    fs.mkdirSync(path.join(directory, 'src'));
    for (const name of ['src/a.ts', 'src/b.js', 'src/.gitignore', '.gitignore']) fs.writeFileSync(path.join(directory, name), 'synthetic\n');
    const expoRequire = createRequire(require.resolve('expo/package.json'));
    const cliPath = path.join(path.dirname(expoRequire.resolve('@expo/cli/package.json')), 'build/src/utils/glob.js');
    const cli = require(cliPath);
    assert.deepEqual(await cli.everyMatchAsync('src/**/*.ts', { cwd: directory, nodir: true }), ['src/a.ts']);
    assert.deepEqual(await cli.anyMatchAsync('no-match-*', { cwd: directory }), []);
    const fingerprintPath = path.join(path.dirname(require.resolve('@expo/fingerprint/package.json')), 'build/utils/Path.js');
    const fingerprint = require(fingerprintPath);
    const objects = fingerprint.buildPathMatchObjects(['**/*.ts', '!src/a.ts']);
    assert.equal(fingerprint.isIgnoredPathWithMatchObjects('src/a.ts', objects), false);
    assert.equal(fingerprint.isIgnoredPathWithMatchObjects('src/c.ts', objects), true);
    const glob = require('glob');
    assert.deepEqual(glob.globSync('src/*.{ts,js}', { cwd: directory, nodir: true }).sort(), ['src/a.ts', 'src/b.js']);
    const reason = Error('OWNED_GLOB_CANCELLATION');
    await assert.rejects(glob.glob('**/*', { cwd: directory, signal: AbortSignal.abort(reason) }), error => error === reason);
    const minimatch = require('minimatch');
    const match = new minimatch.Minimatch('a/**/../b/**/../c', { optimizationLevel: 2, braceExpandMax: 2 });
    assert.ok(match.set.length <= 2);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('glob private artifact preserves complete embedded licences without changing the deepmerge exception', () => {
  assert.equal(globProvenance.privateCompatibilityBackport, true);
  assert.equal(globProvenance.officialFixedArtifact, false);
  assert.equal(globProvenance.auditExceptionAdded, false);
  const attributes = bytes(path.join(repo, '.gitattributes')).toString('utf8');
  for (const rule of ['*.tgz -text', '*.json text eol=lf', '*.md text eol=lf', '*.txt text eol=lf'])
    assert.equal(attributes.includes('apps/mobile/vendor/glob-14.0.2-caseops.1/' + rule), true);
  const names = globProvenance.embeddedPackages.map(row => row.name).sort();
  assert.deepEqual(names, ['@isaacs/nonrecursive-glob-match', 'balanced-match', 'brace-expansion', 'glob', 'lru-cache', 'minimatch', 'minipass', 'path-scurry']);
  const licences = bytes(path.join(globVendor, 'BUNDLED-LICENSES.txt'));
  assert.equal(sha(licences), globProvenance.packageFiles['CASEOPS-BUNDLE-LICENSES.txt']);
  assert.equal(bytes(path.join(app, 'BUILD_TOOL_NOTICES.txt')).includes(licences), true);
  for (const row of globProvenance.embeddedPackages) {
    assert.equal(row.officialTarball.startsWith('https://registry.npmjs.org/'), true);
    assert.ok(row.sha256.match(/^[a-f0-9]{64}$/));
    assert.equal(licences.includes(Buffer.from(row.name + ' ' + row.version)), true);
  }
  assert.equal(provenance.originalAdvisory, 'https://github.com/advisories/GHSA-gcqx-w48m-w2h4');
  assert.equal(provenance.auditExceptionAdded, false);
});
