/**
 * Hari 2026-06-24 workbook regressions.
 *
 * BUG-001: New Matter District Court hierarchy must expose every official
 * India.gov state/UT jurisdiction and must still allow "Other" fallback when
 * a district court is not in the catalog.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun24Bugs!";

const DISTRICT_STATE_JURISDICTIONS = [
  "Andaman and Nicobar Islands",
  "Andhra Pradesh",
  "Arunachal Pradesh",
  "Assam",
  "Bihar",
  "Chandigarh",
  "Chhattisgarh",
  "Dadra and Nagar Haveli and Daman and Diu",
  "Delhi",
  "Goa",
  "Gujarat",
  "Haryana",
  "Himachal Pradesh",
  "Jammu and Kashmir",
  "Jharkhand",
  "Karnataka",
  "Kerala",
  "Ladakh",
  "Lakshadweep",
  "Madhya Pradesh",
  "Maharashtra",
  "Manipur",
  "Meghalaya",
  "Mizoram",
  "Nagaland",
  "Odisha",
  "Puducherry",
  "Punjab",
  "Rajasthan",
  "Sikkim",
  "Tamil Nadu",
  "Telangana",
  "Tripura",
  "Uttar Pradesh",
  "Uttarakhand",
  "West Bengal",
].sort((left, right) => left.localeCompare(right));

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
      company_name: "Hari 2026-06-24 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun24 Owner",
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

test.describe("Hari 2026-06-24 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-001: Add Matter supports all district states and uncatalogued district court fallback", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h62401");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    await page.goto("/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    await expect(page.getByTestId("new-matter-forum-state")).toHaveValue("Delhi");
    await page
      .getByTestId("new-matter-forum-category")
      .selectOption("district_court");

    const stateSelect = page.getByTestId("new-matter-forum-district-state");
    await expect
      .poll(async () =>
        stateSelect.locator("option").evaluateAll((options) =>
          options.map((option) => option.textContent?.trim() ?? ""),
        ),
      )
      .toEqual(DISTRICT_STATE_JURISDICTIONS);

    await stateSelect.selectOption("Assam");
    await expect(stateSelect).toHaveValue("Assam");

    const districtSelect = page.getByTestId("new-matter-forum-district");
    await expect(districtSelect).toHaveValue("district:india-gov:assam:bajali");
    await expect
      .poll(async () =>
        districtSelect.locator("option").evaluateAll((options) =>
          options.map((option) => option.textContent?.trim() ?? ""),
        ),
      )
      .toEqual(
        expect.arrayContaining([
          "Bajali District Judiciary (Bajali)",
          "Kamrup Metro District Judiciary (Kamrup)",
          "Other district court in Assam",
        ]),
      );
    await expect
      .poll(async () => districtSelect.locator("option").count())
      .toBe(35);

    await districtSelect.selectOption("__uncatalogued_district_court__");
    await expect(districtSelect).toHaveValue("__uncatalogued_district_court__");

    await page.getByLabel("Title").fill("Assam district matter");
    const matterCode = `ASM-${slug.slice(-6).toUpperCase()}`;
    await page.getByLabel("Matter code").fill(matterCode);
    await page.getByLabel("Practice area").fill("Commercial");
    await expect(page.getByRole("button", { name: /Create matter/i })).toBeDisabled();

    await page.getByTestId("new-matter-forum-district-name").fill("Kamrup Metro");
    await expect(page.getByRole("button", { name: /Create matter/i })).toBeDisabled();

    await page
      .getByTestId("new-matter-forum-district-court")
      .fill("Kamrup Metro District Court");
    await expect(page.getByRole("button", { name: /Create matter/i })).toBeEnabled();
    await page.getByRole("button", { name: /Create matter/i }).click();

    await expect(page.getByRole("dialog")).toBeHidden({ timeout: 15_000 });
    await expect(page.getByText("Matter created")).toBeVisible();
    await expect(page.getByText(matterCode)).toBeVisible({ timeout: 15_000 });
  });
});
