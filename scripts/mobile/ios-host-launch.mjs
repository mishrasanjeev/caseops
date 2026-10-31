// Host-only recipes. Preparation does not run Pods, download, build or sign.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash, X509Certificate, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { registerHooks } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const IOS_HOST_ENV = Object.freeze({ file: 'CASEOPS_IOS_HOST_POLICY_FILE', sha256: 'CASEOPS_IOS_HOST_POLICY_SHA256' });
export const RUBY_ROOT_SET = '105453e7eeeb26f9778e22b4212b7a6725079827b4de684784eacde93845787a';
const DENIED_CA = '86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b';
const NODE_HELPER = '4dcca216db4071bee09d939142c5ea92bfb120b0bffa152ebefcf0b9acab1a18';
const NODE_BOOTSTRAP = 'c6c1c264a03c8f849b18f917d0f79e1f15eecc6876db89bd29680e2da59169e1';
export const IOS_PODS_SOURCE_SHA256 = 'bcac5eb3bf33069d711759ba925b8ff54d474bc1f64b36176be52b6daec32947';
const SOURCE_PINS = Object.freeze({ 'ios-host-pods.rb': IOS_PODS_SOURCE_SHA256,
  'ios-simulator-build.sh': '93e748e4993eb19b992e7f1f6d480368070b5e1423467640bf8d8908b083e72e',
  'ios-node-build-env.json': '050bd27cab9480e208d17141e5df2d5f98d8f7cdbadc73c31b085ff3be5f0ba6',
  'ios-git-readonly.py': '17b09505fbf0d95e71386d0bfe0f685c2f4c0802b1ddcd9443d1d8042ea207a9',
  'ios-local-qa-host.py': 'c79fedf8f144a311dbcf591d51bf10b6905ae7cc2351fa9ec972dbd0917f783d',
  'store-packaging-host.py': 'a7c9d00f7e9c87a3e2a27ce758b49464fa4c50da92001aac02ebb20ee2dc71bb',
  'store_process_owner.py': 'eaa036bea90b08ba721deb4ece7286bd93315e8d64d128b646d27b78fa2176cf' });
const sha = b => createHash('sha256').update(b).digest('hex');
const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const identity = ['dev', 'ino', 'mode', 'uid', 'gid'];
const same = (a, b, keys = fields) => keys.every(k => a[k] === b[k]);
const refKeys = ['path', 'sha256', 'sizeBytes'];
const NPMRC = Buffer.from('# CaseOps isolated public package requests; no owner configuration.\n');
const check = end => assert.ok(Number.isFinite(end) && Date.now() < end, 'IOS_HOST_DEADLINE');
const exact = (v, keys, code) => assert.ok(v && typeof v === 'object' && !Array.isArray(v)
  && JSON.stringify(Object.keys(v).sort()) === JSON.stringify([...keys].sort()), code);
const absolute = p => typeof p === 'string' && path.isAbsolute(p) && path.resolve(p) === p;
const cleanText = (s, n = 8192) => typeof s === 'string' && s.length > 0 && Buffer.byteLength(s) <= n && !/[\0\r\n]/.test(s);
function namespace(file, end) {
  const rows = [];
  for (let p = path.dirname(file);;) {
    check(end); const s = fs.lstatSync(p, { bigint: true });
    assert.ok(s.isDirectory() && !s.isSymbolicLink() && rows.length < 128, 'IOS_HOST_NAMESPACE');
    rows.push([p, ...identity.map(k => String(s[k]))]);
    if (p === path.dirname(p)) return rows;
    p = path.dirname(p);
  }
}
function directory(p, end, privateMode = true) {
  check(end); assert.ok(absolute(p) && fs.realpathSync(p) === p, 'IOS_HOST_DIRECTORY');
  const s = fs.lstatSync(p, { bigint: true }), uid = process.getuid?.();
  assert.ok(s.isDirectory() && !s.isSymbolicLink() && (uid === undefined || s.uid === BigInt(uid) || !privateMode && s.uid === 0n)
    && (s.mode & (privateMode ? 0o077n : 0o022n)) === 0n, 'IOS_HOST_DIRECTORY');
  return { path: p, identity: identity.map(k => String(s[k])), namespace: namespace(p, end) };
}
function empty(p, end) {
  const before = directory(p, end), d = fs.opendirSync(p);
  try { check(end); assert.equal(d.readSync(), null, 'IOS_HOST_EMPTY_DIRECTORY'); }
  finally { d.closeSync(); }
  assert.deepEqual(directory(p, end), before, 'IOS_HOST_DIRECTORY_CHANGED');
}
export function readIosHostInput(ref, { end = Date.now() + 20000, maxBytes = 1048576, system = false } = {}) {
  assert.ok(typeof process.getuid === 'function', 'IOS_HOST_POSIX_OWNER_REQUIRED');
  exact(ref, refKeys, 'IOS_HOST_REFERENCE');
  assert.ok(absolute(ref.path) && /^[a-f0-9]{64}$/.test(ref.sha256) && Number.isSafeInteger(ref.sizeBytes)
    && ref.sizeBytes > 0 && ref.sizeBytes <= maxBytes && maxBytes <= 256 * 1024 * 1024, 'IOS_HOST_REFERENCE');
  check(end); const fd = fs.openSync(ref.path, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
  let bytes;
  try {
    const a = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(ref.path, { bigint: true }), uid = process.getuid?.();
    assert.ok(a.isFile() && !named.isSymbolicLink() && a.nlink === 1n && a.size === BigInt(ref.sizeBytes)
      && same(a, named) && (uid === undefined || a.uid === BigInt(uid) || system && a.uid === 0n)
      && (a.mode & 0o022n) === 0n, 'IOS_HOST_FILE_IDENTITY');
    const canonical = fs.realpathSync(ref.path), ns = namespace(canonical, end);
    assert.ok(same(a, fs.lstatSync(canonical, { bigint: true })), 'IOS_HOST_NAMESPACE');
    bytes = Buffer.alloc(Number(a.size) + 1); let n = 0;
    while (n < bytes.length) { check(end); const width = fs.readSync(fd, bytes, n, Math.min(65536, bytes.length - n), null); if (!width) break; n += width; }
    check(end); assert.ok(BigInt(n) === a.size && same(a, fs.fstatSync(fd, { bigint: true })) && same(named, fs.lstatSync(ref.path, { bigint: true }))
      && fs.realpathSync(ref.path) === canonical && same(a, fs.lstatSync(canonical, { bigint: true })), 'IOS_HOST_INPUT_CHANGED');
    assert.deepEqual(namespace(canonical, end), ns, 'IOS_HOST_NAMESPACE_CHANGED');
    assert.equal(sha(bytes.subarray(0, n)), ref.sha256, 'IOS_HOST_HASH_CHANGED');
    return { bytes: Buffer.from(bytes.subarray(0, n)), metadata: fields.map(k => String(a[k])), canonical, namespace: ns };
  } finally { bytes?.fill(0); fs.closeSync(fd); }
}
export function referenceIosHostInput(file, end, maxBytes = 1048576, system = false) {
  assert.ok(typeof process.getuid === 'function', 'IOS_HOST_POSIX_OWNER_REQUIRED');
  check(end); assert.ok(absolute(file) && Number.isSafeInteger(maxBytes) && maxBytes > 0
    && maxBytes <= 256 * 1024 * 1024 && typeof system === 'boolean', 'IOS_HOST_REFERENCE');
  // Admit the opened descriptor before observing or consuming the pathname.
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
  let b;
  try {
    const before = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(file, { bigint: true });
    const uid = process.getuid?.();
    assert.ok(same(before, named) && before.isFile() && named.isFile() && !named.isSymbolicLink()
      && before.nlink === 1n && before.size > 0n && before.size <= BigInt(maxBytes)
      && (uid !== undefined && (before.uid === BigInt(uid) || system && before.uid === 0n))
      && (before.mode & 0o022n) === 0n, 'IOS_HOST_FILE_IDENTITY');
    const canonical = fs.realpathSync(file), ns = namespace(canonical, end), size = Number(before.size);
    assert.ok(canonical === file && same(before, fs.lstatSync(canonical, { bigint: true })), 'IOS_HOST_NAMESPACE');
    b = Buffer.alloc(size + 1); let n = 0;
    while (n < b.length) { check(end); const v = fs.readSync(fd, b, n, Math.min(65536, b.length - n), null); if (!v) break; n += v; }
    check(end); assert.ok(n === size && same(before, fs.fstatSync(fd, { bigint: true })) && same(named, fs.lstatSync(file, { bigint: true }))
      && fs.realpathSync(file) === canonical, 'IOS_HOST_INPUT_CHANGED');
    assert.deepEqual(namespace(canonical, end), ns, 'IOS_HOST_NAMESPACE_CHANGED');
    const ref = { path: file, sha256: sha(b.subarray(0, n)), sizeBytes: n };
    const verified = readIosHostInput(ref, { end, maxBytes, system }); verified.bytes.fill(0);
    check(end); assert.ok(same(before, fs.fstatSync(fd, { bigint: true })) && same(named, fs.lstatSync(file, { bigint: true }))
      && fs.realpathSync(file) === canonical, 'IOS_HOST_INPUT_CHANGED');
    assert.deepEqual(namespace(canonical, end), ns, 'IOS_HOST_NAMESPACE_CHANGED'); return ref;
  } finally { b?.fill(0); fs.closeSync(fd); }
}
function writeExclusive(file, bytes, end, mode = 0o600) {
  directory(path.dirname(file), end); const ns = namespace(file, end);
  const fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), mode);
  let probe;
  try {
    const a = fs.fstatSync(fd, { bigint: true });
    assert.ok(a.isFile() && a.nlink === 1n && a.size === 0n && a.uid === BigInt(process.getuid()) && (a.mode & 0o777n) === BigInt(mode), 'IOS_HOST_OUTPUT_IDENTITY');
    let n = 0;
    while (n < bytes.length) { check(end); const v = fs.writeSync(fd, bytes, n, Math.min(65536, bytes.length - n), n); assert.ok(v > 0 && v <= bytes.length - n, 'IOS_HOST_WRITE_PROGRESS'); n += v; }
    fs.fsyncSync(fd); const written = fs.fstatSync(fd, { bigint: true }); probe = Buffer.alloc(bytes.length + 1); n = 0;
    while (n < probe.length) { check(end); const v = fs.readSync(fd, probe, n, Math.min(65536, probe.length - n), n); if (!v) break; n += v; }
    assert.ok(n === bytes.length && probe.subarray(0, n).equals(bytes) && same(written, fs.fstatSync(fd, { bigint: true })) && same(written, fs.lstatSync(file, { bigint: true }))
      && fs.realpathSync(file) === file, 'IOS_HOST_WRITE_CHANGED');
    assert.deepEqual(namespace(file, end), ns, 'IOS_HOST_NAMESPACE_CHANGED');
    return { path: file, sha256: sha(bytes), sizeBytes: bytes.length };
  } finally { probe?.fill(0); fs.closeSync(fd); }
}
function certs(bytes) {
  const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const pems = text.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g) || [];
  assert.ok(pems.length > 0 && pems.length <= 256 && text.replace(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g, '').trim() === '', 'IOS_HOST_CERTIFICATES');
  const rows = pems.map(pem => ({ pem, cert: new X509Certificate(pem) }));
  for (const row of rows) row.id = sha(row.cert.raw);
  assert.equal(new Set(rows.map(r => r.id)).size, rows.length, 'IOS_HOST_DUPLICATE_CERTIFICATE');
  assert.ok(rows.every(r => r.id !== DENIED_CA), 'IOS_HOST_DENIED_CERTIFICATE'); return rows;
}
export function reviewRubyRootBundle(bytes) {
  const rows = certs(bytes), set = sha([...rows.map(r => r.id)].sort().join('\n') + '\n');
  assert.ok(rows.length === 188 && set === RUBY_ROOT_SET, 'IOS_HOST_RUBY188_SET_REQUIRED');
  return { rows, count: 188, setSha256: set };
}
const nodeKeys = ['NODE_OPTIONS', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CASEOPS_HOST_NODE_TRUST_POLICY_FILE', 'CASEOPS_HOST_NODE_TRUST_POLICY_SHA256'];
const unsafe = /^(?:DYLD_.*|LD_(?:PRELOAD|LIBRARY_PATH|AUDIT|DEBUG|PROFILE|ASSUME_KERNEL|BIND_NOW)|NODE_OPTIONS|NODE_EXTRA_CA_CERTS|NODE_USE_SYSTEM_CA|NODE_TLS_REJECT_UNAUTHORIZED|OPENSSL_CONF|OPENSSL_CONF_INCLUDE|SSL_CERT_FILE|SSL_CERT_DIR|CURL_CA_BUNDLE|REQUESTS_CA_BUNDLE|RUBYOPT|RUBYLIB|GEM_HOME|GEM_PATH|BUNDLE_.*|[Nn][Pp][Mm]_[Cc][Oo][Nn][Ff][Ii][Gg]_.*|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|http_proxy|https_proxy|all_proxy|no_proxy|CURL_HOME|CP_HOME_DIR|CP_CACHE_DIR|CP_REPOS_DIR|HOME|XDG_CONFIG_HOME|NODE_BINARY)$/;
const publicKeys = /^(?:PATH|LANG|LC_ALL|TZ|TMPDIR|CI|NODE_ENV|__EXPO_CONFIG_MODE|EXPO_NO_DOTENV|EXPO_NO_TELEMETRY|EXPO_OFFLINE|EXPO_PUBLIC_API_ORIGIN|EXPO_PUBLIC_WEB_ORIGIN|SIMULATOR_UDID|CASEOPS_MOBILE_(?:BUILD_PROFILE|AUTOMATED_TEST|RELEASE_SHA|ANDROID_CA_FILE|ANDROID_CA_SHA256|PRIVACY_POLICY_FILE|PRIVACY_POLICY_SHA256)|CASEOPS_(?:NATIVE_LINK_CONFIG|STORE_BUILD)_(?:FILE|SHA256)|DEVELOPER_DIR|SDKROOT|ARCHS|CODE_SIGN_(?:IDENTITY|STYLE|ENTITLEMENTS)|GIT_(?:CONFIG_GLOBAL|CONFIG_NOSYSTEM|OPTIONAL_LOCKS|TERMINAL_PROMPT))$/;
// Expo's generated Podfile sets these before its Node autolinking subprocess.
// Keep their finite public build values across the Ruby/Node/tool boundary.
const podBuildValues = Object.freeze({
  EXPO_USE_PRECOMPILED_MODULES: Object.freeze(['0', '1']),
  EX_DEV_CLIENT_NETWORK_INSPECTOR: Object.freeze(['true', 'false']),
  RCT_USE_PREBUILT_RNCORE: Object.freeze(['0', '1']),
  RCT_USE_RN_DEP: Object.freeze(['0', '1']),
  RCT_SKIP_CODEGEN: Object.freeze(['0', '1']),
  RCT_REMOVE_LEGACY_ARCH: Object.freeze(['0', '1']),
  RCT_REMOVE_LEGACY_MODULE_INTEROP: Object.freeze(['0', '1']),
  RCT_REMOVE_LEGACY_COMPONENT_INTEROP: Object.freeze(['0', '1']),
  RCT_HERMES_V1_ENABLED: Object.freeze(['0', '1']),
  RCT_FABRIC_ENABLED: Object.freeze(['1']),
  RCT_AGGREGATE_PRIVACY_FILES: Object.freeze(['0', '1']),
  RCT_NEW_ARCH_ENABLED: Object.freeze(['1']),
});
export function neutralIosEnvironment(environment, { buildNames = [], podBuildPaths = null } = {}) {
  assert.ok(environment && typeof environment === 'object' && !Array.isArray(environment), 'IOS_HOST_ENVIRONMENT');
  const result = {}; let bytes = 0;
  for (const [key, value] of Object.entries(environment)) {
    assert.ok(typeof value === 'string' && !value.includes('\0') && Buffer.byteLength(value) <= 32768, 'IOS_HOST_ENVIRONMENT');
    bytes += Buffer.byteLength(key) + Buffer.byteLength(value) + 2;
    assert.ok(bytes <= 262144, 'IOS_HOST_ENVIRONMENT_BOUND');
    if (key === '__CF_USER_TEXT_ENCODING') {
      const parts = value.split(':');
      assert.ok(typeof process.getuid === 'function' && parts.length === 3 && parts.every(v => /^(?:0x[0-9a-fA-F]+|[0-9]+)$/.test(v)
        && Number.isSafeInteger(Number(v)) && Number(v) >= 0 && Number(v) <= 0xffffffff)
        && Number(parts[0]) === process.getuid(), 'IOS_HOST_MACOS_TEXT_ENCODING');
      continue; // Generated CF metadata is validated, never an owner-env grant.
    }
    if (key === 'CASEOPS_STORE_CHILD_STATUS_FD') {
      assert.ok(/^[0-9]{1,10}$/.test(value) && Number(value) >= 3 && Number(value) <= 0x7fffffff, 'IOS_HOST_INTERNAL_STATUS_FD');
      continue; // Pinned host-worker protocol marker, never business authority.
    }
    if (unsafe.test(key) || key.startsWith('CASEOPS_HOST_') || key.startsWith('CASEOPS_IOS_HOST_')
      || ['PWD', 'OLDPWD', 'SHLVL', '_', 'COCOAPODS_DISABLE_STATS', 'COCOAPODS_SKIP_UPDATE_MESSAGE', 'CASEOPS_IOS_PODS_TLS_POLICY', 'CASEOPS_IOS_POD_SOURCE_BASE64'].includes(key)) continue;
    const sdkName = key.toUpperCase();
    if (Object.hasOwn(podBuildValues, sdkName) || ['APP_PATH', 'REACT_NATIVE_PATH'].includes(sdkName))
      assert.equal(key, sdkName, 'IOS_HOST_UNREVIEWED_ENVIRONMENT');
    if (['APP_PATH', 'REACT_NATIVE_PATH'].includes(key)) {
      assert.ok(podBuildPaths && Object.hasOwn(podBuildPaths, key) && Array.isArray(podBuildPaths[key])
        && podBuildPaths[key].includes(value), 'IOS_HOST_POD_SOURCE_PATH'); result[key] = value; continue;
    }
    if (Object.hasOwn(podBuildValues, key)) {
      assert.ok(podBuildValues[key].includes(value), 'IOS_HOST_POD_BUILD_VALUE'); result[key] = value; continue;
    }
    assert.ok(publicKeys.test(key) || buildNames.includes(key), 'IOS_HOST_UNREVIEWED_ENVIRONMENT'); result[key] = value;
  }
  return result;
}
async function nodeRecipe(ref, end) {
  const raw = readIosHostInput(ref, { end, maxBytes: 16384 }); let policy;
  try { policy = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw.bytes)); } finally { raw.bytes.fill(0); }
  assert.ok(policy.kind === 'caseops-host-node-trust-v1' && policy.schemaVersion === 1 && policy.nodeVersion === '24.15.0'
    && ['base', 'native-qa'].includes(policy.role) && policy.runtimeSource?.helper?.sha256 === NODE_HELPER
    && policy.runtimeSource?.bootstrap?.sha256 === NODE_BOOTSTRAP, 'IOS_HOST_NODE_POLICY');
  const h = readIosHostInput(policy.runtimeSource.helper, { end, maxBytes: 65536 }), b = readIosHostInput(policy.runtimeSource.bootstrap, { end, maxBytes: 16384 });
  try {
    const descriptorEnv = { NODE_OPTIONS: '--use-openssl-ca --import=data:text/javascript;base64,' + b.bytes.toString('base64'), SSL_CERT_FILE: policy.bundle.path,
      SSL_CERT_DIR: policy.emptyDirectory, CASEOPS_HOST_NODE_TRUST_POLICY_FILE: ref.path, CASEOPS_HOST_NODE_TRUST_POLICY_SHA256: ref.sha256 };
    if (policy.fixtureCA) descriptorEnv.NODE_EXTRA_CA_CERTS = policy.fixtureCA.path;
    const helper = await import('data:text/javascript;base64,' + h.bytes.toString('base64'));
    return { policy, environment: descriptorEnv, helper };
  } finally { h.bytes.fill(0); b.bytes.fill(0); }
}
export function reviewIosHostHome(home, end = Date.now() + 20000) {
  const before = directory(home, end);
  for (const name of ['.netrc', '_netrc', '.curlrc', '.npmrc', '.gemrc', '.bundle', '.cocoapods']) {
    check(end); assert.equal(fs.lstatSync(path.join(home, name), { throwIfNoEntry: false }), undefined, 'IOS_HOST_OWNER_CONFIG_REFUSED');
  }
  assert.deepEqual(directory(home, end), before, 'IOS_HOST_HOME_NAMESPACE_CHANGED');
  return { frame: fields.map(k => String(fs.lstatSync(home, { bigint: true })[k])), namespace: before };
}
function validateIncoming(p, nodeEnvironment, environment) {
  const allowed = { HOME: [p.paths.home], CURL_HOME: [p.paths.home], XDG_CONFIG_HOME: [p.paths.home],
    SSL_CERT_FILE: [p.bundle.path, nodeEnvironment.SSL_CERT_FILE], SSL_CERT_DIR: [p.paths.empty, nodeEnvironment.SSL_CERT_DIR],
    NODE_OPTIONS: [nodeEnvironment.NODE_OPTIONS], NODE_EXTRA_CA_CERTS: p.fixtureCA ? [p.fixtureCA.path] : [],
    GEM_HOME: [p.podHome], GEM_PATH: [[p.podHome, p.rubyGems].join(':')], CP_HOME_DIR: [p.paths.pods], CP_CACHE_DIR: [p.paths.cache], CP_REPOS_DIR: [p.paths.repos], NODE_BINARY: [p.shims.node.path],
    NPM_CONFIG_USERCONFIG: [p.nodeNpm.user.path], NPM_CONFIG_GLOBALCONFIG: [p.nodeNpm.global.path], NPM_CONFIG_STRICT_SSL: ['true'], NPM_CONFIG_REGISTRY: ['https://registry.npmjs.org/'] };
  for (const [key, value] of Object.entries(environment)) if (unsafe.test(key)) assert.ok(allowed[key]?.includes(value), 'IOS_HOST_CROSS_ROLE_OVERRIDE');
  for (const [key, expected] of Object.entries({ GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_OPTIONAL_LOCKS: '0', GIT_TERMINAL_PROMPT: '0' }))
    if (environment[key] !== undefined) assert.equal(environment[key], expected, 'IOS_HOST_OWNER_GIT_CONFIG_REFUSED');
  for (const key of nodeKeys.slice(3)) if (environment[key] !== undefined) assert.equal(environment[key], nodeEnvironment[key], 'IOS_HOST_NODE_POLICY_OVERRIDE');
}
const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
// This source is embedded in the owned shim, so no .pyc/module-path reopen can
// substitute the helper before its actual held bytes have been checked.
const SHIM_BOOTSTRAP = String.raw`import fs from'node:fs';import path from'node:path';import{createHash}from'node:crypto';
const[file,pin,size,role,...args]=process.argv.slice(1),end=Date.now()+20000;let fd,b;
const fail=()=>{throw Error('IOS_HOST_SHIM_SOURCE_REFUSED')};
const frame=s=>['dev','ino','mode','uid','gid','nlink','size','mtimeNs','ctimeNs'].map(k=>String(s[k])).join(':');
const ns=()=>{const out=[fs.realpathSync(file)];for(let p=path.dirname(out[0]);;p=path.dirname(p)){const s=fs.lstatSync(p,{bigint:true});if(!s.isDirectory()||s.isSymbolicLink()||out.length>128)fail();out.push([p,...['dev','ino','mode','uid','gid'].map(k=>String(s[k]))]);if(p===path.dirname(p))return JSON.stringify(out)}};
try{if(!path.isAbsolute(file)||!/^\d+$/.test(size)||Number(size)>131072)fail();fd=fs.openSync(file,fs.constants.O_RDONLY|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0));const a=fs.fstatSync(fd,{bigint:true}),n=fs.lstatSync(file,{bigint:true}),before=ns();if(!a.isFile()||n.isSymbolicLink()||a.uid!==BigInt(process.getuid())||a.nlink!==1n||a.size!==BigInt(size)||frame(a)!==frame(n)||(a.mode&0o022n)!==0n)fail();b=Buffer.alloc(Number(size)+1);let count=0;while(count<b.length){if(Date.now()>=end)fail();const v=fs.readSync(fd,b,count,Math.min(65536,b.length-count),null);if(!v)break;count+=v}if(count!==Number(size)||frame(a)!==frame(fs.fstatSync(fd,{bigint:true}))||frame(n)!==frame(fs.lstatSync(file,{bigint:true}))||ns()!==before||createHash('sha256').update(b.subarray(0,count)).digest('hex')!==pin)fail();const module=await import('data:text/javascript;base64,'+b.subarray(0,count).toString('base64'));process.exitCode=await module.iosHostCli([role,...args]);}catch(error){const code=String(error?.message||'').split('\n',1)[0];console.error(/^IOS_HOST_[A-Z0-9_]+$/.test(code)?code:'IOS_HOST_CHILD_REFUSED');process.exitCode=1}finally{b?.fill(0);if(fd!==undefined)fs.closeSync(fd)}
`;
const LOADER_FENCE = 'for name in ${!DYLD_@} LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT LD_DEBUG LD_PROFILE LD_ASSUME_KERNEL LD_BIND_NOW; do if declare -p "$name" >/dev/null 2>&1; then echo IOS_HOST_DYNAMIC_LOADER_OVERRIDE_REFUSED >&2; exit 1; fi; done\n';
// The readonly branch is a separate pinned Python transport. It never imports
// Node/TLS policy or the general launcher; mutation/network commands stay below.
const GIT_READONLY_BOOTSTRAP = String.raw`import hashlib,json,os,pathlib,stat,sys,time
ref,python,git=map(json.loads,sys.argv[1:4]);args=sys.argv[4:];fd=None;b=bytearray();end=time.monotonic()+5
fields=('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
def frame(s):return tuple(getattr(s,k) for k in fields)
def ns():
 if time.monotonic()>=end or os.path.realpath(ref['path'])!=ref['path']:raise ValueError('REFUSED')
 rows=[];p=os.path.dirname(ref['path'])
 while True:
  if time.monotonic()>=end or len(rows)>=128:raise ValueError('REFUSED')
  v=os.lstat(p)
  if not stat.S_ISDIR(v.st_mode) or stat.S_ISLNK(v.st_mode):raise ValueError('REFUSED')
  rows.append((p,tuple(getattr(v,k) for k in fields[:5])))
  above=os.path.dirname(p)
  if above==p:return rows
  p=above
try:
 if sys.version_info[:3]!=(3,13,17) or not 0<ref['sizeBytes']<=32768:raise ValueError('REFUSED')
 fd=os.open(ref['path'],os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0));a=os.fstat(fd);n=os.lstat(ref['path']);before=ns()
 if not stat.S_ISREG(a.st_mode) or stat.S_ISLNK(n.st_mode) or a.st_uid!=os.getuid() or a.st_nlink!=1 or a.st_size!=ref['sizeBytes'] or a.st_mode&0o022 or frame(a)!=frame(n):raise ValueError('REFUSED')
 while len(b)<ref['sizeBytes']+1:
  if time.monotonic()>=end:raise ValueError('REFUSED')
  block=os.read(fd,min(65536,ref['sizeBytes']+1-len(b)))
  if not block:break
  b.extend(block)
 if len(b)!=ref['sizeBytes'] or hashlib.sha256(b).hexdigest()!=ref['sha256'] or frame(a)!=frame(os.fstat(fd)) or frame(n)!=frame(os.lstat(ref['path'])) or ns()!=before:raise ValueError('REFUSED')
 scope={'__name__':'ios_git_readonly_retained','__file__':ref['path']};exec(compile(bytes(b),ref['path'],'exec'),scope)
 result=scope['main']({'source':ref,'python':python,'git':git},args,deadline=end)
 if frame(a)!=frame(os.fstat(fd)) or frame(n)!=frame(os.lstat(ref['path'])) or ns()!=before:raise ValueError('REFUSED')
 sys.exit(result)
except SystemExit:raise
except BaseException:
 print('IOS_GIT_READONLY_REFUSED',file=sys.stderr);sys.exit(1)
finally:
 b[:]=b'\0'*len(b)
 if fd is not None:os.close(fd)
`;
function shimBytes(node, helper, nodeEnvironment, role, readonly = null) {
  const assignments = Object.entries(nodeEnvironment).map(([k, v]) => quote(k + '=' + v)).join(' ');
  let fast = '';
  if (role === 'git') {
    assert.ok(readonly?.source && readonly.python?.version === '3.13.17' && readonly.git, 'IOS_HOST_READONLY_SOURCE');
    fast = 'case "${1-}" in --version|rev-parse|ls-files|status|check-ignore)\n' +
      '/usr/bin/env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C TZ=UTC ' +
      'CASEOPS_IOS_HOST_POLICY_FILE="${CASEOPS_IOS_HOST_POLICY_FILE-}" CASEOPS_IOS_HOST_POLICY_SHA256="${CASEOPS_IOS_HOST_POLICY_SHA256-}" CASEOPS_IOS_HOST_POLICY_SIZE="${CASEOPS_IOS_HOST_POLICY_SIZE-}" ' +
      quote(readonly.python.path) + ' -I -B -c ' + quote(GIT_READONLY_BOOTSTRAP) + ' ' +
      [readonly.source, readonly.python, readonly.git].map(v => quote(JSON.stringify(v))).join(' ') + ' "$@"\nexit "$?";; esac\n';
  }
  return Buffer.from('#!/bin/bash\nset -euo pipefail\ntrap \':\' EXIT\n' + LOADER_FENCE + fast + '/usr/bin/env ' + assignments + ' ' + quote(node) + ' --input-type=module -e ' + quote(SHIM_BOOTSTRAP)
    + ' ' + [helper.path, helper.sha256, String(helper.sizeBytes), role].map(quote).join(' ') + ' "$@"\n');
}
export function renderIosHostBuildEntry(helper) {
  exact(helper, refKeys, 'IOS_HOST_ENTRY_REFERENCE');
  assert.ok(/^[a-f0-9]{64}$/.test(helper.sha256) && Number.isSafeInteger(helper.sizeBytes) && helper.sizeBytes > 0 && helper.sizeBytes <= 131072, 'IOS_HOST_ENTRY_REFERENCE');
  return '#!/bin/bash\nset -euo pipefail\ntrap \':\' EXIT\n' + LOADER_FENCE +
    '[[ "$(uname -s)" == Darwin ]] || { echo "An actual Mac with Xcode is required." >&2; exit 1; }\n' +
    ': "${CASEOPS_IOS_HOST_NODE:?Supply the admitted Node24 executable}"\n' +
    ': "${CASEOPS_IOS_HOST_POLICY_FILE:?Prepare an immutable iOS host policy}"\n' +
    ': "${CASEOPS_IOS_HOST_POLICY_SHA256:?Bind the exact iOS host policy bytes}"\n' +
    ': "${CASEOPS_IOS_HOST_POLICY_SIZE:?Bind the exact policy extent}"\n' +
    ': "${CASEOPS_IOS_SIMULATOR_BUILD_GO:?An explicit reviewed local simulator build is required}"\n' +
    'repo="$(cd "$(dirname "$0")/../.." && pwd)"\n' +
    '# IOS_HOST_REVIEWED_ENTRY: execute retained reviewed bytes, never a module-path reopen.\n' +
    '"$CASEOPS_IOS_HOST_NODE" --input-type=module -e ' + quote(SHIM_BOOTSTRAP) +
    ' "$repo/scripts/mobile/ios-host-launch.mjs" ' + quote(helper.sha256) + ' ' + quote(String(helper.sizeBytes)) + ' simulator\n';
}
// npm code is always constructed from the reviewed public artifact. These two
// modules are consumed from their checked descriptors, including the relative
// registry import when this host helper itself was loaded from a held data URL.
const NPM_INPUTS = Object.freeze({
  tooling: Object.freeze({ relative: 'scripts/mobile/npm-tooling.mjs', sha256: '7509dda7422c23f3eaf55a9c48c9aafe5cd796f5988b581a55d28f62445e2c7f', sizeBytes: 25889 }),
  registry: Object.freeze({ relative: 'scripts/mobile/npm-registry.mjs', sha256: 'f354a9d943ebcb78cb7afdb78c83bc0961fc01bbe183a6791486464cad6db9de', sizeBytes: 12058 }),
  archive: Object.freeze({ relative: 'apps/mobile/vendor/npm-11.12.1-caseops-security/npm-11.12.1-caseops-security.tgz', sha256: 'fcfa9290ee0acca362be71768de3dcc591f6af00622270529e70fbb25b831052', sizeBytes: 4043346 }),
});
const NPM_ENV_KEYS = ['CASEOPS_PINNED_NPM_NODE', 'CASEOPS_PINNED_NPM_ROOT', 'CASEOPS_PINNED_NPM_ENTRY', 'CASEOPS_PINNED_NPM_BOOTSTRAP', 'CASEOPS_PINNED_NPM_CLI_SHA256', 'CASEOPS_PINNED_NPX_CLI_SHA256', 'CASEOPS_PINNED_NPM_DEADLINE', 'CASEOPS_PINNED_NPM_CLI', 'CASEOPS_PINNED_NPX_CLI', 'PATH'];
function npmInputReferences(root) {
  return Object.fromEntries(Object.entries(NPM_INPUTS).map(([key, row]) => [key,
    { path: path.join(root, row.relative), sha256: row.sha256, sizeBytes: row.sizeBytes }]));
}
function reviewIosNpmInputs(p, end, archivePayload = false) {
  exact(p.nodeNpm, ['user', 'global', 'parent', 'tooling', 'registry', 'archive'], 'IOS_HOST_NPM_FIELDS');
  const parent = path.dirname(p.paths.home), root = path.resolve(path.dirname(p.helper.path), '../..');
  for (const name of ['user', 'global']) {
    assert.equal(p.nodeNpm[name].path, path.join(parent, 'npm-' + name + '.npmrc'), 'IOS_HOST_NPM_CONFIG_PATH');
    const input = readIosHostInput(p.nodeNpm[name], { end, maxBytes: 4096 });
    try { assert.ok(input.bytes.equals(NPMRC) && (BigInt(input.metadata[2]) & 0o7777n) === 0o600n, 'IOS_HOST_ANONYMOUS_NPM_CONFIG'); } finally { input.bytes.fill(0); }
  }
  assert.equal(p.nodeNpm.parent, path.join(p.paths.runtime, 'npm'), 'IOS_HOST_NPM_OWNED_PARENT');
  directory(p.nodeNpm.parent, end);
  const expected = npmInputReferences(root);
  for (const name of ['tooling', 'registry', 'archive']) {
    assert.deepEqual(p.nodeNpm[name], expected[name], 'IOS_HOST_NPM_SOURCE_BINDING');
    if (name !== 'archive' || archivePayload) {
      const input = readIosHostInput(expected[name], { end, maxBytes: name === 'archive' ? 8388608 : 65536 }); input.bytes.fill(0);
    } else {
      // No archive code is consumed by non-npm roles. The actual constructor
      // independently hashes its full descriptor before any CLI is produced.
      const ref = expected[name], fd = fs.openSync(ref.path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
      try {
        const a = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(ref.path, { bigint: true });
        assert.ok(a.isFile() && !named.isSymbolicLink() && a.uid === BigInt(process.getuid()) && a.nlink === 1n
          && a.size === BigInt(ref.sizeBytes) && same(a, named) && (a.mode & 0o022n) === 0n, 'IOS_HOST_NPM_ARCHIVE_IDENTITY');
        const ns = namespace(ref.path, end); assert.equal(fs.realpathSync(ref.path), ref.path, 'IOS_HOST_NPM_ARCHIVE_NAMESPACE');
        assert.ok(same(a, fs.fstatSync(fd, { bigint: true })) && same(a, fs.lstatSync(ref.path, { bigint: true })), 'IOS_HOST_NPM_ARCHIVE_IDENTITY');
        assert.deepEqual(namespace(ref.path, end), ns, 'IOS_HOST_NPM_ARCHIVE_NAMESPACE');
      } finally { fs.closeSync(fd); }
    }
  }
}
export async function prepareIosNpmRuntime(p, { end = Date.now() + 20000 } = {}) {
  assert.equal(p.tools.node.path, process.execPath, 'IOS_HOST_NPM_PINNED_NODE');
  reviewIosNpmInputs(p, end);
  const tooling = readIosHostInput(p.nodeNpm.tooling, { end, maxBytes: 65536 }); let registry, hooks;
  try {
    registry = readIosHostInput(p.nodeNpm.registry, { end, maxBytes: 65536 });
    const toolingURL = 'data:text/javascript;base64,' + tooling.bytes.toString('base64');
    const registryURL = 'data:text/javascript;base64,' + registry.bytes.toString('base64');
    hooks = registerHooks({ resolve(specifier, context, nextResolve) {
      if (context.parentURL === toolingURL && specifier === './npm-registry.mjs') return { url: registryURL, shortCircuit: true };
      return nextResolve(specifier, context);
    } });
    const { prepareNpm } = await import(toolingURL);
    const prepared = prepareNpm({ parent: p.nodeNpm.parent, archive: p.nodeNpm.archive.path }); check(end);
    assert.ok(path.dirname(prepared.root) === p.nodeNpm.parent && /^caseops-npm-[A-Za-z0-9]{6}$/.test(path.basename(prepared.root))
      && prepared.files === 2149 && prepared.inventory.entries === 2600 && prepared.inventory.observations === 7800, 'IOS_HOST_NPM_CANONICAL_CONSTRUCTOR');
    exact(prepared.environment, NPM_ENV_KEYS, 'IOS_HOST_NPM_CANONICAL_ENVIRONMENT');
    return prepared;
  } finally { hooks?.deregister(); tooling.bytes.fill(0); registry?.bytes.fill(0); }
}

export async function prepareIosHostLaunch({ directory: output, nodePolicy, rubyBundle, tools, role = 'base', fixtureCA = null,
  deadline = Date.now() + 3600000, sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..') } = {}) {
  const end = Math.min(Date.now() + 20000, deadline); check(end);
  assert.ok(process.platform === 'darwin' && process.versions.node === '24.15.0' && Number.isFinite(deadline) && deadline <= Date.now() + 3600000, 'IOS_HOST_ACCEPTED_HOST');
  exact(tools, ['node', 'ruby', 'pod', 'curl', 'python', 'git', 'xcodebuild', 'plutil'], 'IOS_HOST_TOOL_ROLES');
  const versions = { node: '24.15.0', ruby: '4.0.9', pod: '1.17.0', curl: '8.7.1', python: '3.13.17' };
  for (const [name, ref] of Object.entries(tools)) {
    exact(ref, [...refKeys, 'version'], 'IOS_HOST_TOOL_REFERENCE');
    assert.ok(cleanText(ref.version, 256), 'IOS_HOST_TOOL_VERSION'); if (versions[name]) assert.equal(ref.version, versions[name], 'IOS_HOST_TOOL_VERSION');
    const b = readIosHostInput({ path: ref.path, sha256: ref.sha256, sizeBytes: ref.sizeBytes }, { end, maxBytes: 256 * 1024 * 1024, system: true }); b.bytes.fill(0);
  }
  assert.equal(fs.realpathSync(tools.node.path), fs.realpathSync(process.execPath), 'IOS_HOST_ACTUAL_NODE');
  const node = await nodeRecipe(nodePolicy, end); assert.equal(node.policy.role, role, 'IOS_HOST_ROLE');
  assert.deepEqual(node.policy.fixtureCA, fixtureCA, 'IOS_HOST_FIXTURE_BINDING');
  const roots = readIosHostInput(rubyBundle, { end, maxBytes: 1048576, system: true }); let ca;
  try {
    const reviewed = reviewRubyRootBundle(roots.bytes); ca = Buffer.from(reviewed.rows.map(r => r.pem).join('\n') + '\n');
    if (role === 'native-qa') {
      const f = readIosHostInput({ path: fixtureCA.path, sha256: fixtureCA.sha256, sizeBytes: fs.lstatSync(fixtureCA.path).size }, { end, maxBytes: 65536 });
      try { const rows = certs(f.bytes); assert.ok(rows.length === 1 && rows[0].id === fixtureCA.certificateSha256 && rows[0].cert.subject === rows[0].cert.issuer && rows[0].cert.verify(rows[0].cert.publicKey), 'IOS_HOST_FIXTURE_CERTIFICATE'); ca = Buffer.concat([ca, Buffer.from(rows[0].pem + '\n')]); } finally { f.bytes.fill(0); }
    } else assert.ok(role === 'base' && fixtureCA === null, 'IOS_HOST_ROLE');
  } finally { roots.bytes.fill(0); }
  assert.ok(absolute(output), 'IOS_HOST_OUTPUT'); directory(path.dirname(output), end); fs.mkdirSync(output, { mode: 0o700 }); directory(output, end);
  const paths = {};
  for (const name of ['home', 'empty', 'bin', 'cache', 'pods', 'repos', 'temporary', 'build', 'runtime']) { paths[name] = path.join(output, name); fs.mkdirSync(paths[name], { mode: 0o700 }); }
  // Expo/CocoaPods create this deferred project path during the admitted build.
  // CP_HOME_DIR is not Pod::Config.project_pods_root.
  paths.projectPods = path.join(sourceRoot, 'apps/mobile/ios/Pods');
  for (const suffix of ['Library', 'Library/Caches', 'Library/Caches/ReactNative']) fs.mkdirSync(path.join(paths.home, suffix), { mode: 0o700 });
  const bundle = writeExclusive(path.join(output, 'ruby-curl-roots.pem'), ca, end); ca.fill(0);
  const helper = referenceIosHostInput(path.join(sourceRoot, 'scripts/mobile/ios-host-launch.mjs'), end, 131072);
  const executing = readIosHostInput(helper, { end, maxBytes: 131072 });
  try { assert.ok(import.meta.url === pathToFileURL(helper.path).href || import.meta.url === 'data:text/javascript;base64,' + executing.bytes.toString('base64'), 'IOS_HOST_PREPARE_SOURCE_AUTHORITY'); }
  finally { executing.bytes.fill(0); }
  const podHome = path.resolve(path.dirname(tools.pod.path), '../libexec'); directory(podHome, end, false);
  const rubyGems = path.resolve(path.dirname(tools.ruby.path), '../lib/ruby/gems/4.0.0'); directory(rubyGems, end, false);
  const podScript = referenceIosHostInput(path.join(podHome, 'bin/pod'), end, 32768, true);
  const source = {};
  for (const [name, pin] of Object.entries(SOURCE_PINS)) {
    source[name] = referenceIosHostInput(path.join(sourceRoot, 'scripts/mobile', name), end, 32768);
    assert.equal(source[name].sha256, pin, 'IOS_HOST_RUNTIME_SOURCE_UNREVIEWED');
    if (name.endsWith('.py')) { const input = readIosHostInput(source[name], { end, maxBytes: 32768 }); try { writeExclusive(path.join(paths.runtime, name), input.bytes, end); } finally { input.bytes.fill(0); } }
  }
  const shims = {};
  for (const name of ['node', 'npm', 'ruby', 'pod', 'curl', 'git']) shims[name] = writeExclusive(path.join(paths.bin, name), shimBytes(tools.node.path, helper, node.environment, name, { source: source['ios-git-readonly.py'], python: tools.python, git: tools.git }), end, 0o700);
  const npmParent = path.join(paths.runtime, 'npm'); fs.mkdirSync(npmParent, { mode: 0o700 });
  const nodeNpm = { user: writeExclusive(path.join(output, 'npm-user.npmrc'), NPMRC, end), global: writeExclusive(path.join(output, 'npm-global.npmrc'), NPMRC, end),
    parent: npmParent, ...npmInputReferences(sourceRoot) };
  reviewIosNpmInputs({ nodeNpm, paths, helper }, end, true);
  const policy = { schemaVersion: 1, kind: 'caseops-ios-host-launch-v1', role, deadlineEpochMs: deadline, nodePolicy, nodeNpm, tools, helper, podHome, rubyGems, podScript,
    rubySourceBundle: rubyBundle, rubyRootCount: 188, rubyRootSetSha256: RUBY_ROOT_SET, bundle, fixtureCA, paths, shims, source,
    curlScope: 'explicit-selected-ruby188-file; native-OS-default-unverified', requiresOwnedOuterController: true };
  const policyRef = writeExclusive(path.join(output, 'policy.json'), Buffer.from(JSON.stringify(policy, null, 2) + '\n'), end);
  return { policyRef, policy, globalTrustChanges: 0, builds: 0, downloads: 0, nativeAcceptance: false };
}

export async function verifyIosHostLaunch(policyRef, { end = Date.now() + 20000 } = {}) {
  end = Math.min(end, Date.now() + 20000);
  const loaded = readIosHostInput(policyRef, { end, maxBytes: 65536 }); let p;
  try { p = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(loaded.bytes)); } finally { loaded.bytes.fill(0); }
  exact(p, ['schemaVersion', 'kind', 'role', 'deadlineEpochMs', 'nodePolicy', 'nodeNpm', 'tools', 'helper', 'podHome', 'rubyGems', 'podScript', 'rubySourceBundle', 'rubyRootCount', 'rubyRootSetSha256', 'bundle', 'fixtureCA', 'paths', 'shims', 'source', 'curlScope', 'requiresOwnedOuterController'], 'IOS_HOST_POLICY_KEYS');
  assert.ok(p.schemaVersion === 1 && p.kind === 'caseops-ios-host-launch-v1' && p.rubyRootCount === 188 && p.rubyRootSetSha256 === RUBY_ROOT_SET
    && p.requiresOwnedOuterController === true, 'IOS_HOST_POLICY'); check(Math.min(end, p.deadlineEpochMs));
  assert.equal(p.tools?.node?.path, fs.realpathSync(process.execPath), 'IOS_HOST_ACTUAL_NODE');
  const node = await nodeRecipe(p.nodePolicy, end); assert.ok(p.role === node.policy.role, 'IOS_HOST_ROLE'); assert.deepEqual(p.fixtureCA, node.policy.fixtureCA, 'IOS_HOST_FIXTURE_BINDING');
  exact(p.paths, ['home', 'empty', 'bin', 'cache', 'pods', 'repos', 'temporary', 'build', 'runtime', 'projectPods'], 'IOS_HOST_PATHS');
  const parent = path.dirname(policyRef.path); directory(parent, end);
  reviewIosNpmInputs(p, end);
  reviewProjectNpm(p, end);
  assert.equal(p.bundle.path, path.join(parent, 'ruby-curl-roots.pem'), 'IOS_HOST_OWNED_BUNDLE');
  for (const [name, value] of Object.entries(p.paths)) {
    if (name === 'projectPods') {
      assert.equal(value, path.resolve(path.dirname(p.helper.path), '../../apps/mobile/ios/Pods'), 'IOS_HOST_PROJECT_PODS_BINDING');
    } else { assert.equal(value, path.join(parent, name), 'IOS_HOST_OWNED_PATH'); directory(value, end); }
  }
  empty(p.paths.empty, end); const homeObservation = reviewIosHostHome(p.paths.home, end);
  const bundle = readIosHostInput(p.bundle, { end, maxBytes: 1048576 });
  try {
    const rows = certs(bundle.bytes), fixtureId = p.fixtureCA?.certificateSha256;
    const base = rows.filter(r => r.id !== fixtureId); reviewRubyRootBundle(Buffer.from(base.map(r => r.pem).join('\n')));
    assert.ok(rows.length === 188 + (p.role === 'native-qa' ? 1 : 0), 'IOS_HOST_BUNDLE_COUNT');
  } catch (error) { bundle.bytes.fill(0); throw error; }
  try {
    const helper = readIosHostInput(p.helper, { end, maxBytes: 131072 });
    try { assert.ok(import.meta.url === 'data:text/javascript;base64,' + helper.bytes.toString('base64') || import.meta.url === pathToFileURL(p.helper.path).href, 'IOS_HOST_EXECUTING_HELPER_CHANGED'); } finally { helper.bytes.fill(0); }
    exact(p.shims, ['node', 'npm', 'ruby', 'pod', 'curl', 'git'], 'IOS_HOST_SHIM_KEYS');
    for (const [name, ref] of Object.entries(p.shims)) {
      assert.ok(ref.path === path.join(p.paths.bin, name), 'IOS_HOST_SHIM_PATH');
      const input = readIosHostInput(ref, { end, maxBytes: 65536 }); try { assert.deepEqual(input.bytes, shimBytes(p.tools.node.path, p.helper, node.environment, name, { source: p.source['ios-git-readonly.py'], python: p.tools.python, git: p.tools.git }), 'IOS_HOST_SHIM_CHANGED'); } finally { input.bytes.fill(0); }
    }
    exact(p.tools, ['node', 'ruby', 'pod', 'curl', 'python', 'git', 'xcodebuild', 'plutil'], 'IOS_HOST_TOOL_ROLES');
    const versions = { node: '24.15.0', ruby: '4.0.9', pod: '1.17.0', curl: '8.7.1', python: '3.13.17' };
    for (const [name, ref] of Object.entries(p.tools)) {
      exact(ref, [...refKeys, 'version'], 'IOS_HOST_TOOL_REFERENCE');
      assert.ok(cleanText(ref.version, 256), 'IOS_HOST_TOOL_VERSION'); if (versions[name]) assert.equal(ref.version, versions[name], 'IOS_HOST_TOOL_VERSION');
      const actual = readIosHostInput({ path: ref.path, sha256: ref.sha256, sizeBytes: ref.sizeBytes }, { end, maxBytes: 256 * 1024 * 1024, system: true }); actual.bytes.fill(0);
    }
    assert.equal(fs.realpathSync(p.tools.node.path), fs.realpathSync(process.execPath), 'IOS_HOST_ACTUAL_NODE');
    const original = readIosHostInput(p.rubySourceBundle, { end, maxBytes: 1048576, system: true });
    try { reviewRubyRootBundle(original.bytes); } finally { original.bytes.fill(0); }
    assert.equal(p.podHome, path.resolve(path.dirname(p.tools.pod.path), '../libexec'), 'IOS_HOST_GEM_HOME'); directory(p.podHome, end, false);
    assert.equal(p.rubyGems, path.resolve(path.dirname(p.tools.ruby.path), '../lib/ruby/gems/4.0.0'), 'IOS_HOST_RUBY_GEMS'); directory(p.rubyGems, end, false);
    assert.equal(p.podScript.path, path.join(p.podHome, 'bin/pod'), 'IOS_HOST_POD_SCRIPT');
    exact(p.source, Object.keys(SOURCE_PINS), 'IOS_HOST_SOURCE_KEYS');
    for (const [name, pin] of Object.entries(SOURCE_PINS)) {
      const ref = p.source[name]; assert.ok(ref.sha256 === pin && ref.path === path.join(path.dirname(p.helper.path), name), 'IOS_HOST_SOURCE_BINDING');
      const input = readIosHostInput(ref, { end, maxBytes: 32768 }); input.bytes.fill(0);
      if (name.endsWith('.py')) { const copy = readIosHostInput({ ...ref, path: path.join(p.paths.runtime, name) }, { end, maxBytes: 32768 }); copy.bytes.fill(0); }
    }
    const namesInput = readIosHostInput(p.source['ios-node-build-env.json'], { end, maxBytes: 32768 }); let nodeBuildNames;
    try {
      const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(namesInput.bytes));
      assert.ok(value.schemaVersion === 1 && value.kind === 'caseops-ios-node-build-environment-names'
        && Array.isArray(value.names) && value.names.length === 586 && new Set(value.names).size === value.names.length
        && value.names.every(k => /^[A-Z_][A-Z0-9_]*$/.test(k) && !unsafe.test(k)), 'IOS_HOST_BUILD_NAMES'); nodeBuildNames = value.names;
    } finally { namesInput.bytes.fill(0); }
    const script = readIosHostInput(p.podScript, { end, maxBytes: 32768, system: true });
    try {
      const ref = p.source['ios-host-pods.rb']; assert.equal(ref.sha256, IOS_PODS_SOURCE_SHA256, 'IOS_HOST_PODS_SOURCE_UNREVIEWED');
      assert.equal(ref.path, path.join(path.dirname(p.helper.path), 'ios-host-pods.rb'), 'IOS_HOST_PODS_SOURCE_PATH');
      const code = readIosHostInput(ref, { end, maxBytes: 32768 });
      return { policy: p, node, bundle, podsSource: code.bytes, podEntry: script.bytes, homeObservation, nodeBuildNames };
    } catch (error) { script.bytes.fill(0); throw error; }
  } catch (error) { bundle.bytes.fill(0); throw error; }
}
export function validatePodsCurlArguments(args) {
  assert.ok(Array.isArray(args) && args.length >= 9 && args.length <= 64 && args.every(v => cleanText(v)), 'IOS_HOST_CURL_ARGUMENTS');
  assert.deepEqual([args[0], args[1], args[2], ...args.slice(5, 9)], ['-f', '-L', '-o', '--create-dirs', '--netrc-optional', '--retry', '2'], 'IOS_HOST_EXACT_DOWNLOADER_FORM');
  assert.ok(absolute(args[3]), 'IOS_HOST_CURL_OUTPUT');
  const url = new URL(args[4]); assert.ok(url.protocol === 'https:' && !url.username && !url.password && !url.hash && !args[4].includes('#'), 'IOS_HOST_HTTPS_DOWNLOAD');
  let i = 9, marker = false;
  if (args[i]?.startsWith('-A ')) { assert.match(args[i], /^-A '[^'\r\n\0]{1,1024}'$/, 'IOS_HOST_CURL_USER_AGENT'); i++; }
  while (i < args.length) {
    assert.equal(args[i++], '-H', 'IOS_HOST_CURL_OPTION_REFUSED'); const header = args[i++];
    assert.ok(cleanText(header, 4096) && /^[A-Za-z0-9!#$%&'*+.^_`|~-]+: [^\r\n\0]*$/.test(header), 'IOS_HOST_CURL_HEADER');
    if (/^X-CaseOps-Automated-Test:/i.test(header)) { assert.equal(header, 'X-CaseOps-Automated-Test: no-paid-providers', 'IOS_HOST_MARKER'); assert.equal(marker, false, 'IOS_HOST_DUPLICATE_MARKER'); marker = true; }
  }
  return marker ? [...args] : [...args, '-H', 'X-CaseOps-Automated-Test: no-paid-providers'];
}
function httpsDownload(value) {
  assert.ok(cleanText(value), 'IOS_HOST_HTTPS_DOWNLOAD');
  const u = new URL(value);
  assert.ok(u.protocol === 'https:' && !u.username && !u.password && !u.hash && !value.includes('#'), 'IOS_HOST_HTTPS_DOWNLOAD');
  return value;
}
export function validateIosCurlArguments(args) {
  assert.ok(Array.isArray(args) && args.length <= 64 && args.every(v => cleanText(v)), 'IOS_HOST_CURL_ARGUMENTS');
  if (args[0] === '-f') return { args: validatePodsCurlArguments(args), output: args[3], family: 'cocoapods-archive' };
  let output = null, family;
  if (args.length === 5 && args[0] === '-A' && /^react-native-[A-Za-z0-9.+_-]{1,64}$/.test(args[1]) && args[3] === '-Lo' && absolute(args[4])) {
    httpsDownload(args[2]); output = args[4]; family = 'react-native-archive';
  } else if (args.length === 6 && JSON.stringify(args.slice(0, 5)) === JSON.stringify(['-Ls', '-o', '/dev/null', '-w', '%{url_effective}'])) {
    httpsDownload(args[5]); family = 'react-native-redirect';
  } else if (args.length === 7 && JSON.stringify(args.slice(0, 6)) === JSON.stringify(['-o', '/dev/null', '--silent', '-Iw', '%{http_code}', '-L'])) {
    httpsDownload(args[6]); family = 'react-native-head';
  } else if (args.length === 2 && args[0] === '-sL' && new URL(httpsDownload(args[1])).pathname.endsWith('.sha1')) {
    family = 'react-native-sha1';
  } else assert.fail('IOS_HOST_EXACT_SDK_CURL_FORM');
  return { args: [...args, '-H', 'X-CaseOps-Automated-Test: no-paid-providers'], output, family };
}

const IOS_LOCAL_ARCHIVES = (() => { const value = {"schemaVersion":1,"lock":{"path":"apps/mobile/package-lock.json","sha256":"d15da4b402622883d58f0c61cd5b8fd7bc95cb36bb8ead1b3cc46b1b596c5def","sizeBytes":267494},"producer":{"path":"apps/mobile/node_modules/expo-modules-autolinking/scripts/ios/precompiled_modules.rb","sha256":"480dc0e74b8712833cace4087c9ab16cd3115caa2849786432eb2c387e2f743e","sizeBytes":128827},"packages":{"node_modules/expo/node_modules/expo-font":{"name":"expo-font","version":"58.0.11","manifestSha256":"a39a111996fb3549857ce64b59fee0900af9d953f9b8581e5f116ae647041220","manifestSizeBytes":2260,"integrity":"sha512-6r7s6xk2L2orvum+x+TY1fzEcMtuCBRQTLgC/Su2uLzNPpT4L+E+S4IAGy8ZIjeVvwk2j2pj+HiZ23O7eh1PGQ==","resolved":"https://registry.npmjs.org/expo-font/-/expo-font-58.0.11.tgz","licenseSha256":"fb3ca4a837f5779e83cef89b78253a8949cfb9429c340309f62d0465ec6610b4"},"node_modules/expo-file-system":{"name":"expo-file-system","version":"58.0.13","manifestSha256":"7a5f05dffbdfb6071054dc164f44be739b25397f846845a38989686ef7b32cac","manifestSizeBytes":2254,"integrity":"sha512-+/1aFErkawyky5UdWI06zYeO2DeHUnfaWnYHeiI8M8Z/sB6L66gI3WUxqtvUvKJoaM0Ti1CximD3x3JwteLYIg==","resolved":"https://registry.npmjs.org/expo-file-system/-/expo-file-system-58.0.13.tgz","licenseSha256":"fb3ca4a837f5779e83cef89b78253a8949cfb9429c340309f62d0465ec6610b4"},"node_modules/expo-font":{"name":"expo-font","version":"58.0.10","manifestSha256":"c5e1bb077f5a2193b58e5942ce0713398d08afa1cd0cf2372e196bce47d5e9c4","manifestSizeBytes":2260,"integrity":"sha512-13orvRCiXg3EuirjMznWTKwFzhKHvtHRkUdgbvolbkyA1+EAbYDpp7LJMnvDnbTFU/m8Kb5awvOiaGzPYQ/ojg==","resolved":"https://registry.npmjs.org/expo-font/-/expo-font-58.0.10.tgz","licenseSha256":"fb3ca4a837f5779e83cef89b78253a8949cfb9429c340309f62d0465ec6610b4"},"node_modules/expo-modules-core":{"name":"expo-modules-core","version":"58.0.28","manifestSha256":"47517f4ef32b3d385516b939e99800b0a816481682ecb94c409eae9720827373","manifestSizeBytes":2846,"integrity":"sha512-2FCnT8mIubdQAHVtX9fVMN9qajF7hGDC3CjxxBG0HlyK7NEsxUDKkukiNVzqQpwiI+jJx7ysG0YvATwKKlu1sw==","resolved":"https://registry.npmjs.org/expo-modules-core/-/expo-modules-core-58.0.28.tgz","licenseSha256":"fb3ca4a837f5779e83cef89b78253a8949cfb9429c340309f62d0465ec6610b4"}},"archives":[{"path":"apps/mobile/node_modules/expo/node_modules/expo-font/prebuilds/output/debug/xcframeworks/ExpoFont.tar.gz","packageRelative":"node_modules/expo/node_modules/expo-font","flavor":"debug","product":"ExpoFont","sha256":"49334bfec7c0c87913499c1694e5e00d78fe87e8f18d0497fcfffe24cc5fe4e8","sizeBytes":1317476},{"path":"apps/mobile/node_modules/expo/node_modules/expo-font/prebuilds/output/release/xcframeworks/ExpoFont.tar.gz","packageRelative":"node_modules/expo/node_modules/expo-font","flavor":"release","product":"ExpoFont","sha256":"290797137e75ad1edb793ab3019577a0295a4d0196c3684a1737a2d0c2999f92","sizeBytes":1265246},{"path":"apps/mobile/node_modules/expo-file-system/prebuilds/output/debug/xcframeworks/ExpoFileSystem.tar.gz","packageRelative":"node_modules/expo-file-system","flavor":"debug","product":"ExpoFileSystem","sha256":"3b10e581b292a4550fa940b2d0bcfe2c5274f1a88e974c0af2386ad26fda3f2e","sizeBytes":4431085},{"path":"apps/mobile/node_modules/expo-file-system/prebuilds/output/release/xcframeworks/ExpoFileSystem.tar.gz","packageRelative":"node_modules/expo-file-system","flavor":"release","product":"ExpoFileSystem","sha256":"ff79f423af91eafd8b8a3607d2d64b3bed9d3f6098035d3fbd9c94fe910a6766","sizeBytes":3235468},{"path":"apps/mobile/node_modules/expo-font/prebuilds/output/debug/xcframeworks/ExpoFont.tar.gz","packageRelative":"node_modules/expo-font","flavor":"debug","product":"ExpoFont","sha256":"86f51373e8e401513ba873f48f2ae00c1a9cb8df57d5a894842bc940b9eb9639","sizeBytes":1229343},{"path":"apps/mobile/node_modules/expo-font/prebuilds/output/release/xcframeworks/ExpoFont.tar.gz","packageRelative":"node_modules/expo-font","flavor":"release","product":"ExpoFont","sha256":"b1cdfbaeefca5dfe219743dbce305924158b91569cc3ecf8d5ece0445a2d601a","sizeBytes":1173496},{"path":"apps/mobile/node_modules/expo-modules-core/prebuilds/output/debug/xcframeworks/ExpoModulesCore.tar.gz","packageRelative":"node_modules/expo-modules-core","flavor":"debug","product":"ExpoModulesCore","sha256":"bc3dcb318b342ca373b5149e64989b7e40decd848da6f4931ff817e37d6df639","sizeBytes":16127814},{"path":"apps/mobile/node_modules/expo-modules-core/prebuilds/output/debug/xcframeworks/ExpoModulesWorklets.tar.gz","packageRelative":"node_modules/expo-modules-core","flavor":"debug","product":"ExpoModulesWorklets","sha256":"581e17eaf29bfbdb1d7e07b5832cc4314bfe89aeddfe9d2fced19ec2b00daff0","sizeBytes":1030869},{"path":"apps/mobile/node_modules/expo-modules-core/prebuilds/output/release/xcframeworks/ExpoModulesCore.tar.gz","packageRelative":"node_modules/expo-modules-core","flavor":"release","product":"ExpoModulesCore","sha256":"e67a98002c67327a13bba00f645a192799327e57276ce3b1d625e09937bf036c","sizeBytes":14239057},{"path":"apps/mobile/node_modules/expo-modules-core/prebuilds/output/release/xcframeworks/ExpoModulesWorklets.tar.gz","packageRelative":"node_modules/expo-modules-core","flavor":"release","product":"ExpoModulesWorklets","sha256":"12f3c6a36d914b1a72e5dd516f541aa71a6fc0feeb770de4f6967a778670d646","sizeBytes":975452}]}; Object.freeze(value.lock); Object.freeze(value.producer); Object.values(value.packages).forEach(Object.freeze); Object.freeze(value.packages); value.archives.forEach(Object.freeze); Object.freeze(value.archives); return Object.freeze(value); })();
const localArchiveReceipts = new WeakSet();
export function validateIosLocalArchiveArguments(args, sourceRoot) {
  assert.ok(typeof process.getuid === 'function', 'IOS_HOST_POSIX_OWNER_REQUIRED');
  assert.ok(absolute(sourceRoot) && cleanText(sourceRoot), 'IOS_HOST_LOCAL_ARCHIVE_ROOT');
  assert.ok(Array.isArray(args) && [10, 12].includes(args.length), 'IOS_HOST_LOCAL_ARCHIVE_FORM');
  assert.deepEqual(args.slice(0, 3), ['-f', '-L', '-o'], 'IOS_HOST_LOCAL_ARCHIVE_FORM');
  assert.deepEqual(args.slice(5, 9), ['--create-dirs', '--netrc-optional', '--retry', '2'], 'IOS_HOST_LOCAL_ARCHIVE_FORM');
  assert.equal(args[9], "-A 'CocoaPods/1.17.0 cocoapods-downloader/2.1'", 'IOS_HOST_LOCAL_ARCHIVE_FORM');
  if (args.length === 12) assert.deepEqual(args.slice(10), ['-H', 'X-CaseOps-Automated-Test: no-paid-providers'], 'IOS_HOST_LOCAL_ARCHIVE_FORM');
  assert.ok(args.every(v => cleanText(v)) && absolute(args[3]) && path.basename(args[3]) === 'file.tgz', 'IOS_HOST_LOCAL_ARCHIVE_FORM');
  assert.ok(args[4].startsWith('file:///'), 'IOS_HOST_LOCAL_ARCHIVE_URI');
  const url = new URL(args[4]);
  assert.ok(url.protocol === 'file:' && !url.hostname && !url.username && !url.password && !url.search && !url.hash, 'IOS_HOST_LOCAL_ARCHIVE_URI');
  const matches = IOS_LOCAL_ARCHIVES.archives.filter(row => args[4] === pathToFileURL(path.join(sourceRoot, row.path)).href);
  assert.equal(matches.length, 1, 'IOS_HOST_LOCAL_ARCHIVE_UNKNOWN');
  return { args: [...args], output: args[3], archive: matches[0], sourceRoot };
}
export function reviewIosLocalArchive(p, args, end = Date.now() + 20000) {
  const root = path.resolve(path.dirname(p.helper.path), '../..');
  directory(root, end, false); assert.equal(fs.lstatSync(root, { bigint: true }).uid, BigInt(process.getuid()), 'IOS_HOST_LOCAL_ARCHIVE_ROOT');
  const form = validateIosLocalArchiveArguments(args, root), table = IOS_LOCAL_ARCHIVES;
  assert.equal(table.schemaVersion, 1, 'IOS_HOST_LOCAL_ARCHIVE_CATALOG');
  assert.ok(table.archives.length === 10 && Object.keys(table.packages).length === 4 && table.archives.reduce((n, x) => n + x.sizeBytes, 0) === 45025306, 'IOS_HOST_LOCAL_ARCHIVE_CATALOG');
  const relativeTarget = path.relative(p.paths.temporary, form.output).split(path.sep);
  assert.ok(relativeTarget.length === 2 && /^d[0-9]{8}-[0-9]+-[a-z0-9]+$/.test(relativeTarget[0]) && relativeTarget[1] === 'file.tgz', 'IOS_HOST_LOCAL_ARCHIVE_OUTPUT');
  const outputParent = directory(path.dirname(form.output), end);
  const read = (relative, pin, size, max) => {
    const file = path.join(root, relative), input = readIosHostInput({ path: file, sha256: pin, sizeBytes: size }, { end, maxBytes: max });
    try { assert.equal(input.canonical, file, 'IOS_HOST_LOCAL_ARCHIVE_SOURCE_ALIAS'); return input; }
    catch (error) { input.bytes.fill(0); throw error; }
  };
  let lock, producer, manifest, archive;
  try {
    lock = read(table.lock.path, table.lock.sha256, table.lock.sizeBytes, 1048576);
    const locked = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(lock.bytes)).packages[form.archive.packageRelative];
    const pkg = table.packages[form.archive.packageRelative];
    assert.ok(locked && locked.version === pkg.version && locked.integrity === pkg.integrity && locked.resolved === pkg.resolved && !locked.link, 'IOS_HOST_LOCAL_ARCHIVE_LOCK');
    producer = read(table.producer.path, table.producer.sha256, table.producer.sizeBytes, 262144);
    manifest = read('apps/mobile/' + form.archive.packageRelative + '/package.json', pkg.manifestSha256, pkg.manifestSizeBytes, 65536);
    const packageValue = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(manifest.bytes));
    assert.ok(packageValue.name === pkg.name && packageValue.version === pkg.version, 'IOS_HOST_LOCAL_ARCHIVE_PACKAGE');
    archive = read(form.archive.path, form.archive.sha256, form.archive.sizeBytes, 33554432);
    const receipt = { ...form, outputParent, bytes: archive.bytes, expectedSha256: form.archive.sha256, consumed: false,
      source: { path: archive.canonical, metadata: archive.metadata, namespace: archive.namespace } };
    archive = null; localArchiveReceipts.add(receipt); return receipt;
  } finally { lock?.bytes.fill(0); producer?.bytes.fill(0); manifest?.bytes.fill(0); archive?.bytes.fill(0); }
}
function checkIosLocalArchiveSource(receipt, end) {
  check(end); const source = receipt.source, current = fs.lstatSync(source.path, { bigint: true });
  assert.ok(current.isFile() && !current.isSymbolicLink() && fs.realpathSync(source.path) === source.path, 'IOS_HOST_LOCAL_ARCHIVE_SOURCE_CHANGED');
  assert.deepEqual(fields.map(k => String(current[k])), source.metadata, 'IOS_HOST_LOCAL_ARCHIVE_SOURCE_CHANGED');
  assert.deepEqual(namespace(source.path, end), source.namespace, 'IOS_HOST_LOCAL_ARCHIVE_SOURCE_NAMESPACE_CHANGED');
}
function transferIosLocalArchive(command, end) {
  const receipt = command.localArchive;
  assert.ok(receipt && localArchiveReceipts.has(receipt) && receipt.consumed === false && Buffer.isBuffer(receipt.bytes), 'IOS_HOST_LOCAL_ARCHIVE_RECEIPT');
  receipt.consumed = true;
  assert.equal(sha(receipt.bytes), receipt.expectedSha256, 'IOS_HOST_LOCAL_ARCHIVE_BUFFER_CHANGED');
  checkIosLocalArchiveSource(receipt, end);
  const output = receipt.output;
  assert.deepEqual(directory(path.dirname(output), end), receipt.outputParent, 'IOS_HOST_LOCAL_ARCHIVE_OUTPUT_NAMESPACE_CHANGED');
  ownedMutationPath(output, command.policy.paths, end);
  const parents = namespace(output, end); let fd;
  try {
    try { fd = fs.openSync(output, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK, 0o600); }
    catch (error) { if (error.code !== 'EEXIST') throw error; fd = fs.openSync(output, fs.constants.O_RDWR | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK); }
    const before = fs.fstatSync(fd, { bigint: true });
    assert.ok(before.isFile() && before.uid === BigInt(process.getuid()) && before.nlink === 1n && before.size === 0n && (before.mode & 0o022n) === 0n, 'IOS_HOST_LOCAL_ARCHIVE_EMPTY_OUTPUT');
    const named = fs.lstatSync(output, { bigint: true });
    assert.ok(named.isFile() && !named.isSymbolicLink() && same(before, named) && fs.realpathSync(output) === output, 'IOS_HOST_LOCAL_ARCHIVE_OUTPUT_CHANGED');
    checkIosLocalArchiveSource(receipt, end);
    let at = 0;
    while (at < receipt.bytes.length) { check(end); const n = fs.writeSync(fd, receipt.bytes, at, Math.min(65536, receipt.bytes.length - at), at); assert.ok(n > 0, 'IOS_HOST_LOCAL_ARCHIVE_WRITE'); at += n; }
    fs.fsyncSync(fd);
    const written = fs.fstatSync(fd, { bigint: true });
    assert.equal(written.size, BigInt(receipt.bytes.length), 'IOS_HOST_LOCAL_ARCHIVE_OUTPUT_CHANGED');
    const hash = createHash('sha256'), chunk = Buffer.alloc(65536); at = 0;
    try { while (at < receipt.bytes.length) { check(end); const n = fs.readSync(fd, chunk, 0, Math.min(chunk.length, receipt.bytes.length - at), at); assert.ok(n > 0, 'IOS_HOST_LOCAL_ARCHIVE_READBACK'); hash.update(chunk.subarray(0, n)); at += n; } }
    finally { chunk.fill(0); }
    assert.equal(hash.digest('hex'), receipt.expectedSha256, 'IOS_HOST_LOCAL_ARCHIVE_READBACK');
    const after = fs.fstatSync(fd, { bigint: true }), finalNamed = fs.lstatSync(output, { bigint: true });
    assert.ok(after.isFile() && same(written, after) && same(after, finalNamed) && !finalNamed.isSymbolicLink() && fs.realpathSync(output) === output, 'IOS_HOST_LOCAL_ARCHIVE_OUTPUT_CHANGED');
    assert.deepEqual(namespace(output, end), parents, 'IOS_HOST_LOCAL_ARCHIVE_OUTPUT_NAMESPACE_CHANGED');
    checkIosLocalArchiveSource(receipt, end);
    return 0;
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}

const gitRef = s => cleanText(s, 256) && /^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(s) && !s.includes('..') && !s.includes('//') && !s.endsWith('/') && !s.endsWith('.lock');
const mutationRoots = paths => [...['cache', 'temporary', 'pods', 'repos'].map(k => paths[k]), path.join(paths.home, 'Library/Caches/ReactNative'), ...(typeof paths.projectPods === 'string' ? [paths.projectPods] : [])];
const ownedPath = (value, paths) => absolute(value) && mutationRoots(paths).some(p => value.startsWith(p + path.sep));
export function projectIosGitArguments(args, paths) {
  assert.ok(Array.isArray(args) && args.length <= 256 && args.every(s => cleanText(s)), 'IOS_HOST_GIT_ARGUMENTS');
  try { return { args: validateIosReadonlyGitArguments(args), network: false, repository: null, clone: false, family: 'local-source-inventory' }; }
  catch (error) { assert.equal(error.message, 'IOS_HOST_GIT_TLS_UNPROVEN'); }
  assert.ok(args.length <= 16, 'IOS_HOST_GIT_MUTATION_ARGUMENT_BOUND');
  let network = false, repository = null, clone = false, family;
  if (args[0] === 'ls-remote') {
    const offset = args[1] === '--' ? 2 : 1;
    assert.ok(args.length >= offset + 1 && args.length <= offset + 2 && (args.length === offset + 1 || gitRef(args[offset + 1])), 'IOS_HOST_EXACT_GIT_FORM');
    httpsDownload(args[offset]); network = true; family = 'ls-remote';
  } else if (args[0] === 'clone') {
    assert.ok(args.length >= 4 && args[3] === '--template=' && ownedPath(args[2], paths), 'IOS_HOST_EXACT_GIT_FORM');
    httpsDownload(args[1]); let i = 4;
    if (args[i] === '--single-branch') { assert.deepEqual(args.slice(i, i + 3), ['--single-branch', '--depth', '1'], 'IOS_HOST_EXACT_GIT_FORM'); i += 3; }
    if (args[i] === '--branch') { assert.ok(gitRef(args[i + 1]), 'IOS_HOST_GIT_REF'); i += 2; }
    assert.equal(i, args.length, 'IOS_HOST_EXACT_GIT_FORM'); network = true; repository = args[2]; clone = true; family = 'clone';
  } else {
    assert.ok(args[0] === '-C' && ownedPath(args[1], paths), 'IOS_HOST_GIT_OWNED_REPOSITORY'); repository = args[1]; const a = args.slice(2);
    if (JSON.stringify(a) === JSON.stringify(['rev-parse', 'HEAD']) || JSON.stringify(a) === JSON.stringify(['rev-parse', '--abbrev-ref', 'HEAD'])
      || JSON.stringify(a) === JSON.stringify(['config', '--get', 'remote.origin.url']) || JSON.stringify(a) === JSON.stringify(['diff', '--name-only'])
      || a.length === 3 && a[0] === 'diff' && a[1] === '--name-only' && /^[a-f0-9]{40}\.\.HEAD$/.test(a[2])) family = 'owned-read';
    else if (a[0] === 'checkout' && (a.length === 2 && gitRef(a[1]) || a.length === 3 && a[1] === '--quiet' && /^[a-f0-9]{40}$/.test(a[2]))) family = 'checkout';
    else if (a.length === 3 && a[0] === 'reset' && a[1] === '--hard' && /^origin\//.test(a[2]) && gitRef(a[2])) family = 'reset';
    else if (a[0] === 'fetch' && a[1] === 'origin' && (a.length === 2 || a.length === 3 && (a[2] === '--progress' || gitRef(a[2])))) { network = true; family = 'fetch'; }
    else if (JSON.stringify(a) === JSON.stringify(['pull', '--ff-only'])) { network = true; family = 'pull'; }
    else if (JSON.stringify(a) === JSON.stringify(['submodule', 'update', '--init', '--recursive'])) { network = true; family = 'submodule'; }
    else assert.fail('IOS_HOST_EXACT_GIT_FORM');
  }
  const fixed = ['core.fsmonitor=false', 'core.untrackedCache=false', 'core.hooksPath=/dev/null', 'credential.helper=', 'core.askPass=/usr/bin/false',
    'http.sslVerify=true', 'http.sslCAInfo=/dev/fd/3', 'http.sslCAPath=' + paths.empty, 'http.proxy=', 'http.extraHeader=',
    'http.extraHeader=X-CaseOps-Automated-Test: no-paid-providers', 'protocol.allow=never', 'protocol.https.allow=always'];
  return { args: [...fixed.flatMap(s => ['-c', s]), ...args], network, repository, clone, family };
}
function ownedMutationPath(value, paths, end) {
  assert.ok(ownedPath(value, paths), 'IOS_HOST_OWNED_MUTATION_PATH');
  const root = mutationRoots(paths).filter(p => value.startsWith(p + path.sep)).sort((a, b) => b.length - a.length)[0];
  // Project Pods is generated after prebuild, normally0755/current-owned. Other
  // roots were created0700 by preparation. Never broaden to the whole checkout.
  directory(root, end, root !== paths.projectPods);
  if (root === paths.projectPods) {
    const source = path.resolve(root, '../../../..');
    for (let parent = root;; parent = path.dirname(parent)) {
      check(end); const row = fs.lstatSync(parent, { bigint: true });
      assert.ok(row.isDirectory() && !row.isSymbolicLink() && row.uid === BigInt(process.getuid()) && (row.mode & 0o022n) === 0n, 'IOS_HOST_PROJECT_PODS_NAMESPACE');
      if (parent === source) break;
    }
  }
  assert.equal(fs.lstatSync(root, { bigint: true }).uid, BigInt(process.getuid()), 'IOS_HOST_MUTATION_NAMESPACE'); let p = root;
  const parts = path.relative(root, value).split(path.sep);
  for (let i = 0; i < parts.length; i++) { const name = parts[i];
    check(end); assert.ok(name && name !== '.' && name !== '..', 'IOS_HOST_OWNED_MUTATION_PATH'); p = path.join(p, name);
    let s = fs.lstatSync(p, { bigint: true, throwIfNoEntry: false });
    if (!s && i < parts.length - 1) { fs.mkdirSync(p, { mode: 0o700 }); s = fs.lstatSync(p, { bigint: true }); }
    if (!s) break;
    assert.ok(!s.isSymbolicLink() && s.uid === BigInt(process.getuid()) && (s.mode & 0o022n) === 0n && fs.realpathSync(p) === p
      && (s.isDirectory() || i === parts.length - 1 && s.isFile() && s.nlink === 1n), 'IOS_HOST_MUTATION_NAMESPACE');
  }
  return { root, namespace: namespace(value, end) };
}
function gitConfig(ref, end) {
  const input = referenceIosHostInput(ref, end, 65536); const held = readIosHostInput(input, { end, maxBytes: 65536 });
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(held.bytes); assert.ok(!text.includes('\0'), 'IOS_HOST_GIT_CONFIG');
    let section = '', remote = null;
    for (const row of text.split(/\r?\n/)) {
      check(end); const line = row.trim(); if (!line || line.startsWith('#') || line.startsWith(';')) continue;
      if (/^\[(core|remote "origin"|branch "[A-Za-z0-9][A-Za-z0-9._/-]*"|submodule "[A-Za-z0-9][A-Za-z0-9._/-]*")\]$/.test(line)) { section = line; continue; }
      const m = /^([A-Za-z][A-Za-z0-9]*)\s*=\s*(.+)$/.exec(line); assert.ok(m, 'IOS_HOST_GIT_CONFIG'); const [, key, value] = m;
      if (section === '[core]') assert.ok(({repositoryformatversion:['0'],filemode:['true','false'],bare:['false'],logallrefupdates:['true'],ignorecase:['true','false'],precomposeunicode:['true','false']})[key]?.includes(value), 'IOS_HOST_GIT_CONFIG');
      else if (section === '[remote "origin"]' && key === 'url') { assert.equal(remote, null, 'IOS_HOST_GIT_CONFIG'); remote = httpsDownload(value); }
      else if (section === '[remote "origin"]' && key === 'fetch') assert.match(value, /^\+refs\/heads\/(?:\*|[A-Za-z0-9][A-Za-z0-9._/-]*):refs\/remotes\/origin\/(?:\*|[A-Za-z0-9][A-Za-z0-9._/-]*)$/, 'IOS_HOST_GIT_CONFIG');
      else if (section.startsWith('[branch ')) assert.ok(key === 'remote' && value === 'origin' || key === 'merge' && value.startsWith('refs/heads/') && gitRef(value), 'IOS_HOST_GIT_CONFIG');
      else if (section.startsWith('[submodule ')) assert.ok(key === 'active' && value === 'true' || key === 'url' && httpsDownload(value), 'IOS_HOST_GIT_CONFIG');
      else assert.fail('IOS_HOST_GIT_CONFIG');
    }
    assert.ok(remote, 'IOS_HOST_GIT_ORIGIN_REQUIRED'); return input;
  } finally { held.bytes.fill(0); }
}
export function admitIosGitRepository(command, { end = Date.now() + 20000, completed = false } = {}) {
  assert.ok(typeof process.getuid === 'function', 'IOS_HOST_POSIX_OWNER_REQUIRED');
  const g = command.git; assert.ok(g, 'IOS_HOST_GIT_ARGUMENTS'); if (!g.repository) return null;
  const fence = ownedMutationPath(g.repository, command.policy.paths, end), s = fs.lstatSync(g.repository, { bigint: true, throwIfNoEntry: false });
  if (g.clone && !completed) {
    if (s) { directory(g.repository, end, false); const d = fs.opendirSync(g.repository); try { check(end); assert.equal(d.readSync(), null, 'IOS_HOST_GIT_NEW_TARGET'); } finally { d.closeSync(); } }
    return { ...fence, repositoryIdentity: s ? identity.map(k => String(s[k])) : null };
  }
  assert.ok(s?.isDirectory() && s.uid === BigInt(process.getuid()) && !s.isSymbolicLink() && (s.mode & 0o022n) === 0n, 'IOS_HOST_GIT_REPOSITORY');
  const git = path.join(g.repository, '.git'); directory(git, end, false);
  for (const name of ['commondir', 'objects/info/alternates']) assert.equal(fs.lstatSync(path.join(git, name), { throwIfNoEntry: false }), undefined, 'IOS_HOST_GIT_EXTERNAL_OBJECTS');
  gitConfig(path.join(git, 'config'), end); return { ...fence, repositoryIdentity: identity.map(k => String(s[k])) };
}
export function validateIosReadonlyGitArguments(args) {
  const files = value => cleanText(value) && !path.isAbsolute(value) && !value.startsWith('-') && !value.split(/[\\/]/).includes('..');
  assert.ok(Array.isArray(args), 'IOS_HOST_GIT_TLS_UNPROVEN');
  const allowed = args.length === 1 && args[0] === '--version'
    || args.length === 3 && JSON.stringify(args) === JSON.stringify(['check-ignore', '-z', '--stdin'])
    || args.length === 2 && args[0] === 'rev-parse' && args[1] === 'HEAD'
    || args.length > 6 && JSON.stringify(args.slice(0, 6)) === JSON.stringify(['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--']) && args.slice(6).every(files)
    || args.length > 4 && JSON.stringify(args.slice(0, 4)) === JSON.stringify(['status', '--porcelain', '--untracked-files=all', '--']) && args.slice(4).every(files);
  assert.ok(allowed, 'IOS_HOST_GIT_TLS_UNPROVEN');
  return ['-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', ...args];
}
export function reviewProjectNpm(p, end = Date.now() + 20000) {
  const root = path.resolve(path.dirname(p.helper.path), '../..'), rows = [];
  for (const folder of [root, path.join(root, 'apps/mobile')]) {
    check(end); const name = path.join(folder, '.npmrc');
    assert.equal(fs.lstatSync(name, { throwIfNoEntry: false }), undefined, 'IOS_HOST_PROJECT_NPMRC_REFUSED');
    rows.push({ path: name, namespace: namespace(name, end) });
  }
  return rows;
}
// These are SDK source paths, not arbitrary Xcode build-name values. Review
// them only after prebuild has created ios/ and when a child actually has them.
export function reviewIosPodBuildPaths(policy, { end = Date.now() + 20000 } = {}) {
  assert.ok(typeof process.getuid === 'function', 'IOS_HOST_POSIX_OWNER_REQUIRED');
  const helper = readIosHostInput(policy.helper, { end, maxBytes: 131072 });
  try {
    assert.equal(helper.canonical, policy.helper.path, 'IOS_HOST_POD_SOURCE_ROOT');
    const root = path.resolve(path.dirname(policy.helper.path), '../..');
    assert.equal(policy.helper.path, path.join(root, 'scripts/mobile/ios-host-launch.mjs'), 'IOS_HOST_POD_SOURCE_ROOT');
    const mobile = path.join(root, 'apps/mobile'), ios = path.join(mobile, 'ios');
    const rn = path.join(mobile, 'node_modules/react-native'), pods = path.join(ios, 'Pods');
    assert.equal(policy.paths.projectPods, pods, 'IOS_HOST_PROJECT_PODS_BINDING');
    const observe = folder => {
      const row = directory(folder, end, false);
      assert.equal(fs.lstatSync(folder, { bigint: true }).uid, BigInt(process.getuid()), 'IOS_HOST_POD_SOURCE_OWNER');
      return row;
    };
    const observed = [root, mobile, ios, rn].map(observe);
    const podsStat = fs.lstatSync(pods, { bigint: true, throwIfNoEntry: false });
    const nativePaths = [rn];
    if (podsStat) {
      observed.push(observe(pods));
      // RN post_install writes this exact physical-relative Xcode setting.
      nativePaths.push(pods + path.sep + path.relative(pods, rn));
    }
    const values = Object.freeze({ APP_PATH: Object.freeze([ios + path.sep + '..']),
      REACT_NATIVE_PATH: Object.freeze(nativePaths) });
    for (const row of observed) assert.deepEqual(observe(row.path), row, 'IOS_HOST_POD_SOURCE_CHANGED');
    if (!podsStat) assert.equal(fs.lstatSync(pods, { throwIfNoEntry: false }), undefined, 'IOS_HOST_POD_SOURCE_CHANGED');
    const named = fs.lstatSync(policy.helper.path, { bigint: true });
    assert.deepEqual(fields.map(key => String(named[key])), helper.metadata, 'IOS_HOST_INPUT_CHANGED');
    assert.equal(fs.realpathSync(policy.helper.path), helper.canonical, 'IOS_HOST_INPUT_CHANGED');
    assert.deepEqual(namespace(policy.helper.path, end), helper.namespace, 'IOS_HOST_NAMESPACE_CHANGED');
    return Object.freeze({ sourceRoot: root, values, directories: observed });
  } finally { helper.bytes.fill(0); }
}

const nodeCodeOptions = new Set(['-p', '--print', '-e', '--eval']);
export function validateIosHostArguments(role, args) {
  assert.ok(['node', 'npm', 'ruby', 'pod', 'curl', 'git', 'xcodebuild', 'neutral'].includes(role) && Array.isArray(args) && args.length <= 256, 'IOS_HOST_COMMAND_DOMAIN');
  const code = role === 'node' && nodeCodeOptions.has(args[0]) ? 1 : -1;
  const terminator = args.indexOf('--', 2);
  assert.ok(code < 0 || (args.length > 1 && !nodeCodeOptions.has(args[1]) && !args.slice(2, terminator < 0 ? undefined : terminator).some(arg => nodeCodeOptions.has(arg))), 'IOS_HOST_COMMAND_DOMAIN');
  let bytes = 0;
  for (const [index, arg] of args.entries()) {
    const valid = index === code ? typeof arg === 'string' && arg.length > 0 && Buffer.byteLength(arg) <= 8192 && !arg.includes('\0') : cleanText(arg);
    assert.ok(valid, 'IOS_HOST_COMMAND_DOMAIN'); bytes += Buffer.byteLength(arg);
    assert.ok(bytes <= 256 * 8192, 'IOS_HOST_COMMAND_DOMAIN');
  }
  return args;
}

export async function composeIosHostCommand(policyRef, role, args, { environment = {}, end = Date.now() + 20000 } = {}) {
  validateIosHostArguments(role, args);
  if (role === 'npm') assert.deepEqual(args, ['--version'], 'IOS_HOST_NPM_METADATA_ONLY');
  const admitted = await verifyIosHostLaunch(policyRef, { end });
  try {
    if (['APP_PATH', 'REACT_NATIVE_PATH'].some(name => Object.hasOwn(environment, name)))
      admitted.podBuildPaths = reviewIosPodBuildPaths(admitted.policy, { end });
    if (role === 'curl' && args[0] === '-f' && args[4]?.startsWith('file:')) admitted.localArchive = reviewIosLocalArchive(admitted.policy, args, end);
    if (role === 'npm') {
      const deadline = Number(environment.CASEOPS_IOS_HOST_OUTER_DEADLINE);
      assert.ok(Number.isFinite(deadline) && deadline > Date.now() && deadline <= admitted.policy.deadlineEpochMs, 'IOS_HOST_OWNED_OUTER_REQUIRED');
      admitted.npmRuntime = await prepareIosNpmRuntime(admitted.policy, { end });
    }
    return iosHostCommandProjection(admitted, policyRef, role, args, environment);
  }
  finally { admitted.bundle?.bytes.fill(0); admitted.localArchive?.bytes.fill(0); admitted.podsSource.fill(0); admitted.podEntry.fill(0); }
}
// Pure projection, not an admission or execution API. The actual CLI always
// obtains this object through verifyIosHostLaunch; JSON cannot supply it.
export function iosHostCommandProjection(admitted, policyRef, role, args, environment) {
  const p = admitted.policy;
  try {
    validateIncoming(p, admitted.node.environment, environment);
    if (admitted.podBuildPaths) assert.equal(admitted.podBuildPaths.sourceRoot,
      path.resolve(path.dirname(p.helper.path), '../..'), 'IOS_HOST_POD_SOURCE_ROOT');
    const neutral = neutralIosEnvironment(environment, { buildNames: role === 'node' ? admitted.nodeBuildNames ?? [] : [],
      podBuildPaths: admitted.podBuildPaths?.values ?? null });
    Object.assign(neutral, { HOME: p.paths.home, CURL_HOME: p.paths.home, XDG_CONFIG_HOME: p.paths.home,
      CP_HOME_DIR: p.paths.pods, CP_CACHE_DIR: p.paths.cache, CP_REPOS_DIR: p.paths.repos, TMPDIR: p.paths.temporary,
      LANG: 'en_US.UTF-8', LC_ALL: 'en_US.UTF-8',
      PATH: [p.paths.bin, path.dirname(p.tools.ruby.path), '/opt/homebrew/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'].join(':'),
      NODE_BINARY: p.shims.node.path, [IOS_HOST_ENV.file]: policyRef.path, [IOS_HOST_ENV.sha256]: policyRef.sha256,
      CASEOPS_IOS_HOST_POLICY_SIZE: String(policyRef.sizeBytes) });
    Object.assign(neutral, { GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_OPTIONAL_LOCKS: '0', GIT_TERMINAL_PROMPT: '0' });
    if (environment.CASEOPS_IOS_HOST_OUTER_DEADLINE !== undefined) {
      const deadline = Number(environment.CASEOPS_IOS_HOST_OUTER_DEADLINE);
      assert.ok(Number.isFinite(deadline) && deadline > Date.now() && deadline <= p.deadlineEpochMs, 'IOS_HOST_OWNED_OUTER_REQUIRED');
      neutral.CASEOPS_IOS_HOST_OUTER_DEADLINE = String(deadline);
    }
    const result = { role, args: [...args], environment: neutral, bundle: null, policy: p, node: admitted.node, homeObservation: admitted.homeObservation };
    if (role === 'node' || role === 'npm') {
      result.executable = p.tools.node.path;
      Object.assign(neutral, admitted.node.environment, { NPM_CONFIG_USERCONFIG: p.nodeNpm.user.path, NPM_CONFIG_GLOBALCONFIG: p.nodeNpm.global.path,
        NPM_CONFIG_STRICT_SSL: 'true', NPM_CONFIG_REGISTRY: 'https://registry.npmjs.org/' });
      if (role === 'npm') {
        assert.deepEqual(args, ['--version'], 'IOS_HOST_NPM_METADATA_ONLY');
        const prepared = admitted.npmRuntime;
        assert.ok(prepared && path.dirname(prepared.root) === p.nodeNpm.parent && /^caseops-npm-[A-Za-z0-9]{6}$/.test(path.basename(prepared.root)), 'IOS_HOST_NPM_ACTUAL_CONSTRUCTOR_REQUIRED');
        exact(prepared.environment, NPM_ENV_KEYS, 'IOS_HOST_NPM_CANONICAL_ENVIRONMENT');
        const scoped = prepared.environment;
        assert.ok(scoped.CASEOPS_PINNED_NPM_NODE === p.tools.node.path && scoped.CASEOPS_PINNED_NPM_ROOT === prepared.root
          && scoped.CASEOPS_PINNED_NPM_CLI === path.join(prepared.root, 'package/bin/npm-cli.js')
          && scoped.CASEOPS_PINNED_NPM_ENTRY === path.join(prepared.root, 'caseops-entry.mjs'), 'IOS_HOST_NPM_CANONICAL_ENVIRONMENT');
        const executionDeadline = Math.min(p.deadlineEpochMs, Number(neutral.CASEOPS_IOS_HOST_OUTER_DEADLINE));
        assert.ok(Number.isFinite(executionDeadline) && executionDeadline > Date.now(), 'IOS_HOST_OWNED_OUTER_REQUIRED');
        Object.assign(neutral, Object.fromEntries(Object.entries(scoped).filter(([key]) => key !== 'PATH')),
          { CASEOPS_PINNED_NPM_DEADLINE: String(executionDeadline),
            PATH: [path.join(prepared.root, 'bin'), path.dirname(p.tools.node.path), neutral.PATH].join(':') });
        result.args = ['--input-type=module', '--eval', scoped.CASEOPS_PINNED_NPM_BOOTSTRAP, '--', 'npm', ...args];
        result.npmSource = { root: prepared.root, files: prepared.files, inventory: prepared.inventory };
      }
    }
    if (role === 'pod' || role === 'ruby') { result.executable = p.tools.ruby.path; result.args = [...args]; Object.assign(neutral,
      { GEM_HOME: p.podHome, GEM_PATH: [p.podHome, p.rubyGems].join(':'), SSL_CERT_FILE: p.bundle.path, SSL_CERT_DIR: p.paths.empty, COCOAPODS_DISABLE_STATS: 'true', COCOAPODS_SKIP_UPDATE_MESSAGE: 'true' }); }
    if (role === 'pod' || role === 'ruby') Object.assign(neutral, { LANG: 'en_US.UTF-8', LC_ALL: 'en_US.UTF-8' });
    if (role === 'git') {
      result.executable = p.tools.git.path; result.git = projectIosGitArguments(args, p.paths); result.args = result.git.args;
      if (result.git.family !== 'local-source-inventory') {
        result.bundle = admitted.bundle.bytes; admitted.bundle = null; result.cwd = p.paths.empty;
        // Clone/ls-remote must not discover the caller worktree's local config.
        neutral.GIT_CEILING_DIRECTORIES = p.paths.empty;
      }
    }
    if (role === 'pod') {
      assert.equal(p.source['ios-host-pods.rb'].sha256, IOS_PODS_SOURCE_SHA256, 'IOS_HOST_PODS_SOURCE_UNREVIEWED');
        result.args = ['-', ...args];
        result.input = Buffer.concat([admitted.podsSource, Buffer.from('\nCaseopsIosPods.run\n')]);
        neutral.CASEOPS_IOS_PODS_TLS_POLICY = JSON.stringify({ bundle: p.bundle, empty: p.paths.empty, home: p.paths.home, podHome: p.podHome, rubyGems: p.rubyGems, fixtureSha256: p.fixtureCA?.certificateSha256 ?? null });
        neutral.CASEOPS_IOS_POD_SOURCE_BASE64 = admitted.podEntry.toString('base64');
    }
    if (role === 'curl' && admitted.localArchive) {
      assert.ok(localArchiveReceipts.has(admitted.localArchive), 'IOS_HOST_LOCAL_ARCHIVE_RECEIPT');
      assert.deepEqual(args, admitted.localArchive.args, 'IOS_HOST_LOCAL_ARCHIVE_ARGUMENT_CHANGED');
      result.localArchive = admitted.localArchive; admitted.localArchive = null;
      result.curl = { family: 'expo-sdk-local-archive', output: result.localArchive.output, args: [...args] };
    } else if (role === 'curl') {
      const form = validateIosCurlArguments(args);
      result.executable = p.tools.curl.path; result.args = ['--disable', '--cacert', '/dev/fd/3', '--proto', '=https', '--proto-redir', '=https', ...form.args];
      assert.ok(form.output === null || ownedPath(form.output, p.paths), 'IOS_HOST_CURL_OWNED_OUTPUT'); result.curl = form;
      result.bundle = admitted.bundle.bytes; admitted.bundle = null;
      // A selected file policy is not an assertion about Apple's native store.
      neutral.CURL_SSL_BACKEND = 'secure-transport';
    }
    return result;
  } catch (error) { admitted.bundle?.bytes.fill(0); throw error; }
}
export async function admitIosHostExecution(policyRef, { end = Date.now() + 20000, activeNode = true } = {}) {
  const admitted = await verifyIosHostLaunch(policyRef, { end });
  try {
    if (activeNode) admitted.node.helper.assertHostNodeTrust({ policyRef: admitted.policy.nodePolicy,
      role: admitted.policy.role, expectedFixtureCA: admitted.policy.fixtureCA });
    return admitted.policy;
  } finally { admitted.bundle.bytes.fill(0); admitted.podsSource.fill(0); admitted.podEntry.fill(0); }
}
export function openIosCurlTransport(command, { end = Date.now() + 20000 } = {}) {
  assert.ok(['curl', 'git'].includes(command.role) && Buffer.isBuffer(command.bundle) && command.bundle.length > 0 && command.bundle.length <= 1048576, 'IOS_HOST_TRANSPORT_BYTES');
  assert.ok(typeof process.getuid === 'function', 'IOS_HOST_POSIX_OWNER_REQUIRED');
  const parent = command.policy.paths.temporary; directory(parent, end);
  const file = path.join(parent, 'tls-ca-' + randomUUID() + '.pem'), ns = namespace(file, end);
  const fd = fs.openSync(file, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
  let accepted = false, probe;
  try {
    let n = 0;
    while (n < command.bundle.length) { check(end); const count = fs.writeSync(fd, command.bundle, n, Math.min(65536, command.bundle.length - n), n); assert.ok(count > 0 && count <= command.bundle.length - n, 'IOS_HOST_WRITE_PROGRESS'); n += count; }
    fs.fchmodSync(fd, 0o400); fs.fsyncSync(fd); const before = fs.fstatSync(fd, { bigint: true });
    assert.ok(before.isFile() && before.uid === BigInt(process.getuid()) && before.nlink === 1n && before.size === BigInt(command.bundle.length)
      && (before.mode & 0o7777n) === 0o400n && same(before, fs.lstatSync(file, { bigint: true })) && fs.realpathSync(file) === file, 'IOS_HOST_TRANSPORT_IDENTITY');
    probe = Buffer.alloc(command.bundle.length + 1); n = 0;
    while (n < probe.length) { check(end); const count = fs.readSync(fd, probe, n, Math.min(65536, probe.length - n), n); if (!count) break; n += count; }
    assert.ok(n === command.bundle.length && probe.subarray(0, n).equals(command.bundle) && same(before, fs.fstatSync(fd, { bigint: true })), 'IOS_HOST_TRANSPORT_CHANGED');
    accepted = true; let closed = false;
    return { fd, file, finish(deadline = end) {
      assert.equal(closed, false, 'IOS_HOST_TRANSPORT_ALREADY_CLOSED'); closed = true;
      try {
        check(deadline); assert.ok(same(before, fs.fstatSync(fd, { bigint: true })) && same(before, fs.lstatSync(file, { bigint: true })) && fs.realpathSync(file) === file, 'IOS_HOST_TRANSPORT_CHANGED');
        assert.deepEqual(namespace(file, deadline), ns, 'IOS_HOST_TRANSPORT_NAMESPACE_CHANGED');
        assert.deepEqual(reviewIosHostHome(command.policy.paths.home, deadline), command.homeObservation, 'IOS_HOST_HOME_CHANGED');
        fs.unlinkSync(file);
      } finally { fs.closeSync(fd); }
    } };
  } finally { probe?.fill(0); if (!accepted) fs.closeSync(fd); }
}
const HOST_BOOTSTRAP = String.raw`import hashlib,os,sys
p,h=sys.argv[1:3];b=bytearray()
try:
 while len(b)<=32768:
  v=os.read(3,min(65536,32769-len(b)))
  if not v:break
  b.extend(v)
finally:os.close(3)
if not 0<len(b)<=32768 or hashlib.sha256(b).hexdigest()!=h:raise ValueError('IOS_HOST_WORKER_SOURCE_REFUSED')
sys.argv=[p]
exec(compile(bytes(b),p,'exec'),{'__name__':'__main__','__file__':p,'__caseops_host_source__':bytes(b)})
`;
async function dispatchLocalQaChild(p, hostRef, hostBytes, request, environment, end, transport) {
  if (transport) return await transport({ request, environment, hostRef, hostBytes });
  return await new Promise((resolve, reject) => {
    const child = spawn(p.tools.python.path, ['-I', '-B', '-c', HOST_BOOTSTRAP, hostRef.path, hostRef.sha256],
      { cwd: request.cwd, env: environment, stdio: ['pipe', 'pipe', 'pipe', 'pipe'], shell: false });
    const chunks = []; let count = 0, errors = 0;
    const timer = setTimeout(() => reject(new Error('IOS_HOST_BUILD_ACK_UNKNOWN')), Math.max(1, end - Date.now()));
    child.stdout.on('data', b => { count += b.length; if (count <= 4194304) chunks.push(b); });
    child.stderr.on('data', b => { errors += b.length; });
    child.on('error', () => { clearTimeout(timer); reject(new Error('IOS_HOST_BUILD_LAUNCH_FAILED')); });
    child.on('close', code => { clearTimeout(timer); try { assert.ok(code === 0 && count <= 4194304 && errors === 0, 'IOS_HOST_BUILD_TRANSPORT_REFUSED'); resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { reject(new Error('IOS_HOST_BUILD_TRANSPORT_REFUSED')); } });
    child.stdin.on('error', () => {}); child.stdio[3].on('error', () => {}); child.stdio[3].end(hostBytes); child.stdin.end(JSON.stringify(request) + '\n');
  });
}
// Public local-QA constructors only. Store/signing uses its unchanged strict host.
export async function runIosLocalQaCommand(policyRef, role, args, { environment = {}, cwd, timeoutMs = 20000,
  deadline = Date.now() + 50000, transport } = {}) {
  const started = Date.now(), end = Math.min(deadline, started + 1830000);
  assert.ok(['git', 'curl', 'pod', 'npm'].includes(role) && Array.isArray(args) && Number.isFinite(timeoutMs) && timeoutMs > 0 && timeoutMs <= 1800000, 'IOS_HOST_LOCAL_QA_COMMAND');
  if (role === 'pod' || role === 'npm') assert.deepEqual(args, ['--version'], 'IOS_HOST_LOCAL_QA_METADATA_ONLY');
  const scoped = await composeIosHostCommand(policyRef, 'neutral', [], { environment, end: Math.min(end - 30000, started + 20000) }), p = scoped.policy;
  const finish = Math.min(end, p.deadlineEpochMs); directory(cwd, finish, false);
  if (role === 'git') projectIosGitArguments(args, p.paths); else if (role === 'curl') validateIosCurlArguments(args);
  scoped.environment.CASEOPS_IOS_HOST_OUTER_DEADLINE = String(finish - 30000);
  const hostRef = { ...p.source['ios-local-qa-host.py'], path: path.join(p.paths.runtime, 'ios-local-qa-host.py') };
  const host = readIosHostInput(hostRef, { end: finish, maxBytes: 32768 });
  try {
    const remaining = finish - 30000 - Date.now(); assert.ok(remaining > 0, 'IOS_HOST_DEADLINE');
    const request = { kind: 'caseops-local-ios-qa-child', scope: 'public-local-qa-only', deadlineEpochMs: finish,
      argv: [p.shims[role].path, ...args], cwd, timeoutSeconds: Math.min(timeoutMs, remaining) / 1000,
      outputLimit: 1048576, capture: true, inputBase64: '', sourceBase64: '' };
    return await dispatchLocalQaChild(p, hostRef, host.bytes, request, scoped.environment, finish, transport);
  } finally { host.bytes.fill(0); }
}
export async function runIosSimulatorBuild(policyRef, environment, { transport } = {}) {
  assert.equal(environment.CASEOPS_IOS_SIMULATOR_BUILD_GO, 'EXPLICIT_REVIEWED_LOCAL_SIMULATOR_BUILD', 'IOS_HOST_SIMULATOR_NOT_ARMED');
  assert.match(environment.SIMULATOR_UDID || '', /^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$/, 'IOS_HOST_SIMULATOR_ID');
  assert.match(environment.CASEOPS_MOBILE_RELEASE_SHA || '', /^[a-f0-9]{40}$/, 'IOS_HOST_SOURCE_SHA');
  const p = await admitIosHostExecution(policyRef), end = Math.min(p.deadlineEpochMs, Date.now() + 1830000);
  const supplied = Object.fromEntries(Object.entries(environment).filter(([key]) => publicKeys.test(key)));
  const scoped = await composeIosHostCommand(policyRef, 'neutral', [], { environment: supplied, end: Math.min(Date.now() + 20000, end) });
  scoped.environment.CASEOPS_IOS_HOST_OUTER_DEADLINE = String(end - 30000);
  scoped.environment.CASEOPS_IOS_HOST_SOURCE_ROOT = path.resolve(path.dirname(p.helper.path), '../..');
  scoped.environment.CASEOPS_IOS_HOST_BUILD_OUTPUT = p.paths.build;
  scoped.environment.CASEOPS_IOS_HOST_XCODEBUILD = p.tools.xcodebuild.path;
  scoped.environment.CASEOPS_IOS_HOST_PLUTIL = p.tools.plutil.path;
  const source = readIosHostInput(p.source['ios-simulator-build.sh'], { end, maxBytes: 32768 });
  const hostRef = { ...p.source['ios-local-qa-host.py'], path: path.join(p.paths.runtime, 'ios-local-qa-host.py') };
  const host = readIosHostInput(hostRef, { end, maxBytes: 32768 });
  try {
    // This is the single build-attempt boundary. A refusal/unknown outcome keeps
    // the claim; neither this entry nor its adapters replay a build.
    writeExclusive(path.join(path.dirname(policyRef.path), 'simulator-build.claim'), Buffer.from(JSON.stringify({ source: environment.CASEOPS_MOBILE_RELEASE_SHA, simulator: environment.SIMULATOR_UDID }) + '\n'), end);
    const request = { kind: 'caseops-local-ios-qa-child', scope: 'public-local-qa-only', deadlineEpochMs: end,
      argv: ['/bin/bash', '@CASEOPS_VERIFIED_SOURCE_FD@'], cwd: scoped.environment.CASEOPS_IOS_HOST_SOURCE_ROOT,
      timeoutSeconds: Math.min(1800, (end - 30000 - Date.now()) / 1000), outputLimit: 16777216, capture: false, inputBase64: '', sourceBase64: source.bytes.toString('base64') };
    assert.ok(request.timeoutSeconds > 0, 'IOS_HOST_DEADLINE');
    const result = await dispatchLocalQaChild(p, hostRef, host.bytes, request, scoped.environment, end, transport);
    writeExclusive(path.join(path.dirname(policyRef.path), 'simulator-build-result.json'), Buffer.from(JSON.stringify({ ...result, nativeAcceptance: false, shippingOrStoreAcceptance: false }) + '\n'), end);
    await admitIosHostExecution(policyRef, { end: Math.min(end, Date.now() + 20000) });
    assert.ok(result.exitCode === 0 && result.workerExitCode === 0 && result.timedOut === false && result.cleanup?.complete === true
      && result.outputExceeded !== true && result.failureClass == null, 'IOS_HOST_BUILD_FAILED'); return result;
  } finally { source.bytes.fill(0); host.bytes.fill(0); }
}
export async function iosHostCli(args) {
  const end = Date.now() + 20000;
  if (args[0] === 'prepare') {
    assert.equal(args.length, 4, 'IOS_HOST_PREPARE_ARGUMENTS');
    const input = readIosHostInput({ path: args[1], sha256: args[2], sizeBytes: Number(args[3]) }, { end, maxBytes: 65536 });
    try {
      const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(input.bytes));
      assert.ok(value && typeof value === 'object' && !Array.isArray(value)
        && ['directory', 'nodePolicy', 'rubyBundle', 'tools'].every(k => Object.hasOwn(value, k))
        && Object.keys(value).every(k => ['directory', 'nodePolicy', 'rubyBundle', 'tools', 'role', 'fixtureCA', 'deadline', 'sourceRoot'].includes(k)), 'IOS_HOST_PREPARE_KEYS');
      const made = await prepareIosHostLaunch(value); console.log(JSON.stringify({ policyRef: made.policyRef, builds: 0, downloads: 0 })); return 0;
    }
    finally { input.bytes.fill(0); }
  }
  const policyRef = { path: process.env[IOS_HOST_ENV.file], sha256: process.env[IOS_HOST_ENV.sha256], sizeBytes: Number(process.env.CASEOPS_IOS_HOST_POLICY_SIZE) };
  if (args.length === 1 && args[0] === 'simulator') { await runIosSimulatorBuild(policyRef, process.env); return 0; }
  const command = await composeIosHostCommand(policyRef, args[0], args.slice(1), { environment: process.env, end });
  const p = command.policy;
  let caTransport, originalStatus, mutationFence, originalFailure;
  const originalStatusLabel = command.localArchive ? 'IOS_HOST_ORIGINAL_LOCAL_TRANSFER_EXIT_' : 'IOS_HOST_ORIGINAL_CHILD_EXIT_';
  try {
    command.node.helper.assertHostNodeTrust({ policyRef: p.nodePolicy, role: p.role, expectedFixtureCA: p.fixtureCA });
    assert.ok(process.platform === 'darwin', 'IOS_HOST_MACOS_REQUIRED');
    assert.ok(Number(process.env.CASEOPS_IOS_HOST_OUTER_DEADLINE) > Date.now() && Number(process.env.CASEOPS_IOS_HOST_OUTER_DEADLINE) <= p.deadlineEpochMs, 'IOS_HOST_OWNED_OUTER_REQUIRED');
    const timeout = Math.min(Number(process.env.CASEOPS_IOS_HOST_OUTER_DEADLINE), p.deadlineEpochMs) - Date.now();
    if (command.role === 'node' || command.role === 'npm') reviewProjectNpm(p, end);
    if (command.git) mutationFence = admitIosGitRepository(command, { end });
    if (command.curl?.output) mutationFence = ownedMutationPath(command.curl.output, p.paths, end);
    if (command.bundle) {
      caTransport = openIosCurlTransport(command, { end });
      // Git's parallel object handles reopen CAInfo; /dev/fd/3 shares a consumed
      // offset and fails with curl77. Keep the verified descriptor open and use
      // its new owned0400 canonical copy for this selected-file API, with the
      // same complete postflight. This is not OS-default trust acceptance.
      if (command.git) command.args = command.args.map(v => v === 'http.sslCAInfo=/dev/fd/3' ? 'http.sslCAInfo=' + caTransport.file : v);
    }
    const status = command.localArchive ? transferIosLocalArchive(command, end) : await new Promise((resolve, reject) => {
      const child = spawn(command.executable, command.args, { cwd: command.cwd, env: command.environment, stdio: command.bundle
        ? ['ignore', 'inherit', 'inherit', caTransport.fd] : command.input ? ['pipe', 'inherit', 'inherit'] : 'inherit', shell: false });
      let ended = false;
      // The enclosing reviewed owner retains signal authority; this shim never
      // claims a complete live inventory or signals an unadmitted descendant.
      const timer = setTimeout(() => { if (!ended) reject(new Error('IOS_HOST_CHILD_OUTCOME_UNKNOWN')); }, timeout);
      child.on('error', () => { clearTimeout(timer); reject(new Error('IOS_HOST_CHILD_LAUNCH_FAILED')); });
      child.on('close', (code, signal) => { ended = true; clearTimeout(timer); signal === null && Number.isInteger(code) ? resolve(code) : reject(new Error('IOS_HOST_CHILD_OUTCOME_UNKNOWN')); });
      if (command.input) { child.stdin.on('error', () => {}); child.stdin.end(command.input); }
    });
    originalStatus = status;
    const postEnd = Math.min(Date.now() + 20000, p.deadlineEpochMs);
    if (mutationFence) {
      const value = command.git?.repository ?? command.curl.output;
      assert.deepEqual(namespace(value, postEnd), mutationFence.namespace, 'IOS_HOST_MUTATION_NAMESPACE_CHANGED');
      if (mutationFence.repositoryIdentity) assert.deepEqual(identity.map(k => String(fs.lstatSync(value, { bigint: true })[k])), mutationFence.repositoryIdentity, 'IOS_HOST_GIT_REPOSITORY_CHANGED');
    }
    if (command.git && (status === 0 || !command.git.clone)) admitIosGitRepository(command, { end: postEnd, completed: true });
    // Namespace/absence/CA validation is also required after a nonzero exit.
    const after = await verifyIosHostLaunch(policyRef, { end: Math.min(Date.now() + 20000, p.deadlineEpochMs) });
    after.bundle.bytes.fill(0); after.podsSource.fill(0); after.podEntry.fill(0);
    return status;
  } catch (error) {
    originalFailure = error;
    if (originalStatus !== undefined) console.error(originalStatusLabel + originalStatus);
    throw error;
  } finally {
    try { caTransport?.finish(Math.min(Date.now() + 20000, p.deadlineEpochMs)); }
    catch (error) {
      console.error('IOS_HOST_TRANSPORT_CLEANUP_REFUSED');
      if (!originalFailure) {
        if (originalStatus !== undefined) console.error(originalStatusLabel + originalStatus);
        throw error;
      }
    }
    finally { command.bundle?.fill(0); command.input?.fill(0); command.localArchive?.bytes.fill(0); }
  }
}
if (import.meta.url.startsWith('file:') && process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try { process.exitCode = await iosHostCli(process.argv.slice(2)); }
  catch (error) { console.error(/^IOS_HOST_[A-Z0-9_]+$/.test(error.message) ? error.message : 'IOS_HOST_LAUNCH_REFUSED'); process.exitCode = 1; }
}
