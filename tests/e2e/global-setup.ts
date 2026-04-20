import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import {
  documentCachePath,
  documentStoragePath,
  e2eEnv,
  repoRoot,
  runtimeRoot,
  uploadsRoot,
} from "./support/env";

/**
 * Resolve the API venv Python interpreter. Playwright global-setup used
 * to invoke ``uv --directory apps/api run python ...`` which triggers
 * uv's package-sync step on every run. On Windows, that step can fail
 * with a file-lock on ``.venv/Scripts/caseops-*.exe`` whenever another
 * process (ingest worker, dev server) is holding the script. The
 * Codex 2026-04-20 test-suite gap audit flagged this as a P0 because
 * the entire Playwright suite was blocked before any browser tests ran.
 *
 * Fix: prefer the interpreter path directly (no sync path) and fall
 * back to ``uv run --no-sync`` — which skips sync but still resolves
 * through uv — only if the interpreter isn't materialised yet.
 */
function apiVenvPython(): { cmd: string; prefixArgs: string[] } {
  const direct =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  if (fs.existsSync(direct)) {
    return { cmd: direct, prefixArgs: [] };
  }
  return {
    cmd: "uv",
    prefixArgs: ["--directory", "apps/api", "run", "--no-sync", "python"],
  };
}

export default async function globalSetup(): Promise<void> {
  fs.rmSync(runtimeRoot, { force: true, recursive: true });
  fs.rmSync(path.join(repoRoot, "caseops-e2e.db"), { force: true });
  fs.mkdirSync(runtimeRoot, { recursive: true });
  fs.mkdirSync(documentStoragePath, { recursive: true });
  fs.mkdirSync(documentCachePath, { recursive: true });
  fs.mkdirSync(uploadsRoot, { recursive: true });

  const { cmd, prefixArgs } = apiVenvPython();
  const migrationRun = spawnSync(
    cmd,
    [
      ...prefixArgs,
      "-c",
      "from caseops_api.db.migrations import run_migrations; run_migrations()",
    ],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        ...e2eEnv,
        CASEOPS_AUTO_MIGRATE: "true",
      },
      encoding: "utf8",
    },
  );

  if (migrationRun.status !== 0) {
    throw new Error(
      `Could not prepare the e2e database.\nSTDOUT:\n${migrationRun.stdout}\nSTDERR:\n${migrationRun.stderr}`,
    );
  }
}
