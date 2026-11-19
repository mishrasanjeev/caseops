import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { readFixtureBytes } from './fixtures/picomatch-byte-input.mjs';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const app = path.join(repo, 'apps/mobile');
const vendor = path.join(app, 'vendor/picomatch-4.0.7-caseops.1');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
let charged = 0;
function bytes(file, limit = 1048576) {
  const value = readFixtureBytes(file, limit); charged += value.length;
  assert.ok(charged <= 16777216, 'Installed manifest/source inventory byte bound');
  return value;
}
const json = file => JSON.parse(bytes(file).toString('utf8'));
const scope = process.env.CASEOPS_MOBILE_DEPENDENCY_SCOPE ?? 'root-and-mobile';
assert.ok(['root-only', 'mobile-only', 'root-and-mobile'].includes(scope), 'Explicit installed graph scope required');
const provenance = json(path.join(vendor, 'provenance.json'));
const graphRoots = scope === 'root-only' ? [repo] : scope === 'mobile-only' ? [app] : [repo, app];
const locks = graphRoots.map(root => ({ root, lock: json(path.join(root, 'package-lock.json')) }));
const physical = new Set(), visited = new Set();
let entries = 0;

function discover(directory) {
  assert.ok(++entries <= 20000, 'Installed discovery entry bound');
  let metadata;
  try { metadata = fs.lstatSync(directory); }
  catch (error) { if (error.code === 'ENOENT') return; throw error; }
  assert.equal(metadata.isSymbolicLink(), false);
  assert.equal(metadata.isDirectory(), true);
  assert.equal(visited.has(directory), false); visited.add(directory);
  function packageDirectory(candidate) {
    assert.ok(++entries <= 20000, 'Installed discovery entry bound');
    const value = fs.lstatSync(candidate);
    if (value.isSymbolicLink()) {
      assert.equal(candidate, path.join(repo, 'node_modules/@caseops/web'));
      assert.equal(fs.realpathSync(candidate), fs.realpathSync(path.join(repo, 'apps/web')));
      return;
    }
    assert.equal(value.isDirectory(), true);
    const identity = json(path.join(candidate, 'package.json'));
    if (identity.name === 'picomatch' || path.basename(candidate) === 'picomatch') {
      assert.equal(identity.name, 'picomatch');
      physical.add(candidate);
    }
    discover(path.join(candidate, 'node_modules'));
  }
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.name.startsWith('.')) continue;
    const candidate = path.join(directory, entry.name);
    if (entry.name.startsWith('@')) {
      assert.equal(entry.isDirectory(), true);
      for (const name of fs.readdirSync(candidate)) packageDirectory(path.join(candidate, name));
    } else packageDirectory(candidate);
  }
}
for (const root of graphRoots) discover(path.join(root, 'node_modules'));
if (graphRoots.includes(repo)) discover(path.join(repo, 'apps/web/node_modules'));

test('all locked and physical matcher copies use the reviewed private archive', () => {
  const expected = new Set();
  for (const { root, lock } of locks) {
    const rows = Object.entries(lock.packages).filter(([name]) => name.endsWith('node_modules/picomatch'));
    assert.ok(rows.length > 0);
    for (const [name, row] of rows) {
      assert.equal(row.version, '4.0.7-caseops.1', name);
      assert.equal(row.integrity, provenance.artifactIntegrity, name);
      assert.match(row.resolved, /^file:/);
      const archive = path.resolve(root, row.resolved.slice(5));
      assert.equal(archive, path.join(vendor, 'picomatch-4.0.7-caseops.1.tgz'));
      expected.add(path.resolve(root, name));
    }
  }
  assert.deepEqual([...physical].sort(), [...expected].sort());
});

test('installed runtime, manifest, MIT and modification notice bytes all match the source receipt', () => {
  assert.ok(physical.size > 0);
  for (const directory of physical) {
    const identity = json(path.join(directory, 'package.json'));
    assert.equal(identity.version, '4.0.7-caseops.1');
    assert.equal(identity.license, 'MIT'); assert.equal(identity.private, true);
    assert.equal(identity.caseopsBackport.notUpstreamRelease, true);
    const pending = [directory], actual = [];
    while (pending.length) {
      const current = pending.pop();
      for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
        assert.equal(entry.isSymbolicLink(), false);
        const file = path.join(current, entry.name);
        if (entry.isDirectory()) {
          assert.equal(path.relative(directory, file), 'lib'); pending.push(file);
        } else {
          assert.equal(entry.isFile(), true);
          const relative = path.relative(directory, file).replaceAll(path.sep, '/');
          assert.ok(Object.hasOwn(provenance.files, relative), relative);
          const content = bytes(file);
          assert.equal(content.length, provenance.files[relative].sizeBytes, relative);
          assert.equal(sha(content), provenance.files[relative].sha256, relative);
          actual.push(relative);
        }
      }
    }
    assert.deepEqual(actual.sort(), Object.keys(provenance.files).sort());
  }
});

test('real web and Expo consumers resolve the reviewed matcher and preserve filtering', t => {
  const fixture = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'picomatch-consumer-')));
  const parent = fs.realpathSync(os.tmpdir()), admitted = fs.lstatSync(fixture, { bigint: true });
  assert.equal(path.dirname(fixture), parent);
  t.after(() => {
    assert.equal(fs.realpathSync(fixture), fixture);
    assert.equal(fs.lstatSync(fixture, { bigint: true }).ino, admitted.ino);
    assert.equal(path.dirname(fixture), parent); fs.rmSync(fixture, { recursive: true });
  });
  fs.mkdirSync(path.join(fixture, 'src'));
  for (const name of ['ordinary.ts', 'ordinary.test.ts', 'notes.txt']) fs.writeFileSync(path.join(fixture, 'src', name), name);
  for (const { root, lock } of locks) {
    const consumers = root === repo ? ['vite', 'vitest', 'tinyglobby']
      : ['micromatch', 'jest-util', 'tinyglobby', '@expo/cli', '@expo/metro-config'];
    for (const name of consumers) {
      const paths = Object.keys(lock.packages).filter(location => location.endsWith('node_modules/' + name));
      assert.ok(paths.length > 0, name);
      for (const location of paths) {
        const require = createRequire(path.join(root, location, 'package.json'));
        const resolved = require.resolve('picomatch');
        assert.ok(physical.has(path.dirname(resolved)), resolved);
        const matcher = require('picomatch')('**/*.ts');
        assert.equal(matcher('src/ordinary.ts'), true);
        assert.equal(matcher('src/ordinary.tsx'), false);
        if (name === 'micromatch') {
          const micromatch = require('./');
          const result = micromatch(['src/ordinary.ts', 'src/ordinary.test.ts', 'src/notes.txt'], ['**/*.ts', '!**/*.test.ts']);
          assert.deepEqual(result, ['src/ordinary.ts']);
        }
        if (name === 'tinyglobby') {
          const tinyglobby = require('./');
          const result = tinyglobby.globSync(['src/**/*.ts', '!**/*.test.ts'], { cwd: fixture });
          assert.deepEqual(result, ['src/ordinary.ts']);
        }
      }
    }
  }
});
