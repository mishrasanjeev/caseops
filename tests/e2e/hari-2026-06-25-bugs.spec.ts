/**
 * Hari 2026-06-25 workbook regressions.
 *
 * BUG-001: New Matter Consumer Forum hierarchy must expose every e-Jagriti
 * state/UT jurisdiction and the DCDRC rows for the selected state, with an
 * explicit uncatalogued DCDRC fallback instead of silently blocking creation.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun25Bugs!";

const CONSUMER_STATE_JURISDICTIONS = [
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
      company_name: "Hari 2026-06-25 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun25 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed with HTTP ${resp.status()}: ${await resp.text()}`);
  }
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

async function openNewMatter(page: Page): Promise<void> {
  await page.goto("/app/matters");
  await page.getByTestId("new-matter-trigger").first().click();
  await expect(page.getByTestId("new-matter-forum-state")).toHaveValue("Delhi");
}

async function fillRequiredFields(
  page: Page,
  values: { title: string; matterCode: string },
): Promise<void> {
  await page.getByLabel("Title").fill(values.title);
  await page.getByLabel("Matter code").fill(values.matterCode);
  await page.getByLabel("Practice area").fill("Consumer");
}

test.describe("Hari 2026-06-25 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-001: Add Matter supports all Consumer Forum states, DCDRC rows, and fallback", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h62501");
    let ownerEmail = "";
    try {
      ({ ownerEmail } = await bootstrap(api, slug));
    } finally {
      await api.dispose();
    }
    await signIn(page, slug, ownerEmail);

    await openNewMatter(page);
    await page
      .getByTestId("new-matter-forum-category")
      .selectOption("state_commission");

    const stateSelect = page.getByTestId("new-matter-forum-consumer-state");
    await expect
      .poll(async () =>
        stateSelect.locator("option").evaluateAll((options) =>
          options.map((option) => option.textContent?.trim() ?? ""),
        ),
      )
      .toEqual(CONSUMER_STATE_JURISDICTIONS);

    await stateSelect.selectOption("Rajasthan");
    await page
      .getByTestId("new-matter-forum-category")
      .selectOption("district_commission");
    await expect(stateSelect).toHaveValue("Rajasthan");

    const districtSelect = page.getByTestId("new-matter-forum-consumer-district");
    await expect(districtSelect).toHaveValue("consumer:dcdrc:11080086");
    await expect
      .poll(async () =>
        districtSelect.locator("option").evaluateAll((options) =>
          options.map((option) => option.textContent?.trim() ?? ""),
        ),
      )
      .toEqual(
        expect.arrayContaining([
          "Ajmer District Consumer Disputes Redressal Commission (Ajmer)",
          "Jaipur-III District Consumer Disputes Redressal Commission (Jaipur-III)",
          "Other DCDRC in Rajasthan",
        ]),
      );
    await expect.poll(async () => districtSelect.locator("option").count()).toBe(46);

    const catalogCode = `CONS-CAT-${slug.slice(-5).toUpperCase()}`;
    await fillRequiredFields(page, {
      title: "Rajasthan catalogued consumer matter",
      matterCode: catalogCode,
    });
    await page.getByRole("button", { name: /Create matter/i }).click();

    await expect(page.getByRole("dialog")).toBeHidden({ timeout: 15_000 });
    await expect(page.getByText("Matter created")).toBeVisible();
    await expect(page.getByText(catalogCode)).toBeVisible({ timeout: 15_000 });

    await openNewMatter(page);
    await page
      .getByTestId("new-matter-forum-category")
      .selectOption("district_commission");
    await page.getByTestId("new-matter-forum-consumer-state").selectOption("Rajasthan");
    await page
      .getByTestId("new-matter-forum-consumer-district")
      .selectOption("__uncatalogued_consumer_district__");
    await expect(page.getByTestId("new-matter-forum-consumer-district-name")).toHaveValue("");
    await expect(page.getByTestId("new-matter-forum-consumer-forum-name")).toHaveValue("");

    const fallbackCode = `CONS-OTH-${slug.slice(-5).toUpperCase()}`;
    await fillRequiredFields(page, {
      title: "Rajasthan uncatalogued consumer matter",
      matterCode: fallbackCode,
    });
    await expect(page.getByRole("button", { name: /Create matter/i })).toBeDisabled();

    await page.getByTestId("new-matter-forum-consumer-district-name").fill("South II");
    await expect(page.getByRole("button", { name: /Create matter/i })).toBeDisabled();
    await page
      .getByTestId("new-matter-forum-consumer-forum-name")
      .fill("South II DCDRC Annex");
    await expect(page.getByRole("button", { name: /Create matter/i })).toBeEnabled();
    await page.getByRole("button", { name: /Create matter/i }).click();

    await expect(page.getByRole("dialog")).toBeHidden({ timeout: 15_000 });
    await expect(page.getByText("Matter created")).toBeVisible();
    await expect(page.getByText(fallbackCode)).toBeVisible({ timeout: 15_000 });
  });
});
