/**
 * Hari 2026-06-23 workbook regressions.
 *
 * BUG-001: New Matter District Court hierarchy must expose all seven Delhi
 * district court complexes, including entries that were absent from the
 * original LW-S4 seed.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun23Bugs!";

const DELHI_DISTRICT_COMPLEXES = [
  "Tis Hazari Courts Complex (Central & West / Tis Hazari)",
  "Patiala House Courts Complex (New Delhi / New Delhi)",
  "Karkardooma Courts Complex (East, North-East & Shahdara / Karkardooma)",
  "Rohini Courts Complex (North & North-West / Rohini)",
  "Dwarka Courts Complex (South-West / Dwarka)",
  "Saket Courts Complex (South & South-East / Saket)",
  "Rouse Avenue Courts Complex (Special Courts / Central / Rouse Avenue)",
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
    await expect(districtSelect).toHaveValue("district:delhi:central");
    await expect
      .poll(async () =>
        districtSelect.locator("option").evaluateAll((options) =>
          options.map((option) => option.textContent?.trim() ?? ""),
        ),
      )
      .toEqual(DELHI_DISTRICT_COMPLEXES);

    await districtSelect.selectOption("district:delhi:dwarka");
    await expect(districtSelect).toHaveValue("district:delhi:dwarka");

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
