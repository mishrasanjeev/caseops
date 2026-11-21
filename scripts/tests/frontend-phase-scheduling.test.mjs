import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import test from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const cli = path.join(root, 'node_modules/vitest/vitest.mjs');
const config = pathToFileURL(path.join(root, 'apps/web/vitest.config.ts')).href;
const vitest = pathToFileURL(path.join(root, 'node_modules/vitest/dist/index.js')).href;

test('actual frontend discovery and workers keep both native phases exclusive', { timeout: 60_000 }, () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'co-phases-'));
  const retained = path.join(root, 'test-results/frontend-scheduling', path.basename(dir));
  mkdirSync(retained, { recursive: true });
  const marker = path.join(dir, 'phases.jsonl');
  const files = [
    ['lib/prod-tester-source-inventory.test.ts', 'source'],
    ['lib/e2e-external-journey-loading.test.ts', 'native'],
    ['components/first.test.ts', 'first'],
    ['components/second.test.ts', 'second'],
  ];
  for (const [file, phase] of files) {
    const target = path.join(dir, file);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, `import { it, expect } from ${JSON.stringify(vitest)};
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
const marker = ${JSON.stringify(marker)};
it(${JSON.stringify(phase)}, () => {
  const prior = existsSync(marker) ? readFileSync(marker, 'utf8').trim().split('\\n') : [];
  if (${JSON.stringify(phase)} === 'source') expect(prior).toEqual([]);
  else if (${JSON.stringify(phase)} === 'native') expect(prior).toEqual(['source']);
  else expect(prior.slice(0, 2)).toEqual(['source', 'native']);
  appendFileSync(marker, ${JSON.stringify(phase + '\n')});
});
`);
  }
  for (const pooled of [false, true]) {
    const name = pooled ? 'pooled-control' : 'candidate';
    writeFileSync(path.join(dir, name + '.config.ts'), `import base from ${JSON.stringify(config)};
const projects = base.test.projects.map(project => ({ ...project, test: { ...project.test } }));
if (${pooled}) {
  const index = projects.findIndex(project => project.test.name === 'native-libraries');
  if (index < 0) throw new Error('CONTROL_REQUIRES_NATIVE_PHASE');
  projects.splice(index, 1);
  const web = projects.find(project => project.test.name === 'web');
  web.test.exclude = web.test.exclude.filter(value => value !== 'lib/e2e-external-journey-loading.test.ts');
}
export default { ...base, root: ${JSON.stringify(dir)}, test: { ...base.test,
  environment: 'node', setupFiles: [], coverage: { ...base.test.coverage, enabled: false },
  projects, testTimeout: 5000, reporters: ['json'] } };
`);
    const listFile = path.join(retained, name + '-files.json');
    const run = spawnSync(process.execPath, [cli, 'list', '--config', path.join(dir, name + '.config.ts'),
      '--filesOnly', '--json=' + listFile], {
      cwd: root, env: { ...process.env, CI: '1', NPM_CONFIG_OFFLINE: 'true' },
      encoding: 'utf8', windowsHide: true, timeout: 15_000, maxBuffer: 1024 * 1024,
    });
    writeFileSync(path.join(retained, name + '-list-transport.json'), JSON.stringify({ status: run.status,
      signal: run.signal, error: run.error?.message, stdout: run.stdout, stderr: run.stderr }));
    assert.equal(run.error, undefined, name);
    assert.equal(run.status, 0, run.stderr);
    const rows = JSON.parse(readFileSync(listFile, 'utf8')).map(row => ({
      file: path.relative(dir, row.file).replaceAll('\\', '/'), project: row.projectName,
    })).sort((a, b) => a.file.localeCompare(b.file));
    const expected = files.map(([file, phase]) => ({ file,
      project: phase === 'source' ? 'source-inventory' : phase === 'native' ? 'native-libraries' : 'web',
    })).sort((a, b) => a.file.localeCompare(b.file));
    if (pooled) {
      assert.deepEqual(rows.map(row => row.file), expected.map(row => row.file));
      assert.throws(() => assert.deepEqual(rows, expected), assert.AssertionError);
      assert.equal(rows.find(row => row.file.endsWith('/e2e-external-journey-loading.test.ts')).project, 'web');
    } else assert.deepEqual(rows, expected);
  }
  const nativeFile = path.join(retained, 'native.json');
  const run = spawnSync(process.execPath, [cli, 'run', '--config', path.join(dir, 'candidate.config.ts'),
    '--reporter=json', '--outputFile=' + nativeFile], {
    cwd: root, env: { ...process.env, CI: '1', NPM_CONFIG_OFFLINE: 'true' },
    encoding: 'utf8', windowsHide: true, timeout: 15_000, maxBuffer: 1024 * 1024,
  });
  writeFileSync(path.join(retained, 'run-transport.json'), JSON.stringify({ status: run.status,
    signal: run.signal, error: run.error?.message, stdout: run.stdout, stderr: run.stderr }));
  assert.equal(run.error, undefined);
  assert.equal(run.status, 0, run.stderr + run.stdout);
  const native = JSON.parse(readFileSync(nativeFile, 'utf8'));
  assert.equal(native.success, true);
  assert.equal(native.numTotalTests, 4);
  assert.equal(native.numPassedTests, 4);
  for (const key of ['numFailedTests', 'numPendingTests', 'numTodoTests']) assert.equal(native[key], 0);
  assert.equal(native.testResults.length, 4);
  const byFile = new Map(native.testResults.map(file => [path.relative(dir, file.name).replaceAll('\\', '/'), file]));
  assert.deepEqual([...byFile.keys()].sort(), files.map(([file]) => file).sort());
  for (const file of native.testResults) {
    assert.equal(file.assertionResults.length, 1);
    assert.equal(file.assertionResults[0].status, 'passed');
  }
  const source = byFile.get(files[0][0]), libraries = byFile.get(files[1][0]);
  assert.ok(source.endTime <= libraries.startTime);
  for (const [file] of files.slice(2)) assert.ok(libraries.endTime <= byFile.get(file).startTime);
});
