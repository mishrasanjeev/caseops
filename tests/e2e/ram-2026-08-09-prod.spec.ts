import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
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

test("IPLF-023B production keeps unentitled legal automation and records fail-closed at 360px", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signIn(page);
  const protectedRequests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      pathname.includes("/deadline-workspace") ||
      pathname.includes("/deadline-rules") ||
      pathname.includes("/working-calendars")
    ) {
      protectedRequests.push(pathname);
    }
  });
  const readinessResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/ip/readiness" &&
      response.request().method() === "GET",
  );
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto(`${PROD_BASE_URL}/app/ip`);
  const readiness = await readinessResponse;
  expect(readiness.status()).toBe(200);
  const body = (await readiness.json()) as { workspace_available: boolean };
  expect(body.workspace_available).toBe(false);
  await expect(page.getByRole("heading", { name: "IP workspace setup" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Legal deadline control" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Rule and calendar governance" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Calculate deadline proposal" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Confirm legal deadline" })).toHaveCount(0);
  expect(protectedRequests).toEqual([]);

  const setup = page.getByRole("heading", { name: "IP workspace setup" });
  const box = await setup.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(360);
});

test("IPLF-024A production exposes document contracts only behind IP entitlement", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signIn(page);
  const foundation = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/documents/foundation-contract`,
  );
  expect(foundation.status(), await foundation.text()).toBe(403);
  expect(await foundation.text()).toContain("ip_workspace");

  const taxonomy = await page.request.get(`${PROD_API_BASE_URL}/api/ip/document-taxonomy`);
  expect(taxonomy.status(), await taxonomy.text()).toBe(403);
  expect(await taxonomy.text()).toContain("ip_workspace");
});
