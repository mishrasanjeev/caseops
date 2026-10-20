import type { SpawnSyncReturns } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { constants } from "node:os";
import type { TestInfo } from "@playwright/test";

export const FIXTURE_EVIDENCE_MAX_BYTES = 64 * 1024;
export const DRIVE_ISOLATION_UNIT_NAMES = [
  "test_fixture_inventory_is_bounded",
  "test_install_rejects_non_e2e_and_cloud_before_touching_application",
  "test_provider_cannot_authorize_exchange_or_browse_google",
  "test_provider_does_not_allow_cross_fixture_tokens",
  "test_provider_enforces_the_captured_version_size_and_deadline",
  "test_provider_returns_exact_registered_bytes_only",
] as const;

type EvidenceTestInfo = Pick<TestInfo, "testId" | "project" | "outputPath" | "attach">;
type ProcessEvidenceName = "selection-fixture-process" | "drive-isolation-process";

export function reviewDriveSupervisor(output: string) {
  if (Buffer.byteLength(output) > FIXTURE_EVIDENCE_MAX_BYTES) {
    throw new Error("Drive supervisor output exceeds its evidence bound.");
  }
  const events = output.trim().split(/\r?\n/).map((line) => {
    if (!line.startsWith("CASEOPS_FIXTURE_EVENT ")) throw new Error("Unrecognized Drive supervisor output.");
    let event: unknown;
    try { event = JSON.parse(line.slice("CASEOPS_FIXTURE_EVENT ".length)); }
    catch { throw new Error("Invalid Drive supervisor JSON."); }
    if (!event || typeof event !== "object" || Array.isArray(event)) throw new Error("Invalid Drive supervisor event.");
    return event as Record<string, unknown>;
  });
  const names = events.map((event) => event.event);
  const expected = DRIVE_ISOLATION_UNIT_NAMES.map((name) => `test_drive_import_emulator.DriveImportIsolationTests.${name}`);
  const starts = events.filter((event) => event.event === "test_started").map((event) => event.test_id);
  const ends = events.filter((event) => event.event === "test_finished").map((event) => event.test_id);
  const one = (name: string) => {
    const selected = events.filter((event) => event.event === name);
    return selected.length === 1 ? selected[0] : undefined;
  };
  const first = one("supervisor_started");
  const child = one("child_started");
  const collection = one("collection");
  const result = one("unittest_finished");
  const cleanup = one("cleanup_started");
  const killed = one("cleanup_kill_sent");
  const last = one("supervisor_finished");
  const same = (value: unknown, wanted: unknown) => JSON.stringify(value) === JSON.stringify(wanted);
  const sequence = ["supervisor_started", "child_started", "collection",
    ...expected.flatMap(() => ["test_started", "test_finished"]),
    "unittest_finished", "cleanup_started", "cleanup_kill_sent", "supervisor_finished"];
  const complete = same(names, sequence)
    && first?.pattern === "test_drive_import_emulator.py" && first.deadline_seconds === 50
    && Number.isSafeInteger(child?.pid) && Number(child?.pid) > 0
    && cleanup?.pid === child?.pid && killed?.pid === child?.pid
    && typeof child?.source_sha256 === "string" && /^[0-9a-f]{64}$/.test(child.source_sha256)
    && same(collection?.test_ids, expected) && same(starts, expected) && same(ends, expected)
    && result?.tests_run === expected.length && result.failures === 0 && result.errors === 0 && result.skipped === 0
    && last?.exit_code === 0 && last.reason === "child_exited" && last.tree_reaped === true
    && last.child_exit_code === 0 && typeof last.duration_seconds === "number"
    && Number.isFinite(last.duration_seconds) && last.duration_seconds >= 0 && last.duration_seconds <= 56;
  // Retain only reviewed fields, never arbitrary process output or exception text.
  return {
    event: "drive_supervision_reviewed", complete, stdout_bytes: Buffer.byteLength(output),
    stdout_sha256: createHash("sha256").update(output).digest("hex"),
    source_sha256: complete ? child!.source_sha256 : null,
    unit_ids: complete ? expected : [], tree_reaped: complete ? true : null,
  };
}

function driveTranscriptReview(output: string) {
  const bytes = Buffer.byteLength(output);
  if (bytes > FIXTURE_EVIDENCE_MAX_BYTES) {
    return { state: "rejected", reason: "byte_limit", units: [] };
  }
  // Only this audited offline unittest command may retain text, never generic process streams.
  const sensitive = /\bBearer\s+\S+|\b(?:Authorization|Cookie|Set-Cookie)\s*:|\b(?:access_token|refresh_token|client_secret|password|api_key|(?:CASEOPS_)?auth_secret)\b["']?\s*[:=]\s*\S+|\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b|(?:https?|postgresql(?:\+psycopg)?):\/\/[^/\s]*@|https?:\/\/[^\s"']*\?|[?&](?:state|code|token|password|key|q|query)=/i;
  if (sensitive.test(output)) {
    return { state: "rejected", reason: "sensitive_output", units: [] };
  }
  const lines = output.replace(/\r\n/g, "\n");
  const headers = [...lines.matchAll(/^([a-zA-Z0-9_]+) \(([^\n]+)\) \.\.\./gm)];
  const units = headers.flatMap((match, index) => {
    const name = match[1];
    if (DRIVE_ISOLATION_UNIT_NAMES.some((reviewed) => reviewed === name)
      && match[2] === `test_drive_import_emulator.DriveImportIsolationTests.${name}`) {
      const block = lines.slice(match.index! + match[0].length, headers[index + 1]?.index)
        .split(/\n(?:={70}|-{70})\n/, 1)[0];
      const direct = block.match(/^ (ok|FAIL|ERROR)(?:\n|$)/)?.[1]
        ?? block.match(/^(ok|FAIL|ERROR)$/m)?.[1];
      const subtests = [...block.matchAll(new RegExp(
        `^ +${name} \\(test_drive_import_emulator\\.DriveImportIsolationTests\\.${name}\\)(?: \\([^\\n]+\\))? \\.\\.\\. (FAIL|ERROR)(?:\\n|$)`, "gm",
      ))];
      const status = subtests.some((subtest) => subtest[1] === "ERROR") ? "ERROR"
        : subtests.length ? "FAIL" : direct ?? null;
      return [{ name, status }];
    }
    return [];
  });
  const loaderFailure = headers.length === 1
    && headers[0][1] === "test_drive_import_emulator"
    && headers[0][2] === "unittest.loader._FailedTest.test_drive_import_emulator";
  if (headers.length === 0 || (headers.length !== units.length && !loaderFailure)
    || new Set(units.map((unit) => unit.name)).size !== units.length) {
    return { state: "rejected", reason: "unreviewed_unit_inventory", units };
  }
  const count = DRIVE_ISOLATION_UNIT_NAMES.length;
  const complete = units.length === count
    && new RegExp(`^Ran ${count} tests in [0-9]+(?:\\.[0-9]+)?s$`, "m").test(lines);
  if (complete && units.every((unit) => unit.status === "ok") && /\nOK\s*$/.test(lines)) {
    return { state: "passed", reason: null, units };
  }
  if (complete && units.every((unit) => unit.status !== null)
    && /\nFAILED \((?:failures|errors)=\d+(?:, (?:failures|errors)=\d+)*\)\s*$/.test(lines)) {
    return { state: "failed", reason: null, units };
  }
  return { state: "incomplete", reason: "missing_unit_completion", units };
}

export async function persistFixtureProcessEvidence(
  testInfo: EvidenceTestInfo,
  name: ProcessEvidenceName,
  result: SpawnSyncReturns<string>,
  startedAt: string,
  durationMs: number,
  driveTranscript?: string,
) {
  if (!/^[0-9a-f]{20}-[0-9a-f]{20}$/.test(testInfo.testId)
    || !/^[a-z][a-z0-9-]{0,63}$/.test(testInfo.project.name)
    || !["selection-fixture-process", "drive-isolation-process"].includes(name)
    || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(startedAt)
    || !Number.isFinite(Date.parse(startedAt))
    || !Number.isFinite(durationMs) || durationMs < 0
    || (driveTranscript !== undefined && name !== "drive-isolation-process")) {
    throw new Error("Invalid fixture evidence metadata.");
  }
  const evidenceId = randomUUID().replace(/-/g, "").slice(0, 12);
  const error = result.error as NodeJS.ErrnoException | undefined;
  const transcriptName = `drive-emulator-isolation-${evidenceId}.txt`;
  const review = driveTranscript === undefined ? undefined : driveTranscriptReview(driveTranscript);
  const receipt = JSON.stringify({
    event: "fixture_process_finished",
    evidence_id: evidenceId,
    test_id: testInfo.testId,
    project: testInfo.project.name,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    duration_ms: durationMs,
    pid: Number.isSafeInteger(result.pid) ? result.pid : null,
    exit_code: Number.isSafeInteger(result.status) ? result.status : null,
    signal: result.signal && Object.hasOwn(constants.signals, result.signal) ? result.signal : null,
    error: error ? {
      name: ["Error", "TypeError", "RangeError"].includes(error.name) ? error.name : "Error",
      code: error.code && Object.hasOwn(constants.errno, error.code) ? error.code : null,
      errno: Number.isSafeInteger(error.errno) ? error.errno : null,
    } : null,
    stdout_bytes: Buffer.byteLength(result.stdout ?? ""),
    stderr_bytes: Buffer.byteLength(result.stderr ?? ""),
    transcript: review && {
      ...review,
      file: review.state === "rejected" ? null : transcriptName,
      bytes: Buffer.byteLength(driveTranscript!),
      sha256: review.state === "rejected" ? null
        : createHash("sha256").update(driveTranscript!).digest("hex"),
    },
  }, null, 2) + "\n";
  if (Buffer.byteLength(receipt) > FIXTURE_EVIDENCE_MAX_BYTES) {
    throw new Error("Fixture receipt exceeds the evidence byte limit; acceptance incomplete.");
  }
  const receiptPath = testInfo.outputPath(`${name}-${evidenceId}.json`);
  await writeFile(receiptPath, receipt, { encoding: "utf8", flag: "wx", mode: 0o600 });
  await testInfo.attach(name, { path: receiptPath, contentType: "application/json" });
  let transcriptPath: string | undefined;
  if (review) {
    if (review.state === "rejected") {
      throw new Error(`Drive fixture transcript rejected (${review.reason}); acceptance incomplete.`);
    }
    transcriptPath = testInfo.outputPath(transcriptName);
    await writeFile(transcriptPath, driveTranscript!, { encoding: "utf8", flag: "wx", mode: 0o600 });
    await testInfo.attach("drive-emulator-isolation", { path: transcriptPath, contentType: "text/plain" });
    if (!error && result.status === 0 && review.state !== "passed") {
      throw new Error("Drive fixture transcript lacks complete reviewed-unit outcomes; acceptance incomplete.");
    }
  }
  return { receipt, receiptPath, transcriptPath };
}

export function fixtureProcessEvidence(
  result: SpawnSyncReturns<string>,
  startedAt: string,
  durationMs: number,
  includeStdout = true,
): string {
  const error = result.error as NodeJS.ErrnoException | undefined;
  return JSON.stringify({
    event: "fixture_process_finished",
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    duration_ms: durationMs,
    pid: result.pid,
    exit_code: result.status,
    signal: result.signal,
    error: error ? {
      name: error.name,
      message: error.message,
      code: error.code,
      errno: error.errno,
      syscall: error.syscall,
    } : null,
    stdout_bytes: Buffer.byteLength(result.stdout ?? ""),
    stdout: includeStdout ? result.stdout : undefined,
    stderr: result.stderr,
  }, null, 2);
}
