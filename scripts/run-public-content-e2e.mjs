import { spawn } from "node:child_process";
import { once } from "node:events";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const webDir = path.join(root, "apps", "web");
const nextCli = path.join(root, "node_modules", "next", "dist", "bin", "next");
const playwrightCli = path.join(root, "node_modules", "@playwright", "test", "cli.js");
const localBaseUrl = "http://127.0.0.1:3101";
const configuredBaseUrl = process.env.CASEOPS_WEB_BASE_URL?.trim();
const playwrightConfig = process.argv[2] ?? "playwright.public-content.config.ts";
const productionBuildEnv = {
  ...process.env,
  NEXT_PUBLIC_SITE_URL:
    process.env.NEXT_PUBLIC_SITE_URL?.trim() || "https://caseops.ai",
  NEXT_PUBLIC_APP_URL:
    process.env.NEXT_PUBLIC_APP_URL?.trim() || "https://caseops.ai/app",
};

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      env: process.env,
      stdio: "inherit",
      windowsHide: true,
      ...options,
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (signal) {
        reject(new Error(`${path.basename(command)} exited on signal ${signal}`));
        return;
      }
      resolve(code ?? 1);
    });
  });
}

async function waitForServer(child) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Next.js server exited before becoming ready (${child.exitCode}).`);
    }
    try {
      const response = await fetch(localBaseUrl, { cache: "no-store" });
      if (response.status < 500) return;
    } catch {
      // The socket is expected to refuse connections during startup.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Next.js server did not become ready at ${localBaseUrl}.`);
}

async function stopServer(child) {
  if (child.exitCode !== null) return;
  const exited = once(child, "exit").then(() => true);
  child.kill("SIGTERM");
  const stopped = await Promise.race([
    exited,
    new Promise((resolve) => setTimeout(() => resolve(false), 5_000)),
  ]);
  if (!stopped) {
    child.kill("SIGKILL");
    await Promise.race([
      exited,
      new Promise((resolve) => setTimeout(() => resolve(false), 1_000)),
    ]);
  }
  child.unref();
}

async function runPlaywright(baseUrl) {
  return run(
    process.execPath,
    [playwrightCli, "test", "--config", playwrightConfig],
    {
      env: { ...process.env, CASEOPS_WEB_BASE_URL: baseUrl },
    },
  );
}

async function main() {
  if (configuredBaseUrl) {
    if (playwrightConfig !== "playwright.public-content.config.ts") {
      throw new Error(
        "Only the read-only public-content suite may target CASEOPS_WEB_BASE_URL; marketing tests submit demo requests.",
      );
    }
    return runPlaywright(configuredBaseUrl);
  }

  const buildCode = await run(process.execPath, [nextCli, "build"], {
    cwd: webDir,
    env: productionBuildEnv,
  });
  if (buildCode !== 0) return buildCode;

  const server = spawn(
    process.execPath,
    [nextCli, "start", "--hostname", "127.0.0.1", "--port", "3101"],
    {
      cwd: webDir,
      env: productionBuildEnv,
      stdio: "inherit",
      windowsHide: true,
    },
  );

  try {
    await waitForServer(server);
    console.log(`[web-e2e] Next.js ready at ${localBaseUrl}; starting ${playwrightConfig}.`);
    const testCode = await runPlaywright(localBaseUrl);
    console.log(`[web-e2e] Playwright exited with code ${testCode}.`);
    return testCode;
  } finally {
    console.log("[web-e2e] Stopping local Next.js server.");
    await stopServer(server);
  }
}

try {
  process.exitCode = await main();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
