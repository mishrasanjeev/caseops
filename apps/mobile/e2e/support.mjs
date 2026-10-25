import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { appendFileSync, closeSync, fsyncSync, lstatSync, openSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';

export const MARKER = 'no-paid-providers';
export const MARKER_HEADER = 'X-CaseOps-Automated-Test';

export function localUrl(value) {
  const url = new URL(value);
  assert.ok(['http:', 'https:'].includes(url.protocol), 'LOCAL_HTTP_REQUIRED');
  assert.ok(['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname), 'LOOPBACK_REQUIRED');
  assert.ok(!url.username && !url.password && !url.search && !url.hash, 'CLEAN_ORIGIN_REQUIRED');
  return url;
}

export async function localJson(url, options = {}) {
  localUrl(url);
  const response = await fetch(url, {
    ...options,
    redirect: 'error',
    signal: AbortSignal.timeout(10000),
    headers: { ...options.headers, [MARKER_HEADER]: MARKER },
  });
  assert.ok(response.ok, 'LOCAL_REQUEST_FAILED');
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      assert.ok(size <= 1048576, 'RESPONSE_BOUND_EXCEEDED');
      chunks.push(value);
    }
  } finally {
    await reader.cancel();
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

export function binaryHash(root) {
  const rootStat = lstatSync(root);
  if (rootStat.isFile()) {
    assert.ok(rootStat.size > 0 && rootStat.size <= 2147483648, 'BINARY_BOUND_EXCEEDED');
    return createHash('sha256').update(readFileSync(root)).digest('hex');
  }
  const hash = createHash('sha256');
  let files = 0;
  let bytes = 0;
  const visit = (file, relative) => {
    const stat = lstatSync(file);
    assert.ok(!stat.isSymbolicLink(), 'BINARY_SYMLINK_UNSUPPORTED');
    if (stat.isDirectory()) {
      for (const entry of readdirSync(file).sort()) visit(path.join(file, entry), `${relative}/${entry}`);
    } else {
      assert.ok(stat.isFile(), 'BINARY_REGULAR_FILE_REQUIRED');
      assert.ok(++files <= 30000 && (bytes += stat.size) <= 2147483648, 'BINARY_BOUND_EXCEEDED');
      hash.update(`${relative}\0${stat.size}\0`);
      hash.update(readFileSync(file));
    }
  };
  visit(root, '');
  assert.ok(files > 0, 'EMPTY_BINARY');
  return hash.digest('hex');
}

export function reconcileInventory(intended, discovered) {
  assert.ok(intended.length > 0, 'EMPTY_INVENTORY');
  assert.equal(new Set(intended).size, intended.length, 'DUPLICATE_INTENDED_ID');
  assert.equal(new Set(discovered).size, discovered.length, 'DUPLICATE_DISCOVERED_ID');
  assert.deepEqual(discovered, intended, 'INVENTORY_MISMATCH');
}

export class Journal {
  constructor(file) {
    this.fd = openSync(file, 'wx');
    this.events = [];
  }
  write(event) {
    assert.ok(this.events.length < 2000, 'JOURNAL_EVENT_BOUND');
    const entry = { at: new Date().toISOString(), ...event };
    appendFileSync(this.fd, `${JSON.stringify(entry)}\n`);
    fsyncSync(this.fd);
    this.events.push(entry);
  }
  close() { closeSync(this.fd); }
}

export function reconcileResults(events, intended) {
  const starts = events.filter((event) => event.type === 'run_started');
  assert.equal(starts.length, 1, 'MISSING_OR_DUPLICATE_START');
  reconcileInventory(intended, starts[0].intended);
  reconcileInventory(intended, starts[0].discovered);
  const completion = events.filter((event) => event.type === 'run_completed');
  assert.equal(completion.length, 1, 'MISSING_OR_DUPLICATE_COMPLETION');
  assert.equal(events.at(-1), completion[0], 'COMPLETION_MUST_BE_LAST');
  const strict = starts[0].inventoryId !== undefined;
  assert.equal(events.some((event) => event.type === 'run_interrupted'), false, 'INTERRUPTED_RUN_CANNOT_COMPLETE');
  if (strict) {
    assert.equal(completion[0].platform, starts[0].platform, 'COMPLETION_PLATFORM_MISMATCH');
    assert.equal(completion[0].intendedCount, intended.length, 'COMPLETION_COUNT_MISMATCH');
    assert.match(starts[0].harnessFingerprint || '', /^[a-f0-9]{64}$/, 'HARNESS_IDENTITY_REQUIRED');
    assert.equal(events[0], starts[0], 'START_MUST_BE_FIRST');
  }
  const preflights = events.filter((event) => event.type === 'preflight_result');
  assert.equal(preflights.length, 1, 'MISSING_OR_DUPLICATE_PREFLIGHT');
  assert.ok(['passed', 'failed'].includes(preflights[0].status), 'INVALID_PREFLIGHT');
  const postflights = events.filter((event) => event.type === 'postflight_result');
  assert.equal(postflights.length, preflights[0].status === 'passed' ? 1 : 0, 'POSTFLIGHT_INVENTORY_MISMATCH');
  for (const id of intended) {
    for (const phase of ['setup', 'call', 'teardown']) {
      const began = events.filter((event) => event.type === 'phase_started' && event.id === id && event.phase === phase);
      assert.equal(began.length, 1, 'MISSING_OR_DUPLICATE_PHASE_START');
      const rows = events.filter((event) => event.type === 'phase_result' && event.id === id && event.phase === phase);
      assert.equal(rows.length, 1, 'MISSING_OR_DUPLICATE_PHASE');
      assert.ok(events.indexOf(began[0]) < events.indexOf(rows[0]), 'PHASE_RESULT_BEFORE_START');
      assert.ok(['passed', 'failed', 'not-run', ...(strict ? ['blocked'] : [])].includes(rows[0].status), 'UNKNOWN_PHASE_STATUS');
    }
  }
  const phases = events.filter((event) => event.type === 'phase_result');
  assert.equal(phases.length, intended.length * 3, 'UNEXPECTED_PHASE_ID');
  if (strict) {
    assert.equal(events.filter((event) => event.type === 'phase_started').length, intended.length * 3, 'UNEXPECTED_PHASE_START');
    const phaseEvents = events.filter((event) => ['phase_started', 'phase_result'].includes(event.type));
    const expected = intended.flatMap((id) => ['setup', 'call', 'teardown'].flatMap((phase) =>
      ['phase_started', 'phase_result'].map((type) => ({ id, phase, type }))));
    assert.deepEqual(phaseEvents.map(({ id, phase, type }) => ({ id, phase, type })), expected, 'PHASE_EXECUTION_ORDER_MISMATCH');
    assert.ok(events.indexOf(preflights[0]) < events.indexOf(phaseEvents[0]), 'PREFLIGHT_MUST_PRECEDE_CASES');
    for (const id of intended) {
      const rows = phases.filter((row) => row.id === id);
      assert.ok(['passed', 'failed', 'blocked'].includes(rows[0].status), 'INVALID_SETUP_OUTCOME');
      assert.ok(['passed', 'failed'].includes(rows[2].status), 'INVALID_TEARDOWN_OUTCOME');
      if (preflights[0].status !== 'passed') assert.notEqual(rows[0].status, 'passed', 'SETUP_PASSED_AFTER_FAILED_PREFLIGHT');
      if (rows[0].status !== 'passed') assert.equal(rows[1].status, 'not-run', 'CALL_EXECUTED_AFTER_FAILED_SETUP');
      else assert.notEqual(rows[1].status, 'not-run', 'CALL_UNEXECUTED_AFTER_PASSED_SETUP');
    }
    if (postflights.length) assert.ok(events.indexOf(postflights[0]) > events.indexOf(phaseEvents.at(-1)), 'POSTFLIGHT_MUST_FOLLOW_CASES');
  }
  return {
    nativeCallsPassed: phases.filter((row) => row.phase === 'call' && row.status === 'passed').length,
    failedPhases: phases.filter((row) => row.status === 'failed').length,
    unexecutedCalls: phases.filter((row) => row.phase === 'call' && row.status === 'not-run').length,
    blockedCalls: phases.filter((row) => row.phase === 'call' && row.status === 'blocked').length,
    blockedScenarios: new Set(phases.filter((row) => row.status === 'blocked').map((row) => row.id)).size,
    status: phases.every((row) => row.status === 'passed') && preflights[0].status === 'passed'
      && postflights[0]?.status === 'passed' ? 'passed' : 'incomplete-or-failed',
  };
}

export function safeFailure(error, fallback) {
  const code = /^([A-Z][A-Z0-9_]{2,})(?:\n|$)/.exec(error?.message || '')?.[1];
  return code || (['ENOENT', 'ECONNREFUSED', 'ETIMEDOUT'].includes(error?.code) ? error.code : fallback);
}

export async function byTestId(driver, platform, id) {
  assert.match(id, /^[a-zA-Z0-9_.:-]{1,160}$/, 'INVALID_TEST_ID');
  const selector = platform === 'android' ? `id=${id}` : `~${id}`;
  const element = await driver.$(selector);
  await element.waitForDisplayed({ timeout: 10000 });
  return element;
}
