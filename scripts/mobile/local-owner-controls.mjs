import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const operations = new Set(['disposeMatter', 'readMatterState', 'revokeMatterAccess', 'readNoteState']);
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
function checked(file, sha256) {
  assert.ok(path.isAbsolute(file) && statSync(file).isFile() && statSync(file).size <= 1048576, 'BOUNDED_OWNER_EVIDENCE_REQUIRED');
  const bytes = readFileSync(file);
  assert.equal(hash(bytes), sha256, 'OWNER_EVIDENCE_CHANGED');
  return bytes;
}
function command(args, input, signal, deadline, spawnProcess, now) {
  return new Promise((resolve, reject) => {
    const child = spawnProcess('docker', args, { windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', size = 0, done = false;
    const stop = (error) => {
      if (done) return;
      done = true;
      child.kill();
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      reject(error);
    };
    const abort = () => stop(new Error('OWNER_CONTROL_ABORTED'));
    const timer = setTimeout(() => stop(new Error('OWNER_CONTROL_DEADLINE')), Math.max(1, deadline - now()));
    signal.addEventListener('abort', abort, { once: true });
    child.on('error', () => stop(new Error('OWNER_DOCKER_START_FAILED')));
    child.stdout.on('data', (data) => {
      size += data.length;
      if (size > 65536) return stop(new Error('OWNER_OUTPUT_BOUND'));
      output += data.toString('utf8');
    });
    child.stderr.on('data', (data) => { size += data.length; if (size > 65536) stop(new Error('OWNER_OUTPUT_BOUND')); });
    child.on('close', (code) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      if (code !== 0) reject(new Error('OWNER_COMMAND_FAILED_NO_REPLAY'));
      else resolve(output);
    });
    child.stdin.on('error', () => stop(new Error('OWNER_STDIN_FAILED')));
    child.stdin.end(input);
    if (signal.aborted) abort();
  });
}

export function createOwnerControls({ spawnProcess = spawn, cacheRoot, now = Date.now } = {}) {
  let phase = 'new', child, pending, context, workerId, ready, busy = false, sequence = 0, lifetime;
  let buffer = Buffer.alloc(0), stderrBytes = 0, exited, resolveExit, stopping = false;
  const fail = (error) => {
    phase = 'failed';
    clearTimeout(lifetime);
    if (pending) { const current = pending; pending = undefined; current.finish(error); }
    if (child && !exited && !stopping) {
      stopping = true;
      child.kill(); // Only the exact docker-exec child created by this adapter.
    }
  };
  function load(backendSha) {
    const cache = path.resolve(cacheRoot || process.env.CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE || path.join(os.homedir(), '.cache/caseops-mobile/local-docker-20261025'));
    const pointer = JSON.parse(readFileSync(path.join(cache, 'owner-active.json'), 'utf8'));
    assert.match(pointer.file || '', /^owner-binding-[a-zA-Z0-9_-]+\.json$/);
    const binding = JSON.parse(checked(path.join(cache, pointer.file), pointer.sha256));
    assert.match(binding.extensionFile || '', /^[a-zA-Z0-9_.-]+\.json$/);
    const extension = JSON.parse(checked(path.join(cache, binding.extensionFile), binding.extensionSha256));
    checked(binding.pythonPath, binding.pythonSha256);
    assert.equal(path.normalize(binding.modulePath), path.normalize(fileURLToPath(import.meta.url)));
    checked(binding.modulePath, binding.moduleSha256);
    assert.equal(binding.environment, 'docker-integration');
    assert.equal(binding.syntheticDataOnly, true);
    assert.equal(binding.backendSha, backendSha, 'OWNER_RELEASE_CHANGED_REBIND_REQUIRED');
    assert.match(binding.apiContainerId || '', /^[a-f0-9]{64}$/, 'IMMUTABLE_OWNER_CONTAINER_ID_REQUIRED');
    assert.match(binding.apiImage || '', /^sha256:[a-f0-9]{64}$/);
    assert.match(binding.project || '', /^[a-zA-Z0-9_-]{1,100}$/);
    return { cache, pointer, binding, extension };
  }
  async function inspect(current, signal, deadline) {
    const items = JSON.parse(await command(['inspect', current.binding.apiContainerId], '', signal, deadline, spawnProcess, now));
    assert.equal(items.length, 1);
    const inspected = items[0], binding = current.binding;
    assert.equal(inspected.Id, binding.apiContainerId);
    assert.equal(inspected.Image, binding.apiImage);
    assert.equal(inspected.Config.Labels['com.docker.compose.project'], binding.project);
    assert.equal(inspected.Config.Labels['com.docker.compose.service'], 'api');
    assert.equal(inspected.State.Running, true);
  }
  function rpc(request, type, signal, deadline) {
    assert.equal(pending, undefined, 'OWNER_SINGLE_INFLIGHT_REQUIRED');
    assert.ok(signal instanceof AbortSignal && !signal.aborted, 'OWNER_ABORT_SIGNAL_REQUIRED');
    const line = `${JSON.stringify(request)}\n`;
    assert.ok(Buffer.byteLength(line) <= 4096, 'OWNER_REQUEST_BOUND');
    assert.ok(deadline > now(), 'OWNER_CONTROL_DEADLINE');
    return new Promise((resolve, reject) => {
      const abort = () => fail(new Error('OWNER_CONTROL_ABORTED'));
      const timer = setTimeout(() => fail(new Error('OWNER_CONTROL_DEADLINE')), Math.max(1, deadline - now()));
      pending = { request, type, finish(error, value) {
        clearTimeout(timer); signal.removeEventListener('abort', abort);
        if (error) reject(error); else resolve(value);
      } };
      signal.addEventListener('abort', abort, { once: true });
      child.stdin.write(line, (error) => { if (error) fail(new Error('OWNER_STDIN_FAILED')); });
      if (signal.aborted) abort();
    });
  }
  function data(chunk) {
    try {
      assert.ok(buffer.length + chunk.length <= 65536, 'OWNER_OUTPUT_BOUND');
      buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
      while (buffer.includes(10)) {
        const index = buffer.indexOf(10), line = buffer.subarray(0, index);
        buffer = buffer.subarray(index + 1);
        const value = JSON.parse(line.toString('utf8')), current = pending;
        assert.ok(current, 'UNSOLICITED_OWNER_RESPONSE');
        assert.equal(value.type, current.type, 'OWNER_PROTOCOL_TYPE');
        assert.equal(value.workerId, workerId, 'OWNER_PROTOCOL_WORKER');
        assert.equal(value.requestId, current.request.requestId, 'OWNER_PROTOCOL_REQUEST');
        if (current.type !== 'ready') assert.equal(value.readySha256, ready.sha256, 'OWNER_PROTOCOL_READY_PROOF');
        pending = undefined;
        current.finish(undefined, value);
      }
    } catch (error) { fail(error); }
  }
  async function prepare({ fixture, signal = AbortSignal.timeout(60000) } = {}) {
    assert.equal(phase, 'new', 'OWNER_PREPARATION_ALREADY_STARTED');
    phase = 'preparing';
    // Cold canonical imports/mappers are fixture startup, never an operation.
    const started = now(), deadline = started + 60000;
    try {
      assert.match(fixture?.backendSha || '', /^[a-f0-9]{40}$/, 'EXACT_OWNER_BACKEND_REQUIRED');
      assert.ok(signal instanceof AbortSignal && !signal.aborted, 'OWNER_ABORT_SIGNAL_REQUIRED');
      context = load(fixture.backendSha);
      for (const key of ['companyId', 'membershipId']) assert.equal(fixture[key], context.extension[key]);
      for (const key of ['lifecycleMatter', 'accessMatter']) assert.equal(fixture[key]?.id, context.extension[key].id);
      await inspect(context, signal, deadline);
      assert.ok(deadline > now() && !signal.aborted, 'OWNER_READINESS_DEADLINE');
      workerId = randomBytes(12).toString('hex');
      child = spawnProcess('docker', ['exec', '-i', context.binding.apiContainerId, 'python', '-B', '/mobile-fixture/local-owner.py', '--worker'],
        { windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'pipe'] });
      const exit = new Promise((resolve) => { resolveExit = resolve; });
      exited = false;
      child.stdout.on('data', data);
      child.stderr.on('data', (chunk) => { stderrBytes += chunk.length; if (stderrBytes > 65536) fail(new Error('OWNER_OUTPUT_BOUND')); });
      child.stdin.on('error', () => fail(new Error('OWNER_STDIN_FAILED')));
      child.on('error', () => fail(new Error('OWNER_DOCKER_START_FAILED')));
      child.on('close', () => {
        exited = true; resolveExit();
        if (!['closing', 'closed'].includes(phase)) fail(new Error('OWNER_WORKER_DISCONNECTED'));
      });
      context.exit = exit;
      const requestId = randomBytes(12).toString('hex');
      const response = await rpc({ type: 'prepare', workerId, requestId, backendSha: fixture.backendSha,
        apiContainerId: context.binding.apiContainerId, apiImage: context.binding.apiImage, project: context.binding.project,
        marker: 'no-paid-providers', deadlineMs: deadline, bindingFile: context.pointer.file,
        bindingSha256: context.pointer.sha256 }, 'ready', signal, deadline);
      assert.equal(response.readyFile, `owner-ready-${workerId}.json`);
      const evidencePath = path.join(context.cache, response.readyFile);
      const bytes = checked(evidencePath, response.readySha256), proof = JSON.parse(bytes);
      assert.ok(bytes.length <= 65536);
      for (const [key, value] of Object.entries({ kind: 'docker-owner-worker-ready', workerId, requestId,
        bindingFile: context.pointer.file, bindingSha256: context.pointer.sha256,
        ...Object.fromEntries(['backendSha', 'backendRevision', 'apiContainerId', 'apiImage', 'project', 'pythonSha256', 'moduleSha256', 'extensionSha256'].map((key) => [key, context.binding[key]])),
        maxCommands: 16, maxRequestBytes: 4096, maxResponseBytes: 65536, preparationTimeoutMs: 60000, operationDeadlineMs: 8000,
        idleSeconds: 1200, lifetimeSeconds: 1200, canonicalMutationImportsPreloaded: true, databaseSessionRetained: false })) assert.equal(proof[key], value, 'OWNER_READINESS_PROOF_MISMATCH');
      assert.match(proof.readyId || '', /^[a-f0-9]{24}$/);
      assert.equal(phase, 'preparing', 'OWNER_WORKER_DISCONNECTED');
      assert.ok(now() <= deadline && !signal.aborted, 'OWNER_READINESS_DEADLINE');
      ready = { file: response.readyFile, sha256: response.readySha256 };
      phase = 'ready';
      lifetime = setTimeout(() => fail(new Error('OWNER_WORKER_LIFETIME_EXPIRED')), Math.max(1, started + 1200000 - now()));
      lifetime.unref?.();
      return { kind: proof.kind, workerId, evidencePath, evidenceSha256: ready.sha256, maxCommands: 16 };
    } catch (error) { fail(error); throw error; }
  }
  async function control({ operation, targetId, runId, backendSha, marker, signal }) {
    assert.equal(busy, false, 'OWNER_SINGLE_INFLIGHT_REQUIRED');
    busy = true;
    try {
      assert.ok(operations.has(operation), 'UNSUPPORTED_OWNER_OPERATION');
      for (const value of [targetId, runId]) assert.match(value || '', /^[a-zA-Z0-9_-]{1,100}$/, 'OWNER_IDENTITY_REQUIRED');
      assert.match(backendSha || '', /^[a-f0-9]{40}$/, 'EXACT_OWNER_BACKEND_REQUIRED');
      assert.equal(marker, 'no-paid-providers', 'OWNER_MARKER_REQUIRED');
      assert.ok(signal instanceof AbortSignal && !signal.aborted, 'OWNER_ABORT_SIGNAL_REQUIRED');
      assert.equal(phase, 'ready', 'OWNER_PREPARE_REQUIRED_OR_WORKER_FAILED');
      assert.ok(sequence < 16, 'OWNER_WORKER_COMMAND_BOUND');
      const deadline = now() + 8000, current = load(backendSha);
      checked(path.join(current.cache, ready.file), ready.sha256);
      assert.equal(current.pointer.file, context.pointer.file, 'OWNER_BINDING_CHANGED_REPREPARE_REQUIRED');
      assert.equal(current.pointer.sha256, context.pointer.sha256, 'OWNER_BINDING_CHANGED_REPREPARE_REQUIRED');
      const kind = ['disposeMatter', 'readMatterState'].includes(operation) ? 'lifecycleMatter' : 'accessMatter';
      assert.equal(current.extension[kind].id, targetId, 'UNOWNED_OWNER_TARGET');
      await inspect(current, signal, deadline);
      assert.equal(phase, 'ready', 'OWNER_WORKER_DISCONNECTED');
      const requestId = randomBytes(12).toString('hex');
      const response = await rpc({ type: 'control', operation, targetId, runId, backendSha, marker, requestId,
        workerId, readySha256: ready.sha256, deadlineMs: deadline,
        bindingFile: current.pointer.file, bindingSha256: current.pointer.sha256 }, 'result', signal, deadline);
      assert.equal(phase, 'ready', 'OWNER_WORKER_DISCONNECTED');
      sequence += 1;
      assert.equal(response.commandIndex, sequence, 'OWNER_PROTOCOL_SEQUENCE');
      assert.equal(response.evidenceFile, `owner-evidence-${requestId}.json`);
      const evidencePath = path.join(current.cache, response.evidenceFile), bytes = readFileSync(evidencePath);
      assert.ok(bytes.length <= 65536);
      const evidence = JSON.parse(bytes);
      for (const [key, value] of Object.entries({ operation, targetId, runId, backendSha, requestId, workerId,
        workerCommand: sequence, apiContainerId: current.binding.apiContainerId, apiImage: current.binding.apiImage,
        project: current.binding.project, backendRevision: current.binding.backendRevision })) assert.equal(evidence[key], value);
      assert.deepEqual(evidence.workerReadyEvidence, ready);
      assert.deepEqual(evidence.result, response.result);
      assert.ok(now() <= deadline && !signal.aborted, 'OWNER_CONTROL_DEADLINE');
      return { kind: 'docker-owner-control', operation, targetId, runId, backendSha,
        evidencePath, evidenceSha256: hash(bytes), result: evidence.result };
    } catch (error) { fail(error); throw error; }
    finally { busy = false; }
  }
  async function close() {
    if (phase === 'closed') return;
    clearTimeout(lifetime);
    if (!child || exited) { phase = 'closed'; return; }
    if (pending || phase !== 'ready') {
      fail(new Error('OWNER_WORKER_CLOSED'));
      phase = 'closed';
      return;
    }
    phase = 'closing';
    try {
      await rpc({ type: 'close', workerId, readySha256: ready.sha256, requestId: randomBytes(12).toString('hex') },
        'closed', AbortSignal.timeout(1000), now() + 1000);
      child.stdin.end();
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          if (!exited && !stopping) { stopping = true; child.kill(); }
          resolve();
        }, 1000);
        context.exit.then(() => { clearTimeout(timer); resolve(); });
      });
    } catch (error) { fail(error); throw error; }
    finally { phase = 'closed'; }
  }
  return { prepare, control, close };
}

const adapter = createOwnerControls();
export const prepare = adapter.prepare;
export const control = adapter.control;
export const close = adapter.close;
