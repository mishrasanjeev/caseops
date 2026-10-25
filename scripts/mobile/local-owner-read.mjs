import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { control } from './local-owner-controls.mjs';

const cache = path.resolve(process.env.CASEOPS_MOBILE_LOCAL_FIXTURE_CACHE || path.join(os.homedir(), '.cache/caseops-mobile/local-docker-20261025'));
const pointer = JSON.parse(readFileSync(path.join(cache, 'extended-current.json'), 'utf8'));
const fixture = JSON.parse(readFileSync(path.join(cache, pointer.file), 'utf8'));
const bindingPointer = JSON.parse(readFileSync(path.join(cache, 'owner-active.json'), 'utf8'));
const binding = JSON.parse(readFileSync(path.join(cache, bindingPointer.file), 'utf8'));
const results = [];
for (const [operation, key] of [['readMatterState', 'lifecycleMatter'], ['readNoteState', 'accessMatter']]) {
  const receipt = await control({ operation, targetId: fixture[key].id, runId: `readonly-preflight-${Date.now()}`,
    backendSha: binding.backendSha, marker: 'no-paid-providers', signal: AbortSignal.timeout(10000) });
  assert.equal(receipt.result.status, 'intake');
  assert.equal(receipt.result.isActive, true);
  assert.equal(receipt.result.lifecycleVersion, 0);
  assert.deepEqual(receipt.result.noteIds, []);
  results.push(receipt);
}
process.stdout.write(JSON.stringify({ readOnly: true, destructiveControlsExecuted: false, results }, null, 2) + '\n');
