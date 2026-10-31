import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';
import https from 'node:https';
import http from 'node:http';
import { EventEmitter } from 'node:events';
import { auditNpmInventory, NPM_ARTIFACT, npmAdvisoryInventory, prepareNpm, readPinnedArchive, regularTarMembers, verifyInstalledNpm } from './npm-tooling.mjs';
import { installNpmRegistryTransport } from './npm-registry.mjs';

const archive = process.env.CASEOPS_TEST_NPM_ARCHIVE || fileURLToPath(new URL('../../apps/mobile/vendor/npm-11.12.1-caseops-security/npm-11.12.1-caseops-security.tgz', import.meta.url));
const hash = b => createHash('sha256').update(b).digest('hex');
function fixture(t) { const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'caseops-npm-test-'))); t.after(() => fs.rmSync(root, { recursive: true, force: true })); return root; }
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
    for (const options of [{ hostname: 'elsewhere.example', path: '/' }, { hostname: 'registry.npmjs.org', path: '/', rejectUnauthorized: false },
      { hostname: 'registry.npmjs.org', path: '/', servername: 'elsewhere.example' },
      { hostname: 'registry.npmjs.org', path: '/', headers: { 'x-caseops-automated-test': 'conflict' } }]) assert.throws(() => https.request(options));
    assert.throws(() => http.request('http://registry.npmjs.org/'), /NPM_REGISTRY_PLAINTEXT_REFUSED/); assert.equal(requests.length, 0);
  });
});
test('ordinary registry log failure restores constructors and closes its descriptor', t => {
  const root = fixture(t), original = https.request, log = path.join(root, 'requests.jsonl');
  const transport = installNpmRegistryTransport({ logPath: log, deadline: Date.now() + 5000 });
  const replacement = path.join(root, 'replacement'); fs.writeFileSync(replacement, 'replacement'); fs.renameSync(replacement, log);
  assert.throws(() => transport.close(), /NPM_REGISTRY_LOG_IDENTITY/); assert.equal(https.request, original);
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
