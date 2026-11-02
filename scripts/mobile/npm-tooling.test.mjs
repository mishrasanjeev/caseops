import assert from 'node:assert/strict';
import childProcess, { spawnSync } from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { gunzipSync, gzipSync } from 'node:zlib';
import https from 'node:https';
import http from 'node:http';
import { EventEmitter } from 'node:events';
import { auditNpmInventory, NPM_ARTIFACT, npmAdvisoryInventory, npmWindowsOwnerDiagnostic, prepareNpm, readPinnedArchive, regularTarMembers, reviewNpmWindowsOwnerOutput, runNpm, verifyInstalledNpm } from './npm-tooling.mjs';
import { installNpmRegistryTransport } from './npm-registry.mjs';

const archive = process.env.CASEOPS_TEST_NPM_ARCHIVE || fileURLToPath(new URL('../../apps/mobile/vendor/npm-11.12.1-caseops-security/npm-11.12.1-caseops-security.tgz', import.meta.url));
const hash = b => createHash('sha256').update(b).digest('hex');
function fixture(t) { const root = (fs.realpathSync.native ?? fs.realpathSync)(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-npm-test-'))); t.after(() => fs.rmSync(root, { recursive: true, force: true })); return root; }
// An open Windows handle may prevent replacement. Keep that native refusal and
// then model only a mismatched named inode; this is a unit double, not OS proof.
function replaceNamedFixture(replacement, target, fd, platform = process.platform) {
  try { fs.renameSync(replacement, target); return false; }
  catch (error) {
    assert.equal(platform, 'win32'); assert.equal(error.code, 'EPERM');
    assert.equal(fs.lstatSync(target, { bigint: true }).ino, fs.fstatSync(fd, { bigint: true }).ino);
    return true;
  }
}
function fixtureRenameMode(mode, run) {
  return mode === 'native' ? run(process.platform) : withFs({ renameSync() { const error = new Error('CONTROL_WINDOWS_OPEN_HANDLE'); error.code = 'EPERM'; throw error; } }, () => run('win32'));
}
function tar(entries) {
  const blocks = [];
  for (const { name = 'package/a', bytes = Buffer.from('ordinary'), mode = 0o644, type = '0' } of entries) {
    const h = Buffer.alloc(512); h.write(name); h.write(mode.toString(8).padStart(7, '0') + '\0', 100);
    h.write('0000000\0', 108); h.write('0000000\0', 116); h.write(bytes.length.toString(8).padStart(11, '0') + '\0', 124);
    h.write('00000000000\0', 136); h.fill(32, 148, 156); h.write(type, 156); h.write('ustar\0', 257); h.write('00', 263);
    const sum = h.reduce((a, b) => a + b, 0); h.write(sum.toString(8).padStart(6, '0') + '\0 ', 148);
    blocks.push(h, bytes, Buffer.alloc((512 - bytes.length % 512) % 512));
  }
  return Buffer.concat([...blocks, Buffer.alloc(1024)]);
}
function withFs(overrides, fn) {
  const prior = Object.fromEntries(Object.keys(overrides).map(k => [k, fs[k]]));
  for (const [k, wrap] of Object.entries(overrides)) fs[k] = (...args) => wrap(prior[k], ...args);
  try { return fn(); } finally { Object.assign(fs, prior); }
}
async function withFsAsync(overrides, fn) {
  const prior = Object.fromEntries(Object.keys(overrides).map(k => [k, fs[k]]));
  for (const [k, wrap] of Object.entries(overrides)) fs[k] = (...args) => wrap(prior[k], ...args);
  try { return await fn(); } finally { Object.assign(fs, prior); }
}
function installed(t) {
  const root = fixture(t), file = path.join(root, 'ordinary'), bytes = Buffer.from('ordinary'); fs.writeFileSync(file, bytes); fs.chmodSync(file, 0o644);
  return { root, file, rows: [{ path: 'ordinary', mode: 0o644, bytes, sha256: hash(bytes) }], directories: new Set([root]), uid: fs.lstatSync(root, { bigint: true }).uid };
}
function verify(v) { return verifyInstalledNpm(v.root, v.rows, v.directories, performance.now() + 5000, v.uid); }

test('the exact pinned installer classifies every package, marker and embedded dependency', () => {
  const bytes = readPinnedArchive(archive), members = regularTarMembers(gunzipSync(bytes)), graph = npmAdvisoryInventory(members);
  assert.equal(hash(bytes), NPM_ARTIFACT.sha256); assert.equal(members.length, 2149);
  assert.equal(graph.logicalPackages, 146); assert.equal(graph.ownedModuleMarkers, 42); assert.equal(graph.rows.length, 154); assert.equal(graph.names, 142);
  assert.deepEqual(graph.graph.glob, ['14.0.2', '14.0.2-caseops.1']); assert.deepEqual(graph.graph.minimatch, ['11.0.1']);
  assert.deepEqual(graph.graph['lru-cache'], ['11.2.7', '11.5.3']);
});
test('a changed archive is refused before extraction or CLI execution', t => {
  const root = fixture(t), input = path.join(root, 'changed.tgz'), bytes = readPinnedArchive(archive); bytes[bytes.length - 1] ^= 1; fs.writeFileSync(input, bytes);
  assert.throws(() => readPinnedArchive(input), /NPM_TOOLING_ARCHIVE_DIGEST/); assert.deepEqual(fs.readdirSync(root), ['changed.tgz']);
});
test('the two reviewed diff module markers retain sideEffects false without admitting unrelated metadata', () => {
  const members = regularTarMembers(gunzipSync(readPinnedArchive(archive)));
  for (const name of ['package/node_modules/diff/libcjs/package.json', 'package/node_modules/diff/libesm/package.json']) {
    const changed = members.map(row => row.path === name ? { ...row, bytes: Buffer.from(JSON.stringify({ type: 'module', sideEffects: true })) } : row);
    assert.throws(() => npmAdvisoryInventory(changed), /NPM_TOOLING_UNCLASSIFIED_MANIFEST/);
  }
});
test('an unexpected partial package identity is refused instead of omitted from the advisory graph', () => {
  const members = regularTarMembers(gunzipSync(readPinnedArchive(archive))), marker = members.find(row => row.path.endsWith('/minimatch/dist/esm/package.json'));
  assert.ok(marker);
  const changed = members.map(row => row === marker ? { ...row, bytes: Buffer.from('{"type":"module","name":"hidden-package"}') } : row);
  assert.throws(() => npmAdvisoryInventory(changed), /NPM_TOOLING_UNCLASSIFIED_MANIFEST/);
});
test('archive descriptors close on read failure and a named inode replacement is rejected', () => {
  let opened, closed;
  withFs({ openSync(original, ...args) { const fd = original(...args); if (args[0] === archive) opened = fd; return fd; },
    readSync(original, fd, ...args) { if (fd === opened) throw new Error('CONTROL_READ_FAILURE'); return original(fd, ...args); },
    closeSync(original, fd) { if (fd === opened) closed = fd; return original(fd); } }, () => assert.throws(() => readPinnedArchive(archive), /CONTROL_READ_FAILURE/));
  assert.equal(closed, opened); assert.throws(() => fs.fstatSync(opened), { code: 'EBADF' });
  withFs({ lstatSync(original, file, ...args) { const s = original(file, ...args); return file === archive ? new Proxy(s, { get: (target, key) => key === 'ino' ? s.ino + 1n : Reflect.get(target, key) }) : s; } },
    () => assert.throws(() => readPinnedArchive(archive), /NPM_TOOLING_NAMED_DESCRIPTOR_CHANGED/));
});
test('portable tar paths reject traversal, absolute, duplicate and case-folded aliases', () => {
  for (const name of ['../escape', '/package/a', 'package/../a', 'package/a\\b', 'package/a.', 'package//a'])
    assert.throws(() => regularTarMembers(tar([{ name }])), /NPM_TOOLING_TAR_PATH/);
  for (const name of ['package/a', 'package/A']) assert.throws(() => regularTarMembers(tar([{}, { name }])), /NPM_TOOLING_TAR_PATH/);
});
test('links, directories and extension records cannot enter a regular-only installer', () => {
  for (const type of ['1', '2', '5', 'x', 'g', 'L']) assert.throws(() => regularTarMembers(tar([{ type }])), /NPM_TOOLING_TAR_REGULAR_ONLY/);
});
test('tar checksum and unsafe modes are refused', () => {
  const input = tar([{}]); input[0] ^= 1; assert.throws(() => regularTarMembers(input), /NPM_TOOLING_TAR_CHECKSUM/);
  for (const mode of [0o777, 0o4644, 0o2644, 0o600]) assert.throws(() => regularTarMembers(tar([{ mode }])), /NPM_TOOLING_TAR_MODE_EXTENT/);
});
test('truncation, nonzero padding and hidden trailing members are refused', () => {
  assert.throws(() => regularTarMembers(tar([{}]).subarray(0, 1024)), /NPM_TOOLING_TAR_BOUND/);
  const pad = tar([{}]); pad[530] = 1; assert.throws(() => regularTarMembers(pad), /NPM_TOOLING_TAR_PADDING/);
  const trailing = tar([{}]); trailing[trailing.length - 1] = 1; assert.throws(() => regularTarMembers(trailing), /NPM_TOOLING_TAR_END/);
});
test('complete installed proof includes the root and charges both scans and final reconciliation', t => {
  const value = installed(t), result = verify(value); assert.equal(result.entries, 2); assert.equal(result.observations, 6); assert.equal(result.bytesRead, 16);
});
test('a payload change during the paired observation is refused', t => {
  const value = installed(t); let rootReads = 0;
  withFs({ readdirSync(original, file, ...args) { if (file === value.root && ++rootReads === 2) fs.writeFileSync(value.file, 'mutation'); return original(file, ...args); } },
    () => assert.throws(() => verify(value), /NPM_TOOLING_INSTALLED_(?:PAYLOAD_CHANGED|FILE_CHANGED)/));
});
test('a file inserted after discovery is refused by final root reconciliation', t => {
  const value = installed(t); let rootReads = 0;
  withFs({ readdirSync(original, file, ...args) { if (file === value.root && ++rootReads === 3) fs.writeFileSync(path.join(file, 'late'), 'late'); return original(file, ...args); } },
    () => assert.throws(() => verify(value), /NPM_TOOLING_FINAL_DIRECTORY_CHANGED/));
});
test('unexpected empty directories and changed file owners cannot yield a zero-copy proof', t => {
  const value = installed(t); fs.mkdirSync(path.join(value.root, 'extra'));
  assert.throws(() => verify(value), /NPM_TOOLING_UNEXPECTED_INSTALLED_FILE/); fs.rmdirSync(path.join(value.root, 'extra'));
  withFs({ lstatSync(original, file, ...args) { const s = original(file, ...args); return file === value.file ? new Proxy(s, { get: (target, key) => key === 'uid' ? s.uid + 1n : Reflect.get(target, key) }) : s; } },
    () => assert.throws(() => verify(value), /NPM_TOOLING_INSTALLED_OWNER/));
});
test('an incomplete installed inventory fails instead of reporting an empty success', t => {
  const value = installed(t); withFs({ readdirSync(original, file, ...args) { return file === value.root ? [] : original(file, ...args); } },
    () => assert.throws(() => verify(value), /NPM_TOOLING_COMPLETE_INSTALLED_INVENTORY/));
});
test('new staged bytes execute the unchanged npm CLI and a healthy full dependency graph', t => {
  const root = fixture(t), result = prepareNpm({ parent: root, archive }); assert.equal(result.files, 2149); assert.equal(result.inventory.entries, 2600); assert.equal(result.inventory.observations, 7800);
  assert.ok(Object.entries(result.environment).every(([name, value]) => name.length + value.length < 8191));
  assert.ok(result.environment.CASEOPS_PINNED_NPM_ENTRY.endsWith('caseops-entry.mjs'));
  assert.equal(result.environment.CASEOPS_PINNED_NPM_BOOTSTRAP.includes('\n'), false);
  const user = path.join(root, 'user.npmrc'), global = path.join(root, 'global.npmrc'); fs.writeFileSync(user, ''); fs.writeFileSync(global, '');
  const env = { ...process.env, NODE_DISABLE_COMPILE_CACHE: '1', HOME: root, USERPROFILE: root, NPM_CONFIG_CACHE: path.join(root, 'cache'), NPM_CONFIG_USERCONFIG: user, NPM_CONFIG_GLOBALCONFIG: global };
  for (const key of Object.keys(env)) if (key.toUpperCase() === 'PATH') delete env[key]; Object.assign(env, result.environment);
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ private: true, scripts: { nested: 'npm --version' } }));
  for (const args of [['--version'], ['ls', '--all', '--omit=dev', '--json', '--prefix', path.dirname(path.dirname(result.cli))], ['run', '--silent', 'nested']]) {
    const run = spawnSync(process.execPath, ['--input-type=module', '--eval', result.environment.CASEOPS_PINNED_NPM_BOOTSTRAP, '--', 'npm', ...args], { env, cwd: root, encoding: 'utf8', timeout: 15000, maxBuffer: 65536, windowsHide: true });
    assert.equal(run.error, undefined); assert.equal(run.status, 0, run.stderr); assert.equal(run.signal, null);
    if (args[0] === 'ls') assert.equal(JSON.parse(run.stdout).version, '11.12.1'); else assert.equal(run.stdout.trim(), '11.12.1');
  }
});

test('nested npm and npx execute the exact repaired CLI despite a different hostile global version', t => {
  const root = fixture(t), result = prepareNpm({ parent: root, archive });
  const hostile = path.join(root, 'hostile'); fs.mkdirSync(hostile);
  fs.writeFileSync(path.join(hostile, process.platform === 'win32' ? 'npm.cmd' : 'npm'), process.platform === 'win32'
    ? '@ECHO off\r\nECHO 10.9.9\r\nEXIT /B 91\r\n' : '#!/bin/sh\nprintf "10.9.9\\n"\nexit 91\n', { mode: 0o755 });
  const user = path.join(root, 'user.npmrc'), global = path.join(root, 'global.npmrc'); fs.writeFileSync(user, ''); fs.writeFileSync(global, '');
  const env = { ...process.env, NODE_DISABLE_COMPILE_CACHE: '1', HOME: root, USERPROFILE: root, NPM_CONFIG_CACHE: path.join(root, 'cache'), NPM_CONFIG_USERCONFIG: user,
    NPM_CONFIG_GLOBALCONFIG: global, NPM_CONFIG_OFFLINE: 'true', NPM_CONFIG_UPDATE_NOTIFIER: 'false' };
  for (const key of Object.keys(env)) if (key.toUpperCase() === 'PATH') delete env[key]; Object.assign(env, result.environment);
  env.PATH = [path.join(result.root, 'bin'), hostile, path.dirname(process.execPath), process.env.PATH || ''].join(path.delimiter);
  const identity = 'node -p "JSON.stringify({cli:process.env.npm_execpath,node:process.execPath})"';
  fs.writeFileSync(path.join(root, 'package.json'), JSON.stringify({ private: true, scripts: { nested: 'npm run --silent identity', identity } }));
  for (const mode of ['npm', 'npx']) {
    const args = mode === 'npm' ? ['run', '--silent', 'nested'] : ['--no-install', '-c', 'npm run --silent identity'];
    const run = spawnSync(process.execPath, ['--input-type=module', '--eval', result.environment.CASEOPS_PINNED_NPM_BOOTSTRAP, '--', mode, ...args],
      { env, cwd: root, encoding: 'utf8', timeout: 15000, maxBuffer: 65536, windowsHide: true });
    assert.equal(run.error, undefined); assert.equal(run.status, 0, run.stderr); assert.equal(run.signal, null);
    assert.deepEqual(JSON.parse(run.stdout), { cli: result.cli, node: process.execPath });
  }
  const records = fs.readdirSync(path.join(result.root, 'transport'));
  for (const name of records) { const rows = fs.readFileSync(path.join(result.root, 'transport', name), 'utf8').trim().split('\n').map(JSON.parse); assert.deepEqual(rows, [{ event: 'transport-finished', requests: 0, receivedBytes: 0 }]); }
  assert.ok(records.length === 4 && records.every(name => /^[0-9]+-[a-f0-9]{16}\.jsonl$/.test(name)));
});

function withNativeRequest(t, run) {
  const root = fixture(t), original = https.request, requests = [];
  https.request = (options, callback) => {
    const req = new EventEmitter(); req.socket = { authorized: true }; req.getHeader = key => options.headers[key];
    req.setTimeout = (timeout, fn) => { req.timeout = timeout; req.timeoutCallback = fn; return req; };
    req.destroy = error => { req.destroyed = error || true; return req; }; req.end = () => { req.ended = true; return req; };
    req.write = bytes => { (req.payload ??= []).push(bytes); return true; };
    requests.push({ options, callback, req }); return req;
  };
  let transport;
  try {
    transport = installNpmRegistryTransport({ logPath: path.join(root, 'requests.jsonl'), deadline: Date.now() + 5000 });
    run({ requests, transport, root });
  } finally { try { transport?.close(); } finally { https.request = original; } }
}
test('ordinary npm transport preserves native request identity payload auth and timeout while marking every caller retry', t => {
  withNativeRequest(t, ({ requests, root }) => {
    const callback = () => {}, token = 'synthetic-only-token';
    const first = https.request('https://registry.npmjs.org/package?synthetic=private', { method: 'POST', headers: { Authorization: 'Bearer ' + token, 'content-type': 'application/json' } }, callback);
    const payload = Buffer.from('{"ordinary":"payload"}'); first.write(payload); first.end();
    const second = https.request({ hostname: 'registry.npmjs.org', protocol: 'https:', path: '/package', method: 'GET' });
    first.on('error', () => {});
    first.emit('error', new Error('synthetic transport failure')); // A caller retry is a separate original request.
    assert.equal(first, requests[0].req); assert.equal(second, requests[1].req); assert.equal(requests.length, 2);
    assert.equal(requests[0].callback, callback); assert.equal(requests[0].options.headers.Authorization, 'Bearer ' + token);
    assert.equal(requests[0].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
    assert.equal(requests[1].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
    assert.equal(requests[0].options.rejectUnauthorized, true); assert.equal(requests[0].options.agent, undefined);
    assert.equal(first.payload[0], payload); assert.ok(first.timeout > 0 && first.timeout <= 30000);
    const log = fs.readFileSync(path.join(root, 'requests.jsonl'), 'utf8'); assert.equal(log.includes(token), false); assert.equal(log.includes('synthetic=private'), false);
  });
});
test('failed ordinary native requests are not replayed and get keeps the original request', t => {
  withNativeRequest(t, ({ requests }) => {
    const request = https.get('https://registry.npmjs.org/ordinary'); request.on('error', () => {});
    const error = new Error('CONTROL_ORIGINAL_FAILURE'); let caught; request.once('error', value => { caught = value; }); request.emit('error', error);
    assert.equal(caught, error); assert.equal(requests.length, 1); assert.equal(request, requests[0].req); assert.equal(request.ended, true);
    request.timeoutCallback(); assert.match(request.destroyed.message, /NPM_REGISTRY_REQUEST_TIMEOUT/);
  });
});
test('ordinary registry transport refuses unverified TLS foreign origins plaintext and conflicting markers before request', t => {
  withNativeRequest(t, ({ requests }) => {
    // Adversarial data is rejected before the native request constructor sees it.
    const tlsInputs = JSON.parse('[{"rejectUnauthorized":false},{"rejectUnauthorized":"INERT_FORBIDDEN_VALUE"},{"rejectUnauthorized":null}]');
    assert.equal(tlsInputs[0].rejectUnauthorized, false);
    for (const options of [{ hostname: 'elsewhere.example', path: '/' },
      ...tlsInputs.map(value => ({ hostname: 'registry.npmjs.org', path: '/', ...value })),
      { hostname: 'registry.npmjs.org', path: '/', servername: 'elsewhere.example' },
      { hostname: 'registry.npmjs.org', path: '/', headers: { 'x-caseops-automated-test': 'conflict' } }]) assert.throws(() => https.request(options));
    assert.throws(() => http.request('http://registry.npmjs.org/'), /NPM_REGISTRY_PLAINTEXT_REFUSED/); assert.equal(requests.length, 0);
  });
});
test('ordinary registry log failure restores constructors and closes its descriptor', t => {
  for (const mode of ['native', 'windows-refusal']) fixtureRenameMode(mode, platform => {
    const root = fixture(t), original = https.request, log = path.join(root, 'requests.jsonl'); let opened, transport;
    withFs({ openSync(originalOpen, ...args) { const fd = originalOpen(...args); if (args[0] === log) opened = fd; return fd; } }, () => { transport = installNpmRegistryTransport({ logPath: log, deadline: Date.now() + 5000 }); });
    const replacement = path.join(root, 'replacement'); fs.writeFileSync(replacement, 'replacement');
    const modelNamed = replaceNamedFixture(replacement, log, opened, platform);
    withFs({ lstatSync(originalLstat, file, ...args) { const state = originalLstat(file, ...args); return modelNamed && file === log ? new Proxy(state, { get: (target, key) => key === 'ino' ? state.ino + 1n : Reflect.get(target, key) }) : state; } }, () => assert.throws(() => transport.close(), /NPM_REGISTRY_LOG_IDENTITY/));
    assert.equal(https.request, original); assert.throws(() => fs.fstatSync(opened), { code: 'EBADF' });
  });
});
test('fresh advisory requests retain default TLS, the isolation marker and exact installed graph', async () => {
  const inventory = { graph: { npm: ['11.12.1'] }, rows: [{ name: 'npm', version: '11.12.1' }] }; let calls = 0;
  const result = await auditNpmInventory(inventory, async (url, options) => { calls++;
    assert.equal(url, 'https://registry.npmjs.org/-/npm/v1/security/advisories/bulk'); assert.equal(options.method, 'POST'); assert.equal(options.redirect, 'error');
    assert.equal(options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers'); assert.equal(options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(options.body), inventory.graph); assert.ok(options.signal instanceof AbortSignal); assert.equal(options.dispatcher, undefined);
    return new Response('{}', { status: 200 }); });
  assert.equal(calls, 1); assert.deepEqual(result.advisories, {}); assert.equal(result.advisoryResponseSha256, hash(Buffer.from('{}')));
});
test('failed, malformed or nonempty advisory responses are never retried or accepted', async () => {
  for (const response of [new Response('bad', { status: 500 }), new Response('bad'), new Response('[]'), new Response('{"glob":[]}')]) {
    let calls = 0; await assert.rejects(auditNpmInventory({ graph: {} }, async () => { calls++; return response; })); assert.equal(calls, 1);
  }
});
test('oversized advisory bodies are cancelled without retry', async () => {
  let calls = 0, cancelled = false;
  const body = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(4194305)); }, cancel() { cancelled = true; } });
  await assert.rejects(auditNpmInventory({ graph: {} }, async () => { calls++; return new Response(body); }), /NPM_TOOLING_ADVISORY_RESPONSE_BOUND/);
  assert.equal(calls, 1); assert.equal(cancelled, true);
});


test('POSIX kernel EACCES on either owned shim refuses preparation before any CLI fallback', t => {
  if (process.platform === 'win32') { t.skip('POSIX executable access is a kernel permission on Unix'); return; }
  for (const target of ['npm', 'npx']) {
    const root = fixture(t); let denied = false;
    withFs({ accessSync(original, file, mode) {
      if (file.endsWith(path.sep + 'bin' + path.sep + target)) {
        assert.equal(mode, fs.constants.X_OK); fs.chmodSync(file, 0o600);
        assert.throws(() => original(file, mode), { code: 'EACCES' }); denied = true;
      }
      return original(file, mode);
    } }, () => assert.throws(() => prepareNpm({ parent: root, archive }), /NPM_TOOLING_EXECUTABLE_SHIM_REQUIRED/));
    assert.equal(denied, true);
  }
});


// These fixed-fact/mocked-command controls exercise the portable admission code.
// They do not establish actual Windows SID/ACL acceptance; fresh Windows CI does.
const windowsAclFact = (patch = {}) => ({ runtimeOwner: true, reviewedAdminSource: false,
  writeScopeSafe: true, tokenUserPresent: true, aclSha256: 'a'.repeat(64), ...patch });
function withWindowsAcl(root, producer, run) {
  const platform = Object.getOwnPropertyDescriptor(process, 'platform'), original = childProcess.spawnSync;
  const systemRoot = Object.getOwnPropertyDescriptor(process.env, 'SystemRoot');
  Object.defineProperty(process, 'platform', { ...platform, value: 'win32' }); process.env.SystemRoot = root;
  childProcess.spawnSync = producer; syncBuiltinESMExports();
  try { return run(); }
  finally {
    childProcess.spawnSync = original; syncBuiltinESMExports(); Object.defineProperty(process, 'platform', platform);
    if (systemRoot) Object.defineProperty(process.env, 'SystemRoot', systemRoot); else delete process.env.SystemRoot;
  }
}
test('Windows npm ownership facts retain exact runtime and public-only administrator admission', () => {
  const decoded = patch => JSON.stringify(windowsAclFact(patch));
  assert.equal(reviewNpmWindowsOwnerOutput(decoded()), 'a'.repeat(64));
  assert.equal(reviewNpmWindowsOwnerOutput(decoded({ runtimeOwner: false, reviewedAdminSource: true }), true), 'a'.repeat(64));
  assert.throws(() => reviewNpmWindowsOwnerOutput(decoded({ runtimeOwner: false, reviewedAdminSource: true })), /NPM_TOOLING_WINDOWS_OWNER_SID_REFUSED/);
  for (const publicData of [false, true]) {
    assert.throws(() => reviewNpmWindowsOwnerOutput(decoded({ writeScopeSafe: false }), publicData), /NPM_TOOLING_WINDOWS_OWNER_WRITE_SCOPE_REFUSED/);
    assert.throws(() => reviewNpmWindowsOwnerOutput(decoded({ tokenUserPresent: false }), publicData), /NPM_TOOLING_WINDOWS_OWNER_TOKEN_REQUIRED/);
    assert.throws(() => reviewNpmWindowsOwnerOutput(decoded({ runtimeOwner: false, reviewedAdminSource: false }), publicData), /NPM_TOOLING_WINDOWS_OWNER_SID_REFUSED/);
  }
});
test('Windows npm ACL protocol refuses malformed oversized and unknown facts without reflecting them', () => {
  for (const raw of ['', ' ', '{', 'null', '[]', 'x'.repeat(4097)])
    assert.throws(() => reviewNpmWindowsOwnerOutput(raw), /NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_/);
  for (const key of Object.keys(windowsAclFact())) {
    const missing = windowsAclFact(); delete missing[key];
    assert.throws(() => reviewNpmWindowsOwnerOutput(JSON.stringify(missing)), /NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_FIELDS/);
    const wrong = windowsAclFact({ [key]: key === 'aclSha256' ? 'NOT_A_DIGEST' : 'true' });
    assert.throws(() => reviewNpmWindowsOwnerOutput(JSON.stringify(wrong)), /NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_/);
  }
  assert.throws(() => reviewNpmWindowsOwnerOutput(JSON.stringify(windowsAclFact({ privateUnknownField: 'DO_NOT_REFLECT' }))), error => {
    assert.match(error.message, /NPM_TOOLING_WINDOWS_OWNER_PROTOCOL_FIELDS/); assert.equal(error.message.includes('DO_NOT_REFLECT'), false); return true;
  });
  assert.throws(() => reviewNpmWindowsOwnerOutput(JSON.stringify(windowsAclFact()), 'true'), /NPM_TOOLING_WINDOWS_OWNER_ADMISSION/);
});
test('the actual archive caller brackets held bytes with typed Windows ACL commands and rejects transport or hash drift', t => {
  const root = fixture(t), calls = [];
  const success = { status: 0, signal: null, stderr: '', stdout: JSON.stringify(windowsAclFact({ runtimeOwner: false, reviewedAdminSource: true })) };
  withWindowsAcl(root, (executable, args, options) => {
    calls.push({ executable, args, options }); return success;
  }, () => assert.equal(hash(readPinnedArchive(archive)), NPM_ARTIFACT.sha256));
  assert.equal(calls.length, 2);
  for (const { executable, args, options } of calls) {
    assert.equal(executable, path.join(root, 'System32/WindowsPowerShell/v1.0/powershell.exe'));
    assert.deepEqual(args.slice(0, 4), ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command']);
    assert.match(args[4], /\[IO\.File\]::GetAccessControl/); assert.match(args[4], /\[IO\.Directory\]::GetAccessControl/);
    assert.equal(args[4].includes('Get-Acl'), false);
    assert.deepEqual(options.env, { SystemRoot: root, WINDIR: root, CASEOPS_NPM_ACL_PATH: archive, CASEOPS_NPM_ACL_KIND: 'file' });
    assert.ok(options.timeout > 0 && options.timeout <= 5000); assert.equal(options.maxBuffer, 4096); assert.equal(options.windowsHide, true);
  }
  for (const change of [{ status: 1 }, { signal: 'SIGTERM' }, { error: Error('CONTROL_TIMEOUT') }, { stderr: 'CONTROL_DIAGNOSTIC' }]) {
    let opened, closed;
    withWindowsAcl(root, () => ({ ...success, ...change }), () => withFs({
      openSync(original, ...args) { const fd = original(...args); if (args[0] === archive) opened = fd; return fd; },
      closeSync(original, fd) { if (fd === opened) closed = fd; return original(fd); },
    }, () => assert.throws(() => readPinnedArchive(archive), /NPM_TOOLING_WINDOWS_OWNER_COMMAND_REFUSED/)));
    assert.equal(closed, opened); assert.throws(() => fs.fstatSync(opened), { code: 'EBADF' });
  }
  let observations = 0;
  withWindowsAcl(root, () => ({ ...success, stdout: JSON.stringify(windowsAclFact({ aclSha256: (++observations === 1 ? 'a' : 'b').repeat(64) })) }),
    () => assert.throws(() => readPinnedArchive(archive), /NPM_TOOLING_ARCHIVE_CHANGED/));
  assert.equal(observations, 2);
});
test('a private npm runtime cannot inherit the pinned public archive owner exception', t => {
  const root = fixture(t), kinds = [];
  withWindowsAcl(root, (_executable, _args, options) => {
    kinds.push(options.env.CASEOPS_NPM_ACL_KIND);
    return { status: 0, signal: null, stderr: '', stdout: JSON.stringify(windowsAclFact({ runtimeOwner: false, reviewedAdminSource: true })) };
  }, () => assert.throws(() => prepareNpm({ parent: root, archive }), /NPM_TOOLING_WINDOWS_OWNER_SID_REFUSED/));
  assert.deepEqual(kinds, ['file', 'file', 'directory']);
  const children = fs.readdirSync(root); assert.equal(children.length, 1); assert.match(children[0], /^caseops-npm-/);
  assert.deepEqual(fs.readdirSync(path.join(root, children[0])), []);
});
test('Windows npm ACL diagnostics identify all four fixed boundaries before any worker execution', async t => {
  const phases = ['ARCHIVE_PRE_READ', 'ARCHIVE_POST_READ', 'RUNTIME_PRE_WRITE', 'RUNTIME_POST_SCAN'];
  for (const [index, phase] of phases.entries()) {
    const root = fixture(t); let calls = 0, workers = 0, caught;
    const originalSpawn = childProcess.spawn;
    childProcess.spawn = () => { workers++; throw new Error('CONTROL_UNEXPECTED_NPM_WORKER'); };
    syncBuiltinESMExports();
    try {
      const pending = withWindowsAcl(root, () => ({ status: 0, signal: null, stderr: '',
        stdout: JSON.stringify(windowsAclFact({ writeScopeSafe: ++calls !== index + 1 })) }),
      () => runNpm(['--cli-health'], { parent: root, archive }));
      try { await pending; assert.fail('Expected the unchanged Windows ownership refusal'); } catch (error) { caught = error; }
    } finally { childProcess.spawn = originalSpawn; syncBuiltinESMExports(); }
    assert.equal(caught.message, 'NPM_TOOLING_WINDOWS_OWNER_WRITE_SCOPE_REFUSED');
    assert.deepEqual(npmWindowsOwnerDiagnostic(caught), { phase, ...windowsAclFact({ writeScopeSafe: false }) });
    assert.equal(Object.isFrozen(npmWindowsOwnerDiagnostic(caught)), true);
    assert.equal(calls, index + 1); assert.equal(workers, 0);
    if (phase === 'RUNTIME_PRE_WRITE') {
      const children = fs.readdirSync(root); assert.equal(children.length, 1);
      assert.deepEqual(fs.readdirSync(path.join(root, children[0])), []);
    }
  }
});

test('Windows npm diagnostics retain the original Error and exclude unvalidated and spoofed facts', t => {
  const root = fixture(t), sentinel = new Error('CONTROL_DO_NOT_REFLECT_PATH_SID_ENV'); let caught;
  withWindowsAcl(root, () => { throw sentinel; }, () => {
    try { readPinnedArchive(archive); } catch (error) { caught = error; }
  });
  assert.equal(caught, sentinel);
  assert.deepEqual(npmWindowsOwnerDiagnostic(caught), { phase: 'ARCHIVE_PRE_READ' });
  for (const result of [
    { status: 0, signal: null, stderr: '', stdout: JSON.stringify(windowsAclFact({ privateUnknownField: sentinel.message })) },
    { status: 0, signal: null, stderr: sentinel.message, stdout: JSON.stringify(windowsAclFact()) },
  ]) {
    withWindowsAcl(root, () => result, () => {
      try { readPinnedArchive(archive); assert.fail('Expected the unchanged protocol/transport refusal'); } catch (error) { caught = error; }
    });
    assert.match(caught.message, /^NPM_TOOLING_WINDOWS_OWNER_(PROTOCOL_FIELDS|COMMAND_REFUSED)$/);
    assert.deepEqual(npmWindowsOwnerDiagnostic(caught), { phase: 'ARCHIVE_PRE_READ' });
    assert.equal(JSON.stringify(npmWindowsOwnerDiagnostic(caught)).includes(sentinel.message), false);
  }
  const spoof = Object.assign(new Error(sentinel.message), { phase: 'ARCHIVE_PRE_READ', writeScopeSafe: false });
  assert.equal(npmWindowsOwnerDiagnostic(spoof), null); assert.equal(npmWindowsOwnerDiagnostic(null), null);
});

test('installed file descriptors precede pathname checks and reject replacement before any payload read', t => {
  const value = installed(t), events = [];
  withFs({
    openSync(original, file, ...args) { if (file === value.file) events.push('open'); return original(file, ...args); },
    lstatSync(original, file, ...args) { if (file === value.file) events.push('named'); return original(file, ...args); },
  }, () => verify(value));
  assert.equal(events[0], 'open');
  for (const mode of ['native', 'windows-refusal']) fixtureRenameMode(mode, platform => {
    const target = installed(t); let opened, closed, reads = 0, modelNamed = false;
    withFs({
      openSync(original, file, ...args) {
        const fd = original(file, ...args);
        if (file === target.file) { opened = fd; const replacement = path.join(target.root, 'replacement'); fs.writeFileSync(replacement, 'ordinary'); modelNamed = replaceNamedFixture(replacement, file, fd, platform); }
        return fd;
      },
      lstatSync(original, file, ...args) { const state = original(file, ...args); return modelNamed && file === target.file ? new Proxy(state, { get: (entry, key) => key === 'ino' ? state.ino + 1n : Reflect.get(entry, key) }) : state; },
      readSync(original, fd, ...args) { if (fd === opened) reads++; return original(fd, ...args); },
      closeSync(original, fd) { if (fd === opened) closed = fd; return original(fd); },
    }, () => assert.throws(() => verify(target), /NPM_TOOLING_NAMED_DESCRIPTOR_CHANGED/));
    assert.equal(reads, 0); assert.equal(closed, opened); assert.throws(() => fs.fstatSync(opened), { code: 'EBADF' });
  });
});

test('ordinary registry transport accepts only default or explicit verified TLS and preserves native request identity', t => {
  withNativeRequest(t, ({ requests }) => {
    // Missing options exercise the undefined/default branch without configuring
    // a native TLS client with an explicit undefined verification setting.
    for (const option of [{}, { rejectUnauthorized: true }]) {
      const request = https.request({ hostname: 'registry.npmjs.org', path: '/ordinary', ...option });
      assert.equal(request, requests[requests.length - 1].req);
      assert.equal(requests[requests.length - 1].options.rejectUnauthorized, true);
      assert.equal(requests[requests.length - 1].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers');
    }
    assert.equal(requests.length, 2);
  });
});

// Appium tooling repair: offline fixtures only; prepareAppiumTooling's network,
// npm and Appium steps are exercised by the retained native receipt.
const appiumTooling = await import('./appium-tooling.mjs');
const { sourceSnapshot } = await import('./source-snapshot.mjs');
const sri = b => 'sha512-' + createHash('sha512').update(b).digest('base64');
function packageArchive(files) {
  return gzipSync(appiumTooling.deterministicTar(Object.entries(files).map(([name, body]) =>
    ({ path: 'package/' + name, mode: 0o644, bytes: Buffer.from(typeof body === 'string' ? body : JSON.stringify(body)) }))));
}
function driverFixture() {
  const archives = {
    'appium-uiautomator2-driver': packageArchive({ 'package.json': { name: 'appium-uiautomator2-driver', version: '8.7.3', files: ['build/lib'] },
      'LICENSE': 'Apache', 'build/lib/driver.js': 'driver', 'node_modules/glob/package.json': { name: 'glob', version: '13.0.6' }, 'node_modules/glob/old.js': 'old',
      'node_modules/minimatch/package.json': { name: 'minimatch', version: '10.2.6' },
      'node_modules/@appium/support/package.json': { name: '@appium/support', version: '7.2.9', dependencies: { glob: '13.0.6', semver: '7.7.2' } },
      'node_modules/readdir-glob/package.json': { name: 'readdir-glob', version: '3.0.0', dependencies: { minimatch: '^10.2.2' } },
      'node_modules/parse-listing/.Makefile.un~': 'undo' }),
    glob: packageArchive({ 'package.json': { name: 'glob', version: '14.0.2-caseops.1', dependencies: { minimatch: '^11.0.0' } }, 'LICENSE.md': 'BlueOak', 'dist/index.js': 'new' }),
    minimatch: packageArchive({ 'package.json': { name: 'minimatch', version: '11.0.1' }, 'LICENSE.md': 'BlueOak' }),
    '@isaacs/nonrecursive-glob-match': packageArchive({ 'package.json': { name: '@isaacs/nonrecursive-glob-match', version: '1.0.3' }, 'LICENSE.md': 'BlueOak' }),
    'path-scurry': packageArchive({ 'package.json': { name: 'path-scurry', version: '3.0.0' }, 'LICENSE.md': 'BlueOak' }),
  };
  const spec = { ...appiumTooling.UIA2_REBUNDLE, tarSha256: null,
    upstream: { ...appiumTooling.UIA2_REBUNDLE.upstream, integrity: sri(archives['appium-uiautomator2-driver']) },
    replacements: appiumTooling.UIA2_REBUNDLE.replacements.map(r => r.vendored ? { ...r, sha256: hash(archives.glob) } : { ...r, integrity: sri(archives[r.name]) }) };
  return { archives, spec };
}
const memberMap = tgz => new Map(appiumTooling.packageTarMembers(tgz).map(r => [r.path, r]));

test('appium driver rebundle replaces only advisory glob/minimatch copies and records every change', () => {
  const { archives, spec } = driverFixture(), first = appiumTooling.rebundleDriver(archives, spec);
  assert.ok(first.tgz.equals(appiumTooling.rebundleDriver(archives, spec).tgz)); assert.equal(first.tgz[9], 3);
  const rows = memberMap(first.tgz), json = name => JSON.parse(rows.get('package/' + name).bytes.toString('utf8'));
  assert.deepEqual(json('package.json'), { name: 'appium-uiautomator2-driver', version: '8.7.3-caseops.1', files: ['build/lib', 'CASEOPS-REBUNDLE.json'] });
  assert.equal(json('node_modules/glob/package.json').version, '14.0.2-caseops.1'); assert.ok(!rows.has('package/node_modules/glob/old.js'));
  assert.equal(json('node_modules/minimatch/package.json').version, '11.0.1');
  assert.equal(json('node_modules/glob/node_modules/path-scurry/package.json').version, '3.0.0');
  assert.equal(json('node_modules/@isaacs/nonrecursive-glob-match/package.json').version, '1.0.3');
  assert.deepEqual(json('node_modules/@appium/support/package.json').dependencies, { glob: '14.0.2-caseops.1', semver: '7.7.2' });
  assert.deepEqual(json('node_modules/readdir-glob/package.json').dependencies, { minimatch: '11.0.1' });
  assert.equal(rows.get('package/build/lib/driver.js').bytes.toString(), 'driver'); assert.ok(rows.has('package/node_modules/parse-listing/.Makefile.un~'));
  const provenance = json('CASEOPS-REBUNDLE.json');
  assert.deepEqual(provenance.dependentSpecs.map(r => [r.package, r.name, r.from, r.to]),
    [['@appium/support@7.2.9', 'glob', '13.0.6', '14.0.2-caseops.1'], ['readdir-glob@3.0.0', 'minimatch', '^10.2.2', '11.0.1']]);
  assert.deepEqual(provenance.replacements.map(r => [r.directory, r.from, r.to]), [['node_modules/glob', '13.0.6', '14.0.2-caseops.1'],
    ['node_modules/minimatch', '10.2.6', '11.0.1'], ['node_modules/@isaacs/nonrecursive-glob-match', null, '1.0.3'], ['node_modules/glob/node_modules/path-scurry', null, '3.0.0']]);
  assert.deepEqual(provenance.advisories, ['GHSA-3g3m-2fjr-6pw4', 'GHSA-g3hv-75wg-m249']);
  assert.throws(() => appiumTooling.rebundleDriver(archives, { ...spec, tarSha256: '0'.repeat(64) }), /APPIUM_TOOLING_REBUNDLE_DIGEST/);
});

test('appium driver rebundle refuses unpinned inputs, unexpected prior versions and duplicate vulnerable copies', () => {
  const { archives, spec } = driverFixture();
  assert.throws(() => appiumTooling.rebundleDriver({ ...archives, minimatch: packageArchive({ 'package.json': { name: 'minimatch', version: '11.0.1' }, 'x.js': '' }) }, spec), /APPIUM_TOOLING_REPLACEMENT_INTEGRITY/);
  assert.throws(() => appiumTooling.rebundleDriver({ ...archives, glob: packageArchive({ 'package.json': { name: 'glob', version: '14.0.2-caseops.1' } }) }, spec), /APPIUM_TOOLING_VENDORED_DIGEST/);
  const swapped = packageArchive({ 'package.json': { name: 'appium-uiautomator2-driver', version: '8.7.3', files: [] }, 'node_modules/glob/package.json': { name: 'glob', version: '13.0.5' } });
  assert.throws(() => appiumTooling.rebundleDriver({ ...archives, 'appium-uiautomator2-driver': swapped }, spec), /APPIUM_TOOLING_UPSTREAM_INTEGRITY/);
  assert.throws(() => appiumTooling.rebundleDriver({ ...archives, 'appium-uiautomator2-driver': swapped },
    { ...spec, upstream: { ...spec.upstream, integrity: sri(swapped) } }), /APPIUM_TOOLING_REPLACED_IDENTITY/);
  const nested = packageArchive({ 'package.json': { name: 'appium-uiautomator2-driver', version: '8.7.3', files: [] }, 'LICENSE': 'Apache',
    'node_modules/glob/package.json': { name: 'glob', version: '13.0.6' }, 'node_modules/minimatch/package.json': { name: 'minimatch', version: '10.2.6' },
    'node_modules/archiver/node_modules/minimatch/package.json': { name: 'minimatch', version: '10.2.6' } });
  assert.throws(() => appiumTooling.rebundleDriver({ ...archives, 'appium-uiautomator2-driver': nested },
    { ...spec, upstream: { ...spec.upstream, integrity: sri(nested) } }), /APPIUM_TOOLING_SINGLE_FIXED_COPY/);
});

test('appium package archive reader accepts long USTAR and GNU regular members but refuses unsafe members', () => {
  const long = 'node_modules/' + 'a'.repeat(60) + '/' + 'b'.repeat(60) + '/index.js';
  assert.deepEqual([...memberMap(packageArchive({ 'package.json': '{}', [long]: 'x' })).keys()], ['package/' + long, 'package/package.json']);
  const header = (patch) => { const tar = appiumTooling.deterministicTar([{ path: 'package/a', mode: 0o644, bytes: Buffer.from('x') }]);
    patch(tar); let sum = 0; for (let i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? 32 : tar[i];
    tar.write(sum.toString(8).padStart(6, '0') + '\0 ', 148, 'ascii'); return gzipSync(tar); };
  assert.equal(appiumTooling.packageTarMembers(header(t => t.write('ustar  \0', 257, 'latin1'))).length, 1);
  assert.throws(() => appiumTooling.packageTarMembers(header(t => { t[156] = 50; })), /APPIUM_TOOLING_TAR_REGULAR_ONLY/);
  assert.throws(() => appiumTooling.packageTarMembers(header(t => { t.write('ustar  \0', 257, 'latin1'); t.write('pfx', 345); })), /APPIUM_TOOLING_TAR_REGULAR_ONLY/);
  assert.throws(() => appiumTooling.packageTarMembers(header(t => t.write('0000777\0', 100))), /APPIUM_TOOLING_TAR_MODE/);
  assert.throws(() => appiumTooling.packageTarMembers(header(t => t.write('package/../a\0', 0))), /APPIUM_TOOLING_TAR_PATH/);
  assert.throws(() => appiumTooling.packageTarMembers(packageArchive({ A: '', a: '' })), /APPIUM_TOOLING_TAR_PATH/);
  assert.throws(() => appiumTooling.packageTarMembers(packageArchive({ a: '', b: '' }), { maxMembers: 1 }), /APPIUM_TOOLING_TAR_MEMBER_BOUND/);
  assert.throws(() => appiumTooling.deterministicTar([{ path: 'package/' + 'c'.repeat(120), mode: 0o644, bytes: Buffer.alloc(0) }]), /APPIUM_TOOLING_TAR_PATH_LENGTH/);
});

test('appium driver rebundle records each shipped licence and refuses a pinned replacement without one', () => {
  const { archives, spec } = driverFixture(), provenance = appiumTooling.rebundleDriver(archives, spec).provenance;
  assert.deepEqual(provenance.driverLicence.licenseFile.path, 'LICENSE');
  assert.deepEqual(provenance.replacements.map(r => r.licenseFile.path), ['node_modules/glob/LICENSE.md', 'node_modules/minimatch/LICENSE.md',
    'node_modules/@isaacs/nonrecursive-glob-match/LICENSE.md', 'node_modules/glob/node_modules/path-scurry/LICENSE.md']);
  const bare = packageArchive({ 'package.json': { name: 'minimatch', version: '11.0.1' } });
  assert.throws(() => appiumTooling.rebundleDriver({ ...archives, minimatch: bare },
    { ...spec, replacements: spec.replacements.map(r => r.name === 'minimatch' ? { ...r, integrity: sri(bare) } : r) }), /APPIUM_TOOLING_LICENCE_REQUIRED/);
});

// A small root-present install with its lockfile and npm hidden lock.
function installFixture(t, { bins = true } = {}) {
  const root = fixture(t), write = (file, value) => { fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    fs.writeFileSync(path.join(root, file), typeof value === 'string' ? value : JSON.stringify(value)); };
  const other = process.platform === 'darwin' ? 'linux' : 'darwin';
  const packages = { 'node_modules/appium': { version: '3.9.0' }, 'node_modules/@scope/x': { version: '1.0.0' },
    'node_modules/appium/node_modules/glob': { version: '14.0.2-caseops.1' }, 'node_modules/driver': { version: '1.0.0' },
    'node_modules/driver/node_modules/@emnapi/runtime': { version: '1.11.3', optional: true, inBundle: true },
    'node_modules/@img/sharp-other': { version: '0.34.5', optional: true, os: [other] } };
  write('package-lock.json', { lockfileVersion: 3, packages: { '': { name: 'fixture' }, ...packages } });
  write('node_modules/.package-lock.json', { lockfileVersion: 3, packages: Object.fromEntries(Object.entries(packages).filter(([key]) => !key.includes('sharp'))) });
  write('node_modules/appium/package.json', { name: 'appium', version: '3.9.0', bin: { appium: 'index.js' } }); write('node_modules/appium/index.js', '');
  write('node_modules/@scope/x/package.json', { name: '@scope/x', version: '1.0.0' });
  write('node_modules/appium/node_modules/glob/package.json', { name: 'glob', version: '14.0.2-caseops.1' });
  write('node_modules/appium/node_modules/glob/CASEOPS-BUNDLE-SOURCES.json', { sourceArchives: [{ name: 'minimatch', version: '11.0.1' }] });
  write('node_modules/driver/package.json', { name: 'driver', version: '1.0.0' });
  fs.mkdirSync(path.join(root, 'node_modules/driver/node_modules/@emnapi/runtime'), { recursive: true });
  write('node_modules/.cache/appium/extensions.yaml', 'drivers: {}\n');
  if (bins) {
    fs.mkdirSync(path.join(root, 'node_modules/.bin'));
    if (process.platform === 'win32') write('node_modules/.bin/appium.cmd', '@echo off');
    else fs.symlinkSync('../appium/index.js', path.join(root, 'node_modules/.bin/appium'));
  }
  return { root, write };
}
const inventoryRefusal = (root, pattern, options) => assert.throws(() => appiumTooling.physicalAdvisoryInventory(root, options), pattern);

test('appium physical inventory reconciles nested, scoped, embedded, placeholder, absent optional and bin identities with both locks', t => {
  const { root } = installFixture(t), inventory = appiumTooling.physicalAdvisoryInventory(root);
  assert.deepEqual(inventory.graph, { '@scope/x': ['1.0.0'], appium: ['3.9.0'], driver: ['1.0.0'], glob: ['14.0.2-caseops.1'], minimatch: ['11.0.1'] });
  assert.deepEqual(inventory.emptyPlaceholders, ['node_modules/driver/node_modules/@emnapi/runtime']);
  assert.deepEqual(inventory.absentOptional, ['node_modules/@img/sharp-other']);
  assert.equal(inventory.binLinks, process.platform === 'win32' ? 0 : 1);
  assert.ok(inventory.observations.entries > 0 && inventory.observations.bytes > 0);
  assert.equal(appiumTooling.platformExcluded({ os: [process.platform] }), false); assert.equal(appiumTooling.platformExcluded({ os: ['!' + process.platform] }), true);
  assert.equal(appiumTooling.platformExcluded({ cpu: [process.arch] }), false); assert.equal(appiumTooling.platformExcluded({}), false);
});

test('appium physical inventory refuses a missing root, unknown metadata and unreconciled lock identities', t => {
  inventoryRefusal(path.join(fixture(t), 'absent'), /APPIUM_TOOLING_PHYSICAL_ROOT_REQUIRED/);
  { const { root } = installFixture(t); fs.rmSync(path.join(root, 'node_modules'), { recursive: true }); inventoryRefusal(root, /APPIUM_TOOLING_PHYSICAL_ROOT_REQUIRED/); }
  { const { root, write } = installFixture(t); write('node_modules/.hidden-code/index.js', ''); inventoryRefusal(root, /APPIUM_TOOLING_UNKNOWN_METADATA/); }
  { const { root, write } = installFixture(t); write('node_modules/.cache/appium/payload.js', ''); inventoryRefusal(root, /APPIUM_TOOLING_UNKNOWN_METADATA/); }
  { const { root, write } = installFixture(t); write('node_modules/@scope/.x/index.js', ''); inventoryRefusal(root, /APPIUM_TOOLING_UNKNOWN_METADATA/); }
  { const { root, write } = installFixture(t); write('node_modules/driver/node_modules/@emnapi/runtime/index.js', ''); inventoryRefusal(root, /APPIUM_TOOLING_UNMANIFESTED_PACKAGE/); }
  { const { root, write } = installFixture(t); write('node_modules/extra/package.json', { name: 'extra', version: '1.0.0' }); inventoryRefusal(root, /APPIUM_TOOLING_UNLOCKED_PACKAGE/); }
  { const { root, write } = installFixture(t); write('node_modules/@scope/x/package.json', { name: '@scope/x', version: '1.0.1' }); inventoryRefusal(root, /APPIUM_TOOLING_LOCK_IDENTITY_MISMATCH/); }
  const lockEdit = (root, edit) => { const file = path.join(root, 'package-lock.json'), lock = JSON.parse(fs.readFileSync(file, 'utf8')); edit(lock.packages); fs.writeFileSync(file, JSON.stringify(lock)); };
  { const { root } = installFixture(t); lockEdit(root, p => { delete p['node_modules/driver/node_modules/@emnapi/runtime'].optional; }); inventoryRefusal(root, /APPIUM_TOOLING_PLACEHOLDER_NOT_OPTIONAL/); }
  { const { root } = installFixture(t); lockEdit(root, p => { p['node_modules/@img/sharp-other'].os = [process.platform]; }); inventoryRefusal(root, /APPIUM_TOOLING_LOCKED_PACKAGE_ABSENT/); }
  { const { root } = installFixture(t); lockEdit(root, p => { p['node_modules/required'] = { version: '1.0.0' }; }); inventoryRefusal(root, /APPIUM_TOOLING_LOCKED_PACKAGE_ABSENT/); }
  { const { root, write } = installFixture(t); write('node_modules/.package-lock.json', { lockfileVersion: 3, packages: { 'node_modules/appium': { version: '3.9.0' } } }); inventoryRefusal(root, /APPIUM_TOOLING_HIDDEN_LOCK_MISMATCH/); }
});

test('appium physical inventory refuses links, undeclared bins and insertion or change after discovery', t => {
  if (process.platform !== 'win32') {
    { const { root } = installFixture(t); fs.symlinkSync(path.join(root, 'node_modules/appium/index.js'), path.join(root, 'node_modules/.bin/other')); inventoryRefusal(root, /APPIUM_TOOLING_UNDECLARED_BIN/); }
    { const { root } = installFixture(t); fs.rmSync(path.join(root, 'node_modules/@scope/x'), { recursive: true });
      fs.symlinkSync(path.join(root, 'node_modules/appium'), path.join(root, 'node_modules/@scope/x')); inventoryRefusal(root, /APPIUM_TOOLING_PHYSICAL_DIRECTORY/); }
  } else { const { root, write } = installFixture(t); write('node_modules/.bin/other.cmd', ''); inventoryRefusal(root, /APPIUM_TOOLING_UNDECLARED_BIN/); }
  { const { root, write } = installFixture(t);
    inventoryRefusal(root, /APPIUM_TOOLING_PHYSICAL_DRIFT/, { afterDiscovery: () => write('node_modules/late/package.json', { name: 'late', version: '1.0.0' }) }); }
  { const { root, write } = installFixture(t);
    inventoryRefusal(root, /APPIUM_TOOLING_PHYSICAL_DRIFT/, { afterDiscovery: () => write('node_modules/@scope/x/package.json', { name: '@scope/x', version: '9.9.9', extra: 'changed bytes' }) }); }
  { const { root } = installFixture(t), file = path.join(root, 'package-lock.json');
    inventoryRefusal(root, /APPIUM_TOOLING_PHYSICAL_DRIFT/, { afterDiscovery: () => {
      const lock = JSON.parse(fs.readFileSync(file, 'utf8')); lock.packages['node_modules/@scope/x'].version = '9.0.0';
      fs.writeFileSync(file, JSON.stringify(lock));
    } }); }
  { const { root } = installFixture(t);
    inventoryRefusal(root, /APPIUM_TOOLING_PHYSICAL_DRIFT/, { afterDiscovery: () => fs.rmSync(path.join(root, 'node_modules/.cache'), { recursive: true }) }); }
});

test('appium runtime with a dot-dot name inside the repository refuses before writes or downloads', async t => {
  const repo = fileURLToPath(new URL('../../', import.meta.url));
  const runtime = path.join(repo, '..runtime-' + path.basename(fixture(t)));
  assert.equal(fs.existsSync(runtime), false);
  let writes = 0, requests = 0;
  const mkdir = t.mock.method(fs, 'mkdirSync', () => { writes++; throw new Error('OFFLINE_UNEXPECTED_RUNTIME_WRITE'); });
  try {
    await assert.rejects(appiumTooling.prepareAppiumTooling(runtime, { request: async () => { requests++; throw new Error('OFFLINE_UNEXPECTED_DOWNLOAD'); } }),
      /APPIUM_TOOLING_RUNTIME_OUTSIDE_REPOSITORY/);
    assert.equal(writes, 0); assert.equal(requests, 0); assert.equal(fs.existsSync(runtime), false);
  } finally { mkdir.mock.restore(); }
});

test('appium physical inventory charges discovery and reconciliation to one entry, byte and deadline budget', t => {
  const { root } = installFixture(t), full = appiumTooling.physicalAdvisoryInventory(root).observations;
  inventoryRefusal(root, /APPIUM_TOOLING_INVENTORY_ENTRY_BOUND/, { limits: { ...appiumTooling.INVENTORY_LIMITS, entries: full.entries - 1 } });
  inventoryRefusal(root, /APPIUM_TOOLING_INVENTORY_BYTE_BOUND/, { limits: { ...appiumTooling.INVENTORY_LIMITS, bytes: full.bytes - 1 } });
  inventoryRefusal(root, /APPIUM_TOOLING_INVENTORY_DEADLINE/, { limits: { ...appiumTooling.INVENTORY_LIMITS, milliseconds: -1 } });
  assert.deepEqual(appiumTooling.physicalAdvisoryInventory(root, { limits: { ...appiumTooling.INVENTORY_LIMITS, ...full } }).observations, full);
});

function archiveResponse(bytes, { status = 200, chunk = 4, length = true, cancelled } = {}) {
  let offset = 0;
  const body = new ReadableStream({ pull(controller) { if (offset >= bytes.length) return controller.close(); controller.enqueue(bytes.subarray(offset, offset += chunk)); },
    cancel() { if (cancelled) cancelled.value = true; } });
  return new Response(body, { status, headers: length ? { 'content-length': String(bytes.length) } : {} });
}
test('appium archive download streams official archives under one bound and deadline with the no-paid marker', async () => {
  const bytes = Buffer.from('official archive bytes'), integrity = sri(bytes), url = 'https://registry.npmjs.org/x/-/x-1.0.0.tgz', seen = [];
  const request = async (target, options) => { seen.push({ target, options }); return archiveResponse(bytes); };
  const download = appiumTooling.downloadSession({ archiveBytes: 64, totalBytes: 40, milliseconds: 60000 }, request);
  assert.ok((await download(url, integrity)).equals(bytes));
  assert.equal(seen[0].options.headers['X-CaseOps-Automated-Test'], 'no-paid-providers'); assert.equal(seen[0].options.redirect, 'error');
  assert.ok(seen[0].options.signal instanceof AbortSignal);
  await assert.rejects(download(url, integrity), /APPIUM_TOOLING_DOWNLOAD_BOUND/); // the second archive exceeds the shared total
  const fresh = (limits, respond) => appiumTooling.downloadSession({ archiveBytes: 64, totalBytes: 1024, milliseconds: 60000, ...limits }, respond);
  await assert.rejects(fresh({}, async () => archiveResponse(bytes, { status: 403 }))(url, integrity), /APPIUM_TOOLING_DOWNLOAD_STATUS/);
  await assert.rejects(fresh({ archiveBytes: 8 }, async () => archiveResponse(bytes))(url, integrity), /APPIUM_TOOLING_DOWNLOAD_BOUND/);
  const cancelled = { value: false };
  await assert.rejects(fresh({ archiveBytes: 8 }, async () => archiveResponse(bytes, { length: false, cancelled }))(url, integrity), /APPIUM_TOOLING_DOWNLOAD_BOUND/);
  assert.equal(cancelled.value, true);
  await assert.rejects(fresh({}, async () => archiveResponse(bytes))(url, sri(Buffer.from('other'))), /APPIUM_TOOLING_DOWNLOAD_INTEGRITY/);
  await assert.rejects(fresh({ milliseconds: -1 }, async () => assert.fail('no request'))(url, integrity), /APPIUM_TOOLING_DOWNLOAD_DEADLINE/);
  await assert.rejects(fresh({}, async () => assert.fail('no request'))('https://example.com/x.tgz', integrity), /APPIUM_TOOLING_OFFICIAL_ARCHIVE_REQUIRED/);
});

test('appium downloader additional TLS refusal is checked at each entry without changing live TLS settings', async () => {
  const prior = process.env.NODE_TLS_REJECT_UNAUTHORIZED, environment = {}, bytes = Buffer.from('official archive bytes'); let requests = 0;
  const download = appiumTooling.downloadSession({ archiveBytes: 64, totalBytes: 1024, milliseconds: 60000 },
    async () => { requests++; return archiveResponse(bytes); }, { environment });
  const url = 'https://registry.npmjs.org/x/-/x-1.0.0.tgz';
  assert.ok((await download(url, sri(bytes))).equals(bytes)); assert.equal(requests, 1);
  environment.NODE_TLS_REJECT_UNAUTHORIZED = '0';
  await assert.rejects(download(url, sri(bytes)), /APPIUM_TOOLING_TLS_VERIFICATION_REQUIRED/);
  assert.equal(requests, 1); assert.equal(process.env.NODE_TLS_REJECT_UNAUTHORIZED, prior);
  let refusedRequests = 0;
  const refused = appiumTooling.downloadSession(appiumTooling.DOWNLOAD_LIMITS, async () => { refusedRequests++; assert.fail('no request'); }, { environment });
  await assert.rejects(refused(url, sri(bytes)), /APPIUM_TOOLING_TLS_VERIFICATION_REQUIRED/);
  assert.equal(refusedRequests, 0); assert.equal(process.env.NODE_TLS_REJECT_UNAUTHORIZED, prior);
  const source = fs.readFileSync(new URL('./appium-tooling.mjs', import.meta.url), 'utf8');
  assert.match(source, /return async function downloadOfficialArchive\(url, integrity\) \{\s*assert\.notEqual\(process\.env\.NODE_TLS_REJECT_UNAUTHORIZED, '0'/);
});

function driverListFixture(t, action = 'process.stdout.write(JSON.stringify(drivers));') {
  const root = fixture(t), appium = path.join(root, 'node_modules/appium'); fs.mkdirSync(appium, { recursive: true, mode: 0o700 });
  const drivers = Object.fromEntries(appiumTooling.DRIVER_REBUNDLES.map(spec => [spec.driver, { installed: true, version: spec.localVersion }]));
  fs.writeFileSync(path.join(appium, 'index.js'), `const assert = require('node:assert/strict'), fs = require('node:fs');
assert.deepEqual(process.argv.slice(2), ['driver', 'list', '--installed', '--json']);
assert.equal(process.env.APPIUM_HOME, process.cwd());
const drivers = ${JSON.stringify(drivers)};
${action}\n`, { mode: 0o600 });
  return { root, drivers, listed: path.join(root, 'driver-list.json') };
}
async function observeDriverListClose(v, fn, overrides = {}) {
  let opened, opens = 0, closes = 0, reads = 0;
  await withFsAsync({
    openSync(original, file, ...args) { const fd = original(file, ...args); if (file === v.listed) { opened = fd; opens++; assert.ok(args[0] & fs.constants.O_RDWR); } return fd; },
    closeSync(original, fd) { if (fd === opened) closes++; return original(fd); },
    readSync(original, fd, ...args) { if (fd === opened) { reads++; assert.equal(typeof args[3], 'number'); } return original(fd, ...args); },
    readFileSync(original, file, ...args) { assert.notEqual(file, v.listed, 'driver stdout must never be reopened'); return original(file, ...args); },
    ...overrides,
  }, () => fn(() => opened));
  assert.equal(opens, 1); assert.equal(closes, 1); assert.throws(() => fs.fstatSync(opened), { code: 'EBADF' });
  return { reads };
}
test('appium driver listing reads actual child stdout on the original descriptor and closes after JSON validation', async t => {
  const v = driverListFixture(t);
  const observed = await observeDriverListClose(v, async () => assert.deepEqual(await appiumTooling.readInstalledDrivers(v.root), v.drivers));
  assert.ok(observed.reads >= 2); // positional data read plus EOF; child advanced the shared stdout offset
});
test('appium driver listing refuses actual child pathname replacement and late namespace entries before reading', async t => {
  for (const action of [
    `try { fs.renameSync('driver-list.json', 'retained-original.json'); fs.writeFileSync('driver-list.json', JSON.stringify(drivers)); }
catch (error) { assert.equal(process.platform, 'win32'); assert.equal(error.code, 'EPERM'); fs.writeFileSync('replacement-denied.json', '{}'); }
process.stdout.write(JSON.stringify(drivers));`,
    `try { fs.unlinkSync('driver-list.json'); fs.writeFileSync('driver-list.json', JSON.stringify(drivers)); }
catch (error) { assert.equal(process.platform, 'win32'); assert.equal(error.code, 'EPERM'); fs.writeFileSync('replacement-denied.json', '{}'); }
process.stdout.write(JSON.stringify(drivers));`,
    `fs.writeFileSync('late-entry.json', '{}'); process.stdout.write(JSON.stringify(drivers));`,
  ]) {
    const v = driverListFixture(t, action);
    const sameNames = action.startsWith("try { fs.unlinkSync") && process.platform !== 'win32';
    const pattern = sameNames ? /APPIUM_TOOLING_DRIVER_LIST_CHANGED/ : /APPIUM_TOOLING_DRIVER_LIST_(NAMESPACE|CHANGED)/;
    const observed = await observeDriverListClose(v, async () => assert.rejects(appiumTooling.readInstalledDrivers(v.root), pattern));
    assert.equal(observed.reads, 0);
    if (sameNames) assert.deepEqual(fs.readdirSync(v.root).sort(), ['driver-list.json', 'node_modules']);
  }
});
test('appium driver listing closes on actual child failure, malformed JSON, identity mismatch and oversized output', async t => {
  for (const [action, pattern, limits] of [
    ['process.exitCode = 7;', /APPIUM_TOOLING_DRIVER_LIST/],
    ["process.stdout.write('{');", /SyntaxError/],
    ['drivers.uiautomator2.version = "wrong"; process.stdout.write(JSON.stringify(drivers));', /APPIUM_TOOLING_DRIVER_IDENTITY/],
    ['process.stdout.write("x".repeat(65));', /APPIUM_TOOLING_DRIVER_LIST_BOUND/, { ...appiumTooling.DRIVER_LIST_LIMITS, bytes: 64 }],
  ]) {
    const v = driverListFixture(t, action);
    await observeDriverListClose(v, async () => assert.rejects(appiumTooling.readInstalledDrivers(v.root, { limits }), pattern));
  }
  const v = driverListFixture(t), mutable = { ...appiumTooling.DRIVER_LIST_LIMITS, bytes: 64 };
  await observeDriverListClose(v, async () => {
    const pending = appiumTooling.readInstalledDrivers(v.root, { limits: mutable });
    mutable.bytes = appiumTooling.DRIVER_LIST_LIMITS.bytes;
    await assert.rejects(pending, /APPIUM_TOOLING_DRIVER_LIST_BOUND/);
  });
});
test('appium driver listing closes on descriptor read failure and rejects metadata drift', async t => {
  for (const mutate of [false, true]) {
    const v = driverListFixture(t); let opened;
    await observeDriverListClose(v, async getFd => { opened = getFd;
      await assert.rejects(appiumTooling.readInstalledDrivers(v.root), mutate ? /APPIUM_TOOLING_DRIVER_LIST_CHANGED/ : /CONTROL_DRIVER_READ_FAILURE/);
    }, { readSync(original, fd, ...args) {
      if (fd === opened?.()) {
        if (!mutate) throw new Error('CONTROL_DRIVER_READ_FAILURE');
        const count = original(fd, ...args); fs.ftruncateSync(fd, 0); return count;
      }
      return original(fd, ...args);
    } });
  }
});
test('appium driver listing charges final reconciliation and bounds the actual child deadline', async t => {
  const v = driverListFixture(t, "process.on('SIGTERM', () => {}); process.stdout.write('READY_WITH_SIGTERM_HANDLER\\n'); setInterval(() => {}, 1000);");
  await observeDriverListClose(v, async () => assert.rejects(appiumTooling.readInstalledDrivers(v.root,
    { limits: { ...appiumTooling.DRIVER_LIST_LIMITS, milliseconds: 1000 } }), /APPIUM_TOOLING_(CHILD_SIGNAL|DRIVER_LIST_DEADLINE)/));
  // POSIX proves the child installed its SIGTERM handler before the SIGKILL
  // deadline. Windows has no catchable SIGTERM and a slower child start, so
  // only the deadline refusal and an unextended stdout are meaningful there.
  const listedOutput = fs.readFileSync(v.listed, 'utf8');
  if (process.platform === 'win32') assert.ok(['', 'READY_WITH_SIGTERM_HANDLER\n'].includes(listedOutput));
  else assert.equal(listedOutput, 'READY_WITH_SIGTERM_HANDLER\n');
  const full = driverListFixture(t); let entries = 0;
  await withFsAsync({ lstatSync(original, ...args) { entries++; return original(...args); },
    readdirSync(original, ...args) { const names = original(...args); entries += names.length; return names; } },
  () => appiumTooling.readInstalledDrivers(full.root));
  const short = driverListFixture(t);
  const shortLimits = { ...appiumTooling.DRIVER_LIST_LIMITS, entries: entries - 1 };
  const observed = await observeDriverListClose(short, async () => {
    const pending = appiumTooling.readInstalledDrivers(short.root, { limits: shortLimits });
    shortLimits.entries = appiumTooling.DRIVER_LIST_LIMITS.entries;
    await assert.rejects(pending, /APPIUM_TOOLING_INVENTORY_ENTRY_BOUND/);
  });
  assert.ok(observed.reads >= 2, 'entry exhaustion must follow actual child completion and descriptor readback');
});

test('committed appium tooling lock pins the rebundled driver and only fixed glob/minimatch identities', () => {
  const project = fileURLToPath(new URL('../../' + appiumTooling.APPIUM_TOOLING_PROJECT + '/', import.meta.url));
  const manifest = JSON.parse(fs.readFileSync(path.join(project, 'package.json'), 'utf8'));
  const pins = JSON.parse(fs.readFileSync(fileURLToPath(new URL('./tooling.json', import.meta.url)), 'utf8'));
  assert.equal(manifest.dependencies.appium, pins.appium); assert.equal(manifest.dependencies.webdriverio, pins.webdriverio);
  assert.equal(appiumTooling.UIA2_REBUNDLE.upstream.version, pins.uiautomator2);
  assert.equal(appiumTooling.XCUITEST_REBUNDLE.upstream.version, pins.xcuitest);
  assert.deepEqual(appiumTooling.DRIVER_REBUNDLES.map(spec => spec.driver), ['uiautomator2', 'xcuitest']);
  for (const spec of appiumTooling.DRIVER_REBUNDLES)
    assert.equal(manifest.dependencies[spec.upstream.name], `file:vendor/${spec.upstream.name}-${spec.localVersion}.tgz`);
  assert.equal(manifest.dependencies.glob, 'file:vendor/' + path.basename(appiumTooling.VENDORED_GLOB.relative));
  assert.deepEqual(manifest.overrides, { appium: { glob: '$glob', minimatch: '$minimatch' }, webdriverio: { glob: '$glob', minimatch: '$minimatch' } });
  const lockfile = path.join(project, 'package-lock.json'), lock = JSON.parse(fs.readFileSync(lockfile, 'utf8')).packages;
  for (const spec of appiumTooling.DRIVER_REBUNDLES) {
    assert.equal(lock[`node_modules/${spec.upstream.name}`].integrity, spec.tgzIntegrity);
    assert.equal(lock[`node_modules/${spec.upstream.name}`].version, spec.localVersion);
  }
  assert.equal(hash(fs.readFileSync(fileURLToPath(new URL('../../' + appiumTooling.VENDORED_GLOB.relative, import.meta.url)))), appiumTooling.VENDORED_GLOB.sha256);
  const graph = appiumTooling.lockedAdvisoryInventory(lockfile).graph;
  assert.deepEqual(graph.glob, ['14.0.2-caseops.1']); assert.deepEqual(graph.minimatch, ['11.0.1']); assert.deepEqual(graph['path-scurry'], ['2.0.2', '3.0.0']);
});

test('appium tooling sources are in the native source fingerprint and its dirty fence', t => {
  const dir = fixture(t), git = (...args) => assert.equal(spawnSync('git', ['-c', 'user.name=Offline fixture', '-c', 'user.email=offline@example.invalid',
    '-c', 'commit.gpgsign=false', ...args], { cwd: dir, windowsHide: true }).status, 0);
  const files = ['scripts/mobile/appium-tooling.mjs', 'scripts/mobile/appium-tooling/package.json', 'scripts/mobile/appium-tooling/package-lock.json'];
  for (const file of ['apps/mobile/index.ts', ...files]) { fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true }); fs.writeFileSync(path.join(dir, file), 'export {};\n'); }
  // Hosted Windows git defaults to core.autocrlf=true, which would rewrite the
  // LF fixtures on checkout and change the restored fingerprint.
  git('init', '--quiet'); git('config', 'core.autocrlf', 'false'); git('add', '.'); git('commit', '--quiet', '-m', 'Synthetic Appium tooling source');
  const clean = sourceSnapshot(dir); assert.equal(clean.sourceDirty, false);
  for (const file of files) {
    fs.writeFileSync(path.join(dir, file), 'changed\n');
    const dirty = sourceSnapshot(dir); assert.equal(dirty.sourceDirty, true, file); assert.notEqual(dirty.sourceFingerprint, clean.sourceFingerprint, file);
    git('checkout', '--quiet', '--', file);
  }
  assert.equal(sourceSnapshot(dir).sourceFingerprint, clean.sourceFingerprint);
});
