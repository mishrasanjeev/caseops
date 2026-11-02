import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const vendor = path.join(repo, 'apps/mobile/vendor/deepmerge-4.3.1-caseops.1');
const require = createRequire(new URL('../../apps/mobile/package.json', import.meta.url));
const flag = process.env.CASEOPS_DEEPMERGE_ORIGINAL_COUNTEREXAMPLE;
assert.ok(flag === undefined || flag === '0' || flag === '1', 'EXACT_COUNTEREXAMPLE_DOMAIN_REQUIRED');
const original = flag === '1';
const selected = path.join(vendor, original ? 'upstream-runtime.cjs' : 'package/dist/cjs.js');
const merge = require(selected);
const sha = body => createHash('sha256').update(body).digest('hex');
const literal = () => JSON.parse('{"session":{"__proto__":{"caseopsSyntheticAdmin":true}}}');
const explain = t => t.diagnostic(JSON.stringify({ actualCounterexampleFlag: flag ?? null, original,
  selected: path.relative(repo, selected), sha256: sha(fs.readFileSync(selected)) }));

test('deepmerge output prototype stays default for a null placeholder', t => {
  explain(t);
  const value = merge({ session: null }, literal());
  assert.equal(Object.getPrototypeOf(value.session), Object.prototype);
  assert.equal(value.session.caseopsSyntheticAdmin, undefined);
  assert.equal(Object.prototype.caseopsSyntheticAdmin, undefined);
});
test('deepmerge output prototype stays default for an own __proto__ target', t => {
  explain(t);
  const target = JSON.parse('{"__proto__":{"caseopsSyntheticAdmin":true}}');
  const value = merge(target, {});
  assert.equal(Object.getPrototypeOf(value), Object.prototype);
  assert.equal(value.caseopsSyntheticAdmin, undefined);
  assert.equal(Object.prototype.caseopsSyntheticAdmin, undefined);
});
test('deepmerge output prototype stays default for a null-prototype target', t => {
  explain(t);
  const value = merge(Object.create(null), JSON.parse('{"__proto__":{"caseopsSyntheticAdmin":true}}'));
  assert.equal(Object.getPrototypeOf(value), Object.prototype);
  assert.equal(value.caseopsSyntheticAdmin, undefined);
  assert.equal(Object.prototype.caseopsSyntheticAdmin, undefined);
});
test('retained __proto__ values are visible own writable enumerable configurable data', () => {
  const value = merge({ session: null }, literal());
  const descriptor = Object.getOwnPropertyDescriptor(value.session, '__proto__');
  assert.deepEqual(descriptor, { value: { caseopsSyntheticAdmin: true }, writable: true, enumerable: true, configurable: true });
  assert.equal(Object.hasOwn(value.session, '__proto__'), true);
  assert.equal(JSON.stringify(value), '{"session":{"__proto__":{"caseopsSyntheticAdmin":true}}}');
});
test('ordinary nested merges concatenate arrays and preserve both original inputs', () => {
  const target = { name: 'CaseOps', extra: { enabled: true, list: [{ id: 1 }] } };
  const source = { extra: { caption: 'reviewed', list: [{ id: 2 }] } };
  const value = merge(target, source);
  assert.deepEqual(value, { name: 'CaseOps', extra: { enabled: true, caption: 'reviewed', list: [{ id: 1 }, { id: 2 }] } });
  value.extra.list[0].id = 9;
  value.extra.list[1].id = 8;
  assert.deepEqual(target, { name: 'CaseOps', extra: { enabled: true, list: [{ id: 1 }] } });
  assert.deepEqual(source, { extra: { caption: 'reviewed', list: [{ id: 2 }] } });
});
test('enumerable symbols merge without copying hidden symbols or aliasing their values', () => {
  const symbol = Symbol('reviewed'), hidden = Symbol('hidden');
  const source = { [symbol]: { value: 2 } };
  Object.defineProperty(source, hidden, { value: 3, enumerable: false });
  const value = merge({ [symbol]: { enabled: true } }, source);
  assert.deepEqual(value[symbol], { enabled: true, value: 2 });
  assert.equal(value[hidden], undefined);
  assert.notEqual(value[symbol], source[symbol]);
});
test('all retains empty, sequential, array and invalid-input behavior', () => {
  const value = merge.all([{ extra: { first: 1 }, values: [1] }, { extra: { second: 2 }, values: [2] }]);
  assert.deepEqual(value, { extra: { first: 1, second: 2 }, values: [1, 2] });
  assert.deepEqual(merge.all([]), {});
  assert.throws(() => merge.all({}), /array/);
});
test('custom arrayMerge keeps Expo update-set semantics without changing default arrays', () => {
  const options = { arrayMerge: (target, source) => [...new Set([...target, ...source])] };
  const value = merge({ values: ['one', 'two'] }, { values: ['two', 'three'] }, options);
  assert.deepEqual(value, { values: ['one', 'two', 'three'] });
  assert.deepEqual(merge({ values: ['one'] }, { values: ['one'] }), { values: ['one', 'one'] });
});
test('customMerge still controls only the named object while other fields recurse', () => {
  const value = merge({ selected: { value: 1 }, normal: { first: true } },
    { selected: { value: 2 }, normal: { second: true } },
    { customMerge: key => key === 'selected' ? (a, b) => ({ values: [a.value, b.value] }) : undefined });
  assert.deepEqual(value, { selected: { values: [1, 2] }, normal: { first: true, second: true } });
});
test('null, undefined, dates and regular expressions retain the upstream value contract', () => {
  const date = new Date('2026-10-28T00:00:00Z'), expression = /CaseOps/i;
  const value = merge({ missing: 1 }, { missing: undefined, nullable: null, date, expression });
  assert.equal(Object.hasOwn(value, 'missing'), true);
  assert.equal(value.missing, undefined);
  assert.equal(value.nullable, null);
  assert.equal(value.date, date);
  assert.equal(value.expression, expression);
});
test('CJS and UMD forms both reject poisoning while preserving literal ordinary JSON', () => {
  const context = vm.createContext({ module: { exports: {} }, exports: {} });
  vm.runInContext(fs.readFileSync(path.join(vendor, 'package/dist/umd.js'), 'utf8'), context, { timeout: 1000 });
  const umd = context.module.exports;
  const ordinary = umd({ nested: { first: 1 }, values: [1] }, { nested: { second: 2 }, values: [2] });
  assert.equal(JSON.stringify(ordinary), '{"nested":{"first":1,"second":2},"values":[1,2]}');
  const value = umd({ session: null }, literal());
  const empty = umd({}, {});
  assert.equal(Object.getPrototypeOf(value.session), Object.getPrototypeOf(empty));
  assert.equal(value.session.caseopsSyntheticAdmin, undefined);
});
test('exact installed Expo config function preserves update arrays and existing plugin properties', () => {
  const ts = require('typescript');
  const file = path.join(path.dirname(require.resolve('@expo/config')), 'Config.js');
  const source = fs.readFileSync(file, 'utf8');
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const names = ['mergeArraysWithoutDuplicates', 'mergeConfigModifications', 'isPlainObject'];
  const functions = names.map(name => {
    const node = tree.statements.find(item => ts.isFunctionDeclaration(item) && item.name?.text === name);
    assert.ok(node, `EXACT_INSTALLED_EXPO_FUNCTION_REQUIRED:${name}`);
    return node.getText(tree);
  });
  const sdk = vm.runInNewContext(functions.join('\n') + '\n({ mergeConfigModifications })',
    { _deepmerge: () => ({ default: merge }), _util: () => require('node:util') }, { timeout: 1000 });
  const config = { rootConfig: { expo: { name: 'CaseOps', slug: 'caseops',
    updates: { assetPatternsToBeBundled: ['assets/*'] },
    plugins: [['reviewed-plugin', { first: true, values: [1] }]] } } };
  const changes = { name: 'CaseOps QA', updates: { assetPatternsToBeBundled: ['assets/*', 'images/*'] },
    plugins: [['reviewed-plugin', { second: true, values: [2] }]] };
  const value = sdk.mergeConfigModifications(config, changes);
  assert.deepEqual(JSON.parse(JSON.stringify(value)), { expo: { name: 'CaseOps QA', slug: 'caseops',
    updates: { assetPatternsToBeBundled: ['assets/*', 'images/*'] },
    plugins: [['reviewed-plugin', { first: true, values: [1, 2], second: true }]] } });
  assert.equal(config.rootConfig.expo.name, 'CaseOps');
  assert.deepEqual(config.rootConfig.expo.plugins[0][1], { first: true, values: [1] });
});
test('private compatibility identity and notices preserve the exact original MIT bytes', () => {
  const identity = JSON.parse(fs.readFileSync(path.join(vendor, 'package/package.json')));
  const provenance = JSON.parse(fs.readFileSync(path.join(vendor, 'provenance.json')));
  assert.equal(identity.name, 'deepmerge');
  assert.equal(identity.version, '4.3.1-caseops.1');
  assert.equal(identity.private, true);
  assert.equal(identity.license, 'MIT');
  assert.equal(identity.caseopsCompatibilityBackport.upstreamFixedRelease, false);
  assert.equal(provenance.upstream.gitHead, '5b87756a5671635679001cbac72aa42f23472c81');
  const licence = fs.readFileSync(path.join(vendor, 'LICENSE.txt'));
  assert.deepEqual(licence, fs.readFileSync(path.join(vendor, 'package/license.txt')));
  assert.equal(sha(licence), provenance.originalFiles['license.txt']);
  const buildNotices = fs.readFileSync(path.join(repo, 'apps/mobile/BUILD_TOOL_NOTICES.txt'), 'utf8');
  assert.equal(buildNotices.includes('deepmerge 4.3.1-caseops.1'), true);
  assert.equal(buildNotices.includes(licence.toString('utf8')), true);
  assert.match(fs.readFileSync(path.join(vendor, 'MODIFICATIONS.txt'), 'utf8'), /not an upstream release/);
  assert.equal(provenance.originalAuditAffectedNodes, 7);
  assert.equal(provenance.auditExceptionAdded, false);
});
test('offline generator reproduces every byte twice and refuses changed official input before output', () => {
  const temp = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'caseops-deepmerge-'));
  try {
    const upstream = path.join(vendor, 'upstream/deepmerge-4.3.1.tgz');
    const generator = path.join(repo, 'scripts/mobile/rebuild-deepmerge-compat.py');
    const python = process.env.PYTHON ?? 'python3';
    for (const name of ['first', 'second']) {
      const output = path.join(temp, name);
      const child = spawnSync(python, [generator, '--upstream-tarball', upstream, '--output', output],
        { encoding: 'utf8', timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
      assert.equal(child.status, 0, child.stderr);
      assert.deepEqual(fs.readFileSync(path.join(output, 'deepmerge-4.3.1-caseops.1.tgz')),
        fs.readFileSync(path.join(vendor, 'deepmerge-4.3.1-caseops.1.tgz')));
      assert.deepEqual(fs.readFileSync(path.join(output, 'provenance.json')), fs.readFileSync(path.join(vendor, 'provenance.json')));
    }
    const bad = path.join(temp, 'changed.tgz'), body = fs.readFileSync(upstream);
    body[body.length - 1] ^= 1;
    fs.writeFileSync(bad, body);
    const output = path.join(temp, 'refused');
    const child = spawnSync(python, [generator, '--upstream-tarball', bad, '--output', output],
      { encoding: 'utf8', timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
    assert.notEqual(child.status, 0);
    assert.equal(fs.existsSync(output), false);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
