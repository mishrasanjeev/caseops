import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { scenarios } from './journeys.mjs';
import { reconcileInventory } from './support.mjs';

export const inventory = JSON.parse(readFileSync(new URL('./core-20261025.json', import.meta.url), 'utf8'));
export const historicalInventory = JSON.parse(readFileSync(new URL('./inventory.json', import.meta.url), 'utf8'));
export function collect(platform) {
  assert.ok(inventory.platforms.includes(platform), 'NATIVE_PLATFORM_REQUIRED');
  const intended = inventory.cases.map((item) => `${platform}:${item.id}`);
  const discovered = scenarios.map((item) => `${platform}:${item.id}`);
  reconcileInventory(intended, discovered);
  for (let index = 0; index < scenarios.length; index++) {
    const dependency = scenarios[index].signedOutAfter;
    assert.equal(dependency, inventory.cases[index].signedOutAfter, 'SCENARIO_AUTH_STATE_CONTRACT_MISMATCH');
    if (dependency) assert.ok(scenarios.slice(0, index).some(({ id }) => id === dependency), 'SCENARIO_DEPENDENCY_MUST_PRECEDE_CASE');
  }
  return { platform, inventoryId: inventory.inventoryId, scope: inventory.scope, intended, discovered };
}
export function receiptInventory(start, platform) {
  assert.ok(inventory.platforms.includes(platform), 'NATIVE_PLATFORM_REQUIRED');
  assert.equal(start?.platform, platform, 'RECEIPT_PLATFORM_MISMATCH');
  if (start.inventoryId === inventory.inventoryId) return inventory;
  assert.equal(start.inventoryId, undefined, 'UNKNOWN_NATIVE_RECEIPT_INVENTORY');
  assert.equal(start.scope, historicalInventory.scope, 'UNRECOGNIZED_HISTORICAL_SCOPE');
  return historicalInventory;
}
export function harnessFingerprint() {
  const files = readdirSync(fileURLToPath(new URL('./', import.meta.url))).filter((file) => /\.(mjs|json)$/.test(file)).sort();
  const hash = createHash('sha256');
  for (const file of [...files, '../../../scripts/mobile/run-native.mjs', '../../../scripts/mobile/reconcile-native.mjs', '../../../scripts/mobile/source-snapshot.mjs']) {
    const bytes = readFileSync(new URL(file, import.meta.url));
    hash.update(`${file}\0${bytes.length}\0`).update(bytes);
  }
  return hash.digest('hex');
}
