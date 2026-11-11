import { createHash } from "node:crypto";

import { devices, expect, type Browser, type Page, type Response, type TestInfo } from "@playwright/test";

import { authContext, draft as draftSchema, type Draft } from "../../../apps/web/lib/api/schemas";
import { noPaidProviderHeaders } from "./cost-controls";
import { assertPublicReleaseIdentity } from "./public-release-identity";
import { allowedProductionDraftRead, capturePdfDownloadsInMemory, citationReviewExportGuard, productionDraftRequestPolicy, productionDraftSettings } from "./draft_pdf_production_policy_20261111";

const hash = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");
const fingerprint = (draft: Draft) => hash(JSON.stringify(draft));
const mediaOff = (value: unknown) => value === "off";

async function renderedPages(page: Page) {
  await expect(page.getByTestId("draft-download-pdf")).toBeEnabled();
  await expect(page.locator("[data-testid=draft-pdf-preview] canvas")).toBeVisible();
  const pages = Number((await page.getByTestId("draft-pdf-pagination").innerText()).split(" of ")[1]);
  expect(Number.isInteger(pages) && pages >= 1 && pages <= 200, "Complete bounded PDF page inventory").toBe(true);
  for (let index = 1; index <= pages; index++) {
    await expect(page.getByTestId("draft-pdf-pagination")).toHaveText(`Page ${index} of ${pages}`);
    await expect(page.getByRole("region", { name: "PDF page canvas" })).toHaveAttribute("data-rendered-page", String(index));
    const canvas = page.locator("[data-testid=draft-pdf-preview] canvas");
    await canvas.scrollIntoViewIfNeeded();
    await expect.poll(() => canvas.evaluate(node => {
      const canvas = node as HTMLCanvasElement;
      const data = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
      let ink = 0;
      for (let offset = 0; offset < data.length; offset += 4) if (data[offset] < 200 && data[offset + 1] < 200 && data[offset + 2] < 200 && data[offset + 3] > 0) ink++;
      return ink;
    })).toBeGreaterThan(50);
    if (index < pages) await page.getByRole("button", { name: "Next PDF page" }).click();
  }
  return pages;
}

export async function productionDraftPdfJourney(browser: Browser, baseURL: string, info: TestInfo, phone: boolean) {
  let stage = "configuration", failure: string | undefined;
  let parityUnverified = false;
  const settings = productionDraftSettings(baseURL, process.env);
  expect(info.config.workers, "Production mutation boundaries are serialized").toBe(1);
  expect(info.project.retries).toBe(0);
  expect([info.project.use.trace, info.project.use.screenshot, info.project.use.video].every(mediaOff),
    "Production trace/screenshot/video must be explicitly off").toBe(true);
  const context = await browser.newContext({ ...(phone ? devices["Pixel 5"] : { viewport: { width: 1280, height: 1000 } }),
    baseURL: settings.web, storageState: { cookies: [], origins: [] }, serviceWorkers: "block",
    acceptDownloads: false, extraHTTPHeaders: noPaidProviderHeaders });
  const page = await context.newPage();
  let logins = 0, nativeDownloads = 0, blockedExternal = 0;
  const violations = new Set<string>();
  const draftPath = `/api/matters/${settings.matterId}/drafts/${settings.draftId}`;
  const exportPath = `${draftPath}/export.pdf`;
  const release = () => assertPublicReleaseIdentity([`${settings.api}/api/build`, `${settings.web}/api/release-identity`], settings.sha);
  const receipt = () => page.waitForResponse(response => new URL(response.url()).origin === settings.api
    && new URL(response.url()).pathname === exportPath && response.request().method() === "GET");
  const read = async (pathname: string) => {
    if (!allowedProductionDraftRead(pathname)) throw new Error("Production read is not allowlisted.");
    const response = await page.request.get(`${settings.api}${pathname}`, { headers: noPaidProviderHeaders,
      maxRetries: 0, maxRedirects: 0, timeout: 30_000 });
    expect(response.status(), "Authorized retained-record GET").toBe(200);
    return response.json();
  };
  const readDraft = async () => {
    const parsed = draftSchema.safeParse(await read(draftPath));
    if (!parsed.success) throw new Error("Retained draft contract rejected.");
    return parsed.data;
  };
  await context.addInitScript(capturePdfDownloadsInMemory);
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url()), method = request.method();
    const decision = productionDraftRequestPolicy(url.href, method, request.headers()["x-caseops-automated-test"], settings);
    if (decision === "external") { blockedExternal++; return route.abort("blockedbyclient"); }
    if (decision === "blocked" || (decision === "login" && ++logins > 1)) {
      violations.add("prohibited-operation-or-missing-marker");
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  page.on("download", () => { nativeDownloads++; });
  try {
    stage = "release-before-login";
    await release();
    stage = "reporter-login";
    const listPath = `/app/matters/${settings.matterId}/drafts`;
    await page.goto(`${settings.web}/sign-in?next=${encodeURIComponent(listPath)}`);
    await page.locator("#company-slug").fill(settings.slug);
    await page.locator("#email").fill(settings.email);
    await page.locator("#password").fill(settings.password);
    const signed = page.waitForResponse(response => new URL(response.url()).pathname === "/api/auth/login" && response.request().method() === "POST");
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    expect((await signed).status(), "Reporter login").toBe(200);
    await page.waitForURL(url => url.origin === settings.web && url.pathname.replace(/\/$/, "") === listPath);
    stage = "authorized-persisted-version";
    const actor = authContext.safeParse(await read("/api/auth/me"));
    if (!actor.success) throw new Error("Reporter identity contract rejected.");
    expect(actor.data.company.slug === settings.slug && actor.data.user.email.toLowerCase() === settings.email.toLowerCase()
      && actor.data.company.is_active && actor.data.user.is_active && actor.data.membership.is_active, "Exact active reporting actor").toBe(true);
    const before = await readDraft();
    expect(before.id === settings.draftId && before.matter_id === settings.matterId && before.company_id === actor.data.company.id,
      "Exact reported draft and tenant").toBe(true);
    const version = before.versions.find(row => row.id === before.current_version_id);
    if (!version) throw new Error("Persisted current version is absent.");
    const unchanged = async () => expect(fingerprint(await readDraft()) === fingerprint(before), "Retained content and review state remain unchanged").toBe(true);
    const pinned = async (response: Response, profile?: string) => {
      expect(await response.finished(), "PDF transport completes").toBeNull();
      const url = new URL(response.url());
      expect(url.searchParams.get("version_id") === version.id, "Export pins the authorized persisted version").toBe(true);
      expect(url.searchParams.get("court_profile") === (profile ?? null), "Export pins the visible profile selection").toBe(true);
    };
    stage = "initial-preview";
    const initialPdf = receipt();
    await page.goto(`${settings.web}/app/matters/${settings.matterId}/drafts/${settings.draftId}`);
    await expect(page.getByTestId("draft-current-revision")).toHaveText(`Revision ${version.revision}`);
    expect(await page.getByTestId("draft-body-readonly").textContent() === version.body, "Visible text is retained source content").toBe(true);
    await page.getByRole("tab", { name: "PDF preview" }).click();
    const initial = await initialPdf;
    await pinned(initial);
    if (initial.status() !== 200) {
      stage = `export-http-${initial.status()}`;
      expect(citationReviewExportGuard(initial.status(), await initial.json().catch(() => null), before.status, version.verified_citation_count),
        "Only the existing citation/review refusal qualifies as a verified guard").toBe(true);
      stage = "citation-review-guard";
      await expect(page.getByRole("alert").filter({ hasText: "zero verified citations" })).toBeVisible();
      await expect(page.getByTestId("draft-download-pdf")).toBeDisabled();
      await expect(page.locator("[data-testid=draft-pdf-preview] canvas")).toHaveCount(0);
      await unchanged();
      await release();
      expect(violations.size === 0 && logins === 1 && nativeDownloads === 0, "Read-only production boundary").toBe(true);
      await info.attach("bug001-production-parity", { body: JSON.stringify({ outcome: "PARITYUNVERIFIED", reason: "existing-citation-review-guard", httpStatus: initial.status(), sha: settings.sha }), contentType: "application/json" });
      parityUnverified = true;
      throw new Error("PARITYUNVERIFIED");
    }
    const checkedPdf = async (response: Response, profile?: string) => {
      await pinned(response, profile);
      expect(response.status(), "Authorized read-only PDF export").toBe(200);
      expect((await response.headerValue("content-type"))?.split(";")[0]).toBe("application/pdf");
      const resolvedProfile = await response.headerValue("x-caseops-court-profile");
      expect(Boolean(resolvedProfile && /^[a-z0-9_]{1,80}$/.test(resolvedProfile)), "Resolved export profile identity").toBe(true);
      if (profile) expect(resolvedProfile).toBe(profile);
      else await expect(page.getByTestId("court-profile-select").locator(`option[value="${resolvedProfile}"]`)).toHaveCount(1);
      const bytes = await response.body();
      expect(bytes.subarray(0, 5).equals(Buffer.from("%PDF-")), "Real PDF bytes").toBe(true);
      return { hash: hash(bytes), bytes: bytes.length, profile: resolvedProfile };
    };
    const memoryDownload = async (expected: { hash: string; bytes: number }, count: number, profile?: string) => {
      const checked = receipt();
      const button = page.getByTestId("draft-download-pdf");
      await button.scrollIntoViewIfNeeded();
      await expect(button).toBeEnabled();
      const bounds = await button.boundingBox();
      expect(Boolean(bounds && bounds.width >= 40 && bounds.x >= 0 && bounds.x + bounds.width <= page.viewportSize()!.width + 1), "Visible usable download control").toBe(true);
      await button.click();
      const fresh = await checkedPdf(await checked, profile);
      expect(fresh.hash === expected.hash, "Reauthorization preserves displayed bytes").toBe(true);
      await expect.poll(() => page.evaluate(() => (window as unknown as { __bug001Download: { count: number; hash: string | null; bytes: number; invalid: boolean } }).__bug001Download))
        .toEqual({ count, hash: expected.hash, bytes: expected.bytes, invalid: false });
    };
    stage = "auto-profile-parity";
    const auto = await checkedPdf(initial);
    const autoPages = await renderedPages(page);
    await memoryDownload(auto, 1);
    stage = "selected-profile-parity";
    await expect(page.getByTestId("court-profile-select").locator('option[value="generic"]')).toHaveCount(1);
    const selectedPdf = receipt();
    await page.getByTestId("court-profile-select").selectOption("generic");
    const selected = await checkedPdf(await selectedPdf, "generic");
    expect(auto.profile === "generic" || selected.hash !== auto.hash, "A different resolved preset changes the exported snapshot").toBe(true);
    const selectedPages = await renderedPages(page);
    await memoryDownload(selected, 2, "generic");
    stage = "reload-parity";
    const reloadedPdf = receipt();
    await page.reload();
    await expect(page.getByTestId("draft-current-revision")).toHaveText(`Revision ${version.revision}`);
    expect(await page.getByTestId("draft-body-readonly").textContent() === version.body, "Reload preserves source content").toBe(true);
    await page.getByRole("tab", { name: "PDF preview" }).click();
    expect((await checkedPdf(await reloadedPdf)).hash === auto.hash, "Reload preserves automatic-profile bytes").toBe(true);
    expect(await renderedPages(page)).toBe(autoPages);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "No page-width overflow").toBe(true);
    await unchanged();
    await release();
    expect(violations.size === 0 && logins === 1 && nativeDownloads === 0, "Read-only production boundary").toBe(true);
    await info.attach("bug001-production-parity", { body: JSON.stringify({ outcome: "READ_ONLY_PARITY_VERIFIED", sha: settings.sha,
      autoHash: auto.hash, selectedHash: selected.hash, autoPages, selectedPages, blockedExternal,
      autoProfile: auto.profile, selectedProfile: selected.profile,
      nativeDownloadSuppressed: true, legalSuitability: "UNVERIFIED" }), contentType: "application/json" });
  } catch {
    failure = parityUnverified ? "BUG001 PARITYUNVERIFIED: the existing citation/review guard blocks export; no production record was changed."
      : `BUG001 production read-only parity failed at ${stage}; private details omitted.`;
  } finally {
    try { await context.close(); } catch { failure ??= "BUG001 production browser cleanup failed; private details omitted."; }
  }
  if (failure) throw new Error(failure);
}
