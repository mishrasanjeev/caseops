import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const operations = new Set(['disposeMatter', 'readMatterState', 'revokeMatterAccess', 'readNoteState']);
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');
function checked(file, sha256) {
  assert.ok(path.isAbsolute(file) && statSync(file).isFile() && statSync(file).size <= 1048576, 'BOUNDED_OWNER_EVIDENCE_REQUIRED');
  const bytes = readFileSync(file);
  assert.equal(hash(bytes), sha256, 'OWNER_EVIDENCE_CHANGED');
  return bytes;
}
function command(args, input, signal, deadline) {
  return new Promise((resolve, reject) => {
    const child = spawn('docker', args, { windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'pipe'] });
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
    const timer = setTimeout(() => stop(new Error('OWNER_CONTROL_DEADLINE')), Math.max(1, deadline - Date.now()));
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

export async function control({ operation, targetId, runId, backendSha, marker, signal }) {
  assert.ok(operations.has(operation), 'UNSUPPORTED_OWNER_OPERATION');
  for (const value of [targetId, runId]) assert.match(value || '', /^[a-zA-Z0-9_-]{1,100}$/, 'OWNER_IDENTITY_REQUIRED');
  assert.match(backendSha || '', /^[a-f0-9]{40}$/, 'EXACT_OWNER_BACKEND_REQUIRED');
  assert.equal(marker, 'no-paid-providers', 'OWNER_MARKER_REQUIRED');
  assert.ok(signal instanceof AbortSignal && !signal.aborted, 'OWNER_ABORT_SIGNAL_REQUIRED');
  const deadline = Date.now() + 8000;
  const cache = path.resolve(process.env.CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE || path.join(os.homedir(), '.cache/caseops-mobile/local-docker-20261025'));
  const pointer = JSON.parse(readFileSync(path.join(cache, 'owner-active.json'), 'utf8'));
  assert.match(pointer.file || '', /^owner-binding-[a-zA-Z0-9_-]+\.json$/);
  const binding = JSON.parse(checked(path.join(cache, pointer.file), pointer.sha256));
  const extension = JSON.parse(checked(path.join(cache, binding.extensionFile), binding.extensionSha256));
  checked(binding.pythonPath, binding.pythonSha256);
  assert.equal(binding.environment, 'docker-integration');
  assert.equal(binding.syntheticDataOnly, true);
  assert.equal(binding.backendSha, backendSha, 'OWNER_RELEASE_CHANGED_REBIND_REQUIRED');
  const kind = ['disposeMatter', 'readMatterState'].includes(operation) ? 'lifecycleMatter' : 'accessMatter';
  assert.equal(extension[kind].id, targetId, 'UNOWNED_OWNER_TARGET');
  const inspected = JSON.parse(await command(['inspect', binding.apiContainerId], '', signal, deadline))[0];
  assert.equal(inspected.Id, binding.apiContainerId);
  assert.equal(inspected.Image, binding.apiImage);
  assert.equal(inspected.Config.Labels['com.docker.compose.project'], binding.project);
  assert.equal(inspected.Config.Labels['com.docker.compose.service'], 'api');
  assert.equal(inspected.State.Running, true);
  const requestId = randomBytes(12).toString('hex');
  const output = await command(['exec', '-i', binding.apiContainerId, 'python', '/mobile-fixture/local-owner.py'],
    JSON.stringify({ operation, targetId, runId, backendSha, marker, requestId, deadlineMs: deadline,
      bindingFile: pointer.file, bindingSha256: pointer.sha256 }), signal, deadline);
  const response = JSON.parse(output);
  assert.equal(response.evidenceFile, `owner-evidence-${requestId}.json`);
  const evidencePath = path.join(cache, response.evidenceFile);
  const bytes = readFileSync(evidencePath);
  assert.ok(bytes.length <= 65536);
  const evidence = JSON.parse(bytes);
  for (const [key, value] of Object.entries({ operation, targetId, runId, backendSha, requestId })) assert.equal(evidence[key], value);
  assert.deepEqual(evidence.result, response.result);
  return { kind: 'docker-owner-control', operation, targetId, runId, backendSha,
    evidencePath, evidenceSha256: hash(bytes), result: evidence.result };
}
