import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { appendFileSync, closeSync, constants, fstatSync, fsyncSync, lstatSync, openSync, opendirSync, readSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { performance } from 'node:perf_hooks';

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
  const parsed = localUrl(url);
  assert.ok(options && Object.keys(options).length === 0, 'READ_ONLY_LOCAL_PROBE_REQUIRED');
  // This client reads status/build evidence only. Reconstruct the request from
  // reviewed literals so an input file cannot supply arbitrary path/header/body
  // data, even to a local listener.
  const protocol = parsed.protocol === 'https:' ? 'https:' : 'http:';
  const hostname = parsed.hostname === 'localhost' ? 'localhost' : parsed.hostname === '[::1]' ? '[::1]' : '127.0.0.1';
  const port = parsed.port ? Number(parsed.port) : protocol === 'https:' ? 443 : 80;
  assert.ok(Number.isInteger(port) && port > 0 && port <= 65535, 'LOCAL_PROBE_PORT_REQUIRED');
  const pathname = ['/api/build', '/api/release-identity', '/__caseops_e2e/status', '/status', '/wd/hub/status']
    .find(candidate => candidate === parsed.pathname);
  assert.ok(pathname, 'LOCAL_PROBE_ENDPOINT_REQUIRED');
  const destination = `${protocol}//${hostname}:${port}${pathname}`;
  const response = await fetch(destination, {
    method: 'GET',
    redirect: 'error',
    signal: AbortSignal.timeout(10000),
    headers: { [MARKER_HEADER]: MARKER },
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

const binaryFields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const binaryFrame = value => binaryFields.map(key => String(value[key]));
const binarySame = (a, b, cross = false) => binaryFields.every(key =>
  (cross && key === 'dev' && process.platform === 'win32' && b.dev === 0n) || a[key] === b[key]);

function readBinaryFile(file, remaining, allowEmpty = true, { check = () => {}, chargeBytes = () => {}, expected, namespace = () => [] } = {}) {
  check();
  const fd = openSync(file, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  try {
    const opened = fstatSync(fd, { bigint: true });
    assert.ok(opened.isFile(), 'BINARY_REGULAR_FILE_REQUIRED');
    assert.ok(opened.size <= BigInt(remaining) && (allowEmpty || opened.size > 0n), 'BINARY_BOUND_EXCEEDED');
    const named = lstatSync(file, { bigint: true });
    assert.ok(named.isFile() && !named.isSymbolicLink() && binarySame(opened, named, true), 'BINARY_FILE_REPLACED');
    if (expected) assert.deepEqual(binaryFrame(named), expected, 'BINARY_FILE_REPLACED');
    const parents = namespace(file);
    const buffer = Buffer.alloc(Number(opened.size) + 1);
    let length = 0;
    while (length < buffer.length) {
      check();
      const count = readSync(fd, buffer, length, Math.min(65536, buffer.length - length), null);
      chargeBytes(count); check();
      if (count === 0) break;
      length += count;
    }
    const after = fstatSync(fd, { bigint: true }), final = lstatSync(file, { bigint: true });
    assert.ok(binarySame(opened, after) && binarySame(named, final) && final.isFile() && !final.isSymbolicLink()
      && BigInt(length) === opened.size, 'BINARY_FILE_CHANGED');
    assert.deepEqual(namespace(file), parents, 'BINARY_NAMESPACE_CHANGED'); check();
    return buffer.subarray(0, length);
  } finally { closeSync(fd); }
}

export const BINARY_HASH_LIMITS = Object.freeze({ files: 30000, payloadBytes: 2147483648,
  inventoryEntries: 60000, depth: 64, milliseconds: 30000 });

/** Two metadata censuses share one entry/deadline budget. Payload is read once;
 * the legacy file/directory digest serialization is unchanged. */
export function binaryHash(root, { maxEntries = BINARY_HASH_LIMITS.inventoryEntries,
  maxDepth = BINARY_HASH_LIMITS.depth, timeoutMs = BINARY_HASH_LIMITS.milliseconds } = {}) {
  for (const [value, maximum] of [[maxEntries, 60000], [timeoutMs, 30000]]) assert.ok(Number.isSafeInteger(value) && value > 0 && value <= maximum, 'BINARY_BOUND_REQUIRED');
  assert.ok(Number.isSafeInteger(maxDepth) && maxDepth >= 0 && maxDepth <= 64, 'BINARY_BOUND_REQUIRED');
  const deadline = performance.now() + timeoutMs;
  const check = () => assert.ok(performance.now() < deadline, 'BINARY_CENSUS_DEADLINE');
  let chargedEntries = 0, bytesRead = 0;
  const charge = () => { check(); assert.ok(chargedEntries < maxEntries, 'BINARY_CENSUS_ENTRY_BOUND'); chargedEntries++; };
  const chargeBytes = count => { bytesRead += count; assert.ok(bytesRead <= BINARY_HASH_LIMITS.payloadBytes + 1, 'BINARY_BOUND_EXCEEDED'); };
  root = path.resolve(root); check();
  const rootProbe = lstatSync(root);
  if (rootProbe.isFile()) {
    assert.ok(rootProbe.size > 0 && rootProbe.size <= 2147483648, 'BINARY_BOUND_EXCEEDED');
    return createHash('sha256').update(readBinaryFile(root, 2147483648, false, { check, chargeBytes })).digest('hex');
  }
  const rootStat = lstatSync(root, { bigint: true });
  assert.ok(!rootStat.isSymbolicLink(), 'BINARY_SYMLINK_UNSUPPORTED');
  assert.ok(rootStat.isDirectory(), 'BINARY_REGULAR_FILE_REQUIRED');
  const canonical = file => (realpathSync.native ?? realpathSync)(file);
  const canonicalRoot = canonical(root);
  const external = () => {
    check(); assert.equal(canonical(root), canonicalRoot, 'BINARY_NAMESPACE_CHANGED');
    const result = [];
    for (let p = path.dirname(canonicalRoot);; p = path.dirname(p)) {
      check(); const value = lstatSync(p, { bigint: true });
      assert.ok(value.isDirectory() && !value.isSymbolicLink(), 'BINARY_NAMESPACE_CHANGED');
      result.push([p, ...['dev', 'ino', 'mode', 'uid', 'gid'].map(key => String(value[key]))]);
      if (path.dirname(p) === p) return result;
    }
  };
  const parents = external();
  let admittedDirectories;
  const namespace = file => {
    check(); assert.equal(canonical(file), path.join(canonicalRoot, path.relative(root, file)), 'BINARY_NAMESPACE_CHANGED');
    const result = [];
    if (admittedDirectories && file !== root) for (let p = path.dirname(file);; p = path.dirname(p)) {
      check(); const value = lstatSync(p, { bigint: true }), expected = admittedDirectories.get(p);
      assert.ok(value.isDirectory() && !value.isSymbolicLink() && expected, 'BINARY_NAMESPACE_CHANGED');
      const identity = binaryFrame(value).slice(0, 5);
      assert.deepEqual(identity, expected.slice(0, 5), 'BINARY_NAMESPACE_CHANGED'); result.push([p, ...identity]);
      if (p === root) break;
    }
    return result;
  };
  const inventory = () => {
    assert.deepEqual(external(), parents, 'BINARY_NAMESPACE_CHANGED');
    const rows = [], paths = new Set(), todo = [{ file: root, relative: '', depth: 0 }];
    let files = 0, declaredBytes = 0; charge();
    while (todo.length) {
      check(); const item = todo.pop(), { file, relative, depth } = item;
      assert.ok(!paths.has(file), 'BINARY_DUPLICATE_ENTRY'); paths.add(file);
      const value = lstatSync(file, { bigint: true }); namespace(file);
      if (file === root) assert.ok(value.isDirectory() && binarySame(value, rootStat), 'BINARY_DIRECTORY_CHANGED');
      assert.ok(!value.isSymbolicLink(), 'BINARY_SYMLINK_UNSUPPORTED');
      const row = { file, relative, kind: value.isDirectory() ? 'directory' : 'file', metadata: binaryFrame(value) };
      if (value.isDirectory()) {
        const names = [], seen = new Set(); let directory;
        try {
          check(); directory = opendirSync(file, { bufferSize: 1 });
          for (;;) {
            check(); const entry = directory.readSync(); check(); if (!entry) break;
            assert.ok(typeof entry.name === 'string' && entry.name && !['.', '..'].includes(entry.name)
              && path.basename(entry.name) === entry.name && !seen.has(entry.name), 'BINARY_DUPLICATE_ENTRY');
            assert.ok(depth < maxDepth, 'BINARY_CENSUS_DEPTH_BOUND');
            charge(); seen.add(entry.name); names.push(entry.name);
          }
        } finally { if (directory) directory.closeSync(); }
        names.sort(); row.names = names;
        assert.deepEqual(binaryFrame(lstatSync(file, { bigint: true })), row.metadata, 'BINARY_DIRECTORY_CHANGED'); namespace(file);
        for (let i = names.length - 1; i >= 0; i--) todo.push({ file: path.join(file, names[i]), relative: `${relative}/${names[i]}`, depth: depth + 1 });
      } else {
        assert.ok(value.isFile(), 'BINARY_REGULAR_FILE_REQUIRED');
        assert.ok(++files <= 30000 && value.size <= BigInt(2147483648 - declaredBytes), 'BINARY_BOUND_EXCEEDED');
        declaredBytes += Number(value.size);
      }
      rows.push(row);
    }
    assert.ok(rows[0]?.file === root, 'BINARY_ROOT_REQUIRED');
    assert.deepEqual(external(), parents, 'BINARY_NAMESPACE_CHANGED');
    return rows;
  };
  const first = inventory(), hash = createHash('sha256'); let logicalBytes = 0, files = 0;
  admittedDirectories = new Map(first.filter(row => row.kind === 'directory').map(row => [row.file, row.metadata]));
  for (const row of first) if (row.kind === 'file') {
    const content = readBinaryFile(row.file, 2147483648 - logicalBytes, true, { check, chargeBytes, expected: row.metadata, namespace });
    logicalBytes += content.length; files++;
    hash.update(`${row.relative}\0${content.length}\0`); hash.update(content);
  }
  const second = inventory(); assert.deepEqual(second, first, 'BINARY_CENSUS_CHANGED');
  for (const row of second) { check(); assert.deepEqual(binaryFrame(lstatSync(row.file, { bigint: true })), row.metadata, 'BINARY_CENSUS_CHANGED'); namespace(row.file); }
  for (const row of second) if (row.kind === 'directory') { check(); assert.deepEqual(binaryFrame(lstatSync(row.file, { bigint: true })), row.metadata, 'BINARY_CENSUS_CHANGED'); namespace(row.file); }
  assert.deepEqual(external(), parents, 'BINARY_NAMESPACE_CHANGED'); check();
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
