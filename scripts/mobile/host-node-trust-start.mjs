// This bootstrap is passed as a data URI made from its admitted held buffer.
// It runs before the real npm/Appium entry and never follows a module pathname.
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';

// Public reviewed source identity, not a policy-supplied code authority.
const APPROVED_HELPER_SHA256 = '13576eb5d2a4aed86b38f6dbae240ba290d08e653107c9ffeed060fa2e048787';
const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const end = performance.now() + 20000;
const check = () => { if (performance.now() >= end) throw new Error('HOST_TRUST_BOOTSTRAP_DEADLINE'); };
const insist = value => { if (!value) throw new Error('HOST_TRUST_BOOTSTRAP_REFUSED'); };
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const frame = value => fields.map(key => String(value[key])).join(':');
const real = file => (fs.realpathSync.native ?? fs.realpathSync)(file);
function namespace(file) {
  check(); const resolved = real(file), rows = [];
  for (let p = path.dirname(resolved); ; p = path.dirname(p)) {
    check(); const s = fs.lstatSync(p, { bigint: true }); insist(s.isDirectory() && !s.isSymbolicLink());
    rows.push([p, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(s[key]))]);
    if (path.dirname(p) === p) return JSON.stringify([resolved, rows]);
  }
}
function owner(file, s, privateFile) {
  if (typeof process.getuid === 'function') {
    insist(s.uid === BigInt(process.getuid()));
    insist(privateFile ? (s.mode & 0o7777n) === 0o600n : (s.mode & 0o7133n) === 0n);
    return;
  }
  insist(process.platform === 'win32' && path.isAbsolute(process.env.SystemRoot || ''));
  const code = "$ErrorActionPreference='Stop';[Console]::Error.WriteLine('COPS_ACL0');try{$s=[Security.AccessControl.AccessControlSections]'Access,Owner';$a=[IO.File]::GetAccessControl($env:CASEOPS_TRUST_ACL_PATH,$s);[Console]::Error.WriteLine('COPS_ACL1');$i=[Security.Principal.WindowsIdentity]::GetCurrent();$u=$i.User.Value;$t=$i.Owner.Value;$o=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value;[Console]::Error.WriteLine('COPS_ACL2');$ok=($o -eq $u -or ($o -eq $t -and $o -in @('S-1-5-18','S-1-5-32-544')));foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($r.AccessControlType -eq 'Allow' -and ([int]$r.FileSystemRights -band 852310) -ne 0 -and $r.IdentityReference.Value -notin @($u,'S-1-5-18','S-1-5-32-544','S-1-3-0')){$ok=$false}};[Console]::Error.WriteLine('COPS_ACL3');if($ok){[Console]::Out.Write('SAFE')}else{exit 1}}catch{[Console]::Error.WriteLine('COPS_ACL_FAIL');exit 1}";
  check(); const result = spawnSync(path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe'), ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', code], { env: { SystemRoot: process.env.SystemRoot, CASEOPS_TRUST_ACL_PATH: file }, encoding: 'utf8', timeout: Math.max(1, Math.min(5000, end - performance.now())), maxBuffer: 4096, windowsHide: true });
  insist(!result.error && result.status === 0 && result.stdout.trim() === 'SAFE' && result.stderr.replaceAll('\r', '') === 'COPS_ACL0\nCOPS_ACL1\nCOPS_ACL2\nCOPS_ACL3\n'); check();
}
function held(file, expected, limit, privateFile = false) {
  insist(typeof file === 'string' && path.isAbsolute(file) && path.resolve(file) === file && /^[a-f0-9]{64}$/.test(expected));
  let fd;
  try {
    check(); fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const a = fs.fstatSync(fd, { bigint: true }), n = fs.lstatSync(file, { bigint: true });
    insist(a.isFile() && n.isFile() && !n.isSymbolicLink() && a.nlink === 1n && a.size > 0n && a.size <= BigInt(limit));
    for (const key of fields) if (!(process.platform === 'win32' && key === 'dev' && n.dev === 0n)) insist(a[key] === n[key]);
    owner(file, n, privateFile); const ns = namespace(file), bytes = Buffer.alloc(Number(a.size) + 1); let count = 0;
    while (count < bytes.length) { check(); const amount = fs.readSync(fd, bytes, count, bytes.length - count, null); if (!amount) break; count += amount; }
    insist(BigInt(count) === a.size && frame(fs.fstatSync(fd, { bigint: true })) === frame(a) && frame(fs.lstatSync(file, { bigint: true })) === frame(n) && namespace(file) === ns);
    const retained = bytes.subarray(0, count); insist(sha(retained) === expected); return retained;
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}
try {
  const policyRef = { path: process.env.CASEOPS_HOST_NODE_TRUST_POLICY_FILE, sha256: process.env.CASEOPS_HOST_NODE_TRUST_POLICY_SHA256 };
  const input = held(policyRef.path, policyRef.sha256, 16384, true);
  let policy; try { policy = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(input)); } finally { input.fill(0); }
  insist(policy.kind === 'caseops-host-node-trust-v1' && policy.schemaVersion === 1);
  const self = held(policy.runtimeSource.bootstrap.path, policy.runtimeSource.bootstrap.sha256, 16384);
  try { insist(import.meta.url === 'data:text/javascript;base64,' + self.toString('base64')); } finally { self.fill(0); }
  insist(policy.runtimeSource.helper.sha256 === APPROVED_HELPER_SHA256);
  insist(path.basename(policy.runtimeSource.helper.path) === 'host-node-trust.mjs' && policy.runtimeSource.bootstrap.path === path.join(path.dirname(policy.runtimeSource.helper.path), 'host-node-trust-start.mjs'));
  const source = held(policy.runtimeSource.helper.path, APPROVED_HELPER_SHA256, 65536);
  try {
    const helper = await import('data:text/javascript;base64,' + source.toString('base64'));
    helper.activateHostNodeTrust({ policyRef, role: policy.role, expectedFixtureCA: policy.fixtureCA });
  } finally { source.fill(0); }
} catch (error) {
  // Fixed diagnostic only: this boundary may run before any application logger.
  console.error(/^HOST_TRUST_[A-Z_]+$/.test(error.message) ? error.message : 'HOST_TRUST_BOOTSTRAP_REFUSED');
  process.exit(1);
}
