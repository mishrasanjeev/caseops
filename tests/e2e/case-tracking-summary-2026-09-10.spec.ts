import { createHash, randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, repoRoot, webBaseUrl } from "./support/env";

const fixtureModule = "caseops_api.scripts.docker_acceptance_summary";
const sourceText = "Synthetic order dated 10 September 2026. File the witness list before the next hearing.";
const fallback = "Provider fixture: review the order and prepare the witness list.";
const generated = "The order directs filing of a witness list before the next hearing.";
const hash = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");
type Scenario = "positive" | "marked" | "persistent_qa";
type Seed = { actor_id: string; matter_id: string; bookmark_id: string; update_id: string };
type Inspection = {
  summary: string; model_run_id: string | null; source_sha256: string;
  ai_summary: { concise_summary: string; summary_source: string };
  event: { id: string; state: string; attempts: number; no_paid_providers: boolean };
  effects: { state: string; result_type: string; result_id: string }[];
  runs: { id: string; status: string; provider: string; model: string; prompt_tokens: number; completion_tokens: number }[];
  provider_operations: number; spend_reservations: number;
};
type Container = {
  Id: string; Image: string; State: { Running: boolean; Status: string; ExitCode: number };
  Config: { Labels: Record<string, string>; Env: string[] };
  NetworkSettings: { Networks: Record<string, unknown> };
};

test.use({ extraHTTPHeaders: noPaidProviderHeaders });

test("dated async summary: visible fallback, release-image worker, retained source and no-paid fences", async ({ browser, request }, info) => {
  test.setTimeout(300_000);
  const project = process.env.CASEOPS_E2E_DOCKER_PROJECT;
  test.skip(!project, "Requires the isolated exact-image Docker worker stack; not host or production acceptance.");
  const composeFile = process.env.CASEOPS_E2E_DOCKER_COMPOSE_FILE;
  expect(composeFile, "Docker compose metadata is required").toBeTruthy();
  expect(process.env.CASEOPS_SUMMARY_ACCEPTANCE).toBe("1");
  for (const endpoint of [apiBaseUrl, webBaseUrl]) {
    expect(["127.0.0.1", "localhost"]).toContain(new URL(endpoint).hostname);
  }
  expect(process.env.PROD_BASE_URL || process.env.PROD_API_BASE_URL || "").toBe("");
  const compose = ["compose", "--project-name", project!, "--file", composeFile!];
  const journal = info.outputPath("summary-boundary.jsonl");
  fs.mkdirSync(path.dirname(journal), { recursive: true });
  const record = (phase: string, detail: unknown) => {
    fs.appendFileSync(journal, JSON.stringify({ phase, at: new Date().toISOString(), detail }) + "\n");
  };
  const docker = (args: string[], timeout = 60_000) => {
    const result = spawnSync("docker", args, { encoding: "utf8", timeout, maxBuffer: 8 * 1024 * 1024 });
    if (result.error || result.status !== 0) {
      record("command_failed", { error: result.error?.message, status: result.status,
        stdout: result.stdout, stderr: result.stderr });
      throw new Error(`Docker acceptance command failed: ${result.error?.message || result.status}\n${result.stderr}`);
    }
    return (args[0] === "logs" ? result.stdout + result.stderr : result.stdout).trim();
  };
  const inspectContainer = (id: string): Container => JSON.parse(docker(["inspect", id]))[0];
  const service = (name: string) => {
    const id = docker([...compose, "ps", "--all", "--quiet", name]);
    expect(id).toMatch(/^[a-f0-9]+$/);
    const value = inspectContainer(id);
    expect(value.Config.Labels["com.docker.compose.project"]).toBe(project);
    expect(value.Config.Labels["com.docker.compose.service"]).toBe(name);
    return value;
  };
  const api = service("api");
  const worker = service("worker");
  expect(api.State.Running).toBe(true);
  expect(worker.Image).toBe(api.Image);
  for (const container of [api, worker]) {
    const networks = Object.keys(container.NetworkSettings.Networks);
    expect(networks.length).toBeGreaterThan(0);
    for (const name of networks) {
      const network = JSON.parse(docker(["network", "inspect", name]))[0];
      if (container.Id === worker.Id) {
        expect(network.Internal, `${name} must deny worker external egress`).toBe(true);
      }
      expect(network.Labels["com.docker.compose.project"]).toBe(project);
    }
  }
  const fixture = <T,>(command: string, args: string[] = []): T => JSON.parse(docker([
    ...compose, "exec", "-T", "api", "python", "-m", fixtureModule, command, ...args,
  ]));
  const contract = fixture<{ hashes: Record<string, string>; source_sha256: string; cassette_key: string }>("contract");
  expect(contract.cassette_key).toBe("fb977e47e7dde573278d134ae98d89580cb2b6dbbcb847ac406d13d6600e20db");
  expect(contract.source_sha256).toBe(hash(sourceText));
  for (const [key, file] of Object.entries({
    consumer: "services/case_tracking_summary.py", worker: "workers/document_processor.py",
  })) {
    expect(contract.hashes[key], `Image must contain frozen ${file}`).toBe(hash(fs.readFileSync(
      path.join(repoRoot, "apps/api/src/caseops_api", file),
    )));
  }
  const build = await request.get(`${apiBaseUrl}/api/build`, { headers: noPaidProviderHeaders });
  expect(build.ok()).toBe(true);
  expect((await build.json()).release_sha).toBe(process.env.CASEOPS_RELEASE_SHA);
  record("image_verified", { api: api.Image, worker: worker.Image, contract });

  const contexts: BrowserContext[] = [];
  const ownedRunners: string[] = [];
  const cases: { scenario: Scenario; slug: string; seed: Seed; page: Page;
    headers: Record<string, string>; lifecycle: unknown; before: Inspection }[] = [];
  const missingMarkers: string[] = [];
  const paidActions: string[] = [];
  const override = info.outputPath("summary-worker.compose.json");
  fs.writeFileSync(override, JSON.stringify({ services: { worker: {
    cpus: 1, mem_limit: "2g", memswap_limit: "2g",
  } } }));
  const inspect = (seed: Seed) => fixture<Inspection>("inspect", [
    "--actor-id", seed.actor_id, "--update-id", seed.update_id,
  ]);
  const lifecycle = async (matterId: string, headers: Record<string, string>) => {
    const response = await request.get(`${apiBaseUrl}/api/matters/${matterId}`, { headers });
    expect(response.ok(), await response.text()).toBe(true);
    const matter = await response.json();
    return { status: matter.status, is_active: matter.is_active, lifecycle_version: matter.lifecycle_version };
  };
  const openUpdate = async (page: Page, seed: Seed) => {
    await page.goto(`${webBaseUrl}/app/case-tracking`);
    await page.getByTestId(`case-tracking-bookmark-${seed.bookmark_id}`).getByRole("button").first().click();
    return page.getByTestId(`case-tracking-update-${seed.update_id}`);
  };
  try {
    if (worker.State.Running) docker([...compose, "stop", "--timeout", "30", "worker"]);
    expect(service("worker").State.Running).toBe(false);
    record("worker_paused", { was_running: worker.State.Running });
    for (const scenario of ["positive", "marked", "persistent_qa"] as const) {
      const suffix = randomUUID().replaceAll("-", "");
      const slug = `${scenario === "persistent_qa" ? "summarypersistent" : "summaryacceptance"}-${suffix}`;
      const email = `summary-${suffix}@example.com`;
      const password = "SummarySep10Local!";
      const boot = await request.post(`${apiBaseUrl}/api/bootstrap/company`, {
        headers: noPaidProviderHeaders,
        data: { company_name: `Summary ${scenario} ${suffix}`, company_slug: slug, company_type: "law_firm",
          owner_full_name: "Summary acceptance", owner_email: email, owner_password: password },
      });
      expect(boot.status(), await boot.text()).toBe(200);
      const identity = await boot.json();
      const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` };
      const billing = await request.get(`${apiBaseUrl}/api/billing/current`, { headers });
      expect(billing.ok(), await billing.text()).toBe(true);
      expect((await billing.json()).subscription.plan_code).toBe("grandfathered_free");
      const created = await request.post(`${apiBaseUrl}/api/matters/`, { headers,
        data: { title: `Summary worker ${scenario}`, matter_code: `SUM-${suffix.slice(0, 8)}`,
          practice_area: "litigation", forum_level: "high_court", status: "intake" } });
      expect(created.status(), await created.text()).toBe(200);
      const matterId = (await created.json()).id as string;
      const originalLifecycle = await lifecycle(matterId, headers);
      expect(originalLifecycle.status).toBe("intake");
      expect(originalLifecycle.is_active).toBe(true);
      expect(typeof originalLifecycle.lifecycle_version).toBe("number");
      const seed = fixture<Seed>("seed", ["--actor-id", identity.membership.id,
        "--matter-id", matterId, "--scenario", scenario]);
      const before = inspect(seed);
      expect(before.summary).toBe(fallback);
      expect(before.ai_summary.summary_source).toBe("provider");
      expect(before.model_run_id).toBeNull();
      expect(before.runs).toEqual([]);
      expect(before.effects).toEqual([]);
      expect(before.event.no_paid_providers).toBe(scenario === "marked");
      expect(before.event.attempts).toBe(0);
      expect(before.provider_operations).toBe(0);
      expect(before.spend_reservations).toBe(0);
      const context = await browser.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
      contexts.push(context);
      context.on("request", req => {
        const url = new URL(req.url());
        if (!url.pathname.startsWith("/api/")) return;
        if (req.headers()["x-caseops-automated-test"] !== "no-paid-providers") missingMarkers.push(url.pathname);
        if (req.method() === "POST" && /\/case-tracking\/(search|bookmarks\/[^/]+\/refresh)$/.test(url.pathname)) {
          paidActions.push(url.pathname);
        }
      });
      const page = await context.newPage();
      await page.goto(`${webBaseUrl}/sign-in`);
      await page.locator("#company-slug").fill(slug);
      await page.locator("#email").fill(email);
      await page.locator("#password").fill(password);
      const login = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
      await page.locator('button[type="submit"]').click();
      expect((await login).status()).toBe(200);
      await page.waitForURL(/\/app(?:[/?]|$)/);
      const row = await openUpdate(page, seed);
      await expect(row.getByText(fallback, { exact: true })).toBeVisible();
      await expect(row.getByText(generated, { exact: true })).toHaveCount(0);
      await page.screenshot({ path: info.outputPath(`${scenario}-before-worker.png`), fullPage: true });
      cases.push({ scenario, slug, seed, page, headers, lifecycle: originalLifecycle, before });
      record("fallback_visible", { scenario, seed, before, lifecycle: originalLifecycle });
    }

    const runWorker = (iteration: number) => {
      const name = `${project}-summary-${randomUUID().slice(0, 8)}`;
      const blockedSlug = cases.find(c => c.scenario === "persistent_qa")!.slug;
      ownedRunners.push(name);
      docker([...compose, "--file", override, "run", "--detach", "--no-deps", "--name", name,
        "--env", `CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS=caseops-qa,caseops-ip-qa,test-legal,${blockedSlug}`,
        "worker", "python", "-m", fixtureModule, "worker"]);
      const runner = inspectContainer(name);
      expect(runner.Image).toBe(api.Image);
      expect(Object.keys(runner.NetworkSettings.Networks).sort()).toEqual(
        Object.keys(worker.NetworkSettings.Networks).sort(),
      );
      expect(runner.Config.Env).toContain(`CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS=caseops-qa,caseops-ip-qa,test-legal,${blockedSlug}`);
      const exit = docker(["wait", name], 90_000);
      const logs = docker(["logs", name]);
      fs.writeFileSync(info.outputPath(`worker-${iteration}.log`), logs);
      const completed = inspectContainer(name);
      record("worker_complete", { iteration, image: completed.Image, id: completed.Id,
        exit, state: completed.State, logs });
      expect(exit, logs).toBe("0");
      expect(logs).toContain("case_summaries_processed=");
    };
    runWorker(1);
    const afterFirst = cases.map(c => inspect(c.seed));
    for (const [index, current] of cases.entries()) {
      const after = afterFirst[index];
      expect(after.event.state).toBe("succeeded");
      expect(after.event.attempts).toBe(1);
      expect(after.event.no_paid_providers).toBe(current.scenario === "marked");
      expect(after.provider_operations).toBe(current.before.provider_operations);
      expect(after.spend_reservations).toBe(current.before.spend_reservations);
      expect(after.source_sha256).toBe(hash(sourceText));
      if (current.scenario === "positive") {
        expect(after.summary).toBe(generated);
        expect(after.ai_summary).toMatchObject({ concise_summary: generated, summary_source: "caseops" });
        expect(after.runs).toEqual([{ id: after.model_run_id, status: "ok", provider: "mock",
          model: "caseops-mock-1", prompt_tokens: 80, completion_tokens: 40 }]);
        expect(after.effects).toEqual([{ state: "completed", result_type: "tracked_case_update", result_id: current.seed.update_id }]);
      } else {
        expect(after.summary).toBe(fallback);
        expect(after.model_run_id).toBeNull();
        expect(after.runs).toEqual([]);
        expect(after.effects).toEqual([{ state: "completed", result_type: "case_summary_suppressed",
          result_id: current.scenario === "marked" ? "automated_request" : "automated_worker_or_tenant" }]);
      }
      const response = await request.get(`${apiBaseUrl}/api/case-tracking/bookmarks/${current.seed.bookmark_id}/updates`, { headers: current.headers });
      expect(response.ok(), await response.text()).toBe(true);
      const update = (await response.json()).updates.find((item: { id: string }) => item.id === current.seed.update_id);
      const sourcePath = `/api/case-tracking/bookmarks/${current.seed.bookmark_id}/updates/${current.seed.update_id}/source`;
      expect(update.summary).toBe(after.summary);
      expect(update.ai_summary.concise_summary).toBe(after.summary);
      expect(update.source_url).toBe(sourcePath);
      expect(update.ai_summary.source_reference).toBe(sourcePath);
      for (const width of [393, 768, 1280]) {
        await current.page.setViewportSize({ width, height: 900 });
        await current.page.reload();
        const row = await openUpdate(current.page, current.seed);
        await expect(row.getByText(after.summary, { exact: true })).toBeVisible();
        const source = row.getByRole("link", { name: "Source", exact: true });
        await expect(source).toBeVisible();
        expect(new URL((await source.getAttribute("href"))!, apiBaseUrl).pathname).toBe(sourcePath);
        const bounds = await source.boundingBox();
        expect(bounds).not.toBeNull();
        expect(bounds!.x).toBeGreaterThanOrEqual(0);
        expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
        await expect(current.page.getByRole("alert").filter({ hasText: /failed|error|unable/i })).toHaveCount(0);
        await current.page.screenshot({ path: info.outputPath(`${current.scenario}-after-worker-${width}.png`), fullPage: true });
      }
      expect(await lifecycle(current.seed.matter_id, current.headers)).toEqual(current.lifecycle);
      record("published_or_suppressed", { scenario: current.scenario, after, update });
    }
    runWorker(2);
    expect(cases.map(c => inspect(c.seed))).toEqual(afterFirst);
    record("replay_unchanged", afterFirst);

    for (const current of cases) {
      const row = await openUpdate(current.page, current.seed);
      const source = row.getByRole("link", { name: "Source", exact: true });
      const response = await request.get((await source.getAttribute("href"))!, { headers: current.headers });
      expect(response.status(), await response.text()).toBe(200);
      expect(response.headers()["x-caseops-source-format"]).toBe("provider-document");
      expect(await response.text()).toBe(sourceText);
      expect(hash(await response.body())).toBe(hash(sourceText));
      const downloadEvent = current.page.waitForEvent("download");
      await source.click();
      const download = await downloadEvent;
      expect(await download.failure()).toBeNull();
      const downloadedPath = info.outputPath(`${current.scenario}-source.md`);
      await download.saveAs(downloadedPath);
      expect(hash(fs.readFileSync(downloadedPath))).toBe(hash(sourceText));
      expect(await lifecycle(current.seed.matter_id, current.headers)).toEqual(current.lifecycle);
    }
    expect(missingMarkers).toEqual([]);
    expect(paidActions).toEqual([]);
    record("completed", { scenarios: cases.map(c => c.scenario), worker_external_egress: false,
      missing_markers: missingMarkers, browser_paid_actions: paidActions });
  } finally {
    for (const name of ownedRunners) {
      const state = spawnSync("docker", ["inspect", name], { encoding: "utf8", timeout: 15_000 });
      if (state.status === 0 && (JSON.parse(state.stdout)[0] as Container).State.Running) {
        docker(["stop", "--time", "10", name]);
      }
      if (state.status === 0) {
        const logs = docker(["logs", name]);
        fs.writeFileSync(info.outputPath(`${name}-final.log`), logs);
        record("runner_retained", { name, state: inspectContainer(name).State, logs });
      }
    }
    for (const context of contexts) await context.close();
    if (worker.State.Running) docker([...compose, "start", "worker"]);
    record("cleanup", { service_worker_restored: worker.State.Running, retained_runners: ownedRunners });
    await info.attach("summary-boundary-journal", { path: journal, contentType: "application/x-ndjson" });
  }
});
