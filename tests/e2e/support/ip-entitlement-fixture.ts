import { execFile } from "node:child_process";
import path from "node:path";

import { apiBaseUrl, e2eEnv, repoRoot } from "./env";
import { requireFixtureDatabaseUrl } from "./fixture-database";

const deadlineMs = 10_000;
const maxOutputBytes = 8_192;
const stages = new Set(["validate", "driver", "connect", "scope", "insert", "commit", "close", "complete"]);
const successEvents = ["validate", "driver", "connect", "scope", "insert", "commit", "close"]
  .flatMap((stage) => [`${stage}:begin`, `${stage}:end`]).concat("complete:end");

export type IpFixtureScope = {
  company_id: string;
  membership_id: string;
  user_id: string;
  slug: string;
  email: string;
};

export function requireLocalIpFixtureTarget(): void {
  if (process.env.PROD_API_BASE_URL || process.env.PROD_BASE_URL) {
    throw new Error("Synthetic IP entitlement fixtures cannot use production configuration.");
  }
  for (const value of [apiBaseUrl, e2eEnv.CASEOPS_PUBLIC_APP_URL]) {
    let origin: URL;
    try { origin = new URL(value); } catch {
      throw new Error("Synthetic IP entitlement fixture origin is invalid.");
    }
    if (origin.protocol !== "http:" || origin.username || origin.password
      || !["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname)
      || origin.pathname !== "/" || origin.search || origin.hash) {
      throw new Error("Synthetic IP entitlement fixtures require loopback HTTP origins.");
    }
  }
  if (Object.keys(process.env).some((key) => key.toUpperCase().startsWith("PG"))) {
    throw new Error("Synthetic IP entitlement fixtures reject ambient libpq overrides.");
  }
  const ownedSqlite = process.env.CASEOPS_E2E_DOCKER_PROJECT ? ""
    : "sqlite+pysqlite:///" + path.join(repoRoot, "caseops-e2e.db").replace(/\\/g, "/");
  requireFixtureDatabaseUrl(e2eEnv.CASEOPS_DATABASE_URL, ownedSqlite);
}

export async function grantIpEntitlement(scope: IpFixtureScope): Promise<void> {
  requireLocalIpFixtureTarget();
  const input = JSON.stringify(scope);
  if (Buffer.byteLength(input, "utf8") > 4_096) {
    throw new Error("Synthetic IP entitlement scope exceeds its input bound.");
  }
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(
    repoRoot, "apps", "api", ".venv", process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  const env: NodeJS.ProcessEnv = {
    CASEOPS_ENV: "e2e",
    CASEOPS_DATABASE_URL: e2eEnv.CASEOPS_DATABASE_URL,
    CASEOPS_E2E_DOCKER_PROJECT: process.env.CASEOPS_E2E_DOCKER_PROJECT || "",
  };
  for (const key of ["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"]) {
    if (process.env[key] !== undefined) env[key] = process.env[key];
  }
  const started = performance.now();
  process.stdout.write(JSON.stringify({ fixture: "ip-entitlement", stage: "spawn", elapsed_ms: 0 }) + "\n");
  await new Promise<void>((resolve, reject) => {
    let pending = "";
    let lastStage = "spawn";
    let eventCount = 0;
    let protocolFailed = false;
    let complete = false;
    let scriptFailed = false;
    let stdinFailed = false;
    let stderrFailed = false;
    let closed = false;
    let previousElapsed = 0;
    let outcome: { error: (Error & { killed?: boolean }) | null; stderr: string } | undefined;
    const finish = () => {
      if (!closed || !outcome) return;
      process.removeListener("exit", reap);
      const elapsedMs = Math.round(performance.now() - started);
      process.stdout.write(JSON.stringify({ fixture: "ip-entitlement", stage: "reaped", elapsed_ms: elapsedMs }) + "\n");
      if (outcome.error || protocolFailed || scriptFailed || stdinFailed || stderrFailed
        || pending || !complete || outcome.stderr.length) {
        const failure = protocolFailed ? "protocol" : outcome.error?.killed ? "terminated"
          : scriptFailed ? "script" : "process";
        reject(new Error(`IP entitlement fixture failed (${failure}; stage=${lastStage}; elapsed_ms=${elapsedMs}). No retry performed.`));
      } else {
        resolve();
      }
    };
    const child = execFile(python, [
      "-I", "-B", "-u", path.join(repoRoot, "tests", "e2e", "support", "ip_entitlement_fixture.py"),
    ], {
      cwd: repoRoot,
      env,
      encoding: "utf8",
      shell: false,
      windowsHide: true,
      timeout: deadlineMs,
      killSignal: "SIGKILL",
      maxBuffer: maxOutputBytes,
    }, (error, _stdout, stderr) => {
      // Spawn errors can invoke this callback before the child's close event.
      // Never retain or expose Error.message/stdout/stderr beyond this check.
      outcome = { error, stderr: stderr.length ? "unexpected" : "" };
      finish();
    });
    // This Python script spawns no descendants. Await execFile's close callback,
    // including after a hard deadline kill, before settling the fixture promise.
    const reap = () => { child.kill("SIGKILL"); };
    process.once("exit", reap);
    child.once("close", () => { closed = true; finish(); });
    child.stderr?.on("data", () => { stderrFailed = true; child.kill("SIGKILL"); });
    child.stdout?.on("data", (chunk: string | Buffer) => {
      if (protocolFailed) return;
      pending += chunk.toString();
      const lines = pending.split("\n");
      pending = lines.pop()!;
      try {
        if (pending.length > 512) throw new Error("protocol");
        for (const line of lines) {
          const item = JSON.parse(line);
          if (++eventCount > 24 || line.length > 512 || item === null || Array.isArray(item)
            || typeof item !== "object" || Object.keys(item).sort().join(",") !== "duration_ms,elapsed_ms,event,stage"
            || !stages.has(item.stage) || !["begin", "end", "failed"].includes(item.event)
            || !Number.isInteger(item.elapsed_ms) || item.elapsed_ms < previousElapsed || item.elapsed_ms > 60_000
            || !Number.isInteger(item.duration_ms) || item.duration_ms < 0 || item.duration_ms > 60_000
            || item.duration_ms > item.elapsed_ms
            || complete) throw new Error("protocol");
          if (!scriptFailed) {
            const expected = successEvents[eventCount - 1];
            if (item.event === "failed") {
              if (expected !== `${item.stage}:end`) throw new Error("protocol");
            } else if (expected !== `${item.stage}:${item.event}`) throw new Error("protocol");
          } else if (item.stage !== "close") throw new Error("protocol");
          lastStage = item.stage;
          previousElapsed = item.elapsed_ms;
          scriptFailed ||= item.event === "failed";
          complete = item.stage === "complete" && item.event === "end";
          process.stdout.write(JSON.stringify({ fixture: "ip-entitlement", ...item }) + "\n");
        }
      } catch {
        protocolFailed = true;
        child.kill("SIGKILL");
      }
    });
    child.stdin?.on("error", () => { stdinFailed = true; });
    child.stdin?.end(input);
  });
}
