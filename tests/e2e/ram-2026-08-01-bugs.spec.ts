import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "IpDocketProof2026!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function bootstrap(api: APIRequestContext, slug: string): Promise<void> {
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IP Docket Proof LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "IP Proof Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
}

async function signIn(page: Page, slug: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`owner-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe("Ram 2026-08-01 IP law firm slices", () => {
  test.setTimeout(120_000);

  test("IP docket creates a validated trademark and keeps every grouped action visible at 360px", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("ip-proof");
    await bootstrap(api, slug);
    await signIn(page, slug);

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app/ip");
    await expect(page.getByRole("heading", { name: "Trademark docket" })).toBeVisible();

    const create = page.getByRole("button", { name: "New trademark" });
    await expect(create).toBeVisible();
    const createBox = await create.boundingBox();
    expect(createBox).not.toBeNull();
    expect(createBox!.x).toBeGreaterThanOrEqual(0);
    expect(createBox!.x + createBox!.width).toBeLessThanOrEqual(360);
    await create.click();

    await page.getByLabel("Docket title").fill("ASTER mobile mark");
    await page.getByLabel("Application / client reference").fill("TM-MOBILE-001");
    await page.getByLabel("Word mark").fill("ASTER");
    await page.getByLabel("Nice class").fill("42");
    await page.getByLabel("Goods / services specification").fill("Legal software services");
    await page.getByLabel("Applicant").fill("Aster Legal LLP");
    await page
      .getByLabel("Representation evidence reference")
      .fill("attachment:mobile-mark-proof");
    const submit = page.getByRole("button", { name: "Validate and create" });
    await expect(submit).toBeVisible();
    const submitBox = await submit.boundingBox();
    expect(submitBox).not.toBeNull();
    expect(submitBox!.x + submitBox!.width).toBeLessThanOrEqual(360);
    await submit.click();

    await expect(
      page.getByRole("heading", { name: "ASTER mobile mark", exact: true }),
    ).toBeVisible();
    const workspace = page.getByTestId("ip-docket-workspace");
    await expect(workspace).toBeVisible();
    await expect(workspace.getByText("Readiness")).toBeVisible();
    await expect(workspace.getByText("Operational links")).toBeVisible();
    await expect(page.getByRole("button", { name: "Add ownership evidence" })).toBeVisible();
  });
});
