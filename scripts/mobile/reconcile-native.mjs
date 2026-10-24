import { readFileSync } from 'node:fs';
import { reconcileInventory, reconcileResults } from '../../apps/mobile/e2e/support.mjs';

const inventory = JSON.parse(readFileSync(new URL('../../apps/mobile/e2e/inventory.json', import.meta.url), 'utf8'));
const [platform, file] = process.argv.slice(2);
if (!inventory.platforms.includes(platform) || !file) throw new Error('Usage: reconcile-native.mjs android|ios events.jsonl');
const intended = inventory.cases.map((item) => `${platform}:${item.id}`);
const lines = readFileSync(file, 'utf8').trim().split('\n');
if (lines.length > 2000) throw new Error('JOURNAL_EVENT_BOUND');
const events = lines.map((line) => JSON.parse(line));
reconcileInventory(intended, events.find((event) => event.type === 'run_started')?.discovered || []);
const result = reconcileResults(events, intended);
console.log(JSON.stringify({ platform, ...result }, null, 2));
if (result.status !== 'passed') process.exitCode = 1;
