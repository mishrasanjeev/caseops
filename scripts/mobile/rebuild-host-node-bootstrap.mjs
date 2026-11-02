// Offline source generator only. The shipped bootstrap has no parser dependency.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
const PARSER = 'internal/deps/acorn/acorn/dist/acorn';
const PARSER_SHA256 = '2261c5f0e4abe860e889dfc67081683a4ba4d27deb7f4cbc8ad06a1b7fdd510c';
const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const frame = s => fields.map(key => String(s[key]));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const need = (value, code) => { if (!value) throw new Error(code); };
function normalized(value) {
  if (typeof value === 'bigint') return { bigint: String(value) };
  if (Array.isArray(value)) return value.map(normalized);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !['start', 'end', 'loc', 'range'].includes(key)).map(([key, v]) => [key, normalized(v)]));
  return value;
}
export function rebuildHostNodeBootstrap(bytes) {
  const end = performance.now() + 5000;
  need(process.versions.node === '24.15.0' && Buffer.isBuffer(bytes) && bytes.length > 0 && bytes.length <= 16384, 'BOOTSTRAP_GENERATOR_INPUT');
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  // Exact compiler input is already embedded in the accepted Node executable.
  // No package install, external parser, runtime require or downloaded source.
  const parserSource = process.binding('natives')[PARSER];
  need(typeof parserSource === 'string' && Buffer.byteLength(parserSource) <= 524288 && sha(parserSource) === PARSER_SHA256, 'BOOTSTRAP_GENERATOR_PARSER');
  const exports = {}, context = { exports, module: { exports } };
  vm.runInNewContext(parserSource, context, { timeout: 1000, filename: 'node:' + PARSER });
  const acorn = exports, options = { ecmaVersion: 'latest', sourceType: 'module' };
  need(acorn.version === '8.16.0', 'BOOTSTRAP_GENERATOR_PARSER');
  const tokens = acorn.tokenizer(source, options); let result = '', last = '', count = 0;
  while (true) {
    need(performance.now() < end && ++count <= 8192, 'BOOTSTRAP_GENERATOR_BOUND');
    const token = tokens.getToken(); if (token.type.label === 'eof') break;
    const next = source.slice(token.start, token.end); let gap = '';
    if (last) {
      try {
        const pairs = [...acorn.tokenizer(last + next, options)].filter(t => t.type.label !== 'eof');
        if (pairs.length !== 2 || pairs[0].start !== 0 || pairs[0].end !== last.length || pairs[1].start !== last.length) gap = ' ';
      } catch { gap = ' '; }
    }
    result += gap + next; last = next;
  }
  // Existing independent source oracles retain their exact literal anchors.
  result = result.replace('const APPROVED_HELPER_SHA256=', 'const APPROVED_HELPER_SHA256 = ')
    .replace('const code=', 'const code = ') + '\n';
  const before = JSON.stringify(normalized(acorn.parse(source, options))), after = JSON.stringify(normalized(acorn.parse(result, options)));
  need(before === after && performance.now() < end, 'BOOTSTRAP_GENERATOR_AST_CHANGED');
  const output = Buffer.from(result), optionBytes = Buffer.byteLength('--use-openssl-ca --import=data:text/javascript;base64,' + output.toString('base64') + ' --enable-source-maps');
  need(optionBytes <= 8191, 'BOOTSTRAP_GENERATOR_WINDOWS_ENV_BOUND');
  return { bytes: output, provenance: { schemaVersion: 1, kind: 'caseops-host-node-bootstrap-token-compaction', nodeVersion: '24.15.0',
    parser: { nativeId: PARSER, version: acorn.version, sha256: PARSER_SHA256 }, inputSha256: sha(bytes), inputBytes: bytes.length,
    outputSha256: sha(output), outputBytes: output.length, normalizedAstSha256: sha(before), exactAstEqual: true,
    optionWithSourceMapsBytes: optionBytes, optionByteLimit: 8191,
    transformation: 'Exact original token spans; only separating whitespace/comments and two retained literal anchors. No identifier, literal or AST rewriting.' } };
}
export function readBootstrapGeneratorInput(file) {
  const end = performance.now() + 5000;
  need(typeof file === 'string' && path.isAbsolute(file) && fs.realpathSync(file) === file, 'BOOTSTRAP_GENERATOR_PATH');
  const namespace = () => {
    const rows = [];
    for (let p = path.dirname(file); ; p = path.dirname(p)) {
      need(rows.length < 128 && performance.now() < end, 'BOOTSTRAP_GENERATOR_BOUND'); const s = fs.lstatSync(p, { bigint: true });
      need(s.isDirectory() && !s.isSymbolicLink(), 'BOOTSTRAP_GENERATOR_PATH'); rows.push([p, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(k => String(s[k]))]);
      if (p === path.dirname(p)) return rows;
    }
  };
  let fd, buffer;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const a = fs.fstatSync(fd, { bigint: true }), n = fs.lstatSync(file, { bigint: true }), ns = namespace();
    need(a.isFile() && n.isFile() && !n.isSymbolicLink() && a.nlink === 1n && a.size > 0n && a.size <= 16384n
      && (typeof process.getuid !== 'function' || a.uid === BigInt(process.getuid())) && (a.mode & 0o022n) === 0n, 'BOOTSTRAP_GENERATOR_FILE');
    for (const k of fields) need(process.platform === 'win32' && k === 'dev' && n.dev === 0n || a[k] === n[k], 'BOOTSTRAP_GENERATOR_FILE');
    buffer = Buffer.alloc(Number(a.size) + 1); let count = 0;
    while (count < buffer.length) { need(performance.now() < end, 'BOOTSTRAP_GENERATOR_BOUND'); const z = fs.readSync(fd, buffer, count, Math.min(65536, buffer.length - count), null); if (!z) break; count += z; }
    need(count === Number(a.size) && JSON.stringify(frame(a)) === JSON.stringify(frame(fs.fstatSync(fd, { bigint: true })))
      && JSON.stringify(frame(n)) === JSON.stringify(frame(fs.lstatSync(file, { bigint: true }))) && fs.realpathSync(file) === file
      && JSON.stringify(namespace()) === JSON.stringify(ns), 'BOOTSTRAP_GENERATOR_CHANGED');
    return Buffer.from(buffer.subarray(0, count));
  } finally { buffer?.fill(0); if (fd !== undefined) fs.closeSync(fd); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    need(process.argv.length === 3 && process.argv[2] === '--check', 'BOOTSTRAP_GENERATOR_COMMAND');
    const root = path.dirname(fileURLToPath(import.meta.url));
    const input = readBootstrapGeneratorInput(path.join(root, 'host-node-trust-start.source.mjs'));
    const actual = readBootstrapGeneratorInput(path.join(root, 'host-node-trust-start.mjs'));
    const expected = readBootstrapGeneratorInput(path.join(root, 'host-node-trust-start.provenance.json'));
    try {
      const generated = rebuildHostNodeBootstrap(input);
      need(generated.bytes.equals(actual) && JSON.stringify(generated.provenance) === JSON.stringify(JSON.parse(expected)), 'BOOTSTRAP_GENERATOR_OUTPUT');
      console.log(JSON.stringify(generated.provenance));
    } finally { input.fill(0); actual.fill(0); expected.fill(0); }
  } catch { console.error('BOOTSTRAP_GENERATOR_REFUSED'); process.exitCode = 1; }
}
