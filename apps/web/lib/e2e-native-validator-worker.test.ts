// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

it("executes delayed canonical validators in the real native Playwright worker without network or copied schemas", () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "caseops-validator-worker-"));
  const pw = path.join(root, "node_modules/@playwright/test");
  const helper = path.join(root, "tests/e2e/support/canonical-api-validators.ts");
  const schema = path.join(root, "apps/web/lib/api/schemas.ts");
  writeFileSync(path.join(dir, "playwright.config.cjs"), `module.exports = { testDir: __dirname, testMatch: 'validator.spec.ts', workers: 1, retries: 0, repeatEach: 1, timeout: 5000, reporter: [['json']], outputDir: ${JSON.stringify(path.join(dir, "results"))} };`);
  writeFileSync(path.join(dir, "validator.spec.ts"), `
import { test, expect } from ${JSON.stringify(pw)};
import { canonicalApiValidators } from ${JSON.stringify(helper)};
const schemaPath = require.resolve(${JSON.stringify(schema)});
test('delayed canonical auth and draft contracts reject malformed and accept complete payloads', () => {
  const deny = () => { throw new Error('Network forbidden in the native loader regression'); };
  for (const name of ['node:http', 'node:https']) {
    const transport = require(name); transport.request = deny; transport.get = deny;
  }
  const net = require('node:net'); net.connect = deny; net.createConnection = deny;
  require('node:dns').lookup = deny;
  globalThis.fetch = deny;
  expect(require.cache[schemaPath]).toBeUndefined();
  const loaded = canonicalApiValidators();
  expect(require.cache[schemaPath]).toBeDefined();
  const canonical = require(schemaPath);
  for (const key of ['authContext', 'authSession', 'draft']) expect(loaded[key]).toBe(canonical[key]);
  expect(canonicalApiValidators()).toBe(loaded);
  const actor = {
    company: { id: 'company', name: 'Synthetic', slug: 'synthetic', company_type: 'law_firm', tenant_key: 'tenant', is_active: true, created_at: '2026-11-14' },
    user: { id: 'user', email: 'synthetic@example.invalid', full_name: 'Synthetic', is_active: true, created_at: '2026-11-14' },
    membership: { id: 'member', role: 'owner', is_active: true, created_at: '2026-11-14' },
    capabilities: ['communications:write']
  };
  const draft = { id: 'draft', company_id: 'company', matter_id: null, ip_docket_id: null, ip_proceeding_id: null,
    created_by_membership_id: null, title: 'Synthetic', draft_type: 'memo', status: 'draft', review_required: true,
    current_version_id: null, versions: [], reviews: [], created_at: '2026-11-14', updated_at: '2026-11-14' };
  const payloads = { authContext: actor, authSession: { ...actor, access_token: 'not-a-token', token_type: 'bearer' }, draft };
  for (const key of ['authContext', 'authSession', 'draft']) {
    expect(loaded[key].safeParse(payloads[key]).success).toBe(true);
    for (const value of [null, {}, [], { ...payloads[key], company: null }, { ...payloads[key], versions: [{ id: 1 }] }]) {
      expect(loaded[key].safeParse(value)).toEqual(canonical[key].safeParse(value));
    }
    expect(loaded[key].safeParse(null).success).toBe(false);
    expect(loaded[key].safeParse({}).success).toBe(false);
  }
  expect(loaded.authContext.safeParse({ ...actor, membership: { ...actor.membership, role: 'invented' } }).success).toBe(false);
  expect(loaded.authSession.safeParse({ ...payloads.authSession, token_type: 'invented' }).success).toBe(false);
  expect(loaded.draft.safeParse({ ...draft, review_required: 'yes' }).success).toBe(false);
});
`);
  const env: NodeJS.ProcessEnv = { NODE_ENV: "test", CI: "1", TEMP: dir, TMP: dir };
  for (const key of ["PATH", "Path", "SystemRoot", "WINDIR", "HOME", "USERPROFILE"]) {
    if (process.env[key]) env[key] = process.env[key];
  }
  const result = spawnSync(process.execPath, [path.join(pw, "cli.js"), "test", "--config", path.join(dir, "playwright.config.cjs")],
    { cwd: root, env, encoding: "utf8", windowsHide: true, timeout: 15_000, maxBuffer: 4 * 1024 * 1024 });
  // Retain even incomplete native evidence in this fresh owned diagnostic namespace.
  writeFileSync(path.join(dir, "native.json"), result.stdout ?? "");
  writeFileSync(path.join(dir, "stderr.txt"), result.stderr ?? "");
  expect(result.error, dir).toBeUndefined();
  expect(result.status, result.stderr + dir).toBe(0);
  const report = JSON.parse(readFileSync(path.join(dir, "native.json"), "utf8"));
  expect(report.errors).toEqual([]);
  expect(report.stats).toMatchObject({ expected: 1, unexpected: 0, skipped: 0, flaky: 0 });
  const executed = report.suites.flatMap((suite: { specs?: { tests: { results: { status: string }[] }[] }[] }) => suite.specs ?? [])
    .flatMap((spec: { tests: { results: { status: string }[] }[] }) => spec.tests);
  expect(executed).toHaveLength(1);
  expect(executed[0].results).toHaveLength(1);
  expect(executed[0].results[0].status).toBe("passed");
}, 20_000);
