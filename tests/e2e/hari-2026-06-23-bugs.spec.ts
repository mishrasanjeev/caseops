/**
 * Hari 2026-06-23 workbook regressions.
 *
 * BUG-001: New Matter District Court hierarchy must expose the India.gov
 * Delhi district court directory, including entries absent from the original
 * LW-S4 seed.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun23Bugs!";

const DELHI_DISTRICT_COMPLEXES = [
  "Central District Court, Delhi (Central Delhi)",
  "District Court North Delhi (North Delhi)",
  "District Court North West Delhi (North West Delhi)",
  "Dwarka Court South West Delhi | India (South West Delhi)",
  "East District Court, Delhi (East Delhi)",
  "New Delhi District Court, Delhi (New Delhi)",
  "North East District Court, Delhi (North East Delhi)",
  "Shahdara District Court, Delhi (Shahdara)",
  "South District Court, New Delhi (South Delhi)",
  "South-East District Court, New Delhi (South East)",
  "West District Court, Delhi (West Delhi)",
  "Other district court in Delhi",
];

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-06-23 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun23 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return { ownerEmail };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

test.describe("Hari 2026-06-23 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-001: Add Matter can select every Delhi District Court complex", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h62301");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    await page.goto("/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    await expect(page.getByTestId("new-matter-forum-state")).toHaveValue("Delhi");
    await page
      .getByTestId("new-matter-forum-category")
      .selectOption("district_court");

    const districtSelect = page.getByTestId("new-matter-forum-district");
    await expect(districtSelect).toHaveValue("district:india-gov:delhi:centraldelhi");
    await expect
      .poll(async () =>
        districtSelect.locator("option").evaluateAll((options) =>
          options.map((option) => option.textContent?.trim() ?? ""),
        ),
      )
      .toEqual(DELHI_DISTRICT_COMPLEXES);

    await districtSelect.selectOption("district:india-gov:delhi:southwestdelhi");
    await expect(districtSelect).toHaveValue("district:india-gov:delhi:southwestdelhi");

    await page.getByLabel("Title").fill("Dwarka district matter");
    const matterCode = `DW-${slug.slice(-6)}`;
    await page.getByLabel("Matter code").fill(matterCode);
    await page.getByLabel("Practice area").fill("Commercial");
    await page.getByRole("button", { name: /Create matter/i }).click();

    await expect(page.getByRole("dialog")).toBeHidden({ timeout: 15_000 });
    await expect(page.getByText("Matter created")).toBeVisible();
    await expect(page.getByText(matterCode)).toBeVisible({ timeout: 15_000 });
  });
});
