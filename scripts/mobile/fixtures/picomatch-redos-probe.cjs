// A separate physical process bounds synchronous regex execution.
const fs = require('node:fs');
const { performance } = require('node:perf_hooks');
const picomatch = require(process.argv[2]);
const pattern = process.argv[3];
const operation = process.argv[5] ?? 'match';
if (!['match', 'remove-backslashes', 'scan-unescape'].includes(operation)) throw new Error('PICOMATCH_PROBE_OPERATION_REQUIRED');
const count = Number(process.argv[4]);
if (operation !== 'match' && (!Number.isSafeInteger(count) || count < 1 || count > 200000)) {
  throw new Error('PICOMATCH_PROBE_COUNT_REQUIRED');
}
const subject = operation === 'match' ? process.argv[4] : '['.repeat(count) + '\\x';
const matcher = operation === 'match' ? picomatch(pattern)
  : operation === 'remove-backslashes' ? require(process.argv[2] + '/lib/utils.js').removeBackslashes
    : input => picomatch.scan(input, { unescape: true }).base;
fs.writeSync(1, JSON.stringify({ stage: 'ready', pattern, length: subject.length }) + '\n');
// Parent admission separates the inherited trust bootstrap/compilation from
// the unchanged one-second matching budget. No match runs before this byte.
const trigger = Buffer.alloc(2);
if (fs.readSync(0, trigger, 0, 2, null) !== 1 || trigger[0] !== 77) {
  throw new Error('PICOMATCH_PROBE_TRIGGER_REQUIRED');
}
fs.writeSync(1, JSON.stringify({ stage: 'matching' }) + '\n');
const started = performance.now();
const output = matcher(subject);
const matched = operation === 'match' ? output : output === '['.repeat(count) + 'x';
fs.writeSync(1, JSON.stringify({ stage: 'result', matched,
  elapsedMs: performance.now() - started,
  source: operation === 'match' ? picomatch.makeRe(pattern).source : operation }) + '\n');
