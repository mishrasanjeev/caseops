import { spawnSync, type SpawnSyncReturns } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { expect, test } from "@playwright/test";

import {
  DRIVE_ISOLATION_UNIT_NAMES, FIXTURE_EVIDENCE_MAX_BYTES,
  fixtureProcessEvidence, persistFixtureProcessEvidence,
} from "./support/fixture-process";
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

test("resolved browser headers retain the authoritative no-paid marker", ({}, testInfo) => {
  const headers = testInfo.project.use.extraHTTPHeaders;
  expect(headers?.["X-CaseOps-Automated-Test"]).toBe("no-paid-providers");
  const origin = new URL(testInfo.project.use.baseURL!);
  const loopback = origin.protocol === "http:"
    && ["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname);
  expect(headers?.Connection).toBe(loopback ? "close" : undefined);
});

test("fixture database refuses SQLite in Docker acceptance", () => {
  expect(() => requireFixtureDatabaseUrl(ownedSqlite, "")).toThrow();
});

test("fixture database refuses an empty destination when SQLite is disabled", () => {
  expect(() => requireFixtureDatabaseUrl("", "")).toThrow();
});

function processFixture(stdout = "", stderr = ""): SpawnSyncReturns<string> {
  return { pid: 17, status: 0, signal: null, output: [null, stdout, stderr], stdout, stderr };
}

function driveUnitTranscript(failed = false): string {
  const units = DRIVE_ISOLATION_UNIT_NAMES.map((name, index) =>
    `${name} (test_drive_import_emulator.DriveImportIsolationTests.${name}) ... ${failed && index === 0 ? "FAIL" : "ok"}`,
  );
  const failure = failed ? [
    "=".repeat(70),
    `FAIL: ${DRIVE_ISOLATION_UNIT_NAMES[0]} (test_drive_import_emulator.DriveImportIsolationTests.${DRIVE_ISOLATION_UNIT_NAMES[0]})`,
    "-".repeat(70),
    "Traceback (most recent call last):",
    '  File "tests/e2e/support/oauth/test_drive_import_emulator.py", line 1, in fixture',
    '    raise RuntimeError("Offline Drive source identity or download bounds changed.")',
    "RuntimeError: Offline Drive source identity or download bounds changed.",
    "",
  ] : [];
  return [...units, "", ...failure, "-".repeat(70), "Ran 7 tests in 0.125s", "", failed ? "FAILED (failures=1)" : "OK", ""].join("\n");
}

test("persisted fixture receipts retain selected metadata without private output", async ({}, testInfo) => {
  const privateValue = "never-retain-fixture-output";
  const result = processFixture(privateValue, `Authorization: Bearer ${privateValue}`);
  result.status = null;
  result.signal = "SIGTERM";
  result.error = Object.assign(new Error(`private query: ${privateValue}`), {
    name: privateValue, code: "ETIMEDOUT", errno: -110, syscall: `spawnSync ${privateValue}`,
  });
  const info = {
    testId: testInfo.testId,
    project: { ...testInfo.project, use: { ...testInfo.project.use,
      baseURL: `https://private.example/?q=${privateValue}`,
      extraHTTPHeaders: { Authorization: `Bearer ${privateValue.repeat(FIXTURE_EVIDENCE_MAX_BYTES)}` },
    } },
    outputPath: testInfo.outputPath.bind(testInfo), attach: testInfo.attach.bind(testInfo),
  };
  const saved = await persistFixtureProcessEvidence(info, "selection-fixture-process", result, new Date().toISOString(), 100);
  const bytes = await readFile(saved.receiptPath, "utf8");
  const receipt = JSON.parse(bytes);
  expect(bytes).toBe(saved.receipt);
  expect(Buffer.byteLength(bytes)).toBeLessThan(FIXTURE_EVIDENCE_MAX_BYTES);
  expect(receipt).toMatchObject({
    event: "fixture_process_finished", test_id: testInfo.testId, project: testInfo.project.name,
    pid: 17, exit_code: null, signal: "SIGTERM", duration_ms: 100,
    stdout_bytes: Buffer.byteLength(result.stdout), stderr_bytes: Buffer.byteLength(result.stderr),
    error: { name: "Error", code: "ETIMEDOUT", errno: -110 },
  });
  expect(Object.keys(receipt.error).sort()).toEqual(["code", "errno", "name"]);
  expect(receipt).not.toHaveProperty("stdout");
  expect(receipt).not.toHaveProperty("stderr");
  expect(receipt).not.toHaveProperty("arguments");
  expect(receipt).not.toHaveProperty("transcript");
  expect(bytes).not.toContain(privateValue);
  expect(bytes).not.toContain("private.example");
  expect(bytes).not.toContain("Authorization");
  const attachment = testInfo.attachments.find((item) => item.name === "selection-fixture-process");
  expect(attachment?.contentType).toBe("application/json");
  expect(attachment?.body).toBeUndefined();
  expect(attachment?.path).toBeTruthy();
  expect(await readFile(attachment!.path!, "utf8")).toBe(bytes);
});

test("persisted fixture receipts keep distinct files for repeated calls", async ({}, testInfo) => {
  const first = await persistFixtureProcessEvidence(testInfo, "selection-fixture-process", processFixture("first"), new Date().toISOString(), 1);
  const second = await persistFixtureProcessEvidence(testInfo, "selection-fixture-process", processFixture("second"), new Date().toISOString(), 2);
  expect(first.receiptPath).not.toBe(second.receiptPath);
  expect(JSON.parse(first.receipt).evidence_id).not.toBe(JSON.parse(second.receipt).evidence_id);
  expect(await readFile(first.receiptPath, "utf8")).toBe(first.receipt);
  expect(await readFile(second.receiptPath, "utf8")).toBe(second.receipt);
});

test("persisted fixture receipts reject existing destinations without overwrite", async ({}, testInfo) => {
  const first = await persistFixtureProcessEvidence(testInfo, "selection-fixture-process", processFixture(), new Date().toISOString(), 1);
  const reused = {
    testId: testInfo.testId, project: testInfo.project,
    outputPath: () => first.receiptPath, attach: testInfo.attach.bind(testInfo),
  };
  await expect(persistFixtureProcessEvidence(reused, "selection-fixture-process", processFixture(), new Date().toISOString(), 2))
    .rejects.toThrow(/EEXIST/);
  expect(await readFile(first.receiptPath, "utf8")).toBe(first.receipt);
});

test("persisted Drive evidence retains exact seven-unit transcript and binding", async ({}, testInfo) => {
  const first = DRIVE_ISOLATION_UNIT_NAMES[0];
  const output = driveUnitTranscript().replace(
    `${first} (test_drive_import_emulator.DriveImportIsolationTests.${first}) ... ok`,
    `${first} (test_drive_import_emulator.DriveImportIsolationTests.${first}) ... Offline entrypoint diagnostic\nok`,
  ).replace(/\n/g, "\r\n");
  const saved = await persistFixtureProcessEvidence(testInfo, "drive-isolation-process", processFixture("", output), new Date().toISOString(), 125, output);
  const receipt = JSON.parse(await readFile(saved.receiptPath, "utf8"));
  expect(await readFile(saved.transcriptPath!, "utf8")).toBe(output);
  expect(receipt).toMatchObject({ test_id: testInfo.testId, project: testInfo.project.name,
    transcript: { state: "passed", bytes: Buffer.byteLength(output),
      sha256: createHash("sha256").update(output).digest("hex"),
      units: DRIVE_ISOLATION_UNIT_NAMES.map((name) => ({ name, status: "ok" })),
    },
  });
  const attachment = testInfo.attachments.find((item) => item.name === "drive-emulator-isolation");
  expect(attachment?.contentType).toBe("text/plain");
  expect(attachment?.body).toBeUndefined();
  expect(attachment?.path).toBeTruthy();
  expect(await readFile(attachment!.path!, "utf8")).toBe(output);
});

test("persisted Drive failures retain full reviewed fake-emulator trace", async ({}, testInfo) => {
  const first = DRIVE_ISOLATION_UNIT_NAMES[0];
  for (const output of [
    driveUnitTranscript(true),
    driveUnitTranscript(true).replace(
      `${first} (test_drive_import_emulator.DriveImportIsolationTests.${first}) ... FAIL`,
      `${first} (test_drive_import_emulator.DriveImportIsolationTests.${first}) ... \n  ${first} (test_drive_import_emulator.DriveImportIsolationTests.${first}) (boundary='offline') ... FAIL`,
    ),
  ]) {
    const result = processFixture("", output);
    result.status = 1;
    const saved = await persistFixtureProcessEvidence(testInfo, "drive-isolation-process", result, new Date().toISOString(), 125, output);
    const receipt = JSON.parse(await readFile(saved.receiptPath, "utf8"));
    expect(receipt.exit_code).toBe(1);
    expect(receipt.transcript.state).toBe("failed");
    expect(receipt.transcript.units).toHaveLength(7);
    expect(receipt.transcript.units[0].status).toBe("FAIL");
    expect(await readFile(saved.transcriptPath!, "utf8")).toBe(output);
    expect(output).toContain("Traceback (most recent call last):");
    expect(output).toContain("RuntimeError: Offline Drive source identity or download bounds changed.");
  }
});

test("persisted Drive overflow fails admission without truncated success", async ({}, testInfo) => {
  const output = "x".repeat(FIXTURE_EVIDENCE_MAX_BYTES + 1) + driveUnitTranscript();
  await expect(persistFixtureProcessEvidence(testInfo, "drive-isolation-process", processFixture("", output), new Date().toISOString(), 125, output))
    .rejects.toThrow(/byte_limit.*incomplete/);
  const attachment = testInfo.attachments.find((item) => item.name === "drive-isolation-process");
  const receipt = JSON.parse(await readFile(attachment!.path!, "utf8"));
  expect(receipt.transcript).toMatchObject({ state: "rejected", reason: "byte_limit", file: null,
    bytes: Buffer.byteLength(output), sha256: null });
  expect((await readdir(testInfo.outputDir)).filter((file) => file.startsWith("drive-emulator-isolation-"))).toEqual([]);
  const missing = DRIVE_ISOLATION_UNIT_NAMES[6];
  const partial = driveUnitTranscript().replace(
    `${missing} (test_drive_import_emulator.DriveImportIsolationTests.${missing}) ... ok\n`, "",
  );
  const before = testInfo.attachments.length;
  await expect(persistFixtureProcessEvidence(testInfo, "drive-isolation-process", processFixture("", partial), new Date().toISOString(), 125, partial))
    .rejects.toThrow(/lacks complete seven-unit outcomes.*incomplete/);
  const retained = testInfo.attachments.slice(before).find((item) => item.name === "drive-isolation-process");
  const partialReceipt = JSON.parse(await readFile(retained!.path!, "utf8"));
  expect(partialReceipt.transcript.state).toBe("incomplete");
  expect(partialReceipt.transcript.units).toHaveLength(6);
  expect(await readFile(testInfo.outputPath(partialReceipt.transcript.file), "utf8")).toBe(partial);
});

test("persisted Drive evidence rejects credential-bearing text before writing streams", async ({}, testInfo) => {
  const privateValue = "never-retain-fixture-output";
  for (const prefix of [
    `Authorization: Bearer ${privateValue}`, `access_token=${privateValue}`,
    `CASEOPS_AUTH_SECRET=${privateValue}`, `Cookie: fixture=${privateValue}`,
    `https://private.example/?q=${privateValue}`, `postgresql+psycopg://u:${privateValue}@db/caseops`,
  ]) {
    const before = testInfo.attachments.length;
    const output = `${prefix}\n` + driveUnitTranscript();
    await expect(persistFixtureProcessEvidence(testInfo, "drive-isolation-process", processFixture("", output), new Date().toISOString(), 125, output))
      .rejects.toThrow(/sensitive_output.*incomplete/);
    const attachment = testInfo.attachments.slice(before).find((item) => item.name === "drive-isolation-process");
    const bytes = await readFile(attachment!.path!, "utf8");
    expect(bytes).not.toContain(privateValue);
    expect(JSON.parse(bytes).transcript).toMatchObject({ state: "rejected", reason: "sensitive_output", file: null, sha256: null });
  }
  expect((await readdir(testInfo.outputDir)).filter((file) => file.startsWith("drive-emulator-isolation-"))).toEqual([]);
});

test("persisted fixture binding rejects private identity data before file creation", async ({}, testInfo) => {
  let outputCalls = 0;
  for (const [testId, project] of [
    ["private?query=fixture", testInfo.project],
    [testInfo.testId, { ...testInfo.project, name: "private?query=fixture" }],
  ] as const) {
    const info = { testId, project,
      outputPath: (...segments: string[]) => { outputCalls++; return testInfo.outputPath(...segments); },
      attach: testInfo.attach.bind(testInfo),
    };
    await expect(persistFixtureProcessEvidence(info, "selection-fixture-process", processFixture(), new Date().toISOString(), 1))
      .rejects.toThrow("Invalid fixture evidence metadata.");
  }
  expect(outputCalls).toBe(0);
  expect(testInfo.attachments).toEqual([]);
});
