import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { regularTarMembers } from './npm-tooling.mjs';

import { readFixtureBytes } from './fixtures/picomatch-byte-input.mjs';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const vendor = path.join(repo, 'apps/mobile/vendor/picomatch-4.0.7-caseops.1');
const worker = fileURLToPath(new URL('./fixtures/picomatch-redos-probe.cjs', import.meta.url));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const provenance = JSON.parse(readFixtureBytes(path.join(vendor, 'provenance.json'), 65536));
const cases = [
  ['+(*)z', 'a'.repeat(30) + '!'], ['+(*a)', 'a'.repeat(30) + '!'],
  ['+(a*)z', 'a'.repeat(30) + '!'], ['+(ab|abab)z', 'ab'.repeat(35) + '!'],
  ['+(ab|abab)z', 'ab'.repeat(50) + '!'],
];
// V8 in Node24 can complete the35-repeat overlap witness inside one second.
// Keep that exact case in the repaired-path coverage, and use the stronger
// fifty-repeat sibling for the cross-runtime negative control. The three
// original single-branch witnesses and every physical deadline stay unchanged.
const counterfactualCases = [...cases.slice(0, 3), cases[4]];

async function probe(packageRoot, pattern, subject) {
  // Keep the real inherited CI bootstrap. Its existing20-second preparation
  // bound is separate from matching; the acknowledged trigger starts the
  // original1000ms physical budget, including IPC and natural child closure.
  const child = spawn(process.execPath, [worker, packageRoot, pattern, subject], {
    windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
  });
  const rows = [];
  let pending = '', stderr = '', charged = 0, failure, matchingTimer, cleanupTimer;
  let resolveClosed, rejectClosed;
  const closed = new Promise((resolve, reject) => { resolveClosed = resolve; rejectClosed = reject; });
  function stop(error) {
    failure ??= error;
    if (!cleanupTimer) {
      cleanupTimer = setTimeout(() => rejectClosed(new Error('PICOMATCH_PROBE_CLEANUP_DEADLINE')), 5000);
      child.kill();
    }
  }
  const preparationTimer = setTimeout(() => stop({ code: 'PREPARATION_DEADLINE' }), 20000);
  const account = chunk => {
    charged += chunk.length;
    if (charged > 16384) { stop({ code: 'PROBE_OUTPUT_BOUND' }); return false; }
    return true;
  };
  child.stdout.on('data', chunk => {
    if (!account(chunk)) return;
    pending += chunk.toString('utf8');
    let end;
    while ((end = pending.indexOf('\n')) !== -1) {
      const line = pending.slice(0, end); pending = pending.slice(end + 1);
      try {
        const row = JSON.parse(line);
        rows.push(row);
        if (rows.length === 1) {
          assert.deepEqual(row, { stage: 'ready', pattern, length: subject.length });
          clearTimeout(preparationTimer);
          matchingTimer = setTimeout(() => stop({ code: 'ETIMEDOUT' }), 1000);
          child.stdin.end(Buffer.from('M'));
        } else if (rows.length === 2) assert.deepEqual(row, { stage: 'matching' });
        else assert.equal(rows.length, 3);
      } catch { stop({ code: 'PROBE_PROTOCOL_REFUSED' }); }
    }
  });
  child.stderr.on('data', chunk => { if (account(chunk)) stderr += chunk.toString('utf8'); });
  child.stdin.on('error', error => stop({ code: error.code ?? 'PROBE_TRIGGER_REFUSED' }));
  child.on('error', error => stop({ code: error.code ?? 'PROBE_SPAWN_REFUSED' }));
  child.once('close', (status, signal) => resolveClosed({ status, signal, stderr, error: failure }));
  try {
    const result = await closed;
    assert.deepEqual(rows[0], { stage: 'ready', pattern, length: subject.length },
      'A cold process refusal is not proof of regex execution');
    assert.deepEqual(rows[1], { stage: 'matching' }, 'The physical matcher must acknowledge entry');
    assert.equal(pending, '', 'Every child response must be complete');
    return { result, rows };
  } finally {
    clearTimeout(preparationTimer); clearTimeout(matchingTimer); clearTimeout(cleanupTimer);
  }
}

function originalPackage(t) {
  const input = readFixtureBytes(path.join(vendor, 'upstream/picomatch-4.0.7.tgz'), 262144);
  assert.equal(sha(input), '697b463be3cdbd9ffc8f4194fd5019a69ddf95875fb703d78b2b115cc9e740a8');
  const parent = fs.realpathSync(os.tmpdir());
  const root = fs.realpathSync(fs.mkdtempSync(path.join(parent, 'picomatch-original-')));
  assert.equal(path.dirname(root), parent);
  const admitted = fs.lstatSync(root, { bigint: true });
  t.after(() => {
    assert.equal(fs.realpathSync(root), root);
    assert.equal(fs.lstatSync(root, { bigint: true }).ino, admitted.ino);
    assert.equal(path.dirname(root), parent);
    fs.rmSync(root, { recursive: true });
  });
  const members = regularTarMembers(gunzipSync(input, { maxOutputLength: 262144 }));
  assert.equal(members.length, 10);
  for (const row of members) {
    const target = path.join(root, row.path);
    assert.ok(target.startsWith(root + path.sep));
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, row.bytes, { flag: 'wx' });
  }
  return path.join(root, 'package');
}

test('the pinned original really enters and exceeds the unchanged regex budget', async t => {
  const original = originalPackage(t);
  const control = await probe(original, '*.js', 'ordinary.js');
  assert.equal(control.result.status, 0);
  assert.equal(control.rows[2].matched, true);
  for (const [pattern, subject] of counterfactualCases) {
    const { result, rows } = await probe(original, pattern, subject);
    assert.equal(result.error?.code, 'ETIMEDOUT', pattern);
    assert.equal(result.status, null, pattern);
    assert.equal(rows.length, 2, pattern);
  }
});

test('the private backport completes the exact same adversarial probes naturally', async () => {
  const packageRoot = path.join(vendor, 'package');
  for (const [pattern, subject] of cases) {
    const { result, rows } = await probe(packageRoot, pattern, subject);
    assert.equal(result.error, undefined, pattern);
    assert.equal(result.status, 0, pattern);
    assert.equal(result.signal, null, pattern);
    assert.equal(result.stderr, '', pattern);
    assert.equal(rows.length, 3, pattern);
    assert.equal(rows[2].matched, false, pattern);
    assert.ok(rows[2].elapsedMs < 1000, pattern);
    const literal = await probe(packageRoot, pattern, pattern);
    assert.equal(literal.result.status, 0);
    assert.equal(literal.rows[2].matched, true, 'Risky extglobs follow the existing literalization policy');
  }
});

test('common, escaped, quoted, class and safe nested forms retain real matching semantics', t => {
  const require = createRequire(path.join(vendor, 'package/package.json'));
  const pm = require('./index.js');
  const original = createRequire(path.join(originalPackage(t), 'package.json'))('./index.js');
  const rows = [
    ['*.js', 'ordinary.js', true], ['*.js', 'ordinary.ts', false],
    ['**/*.tsx', 'app/deep/page.tsx', true], ['**/*.tsx', 'app/deep/page.ts', false],
    ['+(foo|bar)', 'foobarfoo', true], ['+(foo|bar)', 'foobaz', false],
    ['+(js|jsx)', 'jsxjs', true], ['+(js|jsx)', 'jsxts', false],
    ['*(foo|bar)', '', false], ['*(foo|bar)', 'barfoo', true],
    ['+(*(a)|*(b))', 'abba', true], ['+(*(a)|*(b))', 'abca', false],
    ['+(a\\*)', 'a*a*', true], ['+(a\\*)', 'aaaa', false],
    ['+(a[*])', 'a*a*', true], ['+(a[*])', 'aaaa', false],
    ['+("a*")', 'a*a*', true], ['+("a*")', 'aaaa', false],
    ['src/**/!(*.test).ts', 'src/deep/service.ts', true],
    ['src/**/!(*.test).ts', 'src/deep/service.test.ts', false],
  ];
  for (const [pattern, subject, expected] of rows) {
    const baseline = original(pattern)(subject);
    assert.equal(baseline, expected, 'Pinned upstream contract: ' + JSON.stringify({ pattern, subject }));
    const result = pm(pattern)(subject);
    assert.equal(result, expected, JSON.stringify({ pattern, subject }));
  }
  assert.equal(provenance.upstreamPatchedRelease, null);
  assert.equal(provenance.advisory, 'GHSA-fc5q-39xc-vjpf');
});
