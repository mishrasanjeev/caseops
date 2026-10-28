import assert from "node:assert/strict";
import { execFile as realExecFile, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

const sourceRoot = process.env.CASEOPS_IP_FIXTURE_SOURCE_ROOT || path.resolve(__dirname, "../../..");
const scratchRoot = process.env.CASEOPS_IP_FIXTURE_SCRATCH_ROOT!;
const python = process.env.CASEOPS_E2E_PYTHON!;
assert.ok(sourceRoot && scratchRoot && python, "Explicit source, scratch and Python paths are required.");
const helperPath = path.join(process.env.CASEOPS_IP_FIXTURE_SUPPORT_ROOT || path.join(sourceRoot, "tests/e2e/support"), "ip-entitlement-fixture.ts");
const scope = { company_id: "11111111-1111-4111-8111-111111111111",
  membership_id: "22222222-2222-4222-8222-222222222222", user_id: "33333333-3333-4333-8333-333333333333",
  slug: "intelligent-review-1793200000000-abcde", email: "owner-intelligent-review-1793200000000-abcde@example.com" };
const stageNames = ["validate", "driver", "connect", "scope", "insert", "commit", "close"];
const successPython = `
for name in ${JSON.stringify(stageNames)}:
    emit(name, 'begin')
    emit(name, 'end')
emit('complete', 'end')
`;
const prelude = `
import json, os, signal, sys, time
from pathlib import Path
root = Path(__file__).absolute().parents[3]
scope = json.load(sys.stdin)
started = time.monotonic()
def emit(stage, event):
    print(json.dumps(dict(stage=stage, event=event, elapsed_ms=int((time.monotonic()-started)*1000), duration_ms=0)), flush=True)
`;

function compile(file: string, dependencies: Record<string, unknown>, globals: Record<string, unknown> = {}) {
  const output = ts.transpileModule(readFileSync(file, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true,
  } }).outputText;
  const module = { exports: {} as Record<string, unknown> };
  vm.runInNewContext(output, { module, exports: module.exports, Buffer, URL, performance,
    require: (id: string) => Object.hasOwn(dependencies, id) ? dependencies[id] : require(id), ...globals }, { filename: file });
  return module.exports;
}

function fixture(body: string, overrides: Record<string, string> = {}, injectStdinError = false) {
  const root = mkdtempSync(path.join(scratchRoot, "ip fixture "));
  const script = path.join(root, "tests/e2e/support/ip_entitlement_fixture.py");
  mkdirSync(path.dirname(script), { recursive: true });
  writeFileSync(script, prelude + body, "utf8");
  const children: Array<{ child: ChildProcess; closed: boolean; error: boolean; timeout: number; argv: string[] }> = [];
  const logs: string[] = [];
  const environment = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("PG")));
  delete environment.PROD_BASE_URL; delete environment.PROD_API_BASE_URL;
  delete environment.CASEOPS_E2E_DOCKER_PROJECT;
  Object.assign(environment, { CASEOPS_E2E_PYTHON: python, PRIVATE_PROVIDER_SECRET: "must-not-forward",
    PYTHONPATH: "must-not-import-this", ...overrides });
  const guard = compile(path.join(sourceRoot, "tests/e2e/support/fixture-database.ts"), {});
  const wrappedExecFile = (file: string, args: string[], options: any, callback: any) => {
    const child = realExecFile(file, args, options, callback);
    const record = { child, closed: false, error: false, timeout: options.timeout as number, argv: Array.from(args) };
    children.push(record);
    child.once("close", () => { record.closed = true; });
    child.once("error", () => { record.error = true; });
    if (injectStdinError) queueMicrotask(() => child.stdin?.emit("error", new Error("secret-password")));
    assert.equal(options.timeout, 10_000);
    assert.equal(options.killSignal, "SIGKILL");
    assert.equal(options.shell, false);
    assert.equal(options.windowsHide, true);
    assert.equal(options.env.PRIVATE_PROVIDER_SECRET, undefined);
    assert.equal(options.env.PYTHONPATH, undefined);
    return child;
  };
  const helper = compile(helperPath, { "./env": {
    repoRoot: root, apiBaseUrl: "http://127.0.0.1:18000", e2eEnv: {
      CASEOPS_PUBLIC_APP_URL: "http://127.0.0.1:13100",
      CASEOPS_DATABASE_URL: "sqlite+pysqlite:///" + path.join(root, "caseops-e2e.db").replace(/\\/g, "/"),
    },
  }, "./fixture-database": guard, "node:child_process": { execFile: wrappedExecFile } }, {
    process: { platform: process.platform, env: environment,
      once: process.once.bind(process), removeListener: process.removeListener.bind(process),
      stdout: { write: (value: string) => { logs.push(value); return true; } } },
  }) as { grantIpEntitlement: (value: typeof scope) => Promise<void> };
  const listenerCount = process.listenerCount("exit");
  return { root, script, children, logs, run: () => helper.grantIpEntitlement(scope),
    cleanup: async () => {
      for (const entry of children) {
        if (!entry.closed) {
          await new Promise<void>((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error("Owned child cleanup did not observe close.")), 1_000);
            entry.child.once("close", () => { clearTimeout(timeout); resolve(); });
            entry.child.kill("SIGKILL");
          });
        }
      }
      assert.equal(process.listenerCount("exit"), listenerCount, "Fixture leaked its exit hook.");
      assert.equal(path.dirname(root), path.resolve(scratchRoot));
      rmSync(root, { recursive: true, force: true });
    } };
}

async function assertFailure(f: ReturnType<typeof fixture>) {
  let error: unknown;
  try { await f.run(); } catch (caught) { error = caught; }
  assert.ok(error, "The invalid child was accepted.");
  assert.equal(f.children.length, 1, "No retries or replacement children are permitted.");
  assert.equal(f.children[0].closed, true, "Promise settled before the observed close event.");
  assert.doesNotMatch(String(error) + f.logs.join(""), /secret-password|postgresql:\/\/|PRIVATE_PROVIDER_SECRET/);
  return error;
}

test("full helper is asynchronous, preserves Windows argv, and accepts ordered complete evidence", async () => {
  const f = fixture("time.sleep(0.35)\n" + successPython);
  let ticks = 0;
  const timer = setInterval(() => { ticks++; }, 25);
  try {
    await f.run();
    assert.ok(ticks >= 3, "Parent event loop did not progress while the child was pending.");
    assert.equal(f.children.length, 1);
    assert.equal(f.children[0].closed, true);
    assert.deepEqual(f.children[0].argv, ["-I", "-B", "-u", f.script]);
    const events = f.logs.map((line) => JSON.parse(line));
    assert.equal(events[0].stage, "spawn");
    assert.equal(events.at(-1).stage, "reaped");
    assert.deepEqual(events.slice(1, -1).map((event) => `${event.stage}:${event.event}`),
      stageNames.flatMap((stage) => [`${stage}:begin`, `${stage}:end`]).concat("complete:end"));
  } finally { clearInterval(timer); await f.cleanup(); }
});

test("selected venv still exposes psycopg under -I without PYTHONPATH or API imports", async () => {
  const body = `
for name in ${JSON.stringify(stageNames)}:
    emit(name, 'begin')
    if name == 'driver':
        import psycopg
        proof = dict(isolated=sys.flags.isolated, executable=sys.executable, prefix=sys.prefix,
                     base_prefix=sys.base_prefix, driver=psycopg.__file__, argv=sys.argv,
                     api_imported=any(k == 'caseops_api' or k.startswith('caseops_api.') for k in sys.modules))
        (root / 'venv-proof.json').write_text(json.dumps(proof), encoding='utf-8')
    emit(name, 'end')
emit('complete', 'end')
`;
  const f = fixture(body);
  try {
    await f.run();
    const proof = JSON.parse(readFileSync(path.join(f.root, "venv-proof.json"), "utf8"));
    const normalize = (value: string) => process.platform === "win32" ? path.resolve(value).toLowerCase() : path.resolve(value);
    assert.equal(proof.isolated, 1);
    assert.equal(normalize(proof.executable), normalize(python));
    assert.equal(normalize(proof.argv[0]), normalize(f.script));
    assert.notEqual(normalize(proof.prefix), normalize(proof.base_prefix), "The selected Python is not a venv interpreter.");
    const relativeDriver = path.relative(normalize(proof.prefix), normalize(proof.driver));
    assert.ok(relativeDriver && !path.isAbsolute(relativeDriver) && relativeDriver !== ".."
      && !relativeDriver.startsWith(".." + path.sep), "psycopg came from outside the selected venv.");
    assert.equal(proof.api_imported, false);
  } finally { await f.cleanup(); }
});

const invalid = [
  ["complete without stages", "emit('complete', 'end')"],
  ["out-of-order", "emit('driver', 'begin')"],
  ["duplicate begin", "emit('validate', 'begin'); emit('validate', 'begin')"],
  ["failed stage", "emit('validate', 'begin'); emit('validate', 'failed')"],
  ["missing completion", "emit('validate', 'begin'); emit('validate', 'end')"],
  ["malformed", "print('not-json', flush=True)"],
  ["partial", "sys.stdout.write('{'); sys.stdout.flush()"],
  ["secret field", "print(json.dumps(dict(event='begin',stage='validate',elapsed_ms=0,duration_ms=0,dsn='postgresql://secret-password')),flush=True)"],
  ["oversized line", "print('x'*9000, flush=True)"],
  ["negative time", "print(json.dumps(dict(event='begin',stage='validate',elapsed_ms=-1,duration_ms=0)),flush=True)"],
  ["trailing event", successPython + "emit('close','begin')"],
  ["nonzero after complete", successPython + "sys.exit(4)"],
];
for (const [name, body] of invalid) {
  test(`rejects ${name} and observes close before rejection`, async () => {
    const f = fixture(body);
    try { await assertFailure(f); } finally { await f.cleanup(); }
  });
}

test("unexpected stderr is sanitized, kills the child, and awaits close", async () => {
  const f = fixture("sys.stderr.write('postgresql://secret-password'); sys.stderr.flush(); time.sleep(30)");
  try { await assertFailure(f); } finally { await f.cleanup(); }
});

test("spawn error waits for close, sanitizes failure, and removes the exit listener", async () => {
  const f = fixture(successPython, { CASEOPS_E2E_PYTHON: path.join(scratchRoot, "missing-secret-password.exe") });
  try {
    await assertFailure(f);
    assert.equal(f.children[0].error, true);
    assert.equal(f.children[0].child.pid, undefined);
  } finally { await f.cleanup(); }
});

test("stdin errors cannot be swallowed behind an otherwise complete child protocol", async () => {
  const f = fixture(successPython, {}, true);
  try { await assertFailure(f); } finally { await f.cleanup(); }
});

test("10-second deadline force-kills and reaps without retry or a late write", { timeout: 15_000 }, async () => {
  const f = fixture(`
if os.name != 'nt': signal.signal(signal.SIGTERM, signal.SIG_IGN)
(root / 'pid.txt').write_text(str(os.getpid()), encoding='ascii')
time.sleep(11)
(root / 'late-write.txt').write_text('must not exist', encoding='ascii')
time.sleep(30)
`);
  let ticks = 0;
  const timer = setInterval(() => { ticks++; }, 25);
  const started = performance.now();
  try {
    await assertFailure(f);
    const elapsed = performance.now() - started;
    assert.ok(elapsed >= 9_500 && elapsed < 12_000, `Unexpected deadline duration: ${elapsed}`);
    assert.ok(ticks > 10, "Deadline blocked the parent event loop.");
    const pid = Number(readFileSync(path.join(f.root, "pid.txt"), "ascii"));
    let alive = true;
    try { process.kill(pid, 0); } catch (error) {
      assert.equal((error as NodeJS.ErrnoException).code, "ESRCH"); alive = false;
    }
    assert.equal(alive, false, "Child PID is still present after promise rejection.");
    await delay(1_500);
    assert.equal(existsSync(path.join(f.root, "late-write.txt")), false);
  } finally { clearInterval(timer); await f.cleanup(); }
});
