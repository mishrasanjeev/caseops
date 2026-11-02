import assert from 'node:assert/strict';

export const v1Inventory = Object.freeze({
  schemaVersion: 3,
  inventoryId: 'native-v1-source-work-2026-10-27-v3',
  platforms: Object.freeze(['android', 'ios']),
  scope: 'Actual source-record and quick-work supplement; independent of core23, Files17, tablet and distribution acceptance',
  cases: Object.freeze([
    ['SOURCE-01', 'Calendar date, week and filter retain exact patent, design and trademark source identity on return'],
    ['SOURCE-02', 'Contract cursor pages and exact scalar detail survive explicit reload and type switching'],
    ['SOURCE-03', 'Nullable contract facts and positive minor units remain truthful; generic IP dates are not inferred'],
    ['SOURCE-04', 'Revoked readiness, denied, missing, offline and malformed source reads discard earlier ready content'],
    ['SOURCE-05', 'Normal sign-out and second-company authentication discard source detail and pagination'],
    ['SOURCE-06', 'An acknowledged ethical wall removes cached IP content and exact normal-API wall revocation restores a fresh read'],
    ['SOURCE-07', 'Recorded obligation pages retain exact parent, responsible person, nullable dates and text after reload and close'],
    ['WORK-01', 'Create one task and verify acknowledged UUID, parent, lifecycle and persisted reload'],
    ['WORK-02', 'Dirty-only task completion and date clearing retain exact before and after record evidence'],
    ['WORK-03', 'Create one hearing with exact legal date and local time and an explicit empty notification plan'],
    ['WORK-04', 'Hearing reschedule and completion use current HMACs and verify the chosen follow-up independently'],
    ['WORK-05', 'Parent close/reopen and child conflict reject stale work without mutation replay'],
    ['WORK-06', 'An unknown save is not replayed; Stay, explicit reload and Leave retain honest outcome history'],
    ['WORK-07', 'A normally authenticated viewer reads current work without native add edit or save authority'],
    ['WORK-08', 'Grant revocation after preflight rejects one stale native PATCH and purges private work without replay'],
    ['COUNSEL-01', 'Independent assignment and spend pages retain exact currency minor units and page-only totals'],
    ['INBOX-01', 'Actual delivered notifications open their source and persist one read dismiss and restore transition each'],
  ].map(([id, title]) => Object.freeze({ id, title }))),
});

export const V1_BUDGETS = Object.freeze({
  serialInventoryMs: 30 * 60 * 1000,
  transportMs: 60000,
  nativeReadMs: 10000,
  nativeTransitionMs: 20000,
  persistedReadMs: 20000,
  pollMs: 200,
  maxScrolls: 9,
  maxControlsPerCase: 160,
  maxAuthoritativeReadsPerCase: 24,
  maxControlCallsPerCase: 24,
  maxContractPages: 2,
  contractPageSize: 25,
});
// These include EVERY transport-level control read, including receipt polls and
// per-case cleanup. One separate final-cleanup operation stays reserved.
export const V1_CASE_CONTROL_LIMITS = Object.freeze({
  'SOURCE-01': 14, 'SOURCE-02': 14, 'SOURCE-03': 14, 'SOURCE-04': 20, 'SOURCE-05': 14, 'SOURCE-06': 14, 'SOURCE-07': 14,
  'WORK-01': 14, 'WORK-02': 14, 'WORK-03': 14, 'WORK-04': 14, 'WORK-05': 20, 'WORK-06': 14, 'WORK-07': 14, 'WORK-08': 18,
  'COUNSEL-01': 14, 'INBOX-01': 14,
});
assert.deepEqual(Object.keys(V1_CASE_CONTROL_LIMITS), v1Inventory.cases.map(record => record.id));
assert.ok(Object.values(V1_CASE_CONTROL_LIMITS).every(limit => limit <= V1_BUDGETS.maxControlCallsPerCase));
assert.ok(Object.values(V1_CASE_CONTROL_LIMITS).reduce((sum, limit) => sum + limit, 1) <= 264);

export function collectV1(platform, scenarios) {
  assert.ok(v1Inventory.platforms.includes(platform), 'SUPPORTED_V1_PLATFORM_REQUIRED');
  assert.ok(Array.isArray(scenarios), 'EXECUTABLE_V1_SCENARIOS_REQUIRED');
  const intended = v1Inventory.cases.map(({ id }) => `${platform}:${id}`);
  const discovered = scenarios.map(({ id, run }) => {
    assert.equal(typeof run, 'function', 'EXECUTABLE_V1_CASE_REQUIRED');
    return `${platform}:${id}`;
  });
  assert.deepEqual(discovered, intended, 'COMPLETE_V1_INVENTORY_REQUIRED');
  return { schemaVersion: 1, inventoryId: v1Inventory.inventoryId, platform, intended, discovered,
    expectedPhases: 51, expectedSessions: 17, nativeExecution: 'not-run' };
}
