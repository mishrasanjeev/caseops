// A separate physical process bounds synchronous regex execution.
const fs = require('node:fs');
const { performance } = require('node:perf_hooks');
const picomatch = require(process.argv[2]);
const pattern = process.argv[3];
const subject = process.argv[4];
const matcher = picomatch(pattern);
fs.writeSync(1, JSON.stringify({ stage: 'ready', pattern, length: subject.length }) + '\n');
// Parent admission separates the inherited trust bootstrap/compilation from
// the unchanged one-second matching budget. No match runs before this byte.
const trigger = Buffer.alloc(2);
if (fs.readSync(0, trigger, 0, 2, null) !== 1 || trigger[0] !== 77) {
  throw new Error('PICOMATCH_PROBE_TRIGGER_REQUIRED');
}
fs.writeSync(1, JSON.stringify({ stage: 'matching' }) + '\n');
const started = performance.now();
const matched = matcher(subject);
fs.writeSync(1, JSON.stringify({ stage: 'result', matched,
  elapsedMs: performance.now() - started, source: picomatch.makeRe(pattern).source }) + '\n');
