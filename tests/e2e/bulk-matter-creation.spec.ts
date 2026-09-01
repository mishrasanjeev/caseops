import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { uniqueId } from "./support/helpers";

const password = "BulkMatterE2E123!";
let api: APIRequestContext;
let slug = "";
let ownerEmail = "";
let viewerEmail = "";
let ownerToken = "";

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

test.describe.serial("Bulk matter creation", () => {
  test.beforeAll(async () => {
    const suffix = uniqueId("bulk").slice(-10).toLowerCase();
    slug = `bulk-${suffix}`;
    ownerEmail = `owner-${suffix}@example.com`;
    viewerEmail = `viewer-${suffix}@example.com`;
    api = await request.newContext();

    const bootstrap = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
      data: {
        company_name: `Bulk Matter E2E ${suffix}`,
        company_slug: slug,
        company_type: "law_firm",
        owner_full_name: "Bulk Import Owner",
        owner_email: ownerEmail,
        owner_password: password,
      },
    });
    expect(bootstrap.status(), await bootstrap.text()).toBe(200);
    ownerToken = ((await bootstrap.json()) as { access_token: string }).access_token;

    const viewer = await api.post(`${apiBaseUrl}/api/companies/current/users`, {
      headers: { Authorization: `Bearer ${ownerToken}` },
      data: {
        full_name: "Read Only User",
        email: viewerEmail,
        role: "viewer",
        password,
      },
    });
    expect(viewer.status(), await viewer.text()).toBe(200);
  });

  test.afterAll(async () => {
    await api?.dispose();
  });

  test("owner validates partial input, downloads errors, imports valid rows, and reopens history", async ({
    page,
  }) => {
    await signIn(page, ownerEmail);
    await page.goto("/app/matters/imports");
    await expect(page.getByRole("heading", { name: "Bulk upload matters" })).toBeVisible();

    const xlsxTemplateDownload = page.waitForEvent("download");
    await page.getByTestId("matter-import-template-xlsx").click();
    await expect((await xlsxTemplateDownload).suggestedFilename()).toBe(
      "caseops-matter-import-template.xlsx",
    );

    const templateDownload = page.waitForEvent("download");
    await page.getByTestId("matter-import-template-csv").click();
    await expect((await templateDownload).suggestedFilename()).toBe(
      "caseops-matter-import-template.csv",
    );

    const code = `BULK-E2E-${Date.now().toString(36).toUpperCase()}`;
    const csv = [
      "Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum,Client Email,Court Forum Number",
      `Bulk E2E valid matter,${code},Technology & Data / Privacy,ACTIVE,,High Court,client@example.com,Court #7 / Bench-A`,
      "Bulk E2E invalid matter,BULK/E2E#BAD,Unknown Practice,,,HIGH COURT,,Court #8",
    ].join("\n");
    await page.getByTestId("matter-import-file").setInputFiles({
      name: "bulk-e2e.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv, "utf8"),
    });
    await page.getByTestId("matter-import-validate").click();

    await expect(page.getByText(/letters, numbers, and hyphens/i)).toBeVisible();
    await expect(page.getByText(code)).toBeVisible();
    await expect(page.getByText("BULK/E2E#BAD")).toBeVisible();
    await expect(page.getByTestId("matter-import-confirm")).toContainText(
      "Confirm import (1)",
    );

    // Renamed 2026-08-14: the report now also lists rows skipped as duplicates,
    // which are excluded from the submission rather than rejected as errors.
    const errorDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download row report" }).click();
    expect((await errorDownload).suggestedFilename()).toMatch(/^matter-import-errors-.+\.csv$/);

    await page.getByTestId("matter-import-confirm").click();
    await expect(page.getByText("completed with errors").first()).toBeVisible();
    await expect(page.getByText("bulk-e2e.csv").last()).toBeVisible();

    const matters = await api.get(`${apiBaseUrl}/api/matters/?q=${encodeURIComponent(code)}`, {
      headers: { Authorization: `Bearer ${ownerToken}` },
    });
    expect(matters.status(), await matters.text()).toBe(200);
    const body = (await matters.json()) as {
      matters: Array<{
        id: string;
        matter_code: string;
        practice_area: string;
        status: string;
        client_name: string | null;
        forum_level: string;
        court_forum_number: string | null;
      }>;
    };
    expect(body.matters).toHaveLength(1);
    expect(body.matters[0].matter_code).toBe(code);
    expect(body.matters[0].practice_area).toBe("Technology & Data / Privacy");
    expect(body.matters[0].status).toBe("active");
    expect(body.matters[0].client_name).toBeNull();
    expect(body.matters[0].forum_level).toBe("high_court");
    expect(body.matters[0].court_forum_number).toBe("Court #7 / Bench-A");

    await page.getByText("bulk-e2e.csv").last().click();
    await expect(page.getByText(code)).toBeVisible();
  });

  test("viewer cannot use the bulk-import workflow", async ({ page }) => {
    await signIn(page, viewerEmail);
    await page.goto("/app/matters/imports");
    await expect(page.getByRole("heading", { name: "Permission required" })).toBeVisible();
    await expect(page.getByTestId("matter-import-file")).toHaveCount(0);
  });
});
