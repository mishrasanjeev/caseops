import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const runtimeRoot = path.join(repoRoot, ".e2e");
const apiPort = process.env.CASEOPS_E2E_API_PORT ?? "8000";
const webPort = process.env.CASEOPS_E2E_WEB_PORT ?? "3100";
const apiBaseUrl = `http://127.0.0.1:${apiPort}`;
const webBaseUrl = `http://127.0.0.1:${webPort}`;
const databasePath = path.join(repoRoot, "caseops-e2e.db").replace(/\\/g, "/");
const documentStoragePath = path.join(runtimeRoot, "documents");
const documentCachePath = path.join(runtimeRoot, "document-cache");
const uploadsRoot = path.join(runtimeRoot, "uploads");

const e2eEnv = {
  ...process.env,
  CASEOPS_ENV: "e2e",
  CASEOPS_API_HOST: "127.0.0.1",
  CASEOPS_API_PORT: apiPort,
  CASEOPS_AUTO_MIGRATE: "false",
  CASEOPS_DATABASE_URL: `sqlite+pysqlite:///${databasePath}`,
  CASEOPS_AUTH_SECRET: "caseops-e2e-secret-caseops-e2e-secret",
  CASEOPS_PUBLIC_APP_URL: webBaseUrl,
  CASEOPS_CORS_ORIGINS: JSON.stringify([
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    webBaseUrl,
    `http://localhost:${webPort}`,
  ]),
  CASEOPS_DOCUMENT_STORAGE_PATH: documentStoragePath.replace(/\\/g, "/"),
  CASEOPS_DOCUMENT_STORAGE_CACHE_PATH: documentCachePath.replace(/\\/g, "/"),
  CASEOPS_AUTH_RATE_LIMIT_ENABLED: "false",
  CASEOPS_CASE_TRACKING_ENABLED: "true",
  CASEOPS_CASE_TRACKING_PROVIDER: "ecourtsindia",
  CASEOPS_ECOURTSINDIA_API_BASE_URL: "https://provider.example",
  CASEOPS_ECOURTSINDIA_API_TOKEN: "e2e-provider-token",
  CASEOPS_WEB_BASE_URL: webBaseUrl,
  UV_CACHE_DIR: path.join(repoRoot, ".uv-cache").replace(/\\/g, "/"),
};

function apiPythonCommand() {
  const direct =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  if (fs.existsSync(direct)) {
    return { command: direct, args: [] };
  }
  return {
    command: "uv",
    args: ["--directory", "apps/api", "run", "--no-sync", "python"],
  };
}

function shellCommand(command, args) {
  if (process.platform !== "win32") {
    return { command, args };
  }
  return { command: "cmd.exe", args: ["/d", "/s", "/c", command, ...args] };
}

function prepareRuntime() {
  fs.rmSync(runtimeRoot, { force: true, recursive: true });
  for (const suffix of ["", "-shm", "-wal"]) {
    fs.rmSync(path.join(repoRoot, `caseops-e2e.db${suffix}`), { force: true });
  }
  fs.mkdirSync(documentStoragePath, { recursive: true });
  fs.mkdirSync(documentCachePath, { recursive: true });
  fs.mkdirSync(uploadsRoot, { recursive: true });

  const python = apiPythonCommand();
  const result = spawnSync(
    python.command,
    [
      ...python.args,
      "-c",
      "from caseops_api.db.migrations import run_migrations; run_migrations()",
    ],
    {
      cwd: repoRoot,
      env: { ...e2eEnv, CASEOPS_AUTO_MIGRATE: "true" },
      encoding: "utf8",
    },
  );
  if (result.status !== 0) {
    throw new Error(
      `Could not prepare the e2e database.\nSTDOUT:\n${result.stdout}\nSTDERR:\n${result.stderr}`,
    );
  }
}

function buildWeb() {
  if (process.env.CASEOPS_E2E_SKIP_WEB_BUILD === "1") {
    return;
  }
  const npm = shellCommand("npm", ["run", "build"]);
  const result = spawnSync(npm.command, npm.args, {
    cwd: path.join(repoRoot, "apps", "web"),
    env: {
      ...e2eEnv,
      NEXT_PUBLIC_API_BASE_URL: apiBaseUrl,
      NEXT_PUBLIC_SITE_URL: "https://caseops.ai",
      NEXT_PUBLIC_APP_URL: "https://caseops.ai/app",
    },
    stdio: "inherit",
  });
  if (result.status !== 0) {
    const cause = result.error?.message ?? result.signal ?? result.status;
    throw new Error(`Web build failed with status ${cause}`);
  }
}

function spawnLogged(name, command, args, options) {
  const child = spawn(command, args, {
    ...options,
    detached: process.platform !== "win32",
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => process.stdout.write(`[${name}] ${chunk}`));
  child.stderr.on("data", (chunk) => process.stderr.write(`[${name}] ${chunk}`));
  return child;
}

function startApi() {
  const command =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "uvicorn.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "uvicorn");
  return spawnLogged(
    "api",
    command,
    [
      "caseops_api.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      apiPort,
      "--app-dir",
      "apps/api/src",
    ],
    { cwd: repoRoot, env: e2eEnv },
  );
}

function startWeb() {
  const npx = shellCommand("npx", [
    "next",
    "start",
    "--hostname",
    "127.0.0.1",
    "--port",
    webPort,
  ]);
  return spawnLogged(
    "web",
    npx.command,
    npx.args,
    {
      cwd: path.join(repoRoot, "apps", "web"),
      env: {
        ...e2eEnv,
        NEXT_PUBLIC_API_BASE_URL: apiBaseUrl,
        NEXT_PUBLIC_SITE_URL: "https://caseops.ai",
        NEXT_PUBLIC_APP_URL: "https://caseops.ai/app",
      },
    },
  );
}

async function waitForUrl(url, timeoutMs) {
  const start = Date.now();
  let lastError = "";
  while (Date.now() - start < timeoutMs) {
    try {
      const status = await new Promise((resolve, reject) => {
        const request = http.get(url, (response) => {
          response.resume();
          response.on("end", () => resolve(response.statusCode ?? 0));
        });
        request.setTimeout(1500, () => {
          request.destroy(new Error("request timed out"));
        });
        request.on("error", reject);
      });
      if (status >= 200 && status < 400) {
        return;
      }
      lastError = `HTTP ${status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError}`);
}

function runPlaywright() {
  const npx = shellCommand("npx", [
    "playwright",
    "test",
    "--config",
    "playwright.functional-qa.config.ts",
    "--reporter=line",
    ...process.argv.slice(2),
  ]);
  const result = spawnSync(
    npx.command,
    npx.args,
    {
      cwd: repoRoot,
      env: e2eEnv,
      stdio: "inherit",
    },
  );
  return result.status ?? 1;
}

function stopProcessTree(child) {
  if (!child || child.exitCode !== null) {
    return;
  }
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
    });
    return;
  }
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    child.kill("SIGTERM");
  }
}

let api;
let web;
let exitCode = 1;
try {
  prepareRuntime();
  buildWeb();
  api = startApi();
  await waitForUrl(`${apiBaseUrl}/api/health`, 120_000);
  web = startWeb();
  await waitForUrl(webBaseUrl, 120_000);
  exitCode = runPlaywright();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  exitCode = 1;
} finally {
  stopProcessTree(web);
  stopProcessTree(api);
}

process.exit(exitCode);
