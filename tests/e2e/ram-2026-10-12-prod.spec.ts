/** J10/M09/FT-051/052: all four contract AI actions, at zero external cost. */
import { randomUUID } from "node:crypto";
import type { APIRequestContext, Locator, Page, Response } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";
import { runDocumentWorkerOnce } from "./support/helpers";
import { terminateContract } from "./support/retire-records";

test.use({ extraHTTPHeaders: noPaidProviderHeaders, storageState: { cookies: [], origins: [] },
  trace: "off", screenshot: "off", video: "off" });
test.describe.configure({ retries: 0 });
test.setTimeout(300_000);

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing acceptance setup is not a skip.`);
  return value;
}
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const SOURCE = "Acme India shall pay Supplier India by 20 October 2026.";

async function assertContractTabsReachable(page: Page) {
  const tabs = page.getByRole("tablist").getByRole("tab");
  await expect(tabs).toHaveCount(8);
  for (const tab of await tabs.all()) {
    await expect(tab).toBeVisible();
    await expect(tab).toBeEnabled();
    await tab.scrollIntoViewIfNeeded();
    const geometry = await tab.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      const list = element.closest('[role="tablist"]')!.getBoundingClientRect();
      const hit = document.elementFromPoint(
        bounds.left + bounds.width / 2, bounds.top + bounds.height / 2,
      );
      return {
        label: element.textContent,
        width: bounds.width,
        contained: bounds.left >= list.left - 1 && bounds.right <= list.right + 1
          && bounds.top >= list.top - 1 && bounds.bottom <= list.bottom + 1,
        withinViewport: bounds.left >= 0 && bounds.right <= window.innerWidth + 1,
        ownsPointer: hit !== null && (hit === element || element.contains(hit)),
      };
    });
    expect(geometry.width, `${geometry.label} has useful width`).toBeGreaterThan(24);
    expect(geometry.contained, `${geometry.label} remains inside its tablist`).toBe(true);
    expect(geometry.withinViewport, `${geometry.label} remains visible horizontally`).toBe(true);
    expect(geometry.ownsPointer, `${geometry.label} is not covered by its panel`).toBe(true);
  }
}

for (const width of [1280, 393]) {
  test.describe(`Contract AI source preservation at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 }, isMobile: width === 393, hasTouch: width === 393 });
    test("extract, replace only auto rows, reload and compare through all four actions", async ({ page, request, baseURL }) => {
      if (!baseURL) throw new Error("Use the app, Docker or exact-release production config.");
      const web = new URL(baseURL);
      const local = loopback(web);
      const api = new URL(local ? apiBaseUrl : required("PROD_API_BASE_URL"));
      if (local !== loopback(api)) throw new Error("Mixed live/local endpoints are forbidden.");
      if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
        throw new Error("Only canonical production origins are authorized.");
      }
      const sha = local ? required("CASEOPS_RELEASE_SHA") : required("CASEOPS_EXPECTED_RELEASE_SHA");
      expect(sha).toMatch(/^[a-f0-9]{40}$/);
      async function release(client: APIRequestContext) {
        for (const endpoint of [`${api.origin}/api/build`, `${web.origin}/api/release-identity`]) {
          const response = await client.get(endpoint, { headers: noPaidProviderHeaders });
          expect(response.status(), "exact API/web serving identity").toBe(200);
          expect((await response.json()).release_sha).toBe(sha);
        }
      }
      await release(request);
      const run = randomUUID().slice(0, 8);
      const credentials = local
        ? { slug: `contract-ai-${run}`, email: `owner-${run}@example.com`, password: `Contract!${randomUUID()}` }
        : { slug: required("CASEOPS_NOTICE_QA_SLUG"), email: required("CASEOPS_NOTICE_OWNER_EMAIL"),
            password: required("CASEOPS_NOTICE_OWNER_PASSWORD") };
      if (!local && !["test-legal", "caseops-qa"].includes(credentials.slug)) {
        throw new Error("Only authorized QA tenants may be mutated, never GBA or real-client tenants.");
      }
      if (local) {
        const bootstrap = await request.post(`${api.origin}/api/bootstrap/company`, {
          headers: noPaidProviderHeaders,
          data: { company_name: `Contract AI acceptance ${run}`, company_slug: credentials.slug,
            company_type: "law_firm", owner_full_name: "Offline contract owner",
            owner_email: credentials.email, owner_password: credentials.password },
        });
        expect(bootstrap.status(), "loopback-only fixture bootstrap").toBe(200);
      }
      const login = await request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
        data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
      expect(login.status(), "authorized QA authentication").toBe(200);
      const identity = await login.json();
      expect(identity.company.slug).toBe(credentials.slug);
      const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` };
      await page.goto("/sign-in");
      await page.locator("#company-slug").fill(credentials.slug);
      await page.locator("#email").fill(credentials.email);
      await page.locator("#password").fill(credentials.password);
      await page.getByRole("button", { name: /^Sign in$/ }).click();
      await page.waitForURL(/\/app(?:[/?]|$)/);
      const title = `Contract AI source QA ${run}`;
      const created = await request.post(`${api.origin}/api/contracts/`, { headers,
        data: { title, contract_code: `CAI-${run}`, contract_type: "agreement", status: "under_review" } });
      expect(created.status(), "unique retained QA contract").toBe(200);
      const contractId = (await created.json()).id as string;
      try {
        const path = `/api/contracts/${contractId}`;
        async function add(suffix: string, data: Record<string, unknown>) {
          const response = await request.post(`${api.origin}${path}/${suffix}`, { headers, data });
          expect(response.status(), `retain reviewed ${suffix} fixture`).toBe(200);
          return await response.json();
        }
        const manualClause = await add("clauses", { title: "Counsel-reviewed clause", clause_type: "payment",
          clause_text: SOURCE, risk_level: "low", notes: "Manual review must survive extraction." });
        const manualDuty = await add("obligations", { title: "Counsel-reviewed duty", description: SOURCE });
        const rule = await add("playbook-rules", { rule_name: "Counsel-reviewed payment rule", clause_type: "payment",
          expected_position: SOURCE, severity: "medium" });
        await page.goto(`/app/contracts/${contractId}`);
        await expect(page.getByRole("heading", { name: title })).toBeVisible();
        for (const layoutWidth of [320, 393, 767, 768, 769, 1023, 1024, 1025, 1280]) {
          await page.setViewportSize({ width: layoutWidth, height: 900 });
          await assertContractTabsReachable(page);
          if (local && width === 1280) {
            await test.info().attach(`contract-tabs-${layoutWidth}px`, {
              body: await page.getByRole("tablist").screenshot(), contentType: "image/png",
            });
          }
        }
        await page.setViewportSize({ width, height: 900 });
        await assertContractTabsReachable(page);
        await page.getByRole("tab", { name: /^Clauses/ }).click();
        await expect(page.getByTestId("contract-extract-clauses")).toBeDisabled();
        await page.getByRole("tab", { name: /^Attachments/ }).click();
        const uploading = page.waitForResponse(response => new URL(response.url()).pathname === `${path}/attachments`
          && response.request().method() === "POST");
        await page.getByTestId("contract-attachment-input").setInputFiles({
          name: `contract-source-${run}.txt`, mimeType: "text/plain", buffer: Buffer.from(`${SOURCE}\n`.repeat(8)),
        });
        const uploaded = await uploading;
        expect(uploaded.status(), "original upload without retries").toBe(200);
        const attachmentId = (await uploaded.json()).id as string;
        if (local) await runDocumentWorkerOnce();
        const deadline = Date.now() + 90_000;
        let indexed = false;
        while (Date.now() < deadline) {
          const response = await request.get(`${api.origin}${path}/workspace`, { headers });
          expect(response.status(), "authorized indexed workspace").toBe(200);
          const attachment = (await response.json()).attachments.find((row: { id: string }) => row.id === attachmentId);
          expect(attachment).toBeDefined();
          if (attachment.processing_status === "failed") throw new Error("Contract fixture indexing failed.");
          if (attachment.processing_status === "indexed") {
            expect(attachment.extracted_char_count).toBeGreaterThan(0);
            indexed = true;
            break;
          }
          await page.waitForTimeout(1500);
        }
        expect(indexed, "bounded real worker completion, not a skip").toBe(true);
        await page.reload();
        async function action(button: Locator, suffix: string): Promise<Response> {
          await release(request);
          await expect(button).toBeVisible();
          await expect(button).toBeEnabled();
          await button.scrollIntoViewIfNeeded();
          const bounds = await button.boundingBox();
          expect(bounds!.width).toBeGreaterThan(24);
          expect(bounds!.x).toBeGreaterThanOrEqual(0);
          expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
          const result = page.waitForResponse(response => new URL(response.url()).pathname === `/api/ai/contracts/${contractId}/${suffix}`
            && response.request().method() === "POST");
          await button.click();
          const response = await result;
          expect(await response.request().headerValue("X-CaseOps-Automated-Test")).toBe("no-paid-providers");
          expect(response.status(), `first ${suffix} response, without browser retry`).toBe(200);
          expect((await response.json()).provider, "offline result is not paid-model accuracy evidence").toBe("mock");
          return response;
        }
        await page.getByRole("tab", { name: /^Clauses/ }).click();
        for (let iteration = 0; iteration < 2; iteration++) {
          const response = await action(page.getByTestId("contract-extract-clauses"), "clauses/extract");
          expect(await response.json()).toMatchObject({ inserted: 1, removed: iteration, contract_id: contractId });
          await expect(page.getByRole("heading", { name: "Offline source excerpt", exact: true })).toBeVisible();
          await page.reload();
          await page.getByRole("tab", { name: /^Clauses/ }).click();
        }
        await expect(page.getByRole("heading", { name: "Counsel-reviewed clause", exact: true })).toBeVisible();
        const party = page.getByTestId("party-perspective-panel");
        await party.getByTestId("party-first-name").fill("Acme India");
        await party.getByTestId("party-second-name").fill("Supplier India");
        const extractedParty = await action(party.getByTestId("party-extract-button"), "clauses/extract-by-party");
        const partyBody = await extractedParty.json();
        expect(partyBody.dropped_source_unverified_count).toBe(0);
        expect(partyBody.ambiguous_items).toHaveLength(1);
        expect(partyBody.ambiguous_items[0].source).toMatchObject({ attachment_id: attachmentId, snippet: SOURCE });
        await expect(party.getByText(/Ambiguous.*needs review \(1\)/)).toBeVisible();
        await expect(party.getByText(SOURCE, { exact: false })).toBeVisible();
        await page.getByRole("tab", { name: /^Obligations/ }).click();
        const obligations = await action(page.getByTestId("contract-extract-obligations"), "obligations/extract");
        expect(await obligations.json()).toMatchObject({ contract_id: contractId, inserted: 1, removed: 0 });
        await expect(page.getByText("Offline source duty", { exact: true })).toBeVisible();
        await assertContractTabsReachable(page);
        await page.getByRole("tab", { name: /^Playbook/ }).click();
        const compared = await action(page.getByTestId("contract-run-playbook-compare"), "playbook/compare");
        expect((await compared.json()).findings).toEqual([expect.objectContaining({ rule_id: rule.id, status: "missing" })]);
        await expect(page.getByText("Findings (1)", { exact: true })).toBeVisible();
        await assertContractTabsReachable(page);
        const workspace = await request.get(`${api.origin}${path}/workspace`, { headers });
        expect(workspace.status()).toBe(200);
        const retained = await workspace.json();
        expect(retained.clauses).toHaveLength(2);
        expect(retained.clauses).toContainEqual(expect.objectContaining({ id: manualClause.id, clause_text: SOURCE }));
        expect(retained.obligations).toHaveLength(2);
        expect(retained.obligations).toContainEqual(expect.objectContaining({ id: manualDuty.id, description: SOURCE }));
        expect(retained.playbook_rules).toHaveLength(1);
        await page.reload();
        await page.getByRole("tab", { name: /^Obligations/ }).click();
        await expect(page.getByText("Offline source duty", { exact: true })).toBeVisible();
        await expect(page.getByText("Counsel-reviewed duty", { exact: true })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
        await release(request);
      } finally {
        // Retire this run's QA Contract whether the journey passed or failed (B4-ADJ-09).
        await terminateContract(request, api.origin, headers, contractId);
      }
    });
  });
}
