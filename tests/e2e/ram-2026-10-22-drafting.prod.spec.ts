/** J07/M06: retained control-state reads only, not generation or approval acceptance. */
import { createHash } from "node:crypto";
import type { APIResponse, Page, Response } from "@playwright/test";
import { authContext, draft as draftSchema, type Draft } from "../../apps/web/lib/api/schemas";
import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";

test.use({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: noPaidProviderHeaders,
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ mode: "serial", retries: 0 });

type RetainedFixture = { draftId: string; matterId: string; status: "finalized" | "draft"; count: number };
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; retained production evidence cannot be replaced or skipped.`);
  return value;
}

function retainedId(name: string, knownPrefix: string): string {
  const value = required(name);
  if (!uuid.test(value) || !value.startsWith(knownPrefix)) {
    throw new Error(`${name} must identify the exact known retained QA record; no fixture discovery or creation.`);
  }
  return value;
}

function origin(value: string, expected: string): URL {
  const url = new URL(value);
  if (url.origin !== expected || url.pathname !== "/" || url.username || url.password || url.search || url.hash) {
    throw new Error("Read-only draft acceptance requires the canonical production origins.");
  }
  return url;
}

async function json(response: Pick<APIResponse, "status" | "json">, label: string): Promise<unknown> {
  expect(response.status(), `${label} must succeed without retry or redirect`).toBe(200);
  try { return await response.json(); }
  catch { throw new Error(`${label} JSON could not be read; private response omitted.`); }
}

function parseDraft(value: unknown): Draft {
  const parsed = draftSchema.safeParse(value);
  if (!parsed.success) throw new Error("Retained draft does not match the current frontend contract; private response omitted.");
  return parsed.data;
}

function fingerprint(value: Draft): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function assertRetained(value: Draft, fixture: RetainedFixture, companyId: string): void {
  expect(value.id === fixture.draftId && value.matter_id === fixture.matterId && value.company_id === companyId,
    "Retained draft belongs to the exact authenticated QA company and supplied Matter").toBe(true);
  expect(value.template_type === "appeal_memorandum", "Retained record is the known Appeal template").toBe(true);
  expect(value.status).toBe(fixture.status);
  const current = value.versions.find(version => version.id === value.current_version_id);
  expect(Boolean(current), "The exact retained current revision must exist").toBe(true);
  expect(current?.verified_citation_count).toBe(fixture.count);
  expect(value.review_required).toBe(fixture.status !== "finalized");
}

async function controls(page: Page, value: Draft, fixture: RetainedFixture): Promise<void> {
  const current = value.versions.find(version => version.id === value.current_version_id)!;
  await expect(page.getByTestId("draft-current-revision")).toHaveText(`Revision ${current.revision}`);
  await expect(page.getByTestId("draft-body-readonly")).toBeVisible();
  expect(await page.getByTestId("draft-body-readonly").textContent() === current.body,
    "Visible body is the exact retained current revision; text is not retained in test evidence").toBe(true);
  await expect(page.getByText(`${fixture.count} verified citation${fixture.count === 1 ? "" : "s"}.`,
    { exact: true })).toBeVisible();
  await expect(page.getByText("Citation verification confirms catalogue records, not the correctness of legal propositions.",
    { exact: true })).toBeVisible();
  await expect(page.getByTestId("draft-citation-status")).toHaveCount(0);
  for (const id of ["draft-download-docx", "draft-download-pdf", "draft-download-filing-bundle"]) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
  for (const id of ["draft-approve", "draft-finalize", "draft-request-changes", "draft-save-edit", "draft-body-editor"]) {
    await expect(page.getByTestId(id)).toHaveCount(0);
  }
  if (fixture.status === "finalized") {
    await expect(page.getByTestId("draft-generate")).toBeDisabled();
    await expect(page.getByTestId("draft-submit")).toHaveCount(0);
    await expect(page.getByTestId("draft-edit-toggle")).toHaveCount(0);
    await expect(page.getByLabel("Regeneration focus", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Matter context", exact: true })).toHaveCount(0);
  } else {
    await expect(page.getByTestId("draft-generate")).toBeEnabled();
    await expect(page.getByTestId("draft-submit")).toBeEnabled();
    await expect(page.getByTestId("draft-edit-toggle")).toBeEnabled();
    await expect(page.getByLabel("Regeneration focus", { exact: true })).toBeEditable();
    await expect(page.getByLabel("Regeneration focus", { exact: true })).toHaveValue("");
    expect(await page.getByRole("link", { name: "Matter context", exact: true }).getAttribute("href")
      === `/app/matters/${fixture.matterId}`, "Matter context retains the exact parent; link is not followed").toBe(true);
  }
}

test("B3-DRAFT-PROD read-only retained finalized and mutable Appeal controls persist after reload", async ({ page, baseURL }, info) => {
  if (!baseURL) throw new Error("Use the production verification config.");
  expect(info.config.workers).toBe(1);
  expect(info.config.fullyParallel).toBe(false);
  expect(info.project.retries).toBe(0);
  expect(info.project.dependencies).toEqual([]);
  const web = origin(baseURL, "https://caseops.ai");
  const api = origin(required("PROD_API_BASE_URL"), "https://api.caseops.ai");
  const sha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const credentials = { company_slug: required("CASEOPS_RAM_PROD_SLUG"),
    email: required("CASEOPS_RAM_PROD_EMAIL"), password: required("CASEOPS_RAM_PROD_PASSWORD") };
  if (credentials.company_slug !== "test-legal") throw new Error("Retained draft reads are test-legal only, never GBA.");
  const fixtures: RetainedFixture[] = [
    { draftId: retainedId("CASEOPS_RAM_BATCH3_FINALIZED_DRAFT_ID", "622b"),
      matterId: retainedId("CASEOPS_RAM_BATCH3_FINALIZED_MATTER_ID", "1795"), status: "finalized", count: 1 },
    { draftId: retainedId("CASEOPS_RAM_BATCH3_MUTABLE_DRAFT_ID", "ecfe"),
      matterId: retainedId("CASEOPS_RAM_BATCH3_MUTABLE_MATTER_ID", "8c1"), status: "draft", count: 3 },
  ];
  const release = () => assertPublicReleaseIdentity(
    [`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha,
  );
  const violations = new Set<string>();
  let logins = 0;
  await page.context().route("**/*", async route => {
    const pending = route.request(), url = new URL(pending.url()), method = pending.method();
    const localOrigin = url.origin === web.origin || url.origin === api.origin;
    const marked = method === "OPTIONS" || pending.headers()["x-caseops-automated-test"] === "no-paid-providers";
    const login = url.origin === api.origin && url.pathname === "/api/auth/login" && method === "POST";
    const safeRead = ["GET", "HEAD", "OPTIONS"].includes(method);
    const prohibited = url.origin === api.origin && /(?:\/(?:export(?:[./]|$)|filing-bundle|generate(?:\/|$)|download(?:\/|$))|\/api\/(?:authorities\/providers|case-tracking\/providers|assistant)(?:\/|$))/.test(url.pathname);
    if (!localOrigin || !marked || prohibited || (!safeRead && !login) || (login && ++logins > 1)) {
      violations.add(!localOrigin ? "external-origin" : !marked ? "missing-no-paid-marker" : "prohibited-operation");
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  page.on("download", () => violations.add("unexpected-download"));
  info.annotations.push({ type: "coverage-boundary",
    description: "Read-only control states and retained catalogue counts only. No generation, approval, finalization, export, or legal-grounding certification." });
  const read = async (pathname: string): Promise<unknown> => {
    let receipt: APIResponse;
    try { receipt = await page.request.get(`${api.origin}${pathname}`, {
      headers: noPaidProviderHeaders, maxRetries: 0, maxRedirects: 0, timeout: 30_000,
    }); }
    catch { throw new Error("Retained QA GET transport failed; no retry; private details omitted."); }
    return json(receipt, "Retained QA GET");
  };
  await release();
  try {
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.goto(`${web.origin}/sign-in`);
    await page.locator("#company-slug").fill(credentials.company_slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    const signed = page.waitForResponse(receipt => new URL(receipt.url()).origin === api.origin
      && new URL(receipt.url()).pathname === "/api/auth/login" && receipt.request().method() === "POST");
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    const login = await signed;
    expect(login.status(), "Normal browser QA login").toBe(200);
    expect(await login.finished(), "Normal browser login response completes").toBeNull();
    await page.waitForURL(/\/app(?:[/?]|$)/);
    const parsed = authContext.safeParse(await read("/api/auth/me"));
    if (!parsed.success) throw new Error("Browser QA context does not match the current contract; private response omitted.");
    const actor = parsed.data;
    expect(actor.company.slug === "test-legal" && actor.company.is_active && actor.membership.is_active
      && actor.user.is_active && actor.user.email === credentials.email, "Normal browser owns the intended active QA context").toBe(true);
    for (const capability of ["drafts:generate", "drafts:edit", "drafts:review", "drafts:finalize"]) {
      expect(actor.capabilities?.includes(capability), `QA actor requires ${capability} to distinguish lifecycle from role gating`).toBe(true);
    }
    const baselines = new Map<string, string>();
    for (const fixture of fixtures) {
      const pathname = `/api/matters/${fixture.matterId}/drafts/${fixture.draftId}`;
      const baseline = parseDraft(await read(pathname));
      assertRetained(baseline, fixture, actor.company.id);
      baselines.set(fixture.draftId, fingerprint(baseline));
      for (const stage of ["initial", "reload"] as const) {
        const received = page.waitForResponse(receipt => new URL(receipt.url()).origin === api.origin
          && new URL(receipt.url()).pathname === pathname && receipt.request().method() === "GET");
        if (stage === "initial") await page.goto(`${web.origin}/app/matters/${fixture.matterId}/drafts/${fixture.draftId}`);
        else await page.reload();
        const receipt: Response = await received;
        expect(await receipt.finished(), "Bound browser draft response completes before another navigation").toBeNull();
        const rendered = parseDraft(await json(receipt, "Browser retained draft"));
        assertRetained(rendered, fixture, actor.company.id);
        expect(fingerprint(rendered) === baselines.get(fixture.draftId), "Browser reload preserves all retained versions and review state").toBe(true);
        await controls(page, rendered, fixture);
      }
    }
    for (const fixture of fixtures) {
      const retained = parseDraft(await read(`/api/matters/${fixture.matterId}/drafts/${fixture.draftId}`));
      expect(fingerprint(retained) === baselines.get(fixture.draftId), "Both retained QA drafts remain byte-equivalent in their canonical DTOs").toBe(true);
    }
    expect(logins, "One normal browser login, no API fixture login or session replacement").toBe(1);
    expect([...violations], "No workflow writes, exports, paid-provider routes, external requests or downloads").toEqual([]);
  } finally {
    await release();
  }
});
