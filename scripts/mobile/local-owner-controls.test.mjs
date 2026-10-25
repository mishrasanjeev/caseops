import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { EventEmitter } from 'node:events';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { control, createOwnerControls } from './local-owner-controls.mjs';

const base = () => ({ operation: 'readMatterState', targetId: 'synthetic-target', runId: 'unit-only',
  backendSha: 'd'.repeat(40), marker: 'no-paid-providers', signal: AbortSignal.timeout(1000) });
test('unsupported command cannot reach Docker or SQL', async () => {
  await assert.rejects(control({ ...base(), operation: 'reopenMatter' }), /UNSUPPORTED_OWNER_OPERATION/);
});
test('missing marker cannot reach Docker or SQL', async () => {
  await assert.rejects(control({ ...base(), marker: '' }), /OWNER_MARKER_REQUIRED/);
});
test('invalid target cannot reach Docker or SQL', async () => {
  await assert.rejects(control({ ...base(), targetId: '../other-target' }), /OWNER_IDENTITY_REQUIRED/);
});
test('an already aborted command cannot reach Docker or SQL', async () => {
  await assert.rejects(control({ ...base(), signal: AbortSignal.abort() }), /OWNER_ABORT_SIGNAL_REQUIRED/);
});

test('Python owner read imports stay lean while canonical mutations and authority budgets remain fenced', (t) => {
  const result = spawnSync(process.env.PYTHON || 'python', ['-B', fileURLToPath(new URL('./local-owner.test.py', import.meta.url))],
    { encoding: 'utf8', windowsHide: true, shell: false });
  assert.equal(result.error, undefined, result.error?.message);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  const report = JSON.parse(result.stdout);
  assert.equal(report.offlineOnly, true);
  assert.equal(report.testsRun, 22);
  assert.equal(new Set(report.collected).size, report.testsRun);
  assert.equal(report.successful, true);
  assert.deepEqual([report.failures, report.errors, report.skipped], [[], [], []]);
  t.diagnostic(JSON.stringify(report));
});

// Injected children below are offline protocol units, never Docker integration receipts.
function workerFixture(t, options = {}) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'caseops-owner-worker-unit-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const sha = (value) => createHash('sha256').update(value).digest('hex');
  const save = (name, value) => {
    const bytes = Buffer.from(JSON.stringify(value));
    writeFileSync(path.join(root, name), bytes, { flag: 'wx' });
    return sha(bytes);
  };
  const extension = { companyId: 'unit-company', membershipId: 'unit-member',
    lifecycleMatter: { id: 'unit-lifecycle' }, accessMatter: { id: 'unit-access' } };
  const modulePath = fileURLToPath(new URL('./local-owner-controls.mjs', import.meta.url));
  const pythonPath = fileURLToPath(new URL('./local-owner.py', import.meta.url));
  const binding = { environment: 'docker-integration', syntheticDataOnly: true, backendSha: 'd'.repeat(40),
    backendRevision: 'unit-api', project: 'unit-owner-project', apiContainerId: 'a'.repeat(64),
    apiImage: `sha256:${'b'.repeat(64)}`, modulePath, moduleSha256: sha(readFileSync(modulePath)),
    pythonPath, pythonSha256: sha(readFileSync(pythonPath)), extensionFile: 'unit-extension.json',
    extensionSha256: save('unit-extension.json', extension) };
  const pointer = { file: 'owner-binding-unit.json', sha256: save('owner-binding-unit.json', binding) };
  save('owner-active.json', pointer);
  const processes = [], requests = [];
  let image = binding.apiImage, count = 0, worker, readyHash;
  function spawnProcess(command, args) {
    assert.equal(command, 'docker');
    const process = new EventEmitter();
    Object.assign(process, { args, stdout: new EventEmitter(), stderr: new EventEmitter(), stdin: new EventEmitter(), killed: 0 });
    process.kill = () => { process.killed++; queueMicrotask(() => process.emit('close', 1)); return true; };
    processes.push(process);
    process.stdin.end = () => queueMicrotask(() => {
      if (args[0] === 'inspect') process.stdout.emit('data', Buffer.from(JSON.stringify([{
        Id: binding.apiContainerId, Image: image, State: { Running: true },
        Config: { Labels: { 'com.docker.compose.project': binding.project, 'com.docker.compose.service': 'api' } },
      }])));
      process.emit('close', 0);
    });
    if (args[0] === 'exec') {
      assert.deepEqual(args, ['exec', '-i', binding.apiContainerId, 'python', '-B', '/mobile-fixture/local-owner.py', '--worker']);
      worker = process;
      process.stdin.write = (line, callback) => {
        assert.ok(Buffer.byteLength(line) <= 4096);
        const request = JSON.parse(line);
        requests.push(request);
        let response;
        if (request.type === 'prepare') {
          const proof = { kind: 'docker-owner-worker-ready', workerId: request.workerId, requestId: request.requestId,
            readyId: 'e'.repeat(24), bindingFile: pointer.file, bindingSha256: pointer.sha256,
            ...Object.fromEntries(['backendSha', 'backendRevision', 'apiContainerId', 'apiImage', 'project', 'pythonSha256', 'moduleSha256', 'extensionSha256'].map((key) => [key, binding[key]])),
            maxCommands: 16, maxRequestBytes: 4096, maxResponseBytes: 65536, operationDeadlineMs: 8000,
            idleSeconds: 1200, lifetimeSeconds: 1200, canonicalMutationImportsPreloaded: true, databaseSessionRetained: false };
          const readyFile = `owner-ready-${request.workerId}.json`;
          readyHash = save(readyFile, proof);
          response = { type: 'ready', workerId: request.workerId, requestId: request.requestId, readyFile, readySha256: readyHash };
        } else if (request.type === 'control') {
          count++;
          const result = { status: 'intake', isActive: true, lifecycleVersion: 0, noteIds: [] };
          const evidenceFile = `owner-evidence-${request.requestId}.json`;
          save(evidenceFile, { kind: 'docker-owner-control', ...request,
            apiContainerId: binding.apiContainerId, apiImage: binding.apiImage, project: binding.project,
            backendRevision: binding.backendRevision, workerCommand: count,
            workerReadyEvidence: { file: `owner-ready-${request.workerId}.json`, sha256: readyHash }, result });
          response = { type: 'result', workerId: request.workerId, requestId: request.requestId,
            readySha256: readyHash, commandIndex: count, evidenceFile, result };
        } else {
          response = { type: 'closed', workerId: request.workerId, requestId: request.requestId, readySha256: readyHash };
        }
        callback?.();
        queueMicrotask(() => {
          const value = options.reply ? options.reply(request, response, process) : response;
          if (value !== undefined) process.stdout.emit('data', Buffer.isBuffer(value) ? value : Buffer.from(`${JSON.stringify(value)}\n`));
        });
        return true;
      };
    }
    return process;
  }
  const adapter = createOwnerControls({ spawnProcess, cacheRoot: root, now: options.now || Date.now });
  t.after(() => adapter.close().catch(() => {}));
  return { adapter, root, binding, pointer, processes, requests, get worker() { return worker; },
    setImage(value) { image = value; }, fixture: { ...extension, backendSha: binding.backendSha },
    prepare(signal) { return adapter.prepare({ fixture: this.fixture, signal }); },
    read(signal = AbortSignal.timeout(1000)) { return adapter.control({ ...base(), targetId: extension.lifecycleMatter.id, signal }); } };
}

test('cold control refuses execution until explicit preparation without launching Docker', async (t) => {
  const unit = workerFixture(t);
  await assert.rejects(unit.read(), /OWNER_PREPARE_REQUIRED/);
  assert.equal(unit.processes.length, 0);
});

test('preparation inspects immutable container identity and verifies a separate durable ready hash', async (t) => {
  const unit = workerFixture(t), ready = await unit.prepare();
  assert.equal(ready.kind, 'docker-owner-worker-ready');
  assert.equal(ready.maxCommands, 16);
  assert.match(ready.evidenceSha256, /^[a-f0-9]{64}$/);
  assert.equal(unit.processes.length, 2);
  assert.deepEqual(unit.processes[0].args, ['inspect', 'a'.repeat(64)]);
  assert.ok(unit.requests[0].deadlineMs - Date.now() <= 30000);
  assert.ok(unit.requests[0].deadlineMs - Date.now() >= 29000);
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 0);
});

test('warm control re-inspects and stays inside the unchanged eight-second deadline', async (t) => {
  const unit = workerFixture(t);
  await unit.prepare();
  const started = Date.now(), result = await unit.read();
  assert.equal(result.result.lifecycleVersion, 0);
  assert.equal(unit.processes.filter(({ args }) => args[0] === 'exec').length, 1);
  assert.equal(unit.processes.filter(({ args }) => args[0] === 'inspect').length, 2);
  assert.ok(unit.requests[1].deadlineMs - started <= 8000);
});

test('startup timeout kills only its owned exec child and never runs or retries a control', async (t) => {
  const unit = workerFixture(t, { reply: () => undefined });
  await assert.rejects(unit.prepare(AbortSignal.timeout(10)), /ABORTED/);
  assert.equal(unit.worker.killed, 1);
  assert.equal(unit.processes[0].killed, 0);
  await assert.rejects(unit.read(), /PREPARE_REQUIRED/);
  assert.equal(unit.requests.length, 1);
});

test('a timed-out operation poisons the worker without replaying an uncertain command', async (t) => {
  const unit = workerFixture(t, { reply: (request, response) => request.type === 'control' ? undefined : response });
  await unit.prepare();
  await assert.rejects(unit.read(AbortSignal.timeout(10)), /ABORTED/);
  await assert.rejects(unit.read(), /PREPARE_REQUIRED/);
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 1);
  assert.equal(unit.worker.killed, 1);
});

for (const alteration of ['requestId', 'workerId', 'type', 'readySha256', 'commandIndex']) {
  test(`wrong RPC ${alteration} fails closed and cannot be retried`, async (t) => {
    const unit = workerFixture(t, { reply: (request, response) => request.type === 'control'
      ? { ...response, [alteration]: alteration === 'commandIndex' ? 999 : 'wrong-unit-value' } : response });
    await unit.prepare();
    await assert.rejects(unit.read());
    assert.equal(unit.worker.killed, 1);
    await assert.rejects(unit.read(), /PREPARE_REQUIRED/);
    assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 1);
  });
}

test('oversized response line is rejected before any evidence can be accepted', async (t) => {
  const unit = workerFixture(t, { reply: (request, response) => request.type === 'control' ? Buffer.alloc(65537, 65) : response });
  await unit.prepare();
  await assert.rejects(unit.read(), /OUTPUT_BOUND/);
  assert.equal(unit.worker.killed, 1);
});

test('changed image is rejected by the per-command inspect before RPC', async (t) => {
  const unit = workerFixture(t);
  await unit.prepare();
  unit.setImage(`sha256:${'f'.repeat(64)}`);
  await assert.rejects(unit.read());
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 0);
  assert.equal(unit.worker.killed, 1);
});

test('sixteen commands retain every response; command seventeen cannot reach the worker', async (t) => {
  const unit = workerFixture(t);
  await unit.prepare();
  for (let index = 0; index < 16; index++) await unit.read();
  await assert.rejects(unit.read(), /COMMAND_BOUND/);
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 16);
  assert.equal(unit.processes.filter(({ args }) => args[0] === 'exec').length, 1);
});

test('concurrent calls cannot overlap and explicit close is idempotent', async (t) => {
  const unit = workerFixture(t);
  await unit.prepare();
  const first = unit.read();
  await assert.rejects(unit.read(), /SINGLE_INFLIGHT/);
  await first;
  await unit.adapter.close();
  await unit.adapter.close();
  assert.equal(unit.requests.filter(({ type }) => type === 'close').length, 1);
  assert.equal(unit.worker.killed, 0);
  await assert.rejects(unit.read(), /PREPARE_REQUIRED/);
});

test('unexpected worker disconnect rejects the inflight request without spawning a replacement', async (t) => {
  const unit = workerFixture(t, { reply: (request, response, process) => {
    if (request.type === 'control') { process.emit('close', 1); return undefined; }
    return response;
  } });
  await unit.prepare();
  await assert.rejects(unit.read(), /DISCONNECTED/);
  assert.equal(unit.processes.filter(({ args }) => args[0] === 'exec').length, 1);
});

test('duplicate response frames poison the worker rather than accepting an ambiguous success', async (t) => {
  const unit = workerFixture(t, { reply: (request, response) => request.type === 'control'
    ? Buffer.from(`${JSON.stringify(response)}\n${JSON.stringify(response)}\n`) : response });
  await unit.prepare();
  await assert.rejects(unit.read(), /DISCONNECTED/);
  assert.equal(unit.worker.killed, 1);
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 1);
});

test('malformed JSON cannot become a successful owner result', async (t) => {
  const unit = workerFixture(t, { reply: (request, response) => request.type === 'control' ? Buffer.from('not-json\n') : response });
  await unit.prepare();
  await assert.rejects(unit.read(), SyntaxError);
  assert.equal(unit.worker.killed, 1);
});

test('changed readiness proof is rejected before a control is dispatched', async (t) => {
  const unit = workerFixture(t), ready = await unit.prepare();
  writeFileSync(ready.evidencePath, 'changed-unit-proof');
  await assert.rejects(unit.read(), /OWNER_EVIDENCE_CHANGED/);
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 0);
  assert.equal(unit.worker.killed, 1);
});

test('short container aliases are refused before any Docker command', async (t) => {
  const unit = workerFixture(t);
  const binding = { ...unit.binding, apiContainerId: 'unit-api-container-alias' };
  const bytes = Buffer.from(JSON.stringify(binding));
  writeFileSync(path.join(unit.root, unit.pointer.file), bytes);
  writeFileSync(path.join(unit.root, 'owner-active.json'), JSON.stringify({ ...unit.pointer,
    sha256: createHash('sha256').update(bytes).digest('hex') }));
  await assert.rejects(unit.prepare(), /IMMUTABLE_OWNER_CONTAINER_ID_REQUIRED/);
  assert.equal(unit.processes.length, 0);
});

test('close during an inflight command rejects it and stops only the owned child', async (t) => {
  const unit = workerFixture(t, { reply: (request, response) => request.type === 'control' ? undefined : response });
  await unit.prepare();
  const rejected = assert.rejects(unit.read(), /OWNER_WORKER_CLOSED/);
  await new Promise(setImmediate);
  await unit.adapter.close();
  await rejected;
  assert.equal(unit.worker.killed, 1);
  assert.ok(unit.processes.filter(({ args }) => args[0] === 'inspect').every(({ killed }) => killed === 0));
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 1);
});

test('stderr overflow also fails closed without retaining an unbounded transcript', async (t) => {
  const unit = workerFixture(t, { reply: (request, response, process) => {
    if (request.type === 'control') { process.stderr.emit('data', Buffer.alloc(65537)); return undefined; }
    return response;
  } });
  await unit.prepare();
  await assert.rejects(unit.read(), /OUTPUT_BOUND/);
  assert.equal(unit.worker.killed, 1);
});

test('readiness proof validation cannot extend the thirty-second preparation budget', async (t) => {
  let clock = 0;
  const unit = workerFixture(t, { now: () => clock, reply: (request, response) => {
    if (request.type === 'prepare') clock = 30001;
    return response;
  } });
  await assert.rejects(unit.prepare(), /READINESS_DEADLINE/);
  assert.equal(unit.worker.killed, 1);
});

test('result evidence validation cannot extend the eight-second operation budget', async (t) => {
  let clock = 0;
  const unit = workerFixture(t, { now: () => clock, reply: (request, response) => {
    if (request.type === 'control') clock = 8001;
    return response;
  } });
  await unit.prepare();
  await assert.rejects(unit.read(), /CONTROL_DEADLINE/);
  assert.equal(unit.worker.killed, 1);
  assert.equal(unit.requests.filter(({ type }) => type === 'control').length, 1);
});
