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

export default async function globalSetup(): Promise<void> {
  fs.rmSync(runtimeRoot, { force: true, recursive: true });
  fs.rmSync(path.join(repoRoot, "caseops-e2e.db"), { force: true });
  fs.mkdirSync(runtimeRoot, { recursive: true });
  fs.mkdirSync(documentStoragePath, { recursive: true });
  fs.mkdirSync(documentCachePath, { recursive: true });
  fs.mkdirSync(uploadsRoot, { recursive: true });

  const migrationRun = spawnSync(
    "uv",
    [
      "--directory",
      "apps/api",
      "run",
      "python",
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
