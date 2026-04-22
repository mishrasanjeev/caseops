import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { e2eEnv, repoRoot, uploadsRoot } from "./env";

// Sprint 6 — /legacy is gone. The Page-driven bootstrapCompany helper
// that used to target the legacy console was removed along with the
// route. Tests that need a tenant should bootstrap via the API
// directly (playwright's `request.newContext()` + POST /bootstrap),
// which is both faster and closer to what the new cockpit exercises
// end to end.

export function uniqueId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

export function plusDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

export function makeUploadFixture(filename: string, contents: string): string {
  fs.mkdirSync(uploadsRoot, { recursive: true });
  const filePath = path.join(uploadsRoot, filename);
  fs.writeFileSync(filePath, contents, "utf8");
  return filePath;
}

export async function runDocumentWorkerOnce(): Promise<void> {
  // Strict Ledger #10 follow-up (2026-04-22): bypass `uv run`'s
  // implicit sync (EBUSY on Windows when a long-running process
  // holds a lock on a .venv/Scripts/*.exe wrapper). Invoke the
  // worker as a python module — works whether or not uv has
  // refreshed the entry-point .exe, and shares the same
  // interpreter the test suite is already using.
  const venvPython =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");

  const result = spawnSync(
    venvPython,
    ["-m", "caseops_api.workers.document_processor", "--once"],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        ...e2eEnv,
      },
      encoding: "utf8",
    },
  );

  if (result.status !== 0) {
    throw new Error(
      `Document worker failed with status ${result.status}.\nSTDOUT:\n${result.stdout}\nSTDERR:\n${result.stderr}`,
    );
  }
}
