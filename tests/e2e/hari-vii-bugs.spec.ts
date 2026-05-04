import fs from "node:fs";
import path from "node:path";

import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl, uploadsRoot } from "./support/env";

const PASSWORD = "HariViiPass123!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function bootstrap(api: APIRequestContext, slug: string): Promise<string> {
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Hari VII ${slug}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari VII Owner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  if (response.status() !== 200 && response.status() !== 409) {
    throw new Error(`bootstrap failed: ${response.status()} ${await response.text()}`);
  }
  return email;
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL("**/app");
}

async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  const value = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;
  if (!value) throw new Error("caseops_csrf cookie missing after sign-in");
  return value;
}

async function createMatter(page: Page, code: string): Promise<string> {
  const response = await page.context().request.post(`${apiBaseUrl}/api/matters/`, {
    data: {
      title: `Hari VII matter ${code}`,
      matter_code: code,
      practice_area: "Commercial",
      forum_level: "high_court",
      court_name: "Delhi High Court",
      description: "Matter seeded for Hari VII regression checks.",
      status: "active",
    },
    headers: { "X-CSRF-Token": await csrf(page) },
  });
  if (!response.ok()) {
    throw new Error(`matter create failed: ${response.status()} ${await response.text()}`);
  }
  return String(((await response.json()) as { id: string }).id);
}

async function createDraft(page: Page, matterId: string): Promise<string> {
  const response = await page.context().request.post(
    `${apiBaseUrl}/api/matters/${matterId}/drafts`,
    {
      data: { title: "Hari VII editable draft", draft_type: "brief" },
      headers: { "X-CSRF-Token": await csrf(page) },
    },
  );
  if (!response.ok()) {
    throw new Error(`draft create failed: ${response.status()} ${await response.text()}`);
  }
  return String(((await response.json()) as { id: string }).id);
}

function writeMinimalPdf(name: string): string {
  fs.mkdirSync(uploadsRoot, { recursive: true });
  const filePath = path.join(uploadsRoot, name);
  fs.writeFileSync(
    filePath,
    `%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 240 240] /Contents 4 0 R >> endobj
4 0 obj << /Length 44 >> stream
BT /F1 12 Tf 20 120 Td (CaseOps PDF) Tj ET
endstream endobj
trailer << /Root 1 0 R >>
%%EOF`,
    "utf8",
  );
  return filePath;
}

test.describe("Hari VII bug regressions", () => {
  test.setTimeout(300_000);

  test("quota banners, draft editing, and PDF original-view path stay fixed", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("hari-vii");
    const email = await bootstrap(api, slug);
    await api.dispose();

    await signIn(page, slug, email);
    const matterId = await createMatter(page, `HVII-${Date.now().toString(36)}`);

    await page.route("**/api/matters/**/recommendations", async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      const requestBody = route.request().postDataJSON() as { type?: string } | null;
      const noun = requestBody?.type === "litigation_strategy" ? "strategy" : "recommendation";
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          type: "llm_quota_exhausted",
          title: "Service unavailable",
          status: 503,
          detail:
            `Could not generate the ${noun}: the configured AI provider quota ` +
            "is exhausted. Restore or top up provider credits, then retry. No output was saved.",
        }),
      });
    });

    await page.goto(`/app/matters/${matterId}/recommendations`);
    await page.getByTestId("generate-remedy-recommendation").click();
    await expect(
      page.getByText(/Remedy generation is temporarily unavailable/),
    ).toBeVisible();
    await expect(
      page.getByTestId("recommendation-last-error").getByText(/No output was saved/),
    ).toBeVisible();

    await page.goto(`/app/matters/${matterId}/strategy`);
    await page.getByTestId("strategy-generate").click();
    await expect(
      page.getByText(/Strategy generation is temporarily unavailable/),
    ).toBeVisible();
    await expect(
      page.getByTestId("strategy-last-error").getByText(/provider quota is exhausted/),
    ).toBeVisible();

    const draftId = await createDraft(page, matterId);
    await page.goto(`/app/matters/${matterId}/drafts/${draftId}`);
    await page.getByTestId("draft-generate").click();
    await expect(page.getByTestId("draft-body-readonly")).toBeVisible({
      timeout: 120_000,
    });
    await page.getByTestId("draft-edit-toggle").click();
    await expect(page.getByTestId("draft-body-editor")).toBeVisible();
    await page.getByTestId("draft-body-editor").fill(
      "Lawyer-reviewed manual edit that must become a new revision.",
    );
    await page.getByTestId("draft-save-edit").click();
    await expect(page.getByTestId("draft-current-revision")).toHaveText(
      "Revision 2",
    );
    await expect(page.getByText(/Review required/)).toBeVisible();

    await page.goto(`/app/matters/${matterId}/documents`);
    const pdfPath = writeMinimalPdf(`hari-vii-${Date.now()}.pdf`);
    await page.setInputFiles('[data-testid="matter-attachment-file-input"]', pdfPath);
    await expect(page.getByText(path.basename(pdfPath), { exact: false })).toBeVisible({
      timeout: 15_000,
    });

    await page.locator('[data-testid^="matter-attachment-view-"]').first().click();
    await expect(page).toHaveURL(/\/documents\/[^/]+\/view$/);
    const openOriginal = page.getByTestId("pdf-open-original");
    const downloadOriginal = page.getByTestId("pdf-download-original");
    await expect(openOriginal).toBeVisible();
    await expect(downloadOriginal).toBeVisible();
    await expect(openOriginal).toHaveAttribute("href", /\/api\/matters\/.*\/attachments\/.*\/download/);
    await expect(downloadOriginal).toHaveAttribute(
      "href",
      /\/api\/matters\/.*\/attachments\/.*\/download/,
    );
  });
});
