import type { SpawnSyncReturns } from "node:child_process";

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
