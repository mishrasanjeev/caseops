import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { defineConfig } from "@playwright/test";

import appConfig from "./playwright.app.config";

const dockerWebBaseUrl =
  process.env.CASEOPS_WEB_BASE_URL ?? "http://127.0.0.1:13100";

// Owner-approved 2026-11-15: the local Docker acceptance gate runs while other
// workstation work continues, and full-docker-17 timed out five browser cases
// that passed in 9-48 s on full-docker-08. Every browser time limit in this
// local-only config is multiplied by CASEOPS_E2E_TIMEOUT_SCALE (default 3, the
// factor Playwright's own test.slow() uses; 1 restores the original limits).
// Production, CI and the app config keep their limits and latency assertions;
// a case that passes only under the scaled limit is not latency evidence.
const DEFAULT_TIMEOUT_SCALE = "3";
const rawTimeoutScale = process.env.CASEOPS_E2E_TIMEOUT_SCALE ?? DEFAULT_TIMEOUT_SCALE;
const timeoutScale = Number(rawTimeoutScale);
if (!/^\d+(\.\d+)?$/.test(rawTimeoutScale) || !(timeoutScale >= 1 && timeoutScale <= 5)) {
  throw new Error("CASEOPS_E2E_TIMEOUT_SCALE must be a number from 1 to 5.");
}
process.env.CASEOPS_E2E_TIMEOUT_SCALE = rawTimeoutScale;

const scaled = (milliseconds: number) => Math.round(milliseconds * timeoutScale);

// Most specs set their own limit with test.setTimeout(), which replaces the
// config timeout, and 181 of them import test directly from @playwright/test.
// Every such call (config default, describe-level and in-test setTimeout, and
// testInfo.setTimeout) ends in the worker's TimeoutManager.setTimeout, so a
// preload scales that one method. Workers inherit NODE_OPTIONS from this
// runner process. The preload is written from this file so the config stays
// self-contained, and an unexpected Playwright worker shape fails the worker.
const preloadSource = `"use strict";
const Module = require("module");
const path = require("path");
const scale = Number(process.env.CASEOPS_E2E_TIMEOUT_SCALE);
if (!(scale >= 1 && scale <= 5)) {
  throw new Error("CaseOps browser time-limit scale is missing or invalid.");
}
const target = path.join("playwright", "lib", "worker", "workerProcessEntry.js");
const original = Module.prototype._compile;
Module.prototype._compile = function (content, filename) {
  if (typeof filename === "string" && path.normalize(filename).endsWith(target)) {
    Module.prototype._compile = original;
    content += "\\n;(" + function install(scaleValue) {
      if (
        typeof TimeoutManager !== "function" ||
        typeof TimeoutManager.prototype.setTimeout !== "function" ||
        typeof TimeoutManager.prototype.slow !== "function"
      ) {
        throw new Error("CaseOps browser time-limit scaling found an unsupported Playwright worker.");
      }
      const setTimeoutOriginal = TimeoutManager.prototype.setTimeout;
      TimeoutManager.prototype.setTimeout = function (timeout) {
        return setTimeoutOriginal.call(this, timeout > 0 ? Math.round(timeout * scaleValue) : timeout);
      };
      globalThis.__caseopsE2eTimeoutScale = scaleValue;
    }.toString() + ")(" + JSON.stringify(scale) + ");\\n";
  }
  return original.call(this, content, filename);
};
`;

if (timeoutScale !== 1) {
  const digest = createHash("sha256").update(preloadSource).digest("hex").slice(0, 16);
  const preloadPath = path.join(tmpdir(), `caseops-playwright-timeout-scale-${digest}.cjs`);
  if (!existsSync(preloadPath) || readFileSync(preloadPath, "utf8") !== preloadSource) {
    writeFileSync(preloadPath, preloadSource, { encoding: "utf8", mode: 0o600 });
  }
  const requireOption = `--require ${JSON.stringify(preloadPath)}`;
  const nodeOptions = process.env.NODE_OPTIONS ?? "";
  if (!nodeOptions.includes(requireOption)) {
    process.env.NODE_OPTIONS = `${nodeOptions} ${requireOption}`.trim();
  }
  // This config also loads inside each worker, after the worker entry ran.
  const scaleInstalled = (globalThis as { __caseopsE2eTimeoutScale?: number })
    .__caseopsE2eTimeoutScale;
  if (process.env.TEST_WORKER_INDEX !== undefined && scaleInstalled !== timeoutScale) {
    throw new Error("CaseOps browser time-limit scaling was not installed in this worker.");
  }
}

export default defineConfig({
  ...appConfig,
  globalSetup: undefined,
  webServer: undefined,
  // The preload scales the default through TimeoutManager.setTimeout, so the
  // config default stays unscaled here; scaling it twice would multiply by 9.
  timeout: appConfig.timeout,
  expect: { ...appConfig.expect, timeout: scaled(appConfig.expect?.timeout ?? 15_000) },
  use: {
    ...appConfig.use,
    // Docker Desktop on Windows can spend tens of seconds materializing the
    // first authenticated route after a clean image/volume reset. Keep this
    // local-only budget below the test ceiling (60 s against 120 s, both
    // scaled); production uses its dedicated latency assertions and
    // exact-release configuration.
    actionTimeout: scaled(60_000),
    navigationTimeout: scaled(appConfig.use?.navigationTimeout ?? 30_000),
    baseURL: dockerWebBaseUrl,
  },
});
