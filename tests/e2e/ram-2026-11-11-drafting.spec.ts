import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

import { devices, expect, request, test, type APIRequestContext } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { localTransportHeaders } from "./support/cost-controls";
import { runId } from "./support/run-id";
import { productionDraftPdfJourney } from "./support/draft_pdf_production_20261111";
import { assertDraftPdfRender } from "./support/draft_pdf_render_proof_20261111";
import type { DraftPdfProfile } from "./support/draft_pdf_oracle_20261111";

const sha256 = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
async function json(api: APIRequestContext, url: string, method = "GET", data?: object) {
  const response = await api.fetch(url, { method, data, maxRetries: 0, maxRedirects: 0 });
  expect(response.status(), `${method} ${new URL(url).pathname}: ${await response.text()}`).toBe(200);
  return response.json();
}

for (const phone of [false, true]) test(`BUG001 2026-11-11 ${phone ? "[mobile] phone" : "desktop"}: persisted draft PDF preview and export parity`, {
  annotation: { type: "caseops-b5-proof", description: "retained-readonly" },
}, async ({ browser, baseURL }, info) => {
  if (baseURL && !["127.0.0.1", "localhost", "[::1]"].includes(new URL(baseURL).hostname)) {
    await productionDraftPdfJourney(browser, baseURL, info, phone);
    return;
  }
  if (!baseURL || ![baseURL, apiBaseUrl].every(value => {
    const url = new URL(value);
    return url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
  })) throw new Error("This synthetic fixture is strictly loopback-only.");
  const run = runId(), slug = `b5draft-${run}`, email = `${slug}@example.com`, password = `Synthetic!${run}aA9`;
  const api = await request.newContext({ extraHTTPHeaders: localTransportHeaders(apiBaseUrl) });
  const context = await browser.newContext({ ...(phone ? devices["Pixel 5"] : { viewport: { width: 1280, height: 1000 } }),
    baseURL, extraHTTPHeaders: localTransportHeaders(baseURL) });
  const page = await context.newPage();
  let modelCalls = 0;
  let pdfActionAllowed = false, passiveExports = 0;
  try {
    const tenant = await json(api, `${apiBaseUrl}/api/bootstrap/company`, "POST", {
      company_name: "Synthetic PDF parity fixture", company_slug: slug, company_type: "law_firm",
      owner_full_name: "Synthetic owner", owner_email: email, owner_password: password,
    });
    const auth = await request.newContext({ extraHTTPHeaders: { ...localTransportHeaders(apiBaseUrl), Authorization: `Bearer ${tenant.access_token}` } });
    try {
      const matter = await json(auth, `${apiBaseUrl}/api/matters/`, "POST", { title: "Synthetic regular bail layout",
        matter_code: `B5PDF-${run}`, practice_area: "Criminal", forum_level: "high_court", status: "intake", court_name: "Delhi High Court" });
      const draft = await json(auth, `${apiBaseUrl}/api/matters/${matter.id}/drafts`, "POST", {
        title: "Synthetic regular bail application", draft_type: "brief", template_type: "bail",
      });
      const python = process.env.CASEOPS_E2E_PYTHON || path.join(repoRoot, "apps/api/.venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
      const seeded = spawnSync(python, [path.join(repoRoot, "tests/e2e/support/draft_pdf_fixture_20261111.py")], {
        cwd: repoRoot, encoding: "utf8", timeout: 30_000,
        env: { ...process.env, ...e2eEnv, CASEOPS_LLM_PROVIDER: "mock", PYTHONPATH: path.join(repoRoot, "apps/api/src") },
        input: JSON.stringify({ web: baseURL, api: apiBaseUrl, run, company_id: tenant.company.id,
          membership_id: tenant.membership.id, matter_id: matter.id, draft_id: draft.id }),
      });
      expect(seeded.status, `${seeded.stdout}\n${seeded.stderr}`).toBe(0);
      const fixture = JSON.parse(seeded.stdout);
      const draftApi = `${apiBaseUrl}/api/matters/${matter.id}/drafts/${draft.id}`;
      for (const action of ["submit", "approve"]) await json(auth, `${draftApi}/${action}`, "POST", {});
      const before = await json(auth, draftApi);
      expect(before.status).toBe("approved");
      expect(before.versions[0].body).toBe(fixture.body);
      expect(before.reviews.some((row: { action: string; version_id: string }) => row.action === "approve" && row.version_id === fixture.version_id)).toBe(true);
      await context.route("**/*", async route => {
        const req = route.request(), url = new URL(req.url());
        if (url.origin === new URL(apiBaseUrl).origin && url.pathname.endsWith("/export.pdf") && !pdfActionAllowed) {
          passiveExports++;
          await route.abort("blockedbyclient");
          return;
        }
        if (![new URL(baseURL).origin, new URL(apiBaseUrl).origin].includes(url.origin) && !url.protocol.startsWith("blob")) throw new Error("External network forbidden.");
        if (url.origin === new URL(apiBaseUrl).origin && req.method() !== "OPTIONS") {
          expect(req.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
        }
        if (/\/(generate|preview)$/.test(url.pathname) && req.method() === "POST") {
          modelCalls++;
          throw new Error("Model generation forbidden in PDF acceptance.");
        }
        await route.continue();
      });
      await page.goto("/sign-in");
      await page.locator("#company-slug").fill(slug);
      await page.locator("#email").fill(email);
      await page.locator("#password").fill(password);
      await page.getByRole("button", { name: /^Sign in$/ }).click();
      await page.waitForURL(/\/app(?:[/?]|$)/);
      const pdfResponses: Array<{ url: string; bytes: Buffer; profile: string }> = [];
      page.on("response", async response => {
        if (new URL(response.url()).pathname.endsWith("/export.pdf") && response.status() === 200) {
          pdfResponses.push({ url: response.url(), bytes: await response.body(), profile: response.headers()["x-caseops-court-profile"] });
        }
      });
      await page.goto(`/app/matters/${matter.id}/drafts/${draft.id}`);
      await expect(page.getByTestId("draft-body-readonly")).toHaveText(fixture.body);
      expect(passiveExports).toBe(0);
      expect(pdfResponses).toHaveLength(0);
      pdfActionAllowed = true;
      await page.getByRole("tab", { name: "PDF preview" }).click();
      await expect(page.getByText("Court-profile rules are unverified for filing. Lawyer review is required.")).toBeVisible();
      await expect.poll(() => pdfResponses.length).toBe(1);
      const catalogue = await json(auth, `${apiBaseUrl}/api/drafting/court-profiles`) as { profiles: Array<DraftPdfProfile & { key: string }> };
      const profileFor = (key: string) => {
        const profile = catalogue.profiles.find(row => row.key === key);
        if (!profile) throw new Error("Export profile metadata is absent.");
        return profile;
      };
      const source = { title: before.title, body: fixture.body, citations: before.versions[0].citations, reviewRequired: before.review_required };
      const pages = await assertDraftPdfRender(page, profileFor(pdfResponses[0].profile), source);
      expect(pages).toBeGreaterThan(1);
      expect(new URL(pdfResponses[0].url).searchParams.get("version_id")).toBe(fixture.version_id);
      const downloadPromise = page.waitForEvent("download");
      const downloadButton = page.getByTestId("draft-download-pdf");
      await downloadButton.scrollIntoViewIfNeeded();
      const bounds = await downloadButton.boundingBox();
      expect(bounds && bounds.width > 40 && bounds.x >= 0 && bounds.x + bounds.width <= page.viewportSize()!.width).toBe(true);
      await downloadButton.click();
      const download = await downloadPromise, downloadedPath = info.outputPath("approved-draft.pdf");
      await download.saveAs(downloadedPath);
      const downloaded = await fs.readFile(downloadedPath);
      expect(sha256(downloaded)).toBe(sha256(pdfResponses[0].bytes));
      await expect.poll(() => pdfResponses.length).toBe(2);
      expect(sha256(pdfResponses[1].bytes)).toBe(sha256(pdfResponses[0].bytes));
      await page.getByTestId("court-profile-select").selectOption("generic");
      await expect.poll(() => pdfResponses.length).toBe(3);
      expect(new URL(pdfResponses[2].url).searchParams.get("court_profile")).toBe("generic");
      expect(new URL(pdfResponses[2].url).searchParams.get("version_id")).toBe(fixture.version_id);
      expect(pdfResponses[2].profile).toBe("generic");
      await assertDraftPdfRender(page, profileFor("generic"), source);
      const selectedDownload = page.waitForEvent("download");
      await page.getByTestId("draft-download-pdf").click();
      const selectedPath = info.outputPath("approved-draft-generic.pdf");
      await (await selectedDownload).saveAs(selectedPath);
      expect(sha256(await fs.readFile(selectedPath))).toBe(sha256(pdfResponses[2].bytes));
      await expect.poll(() => pdfResponses.length).toBe(4);
      expect(sha256(pdfResponses[3].bytes)).toBe(sha256(pdfResponses[2].bytes));
      pdfActionAllowed = false;
      await page.getByRole("tab", { name: "Draft text" }).click();
      await page.reload();
      await expect(page.getByTestId("draft-body-readonly")).toHaveText(fixture.body);
      expect(passiveExports).toBe(0);
      expect(pdfResponses).toHaveLength(4);
      pdfActionAllowed = true;
      await page.getByRole("tab", { name: "PDF preview" }).click();
      await expect.poll(() => pdfResponses.length).toBe(5);
      await assertDraftPdfRender(page, profileFor(pdfResponses[4].profile), source);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
      expect(await json(auth, draftApi)).toEqual(before);
      expect(modelCalls).toBe(0);
      await info.attach("pdf-parity", { body: JSON.stringify({ source: "local source worktree, not production acceptance", version: fixture.version_id,
        sha256: sha256(downloaded), pages, viewport: page.viewportSize(), noModelCalls: modelCalls }), contentType: "application/json" });
    } finally { await auth.dispose(); }
  } finally { await context.close(); await api.dispose(); }
});
