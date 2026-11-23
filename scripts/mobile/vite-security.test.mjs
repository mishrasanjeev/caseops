import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readFixtureBytes } from './fixtures/picomatch-byte-input.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const require = createRequire(path.join(root, 'package.json'));
const json = file => JSON.parse(readFixtureBytes(file, 1048576));
const identity = directory => json(path.join(directory, 'package.json'));
const bindings = ['android-arm-eabi', 'android-arm64', 'darwin-arm64', 'darwin-x64', 'freebsd-x64',
  'linux-arm-gnueabihf', 'linux-arm64-gnu', 'linux-arm64-musl', 'linux-ppc64-gnu',
  'linux-s390x-gnu', 'linux-x64-gnu', 'linux-x64-musl', 'openharmony-arm64',
  'wasm32-wasi', 'win32-arm64-msvc', 'win32-x64-msvc'];
const viteRoot = path.join(root, 'node_modules/vite');
const rolldownRoot = path.join(root, 'node_modules/rolldown');
// Ordinary module-name data only. These fixtures contain no statement payload,
// make no HTTP requests, and never evaluate or execute generated JavaScript.
const data = 'quote " apostrophe \' backslash \\ backtick ` newline\ncarriage\rline\u2028paragraph\u2029';
const browserModule = `node:test ${data}`;
const peer = `peer ${data}`;
const parent = `parent ${data}`;
const peerModule = `__vite-optional-peer-dep:${peer}:${parent}`;

function parseOnly(code, values = [], combinedDiagnostic = false) {
  assert.equal(typeof code, 'string');
  assert.ok(Buffer.byteLength(code) <= 65536, 'BOUNDED_GENERATED_MODULE_REQUIRED');
  // Vite's public load hook returns an ESM default export. Turn only that
  // declaration into a local variable so V8 can parse it without ESM execution.
  new vm.Script(code.replace(/\bexport default\b/, 'const defaultValue ='), { filename: 'ordinary-module-data.js' });
  const ts = require('typescript');
  const source = ts.createSourceFile('ordinary-module-data.js', code, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  assert.deepEqual(source.parseDiagnostics, []);
  const literals = [];
  function visit(node) {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) literals.push(node.text);
    ts.forEachChild(node, visit);
  }
  visit(source);
  // Native bundling folds static diagnostic fragments into one literal.
  // Retain every complete decoded name after both syntax parsers pass.
  for (const value of values) assert.ok(combinedDiagnostic ? literals.some(literal => literal.includes(value)) : literals.includes(value), 'MODULE_DATA_MUST_REMAIN_A_STRING_LITERAL');
}

function fixture() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-vite-module-data-'));
}

function cleanup(t, directory, close, restore = () => {}) {
  t.after(async () => {
    const failures = [];
    try { await close(); } catch (error) { failures.push(error); }
    try { fs.rmSync(directory, { recursive: true, force: false }); } catch (error) { failures.push(error); }
    try { restore(); } catch (error) { failures.push(error); }
    if (failures.length) throw new AggregateError(failures, 'Independent module fixture cleanup failures');
  });
}

async function client(t, production = false) {
  const { createServer } = await import(pathToFileURL(require.resolve('vite')));
  const directory = fixture();
  const before = process.env.NODE_ENV;
  process.env.NODE_ENV = production ? 'production' : 'development';
  let server;
  cleanup(t, directory, () => server?.close(), () => {
    if (before === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = before;
  });
  server = await createServer({ root: directory, configFile: false, envFile: false,
    mode: production ? 'production' : 'development',
    logLevel: 'silent', optimizeDeps: { noDiscovery: true, include: [] },
    // Middleware-only: no listener, public dev server, WebSocket or watcher.
    server: { middlewareMode: true, ws: false, watch: null } });
  return server.environments.client.pluginContainer;
}

function code(result) {
  assert.ok(result !== null && result !== undefined, 'ACTUAL_NATIVE_LOADER_RESULT_REQUIRED');
  return typeof result === 'string' ? result : result.code;
}

test('every locked Vite and native Rolldown binding uses the targeted official repair', () => {
  assert.equal(json(path.join(root, 'package.json')).overrides.vite, '8.2.6');
  assert.deepEqual(json(path.join(root, 'package.json')).overrides.rolldown,
    { '.': '1.2.19', '@rolldown/pluginutils': '1.0.1' });
  assert.deepEqual(json(path.join(root, 'package.json')).overrides.postcss, { '.': '8.5.26', nanoid: '3.3.18' });
  const web = json(path.join(root, 'apps/web/package.json'));
  assert.equal(web.dependencies.postcss, '^8.5.26');
  assert.equal(web.overrides.postcss, '^8.5.26');
  const lock = json(path.join(root, 'package-lock.json'));
  const rows = Object.entries(lock.packages);
  const vite = rows.filter(([name]) => name.endsWith('node_modules/vite'));
  const rolldown = rows.filter(([name]) => name.endsWith('node_modules/rolldown'));
  assert.ok(vite.length > 0 && rolldown.length > 0);
  for (const [, entry] of vite) {
    assert.equal(entry.version, '8.2.6');
    assert.equal(entry.dependencies.rolldown, '~1.2.18');
    assert.match(entry.integrity, /^sha512-[A-Za-z0-9+/]+={0,2}$/);
  }
  for (const [, entry] of rolldown) {
    assert.equal(entry.version, '1.2.19');
    assert.deepEqual(Object.keys(entry.optionalDependencies).sort(), bindings.map(name => `@rolldown/binding-${name}`).sort());
    assert.ok(Object.values(entry.optionalDependencies).every(version => version === '1.2.19'));
  }
  const native = rows.filter(([name]) => name.split('node_modules/').at(-1).startsWith('@rolldown/binding-'));
  assert.deepEqual([...new Set(native.map(([name]) => name.split('node_modules/').at(-1)))].sort(), bindings.map(name => `@rolldown/binding-${name}`).sort());
  for (const [name, entry] of native) {
    assert.equal(entry.version, '1.2.19', name);
    assert.ok(entry.resolved.startsWith('https://registry.npmjs.org/@rolldown/binding-'));
    assert.match(entry.integrity, /^sha512-[A-Za-z0-9+/]+={0,2}$/);
  }
  for (const [name, entry] of rows.filter(([name]) => name.endsWith('node_modules/postcss'))) assert.equal(entry.version, '8.5.26', name);
  assert.equal(createRequire(path.join(viteRoot, 'package.json'))('postcss/package.json').version, '8.5.26');
  assert.equal(identity(viteRoot).version, '8.2.6');
  assert.equal(identity(rolldownRoot).version, '1.2.19');
  for (const consumer of ['vite', 'vitest', '@vitest/mocker', '@vitejs/plugin-react']) {
    const caller = createRequire(path.join(root, 'node_modules', consumer, 'package.json'));
    assert.equal(fs.realpathSync(caller.resolve('vite')), fs.realpathSync(require.resolve('vite')));
  }
});

test('targeted Vite and Rolldown licences match the retained official bytes', () => {
  for (const [directory, retained, name, expected] of [
    [viteRoot, 'vite_8.2.6', 'LICENSE.md', '387dd7baa307083401a27c58c362c30832f5ba1dba84f10cc22c33401523f45c'],
    [rolldownRoot, 'rolldown_1.2.19', 'LICENSE', '23ecfff35a5a2e80d92142f75228912c3b1abc4b5a8337a821ff4397e2f9f734'],
    [rolldownRoot, 'rolldown_1.2.19', 'THIRD-PARTY-LICENSE', 'a877291d800ed43692f3f9ae09d8e01cc6f7293ad39d43896059c188ffbb8b7c'],
  ]) {
    const original = readFixtureBytes(path.join(root, 'license-policy/upstream', retained, name), 1048576);
    assert.equal(createHash('sha256').update(original).digest('hex'), expected);
    assert.deepEqual(readFixtureBytes(path.join(directory, name), 1048576), original);
    assert.equal(identity(directory).license, 'MIT');
  }
});

test('development browser modules preserve ordinary quoted data as parseable literals', { timeout: 30000 }, async t => {
  const loader = await client(t);
  parseOnly(code(await loader.load(`__vite-browser-external:${browserModule}`)), [browserModule]);
});

test('development optional peer modules preserve both ordinary names as parseable literals', { timeout: 30000 }, async t => {
  const loader = await client(t);
  parseOnly(code(await loader.load(peerModule)), [peer, parent]);
});

test('production external and optional peer stubs remain parseable without executing them', { timeout: 30000 }, async t => {
  const loader = await client(t, true);
  parseOnly(code(await loader.load(`__vite-browser-external:${browserModule}`)));
  parseOnly(code(await loader.load(peerModule)), [peer, parent]);
});

function resolver(viteResolvePlugin, directory, isBuild, production) {
  return viteResolvePlugin({ resolveOptions: { isBuild, isProduction: production, asSrc: false,
    preferRelative: false, root: directory, scan: false, mainFields: ['main'], conditions: [],
    externalConditions: [], extensions: ['.js'], tryIndex: true, preserveSymlinks: false, tsconfigPaths: false },
  environmentConsumer: 'client', environmentName: 'client', builtins: [], external: [],
  noExternal: [], dedupe: [], legacyInconsistentCjsInterop: false, resolveSubpathImports: () => undefined });
}

async function nativeBundle(t, { isBuild, production = false, optionalPeer = false }) {
  const { rolldown } = await import(pathToFileURL(require.resolve('rolldown')));
  const { viteResolvePlugin } = await import(pathToFileURL(require.resolve('rolldown/experimental')));
  const directory = fixture();
  const entry = 'caseops-ordinary-data-entry';
  const source = optionalPeer ? `import ${JSON.stringify(peerModule)};`
    : `import value from ${JSON.stringify(browserModule)}; export const read = () => value.test;`;
  let bundle;
  cleanup(t, directory, () => bundle?.close());
  bundle = await rolldown({ input: entry, cwd: directory, treeshake: false,
    plugins: [{ name: 'caseops-public-module-data', resolveId: id => id === entry || id === peerModule ? id : undefined,
      load: id => id === entry ? source : undefined }, resolver(viteResolvePlugin, directory, isBuild, production)] });
  const output = await bundle.generate({ format: 'cjs' });
  assert.equal(output.output.length, 1);
  // CJS output is compiled only. No generated module or supplied name is run.
  parseOnly(output.output[0].code, optionalPeer ? [peer, parent] : production ? [] : [browserModule], optionalPeer);
  const loaded = Object.keys(require.cache).filter(file => /[/\\]@rolldown[/\\]binding-[^/\\]+[/\\].+\.node$/.test(file));
  assert.equal(loaded.length, 1, 'ONE_ACTUAL_NATIVE_ROLLDOWN_BINDING_REQUIRED');
  assert.equal(require.cache[loaded[0]].loaded, true);
  assert.equal(identity(path.dirname(loaded[0])).version, '1.2.19');
}

for (const [name, isBuild] of [['bundled', true], ['unbundled', false]]) {
  test(`native ${name} browser module data remains parseable`, { timeout: 30000 }, async t => {
    await nativeBundle(t, { isBuild });
  });
}

for (const [name, production] of [['development', false], ['production', true]]) {
  test(`native ${name} optional peer data remains parseable`, { timeout: 30000 }, async t => {
    await nativeBundle(t, { isBuild: false, production, optionalPeer: true });
  });
}
