import { expect, request, test } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "ReportEvidence2026!";

test("IPLF-038B generates internal reports and exposes unavailable sources", async ({ page }) => {
  const api = await request.newContext();
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const slug = `report-evidence-${suffix}`;
  const email = `owner-${suffix}@example.com`;
  const bootstrap = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IP Report Evidence LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Report Evidence Owner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(bootstrap.status(), await bootstrap.text()).toBe(200);

  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);

  await page.goto("/app/ip/reports");
  await expect(page.getByRole("heading", { name: "IP reports" })).toBeVisible();
  await expect(page.getByText("Internal only")).toBeVisible();

  await page.getByLabel("Report", { exact: true }).selectOption("opposition_status");
  await page.getByLabel("Keyword").fill("No matching mark");
  await page.getByLabel("Jurisdiction").fill("IN");
  const oppositionResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/ip/reports/preview" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Generate" }).click();
  expect((await oppositionResponse).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Opposition status" })).toBeVisible();
  await expect(page.getByText("No matching records")).toBeVisible();
  await expect(page.getByText(/Restricted records outside your access are omitted/)).toBeVisible();

  await page.getByLabel("Report", { exact: true }).selectOption("watch");
  await expect(page.getByLabel("Keyword")).toHaveCount(0);
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(page.getByText("Report source unavailable")).toBeVisible();
  await expect(page.getByText(/Unavailable sources: Ip watch provider/)).toBeVisible();
  await expect(page.getByText("IP watch operations are not activated for this workspace.")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/app/ip/reports");
  await expect(page.getByRole("heading", { name: "IP reports" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate" })).toBeVisible();
  const bodyWidth = await page.evaluate(() => ({
    client: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(bodyWidth.scroll).toBeLessThanOrEqual(bodyWidth.client);

  await api.dispose();
});
