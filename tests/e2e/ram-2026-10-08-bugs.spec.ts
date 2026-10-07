/**
 * BUG-003/004: real Calendar routes, durable claims, adapter token transport and
 * browser redirects, against the test-only loopback OAuth provider.
 * J08 / M08 / MOD-TS-006; FT-043, NFT-007, SEC-002.
 * This is deliberately not a production Google consent certification.
 */
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, repoRoot } from "./support/env";

const providerRoot = apiBaseUrl + "/_e2e/calendar-oauth";
const callbackPath = "/api/calendar/connections/google-calendar/callback";
const password = "CalendarBrowserRegression123!";
const email = "calendar-emulator@example.test";
const scopes = ["email", "https://www.googleapis.com/auth/calendar.events", "openid"];

function requireLoopback(value: string): void {
  const url = new URL(value);
  expect(url.protocol, "The OAuth emulator must never run against production").toBe("http:");
  expect(["localhost", "127.0.0.1", "[::1]"]).toContain(url.hostname);
}

async function signInAndConfigure(page: Page): Promise<void> {
  const slug = "calendar-oauth-" + randomUUID().slice(0, 12);
  const owner = slug + "@example.com";
  const bootstrap = await page.request.post(apiBaseUrl + "/api/bootstrap/company", {
    headers: noPaidProviderHeaders,
    data: {
      company_name: "Offline Calendar acceptance", company_slug: slug,
      company_type: "law_firm", owner_full_name: "Calendar OAuth Tester",
      owner_email: owner, owner_password: password,
    },
  });
  expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  const { access_token: token } = await bootstrap.json();
  const configured = await page.request.patch(apiBaseUrl + "/api/admin/google-workspace-configuration", {
    headers: { ...noPaidProviderHeaders, Authorization: "Bearer " + token },
    data: {
      client_id: "caseops-calendar-browser-emulator",
      client_secret: "offline-calendar-browser-fixture-secret",
      calendar_redirect_uri: apiBaseUrl + callbackPath,
      gmail_redirect_uri: apiBaseUrl + "/api/mailbox/gmail/callback",
      drive_redirect_uri: apiBaseUrl + "/api/drive/google/callback",
      calendar_enabled: true, gmail_enabled: false, drive_enabled: false, enabled: true,
    },
  });
  expect(configured.status(), await configured.text()).toBe(200);

  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(owner);
  await page.locator("#password").fill(password);
  const login = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/api/auth/login" && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(/\/app(?:[/?]|$)/);
  await page.goto("/app/calendar");
}

async function startConsent(page: Page): Promise<string> {
  const connect = page.getByTestId("calendar-google-connect");
  await expect(connect).toBeEnabled();
  await connect.click();
  await page.waitForURL(providerRoot + "/authorize?**");
  await expect(page.getByRole("heading", { name: "Offline Calendar consent" })).toBeVisible();
  const identity = await page.getByTestId("oauth-emulator-attempt").inputValue();
  expect((await evidence(page, identity)).scopes.sort()).toEqual(scopes);
  return identity;
}

async function evidence(page: Page, identity: string) {
  const result = await page.request.get(providerRoot + "/evidence/" + identity);
  expect(result.status()).toBe(200);
  return result.json() as Promise<{
    scopes: string[]; token_calls: number; userinfo_calls: number; waiting: boolean;
  }>;
}

async function consent(page: Page, button: string): Promise<string> {
  const callback = page.waitForRequest((request) => new URL(request.url()).pathname === callbackPath);
  await page.getByRole("button", { name: button, exact: true }).click();
  return (await callback).url();
}

async function connected(page: Page): Promise<string> {
  await expect(page).toHaveURL(/\/app\/calendar(?:\?|$)/);
  const panel = page.getByTestId("calendar-google-panel");
  await expect(panel).toContainText("Connected as " + email);
  const disconnect = page.getByTestId("calendar-google-revoke");
  await disconnect.scrollIntoViewIfNeeded();
  await expect(disconnect).toBeVisible();
  expect((await disconnect.boundingBox())!.width).toBeGreaterThan(40);
  const listed = await page.request.get(apiBaseUrl + "/api/calendar/connections");
  expect(listed.status()).toBe(200);
  const payload = await listed.json();
  const rows = payload.connections.filter((row: { provider: string }) => row.provider === "google_calendar");
  expect(rows).toHaveLength(1);
  expect(rows[0]).toMatchObject({ status: "connected", display_email: email });
  expect(JSON.stringify(payload)).not.toMatch(/offline-access-|offline-refresh-|encrypted_token_ref/);
  return rows[0].id as string;
}

async function assertConsumed(page: Page, callback: string): Promise<void> {
  const replay = await page.request.get(callback, { headers: { Accept: "application/json" }, maxRedirects: 0 });
  expect(replay.status(), await replay.text()).toBe(409);
  expect((await replay.json()).code).toBe("calendar_oauth_callback_consumed");
}

test("Offline OAuth harness rejects production activation and validates its provider protocol", async ({ baseURL }, testInfo) => {
  requireLoopback(apiBaseUrl);
  requireLoopback(baseURL!);
  const python = process.env.CASEOPS_E2E_PYTHON ?? path.join(
    repoRoot, "apps", "api", ".venv", process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  const result = spawnSync(python, [
    "-m", "unittest", "discover", "-s", "tests/e2e/support/oauth",
    "-p", "test_calendar_oauth_emulator.py", "-v",
  ], { cwd: repoRoot, encoding: "utf8", timeout: 30_000 });
  const output = result.stdout + result.stderr;
  await testInfo.attach("emulator-isolation-and-protocol", { body: output, contentType: "text/plain" });
  expect(result.error, output).toBeUndefined();
  expect(result.status, output).toBe(0);
  expect(output).toContain("Ran 8 tests");
});

for (const viewport of [{ width: 1280, height: 900 }, { width: 393, height: 851 }]) {
  test.describe("Ram Oct 8 Calendar OAuth at " + viewport.width + "px", () => {
    test.use({ viewport });
    test.beforeEach(async ({ page, baseURL }) => {
      requireLoopback(apiBaseUrl);
      requireLoopback(baseURL!);
      const health = await page.request.get(providerRoot + "/health");
      expect(health.status(), "Standard acceptance must load the test-only OAuth entrypoint").toBe(200);
      expect(await health.json()).toEqual({ mode: "calendar-20261008", transport: "loopback-only" });
      await signInAndConfigure(page);
    });

    test("BUG-003: consent returns to Calendar, reload persists, replay cannot degrade it", async ({ page }, testInfo) => {
      const attempt = await startConsent(page);
      const callback = await consent(page, "Allow calendar access");
      await expect(page).toHaveURL(/\/app\/calendar$/);
      const connectionId = await connected(page);
      await page.reload();
      expect(await connected(page)).toBe(connectionId);
      await assertConsumed(page, callback);
      await page.goto(callback);
      await expect(page).toHaveURL(/\/app\/calendar\?oauth_provider=google_calendar&oauth_result=consumed$/);
      await expect(page.getByTestId("oauth-callback-notice")).toContainText("Check the current connection below");
      expect(await connected(page)).toBe(connectionId);
      await page.reload();
      expect(await connected(page)).toBe(connectionId);
      expect(await evidence(page, attempt)).toMatchObject({ token_calls: 1, userinfo_calls: 1 });
      const screenshot = testInfo.outputPath("connected-after-replay.png");
      await page.screenshot({ path: screenshot, fullPage: true });
      await testInfo.attach("connected-after-replay", { path: screenshot, contentType: "image/png" });
    });

    test("BUG-003/004: identity rejection is readable and a fresh consent recovers immediately", async ({ page }, testInfo) => {
      const failedAttempt = await startConsent(page);
      const failedCallback = await consent(page, "Simulate identity rejection");
      await expect(page).toHaveURL(/\/app\/calendar\?oauth_provider=google_calendar&oauth_result=consent_required$/);
      const notice = page.getByTestId("oauth-callback-notice");
      await expect(notice).toContainText("Start a new connection");
      await expect(notice).toContainText("grant");
      await expect(page.getByTestId("calendar-google-panel")).not.toContainText("Connected as " + email);
      await expect(page.getByTestId("calendar-google-connect")).toBeEnabled();
      await assertConsumed(page, failedCallback);
      expect(await evidence(page, failedAttempt)).toMatchObject({ token_calls: 1, userinfo_calls: 1 });
      const recoveryAttempt = await startConsent(page);
      expect(recoveryAttempt).not.toBe(failedAttempt);
      await consent(page, "Allow calendar access");
      const connectionId = await connected(page);
      await page.reload();
      expect(await connected(page)).toBe(connectionId);
      expect(await evidence(page, recoveryAttempt)).toMatchObject({ token_calls: 1, userinfo_calls: 1 });
      const screenshot = testInfo.outputPath("recovered-without-waiting-for-lease.png");
      await page.screenshot({ path: screenshot, fullPage: true });
      await testInfo.attach("recovered-without-waiting-for-lease", { path: screenshot, contentType: "image/png" });
    });

    test("BUG-003/004: declined provider consent returns a readable notice and a new consent succeeds", async ({ page }, testInfo) => {
      const declinedAttempt = await startConsent(page);
      const callbackResponse = page.waitForResponse((response) => new URL(response.url()).pathname === callbackPath);
      const declinedCallback = await consent(page, "Decline consent");
      const callback = new URL(declinedCallback);
      expect(callback.searchParams.get("error")).toBe("access_denied");
      expect(callback.searchParams.has("code")).toBe(false);
      const response = await callbackResponse;
      expect(response.status()).toBe(303);
      expect(response.headers()["cache-control"]).toBe("no-store");
      expect(response.headers()["referrer-policy"]).toBe("no-referrer");
      await expect(page).toHaveURL(/\/app\/calendar\?oauth_provider=google_calendar&oauth_result=consent_required$/);
      const notice = page.getByTestId("oauth-callback-notice");
      await notice.scrollIntoViewIfNeeded();
      await expect(notice).toBeVisible();
      await expect(notice).toContainText("Start a new connection");
      await expect(notice).toContainText("grant");
      await expect(page.getByTestId("calendar-google-panel")).not.toContainText("Connected as " + email);
      await expect(page.getByTestId("calendar-google-connect")).toBeEnabled();
      const listed = await page.request.get(apiBaseUrl + "/api/calendar/connections");
      expect(listed.status()).toBe(200);
      expect((await listed.json()).connections.filter((row: { provider: string }) => row.provider === "google_calendar")).toHaveLength(0);
      expect(await evidence(page, declinedAttempt)).toMatchObject({ token_calls: 0, userinfo_calls: 0 });
      const screenshot = testInfo.outputPath("declined-consent-recovery-notice.png");
      await page.screenshot({ path: screenshot, fullPage: true });
      await testInfo.attach("declined-consent-recovery-notice", { path: screenshot, contentType: "image/png" });
      const jsonDenial = await page.request.get(declinedCallback, {
        headers: { Accept: "application/json, text/html;q=0" }, maxRedirects: 0,
      });
      expect(jsonDenial.status(), await jsonDenial.text()).toBe(422);
      const recoveryAttempt = await startConsent(page);
      expect(recoveryAttempt).not.toBe(declinedAttempt);
      await consent(page, "Allow calendar access");
      const connectionId = await connected(page);
      await page.reload();
      expect(await connected(page)).toBe(connectionId);
      expect(await evidence(page, declinedAttempt)).toMatchObject({ token_calls: 0, userinfo_calls: 0 });
      expect(await evidence(page, recoveryAttempt)).toMatchObject({ token_calls: 1, userinfo_calls: 1 });
    });

    test("BUG-004: an actual in-flight exchange rejects its duplicate without losing the first result", async ({ page, context }) => {
      const attempt = await startConsent(page);
      const callbackRequest = page.waitForRequest((request) => new URL(request.url()).pathname === callbackPath);
      const pendingConsent = page.getByRole("button", { name: "Hold token exchange", exact: true }).click();
      const callback = (await callbackRequest).url();
      const duplicate = await context.newPage();
      try {
        await expect.poll(async () => (await evidence(page, attempt)).waiting, { timeout: 5_000 }).toBe(true);
        const duplicateApi = await page.request.get(callback, { headers: { Accept: "application/json" }, maxRedirects: 0 });
        expect(duplicateApi.status(), await duplicateApi.text()).toBe(409);
        expect((await duplicateApi.json()).code).toBe("calendar_oauth_exchange_in_flight");
        // Chromium coalesces byte-identical pending navigations. Keep the same
        // state/code while giving the second browser request its own cache key;
        // the API probe immediately above already repeats the exact URL.
        await duplicate.goto(callback + "&browser_copy=1");
        await expect(duplicate).toHaveURL(/\/app\/calendar\?oauth_provider=google_calendar&oauth_result=in_flight$/);
        await expect(duplicate.getByTestId("oauth-callback-notice")).toContainText("A connection attempt is still running");
        expect((await evidence(page, attempt)).token_calls).toBe(1);
      } finally {
        const csrf = (await context.cookies(apiBaseUrl)).find((cookie) => cookie.name === "caseops_csrf");
        expect(csrf, "The emulator control must respect the real CSRF boundary").toBeDefined();
        const released = await page.request.post(providerRoot + "/release/" + attempt, {
          headers: { "X-CSRF-Token": csrf!.value },
        });
        expect.soft(released.status(), await released.text()).toBe(200);
        await pendingConsent;
        await duplicate.close();
      }
      const connectionId = await connected(page);
      await page.reload();
      expect(await connected(page)).toBe(connectionId);
      expect(await evidence(page, attempt)).toMatchObject({ token_calls: 1, userinfo_calls: 1 });
    });
  });
}
