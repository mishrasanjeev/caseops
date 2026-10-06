import { expect, test, type Page } from "@playwright/test";

const liveTestEnabled = process.env.CASEOPS_WORKSPACE_E2E_PROD === "true";
const tenantSlug = process.env.CASEOPS_WORKSPACE_E2E_TENANT_SLUG ?? "test-legal";
const email = process.env.CASEOPS_WORKSPACE_E2E_EMAIL;
const password = process.env.CASEOPS_WORKSPACE_E2E_PASSWORD;
const expectedReleaseSha = process.env.CASEOPS_WORKSPACE_E2E_RELEASE_SHA;

test.skip(!liveTestEnabled, "Live Workspace sync runs only in the explicit production verification job.");

async function signIn(page: Page) {
  if (!email || !password || !expectedReleaseSha) {
    throw new Error("Production Workspace Playwright credentials or release identity are missing.");
  }
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(tenantSlug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:\/|$)/);
  const apiBaseUrl = process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
  const buildResponse = await page.request.get(`${apiBaseUrl}/api/build`);
  expect(buildResponse.status()).toBe(200);
  const build = await buildResponse.json();
  expect(build.release_sha).toBe(expectedReleaseSha);
}

test.describe("Google Workspace token recovery on production", () => {
  test.setTimeout(120_000);

  test("Gmail sync succeeds in the UI and persists its last-import time", async ({ page }) => {
    await signIn(page);
    await page.goto("/app/mailbox");
    const sync = page.getByRole("button", { name: "Sync Gmail" });
    await expect(sync).toBeEnabled();

    const syncResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/mailbox/gmail/import") &&
        response.request().method() === "POST",
    );
    await sync.click();
    const syncResponse = await syncResponsePromise;
    expect(syncResponse.status()).toBe(200);
    expect(syncResponse.headers()["access-control-allow-origin"]).toBe(
      new URL(process.env.PROD_BASE_URL ?? "https://caseops.ai").origin,
    );
    const importResult = await syncResponse.json();
    expect(importResult.summary.failed).toBe(0);
    await expect(page.getByText("Gmail metadata synced")).toBeVisible();

    const statusResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/mailbox/gmail/status") &&
        response.request().method() === "GET",
    );
    await page.reload();
    const statusResponse = await statusResponsePromise;
    expect(statusResponse.status()).toBe(200);
    const status = await statusResponse.json();
    expect(status.connections.some(
      (connection: { status: string; last_import_at: string | null }) =>
        connection.status === "connected" && connection.last_import_at,
    )).toBe(true);
  });

  test("Drive sync succeeds in the UI and persists its last-list time", async ({ page }) => {
    await signIn(page);
    await page.goto("/app/drive");
    const sync = page.getByRole("button", { name: "Sync Google Drive" });
    await expect(sync).toBeEnabled();

    const syncResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/drive/google/candidates/sync") &&
        response.request().method() === "POST",
    );
    await sync.click();
    const syncResponse = await syncResponsePromise;
    expect(syncResponse.status()).toBe(200);
    expect(syncResponse.headers()["access-control-allow-origin"]).toBe(
      new URL(process.env.PROD_BASE_URL ?? "https://caseops.ai").origin,
    );
    await expect(page.getByText("Drive metadata synced")).toBeVisible();

    const statusResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/drive/google/status") &&
        response.request().method() === "GET",
    );
    await page.reload();
    const statusResponse = await statusResponsePromise;
    expect(statusResponse.status()).toBe(200);
    const status = await statusResponse.json();
    expect(status.connections.some(
      (connection: { status: string; last_list_at: string | null }) =>
        connection.status === "connected" && connection.last_list_at,
    )).toBe(true);
  });
});
