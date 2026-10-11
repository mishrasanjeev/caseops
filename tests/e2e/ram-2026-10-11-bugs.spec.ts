import { spawnSync } from "node:child_process";
import { expect, test } from "@playwright/test";

import { fixtureProcessEvidence } from "./support/fixture-process";
import { e2eEnv } from "./support/env";
import { requireFixtureDatabaseUrl } from "./support/fixture-database";
import { localTransportHeaders, noPaidProviderHeaders } from "./support/cost-controls";

test("fixture receipt distinguishes a nonzero exit from a timeout", () => {
  const result = spawnSync(process.execPath, ["-e", "process.stderr.write('fixture rejected'); process.exit(7)"], { encoding: "utf8", timeout: 5_000 });
  const evidence = JSON.parse(fixtureProcessEvidence(result, new Date().toISOString(), 10));
  expect(evidence.exit_code).toBe(7);
  expect(evidence.error).toBeNull();
  expect(evidence.signal).toBeNull();
  expect(evidence.stderr).toBe("fixture rejected");
});

test("fixture receipt retains the native timeout code and signal", () => {
  const result = spawnSync(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { encoding: "utf8", timeout: 100 });
  const evidence = JSON.parse(fixtureProcessEvidence(result, new Date().toISOString(), 100));
  expect(evidence.exit_code).toBeNull();
  expect(evidence.error.code).toBe("ETIMEDOUT");
  expect(evidence.signal).toBeTruthy();
});

test("fixture receipt excludes signed tokens without losing failure evidence", () => {
  const result = spawnSync(process.execPath, ["-e", "process.stdout.write('signed-fixture-token'); process.stderr.write('diagnostic');"], { encoding: "utf8", timeout: 5_000 });
  const evidenceText = fixtureProcessEvidence(result, new Date().toISOString(), 10, false);
  const evidence = JSON.parse(evidenceText);
  expect(evidence.exit_code).toBe(0);
  expect(evidence.stdout_bytes).toBe(20);
  expect(evidence.stderr).toBe("diagnostic");
  expect(evidenceText).not.toContain("signed-fixture-token");
});

test("loopback web responses explicitly close completed connections", async ({ request, baseURL }) => {
  const origin = new URL(baseURL!);
  expect(origin.protocol).toBe("http:");
  expect(["127.0.0.1", "localhost", "[::1]"]).toContain(origin.hostname);
  for (let index = 0; index < 3; index++) {
    const response = await request.get("/api/release-identity");
    expect(response.status()).toBe(200);
    expect(response.headers().connection).toBe("close");
    expect((await response.json()).release_sha).toBe(e2eEnv.CASEOPS_RELEASE_SHA);
  }
});

const ownedSqlite = "sqlite+pysqlite:///owned/caseops-e2e.db";
for (const [label, value] of [
  ["host override", "postgresql+psycopg://u:p@127.0.0.1/caseops?host=nonloopback-db"],
  ["hostaddr override", "postgresql+psycopg://u:p@localhost/caseops?hostaddr=203.0.113.1"],
  ["encoded override", "postgresql+psycopg://u:p@127.0.0.1/caseops?%68ost=nonloopback-db"],
  ["port override", "postgresql+psycopg://u:p@127.0.0.1/caseops?port=5432"],
  ["socket override", "postgresql+psycopg://u:p@localhost/caseops?host=/var/run/postgresql"],
  ["nonloopback authority", "postgresql+psycopg://u:p@nonloopback-db/caseops"],
  ["unsupported driver", "postgresql://u:p@127.0.0.1/caseops"],
  ["fragment", "postgresql+psycopg://u:p@127.0.0.1/caseops#override"],
  ["foreign SQLite", "sqlite+pysqlite:///foreign/production.db"],
  ["missing database", "postgresql+psycopg://u:p@127.0.0.1/"],
]) {
  test(`fixture database rejects ${label}`, () => {
    expect(() => requireFixtureDatabaseUrl(value, ownedSqlite)).toThrow();
  });
}

for (const [label, value] of [
  ["IPv4 PostgreSQL", "postgresql+psycopg://u:p@127.0.0.1:25432/caseops"],
  ["IPv6 PostgreSQL", "postgresql+psycopg://u:p@[::1]:25432/caseops"],
  ["owned SQLite", ownedSqlite],
]) {
  test(`fixture database accepts ${label}`, () => {
    expect(() => requireFixtureDatabaseUrl(value, ownedSqlite)).not.toThrow();
  });
}

test("transport header policy is local-only and preserves provider isolation", () => {
  for (const origin of ["http://127.0.0.1:3100", "http://localhost:3100", "http://[::1]:3100"]) {
    expect(localTransportHeaders(origin)).toEqual({ ...noPaidProviderHeaders, Connection: "close" });
  }
  for (const origin of ["https://caseops.ai", "http://public.example", "https://localhost:3100"]) {
    expect(localTransportHeaders(origin)).toEqual(noPaidProviderHeaders);
  }
});

test("fixture database refuses SQLite in Docker acceptance", () => {
  expect(() => requireFixtureDatabaseUrl(ownedSqlite, "")).toThrow();
});

test("fixture database refuses an empty destination when SQLite is disabled", () => {
  expect(() => requireFixtureDatabaseUrl("", "")).toThrow();
});
