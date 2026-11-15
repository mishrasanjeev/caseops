import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { openSync, appendFileSync, fsyncSync, closeSync, fstatSync, lstatSync, readSync } from 'node:fs';
import path from 'node:path';
import { V1_BUDGETS } from './v1-workflows-inventory.mjs';

// Passive browser observations have a separate, mandatory trace. This is an
// explicit aggregate allowance of 4,000 events / 2 MiB, not the old aggregate
// 2,000-event limit. Each stream retains that original entry limit. Neither
// stream may drop observations or continue after a failed write.
export const V1_EVIDENCE_LIMITS = Object.freeze({ streamEvents: 2000, streamBytes: 1048576 });
const nativeIo = { openSync, appendFileSync, fsyncSync, closeSync, fstatSync, lstatSync, readSync };
export class V1RunEvidence {
  constructor(directory, io = nativeIo, { now = () => performance.now(), milliseconds = V1_BUDGETS.serialInventoryMs } = {}) {
    assert.ok(Number.isFinite(milliseconds) && milliseconds > 0 && milliseconds <= V1_BUDGETS.serialInventoryMs);
    this.now = now; this.deadline = now() + milliseconds;
    this.io = io;
    this.sequence = 0; this.failure = null; this.closed = false;
    this.streams = [];
    try {
      for (const name of ['events.jsonl', 'browser-events.jsonl']) this.streams.push({
        name, file: path.join(directory, name), fd: io.openSync(path.join(directory, name), 'wx+', 0o600), events: [], bytes: 0, hash: createHash('sha256'),
      });
    } catch (error) { for (const stream of this.streams) io.closeSync(stream.fd); throw error; }
  }
  get events() { return this.streams[0].events; }
  assertDeadline() {
    if (this.now() >= this.deadline) {
      this.abort('V1_THIRTY_MINUTE_SERIAL_BOUND'); throw new Error('V1_THIRTY_MINUTE_SERIAL_BOUND');
    }
  }
  assertActive() {
    this.assertDeadline();
    assert.equal(this.closed, false, 'V1_EVIDENCE_CLOSED');
    if (this.failure) throw new Error(this.failure);
  }
  abort(reason) { this.failure ??= reason; }
  write(event) {
    this.assertActive();
    let stream, refusal;
    try {
      stream = this.streams[event.type === 'browser_step' ? 1 : 0];
      const entry = { at: new Date().toISOString(), ...event, evidenceSequence: this.sequence + 1 };
      const bytes = Buffer.from(JSON.stringify(entry) + '\n');
      if (stream.events.length >= V1_EVIDENCE_LIMITS.streamEvents) refusal = 'V1_EVIDENCE_EVENT_BOUND';
      else if (stream.bytes + bytes.length > V1_EVIDENCE_LIMITS.streamBytes) refusal = 'V1_EVIDENCE_BYTE_BOUND';
      if (refusal) throw new Error(refusal);
      stream.writeUncertain = true;
      this.io.appendFileSync(stream.fd, bytes); this.io.fsyncSync(stream.fd);
      stream.hash.update(bytes); stream.bytes += bytes.length;
      stream.events.push(JSON.parse(bytes.toString('utf8'))); this.sequence++;
      stream.writeUncertain = false;
    } catch {
      this.failure = refusal || 'V1_EVIDENCE_WRITE_FAILED';
      throw new Error(this.failure);
    }
  }
  close() {
    if (!this.closed) {
      this.closed = true;
      for (const stream of this.streams) {
        try {
          if (!stream.writeUncertain) {
            const opened = this.io.fstatSync(stream.fd, { bigint: true });
            const same = (left, right) => ['ino', 'size', 'mtimeNs', 'ctimeNs', 'uid', 'gid', 'mode', 'nlink']
              .every(key => left[key] === right[key]) && (process.platform === 'win32' || left.dev === right.dev);
            const named = this.io.lstatSync(stream.file, { bigint: true });
            assert.ok(opened.isFile() && !named.isSymbolicLink() && opened.nlink === 1n && same(opened, named));
            assert.ok(typeof process.getuid !== 'function' || opened.uid === BigInt(process.getuid()));
            assert.ok(process.platform === 'win32' || (opened.mode & 0o777n) === 0o600n);
            assert.equal(opened.size, BigInt(stream.bytes));
            const bytes = Buffer.alloc(stream.bytes), hash = createHash('sha256');
            let offset = 0;
            while (offset < bytes.length) {
              const count = this.io.readSync(stream.fd, bytes, offset, bytes.length - offset, offset);
              assert.ok(Number.isInteger(count) && count > 0 && count <= bytes.length - offset); offset += count;
            }
            hash.update(bytes);
            assert.equal(hash.digest('hex'), stream.hash.copy().digest('hex'));
            assert.ok(same(opened, this.io.fstatSync(stream.fd, { bigint: true }))
              && same(opened, this.io.lstatSync(stream.file, { bigint: true })));
            stream.finalBytes = bytes;
            stream.events = bytes.length ? bytes.toString('utf8').trimEnd().split('\n').map(line => JSON.parse(line)) : [];
          }
        } catch { stream.writeUncertain = true; this.failure ??= 'V1_EVIDENCE_FINAL_BYTES_UNVERIFIED'; }
        try { this.io.closeSync(stream.fd); } catch {
          stream.writeUncertain = true; this.failure ??= 'V1_EVIDENCE_CLOSE_FAILED';
        }
      }
      this.manifest = { schemaVersion: 1, status: this.failure ? 'incomplete' : 'complete', failure: this.failure,
        totalEvents: this.sequence, aggregateEventLimit: 4000, aggregateByteLimit: 2097152,
        streams: this.streams.map(stream => ({ file: stream.name, count: stream.events.length,
          bytes: stream.writeUncertain ? null : stream.bytes, acceptedPrefixBytes: stream.bytes,
          sha256: stream.writeUncertain ? null : stream.hash.copy().digest('hex'),
          acceptedPrefixSha256: stream.hash.digest('hex'), fileBytesVerified: !stream.writeUncertain,
          firstSequence: stream.events[0]?.evidenceSequence ?? null,
          lastSequence: stream.events.at(-1)?.evidenceSequence ?? null })) };
    }
    return this.manifest;
  }
}

// Cleanup ownership survives logging failure. Mark an attempt BEFORE transport;
// a lost acknowledgement must never trigger another delete of that session.
export class V1OwnedSessions {
  constructor(timeoutMs = 60000) {
    assert.ok(Number.isInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 60000);
    this.timeoutMs = timeoutMs; this.sessions = [];
  }
  add(driver) {
    assert.ok(this.sessions.length < 17 && this.sessions.every(row => row.attempted), 'V1_OWNED_SESSION_BOUND');
    assert.ok(driver?.sessionId && !this.sessions.some(row => row.id === driver.sessionId), 'UNIQUE_OWNED_V1_SESSION_REQUIRED');
    this.sessions.push({ driver, id: driver.sessionId, attempted: false, acknowledged: false });
  }
  async remove(driver, record) {
    const row = this.sessions.find(value => value.driver === driver);
    assert.ok(row && !row.attempted, 'V1_SESSION_DELETE_MUST_NOT_REPLAY');
    row.attempted = true;
    let timeout;
    try {
      await Promise.race([driver.deleteSession(), new Promise((_, reject) => {
        timeout = setTimeout(() => reject(new Error('V1_SESSION_DELETE_ACK_UNKNOWN')), this.timeoutMs);
      })]); row.acknowledged = true;
    } finally { clearTimeout(timeout); }
    record?.(row.id);
  }
  async close() {
    for (const row of this.sessions) if (!row.attempted) {
      try { await this.remove(row.driver); } catch { /* retained as unknown, never replayed */ }
    }
    return this.snapshot();
  }
  snapshot() { return this.sessions.map(({ id, attempted, acknowledged }) => ({ id, attempted, acknowledged })); }
}

export function validateV1EvidenceStreams(manifest, mainBytes, browserBytes) {
  assert.equal(manifest.status, 'complete', 'COMPLETE_V1_EVIDENCE_REQUIRED');
  assert.equal(manifest.failure, null);
  assert.equal(manifest.aggregateEventLimit, 4000); assert.equal(manifest.aggregateByteLimit, 2097152);
  assert.equal(manifest.streams.length, 2);
  const merged = [];
  for (const [index, raw] of [mainBytes, browserBytes].entries()) {
    const entry = manifest.streams[index], expected = index === 0 ? 'events.jsonl' : 'browser-events.jsonl';
    assert.equal(entry.file, expected); const bytes = Buffer.from(raw);
    assert.equal(entry.fileBytesVerified, true);
    assert.equal(bytes.length, entry.bytes); assert.ok(bytes.length <= V1_EVIDENCE_LIMITS.streamBytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), entry.sha256);
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    assert.ok(text === '' || text.endsWith('\n'));
    const events = text === '' ? [] : text.slice(0, -1).split('\n').map(line => JSON.parse(line));
    assert.equal(events.length, entry.count); assert.ok(events.length <= V1_EVIDENCE_LIMITS.streamEvents);
    assert.equal(entry.firstSequence, events[0]?.evidenceSequence ?? null);
    assert.equal(entry.lastSequence, events.at(-1)?.evidenceSequence ?? null);
    for (const event of events) {
      assert.equal(event.type === 'browser_step', index === 1, 'V1_EVIDENCE_STREAM_ROUTING_REQUIRED');
      assert.ok(Number.isSafeInteger(event.evidenceSequence) && event.evidenceSequence > 0);
    }
    merged.push(...events);
  }
  merged.sort((a, b) => a.evidenceSequence - b.evidenceSequence);
  assert.equal(merged.length, manifest.totalEvents);
  merged.forEach((event, index) => assert.equal(event.evidenceSequence, index + 1, 'COMPLETE_V1_EVIDENCE_ORDER_REQUIRED'));
  return merged;
}

export function finishV1Evidence(journal, validate) {
  const evidence = journal.close();
  try {
    validateV1EvidenceStreams(evidence, ...journal.streams.map(stream => stream.finalBytes));
    const result = validate(journal.events);
    journal.assertDeadline();
    return { completed: true, evidence, result };
  } catch {
    return { completed: false, evidence, reason: journal.failure || 'V1_FINAL_EVIDENCE_OR_RESULT_INCOMPLETE' };
  }
}

export async function verifyV1SessionAbsence(sessions, request, now = () => performance.now()) {
  assert.ok(sessions.length <= 17 && new Set(sessions.map(row => row.id)).size === sessions.length);
  const end = now() + 60000, absent = [];
  const read = async route => {
    const remaining = end - now(); assert.ok(remaining > 0, 'V1_SESSION_ABSENCE_DEADLINE');
    const value = await request(route, Math.min(5000, remaining));
    assert.ok(now() < end, 'V1_SESSION_ABSENCE_DEADLINE'); return value;
  };
  for (const { id } of sessions) {
    assert.match(id, /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i);
    const response = await read(`/session/${id}/timeouts`);
    assert.equal(response.status, 404, 'OWNED_V1_SESSION_STILL_PRESENT');
    assert.equal(response.value?.error, 'invalid session id', 'OWNED_V1_SESSION_ABSENCE_REQUIRED');
    absent.push({ id, status: 404, error: 'invalid session id' });
  }
  const inventory = await read('/appium/sessions');
  assert.equal(inventory.status, 200); assert.deepEqual(inventory.value, [], 'COMPLETE_V1_SESSION_INVENTORY_MUST_BE_EMPTY');
  return { verified: true, known: absent, completeSessionInventory: [] };
}

export async function readV1SessionStatus(target, milliseconds, transport = fetch) {
  const url = new URL(target);
  assert.ok(['http:', 'https:'].includes(url.protocol) && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname));
  assert.ok(!url.username && !url.password && !url.search && !url.hash);
  assert.ok(Number.isInteger(milliseconds) && milliseconds > 0 && milliseconds <= 5000);
  const response = await transport(url, { redirect: 'error', headers: { 'X-CaseOps-Automated-Test': 'no-paid-providers' }, signal: AbortSignal.timeout(milliseconds) });
  assert.ok([200, 404].includes(response.status), 'V1_SESSION_STATUS_REQUIRED');
  assert.ok(response.body, 'V1_SESSION_STATUS_BODY_REQUIRED');
  const reader = response.body.getReader(), chunks = []; let size = 0, finished = false;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) { finished = true; break; }
      size += value.byteLength; assert.ok(size <= 16384, 'V1_SESSION_STATUS_RESPONSE_BOUND'); chunks.push(value);
    }
  } finally {
    if (!finished) try { await reader.cancel(); } catch { /* original refusal is preserved */ }
    reader.releaseLock();
  }
  const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks, size)));
  return { status: response.status, value: value.value };
}
