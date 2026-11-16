import { devices, expect, request, test, type APIRequestContext } from "@playwright/test";

import { localTransportHeaders } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";
import { runId } from "./support/run-id";

type Version = { id: string; body: string; summary: string; revision: number };
type Draft = {
  current_version_id: string; status: string; review_required: boolean; versions: Version[];
};

async function json(api: APIRequestContext, url: string, method = "GET", data?: object) {
  const response = await api.fetch(url, { method, data, maxRetries: 0, maxRedirects: 0 });
  expect(response.status(), `${method} ${new URL(url).pathname}: ${await response.text()}`).toBe(200);
  return response.json();
}

for (const phone of [false, true]) {
  test(`Draft quality 2026-11-14 ${phone ? "[mobile] phone" : "desktop"}: generated findings survive correction and reload`,
    async ({ browser, baseURL }) => {
      // Synthetic generation is never permitted against production, even if
      // somebody explicitly selects this spec with a live configuration.
      if (!baseURL || ![baseURL, apiBaseUrl].every(value => {
        const url = new URL(value);
        return url.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
      })) throw new Error("Draft quality generation fixture is strictly loopback-only.");
      // The canonical local fixture supplies the mock provider. The marker
      // remains authoritative if a misconfigured server selects a real one:
      // generation must refuse without spending, not fall through to a paid call.
      const run = runId(), slug = `draft-quality-${run}`;
      const email = `${slug}@example.com`, password = `Synthetic!${run}aA9`;
      const api = await request.newContext({ extraHTTPHeaders: localTransportHeaders(apiBaseUrl) });
      const context = await browser.newContext({
        ...(phone ? devices["Pixel 5"] : { viewport: { width: 1280, height: 1000 } }),
        baseURL, extraHTTPHeaders: localTransportHeaders(baseURL), serviceWorkers: "block",
      });
      const page = await context.newPage();
      try {
        const tenant = await json(api, `${apiBaseUrl}/api/bootstrap/company`, "POST", {
          company_name: "Synthetic draft quality fixture", company_slug: slug, company_type: "law_firm",
          owner_full_name: "Synthetic owner", owner_email: email, owner_password: password,
        });
        const auth = await request.newContext({ extraHTTPHeaders: {
          ...localTransportHeaders(apiBaseUrl), Authorization: `Bearer ${tenant.access_token}`,
        } });
        try {
          const matter = await json(auth, `${apiBaseUrl}/api/matters/`, "POST", {
            title: "Synthetic draft review", matter_code: `DQ-${run}`, practice_area: "Civil",
            forum_level: "high_court", status: "intake", court_name: "Delhi High Court",
          });
          const shell = await json(auth, `${apiBaseUrl}/api/matters/${matter.id}/drafts`, "POST", {
            title: "Synthetic affidavit review", draft_type: "other", template_type: "affidavit",
          });
          const draftApi = `${apiBaseUrl}/api/matters/${matter.id}/drafts/${shell.id}`;
          await context.route("**/*", async route => {
            const req = route.request(), url = new URL(req.url());
            if (![new URL(baseURL).origin, new URL(apiBaseUrl).origin].includes(url.origin)) {
              throw new Error("External browser network forbidden in draft quality fixture.");
            }
            if (url.origin === new URL(apiBaseUrl).origin && req.method() !== "OPTIONS") {
              expect(req.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
            }
            await route.continue();
          });
          await page.goto("/sign-in");
          await page.locator("#company-slug").fill(slug);
          await page.locator("#email").fill(email);
          await page.locator("#password").fill(password);
          await page.getByRole("button", { name: /^Sign in$/ }).click();
          await page.waitForURL(/\/app(?:[/?]|$)/);
          const route = `/app/matters/${matter.id}/drafts/${shell.id}`;
          await page.goto(route);
          await page.getByTestId("draft-generate").click();
          const finding = page.locator('[data-code="template.affidavit_missing_affirmation"]');
          await expect(finding).toBeVisible();
          await expect(finding).toHaveAttribute("data-severity", "blocker");
          const generated = await json(auth, draftApi) as Draft;
          const original = generated.versions.find(row => row.id === generated.current_version_id)!;
          expect(original.body).toMatch(/^Brief in /); // Actual offline provider, not routed JSON.
          expect(original.summary).toContain("template.affidavit_missing_affirmation");
          expect(generated.review_required).toBe(true);
          await page.reload();
          await expect(finding).toBeVisible();

          await page.getByTestId("draft-edit-toggle").click();
          const editor = page.getByTestId("draft-body-editor");
          await expect(editor).toHaveValue(original.body);
          const repeated = "Section 483 of Bharatiya Nyaya Sanhita. ".repeat(6);
          await editor.fill(repeated);
          await page.getByTestId("draft-save-edit").click();
          await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 2");
          const confusion = page.locator('[data-code="statute.bns_bnss_confusion"]');
          await expect(confusion).toHaveCount(1);
          await expect(confusion).toContainText("6 occurrences");
          await expect(finding).toBeVisible();
          await page.reload();
          await expect(confusion).toHaveCount(1);
          await expect(finding).toBeVisible();
          await page.getByTestId("draft-edit-toggle").click();
          const corrected = "I solemnly affirm the supplied statements.\nVerification: true to my knowledge.";
          await editor.fill(corrected);
          await page.getByTestId("draft-save-edit").click();
          await expect(page.getByTestId("draft-current-revision")).toHaveText("Revision 3");
          await expect(finding).toHaveCount(0);
          await page.reload();
          await expect(page.getByTestId("draft-body-readonly")).toHaveText(corrected);
          await expect(finding).toHaveCount(0);
          const after = await json(auth, draftApi) as Draft;
          expect(after.versions.find(row => row.id === original.id)).toEqual(original);
          expect(after.review_required).toBe(true);
          expect(after.status).toBe("draft");
          await page.getByTestId("draft-submit").click();
          await expect(page.getByTestId("draft-approve")).toBeDisabled();
          const refused = await auth.post(`${draftApi}/approve`, { data: {}, maxRetries: 0 });
          expect(refused.status()).toBe(422);
          expect((await refused.json()).detail).toContain("verified citations");

          const bail = await json(auth, `${apiBaseUrl}/api/matters/${matter.id}/drafts`, "POST", {
            title: "Synthetic citation spelling", draft_type: "brief", template_type: "bail",
          });
          await page.goto(`/app/matters/${matter.id}/drafts/${bail.id}`);
          await page.getByTestId("draft-generate").click();
          const missingStatute = page.locator('[data-code="template.bail_missing_statute"]');
          await expect(missingStatute).toBeVisible();
          const citations = ["BNSS s.483", "Section 483 of BNSS",
            "Section 483 of the Bharatiya Nagarik Suraksha Sanhita, 2023"];
          for (const [index, citation] of citations.entries()) {
            await page.getByTestId("draft-edit-toggle").click();
            const text = `${citation}. The applicant is in custody and addresses the triple test.`;
            await page.getByTestId("draft-body-editor").fill(text);
            await page.getByTestId("draft-save-edit").click();
            await expect(page.getByTestId("draft-current-revision")).toHaveText(`Revision ${index + 2}`);
            await expect(missingStatute).toHaveCount(0);
            await page.reload();
            await expect(page.getByTestId("draft-body-readonly")).toHaveText(text);
            await expect(missingStatute).toHaveCount(0);
          }
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
        } finally { await auth.dispose(); }
      } finally { await context.close(); await api.dispose(); }
    });
}
