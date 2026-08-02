import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL = process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
  return password;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
}

test.describe("Ram 2026-08-01 deployed IP slices", () => {
  test.setTimeout(120_000);

  test("exact production revision exposes the permission-scoped IP docket at desktop and 360px", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${PROD_BASE_URL}/app/ip`);
    await expect(page.getByRole("heading", { name: "Trademark docket" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New trademark" })).toBeVisible();

    const workspace = page.getByTestId("ip-docket-workspace");
    const emptyState = page.getByText("No IP records yet", { exact: true });
    await expect(workspace.or(emptyState)).toBeVisible({ timeout: 30_000 });
    if (await emptyState.isVisible()) {
      await page.getByRole("button", { name: "New trademark" }).click();
      await page.getByLabel("Docket title").fill("Production E2E trademark");
      await page.getByLabel("Word mark").fill("CASEOPS QA");
      await page.getByLabel("Goods / services specification").fill("Quality-assurance software services");
      await page.getByLabel("Applicant").fill("CaseOps QA Bot");
      await page.getByLabel("Representation evidence reference").fill("qa:prod-e2e-2026-08-01");
      await page.getByRole("button", { name: "Validate and create" }).click();
      await expect(workspace).toBeVisible({ timeout: 30_000 });
    }

    await page.setViewportSize({ width: 360, height: 800 });
    await page.reload();
    const create = page.getByRole("button", { name: "New trademark" });
    await expect(create).toBeVisible();
    const box = await create.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);

    for (const name of [
      "Matter evidence intake",
      "Deadline continuity",
      "Related rights and obligations",
      "IP cost evidence",
    ]) {
      const operationalSurface = page.getByRole("heading", { name });
      await operationalSurface.scrollIntoViewIfNeeded();
      await expect(operationalSurface).toBeVisible();
    }

    await create.scrollIntoViewIfNeeded();
    await create.click();
    await expect(page.getByRole("heading", { name: "New trademark particulars" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Validate and create" })).toBeVisible();
  });
});
