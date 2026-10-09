import { expect, test, type Page } from "@playwright/test";

const enabled = process.env.CASEOPS_CALENDAR_OAUTH_PROD === "true";
const api = process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const expectedSha = process.env.CASEOPS_EXPECTED_RELEASE_SHA;
const expectedAccount = process.env.CASEOPS_CALENDAR_OAUTH_ACCOUNT;

test.skip(!enabled, "Explicit Calendar OAuth production acceptance is required; no Google consent is fabricated.");
test.setTimeout(120_000);

async function assertRelease(page: Page) {
  if (!expectedSha || !/^[a-f0-9]{40}$/.test(expectedSha)) {
    throw new Error("An exact expected production release SHA is required.");
  }
  for (const url of [`${api}/api/build`, "/api/release-identity"]) {
    const response = await page.request.get(url);
    expect(response.status()).toBe(200);
    expect((await response.json()).release_sha).toBe(expectedSha);
  }
}

async function signIn(page: Page) {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD;
  if (!password) throw new Error("Calendar acceptance requires tester credentials.");
  await assertRelease(page);
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(process.env.CASEOPS_RAM_PROD_SLUG ?? "test-legal");
  await page.locator("#email").fill(process.env.CASEOPS_RAM_PROD_EMAIL ?? "ram@testfirm.com");
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:\/|$)/);
}

test("BUG-003/004: live authorization scopes and rejected callback return to Calendar safely", async ({ page }) => {
  await signIn(page);
  await page.goto("/app/calendar");
  await expect(page.getByTestId("calendar-google-panel")).toBeVisible({ timeout: 60_000 });
  const csrf = (await page.context().cookies(api)).find((cookie) => cookie.name === "caseops_csrf");
  expect(csrf, "Authenticated browser CSRF cookie is required").toBeTruthy();
  const start = await page.request.post(`${api}/api/calendar/connections/google-calendar/start`, {
    headers: { "X-CSRF-Token": csrf!.value },
  });
  expect(start.status()).toBe(200);
  const result = await start.json();
  expect(result.provider_available).toBe(true);
  const authorization = new URL(result.auth_url);
  expect(authorization.origin).toBe("https://accounts.google.com");
  expect(authorization.searchParams.get("scope")?.split(" ")).toEqual(expect.arrayContaining([
    "openid", "email", "https://www.googleapis.com/auth/calendar.events",
  ]));

  // An invalid state must fail before transport. Do not spend a live Google code.
  await page.goto(`${api}/api/calendar/connections/google-calendar/callback?code=invalid-acceptance-code&state=invalid-acceptance-state`);
  await page.waitForURL(/\/app\/calendar\?oauth_provider=google_calendar&oauth_result=retry$/);
  for (const width of [1280, 393]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByTestId("oauth-callback-notice")).toHaveText(/Start a new connection/);
    await expect(page.getByTestId("calendar-google-panel")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.reload();
    await expect(page.getByTestId("oauth-callback-notice")).toBeVisible();
  }
  await assertRelease(page);
});

test("BUG-003: owner-consented Google account remains connected after responsive reloads", async ({ page }) => {
  test.skip(!expectedAccount, "No owner-authorized Google account/consent supplied; live successful OAuth is unverified.");
  await signIn(page);
  for (const width of [1280, 393]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/app/calendar");
    const response = await page.request.get(`${api}/api/calendar/connections`);
    expect(response.status()).toBe(200);
    const records = (await response.json()).connections;
    const connection = records.find((row: { provider: string; status: string; display_email: string }) =>
      row.provider === "google_calendar" && row.status === "connected" && row.display_email === expectedAccount);
    expect(connection, "The actual owner-consented Google connection must be persisted").toBeTruthy();
    expect(connection.provider_account_id).toBeTruthy();
    await expect(page.getByTestId("calendar-google-panel")).toContainText(`Connected as ${expectedAccount}`);
    await expect(page.getByTestId("calendar-google-sync-range")).toBeEnabled();
    await page.reload();
    await expect(page.getByTestId("calendar-google-panel")).toContainText(`Connected as ${expectedAccount}`);
  }
  await assertRelease(page);
});
