import assert from 'node:assert/strict';
import test from 'node:test';
import { control } from './local-owner-controls.mjs';

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
