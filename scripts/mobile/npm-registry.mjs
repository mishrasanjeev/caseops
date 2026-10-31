import assert from 'node:assert/strict';
import https from 'node:https';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomBytes } from 'node:crypto';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { urlToHttpOptions } from 'node:url';

// Derived from the registry constructor used by the isolated dependency repair.
// It returns the original ClientRequest and adds no command or request replay.
export function installNpmRegistryTransport({ logPath, deadline, maximumRequests = 4096, maximumReceivedBytes = 1073741824 }) {
  assert.ok(Number.isFinite(deadline) && deadline > Date.now() && Number.isSafeInteger(maximumRequests)
    && maximumRequests > 0 && maximumRequests <= 4096 && Number.isSafeInteger(maximumReceivedBytes)
    && maximumReceivedBytes > 0 && maximumReceivedBytes <= 1073741824, 'NPM_REGISTRY_LIMITS');
  let fd, initial;
  try {
    fd = fs.openSync(logPath, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL
      | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0), 0o600);
    initial = fs.fstatSync(fd, { bigint: true });
    assert.ok(initial.isFile() && initial.nlink === 1n && initial.size === 0n, 'NPM_REGISTRY_LOG_DESCRIPTOR');
    if (process.getuid) assert.equal(initial.uid, BigInt(process.getuid()), 'NPM_REGISTRY_LOG_OWNER');
  } catch (error) { if (fd !== undefined) fs.closeSync(fd); throw error; }
  let requests = 0, receivedBytes = 0, logBytes = 0, closed = false;
  const original = https.request, originalGet = https.get, originalHttp = http.request, originalHttpGet = http.get;
  function note(value) {
    const line = Buffer.from(JSON.stringify(value) + '\n');
    assert.ok(!closed && Date.now() < deadline && logBytes + line.length <= 4194304, 'NPM_REGISTRY_LOG_BOUND');
    const opened = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(logPath, { bigint: true });
    assert.ok(named.isFile() && !named.isSymbolicLink() && opened.ino === initial.ino && named.ino === initial.ino
      && opened.dev === initial.dev && (named.dev === opened.dev || process.platform === 'win32' && named.dev === 0n)
      && opened.uid === initial.uid && named.uid === initial.uid && opened.nlink === 1n && named.nlink === 1n,
    'NPM_REGISTRY_LOG_IDENTITY');
    logBytes += line.length; let offset = 0;
    while (offset < line.length) { const n = fs.writeSync(fd, line, offset, line.length - offset); assert.ok(n > 0); offset += n; }
  }
  function request(...args) {
    assert.ok(Date.now() < deadline && ++requests <= maximumRequests, 'NPM_REGISTRY_REQUEST_BOUND');
    let options, callback;
    if (typeof args[0] === 'string' || args[0] instanceof URL) {
      options = { ...urlToHttpOptions(new URL(args[0])), ...(typeof args[1] === 'object' ? args[1] : {}) };
      callback = typeof args[1] === 'function' ? args[1] : args[2];
    } else { options = { ...args[0] }; callback = args[1]; }
    const host = options.hostname || options.host;
    assert.ok(host === 'registry.npmjs.org' && (!options.protocol || options.protocol === 'https:')
      && (options.port === undefined || options.port === null || options.port === '' || String(options.port) === '443')
      && options.rejectUnauthorized !== false && (options.servername === undefined || options.servername === host)
      && typeof options.path === 'string' && options.path.startsWith('/') && options.path.length <= 4096,
    'NPM_REGISTRY_OFFICIAL_HTTPS_ONLY');
    const headers = { ...options.headers };
    for (const key of Object.keys(headers)) if (/^x-caseops-automated-test$/i.test(key))
      assert.equal(headers[key], 'no-paid-providers', 'NPM_REGISTRY_MARKER_CONFLICT');
    headers['X-CaseOps-Automated-Test'] = 'no-paid-providers';
    options = { ...options, headers, rejectUnauthorized: true, maxHeaderSize: 16384 };
    const requestId = requests, req = original.call(https, options, callback);
    assert.equal(req.getHeader('X-CaseOps-Automated-Test'), 'no-paid-providers', 'NPM_REGISTRY_NATIVE_MARKER_REQUIRED');
    // Paths and headers can contain credentials. Retain only fixed metadata and a digest.
    note({ event: 'native-request', requestId, method: options.method || 'GET', hostname: host,
      pathSha256: createHash('sha256').update(options.path).digest('hex'), marker: 'no-paid-providers',
      tlsVerification: true, automaticReplayAdded: false });
    req.setTimeout(Math.min(30000, Math.max(1, deadline - Date.now())), () => req.destroy(Error('NPM_REGISTRY_REQUEST_TIMEOUT')));
    req.once('response', response => {
      if (req.socket?.authorized !== true) { response.destroy(Error('NPM_REGISTRY_TLS_AUTHORIZATION_REQUIRED')); return; }
      note({ event: 'response', requestId, statusCode: response.statusCode, tlsAuthorized: true });
      response.on('data', chunk => {
        receivedBytes += chunk.length;
        if (receivedBytes > maximumReceivedBytes || Date.now() >= deadline) response.destroy(Error('NPM_REGISTRY_RECEIVED_BYTE_OR_TIME_BOUND'));
      });
    });
    return req;
  }
  https.request = request;
  https.get = (...args) => { const req = request(...args); req.end(); return req; };
  http.request = http.get = () => { throw Error('NPM_REGISTRY_PLAINTEXT_REFUSED'); };
  syncBuiltinESMExports();
  return { totals: () => ({ requests, receivedBytes, logBytes }), close() {
    assert.ok(!closed, 'NPM_REGISTRY_DOUBLE_CLOSE');
    try { note({ event: 'transport-finished', requests, receivedBytes }); }
    finally {
      https.request = original; https.get = originalGet; http.request = originalHttp; http.get = originalHttpGet;
      syncBuiltinESMExports(); fs.closeSync(fd); closed = true;
    }
  } };
}

function npmRegistryMain() {
  const mode = process.argv[1], root = process.env.CASEOPS_PINNED_NPM_ROOT;
  assert.ok(['npm', 'npx'].includes(mode) && root && path.isAbsolute(root)
    && fs.realpathSync(root) === root, 'NPM_REGISTRY_CLI_MODE');
  const cli = path.join(root, 'package/bin/' + (mode === 'npm' ? 'npm-cli.js' : 'npx-cli.js'));
  const pin = mode === 'npm' ? process.env.CASEOPS_PINNED_NPM_CLI_SHA256 : process.env.CASEOPS_PINNED_NPX_CLI_SHA256;
  assert.match(pin || '', /^[a-f0-9]{64}$/, 'NPM_REGISTRY_CLI_PIN');
  let fd, raw;
  try {
    fd = fs.openSync(cli, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const before = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(cli, { bigint: true });
    const frame = s => ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'].map(k => String(s[k]));
    assert.ok(before.isFile() && named.isFile() && !named.isSymbolicLink() && before.nlink === 1n
      && before.size > 0n && before.size <= 65536n, 'NPM_REGISTRY_CLI_DESCRIPTOR');
    if (process.getuid) assert.equal(before.uid, BigInt(process.getuid()));
    const bytes = Buffer.alloc(Number(before.size) + 1); let offset = 0;
    while (offset < bytes.length) { const n = fs.readSync(fd, bytes, offset, bytes.length - offset, offset); if (!n) break; offset += n; }
    assert.equal(BigInt(offset), before.size); raw = bytes.subarray(0, offset);
    assert.deepEqual(frame(before), frame(fs.fstatSync(fd, { bigint: true })));
    const afterNamed = fs.lstatSync(cli, { bigint: true });
    for (const key of ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'])
      if (!(process.platform === 'win32' && key === 'dev' && afterNamed.dev === 0n)) assert.equal(before[key], afterNamed[key]);
    assert.equal(createHash('sha256').update(raw).digest('hex'), pin, 'NPM_REGISTRY_CLI_CHANGED');
  } finally { if (fd !== undefined) fs.closeSync(fd); }
  const logDirectory = path.join(root, 'transport'), stat = fs.lstatSync(logDirectory, { bigint: true });
  assert.ok(stat.isDirectory() && !stat.isSymbolicLink() && fs.realpathSync(logDirectory) === logDirectory,
    'NPM_REGISTRY_LOG_DIRECTORY');
  if (process.getuid) assert.equal(stat.uid, BigInt(process.getuid()));
  const transport = installNpmRegistryTransport({ logPath: path.join(logDirectory, process.pid + '-' + randomBytes(8).toString('hex') + '.jsonl'),
    deadline: Number(process.env.CASEOPS_PINNED_NPM_DEADLINE) });
  process.once('exit', () => { try { transport.close(); } catch { process.exitCode = 1; } });
  process.argv = [process.execPath, cli, ...process.argv.slice(2)];
  // Compile the kept verified launcher bytes, never reopen that launcher pathname.
  const Module = createRequire(cli)('node:module'), entry = new Module(cli);
  entry.filename = cli; entry.paths = Module._nodeModulePaths(path.dirname(cli)); entry._compile(raw.toString('utf8'), cli);
}

// The caller passes these exact source bytes through the Node --eval entry. Nested
// shims use the same kept source; neither NODE_OPTIONS nor the CLI archive changes.
export const npmRegistryEntry = [
  "import assert from 'node:assert/strict';import https from 'node:https';import http from 'node:http';import fs from 'node:fs';import path from 'node:path';",
  "import {createHash,randomBytes} from 'node:crypto';import {createRequire,syncBuiltinESMExports} from 'node:module';import {urlToHttpOptions} from 'node:url';",
  installNpmRegistryTransport.toString(), npmRegistryMain.toString(), 'npmRegistryMain();',
].join('\n');

async function importHeldRegistryEntry(expected) {
  const file = process.env.CASEOPS_PINNED_NPM_ENTRY, root = process.env.CASEOPS_PINNED_NPM_ROOT;
  assert.ok(path.isAbsolute(root || '') && file === path.join(root, 'caseops-entry.mjs') && fs.realpathSync(file) === file, 'NPM_REGISTRY_ENTRY_PATH');
  const keys = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
  const frame = s => keys.map(k => String(s[k]));
  const namespace = () => {
    const rows = [];
    for (let p = path.dirname(file); ; p = path.dirname(p)) {
      assert.ok(rows.length < 128); const s = fs.lstatSync(p, { bigint: true });
      assert.ok(s.isDirectory() && !s.isSymbolicLink() && fs.realpathSync(p) === p, 'NPM_REGISTRY_ENTRY_NAMESPACE');
      rows.push([p, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(k => String(s[k]))]);
      if (p === path.dirname(p)) return rows;
    }
  };
  const ns = namespace(); let fd, kept;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const initial = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    assert.ok(initial.isFile() && named.isFile() && !named.isSymbolicLink() && initial.nlink === 1n && initial.size > 0n && initial.size <= 32768n, 'NPM_REGISTRY_ENTRY_DESCRIPTOR');
    if (process.getuid) assert.equal(initial.uid, BigInt(process.getuid()));
    for (const key of keys) if (!(process.platform === 'win32' && key === 'dev' && named.dev === 0n)) assert.equal(initial[key], named[key]);
    const bytes = Buffer.alloc(Number(initial.size) + 1); let offset = 0;
    while (offset < bytes.length) { const n = fs.readSync(fd, bytes, offset, bytes.length - offset, offset); if (!n) break; offset += n; }
    kept = bytes.subarray(0, offset); assert.equal(BigInt(offset), initial.size);
    assert.deepEqual(frame(initial), frame(fs.fstatSync(fd, { bigint: true }))); const final = fs.lstatSync(file, { bigint: true });
    assert.deepEqual(frame(named), frame(final)); assert.equal(fs.realpathSync(file), file); assert.deepEqual(namespace(), ns);
    assert.equal(createHash('sha256').update(kept).digest('hex'), expected, 'NPM_REGISTRY_ENTRY_CHANGED');
  } finally { if (fd !== undefined) fs.closeSync(fd); }
  await import('data:text/javascript;base64,' + kept.toString('base64'));
}
export function npmRegistryBootstrap(sha256) {
  assert.match(sha256, /^[a-f0-9]{64}$/);
  return ["import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import {createHash} from 'node:crypto';",
    importHeldRegistryEntry.toString(), `await importHeldRegistryEntry('${sha256}');`].join(' ').replace(/\r?\n/g, ' ');
}
